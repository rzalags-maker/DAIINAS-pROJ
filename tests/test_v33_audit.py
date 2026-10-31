"""Independent adverse fixtures; none are actual market observations."""
import json
import unittest
from unittest.mock import patch
import test_continuous_paper as fixtures
from test_continuous_paper import market,SYM


class FinancialAuditTests(unittest.TestCase):
    setUp=fixtures.LedgerTests.setUp
    tearDown=fixtures.LedgerTests.tearDown
    send=fixtures.LedgerTests.send
    signal=fixtures.LedgerTests.signal
    opened=fixtures.LedgerTests.opened
    close_quote=fixtures.LedgerTests.close_quote
    def test_external_flow_during_unresolved_depth_is_not_drawdown(self):
        self.opened()
        self.close_quote(300,1.,1.0002,bid_size=.01,ask_size=.01)
        self.assertEqual(self.paper.state['mark_status'],'UNRESOLVED_DEPTH_INDICATIVE_ONLY')
        before=self.paper.state['last_equity']
        self.send(310,('CONTROL','deposit:depth',{'action':'capital-flow','amount':1.}))
        self.assertAlmostEqual(self.paper.state['last_equity'],before+1.,places=6)
        self.assertFalse(self.paper.state['halted'])

    def test_duplicate_provider_quote_cannot_be_a_later_fill(self):
        self.signal()
        packet=market('tickerV2',120,99)
        packet[2]['received_ms']=221
        packet[2]['wire_received_ms']=221
        self.send(221,packet)
        self.assertIsNone(self.paper.state['position'])
        self.assertIsNotNone(self.paper.state['pending'])

    def test_report_marks_unresolved_equity_as_unavailable(self):
        self.opened()
        self.send(3000,('CLOCK','stale:report',{}))
        r=self.paper.report()
        self.assertIsNone(r['executable_equity'])
        self.assertFalse(r['production_ready'])

    def test_entry_has_independent_observed_cost_basis(self):
        self.opened()
        p=self.paper.state['position']
        self.assertEqual(p['entry_observed_bid'],1.)
        self.assertEqual(p['entry_observed_ask'],1.0002)
        self.assertGreater(p['entry_price'],p['entry_observed_ask'])

    def test_health_rejects_fresh_checkpoint_with_stale_feeds(self):
        from daiinas.continuous_ops import status
        service={'connected':True,'active':[SYM],'verified_books':[SYM],
                 'feed_age_ms':{SYM:{'tickerV2':3000,'level2':3000,'execution':100}}}
        self.send(100,('HEALTH','connected:health',{'state':'CONNECTED','session_id':'health'}),
                  ('CLOCK','clock:health',{'service':service}))
        with patch('daiinas.continuous_ops.time.time_ns',return_value=100000000):
            self.assertFalse(status(self.root/'source.sqlite3',self.root/'paper.sqlite3')['healthy'])

    def test_fee_refresh_uses_new_exit_fee_without_recharging_entry(self):
        from test_continuous_paper import scan,specs
        self.opened();entry=self.paper.state['position']['entry_fee_usdt']
        packet=scan(300);packet[2]['report']['paper_contract_specs']=specs(fee=.0012)
        self.send(300,packet)
        self.close_quote(500,.99,.9902);self.close_quote(650,.98,.9802,4)
        done=json.loads(self.paper.db.execute('SELECT payload FROM closed_positions').fetchone()[0])
        self.assertEqual(done['entry_fee_usdt'],entry)
        self.assertAlmostEqual(done['exit_fee_usdt'],done['exit_price']*done['quantity_contracts']*done['contract_multiplier']*.0012)
        self.assertAlmostEqual(self.paper.state['cash'],8+done['net_pnl_usdt'])

    def test_quote_book_drift_prevents_fill(self):
        self.signal()
        self.send(221,market('tickerV2',221,2,bid=1.0001,ask=1.0003))
        self.assertIsNone(self.paper.state['position'])
        self.assertEqual(self.paper.state['counts']['REJECTED'],1)

    def test_stale_metadata_cannot_reinterpret_or_close_position(self):
        self.opened()
        self.close_quote(601000,.9,.9002)
        self.assertIsNotNone(self.paper.state['position'])
        self.assertEqual(self.paper.state['exit_request']['reason'],'STOP')
        self.assertEqual(self.paper.state['position']['unresolved'],'missing_or_changed_asof_exit_rules')

    def test_actual_sqlite_disk_full_source_rolls_back(self):
        import sqlite3
        pages=self.source.db.execute('PRAGMA page_count').fetchone()[0]
        self.source.db.execute('PRAGMA max_page_count='+str(pages))
        before=self.paper.state['cursor']
        with self.assertRaises(sqlite3.OperationalError):
            self.send(300,('CLOCK','disk:full',{'service':{'large':'x'*1000000}}))
        self.assertEqual(self.paper.state['cursor'],before)
        self.assertEqual(self.source.db.execute('SELECT max(seq) FROM journal').fetchone()[0],before)
        self.source.db.execute('PRAGMA max_page_count=100000')
        self.send(301,('CLOCK','disk:recovered',{}))
        self.assertEqual(self.paper.state['cash'],8.)

    def test_actual_sqlite_full_paper_restores_memory_before_recovery(self):
        import sqlite3
        from copy import deepcopy
        before=deepcopy(self.paper.state)
        pages=self.paper.db.execute('PRAGMA page_count').fetchone()[0]
        self.paper.db.execute('PRAGMA max_page_count='+str(pages))
        with patch('daiinas.continuous_store.clock_ms',return_value=300):
            rows=self.source.append([('CONTROL','deposit:disk',{'action':'capital-flow','amount':1.}),
                ('CLOCK','checkpoint:disk',{'service':{'large':'x'*1000000}})])
        with self.assertRaises(sqlite3.OperationalError):self.paper.apply(rows)
        self.assertEqual(self.paper.state,before)
        self.paper.db.execute('PRAGMA max_page_count=100000')
        self.paper.apply(rows);self.paper.apply(rows)
        self.assertEqual(self.paper.state['cash'],9.)
        self.assertEqual(self.paper.state['external_flows'],1.)

    def test_source_rotation_replace_failure_keeps_original_money(self):
        from daiinas.continuous_ops import rotate_source,verify_backup
        self.opened();before=self.paper.report()
        with patch('daiinas.continuous_ops.os.replace',side_effect=OSError('fixture crash before replace')):
            with self.assertRaises(OSError):rotate_source(self.root/'source.sqlite3',self.root/'paper.sqlite3',self.root/'archive')
        self.assertEqual(self.paper.report(),before)
        self.assertTrue(verify_backup(self.root/'archive')['paper_cursor'])

    def test_interrupted_backup_has_no_verified_manifest(self):
        from daiinas.continuous_ops import backup_pair,verify_backup
        with patch('daiinas.continuous_ops.file_digest',side_effect=OSError('fixture interrupted backup')):
            with self.assertRaises(OSError):backup_pair(self.root/'source.sqlite3',self.root/'paper.sqlite3',self.root/'partial')
        with self.assertRaises(FileNotFoundError):verify_backup(self.root/'partial')

    def test_more_than_twenty_pins_fails_closed(self):
        from daiinas.continuous_store import pinned_selection
        from daiinas.universe_rotation import RotationPolicy
        with self.assertRaisesRegex(ValueError,'hard capacity'):
            pinned_selection({}, {}, [str(i)+'USDTM' for i in range(21)],RotationPolicy())

    def test_backup_holds_source_maintenance_lock(self):
        from contextlib import contextmanager
        from daiinas.continuous_ops import backup_pair
        held=[]
        @contextmanager
        def lock(path):
            held.append(True)
            try:yield
            finally:held.pop()
        def copy(*args):
            self.assertTrue(held)
            return {'locked':True}
        with patch('daiinas.continuous_ops.source_maintenance',lock),patch('daiinas.continuous_ops._backup_pair',copy):
            self.assertTrue(backup_pair('source','paper','dest')['locked'])


