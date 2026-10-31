"""DAIINAS v3.2 — deterministic, separate-account micro PAPER replay.

This executable study reads recorded, public KuCoin observation events. It never
connects to an exchange, submits orders, or writes to the existing v1 account.
All entries use a LATER observed quote. Signals are unvalidated hypotheses.
"""
import argparse
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import hashlib
import json
import math
from pathlib import Path
import sqlite3

from .risk import ContractRules
from .shadow_flow import ShadowPolicy, observe


def canonical(obj):
    return json.dumps(obj, separators=(',', ':'), sort_keys=True, allow_nan=False)


@dataclass(frozen=True)
class PaperPolicy:
    initial_capital_usdt: float = 8.0
    leverage: float = 3.0
    margin_fraction: float = 0.80
    minimum_taker_fee_rate: float = .0006
    adverse_slippage_bps: float = 2.0
    stop_bps: float = 35.0
    target_bps: float = 70.0
    entry_ttl_ms: int = 5_000
    minimum_entry_latency_ms: int = 100
    maximum_entry_drift_bps: float = 12.0
    maximum_holding_ms: int = 90_000
    # Research-only carry estimate, NOT verified exchange funding debits.
    modeled_carry_8h_rate: float = .0001
    minimum_net_target_usdt: float = .001
    max_quote_age_ms: int = 2_000

    def __post_init__(self):
        positives=(self.initial_capital_usdt,self.leverage,self.margin_fraction,
                   self.stop_bps,self.target_bps,self.entry_ttl_ms,
                   self.maximum_holding_ms,self.max_quote_age_ms)
        nonnegatives=(self.minimum_taker_fee_rate,self.adverse_slippage_bps,
                     self.minimum_entry_latency_ms,self.maximum_entry_drift_bps,
                     self.modeled_carry_8h_rate,self.minimum_net_target_usdt)
        if any(not math.isfinite(x) or x<=0 for x in positives) or any(
                not math.isfinite(x) or x<0 for x in nonnegatives):
            raise ValueError('Invalid paper policy parameters')
        if not (1 <= self.leverage <= 20 and 0 < self.margin_fraction <= .9
                and self.entry_ttl_ms >= self.minimum_entry_latency_ms
                and self.stop_bps < 5000 and self.target_bps < 5000
                and self.minimum_taker_fee_rate < .1
                and self.adverse_slippage_bps < 1000
                and self.modeled_carry_8h_rate < .1):
            raise ValueError('Unsafe paper policy bounds')


def tier_risk_fraction(equity, peak):
    """Hypothetical v3 risk ceilings, NOT validated live strategy permissions."""
    if equity <= 0 or peak <= 0:
        return 0
    drawdown=max(0,(peak-equity)/peak)
    if drawdown >= .06:
        return 0
    base=.0025 if equity < 20 else .0035 if equity < 50 else .005 if equity < 100 else .0075
    return base * (.5 if drawdown >= .03 else 1.0)


def prepare_rules(scan_report):
    specs=scan_report.get('paper_contract_specs')
    if not isinstance(specs,dict) or not specs:
        raise ValueError('No recorded verified exchange contract rules; recapture with v3.2 observer')
    result={}
    for symbol,spec in specs.items():
        rule=ContractRules(**spec['rules'])
        if rule.symbol != symbol or not symbol.endswith('USDTM'):
            raise ValueError('Contract specification symbol mismatch')
        fee=float(spec['taker_fee_rate'])
        if not math.isfinite(fee) or not 0 <= fee < .1:
            raise ValueError('Invalid observed exchange fee')
        result[symbol]=(rule,fee)
    return result


