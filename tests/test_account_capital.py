"""MOCK account observations only: financial correctness, never KuCoin evidence."""
from dataclasses import replace
from decimal import Decimal as D
import json
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from daiinas.account_capital import (FuturesAccountSnapshot,MockFuturesAdapter,NotConnectedAdapter,
    mock_snapshot,initial_account_state,reconcile,capital_status)
from daiinas.continuous_store import SourceJournal,digest
from daiinas.continuous import replay
from daiinas.portfolio_paper import PortfolioLedger
import test_continuous_paper as f
import test_portfolio_paper as portfolio_f


def trade(i,t,net,fees='.01'):
    return dict(id=i,account_id='MOCK-FUTURES',timestamp_ms=t,type='REALIZED_NET_TRADE',
                net=net,gross=str(D(net)+D(fees)),fees=fees,funding='0',campaign_id='campaign:'+i,campaign_complete=True)


def flow(i,t,net):
    return dict(id=i,account_id='MOCK-FUTURES',timestamp_ms=t,type='EXTERNAL_FLOW',net=net)


def exposure(id='external',margin='10',risk='.1',**changes):
    return dict(id=id,symbol='S0USDTM',margin=margin,planned_loss=risk,margin_mode='ISOLATED',leverage='2',position_side='LONG',campaign_id=None,protected=True) | changes


