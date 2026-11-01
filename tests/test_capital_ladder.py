"""Deterministic DAIINAS v4 allocation tests. Not trading-alpha validation."""
import unittest
from decimal import Decimal
from daiinas.capital_ladder import CapitalLadder


class LadderTest(unittest.TestCase):
    def test_original_8_usdt_bootstrap_one_candidate_slot(self):
        a = CapitalLadder('8')
        self.assertEqual((a.stage, a.slot_ceiling, a.active, a.reserve),
                         ('BOOTSTRAP', 1, Decimal(8), Decimal(0)))
        self.assertEqual(a.new_position_risk_budget('0', 0), Decimal('0.02'))
        a.realized_result('-8')
        self.assertEqual((a.slot_ceiling, a.reserve), (0, Decimal(0)))

    def test_bootstrap_to_activation(self):
        a = CapitalLadder('60')
        self.assertEqual((a.stage, a.slot_ceiling, a.active, a.reserve),
                         ('BOOTSTRAP', 1, Decimal(60), Decimal(0)))
        a.realized_result('39')
        self.assertEqual((a.stage, a.slot_ceiling), ('BOOTSTRAP', 1))
        a.realized_result('1')
        self.assertEqual((a.stage, a.active, a.reserve, a.slot_ceiling),
                         ('EXPAND', Decimal(50), Decimal(50), 2))
        self.assertEqual(a.total, Decimal(100))

    def test_ten_rungs_and_reserve_first(self):
        a = CapitalLadder('100')
        for slots in range(3, 11):
            a.realized_result('25')
            self.assertEqual(a.slot_ceiling, slots)
            self.assertEqual(a.reserve, Decimal(50))
            self.assertEqual(a.active, Decimal(slots * 25))
        self.assertEqual((a.stage, a.total, a.next_step),
                         ('SCALE', Decimal(300), 'RESERVE'))
        a.realized_result('49')
        self.assertEqual((a.reserve, a.active, a.pending),
                         (Decimal(50), Decimal(250), Decimal(49)))
        a.realized_result('1')
        self.assertEqual((a.reserve, a.active, a.pending, a.next_step),
                         (Decimal(100), Decimal(250), Decimal(0), 'ACTIVE'))
        a.realized_result('50')
        self.assertEqual((a.reserve, a.active, a.total, a.next_step),
                         (Decimal(100), Decimal(300), Decimal(400), 'RESERVE'))
        self.assertEqual(a.slot_ceiling, 10)

    def test_backward_ladder_never_sells_reserve(self):
        a = CapitalLadder('300')
        self.assertEqual((a.reserve, a.active, a.slot_ceiling),
                         (Decimal(50), Decimal(250), 10))
        a.realized_result('-40')
        self.assertEqual((a.reserve, a.active, a.slot_ceiling),
                         (Decimal(50), Decimal(210), 8))
        a.realized_result('14')
        self.assertEqual((a.reserve, a.active, a.slot_ceiling),
                         (Decimal(50), Decimal(224), 8))
        a.realized_result('1')
        self.assertEqual(a.slot_ceiling, 9)
        a.realized_result('25')
        self.assertEqual((a.active, a.slot_ceiling, a.total),
                         (Decimal(250), 10, Decimal(300)))

    def test_scale_loss_recovered_before_next_reserve_step(self):
        a = CapitalLadder('300')
        a.realized_result('30')
        a.realized_result('-20')
        self.assertEqual((a.reserve, a.pending, a.active, a.slot_ceiling),
                         (Decimal(50), Decimal(30), Decimal(230), 9))
        a.realized_result('20')
        self.assertEqual((a.reserve, a.pending, a.active, a.slot_ceiling),
                         (Decimal(50), Decimal(30), Decimal(250), 10))
        a.realized_result('20')
        self.assertEqual((a.reserve, a.pending, a.active),
                         (Decimal(100), Decimal(0), Decimal(250)))

    def test_mark_loss_latches_slots_until_realized_profit(self):
        a = CapitalLadder('300')
        status = a.mark_to_market('-1', open_positions=10)
        self.assertEqual((status['allowed_slots'],
                          status['excess_open_to_reduce_safely']), (9, 1))
        self.assertEqual(a.mark_to_market('3', open_positions=9)['allowed_slots'], 9)
        a.realized_result('1')
        self.assertEqual(a.slot_ceiling, 10)

    def test_no_force_close_and_unaffordable_account_stop(self):
        a = CapitalLadder('100')
        a.realized_result('-49')
        self.assertEqual((a.reserve, a.active, a.slot_ceiling),
                         (Decimal(50), Decimal(1), 0))
        s = a.mark_to_market('0', open_positions=1)
        self.assertTrue(s['manual_safe_exit_required'])
        self.assertEqual(s['excess_open_to_reduce_safely'], 1)
        self.assertEqual(a.new_position_risk_budget('0', 1), 0)

    def test_deficit_visible_not_silent_transfer(self):
        a = CapitalLadder('100')
        a.realized_result('-60')
        self.assertEqual((a.reserve, a.active, a.deficit, a.total, a.slot_ceiling),
                         (Decimal(50), Decimal(0), Decimal(10), Decimal(40), 0))
        a.realized_result('20')
        self.assertEqual((a.deficit, a.active, a.reserve),
                         (Decimal(0), Decimal(10), Decimal(50)))

    def test_risk_budget_aggregate_and_remainder(self):
        a = CapitalLadder('300')
        self.assertEqual(a.new_position_risk_budget('0', 0), Decimal('0.25'))
        self.assertEqual(a.new_position_risk_budget('2.25', 9), Decimal('0.25'))
        self.assertEqual(a.new_position_risk_budget('2.5', 9), Decimal(0))

    def test_invalid_money_never_mutates_account(self):
        a = CapitalLadder('60')
        for value in ['NaN', 'Infinity', 1.5, None, True]:
            with self.assertRaises(ValueError):
                a.realized_result(value)
        self.assertEqual(a.total, Decimal(60))

    def test_unrealized_rebound_without_realization_does_not_promote(self):
        a = CapitalLadder('150')
        self.assertEqual(a.slot_ceiling, 4)
        self.assertEqual(a.mark_to_market('-1', open_positions=4)['allowed_slots'], 3)
        self.assertEqual(a.mark_to_market('20', open_positions=3)['allowed_slots'], 3)
        self.assertEqual(a.realized_result('0')['slot_ceiling'], 3)
        a.realized_result('0.1')
        self.assertEqual(a.slot_ceiling, 4)

    def test_pending_profit_frozen_when_active_draws_down(self):
        a = CapitalLadder('300')
        a.realized_result('49.99')
        self.assertEqual(a.pending, Decimal('49.99'))
        a.realized_result('-26')
        self.assertEqual((a.active, a.reserve, a.pending, a.slot_ceiling),
                         (Decimal(224), Decimal(50), Decimal('49.99'), 8))
        a.realized_result('26')
        self.assertEqual((a.active, a.reserve, a.pending, a.slot_ceiling),
                         (Decimal(250), Decimal(50), Decimal('49.99'), 10))
        a.realized_result('0.01')
        self.assertEqual((a.active, a.reserve, a.pending),
                         (Decimal(250), Decimal(100), Decimal(0)))

    def test_large_profit_crosses_multiple_scaling_steps(self):
        a = CapitalLadder('100')
        a.realized_result('450.25')
        self.assertEqual((a.reserve, a.active, a.pending, a.total, a.slot_ceiling),
                         (Decimal(200), Decimal(350), Decimal('0.25'), Decimal('550.25'), 10))

    def test_restart_parity(self):
        a = CapitalLadder('100')
        for pnl in ('25', '25', '-2', '2', '130', '49', '1', '-15', '15', '50'):
            a.realized_result(pnl)
        a.mark_to_market('-1', open_positions=2)
        b = CapitalLadder.restore(a.export_state())
        self.assertEqual(a.snapshot(), b.snapshot())
        for pnl in ('-6', '6', '50', '50'):
            self.assertEqual(a.realized_result(pnl), b.realized_result(pnl))

    def test_activation_100_and_300_direct_capital(self):
        for initial, reserve, active, slots in [
            ('100', '50', '50', 2), ('300', '50', '250', 10),
            ('350', '100', '250', 10), ('400', '100', '300', 10),
        ]:
            a = CapitalLadder(initial)
            self.assertEqual((a.reserve, a.active, a.slot_ceiling),
                             (Decimal(reserve), Decimal(active), slots))
            self.assertEqual(a.total, Decimal(initial))


if __name__ == '__main__':
    unittest.main()
