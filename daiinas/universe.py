"""Public KuCoin Classic Futures market-wide opportunity pre-screen.

Shortlists candidates for deeper LIVE data collection; it never emits orders or
claims that a symbol has a positive trading edge. This is not a trading signal.
"""
from dataclasses import asdict, dataclass
import argparse
import json
import math
from pathlib import Path
import time
from urllib.request import Request, urlopen

BASE = 'https://api-futures.kucoin.com'
PUBLIC_PATHS = ('/api/v1/contracts/active', '/api/v1/allTickers')


def number(v, label, *, allow_zero=False):
    try:
        val = float(v)
    except (ValueError, TypeError) as exc:
        raise ValueError(f'Invalid {label}') from exc
    if not math.isfinite(val) or val < 0 or (val == 0 and not allow_zero):
        raise ValueError(f'Invalid {label}')
    return val


def public_get(path):
    if path not in PUBLIC_PATHS:
        raise ValueError('Unsupported public universe endpoint')
    req = Request(BASE + path, headers={'User-Agent': 'DAIINAS-universe-research/0.1'})
    with urlopen(req, timeout=20) as response:
        data = json.load(response)
    if data.get('code') != '200000' or not isinstance(data.get('data'), list):
        raise ValueError(f'Unexpected KuCoin response: {path}')
    return data['data']


@dataclass(frozen=True)
class Policy:
    min_turnover_usdt_24h: float = 1_000_000
    max_spread_bps: float = 8.0
    max_quote_age_ms: int = 45_000
    min_listing_age_days: int = 7
    max_margin_fraction: float = 0.8
    leverage: float = 3.0
    risk_fraction: float = 0.0025
    assumed_stop_bps: float = 20.0
    assumed_adverse_slippage_bps_per_fill: float = 2.0
    top: int = 20

    def __post_init__(self):
        vals = (self.min_turnover_usdt_24h, self.max_spread_bps,
                self.max_margin_fraction, self.leverage, self.risk_fraction,
                self.assumed_stop_bps, self.assumed_adverse_slippage_bps_per_fill)
        if any(not math.isfinite(x) for x in vals) or any(x < 0 for x in vals):
            raise ValueError('Invalid filter parameter')
        if not (0 < self.max_margin_fraction <= .9 and 1 <= self.leverage <= 20
                and 0 < self.risk_fraction <= .1 and 1 <= self.top <= 100
                and 1_000 <= self.max_quote_age_ms <= 300_000
                and 0 <= self.min_listing_age_days <= 365):
            raise ValueError('Invalid filter bounds')


