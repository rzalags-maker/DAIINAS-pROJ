"""Synthetic, chronological v3.3 fixtures. Not real KuCoin evidence."""
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from daiinas.continuous_store import SourceJournal,Timeline,pinned_selection
from daiinas.continuous_paper import PaperLedger
from daiinas.universe_rotation import RotationPolicy
from daiinas.paper_micro import PaperPolicy

SYM='TESTUSDTM'
OTHER='OTHERUSDTM'


def specs(symbol=SYM,multiplier='1',fee=.0006):
    return {symbol:{'rules':{'symbol':symbol,'min_qty':'1','max_qty':'100000','step_size':'1',
            'tick_size':'.0001','min_notional':'0','contract_size':multiplier},
            'captured_ms':0,'source':'synthetic fixture','taker_fee_rate':fee}}


def scan(t=0,symbol=SYM,extra=None,unavailable=()):
    spec=specs(symbol);spec.update(extra or {})
    report={'time_ms':t,'capital_usdt':8,'contracts_observed':len(spec),'preflight_eligible':1,
            'paper_contract_specs':spec}
    watch={'time_ms':t,'deep_symbols':list(spec),'blocked_new_entries':[],'capacity_exhausted':False}
    return ('SCAN',f'scan:{t}:{symbol}',{'report':report,'watch':watch,'unavailable':list(unavailable)})


