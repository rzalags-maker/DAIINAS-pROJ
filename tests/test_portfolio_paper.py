"""Synthetic public-event fixtures; not market performance evidence."""
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from daiinas.continuous_store import SourceJournal
from daiinas.portfolio_paper import PortfolioLedger,PortfolioPolicy
from daiinas.funding import paper_funding
from daiinas.paper_micro import PaperPolicy
import test_continuous_paper as f

D=lambda x:Decimal(str(x))

class PortfolioTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.source=SourceJournal(self.root/'source.sqlite3')
        self.paper=None;self.clock=0;self.idx=0
    def tearDown(self):
        if self.paper:self.paper.close()
        self.source.close();self.tmp.cleanup()
    def start(self,capital='100',mode='M1',decision_model='pressure'):
        self.policy=PaperPolicy(initial_capital_usdt=float(capital))
        self.pp=PortfolioPolicy(initial_capital=capital,funding=paper_funding(capital,account_id='fixture-'+capital,source_reference='explicit-unit-fixture',timestamp_ms=0),mode=mode,decision_model=decision_model,allow_research_expansion=True)
        self.paper=PortfolioLedger(self.root/'portfolio.sqlite3',self.source.source_id,self.policy,portfolio=self.pp)
        self.send(0,f.scan(extra={f'S{i}USDTM':f.specs(f'S{i}USDTM')[f'S{i}USDTM'] for i in range(12)}))
    def send(self,t,*packets):
        self.clock=t
        with patch('daiinas.continuous_store.clock_ms',return_value=t):rows=self.source.append(packets)
        self.paper.apply(rows);return rows
    def market(self,sym,t,channel,bid=1.,ask=1.0002,side='buy',size=10000):
        self.idx+=1
        return f.market(channel,t,self.idx,sym=sym,bid=bid,ask=ask,side=side,bid_size=size,ask_size=size)
    def signal(self,sym,t=100,side='buy'):
        for i in range(3):self.send(t+i,self.market(sym,t+i,'execution',side=side))
        self.idx+=1
        sizes={'bid_size':10000 if side=='buy' else 1000,'ask_size':1000 if side=='buy' else 10000}
        self.send(t+10,f.market('level2',t+10,self.idx,sym=sym,**sizes))
        self.send(t+20,f.market('tickerV2',t+20,self.idx,sym=sym,**sizes))
    def open(self,sym,t=100,side='buy'):
        self.signal(sym,t,side)
        self.idx+=1
        sizes={'bid_size':10000 if side=='buy' else 1000,'ask_size':1000 if side=='buy' else 10000}
        self.send(t+121,f.market('tickerV2',t+121,self.idx,sym=sym,**sizes))
    def quote(self,sym,t,bid,ask,size=10000):
        self.send(t-1,self.market(sym,t-1,'level2',bid,ask,size=size))
        return self.send(t,self.market(sym,t,'tickerV2',bid,ask,size=size))

    def test_separate_8_60_100_scenarios_and_no_legacy_migration(self):
        from daiinas.continuous_paper import PaperLedger
        self.start('8');self.open('S0USDTM')
        self.assertEqual(self.paper.ladder().reserve,0)
        self.assertLessEqual(len(self.paper.state['positions']),1)
        with self.assertRaises(ValueError):PaperLedger(self.root/'portfolio.sqlite3',self.source.source_id)
        self.paper.close();self.paper=None
        with self.assertRaises(ValueError):PortfolioLedger(self.root/'portfolio.sqlite3',self.source.source_id,PaperPolicy(initial_capital_usdt=60),portfolio={'initial_capital':'60'})

    def test_entry_fee_cash_active_and_reverse_slots(self):
        self.start();self.open('S0USDTM')
        s=self.paper.state;p=next(iter(s['positions'].values()))
        self.assertEqual(D(s['cash']),D(100)-D(p['entry_fee_usdt']))
        self.assertEqual(self.paper.ladder().reserve,D(50))
        self.assertEqual(s['capital_status']['allowed_slots'],1)
        self.assertLessEqual(D(p['planned_loss_usdt']),D(50)*D('.0025'))
        self.paper.invariant()

    def test_multiple_positions_gross_cap_risk_and_margin(self):
        for count,capital in [(2,'126'),(3,'151'),(5,'201'),(10,'400')]:
            with self.subTest(count=count):
                if self.paper:self.paper.close();self.paper=None
                path=self.root/'portfolio.sqlite3'
                for suffix in ('','-wal','-shm'):
                    q=Path(str(path)+suffix)
                    if q.exists():q.unlink()
                # New account and independent journal for each synthetic scenario.
                self.source.close();src=self.root/f'source{count}.sqlite3';self.source=SourceJournal(src)
                self.start(capital)
                # Independent synthetic return histories establish diversification as-of entry.
                import random
                paths={}
                for i in range(count):
                    rng=random.Random(i+20);values=[1.]
                    for j in range(20):values.append(values[-1]*(1+rng.uniform(-.0001,.0001)))
                    paths[i]=[x/values[-1] for x in values]
                for j in range(21):
                    t=1000+j*1000
                    for i in range(count):
                        mid=paths[i][j]
                        self.send(t,self.market(f'S{i}USDTM',t,'level2',mid-.0001,mid+.0001),
                                  self.market(f'S{i}USDTM',t,'tickerV2',mid-.0001,mid+.0001))
                for i in range(count):self.open(f'S{i}USDTM',22000+i*130)
                self.assertEqual(len(self.paper.state['positions']),count)
                self.assertLessEqual(self.paper.planned(),D(self.paper.state['active_equity'])*D('.01'))
                self.assertLessEqual(self.paper.reserved(),self.paper.ladder().active*D('.8'))
                self.assertEqual(len(self.paper.pins()),count)
                self.paper.invariant()

    def test_later_stop_and_depth_unresolved_then_restart_replay(self):
        self.start('126');self.open('S0USDTM')
        self.quote('S0USDTM',500,.99,.9902,size=.001)
        self.quote('S0USDTM',650,.98,.9802,size=.001)
        self.assertTrue(self.paper.state['positions'])
        cash=self.paper.state['cash'];self.assertTrue(self.paper.state['exit_requests'])
        self.paper.close();self.paper=PortfolioLedger(self.root/'portfolio.sqlite3',self.source.source_id,self.policy,portfolio=self.pp)
        self.assertEqual(self.paper.state['cash'],cash)
        self.quote('S0USDTM',800,.97,.9702)
        self.assertFalse(self.paper.state['positions'])
        expected=self.paper.report()
        replica=PortfolioLedger(self.root/'replica.sqlite3',self.source.source_id,self.policy,portfolio=self.pp)
        try:
            rows=self.source.after(0,10000);replica.apply(rows);replica.apply(rows)
            self.assertEqual(expected,replica.report())
        finally:replica.close()

    def test_deposit_is_quarantined_not_profit_or_margin(self):
        self.start('60');before=self.paper.ladder().snapshot()
        self.send(100,('CONTROL','deposit:100',{'action':'capital-flow','amount':'100'}))
        self.assertEqual(self.paper.ladder().snapshot(),before)
        self.assertEqual(self.paper.state['cash'],'160')
        self.assertEqual(self.paper.observation_equity(),60)
        self.assertEqual(self.paper.ladder().slot_ceiling,1)
        self.assertEqual(self.paper.report()['account_maximum_drawdown'],0)
        self.assertEqual(D(self.paper.report()['account_peak']),D(160))

    def test_disk_full_rolls_back_decimal_money_and_ladder(self):
        from copy import deepcopy
        self.start();before=deepcopy(self.paper.state)
        self.paper.db.execute('PRAGMA max_page_count='+str(self.paper.db.execute('PRAGMA page_count').fetchone()[0]))
        with patch('daiinas.continuous_store.clock_ms',return_value=100):
            rows=self.source.append([('CONTROL','deposit',{'action':'capital-flow','amount':'1'}),('CLOCK','full',{'service':{'x':'x'*1000000}})])
        with self.assertRaises(sqlite3.OperationalError):self.paper.apply(rows)
        self.assertEqual(self.paper.state,before)
        self.paper.db.execute('PRAGMA max_page_count=100000');self.paper.apply(rows);self.paper.apply(rows)
        self.assertEqual(D(self.paper.state['cash']),D(101))

    def test_adaptive_simultaneous_markets_choose_independently(self):
        import math
        self.start('400','M3','adaptive')
        directions={'S0USDTM':'buy','S1USDTM':'sell','S2USDTM':'buy','S3USDTM':'buy'}
        for i in range(1,70):
            t=i*1000
            for j,sym in enumerate(directions):
                mid=1+i*.0004 if j==0 else 1-i*.0004 if j==1 else 1+math.sin(i*math.pi/3)*.01 if j==2 else 1.
                sizes={'bid_size':10000 if j==0 else 1000 if j==1 else 10000,
                       'ask_size':1000 if j==0 else 10000}
                for k in range(3):
                    event=self.market(sym,t,'execution',side=directions[sym]);event[2]['normalized']['price']=mid
                    self.send(t,event)
                self.idx+=1
                self.send(t,f.market('level2',t,self.idx,sym=sym,bid=mid-.0001,ask=mid+.0001,**sizes),
                          f.market('tickerV2',t,self.idx,sym=sym,bid=mid-.0001,ask=mid+.0001,**sizes))
        states=self.paper.state['market_states']
        self.assertEqual(states['S0USDTM']['regime'],'UP_TREND')
        self.assertEqual(states['S1USDTM']['regime'],'DOWN_TREND')
        self.assertEqual(states['S3USDTM']['last_action'],'NO_TRADE')
        actions={sym:set() for sym in directions}
        for row in self.paper.db.execute("SELECT payload FROM audit WHERE action='DECISION'"):
            event=json.loads(row[0]);actions[event['symbol']].add(event['selected_action'])
        self.assertIn('ENTER_LONG',actions['S0USDTM']);self.assertIn('ENTER_SHORT',actions['S1USDTM'])
        self.assertNotIn('ADD_OPPOSITE_LEG',actions['S2USDTM'])
        self.assertFalse(states['S2USDTM']['hedge_evidence_supported'])
        self.paper.invariant()

    def range_candidates(self,capital='400',fill=True):
        import math
        self.start(capital,'M2','adaptive')
        sym='S0USDTM'
        for i in range(1,60):
            t=i*1000;mid=1+math.sin(i*math.pi/3)*.01
            self.send(t,self.market(sym,t,'level2',mid-.0001,mid+.0001,size=.001),
                      self.market(sym,t,'tickerV2',mid-.0001,mid+.0001,size=.001))
        self.quote(sym,60000,.9999,1.0001)
        if fill:self.quote(sym,60150,.9999,1.0001)

    def test_two_legs_count_slots_and_winner_cannot_promote_campaign(self):
        self.range_candidates()
        self.assertEqual(len(self.paper.state['positions']),2)
        self.assertEqual(len({D(p['quantity_contracts']) for p in self.paper.state['positions'].values()}),1)
        c=next(c for c in self.paper.state['campaigns'].values() if not c['settled'])
        self.assertEqual(len({p['campaign_id'] for p in self.paper.state['positions'].values()}),1)
        self.assertEqual(D(c['net_notional']),0)
        # Long can close, but there is no executable ask liquidity for the losing short.
        for t in [60500,60700]:
            self.idx+=1
            self.send(t,f.market('level2',t,self.idx,sym='S0USDTM',bid=1.05,ask=1.0502,bid_size=10000,ask_size=.001),
                      f.market('tickerV2',t,self.idx,sym='S0USDTM',bid=1.05,ask=1.0502,bid_size=10000,ask_size=.001))
        self.assertEqual(len(self.paper.state['positions']),1)
        self.assertEqual(next(iter(self.paper.state['positions'].values()))['direction'],'SHORT')
        self.assertGreater(D(c['realized_net']),0)
        self.assertEqual(self.paper.ladder().realized_net,0)
        self.assertFalse(c['settled']);self.assertIsNone(c['net_mark']);self.assertEqual(c['mark_status'],'UNRESOLVED')
        self.assertIn('S0USDTM',self.paper.pins())
        self.quote('S0USDTM',61000,1.06,1.0602)
        self.assertFalse(self.paper.state['positions']);self.assertTrue(c['settled'])
        self.assertEqual(D(c['net_base_units']),0)
        self.assertLess(D(c['realized_net']),0)
        self.assertEqual(self.paper.ladder().reserve,D(100))
        self.paper.invariant()

    def test_bootstrap_does_not_admit_two_leg_control(self):
        self.range_candidates('60')
        self.assertLessEqual(len(self.paper.state['positions']),1)
        self.assertEqual(len(self.paper.state['positions']),0)
        self.assertEqual(self.paper.state['cash'],'60')

    def test_ladder_growth_only_after_whole_campaign_finalizes(self):
        self.start('60');self.open('S0USDTM')
        # Large favorable synthetic gap is not a forecast; all closes use later data.
        self.quote('S0USDTM',500,3.,3.0002);self.quote('S0USDTM',650,3.,3.0002)
        self.assertFalse(self.paper.state['positions'])
        self.assertGreaterEqual(self.paper.ladder().reserve,D(50))
        self.assertEqual(self.paper.ladder().total,D(self.paper.state['cash']))
        self.assertGreater(self.paper.ladder().realized_net,0)

    def test_pending_correlation_capacity_and_rotation_pins(self):
        self.start('400')
        self.signal('S0USDTM');self.assertIn('S0USDTM',self.paper.pins())
        watch=f.scan(200,symbol='NEWUSDTM',extra=f.specs('S0USDTM'))
        self.send(200,watch)
        self.assertIn('S0USDTM',self.paper.pins())
        self.assertTrue(self.paper.state['pending_entries'])
        self.send(300,('HEALTH','gap',{'state':'CONNECTION_LOSS'}))
        self.assertIn('S0USDTM',self.paper.pins())

    def test_pending_entry_rechecks_wide_spread_and_later_wire_time(self):
        self.start('126');self.signal('S0USDTM')
        self.quote('S0USDTM',300,.999,1.001)
        self.assertFalse(self.paper.state['positions'])
        self.assertIn('REJECTED:spread_over_budget',self.paper.state['reason_counts'])

    def test_fee_increase_revalues_remaining_stop_risk(self):
        self.start('126');self.open('S0USDTM')
        packet=f.scan(300,extra={'S0USDTM':f.specs('S0USDTM',fee=.02)['S0USDTM']})
        self.send(300,packet)
        self.assertTrue(self.paper.state['exit_requests'])
        p=next(iter(self.paper.state['positions'].values()))
        self.assertGreater(D(p['current_planned_loss_usdt']),D(p['planned_loss_usdt']))
        self.assertEqual(self.paper.ladder().reserve,D(50))

    def test_unverified_hours_accrue_carry_without_fictional_exit(self):
        self.start('126');self.open('S0USDTM')
        cash=self.paper.state['cash']
        self.send(3000,('CLOCK','stale1',{}));first=D(self.paper.state['marked_unrealized'])
        self.send(100000,('CLOCK','stale2',{}));second=D(self.paper.state['marked_unrealized'])
        self.assertLess(second,first);self.assertEqual(self.paper.state['cash'],cash)
        self.assertIsNone(self.paper.report()['executable_equity'])

    def test_symmetric_control_cannot_silently_become_directional_baseline(self):
        self.start('400','M2','adaptive')
        for i in range(1,40):
            t=i*1000;mid=1+i*.0004
            for j in range(3):
                event=self.market('S0USDTM',t,'execution');event[2]['normalized']['price']=mid
                self.send(t,event)
            self.idx+=1
            self.send(t,f.market('level2',t,self.idx,sym='S0USDTM',bid=mid-.0001,ask=mid+.0001,bid_size=10000,ask_size=1000),
                      f.market('tickerV2',t,self.idx,sym='S0USDTM',bid=mid-.0001,ask=mid+.0001,bid_size=10000,ask_size=1000))
        self.assertEqual(self.paper.state['market_states']['S0USDTM']['regime'],'UP_TREND')
        self.assertEqual(self.paper.state['counts'].get('OPENED',0),0)

    def test_failed_second_control_leg_requests_real_exit_of_first(self):
        self.range_candidates(fill=False)
        self.idx+=1
        self.send(60150,f.market('level2',60150,self.idx,sym='S0USDTM',bid=.9999,ask=1.0001,bid_size=.001,ask_size=10000),
                  f.market('tickerV2',60150,self.idx,sym='S0USDTM',bid=.9999,ask=1.0001,bid_size=.001,ask_size=10000))
        self.assertEqual(self.paper.state['counts'].get('OPENED',0),1)
        self.assertEqual(next(iter(self.paper.state['exit_requests'].values()))['reason'],'UNMATCHED_HEDGE')
        self.assertIsNone(self.paper.report()['executable_equity'])
        self.assertIn('S0USDTM',self.paper.pins())
        self.quote('S0USDTM',61000,.9999,1.0001)
        self.assertFalse(self.paper.state['positions']);self.paper.invariant()

