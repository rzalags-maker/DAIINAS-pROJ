"""P05.1 offline injected sessions. All credentials and account data are synthetic."""
import asyncio
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from daiinas import bitsgap_account_acceptance as acceptance
from daiinas import bitsgap_futures_cli as legacy
from daiinas.bitsgap_account_state import AccountState, AccountStateError, PrivateStore, session_sample
from daiinas.bitsgap_account_visibility import load_state, visibility
from daiinas.bitsgap_futures_observe import BitsgapFuturesObserver
from daiinas.bitsgap_futures_stream import BitsgapFuturesStream
from daiinas.bitsgap_read_budget import AccountReadBudget
from daiinas.bitsgap_readonly import BitsgapError
import test_bitsgap_account_state as state_fixtures
from test_bitsgap_futures_observe import FakeWire, new_pem
from test_bitsgap_futures_stream import FakeWS


class SessionCohortTests(unittest.TestCase):
    def setUp(self):
        self.h = state_fixtures.AccountStateTests('runTest')
        self.h.setUp()
        self.h.connect()
        self.samples = acceptance.SessionEvidence()
        self.state = self.h.state
        self.state.transport_diagnostics = {'ws_auth_succeeded_in_last_session':True,
            'ws_last_failure':'NONE', 'ws_disconnects':1}

    def pair_all(self):
        for topic, value in (('balance',self.h.wire.balance),('orders',self.h.wire.orders),
                             ('positions',self.h.wire.positions),('positions_settings',self.h.wire.settings)):
            self.h.pair(topic,value)
        self.samples.capture(session_sample(self.state))

    def report(self):
        return self.samples.report(self.state,catalog={'balance':'LIVE_DISCOVERED'},now_ms=self.h.now)

    def test_explicit_empty_observation_pass_is_never_financial_permission(self):
        self.pair_all()
        self.state.connection('DISCONNECTED')
        result=self.report()
        self.assertEqual(result['status'],'PASS')
        self.assertEqual(result['connection_after_stop'],'DISCONNECTED')
        self.assertEqual(result['financial_admission'],'BLOCKED')
        self.assertEqual(result['new_entry'],'NO_TRADE_ACCOUNT_NOT_RECONCILED')
        self.assertEqual(result['terminal_parity'],'PENDING_OWNER_VERIFICATION')
        self.assertFalse(result['orders_enabled'])
        text=json.dumps(result)
        for sensitive in ('913.2468','812.1357','synthetic-owner-scope','fingerprint','market_id','count"'):
            self.assertNotIn(sensitive,text)

    def test_lifecycle_hook_is_a_redacted_projection_not_private_service(self):
        self.pair_all()
        sample=session_sample(self.state)
        self.assertIsInstance(sample,dict)
        text=json.dumps(sample)
        for sensitive in ('913.2468','812.1357','synthetic-owner-scope','fingerprint','values','count"'):
            self.assertNotIn(sensitive,text)
        self.assertNotIn('records',sample)

    def test_null_inventory_is_partial_and_not_zero(self):
        self.h.wire.orders=self.h.wire.positions=None
        self.pair_all()
        report=self.report()
        self.assertEqual(report['status'],'PARTIAL')
        self.assertIn('NULL_IS_NOT_ZERO',report['reasons'])
        self.assertIn('EXPOSURE_UNVERIFIED',report['reasons'])
        self.assertEqual(report['session_evidence']['topics']['positions']['state'],'PROVIDER_NO_DATA')

    def test_active_api_inventory_is_not_full_account_proof(self):
        self.h.wire.orders = {'data': {'BTC_USDT': [{'id':'SYNTHETIC_ORDER','eost':4,
            'eot':1,'eos':1,'epps':1,'t0':1,'pr':'2','am':'3'}]}, 'cnt':1}
        self.h.wire.positions = {'data': {'BTC_USDT': [{'epps':1,'eps':1,
            'am':'3','pr':'2'}]}, 'cnt':1,'epmd':1,'epm':2}
        self.pair_all()
        report=self.report()
        self.assertEqual(report['status'],'PASS')
        self.assertEqual(report['session_evidence']['topics']['orders']['state'],'VERIFIED_ACTIVE')
        self.assertEqual(report['session_evidence']['topics']['positions']['state'],'VERIFIED_ACTIVE')
        self.assertEqual(report['full_exposure_completeness'],'UNVERIFIED')
        self.assertNotIn('SYNTHETIC_ORDER',json.dumps(report))

    def test_schema_mismatch_blocks_wallet(self):
        self.h.pair('balance',{'data':{'USDT':{'t':'bad-private-value','a':'0'}}})
        self.samples.capture(session_sample(self.state))
        self.assertEqual(self.report()['status'],'BLOCKED')
        self.assertNotIn('bad-private-value',json.dumps(self.report()))

    def test_foreign_scope_never_establishes_cohort(self):
        with self.assertRaisesRegex(AccountStateError,'ACCOUNT_SCOPE_MISMATCH'):
            self.h.push('balance',self.h.wire.balance,market_id=71)
        self.samples.capture(session_sample(self.state))
        self.assertEqual(self.report()['status'],'BLOCKED')

    def test_stale_cohort_is_not_rejuvenated_at_stop(self):
        self.pair_all()
        self.h.now+=15001
        self.assertEqual(self.report()['status'],'BLOCKED')
        self.assertIn('ACCOUNT_EVIDENCE_STALE',self.report()['reasons'])

    def test_differing_source_phase_never_validates(self):
        self.h.push('balance',self.h.wire.balance)
        self.h.push('balance',self.h.wire.balance,'WS',when=7001)
        self.samples.capture(session_sample(self.state))
        report=self.report()
        self.assertEqual(report['status'],'BLOCKED')
        self.assertIn('OBSERVATION_WINDOW_MISMATCH',report['reasons'])

    def test_reconnect_drops_prior_generation(self):
        self.pair_all()
        self.state.connection('CONNECTING')
        self.samples.capture(session_sample(self.state))
        self.assertEqual(self.report()['status'],'BLOCKED')
        self.assertNotIn('session_evidence',self.report())

    def test_no_evidence_timeout_is_blocked(self):
        self.assertEqual(self.report()['status'],'BLOCKED')

    def test_real_transport_failure_is_not_normal_stop(self):
        self.pair_all()
        self.state.transport_diagnostics['ws_last_failure']='PRIVATE_REMOTE_ERROR'
        result=self.report()
        self.assertEqual(result['status'],'PARTIAL')
        self.assertIn('TRANSPORT_INTERRUPTED',result['reasons'])
        self.assertNotIn('PRIVATE_REMOTE_ERROR',json.dumps(result))

    def test_unchanged_subscription_does_not_refresh_timestamps(self):
        self.pair_all()
        first=self.samples.latest['oldest_receipt_ms']['balance']
        self.h.now+=1000
        self.h.push('balance',self.h.wire.balance,'WS')
        self.samples.capture(session_sample(self.state))
        self.assertEqual(self.samples.latest['oldest_receipt_ms']['balance'],first)


