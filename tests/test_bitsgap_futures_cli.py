"""Futures CLI diagnostics: never disclose keys, balances or remote error text."""
import contextlib
import io
import json
import os
import unittest
from unittest.mock import patch

from daiinas import bitsgap_futures_cli as cli
from daiinas.bitsgap_readonly import BitsgapError


class FuturesCliDiagnosticsTests(unittest.TestCase):
    def test_missing_key_reports_specific_safe_configuration_blocker(self):
        sink = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stdout(sink):
            status = cli.main([])
        self.assertEqual(status, 2)
        result = json.loads(sink.getvalue())
        self.assertEqual(result["reason"], "CREDENTIAL_NOT_CONFIGURED_OR_INVALID")
        self.assertFalse(result["capital_reconciled"])
        self.assertFalse(result["orders_enabled"])

    def test_github_actions_private_panel_refused_even_with_key(self):
        sink = io.StringIO()
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}, clear=True):
            with contextlib.redirect_stdout(sink):
                status = cli.main(["--private-panel"])
        self.assertEqual(status, 2)
        self.assertEqual(json.loads(sink.getvalue())["status"], "PRIVATE_OUTPUT_DISALLOWED")

    def test_private_remote_error_values_never_reflected_in_cli_diagnostics(self):
        sink = io.StringIO()
        with patch.object(cli, "BitsgapFuturesObserver",
                          side_effect=BitsgapError("SECRET_SESSION_VALUE_NOT_TO_PRINT")):
            with contextlib.redirect_stdout(sink):
                status = cli.main([])
        self.assertEqual(status, 2)
        self.assertNotIn("SECRET_SESSION_VALUE", sink.getvalue())
        self.assertEqual(json.loads(sink.getvalue())["reason"], "SCHEMA_OR_RESPONSE_UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