import asyncio
import time
from daiinas.continuous_paper import Pipeline
from daiinas.continuous import replay
from daiinas.continuous_stream import ContinuousObserver
from test_continuous_stream import metadata

class WriterIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_writer_scan_pin_backup_and_offline_replay(self):
        from daiinas.continuous_ops import backup_pair,verify_backup
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);src=root/'source.sqlite3';paper=root/'portfolio.sqlite3'
            policy=PaperPolicy(initial_capital_usdt=126);pp=PortfolioPolicy(initial_capital='126',funding=paper_funding('126',account_id='fixture-126',source_reference='explicit-unit-fixture',timestamp_ms=0),mode='M1',decision_model='pressure')
            pipe=Pipeline(src,paper,policy,ledger_factory=PortfolioLedger,ledger_options={'portfolio':pp})
            observer=None
            try:
                now=time.time_ns()//1000000;packet=f.scan(now)
                packet[2]['report']['paper_contract_specs'][f.SYM]['captured_ms']=now
                await pipe.append([packet])
                for i in range(3):await pipe.append([f.market('execution',now,i+1)])
                await pipe.append([f.market('level2',now,1,bid_size=10000,ask_size=1000),f.market('tickerV2',now,1,bid_size=10000,ask_size=1000)])
                await asyncio.sleep(.12);later=time.time_ns()//1000000
                await pipe.append([f.market('tickerV2',later,2,bid_size=10000,ask_size=1000)])
                self.assertIn(f.SYM,(await pipe.report())['pins'])
                def public(path):
                    if path.endswith('active'):return [metadata(s) for s in ['AAAUSDTM','BBBUSDTM','CCCUSDTM']]
                    return [{'symbol':s,'ts':time.time_ns(),'bestBidPrice':'1','bestAskPrice':'1.0002','bestBidSize':100000,'bestAskSize':100000}
                            for s in ['AAAUSDTM','BBBUSDTM','CCCUSDTM']]
                observer=ContinuousObserver(pipe,source_path=src,deep=3,market_get=public)
                scan=await observer.preflight()
                self.assertIn(f.SYM,scan['watch']['deep_symbols']);self.assertIn(f.SYM,scan['unavailable'])
                expected=await pipe.report();self.assertTrue(expected['positions'])
            finally:
                if observer:observer.close()
                pipe.close()
            replica=replay([src],root/'replica.sqlite3',policy,ledger_factory=PortfolioLedger,ledger_options={'portfolio':pp})
            self.assertEqual(expected,replica)
            backup_pair(src,paper,root/'backup');self.assertTrue(verify_backup(root/'backup'))

