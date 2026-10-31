"""Independent Decimal financial audit. Reads public evidence; never sends orders.

Does not call size_for_quote/finish_position for its reconciliation arithmetic.
"""
import argparse
from collections import defaultdict
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3

D=lambda x:Decimal(str(x))
TOL=D('0.00000001')


def equal(a,b,label):
    if abs(D(a)-D(b))>TOL:raise AssertionError(label+': financial mismatch')


def position_costs(p,entry_quote=None,exit_quote=None,carry_rate=.0001):
    units=D(p['quantity_contracts'])*D(p['contract_multiplier'])
    sign=D(1 if p['direction']=='LONG' else -1)
    entry,exit=D(p['entry_price']),D(p['exit_price'])
    gross=sign*(exit-entry)*units
    # Entry/exit rates can differ after an as-of fee refresh.
    fees=D(p['entry_fee_usdt'])+D(p['exit_fee_usdt'])
    carry=D(p['entry_notional_usdt'])*D(carry_rate)*D(p['holding_ms'])/D(28800000)
    equal(gross,p['gross_pnl_usdt'],'gross')
    equal(carry,p['modeled_carry_usdt'],'default modeled carry')
    net=gross-fees-carry;equal(net,p['net_pnl_usdt'],'net')
    result={'id':p['id'],'symbol':p['symbol'],'direction':p['direction'],
        'exit_reason':p['exit_reason'],'exit_class':'INFRASTRUCTURE' if p['exit_reason']=='DATA_HEALTH' else 'STRATEGY_OR_RISK',
        'gross_pnl':float(gross),'fees':float(fees),'modeled_carry':float(carry),'net_pnl':float(net),
        'planned_loss':p['planned_loss_usdt'],'realized_loss':float(max(D(0),-net)),
        'planned_risk_budget':p['risk_budget_usdt'],
        'planned_risk_utilization':float(D(p['planned_loss_usdt'])/D(p['risk_budget_usdt'])),
        'loss_over_planned':float(max(D(0),-net-D(p['planned_loss_usdt']))),
        'realized_risk_budget_utilization':float(max(D(0),-net)/D(p['risk_budget_usdt'])),
        'stop_gap_price':float(max(D(0),-sign*(exit-D(p['planned_stop_mid'])))) if p['exit_reason']=='STOP' else None,
        'fee_and_carry_pct_abs_gross':float((fees+carry)/abs(gross)*100) if gross else None,
        'spread_slippage_status':'BLOCKED_RAW_QUOTES_REQUIRED'}
    if entry_quote is None and 'entry_observed_bid' in p:
        entry_quote={'bid':p['entry_observed_bid'],'ask':p['entry_observed_ask']}
    if exit_quote is None and 'exit_observed_bid' in p:
        exit_quote={'bid':p['exit_observed_bid'],'ask':p['exit_observed_ask']}
    if entry_quote and exit_quote:
        eb,ea,xb,xa=(D(q[k]) for q,k in [(entry_quote,'bid'),(entry_quote,'ask'),(exit_quote,'bid'),(exit_quote,'ask')])
        if not 0<eb<ea or not 0<xb<xa:raise AssertionError('Invalid independent BBO')
        em,xm=(eb+ea)/2,(xb+xa)/2
        eq,xq=(ea,xb) if sign==1 else (eb,xa)
        mid_gross=sign*(xm-em)*units
        spread=((ea-eb)+(xa-xb))/2*units
        slip=(sign*(entry-eq)+sign*(xq-exit))*units
        if slip<0:raise AssertionError('Adverse model improved observed fill')
        cost=spread+slip+fees+carry
        equal(mid_gross-cost,net,'mid-price cost decomposition without double spread')
        result.update(spread_slippage_status='VERIFIED_OBSERVED_BBO_WITH_MODELED_FILLS',
            mid_price_gross_pnl=float(mid_gross),spread_cost=float(spread),
            slippage_and_tick_cost=float(slip),round_trip_cost_usdt=float(cost),
            round_trip_cost_bps=float(cost/(em*units)*10000),
            modeled_break_even_mid_price_move=float(cost/units),
            modeled_break_even_move_bps=float(cost/(em*units)*10000))
    return result


