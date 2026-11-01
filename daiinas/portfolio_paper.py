"""Opt-in v4 portfolio on the audited v3.3 journal/transaction/writer machinery.

Decimal money, protected reserve, up to ten independent paper legs. No orders.
"""
from dataclasses import asdict,dataclass,replace
from decimal import Decimal,ROUND_FLOOR,ROUND_CEILING
import json
import math

from .capital_ladder import CapitalLadder,dec
from .continuous_paper import PaperLedger
from .continuous_store import Timeline,digest,canonical
from .paper_micro import size_for_quote,finish_position,PaperPolicy
from .shadow_flow import observe,ShadowPolicy
from .paper_audit import position_costs
from .market_intelligence import update as update_market,correlation,supported_hedge

D=lambda v:dec(str(v))
ZERO=D(0)
MONEY_QUANTUM=D('0.000000000000000001')
EXECUTION_VERSION='v4.1-decimal18-v2'

def money(value,*,cost=False):
    # Conservative fixed ledger precision avoids association-dependent repeating carry.
    return D(value).quantize(MONEY_QUANTUM,rounding=ROUND_CEILING if cost else ROUND_FLOOR)


@dataclass(frozen=True)
class PortfolioPolicy:
    initial_capital: str='8'
    mode: str='M3'
    decision_model: str='adaptive'
    correlation_limit: float=.85
    correlated_risk_fraction: str='.005'
    correlation_min_samples: int=12
    campaign_target_fraction: str='.02'
    campaign_loss_fraction: str='.005'
    cooldown_ms: int=30000
    allow_research_expansion: bool=False

    def __post_init__(self):
        if self.decision_model not in ('adaptive','pressure') or D(self.initial_capital)<=0 or self.mode not in ('M0','M1','M2','M3'):raise ValueError('Invalid portfolio scenario')
        if (not isinstance(self.allow_research_expansion,bool) or not isinstance(self.cooldown_ms,int)
                or isinstance(self.cooldown_ms,bool) or not isinstance(self.correlation_min_samples,int)
                or not 0<self.correlation_limit<1 or self.correlation_min_samples<4 or self.cooldown_ms<100):raise ValueError('Invalid evidence guards')
        if not 0<D(self.correlated_risk_fraction)<=D('.01'):raise ValueError('Concentration risk too large')
        if not 0<D(self.campaign_loss_fraction)<=D('.01') or not 0<D(self.campaign_target_fraction)<=D('.1'):raise ValueError('Invalid campaign assumptions')


