"""Bitsgap KuCoin Futures account OBSERVE status. No order/write functions.

Default output is CI-safe. --private-panel may be used on a trusted local
terminal only (never GitHub Actions) and contains private financial amounts.
"""
import argparse
import asyncio
import json
import os

from .bitsgap_readonly import BitsgapError
from .bitsgap_futures_observe import BitsgapFuturesObserver, safe_diagnostic_category
from .bitsgap_futures_stream import BitsgapFuturesStream


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-panel", action="store_true")
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args(argv)
    if args.private_panel and (os.environ.get("GITHUB_ACTIONS", "").lower() == "true"
                               or args.watch):
        print(json.dumps({"status":"PRIVATE_OUTPUT_DISALLOWED", "order_routing":"DISABLED"}))
        return 2
    if args.watch:
        return asyncio.run(_watch())
    try:
        client = BitsgapFuturesObserver(os.environ.get("BITSGAP_PRIVATE_KEY_PEM"))
        client.discover()
        snap = client.wallet_observation()
        if args.private_panel:
            print(json.dumps(snap.private_panel(), sort_keys=True))
        else:
            print(json.dumps(snap.safe_status(), sort_keys=True))
        # A valid balance alone is partial evidence, not a green trading gate.
        return 0 if snap.safe_status()["status"] == "OBSERVED_NON_ATOMIC_NOT_RECONCILED" else 2
    except BitsgapError as exc:
        print(json.dumps({"status": "UNVERIFIED", "reason": safe_diagnostic_category(exc.category),
                          "capital_reconciled": False, "orders_enabled": False}, sort_keys=True))
        return 2
    except Exception:
        print(json.dumps({"status":"UNVERIFIED", "reason":"LOCAL_RUNTIME_UNVERIFIED",
                          "capital_reconciled":False, "orders_enabled":False}, sort_keys=True))
        return 2


async def _watch():
    try:
        from websockets.asyncio.client import connect
    except ImportError:
        print(json.dumps({"status":"MISSING_WEBSOCKETS_DEPENDENCY", "orders_enabled":False}))
        return 2
    try:
        client = BitsgapFuturesObserver(os.environ.get("BITSGAP_PRIVATE_KEY_PEM"))
        client.discover()
        stream = BitsgapFuturesStream(client)
        stop = asyncio.Event()
        async def event_callback(event):
            # Only sanitized topic names/statuses and counts are ever printed.
            print(json.dumps(event, sort_keys=True), flush=True)
        await stream.observe_forever(connect, on_event=event_callback, stop_event=stop)
        return 0
    except (BitsgapError, KeyboardInterrupt):
        print(json.dumps({"status":"WATCH_STOPPED_OR_FAILED", "orders_enabled":False}))
        return 2
    except Exception:
        print(json.dumps({"status":"WATCH_UNVERIFIED", "orders_enabled":False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