def market(channel,t,idx,sym=SYM,bid=1.,ask=1.0002,side='buy',bid_size=100,ask_size=10):
    q={'timestamp':t,'bid':str(bid),'ask':str(ask),'bid_base_size':bid_size,'ask_base_size':ask_size}
    normalized=q if channel=='tickerV2' else {
        'verified':True,'best_bid':bid,'best_ask':ask,'bid_base_size':bid_size,'ask_base_size':ask_size,
        'book_sequence':idx} if channel=='level2' else {
        'timestamp':t,'price':1.,'quantity':10.,'buyer_is_maker':side=='sell'}
    return ('MARKET',f'market:{sym}:{channel}:{idx}',{'symbol':sym,'channel':channel,
          'event_key':str(idx),'event_ms':t,'received_ms':t,'raw':{'seq':idx,'channel':channel},'normalized':normalized})


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.source=SourceJournal(self.root/'source.sqlite3')
        self.paper=PaperLedger(self.root/'paper.sqlite3',self.source.source_id)
        self.send(0,scan())

    def tearDown(self):
        self.paper.close();self.source.close();self.temp.cleanup()

    def send(self,t,*packets):
        with patch('daiinas.continuous_store.clock_ms',return_value=t):rows=self.source.append(packets)
        self.paper.apply(rows)
        return rows

    def signal(self,side='buy'):
        for i in range(3):self.send(100+i,market('execution',100+i,i+1,side=side))
        sizes={'bid_size':100 if side=='buy' else 10,'ask_size':10 if side=='buy' else 100}
        self.send(110,market('level2',110,1,**sizes))
        self.send(120,market('tickerV2',120,1,**sizes))
        self.assertIsNotNone(self.paper.state['pending'])

    def opened(self,side='buy'):
        self.signal(side)
        sizes={'bid_size':100 if side=='buy' else 10,'ask_size':10 if side=='buy' else 100}
        self.send(221,market('tickerV2',221,2,**sizes))
        self.assertIsNotNone(self.paper.state['position'])

    def close_quote(self,t,bid,ask,idx=3,bid_size=100,ask_size=100):
        self.send(t-1,market('level2',t-1,idx,bid=bid,ask=ask,bid_size=bid_size,ask_size=ask_size))
        self.send(t,market('tickerV2',t,idx,bid=bid,ask=ask,bid_size=bid_size,ask_size=ask_size))

    def test_long_uses_later_quote_for_entry_and_later_exit(self):
        self.opened()
        fee=self.paper.state['fees']
        self.close_quote(500,1.01,1.0102)
        self.assertIsNotNone(self.paper.state['position'])
        self.assertEqual(self.paper.state['exit_request']['reason'],'TARGET')
        self.close_quote(650,1.011,1.0112,4)
        self.assertIsNone(self.paper.state['position'])
        self.assertGreater(self.paper.state['realized'],0)
        self.assertGreater(self.paper.state['fees'],fee)
        self.assertAlmostEqual(self.paper.state['cash'],8+self.paper.state['realized'])

    def test_short_stop_uses_actual_adverse_gap_not_stop_threshold(self):
        self.opened('sell')
        self.close_quote(500,1.02,1.0202)
        self.assertEqual(self.paper.state['exit_request']['reason'],'STOP')
        self.close_quote(650,1.03,1.0302,4)
        done=json.loads(self.paper.db.execute('SELECT payload FROM closed_positions').fetchone()[0])
        self.assertEqual(done['direction'],'SHORT')
        self.assertGreater(done['exit_price'],1.0302)
        self.assertLess(done['net_pnl_usdt'], -done['planned_loss_usdt'])

    def test_position_and_pending_exit_survive_process_restart_and_rotation(self):
        self.opened();cash=self.paper.state['cash']
        self.send(300,scan(300,OTHER,extra=specs(SYM)))
        self.close_quote(500,.99,.9902)
        self.paper.close();self.paper=PaperLedger(self.root/'paper.sqlite3',self.source.source_id)
        self.assertEqual(self.paper.state['cash'],cash)
        self.assertIn(SYM,self.paper.pins())
        self.assertEqual(self.paper.state['exit_request']['reason'],'STOP')
        self.close_quote(650,.98,.9802,4)
        self.assertIsNone(self.paper.state['position'])
        self.assertEqual(self.paper.state['counts']['OPENED'],1)

    def test_disappearing_contract_stays_unresolved_not_closed(self):
        self.opened()
        self.send(300,scan(300,OTHER,unavailable=[SYM]))
        self.close_quote(500,.90,.9002)
        self.assertIsNotNone(self.paper.state['position'])
        self.assertTrue(self.paper.state['position']['unresolved'])
        self.assertIn(SYM,self.paper.pins())
        self.assertFalse(self.paper.db.execute('SELECT * FROM closed_positions').fetchall())

    def test_changed_multiplier_never_reinterprets_open_contract(self):
        self.opened()
        change=scan(300);change[2]['report']['paper_contract_specs']=specs(multiplier='1000')
        self.send(300,change)
        self.close_quote(500,1.01,1.0102)
        self.close_quote(650,1.02,1.0202,4)
        self.assertEqual(self.paper.state['position']['contract_multiplier'],1)
        self.assertEqual(self.paper.state['position']['unresolved'],'missing_or_changed_asof_exit_rules')

    def test_ttl_pause_and_empty_market_no_forced_trades(self):
        self.signal()
        self.send(6000,('CLOCK','clock:6000',{}))
        self.assertIsNone(self.paper.state['pending'])
        self.assertEqual(self.paper.state['counts']['UNFILLED'],1)
        self.send(6001,('CONTROL','pause:1',{'action':'pause'}))
        self.assertTrue(self.paper.state['paused'])
        self.assertEqual(self.paper.state['cash'],8)

    def test_pause_does_not_abandon_open_exit(self):
        self.opened()
        self.send(250,('CONTROL','pause:1',{'action':'pause'}))
        self.close_quote(500,.99,.9902)
        self.close_quote(650,.98,.9802,4)
        self.assertIsNone(self.paper.state['position'])
        self.assertTrue(self.paper.state['paused'])

    def test_partial_depth_is_unresolved_not_fabricated_partial_close(self):
        self.opened();cash=self.paper.state['cash']
        self.close_quote(500,.99,.9902)
        self.close_quote(650,.98,.9802,4,bid_size=.01)
        self.assertIsNotNone(self.paper.state['position'])
        self.assertEqual(self.paper.state['cash'],cash)
        self.assertEqual(self.paper.state['position']['unresolved'],'insufficient_verified_depth_for_full_exit')
        self.close_quote(800,.97,.9702,5)
        self.assertIsNone(self.paper.state['position'])

    def test_gap_stale_quotes_and_clock_never_invent_exit(self):
        self.opened()
        self.send(400,('HEALTH','gap:1',{'symbol':SYM,'state':'book_gap'}))
        self.send(500,market('tickerV2',500,3,bid=.99,ask=.9902))
        self.assertIsNotNone(self.paper.state['position'])
        self.send(10000,('CLOCK','clock:10000',{}))
        self.assertIn('UNRESOLVED',self.paper.state['mark_status'])
        self.assertIsNotNone(self.paper.state['position'])

    def test_minimum_lot_risk_is_rejected_not_rounded_up(self):
        change=scan(50);change[2]['report']['paper_contract_specs']=specs(multiplier='1000')
        self.send(50,change);self.signal()
        self.send(221,market('tickerV2',221,2))
        self.assertIsNone(self.paper.state['position'])
        rows=self.paper.db.execute("SELECT payload FROM audit WHERE action='REJECTED'").fetchall()
        self.assertIn('minimum_lot_exceeds_account_risk_or_margin',rows[-1][0])
        self.assertEqual(self.paper.state['cash'],8)

    def test_source_fee_asof_later_scan_and_no_future_scan(self):
        self.signal()
        change=scan(200);change[2]['report']['paper_contract_specs']=specs(fee=.05)
        self.send(200,change)
        self.send(221,market('tickerV2',221,2))
        self.assertIsNone(self.paper.state['position'])
        future=scan(10000)
        with self.assertRaisesRegex(ValueError,'Future scan'):
            self.send(300,future)

    def test_exactly_once_fee_carry_and_deterministic_replay(self):
        self.opened()
        self.close_quote(500,1.01,1.0102);self.close_quote(650,1.011,1.0112,4)
        before=self.paper.report()
        records=self.source.after(0,1000)
        self.paper.apply(records)
        self.assertEqual(before,self.paper.report())
        replica=PaperLedger(self.root/'replica.sqlite3',self.source.source_id)
        try:
            for row in records:replica.apply([row])
            self.assertEqual(before,replica.report())
            self.assertEqual(self.paper.db.execute('SELECT * FROM audit').fetchall(),replica.db.execute('SELECT * FROM audit').fetchall())
        finally:replica.close()

    def test_crash_transaction_rolls_back_fill_and_checkpoint(self):
        self.signal()
        with patch('daiinas.continuous_store.clock_ms',return_value=221):
            rows=self.source.append([market('tickerV2',221,2)])
        original=self.paper.audit
        def crash(action,**kw):
            original(action,**kw)
            if action=='OPENED':raise OSError('kill between fill and checkpoint')
        with patch.object(self.paper,'audit',side_effect=crash):
            with self.assertRaises(OSError):self.paper.apply(rows)
        self.assertEqual(self.paper.state['cash'],8)
        self.paper.close();self.paper=PaperLedger(self.root/'paper.sqlite3',self.source.source_id)
        self.paper.apply(rows);fee=self.paper.state['fees']
        self.paper.apply(rows)
        self.assertEqual(self.paper.state['fees'],fee)
        self.assertEqual(self.paper.state['counts']['OPENED'],1)

    def test_drawdown_halt_latched_and_deposits_are_not_profit(self):
        self.opened()
        self.close_quote(500,.80,.8002)
        self.assertTrue(self.paper.state['halted'])
        self.close_quote(650,.79,.7902,4)
        self.send(700,('CONTROL','flow:1',{'action':'capital-flow','amount':42.}))
        self.assertTrue(self.paper.state['halted'])
        self.assertAlmostEqual(self.paper.report()['cash_pnl_excluding_external_flows'],self.paper.state['realized'])
        self.send(710,('CONTROL','bad-reset',{'action':'reset-halt','review_note':''}))
        self.assertTrue(self.paper.state['halted'])
        self.send(720,('CONTROL','reviewed-reset',{'action':'reset-halt','review_note':'reviewed gap incident'}))
        self.assertFalse(self.paper.state['halted'])
        self.assertEqual(self.paper.state['counts']['CONTROL_REJECTED'],1)

    def test_legacy_database_and_policy_identity_are_protected(self):
        path=self.root/'legacy.sqlite3'
        c=sqlite3.connect(path);c.execute('CREATE TABLE kv(key,value)');c.close()
        with self.assertRaisesRegex(ValueError,'legacy'):PaperLedger(path,'x')
        with self.assertRaises(ValueError):PaperLedger(self.root/'paper.sqlite3','another-source')
        with self.assertRaises(ValueError):PaperLedger(self.root/'unsafe.sqlite3','x',PaperPolicy(margin_fraction=.9))


class SelectionTests(unittest.TestCase):
    def test_pins_exhausting_soft_capacity_are_retained_without_new_entries(self):
        report={'time_ms':1000,'selected_for_deeper_observation':[{'symbol':'NEW','eligible':True,'liquidity_score_not_alpha':100}]}
        selected=pinned_selection(report,{},['A','B','C','D'],RotationPolicy(deep_slots=3))
        self.assertEqual(set(selected['deep_symbols']),{'A','B','C','D'})
        self.assertTrue(selected['capacity_exhausted'])
        self.assertNotIn('NEW',selected['deep_symbols'])

    def test_future_spec_is_not_available(self):
        packet=scan();packet[2]['report']['paper_contract_specs'][SYM]['captured_ms']=2000
        with self.assertRaises(ValueError):Timeline.scan(packet[2],1000)
