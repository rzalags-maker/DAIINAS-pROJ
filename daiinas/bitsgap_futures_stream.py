"""Bitsgap Futures observation-only WS stream with fail-closed reconnect.

No order, cancel, close, leverage or transfer packets can be sent from this class.
Never use stream changes alone to fund an actual Model A campaign.
"""
from __future__ import annotations

import asyncio
import base64
import json
import secrets
import time

from .bitsgap_readonly import BitsgapError, _unique_object, _reject_constant
from .bitsgap_futures_observe import BitsgapFuturesObserver, _fail

_SUBS = ("balance", "orders", "positions", "positions_settings")
# Snapshot responses refresh evidence; unchanged subscription frames do not.
# A response must arrive within this window of an explicit one-off request.
_SNAPSHOT_RESPONSE_WINDOW_SECONDS = 5.0
_SNAPSHOT_INTERVAL_SECONDS = 8.0


def _parse_json(raw):
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if not isinstance(raw, str) or len(raw) > 1_000_000:
        _fail("WS_BAD_FRAME")
    try:
        return json.loads(raw, object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant)
    except (TypeError, ValueError, UnicodeError):
        _fail("WS_BAD_FRAME")


def _safe_envelope_shape(value):
    """Only bounded, fixed vocabulary; never logs remote values or private keys."""
    if isinstance(value, list):
        return {"kind": "ARRAY", "size_band": "EMPTY" if not value else "NONEMPTY"}
    if not isinstance(value, dict):
        return {"kind": "OTHER"}
    allowed = ("type", "ok", "topic", "params", "value", "mes", "subs",
               "sid", "error", "code", "status")
    return {
        "kind": "OBJECT",
        "known_fields": [key for key in allowed if key in value],
        "other_field_count": sum(1 for key in value if key not in allowed),
        "topic_class": ("ACCOUNT" if value.get("topic") in _SUBS else
                        "OTHER" if isinstance(value.get("topic"), str) else "NONE"),
        "ok_class": ("TRUE" if value.get("ok") is True else
                     "FALSE" if value.get("ok") is False else "MISSING_OR_OTHER"),
        "params_class": ("OBJECT" if isinstance(value.get("params"), dict) else
                         "MISSING_OR_OTHER"),
        "message_class": ("ABSENT" if "mes" not in value else
                          "NULL" if value["mes"] is None else
                          "STRING" if isinstance(value["mes"], str) else
                          "OBJECT" if isinstance(value["mes"], dict) else
                          "ARRAY" if isinstance(value["mes"], list) else "OTHER"),
        "value_class": ("NULL" if "value" in value and value["value"] is None else
                        "OBJECT" if isinstance(value.get("value"), dict) else
                        "ARRAY" if isinstance(value.get("value"), list) else
                        "OTHER" if "value" in value else "ABSENT"),
    }


