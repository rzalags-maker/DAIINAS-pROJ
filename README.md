# DAIINAS — Micro Trading Engine v2

Python 3.11+ cryptocurrency perpetual-futures **research and simulation only**.

KuCoin Classic Futures WebSocket is the primary live provider; see the
[KuCoin service runbook](docs/KUCOIN.md) and the
[verified real-data connection report](reports/KUCOIN_VALIDATION.md). Binance archives remain a separate
historical research provider. The existing strategy and account model are retained.
No live execution module, signed API calls, exchange keys, Bitsgap, martingale,
or loss-based risk escalation. Initial simulated capital is **8 USDT**.

## Run

The engine uses only the Python standard library; no dependency installation is
needed when running from the checkout. Optional packaging: `python -m pip install -e .`.

```bash
cd /workspace/DAIINAS-pROJ  # or your local checkout
python -m unittest discover -s tests -v
python -m daiinas download --config configs/default.json
python -m daiinas backtest --config configs/default.json --output reports/default
```

Download requires HTTPS access to `data.binance.vision` and `fapi.binance.com`;
no API credentials. Errors (including geographic restrictions, unavailable dates,
or policy denials) stop the command; they never cause synthetic data substitution.
The default downloads January 1–14, 2025, for BTC, ETH, SOL, BNB, and XRP USDT
USD-M perpetual futures at 5m. Dates are UTC, end exclusive. Change `interval`
to `1m` or `15m` in a separate config to run those intervals.

Daily Binance archives and publisher `.CHECKSUM` files are cached under ignored
`data/`. SHA-256 verification occurs on download **and every load**. Missing,
duplicate, out-of-order, malformed, or unsynchronized candles fail validation.
Cached downloads are verified and reused. Backtests are offline after download.
Use a new data directory or `download --refresh-rules` to refresh public contract
rules intentionally. TLS and checksum verification remain enabled.

For reproducibility, preserve the cached `exchangeInfo.json`, or copy it to a
versioned public metadata snapshot and pass `--rules-file path/to/snapshot.json`
to both commands. The report records all archive URLs (in `data/manifest.json`),
archive hashes, applied contract rules, metadata hash, fully expanded parameters,
source file hashes, equity curve, and every trade. Running with the same source,
config, archives, and rule snapshot produces identical results; Git revision and
working-tree status are provenance fields and may differ.

## Strategy and decision time

Micro Liquidity Reversal here is an **OHLCV price-pattern hypothesis**:

1. Find the previous `lookback` candles' high and low, excluding the decision candle.
2. Calculate prior ATR using true ranges and prior closes, also excluding the decision candle.
3. Require ATR/price between configured volatility bounds.
4. LONG: price sweeps below the prior low by `sweep_atr * ATR`, then closes strictly
   inside the prior range. SHORT mirrors the prior high. By default the candle
   body must reverse in the signal direction. Candles sweeping both sides are rejected.
5. At the next open, enter if the stop and reclaimed range boundary remain valid.
   Stop is beyond the sweep extreme by `stop_atr * ATR`; take-profit is a configurable
   multiple of initial stop distance. A close outside the reclaimed boundary
   (plus optional `invalidate_atr` buffer) schedules a next-open invalidation exit.

Signals read only completed candles. No fixed holding period exists. Samples
force-close any remaining positions at the sample end, separately labeled in the
trade ledger. `daiinas/flow.py` defines future order-book and aggressive-trade
interfaces only. **No order-flow or genuine resting-liquidity signals are tested.**

## Portfolio, risk, and fills

- Hedge Mode architecture uses `(symbol, side)` legs: one LONG and one SHORT per
  symbol can coexist. Both consume a shared account; each symbol does not receive
  a separate 8 USDT. Simultaneous signals use alphabetical symbol order.
- Risk is a fixed fraction of current equity (default 1%), including estimated
  stop slippage and entry/exit fees. It never increases after losses. Funding and
  price gaps can exceed the planned loss budget.
