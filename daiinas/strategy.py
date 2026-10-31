"""OHLCV price-pattern proxy, NOT order-book or trade-flow evidence."""
from .models import Candle, Signal, StrategyConfig


def signal(candles: list[Candle], i: int, config: StrategyConfig) -> Signal | None:
    """Called on completed candle i. Only reads indices <= i."""
    if i < max(config.lookback, config.atr_period + 1):
        return None
    bar = candles[i]
    prior = candles[i - config.lookback:i]
    high, low = max(c.high for c in prior), min(c.low for c in prior)
    # Prior ATR excludes the sweep candle so the threshold cannot inflate with it.
    atr = sum(max(candles[j].high - candles[j].low,
                  abs(candles[j].high - candles[j-1].close),
                  abs(candles[j].low - candles[j-1].close))
              for j in range(i-config.atr_period, i)) / config.atr_period
    if not config.min_atr_fraction <= atr / bar.close <= config.max_atr_fraction:
        return None
    long = bar.low < low - config.sweep_atr * atr and low < bar.close < high
    short = bar.high > high + config.sweep_atr * atr and low < bar.close < high
    if long and short:  # intrabar ordering unknowable
        return None
    if long and (not config.require_reversal_body or bar.close > bar.open):
        return Signal('LONG', bar.low-config.stop_atr*atr, low, atr)
    if short and (not config.require_reversal_body or bar.close < bar.open):
        return Signal('SHORT', bar.high+config.stop_atr*atr, high, atr)
    return None


def invalidated(position, close: float, config: StrategyConfig) -> bool:
    buffer = config.invalidate_atr * position.atr
    return (close < position.boundary-buffer if position.side == 'LONG'
            else close > position.boundary+buffer)
