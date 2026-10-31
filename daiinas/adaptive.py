"""Research-only adaptive capital risk gate. Does NOT place orders or alter v1 defaults.

This module's in-memory state MUST be persisted into the service's atomic
SQLite checkpoint before it is used by a continuously running paper worker.
"""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class CapitalDecision:
    mode: str  # HALTED, STANDBY, MICRO, EXTENDED
    equity: float
    adjusted_peak: float
    drawdown_fraction: float
    risk_fraction: float
    risk_budget_usdt: float
    reason: str


class CapitalController:
    """Deposit-adjusted high-water mark with latched stop, not profit guarantee.

    equity and external_capital_flow must be obtained from a trusted ledger.
    Deposits are not trading profit, and cannot automatically release a halt.
    """
    def __init__(self, initial_equity: float):
        self._positive(initial_equity, 'initial_equity')
        self.peak = initial_equity
        self.halted = False
        self.last_equity = initial_equity

    @staticmethod
    def _positive(value, name):
        if not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'{name} must be positive finite')

    def review_reset(self):
        """Requires an explicit authorized operator review."""
        self.halted = False

    def evaluate(self, *, equity: float, external_capital_flow: float = 0.0,
                 fresh_market_data: bool, strategy_validated: bool,
                 executable_contract: bool, market_regime: str,
                 execution_costs_acceptable: bool) -> CapitalDecision:
        self._positive(equity, 'equity')
        if not math.isfinite(external_capital_flow):
            raise ValueError('Invalid external capital flow')
        if market_regime not in ('micro', 'trend', 'unfavorable'):
            raise ValueError('Unknown regime')
        self.peak = max(1e-9, self.peak + external_capital_flow, equity)
        self.last_equity = equity
        drawdown = max(0.0, (self.peak - equity)/self.peak)
        if drawdown >= 0.06:
            self.halted = True
        if self.halted:
            return CapitalDecision('HALTED', equity, self.peak, drawdown, 0, 0,
                                   'Latched drawdown stop; manual review required')
        if not fresh_market_data:
            return CapitalDecision('STANDBY', equity, self.peak, drawdown, 0, 0,
                                   'Stale or unverified market data')
        if not strategy_validated:
            return CapitalDecision('STANDBY', equity, self.peak, drawdown, 0, 0,
                                   'No demonstrated net trading edge')
        if not executable_contract:
            return CapitalDecision('STANDBY', equity, self.peak, drawdown, 0, 0,
                                   'Minimum contract or risk limit infeasible')
        if not execution_costs_acceptable:
            return CapitalDecision('STANDBY', equity, self.peak, drawdown, 0, 0,
                                   'Trading costs exceed budget')
        if market_regime == 'unfavorable':
            return CapitalDecision('STANDBY', equity, self.peak, drawdown, 0, 0,
                                   'Unfavorable market regime')
        # Illustrative starting ceilings: must be independently validated.
        base = (0.0025 if equity < 20 else 0.0035 if equity < 50
                else 0.005 if equity < 100 else 0.0075)
        multiplier = 0.5 if drawdown >= 0.03 else 1.0
        mode = 'EXTENDED' if equity >= 50 and market_regime == 'trend' else 'MICRO'
        return CapitalDecision(mode, equity, self.peak, drawdown,
                               base*multiplier, equity*base*multiplier,
                               'Maximum risk budget only; lot/margin gate still applies')
