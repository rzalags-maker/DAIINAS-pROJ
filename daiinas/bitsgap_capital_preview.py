"""Non-mutating Model A projection, never an admission or funding adapter.

Existing ledgers retain their history. An explicit hypothetical first-allocation
scenario can use a fresh reported wallet total, but that total is NOT verified
eligible Futures equity. Actual financial/exposure admission stays blocked.
"""
from dataclasses import dataclass, field
import json

from .capital_ladder import CapitalLadder
from .account_capital import exact
from .execution_boundary import InertOrderGateway
from .bitsgap_account_state import AccountStateError, BLOCKED


@dataclass(frozen=True, repr=False)
class CapitalAdmissionPreview:
    source: str
    blockers: tuple
    _projection: dict | None = field(default=None, repr=False)

    def __repr__(self):
        return "CapitalAdmissionPreview(PRIVATE_PROJECTION_REDACTED, NOT_ADMITTED)"

    def safe_status(self):
        return {"decision": BLOCKED, "source": self.source,
                "projection_available": self._projection is not None,
                "blockers": list(self.blockers),
                "eligible_capital": "UNVERIFIED", "funded_slots": "BLOCKED",
                "funding_authorized": False, "order_routing": "DISABLED",
                "execution_transport": InertOrderGateway().status()["transport"]}

    def private_status(self):
        # Only the trusted CLI's existing private-output gate may expose this.
        # JSON round trip returns a detached value; no mutable ladder is shared.
        return {**self.safe_status(), "model_a_projection":
                json.loads(json.dumps(self._projection)) if self._projection else None,
                "projection_is_verified_account_allocation": False}


def capital_admission_preview(service, *, existing_ladder=None, initial_scenario=False):
    """Read current observations and project ONLY with the existing Model A code.

    existing_ladder: CapitalLadder or its exported JSON. Never reset an existing
    account from its current wallet number. initial_scenario is an explicit,
    counterfactual first-funding scenario, not an account initialization action.
    """
    if type(initial_scenario) is not bool or (existing_ladder is not None and initial_scenario):
        raise AccountStateError("AMBIGUOUS_PREVIEW_SOURCE")
    observed = service.status(private=True)
    blockers = ["OBSERVE_PHASE_NO_FUNDING_AUTHORIZATION"]
    if observed["connection"] != "CONNECTED":
        blockers.append("ACCOUNT_CONNECTION_NOT_CURRENT")
    if any(observed["topics"][topic]["state"] not in ("VERIFIED_EMPTY", "VERIFIED_ACTIVE")
           for topic in ("orders", "positions")):
        blockers.append("EXPOSURE_UNVERIFIED")
    for name in ("equity", "free_margin", "margin_committed", "unrealized_pnl",
                 "fees_funding", "position_protection", "collateral_eligibility"):
        if observed[name] == "UNVERIFIED":
            blockers.append(name.upper() + "_UNVERIFIED")
    if observed["account_identity"] != "VERIFIED":
        blockers.append("ACCOUNT_IDENTITY_UNVERIFIED")
    if observed["snapshot_atomicity"] != "VERIFIED_COHERENT_ACCOUNT":
        blockers.append("ACCOUNT_COHERENCE_UNVERIFIED")
    if observed["observed_position_mode"] != "ONE_WAY":
        blockers.append("OBSERVED_ONE_WAY_UNVERIFIED_OR_MISMATCH")
    source = "NO_LADDER_CONTEXT"
    ladder = None
    if existing_ladder is not None:
        try:
            encoded = existing_ladder.export_state() if isinstance(existing_ladder, CapitalLadder) else existing_ladder
            decoded = json.loads(encoded)
            if type(decoded.get("slot_ceiling")) is not int:
                raise ValueError()
            ladder = CapitalLadder.restore(encoded)
        except Exception:
            raise AccountStateError("INVALID_EXISTING_LADDER_PREVIEW") from None
        source = "DETACHED_EXISTING_LEDGER_HISTORY"
        # Wallet total and a historic ladder total are different scopes. Do not
        # synthesize deposits, P&L, reserve moves or recovery from their delta.
        blockers.append("WALLET_TO_LEDGER_RECONCILIATION_UNVERIFIED")
    elif initial_scenario:
        source = "HYPOTHETICAL_INITIAL_ALLOCATION_FROM_REPORTED_TOTAL"
        if observed.get("wallet_amounts_status") != "CURRENT_LOCAL_RECEIPT":
            blockers.append("CURRENT_REPORTED_TOTAL_UNVERIFIED")
        else:
            try:
                capital = exact(observed["total_reported"])
                if capital <= 0:
                    raise ValueError()
                ladder = CapitalLadder(capital)
            except Exception:
                raise AccountStateError("INVALID_INITIAL_CAPITAL_SCENARIO") from None
        blockers.append("REPORTED_TOTAL_NOT_VERIFIED_ELIGIBLE_CAPITAL")
    else:
        blockers.append("EXISTING_LEDGER_OR_EXPLICIT_INITIAL_SCENARIO_REQUIRED")
    projection = None
    if ladder is not None:
        state = ladder.snapshot()
        projection = {
            "reserve": state["reserve"], "active": state["active"],
            "pending": state["pending"], "deficit": state["deficit"],
            "stage": state["stage"], "nominal_slot_ceiling": state["slot_ceiling"],
            "next_step": state["next_step"], "total": state["total"],
            "policy": state["policy"],
            "actual_admissible_slots": "BLOCKED",
            "new_position_risk_budget": "UNVERIFIED",
            "reason": "NOMINAL_MODEL_A_MATH_ONLY_NOT_FREE_MARGIN_OR_TRADE_PERMISSION",
        }
    return CapitalAdmissionPreview(source, tuple(blockers), projection)
