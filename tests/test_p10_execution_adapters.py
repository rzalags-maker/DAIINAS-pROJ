import unittest

from daiinas.execution_replay import ExecutionIntent, replay
from daiinas.ccxt_kucoin_futures import CCXTKucoinFuturesAdapter
from daiinas.kucoin_native_futures import KucoinNativeFuturesAdapter


INTENT = ExecutionIntent("intent-1", "XBTUSDTM", "LONG", "3")
PROTECTED = [
    {"id": "a", "kind": "ENTRY_ACK", "exchange_order_id": "entry-1"},
    {"id": "f", "kind": "FILL", "quantity": "3"},
    {"id": "tp", "kind": "PROTECTION_ACK", "role": "TP", "exchange_order_id": "tp-1", "quantity": "3"},
    {"id": "sl", "kind": "PROTECTION_ACK", "role": "SL", "exchange_order_id": "sl-1", "quantity": "3"},
]


class P10ExecutionAdapterTests(unittest.TestCase):
    def test_common_replay_proves_protection_only_from_two_exact_children(self):
        r = replay(INTENT, PROTECTED + [PROTECTED[1]])
        self.assertEqual(r["status"], "REPLAY_VERIFIED")
        self.assertTrue(r["protection_confirmed"])
        self.assertEqual(r["filled_quantity"], "3")
        self.assertFalse(r["new_entries_allowed"])

    def test_partial_fill_mismatch_and_missing_protection_fail_closed(self):
        events = PROTECTED[:2] + [{"id":"tp", "kind":"PROTECTION_ACK", "role":"TP", "exchange_order_id":"tp", "quantity":"1"}]
        r = replay(INTENT, events)
        self.assertEqual(r["status"], "BLOCKED")
        self.assertIn("UNPROTECTED_EXPOSURE", r["reasons"])

    def test_exit_requires_sibling_terminal_confirmation(self):
        r = replay(INTENT, PROTECTED + [{"id":"exit", "kind":"EXIT", "role":"TP"}])
        self.assertEqual(r["status"], "BLOCKED")
        self.assertIn("SIBLING_STATE_UNCONFIRMED", r["reasons"])
        r = replay(INTENT, PROTECTED + [{"id":"exit", "kind":"EXIT", "role":"TP"}, {"id":"sib", "kind":"SIBLING_TERMINAL", "role":"SL"}, {"id":"self", "kind":"SIBLING_TERMINAL", "role":"TP"}])
        self.assertEqual(r["status"], "REPLAY_VERIFIED")

    def test_unknown_and_ambiguous_states_never_authorize_entry(self):
        r = replay(INTENT, [{"id":"x", "kind":"AMBIGUOUS_SUBMISSION"}, {"id":"y", "kind":"EXTERNAL_EXPOSURE"}, {"id":"z", "kind":"POSITIONS_UNAVAILABLE"}, {"id":"m", "kind":"FREE_MARGIN_UNAVAILABLE"}])
        self.assertEqual(r["status"], "BLOCKED")
        self.assertFalse(r["new_entries_allowed"])
        self.assertIn("AMBIGUOUS_SUBMISSION_RECONCILE_FIRST", r["reasons"])

    def test_ccxt_fixture_normalization_and_feature_advertisement(self):
        x = CCXTKucoinFuturesAdapter()
        market = x.market({"id":"XBTUSDTM", "symbol":"BTC/USDT:USDT", "contractSize":.001,
                           "precision":{"amount":1,"price":.1}, "limits":{"amount":{"min":1}}})
        self.assertEqual(market["exchange_symbol"], "XBTUSDTM")
        self.assertEqual(x.conditional_capability({"attachedStopLossTakeProfit":False})["status"], "BLOCKED")
        self.assertEqual(x.conditional_capability({"attachedStopLossTakeProfit":True})["status"], "DOCUMENTED_ONLY")

    def test_native_fixture_schema_is_documented_only_and_has_no_transport(self):
        n = KucoinNativeFuturesAdapter()
        p = n.conditional_request(client_oid="native-1", symbol="XBTUSDTM", side="sell", size=3,
                                  take_profit="101", stop_loss="99")
        self.assertEqual(p["classification"], "DOCUMENTED_ONLY")
        self.assertTrue(p["reduceOnly"])
        self.assertFalse(hasattr(n, "send"))
