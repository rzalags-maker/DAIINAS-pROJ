"""Owner-private Futures acceptance view; reads the existing worker checkpoint.

Never loads credentials or sends provider requests. No trade permission exists.
Private comparison records contain financial data and must never enter Git/CI.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import json
from pathlib import Path
import sys

from .bitsgap_account_state import AccountState, AccountStateError, BLOCKED, PrivateStore, SOURCES, TOPICS, _ci


def trusted_terminal():
    return not _ci() and sys.stdin.isatty() and sys.stdout.isatty()


def load_state(store, scope_ref, *, clock_ms=None):
    saved = store.load()
    if not isinstance(saved, dict):
        raise AccountStateError("NO_CHECKPOINT")
    scope = type("CheckpointScope", (), {"_futures_em": saved.get("market_id")})()
    return AccountState(scope, scope_ref=scope_ref, store=store,
                        status_reader=True, clock_ms=clock_ms)


def visibility(state, *, private=False):
    """Redacted by default; current amounts require coherent, connected evidence."""
    now = state.clock()
    status = state.status(private=True)
    balance = status["topics"]["balance"]
    current = status["connection"] == "CONNECTED" and balance["state"] == "VALIDATED"
    blockers = []
    if status["connection"] != "CONNECTED":
        blockers.append("OBSERVER_NOT_CONNECTED")
    if not current:
        blockers.append("BALANCE_NOT_CURRENT_CROSS_TRANSPORT_VALIDATED")
    if any(status["topics"][t]["state"] not in ("VERIFIED_EMPTY", "VERIFIED_ACTIVE")
           for t in ("orders", "positions")):
        blockers.append("EXPOSURE_NOT_RECONCILED")
    if status["observed_position_mode"] != "ONE_WAY":
        blockers.append("ONE_WAY_NOT_VALIDATED")
    blockers += ["TERMINAL_PARITY_NOT_VERIFIED", "ACCOUNT_IDENTITY_AND_COMPLETENESS_UNVERIFIED",
                 "EQUITY_FREE_MARGIN_AND_COSTS_UNVERIFIED", "PERSISTENT_TP_SL_UNVERIFIED"]
    result = {"connection": status["connection"], "source": "BITSGAP REST + WS",
        "exchange": "KUCOIN_FUTURES", "currency": "USDT",
        "account_identity": status["account_identity"],
        "timestamp_source": status["timestamp_source"],
        "freshness_ttl_ms": state.max_age_ms, "comparison_window_ms": state.comparison_ms,
        "state_version": state.state_version, "generation": state.generation,
        "balance_state": balance["state"], "balance_reason": balance["reason"],
        "balance_current": current, "sources": {},
        "open_orders_state": status["topics"]["orders"]["state"],
        "positions_state": status["topics"]["positions"]["state"],
        "position_mode": status["observed_position_mode"],
        "position_mode_state": status["topics"]["positions_settings"]["state"],
        "free_margin": "UNVERIFIED", "terminal_parity": "NOT_VERIFIED",
        "balance_terminal_parity": "NOT_VERIFIED",
        "account_readiness": "PARTIAL" if current else "BLOCKED",
        "blockers": blockers, "model_a": "PREVIEW ONLY", "new_entry": BLOCKED,
        "orders_enabled": False, "live_trading": "DISABLED", "read_only_safety": "PASS"}
    for topic in TOPICS:
        result["sources"][topic] = {}
        for source in SOURCES:
            r = state.records.get((topic, source))
            result["sources"][topic][source] = {
                "validation": r.quality if r else "UNVERIFIED",
                "fresh": state._current(r, now) and state.connected,
                "received_ms": r.received_ms if r else None,
                "age_ms": now-r.received_ms if r else None}
    if private:
        result.update(market_id=state.market_id, scope_ref=state.scope_ref,
            total_reported=status["total_reported"] if current else "UNVERIFIED",
            available_reported=status["available_reported"] if current else "UNVERIFIED",
            amount_semantics="BITSGAP balance.t TOTAL; balance.a AVAILABLE_FOR_TRADING; NOT VERIFIED FREE MARGIN",
            last_observed={"total_reported": status["total_reported"],
                "available_reported": status["available_reported"],
                "received_ms": status["wallet_observed_ms"], "current": current},
            open_orders=status["pending_orders"], positions=status["open_positions"])
    return result


def _amount(text):
    if not isinstance(text, str) or not 1 <= len(text) <= 100:
        raise AccountStateError("INVALID_TERMINAL_INPUT")
    try:
        d = Decimal(text)
        if not d.is_finite() or d < 0 or abs(d.adjusted()) > 100:
            raise InvalidOperation()
        return d
    except (InvalidOperation, ValueError):
        raise AccountStateError("INVALID_TERMINAL_INPUT") from None


def compare_terminal(state, terminal, *, captured_ms=None):
    """Pure private comparison. Owner assertions never upgrade API truth."""
    now = state.clock()
    required = {"total", "available", "precision", "observed_ms", "open_orders",
                "positions", "position_mode", "same_account_confirmed", "identity_basis"}
    if not isinstance(terminal, dict) or set(terminal) != required:
        raise AccountStateError("INVALID_TERMINAL_INPUT")
    if (type(terminal["precision"]) is not int or not 0 <= terminal["precision"] <= 18
            or type(terminal["observed_ms"]) is not int or terminal["observed_ms"] < 0
            or type(terminal["same_account_confirmed"]) is not bool
            or terminal["position_mode"] not in ("ONE_WAY", "HEDGE", "UNVERIFIED")
            or terminal["identity_basis"] not in ("OWNER_CONFIRMED_KEY_BOUND_MARKET", "UNVERIFIED")
            or any(v is not None and (type(v) is not int or v < 0)
                   for v in (terminal["open_orders"], terminal["positions"]))):
        raise AccountStateError("INVALID_TERMINAL_INPUT")
    total, available = _amount(terminal["total"]), _amount(terminal["available"])
    if available > total:
        raise AccountStateError("INVALID_TERMINAL_INPUT")
    view = visibility(state, private=True)
    received = [view["sources"]["balance"][s]["received_ms"] for s in SOURCES]
    times = [now, terminal["observed_ms"], *received]
    in_window = (all(type(t) is int and 0 <= t <= now for t in times)
                 and max(times)-min(times) <= state.comparison_ms
                 and (captured_ms is None or 0 <= now-captured_ms <= state.comparison_ms))
    amounts = {}
    for name, displayed in (("total", total), ("available", available)):
        field = name+"_reported"
        provider = view[field]
        if provider == "UNVERIFIED":
            amounts[name] = {"outcome": "NOT_VERIFIED", "difference": None}
        else:
            with localcontext() as ctx:
                ctx.prec = 256
                api = _amount(provider)
                quantum = Decimal(1).scaleb(-terminal["precision"])
                # Explicit nearest/half-up policy; operator must confirm UI rounding.
                equal = api.quantize(quantum, rounding=ROUND_HALF_UP) == displayed
                amounts[name] = {"outcome": "MATCH" if equal else "MISMATCH",
                                 "difference": str(api-displayed)}
    evidence = terminal["same_account_confirmed"] and terminal["identity_basis"] != "UNVERIFIED"
    if view["connection"] != "CONNECTED" or not in_window:
        outcome = "STALE"
    elif not view["balance_current"] or not evidence:
        outcome = "NOT_VERIFIED"
    else:
        outcome = "MATCH" if all(x["outcome"] == "MATCH" for x in amounts.values()) else "MISMATCH"
    def topic_window(topic):
        receipts = [view["sources"][topic][s]["received_ms"] for s in SOURCES]
        samples = [now, terminal["observed_ms"], *receipts]
        return (all(type(t) is int and 0 <= t <= now for t in samples)
                and max(samples)-min(samples) <= state.comparison_ms)
    exposure = {}
    for key, state_key in (("open_orders", "open_orders_state"), ("positions", "positions_state")):
        known = view[state_key] in ("VERIFIED_EMPTY", "VERIFIED_ACTIVE") and terminal[key] is not None
        exposure[key] = ("STALE" if not in_window or view["connection"] != "CONNECTED" else
            "NOT_VERIFIED" if not evidence or not known else
            "STALE" if not topic_window("orders" if key == "open_orders" else "positions") else
            "MATCH" if view[key] == terminal[key] else "MISMATCH")
    mode = ("STALE" if not in_window or view["connection"] != "CONNECTED" else
        "NOT_VERIFIED" if not evidence or view["position_mode_state"] != "VALIDATED"
        or terminal["position_mode"] == "UNVERIFIED" else
        "STALE" if not topic_window("positions_settings") else
        "MATCH" if view["position_mode"] == terminal["position_mode"] else "MISMATCH")
    outcomes = [outcome, mode, *exposure.values()]
    overall = ("STALE" if "STALE" in outcomes else "MISMATCH" if "MISMATCH" in outcomes
               else "NOT_VERIFIED" if "NOT_VERIFIED" in outcomes else "MATCH")
    return {"version": 1, "kind": "PRIVATE_TERMINAL_COMPARISON", "market_id": state.market_id,
        "scope_ref": state.scope_ref, "currency": "USDT", "generation": state.generation,
        "state_version": state.state_version, "captured_ms": now,
        "terminal": terminal, "terminal_timestamp_source": "OWNER_LOCAL_OBSERVATION_NOT_PROVIDER_TIME",
        "api": view, "same_window": in_window,
        "rounding": "ROUND_HALF_UP_OWNER_MUST_CONFIRM", "amounts": amounts,
        "balance_outcome": outcome, "overall_outcome": overall, "exposure_outcomes": exposure,
        "position_mode_outcome": mode, "orders_enabled": False,
        "account_identity": "OWNER_ASSERTED_NOT_INDEPENDENTLY_VERIFIED"}


def _prompt_terminal():
    print("Private comparison: verify KuCoin FUTURES, USDT, key-bound account and UI rounding.")
    confirmed = input("Same key-bound market/account corroborated? Type YES: ") == "YES"
    precision = int(input("Confirmed decimal display precision (half-up rounding): "))
    mode = input("Terminal mode ONE_WAY/HEDGE/UNVERIFIED: ").strip()
    print("Now sample the live terminal. Enter one line: TOTAL AVAILABLE ORDERS POSITIONS UTC_MS")
    print("Use ? for unknown counts; NOW for the local time you confirm this live sample.")
    fields = input("Live sample: ").split()
    if len(fields) != 5:
        raise AccountStateError("INVALID_TERMINAL_INPUT")
    import time
    observed_ms = int(time.time() * 1000) if fields[4] == "NOW" else int(fields[4])
    return {"total": fields[0], "available": fields[1], "precision": precision,
        "observed_ms": observed_ms,
        "open_orders": None if fields[2] == "?" else int(fields[2]),
        "positions": None if fields[3] == "?" else int(fields[3]),
        "position_mode": mode, "same_account_confirmed": confirmed,
        "identity_basis": "OWNER_CONFIRMED_KEY_BOUND_MARKET" if confirmed else "UNVERIFIED"}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state-file", type=Path, required=True)
    p.add_argument("--scope-ref", required=True)
    p.add_argument("--private-panel", action="store_true")
    p.add_argument("--compare", action="store_true")
    p.add_argument("--comparison-file", type=Path)
    args = p.parse_args(argv)
    if (args.private_panel or args.compare) and not trusted_terminal():
        print(json.dumps({"status": "PRIVATE_OUTPUT_DISALLOWED", "orders_enabled": False}))
        return 2
    if args.compare and (not args.private_panel or args.comparison_file is None):
        print(json.dumps({"status": "PRIVATE_COMPARISON_REQUIRES_PRIVATE_PANEL_AND_FILE", "orders_enabled": False}))
        return 2
    try:
        if args.comparison_file and args.comparison_file.resolve() == args.state_file.resolve():
            raise AccountStateError("SEPARATE_COMPARISON_FILE_REQUIRED")
        # Prompt before loading: compare against a fresh checkpoint after operator input.
        terminal = _prompt_terminal() if args.compare else None
        with_store = PrivateStore(args.state_file, readonly=True)
        try:
            state = load_state(with_store, args.scope_ref)
            result = visibility(state, private=args.private_panel)
            if args.compare:
                record = compare_terminal(state, terminal)
                target = PrivateStore(args.comparison_file)
                try:
                    existing = target.load()
                    if existing is not None and existing.get("kind") != "PRIVATE_TERMINAL_COMPARISON":
                        raise AccountStateError("NOT_A_COMPARISON_FILE")
                    target.save(record)
                finally:
                    target.close()
                result["private_comparison"] = record
                result["terminal_parity"] = record["overall_outcome"]
                result["balance_terminal_parity"] = record["balance_outcome"]
            elif args.comparison_file:
                saved_store = PrivateStore(args.comparison_file, readonly=True)
                try:
                    record = saved_store.load()
                finally:
                    saved_store.close()
                if (not isinstance(record, dict) or record.get("kind") != "PRIVATE_TERMINAL_COMPARISON"
                        or record.get("market_id") != state.market_id
                        or record.get("scope_ref") != state.scope_ref):
                    raise AccountStateError("COMPARISON_SCOPE_MISMATCH")
                if record.get("generation") != state.generation:
                    result["terminal_parity"] = "STALE"
                    result["balance_terminal_parity"] = "STALE"
                else:
                    comparison = compare_terminal(state, record["terminal"], captured_ms=record["captured_ms"])
                    result["terminal_parity"] = comparison["overall_outcome"]
                    result["balance_terminal_parity"] = comparison["balance_outcome"]
            if result["terminal_parity"] == "MATCH":
                result["blockers"].remove("TERMINAL_PARITY_NOT_VERIFIED")
            print(json.dumps(result, sort_keys=True))
        finally:
            with_store.close()
        return 0  # Observation displayed; never execution permission.
    except (Exception, KeyboardInterrupt):
        # Never emit exception text, arbitrary operator input, paths or payloads.
        print(json.dumps({"status": "LOCAL_VISIBILITY_UNVERIFIED", "orders_enabled": False,
                          "new_entry": BLOCKED}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
