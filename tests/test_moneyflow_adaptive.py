"""Offline tests of isolated v2 components: no exchange calls or orders."""
import unittest
from daiinas.moneyflow import Execution, BestQuotes, OpenInterest, snapshot, minimum_taker_move_bps
from daiinas.adaptive import CapitalController


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.quote = BestQuotes(1000, 100, 100.02, 6, 4, 0.01)
        self.trades = [Execution(900, 100.0, 5, .01, 'buy', '1'),
                       Execution(950, 100.0, 3, .01, 'sell', '2')]

    def test_aggressor_flow_is_not_position_direction(self):
        f = snapshot(now_ms=1000, period_ms=200, trades=self.trades, quote=self.quote)
        self.assertAlmostEqual(f.traded_notional, 8)
        self.assertAlmostEqual(f.cvd_notional, 2)
        self.assertAlmostEqual(f.cvd_ratio, .25)
        self.assertAlmostEqual(f.best_quote_imbalance, .2)
        self.assertIsNone(f.open_interest_change_fraction)

    def test_oi_relative_change(self):
        f = snapshot(now_ms=1000, period_ms=200, trades=self.trades, quote=self.quote,
                     oi_before=OpenInterest(100, 100), oi_after=OpenInterest(980, 105))
        self.assertAlmostEqual(f.open_interest_change_fraction, .05)
        self.assertEqual(f.oi_measurement_lag_ms, 20)

    def test_stale_quote_is_not_a_signal(self):
        with self.assertRaisesRegex(ValueError, 'stale'):
            snapshot(now_ms=10000, period_ms=20000, trades=self.trades, quote=self.quote)

    def test_no_future_trade_in_signal(self):
        with self.assertRaisesRegex(ValueError, 'window'):
            snapshot(now_ms=1000, period_ms=200, trades=self.trades +
                     [Execution(1001, 100, 1, .01, 'buy', '3')], quote=self.quote)

    def test_duplicate_trade_is_not_counted_twice(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            snapshot(now_ms=1000, period_ms=200, trades=[self.trades[0]]*2, quote=self.quote)

    def test_contract_multiplier_is_mandatory(self):
        with self.assertRaisesRegex(ValueError, 'multiplier'):
            snapshot(now_ms=1000, period_ms=200,
                     trades=[Execution(900, 100, 1, 1, 'buy', '3')], quote=self.quote)

    def test_partial_oi_window_is_not_valid(self):
        with self.assertRaisesRegex(ValueError, 'both'):
            snapshot(now_ms=1000, period_ms=200, trades=self.trades,
                     quote=self.quote, oi_before=OpenInterest(100, 100))

    def test_taker_break_even_cost_before_profit(self):
        self.assertAlmostEqual(minimum_taker_move_bps(
            fee_entry=.0006, fee_exit=.0006, full_spread_bps=2,
            adverse_slippage_each_bps=2), 18)
        with self.assertRaises(ValueError):
            minimum_taker_move_bps(fee_entry=-1, fee_exit=0,
                                  full_spread_bps=0, adverse_slippage_each_bps=0)


class CapitalTests(unittest.TestCase):
    def args(self, **extra):
        kwargs = dict(fresh_market_data=True, strategy_validated=True,
                      executable_contract=True, market_regime='micro',
                      execution_costs_acceptable=True)
        kwargs.update(extra)
        return kwargs

    def test_no_edge_or_nonexecutable_order_is_standby(self):
        c = CapitalController(8)
        self.assertEqual(c.evaluate(equity=8, **self.args(strategy_validated=False)).mode,
                         'STANDBY')
        self.assertEqual(c.evaluate(equity=8, **self.args(executable_contract=False)).risk_budget_usdt,
                         0)

    def test_risk_budget_grows_with_equity_not_martingale(self):
        c = CapitalController(8)
        a = c.evaluate(equity=8, **self.args())
        self.assertEqual(a.mode, 'MICRO')
        self.assertAlmostEqual(a.risk_budget_usdt, .02)
        b = c.evaluate(equity=50, external_capital_flow=42,
                       **self.args(market_regime='trend'))
        self.assertEqual(b.mode, 'EXTENDED')
        self.assertAlmostEqual(b.risk_budget_usdt, .25)
        self.assertAlmostEqual(b.drawdown_fraction, 0)

    def test_drawdown_deescalates_and_latches(self):
        c = CapitalController(100)
        x = c.evaluate(equity=96, **self.args())
        self.assertAlmostEqual(x.risk_fraction, .005/2)
        y = c.evaluate(equity=93, **self.args())
        self.assertEqual(y.mode, 'HALTED')
        z = c.evaluate(equity=110, external_capital_flow=17, **self.args())
        self.assertEqual(z.mode, 'HALTED')
        c.review_reset()
        self.assertEqual(c.evaluate(equity=110, **self.args()).mode, 'MICRO')

    def test_unfavorable_regime_is_standby(self):
        c = CapitalController(100)
        self.assertEqual(c.evaluate(equity=100,
                         **self.args(market_regime='unfavorable')).mode, 'STANDBY')

    def test_external_withdrawal_is_not_a_loss(self):
        c = CapitalController(100)
        a = c.evaluate(equity=90, external_capital_flow=-10, **self.args())
        self.assertEqual(a.drawdown_fraction, 0)
        self.assertEqual(a.mode, 'MICRO')

    def test_bad_market_data_cannot_increase_risk(self):
        c = CapitalController(20)
        a = c.evaluate(equity=20, **self.args(fresh_market_data=False))
        self.assertEqual(a.risk_budget_usdt, 0)


if __name__ == '__main__':
    unittest.main()