class WriterIncarnationTests(unittest.TestCase):
    def test_new_lease_cannot_revive_old_connected_payload(self):
        h=state_fixtures.AccountStateTests('runTest');h.setUp()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{},clear=True):
            path=Path(directory)/'account.sqlite'
            with contextlib.ExitStack() as stack:
                writer=PrivateStore(path)
                h.state=h.make_state(store=writer);h.connect();h.pair('balance',h.wire.balance)
                reader=PrivateStore(path,readonly=True);stack.callback(reader.close)
                current=load_state(reader,'synthetic-owner-scope',clock_ms=lambda:1100)
                self.assertTrue(visibility(current)['balance_current'])
                writer.close()  # Crash model: no DISCONNECTED checkpoint.
                replacement=PrivateStore(path);stack.callback(replacement.close)
                self.assertFalse(visibility(current)['balance_current'])
                stale=load_state(reader,'synthetic-owner-scope',clock_ms=lambda:1100)
                self.assertFalse(visibility(stale)['balance_current'])
                self.assertEqual(stale.status()['connection'],'DISCONNECTED')
                new=h.make_state(store=replacement)
                self.assertFalse(new.connected)

    def test_expired_heartbeat_rejects_held_lease(self):
        h=state_fixtures.AccountStateTests('runTest');h.setUp()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{},clear=True):
            writer=PrivateStore(Path(directory)/'account.sqlite')
            try:
                h.state=h.make_state(store=writer);h.connect();h.pair('balance',h.wire.balance)
                reader=PrivateStore(writer.path,readonly=True)
                try:
                    state=load_state(reader,'synthetic-owner-scope',clock_ms=lambda:16001)
                    self.assertEqual(state.status()['connection'],'DISCONNECTED')
                finally:reader.close()
            finally:writer.close()


