# v4.7 completion against the uploaded autonomous-engine brief

The working branch remains `feature/v4-ladder-integration`. Tested source:
`0bc3bafdb5816967383a84c0e265b51baab7db27`. This extends the verified v4.7
implementation delivered at `b65fe4a`; it does not rebuild v4.6 or change Model A,
`risk.py`, the exactly-once capital ledger or INITIAL_FUNDING provenance.

Review of the supplied full brief identified two concrete gaps: deep analysis
needed actual closed multiframe OHLCV, and local session STOP needed to be distinct
from PAUSE. Both now have executable implementation and regression tests.

## Added code and behavior

- `daiinas/candle_context.py`: public 1m/5m/15m klines for the bounded deep
  shortlist/pinned symbols, three concurrent calls maximum and closed-interval
  cache. Sixteen contiguous CLOSED bars per interval are required; missing bars
  are not fabricated. A live/future candle cannot affect the analysis.
- Source journal retains request parameters, returned rows, canonical row digests
  and response-body hashes. The single existing checkpoint keeps verified
  summaries and is pruned to the current watch plus pinned exposure. No second
  ledger, trader, graphical interface or private transport was introduced.
- Per-token candle confirmation adds closed 5m/15m directional contradiction,
  1m ATR/noise and last-three-closed-bar swing structure to the SAME x1–x5,
  0.5%/1% stop/fee feasibility selector. Stops inside that structure are rejected.
  Widening a price stop cannot widen the unchanged monetary risk limits.
- New generated v4.7 profiles require this context. Existing saved policy
  identities are preserved rather than silently migrated or reseeded. Selected
  positions retain their exact candle-context digest. Missing/stale context
  blocks NEW entry, while existing risk management continues.
- OHLCV never supplies CVD or order-flow evidence. Actual public prints and
  sequence-verified L2 remain the independent sources for those observations.
- Local `start --session-seconds 18000`, `pause`, `stop` and `status` now have
  distinct v4.7 behavior. START/STOP are queued source controls; output says
  SOURCE_ACCEPTED_AWAITING_WORKER and never pretends an absent worker is running.
  PAUSE preserves monitoring; STOP durably disarms/retains exposure and ends the
  bounded worker. START never clears PAUSE/HALT. Legacy STOP semantics remain.
  STATUS exposes committed session state and ACK freshness. Mobile control is
  still NOT_CONNECTED, and stopped PAPER positions are not real venue protection.

The existing adaptive per-position leverage, independent LONG/SHORT/NO_TRADE
ranking, 2% allocation NET target, fee-aware partial lifecycle, ten-position shared
risk, replacement, loss recovery, native MOCK receipt reconciliation and SIGKILL
replay functionality remain. The older verified report is
[V47_VALIDATION.md](V47_VALIDATION.md); its results are not relabeled as new runs.

## Actual tests

**306 tests pass**: all 271 v4.6 tests, all 298 previously verified v4.7 tests,
and eight new closed-candle/session integration cases.