def size_for_quote(*, equity, peak, quote, direction, rules, observed_fee, policy):
    """Conservative market-taker entry/stop/target quote model.

    All prices used here come from decision-time quote plus explicitly modeled
    future stop/target assumptions. NO future market quote is used for sizing.
    """
    risk=tier_risk_fraction(equity,peak)
    if risk <= 0:
        return None,'drawdown_halted'
    try:
        bid=float(quote['bid']); ask=float(quote['ask'])
        if not all(math.isfinite(x) and x>0 for x in (bid,ask)) or bid>=ask:
            return None,'bad_quote'
    except (ValueError,KeyError,TypeError):
        return None,'bad_quote'
    if direction not in ('LONG','SHORT'):
        raise ValueError('Unsupported paper position direction')
    fee=max(observed_fee,policy.minimum_taker_fee_rate)
    slip=policy.adverse_slippage_bps/10_000
    mid=(bid+ask)/2
    halfspread=(ask-bid)/2
    s=1 if direction=='LONG' else -1
    entry=rules.price(ask*(1+slip), up=True) if s==1 else rules.price(bid*(1-slip), up=False)
    # Synthetic stop/target are only planned thresholds. Future fill prices
    # will come from observed bid/ask, with adverse slippage, NEVER from targets.
    stop_mid=mid*(1-s*policy.stop_bps/10_000)
    target_mid=mid*(1+s*policy.target_bps/10_000)
    worst_stop_quote=(stop_mid-halfspread) if s==1 else (stop_mid+halfspread)
    target_exit_quote=(target_mid-halfspread) if s==1 else (target_mid+halfspread)
    stop_fill=rules.price(worst_stop_quote*(1-slip if s==1 else 1+slip),up=s==-1)
    target_fill=rules.price(target_exit_quote*(1-slip if s==1 else 1+slip),up=s==-1)
    if min(entry,stop_fill,target_fill,stop_mid,target_mid)<=0:
        return None,'invalid_stop_or_target'
    unit=float(rules.contract_size)
    loss_one=(s*(entry-stop_fill)+fee*(entry+stop_fill))*unit
    gain_one=(s*(target_fill-entry)-fee*(entry+target_fill))*unit
    if loss_one<=0 or gain_one<=0:
        return None,'target_not_net_profitable_after_costs'
    by_risk=equity*risk/loss_one
    by_margin=equity*policy.margin_fraction/(entry*unit*(1/policy.leverage+2*fee))
    quantity=rules.quantity(min(by_risk,by_margin,float(rules.max_qty)))
    if not rules.valid(quantity,entry) or quantity<=0:
        return None,'minimum_lot_exceeds_account_risk_or_margin'
    available=float(quote['ask_base_size'] if s==1 else quote['bid_base_size'])
    if not math.isfinite(available) or available < quantity*unit:
        return None,'insufficient_displayed_depth_at_entry'
    if gain_one*quantity < policy.minimum_net_target_usdt:
        return None,'target_net_pnl_too_small'
    return {
        'direction':direction,'quantity_contracts':quantity,'contract_multiplier':unit,
        'price_tick_size':rules.tick_size,
        'entry_price':entry,'entry_fee_usdt':entry*unit*quantity*fee,
        'fee_rate':fee,'planned_stop_mid':stop_mid,'planned_target_mid':target_mid,
        'planned_stop_quote':worst_stop_quote,
        'planned_target_net_usdt':gain_one*quantity,
        'planned_loss_usdt':loss_one*quantity,
        'risk_budget_usdt':equity*risk,
        'margin_reserved_usdt':entry*unit*quantity/policy.leverage,
        'entry_notional_usdt':entry*unit*quantity,
    },None


def finish_position(pos, quote, timestamp, reason, policy):
    """Close only on a subsequent OBSERVED quote. No fill on missing data."""
    direction=pos['direction']
    s=1 if direction=='LONG' else -1
    exit_quote=float(quote['bid'] if s==1 else quote['ask'])
    if not math.isfinite(exit_quote) or exit_quote<=0:
        raise ValueError('Invalid observed exit quote')
    slip=policy.adverse_slippage_bps/10_000
    modeled=exit_quote*(1-slip if s==1 else 1+slip)
    tick=Decimal(pos['price_tick_size'])
    price=float((Decimal(str(modeled))/tick).to_integral_value(
        rounding=ROUND_FLOOR if s==1 else ROUND_CEILING)*tick)
    quantity=pos['quantity_contracts']
    unit=pos['contract_multiplier']
    fee=price*quantity*unit*pos['fee_rate']
    gross=s*(price-pos['entry_price'])*quantity*unit
    held=max(0,timestamp-pos['entry_received_ms'])
    carry=pos['entry_notional_usdt']*policy.modeled_carry_8h_rate*held/28_800_000
    net=gross-pos['entry_fee_usdt']-fee-carry
    return {**pos,'exit_received_ms':timestamp,'exit_price':price,'exit_quote':exit_quote,
            'exit_reason':reason,'holding_ms':held,
            'gross_pnl_usdt':gross,'exit_fee_usdt':fee,
            'modeled_carry_usdt':carry,'net_pnl_usdt':net}


