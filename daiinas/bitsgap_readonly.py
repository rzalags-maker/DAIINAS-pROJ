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
import re
from decimal import Decimal, InvalidOperation, localcontext
import urllib.error
import urllib.request

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_URL = "https://open.bitsgap.com/api/v1/topic"
_ALLOWED = frozenset(("manual", "conf_enums", "balance", "orders"))
_SIGNED_READ_ONLY = _ALLOWED | frozenset(("positions", "positions_settings", "orders_history", "conf_pairs"))


class BitsgapError(RuntimeError):
    def __init__(self, category):
        self.category = category
        super().__init__(category)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON member")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("Non-JSON numeric constant")


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
        self._spot_em = None
        self._order_types = None
        self._order_states = None
        self._order_sides = None
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
        if not isinstance(params, dict):
            raise BitsgapError("UNEXPECTED_TOPIC_PARAMETERS")
        if name in ("balance", "orders"):
            if (set(params) != {"em"} or type(params["em"]) is not int
                    or self._spot_em is None or params["em"] != self._spot_em):
                raise BitsgapError("UNEXPECTED_EXCHANGE_PARAMETERS")
        elif params:
            raise BitsgapError("UNEXPECTED_TOPIC_PARAMETERS")
        return self._signed_read(name, params, timestamp=timestamp, nonce=nonce)

    def _signed_read(self, name, params, *, timestamp=None, nonce=None):
        # Canonical Ed25519 and transport bytes stay unchanged. Harden internal helper.
        if name not in _SIGNED_READ_ONLY:
            raise BitsgapError("NON_READ_ONLY_TOPIC_REFUSED")
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
            obj = json.loads(raw, object_pairs_hook=_unique_object,
                             parse_constant=_reject_constant)
        except BitsgapError:
            raise
        except (ValueError, TypeError, UnicodeError):
            raise BitsgapError("INVALID_RESPONSE") from None
        if not isinstance(obj, dict) or "data" not in obj:
            raise BitsgapError("UNEXPECTED_RESPONSE_SHAPE")
        keys = set(obj)
        # Real Bitsgap topic values may appear directly on REST:
        # manual: {data, descr}; conf_enums: {data, aliases};
        # orders/positions: {data, cnt, optional epmd/epm}.
        # Preserve the historical {data: <topic-value>} envelope.
        if name == "manual" and keys == {"data", "descr"}:
            if not isinstance(obj["data"], dict) or not isinstance(obj["descr"], str):
                raise BitsgapError("UNEXPECTED_RESPONSE_SHAPE")
            return obj["data"]
        if name == "conf_enums" and keys == {"data", "aliases"}:
            if not isinstance(obj["data"], dict) or not isinstance(obj["aliases"], dict):
                raise BitsgapError("UNEXPECTED_RESPONSE_SHAPE")
            return obj["data"]
        if name in ("orders", "positions", "positions_settings") and "cnt" in keys:
            if (keys - {"data", "cnt", "epmd", "epm"} or type(obj["cnt"]) is not int
                    or not isinstance(obj["data"], dict)):
                raise BitsgapError("UNEXPECTED_RESPONSE_SHAPE")
            return obj
        if keys != {"data"}:
            raise BitsgapError("UNEXPECTED_RESPONSE_SHAPE")
        if name == "balance":
            # Direct topic value: {data: {USDT: {t,a}}}.
            # Wrapped envelope: {data: {data: {USDT: {t,a}}}}.
            return obj["data"] if isinstance(obj["data"], dict) and "data" in obj["data"] else obj
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

    def resolve_kucoin_spot(self):
        """Resolve a real Spot catalog entry, never a connected-account identity."""
        self._spot_em = None
        self._order_types = None
        self._order_states = None
        self._order_sides = None
        enums = self.topic("conf_enums")
        market = enums.get("market") if isinstance(enums, dict) else None
        if (not isinstance(market, dict) or market.get("alias") != "em"
                or not isinstance(market.get("items"), dict)):
            raise BitsgapError("INVALID_MARKET_ENUM_SCHEMA")
        items = market["items"]
        if any(not isinstance(k, str) or type(v) is not int or v <= 0
               for k, v in items.items()):
            raise BitsgapError("INVALID_MARKET_ENUM_SCHEMA")
        # Only explicit real Spot spellings. Unknown variants fail closed.
        matches = [v for k, v in items.items()
                   if k.upper().replace(" ", "_") in ("KUCOIN", "KUCOIN_SPOT")]
        if (len(matches) != 1
                or sum(v == matches[0] for v in items.values()) != 1):
            raise BitsgapError("KUCOIN_SPOT_ENUM_UNRESOLVED")
        self._spot_em = matches[0]
        types = enums.get("order_type", {}).get("items") if isinstance(
            enums.get("order_type", {}), dict) else None
        if (isinstance(types, dict) and types and all(isinstance(k, str)
                and type(v) is int and v >= 0 for k, v in types.items())
                and len(set(types.values())) == len(types)):
            self._order_types = types
        # Unknown catalog tables never earn account-data PASS.
        for enum_name, alias, dest in (
                ("order_state", "eost", "_order_states"),
                ("order_side", "eos", "_order_sides")):
            table = enums.get(enum_name)
            entries = table.get("items") if isinstance(table, dict) and table.get("alias") == alias else None
            if (isinstance(entries, dict) and entries
                    and all(isinstance(k, str) and k and type(v) is int and v >= 0
                            for k, v in entries.items())
                    and len(set(entries.values())) == len(entries)):
                setattr(self, dest, entries)
        return self._spot_em

    @staticmethod
    def _decimal(value, *, positive=False):
        if (not isinstance(value, str) or len(value) > 128
                or re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value) is None):
            raise BitsgapError("INVALID_ACCOUNT_SCHEMA")
        try:
            number = Decimal(value)
        except InvalidOperation:
            raise BitsgapError("INVALID_ACCOUNT_SCHEMA") from None
        if not number.is_finite() or number < 0 or (positive and number <= 0):
            raise BitsgapError("INVALID_ACCOUNT_SCHEMA")
        return number

    @classmethod
    def validate_balance(cls, value):
        # Documented topic-value wrapper only; never recursively unwrap data.
        if (not isinstance(value, dict) or set(value) != {"data"}
                or not isinstance(value["data"], dict)):
            raise BitsgapError("UNVERIFIED_BALANCE_RESPONSE_SHAPE")
        if not value["data"]:
            raise BitsgapError("EMPTY_BALANCE_UNVERIFIED")
        for currency, record in value["data"].items():
            if (not isinstance(currency, str) or not currency
                    or not isinstance(record, dict)
                    or not {"t", "a"} <= set(record)
                    or not set(record) <= {"t", "a", "l"}):
                raise BitsgapError("INVALID_ACCOUNT_SCHEMA")
            total, available = cls._decimal(record["t"]), cls._decimal(record["a"])
            locked = cls._decimal(record["l"]) if "l" in record else Decimal(0)
            with localcontext() as context:
                context.prec = 256
                if available > total or available + locked > total:
                    raise BitsgapError("INVALID_ACCOUNT_SCHEMA")
        return True

    @classmethod
    def validate_orders(cls, value, order_types=None, order_states=None, order_sides=None):
        if (not isinstance(value, dict) or set(value) != {"data", "cnt"}
                or not isinstance(value["data"], dict)
                or type(value["cnt"]) is not int or value["cnt"] < 0):
            raise BitsgapError("UNVERIFIED_ORDERS_RESPONSE_SHAPE")
        if not order_states:
            raise BitsgapError("UNVERIFIED_ORDER_STATE_ENUM")
        if not order_sides:
            raise BitsgapError("UNVERIFIED_ORDER_SIDE_ENUM")
        count = 0
        seen_ids = set()
        for pair, orders in value["data"].items():
            if not isinstance(pair, str) or not pair or not isinstance(orders, list):
                raise BitsgapError("INVALID_ACCOUNT_SCHEMA")
            for order in orders:
                if (not isinstance(order, dict)
                        or not {"id", "eost", "eot", "eos", "t0"} <= set(order)
                        or not isinstance(order["id"], str) or not order["id"]
                        or any(type(order[k]) is not int or order[k] < 0
                               for k in ("eost", "eot", "eos", "t0"))):
                    raise BitsgapError("INVALID_ACCOUNT_SCHEMA")
                if order["id"] in seen_ids:
                    raise BitsgapError("DUPLICATE_ORDER_ID")
                seen_ids.add(order["id"])
                if order["eost"] not in order_states.values():
                    raise BitsgapError("UNVERIFIED_ORDER_STATE_ENUM")
                if order["eos"] not in order_sides.values():
                    raise BitsgapError("UNVERIFIED_ORDER_SIDE_ENUM")
                side_name = next(k for k, v in order_sides.items() if v == order["eos"])
                if side_name not in ("BUY", "SELL"):
                    raise BitsgapError("UNVERIFIED_ORDER_SIDE_ENUM")
                allowed = {"id", "eost", "eot", "eos", "t0", "am", "pr", "eid",
                           "ame", "pre", "tl", "f", "apiid"}
                if not set(order) <= allowed:
                    raise BitsgapError("INVALID_ACCOUNT_SCHEMA")
                if not order_types or order["eot"] not in order_types.values():
                    raise BitsgapError("UNVERIFIED_ORDER_TYPE_ENUM")
                type_name = next(k for k, v in order_types.items() if v == order["eot"])
                if type_name not in ("LIMIT", "MARKET"):
                    raise BitsgapError("UNVERIFIED_ORDER_TYPE_ENUM")
                if ((type_name == "LIMIT" and "pr" not in order)
                        or (type_name == "MARKET" and "pr" in order)):
                    raise BitsgapError("INVALID_ACCOUNT_SCHEMA")
                # Partial-fill/fee structures lack a complete schema in the
                # supplied reference. Do not bless them using guessed types.
                if set(order) & {"ame", "pre", "tl", "f"}:
                    raise BitsgapError("UNVERIFIED_ORDER_OPTIONAL_SCHEMA")
                for field in ("am", "pr"):
                    if field in order:
                        cls._decimal(order[field], positive=True)
                for field in ("eid", "apiid"):
                    if field in order and not isinstance(order[field], str):
                        raise BitsgapError("INVALID_ACCOUNT_SCHEMA")
                count += 1
        if count == 0 and value["cnt"] == 0:
            raise BitsgapError("EMPTY_ORDERS_UNVERIFIED")
        # Full-snapshot count semantics are not established by the reference.
        if count != value["cnt"]:
            raise BitsgapError("ORDER_SNAPSHOT_COUNT_UNVERIFIED")
        return True

    def check_balance(self):
        if self._spot_em is None:
            raise BitsgapError("KUCOIN_SPOT_ENUM_UNRESOLVED")
        return self.validate_balance(self.topic("balance", {"em": self._spot_em}))

    def check_orders(self):
        if self._spot_em is None:
            raise BitsgapError("KUCOIN_SPOT_ENUM_UNRESOLVED")
        return self.validate_orders(self.topic("orders", {"em": self._spot_em}),
                                    self._order_types, self._order_states, self._order_sides)