class AccountBoundaryTests(unittest.TestCase):
    def test_strict_scope_transport_precision_completeness_and_provenance(self):
        valid=mock_snapshot(cash='60',timestamp_ms=100,snapshot_id='s0')
        valid.validate(now_ms=100)
        for change in ({'account_mode':'UTA'},{'account_mode':'CLASSIC_SPOT'},
                       {'complete':False},{'complete':1},{'signature_validated':False},
                       {'transport_validated':False},{'timestamp_ms':True},{'timestamp_ms':-1},
                       {'source_kind':'AUTHENTICATED'}, {'free_margin':'61'},
                       {'equity':'100'}, {'settled_cash':60.0},{'leverage':'3'},
                       {'margin_mode':'CROSS'},{'liabilities':'-1'},
                       {'orders':None}, {'source_digest':'wrong'},
                       {'settled_cash':'60.0000000000000000001'}):
            obj={**valid.payload(),**change}
            if 'source_digest' not in change:obj['source_digest']=digest({k:v for k,v in obj.items() if k!='source_digest'})
            with self.subTest(change=change),self.assertRaises((ValueError,TypeError)):
                FuturesAccountSnapshot(**obj).validate(now_ms=100)
        for now in (99,15101):
            with self.assertRaises(ValueError):valid.validate(now_ms=now)
        with self.assertRaises(TypeError):FuturesAccountSnapshot(exchange='KUCOIN')
        self.assertIsNone(NotConnectedAdapter().snapshot())
        fake=MockFuturesAdapter([valid]);self.assertEqual(fake.snapshot(),valid);self.assertIsNone(fake.snapshot())

    def test_wallets_excluded_and_free_margin_not_double_deducted(self):
        # Funding=500, external wallet=300 are intentionally NOT in this scope.
        with self.assertRaises(TypeError):mock_snapshot(cash='60',timestamp_ms=1,snapshot_id='a',funding_wallet='500')
        snap=mock_snapshot(cash='60',timestamp_ms=1,snapshot_id='a',orders=[exposure('owned','10')],free_margin='40')
        state,_=reconcile(initial_account_state('60',snap.account_id),snap,now_ms=1,owned_ids={'owned'})
        limits=capital_status(state,now_ms=1)
        self.assertEqual(D(limits['current_futures_equity']),60)
        self.assertEqual(D(limits['marginal_margin']),40) # not 40-10
        self.assertEqual(D(capital_status(state,now_ms=1,local_margin=D(5))['marginal_margin']),35)
        self.assertLess(D(limits['risk_budget']),D('.6'))

    def test_event_replay_costs_external_flows_and_conflicts(self):
        state=initial_account_state('60','MOCK-FUTURES')
        a=mock_snapshot(cash='60',timestamp_ms=0,snapshot_id='a');state,_=reconcile(state,a,now_ms=0)
        b=mock_snapshot(cash='160',timestamp_ms=1,snapshot_id='b',cash_events=[flow('deposit',1,'100')])
        state,audit=reconcile(state,b,now_ms=1)
        self.assertEqual(state['unallocated'],'100');self.assertEqual(D(capital_status(state,now_ms=1)['active_budget']),60)
        self.assertEqual(audit[0]['event_type'],'EXTERNAL_FLOW')
        c=mock_snapshot(cash='159.8',timestamp_ms=2,snapshot_id='c',cash_events=[flow('deposit',1,'100'),trade('loss',2,'-.2')])
        state,_=reconcile(state,c,now_ms=2)
        self.assertEqual(D(capital_status(state,now_ms=2)['active_budget']),D('59.8'))
        again,records=reconcile(state,c,now_ms=2);self.assertEqual(again,state);self.assertEqual(records,[])
        for bad in (replace(c,source_digest='bad'),mock_snapshot(cash='159.9',timestamp_ms=3,snapshot_id='d'),
                    mock_snapshot(cash='159.8',timestamp_ms=3,snapshot_id='d',account_id='other'),
                    mock_snapshot(cash='159.8',timestamp_ms=3,snapshot_id='d',cash_events=[{**trade('loss',2,'-.3')}]),
                    mock_snapshot(cash='159.8',timestamp_ms=3,snapshot_id='d',cash_events=[{**trade('next',3,'0'),'fees':'-.01'}])):
            with self.assertRaises(ValueError):reconcile(state,bad,now_ms=3)
        with self.assertRaises(ValueError):reconcile(state,mock_snapshot(cash='49.8',timestamp_ms=4,snapshot_id='withdraw',cash_events=[flow('withdraw',4,'-110')]),now_ms=4)

    def test_separate_fees_funding_and_deposit_cannot_promote_slots(self):
        state=initial_account_state('60','MOCK-FUTURES')
        state,_=reconcile(state,mock_snapshot(cash='60',timestamp_ms=0,snapshot_id='a'),now_ms=0)
        events=[dict(id='fee',account_id='MOCK-FUTURES',timestamp_ms=1,type='CASH_COST',net='-.1',category='FEE'),
                dict(id='funding',account_id='MOCK-FUTURES',timestamp_ms=2,type='CASH_COST',net='-.2',category='FUNDING')]
        state,_=reconcile(state,mock_snapshot(cash='59.7',timestamp_ms=2,snapshot_id='b',cash_events=events),now_ms=2)
        self.assertEqual(D(capital_status(state,now_ms=2)['active_budget']),D('59.7'))
        state,_=reconcile(state,mock_snapshot(cash='159.7',timestamp_ms=3,snapshot_id='c',cash_events=[flow('external',3,'100')]),now_ms=3)
        self.assertEqual(capital_status(state,now_ms=3)['allowed_slots'],1)
        self.assertEqual(D(capital_status(state,now_ms=3)['unallocated_external']),100)

    def test_unprotected_and_still_open_campaign_cannot_unlock_win(self):
        state=initial_account_state('60','MOCK-FUTURES')
        snap=mock_snapshot(cash='60',timestamp_ms=0,snapshot_id='a',positions=[exposure('owned',protected=False,campaign_id='campaign:win')])
        state,_=reconcile(state,snap,now_ms=0,owned_ids={'owned'})
        self.assertEqual(capital_status(state,now_ms=0)['connector_status'],'UNPROTECTED_EXPOSURE')
        next_snapshot=mock_snapshot(cash='60.5',timestamp_ms=1,snapshot_id='b',positions=[exposure('owned',campaign_id='campaign:win')],cash_events=[trade('win',1,'.5')])
        with self.assertRaisesRegex(ValueError,'still has open'):
            reconcile(state,next_snapshot,now_ms=1,owned_ids={'owned'})
        self.assertEqual(state['earned_early_ports'],1)

    def test_adverse_marks_drawdown_halt_and_profit_recovery(self):
        state=initial_account_state('175','MOCK-FUTURES')
        for n,cash,events in [(0,'175',[]),(1,'171',[trade('loss',1,'-4')]),(2,'167',[trade('loss2',2,'-4')])]:
            state,_=reconcile(state,mock_snapshot(cash=cash,timestamp_ms=n,snapshot_id=str(n),cash_events=events),now_ms=n)
        limits=capital_status(state,now_ms=2)
        self.assertTrue(limits['halted']);self.assertFalse(limits['ready_for_paper']);self.assertEqual(D(limits['reserve']),50)
        state,_=reconcile(state,mock_snapshot(cash='175',timestamp_ms=3,snapshot_id='heal',cash_events=[trade('gain',3,'8')]),now_ms=3)
        self.assertTrue(state['halted']) # no automatic re-arm