import test_continuous_stream as streams
import asyncio

class StreamAuditTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=streams.ContinuousStreamTests.asyncSetUp
    asyncTearDown=streams.ContinuousStreamTests.asyncTearDown

    async def test_unknown_ack_fails_closed(self):
        from daiinas.providers.kucoin import DataGap
        with self.assertRaisesRegex(DataGap,'Unexpected'):
            self.observer.acknowledge({'id':'unknown'})

    async def test_bounded_queue_saturation_disconnects(self):
        class Flood(streams.Socket):
            async def feed(self):
                while not self.active:await asyncio.sleep(.001)
                topic=next(iter(self.active))
                for i in range(500):
                    self.queue.put_nowait({'type':'message','topic':topic,'data':{}})
                await asyncio.Future()
        self.observer.connector=lambda *a,**kw:Flood(self.rest)
        self.observer.queue_size=100
        await self.observer.preflight()
        with self.assertRaises(ExceptionGroup) as ctx:
            await asyncio.wait_for(self.observer.session(),3)
        def leaves(exc):
            if isinstance(exc,BaseExceptionGroup):
                return [x for e in exc.exceptions for x in leaves(e)]
            return [str(exc)]
        self.assertTrue(any('queue overflow' in x for x in leaves(ctx.exception)))
        self.assertFalse(self.observer.connected)


