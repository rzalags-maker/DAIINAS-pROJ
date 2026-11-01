"""Validate real public-data capture; capital/orders remain explicitly modeled."""
from decimal import Decimal,ROUND_FLOOR,ROUND_CEILING
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from daiinas.continuous_ops import backup_pair

D=Decimal
Q=D('1e-18')


def verify(root):
    root=Path(root)
    first,second,replica=[json.loads((root/(name+'.json')).read_text()) for name in ('first','restart','replay')]
    assert first['smoke_status']==second['smoke_status']=='passed'
    assert first['boot_id']!=second['boot_id'] and second['source_cursor']>first['source_cursor']
    for key,value in replica.items():assert second[key]==value,('replay mismatch',key)
    assert replica['strategy_version']=='v47' and replica['actual_exchange_balance_status']=='NOT_CONNECTED'
    assert not replica['live_orders_enabled'] and not replica['strategy_validated']
    assert replica['whole_market_pulse']['catalog_count']==second['observed_contracts']>0
    with sqlite3.connect(root/'paper.sqlite3') as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute('SELECT count(*) FROM initial_funding').fetchone()[0]==1
        state=json.loads(db.execute('SELECT payload FROM checkpoint WHERE id=1').fetchone()[0])
        closed=[json.loads(row[0]) for row in db.execute('SELECT payload FROM closed_positions')]
    gross=fees=carry=net=D(0)
    for row in closed:
        units=D(row['quantity_contracts'])*D(row['contract_multiplier'])
        sign=1 if row['direction']=='LONG' else -1
        g=(sign*(D(row['exit_price'])-D(row['entry_price']))*units).quantize(Q,rounding=ROUND_FLOOR)
        assert g==D(row['gross_pnl_usdt'])
        f=D(row['entry_fee_usdt'])+D(row['exit_fee_usdt']);c=D(row['modeled_carry_usdt'])
        assert g-f-c==D(row['net_pnl_usdt'])
        assert row['exit_received_ms']>row['entry_received_ms'] and row['exit_source_seq']>row['entry_source_seq']
        gross+=g;fees+=f;carry+=c;net+=g-f-c
    open_fees=sum((D(p['entry_fee_usdt']) for p in replica['positions']),D(0))
    assert D(replica['cash'])==D(replica['initial_capital'])+net-open_fees
    assert D(replica['fees'])==fees+open_fees and D(replica['realized_net_pnl'])==net
    assert D(replica['modeled_carry'])==carry
    account=state['account_capital'];queued=sum((D(e['net']) for e in state.get('paper_settlements',[])),D(0))
    assert D(account['cash'])==D(replica['cash'])+D(account['unallocated'])-queued
    assert len(replica['positions'])+len(replica['pending_entries'])<=10
    for p in replica['positions']:
        assert 1<=p['leverage']<=5
        assert D(p['planned_loss_usdt'])<=D(p['allocation_budget_usdt'])*D('.005')
        assert D(p['margin_reserved_usdt'])==D(p['entry_notional_usdt'])/p['leverage']
    with sqlite3.connect(root/'source.sqlite3') as db:
        counts=dict(db.execute('SELECT channel,count(*) FROM raw_events GROUP BY channel'))
        low,high=db.execute('SELECT min(available_ms),max(available_ms) FROM journal').fetchone()
    assert counts.get('level2',0)>0 and counts.get('tickerV2',0)>0
    backup=backup_pair(root/'source.sqlite3',root/'paper.sqlite3',root/'backup')
    return {'status':'PASS','evidence_kind':'REAL_PUBLIC_KUCOIN_MARKET_WITH_EXPLICIT_MOCK_PAPER_ACCOUNT',
        'tested_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'actual_account':'NOT_CONNECTED','live_orders_enabled':False,'strategy_validated':False,'production_ready':False,
        'public_event_counts':counts,'duration_seconds':(high-low)/1000,'observed_contracts':second['observed_contracts'],
        'source_cursor':replica['source_cursor'],'input_digest':replica['input_digest'],
        'initial_funding':replica['initial_funding'],'cash':replica['cash'],'realized_net_pnl':str(net),
        'fees':replica['fees'],'modeled_carry':replica['modeled_carry'],'maximum_drawdown':replica['maximum_drawdown'],
        'closed_summary':replica['closed_summary'],'open_positions':replica['positions'],
        'pending_entries':replica['pending_entries'],'exit_requests':replica['exit_requests'],
        'selected_leverages':sorted({p['leverage'] for p in [*closed,*replica['positions']]}),
        'decision_counts':replica['counts'],'reason_counts':replica['reason_counts'],'account_status':replica['account_status'],
        'conveyor':replica['conveyor'],'errors':first.get('errors',[])+second.get('errors',[]),
        'replay_identical':True,'cash_independently_reconciled':True,'backup':backup,
        'out_of_sample_status':'SHORT_INFRASTRUCTURE_SMOKE_NOT_ECONOMIC_VALIDATION',
        '24h_host_gate':'NOT_RUN_HOST_NOT_PROVISIONED',
        'report_sha256':{str(root/(name+'.json')):hashlib.sha256((root/(name+'.json')).read_bytes()).hexdigest() for name in ('first','restart','replay')}}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',required=True,type=Path);args=p.parse_args()
    result=verify(args.root);(args.root/'validation.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('status','evidence_kind','public_event_counts','cash','realized_net_pnl','closed_summary','replay_identical')}))
