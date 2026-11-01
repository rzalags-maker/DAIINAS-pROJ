"""v4.7 PAPER IOC fills/protection on the existing portfolio transaction.

No exchange transport. ACK below means modeled coverage, never an exchange ACK.
"""
from decimal import Decimal,ROUND_FLOOR
import json
from .adaptive_execution import cash,target_price
from .account_capital import mock_snapshot,reconcile
from .capital_ladder import CapitalLadder
from .continuous_store import canonical,digest
from .paper_audit import position_costs

D=lambda x:Decimal(str(x))
Z=D(0)


class ConveyorMixin:
    def paper_overlay_loss(self):
        s=self.state
        if self.v47() and self.portfolio.paper_settlement:
            # Compare the same modeled cash scope: paid components already in
            # the mirror must not be charged again by the paper risk overlay.
            return min(Z,D(s['cash'])+D(s['account_capital']['unallocated'])-D(s['account_capital']['cash'])+D(s['marked_unrealized']))
        return min(Z,D(s['last_equity'])-D(self.portfolio.initial_capital)-D(s['quarantined_flows']))

    def queue_model_cash(self,campaign_id,*,gross,fees,carry,complete,phase):
        if not self.portfolio.paper_settlement:return
        s=self.state
        event={'id':f'paper-cash:{self.seq:020d}:'+campaign_id+':'+phase,'type':'REALIZED_NET_TRADE',
               'account_id':s['account_capital']['account_id'],'timestamp_ms':s['now_ms'],
               'campaign_id':campaign_id,'campaign_complete':complete,'net':str(D(gross)-D(fees)-D(carry)),
               'gross':str(gross),'fees':str(fees),'funding':str(-D(carry))}
        s.setdefault('paper_settlements',[]).append(event)
        self.flush_paper_settlement()

    def queue_paper_settlement(self,campaign):
        # Components were posted when paid. Finalization validates attribution;
        # it must NEVER post the whole net again after entry/partial cash events.
        records=[json.loads(x[0]) for x in self.db.execute('SELECT payload FROM closed_positions')]
        records=[x for x in records if x['campaign_id']==campaign['id']]
        gross=sum((D(x['gross_pnl_usdt']) for x in records),Z)
        fees=sum((D(x['entry_fee_usdt'])+D(x['exit_fee_usdt']) for x in records),Z)
        carry=sum((D(x['modeled_carry_usdt']) for x in records),Z)
        if D(campaign['realized_net'])!=gross-fees-carry:raise AssertionError('Modeled campaign cash attribution discrepancy')

    def flush_paper_settlement(self):
        s=self.state;queue=s.get('paper_settlements',[]);snap=s['account_capital']['snapshot'];now=s['now_ms']
        if not queue or snap is None or now<=snap['timestamp_ms']:return
        event={**queue[0],'timestamp_ms':now}
        self.apply_model_snapshot(snap,event)
        queue.pop(0)

    def apply_model_snapshot(self,snap,event=None):
        s=self.state;net=D(event['net']) if event else Z
        cash_now=D(s['account_capital']['cash'])+net
        equity=cash_now+D(snap['unrealized_pnl'])-D(snap['liabilities'])
        held=sum((D(snap[k]) for k in ('position_margin','order_margin','restricted_collateral')),Z)
        free=max(Z,min(equity-held,D(snap['free_margin'])+net))
        snapshot=mock_snapshot(cash=str(cash_now),free_margin=str(free),timestamp_ms=s['now_ms'],
            snapshot_id='PAPER-MODELED:'+str(self.seq)+(':'+event['id'] if event else ':heartbeat'),
            account_id=snap['account_id'],unrealized_pnl=snap['unrealized_pnl'],liabilities=snap['liabilities'],
            restricted_collateral=snap['restricted_collateral'],orders=snap['orders'],positions=snap['positions'],
            cash_events=[event] if event else [],leverage=snap['leverage'])
        before=self.ladder()
        updated,records=reconcile(self.account_context(),snapshot,now_ms=s['now_ms'],owned_ids=set())
        after=CapitalLadder.restore(updated['ladder'])
        self.add('active_flow_adjustment',after.active-before.active-(after.realized_net-before.realized_net))
        s['ladder']=updated.pop('ladder');s['account_capital']=updated
        for record in records:
            action='MODELED_CASH_COMPONENT' if record.get('type')=='REALIZED_NET_TRADE' and record.get('campaign_complete') is False else record['event_type']
            self.audit(action,**{k:v for k,v in record.items() if k!='event_type'})
        self.audit('MODELED_ACCOUNT_ONLY',snapshot_id=snapshot.snapshot_id,actual_kucoin_connected=False)

    def choose_conveyor(self,sym,q):
        s=self.state;now=s['now_ms'];m=s['market_states'].get(sym,{})
        # Risk monitoring precedes discovery; invalidation applies per symbol.
        for key,p in s['positions'].items():
            market=s['market_states'].get(p['symbol'],{})
            opposite=(p['direction']=='LONG' and market.get('regime')=='DOWN_TREND') or (p['direction']=='SHORT' and market.get('regime')=='UP_TREND')
            if opposite or market.get('regime')=='DISLOCATED':self.request(key,'REGIME_EXIT')
        reason='no_qualified_candidate';chosen=None;candidates=[]
        if any(p.get('protection',{}).get('state')!='MODELED_ACKED' for p in s['positions'].values()):reason='protection_not_confirmed'
        elif s['exit_requests'] or s.get('paper_settlements'):reason='existing_exit_or_cash_reconciliation_first'
        elif s['paused'] or s['halted']:reason='operator_or_risk_halt'
        elif self.portfolio.mode=='M0':reason='M0_flat_control'
        else:
            occupied={p['symbol'] for p in [*s['positions'].values(),*s['pending_entries'].values()]}
            for symbol,market in s['market_states'].items():
                if symbol in occupied or now<s['cooldowns'].get(symbol,0):continue
                quote=s['quotes'].get(symbol)
                if not quote or not self.valid_quote(quote,now) or not market.get('data_fresh'):continue
                regime=market.get('regime');direction='LONG' if regime=='UP_TREND' else 'SHORT' if regime=='DOWN_TREND' else None
                if direction is None or market.get('observed_print_count',0)<self.shadow.min_trades:continue
                sign=1 if direction=='LONG' else -1
                if market.get('cvd_ratio',0)*sign<=0 or market.get('bbo_imbalance',0)*sign<=0:continue
                score=market.get('prospective_move_minus_cost_bps',0)/max(1,market.get('round_trip_cost_floor_bps',1))
                candidates.append((score,symbol,direction,quote))
            for score,symbol,direction,quote in sorted(candidates,key=lambda x:(-x[0],x[1])):
                if self.propose(symbol,direction,quote):chosen=(symbol,direction);reason='ranked_cost_risk_feasible';break
            if candidates and chosen is None:reason='all_ranked_candidates_failed_admission'
        conveyor=s.setdefault('conveyor',{'decisions':0,'entries':0,'partial_entries':0,'partial_exits':0})
        conveyor['decisions']=conveyor.get('decisions',0)+1
        conveyor.update(last_decision_ms=now,last_selected=list(chosen) if chosen else None,ranked_candidates=[{'symbol':x[1],'direction':x[2],'score':x[0]} for x in sorted(candidates,key=lambda x:(-x[0],x[1]))],last_reason=reason)
        action='ENTER_'+chosen[1] if chosen else 'EXIT' if any(p['symbol']==sym for k,p in s['positions'].items() if k in s['exit_requests']) else 'MAINTAIN' if any(p['symbol']==sym for p in s['positions'].values()) else 'NO_TRADE'
        m.update(last_action=action,last_decision_ms=now,decision_reason=reason)
        self.audit('DECISION',symbol=sym,selected_action=action,selected_symbol=chosen[0] if chosen else None,reason=reason,strategy_validated=False)

    def fill_conveyor(self,sym,q,spec,data):
        s=self.state;now=s['now_ms']
        depth={side:D(data[side+'_base_size']) if data else Z for side in ('bid','ask')}
        for key,p in sorted(list(s['positions'].items())):
            if p['symbol']!=sym:continue
            sign=1 if p['direction']=='LONG' else -1;side='bid' if sign==1 else 'ask'
            protection=p['protection']
            if protection['state']=='REQUESTED' and data and self.seq>protection['requested_seq'] and now-protection['requested_ms']>=self.policy.minimum_entry_latency_ms and q['observed_ms']>=protection['requested_ms']+self.policy.minimum_entry_latency_ms and int(q['timestamp'])>p['entry_provider_ms']:
                protection.update(state='MODELED_ACKED',ack_seq=self.seq,ack_ms=now,covered_quantity=p['quantity_contracts'])
                self.audit('PROTECTION_MODELED_ACK',position_id=p['id'],quantity=p['quantity_contracts'],exchange_ack=False)
            if protection['state']=='FAILED':self.request(key,'PROTECTION_FAILURE')
            if sign*(D(q[side])-D(p['planned_stop_mid']))<=0:self.request(key,'STOP')
            elif sign*(D(q[side])-D(p['planned_target_mid']))>=0 and protection['state']=='MODELED_ACKED':self.request(key,'TARGET')
            req=s['exit_requests'].get(key)
            if not req or not spec or digest(spec['rules'])!=p['rules_hash']:continue
            later=self.seq>req['requested_seq'] and now-req['requested_ms']>=self.policy.minimum_entry_latency_ms and q['observed_ms']>=req['requested_ms']+self.policy.minimum_entry_latency_ms and int(q['timestamp'])>req['provider_ms']
            if not later:continue
            # A target touch is not a limit fill; stop can supersede a resting TP.
            campaign=s['campaigns'][p['campaign_id']]
            target_feasible=bool(data) and D(campaign['realized_net'])+self.close_math(p,q,now,spec)['net']>=D(campaign['allocated'])*D(self.portfolio.campaign_target_fraction)
            if req['reason'] in ('TARGET','CAMPAIGN_TARGET') and (sign*(D(q[side])-D(p['planned_target_mid']))<0 or not target_feasible):
                self.audit('TP_NOT_FILLED',position_id=p['id'],reason='quote_below_net_target');continue
            step=D(spec['rules']['step_size']);unit=D(p['contract_multiplier']);original=D(p['quantity_contracts'])
            quantity=min(original,(depth[side]/unit/step).to_integral_value(rounding=ROUND_FLOOR)*step)
            if quantity<=0:self.unresolved_leg(key,'insufficient_verified_partial_exit_depth');continue
            ratio=quantity/original
            piece={**p,'quantity_contracts':str(quantity),'entry_notional_usdt':str(D(p['entry_price'])*unit*quantity),
                   'entry_fee_usdt':str(D(p['entry_fee_usdt']) if quantity==original else cash(D(p['entry_fee_usdt'])*ratio))}
            amounts=self.close_math(piece,q,now,spec);depth[side]-=quantity*unit
            done={**piece,'id':p['id']+':slice:'+str(self.seq),'position_id':p['id'],'exit_reason':req['reason'],
                  'exit_received_ms':now,'exit_source_seq':self.seq,'exit_provider_ms':int(q['timestamp']),
                  'exit_wire_received_ms':q['observed_ms'],'exit_request_ms':req['requested_ms'],
                  'exit_observed_bid':q['bid'],'exit_observed_ask':q['ask'],'exit_quote':q[side],
                  'exit_price':amounts['exit_price'],'exit_fee_usdt':str(amounts['exit_fee']),
                  'modeled_carry_usdt':str(amounts['carry']),'gross_pnl_usdt':str(amounts['gross']),
                  'net_pnl_usdt':str(amounts['net']),'holding_ms':now-p['entry_received_ms']}
            done['cost_attribution']=position_costs(done,carry_rate=self.policy.modeled_carry_8h_rate)
            self.db.execute('INSERT INTO closed_positions VALUES (?,?)',(done['id'],canonical(done)))
            self.add('cash',amounts['net_after_exit_only']);self.add('fees',amounts['exit_fee']);self.add('exit_fees',amounts['exit_fee']);self.add('carry',amounts['carry']);self.add('realized',amounts['net'])
            campaign=s['campaigns'][p['campaign_id']];campaign['realized_net']=str(D(campaign['realized_net'])+amounts['net'])
            leg_net=D(p.get('closed_slice_net','0'))+amounts['net']
            self.queue_model_cash(p['campaign_id'],gross=amounts['gross'],fees=amounts['exit_fee'],carry=amounts['carry'],complete=quantity==original,phase='exit')
            if quantity==original:
                del s['positions'][key];s['exit_requests'].pop(key,None);campaign['closed_legs'].append(p['id'])
                summary=s['closed_summary'];summary['count']+=1
                if leg_net>0:summary['wins']+=1;summary['profit']=str(D(summary['profit'])+leg_net)
                elif leg_net<0:summary['losses']+=1;summary['loss']=str(D(summary['loss'])-leg_net)
                s['cooldowns'][sym]=now+self.portfolio.cooldown_ms
                self.audit('CLOSED',position_id=p['id'],net_pnl=str(leg_net),reason=req['reason']);self.settle(campaign)
            else:
                remaining=original-quantity;p['quantity_contracts']=str(remaining)
                p['entry_fee_usdt']=str(D(p['entry_fee_usdt'])-D(piece['entry_fee_usdt']))
                p['entry_notional_usdt']=str(D(p['entry_price'])*unit*remaining)
                for field in ('margin_reserved_usdt','planned_loss_usdt','current_planned_loss_usdt'):
                    if field in p:p[field]=str(D(p[field])*(1-ratio))
                p['closed_slice_net']=str(leg_net);p['protection']['covered_quantity']=str(remaining)
                s.setdefault('conveyor',{}).setdefault('partial_exits',0);s['conveyor']['partial_exits']+=1
                self.audit('PARTIAL_EXIT',position_id=p['id'],filled=str(quantity),remaining=str(remaining),net_pnl=str(amounts['net']))
        for key,intent in sorted(list(s['pending_entries'].items())):
            if intent['symbol']!=sym:continue
            if any(p['protection']['state']!='MODELED_ACKED' for p in s['positions'].values()):continue
            if not (self.seq>intent['signal_seq'] and now-intent['signal_ms']>=self.policy.minimum_entry_latency_ms and int(q['timestamp'])>intent['provider_ms'] and q['observed_ms']>=intent['signal_ms']+self.policy.minimum_entry_latency_ms):continue
            del s['pending_entries'][key]
            plan,reason=self.plan(sym,intent['direction'],q)
            if plan and (plan['leverage']>intent['leverage'] or D(plan['quantity_contracts'])>D(intent['quantity_contracts'])):plan=None;reason='intent_cannot_increase_leverage_or_size'
            if not spec or digest(spec['rules'])!=intent['rules_hash']:plan=None;reason='changed_entry_rules'
            mid=(D(q['bid'])+D(q['ask']))/2
            if abs(mid-D(intent['signal_mid']))/D(intent['signal_mid'])*10000>D(self.policy.maximum_entry_drift_bps):plan=None;reason='entry_drift'
            if not plan:
                s['pending_entries'][key]=intent;self.cancel(key,reason);continue
            side='ask' if intent['direction']=='LONG' else 'bid';unit=D(plan['contract_multiplier']);step=D(spec['rules']['step_size'])
            desired=D(plan['quantity_contracts']);quantity=min(desired,(depth[side]/unit/step).to_integral_value(rounding=ROUND_FLOOR)*step)
            if quantity<D(spec['rules']['min_qty']) or quantity*unit*D(plan['entry_price'])<D(spec['rules']['min_notional']):
                s['pending_entries'][key]=intent;self.cancel(key,'IOC_no_admissible_displayed_fill');continue
            ratio=quantity/desired
            allocation=D(intent['allocation_budget_usdt'])*quantity/D(intent['quantity_contracts'])
            notional=D(plan['entry_price'])*unit*quantity;entry_fee=cash(notional*D(plan['fee_rate']),True)
            plan.update(quantity_contracts=str(quantity),entry_notional_usdt=str(notional),entry_fee_usdt=str(entry_fee),
                margin_reserved_usdt=str(notional/D(plan['leverage'])),planned_loss_usdt=str(D(plan['planned_loss_usdt'])*ratio),allocation_budget_usdt=str(allocation))
            if D(plan['planned_loss_usdt'])>allocation*D(self.portfolio.campaign_loss_fraction):
                s['pending_entries'][key]=intent;self.cancel(key,'partial_IOC_full_cost_risk_exceeds_scaled_allocation');continue
            # Reprice the scaled allocation after a partial IOC, never fake the tail.
            carry=cash(notional*D(self.policy.modeled_carry_8h_rate)*D(self.policy.maximum_holding_ms)/28800000,True)
            target=target_price(entry=plan['entry_price'],units=unit*quantity,entry_fee=entry_fee,allocation=allocation,
                fee=plan['fee_rate'],carry=carry,side=intent['direction'],target_fraction=self.portfolio.campaign_target_fraction)
            sign=1 if intent['direction']=='LONG' else -1
            plan['planned_target_mid']=str(target/(1-D(sign)*D(self.policy.adverse_slippage_bps)/10000))
            plan['planned_target_net_usdt']=str(allocation*D(self.portfolio.campaign_target_fraction))
            pos={**plan,'id':'position:'+intent['id'],'campaign_id':intent['campaign_id'],'symbol':sym,'direction':intent['direction'],
                 'rules_hash':intent['rules_hash'],'signal_received_ms':intent['signal_ms'],'entry_received_ms':now,
                 'entry_source_seq':self.seq,'entry_provider_ms':int(q['timestamp']),'entry_wire_received_ms':q['observed_ms'],
                 'entry_observed_bid':q['bid'],'entry_observed_ask':q['ask'],'last_mark':str(-entry_fee),'last_mark_ms':now,'unresolved':None,
                 'protection':{'state':'REQUESTED','requested_seq':self.seq,'requested_ms':now,'covered_quantity':'0','kind':'MODELED_ISOLATED_STOP_NOT_EXCHANGE_ACK'}}
            campaign=s['campaigns'][intent['campaign_id']]
            campaign['allocated']=str(D(campaign['allocated'])-D(intent['allocation_budget_usdt'])+allocation)
            campaign['filled_leg_count']+=1;s['positions'][key]=pos
            self.add('cash',-entry_fee);self.add('fees',entry_fee);self.add('entry_fees',entry_fee);depth[side]-=quantity*unit
            self.queue_model_cash(pos['campaign_id'],gross=Z,fees=entry_fee,carry=Z,complete=False,phase='entry')
            conveyor=s.setdefault('conveyor',{});conveyor['entries']=conveyor.get('entries',0)+1
            if quantity<D(intent['quantity_contracts']):
                conveyor['partial_entries']=conveyor.get('partial_entries',0)+1
                self.audit('PARTIAL_ENTRY_IOC',position_id=pos['id'],filled=str(quantity),canceled_remainder=str(D(intent['quantity_contracts'])-quantity))
            self.audit('OPENED',position_id=pos['id'],symbol=sym,positionSide=pos['direction'],leverage=pos['leverage'],protection='REQUESTED')
        self.choose_conveyor(sym,q)
