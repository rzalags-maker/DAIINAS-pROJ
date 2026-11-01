"""Deterministic public-source M0–M3 comparison; illustrative hedge negatives.

No private requests. A short sample cannot establish a held-out trading edge.
"""
import argparse
from dataclasses import replace
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import statistics

from .continuous import replay,source_rows
from .paper_micro import PaperPolicy
from .portfolio_paper import PortfolioLedger,PortfolioPolicy
from .funding import paper_funding

D=lambda x:Decimal(str(x))


def illustrative_path(mids,*,capital='50',fee='.0006',spread_bps='2',slippage_bps='2'):
    """Synthetic source example only, NOT risk-approved engine orders.

    25 notional per side, not a 25-USDT permitted loss. Models mark/fees and
    later winner exits to expose residual losses; ordinary engine stops may
    close earlier. Not a trading recommendation or backtest.
    """
    if len(mids)<2:raise ValueError('Need a chronological path')
    initial=D(mids[0]);units=D(capital)/2/initial;half=D(spread_bps)/20000;slip=D(slippage_bps)/10000;f=D(fee)
    entry={'LONG':initial*(1+half)*(1+slip),'SHORT':initial*(1-half)*(1-slip)}
    entryfees={k:p*units*f for k,p in entry.items()};realized=D(0);closed=set();rows=[]
    previous=None;requests={}
    for i,value in enumerate(mids):
        mid=D(value);quotes={'LONG':mid*(1-half)*(1-slip),'SHORT':mid*(1+half)*(1+slip)}
        # Request only after observing a path; fill on a strictly LATER sample.
        for side in ['LONG','SHORT']:
            if side in closed:continue
            sign=1 if side=='LONG' else -1
            if side in requests and i>requests[side]:
                realized+=sign*(quotes[side]-entry[side])*units-entryfees[side]-quotes[side]*units*f
                closed.add(side)
            elif (mid-initial)*sign>=initial*D('.02'):requests[side]=i
        open_net=sum(((1 if side=='LONG' else -1)*(quotes[side]-entry[side])*units-entryfees[side]-quotes[side]*units*f
                      for side in entry if side not in closed),D(0))
        gross_mark=(mid-initial)*units+(initial-mid)*units
        rows.append({'index':i,'mid':str(mid),'equal_pair_gross_at_single_mark':str(gross_mark),
                     'realized_net':str(realized),'remaining_net_after_exit_costs':str(open_net),
                     'campaign_net_mark':str(realized+open_net),'open_sides':sorted(set(entry)-closed)})
        previous=mid
    net=realized+open_net
    return {'sample_kind':'SYNTHETIC_ILLUSTRATION_NOT_ENGINE_APPROVED','allocated_capital':capital,
            'net_campaign_mark':str(net),'return_on_campaign_allocation':str(net/D(capital)),
            'price_move_fraction':str((D(mids[-1])-initial)/initial),'rows':rows,
            'risk_note':'Illustrates hidden residual loss; real engine stops/risk limits remain enforced.'}


def compare(sources,output_dir,capitals=('8','60','100')):
    root=Path(output_dir);root.mkdir(parents=True,exist_ok=True)
    first,last=None,None
    for path in sources:
        for row in source_rows(path):
            first=row[1] if first is None else min(first,row[1]);last=row[1] if last is None else max(last,row[1])
    if first is None:raise ValueError('No real source records')
    split=first+(last-first)//2;results={}
    for capital in capitals:
        results[capital]={}
        for mode in ('M0','M1','M2','M3'):
            pp=PortfolioPolicy(initial_capital=capital,mode=mode,funding=paper_funding(capital,account_id='comparison-'+capital+'-'+mode,
                source_reference='Explicit recorded-public-data counterfactual comparison',timestamp_ms=first-1))
            report=replay(sources,root/f'{capital}-{mode}.sqlite3',PaperPolicy(initial_capital_usdt=float(capital)),
                ledger_factory=PortfolioLedger,ledger_options={'portfolio':pp})
            closed=report['recent_closed_positions']
            # Full SQL closed records, rather than the bounded report's recent window.
            import sqlite3
            con=sqlite3.connect(root/f'{capital}-{mode}.sqlite3')
            try:closed=[json.loads(r[0]) for r in con.execute('SELECT payload FROM closed_positions')]
            finally:con.close()
            held=[float(p['net_pnl_usdt']) for p in closed if p['entry_received_ms']>=split]
            results[capital][mode]={k:report[k] for k in ('initial_funding','actual_exchange_balance_status','cash','equity_last_mark','executable_equity','mark_status','ladder',
                'realized_net_pnl','fees','modeled_carry','maximum_drawdown','account_maximum_drawdown','positions','campaigns','closed_summary','reason_counts','counts')}
            results[capital][mode].update(held_out_closed_legs=len(held),held_out_mean_net=statistics.mean(held) if held else None,
                confidence_interval=None,expected_net_advantage='UNSUPPORTED',abstention_count=report['counts'].get('DECISION',0)-report['counts'].get('SIGNAL',0),
                source_cursor=report['source_cursor'],input_digest=report['input_digest'],
                comparison_policy='Same as-of observations, same initial capital and risk model; M2 is a negative control')
            if mode=='M0' and (D(report['cash'])!=D(capital)+D(report['external_simulated_flows']) or report['positions']):raise AssertionError('Flat control altered trading capital')
    return {'funding_mode':'EXPLICIT_HYPOTHETICAL_PAPER','actual_exchange_balance_status':'NOT_CONNECTED',
        'live_orders_enabled':False,'sample_kind':'RECORDED_PUBLIC_MARKET_DATA','strategy_validated':False,'production_ready':False,
        'source_sha256':{str(p):hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in sources},
        'first_available_ms':first,'last_available_ms':last,'duration_seconds':(last-first)/1000,
        'walk_forward':{'training_end_ms':split-1,'held_out_start_ms':split,
            'thresholds':'Online per-symbol cost/volatility/structure estimates; no fitted return probabilities',
            'status':'INSUFFICIENT_MULTIDAY_OUT_OF_SAMPLE_EVIDENCE','confidence_intervals':'Not estimated from sparse dependent legs'},
        'scenarios':results,'hedge_authorization':'No supported held-out advantage installed; adaptive hedge abstains',
        '24h_host_gate':'BLOCKED — HOST NOT PROVISIONED','uk_product_gate':'OPEN_NOT_VERIFIED'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,action='append',required=True)
    p.add_argument('--output-dir',type=Path,default=Path('state/v41-comparison'))
    p.add_argument('--report',type=Path,default=Path('reports/V41_HEDGE_COMPARISON.json'));a=p.parse_args()
    result=compare(a.source,a.output_dir);a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'report':str(a.report),'strategy_validated':False}))

if __name__=='__main__':main()
