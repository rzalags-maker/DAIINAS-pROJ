"""Replay-only shadow diagnostics for public KuCoin Futures observations.

This deliberately produces NO orders, NO paper fills, and NO profit forecast.
A pressure observation is not evidence of positive trading expectancy.
"""
import argparse
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import sqlite3


@dataclass(frozen=True)
class ShadowPolicy:
    window_ms: int = 30_000
    max_book_age_ms: int = 8_000
    min_trades: int = 3
    min_trade_notional: float = 25.0
    min_cvd_ratio: float = 0.40
    min_bbo_imbalance: float = 0.10
    max_spread_bps: float = 8.0

    def __post_init__(self):
        if not 1_000 <= self.window_ms <= 300_000 or not 0 < self.max_book_age_ms <= 60_000:
            raise ValueError('Invalid replay freshness limits')
        if not 1 <= self.min_trades <= 500 or self.min_trade_notional <= 0:
            raise ValueError('Invalid trade volume thresholds')
        if not 0 < self.min_cvd_ratio <= 1 or not 0 <= self.min_bbo_imbalance <= 1 or self.max_spread_bps <= 0:
            raise ValueError('Invalid observation thresholds')


def observe(*, received_ms, recent_trades, book_received_ms, quote, policy=ShadowPolicy()):
    """Classify an as-observed snapshot, without predicting price movement.

    Inputs must be inserted in received-time order. Never use executions whose
    receipt time is after the quote snapshot (avoid look-ahead bias).
    """
    if not isinstance(received_ms,int) or received_ms < 0:
        raise ValueError('Invalid receipt time')
    if book_received_ms is None or not 0 <= received_ms-book_received_ms <= policy.max_book_age_ms:
        return {'state':'NO_SIGNAL','reason':'missing_or_stale_verified_book'}
    try:
        bid=float(quote['bid'])
        ask=float(quote['ask'])
        bid_size=float(quote['bid_base_size'])
        ask_size=float(quote['ask_base_size'])
    except (KeyError,TypeError,ValueError) as exc:
        raise ValueError('Invalid market quote') from exc
    if any(not math.isfinite(x) or x < 0 for x in (bid,ask,bid_size,ask_size)) or bid <= 0 or ask <= bid:
        return {'state':'NO_SIGNAL','reason':'invalid_or_crossed_quote'}
    if bid_size == 0 or ask_size == 0:
        return {'state':'NO_SIGNAL','reason':'empty_top_quote'}
    mid=(bid+ask)/2
    spread_bps=10_000*(ask-bid)/mid
    if spread_bps > policy.max_spread_bps:
        return {'state':'NO_SIGNAL','reason':'spread_over_budget','spread_bps':round(spread_bps,5)}
    matched = []
    for tr in recent_trades:
        t=tr['received_ms']
        if t > received_ms:
            raise ValueError('Replay includes a future-arriving execution')
        if 0 <= received_ms-t <= policy.window_ms:
            qty=float(tr['quantity'])
            price=float(tr['price'])
            if not all(math.isfinite(x) and x > 0 for x in (qty,price)):
                raise ValueError('Invalid execution units')
            matched.append((price*qty, bool(tr['buyer_is_maker'])))
    if len(matched) < policy.min_trades:
        return {'state':'NO_SIGNAL','reason':'insufficient_executions','trades':len(matched)}
    buy=sum(n for n,maker in matched if not maker)  # aggressive taker buy
    sell=sum(n for n,maker in matched if maker)      # aggressive taker sell
    volume=buy+sell
    if volume < policy.min_trade_notional:
        return {'state':'NO_SIGNAL','reason':'insufficient_traded_notional','trades':len(matched)}
    cvd_ratio=(buy-sell)/volume
    depth_total=bid_size+ask_size
    bbo_imbalance=(bid_size-ask_size)/depth_total
    direction='NONE'
    if cvd_ratio >= policy.min_cvd_ratio and bbo_imbalance >= policy.min_bbo_imbalance:
        direction='LONG_PRESSURE'
    elif cvd_ratio <= -policy.min_cvd_ratio and bbo_imbalance <= -policy.min_bbo_imbalance:
        direction='SHORT_PRESSURE'
    return {'state':'PRESSURE_CANDIDATE' if direction!='NONE' else 'NO_SIGNAL',
            'direction':direction,
            'reason':'pressure_alignment_only_no_validated_net_edge' if direction!='NONE' else 'divergent_or_weak_pressure',
            'trades':len(matched),'volume_usdt':round(volume,6),
            'cvd_ratio':round(cvd_ratio,6),'bbo_imbalance':round(bbo_imbalance,6),
            'spread_bps':round(spread_bps,5),
            'estimated_minimum_round_trip_cost_bps':None,
            'execution_allowed':False}


