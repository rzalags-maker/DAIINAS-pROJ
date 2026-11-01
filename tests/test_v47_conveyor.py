"""Synthetic market/account event streams. Not real-market P&L evidence."""
from decimal import Decimal as D
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from daiinas.adaptive_execution import select_leverage
from daiinas.risk import ContractRules
from daiinas.portfolio_paper import PortfolioLedger
from daiinas.account_capital import mock_snapshot
from daiinas.continuous_store import SourceJournal
from daiinas.continuous import replay
from daiinas.market_pulse import rank_pulse
import test_continuous_paper as f
import test_universe as u


def market_state(side='LONG',move=400):
    sign=1 if side=='LONG' else -1
    return dict(data_fresh=True,regime='UP_TREND' if sign==1 else 'DOWN_TREND',trend_persistence=.9,
                volatility_bps=2,momentum_bps=sign*move,trend_bps=sign*move,cvd_ratio=sign*.8)


class LeverageTests(unittest.TestCase):
    def select(self,side='LONG',margin='20',**changes):
        args=dict(rules=ContractRules('S','1','100000','1','.0001','0','1'),
                  quote={'bid':'1','ask':'1.0002'},side=side,allocation='25',margin_budget=margin,risk_budget='.125',
                  fee_rate='.0006',market=market_state(side),max_leverage='5')
        args.update(changes);return select_leverage(**args)

    def test_every_leverage_both_sides_smallest_feasible_with_resized_stop(self):
        for side in ('LONG','SHORT'):
            for expected,margin in ((1,'20'),(2,'10'),(3,'5'),(4,'4'),(5,'3')):
                with self.subTest(side=side,leverage=expected):
                    result=self.select(side,margin)
                    self.assertIsNotNone(result.selected,result.payload());p=result.selected
                    self.assertEqual(p['leverage'],expected,result.payload());self.assertEqual(len(result.alternatives),5)
                    self.assertLessEqual(D(p['planned_loss_usdt']),D('.125'))
                    self.assertLessEqual(D(p['margin_reserved_usdt'])+2*D(p['entry_fee_usdt']),D(margin))
                    self.assertLessEqual(D(p['required_move_bps']),D(p['observed_move_capacity_bps']))
                    self.assertTrue(result.alternatives[4]['full_allocation_rejected'])
                    self.assertLess(D(p['entry_notional_usdt']),D(25)*expected)
                    self.assertEqual(D(p['planned_target_net_usdt']),D('.50'))

    def test_no_leverage_rescue_no_forecast_no_martingale(self):
        for kwargs in ({'margin_budget':'.1'},{'fee_rate':'.05'},
                       {'market':market_state(move=10)},{'market':{**market_state(),'data_fresh':False}},
                       {'market':{**market_state(),'volatility_bps':30}},
                       {'market':{**market_state(),'regime':'RANGE'}},
                       {'max_leverage':'2','margin_budget':'3'}, {'risk_budget':'.0001'}):
            with self.subTest(kwargs=kwargs):self.assertIsNone(self.select(**kwargs).selected)
        before=self.select();after=self.select(risk_budget='.06')
        if after.selected:self.assertLessEqual(D(after.selected['quantity_contracts']),D(before.selected['quantity_contracts']))


class WholeMarketTests(unittest.TestCase):
    def test_whole_catalog_ranks_both_directions_not_gainers_or_volume_only(self):
        from daiinas.universe import scan,Policy
        symbols=('UP','DOWN','RANGE','SPIKE','ILLIQUID');previous=None
        for n in range(6):
            now=u.NOW+n*60000
            contracts=[u.contract(s,turnover=10 if s=='ILLIQUID' else 10_000_000_000 if s=='RANGE' else 20_000_000) for s in symbols]
            ticks=[]
            for sym in symbols:
                price=(1+.003*n if sym=='UP' else 1-.003*n if sym=='DOWN' else 1.5 if sym=='SPIKE' and n==5 else 1)
                ticks.append(u.ticker(sym,bid=price,ask=price+.0002,ts=now))
            report=scan(contracts,ticks,now_ms=now,equity=150,policy=Policy())
            result=rank_pulse(report,contracts,ticks,now=now,previous=previous)
            previous=result['whole_market_pulse']['markets']
        pulse=result['whole_market_pulse'];self.assertEqual(pulse['catalog_count'],5)
        self.assertEqual(previous['UP']['action'],'LONG');self.assertEqual(previous['DOWN']['action'],'SHORT')
        self.assertEqual(previous['RANGE']['action'],'NO_TRADE');self.assertEqual(previous['SPIKE']['regime'],'DISLOCATED')
        self.assertEqual(previous['ILLIQUID']['action'],'NO_TRADE')
        self.assertEqual(set(pulse['ranking'][:2]),{'UP','DOWN'})
        self.assertTrue(all(m['order_flow_status']=='NOT_OBSERVED_IN_SUMMARY' for m in previous.values()))


class ConveyorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.source=SourceJournal(self.root/'source.sqlite3');self.paper=None;self.idx=0
    def tearDown(self):
        if self.paper:self.paper.close()
        self.source.close();self.tmp.cleanup()
    def send(self,t,*packets):
        with patch('daiinas.continuous_store.clock_ms',return_value=t):rows=self.source.append(packets)
        self.paper.apply(rows);return rows
    def start(self,capital='450',symbols=('UPUSDTM','DOWNUSDTM'),free=None,**options):
        snap=mock_snapshot(cash=capital,free_margin=free,timestamp_ms=0,snapshot_id='opening')
        self.paper=PortfolioLedger.from_account_snapshot(self.root/'paper.sqlite3',self.source.source_id,snap,
            strategy_version='v47',paper_settlement=True,mode='M1',cooldown_ms=30000,**options)
        self.pp,self.policy=self.paper.portfolio,self.paper.policy
        self.send(0,('CONTROL','opening',{'action':'account-snapshot','snapshot':snap.payload()}))
        extra={s:{**f.specs(s)[s],'max_leverage':'5','margin_mode':'ISOLATED'} for s in symbols}
        self.send(0,f.scan(extra=extra));self.symbols=symbols
    def heartbeat(self,t):self.send(t,('CONTROL','heartbeat:'+str(t),{'action':'paper-account-heartbeat'}))
    def quote(self,sym,t,bid,ask=None,bid_size=10000,ask_size=1000):
        ask=bid+.0002 if ask is None else ask;self.idx+=1
        self.send(t,f.market('level2',t,self.idx,sym=sym,bid=bid,ask=ask,bid_size=bid_size,ask_size=ask_size))
        return self.send(t,f.market('tickerV2',t,self.idx,sym=sym,bid=bid,ask=ask,bid_size=bid_size,ask_size=ask_size))
    def train(self,symbols=None,n=17,start=100,entry_depth=None,price=None):
        symbols=self.symbols if symbols is None else symbols
        for i in range(n):
            t=start+i*1000;self.heartbeat(t)
            for j,sym in enumerate(symbols):
                side='sell' if sym.startswith('DOWN') else 'buy';bid=price(i,j,sym) if price else (1.003 if side=='buy' else .997)**i
                ts=t+j*10
                for k in range(3):
                    self.idx+=1;self.send(ts,f.market('execution',ts,self.idx,sym=sym,side=side))
                self.quote(sym,ts,bid,bid_size=1000 if side=='sell' else 10000,ask_size=10000 if side=='sell' else 1000)
            for delay in (100,250):
                for j,sym in enumerate(symbols):
                    sell=sym.startswith('DOWN');bid=price(i,j,sym) if price else (.997 if sell else 1.003)**i
                    self.quote(sym,t+delay+j*10,bid,bid_size=(entry_depth if entry_depth is not None and sell and delay==100 else 1000) if sell else 10000,ask_size=10000 if sell else (entry_depth if entry_depth is not None and delay==100 else 1000))
        return start+(n-1)*1000+len(symbols)*10+300
    def reopen(self):
        before=self.paper.report();self.paper.close();self.paper=PortfolioLedger(self.root/'paper.sqlite3',self.source.source_id,self.policy,portfolio=self.pp);self.assertEqual(before,self.paper.report())
    def test_auto_independent_long_short_protection_and_restart_replay(self):
        self.start();t=self.train()
        positions=self.paper.state['positions'];self.assertTrue(positions,self.paper.report()['conveyor'])
        self.assertIn('UPUSDTM|LONG',positions);self.assertIn('DOWNUSDTM|SHORT',positions)
        self.assertTrue(all(p['leverage'] in (1,2,3,4,5) for p in positions.values()))
        self.assertTrue(all(p['protection']['state']=='MODELED_ACKED' for p in positions.values()))
        self.assertEqual(D(self.paper.state['account_capital']['cash']),D(self.paper.state['cash']))
        self.assertEqual(D(self.paper.state['cash']),D(self.pp.initial_capital)-D(self.paper.state['entry_fees']))
        self.reopen();self.paper.invariant()
        replica=replay([self.source.path],self.root/'replay.sqlite3',self.policy,ledger_factory=PortfolioLedger,ledger_options={'portfolio':self.pp})
        self.assertEqual(replica,self.paper.report());self.assertFalse(replica['live_orders_enabled'])
    def test_tp_touch_nonfill_then_stop_partial_loss_is_exactly_once(self):
        self.start(symbols=('UPUSDTM',));t=self.train();key='UPUSDTM|LONG';p=self.paper.state['positions'][key]
        target=float(p['planned_target_mid']);stop=float(p['planned_stop_mid']);original=D(p['quantity_contracts'])
        self.quote('UPUSDTM',t+200,target+.001)
        self.assertIn(key,self.paper.state['exit_requests'])
        self.quote('UPUSDTM',t+400,target-.001)
        self.assertIn(key,self.paper.state['positions']);self.assertGreater(self.paper.state['counts'].get('TP_NOT_FILLED',0),0)
        self.quote('UPUSDTM',t+600,stop-.001,bid_size=2,ask_size=1000)
        self.assertEqual(self.paper.state['exit_requests'][key]['reason'],'STOP')
        self.quote('UPUSDTM',t+800,stop-.001,bid_size=2,ask_size=1000)
        self.assertLess(D(self.paper.state['positions'][key]['quantity_contracts']),original)
        self.reopen()
        rows=self.quote('UPUSDTM',t+1000,stop-.001,bid_size=10000)
        self.paper.apply(rows)
        self.assertNotIn(key,self.paper.state['positions']);self.assertLess(D(self.paper.state['realized']),0)
        self.assertEqual(self.paper.state['closed_summary']['count'],1)
        self.assertEqual(self.paper.state['counts']['REALIZED_NET_TRADE'],1)
        self.assertEqual(self.paper.state['counts']['INITIAL_FUNDING'],1)
        self.assertEqual(self.paper.ladder().realized_net,D(self.paper.state['realized']))
        self.paper.invariant();self.reopen()
    def test_partial_ioc_entry_cancels_tail_and_accounts_actual_allocated_capital(self):
        self.start(symbols=('UPUSDTM',));t=self.train(entry_depth=2)
        p=self.paper.state['positions']['UPUSDTM|LONG']
        self.assertEqual(D(p['quantity_contracts']),2)
        self.assertGreater(self.paper.state['counts'].get('PARTIAL_ENTRY_IOC',0),0)
        self.assertFalse(self.paper.state['pending_entries'])
        self.assertLessEqual(D(p['planned_loss_usdt']),D(p['allocation_budget_usdt'])*D('.005'))
        target=float(p['planned_target_mid']);self.quote('UPUSDTM',t+200,target+.002);self.quote('UPUSDTM',t+400,target+.002)
        self.assertFalse(self.paper.state['positions']);self.assertGreater(D(self.paper.state['realized']),0)
        self.assertEqual(self.paper.ladder().realized_net,D(self.paper.state['realized']))
        self.assertEqual(self.paper.state['closed_summary']['count'],1);self.reopen()

    def test_net_target_settles_once_then_discovers_a_new_token(self):
        self.start(symbols=('UPUSDTM','NEXTUSDTM'));t=self.train(symbols=('UPUSDTM',))
        p=self.paper.state['positions']['UPUSDTM|LONG'];allocation=D(p['allocation_budget_usdt']);target=float(p['planned_target_mid'])
        self.quote('UPUSDTM',t+200,target+.002);self.quote('UPUSDTM',t+400,target+.002)
        self.assertFalse(self.paper.state['positions']);self.assertGreaterEqual(D(self.paper.state['realized']),allocation*D('.02'))
        self.assertEqual(self.paper.state['counts']['REALIZED_NET_TRADE'],1)
        self.train(symbols=('NEXTUSDTM',),start=t+1000)
        self.assertIn('NEXTUSDTM|LONG',self.paper.state['positions'])
        self.assertEqual(self.paper.state['counts']['INITIAL_FUNDING'],1);self.reopen()
        replica=replay([self.source.path],self.root/'replay.sqlite3',self.policy,ledger_factory=PortfolioLedger,ledger_options={'portfolio':self.pp})
        self.assertEqual(replica,self.paper.report())

    def test_ten_correlated_positions_share_margin_and_gross_risk(self):
        symbols=tuple('UP'+str(i)+'USDTM' for i in range(10));self.start('400',symbols)
        t=self.train(n=15)
        for round in range(10):
            base=t+round*250
            self.heartbeat(base)
            for j,sym in enumerate(symbols):self.quote(sym,base+j*10,1.003**14)
        self.assertEqual(len(self.paper.state['positions']),10,self.paper.state['reason_counts'])
        self.assertLessEqual(self.paper.planned(),D(self.paper.account_limits()['active_budget'])*D('.01'))
        self.assertLessEqual(self.paper.planned(),D(self.paper.account_limits()['active_budget'])*D('.005'))
        self.assertLessEqual(self.paper.reserved(),D(self.paper.account_limits()['active_budget']))
        self.assertTrue(all(p['protection']['state']=='MODELED_ACKED' for p in self.paper.state['positions'].values()))
        self.reopen();self.paper.invariant()

    def test_ten_independent_mixed_directions_remain_inside_shared_account_risk(self):
        import math
        from daiinas.market_intelligence import correlation
        symbols=tuple(('UP' if n%2==0 else 'DOWN')+str(n)+'USDTM' for n in range(10))
        price=lambda i,j,sym:1+(1 if sym.startswith('UP') else -1)*.003*i+.001*math.sin(i*(j+1))
        self.start('400',symbols);t=self.train(n=15,price=price)
        for round in range(10):
            base=t+round*250;self.heartbeat(base)
            for j,sym in enumerate(symbols):
                sell=sym.startswith('DOWN')
                self.quote(sym,base+j*10,price(14,j,sym),bid_size=1000 if sell else 10000,ask_size=10000 if sell else 1000)
        self.assertEqual(len(self.paper.state['positions']),10,self.paper.state['reason_counts'])
        histories=[self.paper.state['market_states'][sym]['history'] for sym in symbols]
        self.assertLess(abs(correlation(histories[0],histories[1])),.85)
        self.assertEqual({p['direction'] for p in self.paper.state['positions'].values()},{'LONG','SHORT'})
        self.assertLessEqual(self.paper.planned(),D(self.paper.account_limits()['active_budget'])*D('.01'))
        self.reopen()

    def test_per_position_x5_is_not_the_snapshot_static_leverage(self):
        self.start(symbols=('UPUSDTM',),free='3');self.train(n=18)
        p=self.paper.state['positions']['UPUSDTM|LONG']
        self.assertEqual(p['leverage'],5)
        self.assertEqual(self.paper.state['account_capital']['snapshot']['leverage'],'2')
        self.assertEqual(D(p['margin_reserved_usdt']),D(p['entry_notional_usdt'])/5)
        self.assertLessEqual(D(p['planned_loss_usdt']),D(p['allocation_budget_usdt'])*D('.005'))
        self.reopen()

    def test_contract_leverage_reduction_blocks_entries_and_preserves_exit_monitoring(self):
        self.start(symbols=('UPUSDTM',),free='3');t=self.train(n=18)
        key='UPUSDTM|LONG';self.assertEqual(self.paper.state['positions'][key]['leverage'],5)
        extra={'UPUSDTM':{**f.specs('UPUSDTM')['UPUSDTM'],'max_leverage':'2','margin_mode':'ISOLATED'}}
        self.send(t+100,f.scan(t+100,extra=extra))
        self.assertIn(key,self.paper.state['positions']);self.assertEqual(self.paper.state['exit_requests'][key]['reason'],'CONTRACT_CHANGED')
        self.assertFalse(self.paper.state['equity_verified'])
        self.reopen()

    def test_close_same_timestamp_as_snapshot_defers_reconciliation_without_reseeding(self):
        self.start('60',symbols=('UPUSDTM',));t=self.train();p=self.paper.state['positions']['UPUSDTM|LONG']
        target=float(p['planned_target_mid']);self.quote('UPUSDTM',t+200,target+.002)
        self.heartbeat(t+400);self.quote('UPUSDTM',t+400,target+.002)
        self.assertTrue(self.paper.state['paper_settlements'])
        self.assertEqual(self.paper.account_limits()['earned_early_ports'],1)
        self.send(t+401,('CLOCK','settlement-clock',{}));self.assertFalse(self.paper.state['paper_settlements'])
        self.assertEqual(self.paper.account_limits()['earned_early_ports'],2)
        self.assertEqual(self.paper.state['counts']['INITIAL_FUNDING'],1);self.reopen()

    def test_sigkill_during_auto_settlement_rolls_back_fill_and_replays_once(self):
        import signal,subprocess,sys
        from dataclasses import asdict
        self.start('60',symbols=('UPUSDTM',));t=self.train();p=self.paper.state['positions']['UPUSDTM|LONG']
        target=float(p['planned_target_mid']);self.quote('UPUSDTM',t+200,target+.002)
        self.idx+=1
        packets=[f.market(ch,t+400,self.idx,sym='UPUSDTM',bid=target+.002,ask=target+.0022,bid_size=10000,ask_size=1000) for ch in ('level2','tickerV2')]
        with patch('daiinas.continuous_store.clock_ms',return_value=t+400):self.source.append(packets)
        self.paper.close();self.paper=None
        code="""
import sys,json,os,signal
from pathlib import Path
from daiinas.continuous_store import SourceJournal
from daiinas.portfolio_paper import PortfolioLedger
from daiinas.paper_micro import PaperPolicy
root=Path(sys.argv[1]);src=SourceJournal(root/'source.sqlite3')
p=PortfolioLedger(root/'paper.sqlite3',src.source_id,PaperPolicy(**json.loads(sys.argv[3])),portfolio=json.loads(sys.argv[2]))
old=p.audit
def audit(action,**kw):
 old(action,**kw)
 if action=='REALIZED_NET_TRADE':os.kill(os.getpid(),signal.SIGKILL)
p.audit=audit
p.apply(src.after(p.state['cursor']))
"""
        result=subprocess.run([sys.executable,'-c',code,str(self.root),json.dumps(asdict(self.pp)),json.dumps(asdict(self.policy))],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,-signal.SIGKILL,result.stderr)
        self.paper=PortfolioLedger(self.root/'paper.sqlite3',self.source.source_id,self.policy,portfolio=self.pp)
        self.assertEqual(self.paper.account_limits()['earned_early_ports'],1)
        rows=self.source.after(self.paper.state['cursor']);self.paper.apply(rows);self.paper.apply(rows)
        self.assertEqual(self.paper.account_limits()['earned_early_ports'],2)
        self.assertEqual(self.paper.state['counts']['REALIZED_NET_TRADE'],1)
        self.assertEqual(self.paper.state['closed_summary']['count'],1);self.paper.invariant()

    def test_partial_winning_target_cannot_hide_residual_gap_loss_or_earn_win(self):
        self.start('60',symbols=('UPUSDTM',));t=self.train();p=self.paper.state['positions']['UPUSDTM|LONG']
        target=float(p['planned_target_mid'])+.01;stop=float(p['planned_stop_mid'])-.3
        self.quote('UPUSDTM',t+200,target,bid_size=2);self.quote('UPUSDTM',t+400,target,bid_size=2)
        self.assertGreater(D(self.paper.state['realized']),0)
        self.assertIn('UPUSDTM|LONG',self.paper.state['positions'])
        self.assertEqual(self.paper.account_limits()['earned_early_ports'],1)
        self.assertEqual(self.paper.ladder().realized_net,0)
        self.assertEqual(D(self.paper.state['cash']),D(self.paper.state['account_capital']['cash']))
        self.quote('UPUSDTM',t+600,stop);self.quote('UPUSDTM',t+800,stop)
        self.assertFalse(self.paper.state['positions']);self.assertLess(self.paper.ladder().realized_net,0)
        self.assertEqual(self.paper.account_limits()['earned_early_ports'],1)
        self.assertTrue(self.paper.state['halted']);self.assertEqual(self.paper.state['counts']['REALIZED_NET_TRADE'],1)
        self.reopen()

    def test_failure_of_modeled_protection_blocks_new_entries_and_exits_safely(self):
        self.start(symbols=('UPUSDTM',));t=self.train();key='UPUSDTM|LONG'
        self.send(t+100,('CONTROL','protection-failed',{'action':'protection-failure','position_key':key}))
        self.assertEqual(self.paper.state['positions'][key]['protection']['state'],'FAILED')
        self.assertEqual(self.paper.state['exit_requests'][key]['reason'],'PROTECTION_FAILURE')
        p=self.paper.state['positions'][key];self.quote('UPUSDTM',t+300,float(p['entry_price']))
        self.assertNotIn(key,self.paper.state['positions']);self.assertFalse(self.paper.state['pending_entries'])
    def test_no_trade_while_market_unknown_or_paused(self):
        self.start();self.heartbeat(100);self.quote('UPUSDTM',100,1)
        self.assertFalse(self.paper.state['pending_entries']);self.assertFalse(self.paper.state['positions'])
        self.send(101,('CONTROL','pause',{'action':'pause'}));self.train(start=200)
        self.assertFalse(self.paper.state['positions']);self.reopen();self.assertTrue(self.paper.state['paused'])

    def native_exit(self,p,t,*,quantity=None,fill_id='native-1',sibling=None,liquidity='TAKER',fee='.003'):
        quantity=D(p['quantity_contracts']) if quantity is None else D(quantity);price=D(p['entry_price'])+D('.04')*(1 if p['direction']=='LONG' else -1)
        from daiinas.adaptive_execution import cash
        gross=cash((price-D(p['entry_price']))*D(p['contract_multiplier'])*quantity*(1 if p['direction']=='LONG' else -1))
        remaining=D(p['quantity_contracts'])-quantity
        return dict(source_kind='MOCK_NATIVE',fill_id=fill_id,order_id=p['protection']['order_ids']['target'],account_id=self.pp.funding['account_id'],
                    symbol=p['symbol'],position_side=p['direction'],timestamp_ms=t,price=str(price),quantity=str(quantity),fee=fee,fee_currency='USDT',
                    liquidity=liquidity,funding='0',phase='EXIT',leverage=p['leverage'],authority=dict(snapshot_id='auth:'+fill_id,timestamp_ms=t,complete=True,
                    position_quantity=str(remaining),sibling_status=sibling or ('CANCELED' if remaining==0 else 'ACKED'),reduce_only=True,
                    cash=str(D(self.paper.state['cash'])+gross-D(fee)),free_margin='0',unknown_orders=[],order_status='FILLED' if remaining==0 else 'PARTIAL',protected_quantity=str(remaining)))

    def test_five_hour_expiry_preserves_protection_and_requires_explicit_restart(self):
        self.start('60',symbols=('UPUSDTM',));t=self.train();s=self.paper.state
        deadline=s['session']['expires_ms'];funding=s['initial_funding'];p=next(iter(s['positions'].values()))
        self.send(deadline,('CLOCK','expire',{}));self.assertFalse(self.paper.session_armed())
        self.assertEqual(self.paper.session_status()['state'],'STOPPED_WITH_EXPOSURE')
        self.assertEqual(p['protection']['state'],'MODELED_ACKED');self.reopen()
        self.heartbeat(deadline+1);self.assertFalse(self.paper.session_armed())
        self.send(deadline+2,('CONTROL','new-session',{'action':'session-start','request_id':'second','actor':'test-owner'}))
        self.assertTrue(self.paper.session_armed());self.assertEqual(funding,s['initial_funding'])
        self.assertEqual(self.paper.report()['counts']['INITIAL_FUNDING'],1)

    def test_native_mock_offline_close_pending_sibling_duplicate_and_replay(self):
        self.start('60',symbols=('UPUSDTM',));t=self.train();p=next(iter(self.paper.state['positions'].values()))
        self.send(t+50,('CONTROL','stop-worker',{'action':'session-stop'}));self.reopen()
        packet=self.native_exit(p,t+100,sibling='UNKNOWN');self.send(t+100,('CONTROL','ws-match',{'action':'native-mock-fill','receipt':packet}))
        self.assertTrue(self.paper.state['positions']);self.assertTrue(self.paper.state['pending_native_receipts'])
        self.quote(p['symbol'],t+150,float(p['planned_stop_mid'])-.1)
        self.assertTrue(self.paper.state['positions']);self.assertEqual(self.paper.report()['closed_summary']['count'],0);self.reopen()
        packet['authority']['sibling_status']='CANCELED';packet['authority']['timestamp_ms']=t+200
        self.send(t+200,('CONTROL','rest-proof',{'action':'native-mock-fill','receipt':packet}))
        self.assertFalse(self.paper.state['positions']);self.assertFalse(self.paper.state['pending_native_receipts'])
        after=self.paper.state['cash'];self.reopen()
        self.send(t+300,('CONTROL','duplicate-ws',{'action':'native-mock-fill','receipt':packet}))
        self.assertEqual(self.paper.state['cash'],after);self.assertEqual(self.paper.report()['closed_summary']['count'],1)
        self.assertEqual(self.paper.session_status()['state'],'STOPPED_FLAT')
        self.assertEqual(self.paper.report()['counts']['INITIAL_FUNDING'],1)
        replica=replay([self.source.path],self.root/'native-replay.sqlite3',self.policy,ledger_factory=PortfolioLedger,ledger_options={'portfolio':self.pp})
        self.assertEqual(replica,self.paper.report())

    def test_native_partial_does_not_release_slot_and_actual_maker_fee_is_booked(self):
        self.start('60',symbols=('UPUSDTM',));t=self.train();p=next(iter(self.paper.state['positions'].values()));original=D(p['quantity_contracts'])
        packet=self.native_exit(p,t+100,quantity=2,liquidity='MAKER',fee='.0004')
        self.send(t+100,('CONTROL','partial-native',{'action':'native-mock-fill','receipt':packet}))
        self.assertEqual(len(self.paper.state['positions']),1);self.assertEqual(D(p['quantity_contracts']),original-2)
        self.assertEqual(self.paper.report()['closed_summary']['count'],0)
        self.assertFalse(self.paper.state['campaigns'][p['campaign_id']]['settled'])
        row=json.loads(self.paper.db.execute('SELECT payload FROM closed_positions').fetchone()[0])
        self.assertEqual(D(row['exit_fee_usdt']),D('.0004'));self.assertEqual(row['exit_liquidity'],'MAKER')
        self.assertEqual(D(self.paper.state['cash']),D(self.paper.state['account_capital']['cash']));self.reopen()

    def test_passive_entry_never_fills_on_quote_and_session_cancel_is_flat(self):
        self.start('60',symbols=('UPUSDTM',),entry_kind='POST_ONLY_LIMIT')
        t=self.train();s=self.paper.state
        self.assertTrue(s['pending_entries']);self.assertFalse(s['positions']);self.assertEqual(s['fees'],'0')
        self.send(s['session']['expires_ms'],('CLOCK','five-hours',{}))
        self.assertFalse(s['pending_entries']);self.assertEqual(self.paper.session_status()['state'],'STOPPED_FLAT')
        self.assertTrue(all(o['status']=='MODEL_CANCELED' for o in s['venue_orders'].values()))

    def test_passive_partial_entry_requires_tail_cancel_and_protection_reconciliation(self):
        self.start('60',symbols=('UPUSDTM',),entry_kind='POST_ONLY_LIMIT')
        t=self.train();intent=next(iter(self.paper.state['pending_entries'].values()));price=D(intent['entry_price']);fee='.0004'
        packet=dict(source_kind='MOCK_NATIVE',fill_id='maker-entry',order_id=intent['order_ids']['entry'],account_id=self.pp.funding['account_id'],
                    symbol=intent['symbol'],position_side=intent['direction'],timestamp_ms=t,price=str(price),quantity='2',fee=fee,fee_currency='USDT',
                    liquidity='MAKER',funding='0',phase='ENTRY',leverage=intent['leverage'],authority=dict(snapshot_id='entry-auth',timestamp_ms=t,complete=True,
                    position_quantity='2',sibling_status='ACKED',reduce_only=True,cash=str(D(self.paper.state['cash'])-D(fee)),free_margin='0',unknown_orders=[],order_status='PARTIAL',protected_quantity='2'))
        self.send(t,('CONTROL','partial-entry',{'action':'native-mock-fill','receipt':packet}));self.assertFalse(self.paper.state['positions'])
        packet['authority']['order_status']='CANCELED';packet['authority']['timestamp_ms']=t+100
        self.send(t+100,('CONTROL','canceled-tail',{'action':'native-mock-fill','receipt':packet}))
        self.assertEqual(len(self.paper.state['positions']),1);p=next(iter(self.paper.state['positions'].values()))
        self.assertEqual(p['quantity_contracts'],'2');self.assertEqual(D(p['entry_fee_usdt']),D(fee))
        self.assertFalse(self.paper.state['pending_entries']);self.assertFalse(self.paper.state['pending_native_receipts']);self.reopen()


class RuntimeBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_pipeline_bootstraps_explicit_mock_and_scans_full_catalog(self):
        from daiinas.v47 import configuration
        from daiinas.continuous import settings,account_factory
        from daiinas.continuous_paper import Pipeline
        from daiinas.universe import Policy
        from daiinas.universe_rotation import RotationPolicy
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);cfg=configuration('200','v47-unit-scenario',timestamp_ms=0)
            (root/'config.json').write_text(json.dumps(cfg));config,paper,shadow=settings(root/'config.json')
            pipeline=Pipeline(root/'source.sqlite3',root/'paper.sqlite3',paper,shadow,**account_factory(config))
            try:
                with patch('daiinas.continuous_store.clock_ms',return_value=u.NOW):await pipeline.poll_account()
                self.assertEqual((await pipeline.report())['account_status']['connector_status'],'RECONCILED_MOCK')
                for n in range(3):
                    now=u.NOW+n*60000
                    contracts=[u.contract(sym,maxLeverage=5,initialMargin=.2,maxOrderQty=100000) for sym in ('UPUSDTM','DOWNUSDTM','FLATUSDTM')]
                    ticks=[u.ticker('UPUSDTM',bid=1+n*.003,ask=1.0002+n*.003,ts=now),u.ticker('DOWNUSDTM',bid=1-n*.003,ask=1.0002-n*.003,ts=now),u.ticker('FLATUSDTM',ts=now)]
                    with patch('daiinas.continuous_store.clock_ms',return_value=now):
                        await pipeline.poll_account();await pipeline.scan(contracts,ticks,Policy(),RotationPolicy())
                result=await pipeline.report();pulse=result['whole_market_pulse']
                self.assertEqual(pulse['catalog_count'],3);self.assertEqual(pulse['markets']['UPUSDTM']['action'],'LONG')
                self.assertEqual(pulse['markets']['DOWNUSDTM']['action'],'SHORT')
                self.assertEqual(result['account_status']['funded_slot_ceiling'],6)
                self.assertEqual(result['actual_exchange_balance_status'],'NOT_CONNECTED')
                self.assertFalse(result['live_orders_enabled'])
                # Isolate the watch-capacity boundary: ten pinned risks must not
                # consume the separate bounded discovery shortlist.
                pins=[f'PIN{i}USDTM' for i in range(10)]
                pipeline.executor.submit(lambda:setattr(pipeline.ledger,'pins',lambda:pins)).result()
                now+=1000;names=pins+[f'NEW{i}USDTM' for i in range(5)]
                contracts=[u.contract(sym,maxLeverage=5,initialMargin=.2,maxOrderQty=100000) for sym in names]
                ticks=[u.ticker(sym,ts=now) for sym in names]
                with patch('daiinas.continuous_store.clock_ms',return_value=now):
                    await pipeline.poll_account();scanned=await pipeline.scan(contracts,ticks,Policy(),RotationPolicy())
                self.assertEqual(len(scanned['watch']['deep_symbols']),15)
                self.assertTrue(set(pins)<=set(scanned['watch']['deep_symbols']))
                self.assertFalse(scanned['watch']['capacity_exhausted'])
            finally:pipeline.close()

    async def test_subscription_rotation_releases_only_unpinned_before_provider_cap(self):
        from daiinas.continuous_stream import ContinuousObserver
        pins={f'PIN{i}USDTM' for i in range(10)}
        old={f'OLD{i}USDTM' for i in range(8)};new={f'NEW{i}USDTM' for i in range(8)}
        class PinnedReport:
            async def report(self):return {'pins':sorted(pins)}
        with tempfile.TemporaryDirectory() as directory:
            observer=ContinuousObserver(PinnedReport(),source_path=Path(directory)/'observer.sqlite3')
            commands=[];peaks=[]
            async def command(ws,symbol,action):
                commands.append((symbol,action));peaks.append(len(observer.active))
            async def restore(symbol):pass
            observer.command=command;observer.restore_book=restore
            observer.active=pins|old;observer.watch={'deep_symbols':sorted(pins|new)}
            observer.contracts={sym:ContractRules(sym,'1','1000','1','.0001','0','1') for sym in pins|new}
            try:
                await observer.reconcile(None)
                self.assertEqual(observer.active,pins|new)
                self.assertLessEqual(max(peaks),20)
                self.assertTrue(all(symbol not in pins for symbol,action in commands if action=='unsubscribe'))
                self.assertEqual(sum(action=='unsubscribe' for _,action in commands),8)
            finally:observer.close()