def simulate(connection, *, policy=PaperPolicy(), shadow=ShadowPolicy()):
    """Run chronological paper event replay. No future observations leak.

    Treat missing data as missing. Never close an open position at a fabricated
    final bid/ask, never force an entry or pretend an 8-USDT lot is affordable.
    """
    connection.row_factory=sqlite3.Row
    # A future watchlist must never be used to simulate an earlier signal.
    # Until timeline-aware multi-scan replay is implemented, enforce one scan.
    if connection.execute('SELECT count(*) FROM market_scans').fetchone()[0] != 1:
        raise ValueError('Multi-scan capture needs time-aware contract/watchlist replay')
    data=connection.execute('SELECT raw_report FROM market_scans ORDER BY id DESC LIMIT 1').fetchone()
    if not data:
        raise ValueError('Missing public market scan')
    report=json.loads(data[0])
    rules=prepare_rules(report)
    selected=set(rules)
    selected_watch=connection.execute('SELECT selection FROM watchlists ORDER BY id DESC LIMIT 1').fetchone()
    if selected_watch:
        selected &= set(json.loads(selected_watch[0]).get('deep_symbols',[]))
    if not selected:
        raise ValueError('No observed selected symbols with validated contract rules')
    account=policy.initial_capital_usdt
    peak=account
    halted=False
    rows=connection.execute("""SELECT rowid,symbol,channel,event_ms,received_ms,normalized
         FROM raw_events ORDER BY received_ms,rowid""")
    trades=defaultdict(deque)
    last_book={}
    last_episode={}
    last_print={}
    pending={}
    position=None
    completed=[]
    decisions=[]
    counts=Counter()
    last_arrival=-1
    for row in rows:
        sym=row['symbol']
        if sym not in selected:
            continue
        now=int(row['received_ms'])
        if now < last_arrival:
            raise ValueError('Backward receipt-time replay')
        last_arrival=now
        channel=row['channel']
        if now < report['time_ms']:
            continue
        event=json.loads(row['normalized'])
        counts[channel]+=1
        if channel=='level2':
            if event.get('verified') or event.get('sequence_verified'):
                last_book[sym]=now
            continue
        if channel=='execution':
            if not isinstance(event.get('buyer_is_maker'),bool):
                raise ValueError('Untrusted taker side')
            record={'received_ms':now,'price':event['price'],
                    'quantity':event['quantity'],
                    'buyer_is_maker':event['buyer_is_maker']}
            trades[sym].append(record)
            last_print[sym]=now
            while trades[sym] and now-trades[sym][0]['received_ms']>shadow.window_ms:
                trades[sym].popleft()
            continue
        if channel!='tickerV2':
            continue
        quote_timestamp=int(event['timestamp'])
        if not 0 <= now-quote_timestamp <= policy.max_quote_age_ms:
            counts['stale_quote_skipped']+=1
            continue
        # A quote is model-executable only while the book feed is fresh;
        # the capture still cannot prove all taker prints were delivered.
        book_ok=(sym in last_book and 0<=now-last_book[sym]<=shadow.max_book_age_ms)
        if position is not None and position['symbol']==sym:
            if not book_ok:
                counts['exit_skipped_unverified_book']+=1
            elif now>position['entry_received_ms']:
                bid=float(event['bid']);ask=float(event['ask'])
                s=1 if position['direction']=='LONG' else -1
                reason=None
                # STOP before target: never grant benefit of fill ordering.
                if (s==1 and bid <= position['planned_stop_mid']) or (s==-1 and ask >= position['planned_stop_mid']):
                    reason='STOP'
                elif (s==1 and bid >= position['planned_target_mid']) or (s==-1 and ask <= position['planned_target_mid']):
                    reason='TARGET'
                elif now-position['entry_received_ms']>=policy.maximum_holding_ms:
                    reason='TIME'
                if reason:
                    # A top-of-book fill is not defensible when the displayed
                    # opposite quote has insufficient size for the full exit.
                    available=float(event['bid_base_size'] if s==1 else event['ask_base_size'])
                    required=position['quantity_contracts']*position['contract_multiplier']
                    if not math.isfinite(available) or available < required:
                        counts['exit_skipped_insufficient_displayed_depth']+=1
                        continue
                    closed=finish_position(position,event,now,reason,policy)
                    account+=closed['gross_pnl_usdt']-closed['exit_fee_usdt']-closed['modeled_carry_usdt']
                    completed.append(closed)
                    decisions.append({'time_ms':now,'symbol':sym,'action':'CLOSED',
                                      'reason':reason,'net_pnl_usdt':closed['net_pnl_usdt']})
                    peak=max(peak,account)
                    if account<=.94*peak:
                        halted=True
                    position=None
                    counts['closed_'+reason]+=1
        # Expire quotes based on real receipt-time, even during another position.
        if sym in pending and now-pending[sym]['signal_ms']>policy.entry_ttl_ms:
            decisions.append({'time_ms':now,'symbol':sym,'action':'REJECTED','reason':'signal_expired'})
            del pending[sym]
            counts['signal_expired']+=1
        if position is None and sym in pending:
            p=pending[sym]
            latency=now-p['signal_ms']
            if latency>=policy.minimum_entry_latency_ms and latency>0:
                del pending[sym]
                if not book_ok:
                    reason='unverified_book_at_entry'
                    plan=None
                else:
                    bid=float(event['bid']);ask=float(event['ask'])
                    mid=(bid+ask)/2
                    drift=abs(mid-p['signal_mid'])/p['signal_mid']*10_000
                    if drift>policy.maximum_entry_drift_bps:
                        plan=None;reason='late_or_adverse_price_drift'
                    elif 10_000*(ask-bid)/mid>shadow.max_spread_bps:
                        plan=None;reason='spread_widened_before_entry'
                    else:
                        rule,fee=rules[sym]
                        plan,reason=size_for_quote(equity=account,peak=peak,quote=event,
                            direction=p['direction'],rules=rule,observed_fee=fee,policy=policy)
                if plan is None:
                    counts[reason]+=1
                    decisions.append({'time_ms':now,'symbol':sym,'action':'REJECTED','reason':reason})
                else:
                    account-=plan['entry_fee_usdt']
                    position={**plan,'symbol':sym,
                              'signal_received_ms':p['signal_ms'],'entry_received_ms':now}
                    decisions.append({'time_ms':now,'symbol':sym,'action':'OPENED',
                                      'direction':p['direction'],'quantity_contracts':plan['quantity_contracts'],
                                      'risk_budget_usdt':plan['risk_budget_usdt']})
                    counts['opened']+=1
        # Do not switch coins or build multiple positions in the shared account.
        if position is not None or pending or halted or tier_risk_fraction(account,peak)<=0:
            continue
        if not book_ok:
            continue
        while trades[sym] and now-trades[sym][0]['received_ms']>shadow.window_ms:
            trades[sym].popleft()
        feature=observe(received_ms=now,recent_trades=trades[sym],
                        book_received_ms=last_book.get(sym),quote=event,policy=shadow)
        if feature['state']!='PRESSURE_CANDIDATE':
            continue
        previous=last_episode.get(sym)
        newest=last_print.get(sym,-1)
        changed=(previous is not None and previous[2]!=feature['direction'])
        cooled=(previous is None or now-previous[0]>=shadow.window_ms)
        if previous is not None and newest<=previous[1]:
            continue
        if not (cooled or changed):
            continue
        last_episode[sym]=(now,newest,feature['direction'])
        signal_mid=(float(event['bid'])+float(event['ask']))/2
        pending[sym]={'signal_ms':now,'signal_mid':signal_mid,
                      'direction':'LONG' if feature['direction']=='LONG_PRESSURE' else 'SHORT'}
        decisions.append({'time_ms':now,'symbol':sym,'action':'SIGNAL',
                          'direction':pending[sym]['direction'],
                          'note':'hypothetical unvalidated flow alignment'})
        counts['experimental_signals']+=1
    # Source EOF is not a price event: OPEN remains OPEN, never forced closed.
    for sym,p in pending.items():
        decisions.append({'time_ms':last_arrival,'symbol':sym,'action':'UNFILLED',
                          'reason':'no_subsequent_verified_quote_before_capture_end'})
    realized=sum(t['net_pnl_usdt'] for t in completed)
    # Account already paid fees for currently open leg, which is not realized P&L.
    balance_from_closed=policy.initial_capital_usdt+realized
    assert abs(account-(balance_from_closed-(position['entry_fee_usdt'] if position else 0)))<1e-6
    wins=sum(t['net_pnl_usdt']>0 for t in completed)
    losses=sum(t['net_pnl_usdt']<0 for t in completed)
    return {
        'status':'PAPER_REPLAY_ONLY','live_orders_enabled':False,
        'simulated_fills_not_exchange_execution':True,
        'strategy_validated':False,'initial_capital_usdt':policy.initial_capital_usdt,
        'final_cash_including_open_entry_fee_usdt':account,
        'closed_trade_realized_net_pnl_usdt':realized,
        'completed_paper_trades':len(completed),
        'winning_closed_trades':wins,'losing_closed_trades':losses,
        'open_simulated_position':position,'halted_at_drawdown':halted,
        'high_water_mark_usdt':peak,
        'signals_and_rejections':dict(counts),
        'source_event_counts':{k:v for k,v in counts.items() if k in ('execution','tickerV2','level2')},
        'completed_trades':completed,'decisions':decisions,
        'notes':[
          'Taker fills on subsequent observed BBO quotes plus modeled adverse slippage, never at signal quote.',
          'Stops/targets use future observed quotes; gaps can lead to much worse fills than planned.',
          'Modeled carry is NOT observed exchange funding settlement.',
          'Open positions remain unclosed at capture end; do not treat unmarked position as flat.',
          'Short capture, incomplete public trade tape and simplistic fixed parameters do not establish alpha.'
        ],
        'paper_policy':asdict(policy),'shadow_policy':asdict(shadow),
    }


