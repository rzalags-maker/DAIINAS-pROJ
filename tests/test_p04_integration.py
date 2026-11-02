"""Deterministic MOCK integration with the actual v4.7 strategy/ledger. No API writes."""
from dataclasses import replace
from decimal import Decimal as D
import json
import unittest
from unittest.mock import patch

import test_v47_conveyor as fixture
from daiinas.p04_gateway import P04MockWorker,MockExecutionTransport,MockExecutionContract
from daiinas.bitsgap_capabilities import BitsgapCapabilityRegistry
from daiinas.bitsgap_account_acceptance import AccountAcceptance


class GatewayTests(unittest.TestCase):
    setUp=fixture.ConveyorTests.setUp
    tearDown=fixture.ConveyorTests.tearDown
    send=fixture.ConveyorTests.send
    heartbeat=fixture.ConveyorTests.heartbeat
    train=fixture.ConveyorTests.train
    native_exit=fixture.ConveyorTests.native_exit

    def start(self,*,mode='START_PAPER',outcome='ACKNOWLEDGED',contract=None,registry=None,**kwargs):
        fixture.ConveyorTests.start(self,symbols=('UPUSDTM',),**kwargs)
        self.transport=MockExecutionTransport(outcome=outcome);self.auto=True
        with patch('daiinas.continuous_store.clock_ms',return_value=0):
            self.worker=P04MockWorker(self.source,self.paper,registry=registry or BitsgapCapabilityRegistry.documented(),
                contract=contract or MockExecutionContract(),transport=self.transport)
            if mode!='OBSERVE':self.worker.control(mode,request_id='owner-start',actor='test-owner')

    def quote(self,*args,**kwargs):
        rows=fixture.ConveyorTests.quote(self,*args,**kwargs)
        if self.auto:
            with patch('daiinas.continuous_store.clock_ms',return_value=self.paper.state['now_ms']):
                self.worker.submit_pending()
        return rows

    def mode(self,mode,request):
        with patch('daiinas.continuous_store.clock_ms',return_value=self.paper.state['now_ms']):
            return self.worker.control(mode,request_id=request,actor='test-owner')

    def restart(self):
        self.paper.close()
        self.paper=fixture.PortfolioLedger(self.root/'paper.sqlite3',self.source.source_id,self.policy,portfolio=self.pp)
        with patch('daiinas.continuous_store.clock_ms',return_value=self.paper.state['now_ms']):
            self.worker=P04MockWorker(self.source,self.paper,registry=BitsgapCapabilityRegistry.documented(),
                contract=MockExecutionContract(),transport=self.transport)

    def test_observe_default_and_live_blocked_never_submits(self):
        self.start(mode='OBSERVE');self.train()
        self.assertFalse(self.transport.calls);self.assertFalse(self.paper.state['positions'])
        for mode in ('OBSERVE','START_PAPER','PAUSE','STOP','HALT'):
            self.mode(mode,'mode-'+mode)
            status=self.mode('START_LIVE','live-'+mode)
            self.assertEqual(status['result'],'START_LIVE_BLOCKED_NO_LIVE_TRANSPORT')
            self.assertFalse(status['orders_enabled'])
        self.assertFalse(self.transport.calls)

    def test_ack_is_not_fill_and_existing_strategy_drives_fill_and_protection(self):
        self.start();self.auto=False;t=self.train(n=15)
        self.assertTrue(self.paper.state['pending_entries']);self.assertFalse(self.paper.state['positions'])
        with patch('daiinas.continuous_store.clock_ms',return_value=self.paper.state['now_ms']):self.worker.submit_pending()
        self.assertTrue(self.transport.calls);self.assertFalse(self.paper.state['positions'])
        intent=next(iter(self.paper.state['pending_entries'].values()))
        self.quote('UPUSDTM',t,1.003**14)
        self.quote('UPUSDTM',t+200,1.003**14)
        self.assertTrue(self.paper.state['positions'])
        self.assertEqual(next(iter(self.paper.state['positions'].values()))['protection']['state'],'MODELED_ACKED')
        self.assertFalse(self.paper.state.get('pending_native_receipts'))

    def test_whole_cycle_settles_once_and_replacement_uses_same_ledger(self):
        self.start();t=self.train();s=self.paper.state
        self.assertTrue(s['positions'])
        p=next(iter(s['positions'].values()));target=float(p['planned_target_mid'])
        reserve=self.paper.ladder().reserve
        self.quote('UPUSDTM',t+200,target+.002);rows=self.quote('UPUSDTM',t+400,target+.002)
        self.paper.apply(rows)
        self.assertFalse(s['positions']);self.assertEqual(s['counts']['REALIZED_NET_TRADE'],1)
        self.assertEqual(s['counts']['INITIAL_FUNDING'],1);self.assertEqual(self.paper.ladder().reserve,reserve)
        self.assertEqual(self.paper.ladder().realized_net,D(s['realized']))
        # Same scanner/ledger discovers a fresh independent symbol after settlement.
        kind,_,payload=fixture.f.scan(extra={sym:{**fixture.f.specs(sym)[sym],'max_leverage':'5','margin_mode':'ISOLATED'} for sym in ('UPUSDTM','NEXTUSDTM')})
        self.send(t+600,(kind,'p04-replacement-scan',payload))
        self.train(symbols=('NEXTUSDTM',),start=t+1000)
        self.assertIn('NEXTUSDTM|LONG',s['positions']);self.paper.invariant()
        command_ids=[c['command_id'] for c in self.transport.calls]
        self.assertEqual(len(command_ids),len(set(command_ids)))

    def test_partial_entry_exit_and_native_duplicate_settle_only_final_close(self):
        self.start();t=self.train(entry_depth=2);s=self.paper.state
        p=next(iter(s['positions'].values()));self.assertEqual(D(p['quantity_contracts']),2)
        packet=self.native_exit(p,t,quantity=D('1'),fill_id='partial')
        rows=self.send(t,('CONTROL','partial-native',{'action':'native-mock-fill','receipt':packet}))
        self.paper.apply(rows)
        self.assertEqual(D(next(iter(s['positions'].values()))['quantity_contracts']),1)
        self.assertEqual(s['counts'].get('REALIZED_NET_TRADE',0),0)
        p=next(iter(s['positions'].values()));packet=self.native_exit(p,t+100,fill_id='final')
        self.send(t+100,('CONTROL','final-native',{'action':'native-mock-fill','receipt':packet}))
        self.send(t+101,('CONTROL','duplicate-native',{'action':'native-mock-fill','receipt':packet}))
        self.assertFalse(s['positions']);self.assertEqual(s['counts']['REALIZED_NET_TRADE'],1)
        self.assertEqual(s['counts']['INITIAL_FUNDING'],1)

    def test_uncertain_ack_restart_stop_preserves_reserved_exposure_without_retry(self):
        self.start(outcome='UNCERTAIN');self.train();s=self.paper.state
        self.assertTrue(s['pending_entries']);self.assertTrue(s['pending_native_receipts']);self.assertFalse(s['positions'])
        calls=len(self.transport.calls);self.restart();self.assertEqual(self.worker.status()['mode'],'OBSERVE')
        self.mode('START_PAPER','restart-owner');self.worker.submit_pending()
        self.assertEqual(len(self.transport.calls),calls)
        result=self.mode('STOP','owner-stop')
        self.assertEqual(result['stop_state'],'STOPPED_WITH_EXPOSURE')
        self.assertTrue(self.paper.state['pending_entries'])
        self.assertFalse(self.paper.session_armed())

    def test_stop_ack_with_open_position_then_offline_close_and_replay(self):
        self.start();t=self.train();s=self.paper.state;p=next(iter(s['positions'].values()))
        stopped=self.mode('STOP','stop-with-position');self.assertEqual(stopped['stop_state'],'STOPPED_WITH_EXPOSURE')
        packet=self.native_exit(p,t+100,fill_id='offline-close')
        self.restart()
        self.send(t+100,('CONTROL','offline-close',{'action':'native-mock-fill','receipt':packet}))
        self.assertFalse(self.paper.state['positions'])
        self.assertEqual(self.paper.state['counts']['REALIZED_NET_TRADE'],1)
        replica=fixture.replay([self.source.path],self.root/'replayed.sqlite',self.policy,
            ledger_factory=fixture.PortfolioLedger,ledger_options={'portfolio':self.pp})
        self.assertEqual(replica,self.paper.report())

    def test_missing_mock_protection_rejects_entry(self):
        self.start(contract=MockExecutionContract(protective_tp_sl=False));self.train()
        self.assertFalse(self.transport.calls);self.assertFalse(self.paper.state['positions'])

    def test_unsupported_order_type_no_trade(self):
        self.start(contract=MockExecutionContract(order_types=('LIMIT',)));self.train()
        self.assertFalse(self.transport.calls);self.assertFalse(self.paper.state['positions'])

    def test_provider_null_foreign_or_stale_account_evidence_blocks_new_mock_orders(self):
        self.start()
        evidence=AccountAcceptance(0,1,False,'VALIDATED','PROVIDER_NO_DATA','PROVIDER_NO_DATA','ONE_WAY','CONNECTED')
        with patch('daiinas.continuous_store.clock_ms',return_value=0):self.worker.observe_account(evidence)
        self.train();self.assertFalse(self.transport.calls)
        self.assertIn('p04_account',self.worker.status()['entry_blocker'])

    def test_invalid_live_transport_rejected(self):
        self.start()
        with self.assertRaisesRegex(ValueError,'ONLY_EXPLICIT_MOCK'):
            P04MockWorker(self.source,self.paper,registry=BitsgapCapabilityRegistry.documented(),
                contract=MockExecutionContract(),transport=object())

    def test_crash_between_claim_and_ack_cannot_resubmit(self):
        self.start()
        with patch.object(self.transport,'submit',side_effect=RuntimeError('synthetic crash')) as call:
            self.train();self.assertEqual(call.call_count,1)
        self.assertTrue(self.paper.state['pending_native_receipts'])
        self.restart();self.mode('START_PAPER','owner-restart')
        self.worker.submit_pending();self.assertFalse(self.transport.calls)

    def test_stop_flat_requires_confirmed_mock_cancellation_not_timeout(self):
        self.start(outcome='UNCERTAIN');self.train();self.mode('STOP','stop')
        intent=next(iter(self.paper.state['pending_entries'].values()))
        order=self.paper.state['venue_orders'][intent['order_ids']['entry']]
        proof={'source_kind':'MOCK_CANCEL_RECONCILIATION','command_id':order['gateway_command_id'],
            'intent_digest':order['gateway_intent_digest'],'complete':True,'filled_quantity':'0','remaining_quantity':'0'}
        with patch('daiinas.continuous_store.clock_ms',return_value=self.paper.state['now_ms']):self.worker.reconcile_cancel(proof)
        self.assertEqual(self.worker.status()['stop_state'],'STOPPED_FLAT')
        self.assertFalse(self.paper.state['pending_native_receipts'])
        self.assertFalse(self.paper.state['pending_entries'])

    def test_invalid_fill_cost_margin_or_leverage_retains_exposure(self):
        self.start();t=self.train();p=next(iter(self.paper.state['positions'].values()))
        packet=self.native_exit(p,t,fill_id='bad-fee',fee='NaN')
        before=self.paper.state['fees']
        self.send(t,('CONTROL','invalid-fee',{'action':'native-mock-fill','receipt':packet}))
        self.assertEqual(self.paper.state['fees'],before);self.assertTrue(self.paper.state['positions'])
        self.assertTrue(self.paper.state['pending_native_receipts'])
        packet=self.native_exit(p,t+1,fill_id='bad-leverage');packet['leverage']=99
        self.send(t+1,('CONTROL','invalid-leverage',{'action':'native-mock-fill','receipt':packet}))
        packet=self.native_exit(p,t+2,fill_id='bad-margin');packet['authority']['free_margin']='999999'
        self.send(t+2,('CONTROL','invalid-margin',{'action':'native-mock-fill','receipt':packet}))
        self.assertEqual(self.paper.state['fees'],before);self.assertTrue(self.paper.state['positions'])

    def test_model_a_200_keeps_reserve_and_original_funding_once(self):
        self.start(capital='200')
        self.assertEqual(self.paper.ladder().reserve,D('50'))
        self.assertEqual(self.paper.ladder().active,D('150'))
        self.assertEqual(self.paper.ladder().slot_ceiling,6)
        opening=dict(self.paper.state['initial_funding']);self.train();self.restart()
        self.assertEqual(self.paper.state['initial_funding'],opening)
        self.assertEqual(self.paper.state['counts']['INITIAL_FUNDING'],1)
        self.assertEqual(self.paper.ladder().reserve,D('50'))

    def test_loss_settlement_reduces_active_not_protected_reserve(self):
        from daiinas.adaptive_execution import cash
        self.start(capital='300');t=self.train();p=next(iter(self.paper.state['positions'].values()))
        reserve=self.paper.ladder().reserve;active=self.paper.ladder().active
        packet=self.native_exit(p,t,fill_id='loss');packet['price']=str(D(p['entry_price'])-D('.01'))
        gross=cash((D(packet['price'])-D(p['entry_price']))*D(p['contract_multiplier'])*D(p['quantity_contracts']))
        packet['authority']['cash']=str(D(self.paper.state['cash'])+gross-D(packet['fee']))
        self.send(t,('CONTROL','loss-native',{'action':'native-mock-fill','receipt':packet}))
        self.assertLess(self.paper.ladder().active,active);self.assertEqual(self.paper.ladder().reserve,reserve)
        self.assertEqual(self.paper.state['counts']['REALIZED_NET_TRADE'],1)
        self.assertFalse(self.paper.state['positions']);self.paper.invariant()

    def test_pause_keeps_risk_monitoring_and_blocks_new_mock_submission(self):
        self.start();t=self.train();self.mode('PAUSE','pause')
        self.assertTrue(self.paper.state['positions']);before=len(self.transport.calls)
        self.quote('UPUSDTM',t+500,1.003**16)
        self.assertEqual(len(self.transport.calls),before)
        self.assertEqual(self.worker.status()['mode'],'PAUSE')

    def test_connection_loss_disarms_until_a_new_owner_command(self):
        self.start();self.train();before=len(self.transport.calls)
        now=self.paper.state['now_ms']
        self.send(now,('HEALTH','p04-disconnect',{'state':'CONNECTION_LOSS'}))
        self.assertEqual(self.worker.status()['mode'],'OBSERVE');self.assertFalse(self.paper.session_armed())
        self.send(now+1,('HEALTH','p04-reconnect',{'state':'CONNECTED','session_id':'synthetic-reconnected'}))
        self.worker.submit_pending();self.assertEqual(len(self.transport.calls),before)
        self.assertEqual(self.worker.status()['mode'],'OBSERVE')

    def test_late_ack_after_stop_never_claims_flat_without_cancel_proof(self):
        self.start(outcome='UNCERTAIN');self.train();self.mode('STOP','stop-late')
        intent=next(iter(self.paper.state['pending_entries'].values()))
        order=self.paper.state['venue_orders'][intent['order_ids']['entry']]
        ack={'source_kind':'MOCK_GATEWAY_ACK','command_id':order['gateway_command_id'],
            'intent_digest':order['gateway_intent_digest'],'outcome':'ACKNOWLEDGED'}
        with patch('daiinas.continuous_store.clock_ms',return_value=self.paper.state['now_ms']):self.worker.reconcile_ack(ack)
        self.assertEqual(self.worker.status()['stop_state'],'STOPPED_WITH_EXPOSURE')
        self.assertTrue(self.paper.state['pending_native_receipts'])

    def test_invalid_ack_is_quarantined_without_poisoning_the_journal(self):
        self.start(outcome='UNCERTAIN');self.train()
        intent=next(iter(self.paper.state['pending_entries'].values()))
        order=self.paper.state['venue_orders'][intent['order_ids']['entry']]
        ack={'source_kind':'MOCK_GATEWAY_ACK','command_id':order['gateway_command_id'],
             'intent_digest':'FOREIGN','outcome':'ACKNOWLEDGED'}
        with patch('daiinas.continuous_store.clock_ms',return_value=self.paper.state['now_ms']):self.worker.reconcile_ack(ack)
        self.assertTrue(self.paper.state['pending_native_receipts'])
        self.assertEqual(self.paper.state['counts']['P04_COMMAND_REJECTED'],1)
        self.mode('STOP','stop-after-invalid')
        self.assertEqual(self.worker.status()['mode'],'STOP')

    def test_contract_change_cannot_silently_reuse_an_older_permission(self):
        self.start()
        with patch('daiinas.continuous_store.clock_ms',return_value=self.paper.state['now_ms']):
            with self.assertRaisesRegex(ValueError,'CONTRACT_CHANGE'):
                P04MockWorker(self.source,self.paper,registry=BitsgapCapabilityRegistry.documented(),
                    contract=MockExecutionContract(protective_tp_sl=False),transport=self.transport)
        self.assertTrue(self.paper.state['p04_gateway']['contract']['protective_tp_sl'])
        self.assertFalse(self.transport.calls)

    def test_real_accountstate_type_bridges_to_mock_gate_without_funding_it(self):
        import test_bitsgap_account_state as accounts
        a=accounts.AccountStateTests();a.setUp();a.connect()
        a.pair('balance',a.wire.balance);a.pair('orders',None);a.pair('positions',None)
        evidence=AccountAcceptance.from_state(a.state,expected_market_id=72,expected_scope_ref='synthetic-owner-scope')
        self.start();opening=self.paper.state['initial_funding']
        with patch('daiinas.continuous_store.clock_ms',return_value=1000):self.worker.observe_account(evidence)
        self.train(start=1100)
        self.assertFalse(self.transport.calls);self.assertEqual(self.paper.state['initial_funding'],opening)
        self.assertTrue(self.paper.state['p04_gateway']['account_evidence']['blockers'])
        self.assertFalse(self.worker.status()['orders_enabled'])

    def test_account_generation_regression_cannot_lower_the_high_water_mark(self):
        self.start()
        for generation in (2,1,1):
            e=AccountAcceptance(0,generation,True,'VALIDATED','VERIFIED_EMPTY','VERIFIED_EMPTY','ONE_WAY','CONNECTED')
            with patch('daiinas.continuous_store.clock_ms',return_value=0):self.worker.observe_account(e)
        saved=self.paper.state['p04_gateway']['account_evidence']
        self.assertEqual(saved['generation'],2)
        self.assertIn('ACCOUNT_GENERATION_OR_TIME_REGRESSION',saved['blockers'])

    def test_optional_owner_session_expiry_is_preserved(self):
        self.start(mode='OBSERVE')
        with patch('daiinas.continuous_store.clock_ms',return_value=0):
            self.worker.control('START_PAPER',request_id='bounded',actor='local-owner',duration_ms=1000)
        self.send(1001,('CLOCK','expired-bounded',{}))
        self.assertFalse(self.paper.session_armed())
        self.assertEqual(self.paper.state['session']['stop_reason'],'SESSION_EXPIRED')
        self.assertIsNotNone(self.worker.status()['entry_blocker'])
        self.assertFalse(self.transport.calls)

    def test_missing_provider_order_capability_blocks_existing_strategy_admission(self):
        from test_bitsgap_capabilities import catalog
        wire=catalog();del wire.manual['data']['order_place']
        registry=BitsgapCapabilityRegistry.from_catalogs(wire.manual,wire.enums,observed_ms=0)
        self.start(registry=registry);self.train()
        self.assertFalse(self.transport.calls)
        self.assertEqual(self.worker.status()['entry_blocker'],'p04_order_capability_unavailable')


class PipelineGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_single_writer_pipeline_enables_mock_only_and_boot_disarms(self):
        import tempfile
        from pathlib import Path
        from daiinas.continuous_paper import Pipeline
        from daiinas.v47 import configuration
        from daiinas.paper_micro import PaperPolicy
        config=configuration('200','isolated-p04-pipeline',timestamp_ms=0)
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'source.sqlite';paper=Path(d)/'paper.sqlite'
            pipeline=Pipeline(source,paper,PaperPolicy(**config['paper']),ledger_factory=fixture.PortfolioLedger,
                ledger_options={'portfolio':config['portfolio']},gateway_contract={})
            try:
                self.assertEqual((await pipeline.report())['p04_gateway']['mode'],'OBSERVE')
                await pipeline.poll_account()
                self.assertEqual((await pipeline.report())['session']['state'],'NOT_STARTED')
                live=await pipeline.gateway_control('START_LIVE',request_id='denied',actor='local-owner')
                self.assertEqual(live['result'],'START_LIVE_BLOCKED_NO_LIVE_TRANSPORT')
                started=await pipeline.gateway_control('START_PAPER',request_id='paper',actor='local-owner')
                self.assertEqual(started['mode'],'START_PAPER')
                stopped=await pipeline.gateway_control('STOP',request_id='stop',actor='local-owner')
                self.assertEqual(stopped['stop_state'],'STOPPED_FLAT')
                self.assertFalse(stopped['orders_enabled'])
            finally:pipeline.close()
            pipeline=Pipeline(source,paper,PaperPolicy(**config['paper']),ledger_factory=fixture.PortfolioLedger,
                ledger_options={'portfolio':config['portfolio']},gateway_contract={})
            try:
                report=await pipeline.report()
                self.assertEqual(report['p04_gateway']['mode'],'OBSERVE')
                self.assertEqual(report['counts']['INITIAL_FUNDING'],1)
            finally:pipeline.close()
