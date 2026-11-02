import unittest
from daiinas.bitsgap_account_acceptance import AccountAcceptance
import test_bitsgap_account_state as fixture


class AcceptanceTests(unittest.TestCase):
    setUp=fixture.AccountStateTests.setUp
    make_state=fixture.AccountStateTests.make_state
    connect=fixture.AccountStateTests.connect
    pair=fixture.AccountStateTests.pair
    push=fixture.AccountStateTests.push

    def evidence(self,scope='synthetic-owner-scope',market=72):
        return AccountAcceptance.from_state(self.state,expected_market_id=market,expected_scope_ref=scope)

    def test_provider_null_report_does_not_fund_and_preserves_owner_parity_pending(self):
        self.connect();self.pair('balance',self.wire.balance)
        self.pair('orders',None);self.pair('positions',None)
        report=self.evidence().report(now_ms=self.now)
        self.assertIn('ORDERS_PROVIDER_NO_DATA',report['paper_observation_blockers'])
        self.assertEqual(report['fields']['terminal_parity'],'PENDING_OWNER_VERIFICATION')
        self.assertIsNone(report['eligible_capital']);self.assertFalse(report['orders_enabled'])
        self.assertNotIn('913.2468',str(report))

    def test_stale_capture_does_not_renew_older_receipt_age(self):
        self.connect();self.pair('balance',self.wire.balance);self.now+=14000
        evidence=self.evidence();self.assertEqual(evidence.observed_ms,1000)
        self.assertIn('ACCOUNT_EVIDENCE_STALE',evidence.report(now_ms=17000)['paper_observation_blockers'])

    def test_wrong_scope_and_market_blocked(self):
        self.assertIn('ACCOUNT_SCOPE_MISMATCH',self.evidence(scope='foreign').report(now_ms=self.now)['paper_observation_blockers'])
        self.assertFalse(self.evidence(market=71).account_scope_matches)

    def test_conflict_remains_conflict_and_unknown_financial_fields_have_reasons(self):
        self.connect();self.push('balance',self.wire.balance)
        self.push('balance',{'data':{'USDT':{'t':'914','a':'813'}}},'WS')
        report=self.evidence().report(now_ms=self.now)
        self.assertIn('BALANCE_CONFLICT',report['paper_observation_blockers'])
        self.assertIn('FREE_MARGIN_UNVERIFIED',report['financial_blockers'])

    def test_disconnect_and_reconnect_old_generation_not_accepted(self):
        self.connect();self.pair('balance',self.wire.balance)
        self.state.connection('DISCONNECTED');self.state.connection('CONNECTING')
        report=self.evidence().report(now_ms=self.now)
        self.assertIn('ACCOUNT_DISCONNECTED',report['paper_observation_blockers'])
        self.assertIn('BALANCE_STALE',report['paper_observation_blockers'])
