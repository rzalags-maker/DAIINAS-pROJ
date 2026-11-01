"""Model A counterfactual math, synthetic observations only; no funding."""
import json
import io
import contextlib
import unittest

from daiinas.capital_ladder import CapitalLadder
from daiinas.bitsgap_account_state import AccountStateError, BLOCKED, main
import test_bitsgap_account_state as account_fixture


class CapitalPreviewTests(unittest.TestCase):
    def setUp(self):
        # Reuse the synthetic authenticated-wire fixture, without inheriting
        # its tests or copying any account-state implementation.
        self.fixture = account_fixture.AccountStateTests(methodName="test_rest_ws_null_remains_no_data_not_zero")
        self.fixture.setUp()
        self.fixture.connect()
        self.state = self.fixture.state

    def wallet(self, total):
        self.fixture.now += 1
        self.fixture.pair("balance", {"data":{"USDT":{"t":total,"a":total}}})

    def test_initial_200_and_300_use_original_model_a_not_model_b(self):
        for total, reserve, active, slots in (("200","50","150",6), ("300","50","250",10),
                                              ("450","150","300",10)):
            self.wallet(total)
            result = self.state.capital_admission_preview(initial_scenario=True)
            projection = result.private_status()["model_a_projection"]
            self.assertEqual((projection["reserve"],projection["active"],projection["nominal_slot_ceiling"]),
                             (reserve,active,slots))
            self.assertFalse(result.safe_status()["funding_authorized"])
            self.assertEqual(result.safe_status()["funded_slots"], "BLOCKED")

    def test_existing_activated_history_not_reset_when_balance_falls_below_100(self):
        ladder = CapitalLadder("100")
        ladder.realized_result("-0.01")
        before = ladder.export_state()
        self.wallet("99.99")
        result = self.state.capital_admission_preview(existing_ladder=ladder)
        projection = result.private_status()["model_a_projection"]
        self.assertEqual(projection["reserve"], "50")
        self.assertEqual(projection["active"], "49.99")
        self.assertNotEqual(projection["stage"], "BOOTSTRAP")
        self.assertEqual(ladder.export_state(), before)

    def test_current_wallet_does_not_synthesize_profit_or_deposit_into_existing_ladder(self):
        ladder = CapitalLadder("200")
        before = ladder.export_state()
        self.wallet("450")
        result = self.state.capital_admission_preview(existing_ladder=before)
        self.assertEqual(result.private_status()["model_a_projection"]["total"], "200")
        self.assertIn("WALLET_TO_LEDGER_RECONCILIATION_UNVERIFIED", result.blockers)
        self.assertEqual(ladder.export_state(), before)

    def test_drawdown_slot_latch_and_policy_preserved_on_detached_copy(self):
        ladder = CapitalLadder("300")
        ladder.realized_result("-40")
        before = ladder.export_state()
        result = self.state.capital_admission_preview(existing_ladder=ladder)
        projection = result.private_status()["model_a_projection"]
        self.assertEqual(projection["nominal_slot_ceiling"],8)
        self.assertEqual(projection["policy"],ladder.snapshot()["policy"])
        self.assertEqual(ladder.export_state(),before)

    def test_default_never_guesses_a_starting_capital(self):
        result = self.state.capital_admission_preview()
        self.assertIsNone(result.private_status()["model_a_projection"])
        self.assertEqual(result.safe_status()["decision"], BLOCKED)

    def test_stale_wallet_cannot_make_initial_projection(self):
        self.wallet("200")
        self.fixture.now += 16000
        result = self.state.capital_admission_preview(initial_scenario=True)
        self.assertIsNone(result.private_status()["model_a_projection"])
        self.assertIn("CURRENT_REPORTED_TOTAL_UNVERIFIED",result.blockers)

    def test_null_exposure_keeps_projection_non_admissible(self):
        self.wallet("200")
        self.fixture.pair("orders",None)
        self.fixture.pair("positions",None)
        result = self.state.capital_admission_preview(initial_scenario=True)
        self.assertTrue(result.safe_status()["projection_available"])
        self.assertIn("EXPOSURE_UNVERIFIED",result.blockers)
        self.assertIn("FREE_MARGIN_UNVERIFIED",result.blockers)
        self.assertFalse(self.state.model_a_input()["funding_authorized"])

    def test_hypothetical_initial_must_not_compete_with_existing_history(self):
        with self.assertRaises(AccountStateError):
            self.state.capital_admission_preview(existing_ladder=CapitalLadder("200"),initial_scenario=True)

    def test_invalid_existing_state_rejected_without_echoing_it(self):
        with self.assertRaisesRegex(AccountStateError,"^INVALID_EXISTING_LADDER_PREVIEW$"):
            self.state.capital_admission_preview(existing_ladder="PRIVATE_INVALID_CONTENT")

    def test_safe_status_and_repr_never_emit_projection_amounts(self):
        self.wallet("913.2468")
        result = self.state.capital_admission_preview(initial_scenario=True)
        safe = json.dumps(result.safe_status()) + repr(result)
        self.assertNotIn("913.2468",safe)
        self.assertNotIn("model_a_projection",safe)

    def test_private_projection_is_detached_from_ladder_and_returned_values(self):
        ladder = CapitalLadder("200")
        result = self.state.capital_admission_preview(existing_ladder=ladder)
        private = result.private_status()
        private["model_a_projection"]["active"] = "0"
        self.assertEqual(result.private_status()["model_a_projection"]["active"],"150")
        self.assertEqual(ladder.snapshot()["active"],"150")

    def test_cli_initial_scenario_requires_explicit_preview_selection(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["--scope-ref","synthetic", "--hypothetical-initial"])
        self.assertEqual(code,2)
        self.assertIn("EXPLICIT_CAPITAL_PREVIEW_REQUIRED",output.getvalue())


if __name__ == "__main__":
    unittest.main()
