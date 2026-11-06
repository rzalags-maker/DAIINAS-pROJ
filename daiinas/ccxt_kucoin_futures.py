"""CCXT-shaped fixture adapter.  Offline only; CCXT is not imported or required."""
from .execution_replay import ExecutionIntent, replay

REVISION = "ccxt@a31f168905acea92c05d20750eda0d7ac350eb70"


class CCXTKucoinFuturesAdapter:
    transport = "OFFLINE_FIXTURE_ONLY"

    def market(self, raw):
        required = {"id", "symbol", "contractSize", "precision", "limits"}
        if not isinstance(raw, dict) or not required <= set(raw): raise ValueError("CCXT_MARKET_SCHEMA")
        precision = raw["precision"]
        if not isinstance(precision, dict) or "amount" not in precision or "price" not in precision: raise ValueError("CCXT_PRECISION_SCHEMA")
        return {"symbol": raw["symbol"], "exchange_symbol": raw["id"], "contract_size": str(raw["contractSize"]),
                "amount_precision": precision["amount"], "price_precision": precision["price"],
                "minimum_amount": str(raw["limits"].get("amount", {}).get("min", "0")), "source_revision": REVISION}

    def conditional_capability(self, features):
        # Unified feature advertisement never becomes venue acceptance.
        value = bool(isinstance(features, dict) and features.get("attachedStopLossTakeProfit"))
        return {"status": "DOCUMENTED_ONLY" if value else "BLOCKED", "advertised": value,
                "reason": "CCXT_FEATURE_NOT_VENUE_ACCEPTANCE", "source_revision": REVISION}

    def replay(self, intent: ExecutionIntent, events): return replay(intent, events)
