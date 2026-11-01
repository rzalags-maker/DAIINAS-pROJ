"""Synthetic private acceptance fixtures, never a live account test."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_bitsgap_account_state as fixtures
from daiinas.bitsgap_account_state import AccountState, AccountStateError, PrivateStore, main as observer_main
from daiinas.bitsgap_account_visibility import compare_terminal, load_state, main, visibility


class VisibilityTests(unittest.TestCase):
    setUp = fixtures.AccountStateTests.setUp
    make_state = fixtures.AccountStateTests.make_state
    connect = fixtures.AccountStateTests.connect
    push = fixtures.AccountStateTests.push
    pair = fixtures.AccountStateTests.pair

    def ready(self):
        self.connect()
        for topic, value in (("balance", self.wire.balance), ("orders", self.wire.orders),
                ("positions", self.wire.positions), ("positions_settings", self.wire.settings)):
            self.pair(topic, value)

    def terminal(self, **kwargs):
        t = {"total": "913.25", "available": "812.14", "precision": 2,
            "observed_ms": self.now, "open_orders": 0, "positions": 0,
            "position_mode": "ONE_WAY", "same_account_confirmed": True,
            "identity_basis": "OWNER_CONFIRMED_KEY_BOUND_MARKET"}
        t.update(kwargs)
        return t

    def test_current_private_view_scope_provenance_and_disabled_execution(self):
        self.ready();v = visibility(self.state, private=True)
        self.assertTrue(v['balance_current']);self.assertEqual(v['market_id'], 72)
        self.assertEqual(v['available_reported'], '812.1357')
        self.assertEqual(v['currency'], 'USDT');self.assertEqual(v['freshness_ttl_ms'],15000)
        self.assertEqual(v['sources']['balance']['WS']['validation'], 'VALIDATED')
        self.assertEqual(v['sources']['balance']['REST']['age_ms'],0)
        self.assertEqual(v['free_margin'], 'UNVERIFIED');self.assertFalse(v['orders_enabled'])
        self.assertEqual(v['account_readiness'], 'PARTIAL')

    def test_default_view_redacts_values_scope_and_counts(self):
        self.ready();v=json.dumps(visibility(self.state))
        for secret in ('913.2468','812.1357','synthetic-owner-scope','market_id','last_observed'):
            self.assertNotIn(secret,v)

    def test_null_exposure_is_unknown_even_when_terminal_says_zero(self):
        self.ready();self.now+=1
        self.pair('orders',None);self.pair('positions',None)
        v=visibility(self.state,private=True);c=compare_terminal(self.state,self.terminal())
        self.assertEqual(v['open_orders_state'],'PROVIDER_NO_DATA')
        self.assertEqual(v['open_orders'],'UNVERIFIED')
        self.assertIn('EXPOSURE_NOT_RECONCILED',v['blockers'])
        self.assertEqual(c['exposure_outcomes']['positions'],'NOT_VERIFIED')
        self.assertEqual(c['balance_outcome'],'MATCH')
        self.assertEqual(c['overall_outcome'],'NOT_VERIFIED')
        self.assertFalse(c['orders_enabled'])

    def test_explicit_empty_matches_only_api_view_and_never_admits_capital(self):
        self.ready();c=compare_terminal(self.state,self.terminal())
        self.assertEqual(c['exposure_outcomes']['open_orders'],'MATCH')
        self.assertEqual(c['position_mode_outcome'],'MATCH')
        self.assertFalse(self.state.model_a_input()['funding_authorized'])
        self.assertIn('ACCOUNT_IDENTITY_AND_COMPLETENESS_UNVERIFIED',c['api']['blockers'])

    def test_difference_and_precision_recorded_without_mutation(self):
        self.ready();before=self.state.state_version
        c=compare_terminal(self.state,self.terminal(available='812.13'))
        self.assertEqual(c['balance_outcome'],'MISMATCH')
        self.assertEqual(c['amounts']['available']['difference'],'0.0057')
        self.assertEqual(c['terminal']['precision'],2)
        self.assertEqual(self.state.state_version,before)

    def test_missing_same_account_evidence_not_match(self):
        self.ready();c=compare_terminal(self.state,self.terminal(same_account_confirmed=False))
        self.assertEqual(c['balance_outcome'],'NOT_VERIFIED')
        self.assertEqual(c['position_mode_outcome'],'NOT_VERIFIED')

    def test_old_screenshot_and_future_time_stale(self):
        self.ready()
        for t in (0,1001):
            if t == 0:self.now=10000
            self.assertEqual(compare_terminal(self.state,self.terminal(observed_ms=t))['balance_outcome'],'STALE')
        self.assertEqual(compare_terminal(self.state,self.terminal(observed_ms=10001))['balance_outcome'],'STALE')

    def test_disconnected_view_only_has_labelled_last_observation(self):
        self.ready();self.state.connection('DISCONNECTED')
        v=visibility(self.state,private=True)
        self.assertFalse(v['balance_current']);self.assertEqual(v['total_reported'],'UNVERIFIED')
        self.assertEqual(v['last_observed']['total_reported'],'913.2468')
        self.assertFalse(v['last_observed']['current']);self.assertEqual(v['account_readiness'],'BLOCKED')
        self.assertEqual(compare_terminal(self.state,self.terminal())['balance_outcome'],'STALE')

    def test_expiry_does_not_present_current_balance(self):
        self.ready();self.now+=15001;v=visibility(self.state,private=True)
        self.assertFalse(v['balance_current']);self.assertEqual(v['balance_state'],'STALE')
        self.assertEqual(v['available_reported'],'UNVERIFIED')

    def test_conflict_does_not_present_cached_balance_as_current(self):
        self.ready();self.now+=1
        self.push('balance',{'data':{'USDT':{'t':'914','a':'813'}}})
        v=visibility(self.state,private=True)
        self.assertEqual(v['balance_state'],'CONFLICT');self.assertFalse(v['balance_current'])
        self.assertEqual(compare_terminal(self.state,self.terminal())['balance_outcome'],'NOT_VERIFIED')

    def test_reconnect_requires_new_generation_evidence(self):
        self.ready();self.state.connection('DISCONNECTED');self.state.connection('CONNECTING')
        self.state.connection('SUBSCRIBED');self.state.connection('REST_RESYNC_COMPLETE')
        self.assertFalse(visibility(self.state,private=True)['balance_current'])
        self.now+=1;self.pair('balance',self.wire.balance)
        self.assertTrue(visibility(self.state,private=True)['balance_current'])

    def test_checkpoint_live_reader_and_after_writer_exit_with_configured_ttl(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{},clear=True):
            path=Path(d)/'account.sqlite';w=PrivateStore(path)
            try:
                self.state=self.make_state(store=w,max_age_ms=6000,comparison_ms=2000);self.ready()
                reader=PrivateStore(path,readonly=True)
                try:
                    view=load_state(reader,'synthetic-owner-scope',clock_ms=lambda:self.now)
                    self.assertEqual(view.max_age_ms,6000);self.assertEqual(view.comparison_ms,2000)
                    self.assertTrue(visibility(view,private=True)['balance_current'])
                finally:reader.close()
            finally:w.close()
            reader=PrivateStore(path,readonly=True)
            try:
                view=load_state(reader,'synthetic-owner-scope',clock_ms=lambda:self.now)
                self.assertFalse(visibility(view,private=True)['balance_current'])
            finally:reader.close()

    def test_malformed_terminal_input_fails_closed(self):
        self.ready()
        for kwargs in ({'precision':True},{'total':'NaN'},{'available':'Infinity'},
                {'positions':-1},{'observed_ms':True},{'available':'1000'},
                {'total':'1e999999'},{'position_mode':'UNKNOWN'},{'identity_basis':'arbitrary'}):
            with self.assertRaises(AccountStateError):compare_terminal(self.state,self.terminal(**kwargs))

    def test_private_cli_redirect_and_ci_deny_before_any_checkpoint_access(self):
        for env in ({'CI':'true'},{}):
            out=io.StringIO()
            with patch.dict(os.environ,env,clear=True),contextlib.redirect_stdout(out), \
                 patch('daiinas.bitsgap_account_visibility.PrivateStore',side_effect=AssertionError()):
                self.assertEqual(main(['--state-file','unused','--scope-ref','x','--private-panel']),2)
            self.assertIn('PRIVATE_OUTPUT_DISALLOWED',out.getvalue())

    def test_missing_local_credential_reports_exact_blocker_without_connecting(self):
        out=io.StringIO()
        with patch.dict(os.environ,{},clear=True),contextlib.redirect_stdout(out), \
             patch('daiinas.bitsgap_account_state.BitsgapFuturesObserver',side_effect=AssertionError()):
            self.assertEqual(observer_main(['--observe','--scope-ref','test','--seconds','60']),2)
        self.assertEqual(json.loads(out.getvalue())['status'],'CREDENTIAL_NOT_CONFIGURED')

    def test_private_comparison_record_cli_secure_storage_and_replay_expiry(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{},clear=True):
            statefile=Path(d)/'state.sqlite';comparison=Path(d)/'comparison.sqlite';writer=PrivateStore(statefile)
            try:
                self.state=self.make_state(store=writer);self.ready()
                args=['--state-file',str(statefile),'--scope-ref','synthetic-owner-scope',
                      '--private-panel','--comparison-file',str(comparison)]
                out=io.StringIO()
                with patch('daiinas.bitsgap_account_visibility.trusted_terminal',return_value=True), \
                     patch('daiinas.bitsgap_account_visibility._prompt_terminal',return_value=self.terminal()), \
                     patch('daiinas.bitsgap_account_state.time.time',return_value=1),contextlib.redirect_stdout(out):
                    self.assertEqual(main(args+['--compare']),0)
                self.assertEqual(json.loads(out.getvalue())['terminal_parity'],'MATCH')
                self.assertEqual(comparison.stat().st_mode & 0o777,0o600)
                out=io.StringIO()
                with patch('daiinas.bitsgap_account_state.time.time',return_value=7),contextlib.redirect_stdout(out):
                    self.assertEqual(main(args[:-3]+['--comparison-file',str(comparison)]),0)
                self.assertEqual(json.loads(out.getvalue())['terminal_parity'],'STALE')
                self.assertNotIn('913.2468',out.getvalue())
            finally:writer.close()

    def test_private_comparison_cannot_overwrite_worker_checkpoint(self):
        out=io.StringIO()
        with patch('daiinas.bitsgap_account_visibility.trusted_terminal',return_value=True),contextlib.redirect_stdout(out):
            self.assertEqual(main(['--state-file','same','--comparison-file','same','--scope-ref','test',
                                   '--compare','--private-panel']),2)
        self.assertNotIn('same',out.getvalue())

    def test_expired_private_record_cannot_be_revalidated_by_new_receipts(self):
        self.ready();old=self.now;self.now+=6000;self.pair('balance',self.wire.balance)
        self.assertEqual(compare_terminal(self.state,self.terminal(),captured_ms=old)['balance_outcome'],'STALE')

    def test_old_exposure_cannot_match_new_terminal_sample(self):
        self.ready();self.now+=6000
        self.pair('balance',{'data':{'USDT':{'t':'914.25','a':'813.14'}}})
        c=compare_terminal(self.state,self.terminal(total='914.25',available='813.14'))
        self.assertEqual(c['balance_outcome'],'MATCH')
        self.assertEqual(c['exposure_outcomes']['positions'],'STALE')
        self.assertEqual(c['position_mode_outcome'],'STALE')
        self.assertEqual(c['overall_outcome'],'STALE')

    def test_prompt_labels_local_confirmation_time_without_provider_claim(self):
        from daiinas.bitsgap_account_visibility import _prompt_terminal
        answers=['YES','2','ONE_WAY','913.25 812.14 ? ? NOW']
        with patch('builtins.input',side_effect=answers),patch('time.time',return_value=1), \
             contextlib.redirect_stdout(io.StringIO()):
            t=_prompt_terminal()
        self.assertEqual(t['observed_ms'],1000)
        self.assertIsNone(t['positions'])
