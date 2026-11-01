"""Bitsgap REST v1 Ed25519 handshake, strictly allowlisted read topics.

This client never exposes trading commands or mutable endpoint selection.
The underlying Bitsgap API key itself MAY have live trading authority.
"""
import base64
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.request

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_URL = "https://open.bitsgap.com/api/v1/topic"
_ALLOWED = frozenset(("manual", "conf_enums"))


class BitsgapError(RuntimeError):
    def __init__(self, category):
        self.category = category
        super().__init__(category)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _post(url, body, headers):
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=15) as resp:
            data = resp.read(1000001)
            if len(data) > 1000000:
                raise BitsgapError("OVERSIZED_RESPONSE")
            return data
    except urllib.error.HTTPError as err:
        code = err.code if isinstance(err.code, int) and 100 <= err.code <= 599 else 0
        raise BitsgapError("HTTP_" + str(code)) from None
    except urllib.error.URLError:
        raise BitsgapError("NETWORK_UNAVAILABLE") from None


class BitsgapReadOnly:
    def __init__(self, private_key_pem, transport=_post):
        if not private_key_pem:
            raise BitsgapError("MISSING_GITHUB_ACTIONS_SECRET")
        try:
            data = private_key_pem.encode("utf-8") if isinstance(private_key_pem, str) else private_key_pem
            key = serialization.load_pem_private_key(data, password=None)
        except (TypeError, ValueError):
            raise BitsgapError("INVALID_PRIVATE_KEY_PEM") from None
        if not isinstance(key, Ed25519PrivateKey):
            raise BitsgapError("WRONG_PRIVATE_KEY_TYPE")
        self._key = key
        self._transport = transport
        public_der = key.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        self._public = base64.b64encode(public_der).decode("ascii")

    @classmethod
    def from_env(cls, environ=None, transport=_post):
        env = os.environ if environ is None else environ
        return cls(env.get("BITSGAP_PRIVATE_KEY_PEM"), transport=transport)

    def topic(self, name, params=None, *, timestamp=None, nonce=None):
        if name not in _ALLOWED:
            raise BitsgapError("NON_READ_ONLY_TOPIC_REFUSED")
        if params is None:
            params = {}
        if not isinstance(params, dict) or params:
            raise BitsgapError("UNEXPECTED_TOPIC_PARAMETERS")
        ts = int(time.time()) if timestamp is None else timestamp
        if type(ts) is not int:
            raise BitsgapError("INVALID_TIMESTAMP")
        token = secrets.token_hex(16) if nonce is None else nonce
        if not isinstance(token, str) or len(token) > 80 or not token.isalnum():
            raise BitsgapError("INVALID_NONCE")
        payload_bytes = json.dumps(params, separators=(",", ":")).encode("utf-8")
        digest = base64.b64encode(hashlib.sha256(payload_bytes).digest()).decode("ascii")
        canonical = f"btg-rest\nv1\n{token}\n{ts}\n{name}\n{digest}".encode("utf-8")
        signature = base64.b64encode(self._key.sign(canonical)).decode("ascii")
        # Insert hashed payload bytes verbatim; never reserialize them.
        body = (
            b'{"topic":' + json.dumps(name).encode("utf-8")
            + b',"ts":' + str(ts).encode("ascii")
            + b',"nonce":' + json.dumps(token).encode("utf-8")
            + b',"payload":' + payload_bytes
            + b',"signature":' + json.dumps(signature).encode("ascii") + b"}"
        )
        headers = {"Content-Type": "application/json", "X-Api-Public-Key": self._public}
        try:
            raw = self._transport(_URL, body, headers)
            obj = json.loads(raw)
        except BitsgapError:
            raise
        except (ValueError, TypeError, UnicodeError):
            raise BitsgapError("INVALID_RESPONSE") from None
        if not isinstance(obj, dict) or "data" not in obj:
            raise BitsgapError("UNEXPECTED_RESPONSE_SHAPE")
        return obj["data"]

    @staticmethod
    def _safe_shape(value):
        # Only fixed type labels; never return any response content or field values.
        if isinstance(value, dict):
            return "DICT"
        if isinstance(value, list):
            return "LIST"
        if isinstance(value, str):
            return "STRING"
        if isinstance(value, (int, float, bool)):
            return "SCALAR"
        if value is None:
            return "NULL"
        return "OTHER"

    @classmethod
    def _shape_error(cls, category, payload):
        # Bounded metadata based on known protocol field names, never unknown keys.
        if not isinstance(payload, dict):
            return BitsgapError(category + "; ROOT=" + cls._safe_shape(payload))
        return BitsgapError(
            category
            + "; ROOT=DICT"
            + "; DATA=" + cls._safe_shape(payload.get("data"))
            + "; VALUE=" + cls._safe_shape(payload.get("value"))
            + "; DESCR=" + cls._safe_shape(payload.get("descr"))
            + "; OK=" + ("PRESENT" if "ok" in payload else "ABSENT")
            + "; TOPIC=" + ("PRESENT" if "topic" in payload else "ABSENT")
            + "; MANUAL=" + cls._safe_shape(payload.get("manual"))
            + "; CONF_ENUMS=" + cls._safe_shape(payload.get("conf_enums"))
            + "; MARKET=" + cls._safe_shape(payload.get("market"))
        )

    def handshake(self):
        # REST /api/v1/topic returns {"data": <topic value>}.
        # topic() has already unwrapped that one outer envelope.
        # The manual value is a mapping of topic names directly to descriptors;
        # the conf_enums value maps enum names to their reference tables.
        manual = self.topic("manual")
        if (not isinstance(manual, dict)
                or not isinstance(manual.get("manual"), dict)
                or not isinstance(manual.get("conf_enums"), dict)):
            raise self._shape_error("UNEXPECTED_MANUAL_RESPONSE", manual)
        enums = self.topic("conf_enums")
        if (not isinstance(enums, dict)
                or not isinstance(enums.get("market"), dict)
                or not isinstance(enums["market"].get("items"), dict)):
            raise self._shape_error("UNEXPECTED_ENUMS_RESPONSE", enums)
        # These two static metadata topics prove Bitsgap API access only.
        # Neither KuCoin scope nor account balance is authenticated yet.
        return {"bitsgap_authenticated": True, "kucoin_account_reconciled": False,
                "order_routing_enabled": False}
