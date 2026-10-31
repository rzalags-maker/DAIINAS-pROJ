# DAIINAS v2 — KuCoin validation

Connection/paper smoke status: **passed**.

[GitHub Actions evidence](https://github.com/rzalags-maker/DAIINAS-pROJ/actions/runs/41240044645) tested commit `5bc1f164e558ad9d72d5112fcd004310d84ebeb0`.
Recorded 2026-10-31T20:44:21.811000+00:00.

The market inputs below are actual KuCoin Classic Futures public data. Account
decisions and fills are simulation only. No exchange orders or private API keys
were used. The full machine-readable report and REST hashes are in
[kucoin-actions-connection.json](kucoin-actions-connection.json); a run-specific
copy and the SQLite artifact are associated with the linked workflow.

| Market | Contract | Matched-trade events | Bid/ask events | Accepted L2 deltas |
|---|---|---:|---:|---:|
| BNBUSDT | BNBUSDTM | 10 | 544 | 3089 |
| BTCUSDT | XBTUSDTM | 25 | 1345 | 25321 |
| ETHUSDT | ETHUSDTM | 31 | 1047 | 13689 |
| SOLUSDT | SOLUSDTM | 18 | 1160 | 21351 |
| XRPUSDT | XRPUSDTM | 10 | 3063 | 9783 |

| Lifecycle check | Observed |
|---|---:|
| public_tokens | 5 |
| connections | 5 |
| pongs | 8 |
| renewals | 4 |
| book_gaps | 6 |
| book_resyncs | 6 |
| verified_sessions | 5 |
| checkpoint_resumes | 4 |
| paper_batches | 1 |
| errors | 0 |

Book gaps were detected and resynchronized, preserving strict sequence checks.
Forced renewals occur only after a healthy session has persisted paper state;
checkpoint reuse and another healthy connection are required to pass.
This exercises renewal early, rather than waiting for the 24-hour ticket lifetime.

## Paper account observations

| Metric | Observed |
|---|---:|
| total_trades | 0 |
| net_pnl | 0.000000 |
| maximum_drawdown | 0.000000 |
| final_balance | 8.000000 |
| marked_equity | 8.000000 |
| signals | 1 |
| win_rate | Undefined: no closed trades |
| profit_factor | Undefined: no losing trades |

Natural LONG/SHORT candidate counts: `{"LONG": 1}`.
Rejections: `{"existing_leg": 0, "gap_invalid_stop": 0, "invalid_target": 0, "minimum_or_risk_budget": 0}`.
Open simulated legs retained: 0.

Zero trades or zero signals are genuine short-window observations, not evidence
of profitability or proof that 8 USDT meets every contract minimum. No synthetic
signal, capital increase, or relaxed risk threshold was used to force trades.
The public contract multiplier, minimum lots, increments, price ticks, maximum
quantity and leverage were normalized for all five markets. No additional
notional floor is invented when KuCoin Futures metadata does not publish one.

## Model and operational limits

- Existing Micro Liquidity Reversal, shared-account risk and checkpoint simulator are retained.
- Real WebSocket trade/quote/book readiness gates paper processing. Strategy decisions use actual closed KuCoin OHLCV, not an invented order-flow signal.
- The current default is 5m. Actual 1m missing buckets observed in earlier runs blocked paper accounting; they were never filled with synthetic candles.
- Paper fills remain the existing next-open candle model with stop-first ambiguity handling, modeled spread/slippage, conservative taker fees and assumed funding. They are not executed live quotes.
- Socket reconnection with SQLite state is exercised on real data; full process restart, rollback, LONG/SHORT integration and persistent stops are also tested with explicitly synthetic fixtures.
- The bounded smoke is not a multi-day soak or a hosted 24/7 deployment. Token lifetime expiry after 24 hours was not waited out.
- Trade/ticker monotonicity and freshness do not prove a complete trade tape; only L2 has the exact sequence bridge asserted here.
- No profitability or future-return claim is made.

The combined branch passed **100 offline tests**, compilation and static systemd
unit verification. The report writer was separately checked to preserve concurrent
source-tree changes while adding only fresh evidence.

Earlier real attempts are retained as `kucoin-actions-first-attempt.json`,
`kucoin-actions-second-attempt.json`, and `kucoin-actions-third-attempt.json`.
They document book-gap recovery, absent candle buckets, and test sequencing
corrections rather than being relabeled as passing runs.

Local Codex access still returned `URLError: <urlopen error Tunnel connection
failed: 403 Forbidden>`; that separate failed attempt is in
`kucoin-local-connection.json`. GitHub Actions and local network readiness are
different observations.

Run continuously on a prepared Linux host using the commands and stop/health/
backup controls in [the KuCoin runbook](../docs/KUCOIN.md). Binance archives
remain the separate historical provider. The isolated money-flow/adaptive
research modules added concurrently were preserved and were not silently
enabled as a new live strategy.
