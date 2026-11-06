"""P10 offline-only execution adapter boundary.

This is a deterministic receipt replay, not a transport.  It has no HTTP,
credential, secret, websocket, order, cancellation or account operation.
"""
from dataclasses import dataclass, field
from decimal import Decimal


def _d(value):
    try: result = Decimal(str(value))
    except Exception as exc: raise ValueError("INVALID_DECIMAL") from exc
    if not result.is_finite() or result < 0: raise ValueError("INVALID_DECIMAL")
    return result


@dataclass(frozen=True)
class ExecutionIntent:
    client_oid: str
    symbol: str
    side: str
    quantity: str
    reduce_only: bool = False

    def __post_init__(self):
        if (not self.client_oid or not self.symbol or self.side not in ("LONG", "SHORT")
                or _d(self.quantity) <= 0 or type(self.reduce_only) is not bool):
            raise ValueError("INVALID_EXECUTION_INTENT")


@dataclass
class ReplayState:
    intent: ExecutionIntent
    seen: set = field(default_factory=set)
    exchange_order_id: str | None = None
    filled: Decimal = Decimal("0")
    protection: dict = field(default_factory=dict)
    external_exposure: bool = False
    provider_positions_available: bool = True
    free_margin_available: bool = True
    ambiguous_submission: bool = False
    restarted: bool = False
    exit_kind: str | None = None
    reasons: list = field(default_factory=list)

    def block(self, reason):
        if reason not in self.reasons: self.reasons.append(reason)

    def result(self):
        protected = (self.filled > 0 and set(self.protection) == {"TP", "SL"}
                     and all(x["quantity"] == self.filled for x in self.protection.values())
                     and all(x["exchange_order_id"] for x in self.protection.values()))
        if self.exit_kind and not all(x.get("sibling_terminal") for x in self.protection.values()):
            protected = False; self.block("SIBLING_STATE_UNCONFIRMED")
        if self.filled > 0 and not protected and not self.exit_kind:
            self.block("UNPROTECTED_EXPOSURE")
        if self.external_exposure: self.block("EXTERNAL_ORDER_OR_POSITION_UNKNOWN")
        if not self.provider_positions_available: self.block("PROVIDER_POSITIONS_UNAVAILABLE")
        if not self.free_margin_available: self.block("FREE_MARGIN_UNAVAILABLE")
        if self.ambiguous_submission: self.block("AMBIGUOUS_SUBMISSION_RECONCILE_FIRST")
        return {"client_oid": self.intent.client_oid, "exchange_order_id": self.exchange_order_id,
                "filled_quantity": str(self.filled), "protection_confirmed": protected,
                "exit_kind": self.exit_kind, "restarted": self.restarted,
                "new_entries_allowed": False,
                "status": "REPLAY_VERIFIED" if protected and not self.reasons else "BLOCKED",
                "reasons": self.reasons[:]}


def replay(intent, events):
    """Apply a single recorded event trace. Duplicate event IDs are exactly-once."""
    state = ReplayState(intent)
    for event in events:
        if not isinstance(event, dict) or set(event) - {"id", "kind", "exchange_order_id", "quantity", "role", "sibling_terminal"}:
            raise ValueError("INVALID_REPLAY_EVENT")
        eid, kind = event.get("id"), event.get("kind")
        if not isinstance(eid, str) or not eid or not isinstance(kind, str): raise ValueError("INVALID_REPLAY_EVENT")
        if eid in state.seen: continue
        state.seen.add(eid)
        if kind == "ENTRY_ACK":
            oid = event.get("exchange_order_id")
            if not isinstance(oid, str) or not oid: raise ValueError("MISSING_EXCHANGE_ORDER_ID")
            if state.exchange_order_id and state.exchange_order_id != oid: state.block("CONFLICTING_ENTRY_ACK")
            state.exchange_order_id = oid
        elif kind == "FILL":
            amount = _d(event.get("quantity"))
            if amount <= 0 or state.filled + amount > _d(intent.quantity): raise ValueError("INVALID_FILL_QUANTITY")
            state.filled += amount
        elif kind == "PROTECTION_ACK":
            role, oid, amount = event.get("role"), event.get("exchange_order_id"), _d(event.get("quantity"))
            if role not in ("TP", "SL") or not isinstance(oid, str) or not oid or amount <= 0: raise ValueError("INVALID_PROTECTION_ACK")
            old = state.protection.get(role)
            if old and old["exchange_order_id"] != oid: state.block("CONFLICTING_PROTECTION_ACK")
            state.protection[role] = {"exchange_order_id": oid, "quantity": amount,
                                      "sibling_terminal": bool(event.get("sibling_terminal", False))}
        elif kind == "EXIT":
            if event.get("role") not in ("TP", "SL"): raise ValueError("INVALID_EXIT")
            state.exit_kind = event["role"]
        elif kind == "SIBLING_TERMINAL":
            role = event.get("role")
            if role not in state.protection: state.block("UNKNOWN_SIBLING")
            else: state.protection[role]["sibling_terminal"] = True
        elif kind == "DISCONNECT": state.block("DISCONNECTED_RECONCILIATION_REQUIRED")
        elif kind == "RESTART": state.restarted = True
        elif kind == "AMBIGUOUS_SUBMISSION": state.ambiguous_submission = True
        elif kind == "EXTERNAL_EXPOSURE": state.external_exposure = True
        elif kind == "POSITIONS_UNAVAILABLE": state.provider_positions_available = False
        elif kind == "FREE_MARGIN_UNAVAILABLE": state.free_margin_available = False
        else: raise ValueError("UNKNOWN_REPLAY_EVENT")
    return state.result()
