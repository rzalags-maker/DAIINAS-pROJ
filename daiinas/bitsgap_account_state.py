"""Private normalized Bitsgap account observations; no trading authority.

REST/WS comparison uses local receipt windows, NOT provider-signed time or an
atomic exchange snapshot. No observed wallet amount can fund the PAPER ledger.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, asdict
from decimal import Decimal, localcontext
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import sqlite3
import stat
import sys
import threading
import time

from .bitsgap_readonly import BitsgapError
from .bitsgap_futures_observe import BitsgapFuturesObserver, safe_diagnostic_category
from .bitsgap_futures_stream import BitsgapFuturesStream

TOPICS = ("balance", "orders", "positions", "positions_settings")
SOURCES = ("REST", "WS")
BLOCKED = "NO_TRADE_ACCOUNT_NOT_RECONCILED"


def _fingerprint(topic, value, quality, normalized):
    document = quality
    if quality == "VALIDATED":
        if topic == "balance":
            with localcontext() as context:
                context.prec = 256
                document = {k: format(Decimal(v).normalize(context), "f")
                            for k, v in normalized.items()}
        else:
            # Row order is not account state. Preserve every validated field,
            # but sort groups/records and remove zero-length group placeholders.
            document = dict(value)
            document["data"] = {
                pair: sorted(rows, key=lambda row: json.dumps(row, sort_keys=True))
                for pair, rows in value["data"].items() if rows
            }
    return hashlib.sha256(json.dumps(document, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class AccountStateError(RuntimeError):
    """Fixed local error category only."""


class AccountReadBudget:
    """Shared REST/WS account-topic budget from the pinned public contract.

    Optional to the existing observer, scoped to this worker. Waiting happens in
    REST threads or via to_thread for WS; never blocks the event-loop writer.
    """
    def __init__(self, *, clock=None):
        self.clock = clock or time.monotonic
        self.events = {topic: [] for topic in TOPICS}
        self.lock = threading.Lock()
        self.stopped = threading.Event()

    def acquire(self, topics):
        topics = tuple(topics)
        if not topics or len(set(topics)) != len(topics) or not set(topics) <= set(TOPICS):
            raise AccountStateError("INVALID_BUDGET_TOPIC")
        while not self.stopped.is_set():
            with self.lock:
                now = self.clock()
                delay = 0
                for topic in topics:
                    history = [t for t in self.events[topic] if now - t < 10]
                    self.events[topic] = history
                    one, ten = (1, 5) if topic == "positions_settings" else (5, 20)
                    recent = [t for t in history if now - t < 1]
                    if len(recent) >= one:
                        delay = max(delay, recent[-one] + 1 - now)
                    if len(history) >= ten:
                        delay = max(delay, history[-ten] + 10 - now)
                if delay <= 0:
                    for topic in topics:
                        self.events[topic].append(now)
                    return
            self.stopped.wait(delay + 0.001)
        raise AccountStateError("OBSERVATION_STOPPED")

    def stop(self):
        self.stopped.set()


@dataclass(frozen=True, repr=False)
class Observation:
    topic: str
    source: str
    generation: int
    started_ms: int
    received_ms: int
    quality: str
    fingerprint: str
    values: dict

    def __repr__(self):
        return "Observation(PRIVATE_VALUES_REDACTED)"


class PrivateStore:
    """0600 SQLite normalized checkpoint; opt-in, local, single writer.

    A permanent sidecar file carries flock; locking the SQLite database inode
    itself prevents SQLite acquiring its own locks on macOS. Never unlink the
    sidecar on close, as replacing its inode can permit concurrent writers.
    Read-only status does not acquire the worker's writer lock.
    """
    def __init__(self, path, *, readonly=False):
        if _ci():
            raise AccountStateError("PRIVATE_STORE_DISALLOWED_IN_CI")
        self.path = Path(path)
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self.readonly = readonly
        self.fd = None
        self.db = None
        if self.path.is_symlink() or self.lock_path.is_symlink():
            raise AccountStateError("UNSAFE_PRIVATE_STORE")
        if not readonly:
            self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            try:
                self.fd = os.open(self.lock_path,
                                  os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
                self._check(os.fstat(self.fd))
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                db_fd = os.open(self.path,
                                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
                try:
                    self._check(os.fstat(db_fd))
                finally:
                    os.close(db_fd)
            except Exception:
                if self.fd is not None:
                    os.close(self.fd)
                    self.fd = None
                raise AccountStateError("PRIVATE_STORE_LOCKED_OR_UNSAFE") from None
        else:
            self._check(self.path.stat(follow_symlinks=False))
        uri = self.path.resolve().as_uri() + ("?mode=ro" if readonly else "?mode=rw")
        try:
            self.db = sqlite3.connect(uri, uri=True)
            if not readonly:
                self.db.execute("PRAGMA journal_mode=DELETE")
                self.db.execute("CREATE TABLE IF NOT EXISTS account_state(id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)")
                self.db.commit()
        except Exception:
            self.close()
            raise AccountStateError("PRIVATE_STORE_UNAVAILABLE") from None

    @staticmethod
    def _check(info):
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_nlink != 1):
            raise AccountStateError("UNSAFE_PRIVATE_STORE")

    def load(self):
        row = self.db.execute("SELECT payload FROM account_state WHERE id=1").fetchone()
        return json.loads(row[0]) if row else None

    def writer_active(self):
        # A legacy checkpoint without a sidecar is never considered live.
        try:
            fd = os.open(self.lock_path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return False
        except OSError:
            raise AccountStateError("UNSAFE_PRIVATE_STORE") from None
        try:
            self._check(os.fstat(fd))
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            return False
        finally:
            os.close(fd)

    def save(self, payload):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO account_state VALUES(1,?)",
                            (json.dumps(payload, sort_keys=True, allow_nan=False),))

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def _ci():
    return any(os.environ.get(name, "").lower() == "true" for name in ("GITHUB_ACTIONS", "CI"))


class AccountState:
    def __init__(self, observer, *, scope_ref, max_age_ms=15000,
                 comparison_ms=5000, clock_ms=None, store=None, status_reader=False):
        if not isinstance(scope_ref, str) or not scope_ref.strip() or len(scope_ref) > 128:
            raise AccountStateError("SCOPE_REFERENCE_REQUIRED")
        if (type(max_age_ms) is not int or type(comparison_ms) is not int
                or not 0 < comparison_ms <= max_age_ms):
            raise AccountStateError("INVALID_OBSERVATION_WINDOW")
        if type(observer._futures_em) is not int or observer._futures_em <= 0:
            raise AccountStateError("FUTURES_DISCOVERY_REQUIRED")
        self.observer = observer
        self.scope_ref = scope_ref  # Operator namespace, not a verified account ID.
        self.market_id = observer._futures_em
        self.max_age_ms = max_age_ms
        self.comparison_ms = comparison_ms
        self.clock = clock_ms or (lambda: int(time.time() * 1000))
        self.store = store
        self.records = {}
        self.holds = set()
        self.generation = 0
        self.connected = False
        self.resynced = False
        self.post_subscribe_ms = None
        self.duplicates = 0
        self.state_version = 0
        if store is not None:
            saved = store.load()
            if saved is not None:
                self._restore(saved)
                # Recovery never reuses an old authenticated connection.
                if status_reader and store.readonly and store.writer_active():
                    self.connected = saved.get("connected") is True
                    self.resynced = saved.get("resynced") is True
                    self.post_subscribe_ms = saved.get("post_subscribe_ms")
                    self.holds = set(saved.get("holds", [])) & set(TOPICS)
                else:
                    self.generation += 1

    def __repr__(self):
        return "AccountState(OBSERVE, PRIVATE_VALUES_REDACTED)"

    def _restore(self, saved):
        if (not isinstance(saved, dict) or saved.get("version") != 1
                or saved.get("market_id") != self.market_id
                or saved.get("scope_ref") != self.scope_ref
                or saved.get("currency") != "USDT"
                or type(saved.get("generation")) is not int
                or type(saved.get("state_version", 0)) is not int
                or saved.get("state_version", 0) < 0):
            raise AccountStateError("CHECKPOINT_SCOPE_MISMATCH")
        try:
            for raw in saved["records"]:
                record = Observation(**raw)
                if (record.topic not in TOPICS or record.source not in SOURCES
                        or type(record.started_ms) is not int
                        or type(record.received_ms) is not int
                        or not 0 <= record.started_ms <= record.received_ms
                        or type(record.generation) is not int
                        or not isinstance(record.fingerprint, str)
                        or re.fullmatch("[0-9a-f]{64}", record.fingerprint) is None
                        or record.generation < 0 or not isinstance(record.values, dict)
                        or record.quality not in ("VALIDATED", "PROVIDER_NO_DATA", "UNVERIFIED")):
                    raise ValueError()
                if record.quality == "VALIDATED":
                    if record.topic == "balance":
                        if set(record.values) != {"total_reported", "available_reported"}:
                            raise ValueError()
                        self.observer_balance_check(record.values)
                    else:
                        if type(record.values.get("count")) is not int or record.values["count"] < 0:
                            raise ValueError()
                        expected = {"count"} if record.topic == "orders" else {"count", "position_mode", "margin_mode"}
                        if set(record.values) != expected:
                            raise ValueError()
                        if record.topic != "orders" and (
                            record.values["position_mode"] not in ("ONE_WAY", "HEDGE", "UNVERIFIED")
                            or record.values["margin_mode"] not in ("CROSS", "ISOLATED", "UNVERIFIED")):
                            raise ValueError()
                elif record.values:
                    raise ValueError()
                self.records[(record.topic, record.source)] = record
            windows = (saved.get("max_age_ms", 15000), saved.get("comparison_ms", 5000))
            if (any(type(v) is not int for v in windows)
                    or not 0 < windows[1] <= windows[0]):
                raise ValueError()
            self.max_age_ms, self.comparison_ms = windows
            self.generation = saved["generation"]
            self.state_version = saved.get("state_version", 0)
        except (KeyError, TypeError, ValueError, BitsgapError):
            raise AccountStateError("INVALID_CHECKPOINT") from None

    @staticmethod
    def observer_balance_check(values):
        from .bitsgap_readonly import BitsgapReadOnly
        total = BitsgapReadOnly._decimal(values["total_reported"])
        available = BitsgapReadOnly._decimal(values["available_reported"])
        if available > total:
            raise ValueError()

    def _save(self):
        self.state_version += 1
        if self.store is not None:
            self.store.save({"version": 1, "market_id": self.market_id,
                "scope_ref": self.scope_ref, "currency": "USDT",
                "max_age_ms": self.max_age_ms, "comparison_ms": self.comparison_ms,
                "generation": self.generation,
                "state_version": self.state_version,
                "connected": self.connected, "resynced": self.resynced,
                "post_subscribe_ms": self.post_subscribe_ms, "holds": sorted(self.holds),
                "records": [asdict(r) for r in self.records.values()]})

    def connection(self, state):
        if state == "CONNECTING":
            self.generation += 1
            self.connected = self.resynced = False
            self.post_subscribe_ms = None
            self.holds.clear()
        elif state == "SUBSCRIBED":
            self.connected = True
            self.post_subscribe_ms = self.clock()
        elif state == "REST_RESYNC_COMPLETE":
            self.resynced = True
        elif state == "DISCONNECTED":
            self.connected = self.resynced = False
        else:
            raise AccountStateError("INVALID_CONNECTION_EVENT")
        self._save()

    def ingest(self, *, topic, value, source, market_id, started_ms, received_ms,
               quality="VALIDATED", currency="USDT"):
        if topic not in TOPICS:
            # Optional history/pair reads are not financial authority here.
            raise AccountStateError("UNSUPPORTED_ACCOUNT_TOPIC")
        if (type(market_id) is not int or market_id != self.market_id
                or currency != "USDT" or source not in SOURCES):
            self.holds.add(topic)
            self._save()
            raise AccountStateError("ACCOUNT_SCOPE_MISMATCH")
        if (type(started_ms) is not int or type(received_ms) is not int
                or not 0 <= started_ms <= received_ms <= self.clock()):
            self.holds.add(topic)
            self._save()
            raise AccountStateError("INVALID_OBSERVATION_TIME")
        key = (topic, source)
        previous = self.records.get(key)
        if (previous is not None and previous.generation == self.generation
                and received_ms < previous.received_ms):
            self.holds.add(topic)
            self._save()
            return "OUT_OF_ORDER"
        normalized = {}
        if quality not in ("VALIDATED", "PROVIDER_NO_DATA", "UNVERIFIED"):
            raise AccountStateError("INVALID_OBSERVATION_QUALITY")
        if value is None:
            quality = "UNVERIFIED" if quality == "UNVERIFIED" else "PROVIDER_NO_DATA"
        elif quality == "VALIDATED":
            try:
                if topic == "balance":
                    total, available = self.observer._balance(value)
                    normalized = {"total_reported": total, "available_reported": available}
                elif topic == "orders":
                    normalized = {"count": self.observer._orders(value)}
                else:
                    count, mode, margin = self.observer._positions(
                        value, settings=topic == "positions_settings")
                    # Live Bitsgap conf_enums labels the one-way Futures mode
                    # ONEWAY; Model A/AccountState use the canonical ONE_WAY.
                    # Unknown labels must remain rejected rather than guessed.
                    if mode == "ONEWAY":
                        mode = "ONE_WAY"
                    if mode not in ("ONE_WAY", "HEDGE", "UNVERIFIED") or margin not in ("CROSS", "ISOLATED", "UNVERIFIED"):
                        raise ValueError()
                    normalized = {"count": count, "position_mode": mode, "margin_mode": margin}
            except (BitsgapError, ValueError, TypeError, KeyError):
                quality = "UNVERIFIED"
        # Dedup digest is private, never output; no raw frames are persisted.
        fingerprint = _fingerprint(topic, value, quality, normalized)
        if (previous is not None and previous.generation == self.generation
                and fingerprint == previous.fingerprint and quality == previous.quality):
            self.duplicates += 1
            if source == "WS":
                # Repeated cached frames cannot keep stale evidence alive.
                return "DUPLICATE"
        elif (previous is not None and previous.generation == self.generation
              and received_ms == previous.received_ms and previous.quality == "VALIDATED"):
            self.holds.add(topic)
        self.records[key] = Observation(topic, source, self.generation, started_ms,
                                       received_ms, quality, fingerprint, normalized)
        self._save()
        return quality

    def _current(self, record, now):
        return (record is not None and record.generation == self.generation
                and 0 <= now - record.received_ms <= self.max_age_ms
                and record.received_ms - record.started_ms <= self.comparison_ms)

    def _topic(self, topic, now):
        rest, ws = (self.records.get((topic, s)) for s in SOURCES)
        records = [r for r in (rest, ws) if self._current(r, now)]
        result = {"state": "UNVERIFIED", "reason": "MISSING_CROSS_TRANSPORT_EVIDENCE",
                  "count": None, "values": {}, "last_update_ms": None,
                  "timestamp_source": "LOCAL_RECEIPT_CLOCK_NOT_PROVIDER"}
        if not records:
            if rest is not None or ws is not None:
                result.update(state="STALE", reason="EXPIRED_OR_PREVIOUS_SESSION")
            return result
        result["last_update_ms"] = max(r.received_ms for r in records)
        if topic in self.holds:
            result["state"] = "CONFLICT"
            result["reason"] = "CONTRADICTORY_OR_OUT_OF_ORDER_EVIDENCE"
            return result
        valid = [r for r in records if r.quality == "VALIDATED"]
        if topic == "balance" and valid:
            # A wallet read can be displayed while exposure stays unknown.
            result["values"] = max(valid, key=lambda r: r.received_ms).values
        if not valid:
            if all(r.quality == "PROVIDER_NO_DATA" for r in records):
                result.update(state="PROVIDER_NO_DATA", reason="NULL_IS_NOT_ZERO")
            else:
                result["reason"] = "SCHEMA_OR_PERMISSION_UNVERIFIED"
            return result
        if (len(valid) != 2 or not self.connected or not self.resynced
                or self.post_subscribe_ms is None
                or rest.started_ms < self.post_subscribe_ms):
            return result
        if max(r.received_ms for r in valid) - min(r.started_ms for r in valid) > self.comparison_ms:
            result["reason"] = "OBSERVATION_WINDOW_MISMATCH"
            return result
        if rest.fingerprint != ws.fingerprint:
            result.update(state="CONFLICT", reason="REST_WS_CONFLICT", values={})
            return result
        result.update(state="VALIDATED", reason="CROSS_TRANSPORT_NON_ATOMIC",
                      values=rest.values)
        if topic in ("orders", "positions"):
            count = rest.values["count"]
            result.update(state="VERIFIED_EMPTY" if count == 0 else "VERIFIED_ACTIVE", count=count)
        return result

    def status(self, *, private=False):
        now = self.clock()
        topics = {t: self._topic(t, now) for t in TOPICS}
        positions = topics["positions"]["values"]
        settings = topics["positions_settings"]["values"]
        if any(positions.get(field, "UNVERIFIED") != "UNVERIFIED"
               and settings.get(field, "UNVERIFIED") != "UNVERIFIED"
               and positions[field] != settings[field]
               for field in ("position_mode", "margin_mode")):
            for topic in ("positions", "positions_settings"):
                topics[topic].update(state="CONFLICT", reason="POSITION_SETTINGS_CONFLICT",
                                     count=None, values={})
        balance = topics["balance"]
        any_fresh = any(self._current(r, now) for r in self.records.values())
        connection = ("CONNECTED" if self.connected and any_fresh else
                      "STALE" if self.connected else "DISCONNECTED")
        result = {"exchange": "KUCOIN_FUTURES", "currency": "USDT", "mode": "OBSERVE",
            "connection": connection, "topics": {
                t: {k: v for k, v in data.items() if k not in ("values", "count")}
                for t, data in topics.items()},
            "last_update_ms": max((r.received_ms for r in self.records.values()), default=None),
            "timestamp_source": "LOCAL_RECEIPT_CLOCK_NOT_PROVIDER",
            "state_version": self.state_version,
            "snapshot_atomicity": "NOT_ATOMIC",
            "exposure_proof_scope": "BITSGAP_API_MARKET_VIEW_NOT_EXCHANGE_COMPLETENESS",
            "provider_timestamp": "UNVERIFIED",
            "account_identity": "KEY_BOUND_MARKET_SCOPE_NOT_ACCOUNT_ID_VERIFIED",
            "stream_reconciled_after_subscribe": self.resynced,
            "futures_position_mode_owner_requirement": "ONE_WAY",
            "observed_position_mode": (settings.get("position_mode", "UNVERIFIED")
                if settings.get("position_mode", "UNVERIFIED") != "UNVERIFIED"
                else positions.get("position_mode", "UNVERIFIED")),
            "equity": "UNVERIFIED", "free_margin": "UNVERIFIED",
            "margin_committed": "UNVERIFIED", "unrealized_pnl": "UNVERIFIED",
            "fees_funding": "UNVERIFIED", "model_a_reserve": "NOT RECONCILED",
            "position_protection": "UNVERIFIED", "collateral_eligibility": "UNVERIFIED",
            "model_a_active": "NOT RECONCILED", "eligible_slots": "BLOCKED",
            "new_entry": BLOCKED, "orders_enabled": False, "live_trading": "DISABLED"}
        result["field_provenance"] = {
            field: {"topic": topic, "state": topics[topic]["state"],
                    "timestamp_source": "LOCAL_RECEIPT_CLOCK_NOT_PROVIDER",
                    "last_update_ms": topics[topic]["last_update_ms"],
                    "sources": [source for source in SOURCES
                        if self._current(self.records.get((topic, source)), now)
                        and self.records[(topic, source)].quality == "VALIDATED"]}
            for field, topic in (("total_reported", "balance"), ("available_reported", "balance"),
                ("open_positions", "positions"), ("pending_orders", "orders"),
                ("observed_position_mode", "positions_settings"))
        }
        if settings.get("position_mode", "UNVERIFIED") == "UNVERIFIED" and positions.get("position_mode", "UNVERIFIED") != "UNVERIFIED":
            result["field_provenance"]["observed_position_mode"] = dict(
                result["field_provenance"]["open_positions"])
        for field in ("equity", "free_margin", "margin_committed", "unrealized_pnl",
                      "fees_funding", "position_protection", "collateral_eligibility"):
            result["field_provenance"][field] = {"state": "UNVERIFIED", "sources": [],
                "last_update_ms": None, "timestamp_source": "NOT_AVAILABLE",
                "reason": "AUTHORITATIVE_FINANCIAL_OR_PROTECTION_EVIDENCE_MISSING"}
        if private:
            cached = sorted((r for r in self.records.values() if r.topic == "balance"
                             and r.quality == "VALIDATED"), key=lambda r: r.received_ms)
            values = balance["values"] or (cached[-1].values if cached else {})
            result.update(total_reported=values.get("total_reported", "UNVERIFIED"),
                available_reported=values.get("available_reported", "UNVERIFIED"),
                wallet_amounts_status=("CURRENT_LOCAL_RECEIPT" if balance["state"] == "VALIDATED"
                    and self.connected else "RECENT_SINGLE_SOURCE_NOT_RECONCILED" if balance["values"]
                    else "LAST_OBSERVED_NOT_CURRENT"),
                wallet_observed_ms=cached[-1].received_ms if cached else None,
                open_positions=topics["positions"]["count"] if topics["positions"]["state"].startswith("VERIFIED_") else "UNVERIFIED",
                pending_orders=topics["orders"]["count"] if topics["orders"]["state"].startswith("VERIFIED_") else "UNVERIFIED")
        return result

    def model_a_input(self):
        """Existing ledger boundary: no verified collateral/protection -> no funds.

        This consumes the observation state but never invokes CapitalLadder,
        creates funding, clears a HALT, or overwrites the existing MOCK ledger.
        """
        return {"decision": BLOCKED, "eligible_capital": None, "reserve": None,
                "active": None, "funded_slots": None,
                "account_observation": self.status(), "funding_authorized": False}

    def capital_admission_preview(self, *, existing_ladder=None, initial_scenario=False):
        from .bitsgap_capital_preview import capital_admission_preview
        return capital_admission_preview(self, existing_ladder=existing_ladder,
                                         initial_scenario=initial_scenario)


async def observe_bounded(observer, connect, *, seconds, scope_ref, store=None, clock_ms=None):
    if type(seconds) is not int or not 1 <= seconds <= 3600:
        raise AccountStateError("INVALID_OBSERVER_DURATION")
    service = AccountState(observer, scope_ref=scope_ref, store=store, clock_ms=clock_ms)
    prior_sink = observer.observation_sink
    prior_budget = observer.request_budget
    budget = AccountReadBudget()
    observer.request_budget = budget
    loop = asyncio.get_running_loop()
    accepting = threading.Event()
    accepting.set()
    async def commit(kwargs):
        if not accepting.is_set():
            return "UNVERIFIED"
        return service.ingest(**kwargs)
    def ingest(**kwargs):
        # Existing REST reads run in to_thread; marshal all private checkpoint
        # mutations to the same event loop/SQLite writer as WS observations.
        if not accepting.is_set():
            return "UNVERIFIED"
        try:
            in_loop = asyncio.get_running_loop() is loop
        except RuntimeError:
            in_loop = False
        if in_loop:
            return service.ingest(**kwargs)
        return asyncio.run_coroutine_threadsafe(commit(kwargs), loop).result(timeout=5)
    observer.observation_sink = ingest
    stream = BitsgapFuturesStream(observer, observation_sink=ingest,
                                 connection_sink=service.connection)
    async def event(event):
        if event.get("event") == "DISCONNECTED":
            service.connection("DISCONNECTED")
    async def refresh():
        while True:
            await asyncio.sleep(5)
            if service.connected and service.resynced:
                try:
                    await asyncio.to_thread(observer.wallet_observation)
                except Exception:
                    service.connection("DISCONNECTED")
    refresh_task = asyncio.create_task(refresh())
    try:
        await asyncio.wait_for(stream.observe_forever(connect, on_event=event,
                               stop_event=asyncio.Event()), timeout=seconds)
    except asyncio.TimeoutError:
        pass
    finally:
        accepting.clear()
        budget.stop()
        refresh_task.cancel()
        await asyncio.gather(refresh_task, return_exceptions=True)
        service.connection("DISCONNECTED")
        observer.observation_sink = prior_sink
        observer.request_budget = prior_budget
    return service


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--observe", action="store_true")
    parser.add_argument("--private-panel", action="store_true")
    parser.add_argument("--capital-preview", action="store_true")
    parser.add_argument("--hypothetical-initial", action="store_true",
                        help="Explicit hypothetical Model A initial allocation; never funding")
    parser.add_argument("--state-file", type=Path)
    parser.add_argument("--scope-ref", required=True, help="Non-secret operator namespace, not account ID")
    parser.add_argument("--seconds", type=int, default=8)
    args = parser.parse_args(argv)
    if args.private_panel and (_ci() or not sys.stdout.isatty() or args.observe):
        print(json.dumps({"status": "PRIVATE_OUTPUT_DISALLOWED", "orders_enabled": False}))
        return 2
    if args.state_file is not None and _ci():
        print(json.dumps({"status": "PRIVATE_STORE_DISALLOWED_IN_CI", "orders_enabled": False}))
        return 2
    if args.hypothetical_initial and not args.capital_preview:
        print(json.dumps({"status": "EXPLICIT_CAPITAL_PREVIEW_REQUIRED", "orders_enabled": False}))
        return 2
    store = None
    try:
        if args.status:
            if args.observe or args.state_file is None:
                raise AccountStateError("STATUS_REQUIRES_PRIVATE_CHECKPOINT")
            store = PrivateStore(args.state_file, readonly=True)
            saved = store.load()
            if not isinstance(saved, dict):
                raise AccountStateError("NO_CHECKPOINT")
            # Status never loads an API key. Recovered state remains stale until
            # a running observer obtains a fresh authenticated reconciliation.
            observer = type("CheckpointScope", (), {"_futures_em": saved.get("market_id")})()
            service = AccountState(observer, scope_ref=args.scope_ref, store=store,
                                   status_reader=True)
        else:
            if not args.observe:
                raise AccountStateError("EXPLICIT_OBSERVE_REQUIRED")
            if not os.environ.get("BITSGAP_PRIVATE_KEY_PEM"):
                print(json.dumps({"status": "CREDENTIAL_NOT_CONFIGURED",
                                  "new_entry": BLOCKED, "orders_enabled": False}))
                return 2
            from websockets.asyncio.client import connect
            observer = BitsgapFuturesObserver(os.environ.get("BITSGAP_PRIVATE_KEY_PEM"))
            observer.discover()
            if args.state_file is not None:
                store = PrivateStore(args.state_file)
            def secure_connect(url):
                return connect(url, open_timeout=5, close_timeout=2, max_size=65536,
                               max_queue=16, ping_interval=20)
            service = asyncio.run(observe_bounded(observer, secure_connect,
                seconds=args.seconds, scope_ref=args.scope_ref, store=store))
        result = service.status(private=args.private_panel)
        if args.capital_preview:
            preview = service.capital_admission_preview(initial_scenario=args.hypothetical_initial)
            result["capital_admission_preview"] = (
                preview.private_status() if args.private_panel else preview.safe_status())
        print(json.dumps(result, sort_keys=True))
        return 2  # Account observation never clears the financial gate.
    except Exception as exc:
        category = safe_diagnostic_category(exc.category) if isinstance(exc, BitsgapError) else "LOCAL_ACCOUNT_STATE_UNVERIFIED"
        print(json.dumps({"status": "UNVERIFIED", "reason": category,
                          "new_entry": BLOCKED, "orders_enabled": False}))
        return 2
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
