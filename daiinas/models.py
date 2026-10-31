from dataclasses import dataclass, asdict
import math

SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT')
INTERVALS = {'1m': 60_000, '5m': 300_000, '15m': 900_000}


@dataclass(frozen=True)
class Candle:
    time: int  # UTC open time in milliseconds; decisions occur after close
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self):
        if self.time < 0 or not all(math.isfinite(v) for v in
                                    (self.open, self.high, self.low, self.close, self.volume)):
            raise ValueError('Non-finite candle or negative timestamp')
        if not (0 < self.low <= min(self.open, self.close) <=
                max(self.open, self.close) <= self.high) or self.volume < 0:
            raise ValueError('Invalid OHLCV candle')


@dataclass(frozen=True)
class StrategyConfig:
    lookback: int = 20
    atr_period: int = 14
    min_atr_fraction: float = 0.0005
    max_atr_fraction: float = 0.03
    sweep_atr: float = 0.05
    stop_atr: float = 0.25
    reward_risk: float = 1.5
    require_reversal_body: bool = True
    invalidate_atr: float = 0.0

    def __post_init__(self):
        if self.lookback < 2 or self.atr_period < 2:
            raise ValueError('Lookback and ATR period must be >= 2')
        if not all(math.isfinite(x) for x in (self.min_atr_fraction, self.max_atr_fraction,
                self.sweep_atr, self.stop_atr, self.reward_risk, self.invalidate_atr)):
            raise ValueError('Strategy values must be finite')
        if not 0 <= self.min_atr_fraction <= self.max_atr_fraction or min(
                self.sweep_atr, self.stop_atr, self.invalidate_atr) < 0 or self.reward_risk <= 0:
            raise ValueError('Invalid strategy parameters')


@dataclass(frozen=True)
class RiskConfig:
    initial_capital: float = 8.0
    risk_fraction: float = 0.01
    leverage: float = 3.0
    max_leverage: float = 5.0
    max_margin_fraction: float = 0.8
    max_drawdown: float = 0.20
    fee_rate: float = 0.0005  # taker on each side
    spread_bps: float = 2.0  # full bid/ask spread
    slippage_bps: float = 2.0  # each fill
    funding_8h_rate: float = 0.0001  # conservative charge to BOTH sides

    def __post_init__(self):
        if not all(math.isfinite(v) for v in asdict(self).values()):
            raise ValueError('Risk values must be finite')
        if self.initial_capital <= 0 or not 0 < self.risk_fraction <= 0.1:
            raise ValueError('Capital must be positive; risk fraction in (0, .1]')
        if not 1 <= self.leverage <= self.max_leverage <= 20:
            raise ValueError('Leverage must satisfy 1 <= leverage <= maximum <= 20')
        if not 0 < self.max_margin_fraction <= 0.9 or not 0 < self.max_drawdown < 1:
            raise ValueError('Invalid margin/drawdown limit')
        if min(self.fee_rate, self.spread_bps, self.slippage_bps, self.funding_8h_rate) < 0:
            raise ValueError('Costs cannot be negative')
        if max(self.fee_rate, self.funding_8h_rate) >= 1 or self.spread_bps/2+self.slippage_bps >= 10_000:
            raise ValueError('Costs must preserve positive fill prices and fractional rates')


@dataclass(frozen=True)
class Signal:
    side: str
    stop: float
    range_boundary: float
    atr: float


@dataclass
class Position:
    symbol: str
    side: str
    entry_time: int
    entry: float
    quantity: float
    stop: float
    target: float
    boundary: float
    atr: float
    margin: float
    entry_fee: float
    funding: float = 0.0
