"""Venue-agnostic, decision-time-only trade-flow features.

Research observations are NOT buy/sell recommendations. KuCoin contract counts
must be converted with the exchange's validated contract multiplier.
"""
from dataclasses import dataclass
import math


def positive(value, name):
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f'{name} must be positive and finite')


def nonnegative(value, name):
    if not math.isfinite(value) or value < 0:
        raise ValueError(f'{name} must be nonnegative and finite')


@dataclass(frozen=True)
class Execution:
    time_ms: int
    price: float
    contracts: float
    contract_multiplier: float
    aggressor_side: str  # buy/sell is taker side, NOT net position direction
    trade_id: str

    def __post_init__(self):
        if self.time_ms < 0 or not self.trade_id:
            raise ValueError('Execution requires timestamp and unique provider trade ID')
        for n in ('price', 'contracts', 'contract_multiplier'):
            positive(getattr(self, n), n)
        if self.aggressor_side not in ('buy', 'sell'):
            raise ValueError('Aggressor side must be buy or sell')

    @property
    def notional(self):
        return self.price * self.contracts * self.contract_multiplier


@dataclass(frozen=True)
class BestQuotes:
    time_ms: int
    bid_price: float
    ask_price: float
    bid_contracts: float
    ask_contracts: float
    contract_multiplier: float

    def __post_init__(self):
        if self.time_ms < 0:
            raise ValueError('Negative quote timestamp')
        for n in ('bid_price', 'ask_price', 'contract_multiplier'):
            positive(getattr(self, n), n)
        if self.bid_price >= self.ask_price:
            raise ValueError('Crossed or locked market')
        for n in ('bid_contracts', 'ask_contracts'):
            nonnegative(getattr(self, n), n)

    @property
    def spread_bps(self):
        return 10_000 * (self.ask_price - self.bid_price) / ((self.ask_price + self.bid_price) / 2)

    @property
    def top_imbalance(self):
        """Best-level displayed imbalance, NOT full-book executable liquidity."""
        total = self.bid_contracts + self.ask_contracts
        return (self.bid_contracts - self.ask_contracts) / total if total else 0.0


@dataclass(frozen=True)
class OpenInterest:
    time_ms: int
    contracts: float

    def __post_init__(self):
        if self.time_ms < 0:
            raise ValueError('Negative OI timestamp')
        positive(self.contracts, 'open interest')


@dataclass(frozen=True)
class FlowFeatures:
    decision_time_ms: int
    period_ms: int
    traded_notional: float
    aggressive_buy_notional: float
    aggressive_sell_notional: float
    cvd_notional: float
    cvd_ratio: float
    spread_bps: float
    best_quote_imbalance: float
    open_interest_change_fraction: float | None
    oi_measurement_lag_ms: int | None


def snapshot(*, now_ms: int, period_ms: int, trades: list[Execution],
             quote: BestQuotes, oi_before: OpenInterest | None = None,
             oi_after: OpenInterest | None = None,
             max_quote_age_ms: int = 5_000, max_oi_age_ms: int = 900_000) -> FlowFeatures:
    """Completed-as-of-time features. Caller MUST prove stream completeness.

    Detect duplicate trade IDs, bad chronology, stale quote/OI and multiplier
    mismatches. Missing network messages cannot be detected here without
    the upstream adapter's sequence and connection-state evidence.
    """
    if now_ms < 0 or period_ms <= 0 or max_quote_age_ms <= 0 or max_oi_age_ms <= 0:
        raise ValueError('Invalid time parameters')
    if not 0 <= now_ms - quote.time_ms <= max_quote_age_ms:
        raise ValueError('Quote is stale or from the future')
    if not trades:
        raise ValueError('No verified trades in window')
    seen = set()
    buy = sell = 0.0
    last = None
    for trade in trades:
        if not now_ms - period_ms < trade.time_ms <= now_ms:
            raise ValueError('Trade outside decision window or from future')
        if last is not None and trade.time_ms < last:
            raise ValueError('Trade timestamps not chronological')
        if trade.trade_id in seen:
            raise ValueError('Duplicate trade ID')
        if not math.isclose(trade.contract_multiplier, quote.contract_multiplier, rel_tol=1e-12):
            raise ValueError('Contract multiplier mismatch')
        last = trade.time_ms
        seen.add(trade.trade_id)
        if trade.aggressor_side == 'buy':
            buy += trade.notional
        else:
            sell += trade.notional
    total = buy + sell
    oi_change = lag = None
    if (oi_before is None) != (oi_after is None):
        raise ValueError('OI must provide both before and after snapshots')
    if oi_before is not None:
        if not 0 <= oi_before.time_ms < oi_after.time_ms <= now_ms:
            raise ValueError('Invalid OI chronology')
        lag = now_ms - oi_after.time_ms
        if lag > max_oi_age_ms:
            raise ValueError('OI stale')
        oi_change = (oi_after.contracts - oi_before.contracts) / oi_before.contracts
    return FlowFeatures(now_ms, period_ms, total, buy, sell, buy-sell,
                        (buy-sell)/total, quote.spread_bps, quote.top_imbalance,
                        oi_change, lag)


def minimum_taker_move_bps(*, fee_entry: float, fee_exit: float,
                            full_spread_bps: float, adverse_slippage_each_bps: float) -> float:
    """Approximate mid-to-mid break-even bps, not an expected-profit forecast."""
    for k, v in {'fee_entry': fee_entry, 'fee_exit': fee_exit,
                 'full_spread_bps': full_spread_bps,
                 'adverse_slippage_each_bps': adverse_slippage_each_bps}.items():
        nonnegative(v, k)
    if fee_entry >= 1 or fee_exit >= 1:
        raise ValueError('Invalid fee')
    return (fee_entry + fee_exit)*10_000 + full_spread_bps + 2*adverse_slippage_each_bps