class OwnerSourceGoldenTests(unittest.TestCase):
    def test_all_source_forward_and_reverse_examples(self):
        from daiinas.capital_ladder import CapitalLadder
        states=[('8','0','8','0',1),('29','0','29','0',1),('60','0','60','0',1)]
        states += [(str(100+25*i),'50',str(50+25*i),'0',2+i) for i in range(9)]
        states += [('330','50','250','30',10),('350','100','250','0',10),('400','100','300','0',10),
                   ('450','150','300','0',10),('500','150','350','0',10),('550','200','350','0',10),
                   ('600','200','400','0',10),('650','250','400','0',10),('700','250','450','0',10)]
        for total,r,a,p,n in states:
            x=CapitalLadder(total)
            self.assertEqual((x.reserve,x.active,x.pending,x.slot_ceiling),(D(r),D(a),D(p),n))
        for active in [250,225,200,175,150,125,100,75,50,25,24,0]:
            x=CapitalLadder('300');x.realized_result(str(active-250))
            self.assertEqual(x.reserve,D(50));self.assertEqual(x.slot_ceiling,min(10,max(0,active//25)))
        x=CapitalLadder('400');x.realized_result('-60')
        self.assertEqual((x.reserve,x.active,x.slot_ceiling),(D(100),D(240),9))
        x.realized_result('59');self.assertEqual(x.pending,0);x.realized_result('1');self.assertEqual(x.active,D(300))
        self.assertEqual(D(25)*D('.02'),D('.50'));self.assertEqual(D(25)/(D(25)*D('.02')),D(50))

class ProcessKillTests(unittest.TestCase):
    setUp=PortfolioTests.setUp
    tearDown=PortfolioTests.tearDown
    start=PortfolioTests.start
    send=PortfolioTests.send
    signal=PortfolioTests.signal
    market=PortfolioTests.market
    def test_process_kill_after_fill_before_checkpoint_recovers_once(self):
        import subprocess,sys,signal
        self.start('126');self.signal('S0USDTM')
        self.idx+=1
        with patch('daiinas.continuous_store.clock_ms',return_value=221):
            self.source.append([f.market('tickerV2',221,self.idx,sym='S0USDTM',bid_size=10000,ask_size=1000)])
        self.paper.close();self.paper=None
        code="""
import os,sys,signal
from pathlib import Path
from daiinas.portfolio_paper import PortfolioLedger,PortfolioPolicy
from daiinas.funding import paper_funding
from daiinas.continuous_store import SourceJournal
from daiinas.paper_micro import PaperPolicy
from daiinas.funding import paper_funding
root=Path(sys.argv[1]);source=SourceJournal(root/'source.sqlite3')
p=PortfolioLedger(root/'portfolio.sqlite3',source.source_id,PaperPolicy(initial_capital_usdt=126.0),
 portfolio=PortfolioPolicy(initial_capital='126',funding=paper_funding('126',account_id='fixture-126',source_reference='explicit-unit-fixture',timestamp_ms=0),mode='M1',decision_model='pressure',allow_research_expansion=True))
old=p.audit
def audit(action,**detail):
 old(action,**detail)
 if action=='OPENED':os.kill(os.getpid(),signal.SIGKILL)
p.audit=audit
p.apply(source.after(p.state['cursor']))
"""
        result=subprocess.run([sys.executable,'-c',code,str(self.root)],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,-signal.SIGKILL,result.stderr)
        self.paper=PortfolioLedger(self.root/'portfolio.sqlite3',self.source.source_id,self.policy,portfolio=self.pp)
        self.assertEqual(D(self.paper.state['cash']),D(126))
        rows=self.source.after(self.paper.state['cursor']);self.paper.apply(rows);self.paper.apply(rows)
        self.assertEqual(len(self.paper.state['positions']),1)
        self.assertEqual(self.paper.state['counts']['OPENED'],1)
        self.paper.invariant()
