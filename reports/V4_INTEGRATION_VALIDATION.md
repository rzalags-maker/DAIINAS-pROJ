# Issues #10/#11 — Capital Ladder and adaptive PAPER implementation

**LIVE ORDERS DISABLED. No private exchange requests, secrets, orders or wallet
transactions.** No stable merge or activation of an actual KuCoin account.

## Baselines, source and scope

Base: reviewed issue #8 lineage `8101e5f12bc3ecb76e478dc761cb85c7a626e008`.
Math/source: PR #9 branch `60afe06b346a9f3fca0a55395b2f5ac330520c42`.
Stable remains `8587154e67a47c7924c133b1ef859ff675a9a50e`; v3.3 feature remains
`4644bdd677318a780cd9880933108228f6f39412`. Dedicated branch:
`feature/v4-ladder-integration`, targeting `feature/v33-risk-acceptance` for review.

AGENTS.md, full issues #10/#11, PR #9 and the entire owner source were read before
code changes. The 292-line source is preserved verbatim, including alternate B;
selected Model A is executable. Owner ACK/scan/pong timing stabilization is retained
without weakening the expected subscription, scan or heartbeat results. No audit
rollback, implicit account migration or rebuilding the public collector/backtester.

## Implementation and evidence matrix

| Component | Prior / change | Deterministic evidence | Remaining boundary |
| --- | --- | --- | --- |
| Ladder | Standalone math -> versioned in the audited SQLite account transaction | All exact forward/reverse examples through 700; 49.99 pending; deficit/recovery; original math tests preserved | Real positive expectancy unproven; no forced economic expansion |
| Money | One legacy float account -> separate Decimal18 portfolio accounts | Exact cash/R/A/P/deficit/closed/open-fee identity; fees/carry once; conservative quantum; actual SQLITE_FULL and SIGKILL recovery | Model rounding and carry are assumptions, not exchange settlements |
| Positions | One leg -> up to ten independent `(symbol, positionSide)` legs and campaigns | 2/3/5/10 simultaneous cases; margin/gross planned risk; later exits; active-cap reversal and pins | Partial/deeper-book fills unsupported -> UNRESOLVED |
| Risk | Existing gate preserved plus active-only allocation | <=0.25% per leg, <=1% aggregate, correlation/unknown grouping, 3% half-risk/6% HALT, fee refresh, spread/carry/min-lot | Stops are not guaranteed; tail/liquidation obligations can exceed active |
| Observable state | Pressure-only control -> independent per-token time-indexed regimes | Same timestamp UP/DOWN/RANGE/UNKNOWN; reversals; stale book; source chronology; no future certificate | Heuristic hypotheses, no calibrated probabilities or expected returns |
| Hedge | One direction -> conditional second leg plus explicit symmetric control | Zero gross ideal pair / negative costs; winner-loser trap; bidirectional path; integrated unfilled losing residual; no premature rung | Current genuine held-out advantage UNSUPPORTED; M3 does not manufacture a certificate |
| Operations | Existing writer/collector/backup reused | Async pipeline/preflight pins, restart/replay, idempotence, backup; isolated hardened v4 units statically checked | Independent >=24h host BLOCKED; no remote deployment/alerts sent |

Local complete suite: **242 tests passed**, preserving 200 audit-lineage tests,
15 original Ladder tests, and owner timing fix. Tests explicitly label synthetic
fixtures. The actual SIGKILL test kills after OPENED/fee but before checkpoint,
then recovers one position/fee from the already-committed source record. A separate
fixed-precision test demonstrates why recurring carry must not produce a 10^-26
association discrepancy in an exact cash/allocation identity.

## Audit corrections made during integration

- **P1 — comparison validity:** a reproduced test observed one directional OPENED
  event in M2 on a persistent UP-only fixture, where the symmetric control must
  abstain. Mode dispatch now prohibits the directional fallback. Matched-lot
  pairing is required; failed second entry requests a verified later exit of the
  unmatched first leg. Tests explicitly distinguish this from a residual leg
  after a genuine two-leg campaign winner closes.
- **P2 — exposure measurement:** entry-cost notionals are separately labeled from
  current gross/net mark exposure. Equal contract lots have zero current net base
  delta at a common mark. Finalized campaigns explicitly zero remaining exposure;
  unresolved marks never become executable positive campaign P&L.
- **P1 — exact-reconciliation liveness:** analytic recurring-carry fixtures show
  association-dependent Decimal context rounding of 10^-26 can falsely break an
  exact money identity. Fixed conservative 10^-18 cash precision prevents it.
  This is a model/fixture finding, not a claim of lost real money or an observed
  exchange accounting error.

