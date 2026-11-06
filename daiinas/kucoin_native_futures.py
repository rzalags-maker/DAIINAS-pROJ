"""Offline normalizer for documented KuCoin Futures conditional-order fixtures."""
from .execution_replay import ExecutionIntent, replay

REVISION = "kucoin-universal-sdk@c2f39bdb8b7d5f31cfb3fd532f9baf2f09fd8f12"


class KucoinNativeFuturesAdapter:
    transport = "OFFLINE_FIXTURE_ONLY"

    def conditional_request(self, *, client_oid, symbol, side, size, take_profit, stop_loss,
                            trigger_reference="MP", reduce_only=True, margin_mode="ISOLATED"):
        if (not isinstance(client_oid, str) or not 1 <= len(client_oid) <= 40 or side not in ("buy", "sell")
                or trigger_reference not in ("TP", "MP", "IP") or margin_mode not in ("ISOLATED", "CROSS")
                or not reduce_only or int(size) <= 0): raise ValueError("NATIVE_CONDITIONAL_SCHEMA")
        # This is a serializable fixture shape only. It deliberately has no send method.
        return {"clientOid": client_oid, "symbol": symbol, "side": side, "type": "market", "size": int(size),
                "stopPriceType": trigger_reference, "reduceOnly": True, "marginMode": margin_mode,
                "triggerStopUpPrice": str(take_profit), "triggerStopDownPrice": str(stop_loss),
                "classification": "DOCUMENTED_ONLY", "source_revision": REVISION}

    def replay(self, intent: ExecutionIntent, events): return replay(intent, events)
