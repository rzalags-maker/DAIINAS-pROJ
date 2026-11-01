"""Offline tests for the Bitsgap no-trading REST adapter."""
import base64
import json
import unittest
import copy
import contextlib
import io
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from daiinas.bitsgap_readonly import BitsgapError, BitsgapReadOnly, main


def new_pem():
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    return key, pem


class BitsgapReadOnlyTests(unittest.TestCase):
    def setUp(self):
        self.key, self.pem = new_pem()
        self.calls = []

    def transport(self, url, body, headers):
        self.calls.append((url, body, headers))
        data = json.loads(body)
        name = data["topic"]
        if name == "manual":
            data = {"manual": {"descr": "catalog"},
                    "conf_enums": {"descr": "enums"},
                    "price": {"descr": "price"}}
        elif name == "conf_enums":
            data = {"market": {"alias": "em", "items": {"KUCOIN": 1}}}
        else:
            raise AssertionError("Unexpected network topic")
        return json.dumps({"data": data}).encode()

    def test_signed_payload_and_key_are_verifiable(self):
        api = BitsgapReadOnly(self.pem, self.transport)
        out = api.topic("manual", timestamp=1762010000, nonce="abc123")
        self.assertIsInstance(out, dict)
        url, body, headers = self.calls[0]
        self.assertEqual(url, "https://open.bitsgap.com/api/v1/topic")
        doc = json.loads(body)
        self.assertEqual(doc["payload"], {})
        self.assertEqual(doc["topic"], "manual")
        self.assertEqual(headers["X-Api-Public-Key"], base64.b64encode(
            self.key.public_key().public_bytes(
                serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
            )).decode("ascii"))
        import hashlib
        h = base64.b64encode(hashlib.sha256(b"{}").digest()).decode("ascii")
        canonical = f"btg-rest\nv1\nabc123\n1762010000\nmanual\n{h}".encode()
        self.key.public_key().verify(base64.b64decode(doc["signature"]), canonical)

    def test_command_and_non_allowlisted_topics_rejected_before_network(self):
        api = BitsgapReadOnly(self.pem, self.transport)
        for name in ("order_place", "order_cancel", "position_close", "demo_market_reset",
                     "balance", "positions", "price", "order_detail", "manual\nx"):
            with self.assertRaises(BitsgapError):
                api.topic(name)
        self.assertEqual(self.calls, [])

    def test_extra_parameters_rejected(self):
        api = BitsgapReadOnly(self.pem, self.transport)
        with self.assertRaises(BitsgapError):
            api.topic("manual", {"em": 2})
        self.assertFalse(self.calls)

    def test_missing_and_invalid_private_key_rejected(self):
        with self.assertRaises(BitsgapError):
            BitsgapReadOnly.from_env({})
        with self.assertRaises(BitsgapError):
            BitsgapReadOnly("junk")

    def test_sanitized_handshake_marks_real_order_routing_disabled(self):
        api = BitsgapReadOnly(self.pem, self.transport)
        result = api.handshake()
        self.assertEqual(result, {"bitsgap_authenticated": True,
                                  "kucoin_account_reconciled": False,
                                  "order_routing_enabled": False})
        self.assertEqual([json.loads(c[1])["topic"] for c in self.calls],
                         ["manual", "conf_enums"])

    def test_shape_diagnostics_never_include_api_response_values(self):
        account_marker = "NEVER_SHOW_ACCOUNT_INFO_923"
        def unexpected(url, body, headers):
            return json.dumps({"data": {"value": {"descr": account_marker}, "topic": account_marker}}).encode()
        api = BitsgapReadOnly(self.pem, unexpected)
        with self.assertRaises(BitsgapError) as caught:
            api.handshake()
        category = str(caught.exception)
        self.assertIn("UNEXPECTED_MANUAL_RESPONSE", category)
        self.assertIn("VALUE=DICT", category)
        self.assertIn("TOPIC=PRESENT", category)
        self.assertNotIn(account_marker, category)

    def test_rejects_unknown_success_body_instead_of_claiming_authenticated(self):
        def unexpected(url, body, headers):
            return json.dumps({"data": {"unrecognized": {"content": "redacted"}}}).encode()
        api = BitsgapReadOnly(self.pem, unexpected)
        with self.assertRaisesRegex(BitsgapError, "UNEXPECTED_MANUAL_RESPONSE"):
            api.handshake()

    def test_server_http_rejection_uses_only_status_code(self):
        def fail(url, body, headers):
            raise BitsgapError("HTTP_403")
        api = BitsgapReadOnly(self.pem, fail)
        with self.assertRaisesRegex(BitsgapError, "^HTTP_403$"):
            api.handshake()