All changes retain the issue #8 SQLITE_FULL memory rollback, flow-adjusted marks,
stale-feed health, backup maintenance locking and existing financial evidence.
Owner source SHA-256:
`b5e12d6da3aa663e1c04cd3012a5bac6fa7fdd57de906b7de052d1ce1f5f8a70`.

## Financial interpretation

Authoritative invariants and lifecycle are in [the integration contract](../docs/V4_LADDER_INTEGRATION.md).
Reserve/pending never fund fees, margin or losses. External simulated deposits are
quarantined and do not activate/scale/unhalt the Ladder. A slot is an allocation,
not a loss limit or order. All pending/open legs count toward gross slots/risk.

At exact active rung boundaries, entry costs/adverse marks can immediately reduce
capacity. The engine requests controlled later-quote whole-leg exits, preserving
pins and unresolved risk rather than fabricating liquidity. For a 100 account,
R50/A50 funds two candidates before costs; neither a persistent two-leg hedge nor
a profitable lot is guaranteed by that fact. Nominal per-slot capacity is capped
at 25 through expansion and the committed active/ten budget after scaling.

Both realized legs and open losing exposure belong to a campaign. A winner alone
cannot increase the Ladder; an unmarked losing residual makes campaign net
UNRESOLVED. Campaign target ~2% net on allocation is aspirational, distinct from
2% price movement or one-slot return. Ordinary risk exits can preempt it.

`maximum_drawdown` is the active-equity safety metric; total account performance
is separately `account_maximum_drawdown`. Cash and unverified indicative equity
are separate; `executable_equity=null` when full verified execution is unavailable.
Fee/carry/gross rounding is disclosed at 10^-18 USDT, and the execution version
is immutable. Older prototype v4 files are refused rather than silently migrated.
The v3.3 audit results and owned 8-USDT account remain unchanged.

## Real-data validation