def replay(connection, *, policy=ShadowPolicy()):
    """Deterministic chronological public-event replay from observer SQLite.

    Missing provider trade messages cannot be proven absent; this is not a
    full-tape completeness guarantee. Read-only connection.
    """
    conn=connection
    conn.row_factory=sqlite3.Row
    scans=conn.execute('SELECT raw_report FROM market_scans ORDER BY id DESC LIMIT 1').fetchone()
    if not scans:
        raise ValueError('No recorded market-wide scan')
    scan_report=json.loads(scans[0])
    by_symbol={r['symbol']:r for r in scan_report['audit']}
    trades=defaultdict(deque)
    last_book={}
    counts=Counter()
    observations=Counter()
    episodes=Counter()
    last_episode={}
    last_execution_arrival={}
    examples=[]
    last_arrival=-1
    sql="""SELECT symbol,channel,event_ms,received_ms,normalized
             FROM raw_events ORDER BY received_ms, rowid"""
    for row in conn.execute(sql):
        sym=row['symbol']
        channel=row['channel']
        received=row['received_ms']
        if received < last_arrival:
            raise ValueError('Out-of-order receipt timestamps')
        last_arrival=received
        obj=json.loads(row['normalized'])
        counts[channel]+=1
        if channel=='level2':
            if obj.get('verified') or obj.get('sequence_verified'):
                last_book[sym]=received
            continue
        if channel=='execution':
            if not isinstance(obj.get('buyer_is_maker'),bool):
                raise ValueError('Missing aggressor-side indicator')
            tr={'received_ms':received,'quantity':obj['quantity'],
                'price':obj['price'],'buyer_is_maker':obj['buyer_is_maker']}
            trades[sym].append(tr)
            last_execution_arrival[sym]=received
            # Consume no more than the trailing recent window.
            while trades[sym] and received-trades[sym][0]['received_ms']>policy.window_ms:
                trades[sym].popleft()
            continue
        if channel != 'tickerV2':
            continue
        while trades[sym] and received-trades[sym][0]['received_ms']>policy.window_ms:
            trades[sym].popleft()
        feature=observe(received_ms=received,recent_trades=trades[sym],
                        book_received_ms=last_book.get(sym),quote=obj,policy=policy)
        observations[(sym,feature['state'],feature['reason'])]+=1
        if feature['state']=='PRESSURE_CANDIDATE':
            # Repeated ticker changes reusing the same executions are NOT
            # independent opportunities. Record a new episode only after
            # fresh prints and either a side flip or a full window cooldown.
            old=last_episode.get(sym)
            newest=last_execution_arrival.get(sym,-1)
            new_evidence=(old is None or newest>old[1])
            side_flipped=old is not None and feature['direction']!=old[2]
            cooldown=old is None or received-old[0]>=policy.window_ms
            if new_evidence and (side_flipped or cooldown):
                episodes[sym]+=1
                last_episode[sym]=(received,newest,feature['direction'])
                if len(examples)<25:
                    pre=by_symbol.get(sym,{})
                    # Cost floor is only indicative: earlier scan snapshot.
                    feature['estimated_minimum_round_trip_cost_bps']=pre.get('estimated_round_trip_cost_bps')
                    examples.append({'symbol':sym,'received_ms':received,**feature})
    return {
        'status':'REPLAY_DIAGNOSTICS_ONLY',
        'simulation_only':True, 'market_orders_enabled':False,
        'validated_positive_expectancy':False, 'paper_trade_count':0,
        'market_contracts_in_original_scan':scan_report['contracts_observed'],
        'observed_symbols':sorted(set(x[0] for x in observations)),
        'event_counts':dict(counts),
        'pressure_snapshots':sum(n for (s,state,reason),n in observations.items()
                                  if state=='PRESSURE_CANDIDATE'),
        'pressure_candidates':sum(episodes.values()),
        'pressure_episodes_by_symbol':dict(episodes),
        'decision_reasons':{f'{sym}:{reason}':n for (sym,state,reason),n in sorted(observations.items())},
        'candidate_examples':examples,
        'policy':asdict(policy),
        'notes':[
          'Pressure alignment is NOT an entry/exit recommendation.',
          'No future price is used; no P&L, win rate or profit factor computed.',
          'KuCoin trade/ticker feeds do not guarantee complete per-message continuity.',
          'Estimate future executable spread, fees, market impact and stop risk separately before any paper entries.'
        ]
    }


def main(argv=None):
    p=argparse.ArgumentParser(description='Replay recorded public KuCoin events as shadow pressure diagnostics')
    p.add_argument('--db',type=Path,required=True)
    p.add_argument('--output',type=Path)
    args=p.parse_args(argv)
    uri=f'file:{args.db.resolve()}?mode=ro'
    conn=sqlite3.connect(uri,uri=True)
    try:
        result=replay(conn)
    finally:
        conn.close()
    payload=json.dumps(result,indent=2,allow_nan=False)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(payload)
    print(payload)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
