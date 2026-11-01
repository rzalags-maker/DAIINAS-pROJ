"""v4.7 deterministic PAPER feasibility, not calibrated price forecasting.

Leverage changes required margin, never the signal or permissible monetary loss.
All alternatives use the same as-of observation and include execution costs.
"""
from dataclasses import dataclass,asdict
from decimal import Decimal,ROUND_FLOOR,ROUND_CEILING
from .capital_ladder import dec

D=lambda x:dec(str(x))
Q=D('1e-18')
VERSION='v4.7-sniper-session-v2'


def cash(x,cost=False):return D(x).quantize(Q,rounding=ROUND_CEILING if cost else ROUND_FLOOR)
def floor(x,step):return (x/step).to_integral_value(rounding=ROUND_FLOOR)*step

def tick(x,step,up=False):return (x/step).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR)*step


@dataclass(frozen=True)
class LeverageSelection:
    selected: dict | None
    alternatives: list
    reason: str
    version: str=VERSION
    forecast_status: str='OBSERVED_MOVE_ENVELOPE_NOT_CALIBRATED_EXPECTANCY'
    def payload(self):return asdict(self)


def target_price(*,entry,units,entry_fee,allocation,fee,carry,side,target_fraction='.02'):
    """Exit FILL price necessary for net return on allocated campaign capital."""
    sign=D(1) if side=='LONG' else D(-1)
    return (D(allocation)*D(target_fraction)+sign*D(entry)*D(units)+D(entry_fee)+D(carry))/(D(units)*(sign-D(fee)))


def select_leverage(*,rules,quote,side,allocation,margin_budget,risk_budget,fee_rate,
                    market,max_leverage,slippage_bps=2,stop_gap_bps=5,
                    carry_rate='.0001',horizon_ms=90000,target_fraction='.02',
                    campaign_loss_fraction='.005',allowed=None,stop_fraction='.005',entry_fee_rate=None,target_fee_rate=None,entry_liquidity='TAKER',target_liquidity='TAKER'):
    alternatives=[];valid=[]
    try:
        if side not in ('LONG','SHORT'):raise ValueError('invalid_direction')
        bid,ask=D(quote['bid']),D(quote['ask']);mid=(bid+ask)/2
        if bid<=0 or ask<=bid:raise ValueError('invalid_quote')
        if not market.get('data_fresh'):raise ValueError('unverified_market')
        if market.get('regime')!=('UP_TREND' if side=='LONG' else 'DOWN_TREND'):
            raise ValueError('no_directional_structure')
        if D(market.get('trend_persistence',0))<D('.5'):raise ValueError('unstable_trend')
        if D(market.get('volatility_bps',0))>D(stop_fraction)*5000:raise ValueError('price_stop_inside_observed_noise')
        # A conservative historical envelope, NOT a probability or guaranteed move.
        observed=min(abs(D(market.get('momentum_bps',0))),abs(D(market.get('trend_bps',0))))
        if observed<=0:raise ValueError('unknown_move_capacity')
        if D(market.get('cvd_ratio',0))*(1 if side=='LONG' else -1)<=0:
            raise ValueError('flow_disagreement')
        unit=D(rules.contract_size);step=D(rules.step_size);price_step=D(rules.tick_size)
        allocation=D(allocation);margin=D(margin_budget);fee=D(fee_rate)
        entry_fee_rate=fee if entry_fee_rate is None else D(entry_fee_rate)
        target_fee_rate=fee if target_fee_rate is None else D(target_fee_rate)
        budget=min(D(risk_budget),allocation*D(campaign_loss_fraction))
        if min(allocation,margin,budget)<=0:raise ValueError('no_uncommitted_budget')
        sign=D(1) if side=='LONG' else D(-1);slip=D(slippage_bps)/10000
        entry=tick((bid if side=='LONG' else ask) if entry_liquidity=='MAKER' else (ask if side=='LONG' else bid)*(1+sign*slip),price_step,side=='LONG')
        stop=entry*(1-sign*D(stop_fraction))
        stop_quote=stop-sign*(ask-bid)/2
        stop_fill=tick(stop_quote*(1-sign*(slip+D(stop_gap_bps)/10000)),price_step,side=='SHORT')
        carry_one=entry*unit*D(carry_rate)*D(horizon_ms)/28800000
        loss_one=sign*(entry-stop_fill)*unit+(entry*entry_fee_rate+stop_fill*fee)*unit+carry_one
        if loss_one<=0 or stop_fill<=0:raise ValueError('invalid_full_cost_stop')
        minimum=max(D(rules.min_qty),(D(rules.min_notional)/entry/unit/step).to_integral_value(rounding=ROUND_CEILING)*step)
        minimum=(minimum/step).to_integral_value(rounding=ROUND_CEILING)*step
        # Never raise leverage just to make an unaffordable minimum order pass.
        baseline_minimum=minimum*entry*unit*(1+entry_fee_rate+fee)
        if baseline_minimum>margin:raise ValueError('minimum_lot_unaffordable_at_1x_no_leverage_rescue')
        for leverage in range(1,6):
            row={'leverage':leverage,'accepted':False,'reason':None,'margin_mode':'ISOLATED','position_mode':'DIRECTIONAL_PAPER','price_stop_fraction':str(stop_fraction),'entry_liquidity':entry_liquidity,'target_liquidity':target_liquidity,'stop_liquidity':'TAKER',
                 'contract_max_leverage':str(max_leverage),'cost_horizon_ms':horizon_ms,
                 'observation_horizons_ms':market.get('horizons_ms'),'liquidation_model':'NOT_EXCHANGE_VERIFIED',
                 'fee_source':'public_taker_or_conservative_minimum','funding_source':'MODELED_CARRY_NOT_PRIVATE_SETTLEMENT'}
            if leverage>D(max_leverage) or allowed is not None and leverage not in allowed:
                row['reason']='unconfirmed_contract_or_account_leverage'
            else:
                margin_one=entry*unit*(1/D(leverage)+entry_fee_rate+fee)
                quantity=floor(min(budget/loss_one,margin/margin_one,D(rules.max_qty)),step)
                row.update(quantity_contracts=str(quantity),full_allocation_stop_loss=str(loss_one*allocation*D(leverage)/(entry*unit)),
                           full_allocation_rejected=loss_one*allocation*D(leverage)/(entry*unit)>budget)
                if quantity<minimum:row['reason']='minimum_lot_exceeds_full_cost_risk'
                else:
                    units=quantity*unit;notional=entry*units
                    entry_fee=cash(notional*entry_fee_rate,True);carry=cash(carry_one*quantity,True)
                    target=target_price(entry=entry,units=units,entry_fee=entry_fee,allocation=allocation,fee=target_fee_rate,carry=carry,side=side,target_fraction=target_fraction)
                    quote_target=target/(1-sign*slip)
                    quote_target=tick(quote_target,price_step,side=='LONG')
                    required=sign*(quote_target/entry-1)*10000
                    observed_fill=tick(entry*(1+sign*observed/10000)*(1-sign*slip),price_step,side=='SHORT')
                    prospective=sign*(observed_fill-entry)*units-entry_fee-cash(observed_fill*units*target_fee_rate,True)-carry
                    loss=cash(sign*(entry-stop_fill)*units+entry_fee+cash(stop_fill*units*fee,True)+carry,True)
                    row.update(margin_reserved_usdt=str(notional/D(leverage)),entry_notional_usdt=str(notional),
                        planned_loss_usdt=str(loss),risk_budget_usdt=str(budget),required_move_bps=str(required),
                        observed_move_capacity_bps=str(observed),prospective_net_usdt=str(cash(prospective)),
                        allocation_budget_usdt=str(allocation),quantity_contracts=str(quantity),contract_multiplier=str(unit),
                        entry_price=str(entry),entry_fee_usdt=str(entry_fee),fee_rate=str(entry_fee_rate),target_fee_rate=str(target_fee_rate),stop_fee_rate=str(fee),
                        planned_stop_mid=str(stop),planned_stop_quote=str(stop_quote),
                        planned_target_mid=str(quote_target),planned_target_net_usdt=str(allocation*D(target_fraction)),
                        price_tick_size=str(price_step),stop_gap_allowance_bps=str(stop_gap_bps))
                    if target<=0 or required>observed or prospective<allocation*D(target_fraction):row['reason']='net_target_outside_observed_move_envelope'
                    elif loss>budget:row['reason']='rounded_full_cost_stop_exceeds_budget'
                    elif market.get('closed_candle_structure') and sign*(stop-D(market['closed_candle_structure']['swing_low' if side=='LONG' else 'swing_high']))>0:
                        row['reason']='price_stop_inside_recent_closed_structure'
                    else:row.update(accepted=True,reason='feasible_resized_risk_and_costs');valid.append(row)
            alternatives.append(row)
        selected=dict(valid[0]) if valid else None  # smallest leverage that meets economics
        return LeverageSelection(selected,alternatives,'selected_lowest_feasible_leverage' if selected else 'NO_TRADE')
    except (ValueError,KeyError,TypeError,ArithmeticError) as exc:
        return LeverageSelection(None,[{'leverage':n,'accepted':False,'reason':str(exc)} for n in range(1,6)],str(exc))


