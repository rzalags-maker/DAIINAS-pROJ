"""Offline tests for the Bitsgap no-trading REST adapter."""
import base64
import json
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from daiinas.bitsgap_readonly import BitsgapError, BitsgapReadOnly


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


if __name__ == "__main__":
    unittest.main()
