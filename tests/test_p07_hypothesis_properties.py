"""P07 generated safety properties; development-only, no provider access."""
from decimal import Decimal
import unittest

from hypothesis import given, settings, strategies as st

from daiinas.capital_ladder import CapitalLadder, dec
from daiinas.execution_boundary import InertOrderGateway, owned_order_ids


money = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("1000"),
                    places=2, allow_nan=False, allow_infinity=False)
pnl = st.decimals(min_value=Decimal("-1000"), max_value=Decimal("1000"),
                  places=2, allow_nan=False, allow_infinity=False)


class P07GeneratedSafetyTests(unittest.TestCase):
    @settings(max_examples=80, deadline=None)
    @given(start=money, results=st.lists(pnl, max_size=24))
    def test_capital_ladder_replay_preserves_reserve_and_snapshot(self, start, results):
        ladder = CapitalLadder(str(start))
        for result in results:
            ladder.realized_result(str(result))
            state = ladder.snapshot()
            self.assertGreaterEqual(dec(state["reserve"]), Decimal(0))
            self.assertGreaterEqual(dec(state["active"]), Decimal(0))
            self.assertLessEqual(state["slot_ceiling"], 10)
            self.assertEqual(CapitalLadder.restore(ladder.export_state()).snapshot(), state)

    @settings(max_examples=60, deadline=None)
    @given(quantity=money, stop=money, target=money,
           leverage=st.integers(min_value=1, max_value=5),
           side=st.sampled_from(("LONG", "SHORT")))
    def test_preview_is_deterministic_and_never_authorizes_orders(
            self, quantity, stop, target, leverage, side):
        gateway = InertOrderGateway()
        args = dict(account_id="PAPER", client_oid="p07", symbol="BTCUSDTM",
                    side=side, quantity=str(quantity), leverage=leverage,
                    order_type="MARKET_IOC", stop_price=str(stop),
                    target_price=str(target))
        first = gateway.preview(**args)
        self.assertEqual(first, gateway.preview(**args))
        self.assertFalse(first["orders_enabled"])
        self.assertEqual(first["status"], "PAPER_PREVIEW_ONLY")
        with self.assertRaises(PermissionError):
            gateway.place_order()

    @settings(max_examples=80, deadline=None)
    @given(position_id=st.text(min_size=1, max_size=64))
    def test_owned_order_ids_are_stable_and_do_not_create_orders(self, position_id):
        ids = owned_order_ids(position_id)
        self.assertEqual(ids, owned_order_ids(position_id))
        self.assertEqual(set(ids), {"entry", "stop", "target"})
        self.assertEqual(len(set(ids.values())), 3)
        self.assertTrue(all(value.startswith("MOCK-") for value in ids.values()))
