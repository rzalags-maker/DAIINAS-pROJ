# DAIINAS v3.1 — Flow Diagnostics and Shadow Signal Lab

**Status:** Pure read-only replay research. **No trading orders, no paper fills, no assumed win rates or profit forecasts.** This is the first step after the verified v3 whole-market public observer, NOT a profitable scalper.

## Completed

- `daiinas/shadow_flow.py` reads the v3 observer's independent SQLite `raw_events` and `market_scans` tables in receipt-time order; it never reaches ahead to later events.
- Reports event counts, recent aggressive traded-notional direction (CVD ratio), current best-bid/best-ask displayed-size imbalance, quote spread and last verified order-book update freshness.
- Separately reports `pressure_snapshots` (each qualifying quote observation) and `pressure_candidates` (deduplicated episodes requiring fresh trades and a side flip or 30-second cooldown). Many repeated price ticks reusing three trades must NOT count as independent market opportunities.
- Uses provisional observation thresholds: 30 seconds trade window, at least 3 public prints and 25 USDT traded notional, CVD imbalance >=40%, best-quote imbalance >=10% on the same side, max spread 8bps, last verified book event <=8 seconds old.
- A matching condition is recorded only as `PRESSURE_CANDIDATE`, **never as LONG/SHORT ENTRY**. No conclusion on future market direction and no expected return. Thresholds are invented research hypotheses to be calibrated out of sample, not a rule copied from an influencer.
- Records per-market explanations such as stale book, too-wide spread, too-few trades, contradictory book pressure. The replay does not pretend to verify completeness of KuCoin public trade prints.
- Includes offline tests against stale/crossed market data, future-arriving events, CVD sign, and SQLite replay.
- GitHub workflow `.github/workflows/shadow-flow-research.yml` collects a fresh dynamic KuCoin public WS sample, then runs deterministic shadow replay and saves the SQLite capture plus JSON report. Running Actions is **temporary**, not persistent data collection.

## Run

```bash
python -m pip install '.[live]'
python -m unittest discover -s tests -v
python -m daiinas.universe_observer --equity 8 --deep 5 --seconds 65 --db state/universe-shadow.sqlite3 --report reports/universe-shadow-connection.json
python -m daiinas.shadow_flow --db state/universe-shadow.sqlite3 --output reports/shadow-flow-diagnostics.json
```

## What the engine still lacks

1. **Continuous verified data and lifecycle:** 24/7 independent host, multi-day data capture, near-zero-loss reconnects and in-session dynamic subscribe/unsubscribe with position pinning. Current observer recreates a WS session on each full-market scan.
2. **Net expectancy:** no proof that pressure predicts a next favorable move beyond commissions, spread, slippage, maker fill risk, stop gaps and adverse execution.
3. **Realistic simulation:** no buy/sell entry planner for the dynamic symbols, no exit triggers, no shared 8-USDT account integration, no funding/OI enrichment, no adaptive controller wired into atomic SQLite paper checkpoint.
4. **Statistical acceptance:** no out-of-sample forward test by different regimes, confidence bounds, net P&L or stable drawdown. The old v1 OHLCV backtest was negative; never relabel it as positive.

## Technical gates for v3.2

- Use only the existing public KuCoin provider; normalize all contract units and live market times.
- Add replayable **event-time** completeness/watermark reasoning, stream quality flags, and resilient in-socket subscription updates; never assume every public trade print is observed.
- Register raw public signals, signal TTL, entry cost/bid-ask, exact lot/minimum, stop risk and NO_TRADE decision. Avoid future-price access.
- Before paper BUY/SELL, calculate conservative per-coin net expected upside > round-trip fees+spread+slippage+funding with risk budget and account-wide margin. This condition requires actual validated predictive evidence; do not turn heuristic pressure into guaranteed expected upside.
- Paper accounting with dynamic exits, partial/missing limit fills, stops and hedge margin; checkpoint atomically in SQLite. Zero eligible paper trades is acceptable.
- Multi-day independent capture before any decision about increasing trade size or deploying a real-order connector.

**Central rule:** more frequent trades do not create positive expectancy. Cost-adjusted predictive edge, risk control and data integrity must all be demonstrated.
