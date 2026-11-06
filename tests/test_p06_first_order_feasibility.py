"""P06 synthetic, no-network tests: NONE of these prove live order readiness."""
import json
import unittest
from dataclasses import replace

from daiinas.bitsgap_account_acceptance import blocked_report
from daiinas.bitsgap_capabilities import (
    BitsgapCapabilityRegistry, Parameter,
)
from daiinas.p06_first_order_feasibility import (
    assess_first_order, from_p051_report,
)


NOW = 15000
MARKER = 'NEVER_PRINT_PRIVATE_TOKEN_9a5e'


def catalog(*, synthetic=False, mode='full'):
    """Injected fixture with supposedly authenticated catalog: NOT real proof."""
    r = BitsgapCapabilityRegistry.documented()
    r.synthetic = synthetic
    for name in ('order_place', 'order_detail', 'order_cancel', 'position_close'):
        c = r.get(name)
        parms = ()
        if name == 'order_place':
            parms = (Parameter('eot', 'unsigned(enum)', True,
                               (('LIMIT', 1), ('MARKET', 2))),
                     Parameter('ro', 'unsigned(bool)', False),
                     Parameter('em', 'unsigned(enum)', True, (('REAL_FUTURES', 72),)))
        r.records[name] = replace(c, market_id=72,
                                  transports=('WS',), parameters=parms,
                                  verification='LIVE_DISCOVERED',
                                  schema_known=True, validated_ms=NOW - 50,
                                  evidence='AUTHENTICATED_MANUAL_AND_CONF_ENUMS')
    if mode == 'without_schema':
        c = r.get('order_place')
        r.records['order_place'] = replace(c, parameters=(), schema_known=False)
    if mode == 'rest_only':
        c = r.get('order_place')
        r.records['order_place'] = replace(c, transports=('REST',))
    if mode == 'other_market':
        c = r.get('order_cancel')
        r.records['order_cancel'] = replace(c, market_id=10)
    if mode == 'demo':
        c = r.get('order_place')
        r.records['order_place'] = replace(c, verification='UNSUPPORTED')
    if mode == 'old_catalog':
        c = r.get('order_place')
        r.records['order_place'] = replace(c, validated_ms=1)
    return r


def observed(*, orders='VERIFIED_EMPTY', positions='VERIFIED_EMPTY',
             settings='VALIDATED', pos_mode='ONE_WAY', age=40,
             scope='KUCOIN_FUTURES_USDT', websocket_auth='PASS',
             connection='CONNECTED'):
    return {
        'status': 'PASS',
        'authenticated_market_scope': scope,
        'transport': {'rest_catalog_auth': 'PASS',
                      'websocket_auth': websocket_auth},
        'session_evidence': {
            'captured_ms': NOW - age,
            'connection': connection,
            'position_mode': pos_mode,
            'topics': {
                'balance': {'state': 'VALIDATED'},
                'orders': {'state': orders},
                'positions': {'state': positions},
                'positions_settings': {'state': settings},
            },
        },
        'equity': 'UNVERIFIED', 'free_margin': 'UNVERIFIED',
        'financial_admission': 'BLOCKED',
        'DAIINAS_ORDER_ROUTING': 'DISABLED',
    }


def assess(registry=None, report=None, **kw):
    v = assess_first_order(registry or catalog(),
                           observed() if report is None else report,
                           now_ms=NOW, **kw)
    return v['first_order_readiness']


def gate(result, name):
    return next(x for x in result['gates'] if x['gate'] == name)


