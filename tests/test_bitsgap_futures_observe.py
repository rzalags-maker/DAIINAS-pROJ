"""Signed offline contract tests. Synthetic records do not attest a real account."""
import base64
import copy
import hashlib
import json
import unittest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from daiinas.bitsgap_readonly import BitsgapError
from daiinas.bitsgap_futures_observe import BitsgapFuturesObserver, safe_preflight


def new_pem():
    key = Ed25519PrivateKey.generate()
    return key, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()).decode()


class FakeWire:
    def __init__(self):
        self.calls = []
        self.enums = {"data": {
            "market": {"alias": "em", "items": {"KUCOIN": 71, "KUCOIN_FUTURES": 72,
                                                  "KUCOIN_FUTURES_DEMO": 73, "OTHER": 90}},
            "order_side": {"alias": "eos", "items": {"BUY": 1, "SELL": 2}},
            "order_type": {"alias": "eot", "items": {"LIMIT": 1, "MARKET": 2}},
            "order_state": {"alias": "eost", "items": {"OPEN": 3, "OPENED": 4}},
            "position_side": {"alias": "epps", "items": {"BOTH": 1, "LONG": 2, "SHORT": 3}},
            "pos_side": {"alias": "eps", "items": {"LONG": 1, "SHORT": 2}},
            "position_margin": {"alias": "epm", "items": {"CROSS": 1, "ISOLATED": 2}},
            "position_mode": {"alias": "epmd", "items": {"ONE_WAY": 1, "HEDGE": 2}},
            "order_tif": {"alias": "etif", "items": {"GTC": 1}}}}
        names = ["manual", "conf_enums", "balance", "orders", "positions", "positions_settings",
                 "orders_history", "conf_pairs", "order_place", "order_cancel", "position_close"]
        self.manual = {"descr": "topic catalog", "data": {k: {"transport": {"ws": True, "rest": True}}
                                                         for k in names}}
        self.balance = {"data": {"USDT": {"t": "61.07", "a": "61.07"}}}
        self.orders = {"data": {}, "cnt": 0}
        self.positions = {"data": {}, "cnt": 0, "epmd": 1, "epm": 2}
        self.settings = {"data": {}, "cnt": 0, "epmd": 1, "epm": 2}
        self.history = {"data": []}
        self.pairs = {"data": {}}
        self.bad = None

    def __call__(self, url, body, headers):
        payload = json.loads(body)
        topic = payload["topic"]
        self.calls.append((topic, payload, headers))
        if self.bad == topic:
            return b'{"data":{"error":"private account value"}}'
        v = {"manual": self.manual, "conf_enums": self.enums, "balance": self.balance,
             "orders": self.orders, "positions": self.positions,
             "positions_settings": self.settings, "orders_history": self.history,
             "conf_pairs": self.pairs}[topic]
        return json.dumps({"data": v}).encode()


