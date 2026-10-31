"""Shared-equity bar simulator; keyed LONG/SHORT legs; no live execution."""
from dataclasses import asdict
from .models import Candle, Position, RiskConfig, StrategyConfig
from .risk import ContractRules, fill, size
from .strategy import signal, invalidated


def run(data: dict[str, list[Candle]], rules: dict[str, ContractRules],
        strategy=StrategyConfig(), risk=RiskConfig(), start=0, end=None) -> dict:
    symbols = sorted(data)  # deterministic shared-capital tie breaker
    if not symbols or not all(s in rules for s in symbols):
        raise ValueError('Missing data or rules')
    n = len(data[symbols[0]])
    times = [b.time for b in data[symbols[0]]]
    if any([b.time for b in data[s]] != times for s in symbols):
        raise ValueError('Portfolio candles must be synchronized')
    end = n if end is None else end
    if not 0 <= start < end <= n or n < 2:
        raise ValueError('Invalid backtest range')
    interval = times[1]-times[0]
    if interval <= 0 or any(b-a != interval for a,b in zip(times,times[1:])):
        raise ValueError('Candles must have a uniform positive interval')
    cash = risk.initial_capital
    peak = cash
    max_dd = 0.0
    halted = False
    positions: dict[tuple[str, str], Position] = {}
    pending = {}
    invalid_exits = set()
    trades, curve = [], []
    rejections = {'minimum_or_risk_budget': 0, 'gap_invalid_stop': 0, 'existing_leg': 0, 'invalid_target': 0}
    count_signals = 0

    def unreal(prices):
        return sum((prices[p.symbol]-p.entry)*(1 if p.side == 'LONG' else -1)*p.quantity*
                   float(rules[p.symbol].contract_size) for p in positions.values())

    def equity(prices):
        # Estimated cost to liquidate makes drawdown net of exit costs.
        return cash + unreal(prices) - sum(
            (abs(fill(prices[p.symbol], p.side == 'SHORT', risk)-prices[p.symbol])
             + fill(prices[p.symbol], p.side == 'SHORT', risk)*risk.fee_rate)*p.quantity*
            float(rules[p.symbol].contract_size) for p in positions.values())

    def close(key, raw_price, t, reason):
        nonlocal cash
        p = positions.pop(key)
        exit_price = fill(raw_price, p.side == 'SHORT', risk)
        unit = float(rules[p.symbol].contract_size)
        gross = (exit_price-p.entry)*(1 if p.side == 'LONG' else -1)*p.quantity*unit
        exit_fee = exit_price*p.quantity*unit*risk.fee_rate
        cash += gross-exit_fee
        net = gross-p.entry_fee-exit_fee-p.funding
        trades.append({**asdict(p), 'exit_time': t, 'exit': exit_price,
                       'exit_fee': exit_fee, 'gross_pnl': gross, 'net_pnl': net,
                       'reason': reason})
        invalid_exits.discard(key)

    for i in range(start, end):
        bars = {s: data[s][i] for s in symbols}
        opens = {s: b.open for s,b in bars.items()}
        # Positions carried over the funding boundary pay before open exits.
        t = times[i]
        if t % (8*3_600_000) == 0:
            for p in positions.values():
                charge = opens[p.symbol]*p.quantity*float(rules[p.symbol].contract_size)*risk.funding_8h_rate
                cash -= charge
                p.funding += charge
        # Process carried positions' opening gaps BEFORE invalidations and new orders.
        for key, p in list(positions.items()):
            price = opens[p.symbol]
            if (p.side == 'LONG' and price <= p.stop) or (p.side == 'SHORT' and price >= p.stop):
                close(key, price, t, 'stop_gap')
            elif (p.side == 'LONG' and price >= p.target) or (p.side == 'SHORT' and price <= p.target):
                close(key, p.target, t, 'take_profit')  # no favorable gap improvement
        for key in list(invalid_exits):
            if key in positions:
                close(key, opens[key[0]], t, 'signal_invalidation')
        open_equity = equity(opens)
        peak = max(peak, open_equity)
        open_dd = (peak-open_equity)/peak
        max_dd = max(max_dd, open_dd)
        if open_dd >= risk.max_drawdown:
            halted = True
        if halted:
            for key in list(positions):
                close(key, opens[key[0]], t, 'drawdown_halt')
        else:
            for s, sig in sorted(pending.items()):
                key = (s, sig.side)
                if key in positions:
                    rejections['existing_leg'] += 1
                    continue
                entry = fill(opens[s], sig.side == 'LONG', risk)
                rule = rules[s]
                stop = rule.price(sig.stop, up=sig.side == 'SHORT')
                distance = (entry-stop)*(1 if sig.side == 'LONG' else -1)
                # Reject gaps through stop or prices no longer inside prior range boundary.
                if distance <= 0 or (sig.side == 'LONG' and opens[s] <= sig.range_boundary) or (
                        sig.side == 'SHORT' and opens[s] >= sig.range_boundary):
                    rejections['gap_invalid_stop'] += 1
                    continue
                eq = equity(opens)
                used = sum(p.margin for p in positions.values())
                free = max(0, eq*risk.max_margin_fraction-used)
                q = size(eq, free, entry, stop, rule, risk)
                if q <= 0:
                    rejections['minimum_or_risk_budget'] += 1
                    continue
                target = rule.price(entry+(1 if sig.side == 'LONG' else -1)*distance*strategy.reward_risk,
                                    up=sig.side == 'SHORT')
                if target <= 0:
                    rejections['invalid_target'] += 1
                    continue
                unit = float(rule.contract_size)
                fee = entry*q*unit*risk.fee_rate
                cash -= fee
                positions[key] = Position(s, sig.side, t, entry, q, stop, target,
                                          sig.range_boundary, sig.atr,
                                          entry*q*unit/risk.leverage, fee)
        pending = {}
        # No tick ordering: stop always wins if both barriers touched.
        for key, p in list(positions.items()):
            b = bars[p.symbol]
            stopped = b.low <= p.stop if p.side == 'LONG' else b.high >= p.stop
            target_hit = b.high >= p.target if p.side == 'LONG' else b.low <= p.target
            if stopped:
                close(key, p.stop, t+interval, 'stop_loss')
            elif target_hit:
                close(key, p.target, t+interval, 'take_profit')
        prices = {s: b.close for s,b in bars.items()}
        eq = equity(prices)
        peak = max(peak, eq)
        dd = (peak-eq)/peak
        max_dd = max(max_dd, dd)
        if dd >= risk.max_drawdown:
            halted = True
            for key in list(positions):
                close(key, prices[key[0]], t+interval, 'drawdown_halt')
            eq = cash
        if i == end-1:
            for key in list(positions):
                close(key, prices[key[0]], t+interval, 'end_of_sample')
            eq = cash
        curve.append({'time': t+interval, 'equity': eq})
        if not halted and i < end-1:
            for key,p in positions.items():
                if invalidated(p, prices[p.symbol], strategy):
                    invalid_exits.add(key)
            for s in symbols:
                sig = signal(data[s], i, strategy)
                if sig:
                    pending[s] = sig
                    count_signals += 1
    wins = [x['net_pnl'] for x in trades if x['net_pnl'] > 0]
    losses = [x['net_pnl'] for x in trades if x['net_pnl'] < 0]
    profit, loss = sum(wins), -sum(losses)
    return {'metrics': {'total_trades': len(trades),
            'win_rate': len(wins)/len(trades) if trades else 0.0,
            'net_pnl': cash-risk.initial_capital,
            'profit_factor': profit/loss if loss else None,
            'profit_factor_note': None if loss else 'Undefined: no losing trades',
            'maximum_drawdown': max_dd,
            'average_profit_per_trade': (cash-risk.initial_capital)/len(trades) if trades else 0.0,
            'final_balance': cash, 'signals': count_signals,
            'rejections': rejections, 'drawdown_halted': halted,
            'start_time': times[start], 'end_time': times[end-1]+interval},
            'trades': trades, 'equity_curve': curve}