[Python 3.11/3.12/3.13 CI 41281466259](https://github.com/rzalags-maker/DAIINAS-pROJ/actions/runs/41281466259)
completed SUCCESS. Each of the three jobs passed the full regression command and
both existing v4.6 and v4.7 executable proof scripts. Local exact-revision runs:
Python 3.12, 306 tests / 44.733 seconds; Python 3.13, 306 / 46.626 seconds.

```sh
python -m unittest discover -s tests -v
python -m unittest discover -s tests -p test_v47_candles.py -v
python scripts/verify_v47.py --output-dir NEW_DIRECTORY
```

The new financial integration test uses the actual existing ledger: missing
closed context rejects entry; verified context permits a protected PAPER entry;
net target closes for at least +0.50 on a 25-USDT allocation; current capital
reconciles, funding stays exactly once, watch rotation prunes stale context,
and restart/full replay remain identical. It uses synthetic observations and is
NOT an actual-market profit claim. The preserved tests separately exercise stop
losses, gaps, partial entry/exit, residual losing exposure, correlation, ten
positions, slot replacement, uncertain protection, duplicate fills and crashes.

## Actual public market acceptance

[Run 41281466260](https://github.com/rzalags-maker/DAIINAS-pROJ/actions/runs/41281466260)
completed SUCCESS using actual public market data and explicitly MOCK capital.
The verifier requires real closed OHLCV contexts in addition to the existing
connection, source, cash, restart, backup and replay conditions.

| Metric | Result |
|---|---:|
| Public catalog | 717 contracts |
| Bounded observation | 130.428 seconds |
| Actual public trade prints | 137 |
| Verified L2 events | 32,041 |
| Bid/ask events | 3,339 |
| Verified multiframe candle-context publications | 30 |
| Final deep context symbols | ENA, HYPE, PEPE, WET, ZEC USDT perpetuals |
| Executed / rejected entry orders | 0 / 0: no qualified entry reached admission |
| Closed / remaining open positions | 0 / 0 |
| Net P&L / fees / modeled carry | 0 / 0 / 0 USDT |
| Maximum drawdown | 0%: no trades |
| Final simulated cash | 200 USDT |
| Win rate / profit factor | Undefined: no closed trades |
| Opening funding records | 1 |
| Restart/replay | Identical; cash independently reconciled |

Thirty contexts are publications across scans, not thirty distinct traded
instruments. The final five contexts each include sixteen closed 1m, 5m and 15m
bars. Their hashes, time bounds, directions, ATR, volume and swing structure are
in the immutable run reports and raw source journal. Four scheduled token
renewals are the only recorded connection errors. Both sessions stop flat.

Source cursor: **35,873**. Input digest:
`2fa9be93093bbc79563aa2c6c2875c4449b4bce7bf8ac84fd9d8fa8a2ee9ebfa`.
Raw source/PAPER SQLite, proof logs and checksums are retained in the run artifact
for 14 days; immutable JSON evidence remains in
`reports/v47-runs/41281466260/`. The companion JSON independently hashes those
reports. This short smoke is infrastructure acceptance, not an out-of-sample
strategy study or evidence of profitable expectancy.

## Failures and limits remain explicit

Superseded public runs 41281213481 and 41281394928 were canceled during follow-up
implementation; their produced evidence remains preserved and is not labeled
accepted. Matrix run 41281394896 failed because a new fixture variable shadowed
its helper module; the final revision corrects it and the complete 306-test matrix
passes. No failure was hidden or reclassified as a successful real-data test.

Candle trend/ATR/swing rules are observational heuristics, not calibrated return
forecasts. The 2% allocation target is conditional feasibility, never guaranteed.
Maker fills, native protection and offline native receipts remain explicitly
modeled/MOCK; live order routing is inert. Real authenticated KuCoin capital,
private fee/funding and liquidation semantics remain unverified. Five-hour expiry
is virtual-clock tested; real five-hour/24-hour independent host uptime is unrun.

Delivery sequence remains **v4.7 PAPER engine → separately authorized General-only
KuCoin read-only adapter → durable supervised hosting and independent 24-hour
acceptance**. No private exchange activation occurred here. PR creation's existing
403 is separate: code and evidence are pushed and tested regardless. Stable and
existing draft PRs remain unmerged. Review comparison:
https://github.com/rzalags-maker/DAIINAS-pROJ/compare/daiinas-v1...feature/v4-ladder-integration


## Preserved v4/legacy acceptance — completed

[Run 41281466283](https://github.com/rzalags-maker/DAIINAS-pROJ/actions/runs/41281466283)
completed SUCCESS on the same tested source: all eleven stages, 306 tests, original
capture parity, two actual processes, identical source replay, independent money
and reserve reconciliation and the same-data 8/60/100 M0–M3 controls. The separate
100-USDT v4 account stayed flat at 100 with zero costs/net/drawdown over 230.3 seconds.

The **separate legacy 8-USDT PAPER account lost money**: four closed trades, zero
wins, net **−0.02586203492464404 USDT**, fees **0.0133493904 USDT**, modeled carry
**0.0000006445246435972222 USDT**, final cash **7.974137965075355 USDT**, maximum
drawdown **0.3382155220196026%** and no remaining position. Win rate 0%, profit
factor 0. These are actual-public-data PAPER results of the legacy engine, not
real fills or v4.7 profits. Full immutable reports and their checksums are retained
under `reports/v4-runs/41281466283/` and in the companion validation JSON.
