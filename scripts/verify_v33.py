"""Verify actual live/restarted reports against the full deterministic journal replay."""
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from daiinas.continuous_ops import backup_pair


def verify(root=Path('.')):
    read=lambda n:json.loads((root/'reports'/f'v33-{n}.json').read_text())
    first,second,replica,tests=(read(n) for n in ('first','restart','replay','tests'))
    if not tests['successful'] or tests['tests_run']<148:raise AssertionError('Existing regression baseline not verified')
    if first.get('smoke_status')!='passed' or second.get('smoke_status')!='passed':
        raise AssertionError('Both real-data processes must pass integrity, not trade-count goals')
    if first['boot_id']==second['boot_id'] or second['source_cursor']<=first['source_cursor']:
        raise AssertionError('No distinct process restart and subsequent source advancement')
    for k,v in replica.items():
        if second[k]!=v:raise AssertionError(f'Online/restarted vs replay mismatch: {k}')
    if second['live_orders_enabled'] is not False or second['initial_capital']!=8:
        raise AssertionError('Paper-only shared capital boundary violated')
    paper=sqlite3.connect(root/'state/v33-paper.sqlite3')
    source=sqlite3.connect(root/'state/v33-source.sqlite3')
    try:
        trades=[json.loads(r[0]) for r in paper.execute('SELECT payload FROM closed_positions')]
        positions=trades+([second['open_position']] if second['open_position'] else [])
        for pos in positions:
            row=source.execute('SELECT available_ms,payload FROM journal WHERE seq=?',(pos['entry_source_seq'],)).fetchone()
            entry_payload=json.loads(row[1])
            if (row[0]!=pos['entry_received_ms'] or pos['entry_received_ms']-pos['signal_received_ms']<100
                or entry_payload.get('wire_received_ms',entry_payload['received_ms'])<pos['signal_received_ms']+100):
                raise AssertionError('Entry did not use a genuinely later observed quote')
            if pos in trades:
                row=source.execute('SELECT available_ms,payload FROM journal WHERE seq=?',(pos['exit_source_seq'],)).fetchone()
                if row[0]!=pos['exit_received_ms'] or pos['exit_provider_ms']<=pos['entry_provider_ms']:
                    raise AssertionError('Invented or non-later exit')
                calculated=pos['gross_pnl_usdt']-pos['entry_fee_usdt']-pos['exit_fee_usdt']-pos['modeled_carry_usdt']
                if abs(calculated-pos['net_pnl_usdt'])>1e-8:raise AssertionError('Cost reconciliation failed')
        closed=sum(p['net_pnl_usdt'] for p in trades)
        open_fee=second['open_position']['entry_fee_usdt'] if second['open_position'] else 0
        if abs(second['cash']-(8+second['external_simulated_flows']+closed-open_fee))>1e-7:
            raise AssertionError('Shared cash does not reconcile')
        scans=source.execute("SELECT count(*) FROM journal WHERE kind='SCAN'").fetchone()[0]
        if scans<2:raise AssertionError('No multi-scan evidence')
        event_counts=dict(source.execute('SELECT channel,count(*) FROM raw_events GROUP BY channel'))
    finally:paper.close();source.close()
    backup=backup_pair(root/'state/v33-source.sqlite3',root/'state/v33-paper.sqlite3',root/'state/v33-backup')
    return {'status':'passed','live_orders_enabled':False,'tests':tests,'market_scans':scans,
            'observed_contracts':second['observed_contracts'],'public_event_counts':event_counts,
            'process_boots':[first['boot_id'],second['boot_id']],
            'source_cursor':second['source_cursor'],'input_digest':second['input_digest'],
            'cash':second['cash'],'equity_last_mark':second['equity_last_mark'],
            'fees':second['fees'],'modeled_carry':second['modeled_carry'],
            'closed_summary':second['closed_summary'],'open_position':second['open_position'],
            'pending_entry':second['pending_entry'],'pending_exit':second['pending_exit'],
            'decision_counts':second['counts'],'rejected_and_unresolved_reasons':second.get('reason_counts',{}),'replay_identical':True,'backup':backup,
            '24h_host_gate':'BLOCKED — HOST NOT PROVISIONED',
            'performance_gate':'Not established by bounded infrastructure smoke'}


if __name__=='__main__':
    try:result=verify()
    except Exception as exc:result={'status':'not_verified','error':f'{type(exc).__name__}: {exc}',
                                  'live_orders_enabled':False,'24h_host_gate':'BLOCKED — HOST NOT PROVISIONED'}
    Path('reports').mkdir(exist_ok=True)
    Path('reports/v33-acceptance.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result['status']=='passed' else 1)