- Default leverage 3x, configured ceiling 5x; validation caps configurable ceilings
  at 20x. Shared margin allocation is capped at 80% by default, with entry fees
  reserved. Quantity rounds down to the common exchange lot increment; quantities,
  maximum sizes, minimum notional, contract multiplier and price ticks are validated.
  Orders below exchange minimums are **rejected**, never rounded up.
- Public current exchange filters are applied to historical candles. Historical
  filter changes are not reconstructed. USD-M quantities are base-asset units,
  contract multiplier 1. Minimum size constraints can prevent 8 USDT accounts
  from trading some or all signals. Rejection counts appear in each report.
- Default taker fee 0.05% **per side**, full spread 2 bps, slippage 2 bps **per fill**.
  Every fill pays adverse half-spread plus slippage, including TP exits.
- When SL and TP both touch in one candle, **SL wins**. Gapped stops fill at the
  adverse open. Gapped take-profit fills receive no favorable price improvement.
  Resting barriers at the open are processed before invalidation market exits.
- Funding is a configurable assumed 8-hour charge (default 0.01%) applied to
  **both** directions carried across UTC 00:00/08:00/16:00. It is a conservative
  cost scenario, **not actual historical funding**.
- Account equity includes estimated exit costs. A 20% default peak-to-equity
  drawdown breach at an open or close flattens all positions and halts new entries
  for that sample. Open/close sampling can miss greater intrabar drawdown, and
  gap losses can exceed the threshold.
- Candle fills cannot model depth, queue priority, partial fills, latency,
  mark-price liquidation, or outages. Leverage is simulated exposure, not proof
  that an exchange would accept or safely maintain the positions. This is not
  an execution-grade futures or liquidation simulator.

## Parameters and reports

`configs/default.json` selects symbols, interval, UTC dates and a chronological
70%/30% in-sample/out-of-sample split. Empty `strategy` and `risk` objects expand
to the explicit defaults in `daiinas/models.py`; override named fields there in
JSON. Unknown fields or invalid parameter values fail. The JSON report stores
all resolved values so defaults cannot silently alter an archived experiment.

Each sample starts independently flat with 8 USDT; out-of-sample can use earlier
candles to warm indicators, but inherits no trades, signals, cash, or positions.
No parameter fitting or tuning is performed. These labels alone do not establish
independent validation after repeated experimentation.

`reports/<name>.md` summarizes trade count, win rate (fraction), net USDT P&L,
profit factor, maximum drawdown (fraction), average net profit/trade, final
balance, rejections, and drawdown halt status. JSON includes trade and equity
ledgers. Profit factor is `null` when there are no losing trades (including zero
trades); it is not a manufactured finite ratio. Zero-trade runs are valid account
constraint outcomes, not evidence of strategy profitability.

No profitability claim is made without measured results. A short positive
backtest would not establish future profitability.

## Layout and verification

- `data.py`: public verified archives, validation, exchange filter snapshots
- `strategy.py`: prefix-invariant candle signals and invalidation
- `risk.py`: costs, contract rules, sizing
- `backtest.py`: deterministic shared-account simulator
- `cli.py`: configuration, downloads, chronological reports
- `flow.py`: future data-source protocol, no strategy implementation
- `tests/`: synthetic unit and integration tests, kept distinct from market results

```bash
python -m unittest discover -s tests -v
python -m compileall -q daiinas tests
```

CI runs offline tests across Python 3.11–3.13. Synthetic tests exercise mechanics;
they do not establish performance on historical market data.

Current execution evidence and the outstanding real-data access requirement are
recorded in [reports/VALIDATION.md](reports/VALIDATION.md). This status is separate
from the generated historical performance report.

## Continuous scanner and paper service foundation

The existing simulator now supports durable continuation without artificial
sample-end exits. A Linux worker polls public closed candles, stores scanner
signals and simulated fills in SQLite, and supports restart recovery, health,
persistent stop/resume, and online backup. It submits no real orders and needs
no exchange keys. Hosting templates and operational limitations are in the
[service runbook](docs/SERVICE.md). Real Binance access and independent-host
acceptance remain pending as detailed in the validation report.
