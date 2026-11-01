# Issue #8 — v3.3 financial, execution and operational audit

**LIVE ORDERS DISABLED.** Public feeds and simulated money only. No private
exchange connector or secret was accessed. PR #7 remains Draft/unmerged.

Start verified: feature `4644bdd677318a780cd9880933108228f6f39412`, stable
`8587154e67a47c7924c133b1ef859ff675a9a50e`. Follow-up branch:
`feature/v33-risk-acceptance`, targeting `feature/v33-continuous-paper`.
This is an incremental audit; existing strategy, risk, provider, five-pair paper
and backtest implementations and all 180 original tests are preserved.

## Findings and regression evidence

| Component / prior behavior | Severity and confirmed finding | Evidence before fix | Change and regression test | Remaining risk |
| --- | --- | --- | --- | --- |
| Paper transaction recovery | **P0:** SQLITE_FULL can auto-rollback; a second ROLLBACK raised before restoring in-memory money/cursor | Actual SQLite `max_page_count` exhaustion: failed checkpoint left memory at cursor 3 rather than committed 1; deposit was uncommitted | [Always restore previous state](../daiinas/continuous_paper.py#L404), rollback only if transaction exists; `test_actual_sqlite_full_paper_restores_memory_before_recovery` fails before, passes after; reapply twice charges flow once | Unknown host filesystem/power-loss behavior; source may be ahead and must replay |
| Deposit-adjusted equity under insufficient depth | **P0:** indicative equity floor ignored a deposit, creating false drawdown/HALT | `test_external_flow_during_unresolved_depth_is_not_drawdown`: 7.994299459 instead of expected 8.994299459 | [Flow-adjusted floor](../daiinas/continuous_paper.py#L147); same test passes | Simulated external flows remain separate from actual exchange balances |
| Health probe | **P1:** fresh checkpoint/connected verified-book flags could conceal stale market feeds | `test_health_rejects_fresh_checkpoint_with_stale_feeds` reported healthy with 3000ms quote/book age before fix | [Include feed age and checkpoint delay](../daiinas/continuous_ops.py#L46); test passes | Strict 2s health threshold can mark quiet feeds unhealthy; host alert delivery not tested |
| Backup versus source rollover | **P1:** online backup had no maintenance lock against replacing the source file | Review-confirmed interleaving: paper copy, source rotation, source copy could span different segments; full replay then needs missing archive | [Shared maintenance lock](../daiinas/continuous_ops.py#L72); `test_backup_holds_source_maintenance_lock`; interrupted backup and replace-failure fixtures retain original money | No assertion that injected exception equals physical power loss; archive set still required |
| Cost attribution / stale equity reporting | **P2:** fills lacked original two-sided BBO in position payload; only labeled last mark was exposed | New cost-basis and executable-equity tests initially raise missing-field errors | Persist original BBO/wire times and exit request time; per-fill and market/direction cost totals; `executable_equity=null` when unresolved; `production_ready=false` | Older records need raw source for independent spread/slippage decomposition; not backfilled into money state |

New adverse fixtures also cover fee refresh, stale metadata, quote/book drift,
unknown ACK, >20 pins, bounded queue overflow, actual source SQLITE_FULL, interrupted
backup, source replacement failure, tampered net P&L, and insufficient 24h evidence.
Original tests already cover concurrent pin/rotation, disappearing/changed
contracts, partial depth, stop gaps, duplicate replay, stale quotes, pending TTL,
HALT/reset, real SIGKILL between fee/checkpoint and source-before-ledger crash.
Fixtures are explicitly synthetic. All 200 tests passed locally after fixes;
exact Python 3.11/3.12/3.13 CI results are linked in the final evidence section.

## Independent reconciliation of the ORIGINAL three-position study

Evidence is immutable under `v33-runs/41251111492/`, from
[real public capture 41251111492](https://github.com/rzalags-maker/DAIINAS-pROJ/actions/runs/41251111492),
not a fresh rerun substituted for the old losses. `daiinas.paper_audit` uses
Decimal arithmetic independently of sizing/fill functions. It checks gross,
net, entry/exit fees, default carry, first/open checkpoint fee handling, final
cash and replay equality. The machine report `v33-risk-audit.json` explicitly
separates report-arithmetic verification from raw-journal availability.

| Source sequence | Financial event | Cash USDT | Reserved margin | Cumulative realized net |
| --- | --- | ---: | ---: | ---: |
| initial | one shared account | 8.000000000000 | 0 | 0 |
| 977 | PEPE LONG entry; entry fee debited | 7.998450576800 | 0.860790666667 | 0 |
| 6334 | PEPE LONG exit; release reserve | 7.993522894006 | 0 | -0.006477105994 |
| 22757 | TAO LONG entry | 7.992099034006 | 0.791033333333 | -0.006477105994 |
| 24432 | TAO LONG exit | 7.989675636424 | 0 | -0.010324363576 |
| 28293 | PEPE SHORT entry; OPEN at first process end | 7.988125589224 | 0.861137333333 | -0.010324363576 |
| 31239 | same PEPE SHORT closes after process restart | 7.988656666881 | 0 | -0.011343333119 |

Margin is a reservation within cash, not a second cash expense; releasing it does
not create income. At an open checkpoint:
`cash = 8 + external flows + closed net P&L - open entry fee`.
At exit cash receives `gross - exit fee - carry`, because the entry fee was
already debited. Final flat equity equals cash. While open, equity includes
unrealized directional movement minus modeled exit costs; a stale or insufficient
depth mark remains indicative, not executable equity. Committed first/restart/replay
cash, mark, reserve, fees/carry and drawdown are separately included in the JSON.
Reported maximum drawdown is 0.1886186285%; replay equality checks it, but the
independent arithmetic audit does **not** claim to reconstruct every intratick
high-water mark. HALT/flow/reset persistence is tested separately.

| Position | Gross fill P&L | Both fees | Modeled carry | Net P&L USDT |
| --- | ---: | ---: | ---: | ---: |
| PEPE LONG | -0.003380 | 0.0030968184 | 0.000000287594 | -0.006477105994 |
| TAO LONG | -0.001000 | 0.0028471200 | 0.000000137582 | -0.003847257582 |
| PEPE SHORT | +0.002080 | 0.0030988464 | 0.000000123143 | -0.001018969543 |
| Total | **-0.002300** | **0.0090427848** | **0.000000548319** | **-0.011343333119** |

All three exits were **DATA_HEALTH**, hence infrastructure-induced exits, not
successful strategy target/stop decisions. Nine signals produced three opened/
closed positions, five entry rejections for unverified/unaligned depth and one
expired unfilled entry. Sixty-five normalization-version events were rejected.
The 207 unresolved transitions include 161 insufficient-full-depth exit checks
and 31 missing/stale marks; they are not 207 positions or 161 executed stops.
No remaining position/pending entry/pending exit existed at the final checkpoint.

Gross positive fill movement was 0.002080 USDT; gross negative fill movement
was -0.004380. Total fees+carry were 434.7756% of positive gross and 206.4688% of
absolute negative gross. On the only gross-positive trade, its own fees+carry
were 148.9889% of its gross gain. Three net losses do not establish predictive
edge, nor justify inverting the signal. Planned losses stayed below their risk
budgets; no observed stop-gap trade exists in this sample. Stop-gap behavior is
a fixture result, not a claimed real stop validation.

## Chronology and execution-cost interpretation

The pipeline requires an actually received later quote plus >=100ms latency
from entry signal/exit request, later journal sequence/provider time, valid BBO,
exact lots/multiplier/tick, current source fees, freshness and verified aligned
full best-level liquidity. Old queued quotes cannot become later observed fills.
Stop overrides target, with adverse observed gap execution; no guarantee of a
stop price or actual maximum loss. Unsupported partial/deeper fills stay
UNRESOLVED, including through outage/rotation/restart.

Observed: provider public BBO, sizes, L2 bridge/sequence, contract fields and
published default taker fee. Assumed: taker execution, 2bps adverse slippage per
side plus tick rounding, 100ms minimum decision latency, full displayed top-level
availability, default carry 0.01%/8h prorated by elapsed time. These are not
exchange-confirmed fills, actual account fee tiers or actual funding debits.

For each position with BBO evidence:
`mid movement - entry/exit half-spreads - adverse slippage/tick - fees - carry = net`.
Gross fill P&L already embeds spread/slippage; they are never subtracted twice.
The report supplies market/direction aggregates, risk utilization, planned versus
realized loss, cost in USDT/bps and modeled break-even mid-price move. A break-even
number is conditional on observed costs, not a prediction of future fees/depth.
For legacy positions without raw source quotes these fields are BLOCKED, never
inferred backwards from rounded fill prices. Custom carry settings must be passed
to position attribution; the historical CLI audits the original default-policy,
flat, zero-flow capture and rejects truncated summaries.

## Operational / account boundary

[Host kit and acceptance procedure](../docs/V33_HOST_ACCEPTANCE.md) includes
least-privilege units, a separate read-only evidence timer, immutable releases,
state separation, controls, health/alerts, storage, WAL backup/restore, archival,
rollback and proof-manifest review. [Future account design](../docs/KUCOIN_ACCOUNT_BOUNDARY.md)
is design only: `account -> instrument -> positionSide`, isolated PAPER versus
ACTUAL account identity, future read-only reconciliation, and prerequisites before
any two-leg experiment. No signed request or private connection is implemented.
The exposed key must be revoked/rotated out of band; it was not used here.

**24h host: BLOCKED — HOST NOT PROVISIONED.** No remote machine was assumed or
silently deployed. Recurring costs require sourced provider pricing plus storage,
backups, traffic and tax; machine pricing evidence is recorded where reachable.

## Delivery status and review

- **Code-complete:** scoped audit fixes and deployment kit delivered; exact final
  commit and verification outcomes below, with blocked evidence clearly separate.
- **Paper-soak-verified:** false; independent >=24h host gate remains blocked.
- **Economically validated:** false; `strategy_validated=false` and
  `production_ready=false`, including when infrastructure CI passes.
- **Live-account-authorized:** false; real 8 USDT never enters paper bookkeeping.

The known repository policy denies Actions PR creation (HTTP 403). No policy or
personal credential bypass was attempted. Open the focused nested Draft PR using
[this exact compare](https://github.com/rzalags-maker/DAIINAS-pROJ/compare/feature/v33-continuous-paper...feature/v33-risk-acceptance).
Neither PR #7 nor stable `daiinas-v1` is merged/changed.

## Final evidence

Final runtime tested: **`93d9a4b1c00a6de165bacf4cdc2d8c8726ae5366`**.

- [Independent original capture + new public integrity run 41252889266](https://github.com/rzalags-maker/DAIINAS-pROJ/actions/runs/41252889266):
  **Success**. Original artifact retrieval/audit, 200/200 tests (zero skipped), new
  first process, restart, replay and integrity verification all passed.
- [Python 3.11/3.12/3.13 matrix 41252889195](https://github.com/rzalags-maker/DAIINAS-pROJ/actions/runs/41252889195):
  **Success**, all three matrix jobs. The original 180 tests were not edited.
- All five service/timer templates pass static `systemd-analyze verify` with the
  local interpreter substituted; no service was started or remotely deployed.
- Original artifact **13061023549**, 28,207,972 compressed bytes, downloaded using
  built-in read-only repository Actions permissions. Archive SHA-256:
  `96238231767ff25ac76292c7458e8bd21547b1a025e7113224f638eb7026cd17`.
  `source_status=VERIFIED_FULL_HASH_CHAIN` checks every journal row/digest through
  the recorded final cursor; source/account integrity and committed checkpoint
  binding pass. Entry/exit BBO, lots/tick/multiplier, fee, freshness, later wire
  time and verified aligned displayed depth pass independently for all three.
- Replaying that **original source** with the audited runtime reproduces original
  cash, fees, carry, realized net, maximum drawdown, cursor and digest exactly;
  see `v33-original-parity.json`. New attribution fields are additive.
- Source storage measured **86,556,672 bytes / 229.749s**; same-rate estimate
  **32.55 GB/day**, illustrative 5x **162.75 GB/day**. The host kit explains why
  default 64 GiB source capacity cannot support 24 uninterrupted hours at 5x.
  Paper write amplification and sustained CPU/RSS are still host measurements.
- Official AWS Lightsail pricing reference retrieved and hashed; $12/month
  2-vCPU/2-GB/60-GB Linux example is a compute-only floor, insufficient storage
  for the retained-backup plan. Larger disk, off-host backup, traffic and taxes
  remain a separate quote; no server purchase/deployment occurred.

Original independently decomposed costs (USDT):

| Position | Mid-price directional P&L | Observed spread | Modeled slippage + tick | Fees + carry | Net | Break-even move bps |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| PEPE LONG | -0.001378 | 0.000962 | 0.001040 | 0.003097106 | -0.006477106 | 19.7540 |
| TAO LONG | +0.000850 | 0.000850 | 0.001000 | 0.002847258 | -0.003847258 | 19.8025 |
| PEPE SHORT | +0.003692 | 0.000572 | 0.001040 | 0.003098970 | -0.001018970 | 18.2305 |

Thus even the two positive mid-price movements did not cover observed/modelled
round-trip costs. This describes these infrastructure-closed observations only,
not expected performance of the strategy.

The **separate new** bounded capture processed 14 scans; 6 closed simulated trades
were all losses, net **-0.030613887172399646 USDT**, final flat cash/equity
**7.969386112827602 USDT**, fees **0.0199429308 USDT**, modeled carry
**0.0000009563723988472224 USDT**. This is new infrastructure evidence, never a
replacement for the original three-trade audit.

Immutable final reports are in `v33-audit-runs/41252889266/`. Top-level
`v33-risk-audit.json` audits the **original** capture, whereas top-level
`v33-first/restart/replay/acceptance.json` describe the **new** bounded capture.
The first two follow-up workflow runs are retained too: their original-source
stage did not verify, although their new public-data stages passed. The final
run above resolves source retrieval; earlier failures are not relabeled successes.
Raw databases and backups are attached to Actions artifacts for 14 days; download
before expiry and retain off-host. Committed reports/hashes alone cannot replay
the raw market stream.

**Outstanding:** owner-created nested Draft PR due existing Actions PR policy;
independent host provisioning/24h soak; physical power-loss/host resource behavior;
independent reconstruction of every intratick drawdown mark; actual funding;
statistically adequate out-of-sample economics; any private account authorization.
The code/test audit delivery is complete within those explicit limits; this is
not approval to merge PR #7 or declare production readiness.