class BoundaryTests(unittest.TestCase):
    def test_all_private_paths_reject_ci_and_noninteractive_before_credentials(self):
        from daiinas.bitsgap_account_state import main as state_main
        from daiinas.bitsgap_account_visibility import main as visibility_main
        commands=((legacy.main,['--private-panel']),
            (state_main,['--status','--private-panel','--scope-ref','test']),
            (visibility_main,['--private-panel','--state-file','unused','--scope-ref','test']))
        for env,stdin_tty,stdout_tty in (({'CI':'true'},True,True),({},False,True),({},True,False)):
            for command,args in commands:
                with self.subTest(env=env,command=command.__module__,stdin=stdin_tty,stdout=stdout_tty):
                    output=io.StringIO()
                    with patch.dict(os.environ,env,clear=True), contextlib.redirect_stdout(output), \
                            patch('sys.stdin.isatty',return_value=stdin_tty), \
                            patch.object(output,'isatty',return_value=stdout_tty), \
                            patch.object(legacy,'BitsgapFuturesObserver',side_effect=AssertionError('private marker')):
                        self.assertEqual(command(args),2)
                    self.assertIn('PRIVATE_OUTPUT_DISALLOWED',output.getvalue())
                    self.assertNotIn('private marker',output.getvalue())

    def test_explicit_credential_file_checks_use_only_synthetic_files(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{},clear=True):
            path=Path(directory)/'synthetic.pem';path.write_text('synthetic-key');path.chmod(0o600)
            self.assertEqual(acceptance._credential(path),'synthetic-key')
            path.chmod(0o644)
            with self.assertRaises(AccountStateError):acceptance._credential(path)
            path.chmod(0o600)
            link=Path(directory)/'link';link.symlink_to(path)
            with self.assertRaises(AccountStateError):acceptance._credential(link)
            with patch.dict(os.environ,{'CI':'true'}):
                with self.assertRaisesRegex(AccountStateError,'DISALLOWED_IN_CI'):acceptance._credential(path)

    def test_missing_credential_report_is_redacted_and_noninteractive(self):
        with patch.dict(os.environ,{},clear=True), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(acceptance.main(['--observe','--_worker','--seconds','1']),2)
        self.assertEqual(json.loads(out.getvalue())['reasons'],['CREDENTIAL_NOT_CONFIGURED'])

    def test_outer_deadline_is_bounded_and_never_prints_partial_output(self):
        exc=subprocess.TimeoutExpired('synthetic',1,output='PRIVATE_RAW_DATA',stderr='PRIVATE_KEY')
        with patch.object(subprocess,'run',side_effect=exc) as run,contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(acceptance.main(['--observe','--seconds','60']),2)
        self.assertEqual(run.call_args.kwargs['timeout'],145)
        self.assertEqual(json.loads(out.getvalue())['reasons'],['SESSION_DEADLINE_EXCEEDED'])
        self.assertNotIn('PRIVATE',out.getvalue())

    def test_real_headless_parent_child_missing_credential(self):
        result=subprocess.run([sys.executable,'-B','-m','daiinas.bitsgap_account_acceptance',
            '--observe','--seconds','1'],env={'PATH':os.defpath},capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,2)
        self.assertEqual(json.loads(result.stdout)['reasons'],['CREDENTIAL_NOT_CONFIGURED'])
        self.assertEqual(result.stderr,'')

    def test_worker_fixed_errors_never_forward_exception_values(self):
        for error in (RuntimeError('PRIVATE_KEY'),BitsgapError('PRIVATE_BALANCE')):
            with patch.object(acceptance,'_credential',side_effect=error),contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(acceptance.main(['--observe','--_worker','--seconds','1']),2)
            self.assertNotIn('PRIVATE_KEY',out.getvalue());self.assertNotIn('PRIVATE_BALANCE',out.getvalue())


class RealStreamBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_startup_and_reconnect_share_actual_settings_budget(self):
        _,pem=new_pem();wire=FakeWire();times=[]
        def transport(*args):
            body=json.loads(args[1])
            if body['topic']=='positions_settings':times.append(time.monotonic())
            return wire(*args)
        observer=BitsgapFuturesObserver(pem,transport=transport);observer.discover()
        stream=BitsgapFuturesStream(observer)
        self.assertIsInstance(observer.request_budget,AccountReadBudget)
        class TimedWS(FakeWS):
            async def send(self,msg):
                if isinstance(json.loads(msg),list):times.append(time.monotonic())
                await super().send(msg)
        async def event(_):pass
        for _ in range(2):
            ws=TimedWS([{'type':'auth_ok','sid':'synthetic'},
                {'ok':True,'topic':'balance','params':{'em':72},'value':wire.balance}])
            await stream.watch_once(lambda _:ws,on_event=event,max_messages=1)
        self.assertEqual(len(times),6)
        self.assertTrue(all(b-a>=0.99 for a,b in zip(times,times[1:])))
        self.assertGreaterEqual(times[-1]-times[0],9.99)  # 5 per 10 seconds.

    async def test_headless_injected_full_session_captures_before_normal_stop(self):
        _,pem=new_pem();wire=FakeWire();observer=BitsgapFuturesObserver(pem,transport=wire)
        class QuietWS(FakeWS):
            async def recv(self):
                if self.frames:return await super().recv()
                await asyncio.Event().wait()
        frames=[{'type':'auth_ok','sid':'PRIVATE_SESSION'}]+[
            {'ok':True,'topic':topic,'params':{'em':72},'value':value}
            for topic,value in (('balance',wire.balance),('orders',wire.orders),
                                ('positions',wire.positions),('positions_settings',wire.settings))]
        prior=AccountReadBudget()
        observer.request_budget=prior
        result=await acceptance.observe_session(observer,lambda _:QuietWS(frames),seconds=5)
        self.assertIs(observer.request_budget,prior)
        self.assertFalse(prior.stopped.is_set())
        self.assertGreaterEqual(len(prior.events['positions_settings']),4)
        child=prior.fork()
        self.assertIs(child.events,prior.events)
        child.stop()
        self.assertFalse(prior.stopped.is_set())
        self.assertEqual(result['status'],'PASS')
        self.assertEqual(result['connection_after_stop'],'DISCONNECTED')
        self.assertGreater(result['observation_samples'],0)
        self.assertNotIn('61.07',json.dumps(result))
        self.assertNotIn('PRIVATE_SESSION',json.dumps(result))
        self.assertFalse(result['orders_enabled'])
