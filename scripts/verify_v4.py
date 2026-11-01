"""Verify genuine public first/restart/replay and independent Decimal cash."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from decimal import Decimal,ROUND_FLOOR
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from daiinas.continuous_ops import backup_pair
D=lambda x:Decimal(str(x))

def verify():
    read=lambda n:json.loads(Path('reports/'+n+'.json').read_text())
    first,second,replica=(read('v4-'+x) for x in ('first','restart','replay'))
    assert first['smoke_status']==second['smoke_status']=='passed'
    assert first['boot_id']!=second['boot_id'] and second['source_cursor']>first['source_cursor']
    for k,v in replica.items():assert second[k]==v,('replay mismatch',k)
    assert second['live_orders_enabled'] is False and second['production_ready'] is False
    assert second['initial_capital']=='100'
    with sqlite3.connect('state/v4-paper.sqlite3') as c:
        assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert c.execute("SELECT count(*) FROM initial_funding").fetchone()[0]==1
        assert c.execute("SELECT count(*) FROM audit WHERE action='INITIAL_FUNDING'").fetchone()[0]==1
        trades=[json.loads(r[0]) for r in c.execute('SELECT payload FROM closed_positions')]
        checkpoint=json.loads(c.execute('SELECT payload FROM checkpoint WHERE id=1').fetchone()[0])
    gross=fees=carry=net=D(0)
    for p in trades:
        units=D(p['quantity_contracts'])*D(p['contract_multiplier'])
        g=((1 if p['direction']=='LONG' else -1)*(D(p['exit_price'])-D(p['entry_price']))*units).quantize(D('0.000000000000000001'),rounding=ROUND_FLOOR)
        assert g==D(p['gross_pnl_usdt'])
        n=g-D(p['entry_fee_usdt'])-D(p['exit_fee_usdt'])-D(p['modeled_carry_usdt'])
        assert n==D(p['net_pnl_usdt'])
        gross+=g;net+=n;fees+=D(p['entry_fee_usdt'])+D(p['exit_fee_usdt']);carry+=D(p['modeled_carry_usdt'])
    openfees=sum((D(p['entry_fee_usdt']) for p in second['positions']),D(0))
    assert D(second['cash'])==D(100)+net+D(second['external_simulated_flows'])-openfees
    assert D(second['fees'])==fees+openfees and D(second['modeled_carry'])==carry
    l=second['ladder']
    allocation=D(l['reserve'])+D(l['active'])+D(l['pending'])-D(l['deficit'])
    assert allocation==D(l['starting_total'])+D(l['realized_net'])
    assert D(second['cash'])==allocation+D(second['external_simulated_flows'])+D(second['unsettled_campaign_pnl'])-openfees
    backup=backup_pair('state/v4-source.sqlite3','state/v4-paper.sqlite3','state/v4-backup')
    with sqlite3.connect('state/v4-source.sqlite3') as c:
        counts=dict(c.execute('SELECT channel,count(*) FROM raw_events GROUP BY channel'))
        rows=c.execute('SELECT count(*),min(available_ms),max(available_ms) FROM journal').fetchone()
    return {'status':'passed','initial_capital':'100','live_orders_enabled':False,'strategy_validated':False,'production_ready':False,
        'initial_funding':second['initial_funding'],'actual_exchange_balance_status':second['actual_exchange_balance_status'],
        'actual_public_events':counts,'journal_records':rows[0],'duration_seconds':(rows[2]-rows[1])/1000,
        'replay_identical':True,'money_reconciled_independently':True,'cash':second['cash'],
        'executable_equity':second['executable_equity'],'equity_last_mark':second['equity_last_mark'],
        'net_realized_pnl':str(net),'fees':second['fees'],'carry':second['modeled_carry'],'ladder':l,
        'active_risk_drawdown':second['maximum_drawdown'],'account_drawdown':second['account_maximum_drawdown'],'positions':second['positions'],'campaigns':second['campaigns'],
        'counts':second['counts'],'reason_counts':second['reason_counts'],'input_digest':second['input_digest'],
        'backup':backup,'24h_host_gate':'BLOCKED — HOST NOT PROVISIONED'}

if __name__=='__main__':
    try:r=verify()
    except Exception as e:r={'status':'not_verified','error':type(e).__name__+': '+str(e),'live_orders_enabled':False}
    Path('reports/v4-validation.json').write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(r,indent=2));raise SystemExit(0 if r['status']=='passed' else 1)
