"""Bounded, account-scoped Bitsgap Futures WebSocket diagnostic.

This module sends only signed authentication and four read-only account-topic
subscriptions. It NEVER sends commands, prints balances, IDs or raw frames.
A missing message is NOT evidence of zero live orders or positions.
"""
from __future__ import annotations

import asyncio
import json
import os

from .bitsgap_readonly import BitsgapError
from .bitsgap_futures_observe import BitsgapFuturesObserver, safe_diagnostic_category
from .bitsgap_futures_stream import BitsgapFuturesStream, read_only_ws_topics

_TOPIC_RANK = {"NO_EVENT_WITHIN_WINDOW":0, "SUBSCRIBED":1, "SUBSCRIPTION_REJECTED":2,
               "PROVIDER_NO_DATA":2, "VALIDATED_UPDATE":3}
_SAFE_WS_ERRORS = frozenset({
    "WS_BAD_FRAME", "WS_AUTH_UNVERIFIED", "WS_UNVERIFIED_TOPIC_FRAME",
    "WS_FOREIGN_EXCHANGE_SCOPE", "WS_DISCONNECTED_OR_TRANSPORT_ERROR",
    "WS_TERMINAL_AUTH_FAILURE", "INVALID_OBSERVATION_CLOCK",
})


async def probe_bounded(*, observer, connect, seconds=8):
    """Inspect a real account without live writes; summarize only category labels."""
    if type(seconds) is not int or not (1 <= seconds <= 30):
        raise ValueError("Probe window must be an integer from 1 to 30 seconds")
    statuses = {topic: "NO_EVENT_WITHIN_WINDOW" for topic in read_only_ws_topics()}
    stream = BitsgapFuturesStream(observer)
    async def on_event(event):
        topic = event.get("topic")
        if topic in statuses:
            kind = event.get("event")
            if kind in _TOPIC_RANK and _TOPIC_RANK[kind] >= _TOPIC_RANK[statuses[topic]]:
                statuses[topic] = kind
    failure = "NONE"
    try:
        await asyncio.wait_for(stream.watch_once(connect, on_event=on_event),
                               timeout=seconds)
    except asyncio.TimeoutError:
        # A bounded observation window is normal. Some topics do not subscribe
        # when there are no corresponding exchange data (vendor docs).
        failure = "OBSERVATION_WINDOW_FINISHED"
    except BitsgapError as exc:
        failure = exc.category if exc.category in _SAFE_WS_ERRORS else safe_diagnostic_category(exc.category)
    except Exception:
        failure = "LOCAL_WS_RUNTIME_FAILURE"
    # A read-only REST account observation and a WS auth OK are independent facts.
    wallet = stream.last_rest_observation
    return {
        "source": "BITSGAP_KUCOIN_FUTURES",
        "rest_balance": "VALIDATED" if wallet is not None else "UNVERIFIED",
        "rest_orders": wallet.orders_status if wallet is not None else "UNVERIFIED",
        "rest_positions": wallet.positions_status if wallet is not None else "UNVERIFIED",
        "websocket_auth": "PASS" if stream.authenticated else "UNVERIFIED",
        "websocket_topics": statuses,
        "diagnostic_outcome": failure,
        "absence_of_data_is_zero_exposure": False,
        "model_a_reconciled": False,
        "order_routing": "DISABLED",
    }


async def _live_probe():
    from websockets.asyncio.client import connect
    client = BitsgapFuturesObserver(os.environ.get("BITSGAP_PRIVATE_KEY_PEM"))
    client.discover()
    def secure_connect(url):
        # No credentials in URL; an authenticated Ed25519 frame is sent inside.
        return connect(url, open_timeout=5, close_timeout=2,
                       max_size=65536, max_queue=16, ping_interval=20)
    return await probe_bounded(observer=client, connect=secure_connect, seconds=8)


def main():
    try:
        result = asyncio.run(_live_probe())
        print(json.dumps(result, sort_keys=True))
        return 0 if result["websocket_auth"] == "PASS" else 2
    except ImportError:
        category = "MISSING_WEBSOCKETS_DEPENDENCY"
    except BitsgapError as exc:
        category = safe_diagnostic_category(exc.category)
    except Exception:
        category = "LOCAL_RUNTIME_UNVERIFIED"
    print(json.dumps({"source":"BITSGAP_KUCOIN_FUTURES",
                      "status":"UNVERIFIED","reason":category,
                      "order_routing":"DISABLED","model_a_reconciled":False},
                     sort_keys=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
