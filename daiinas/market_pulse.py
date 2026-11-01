"""Whole-catalog bounded summary history. Quotes are not order-flow evidence."""
import math


def rank_pulse(report,contracts,tickers,*,now,previous=None):
    previous=previous or {};tickers={x['symbol']:x for x in tickers}
    audit={x['symbol']:x for x in report['audit']};markets={};ranked=[]
    for contract in contracts:
        sym=contract['symbol'];review=audit[sym];tick=tickers.get(sym)
        prior=previous.get(sym,{});history=[x for x in prior.get('history',[]) if 0<=now-x[0]<=3600000]
        record={'symbol':sym,'time_ms':now,'action':'NO_TRADE','regime':'UNKNOWN','reason':'missing_or_ineligible_summary','history':history,'order_flow_status':'NOT_OBSERVED_IN_SUMMARY'}
        if review['eligible'] and tick:
            mid=review['mid_price'];history=(history+[[now,mid]])[-121:]
            moves={}
            for horizon in (60000,300000,900000,3600000):
                rows=[x for x in history if now-x[0]>=horizon]
                moves[str(horizon)]=(mid/rows[-1][1]-1)*10000 if rows else None
            known=[v for v in moves.values() if v is not None]
            direction=1 if known and all(v>0 for v in known) else -1 if known and all(v<0 for v in known) else 0
            changes=[abs(b[1]/a[1]-1)*10000 for a,b in zip(history,history[1:])]
            cost=review['estimated_round_trip_cost_bps']
            gap=bool(changes and len(changes)>3 and changes[-1]>max(200,6*sum(changes[:-1])/len(changes[:-1])))
            regime='DISLOCATED' if gap else 'UP_TREND' if direction>0 else 'DOWN_TREND' if direction<0 else 'RANGE' if known else 'UNKNOWN'
            action='LONG' if regime=='UP_TREND' else 'SHORT' if regime=='DOWN_TREND' else 'NO_TRADE'
            strength=min((abs(v) for v in known),default=0)
            # Liquidity is an observation priority, never alpha. Movement alone
            # cannot turn a spike or an expensive instrument into a trade signal.
            score=(strength/max(cost,1)+math.log10(review['turnover_24h_usdt']+1)) if action!='NO_TRADE' else math.log10(review['turnover_24h_usdt']+1)/100
            record.update(history=history,moves_bps=moves,regime=regime,action=action,
                          reason='shortlist_requires_deep_flow_and_risk_validation' if action!='NO_TRADE' else 'summary_has_no_reliable_direction',
                          ranking_score=score,spread_bps=review['spread_bps'])
            if not gap:ranked.append({**review,'pulse_score':score,'selection_score':score})
        markets[sym]=record
    ranked.sort(key=lambda x:(-x['pulse_score'],x['symbol']))
    report=dict(report);report['selected_for_deeper_observation']=ranked[:report['policy']['top']]
    report['whole_market_pulse']={'time_ms':now,'catalog_count':len(contracts),'markets':markets,
        'ranking':[x['symbol'] for x in ranked],'status':'OBSERVATION_PRIORITY_NOT_TRADING_AUTHORIZATION'}
    return report
