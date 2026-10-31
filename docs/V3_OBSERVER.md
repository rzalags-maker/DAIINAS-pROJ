# DAIINAS v3 — dynamic all-market observer

**Status:** Candidate rotation + public WebSocket observation with separate SQLite ledger. **Read-only.** This is the first integration stage of GitHub issue #2; it is NOT the autonomous micro-scalping trading engine or a validated profitable strategy. No broker authorization, live order endpoint, private API key, permanent server, or real trade execution exists in this module.

## Run

Python 3.11+ with public WebSocket dependency:

```bash
python -m pip install '.[live]'
python -m unittest discover -s tests -v
python -m daiinas.universe_observer --equity 8 --deep 5 --seconds 65 --db state/universe-smoke.sqlite3 --report reports/universe-smoke.json
python -m daiinas.universe_observer --equity 8 --deep 5 --db state/universe-observer.sqlite3
```

Without `--seconds`, the scanner loops. It **requires a host kept running**: a Codex task or GitHub Actions workflow does not run continuously. `Ctrl+C` ends the process; WAL-committed observations survive.

## Real data flow

1. Public KuCoin `contracts/active` plus `allTickers` are scanned as a single near-contemporaneous snapshot; **all** active USDT-margined perpetuals are considered (not the old five static symbols).
2. `daiinas.universe.scan` applies listing age, 24h liquidity, quote freshness, spread, lot notional, illustrative planned loss/available margin, and first-level displayed liquidity. Every rejection is captured in `market_scans.raw_report`.
3. `daiinas.universe_rotation.select` picks up to five **DEEP** markets, retaining eligible previous selections for a dwell interval and requiring a ranking improvement to replace them. Open-position symbols can be pinned by the selection interface, and the system refuses to exceed subscription capacity. **This standalone observer has no access to the v1 paper account's open positions and must not be coupled to it until that pinning and shared risk interface is wired.**
4. Each session obtains a new public connection ticket and subscribes selected exchange symbols to three channels: executions (aggressive trades), best bid/ask (tickerV2), and incremental level2 depth.
5. The adapter validates each KuCoin contract multiplier/lot/tick, timestamp, sequence monotonicity and event normalization. L2 snapshots are obtained **after subscribing**. A book is considered verified only after the first exact `snapshot_sequence + 1` delta; gaps trigger a fresh snapshot, never synthetic levels.
6. Data are inserted into a dedicated SQLite WAL database: `market_scans`, `watchlists`, `raw_events`, and `failures`. Trade and quote payloads have normalized units; this is not a paper-fill or P&L ledger.
7. Every 180 seconds by default, a new whole-market scan is performed and the selected set is reconciled. This initial conservative implementation establishes a **new** public WebSocket session on each scan. This produces a brief observation gap; the next stage must implement acknowledged in-session subscription changes before a continuously evaluated entry/exit system is enabled.

### Important limitations

- Ranking is a *data collection priority* using turnover and spread; it cannot predict a profitable trade.
- Quote timestamps are per-market last-event timestamps. Staleness or missing values are rejected, not inferred from the timestamp of the REST reply.
- Order-book sequence checks detect missing L2 deltas. KuCoin trade/ticker streams may not be perfectly complete, because their sequences aren't necessarily contiguous. Do not equate message count with a verified full trade tape.
- Top of book is not guaranteed executable size. A separately validated limit/maker fill model is required before micro P&L claims.
- A websocket error fails the bounded smoke and persists a failure record. During persistent operation automatic reconnects, per-coin resync, watchdog monitoring and lossless rotation need additional acceptance testing.
- Conservative 8 USDT eligibility uses a **hypothetical 20 bps stop**, **not** an actual strategy stop. A selected coin may still be impossible to trade at a safe loss budget.
- The existing KuCoin 5-market paper trading service and its 8-USDT shared-account checkpoint are left untouched. The current candle-based strategy remains research-only.

## Acceptance sequence

1. Preserve all prior 100 regression tests, plus new rotation/dynamic-contract/persistence tests.
2. Run a GitHub Actions bounded real WebSocket test with the dynamic subset (not pinned BTC/ETH/SOL/BNB/XRP), storing the SQLite artifact and machine-readable report; verify actual execution, quote, and contiguous L2 for at least one symbol. Record failures honestly.
3. Add observable DOLF flow diagnostics from saved events and replay them chronologically.
4. Integrate dynamic subscriptions with paper position pinning, exposure limits, long/short signal evaluation, realistic execution costs, and checkpoint recovery in the **same transactional simulation**.
5. Deploy independent Linux observer/paper service with health checks, backups, 24h reconnection soak and data retention.
6. Do not authorize real orders unless separate long-running out-of-sample paper results are positive net of real costs and every contractual / min-lot rule is satisfied.

**Next task:** finish #2 by implementing a safe in-session rotation + verified signal/entry/exit paper ledger; order-flow signal profitability has NOT been established.
