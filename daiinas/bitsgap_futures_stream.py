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
        "value_class": ("NULL" if "value" in value and value["value"] is None else
                        "OBJECT" if isinstance(value.get("value"), dict) else
                        "ARRAY" if isinstance(value.get("value"), list) else
                        "OTHER" if "value" in value else "ABSENT"),
    }


class BitsgapFuturesStream:
    def __init__(self, observer: BitsgapFuturesObserver):
        self.observer = observer
        self.connected = False
        self.authenticated = False
        self.last_rest_observation = None
        self.updates = 0
        self.disconnects = 0
        self.last_failure = None
        self.last_frame_shape = None
        self.unscoped_control_responses = 0

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

    def _ingest(self, message):
        if not isinstance(message, dict) or message.get("topic") not in _SUBS:
            _fail("WS_UNVERIFIED_TOPIC_FRAME")
        params = message.get("params")
        if (not isinstance(params, dict) or set(params) != {"em"}
                or type(params["em"]) is not int or params["em"] != self.observer._futures_em):
            _fail("WS_FOREIGN_EXCHANGE_SCOPE")
        topic = message["topic"]
        if message.get("ok") is False:
            # Some subscriptions are absent when the exchange has no data.
            # Never claim a negative acknowledgment means zero orders/positions.
            return {"topic": topic, "event": "SUBSCRIPTION_REJECTED",
                    "funding_authorized": False}
        if message.get("ok") is not True:
            _fail("WS_UNVERIFIED_TOPIC_FRAME")
        if "value" in message and message["value"] is None:
            return {"topic": topic, "event": "PROVIDER_NO_DATA",
                    "funding_authorized": False}
        if "value" not in message:
            if message.get("mes") == "subscribed" and set(message) <= {"ok", "topic", "params", "mes"}:
                return {"topic": topic, "event": "SUBSCRIBED", "funding_authorized": False}
            _fail("WS_UNVERIFIED_TOPIC_FRAME")
        if set(message) - {"ok", "topic", "params", "value"}:
            _fail("WS_UNVERIFIED_TOPIC_FRAME")
        value = message["value"]
        if topic == "balance":
            self.observer._balance(value)
            count = 1
        elif topic == "orders":
            count = self.observer._orders(value)
        else:
            count, _, _ = self.observer._positions(value, settings=(topic == "positions_settings"))
        self.updates += 1
        # Raw private data never moves from the validation boundary to events/logs.
        return {"topic": topic, "event": "VALIDATED_UPDATE", "record_count": count,
                "funding_authorized": False}

    async def watch_once(self, connect, *, on_event, max_messages=None):
        """Connect/subscribe read-only, yield sanitized observations; no blind retry."""
        if self.observer._futures_em is None:
            _fail("FUTURES_DISCOVERY_REQUIRED")
        self.connected = False
        self.authenticated = False
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
                await ws.send(json.dumps(subscribe, separators=(",", ":")))
                self.connected = True
                processed = 0
                while max_messages is None or processed < max_messages:
                    frame = _parse_json(await ws.recv())
                    messages = frame if isinstance(frame, list) else [frame]
                    for msg in messages:
                        try:
                            # Bitsgap may acknowledge a batch with {ok, mes} and
                            # no topic. This is NOT a scoped subscription ACK.
                            if (isinstance(msg, dict) and set(msg) == {"ok", "mes"}
                                    and type(msg["ok"]) is bool
                                    and isinstance(msg["mes"], str)):
                                if not msg["ok"]:
                                    _fail("WS_UNSCOPED_REJECTION")
                                self.unscoped_control_responses += 1
                                event = {"topic": "account", "event": "UNSCOPED_OK_RESPONSE",
                                         "funding_authorized": False}
                            else:
                                event = self._ingest(msg)
                        except BitsgapError:
                            self.last_frame_shape = _safe_envelope_shape(msg)
                            raise
                        await on_event(event)
                        processed += 1
                        if max_messages is not None and processed >= max_messages:
                            break
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