class IndependentArithmeticTests(unittest.TestCase):
    def test_existing_three_positions_reconcile_without_engine_math(self):
        from daiinas.paper_audit import audit_reports
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]/'reports/v33-runs/41251111492'
        read=lambda n:json.loads((root/(n+'.json')).read_text())
        r=audit_reports(read('first'),read('restart'),read('replay'))
        self.assertAlmostEqual(r['final_cash'],7.988656666881493)
        self.assertEqual(len(r['money_event_reconciliation']),6)
        self.assertTrue(all(x['exit_class']=='INFRASTRUCTURE' for x in r['positions']))

    def test_cost_attribution_does_not_charge_spread_twice(self):
        from daiinas.paper_audit import position_costs
        p={'id':'fixture','symbol':SYM,'direction':'LONG','quantity_contracts':1,'contract_multiplier':1,
           'entry_price':101.1,'exit_price':101.9,'entry_fee_usdt':.06,'exit_fee_usdt':.06,
           'entry_notional_usdt':101.1,'holding_ms':0,'gross_pnl_usdt':.8,'modeled_carry_usdt':0,
           'net_pnl_usdt':.68,'planned_loss_usdt':1,'risk_budget_usdt':1,'exit_reason':'TARGET'}
        r=position_costs(p,{'bid':99,'ask':101},{'bid':102,'ask':104})
        self.assertAlmostEqual(r['mid_price_gross_pnl'],3)
        self.assertAlmostEqual(r['spread_cost'],2)
        self.assertAlmostEqual(r['slippage_and_tick_cost'],.2)
        self.assertAlmostEqual(r['mid_price_gross_pnl']-r['round_trip_cost_usdt'],.68)

    def test_tampered_net_is_rejected_by_independent_arithmetic(self):
        from daiinas.paper_audit import audit_reports
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]/'reports/v33-runs/41251111492'
        read=lambda n:json.loads((root/(n+'.json')).read_text())
        final=read('restart');final['recent_closed_positions'][0]['net_pnl_usdt']+=.01
        with self.assertRaises(AssertionError):audit_reports(read('first'),final,read('replay'))

    def test_brief_host_samples_cannot_pass_24h_gate(self):
        from daiinas.host_acceptance import evaluate
        s={'observed_ms':0,'host_id':'synthetic-fixture','source_cursor':1,'live_orders_enabled':False,
           'current_paper_integrity':'ok','healthy':True,'counts':{'SCAN':1}}
        r=evaluate([s,{**s,'observed_ms':60000,'source_cursor':2}],{'paper_cursor':2},{})
        self.assertEqual(r['24h_host_gate'],'NOT_VERIFIED')
        self.assertFalse(r['checks']['at_least_24h'])
        self.assertFalse(r['checks']['independent_host_attested'])