def audit_reports(first,final,replayed,source=None,paper=None):
    """Existing three-position study, or another default-policy paper capture."""
    if final.get('external_simulated_flows',0) or final.get('open_position'):
        raise ValueError('This historical audit requires a final flat, zero-external-flow capture')
    positions=sorted(final['recent_closed_positions'],key=lambda p:p['entry_source_seq'])
    if len(positions)!=final['closed_summary']['count']:
        raise AssertionError('Truncated report: full closed position ledger required')
    for key in ('cash','fees','modeled_carry','realized_net_pnl','maximum_drawdown','input_digest','source_cursor'):
        if final[key]!=replayed[key]:raise AssertionError('Restart/replay differs: '+key)
    quotes={};fill_context={};source_status='BLOCKED_RAW_JOURNAL_NOT_AVAILABLE';storage=None;requests={}
    if source:
        con=sqlite3.connect(f'file:{Path(source).resolve()}?mode=ro',uri=True)
        try:
            if con.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise AssertionError('Source corrupt')
            prev=0;prev_ms=-1;h='';events=defaultdict(int);scan=None;books={};session=None;connected=False
            for seq,t,kind,key,body,sha in con.execute('SELECT seq,available_ms,kind,event_key,payload,sha256 FROM journal ORDER BY seq'):
                payload=json.loads(body)
                raw=json.dumps({'kind':kind,'key':key,'available_ms':t,'payload':payload},sort_keys=True,separators=(',',':'),allow_nan=False)
                if seq!=prev+1 or t<prev_ms or hashlib.sha256(raw.encode()).hexdigest()!=sha:raise AssertionError('Source provenance/sequence')
                h=hashlib.sha256(json.dumps([h,sha],separators=(',',':')).encode()).hexdigest()
                prev,prev_ms=seq,t;events[kind]+=1
                if kind=='SCAN':scan=(t,payload['report']['paper_contract_specs'])
                elif kind=='SNAPSHOT':books.pop(payload['symbol'],None)
                elif kind=='HEALTH':
                    if payload['state']=='CONNECTED':session=payload.get('session_id');connected=True
                    elif payload['state'] in ('DISCONNECTED','CONNECTION_LOSS','STORAGE_CAPACITY_HALT'):connected=False
                    if payload.get('symbol'):books.pop(payload['symbol'],None)
                    else:books.clear()
                elif kind=='MARKET' and payload['channel']=='level2':books[payload['symbol']]=(t,payload)
                if kind=='MARKET' and payload['channel']=='tickerV2':
                    if any(seq in (p['entry_source_seq'],p['exit_source_seq']) for p in positions):
                        quotes[seq]=(t,payload)
                        fill_context[seq]=(scan,books.get(payload['symbol']),session,connected)
            if h!=final['input_digest'] or prev!=final['source_cursor']:raise AssertionError('Full source binding')
            span=con.execute('SELECT max(available_ms)-min(available_ms) FROM journal').fetchone()[0]/1000
            size=Path(source).stat().st_size
            daily=size/max(span,1)*86400
            storage={'measured_source_bytes':size,'measured_seconds':span,'events':dict(events),
                     'estimated_source_bytes_24h_same_rate':daily,
                     'planning_envelope_5x_source_bytes_24h':daily*5,
                     'estimate_not_24h_measurement':True}
            source_status='VERIFIED_FULL_HASH_CHAIN'
        finally:con.close()
    if paper:
        c=sqlite3.connect(f'file:{Path(paper).resolve()}?mode=ro',uri=True)
        try:
            if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise AssertionError('Paper corrupt')
            closed=[json.loads(r[0]) for r in c.execute('SELECT payload FROM closed_positions')]
            if {p['id'] for p in positions}!={p['id'] for p in closed}:raise AssertionError('Position identities')
            for seq,action,body in c.execute("SELECT seq,action,payload FROM audit WHERE action='EXIT_REQUEST' ORDER BY seq,idx"):
                a=json.loads(body);requests[a['position_id']]=a
            cp=json.loads(c.execute('SELECT payload FROM checkpoint WHERE id=1').fetchone()[0])
            equal(cp['cash'],final['cash'],'committed checkpoint cash')
            if cp['input_digest']!=final['input_digest']:raise AssertionError('Checkpoint source binding')
        finally:c.close()
    costs=[];timeline=[];cash=D(8);realized=D(0);fee_total=D(0);carry_total=D(0);reserved=D(0)
    for p in positions:
        e=x=None
        if source:
            for label,seq in [('entry',p['entry_source_seq']),('exit',p['exit_source_seq'])]:
                t,q=quotes[seq]
                if t!=p[label+'_received_ms'] or q['symbol']!=p['symbol']:raise AssertionError('Fill source provenance')
                wire=q.get('wire_received_ms',q['received_ms'])
                if label=='exit' and p['id'] not in requests:raise AssertionError('Exit request audit required')
                threshold=p['signal_received_ms'] if label=='entry' else requests[p['id']]['time_ms']
                if wire<threshold+100 or t<threshold+100:raise AssertionError('No later received fill')
                scan,book,session,connected=fill_context[seq]
                if not scan or not book or not connected or session!=q.get('session_id'):raise AssertionError('Unprotected fill context')
                spec=scan[1][p['symbol']];rule=spec['rules'];btime,b=book;normalized=q['normalized']
                if t-scan[0]>600000 or t-spec['captured_ms']>600000:raise AssertionError('Stale fill rules')
                if t-btime>2000 or not b['normalized'].get('verified'):raise AssertionError('Stale/unverified fill book')
                if t-int(normalized['timestamp'])>2000 or int(normalized['timestamp'])>t:raise AssertionError('Quote age')
                units=D(p['quantity_contracts'])*D(p['contract_multiplier'])
                if D(rule['contract_size'])!=D(p['contract_multiplier']):raise AssertionError('Multiplier')
                qty=D(p['quantity_contracts'])
                if qty%D(rule['step_size']) or not D(rule['min_qty'])<=qty<=D(rule['max_qty']):raise AssertionError('Lot filter')
                if D(p[label+'_price'])%D(rule['tick_size']):raise AssertionError('Tick filter')
                for side in ('bid','ask'):
                    if D(normalized[side])!=D(b['normalized']['best_'+side]):raise AssertionError('Book/BBO drift at fill')
                side=('ask' if p['direction']=='LONG' else 'bid') if label=='entry' else ('bid' if p['direction']=='LONG' else 'ask')
                if min(D(normalized[side+'_base_size']),D(b['normalized'][side+'_base_size']))<units:raise AssertionError('Insufficient fill depth')
                equal(D(p[label+'_price'])*units*max(D(spec['taker_fee_rate']),D('.0006')),p[label+'_fee_usdt'],'source fee')
                if label=='entry':e=q['normalized']
                else:x=q['normalized']
        costs.append(position_costs(p,e,x))
    # Reconstruct every money-changing entry/exit without using ledger fill math.
    points=sorted([(p['entry_source_seq'],'ENTRY',p) for p in positions]+
                  [(p['exit_source_seq'],'EXIT',p) for p in positions])
    for seq,kind,p in points:
        if kind=='ENTRY':cash-=D(p['entry_fee_usdt']);fee_total+=D(p['entry_fee_usdt']);reserved+=D(p['margin_reserved_usdt'])
        else:
            cash+=D(p['gross_pnl_usdt'])-D(p['exit_fee_usdt'])-D(p['modeled_carry_usdt'])
            fee_total+=D(p['exit_fee_usdt']);carry_total+=D(p['modeled_carry_usdt'])
            realized+=D(p['net_pnl_usdt']);reserved-=D(p['margin_reserved_usdt'])
        timeline.append({'source_seq':seq,'event':kind,'position_id':p['id'],'cash':float(cash),
                         'reserved_margin':float(reserved),'free_cash_after_margin':float(cash-reserved),
                         'realized_net':float(realized),'fees':float(fee_total),'carry':float(carry_total)})
    equal(cash,final['cash'],'final cash');equal(realized,final['realized_net_pnl'],'realized')
    equal(fee_total,final['fees'],'fees');equal(carry_total,final['modeled_carry'],'carry')
    # First-process checkpoint may include an OPEN position: entry fee is already debited.
    first_closed=[p for p in positions if p['exit_source_seq']<=first['source_cursor']]
    first_open=first['open_position']
    expected=D(8)+sum((D(p['net_pnl_usdt']) for p in first_closed),D(0))-(D(first_open['entry_fee_usdt']) if first_open else D(0))
    equal(expected,first['cash'],'first checkpoint including open entry fee')
    groups={}
    for field in ('symbol','direction'):
        grouped=defaultdict(lambda:defaultdict(float))
        for p in costs:
            g=grouped[p[field]];g['trades']+=1
            for k in ('gross_pnl','fees','modeled_carry','net_pnl','mid_price_gross_pnl','spread_cost','slippage_and_tick_cost'):
                if k in p:g[k]+=p[k]
        groups[field]=dict(grouped)
    posgross=sum(max(0,p['gross_pnl']) for p in costs);neggross=sum(min(0,p['gross_pnl']) for p in costs)
    return {'status':'VERIFIED_COMMITTED_REPORT_ARITHMETIC','source_status':source_status,
        'live_orders_enabled':False,'strategy_validated':False,'production_ready':False,
        'external_flows_in_this_capture':0,'positions':costs,'money_event_reconciliation':timeline,
        'by_market':groups['symbol'],'by_direction':groups['direction'],
        'gross_positive_movements':posgross,'gross_negative_movements':neggross,
        'fee_carry_pct_positive_gross':float((fee_total+carry_total)/D(posgross)*100) if posgross else None,
        'fee_carry_pct_abs_negative_gross':float((fee_total+carry_total)/D(abs(neggross))*100) if neggross else None,
        'final_cash':float(cash),'net_pnl':float(realized),'first_cash_including_open_fee':float(expected),
        'maximum_drawdown_reported':final['maximum_drawdown'],'counts':final['counts'],
        'reason_counts':final.get('reason_counts',{}),'storage':storage,
        '24h_host_gate':'BLOCKED — HOST NOT PROVISIONED',
        'unverified':['24h persistent host','economic edge / out-of-sample','actual funding','private account access']}


def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('--reports',type=Path,default=Path('reports/v33-runs/41251111492'))
    a.add_argument('--source',type=Path);a.add_argument('--paper',type=Path)
    a.add_argument('--output',type=Path,default=Path('reports/v33-risk-audit.json'))
    v=a.parse_args();read=lambda n:json.loads((v.reports/(n+'.json')).read_text())
    result=audit_reports(read('first'),read('restart'),read('replay'),v.source,v.paper)
    result['evidence_run']='https://github.com/rzalags-maker/DAIINAS-pROJ/actions/runs/41251111492'
    v.output.parent.mkdir(parents=True,exist_ok=True);v.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'status':result['status'],'source_status':result['source_status'],'final_cash':result['final_cash']}))

if __name__=='__main__':main()