class KucoinSpotReadOnlyTests(unittest.TestCase):
    def setUp(self):
        _, self.pem = new_pem()
        self.calls = []
        self.enums = {"market": {"alias": "em", "items": {
            "KUCOIN_SPOT": 731, "KUCOIN_DEMO": 732, "KUCOIN_FUTURES": 733}},
            "order_type": {"items": {"LIMIT": 1, "MARKET": 2}},
            "order_state": {"alias": "eost", "items": {"OPEN": 3, "OPENED": 4}},
            "order_side": {"alias": "eos", "items": {"BUY": 1, "SELL": 2}}}
        self.balance = {"data": {"USDT": {"t": "12.5", "a": "12", "l": "0.5"}}}
        self.orders = {"data": {"BTC_USDT": [{"id": "synthetic", "eost": 4,
            "eot": 1, "eos": 1, "t0": 1781701135678, "am": "0.001", "pr": "65000"}]}, "cnt": 1}
        self.api = BitsgapReadOnly(self.pem, self.transport)

    def transport(self, url, body, headers):
        payload = json.loads(body)
        self.calls.append(payload)
        topic = payload["topic"]
        values = {"manual": {"manual": {}, "conf_enums": {}},
                  "conf_enums": self.enums, "balance": self.balance, "orders": self.orders}
        value = values[topic]
        if isinstance(value, Exception):
            raise value
        return json.dumps({"data": value}).encode()

    def test_successful_dynamic_spot_reads(self):
        self.assertTrue(self.api.handshake()["bitsgap_authenticated"])
        self.assertEqual(self.api.resolve_kucoin_spot(), 731)
        self.assertTrue(self.api.check_balance())
        self.assertTrue(self.api.check_orders())
        for call in self.calls[-2:]:
            self.assertEqual(call["payload"], {"em": 731})
            import hashlib
            payload = json.dumps(call["payload"], separators=(",", ":")).encode()
            digest = base64.b64encode(hashlib.sha256(payload).digest()).decode()
            canonical = (f"btg-rest\nv1\n{call['nonce']}\n{call['ts']}\n"
                         f"{call['topic']}\n{digest}").encode()
            self.api._key.public_key().verify(base64.b64decode(call["signature"]), canonical)

    def test_reads_require_resolution(self):
        for topic in ("balance", "orders"):
            with self.assertRaises(BitsgapError):
                self.api.topic(topic, {"em": 731})
        self.assertFalse(self.calls)

    def test_extra_and_foreign_parameters_denied_before_transport(self):
        self.api.resolve_kucoin_spot()
        count = len(self.calls)
        for topic in ("balance", "orders"):
            for params in ({}, {"em": True}, {"em": "731"}, {"em": 732},
                           {"em": 733}, {"em": 731, "subs": True}, {"em": 731, "pair": "BTC_USDT"}):
                with self.assertRaises(BitsgapError):
                    self.api.topic(topic, params)
        self.assertEqual(len(self.calls), count)

    def test_mutating_commands_always_denied_after_resolution(self):
        self.api.resolve_kucoin_spot()
        count = len(self.calls)
        for name in ("order_place", "order_cancel", "order_modify", "position_close",
                     "withdraw", "transfer", "leverage", "position_mode", "positions",
                     "demo_market_reset", "balance\norder_place"):
            with self.assertRaises(BitsgapError):
                self.api.topic(name, {"em": 731})
        self.assertEqual(len(self.calls), count)

    def test_ambiguous_missing_demo_and_bad_enums_fail_closed(self):
        for items in ({"KUCOIN_DEMO": 2}, {"KUCOIN_FUTURES": 3}, {},
                      {"KUCOIN": 1, "KUCOIN_SPOT": 2}, {"KUCOIN": True},
                      {"KUCOIN": -1}, {"KUCOIN": 1, "OTHER": 1}):
            self.enums["market"]["items"] = items
            with self.assertRaises(BitsgapError):
                self.api.resolve_kucoin_spot()
            with self.assertRaises(BitsgapError):
                self.api.check_balance()
        self.assertTrue(all(c["topic"] == "conf_enums" for c in self.calls))

    def test_resolution_failure_clears_old_id(self):
        self.api.resolve_kucoin_spot()
        self.enums["market"]["alias"] = "wrong"
        with self.assertRaises(BitsgapError):
            self.api.resolve_kucoin_spot()
        with self.assertRaises(BitsgapError):
            self.api.check_orders()

    def test_order_states_and_sides_match_dynamic_enum_and_valid_alternates_pass(self):
        self.api.resolve_kucoin_spot()
        record = self.orders["data"]["BTC_USDT"][0]
        self.assertTrue(self.api.check_orders())
        # Other documented enum values remain valid, not hardcoded to a fixture.
        record["eost"] = 3
        record["eos"] = 2
        self.assertTrue(self.api.check_orders())
        for field, category in (("eost", "UNVERIFIED_ORDER_STATE_ENUM"),
                                ("eos", "UNVERIFIED_ORDER_SIDE_ENUM")):
            old = record[field]
            record[field] = 777
            with self.assertRaisesRegex(BitsgapError, "^" + category + "$"):
                self.api.check_orders()
            record[field] = old
        self.assertTrue(self.api.check_orders())

    def test_missing_or_ambiguous_order_enum_is_unverified(self):
        for enum_name, category in (("order_state", "UNVERIFIED_ORDER_STATE_ENUM"),
                                    ("order_side", "UNVERIFIED_ORDER_SIDE_ENUM")):
            original = copy.deepcopy(self.enums[enum_name])
            for broken in (None, {"alias": "wrong", "items": original["items"]},
                           {"alias": original["alias"], "items": {"X": 1, "Y": 1}},
                           {"alias": original["alias"], "items": {"X": True}}):
                if broken is None:
                    del self.enums[enum_name]
                else:
                    self.enums[enum_name] = broken
                self.api.resolve_kucoin_spot()
                with self.assertRaisesRegex(BitsgapError, "^" + category + "$"):
                    self.api.check_orders()
            self.enums[enum_name] = original
        self.api.resolve_kucoin_spot()
        self.assertTrue(self.api.check_orders())

    def test_duplicate_order_ids_rejected_with_matching_count(self):
        self.api.resolve_kucoin_spot()
        first = copy.deepcopy(self.orders["data"]["BTC_USDT"][0])
        self.orders["data"]["BTC_USDT"].append(copy.deepcopy(first))
        self.orders["cnt"] = 2
        with self.assertRaisesRegex(BitsgapError, "^DUPLICATE_ORDER_ID$"):
            self.api.check_orders()
        # IDs must be unique across the entire snapshot, not just per pair.
        self.orders["data"]["BTC_USDT"].pop()
        self.orders["data"]["ETH_USDT"] = [copy.deepcopy(first)]
        with self.assertRaisesRegex(BitsgapError, "^DUPLICATE_ORDER_ID$"):
            self.api.check_orders()
        self.orders["data"]["ETH_USDT"][0]["id"] = "synthetic-distinct"
        self.assertTrue(self.api.check_orders())

    def test_empty_results_are_explicitly_unverified(self):
        self.api.resolve_kucoin_spot()
        self.balance = {"data": {}}
        self.orders = {"data": {}, "cnt": 0}
        with self.assertRaisesRegex(BitsgapError, "^EMPTY_BALANCE_UNVERIFIED$"):
            self.api.check_balance()
        with self.assertRaisesRegex(BitsgapError, "^EMPTY_ORDERS_UNVERIFIED$"):
            self.api.check_orders()

    def test_unknown_and_direct_wrappers_rejected(self):
        self.api.resolve_kucoin_spot()
        for value in (None, [], {}, {"ok": True}, {"error": "denied"},
                      {"USDT": {"t": "1", "a": "1"}}, {"data": {"data": {}}}):
            self.balance = value
            with self.assertRaises(BitsgapError):
                self.api.check_balance()
        for value in (None, [], {}, {"data": []}, {"data": {}, "cnt": True}):
            self.orders = value
            with self.assertRaises(BitsgapError):
                self.api.check_orders()

    def test_invalid_balance_amounts_and_fields(self):
        self.api.resolve_kucoin_spot()
        for amount in (1, True, "NaN", "Infinity", "-1", "1e99999", " 1", "1_0"):
            self.balance = {"data": {"USDT": {"t": amount, "a": "0"}}}
            with self.assertRaises(BitsgapError):
                self.api.check_balance()
        for record in ({"t": "1"}, {"t": "1", "a": "2"},
                       {"t": "1", "a": "1", "l": "1"}, {"t": "1", "a": "1", "error": "x"}):
            self.balance = {"data": {"USDT": record}}
            with self.assertRaises(BitsgapError):
                self.api.check_balance()

    def test_order_record_validation(self):
        self.api.resolve_kucoin_spot()
        original = copy.deepcopy(self.orders)
        for field, value in (("id", 1), ("t0", True), ("eot", -1),
                             ("am", "0"), ("pr", "NaN"), ("eid", {}), ("ro", True)):
            self.orders = copy.deepcopy(original)
            self.orders["data"]["BTC_USDT"][0][field] = value
            with self.assertRaises(BitsgapError):
                self.api.check_orders()
        self.orders = copy.deepcopy(original)
        del self.orders["data"]["BTC_USDT"][0]["pr"]
        with self.assertRaises(BitsgapError):
            self.api.check_orders()
        self.orders = copy.deepcopy(original)
        self.orders["cnt"] = 2
        with self.assertRaisesRegex(BitsgapError, "COUNT_UNVERIFIED"):
            self.api.check_orders()

    def test_undocumented_optional_order_fields_and_types_fail_closed(self):
        self.api.resolve_kucoin_spot()
        self.orders["data"]["BTC_USDT"][0]["f"] = {}
        with self.assertRaisesRegex(BitsgapError, "UNVERIFIED_ORDER_OPTIONAL_SCHEMA"):
            self.api.check_orders()
        del self.orders["data"]["BTC_USDT"][0]["f"]
        self.api._order_types = None
        with self.assertRaisesRegex(BitsgapError, "UNVERIFIED_ORDER_TYPE_ENUM"):
            self.api.check_orders()

    def test_http_errors_are_not_empty_data_or_permission_claims(self):
        self.api.resolve_kucoin_spot()
        for status in (400, 401, 403, 408, 429, 500):
            self.balance = BitsgapError("HTTP_" + str(status))
            with self.assertRaisesRegex(BitsgapError, "^HTTP_" + str(status) + "$"):
                self.api.check_balance()

    def test_invalid_json_and_outer_envelope(self):
        for raw in (b"invalid", b"[]", b"{}", b"null"):
            api = BitsgapReadOnly(self.pem, lambda *args: raw)
            with self.assertRaises(BitsgapError):
                api.handshake()

    def test_probe_emits_fixed_statuses_only(self):
        output = io.StringIO()
        with patch.object(BitsgapReadOnly, "from_env", return_value=self.api), contextlib.redirect_stdout(output):
            self.assertEqual(main(), 0)
        text = output.getvalue()
        for status in ("BITSGAP_API_AUTH", "KUCOIN_EXCHANGE_RESOLVED",
                       "KUCOIN_BALANCE_ACCESS", "KUCOIN_ORDERS_ACCESS"):
            self.assertIn(status + "=PASS", text)
        for sensitive in ("USDT", "synthetic", "65000", self.pem, "signature", "731"):
            self.assertNotIn(sensitive, text)
        self.assertIn("DAIINAS_ORDER_ROUTING=DISABLED", text)

    def test_probe_redacts_untrusted_exception_and_continues_independent_read(self):
        self.balance = BitsgapError("SECRET_ACCOUNT_MARKER")
        output = io.StringIO()
        with patch.object(BitsgapReadOnly, "from_env", return_value=self.api), contextlib.redirect_stdout(output):
            self.assertEqual(main(), 1)
        self.assertNotIn("SECRET_ACCOUNT_MARKER", output.getvalue())
        self.assertIn("KUCOIN_ORDERS_ACCESS=PASS", output.getvalue())


    def test_failed_auth_stops_before_account_calls(self):
        def fail(*args):
            raise BitsgapError("HTTP_403")
        self.api._transport = fail
        output = io.StringIO()
        with patch.object(BitsgapReadOnly, "from_env", return_value=self.api), contextlib.redirect_stdout(output):
            self.assertEqual(main(), 1)
        self.assertIn("BITSGAP_API_AUTH=FAIL; CATEGORY=HTTP_403", output.getvalue())
        self.assertIn("KUCOIN_BALANCE_ACCESS=NOT_TESTED", output.getvalue())
        self.assertIn("KUCOIN_ORDERS_ACCESS=NOT_TESTED", output.getvalue())
        self.assertFalse(self.calls)

    def test_probe_empty_data_does_not_claim_access(self):
        self.balance = {"data": {}}
        self.orders = {"data": {}, "cnt": 0}
        output = io.StringIO()
        with patch.object(BitsgapReadOnly, "from_env", return_value=self.api), contextlib.redirect_stdout(output):
            self.assertEqual(main(), 1)
        self.assertIn("KUCOIN_BALANCE_ACCESS=FAIL; CATEGORY=EMPTY_BALANCE_UNVERIFIED", output.getvalue())
        self.assertIn("KUCOIN_ORDERS_ACCESS=FAIL; CATEGORY=EMPTY_ORDERS_UNVERIFIED", output.getvalue())


    def test_outer_envelope_rejects_extra_errors_duplicates_and_non_json_numbers(self):
        for raw in (b'{"data":{},"error":"SECRET"}', b'{"data":{},"data":{}}',
                    b'{"data":{"amount":NaN}}', b'{"data":{"amount":Infinity}}'):
            api = BitsgapReadOnly(self.pem, lambda *args: raw)
            with self.assertRaises(BitsgapError):
                api.topic("manual")

    def test_market_price_and_unknown_order_type_fail_closed(self):
        self.api.resolve_kucoin_spot()
        self.orders["data"]["BTC_USDT"][0]["eot"] = 2
        with self.assertRaisesRegex(BitsgapError, "INVALID_ACCOUNT_SCHEMA"):
            self.api.check_orders()
        del self.orders["data"]["BTC_USDT"][0]["pr"]
        self.assertTrue(self.api.check_orders())
        self.api._order_types = {"UNKNOWN": 2}
        with self.assertRaisesRegex(BitsgapError, "UNVERIFIED_ORDER_TYPE_ENUM"):
            self.api.check_orders()

    def test_large_decimal_conservation_uses_exact_precision(self):
        self.balance = {"data": {"USDT": {"t": "1" + "0" * 80,
                                          "a": "1" + "0" * 80, "l": "1"}}}
        self.api.resolve_kucoin_spot()
        with self.assertRaisesRegex(BitsgapError, "INVALID_ACCOUNT_SCHEMA"):
            self.api.check_balance()

    def test_probe_safety_invariants_label_owner_configuration(self):
        output = io.StringIO()
        with patch.object(BitsgapReadOnly, "from_env", return_value=self.api), contextlib.redirect_stdout(output):
            self.assertEqual(main(), 0)
        self.assertIn("LIVE_TRADING=DISABLED", output.getvalue())
        self.assertIn("FUTURES_POSITION_MODE=ONE_WAY", output.getvalue())
        self.assertIn("FUTURES_POSITION_MODE_SOURCE=OWNER_CONFIGURATION_NOT_API_VERIFIED", output.getvalue())


if __name__ == "__main__":
    unittest.main()
