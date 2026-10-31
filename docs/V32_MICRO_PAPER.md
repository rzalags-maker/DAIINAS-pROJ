# DAIINAS v3.2 — Micro Paper Execution Research

**Mode:** offline replay on public KuCoin Futures market observations. The service never creates exchange orders, uses private credentials, changes the original 8-USDT paper account, or claims a verified profitable trading edge.

## Completed implementation

- `daiinas/universe_observer.py` now captures the **actual selected contracts'** public lot/tick/multiplier and taker-fee parameters in its market-scan audit. Older raw-event captures without exact contract specifications are deliberately rejected by v3.2.
- `daiinas/paper_micro.py` reads source SQLite read-only, creates a **separate** paper ledger and deterministic report, and never accesses exchange REST/WS/private order endpoints.
- Strategy premise: exploratory alignment of aggressive buy/sell trade notional and top-of-book displayed imbalance. It is not a statistically validated predictor; no trades are required for a successful test.
- Signals are generated on an observed quote, with a minimum 100 ms simulated processing delay. An entry can be model-filled **only at a later observed quote** before the 5-second TTL, after a maximum 12bps price-drift test, a 2-second quote-freshness requirement, and a validated L2 update not older than 8 seconds.
- LONG fills cross the observed **ask**, SHORT fills cross the observed **bid**, with modeled 2bps adverse slippage and adverse tick rounding. The exit crosses the opposite bid/ask on a later observed quote, subject to sufficient displayed size for the entire simulated quantity; when depth is insufficient, no fictional full fill is recorded. Maker fills and partial fills are NOT modeled, so **all v3.2 filled orders are taker-only**.
- Planned stop/target use illustrative mid-market thresholds (35bps stop, 70bps target) and actual future quoted bid/ask conditions. At the first observed fillable quote reaching a stop, target, or 90-second time limit, exit occurs at that quote with modeled adverse slippage, NOT at a fabricated stop/target price. Price gaps can result in losses larger than planned; 0.25% risk is a **planned**, not guaranteed, worst-case limit.
- Position quantity is in **whole provider contract lots**, never rounded upward. Uses contract multiplier, price tick, min/max quantity, 3x assumed leverage, <=80% equity margin, current displayed top-of-book size, two-sided taker commissions, stop and exit slippage. A minimum lot violating 8-USDT equity and risk constraints results in NO TRADE.
- ONE shared-account paper position at a time. No default double-leg hedge and no concurrent symbol positions. Closing P&L is net of entry/exit fees and explicitly labeled modeled carry; actual exchange funding settlements are unavailable.
- Adaptive research risk ceiling: 8–<20 USDT 0.25% per hypothetical trade, 20–<50 0.35%, 50–<100 0.50%, >=100 0.75%. At 3% drawdown halve risk; at 6% drawdown halt new entries for the remainder of the study. No Martingale, automatic leverage increase, or deposits.
- Signals, rejects, fills, exits and realized net P&L retained with raw time-ordered source provenance. **An open position remains open at EOF** and the ending cash reflects paid entry fee. Do not misreport that as a finished profitable or losing trade. Source and ledger databases must differ; repeated identical studies are idempotent.
- This stage intentionally **rejects captures with more than one universe scan** to prevent using a later candidate list for earlier quotes. Multi-day time-aware symbol and contract replay is the next stage; don't remove this guard to make a report run.

## Commands

```bash
python -m pip install '.[live]'
python -m unittest discover -s tests -v
python -m daiinas.universe_observer --equity 8 --deep 5 --seconds 65 --db state/v32-source.sqlite3 --report reports/v32-capture.json
python -m daiinas.paper_micro --source-db state/v32-source.sqlite3 --paper-db state/v32-ledger.sqlite3 --capital 8 --report reports/v32-paper.json
```

GitHub workflow: `.github/workflows/paper-micro-study.yml`. It downloads no private data and never places real orders. Artifacts retain full public-source SQLite, independent study ledger and JSON reports for seven days.

## Verified versus unverified

**Verified by deterministic unit tests:** chronology, no same-tick fill, risk sizing, stop/target, account cash/P&L reconciliation, fees/slippage, quote staleness, contract-minimum rejection, out-of-book-size rejection, nonforced EOF, independent immutable replay and multi-scan future-data guard.

**Not proven by a 65-second smoke:** an economically profitable strategy, unbiased maker fill opportunity, guaranteed full market tape, true funding debit, hidden book liquidity, several-day operation, live execution eligibility or positive expected value. The last v1 historical strategy backtest remains negative; v3.2 is a distinct hypothesis, not its replacement.

## Required v3.3 acceptance gates

1. Extend event collection/replay to multiple timestamped universe scans with as-of contract rules and position pinning. No future watchlist.
2. Model dynamic paper positions through verified stream reconnect/sequence gaps, partial fills, full orderbook market impact, funding settlements and trailing exit; record blocked exits explicitly.
3. Deploy continuously running independent public observer and monitor health, retention, stop/restore and recovery with 24h+ and then multi-day data.
4. Compare independent training/test windows and full fee-adjusted cash performance, including no-trade baseline, with sufficient trades to estimate uncertainty. Only if net results support it should one consider an authenticated real-order component, requiring separate user authorization.

**WARNING:** A passing public-market-data paper replay establishes software behavior only. It does not establish profitability or readiness to trade user funds.