class AccountPortfolioTests(unittest.TestCase):
    setUp=portfolio_f.PortfolioTests.setUp
    tearDown=portfolio_f.PortfolioTests.tearDown
    send=portfolio_f.PortfolioTests.send
    market=portfolio_f.PortfolioTests.market
    signal=portfolio_f.PortfolioTests.signal
    open=portfolio_f.PortfolioTests.open
    quote=portfolio_f.PortfolioTests.quote

    def start(self,cash='450',free=None):
        snap=mock_snapshot(cash=cash,timestamp_ms=0,snapshot_id='opening',free_margin=free)
        self.paper=PortfolioLedger.from_account_snapshot(self.root/'portfolio.sqlite3',self.source.source_id,snap,
            mode='M1',decision_model='pressure',allow_research_expansion=True)
        self.pp=self.paper.portfolio;self.policy=self.paper.policy
        self.snapshot(snap)
        self.send(0,f.scan(extra={f'S{i}USDTM':f.specs(f'S{i}USDTM')[f'S{i}USDTM'] for i in range(12)}))

    def snapshot(self,snap,at=None):
        return self.send(snap.timestamp_ms if at is None else at,('CONTROL','account:'+snap.snapshot_id+':'+snap.source_digest,{'action':'account-snapshot','snapshot':snap.payload()}))

    def reopen(self):
        self.paper.close();self.paper=PortfolioLedger(self.root/'portfolio.sqlite3',self.source.source_id,self.policy,portfolio=self.pp)

    def test_variable_snapshot_cycle_zero_and_budgets(self):
        values=[]
        for cash in ('17','60','99.99','100','175','200','300','350','400','450','500','1000','5000'):
            p=PortfolioLedger.from_account_snapshot(self.root/(cash+'.sqlite3'),self.source.source_id,
                mock_snapshot(cash=cash,timestamp_ms=0,snapshot_id=cash))
            try:
                snap=p.portfolio.funding['snapshot'];self.assertEqual(p.portfolio.initial_capital,cash)
                # Separate source prefix is intentional: apply only this account's event.
                # Direct reducer validated here; journal integration covered below.
                state,_=reconcile(p.account_context(),FuturesAccountSnapshot(**snap),now_ms=0)
                p.state['ladder']=state.pop('ladder');p.state['account_capital']=state;p.state['now_ms']=0
                limits=p.account_limits();values.append(D(limits['active_budget']))
                self.assertEqual(D(limits['current_futures_equity']),D(cash))
                self.assertEqual(p.ladder().realized_net,0)
                self.assertFalse(limits['orders_enabled']);self.assertEqual(limits['connector_status'],'RECONCILED_MOCK')
                if cash in ('200','300'):
                    self.assertEqual(D(limits['reserve']),50) # discriminates against rejected constant-50/50 Model B
                    self.assertEqual(limits['funded_slot_ceiling'],6 if cash=='200' else 10)
                self.assertEqual(p.state['initial_funding']['initial_usable_margin'],cash)
            finally:p.close()
        self.assertEqual(values,[D(x) for x in ('17','60','99.99','50','125','150','250','250','300','300','350','600','2600')])

    def test_continuous_cycles_five_restarts_and_replay(self):
        self.start();opening=self.paper.state['initial_funding'];records=[]
        self.assertNotIn('ladder',self.paper.state['account_capital']) # exactly one durable allocator
        cycles=[('450.50','.50','400'),('450.30','-.20','300'),('451.30','1.00','250'),('451.20','-.10','200'),('451.25','.05','150')]
        for n,(cash,net,free) in enumerate(cycles,1):
            self.snapshot(mock_snapshot(cash=cash,free_margin=free,timestamp_ms=n*100,snapshot_id='cycle'+str(n),cash_events=[trade('trade'+str(n),n*100,net)]))
            before=self.paper.report();records.append(before['account_status']);self.reopen()
            self.assertEqual(self.paper.report(),before);self.assertEqual(self.paper.state['initial_funding'],opening)
            self.assertEqual(self.paper.state['counts']['INITIAL_FUNDING'],1)
            self.assertEqual(D(self.paper.account_limits()['current_futures_equity']),D(cash))
        self.assertEqual(D(self.paper.state['ladder'] and json.loads(self.paper.state['ladder'])['realized_net']),D('1.25'))
        replica=replay([self.source.path],self.root/'replica.sqlite3',self.policy,ledger_factory=PortfolioLedger,ledger_options={'portfolio':self.pp})
        self.assertEqual(replica,self.paper.report());self.paper.invariant()
        self.assertEqual(self.paper.db.execute("SELECT count(*) FROM audit WHERE action='REALIZED_NET_TRADE'").fetchone()[0],5)

    def test_dynamic_sizing_and_margin_reduction_long_and_short(self):
        self.start('17');self.signal('S0USDTM')
        q=self.paper.state['quotes']['S0USDTM'];self.paper.state['pending_entries'].clear();self.paper.state['campaigns'].clear()
        before,reason=self.paper.plan('S0USDTM','LONG',q);self.assertIsNotNone(before,reason)
        self.snapshot(mock_snapshot(cash='42',timestamp_ms=122,snapshot_id='profit',cash_events=[trade('profit',122,'25')]))
        after,reason=self.paper.plan('S0USDTM','LONG',q);self.assertIsNotNone(after,reason)
        self.assertGreater(D(after['risk_budget_usdt']),D(before['risk_budget_usdt']))
        self.assertGreater(D(after['quantity_contracts']),D(before['quantity_contracts']))
        self.snapshot(mock_snapshot(cash='42',free_margin='.1',timestamp_ms=123,snapshot_id='margin'))
        small,reason=self.paper.plan('S0USDTM','LONG',q);self.assertIsNone(small)
        self.assertEqual(D(self.paper.account_limits()['marginal_margin']),D('.1'))
        self.snapshot(mock_snapshot(cash='42',timestamp_ms=124,snapshot_id='restored'))
        for side in ('LONG','SHORT'):
            plan,reason=self.paper.plan('S0USDTM',side,q);self.assertIsNotNone(plan,reason)
            entry=D(plan['entry_price']);stop=D(plan['planned_stop_mid'])
            self.assertAlmostEqual(float(abs(entry-stop)/entry),.005,places=12)
            self.assertLessEqual(D(plan['planned_loss_usdt']),D(plan['allocation_budget_usdt'])*D('.005'))
            self.assertEqual(D(plan['planned_target_net_usdt']),D(plan['allocation_budget_usdt'])*D('.02'))

    def test_early_wins_unique_campaigns_partial_hedges_and_financed_entries(self):
        self.start('60')
        for n,cash in ((1,'60.5'),(2,'61')):
            event=trade('win'+str(n),n*100,'.5')
            self.snapshot(mock_snapshot(cash=cash,timestamp_ms=n*100,snapshot_id='win'+str(n),cash_events=[event]))
            self.assertEqual(self.paper.account_limits()['earned_early_ports'],n+1)
            self.assertEqual(self.paper.account_limits()['allocation_stage'],'BOOTSTRAP')
            self.reopen()
        # Same finalized campaign cannot be paid again under a different cash ID.
        duplicate={**trade('new-id',250,'.5'),'campaign_id':'campaign:win2'}
        self.snapshot(mock_snapshot(cash='61.5',timestamp_ms=250,snapshot_id='duplicate',cash_events=[duplicate]))
        self.assertEqual(self.paper.account_limits()['connector_status'],'DEGRADED')
        self.assertEqual(self.paper.account_limits()['earned_early_ports'],3)
        self.snapshot(mock_snapshot(cash='61',timestamp_ms=251,snapshot_id='recover'))
        # Positive partially closed hedge leg is not a campaign WIN or allocator profit.
        first={**trade('leg1',300,'2'),'campaign_id':'hedge','campaign_complete':False}
        self.snapshot(mock_snapshot(cash='63',timestamp_ms=300,snapshot_id='partial',cash_events=[first]))
        self.assertEqual(self.paper.account_limits()['earned_early_ports'],3)
        self.assertEqual(self.paper.ladder().total,D(61))
        last={**trade('leg2',400,'-3'),'campaign_id':'hedge'}
        self.snapshot(mock_snapshot(cash='60',timestamp_ms=400,snapshot_id='final-loss',cash_events=[last]))
        self.assertEqual(self.paper.account_limits()['earned_early_ports'],3)
        self.assertEqual(self.paper.ladder().total,D(60))
        self.assertEqual(self.paper.state['account_capital']['closed_campaigns']['hedge'],'-1')
        # Three earned permissions are not a fictitious fixed two-slot cap;
        # actual contract minimum, fees, risk, depth and shared margin decide.
        for n in range(3):self.open(f'S{n}USDTM',500+n*200)
        self.assertEqual(len(self.paper.state['positions']),3)
        self.assertLessEqual(self.paper.reserved(),D(60))
        before=self.paper.report();self.reopen();self.assertEqual(self.paper.report(),before)

    def test_activation_once_same_account_preserves_over_cap_positions(self):
        self.start('98')
        for n,cash in ((1,'98.5'),(2,'99')):
            self.snapshot(mock_snapshot(cash=cash,timestamp_ms=n*100,snapshot_id='win'+str(n),cash_events=[trade('w'+str(n),n*100,'.5')]))
        for n in range(3):self.open(f'S{n}USDTM',300+n*200)
        self.assertEqual(len(self.paper.state['positions']),3)
        opening=self.paper.state['initial_funding']
        self.snapshot(mock_snapshot(cash='99.5',timestamp_ms=950,snapshot_id='pre-cross',cash_events=[trade('pre',950,'.5')]))
        self.snapshot(mock_snapshot(cash='100',timestamp_ms=1000,snapshot_id='activate',cash_events=[trade('cross',1000,'.5')]))
        limits=self.paper.account_limits()
        self.assertEqual((limits['allocation_stage'],D(limits['reserve']),D(limits['active_budget']),limits['funded_slot_ceiling']),('EXPAND',D(50),D(50),2))
        self.assertEqual(len(self.paper.state['positions']),3) # no invented liquidation
        self.assertTrue(self.paper.state['exit_requests'])
        self.assertEqual(self.paper.state['counts']['ACTIVATE_LADDER'],1)
        self.assertFalse(self.paper.state['halted']) # reserve allocation is not a 50% trading loss
        self.assertEqual(self.paper.state['initial_funding'],opening)
        self.snapshot(mock_snapshot(cash='99.99',timestamp_ms=1100,snapshot_id='loss',cash_events=[trade('loss',1100,'-.01')]))
        self.assertEqual(self.paper.ladder().stage,'EXPAND');self.assertEqual(self.paper.ladder().reserve,D(50))
        self.assertEqual(self.paper.ladder().active,D('49.99'))
        self.assertLessEqual(self.paper.ladder().slot_ceiling,1)
        self.reopen();self.assertEqual(self.paper.state['counts']['ACTIVATE_LADDER'],1)
        self.assertEqual(len(self.paper.state['positions']),3)
        self.assertEqual(self.paper.state['counts']['INITIAL_FUNDING'],1)

    def test_model_a_post_ten_alternates_reserve_then_active_in_same_account(self):
        self.start('300')
        for n,cash,reserve,active in ((1,'350','100','250'),(2,'400','100','300')):
            self.snapshot(mock_snapshot(cash=cash,timestamp_ms=n*100,snapshot_id=str(n),cash_events=[trade('profit'+str(n),n*100,'50')]))
            self.assertEqual((self.paper.ladder().reserve,self.paper.ladder().active,self.paper.ladder().slot_ceiling),(D(reserve),D(active),10))
            self.assertFalse(self.paper.state['halted'])
            self.reopen()
        self.assertEqual(self.paper.state['counts']['INITIAL_FUNDING'],1)

    def test_funded_rungs_loss_recovery_and_restart_without_bootstrap_reset(self):
        self.start('100')
        for n,(cash,net,active,slots) in enumerate((('125','25','75',3),('300','175','250',10),('260','-40','210',8),('274','14','224',8),('275','1','225',9),('300','25','250',10)),1):
            self.snapshot(mock_snapshot(cash=cash,timestamp_ms=n*100,snapshot_id=str(n),cash_events=[trade('result'+str(n),n*100,net)]))
            self.assertEqual(self.paper.ladder().reserve,D(50));self.assertEqual(self.paper.ladder().active,D(active))
            self.assertEqual(self.paper.ladder().slot_ceiling,slots);self.assertNotEqual(self.paper.ladder().stage,'BOOTSTRAP')
            self.assertEqual(self.paper.account_limits()['earned_early_ports'],1)
            self.reopen()
        self.assertTrue(self.paper.state['halted']) # 16% active loss cannot auto-rearm
        self.assertEqual(self.paper.state['counts']['INITIAL_FUNDING'],1)

    def test_account_driven_concurrent_two_three_five_ten_positions(self):
        for count,cash in ((2,'126'),(3,'151'),(5,'201'),(10,'400')):
            with self.subTest(positions=count):
                scenario=AccountPortfolioTests();scenario.setUp()
                try:
                    scenario.start(cash)
                    for n in range(count):scenario.open(f'S{n}USDTM',100+n*200)
                    self.assertEqual(len(scenario.paper.state['positions']),count)
                    limits=scenario.paper.account_limits()
                    self.assertLessEqual(scenario.paper.planned(),D(limits['active_budget'])*D('.01'))
                    self.assertLessEqual(scenario.paper.reserved(),D(limits['active_budget']))
                    scenario.reopen();scenario.paper.invariant()
                    self.assertEqual(len(scenario.paper.state['positions']),count)
                finally:scenario.tearDown()

    def test_deposit_not_profit_allocation_not_approved(self):
        self.start('60');self.snapshot(mock_snapshot(cash='160',timestamp_ms=100,snapshot_id='deposit',cash_events=[flow('dep',100,'100')]))
        limits=self.paper.account_limits();self.assertEqual(D(limits['current_futures_equity']),160)
        self.assertEqual(D(limits['active_budget']),60);self.assertEqual(D(limits['unallocated_external']),100)
        self.assertEqual(limits['allowed_slots'],1)
        self.assertEqual(self.paper.state['account_capital']['events'].keys(),{'dep'})
        self.send(101,('CONTROL','allocate',{'action':'ALLOCATE_EXTERNAL_FUNDING','amount':'100'}))
        self.assertEqual(D(self.paper.account_limits()['active_budget']),60)

    def test_missing_stale_disconnected_conflicting_snapshots_block_entries(self):
        self.start();self.signal('S0USDTM');self.assertTrue(self.paper.state['pending_entries'])
        self.send(121,('CONTROL','lost',{'action':'account-disconnected'}))
        self.assertFalse(self.paper.state['pending_entries']);self.assertEqual(self.paper.account_limits()['connector_status'],'NOT_CONNECTED')
        self.snapshot(mock_snapshot(cash='450',timestamp_ms=122,snapshot_id='fresh'))
        self.assertTrue(self.paper.account_limits()['ready_for_paper'])
        self.snapshot(mock_snapshot(cash='451',timestamp_ms=123,snapshot_id='unexplained'))
        self.assertEqual(self.paper.account_limits()['connector_status'],'DEGRADED')
        self.snapshot(mock_snapshot(cash='450',timestamp_ms=124,snapshot_id='recover'))
        self.send(16000,('CLOCK','stale',{}));self.assertEqual(self.paper.account_limits()['connector_status'],'STALE')
        self.assertEqual(self.paper.account_limits()['marginal_margin'],'0')

    def test_unknown_account_position_preserves_local_open_monitoring(self):
        self.start();self.open('S0USDTM');self.assertTrue(self.paper.state['positions'])
        positions=dict(self.paper.state['positions'])
        self.snapshot(mock_snapshot(cash='450',timestamp_ms=230,snapshot_id='external',positions=[exposure()]))
        self.assertEqual(self.paper.account_limits()['connector_status'],'EXTERNAL_INTERVENTION')
        self.assertEqual(self.paper.state['positions'],positions)
        self.assertIn('S0USDTM',self.paper.pins());self.reopen()
        self.assertFalse(self.paper.account_limits()['ready_for_paper'])

    def test_sigkill_after_win_commit_before_next_scan_cannot_unlock_twice(self):
        self.start('60');self.paper.close();self.paper=None
        snap=mock_snapshot(cash='60.5',timestamp_ms=100,snapshot_id='win',cash_events=[trade('win',100,'.5')])
        with patch('daiinas.continuous_store.clock_ms',return_value=100):
            self.source.append([('CONTROL','win',{'action':'account-snapshot','snapshot':snap.payload()})])
        from dataclasses import asdict
        code="""
import json,os,signal,sys
from pathlib import Path
from daiinas.portfolio_paper import PortfolioLedger
from daiinas.paper_micro import PaperPolicy
from daiinas.continuous_store import SourceJournal
root=Path(sys.argv[1]);src=SourceJournal(root/'source.sqlite3')
p=PortfolioLedger(root/'portfolio.sqlite3',src.source_id,PaperPolicy(**json.loads(sys.argv[3])),portfolio=json.loads(sys.argv[2]))
p.apply(src.after(p.state['cursor']))
os.kill(os.getpid(),signal.SIGKILL)
"""
        r=subprocess.run([sys.executable,'-c',code,str(self.root),json.dumps(asdict(self.pp)),json.dumps(asdict(self.policy))],capture_output=True,text=True,timeout=10)
        self.assertEqual(r.returncode,-signal.SIGKILL,r.stderr)
        self.paper=PortfolioLedger(self.root/'portfolio.sqlite3',self.source.source_id,self.policy,portfolio=self.pp)
        self.assertEqual(self.paper.account_limits()['earned_early_ports'],2)
        self.assertEqual(D(self.paper.account_limits()['current_futures_equity']),D('60.5'))
        self.assertEqual(self.paper.state['counts']['EARLY_WIN_PORT'],1)
        self.assertEqual(self.paper.state['counts']['INITIAL_FUNDING'],1)
        self.paper.apply(self.source.after(0))
        self.assertEqual(self.paper.account_limits()['earned_early_ports'],2)

    def test_sigkill_account_transaction_rolls_back_and_replays_once(self):
        self.start();self.paper.close();self.paper=None
        snapshot=mock_snapshot(cash='450.5',timestamp_ms=100,snapshot_id='kill',cash_events=[trade('profit',100,'.5')])
        with patch('daiinas.continuous_store.clock_ms',return_value=100):
            self.source.append([('CONTROL','kill',{'action':'account-snapshot','snapshot':snapshot.payload()})])
        code='''
import json,os,signal,sys
from pathlib import Path
from daiinas.portfolio_paper import PortfolioLedger
from daiinas.continuous_store import SourceJournal
root=Path(sys.argv[1]);pp=json.loads(sys.argv[2]);policy=json.loads(sys.argv[3])
from daiinas.paper_micro import PaperPolicy
src=SourceJournal(root/'source.sqlite3')
p=PortfolioLedger(root/'portfolio.sqlite3',src.source_id,PaperPolicy(**policy),portfolio=pp)
old=p.audit
def audit(action,**kw):
 old(action,**kw)
 if action=='REALIZED_NET_TRADE':os.kill(os.getpid(),signal.SIGKILL)
p.audit=audit
p.apply(src.after(p.state['cursor']))
'''
        from dataclasses import asdict
        r=subprocess.run([sys.executable,'-c',code,str(self.root),json.dumps(asdict(self.pp)),json.dumps(asdict(self.policy))],capture_output=True,text=True,timeout=10)
        self.assertEqual(r.returncode,-signal.SIGKILL,r.stderr)
        self.paper=PortfolioLedger(self.root/'portfolio.sqlite3',self.source.source_id,self.policy,portfolio=self.pp)
        self.assertEqual(D(self.paper.account_limits()['current_futures_equity']),450)
        rows=self.source.after(self.paper.state['cursor']);self.paper.apply(rows);self.paper.apply(rows)
        self.assertEqual(D(self.paper.account_limits()['current_futures_equity']),D('450.5'))
        self.assertEqual(self.paper.state['counts']['REALIZED_NET_TRADE'],1)
        self.assertEqual(self.paper.state['counts']['INITIAL_FUNDING'],1)


class AccountPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_poll_missing_and_failed_adapter_use_durable_single_writer(self):
        from daiinas.continuous_paper import Pipeline
        from daiinas.portfolio_paper import PortfolioPolicy
        from daiinas.funding import snapshot_funding
        from daiinas.paper_micro import PaperPolicy
        class FailedAdapter:
            def snapshot(self):raise RuntimeError('sensitive transport URL must never be journaled')
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);snap=mock_snapshot(cash='60',timestamp_ms=1,snapshot_id='a')
            pp=PortfolioPolicy(initial_capital='60',funding=snapshot_funding(snap),account_driven=True)
            pipeline=Pipeline(root/'source.sqlite3',root/'paper.sqlite3',PaperPolicy(initial_capital_usdt=60,leverage=2,stop_bps=50),ledger_factory=PortfolioLedger,ledger_options={'portfolio':pp})
            try:
                self.assertEqual((await pipeline.report())['account_status']['connector_status'],'NOT_CONNECTED')
                with patch('daiinas.continuous_store.clock_ms',return_value=1):
                    await pipeline.poll_account(MockFuturesAdapter([snap]))
                self.assertEqual((await pipeline.report())['account_status']['connector_status'],'RECONCILED_MOCK')
                with patch('daiinas.continuous_store.clock_ms',return_value=2):
                    await pipeline.poll_account(FailedAdapter())
                report=await pipeline.report();self.assertEqual(report['account_status']['connector_status'],'NOT_CONNECTED')
                self.assertEqual(report['counts']['INITIAL_FUNDING'],1)
                with sqlite3.connect(root/'source.sqlite3') as db:
                    payload=''.join(row[0] for row in db.execute('SELECT payload FROM journal'))
                self.assertNotIn('sensitive',payload);self.assertIn('Read-only adapter failed',payload)
            finally:pipeline.close()


if __name__=='__main__':unittest.main()
