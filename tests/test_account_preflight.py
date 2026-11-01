"""Offline, network-free source-of-truth and no-live-funding tests."""
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from daiinas.account_preflight import main, run, summarize


class Wire:
    def __init__(self, *, mode="CLASSIC", fail=None):
        self.mode, self.fail, self.calls = mode, fail, []

    def __call__(self, url, headers):
        self.calls.append(url)
        if self.fail and self.fail in url:
            return json.dumps({"code": "400100", "msg": "private-account-secret"})
        if "/account/mode" in url:
            data = {"selfAccountMode": self.mode}
        elif "/account/balance" in url:
            data = {"accountType": "FUTURES", "accounts": [
                {"currencies": [{"currency": "USDT", "balance": "61.08",
                                "equity": "61.07", "available": "61.07"}]}]}
        elif "/positions" in url:
            data = []
        elif "/orders?" in url or "/stopOrders?" in url:
            data = {"items": [], "totalPage": 1}
        elif "/trade-fees?" in url:
            data = {"symbol": "XBTUSDTM", "makerFeeRate": "0.0002",
                    "takerFeeRate": "0.0006"}
        else:
            raise AssertionError("Unexpected route: " + url)
        return json.dumps({"code": "200000", "data": data}).encode()


class StartSourcePreflightTests(unittest.TestCase):
    def setUp(self):
        self.env = {"KUCOIN_API_KEY": "synthetic-key", "KUCOIN_API_SECRET": "synthetic-secret",
                    "KUCOIN_API_PASSPHRASE": "synthetic-passphrase"}

    def test_observed_classic_futures_is_not_usable_model_a(self):
        wire = Wire()
        r = run(env=self.env, transport=wire)
        self.assertEqual(r["source"], "KUCOIN_DIRECT_GENERAL_READ_ONLY")
        self.assertEqual(r["account_target"], "KUCOIN_CLASSIC_FUTURES_USDT")
        self.assertEqual(r["observation_status"], "CURRENCY_AND_EXPOSURE_LISTS_OBSERVED")
        self.assertTrue(r["currency_assets_observed"])
        self.assertTrue(r["positions_orders_stops_list_observed"])
        self.assertEqual(r["available"], "REDACTED_OR_UNVERIFIED")
        self.assertFalse(r["available_is_trading_capital"])
        self.assertFalse(r["authenticated_model_a_reconciled"])
        self.assertEqual(r["real_account_strategy_start"], "BLOCKED")
        self.assertEqual(r["live_order_routing"], "DISABLED")
        self.assertEqual(len(wire.calls), 6)
        self.assertTrue(all("/api/" in call for call in wire.calls))

    def test_explicit_local_values_are_currency_assets_only(self):
        r = run(env=self.env, transport=Wire(), include_balances=True)
        self.assertEqual(r["available"], "61.07")
        self.assertEqual(r["equity"], "61.07")
        self.assertEqual(r["balance"], "61.08")
        self.assertFalse(r["authenticated_model_a_reconciled"])
        self.assertEqual(r["real_account_strategy_start"], "BLOCKED")

    def test_partial_exposure_scope_does_not_earn_ready_status(self):
        r = run(env=self.env, transport=Wire(fail="/stopOrders"))
        self.assertEqual(r["observation_status"], "CURRENCY_ONLY_PARTIAL")
        self.assertFalse(r["positions_orders_stops_list_observed"])
        self.assertEqual(r["next_action"], "RESOLVE_POSITION_ORDER_AND_STOP_SCOPE")
        self.assertNotIn("private-account-secret", json.dumps(r))

    def test_uta_does_not_fall_back_to_classic_futures_or_spot(self):
        wire = Wire(mode="UNIFIED")
        r = run(env=self.env, transport=wire, include_balances=True)
        self.assertEqual(r["observation_status"], "UNSUPPORTED_UTA")
        self.assertEqual(r["available"], "REDACTED_OR_UNVERIFIED")
        self.assertEqual(len(wire.calls), 1)

    def test_missing_keys_return_explicit_not_connected_without_network(self):
        wire = Wire()
        r = run(env={}, transport=wire, include_balances=True)
        self.assertEqual(r["observation_status"], "NOT_CONNECTED")
        self.assertFalse(r["currency_assets_observed"])
        self.assertEqual(wire.calls, [])
        self.assertNotIn("synthetic", json.dumps(r))

    def test_untrusted_unknown_transport_error_is_not_printed(self):
        def fail(url, headers):
            raise RuntimeError("private-account-secret://token")
        r = run(env=self.env, transport=fail)
        self.assertEqual(r["observation_status"], "NOT_CONNECTED")
        self.assertNotIn("private-account-secret", json.dumps(r))

    def test_private_balance_output_blocked_in_actions(self):
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}, clear=False):
            sink = io.StringIO()
            with redirect_stdout(sink):
                status = main(["--show-local-balances"])
        self.assertEqual(status, 2)
        self.assertIn("PRIVATE_BALANCES_BLOCKED_IN_GITHUB_ACTIONS", sink.getvalue())
        self.assertNotIn("61.07", sink.getvalue())

    def test_status_never_fabricates_real_account_provenance(self):
        r = summarize({"status": "READ_ONLY_CONNECTED_NOT_RECONCILED",
                       "mode": "CLASSIC", "checks": {"mode": "OK"}},
                      show_local_balances=True)
        self.assertEqual(r["observation_status"], "BALANCE_UNVERIFIED")
        self.assertEqual(r["available"], "REDACTED_OR_UNVERIFIED")
        self.assertFalse(r["authenticated_model_a_reconciled"])


if __name__ == "__main__":
    unittest.main()