class BitsgapFuturesStream:
    def __init__(self, observer: BitsgapFuturesObserver, *, observation_sink=None, connection_sink=None):
        self.observer = observer
        self.connected = False
        self.authenticated = False
        self.last_rest_observation = None
        self.updates = 0
        self.disconnects = 0
        self.last_failure = None
        self.last_frame_shape = None
        self.unscoped_control_responses = 0
        self.snapshot_batches = 0
        self.snapshot_responses = 0
        self.snapshot_rejections = 0
        self.subscription_updates = 0
        self._snapshot_pending = {}
        self.observation_sink = observation_sink
        self.connection_sink = connection_sink

    def _observe_value(self, topic, value, quality="VALIDATED", *, snapshot_response=False,
                       received_ms=None):
        if self.observation_sink is not None:
            now = self.observer._clock_ms() if received_ms is None else received_ms
            self.observation_sink(topic=topic, value=value, source="WS",
                market_id=self.observer._futures_em, started_ms=now,
                received_ms=now, quality=quality, snapshot_response=snapshot_response)

    def diagnostic_status(self):
        """Fixed-vocabulary transport counters only: no keys, frames, balances or IDs."""
        return {"ws_auth_succeeded_in_last_session": self.authenticated,
                "ws_snapshot_batches_sent": self.snapshot_batches,
                "ws_snapshot_responses": self.snapshot_responses,
                "ws_snapshot_rejections": self.snapshot_rejections,
                "ws_subscription_updates": self.subscription_updates,
                "ws_disconnects": self.disconnects,
                "ws_last_failure": self.last_failure or "NONE"}

    async def _request_snapshots(self, ws):
        """Explicit WS read snapshots; share REST/WS topic budgets and account scope."""
        if self.observer.request_budget is not None:
            await asyncio.to_thread(self.observer.request_budget.acquire, _SUBS)
        requests = [{"topic": topic, "params": {"em": self.observer._futures_em}}
                    for topic in _SUBS]
        await ws.send(json.dumps(requests, separators=(",", ":")))
        sent_at = time.monotonic()
        self._snapshot_pending = {topic: sent_at for topic in _SUBS}
        self.snapshot_batches += 1

    def _snapshot_response(self, topic, received_monotonic=None):
        received_at = time.monotonic() if received_monotonic is None else received_monotonic
        sent_at = self._snapshot_pending.get(topic)
        # A receive task may finish before a timer/budget wait sends a new read.
        # Processing later must neither consume that request nor renew old data.
        if sent_at is None or received_at < sent_at:
            return False
        self._snapshot_pending.pop(topic, None)
        if received_at - sent_at > _SNAPSHOT_RESPONSE_WINDOW_SECONDS:
            return False
        self.snapshot_responses += 1
        return True

    def _connection(self, state):
        if self.connection_sink is not None:
            self.connection_sink(state)

    def auth_frame(self, *, ts=None, nonce=None):
        timestamp = int(time.time()) if ts is None else ts
        token = secrets.token_hex(16) if nonce is None else nonce
        if (type(timestamp) is not int or not isinstance(token, str) or not token.isalnum()
                or len(token) > 80):
            _fail("WS_INVALID_AUTH_FRAME")
        public = self.observer._public
        canonical = f"btg-ws-auth\nv1\n{public}\n{timestamp}\n{token}".encode("utf-8")
        signed = base64.b64encode(self.observer._key.sign(canonical)).decode("ascii")
        return {"type":"auth", "pubkey": public, "ts":timestamp,
                "nonce":token, "signature":signed}

    def _ingest(self, message, *, received_monotonic=None, received_ms=None):
        if not isinstance(message, dict) or message.get("topic") not in _SUBS:
            _fail("WS_UNVERIFIED_TOPIC_FRAME")
        params = message.get("params")
        if (not isinstance(params, dict) or set(params) != {"em"}
                or type(params["em"]) is not int or params["em"] != self.observer._futures_em):
            _fail("WS_FOREIGN_EXCHANGE_SCOPE")
        topic = message["topic"]
        if message.get("ok") is False:
            # No payload is evidence of neither emptiness nor a current snapshot.
            if topic in self._snapshot_pending:
                self._snapshot_pending.pop(topic, None)
                self.snapshot_rejections += 1
            self._observe_value(topic, None, "UNVERIFIED", received_ms=received_ms)
            return {"topic": topic, "event": "SUBSCRIPTION_REJECTED",
                    "funding_authorized": False}
        if message.get("ok") is not True:
            _fail("WS_UNVERIFIED_TOPIC_FRAME")
        if "value" not in message:
            if message.get("mes") == "subscribed" and set(message) <= {"ok", "topic", "params", "mes"}:
                return {"topic": topic, "event": "SUBSCRIBED", "funding_authorized": False}
            _fail("WS_UNVERIFIED_TOPIC_FRAME")
        if set(message) - {"ok", "topic", "params", "value", "mes"}:
            _fail("WS_UNVERIFIED_TOPIC_FRAME")
        if ("mes" in message and message["mes"] is not None
                and not isinstance(message["mes"], str)):
            _fail("WS_UNVERIFIED_TOPIC_FRAME")
        if message["value"] is None:
            snapshot = self._snapshot_response(topic, received_monotonic)
            self._observe_value(topic, None, "PROVIDER_NO_DATA", snapshot_response=snapshot,
                                received_ms=received_ms)
            return {"topic": topic, "event": "PROVIDER_NO_DATA",
                    "funding_authorized": False}
        value = message["value"]
        if topic == "balance":
            self.observer._balance(value)
            count = 1
        elif topic == "orders":
            count = self.observer._orders(value)
        else:
            count, _, _ = self.observer._positions(value, settings=(topic == "positions_settings"))
        self.updates += 1
        snapshot = self._snapshot_response(topic, received_monotonic)
        if not snapshot:
            self.subscription_updates += 1
        self._observe_value(topic, value, snapshot_response=snapshot, received_ms=received_ms)
        # Raw private data never moves from the validation boundary to events/logs.
        return {"topic": topic, "event": "VALIDATED_UPDATE", "record_count": count,
                "funding_authorized": False}

    async def watch_once(self, connect, *, on_event, max_messages=None):
        """Connect/subscribe read-only, yield sanitized observations; no blind retry."""
        if self.observer._futures_em is None:
            _fail("FUTURES_DISCOVERY_REQUIRED")
        self.connected = False
        self.authenticated = False
        self._snapshot_pending.clear()
        self._connection("CONNECTING")
        # Snapshot-before-subscribe is NOT atomic with WS. It cannot release a
        # funded slot, and reconciliation must re-snapshot on every reconnect.
        # REST orders/positions may literally be null. This must not prevent the
        # independent WS investigation of those same topics.
        self.last_rest_observation = await asyncio.to_thread(self.observer.wallet_observation)
        try:
            async with connect("wss://stream.bitsgap.com/") as ws:
                await ws.send(json.dumps(self.auth_frame(), separators=(",", ":")))
                auth = _parse_json(await asyncio.wait_for(ws.recv(), 5))
                if (not isinstance(auth, dict) or auth.get("type") != "auth_ok"
                        or not isinstance(auth.get("sid"), (str, int)) or type(auth.get("sid")) is bool):
                    _fail("WS_AUTH_UNVERIFIED")
                self.authenticated = True
                subscribe = [{"topic": topic, "params": {"em": self.observer._futures_em}, "subs": True}
                             for topic in _SUBS]
                if self.observer.request_budget is not None:
                    await asyncio.to_thread(self.observer.request_budget.acquire, _SUBS)
                await ws.send(json.dumps(subscribe, separators=(",", ":")))
                self.connected = True
                self._connection("SUBSCRIBED")
                if self.observation_sink is not None:
                    # Additional REST window after subscribe, not an atomic
                    # snapshot. Buffered WS values still require comparison.
                    await asyncio.to_thread(self.observer.wallet_observation)
                    self._connection("REST_RESYNC_COMPLETE")
                # Request a one-time account snapshot separately from subscription.
                # The protocol has no request ID. A response can be treated as
                # explicit only if it follows the matching scoped read promptly.
                await self._request_snapshots(ws)
                processed = 0
                next_snapshot = asyncio.create_task(asyncio.sleep(_SNAPSHOT_INTERVAL_SECONDS))
                async def receive_frame():
                    raw = await ws.recv()
                    return raw, time.monotonic(), self.observer._clock_ms()
                incoming = asyncio.create_task(receive_frame())
                try:
                    while max_messages is None or processed < max_messages:
                        done, _ = await asyncio.wait(
                            (incoming, next_snapshot), return_when=asyncio.FIRST_COMPLETED)
                        if next_snapshot in done:
                            await self._request_snapshots(ws)
                            next_snapshot = asyncio.create_task(
                                asyncio.sleep(_SNAPSHOT_INTERVAL_SECONDS))
                        if incoming not in done:
                            continue
                        raw, received_monotonic, received_ms = incoming.result()
                        frame = _parse_json(raw)
                        incoming = asyncio.create_task(receive_frame())
                        messages = frame if isinstance(frame, list) else [frame]
                        for msg in messages:
                            try:
                                # Bitsgap may acknowledge a batch with {ok, mes}
                                # and no topic. Never count it as account data.
                                if (isinstance(msg, dict) and set(msg) == {"ok", "mes"}
                                        and type(msg["ok"]) is bool
                                        and isinstance(msg["mes"], str)):
                                    if not msg["ok"]:
                                        _fail("WS_UNSCOPED_REJECTION")
                                    self.unscoped_control_responses += 1
                                    event = {"topic": "account",
                                             "event": "UNSCOPED_OK_RESPONSE",
                                             "funding_authorized": False}
                                else:
                                    event = self._ingest(msg, received_monotonic=received_monotonic,
                                                         received_ms=received_ms)
                            except BitsgapError:
                                self.last_frame_shape = _safe_envelope_shape(msg)
                                raise
                            await on_event(event)
                            processed += 1
                            if max_messages is not None and processed >= max_messages:
                                break
                finally:
                    next_snapshot.cancel()
                    incoming.cancel()
                    await asyncio.gather(next_snapshot, incoming, return_exceptions=True)
        except BitsgapError as exc:
            self.last_failure = exc.category
            raise
        except Exception as exc:
            # Revoked/auth-failed/replayed credentials are terminal: never loop.
            close_code = getattr(getattr(exc, "rcvd", None), "code", None)
            if close_code is None:
                close_code = getattr(exc, "code", None)
            self.last_failure = ("WS_TERMINAL_AUTH_FAILURE" if close_code in (4401, 4403, 4409)
                                 else "WS_DISCONNECTED_OR_TRANSPORT_ERROR")
            raise BitsgapError(self.last_failure) from None
        finally:
            self.connected = False
            self.disconnects += 1
            self._snapshot_pending.clear()
            self._connection("DISCONNECTED")

    async def observe_forever(self, connect, *, on_event, stop_event, delay_seconds=1):
        """Reconnect with a fresh REST read + signed WS session each time.

        Caller owns life cycle and must stop this coroutine explicitly. Unknown
        observations fail closed to wallet/capital authority at all times.
        """
        delay = max(1, delay_seconds)
        while not stop_event.is_set():
            try:
                await self.watch_once(connect, on_event=on_event)
                delay = max(1, delay_seconds)
            except BitsgapError as exc:
                await on_event({"event": "DISCONNECTED", "topic": "account",
                                "category": exc.category, "funding_authorized": False})
                if exc.category == "WS_TERMINAL_AUTH_FAILURE":
                    return
            if not stop_event.is_set():
                try:
                    await asyncio.wait_for(stop_event.wait(), delay)
                except asyncio.TimeoutError:
                    pass
                delay = min(delay * 2, 30)


def read_only_ws_topics():
    return _SUBS
