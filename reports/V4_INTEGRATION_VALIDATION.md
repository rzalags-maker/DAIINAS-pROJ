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

Local complete suite: **240 tests passed**, preserving 200 audit-lineage tests,
15 original Ladder tests, and owner timing fix. Tests explicitly label synthetic
fixtures. The actual SIGKILL test kills after OPENED/fee but before checkpoint,
then recovers one position/fee from the already-committed source record. A separate
fixed-precision test demonstrates why recurring carry must not produce a 10^-26
association discrepancy in an exact cash/allocation identity.

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

Final public-data CI and comparison are running. The final evidence section will
record exact tested commit, Python matrix, source counts/digests, restarted money,
net/fees/carry/drawdown and identical-source 8/60/100 M0–M3 results after inspection.
Cancelled superseded CI attempts are retained as cancelled, never relabeled passed.
A preliminary actual feed/restart/replay result is not a completed comparison.

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
economically-validated=false; live-account-authorized=false. Final code/test
acceptance remains subject to the exact evidence section above.

## Review / PR

Existing repository Actions PR policy returned HTTP 403, "GitHub Actions is not
permitted to create or approve pull requests." No personal-token or policy bypass
was attempted. Prepare the focused nested **Draft** PR with
[this exact comparison](https://github.com/rzalags-maker/DAIINAS-pROJ/compare/feature/v33-risk-acceptance...feature/v4-ladder-integration).
The issue #8 lineage and PR #9 source are included in the review; PRs #7/#9 and
stable `daiinas-v1` remain unmerged. No private account or real 8/60/100 USDT balance
was accessed, merged with simulation or represented as verified.
