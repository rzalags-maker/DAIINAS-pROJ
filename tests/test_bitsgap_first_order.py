"""P06 preflight tests use only synthetic, redacted evidence."""
import unittest

from daiinas.bitsgap_account_acceptance import AccountAcceptance
from daiinas.bitsgap_capabilities import BitsgapCapabilityRegistry, Capability, Parameter
from daiinas.bitsgap_first_order import (COMMANDS, REQUIRED, FirstOrderEvidenceBundle,
                                         Proof, assess_first_order)


NOW = 1_000


def registry(*, order_place=True, transport=('WS',), market=72):
    records = []
    for name in COMMANDS:
        params = [Parameter('em', 'unsigned(enum)', True,
                            (('KUCOIN_FUTURES', 72),))]
        if name == 'order_place':
            params += [Parameter('pair', 'string(pair)', True),
                       Parameter('eot', 'unsigned(enum)', True, (('LIMIT', 1),)),
                       Parameter('eos', 'unsigned(enum)', True, (('BUY', 1),)),
                       Parameter('am', 'string(decimal)', True, positive=True),
                       Parameter('ro', 'unsigned(bool)', True)]
        records.append(Capability(name, transport if name == 'order_place' else ('WS',),
            tuple(params), 'KUCOIN_FUTURES', market, 'MUTATING',
            'START_LIVE_OWNER_AUTHORIZATION',
            'DOCUMENTED' if order_place or name != 'order_place' else 'UNSUPPORTED',
            'SYNTHETIC_CATALOG_NOT_LIVE', NOW, True, (),
            runtime_enabled=False))
    return BitsgapCapabilityRegistry(records, synthetic=True)


def account(**overrides):
    values = dict(observed_ms=995, generation=0, account_scope_matches=True,
                  balance='VALIDATED', orders='VERIFIED_EMPTY', positions='VERIFIED_EMPTY',
                  position_mode='ONE_WAY', connection='CONNECTED')
    values.update(overrides)
    return AccountAcceptance(**values)


def acceptance(**overrides):
    sources = {}
    topics = {}
    for name, state in (('balance', 'VALIDATED'), ('orders', 'VERIFIED_EMPTY'),
                        ('positions', 'VERIFIED_EMPTY'), ('positions_settings', 'VALIDATED')):
        sources[name] = {'REST': {'started_ms': 990, 'received_ms': 995, 'quality': 'VALIDATED'},
                         'WS': {'started_ms': 996, 'received_ms': 998, 'quality': 'VALIDATED'}}
        topics[name] = {'state': state}
    result = {'authenticated_market_scope': 'KUCOIN_FUTURES_USDT',
              'connection_after_stop': 'CONNECTED',
              'transport': {'websocket_auth': 'PASS', 'rest_catalog_auth': 'PASS',
                            'stop': 'RUNNING'},
              'session_evidence': {'captured_ms': NOW, 'connection': 'CONNECTED',
                  'position_mode': 'ONE_WAY', 'topics': topics,
                  'oldest_receipt_ms': {name: 995 for name in topics}, 'sources': sources}}
    result.update(overrides)
    return result


def proofs(*, kind='SYNTHETIC', provenance='SYNTHETIC', missing=()):
    return tuple(Proof(name, kind, provenance, NOW, 0,
                       tuple(x for x in required if (name, x) not in missing))
                 for name, required in REQUIRED.items())


def bundle(**overrides):
    values = dict(registry=registry(), account=account(), acceptance=acceptance(),
                  expected_market_id=72, environment='SYNTHETIC', proofs=proofs(),
                  synthetic_generation=0, coverage=(10, 2, 8, 8))
    values.update(overrides)
    return FirstOrderEvidenceBundle(**values)