def review_contract(contract, ticker, now_ms, equity, policy):
    """Returns audit record with every rejection reason. Fail closed on missing data."""
    reasons = []
    symbol = str(contract.get('symbol', '?'))
    mandatory = (contract.get('status') == 'Open' and
                 contract.get('type') == 'FFWCSX' and
                 contract.get('quoteCurrency') == 'USDT' and
                 contract.get('settleCurrency') == 'USDT' and
                 contract.get('isInverse') is False and
                 contract.get('expireDate') is None and
                 contract.get('marketStage', 'NORMAL') == 'NORMAL')
    if not mandatory:
        reasons.append('not_open_linear_usdt_perpetual')
    try:
        first_open = int(contract['firstOpenDate'])
        if first_open > now_ms or now_ms-first_open < policy.min_listing_age_days*86_400_000:
            reasons.append('too_new_or_future_listing')
    except (KeyError, ValueError, TypeError):
        reasons.append('missing_listing_timestamp')
    try:
        turnover = number(contract['turnoverOf24h'], '24h turnover', allow_zero=True)
        if turnover < policy.min_turnover_usdt_24h:
            reasons.append('insufficient_24h_turnover')
    except (KeyError, ValueError):
        turnover = None
        reasons.append('missing_24h_turnover')
    cost_bps = spread_bps = min_lot_usdt = min_margin_usdt = min_loss_usdt = None
    price = None
    if ticker is None:
        reasons.append('missing_ticker')
    else:
        try:
            raw_ts = int(ticker['ts'])
            tick_ms = raw_ts//1_000_000  # Futures allTickers returns ns
            if not 0 <= now_ms-tick_ms <= policy.max_quote_age_ms:
                reasons.append('stale_or_future_quote')
            bid = number(ticker['bestBidPrice'], 'bid')
            ask = number(ticker['bestAskPrice'], 'ask')
            if bid >= ask:
                raise ValueError('Crossed or locked quote')
            price = (bid+ask)/2
            spread_bps = (ask-bid)/price*10_000
            if spread_bps > policy.max_spread_bps:
                reasons.append('wide_spread')
            bid_size = number(ticker['bestBidSize'], 'bid qty', allow_zero=True)
            ask_size = number(ticker['bestAskSize'], 'ask qty', allow_zero=True)
            if min(bid_size, ask_size) == 0:
                reasons.append('empty_top_quote')
            multiplier = number(contract['multiplier'], 'multiplier')
            lot_size = number(contract['lotSize'], 'lot size')
            tick_size = number(contract['tickSize'], 'tick size')
            taker_fee = number(contract['takerFeeRate'], 'taker fee', allow_zero=True)
            if taker_fee >= 1:
                raise ValueError('Unreasonable taker fee')
            min_lot_usdt = price*multiplier*lot_size
            if tick_size >= price:
                reasons.append('unusable_price_tick')
            cost_bps = 2*taker_fee*10_000 + spread_bps + 2*policy.assumed_adverse_slippage_bps_per_fill
            min_margin_usdt = min_lot_usdt * (1/policy.leverage + taker_fee)
            min_loss_usdt = min_lot_usdt * (policy.assumed_stop_bps + cost_bps)/10_000
            if min_margin_usdt > equity*policy.max_margin_fraction:
                reasons.append('minimum_lot_exceeds_margin_budget')
            if min_loss_usdt > equity*policy.risk_fraction:
                reasons.append('minimum_lot_exceeds_assumed_stop_budget')
            # Best level is only a preliminary quality check, not executable depth proof.
            if min(bid_size*bid, ask_size*ask)*multiplier < min_lot_usdt:
                reasons.append('insufficient_displayed_top_depth')
        except (KeyError, ValueError, OverflowError, TypeError):
            reasons.append('invalid_ticker_or_contract_units')
    unique_reasons = sorted(set(reasons))
    score = (math.log10(turnover+1)*10 - (spread_bps or 0)*2
             if turnover is not None and spread_bps is not None else None)
    return {'symbol': symbol, 'eligible': not unique_reasons,
            'reasons': unique_reasons, 'turnover_24h_usdt': turnover,
            'mid_price': price, 'spread_bps': spread_bps,
            'estimated_round_trip_cost_bps': cost_bps,
            'minimum_lot_notional_usdt': min_lot_usdt,
            'minimum_lot_margin_usdt': min_margin_usdt,
            'assumed_minimum_lot_stop_loss_usdt': min_loss_usdt,
            'liquidity_score_not_alpha': score}


def scan(contracts, tickers, *, now_ms, equity, policy=Policy()):
    number(equity, 'equity')
    if not isinstance(contracts, list) or not isinstance(tickers, list):
        raise ValueError('Invalid response collections')
    if not isinstance(now_ms, int) or now_ms <= 0:
        raise ValueError('Invalid decision timestamp')
    ticker_map = {}
    for t in tickers:
        symbol = t.get('symbol')
        if symbol in ticker_map:
            raise ValueError(f'Duplicate ticker: {symbol}')
        ticker_map[symbol] = t
    audit = [review_contract(c, ticker_map.get(c.get('symbol')), now_ms, equity, policy)
             for c in contracts]
    eligible = [r for r in audit if r['eligible']]
    eligible.sort(key=lambda r: (-r['liquidity_score_not_alpha'], r['symbol']))
    reason_counts = {}
    for record in audit:
        for reason in record['reasons']:
            reason_counts[reason] = reason_counts.get(reason, 0)+1
    return {'time_ms': now_ms, 'capital_usdt': equity,
            'policy': asdict(policy), 'contracts_observed': len(audit),
            'preflight_eligible': len(eligible),
            'selected_for_deeper_observation': eligible[:policy.top],
            'rejection_counts': dict(sorted(reason_counts.items())),
            'audit': audit,
            'status': 'READY_TO_OBSERVE' if eligible else 'NO_EXECUTABLE_CANDIDATES',
            'disclaimer': 'Preliminary quote/lot filter, NOT a buy/sell signal or profit forecast. Actual stop risk, depth and funding must be checked at decision time.'}


def main(argv=None):
    p = argparse.ArgumentParser(description='Read-only KuCoin market-wide candidate filter')
    p.add_argument('--equity', type=float, default=8)
    p.add_argument('--top', type=int, default=20)
    p.add_argument('--output', type=Path)
    args = p.parse_args(argv)
    result = scan(public_get(PUBLIC_PATHS[0]), public_get(PUBLIC_PATHS[1]),
                  now_ms=int(time.time()*1000), equity=args.equity,
                  policy=Policy(top=args.top))
    payload = json.dumps(result, indent=2, allow_nan=False)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload)
    # Small output for GitHub Actions logs; full audit stays in artifact.
    print(json.dumps({k:v for k,v in result.items() if k != 'audit'}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
