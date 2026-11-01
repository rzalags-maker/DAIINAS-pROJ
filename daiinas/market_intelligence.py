"""Per-symbol as-of observable states, not calibrated return probabilities.

Public execution CVD uses actual prints only; completeness is never inferred.
"""
import math
import statistics


def correlation(a,b,min_samples=12):
    # Equal publication-time buckets; never align with future observations.
    def returns(rows):return {y[0]:(y[1]/x[1]-1) for x,y in zip(rows,rows[1:]) if y[0]-x[0]==1000}
    aa,bb=returns(a),returns(b);common=sorted(aa.keys()&bb.keys())[-120:]
    if len(common)<min_samples:return None
    av=[aa[t] for t in common];bv=[bb[t] for t in common]
    am,bm=statistics.mean(av),statistics.mean(bv)
    den=math.sqrt(sum((x-am)**2 for x in av)*sum((y-bm)**2 for y in bv))
    return sum((x-am)*(y-bm) for x,y in zip(av,bv))/den if den else None


def update(previous,*,now,quote,book,trades,fee_rate,slippage_bps,book_max_age=8000):
    state=dict(previous or {});bid,ask=float(quote['bid']),float(quote['ask']);mid=(bid+ask)/2
    bucket=(now//1000)*1000
    rows=[list(x) for x in state.get('history',[]) if now-x[0]<=900000]
    if rows and rows[-1][0]==bucket:rows[-1]=[bucket,mid]
    else:rows.append([bucket,mid])
    rows=rows[-901:];state['history']=rows
    spread=(ask-bid)/mid*10000
    cost=spread+2*fee_rate*10000+2*slippage_bps
    recent=[x for x in rows if now-x[0]<=30000]
    trend=[x for x in rows if now-x[0]<=180000]
    volatility=[x for x in rows if now-x[0]<=600000]
    changes=[(b[1]/a[1]-1)*10000 for a,b in zip(volatility,volatility[1:])]
    vol=statistics.pstdev(changes) if len(changes)>1 else 0.
    momentum=(recent[-1][1]/recent[0][1]-1)*10000 if len(recent)>1 else 0
    drift=(trend[-1][1]/trend[0][1]-1)*10000 if len(trend)>1 else 0
    signs=[1 if x>0 else -1 if x<0 else 0 for x in changes[-60:]]
    persistence=abs(sum(signs))/max(1,len(signs))
    nonzero=[1 if x>0 else -1 for x in changes[-60:] if abs(x)>1e-8]
    oscillations=sum(a*b<0 for a,b in zip(nonzero,nonzero[1:]))
    amplitude=(max(x[1] for x in trend)/min(x[1] for x in trend)-1)*10000 if trend else 0
    fresh=book is not None and 0<=now-book['available_ms']<=book_max_age
    sizebid,sizeask=float(quote['bid_base_size']),float(quote['ask_base_size'])
    imbalance=(sizebid-sizeask)/max(sizebid+sizeask,1e-12)
    book_imbalance=None if not book else (float(book['bid_base_size'])-float(book['ask_base_size']))/max(float(book['bid_base_size'])+float(book['ask_base_size']),1e-12)
    prints=[t for t in trades if 0<=now-t['received_ms']<=30000]
    buy=sum(float(t['price'])*float(t['quantity']) for t in prints if not t['buyer_is_maker'])
    sell=sum(float(t['price'])*float(t['quantity']) for t in prints if t['buyer_is_maker'])
    flow=(buy-sell)/(buy+sell) if buy+sell else 0
    threshold=max(cost,vol*math.sqrt(max(1,len(trend)))*1.5)
    if not fresh or sizebid<=0 or sizeask<=0:raw='DISLOCATED';reason='unverified_or_missing_liquidity'
    elif len(rows)<12 or now-rows[0][0]<10000:raw='UNKNOWN';reason='insufficient_history'
    elif changes and abs(changes[-1])>max(cost*3,vol*6):raw='DISLOCATED';reason='abnormal_price_gap'
    elif drift*momentum<0 and abs(momentum)>cost/2:raw='TRANSITION';reason='micro_trend_disagreement'
    elif drift>threshold and momentum>0 and persistence>=.5:raw='UP_TREND';reason='persistent_upward_observation'
    elif drift<-threshold and momentum<0 and persistence>=.5:raw='DOWN_TREND';reason='persistent_downward_observation'
    elif oscillations>=4 and amplitude>cost*2 and persistence<.5:raw='RANGE';reason='observed_cost_exceeding_oscillation_not_validated_edge'
    else:raw='UNKNOWN';reason='no_cost_adjusted_structure'
    prior=state.get('regime','UNKNOWN')
    candidate_since=state.get('candidate_since',now) if state.get('candidate')==raw else now
    # Immediate adverse health/transition, confirmed directional/range changes only.
    if raw in ('UNKNOWN','DISLOCATED','TRANSITION') or now-candidate_since>=3000:regime=raw
    else:regime=prior if prior in ('UNKNOWN','TRANSITION','DISLOCATED') else 'TRANSITION'
    changed=regime!=prior
    state.update(symbol_time_ms=now,regime=regime,candidate=raw,candidate_since=candidate_since,
        last_transition_ms=now if changed else state.get('last_transition_ms',now),
        momentum_bps=momentum,trend_bps=drift,trend_persistence=persistence,volatility_bps=vol,
        volatility_regime='HIGH' if vol>cost else 'LOW' if vol<cost/4 else 'NORMAL',
        cvd_notional=buy-sell,cvd_ratio=flow,observed_print_count=len(prints),
        bbo_imbalance=imbalance,l2_pressure=book_imbalance,spread_bps=spread,
        round_trip_cost_floor_bps=cost,range_amplitude_bps=amplitude,oscillations=oscillations,
        entry_bid_depth=sizebid,entry_ask_depth=sizeask,data_fresh=fresh,
        evidence_confidence='OBSERVATIONAL_ONLY' if len(rows)>=12 and fresh else 'LOW',
        expected_net_status='UNSUPPORTED_UNTIL_HELD_OUT_VALIDATION',reason=reason,
        prospective_move_minus_cost_bps=max(abs(momentum),abs(drift),amplitude/2)-cost,
        horizons_ms={'micro':30000,'trend':180000,'volatility':600000})
    return state


def supported_hedge(evidence,now,policy_hash):
    if not evidence:return False
    try:
        return (evidence['sample_kind']=='observed_public' and len(evidence['source_sha256'])==64
            and evidence['policy_sha256']==policy_hash
            and 0<=evidence['training_end_ms']<evidence['validation_start_ms']<=evidence['validation_end_ms']<=now
            and evidence['held_out_campaigns']>=30 and evidence['net_return_lower_95pct']>0
            and evidence['advantage_over_directional_lower_95pct']>0
            and evidence['advantage_over_flat_lower_95pct']>0
            and evidence['both_leg_exits_validated'] is True)
    except (KeyError,TypeError,ValueError):return False