def record_study(source_path, ledger_path, result):
    src=Path(source_path).resolve();dst=Path(ledger_path).resolve()
    if src==dst:
        raise ValueError('Paper ledger must be separate from public source database')
    digest=hashlib.sha256(canonical(result).encode('utf-8')).hexdigest()
    dst.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(dst)
    try:
        with c:
            c.executescript('''
              CREATE TABLE IF NOT EXISTS paper_runs(
                run_id TEXT PRIMARY KEY, report TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS paper_decisions(
                run_id TEXT, idx INTEGER, payload TEXT NOT NULL,
                PRIMARY KEY(run_id,idx));
              CREATE TABLE IF NOT EXISTS paper_trades(
                run_id TEXT, idx INTEGER, payload TEXT NOT NULL,
                PRIMARY KEY(run_id,idx));
            ''')
            c.execute('INSERT OR IGNORE INTO paper_runs VALUES (?,?)',(digest,canonical(result)))
            c.executemany('INSERT OR IGNORE INTO paper_decisions VALUES (?,?,?)',
                         [(digest,i,canonical(x)) for i,x in enumerate(result['decisions'])])
            c.executemany('INSERT OR IGNORE INTO paper_trades VALUES (?,?,?)',
                         [(digest,i,canonical(x)) for i,x in enumerate(result['completed_trades'])])
    finally:
        c.close()
    return digest


def main(argv=None):
    p=argparse.ArgumentParser(description='Research-only micro paper replay; cannot submit exchange orders')
    p.add_argument('--source-db',type=Path,required=True)
    p.add_argument('--paper-db',type=Path,required=True)
    p.add_argument('--report',type=Path)
    p.add_argument('--capital',type=float,default=8)
    a=p.parse_args(argv)
    if a.source_db.resolve()==a.paper_db.resolve():
        p.error('Public market source and paper ledger must be separate')
    uri=f'file:{a.source_db.resolve()}?mode=ro'
    c=sqlite3.connect(uri,uri=True)
    try:
        result=simulate(c,policy=PaperPolicy(initial_capital_usdt=a.capital))
    finally:
        c.close()
    result['run_id']=record_study(a.source_db,a.paper_db,result)
    output=canonical(result)+'\n'
    if a.report:
        a.report.parent.mkdir(parents=True,exist_ok=True)
        a.report.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    # Print compact summary; full decisions/trades saved to evidence files.
    print(json.dumps({k:v for k,v in result.items()
                      if k not in ('completed_trades','decisions')},indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