class FirstOrderTests(unittest.TestCase):
    def report(self, **overrides):
        return assess_first_order(bundle(**overrides), now_ms=NOW)

    @staticmethod
    def gate(report, name):
        return next(x for x in report['gates'] if x['gate'] == name)

    def test_complete_synthetic_fixture_never_becomes_live_ready(self):
        report = self.report()
        self.assertEqual(report['first_order_readiness'], 'SYNTHETIC_NOT_LIVE_VERIFIED')
        self.assertEqual(report['provenance'], 'SYNTHETIC')
        self.assertFalse(report['orders_enabled'])
        self.assertNotIn('READY', str(report))

    def test_real_and_operator_asserted_proofs_stay_blocked(self):
        report = self.report(environment='REAL', proofs=proofs(kind='ACCOUNT_VERIFIED',
                             provenance='OPERATOR'))
        self.assertEqual(report['first_order_readiness'], 'BLOCKED')
        self.assertIn('BLOCKED_NATIVE_PROTECTION_CONTRACT_UNVERIFIED', report['reasons'])
        self.assertEqual(self.gate(report, 'native_contract')['evidence_kind'], 'UNVERIFIED')
        self.assertNotIn('amount', str(report).lower())

    def test_declared_order_place_and_ambiguous_transport_do_not_authorize(self):
        report = self.report(registry=registry(transport=('REST',)))
        self.assertEqual(self.gate(report, 'catalog_order_place')['reason'],
                         'BLOCKED_COMMAND_SCHEMA_SCOPE_OR_TRANSPORT_UNVERIFIED')
        self.assertEqual(report['first_order_readiness'], 'BLOCKED')
        # A documented schema is only one gate; a real bundle is still blocked.
        self.assertEqual(self.report(environment='REAL')['first_order_readiness'], 'BLOCKED')

    def test_native_protection_and_persistence_claim_gaps_block(self):
        report = self.report(proofs=proofs(missing=(('native_contract', 'tp_create'),
                                                    ('native_persistence', 'controller_disconnect'))))
        self.assertEqual(report['first_order_readiness'], 'BLOCKED')
        self.assertIn('tp_create', self.gate(report, 'native_contract')['missing_proof'])
        self.assertIn('BLOCKED_NATIVE_PERSISTENCE_UNVERIFIED', report['reasons'])

    def test_provider_null_external_or_open_inventory_is_unknown(self):
        for state in ('PROVIDER_NO_DATA', 'VERIFIED_ACTIVE'):
            with self.subTest(state=state):
                report = self.report(account=account(orders=state),
                    acceptance=acceptance(session_evidence={
                        **acceptance()['session_evidence'],
                        'topics': {**acceptance()['session_evidence']['topics'],
                                   'orders': {'state': state}}}))
                self.assertEqual(report['first_order_readiness'], 'BLOCKED')
                self.assertEqual(self.gate(report, 'orders')['status'], 'BLOCKED')

    def test_stale_cohort_scope_demo_stop_and_one_way_all_block(self):
        stale = assess_first_order(bundle(account=account(observed_ms=0)), now_ms=16_000)
        self.assertEqual(self.gate(stale, 'account_freshness')['reason'], 'BLOCKED_ACCOUNT_EVIDENCE_STALE')
        scope = self.report(account=account(account_scope_matches=False))
        self.assertEqual(self.gate(scope, 'real_market_scope')['reason'], 'BLOCKED_ACCOUNT_SCOPE_MISMATCH')
        demo = self.report(environment='DEMO')
        self.assertEqual(demo['first_order_readiness'], 'BLOCKED')
        stopped = self.report(acceptance=acceptance(connection_after_stop='DISCONNECTED'))
        self.assertEqual(self.gate(stopped, 'active_session')['reason'], 'BLOCKED_SESSION_INACTIVE_OR_STOPPED')
        mode = self.report(account=account(position_mode='UNVERIFIED'))
        self.assertEqual(self.gate(mode, 'one_way')['reason'], 'BLOCKED_ONE_WAY_UNVERIFIED')

    def test_partial_fill_mismatch_rejects_protection_coverage(self):
        for coverage in ((10, 2, 7, 8), (10, 11, 0, 0), (10, 2, 8, 7)):
            with self.subTest(coverage=coverage):
                report = self.report(coverage=coverage)
                self.assertEqual(report['first_order_readiness'], 'BLOCKED')
                self.assertEqual(self.gate(report, 'protection_coverage')['reason'],
                                 'BLOCKED_PROTECTION_SIZE_MISMATCH_OR_UNVERIFIED')

    def test_malformed_or_float_coverage_is_rejected_before_assessment(self):
        with self.assertRaises(ValueError):
            bundle(coverage=(10, 2, 8.0, 8))
        with self.assertRaises(ValueError):
            Proof('native_contract', facts=('unknown_fact',))