def main():
    """Explicit manual probe; emits fixed statuses, never account content."""
    checks = ("BITSGAP_API_AUTH", "KUCOIN_EXCHANGE_RESOLVED",
              "KUCOIN_BALANCE_ACCESS", "KUCOIN_ORDERS_ACCESS")
    results = dict.fromkeys(checks, "NOT_TESTED")
    print("DAIINAS_ORDER_ROUTING=DISABLED")
    print("LIVE_TRADING=DISABLED")
    print("FUTURES_POSITION_MODE=ONE_WAY")
    print("FUTURES_POSITION_MODE_SOURCE=OWNER_CONFIGURATION_NOT_API_VERIFIED")
    current = checks[0]
    try:
        client = BitsgapReadOnly.from_env()
        for current, operation in zip(checks, (client.handshake,
                client.resolve_kucoin_spot, client.check_balance, client.check_orders)):
            try:
                operation()
                results[current] = "PASS"
            except BitsgapError as exc:
                # Category allowlist excludes arbitrary messages/response data.
                safe = {"INVALID_MARKET_ENUM_SCHEMA", "KUCOIN_SPOT_ENUM_UNRESOLVED",
                        "UNVERIFIED_BALANCE_RESPONSE_SHAPE", "UNVERIFIED_ORDERS_RESPONSE_SHAPE",
                        "EMPTY_BALANCE_UNVERIFIED", "EMPTY_ORDERS_UNVERIFIED",
                        "INVALID_ACCOUNT_SCHEMA", "UNVERIFIED_ORDER_OPTIONAL_SCHEMA",
                        "UNVERIFIED_ORDER_TYPE_ENUM", "UNVERIFIED_ORDER_STATE_ENUM",
                        "UNVERIFIED_ORDER_SIDE_ENUM", "DUPLICATE_ORDER_ID",
                        "ORDER_SNAPSHOT_COUNT_UNVERIFIED", "NETWORK_UNAVAILABLE",
                        "INVALID_RESPONSE", "UNEXPECTED_RESPONSE_SHAPE", "OVERSIZED_RESPONSE"}
                category = exc.category if exc.category in safe or re.fullmatch(
                    r"HTTP_[1-5][0-9]{2}", exc.category) else "RESPONSE_OR_AUTH_FAILURE"
                results[current] = "FAIL; CATEGORY=" + category
                if current in checks[:2]:
                    break
    except Exception:
        results[current] = "FAIL; CATEGORY=SETUP_OR_RUNTIME_FAILURE"
    for check in checks:
        print(check + "=" + results[check])
    return 0 if all(v == "PASS" for v in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