class FirstOrderReadinessTests(unittest.TestCase):
    def test_01_even_all_declared_and_explicit_empty_is_no_go(self):
        x = assess()
        self.assertEqual(x['decision'], 'NO_GO')
        self.assertEqual(x['status'], 'BLOCKED')
        self.assertEqual(x['reason'], 'BLOCKED_NATIVE_PROTECTION_CONTRACT_UNVERIFIED')
        self.assertEqual(gate(x, 'order_command_transport')['status'], 'DECLARED_ONLY')
        self.assertEqual(gate(x, 'complete_orders_positions_and_external_exposure')['status'],
                         'OBSERVED_COUNTS_ONLY')
        self.assertFalse(x['orders_enabled'])
        self.assertFalse(x['native_tp_sl_verified'])

    def test_02_public_docs_only_never_imply_venue_support(self):
        x = assess(registry=BitsgapCapabilityRegistry.documented())
        self.assertIn('BLOCKED_REAL_FUTURES_CATALOG_NOT_VERIFIED', x['reasons'])
        self.assertEqual(gate(x, 'market_and_catalog')['evidence_kind'], 'UNVERIFIED')

    def test_03_authenticated_catalog_claim_is_still_not_permission(self):
        x = assess()
        self.assertEqual(gate(x, 'order_command_transport')['evidence_kind'],
                         'READ_ONLY_LIVE_CATALOG_DECLARED')
        self.assertIn('BLOCKED_COMMAND_PERMISSION_AND_ASYNC_TRANSPORT_NOT_PROVEN',
                      x['reasons'])

    def test_04_rest_only_documentation_conflict_cannot_authorize_ws(self):
        x = assess(registry=catalog(mode='rest_only'))
        self.assertIn('BLOCKED_ORDER_COMMANDS_OR_TRANSPORT_UNVERIFIED', x['reasons'])

    def test_05_order_place_schema_not_exposed(self):
        x = assess(registry=catalog(mode='without_schema'))
        self.assertIn('BLOCKED_ORDER_SCHEMA_TYPES_OR_REDUCE_ONLY_UNVERIFIED',
                      x['reasons'])

    def test_06_foreign_scope_or_demo_market_disallowed(self):
        for mode in ('other_market', 'demo'):
            with self.subTest(mode=mode):
                x = assess(registry=catalog(mode=mode))
                self.assertEqual(gate(x, 'order_command_transport')['status'],
                                 'UNVERIFIED')

    def test_07_stale_live_catalog_not_promoted(self):
        x = assess(registry=catalog(mode='old_catalog'))
        self.assertEqual(gate(x, 'market_and_catalog')['status'], 'UNVERIFIED')

    def test_08_provider_null_is_not_zero(self):
        for orders, positions in (('PROVIDER_NO_DATA', 'PROVIDER_NO_DATA'),
                                  ('PROVIDER_NO_DATA', 'VERIFIED_EMPTY'),
                                  ('VERIFIED_ACTIVE', 'PROVIDER_NO_DATA')):
            with self.subTest(orders=orders, positions=positions):
                x = assess(report=observed(orders=orders, positions=positions))
                self.assertIn('BLOCKED_EXPOSURE_PROVIDER_NO_DATA', x['reasons'])
                self.assertFalse(x['account_verified'])

    def test_09_explicit_active_positions_are_not_full_inventory(self):
        x = assess(report=observed(orders='VERIFIED_ACTIVE',
                                   positions='VERIFIED_ACTIVE'))
        self.assertIn('BLOCKED_FULL_EXPOSURE_INVENTORY_NOT_PROVEN', x['reasons'])

    def test_10_sample_expired_even_if_caller_claims_pass(self):
        x = assess(report=observed(age=16000))
        self.assertIn('BLOCKED_ACCOUNT_SCOPE_AUTH_OR_AGE_UNVERIFIED', x['reasons'])

    def test_11_wrong_futures_account_scope_is_no_go(self):
        x = assess(report=observed(scope='DEMO_FUTURES'))
        self.assertIn('BLOCKED_ACCOUNT_SCOPE_AUTH_OR_AGE_UNVERIFIED', x['reasons'])

    def test_12_unverified_websocket_or_stopped_session_is_no_go(self):
        for kwargs in ({'websocket_auth': 'UNVERIFIED'},
                       {'connection': 'DISCONNECTED'}):
            with self.subTest(kwargs=kwargs):
                x = assess(report=observed(**kwargs))
                self.assertEqual(gate(x, 'authenticated_read_observation')['status'],
                                 'UNVERIFIED')

    def test_13_one_way_mode_must_be_from_scoped_settings(self):
        for mode, settings in (('HEDGE', 'VALIDATED'),
                               ('ONE_WAY', 'UNVERIFIED'),
                               ('UNVERIFIED', 'PROVIDER_NO_DATA')):
            with self.subTest(mode=mode, settings=settings):
                x = assess(report=observed(pos_mode=mode, settings=settings))
                self.assertIn('BLOCKED_ONE_WAY_POSITION_MODE_UNVERIFIED',
                              x['reasons'])

    def test_14_available_wallet_and_user_equity_claim_cannot_fund_order(self):
        r = observed()
        r.update({'free_margin': 'VERIFIED', 'eligible_capital': '1000000',
                  'account_verified': True, 'owner_authorized': True})
        x = assess(report=r)
        self.assertIn('BLOCKED_EQUITY_FREE_MARGIN_AND_COSTS_UNVERIFIED',
                      x['reasons'])
        self.assertFalse(x['account_verified'])

    def test_15_mock_native_brackets_not_a_venue_attestation(self):
        x = assess(protection_evidence={
            'source_kind': 'MOCK_NATIVE', 'protected_amount': '10000',
            'tp_ack': True, 'sl_ack': True, 'partial_fills_covered': True})
        self.assertIn('BLOCKED_MOCK_OR_UI_PROTECTION_IS_NOT_VENUE_PROOF',
                      x['reasons'])

    def test_16_partial_fill_child_mismatch_must_not_pass(self):
        x = assess(protection_evidence={
            'source_kind': 'UI_ASSERTION', 'position_qty': '3',
            'protected_qty': '1', 'sibling_cancel': True})
        self.assertIn('BLOCKED_MOCK_OR_UI_PROTECTION_IS_NOT_VENUE_PROOF',
                      x['reasons'])
        self.assertIn('BLOCKED_PROTECTIVE_CHILD_AND_RESTART_PERSISTENCE_UNVERIFIED',
                      x['reasons'])

    def test_17_self_asserted_venue_signed_string_is_not_cryptographic_proof(self):
        x = assess(protection_evidence={
            'source_kind': 'VENUE_SIGNED', 'verified': True,
            'restart_persistence': True, 'stop_loss': True, 'take_profit': True})
        self.assertIn('BLOCKED_INDEPENDENT_VENUE_PROTECTION_ATTESTATION_ABSENT',
                      x['reasons'])

    def test_18_perfect_synthetic_fixture_still_never_live_ready(self):
        x = assess(registry=catalog(synthetic=True))
        self.assertTrue(x['synthetic_evidence'])
        self.assertIn('SYNTHETIC_NOT_LIVE_VERIFIED', x['reasons'])
        self.assertEqual(x['decision'], 'NO_GO')

    def test_19_missing_p051_session_evidence_no_go(self):
        x = assess(report=blocked_report('CREDENTIAL_NOT_CONFIGURED'))
        self.assertIn('BLOCKED_ACCOUNT_SCOPE_AUTH_OR_AGE_UNVERIFIED', x['reasons'])

    def test_20_no_echo_of_secrets_private_id_or_money_in_output(self):
        r = observed()
        r['private_key'] = MARKER
        r['session_evidence']['account_id'] = MARKER
        r['session_evidence']['balance'] = MARKER
        x = assess(report=r, protection_evidence={'untrusted_notes': MARKER})
        self.assertNotIn(MARKER, json.dumps(x))
        self.assertNotIn('1000000', json.dumps(x))

    def test_21_p051_report_wrapper_has_identical_result(self):
        r = observed()
        c = catalog()
        self.assertEqual(from_p051_report(c, r, now_ms=NOW),
                         assess_first_order(c, r, now_ms=NOW))

    def test_22_fails_closed_on_invalid_inputs(self):
        c = catalog()
        for reg, acceptance, now, maxage in (
            (None, {}, NOW, 15000),
            (c, 'PRIVATE_TEXT', NOW, 15000),
            (c, {}, True, 15000),
            (c, {}, -1, 15000),
            (c, {}, NOW, 0),
            (c, {}, NOW, 99999999),
        ):
            with self.subTest(reg=reg, acc=acceptance, now=now, ttl=maxage):
                with self.assertRaises((TypeError, ValueError)):
                    assess_first_order(reg, acceptance, now_ms=now,
                                       max_age_ms=maxage)

    def test_23_never_exposes_trading_operation_or_live_ready_state(self):
        x = assess()
        self.assertEqual(x['live_trading'], 'DISABLED')
        self.assertEqual(x['new_entry'], 'NO_TRADE_ACCOUNT_NOT_RECONCILED')
        self.assertTrue(all(z['status'] not in ('READY_FOR_LIVE', 'ACCOUNT_VERIFIED')
                            for z in x['gates']))
        self.assertIn('BLOCKED_START_LIVE_NO_LIVE_TRANSPORT', x['reasons'])


if __name__ == '__main__':
    unittest.main()
