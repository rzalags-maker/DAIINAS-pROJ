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
        self.pp=PortfolioPolicy(initial_capital=capital,mode=mode,decision_model=decision_model,allow_research_expansion=True)
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

    def range_candidates(self,capital='400'):
        import math
        self.start(capital,'M2','adaptive')
        sym='S0USDTM'
        for i in range(1,60):
            t=i*1000;mid=1+math.sin(i*math.pi/3)*.01
            self.send(t,self.market(sym,t,'level2',mid-.0001,mid+.0001,size=.001),
                      self.market(sym,t,'tickerV2',mid-.0001,mid+.0001,size=.001))
        self.quote(sym,60000,.9999,1.0001)
        self.quote(sym,60150,.9999,1.0001)

    def test_two_legs_count_slots_and_winner_cannot_promote_campaign(self):
        self.range_candidates()
        self.assertEqual(len(self.paper.state['positions']),2)
        c=next(c for c in self.paper.state['campaigns'].values() if not c['settled'])
        self.assertEqual(len({p['campaign_id'] for p in self.paper.state['positions'].values()}),1)
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
