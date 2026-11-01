"""DAIINAS startup source-of-truth: KuCoin Classic Futures read-only observation.

A valid read is NOT an account reconciliation or permission to trade. Never
bootstrap Model A or overwrite a MOCK ledger using these currency-level values.
"""
import argparse
import json
import os

from .kucoin_readonly import APIError, Credentials, ReadOnly, probe


def summarize(observation, *, show_local_balances=False):
    """Produce a narrow, deterministic status; never emit identifiers or keys.

    'available' in the Classic Futures currency asset read is informational.
    It is not guaranteed executable margin or the Model A ACTIVE allocation.
    """
    if not isinstance(observation, dict):
        raise ValueError("Expected sanitized KuCoin read-only probe result")

    status = observation.get("status")
    mode = observation.get("mode")
    checks = observation.get("checks", {})
    if not isinstance(checks, dict):
        checks = {}
    balance = observation.get("futures_usdt")
    balance_observed = (
        mode == "CLASSIC" and checks.get("balance") == "CURRENCY_ASSETS_ONLY"
        and isinstance(balance, dict)
        and all(isinstance(balance.get(k), str) for k in ("balance", "equity", "available"))
    )
    scope_checks = ("positions", "orders", "stops")
    scope_observed = balance_observed and all(checks.get(k) == "OK" for k in scope_checks)

    if status == "UNSUPPORTED_UTA":
        stage, next_action = "UNSUPPORTED_UTA", "REVIEW_UTA_FUTURES_BUYING_POWER_CONTRACT"
    elif status == "NOT_CONNECTED":
        stage, next_action = "NOT_CONNECTED", "VERIFY_GENERAL_ONLY_SECRETS_AND_API_ACCESS"
    elif balance_observed and scope_observed:
        stage, next_action = "CURRENCY_AND_EXPOSURE_LISTS_OBSERVED", "IMPLEMENT_COMPLETE_AUTHENTICATED_FUTURES_RECONCILIATION"
    elif balance_observed:
        stage, next_action = "CURRENCY_ONLY_PARTIAL", "RESOLVE_POSITION_ORDER_AND_STOP_SCOPE"
    else:
        stage, next_action = "BALANCE_UNVERIFIED", "VERIFY_CLASSIC_FUTURES_USDT_CURRENCY_READ"

    output = {
        "source": "KUCOIN_DIRECT_GENERAL_READ_ONLY",
        "account_target": "KUCOIN_CLASSIC_FUTURES_USDT",
        "observation_status": stage,
        "mode": mode if mode in ("CLASSIC", "UNIFIED") else "UNVERIFIED",
        "currency_assets_observed": balance_observed,
        "positions_orders_stops_list_observed": scope_observed,
        "failed_observations": sorted(k for k in ("mode", "balance", *scope_checks, "fees")
                                      if checks.get(k) not in ("OK", "CURRENCY_ASSETS_ONLY")),
        "available": (balance["available"] if show_local_balances and balance_observed else "REDACTED_OR_UNVERIFIED"),
        "equity": (balance["equity"] if show_local_balances and balance_observed else "REDACTED_OR_UNVERIFIED"),
        "balance": (balance["balance"] if show_local_balances and balance_observed else "REDACTED_OR_UNVERIFIED"),
        "available_is_trading_capital": False,
        "authenticated_model_a_reconciled": False,
        "real_account_strategy_start": "BLOCKED",
        "live_order_routing": "DISABLED",
        "next_action": next_action,
    }
    return output


def run(*, include_balances=False, fee_symbol="XBTUSDTM", env=None, transport=None):
    """Only sign GET requests through the existing KuCoin General-only adapter."""
    try:
        credentials = Credentials.from_env(env)
        api = ReadOnly(credentials) if transport is None else ReadOnly(credentials, transport=transport)
        report = probe(api, fee_symbol=fee_symbol)
    except APIError:
        report = {"status": "NOT_CONNECTED", "checks": {}}
    except Exception:
        # No untrusted URLs, exceptions or response bodies in stdout.
        report = {"status": "NOT_CONNECTED", "checks": {}}
    return summarize(report, show_local_balances=include_balances)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fee-symbol", default="XBTUSDTM")
    parser.add_argument("--show-local-balances", action="store_true",
                        help="Print private currency-level balances ONLY on a trusted LOCAL terminal")
    args = parser.parse_args(argv)
    if args.show_local_balances and os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        print(json.dumps({"error": "PRIVATE_BALANCES_BLOCKED_IN_GITHUB_ACTIONS",
                          "real_account_strategy_start": "BLOCKED"}))
        return 2
    result = run(include_balances=args.show_local_balances, fee_symbol=args.fee_symbol)
    print(json.dumps(result, indent=2, sort_keys=True))
    # A successful read-only observation is never a successful real trading start.
    return 0 if result["observation_status"] == "CURRENCY_AND_EXPOSURE_LISTS_OBSERVED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