def select_sniper(*,maker_fee_rate,stop_candidates=('.005','.01'),entry_kind='MARKET_IOC',**inputs):
    """Coupled 2 stops x 5 leverages x 4 liquidity paths; no presumed maker fill.

    Maker alternatives are cost scenarios. POST_ONLY may propose a resting
    maker intent, but the ledger requires an authoritative MOCK fill receipt.
    Protective stop fees always use taker, including maker-TP alternatives.
    """
    all_rows=[];eligible=[];taker=D(inputs['fee_rate']);maker=D(maker_fee_rate)
    for distance in stop_candidates:
        for entry_role,target_role in (('TAKER','TAKER'),('MAKER','TAKER'),('TAKER','MAKER'),('MAKER','MAKER')):
            result=select_leverage(**inputs,stop_fraction=distance,entry_fee_rate=maker if entry_role=='MAKER' else taker,
                target_fee_rate=maker if target_role=='MAKER' else taker,entry_liquidity=entry_role,target_liquidity=target_role)
            route=(entry_role=='TAKER' and target_role=='TAKER') if entry_kind!='POST_ONLY_LIMIT' else (entry_role=='MAKER' and target_role=='TAKER')
            for row in result.alternatives:
                row.update(price_stop_fraction=str(distance),entry_liquidity=entry_role,target_liquidity=target_role,stop_liquidity='TAKER',
                    liquidity_path=entry_role+'/'+target_role,entry_kind=entry_kind,
                    executable_route=route,maker_fill_status='UNVERIFIED_REQUIRES_FILL_RECORD' if 'MAKER' in (entry_role,target_role) else 'MODELED_TAKER',
                    maker_fee_source='PUBLIC_METADATA_OR_NAMED_OWNER_PAPER_SCENARIO_NOT_AUTHENTICATED')
                all_rows.append(row)
                if row['accepted'] and route:eligible.append(row)
    eligible.sort(key=lambda x:(x['leverage'],D(x['required_move_bps']),D(x['price_stop_fraction'])))
    return LeverageSelection(dict(eligible[0]) if eligible else None,all_rows,
        'lowest_feasible_coupled_stop_leverage_route' if eligible else 'NO_TRADE')