if __name__=='__main__':unittest.main()

class SniperFeeMatrixTests(unittest.TestCase):
    def test_forty_paths_both_directions_and_wider_price_stop_reduces_size(self):
        from daiinas.adaptive_execution import select_sniper
        for side in ('LONG','SHORT'):
            result=select_sniper(maker_fee_rate='.0002',rules=ContractRules('S','1','100000','1','.0001','0','1'),
                quote={'bid':'1','ask':'1.0002'},side=side,allocation='25',margin_budget='25',risk_budget='.125',
                fee_rate='.0006',market=market_state(side,600),max_leverage='5')
            self.assertEqual(len(result.alternatives),40);self.assertIsNotNone(result.selected)
            self.assertEqual(result.selected['liquidity_path'],'TAKER/TAKER')
            for path in ('TAKER/TAKER','MAKER/TAKER','TAKER/MAKER','MAKER/MAKER'):
                rows=[r for r in result.alternatives if r['liquidity_path']==path and r['leverage']==5]
                self.assertEqual(len(rows),2);self.assertTrue(all(r['full_allocation_rejected'] for r in rows))
                self.assertLessEqual(D(rows[1]['quantity_contracts']),D(rows[0]['quantity_contracts']))
            self.assertTrue(all(r['stop_liquidity']=='TAKER' for r in result.alternatives))
            self.assertTrue(all(D(r['planned_loss_usdt'])<=D('.125') for r in result.alternatives if r['accepted']))
    def test_inert_gateway_post_only_rejection_and_live_mutations_disabled(self):
        from daiinas.execution_boundary import InertOrderGateway
        gateway=InertOrderGateway();args=dict(account_id='MOCK',client_oid='x',symbol='XBTUSDTM',side='LONG',quantity='1',leverage=5,
            order_type='POST_ONLY_LIMIT',stop_price='.99',target_price='1.1',limit_price='1.01',best_bid='1',best_ask='1.01')
        self.assertTrue(gateway.preview(**args)['post_only_rejected'])
        args['order_type']='LIMIT';self.assertEqual(gateway.preview(**args)['prospective_liquidity'],'TAKER')
        for method in (gateway.place_order,gateway.cancel_order,gateway.modify_order):
            with self.assertRaises(PermissionError):method()