class FuturesObservationTests(unittest.TestCase):
    def setUp(self):
        self.key, self.pem = new_pem()
        self.w = FakeWire()
        self.api = BitsgapFuturesObserver(self.pem, transport=self.w, clock_ms=lambda: 1783000000000)

    def test_clean_observation_wallet_private_panel_and_no_live(self):
        self.api.discover()
        result = self.api.snapshot()
        self.assertEqual(result.market_id, 72)
        self.assertEqual(result.total_usdt, "61.07")
        self.assertEqual(result.available_usdt, "61.07")
        self.assertEqual(result.position_mode, "ONE_WAY")
        self.assertEqual(result.margin_mode, "ISOLATED")
        self.assertEqual(result.open_orders, 0)
        self.assertFalse(result.strategy_funding_authorized)
        self.assertEqual(result.private_panel()["model_a_reserve"], "UNVERIFIED")
        self.assertNotIn("61.07", json.dumps(result.safe_status()))
        self.assertEqual([k for k, _, _ in self.w.calls], ["manual", "conf_enums", "balance", "orders",
                                                         "positions", "positions_settings"])
        self.assertTrue(all(d["payload"] == {"em": 72} for _,d,_ in self.w.calls[2:]))

    def test_signatures_are_byte_for_byte_existing_rest_format(self):
        self.api.discover()
        self.api.snapshot()
        for name, packet, header in self.w.calls:
            serialized = json.dumps(packet["payload"], separators=(",", ":")).encode()
            assert json.dumps(packet["payload"], separators=(",", ":")).encode() in json.dumps(packet, separators=(",", ":")).encode()
            sha = base64.b64encode(hashlib.sha256(serialized).digest()).decode()
            canonical = f'btg-rest\nv1\n{packet["nonce"]}\n{packet["ts"]}\n{name}\n{sha}'.encode()
            self.key.public_key().verify(base64.b64decode(packet["signature"]),canonical)
            self.assertEqual(header["Content-Type"], "application/json")

    def test_no_write_or_spot_demo_parameter_escape(self):
        self.api.discover()
        before = len(self.w.calls)
        for topic in ("order_place", "order_cancel", "position_close", "leverage_change",
                      "transfer", "withdraw", "margin_size_change", "price"):
            with self.assertRaisesRegex(BitsgapError,"FUTURES_WRITE_OR_UNKNOWN_TOPIC_DENIED"):
                self.api.read(topic)
        for pair in ("BTC_USDT", 72, "KUCOIN"):
            with self.assertRaises(BitsgapError):
                self.api.read("balance",pair=pair)
        self.assertEqual(before,len(self.w.calls))

    def test_fail_closed_ambiguous_demo_and_unresolved(self):
        for markets in ({"KUCOIN":71,"KUCOIN_FUTURES_DEMO":73},
                        {"KUCOIN_FUTURES":72,"OTHER":72},
                        {"KUCOIN_FUTURES":True},
                        {"KUCOIN_FUTURES":-1}):
            self.w.enums["data"]["market"]["items"] = markets
            with self.assertRaises(BitsgapError):
                self.api.discover()
            with self.assertRaisesRegex(BitsgapError,"FUTURES_DISCOVERY_REQUIRED"):
                self.api.read("balance")
        self.assertTrue(all(name in ("manual","conf_enums") for name,_,_ in self.w.calls))

    def test_partial_catalog_no_false_supported(self):
        del self.w.manual["data"]["positions_settings"]
        with self.assertRaisesRegex(BitsgapError,"UNVERIFIED_MANUAL_CAPABILITIES"):
            self.api.discover()

    def test_missing_usdt_and_spot_only_lock_fail_closed(self):
        self.api.discover()
        for balance in ({"data": {}}, {"data": {"USDT": {"t": "61.07", "a": "61.07", "l": "0"}}},
                        {"data": {"USDT": {"t": "10", "a": "11"}}},
                        {"data": {"USDT": {"t": "NaN", "a": "1"}}}):
            self.w.balance = balance
            with self.assertRaises(BitsgapError):self.api.snapshot()
        self.assertEqual(safe_preflight(client=self.api)["capital_reconciled"], False)

    def test_futures_order_duplicate_and_bad_enum_rejected(self):
        self.api.discover()
        row = {"id": "x", "eost": 4, "eot": 1, "eos": 1, "epps": 1, "t0": 1783000000000,
               "pr": "50000", "am": "0.001", "ro": 1}
        self.w.orders = {"data": {"BTC_USDT": [copy.deepcopy(row)], "ETH_USDT": [copy.deepcopy(row)]}, "cnt": 2}
        with self.assertRaisesRegex(BitsgapError,"DUPLICATE_FUTURES_ORDER_ID"):
            self.api.snapshot()
        self.w.orders["data"]["ETH_USDT"][0]["id"] = "y"
        self.assertEqual(self.api.snapshot().open_orders,2)
        self.w.orders["data"]["ETH_USDT"][0]["eos"] = 999
        with self.assertRaises(BitsgapError):self.api.snapshot()

    def test_partial_fill_fee_fields_and_no_double_amount(self):
        self.api.discover()
        row = {"id": "x", "eost": 4, "eot": 1, "eos": 1, "epps": 1, "t0": 1783000000000,
               "pr": "50000", "am": "0.001", "ame": "0.0005", "pre": "50000",
               "f": {"USDT": "0.004"}, "tl": 1783000000000}
        self.w.orders = {"data": {"BTC_USDT": [row]}, "cnt": 1}
        self.assertEqual(self.api.snapshot().open_orders,1)
        row["f"]["USDT"] = "Infinity"
        with self.assertRaises(BitsgapError):self.api.snapshot()

    def test_live_positions_and_settings_count_and_mode_conflict(self):
        self.api.discover()
        self.w.positions["data"]["BTC_USDT"] = [{"epps":1, "epm":2, "lv":"2",
                            "eps":1, "am":"0.01", "pr":"60000", "msize":"200"}]
        self.w.positions["cnt"] = 1
        self.assertEqual(self.api.snapshot().open_positions, 1)
        self.w.settings["epmd"] = 2
        with self.assertRaisesRegex(BitsgapError,"INCONSISTENT_POSITION_MODES"):
            self.api.snapshot()
        self.w.settings["epmd"] = 1
        self.w.positions["cnt"] = 0
        with self.assertRaisesRegex(BitsgapError,"UNVERIFIED_POSITIONS_COUNT"):
            self.api.snapshot()

    def test_empty_orders_and_positions_are_legitimate_observation(self):
        self.api.discover()
        self.assertEqual(self.api.snapshot().open_orders,0)
        self.assertEqual(self.api.snapshot().open_positions,0)
        self.assertEqual(self.api.snapshot().completeness,"OBSERVED_NON_ATOMIC_NOT_RECONCILED")

    def test_observation_history_allowlist_and_pair(self):
        self.api.discover()
        self.assertEqual(self.api.read("orders_history",pair="BTC_USDT"),{"data":[]})
        with self.assertRaises(BitsgapError):self.api.read("orders_history",pair="../TOKEN")

    def test_unknown_response_never_logs_secret(self):
        self.w.bad="balance"
        report=safe_preflight(client=self.api)
        self.assertEqual(report["status"],"UNVERIFIED")
        self.assertNotIn("private account",json.dumps(report))

if __name__ == "__main__": unittest.main()