class PortfolioLedger(PaperLedger):
    def __init__(self,path,source_id,policy=PaperPolicy(),shadow=ShadowPolicy(),*,portfolio=None):
        self.portfolio=portfolio if isinstance(portfolio,PortfolioPolicy) else PortfolioPolicy(**(portfolio or {}))
        if D(policy.initial_capital_usdt)!=D(self.portfolio.initial_capital):raise ValueError('Explicit initial-capital policy mismatch')
        super().__init__(path,source_id,policy,shadow,_profile={**asdict(self.portfolio),'execution_version':EXECUTION_VERSION})
        self.db.executescript("""CREATE TABLE IF NOT EXISTS campaign_records(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS campaign_no_update BEFORE UPDATE ON campaign_records BEGIN SELECT RAISE(ABORT,'Immutable campaign'); END;
            CREATE TRIGGER IF NOT EXISTS campaign_no_delete BEFORE DELETE ON campaign_records BEGIN SELECT RAISE(ABORT,'Immutable campaign'); END;""")
        if 'ladder' not in self.state:
            if self.state['cursor']:raise ValueError('Refuse implicit portfolio migration')
            ladder=CapitalLadder(self.portfolio.initial_capital)
            active=str(ladder.active)
            self.state.update(cash=self.portfolio.initial_capital,peak=active,last_equity=self.portfolio.initial_capital,
                ladder=ladder.export_state(),initial_slot_limit=ladder.slot_ceiling,positions={},pending_entries={},exit_requests={},
                campaigns={},quarantined_flows='0',realized='0',fees='0',entry_fees='0',exit_fees='0',carry='0',
                cooldowns={},market_states={},evidence={},active_equity=active,active_flow_adjustment='0',
                last_active_base=active,capital_status={},marked_unrealized='0',equity_verified=True,
                account_peak=self.portfolio.initial_capital,account_flow_adjustment='0',account_max_drawdown=0.,
                closed_summary={'count':0,'wins':0,'losses':0,'profit':'0','loss':'0'})

    def evidence_policy_hash(self):
        return digest({'portfolio':asdict(self.portfolio),'paper':asdict(self.policy),'shadow':asdict(self.shadow),'execution_version':EXECUTION_VERSION})

    def ladder(self):return CapitalLadder.restore(self.state['ladder'])
    def save_ladder(self,ladder):self.state['ladder']=ladder.export_state()
    def add(self,key,value):self.state[key]=str(D(self.state[key])+D(value))
    def pins(self):return sorted({p['symbol'] for p in [*self.state['positions'].values(),*self.state['pending_entries'].values()]})
    def leg_key(self,symbol,side):return symbol+'|'+side
    def observation_equity(self):return float(max(ZERO,min(self.ladder().active,D(self.state['active_equity']))))

    def reserved(self):
        return sum((D(p['margin_reserved_usdt']) for p in [*self.state['positions'].values(),*self.state['pending_entries'].values()]),ZERO)

    def planned(self):
        return sum((D(p.get('current_planned_loss_usdt',p['planned_loss_usdt'])) for p in [*self.state['positions'].values(),*self.state['pending_entries'].values()]),ZERO)

    def unsettled(self):
        return sum((D(c['realized_net']) for c in self.state['campaigns'].values() if not c['settled']),ZERO)

    def request(self,key,reason):
        p=self.state['positions'].get(key)
        if not p:return
        priority={'STOP':0,'ACCOUNT_HALT':1,'PORTFOLIO_RISK_CAP':1,'CAMPAIGN_STOP':1,'UNMATCHED_HEDGE':1,'CONTRACT_CHANGED':1,'CAPITAL_REDUCTION':2,
                  'TARGET':3,'CAMPAIGN_TARGET':3,'REGIME_EXIT':4,'TIME':5,'DATA_HEALTH':6}
        old=self.state['exit_requests'].get(key)
        if old and priority.get(old['reason'],7)<=priority.get(reason,7):return
        q=self.state['quotes'].get(p['symbol'],{})
        self.state['exit_requests'][key]={'reason':reason,'requested_ms':self.state['now_ms'],
            'requested_seq':self.seq,'provider_ms':q.get('timestamp',p['entry_provider_ms'])}
        self.audit('EXIT_REQUEST',position_id=p['id'],symbol=p['symbol'],positionSide=p['direction'],reason=reason)

    def unresolved_leg(self,key,reason):
        p=self.state['positions'][key]
        if p.get('unresolved')!=reason:
            p['unresolved']=reason
            self.audit('UNRESOLVED',position_id=p['id'],symbol=p['symbol'],reason=reason)

    def settle(self,campaign):
        s=self.state
        if campaign['settled'] or any(p['campaign_id']==campaign['id'] for p in [*s['positions'].values(),*s['pending_entries'].values()]):return
        ladder=self.ladder();before=ladder.active;net=D(campaign['realized_net'])
        ladder.realized_result(str(net));self.save_ladder(ladder)
        self.add('active_flow_adjustment',ladder.active-before-net)
        campaign['settled']=True;campaign['settled_seq']=self.seq;campaign['net_mark']=str(net)
        campaign['net_return_on_allocation']=str(net/D(campaign['allocated'])) if D(campaign['allocated'])>0 else None
        campaign.update(mark_status='FINALIZED',gross_base_units='0',net_base_units='0',gross_notional='0',net_notional='0',
                        reserved_margin='0',open_planned_risk='0',unresolved_legs=[])
        self.db.execute('INSERT INTO campaign_records VALUES (?,?)',(campaign['id'],canonical(campaign)))
        self.state['campaigns'].pop(campaign['id'],None)
        self.audit('CAMPAIGN_SETTLED',campaign_id=campaign['id'],net_pnl=str(net),ladder=ladder.snapshot())

    def invariant(self):
        s=self.state;ladder=self.ladder()
        fees=sum((D(p['entry_fee_usdt']) for p in s['positions'].values()),ZERO)
        expected=ladder.total+D(s['quarantined_flows'])+self.unsettled()-fees
        if D(s['cash'])!=expected:raise AssertionError('Portfolio Decimal cash/reserve/active/pending/deficit reconciliation')
        if len(s['positions'])+len(s['pending_entries'])>10:raise AssertionError('Ten gross legs maximum')
        if any(p['campaign_id'] not in s['campaigns'] for p in s['positions'].values()):raise AssertionError('Orphan campaign')

    def mark(self,external_flow=0.):
        s=self.state;now=s['now_ms'];ladder=self.ladder();marks=ZERO;all_valid=True
        for key,p in sorted(s['positions'].items()):
            sym=p['symbol'];q=s['quotes'].get(sym);spec=self.spec(sym)
            data=self.executable_quote(sym,q) if q and self.valid_quote(q,now) else None
            valid=bool(spec and digest(spec['rules'])==p['rules_hash'] and data and
                D(data['bid_base_size' if p['direction']=='LONG' else 'ask_base_size'])>=D(p['quantity_contracts'])*D(p['contract_multiplier']))
            if not valid:
                all_valid=False;reason='missing_or_changed_rules' if not spec or digest(spec['rules'])!=p['rules_hash'] else 'unverified_stale_or_insufficient_depth'
                self.unresolved_leg(key,reason)
                if reason=='missing_or_changed_rules':self.request(key,'CONTRACT_CHANGED')
                elif now-p.get('last_good_mark_ms',p['entry_received_ms'])>self.policy.max_quote_age_ms:self.request(key,'DATA_HEALTH')
                carry_since=D(p['entry_notional_usdt'])*D(self.policy.modeled_carry_8h_rate)*D(max(0,now-p.get('last_mark_ms',p['entry_received_ms'])))/D(28800000)
                m=min(ZERO,D(p.get('last_mark','0')))-carry_since
            else:
                m=self.close_math(p,data,now,spec)['net_after_exit_only']
                if p.get('unresolved'):self.audit('RESOLVED',position_id=p['id'],symbol=sym)
                p.update(last_mark=str(m),last_mark_ms=now,last_good_mark_ms=now,unresolved=None)
                net_mark=m-D(p['entry_fee_usdt'])
                p['observed_mae_usdt']=str(min(D(p.get('observed_mae_usdt','0')),net_mark))
                p['observed_mfe_usdt']=str(max(D(p.get('observed_mfe_usdt','0')),net_mark))
            marks+=m
            if spec and digest(spec['rules'])==p['rules_hash'] and q:
                half=(D(q['ask'])-D(q['bid']))/2
                stop=D(p['planned_stop_mid'])+(-half if p['direction']=='LONG' else half)
                if stop>0:
                    horizon=max(now,p['entry_received_ms']+self.policy.maximum_holding_ms)
                    stop_money=self.close_math(p,{'bid':str(stop),'ask':str(stop)},horizon,spec)
                    p['current_planned_loss_usdt']=str(max(ZERO,-stop_money['net']))
            if now-p['entry_received_ms']>=self.policy.maximum_holding_ms:self.request(key,'TIME')
        entryfees=sum((D(p['entry_fee_usdt']) for p in s['positions'].values()),ZERO)
        # Closed winner proceeds remain unallocated until the WHOLE campaign settles.
        active_equity=ladder.active+self.unsettled()-entryfees+marks
        s['active_equity']=str(active_equity);s['marked_unrealized']=str(marks)
        s['last_equity']=str(D(s['cash'])+marks);s['equity_verified']=all_valid
        account_peak=max(D('.000000001'),D(s.get('account_peak',self.portfolio.initial_capital))+D(s.get('account_flow_adjustment','0')),D(s['last_equity']))
        s['account_peak']=str(account_peak);s['account_flow_adjustment']='0'
        s['account_max_drawdown']=max(s.get('account_max_drawdown',0.),float(max(ZERO,(account_peak-D(s['last_equity']))/account_peak)))
        s['mark_status']='FLAT' if not s['positions'] else 'VERIFIED_MODELED_COST_MARK' if all_valid else 'UNRESOLVED_INDICATIVE_ONLY'
        peak=max(D('0.000000001'),D(s['peak'])+D(s['active_flow_adjustment']),active_equity)
        s['active_flow_adjustment']='0';s['peak']=str(peak)
        dd=max(ZERO,(peak-active_equity)/peak);s['max_drawdown']=max(float(dd),s['max_drawdown'])
        if dd>=D('.06') and not s['halted']:s['halted']=True;self.audit('HALTED',drawdown=str(dd))
        cap=ladder.mark_to_market(str(min(ZERO,active_equity-ladder.active)),len(s['positions'])+len(s['pending_entries']))
        self.save_ladder(ladder);s['capital_status']=cap
        allowed=cap['allowed_slots']
        if not all_valid or s['halted'] or s['paused'] or len(s['positions'])+len(s['pending_entries'])>allowed:
            for key in sorted(list(s['pending_entries']),reverse=True):
                self.cancel(key,'portfolio_reduction_or_unverified_risk')
        excess=max(0,len(s['positions'])-allowed)
        for key in sorted(s['positions'],reverse=True)[:excess]:self.request(key,'CAPITAL_REDUCTION')
        per_leg=max(ZERO,active_equity)*D('.0025')*(D('.5') if dd>=D('.03') else 1)
        for key,p in s['positions'].items():
            if D(p.get('current_planned_loss_usdt',p['planned_loss_usdt']))>per_leg:self.request(key,'CAPITAL_REDUCTION')
        if s['halted'] or self.planned()>max(ZERO,active_equity)*D('.01'):
            for key in s['positions']:self.request(key,'ACCOUNT_HALT' if s['halted'] else 'PORTFOLIO_RISK_CAP')
        for campaign in list(s['campaigns'].values()):
            if campaign['settled']:continue
            legs=[p for p in s['positions'].values() if p['campaign_id']==campaign['id']]
            verified=all(not p.get('unresolved') for p in legs)
            net=D(campaign['realized_net'])+sum((D(p.get('last_mark','0'))-D(p['entry_fee_usdt']) for p in legs),ZERO)
            gross_units=sum((D(p['quantity_contracts'])*D(p['contract_multiplier']) for p in legs),ZERO)
            net_units=sum(((1 if p['direction']=='LONG' else -1)*D(p['quantity_contracts'])*D(p['contract_multiplier']) for p in legs),ZERO)
            quote=s['quotes'].get(campaign['symbol'])
            mid=(D(quote['bid'])+D(quote['ask']))/2 if quote and self.valid_quote(quote,now) else None
            campaign.update(gross_base_units=str(gross_units),net_base_units=str(net_units),
                gross_notional=str(gross_units*mid) if mid is not None and verified else None,
                net_notional=str(net_units*mid) if mid is not None and verified else None)
            campaign.update(mark_status='VERIFIED' if verified else 'UNRESOLVED',net_mark=str(net) if verified else None,
                indicative_net_mark=str(net),unresolved_legs=[p['id'] for p in legs if p.get('unresolved')],
                entry_gross_notional=str(sum((D(p['entry_notional_usdt']) for p in legs),ZERO)),
                entry_net_notional=str(sum(((1 if p['direction']=='LONG' else -1)*D(p['entry_notional_usdt']) for p in legs),ZERO)),
                reserved_margin=str(sum((D(p['margin_reserved_usdt']) for p in legs),ZERO)),
                open_planned_risk=str(sum((D(p['planned_loss_usdt']) for p in legs),ZERO)))
            if verified and campaign['allocated'] and legs:
                if net<=-D(campaign['allocated'])*D(self.portfolio.campaign_loss_fraction):reason='CAMPAIGN_STOP'
                elif net>=D(campaign['allocated'])*D(self.portfolio.campaign_target_fraction):reason='CAMPAIGN_TARGET'
                else:continue
                for key,p in s['positions'].items():
                    if p['campaign_id']==campaign['id']:self.request(key,reason)
        self.invariant()

    def close_math(self,p,q,now,spec):
        # Reuse audited adverse side/tick execution; independently keep money Decimal.
        numeric={k:float(p[k]) for k in ('quantity_contracts','contract_multiplier','entry_price','entry_fee_usdt','entry_notional_usdt')}
        model=finish_position({**p,**numeric,'fee_rate':float(max(D(spec['taker_fee_rate']),D(self.policy.minimum_taker_fee_rate)))},q,now,'MODEL',self.policy)
        units=D(p['quantity_contracts'])*D(p['contract_multiplier']);exit_price=D(model['exit_price'])
        gross=money((1 if p['direction']=='LONG' else -1)*(exit_price-D(p['entry_price']))*units)
        fee=money(exit_price*units*max(D(spec['taker_fee_rate']),D(self.policy.minimum_taker_fee_rate)),cost=True)
        carry=money(D(p['entry_notional_usdt'])*D(self.policy.modeled_carry_8h_rate)*D(max(0,now-p['entry_received_ms']))/D(28800000),cost=True)
        return {'exit_price':str(exit_price),'gross':gross,'exit_fee':fee,'carry':carry,
                'net_after_exit_only':gross-fee-carry,'net':gross-fee-carry-D(p['entry_fee_usdt'])}

    def cancel(self,key,reason):
        p=self.state['pending_entries'].pop(key)
        self.state['cooldowns'][p['symbol']]=self.state['now_ms']+self.portfolio.cooldown_ms
        c=self.state['campaigns'][p['campaign_id']]
        c['allocated']=str(max(ZERO,D(c['allocated'])-D(p['allocation_budget_usdt'])))
        self.audit('UNFILLED',signal_id=p['id'],symbol=p['symbol'],reason=reason)
        self.settle(self.state['campaigns'][p['campaign_id']])

    def plan(self,sym,side,q):
        s=self.state;ladder=self.ladder();count=len(s['positions'])+len(s['pending_entries'])
        effective=max(ZERO,min(ladder.active,D(s['active_equity'])))
        allowed=s['capital_status'].get('allowed_slots',0)
        if s['halted'] or s['paused'] or not s['equity_verified']:return None,'account_halt_pause_or_unverified_exposure'
        if count>=allowed or ladder.deficit:return None,'no_funded_slot'
        if count>=s['initial_slot_limit'] and not self.portfolio.allow_research_expansion:
            return None,'expansion_requires_independently_supported_expectancy'
        spec=self.spec(sym);scan=s['scan']
        if not spec or sym not in scan['watch']['deep_symbols'] or sym in scan['watch'].get('blocked_new_entries',[]):return None,'missing_current_entry_rules_or_capacity'
        data=self.executable_quote(sym,q)
        if not data:return None,'unverified_or_unaligned_depth'
        spread=(float(q['ask'])-float(q['bid']))/((float(q['ask'])+float(q['bid']))/2)*10000
        if spread>self.shadow.max_spread_bps:return None,'spread_over_budget'
        dd=max(ZERO,(D(s['peak'])-effective)/D(s['peak']))
        budget=min(effective*D('.0025')*(D('.5') if dd>=D('.03') else 1),
                   max(ZERO,effective*D('.01')-self.planned())/max(1,allowed-count))
        nominal=ladder.active/max(1,ladder.slot_ceiling)
        if ladder.stage=='EXPAND':nominal=min(D(ladder.policy.position_budget),nominal)
        elif ladder.stage=='SCALE':nominal=min(ladder.committed_active/ladder.policy.max_slots,nominal)
        margin=min(nominal*D('.8'),max(ZERO,effective*D('.8')-self.reserved()))
        # Conservative correlation clusters use GROSS planned risk, including opposite legs.
        correlated=ZERO
        for other in [*s['positions'].values(),*s['pending_entries'].values()]:
            corr=1. if other['symbol']==sym else correlation(s['market_states'].get(sym,{}).get('history',[]),
                s['market_states'].get(other['symbol'],{}).get('history',[]),self.portfolio.correlation_min_samples)
            if corr is None or abs(corr)>=self.portfolio.correlation_limit:correlated+=D(other['planned_loss_usdt'])
        budget=min(budget,max(ZERO,effective*D(self.portfolio.correlated_risk_fraction)-correlated))
        if budget<=0:return None,'correlation_or_concentration_risk_cap'
        # A pending fee is a commitment too, never financed by reserve or pending profit.
        holds=sum((D(p['entry_fee_usdt']) for p in s['pending_entries'].values()),ZERO)
        margin=min(margin,max(ZERO,ladder.active+self.unsettled()-sum((D(p['entry_fee_usdt']) for p in s['positions'].values()),ZERO)-self.reserved()-holds))
        rules,fee=self.rules(sym)
        market=s['market_states'].get(sym,{})
        effective_policy=replace(self.policy,stop_bps=max(self.policy.stop_bps,min(500,2*market.get('volatility_bps',0))),
            target_bps=max(self.policy.target_bps,min(1000,4*market.get('volatility_bps',0))))
        plan,reason=size_for_quote(equity=float(effective),peak=float(D(s['peak'])),quote=data,direction=side,
            rules=rules,observed_fee=fee,policy=effective_policy,risk_budget_usdt=float(budget),margin_budget_usdt=float(margin))
        if not plan:return None,reason
        # Final admission uses exact Decimal costs at the SAME adverse tick model.
        # The legacy helper proposes a conservative lot; it never owns v4 money.
        entry=D(plan['entry_price']);unit=D(plan['contract_multiplier']);fee_rate=max(D(fee),D(self.policy.minimum_taker_fee_rate))
        one={**plan,'quantity_contracts':'1','entry_notional_usdt':str(entry*unit),
             'entry_fee_usdt':str(money(entry*unit*fee_rate,cost=True)),'entry_received_ms':s['now_ms']}
        horizon=s['now_ms']+self.policy.maximum_holding_ms
        stop=plan['planned_stop_quote']
        unit_loss=-self.close_math(one,{'bid':stop,'ask':stop},horizon,spec)['net']
        half=(D(q['ask'])-D(q['bid']))/2
        target=D(plan['planned_target_mid'])+(-half if side=='LONG' else half)
        unit_gain=self.close_math(one,{'bid':str(target),'ask':str(target)},horizon,spec)['net']
        if unit_loss<=0 or unit_gain<=0:return None,'full_cost_stop_or_target_infeasible'
        step=D(rules.step_size)
        margin_one=entry*unit*(1/D(self.policy.leverage)+2*fee_rate)
        quantity=min(D(plan['quantity_contracts']),
                     (budget/unit_loss/step).to_integral_value(rounding=ROUND_FLOOR)*step,
                     (margin/margin_one/step).to_integral_value(rounding=ROUND_FLOOR)*step)
        if not rules.valid(float(quantity),float(entry)) or quantity<=0:return None,'minimum_lot_exceeds_full_cost_risk'
        plan.update(quantity_contracts=str(quantity),risk_budget_usdt=str(budget),
            planned_loss_usdt=str(unit_loss*quantity),planned_target_net_usdt=str(unit_gain*quantity),
            entry_notional_usdt=str(entry*unit*quantity),entry_fee_usdt=str(money(entry*unit*quantity*fee_rate,cost=True)),
            margin_reserved_usdt=str(entry*unit*quantity/D(self.policy.leverage)))
        if D(plan['planned_target_net_usdt'])<D(self.policy.minimum_net_target_usdt):return None,'target_net_below_budget_after_full_cost_sizing'
        plan['allocation_budget_usdt']=str(nominal)
        return plan,None

    def propose(self,sym,side,q,campaign_id=None):
        key=self.leg_key(sym,side);s=self.state
        if key in s['positions'] or key in s['pending_entries']:return False
        plan,reason=self.plan(sym,side,q)
        if not plan:
            if sym in s['market_states']:s['market_states'][sym].update(rejection_reason=reason,last_rejection_ms=s['now_ms'])
            self.audit('REJECTED',symbol=sym,positionSide=side,reason=reason);return False
        if self.portfolio.mode=='M2' and campaign_id:
            peers=[p for p in s['pending_entries'].values() if p['campaign_id']==campaign_id]
            if peers and D(peers[0]['quantity_contracts'])!=D(plan['quantity_contracts']):
                self.audit('REJECTED',symbol=sym,reason='symmetric_control_requires_matching_lots')
                return False
        if sym in s['market_states']:s['market_states'][sym]['rejection_reason']=None
        signal=f'signal:{self.seq}:{sym}:{side}'
        campaign_id=campaign_id or 'campaign:'+signal
        if campaign_id not in s['campaigns']:
            s['campaigns'][campaign_id]={'id':campaign_id,'symbol':sym,'realized_net':'0','settled':False,
                'allocated':'0','closed_legs':[],'filled_leg_count':0,'pairing_required':self.portfolio.mode=='M2','created_ms':s['now_ms'],'net_mark':'0','mark_status':'VERIFIED'}
        campaign=s['campaigns'][campaign_id]
        campaign['allocated']=str(D(campaign['allocated'])+D(plan['allocation_budget_usdt']))
        s['pending_entries'][key]={**plan,'id':signal,'campaign_id':campaign_id,'symbol':sym,'direction':side,
            'rules_hash':digest(self.spec(sym)['rules']),'signal_ms':s['now_ms'],'signal_seq':self.seq,
            'provider_ms':int(q['timestamp']),'signal_mid':(float(q['bid'])+float(q['ask']))/2}
        self.audit('SIGNAL',signal_id=signal,symbol=sym,positionSide=side,campaign_id=campaign_id)
        return True

    def fill_quote(self,sym,q):
        s=self.state;now=s['now_ms']
        if not self.valid_quote(q,now):self.audit('REJECTED_QUOTE',symbol=sym,reason='invalid_or_stale');return
        prior=s['quotes'].get(sym)
        if prior and int(q['timestamp'])<int(prior['timestamp']):self.audit('REJECTED_QUOTE',symbol=sym,reason='regressed');return
        s['quotes'][sym]={**q,'available_ms':now,'source_seq':self.seq}
        spec=self.spec(sym)
        if spec:
            s['market_states'][sym]=update_market(s['market_states'].get(sym),now=now,quote=q,
                book=s['books'].get(sym) if self.book_ok(sym,q) else None,trades=s['trades'].get(sym,[]),
                fee_rate=max(spec['taker_fee_rate'],self.policy.minimum_taker_fee_rate),
                slippage_bps=self.policy.adverse_slippage_bps,book_max_age=self.shadow.max_book_age_ms)
            s['market_states'][sym].update(contract_spec=spec,rules_hash=digest(spec['rules']))
        data=self.executable_quote(sym,q);spec=self.spec(sym)
        depth={side:D(data[side+'_base_size']) if data else ZERO for side in ('bid','ask')}
        for key,p in sorted(list(s['positions'].items())):
            if p['symbol']!=sym:continue
            sign=1 if p['direction']=='LONG' else -1;side='bid' if sign==1 else 'ask'
            if sign*(float(q[side])-p['planned_stop_mid'])<=0:self.request(key,'STOP')
            elif sign*(float(q[side])-p['planned_target_mid'])>=0:self.request(key,'TARGET')
            req=s['exit_requests'].get(key)
            if not req:continue
            if not spec or digest(spec['rules'])!=p['rules_hash']:self.unresolved_leg(key,'missing_or_changed_rules');continue
            later=(self.seq>req['requested_seq'] and now-req['requested_ms']>=self.policy.minimum_entry_latency_ms
                   and q['observed_ms']>=req['requested_ms']+self.policy.minimum_entry_latency_ms and int(q['timestamp'])>req['provider_ms'])
            if not later:continue
            needed=D(p['quantity_contracts'])*D(p['contract_multiplier'])
            if depth[side]<needed:self.unresolved_leg(key,'insufficient_verified_full_exit_depth');continue
            money=self.close_math(p,q,now,spec);depth[side]-=needed
            done={**p,'exit_reason':req['reason'],'exit_received_ms':now,'exit_source_seq':self.seq,
                'exit_provider_ms':int(q['timestamp']),'exit_wire_received_ms':q['observed_ms'],'exit_request_ms':req['requested_ms'],
                'exit_observed_bid':q['bid'],'exit_observed_ask':q['ask'],'exit_price':money['exit_price'],
                'exit_fee_usdt':str(money['exit_fee']),'modeled_carry_usdt':str(money['carry']),
                'gross_pnl_usdt':str(money['gross']),'net_pnl_usdt':str(money['net']),
                'holding_ms':now-p['entry_received_ms'],'exit_quote':q[side]}
            done['cost_attribution']=position_costs(done,carry_rate=self.policy.modeled_carry_8h_rate)
            self.add('cash',money['net_after_exit_only']);self.add('fees',money['exit_fee']);self.add('exit_fees',money['exit_fee'])
            self.add('carry',money['carry']);self.add('realized',money['net'])
            c=s['campaigns'][p['campaign_id']];c['realized_net']=str(D(c['realized_net'])+money['net']);c['closed_legs'].append(p['id'])
            summary=s['closed_summary'];summary['count']+=1
            if money['net']>0:summary['wins']+=1;summary['profit']=str(D(summary['profit'])+money['net'])
            elif money['net']<0:summary['losses']+=1;summary['loss']=str(D(summary['loss'])-money['net'])
            self.db.execute('INSERT INTO closed_positions VALUES (?,?)',(p['id'],canonical(done)))
            del s['positions'][key];s['exit_requests'].pop(key,None)
            s['cooldowns'][sym]=now+self.portfolio.cooldown_ms
            self.audit('CLOSED',position_id=p['id'],symbol=sym,reason=req['reason'],net_pnl=str(money['net']))
            self.settle(c)
        # Entries and exits on the same side share this single observed liquidity budget.
        for key,p in sorted(list(s['pending_entries'].items())):
            if p['symbol']!=sym:continue
            if now-p['signal_ms']>self.policy.entry_ttl_ms:self.cancel(key,'entry_ttl');continue
            if not (self.seq>p['signal_seq'] and now-p['signal_ms']>=self.policy.minimum_entry_latency_ms
                    and int(q['timestamp'])>p['provider_ms'] and q['observed_ms']>=p['signal_ms']+self.policy.minimum_entry_latency_ms):continue
            side='ask' if p['direction']=='LONG' else 'bid'
            # Temporarily remove its own commitments for independent re-sizing at actual fill.
            del s['pending_entries'][key]
            plan,reason=self.plan(sym,p['direction'],q)
            if plan and (D(plan['quantity_contracts'])>D(p['quantity_contracts']) or
                         self.portfolio.mode=='M2' and D(plan['quantity_contracts'])!=D(p['quantity_contracts'])):
                # Never enlarge an already admitted intent to chase capital or losses.
                plan=None;reason='changed_size_requires_new_signal'
            needed=D(plan['quantity_contracts'])*D(plan['contract_multiplier']) if plan else ZERO
            mid=(float(q['bid'])+float(q['ask']))/2
            if not spec or digest(spec['rules'])!=p['rules_hash']:plan=None;reason='changed_entry_rules'
            elif abs(mid-p['signal_mid'])/p['signal_mid']*10000>self.policy.maximum_entry_drift_bps:plan=None;reason='entry_drift'
            elif depth[side]<needed:plan=None;reason='shared_observed_depth_exhausted'
            if not plan:
                c=s['campaigns'][p['campaign_id']];c['allocated']=str(max(ZERO,D(c['allocated'])-D(p['allocation_budget_usdt'])))
                s['cooldowns'][sym]=now+self.portfolio.cooldown_ms
                if sym in s['market_states']:s['market_states'][sym].update(rejection_reason=reason,last_rejection_ms=now)
                self.audit('REJECTED',symbol=sym,reason=reason,signal_id=p['id']);self.settle(c);continue
            depth[side]-=needed
            pos={**plan,'id':'position:'+p['id'],'campaign_id':p['campaign_id'],'symbol':sym,'direction':p['direction'],
                'rules_hash':p['rules_hash'],'signal_received_ms':p['signal_ms'],'entry_received_ms':now,
                'entry_source_seq':self.seq,'entry_provider_ms':int(q['timestamp']),'entry_wire_received_ms':q['observed_ms'],
                'entry_observed_bid':q['bid'],'entry_observed_ask':q['ask'],'last_mark':str(-D(plan['entry_fee_usdt'])),
                'last_mark_ms':now,'unresolved':None}
            s['positions'][key]=pos;s['campaigns'][p['campaign_id']]['filled_leg_count']+=1;self.add('cash',-D(plan['entry_fee_usdt']));self.add('fees',plan['entry_fee_usdt']);self.add('entry_fees',plan['entry_fee_usdt'])
            self.audit('OPENED',position_id=pos['id'],symbol=sym,positionSide=p['direction'],campaign_id=p['campaign_id'])
        for c in list(s['campaigns'].values()):
            if c['symbol']==sym and c.get('pairing_required') and c.get('filled_leg_count')==1 and not any(p['campaign_id']==c['id'] for p in s['pending_entries'].values()):
                c['pairing_status']='UNMATCHED_EXIT_REQUESTED'
                for key,p in s['positions'].items():
                    if p['campaign_id']==c['id']:self.request(key,'UNMATCHED_HEDGE')
        self.choose(sym,q)

    def choose_pressure(self,sym,q):
        # Phase 1 uses the existing replay-safe pressure classifier independently per market.
        s=self.state
        if self.portfolio.mode=='M0' or s['now_ms']<s['cooldowns'].get(sym,0):return
        if any(p['symbol']==sym for p in [*s['positions'].values(),*s['pending_entries'].values()]):return
        feature=observe(received_ms=s['now_ms'],recent_trades=s['trades'].get(sym,[]),
            book_received_ms=s['books'].get(sym,{}).get('available_ms') if self.book_ok(sym,q) else None,quote=q,policy=self.shadow)
        if feature['state']!='PRESSURE_CANDIDATE':return
        prior=s['episodes'].get(sym);newest=s['last_print'].get(sym,-1)
        if prior and (newest<=prior[1] or s['now_ms']-prior[0]<self.shadow.window_ms):return
        s['episodes'][sym]=[s['now_ms'],newest,feature['direction']]
        self.propose(sym,'LONG' if feature['direction']=='LONG_PRESSURE' else 'SHORT',q)

    def choose(self,sym,q):
        s=self.state;now=s['now_ms'];m=s['market_states'].get(sym,{})
        action='NO_TRADE';reason=m.get('reason','missing_per_symbol_state')
        open_legs={k:p for k,p in s['positions'].items() if p['symbol']==sym}
        pending=any(p['symbol']==sym for p in s['pending_entries'].values())
        evidence=supported_hedge(s['evidence'].get(sym),now,self.evidence_policy_hash())
        if self.portfolio.decision_model=='pressure':
            self.choose_pressure(sym,q)
            action='MAINTAIN' if open_legs or pending else 'NO_TRADE';reason='legacy_pressure_research_control'
        elif self.portfolio.mode=='M0':reason='M0_flat_control'
        elif any(k in s['exit_requests'] for k in open_legs):
            action='REDUCE' if any(s['exit_requests'][k]['reason']=='CAPITAL_REDUCTION' for k in open_legs if k in s['exit_requests']) else 'EXIT'
            reason='existing_risk_request_precedes_new_tactic'
        elif open_legs:
            action='MANAGE_HEDGE' if len(open_legs)>1 else 'MAINTAIN';reason='existing_exposure'
            opposite=any((p['direction']=='LONG' and m.get('regime')=='DOWN_TREND') or
                         (p['direction']=='SHORT' and m.get('regime')=='UP_TREND') for p in open_legs.values())
            if opposite or m.get('regime')=='DISLOCATED':
                for k in open_legs:self.request(k,'REGIME_EXIT')
                action='EXIT';reason='per_symbol_regime_invalidated'
            elif len(open_legs)==1 and not pending and m.get('regime')=='RANGE' and evidence and self.portfolio.mode=='M3':
                p=next(iter(open_legs.values()));side='SHORT' if p['direction']=='LONG' else 'LONG'
                if now>=s['cooldowns'].get(sym,0) and now-p['entry_received_ms']>=self.portfolio.cooldown_ms:
                    if self.propose(sym,side,q,p['campaign_id']):action='ADD_OPPOSITE_LEG';reason='held_out_campaign_advantage_gate_passed'
        elif pending:action='MAINTAIN';reason='pending_entry_not_a_new_opportunity'
        elif now<s['cooldowns'].get(sym,0):reason='post_campaign_cooldown'
        elif not m.get('data_fresh') or m.get('prospective_move_minus_cost_bps',0)<=0:reason='no_cost_adjusted_observable_opportunity'
        elif self.portfolio.mode=='M2' and m.get('regime')=='RANGE':
            # Explicit losing-control mode only, never an adaptive hedge authorization.
            if self.propose(sym,'LONG',q):
                cid=s['pending_entries'][self.leg_key(sym,'LONG')]['campaign_id']
                if self.propose(sym,'SHORT',q,cid):action='ADD_OPPOSITE_LEG';reason='M2_symmetric_negative_control'
                else:self.cancel(self.leg_key(sym,'LONG'),'two_leg_control_requires_two_funded_slots')
        elif self.portfolio.mode=='M2':reason='symmetric_control_requires_observed_range'
        elif self.portfolio.mode in ('M1','M3') and m.get('regime') in ('UP_TREND','DOWN_TREND'):
            side='LONG' if m['regime']=='UP_TREND' else 'SHORT'
            aligned=(m.get('cvd_ratio',0)>0 and m.get('bbo_imbalance',0)>0) if side=='LONG' else (m.get('cvd_ratio',0)<0 and m.get('bbo_imbalance',0)<0)
            if aligned and m.get('observed_print_count',0)>=self.shadow.min_trades:
                if self.propose(sym,side,q):action='ENTER_'+side;reason='per_symbol_directional_research_hypothesis'
            else:reason='direction_flow_liquidity_disagreement'
        elif m.get('regime')=='RANGE':reason='hedge_advantage_UNSUPPORTED' if not evidence else 'no_independent_first_leg_setup'
        m.update(last_action=action,last_decision_ms=now,decision_reason=reason,hedge_evidence_supported=evidence)
        # Exactly one policy action per accepted material quote; fills are separate audit events.
        self.audit('DECISION',symbol=sym,regime=m.get('regime','UNKNOWN'),selected_action=action,reason=reason,
                   strategy_validated=False,hedge_evidence_supported=evidence)

    def portfolio_event(self,kind,p,available):
        s=self.state
        for key,v in list(s['pending_entries'].items()):
            if available-v['signal_ms']>self.policy.entry_ttl_ms:self.cancel(key,'entry_ttl')
        if kind=='SCAN':
            s['scan']=Timeline.scan(p,available)
            protected=set(s['scan']['watch']['deep_symbols'])|set(self.pins())
            for name in ('books','quotes','trades','episodes','last_print','market_states'):
                s[name]={k:v for k,v in s[name].items() if k in protected}
            for key,pos in list(s['pending_entries'].items()):
                spec=self.spec(pos['symbol'])
                if not spec or digest(spec['rules'])!=pos['rules_hash']:self.cancel(key,'contract_unavailable_or_changed')
            self.audit('SCAN',selected=s['scan']['watch']['deep_symbols'],pins=self.pins())
        elif kind=='SNAPSHOT':
            if p.get('sha256')!=digest(p['snapshot']):raise ValueError('Snapshot hash mismatch')
            s['books'].pop(p['symbol'],None);self.audit('BOOK_SNAPSHOT',symbol=p['symbol'])
        elif kind=='HEALTH':
            if p['state']=='CONNECTED':s['connected']=True;s['session_id']=p.get('session_id');s['trades'].clear()
            elif p['state'] in ('DISCONNECTED','CONNECTION_LOSS','STORAGE_CAPACITY_HALT'):s['connected']=False
            if p.get('symbol'):s['books'].pop(p['symbol'],None)
            else:s['books'].clear()
            self.audit('HEALTH',**p)
        elif kind=='CLOCK':
            if 'service' in p:s['service']=p['service']
        elif kind=='CONTROL':
            action=p.get('action')
            if action in ('pause','resume'):s['paused']=action=='pause';self.audit('CONTROL',operator_action=action)
            elif action=='capital-flow':
                amount=D(p['amount'])
                if amount!=money(amount) or D(s['quarantined_flows'])+amount<0:self.audit('CONTROL_REJECTED',reason='external_flows_quarantined_not_ladder_profit')
                else:self.add('quarantined_flows',amount);self.add('cash',amount);self.add('account_flow_adjustment',amount);self.audit('CONTROL',operator_action=action,amount=str(amount))
            elif action=='install-research-evidence':
                record=p.get('evidence',{});sym=p.get('symbol')
                if sym and supported_hedge(record,available,self.evidence_policy_hash()):
                    s['evidence'][sym]=record;self.audit('CONTROL',operator_action=action,symbol=sym,evidence_sha256=digest(record))
                else:self.audit('CONTROL_REJECTED',reason='unsupported_or_future_held_out_evidence')
            elif action=='reset-halt' and not s['positions'] and not s['pending_entries'] and len(p.get('review_note',''))>=8 and self.ladder().active>0:
                s['halted']=False;s['peak']=str(self.ladder().active);self.audit('CONTROL',operator_action=action,note=p['review_note'])
            else:self.audit('CONTROL_REJECTED',reason='unsupported_or_unsafe_control')
        elif kind=='MARKET':
            sym,channel=p['symbol'],p['channel'];data=p['normalized'];bound=self.spec(sym)
            reason=None
            if p.get('session_id') and (not s.get('connected') or p['session_id']!=s.get('session_id')):reason='retired_session'
            elif p.get('rules_hash') and (not bound or p['rules_hash']!=digest(bound['rules'])):reason='rule_version_mismatch'
            elif int(p['event_ms'])>available or int(p['received_ms'])>available or int(p.get('wire_received_ms',p['received_ms']))>available:reason='future_event'
            if reason:self.audit('REJECTED_EVENT',reason=reason,symbol=sym);return True
            if channel=='level2':
                if data.get('verified') is True and available-int(p['event_ms'])<=self.shadow.max_book_age_ms:
                    if sym not in s['books']:self.audit('VERIFIED_BOOK',symbol=sym)
                    s['books'][sym]={**data,'available_ms':available,'rules_hash':p.get('rules_hash')}
                else:s['books'].pop(sym,None)
            elif channel=='execution':
                if not isinstance(data['buyer_is_maker'],bool) or not all(math.isfinite(float(data[k])) and float(data[k])>0 for k in ('price','quantity')):raise ValueError('Invalid execution')
                s['trades'][sym]=[v for v in s['trades'].get(sym,[]) if available-v['received_ms']<=self.shadow.window_ms][-4999:]+[{**data,'received_ms':available}]
                s['last_print'][sym]=available
            elif channel=='tickerV2':self.fill_quote(sym,{**data,'observed_ms':p.get('wire_received_ms',p['received_ms'])})
            else:raise ValueError('Unknown market channel')
        else:raise ValueError('Unknown portfolio journal kind')
        return True

    def report(self):
        s=self.state;ladder=self.ladder();positions=list(s['positions'].values())
        return {'status':'PAPER_ONLY','engine':'v4','live_orders_enabled':False,'strategy_validated':False,'production_ready':False,
            'initial_capital':self.portfolio.initial_capital,'mode':self.portfolio.mode,
            'execution_version':EXECUTION_VERSION,'money_quantum_usdt':str(MONEY_QUANTUM),'evidence_policy_sha256':self.evidence_policy_hash(),'cash':s['cash'],
            'equity_last_mark':s['last_equity'],'executable_equity':s['last_equity'] if s['equity_verified'] else None,
            'mark_status':s['mark_status'],'active_equity':s['active_equity'],'ladder':ladder.snapshot(),
            'capital_status':s['capital_status'],'reserved_margin':str(self.reserved()),'planned_risk':str(self.planned()),
            'realized_net_pnl':s['realized'],'fees':s['fees'],'entry_fees':s['entry_fees'],'exit_fees':s['exit_fees'],'modeled_carry':s['carry'],
            'external_simulated_flows':s['quarantined_flows'],
            'account_maximum_drawdown':s['account_max_drawdown'],'account_peak':s['account_peak'],
            'maximum_drawdown_basis':'Active equity risk gate; total account metric is account_maximum_drawdown',
            'maximum_drawdown':s['max_drawdown'],'halted':s['halted'],
            'paused_new_entries':s['paused'],'positions':positions,'pending_entries':list(s['pending_entries'].values()),
            'exit_requests':s['exit_requests'],'campaigns':list(s['campaigns'].values())+[json.loads(r[0]) for r in self.db.execute('SELECT payload FROM campaign_records ORDER BY rowid DESC LIMIT 20')],
            'market_states':s['market_states'],
            'closed_summary':s['closed_summary'],'pins':self.pins(),'counts':s['counts'],'reason_counts':s['reason_counts'],
            'recent_closed_positions':[json.loads(row[0]) for row in self.db.execute('SELECT payload FROM closed_positions ORDER BY rowid DESC LIMIT 20')],
            'source_cursor':s['cursor'],'input_digest':s['input_digest'],'checkpoint_available_ms':s['now_ms'],
            'scan':s['scan'],'service':s.get('service'),'unsettled_campaign_pnl':str(self.unsettled())}
