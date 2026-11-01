"""v4.7 deterministic PAPER feasibility, not calibrated price forecasting.

Leverage changes required margin, never the signal or permissible monetary loss.
All alternatives use the same as-of observation and include execution costs.
"""
from dataclasses import dataclass,asdict
from decimal import Decimal,ROUND_FLOOR,ROUND_CEILING
from .capital_ladder import dec

D=lambda x:dec(str(x))
Q=D('1e-18')
VERSION='v4.7-isolated-ioc-conveyor-v1'


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
                    campaign_loss_fraction='.005',allowed=None):
    alternatives=[];valid=[]
    try:
        if side not in ('LONG','SHORT'):raise ValueError('invalid_direction')
        bid,ask=D(quote['bid']),D(quote['ask']);mid=(bid+ask)/2
        if bid<=0 or ask<=bid:raise ValueError('invalid_quote')
        if not market.get('data_fresh'):raise ValueError('unverified_market')
        if market.get('regime')!=('UP_TREND' if side=='LONG' else 'DOWN_TREND'):
            raise ValueError('no_directional_structure')
        if D(market.get('trend_persistence',0))<D('.5'):raise ValueError('unstable_trend')
        if D(market.get('volatility_bps',0))>25:raise ValueError('price_stop_inside_observed_noise')
        # A conservative historical envelope, NOT a probability or guaranteed move.
        observed=min(abs(D(market.get('momentum_bps',0))),abs(D(market.get('trend_bps',0))))
        if observed<=0:raise ValueError('unknown_move_capacity')
        if D(market.get('cvd_ratio',0))*(1 if side=='LONG' else -1)<=0:
            raise ValueError('flow_disagreement')
        unit=D(rules.contract_size);step=D(rules.step_size);price_step=D(rules.tick_size)
        allocation=D(allocation);margin=D(margin_budget);fee=D(fee_rate)
        budget=min(D(risk_budget),allocation*D(campaign_loss_fraction))
        if min(allocation,margin,budget)<=0:raise ValueError('no_uncommitted_budget')
        sign=D(1) if side=='LONG' else D(-1);slip=D(slippage_bps)/10000
        entry=tick((ask if side=='LONG' else bid)*(1+sign*slip),price_step,side=='LONG')
        stop=entry*(1-sign*D('.005'))
        stop_quote=stop-sign*(ask-bid)/2
        stop_fill=tick(stop_quote*(1-sign*(slip+D(stop_gap_bps)/10000)),price_step,side=='SHORT')
        carry_one=entry*unit*D(carry_rate)*D(horizon_ms)/28800000
        loss_one=sign*(entry-stop_fill)*unit+(entry+stop_fill)*unit*fee+carry_one
        if loss_one<=0 or stop_fill<=0:raise ValueError('invalid_full_cost_stop')
        minimum=max(D(rules.min_qty),(D(rules.min_notional)/entry/unit/step).to_integral_value(rounding=ROUND_CEILING)*step)
        minimum=(minimum/step).to_integral_value(rounding=ROUND_CEILING)*step
        # Never raise leverage just to make an unaffordable minimum order pass.
        baseline_minimum=minimum*entry*unit*(1+2*fee)
        if baseline_minimum>margin:raise ValueError('minimum_lot_unaffordable_at_1x_no_leverage_rescue')
        for leverage in range(1,6):
            row={'leverage':leverage,'accepted':False,'reason':None,'margin_mode':'ISOLATED','position_mode':'DIRECTIONAL_PAPER',
                 'contract_max_leverage':str(max_leverage),'cost_horizon_ms':horizon_ms,
                 'observation_horizons_ms':market.get('horizons_ms'),'liquidation_model':'NOT_EXCHANGE_VERIFIED',
                 'fee_source':'public_taker_or_conservative_minimum','funding_source':'MODELED_CARRY_NOT_PRIVATE_SETTLEMENT'}
            if leverage>D(max_leverage) or allowed is not None and leverage not in allowed:
                row['reason']='unconfirmed_contract_or_account_leverage'
            else:
                margin_one=entry*unit*(1/D(leverage)+2*fee)
                quantity=floor(min(budget/loss_one,margin/margin_one,D(rules.max_qty)),step)
                row.update(quantity_contracts=str(quantity),full_allocation_stop_loss=str(loss_one*allocation*D(leverage)/(entry*unit)),
                           full_allocation_rejected=loss_one*allocation*D(leverage)/(entry*unit)>budget)
                if quantity<minimum:row['reason']='minimum_lot_exceeds_full_cost_risk'
                else:
                    units=quantity*unit;notional=entry*units
                    entry_fee=cash(notional*fee,True);carry=cash(carry_one*quantity,True)
                    target=target_price(entry=entry,units=units,entry_fee=entry_fee,allocation=allocation,fee=fee,carry=carry,side=side,target_fraction=target_fraction)
                    quote_target=target/(1-sign*slip)
                    quote_target=tick(quote_target,price_step,side=='LONG')
                    required=sign*(quote_target/entry-1)*10000
                    observed_fill=tick(entry*(1+sign*observed/10000)*(1-sign*slip),price_step,side=='SHORT')
                    prospective=sign*(observed_fill-entry)*units-entry_fee-cash(observed_fill*units*fee,True)-carry
                    loss=cash(sign*(entry-stop_fill)*units+entry_fee+cash(stop_fill*units*fee,True)+carry,True)
                    row.update(margin_reserved_usdt=str(notional/D(leverage)),entry_notional_usdt=str(notional),
                        planned_loss_usdt=str(loss),risk_budget_usdt=str(budget),required_move_bps=str(required),
                        observed_move_capacity_bps=str(observed),prospective_net_usdt=str(cash(prospective)),
                        allocation_budget_usdt=str(allocation),quantity_contracts=str(quantity),contract_multiplier=str(unit),
                        entry_price=str(entry),entry_fee_usdt=str(entry_fee),fee_rate=str(fee),
                        planned_stop_mid=str(stop),planned_stop_quote=str(stop_quote),
                        planned_target_mid=str(quote_target),planned_target_net_usdt=str(allocation*D(target_fraction)),
                        price_tick_size=str(price_step),stop_gap_allowance_bps=str(stop_gap_bps))
                    if target<=0 or required>observed or prospective<allocation*D(target_fraction):row['reason']='net_target_outside_observed_move_envelope'
                    elif loss>budget:row['reason']='rounded_full_cost_stop_exceeds_budget'
                    else:row.update(accepted=True,reason='feasible_resized_risk_and_costs');valid.append(row)
            alternatives.append(row)
        selected=dict(valid[0]) if valid else None  # smallest leverage that meets economics
        return LeverageSelection(selected,alternatives,'selected_lowest_feasible_leverage' if selected else 'NO_TRADE')
    except (ValueError,KeyError,TypeError,ArithmeticError) as exc:
        return LeverageSelection(None,[{'leverage':n,'accepted':False,'reason':str(exc)} for n in range(1,6)],str(exc))