**PASSED** — [full acceptance run 41264446798](https://github.com/rzalags-maker/DAIINAS-pROJ/actions/runs/41264446798),
exact tested revision **`5f1f51c5e6f5b57daf4a32f264e08ce100eab7f2`**.
The original-source audit, all 242 tests (zero failures/errors/skipped), legacy
first/restart/replay, independent legacy verification, v4 first/restart/replay,
independent v4 money/backup verification and M0–M3 comparison all succeeded.
[Matrix run 41264446510](https://github.com/rzalags-maker/DAIINAS-pROJ/actions/runs/41264446510)
also succeeded on Python **3.11, 3.12 and 3.13**. Reported implementation module
SHA-256 hashes match the final worktree; subsequent documentation/review changes
do not change the tested engine.

The actual new KuCoin recording spans **230.324 seconds**, observes **717 public
contracts** across **16 as-of scans**, and retains **72,877 journal records**:
**81 execution prints**, **67,108 L2 events** and **5,348 ticker events**. The first
process's final observed set was SOLUSDTM/ETHUSDTM/HYPEUSDTM; the restarted process's final
selection was ENAUSDTM/ETHUSDTM/TRXUSDTM. These are observed selected markets,
not a claim of full-market L2/trade-tape completeness.

Both real processes passed integrity checks with different boot IDs. The combined
run observed heartbeat replies, public renewal/reconnect, 87 subscription ACKs,
one retired market with 3 unsubscribe ACKs, 68 snapshots and verified book
recovery. There were **8 snapshot-restore retry-limit errors** across the two
processes, causing recovery rather than invented fills; 868 normalization-rule
version frames were rejected. Those events are retained, **not rejected trades**.
Frequent book recovery is an unresolved uptime/quality concern for the future
soak; passing a fail-closed infrastructure smoke is not production readiness.

There were **5,279 accepted quote decisions, zero entry signals, zero filled or
closed legs, and zero remaining positions/pending risk** in the v4 process pair.
The final observed regimes were UNKNOWN with NO_TRADE because no cost-adjusted
observable opportunity qualified. Real data did not exercise open multi-leg
recovery here; that behavior is covered by explicitly synthetic integrated and
actual-SIGKILL fixtures, not relabeled real observations.

| Separate initial account | Modes evaluated on exactly the same source | Final cash/equity per mode | Net P&L | Fees/carry | Active/account max DD | Trades/open legs |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 8 USDT | M0, M1, M2, M3 | 8 USDT | 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| 60 USDT | M0, M1, M2, M3 | 60 USDT | 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| 100 USDT | M0, M1, M2, M3 | 100 USDT | 0 | 0 / 0 | 0 / 0 | 0 / 0 |

The 100-USDT account reconciles exactly to **R50 / A50 / P0 / deficit0 / two
funded candidate slots**. The 8/60 accounts remain bootstrap with one candidate.
Win rate, profit factor and average return per trade are undefined (no fills),
not zero-confidence estimates of strategy quality.
NO_TRADE is a valid safe execution outcome, **not** evidence of positive expected
returns, validated prediction, feasibility of every 8-USDT contract or a demonstrated
2%-net campaign. All twelve held-out closed-leg counts are zero; confidence
intervals are null and multi-day out-of-sample/hedge advantage remain UNSUPPORTED.

Offline replay exactly matched the restarted v4 report; independent Decimal
cash/net/fees/carry and reserve identities passed, and WAL-safe backup validated.
Source UUID: `87a1ce505a4a4656a9c31506867200a1`.
Input chain: `93c6abdac940ec29756c54b072df45d243082c8e5b93860d05c7eaa735d228c2`.
Backup SHA-256:

- SOURCE: `4daeb5c39b3d879b92d4a0465a40f93bc66a75fcffe9544aa5dbc20e5875184d`
- PAPER: `f504ecc988fa0c7f1f2701052a14bdf1241ecc0ed73fa63f37c820a91586f94e`

Machine-readable evidence is `v4-validation.json`, `V41_HEDGE_COMPARISON.json`,
`v33-ci-status.json` and immutable `v4-runs/41264446798/`. The original issue #8
three-trade source audit and financial replay equality also passed unchanged.
Raw SQLite sources/accounts/backups and all comparison ledgers are Actions
artifacts retained **14 days**; download before expiry for independent long-term
reproduction. Committed reports/hashes do not replace raw datasets.

Earlier superseded runs are retained with their cancelled/skipped/failing stage
outcomes. Some passed partial feed checks, but none is relabeled a successful
complete comparison. Only the final all-stage run above supports this acceptance.

## Research and operational limits

- No proven alpha, genuine hedge advantage, calibrated utility/probabilities or
  statistically adequate multi-day out-of-sample study. Confidence bounds remain
  null on sparse dependent observations. Current M3 can legitimately equal M1
  because unsupported hedge evidence must cause abstention.
- M2 is an explicit negative-control capability, not automatic hedging for every
  token. M0/M1/M2/M3 consume identical chronological data and independent accounts.
  Training/validation split is descriptive as-of warmup/held-out evaluation of
  heuristic states, not a claim of a trained validated return model.
- A research evidence certificate is a version/source/policy/chronology guard;
  its authenticity/statistics still require verified artifacts and review. It
  cannot authorize live trading. Actual data do not generate a positive claim
  merely because its schema is valid.
- Unknown correlation is conservatively grouped. No exchange hedge-margin credit,
  complete trade-tape guarantee, full-depth/partial fills or liquidation simulator.
  Commission floors, latency, slippage and elapsed carry are modeled assumptions.
- New protected state directory and five v4 service/timer templates are prepared
  and statically checked. Follow the audited host procedure with v4 paths/config;
  no persistent host has been provisioned: **BLOCKED — HOST NOT PROVISIONED**.
- UK legal/product eligibility remains OPEN, independent of technical account mode.
  The previously exposed credential must be revoked out of band; it was not used.

**Statuses:** implementation delivered; paper-soak-verified=false;
economically-validated=false; live-account-authorized=false. Code/test acceptance passed as recorded above. Real open-position soak and
economic validation remain unverified; no live authorization follows.

## Review / PR

After all verification gates passed, [fresh review workflow 41265667565](https://github.com/rzalags-maker/DAIINAS-pROJ/actions/runs/41265667565)
attempted the explicitly requested nested Draft PR. GitHub returned **HTTP 403**:
**"GitHub Actions is not permitted to create or approve pull requests."** Exact
outcome and tested revision are committed in `v4-pr.json` and immutable
`v4-review-runs/41265667565.json`. No Draft PR was created by this workflow.
No personal token, credential discovery or policy bypass was attempted. Subsequent
pushes retain the denial without retrying; an owner may retry only after changing
the repository Actions PR setting.

The implementation is concrete and reviewable at
[this exact Draft PR comparison](https://github.com/rzalags-maker/DAIINAS-pROJ/compare/feature/v33-risk-acceptance...feature/v4-ladder-integration).
Target: `feature/v33-risk-acceptance`; head: `feature/v4-ladder-integration`.
PRs #7/#9, the original feature/audit branches and stable `daiinas-v1` remain
unmerged and unchanged by this task. No actual 8/60/100-USDT account was accessed
or combined with the simulation.
