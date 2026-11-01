"""Bitsgap KuCoin Futures: read-only OBSERVE capability, wallet and exposure.

No order transport; no live-account promotion into the Model A PAPER ledger.
The existing Ed25519 REST signer is reused without changing its canonical bytes.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import json
import re
import time

from .bitsgap_readonly import BitsgapReadOnly, BitsgapError

# Every remotely invoked topic must be here. Never append order_place or other writes.
_OBSERVE = frozenset({"balance", "orders", "positions", "positions_settings",
                      "orders_history", "conf_pairs"})
_REQUIRED = frozenset({"balance", "orders", "positions", "positions_settings"})
_PAIR = re.compile(r"^[A-Z0-9]{2,30}_[A-Z0-9]{2,30}$")


def _fail(category):
    raise BitsgapError(category)


def _value(value, *, positive=False):
    return BitsgapReadOnly._decimal(value, positive=positive)


def _index_catalog(value, name):
    """Accept documented value.data and original direct catalog representations."""
    if not isinstance(value, dict):
        _fail("UNVERIFIED_" + name + "_SCHEMA")
    if "data" in value:
        keys = {"data", "descr"} if name == "MANUAL" else {"data", "aliases"}
        if set(value) - keys or not isinstance(value["data"], dict):
            _fail("UNVERIFIED_" + name + "_SCHEMA")
        return value["data"]
    return value


def _enum_tables(enums):
    market = enums.get("market")
    if not isinstance(market, dict) or market.get("alias") != "em":
        _fail("UNVERIFIED_FUTURES_ENUM")
    items = market.get("items")
    if (not isinstance(items, dict) or not items or
        any(not isinstance(k, str) or not k or type(v) is not int or v <= 0
            for k, v in items.items()) or len(set(items.values())) != len(items)):
        _fail("UNVERIFIED_FUTURES_ENUM")
    # Fail closed on ambiguity, demo, Spot and unfamiliar variant labels.
    matches = [v for k, v in items.items() if k.upper() == "KUCOIN_FUTURES"]
    if len(matches) != 1:
        _fail("KUCOIN_FUTURES_ENUM_UNRESOLVED")
    return matches[0]


def _enum(enums, table, alias, number):
    entry = enums.get(table)
    if (not isinstance(entry, dict) or entry.get("alias") != alias
        or not isinstance(entry.get("items"), dict)):
        _fail("UNVERIFIED_" + table.upper() + "_ENUM")
    items = entry["items"]
    if (not items or any(not isinstance(k, str) or not k or type(v) is not int or v < 0
                         for k, v in items.items()) or len(set(items.values())) != len(items)):
        _fail("UNVERIFIED_" + table.upper() + "_ENUM")
    found = [k for k, v in items.items() if v == number]
    if len(found) != 1:
        _fail("UNVERIFIED_" + table.upper() + "_ENUM")
    return found[0]


def _counter(value, label):
    if not isinstance(value, dict) or not isinstance(value.get("data"), dict):
        _fail("UNVERIFIED_" + label + "_SHAPE")
    if type(value.get("cnt")) is not int or value["cnt"] < 0:
        _fail("UNVERIFIED_" + label + "_COUNT")
    if set(value) - {"data", "cnt", "epmd", "epm"}:
        _fail("UNVERIFIED_" + label + "_SHAPE")
    return value["data"], value["cnt"]


@dataclass(frozen=True, repr=False)
class FuturesAccountObservation:
    market_id: int                 # Exchange enum ID, NOT a private account ID.
    observed_unix_ms: int
    total_usdt: str                # Bitsgap balance.t, NOT verified futures equity.
    available_usdt: str            # Bitsgap balance.a, NOT Model A ACTIVE.
    open_orders: int
    open_positions: int
    position_settings: int
    position_mode: str             # Verified enum when supplied, else UNVERIFIED.
    margin_mode: str               # Verified enum when supplied, else UNVERIFIED.
    completeness: str
    strategy_funding_authorized: bool = False
    order_routing_enabled: bool = False

    def __repr__(self):
        return "FuturesAccountObservation(OBSERVE, PRIVATE_AMOUNTS_REDACTED, NOT_RECONCILED)"

    def private_panel(self):
        """Call only in an authenticated private interface, NEVER CI stdout."""
        return {"venue": "KUCOIN_FUTURES", "mode": "OBSERVE", "source": "BITSGAP_API",
                "observed_unix_ms": self.observed_unix_ms,
                "usdt_total_reported": self.total_usdt,
                "usdt_available_reported": self.available_usdt,
                "open_orders": self.open_orders, "open_positions": self.open_positions,
                "position_settings": self.position_settings,
                "position_mode": self.position_mode, "margin_mode": self.margin_mode,
                "futures_equity": "UNVERIFIED", "net_free_margin": "UNVERIFIED",
                "model_a_active": "UNVERIFIED", "model_a_reserve": "UNVERIFIED",
                "new_entry": "NO_TRADE_ACCOUNT_NOT_RECONCILED",
                "real_order_routing": "DISABLED"}

    def safe_status(self):
        """Safe for CI; contains no balances, account ID, order IDs or keys."""
        return {"status": self.completeness, "venue": "KUCOIN_FUTURES",
                "balance_schema": "VALIDATED", "exposure_scope": "VALIDATED",
                "capital_reconciled": False, "orders_enabled": False}



@dataclass(frozen=True, repr=False)
class FuturesWalletObservation:
    """An authenticated balance with independently checked exposure scopes.

    This is deliberately NOT FuturesAccountSnapshot and CANNOT fund Model A.
    Unknown orders/positions are None, never zero or a cleared liability.
    """
    received_unix_ms: int
    total_usdt: str
    available_usdt: str
    order_count: int | None
    position_count: int | None
    setting_count: int | None
    orders_status: str
    positions_status: str
    settings_status: str
    position_mode: str
    margin_mode: str

    def __repr__(self):
        return "FuturesWalletObservation(AMOUNTS_REDACTED, REAL_TRADING_DISABLED)"

    def safe_status(self):
        """Redacted evidence suitable for CI; NEVER include private balances."""
        return {"status": "PARTIAL_OBSERVATION_NOT_RECONCILED"
                if any(v != "VALIDATED" for v in
                       (self.orders_status, self.positions_status, self.settings_status))
                else "OBSERVED_NON_ATOMIC_NOT_RECONCILED",
                "source": "BITSGAP_KUCOIN_FUTURES",
                "balance": "VALIDATED",
                "orders": self.orders_status,
                "positions": self.positions_status,
                "positions_settings": self.settings_status,
                "capital_reconciled": False,
                "orders_enabled": False}

    def private_panel(self):
        """Visible ONLY to the authenticated operator, never CI/public logs."""
        return {"source": "BITSGAP_KUCOIN_FUTURES", "mode": "OBSERVE",
                "received_unix_ms": self.received_unix_ms,
                "usdt_total_reported": self.total_usdt,
                "usdt_available_reported": self.available_usdt,
                "orders": (self.order_count if self.orders_status == "VALIDATED" else "UNVERIFIED"),
                "positions": (self.position_count if self.positions_status == "VALIDATED" else "UNVERIFIED"),
                "position_settings": (self.setting_count if self.settings_status == "VALIDATED" else "UNVERIFIED"),
                "position_mode": self.position_mode, "margin_mode": self.margin_mode,
                "futures_equity": "UNVERIFIED", "net_free_margin": "UNVERIFIED",
                "model_a_active": "UNVERIFIED", "model_a_reserve": "UNVERIFIED",
                "new_entry": "NO_TRADE_ACCOUNT_NOT_RECONCILED",
                "real_order_routing": "DISABLED"}



class BitsgapFuturesObserver(BitsgapReadOnly):
    """Separately authorized FUTURES reads, while Spot client remains sealed."""

    def __init__(self, private_key_pem, transport=None, *, clock_ms=None):
        if transport is None:
            super().__init__(private_key_pem)
        else:
            super().__init__(private_key_pem, transport=transport)
        self._futures_em = None
        self._futures_enums = None
        self._capabilities = None
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))

    def discover(self):
        # Do not retain a previously valid market on a subsequent failed discovery.
        self._futures_em = None
        self._futures_enums = None
        self._capabilities = None
        catalog = _index_catalog(super().topic("manual"), "MANUAL")
        if not isinstance(catalog, dict) or not _REQUIRED <= set(catalog):
            _fail("UNVERIFIED_MANUAL_CAPABILITIES")
        for name in _REQUIRED:
            desc = catalog[name]
            if not isinstance(desc, dict):
                _fail("UNVERIFIED_MANUAL_CAPABILITIES")
            transport = desc.get("transport")
            if transport is not None and (not isinstance(transport, dict) or transport.get("rest") is not True):
                _fail("UNVERIFIED_REST_CAPABILITY")
        enums = _index_catalog(super().topic("conf_enums"), "ENUMS")
        em = _enum_tables(enums)
        self._futures_em, self._futures_enums = em, enums
        self._capabilities = frozenset(catalog)
        return {"futures_market_resolved": True,
                "balance_orders_positions_discoverable": True,
                "order_routing_enabled": False}

    def read(self, topic, *, pair=None):
        # Never delegate arbitrary callers to _signed_read. No write capability.
        if topic not in _OBSERVE:
            _fail("FUTURES_WRITE_OR_UNKNOWN_TOPIC_DENIED")
        if self._futures_em is None or self._futures_enums is None:
            _fail("FUTURES_DISCOVERY_REQUIRED")
        if self._capabilities is None or topic not in self._capabilities:
            _fail("TOPIC_NOT_IN_LIVE_CATALOG")
        params = {"em": self._futures_em}
        if pair is not None:
            if topic != "orders_history" or not isinstance(pair, str) or not _PAIR.fullmatch(pair):
                _fail("INVALID_OBSERVATION_PARAMETERS")
            params["pair"] = pair
        return self._signed_read(topic, params)

    def _balance(self, value):
        if not isinstance(value, dict) or set(value) != {"data"} or not isinstance(value["data"], dict):
            _fail("UNVERIFIED_FUTURES_BALANCE_SHAPE")
        ccy = value["data"].get("USDT")
        if not isinstance(ccy, dict) or set(ccy) != {"t", "a"}:
            # Locked 'l' is Spot-only. Do not pretend it is a Futures margin obligation.
            _fail("UNVERIFIED_USDT_FUTURES_BALANCE")
        t, a = _value(ccy["t"]), _value(ccy["a"])
        if a > t:
            _fail("FUTURES_BALANCE_RELATION_UNVERIFIED")
        return str(t), str(a)

    def _orders(self, value):
        rows, count = _counter(value, "ORDERS")
        if set(value) != {"data", "cnt"}:
            _fail("UNVERIFIED_ORDERS_SHAPE")
        actual = 0
        seen = set()
        allowed = {"id", "eost", "eot", "eos", "am", "pr", "eid", "t0", "epps", "etif",
                   "ro", "epm", "lv", "ame", "pre", "tl", "f", "apiid"}
        for pair, group in rows.items():
            if not isinstance(pair, str) or not _PAIR.fullmatch(pair) or not isinstance(group, list):
                _fail("UNVERIFIED_ORDERS_SHAPE")
            for order in group:
                if (not isinstance(order, dict) or not {"id", "eost", "eot", "eos", "epps", "t0"} <= set(order)
                    or set(order) - allowed or not isinstance(order["id"], str) or not order["id"]):
                    _fail("UNVERIFIED_ORDERS_RECORD")
                if order["id"] in seen:
                    _fail("DUPLICATE_FUTURES_ORDER_ID")
                seen.add(order["id"])
                for k, table, alias in (("eost", "order_state", "eost"), ("eot", "order_type", "eot"),
                                        ("eos", "order_side", "eos"), ("epps", "position_side", "epps")):
                    if type(order[k]) is not int or order[k] < 0:
                        _fail("UNVERIFIED_ORDER_ENUM_VALUE")
                    _enum(self._futures_enums, table, alias, order[k])
                if _enum(self._futures_enums, "order_side", "eos", order["eos"]) not in ("BUY", "SELL"):
                    _fail("UNVERIFIED_ORDER_SIDE")
                if type(order["t0"]) is not int or order["t0"] < 0:
                    _fail("UNVERIFIED_ORDER_TIMESTAMP")
                order_type = _enum(self._futures_enums, "order_type", "eot", order["eot"])
                if (order_type == "LIMIT" and "pr" not in order) or (order_type == "MARKET" and "pr" in order):
                    _fail("INVALID_ORDER_PRICE_FOR_TYPE")
                for field in ("am", "pr", "ame", "pre", "lv"):
                    if field in order:
                        _value(order[field], positive=True)
                for field in ("eid", "apiid"):
                    if field in order and (not isinstance(order[field], str) or not order[field]):
                        _fail("UNVERIFIED_ORDER_IDENTIFIER")
                for field, table, alias in (("epm", "position_margin", "epm"),
                                            ("etif", "order_tif", "etif")):
                    if field in order:
                        if type(order[field]) is not int:
                            _fail("UNVERIFIED_ORDER_ENUM_VALUE")
                        _enum(self._futures_enums, table, alias, order[field])
                if "ro" in order and (type(order["ro"]) is not int or order["ro"] not in (0, 1)):
                    _fail("UNVERIFIED_REDUCE_ONLY")
                if "tl" in order and (type(order["tl"]) is not int or order["tl"] < 0):
                    _fail("UNVERIFIED_ORDER_TIMESTAMP")
                if "f" in order:
                    fees = order["f"]
                    if not isinstance(fees, dict) or any(not isinstance(k, str) or not k or _value(v) < 0
                                                           for k, v in fees.items()):
                        _fail("UNVERIFIED_ORDER_FEES")
                actual += 1
        if actual != count:
            _fail("UNVERIFIED_ORDERS_COUNT")
        return actual

    def _positions(self, value, *, settings=False):
        rows, count = _counter(value, "POSITIONS_SETTINGS" if settings else "POSITIONS")
        actual = 0
        identities = set()
        for pair, group in rows.items():
            if not isinstance(pair, str) or not _PAIR.fullmatch(pair) or not isinstance(group, list):
                _fail("UNVERIFIED_POSITIONS_SHAPE")
            for record in group:
                if not isinstance(record, dict) or "epps" not in record:
                    _fail("UNVERIFIED_POSITIONS_RECORD")
                allowed = {"epps", "epm", "lv"} if settings else {
                    "epps", "epm", "lv", "eps", "am", "pr", "liq_price", "msize", "adm"}
                if set(record) - allowed or (not settings and not {"eps", "am", "pr"} <= set(record)):
                    _fail("UNVERIFIED_POSITIONS_RECORD")
                for field, tab, alias in (("epps", "position_side", "epps"),
                                           ("epm", "position_margin", "epm"),
                                           ("eps", "pos_side", "eps")):
                    if field in record:
                        if type(record[field]) is not int:
                            _fail("UNVERIFIED_POSITION_ENUM_VALUE")
                        _enum(self._futures_enums, tab, alias, record[field])
                for field in ("lv", "am", "pr", "liq_price", "msize"):
                    if field in record:
                        _value(record[field], positive=True)
                if "adm" in record and (type(record["adm"]) is not int or record["adm"] not in (0, 1)):
                    _fail("UNVERIFIED_POSITION_MARGIN_TOGGLE")
                identity = (pair, record["epps"], record.get("eps"))
                if identity in identities:
                    _fail("DUPLICATE_POSITION_SCOPE")
                identities.add(identity)
                actual += 1
        if actual != count:
            _fail("UNVERIFIED_POSITIONS_COUNT")
        mode, margin = "UNVERIFIED", "UNVERIFIED"
        if "epmd" in value:
            if type(value["epmd"]) is not int:
                _fail("UNVERIFIED_POSITION_MODE")
            mode = _enum(self._futures_enums, "position_mode", "epmd", value["epmd"])
        if "epm" in value:
            if type(value["epm"]) is not int:
                _fail("UNVERIFIED_POSITION_MARGIN_MODE")
            margin = _enum(self._futures_enums, "position_margin", "epm", value["epm"])
        return actual, mode, margin


    def wallet_observation(self):
        """Observe real reported USDT even when provider order/position scope is unknown.

        No successful response here may authorize funds, positions or order writes.
        """
        if self._futures_em is None:
            _fail("FUTURES_DISCOVERY_REQUIRED")
        total, available = self._balance(self.read("balance"))
        results = {}
        for topic in ("orders", "positions", "positions_settings"):
            try:
                result = self.read(topic)
                if topic == "orders":
                    count = self._orders(result)
                    mode, margin = "UNVERIFIED", "UNVERIFIED"
                else:
                    count, mode, margin = self._positions(
                        result, settings=(topic == "positions_settings"))
                results[topic] = (count, "VALIDATED", mode, margin)
            except BitsgapError:
                # A JSON null is NOT an empty inventory, and an error is not a zero.
                results[topic] = (None, "UNVERIFIED", "UNVERIFIED", "UNVERIFIED")
        # If both scopes report a mode, their agreement is mandatory.
        p_mode, s_mode = results["positions"][2], results["positions_settings"][2]
        p_margin, s_margin = results["positions"][3], results["positions_settings"][3]
        if p_mode != "UNVERIFIED" and s_mode != "UNVERIFIED" and p_mode != s_mode:
            _fail("INCONSISTENT_POSITION_MODES")
        if p_margin != "UNVERIFIED" and s_margin != "UNVERIFIED" and p_margin != s_margin:
            _fail("INCONSISTENT_MARGIN_MODES")
        observed = self._clock_ms()
        if type(observed) is not int or observed <= 0:
            _fail("INVALID_OBSERVATION_CLOCK")
        return FuturesWalletObservation(
            received_unix_ms=observed, total_usdt=total, available_usdt=available,
            order_count=results["orders"][0], position_count=results["positions"][0],
            setting_count=results["positions_settings"][0],
            orders_status=results["orders"][1], positions_status=results["positions"][1],
            settings_status=results["positions_settings"][1],
            position_mode=p_mode if p_mode != "UNVERIFIED" else s_mode,
            margin_mode=p_margin if p_margin != "UNVERIFIED" else s_margin)


    def snapshot(self):
        """Read only: sequential snapshots, NOT a coherent venue atomic snapshot."""
        if self._futures_em is None:
            _fail("FUTURES_DISCOVERY_REQUIRED")
        total, available = self._balance(self.read("balance"))
        orders = self._orders(self.read("orders"))
        positions, mode, margin = self._positions(self.read("positions"))
        settings, setting_mode, setting_margin = self._positions(self.read("positions_settings"), settings=True)
        if mode != "UNVERIFIED" and setting_mode != "UNVERIFIED" and mode != setting_mode:
            _fail("INCONSISTENT_POSITION_MODES")
        if margin != "UNVERIFIED" and setting_margin != "UNVERIFIED" and margin != setting_margin:
            _fail("INCONSISTENT_MARGIN_MODES")
        observed = self._clock_ms()
        if type(observed) is not int or observed <= 0:
            _fail("INVALID_OBSERVATION_CLOCK")
        return FuturesAccountObservation(
            market_id=self._futures_em, observed_unix_ms=observed,
            total_usdt=total, available_usdt=available,
            open_orders=orders, open_positions=positions, position_settings=settings,
            position_mode=mode if mode != "UNVERIFIED" else setting_mode,
            margin_mode=margin if margin != "UNVERIFIED" else setting_margin,
            completeness="OBSERVED_NON_ATOMIC_NOT_RECONCILED")


def safe_preflight(*, client):
    """Never leak private funds or remote error body into stdout/logs."""
    try:
        client.discover()
        result = client.snapshot()
        return result.safe_status()
    except BitsgapError as exc:
        categories = {"KUCOIN_FUTURES_ENUM_UNRESOLVED", "UNVERIFIED_FUTURES_ENUM",
                      "UNVERIFIED_MANUAL_CAPABILITIES", "UNVERIFIED_REST_CAPABILITY",
                      "FUTURES_DISCOVERY_REQUIRED", "UNVERIFIED_USDT_FUTURES_BALANCE",
                      "UNVERIFIED_FUTURES_BALANCE_SHAPE", "UNVERIFIED_ORDERS_SHAPE",
                      "UNVERIFIED_POSITIONS_SHAPE", "UNVERIFIED_POSITIONS_SETTINGS_SHAPE",
                      "UNVERIFIED_ORDERS_COUNT", "UNVERIFIED_POSITIONS_COUNT",
                      "INCONSISTENT_POSITION_MODES", "INCONSISTENT_MARGIN_MODES"}
        return {"status": "UNVERIFIED", "reason": exc.category if exc.category in categories else "SCHEMA_OR_AUTH_FAILURE",
                "orders_enabled": False, "capital_reconciled": False}
    except Exception:
        return {"status": "UNVERIFIED", "reason": "RUNTIME_FAILURE",
                "orders_enabled": False, "capital_reconciled": False}
