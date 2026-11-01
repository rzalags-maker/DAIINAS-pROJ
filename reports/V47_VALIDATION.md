# v4.7 PAPER validation

Implemented on `feature/v4-ladder-integration`; tested source commit
`e443ddc0cc287fcd1c87bf13515a7532d3b49114`. Model A and `risk.py` are unchanged
from the verified v4.6 branch. No stable branch or draft PR #7/#9 was merged.
Actual authenticated KuCoin account: **NOT_CONNECTED**. Live routing: **DISABLED**.

## Executable changes

The existing single-writer `PortfolioLedger` now selects per-leg x1–x5 with
40 coupled price-stop/fee alternatives, ranks the complete supported public
contract catalog, rotates a bounded deep shortlist, preserves pinned risk, and
runs validated entry/protection/net-target/partial-exit/replacement cycles.
All paid cash components and final campaign settlement use the same current
account reconciliation and Model A ledger. There is no second capital allocator.

Market IOC fills require later executable quotes, latency, drift, lot and verified
depth checks. TP touch is not a fill. Both price stops (0.5%/1%) keep campaign
money risk <=0.5% allocation, per-position <=0.25% ACTIVE, gross portfolio <=1%,
existing correlation, available-margin, drawdown and loss-recovery gates.
Full-margin x5 cannot bypass those limits. Maker/maker, maker/taker,
taker/maker and taker/taker are separate cost paths; stop-market uses taker costs.
Unconfirmed passive orders stay unfilled until a normalized authoritative MOCK
receipt proves fill/fees/remaining inventory/coverage. No maker fills are inferred
from limit order type or price touch.

Bounded sessions disarm on five-hour virtual expiry or normal worker exit, cancel
known unfilled entries, retain open risk/protection and report STOPPED_FLAT versus
STOPPED_WITH_EXPOSURE. Restart preserves ledger and latches; explicit
`--start-session` can arm another owner-requested session without clearing HALT or
PAUSE. The inert gateway cannot place, cancel or modify a real order. Native
receipt/protection tests are **MOCK only**, not real KuCoin native-order ACKs.

## Tests

**298 tests pass**, preserving all 271 baseline tests plus 27 v4.7 tests.

- [Python 3.11/3.12/3.13 matrix](https://github.com/rzalags-maker/DAIINAS-pROJ/actions/runs/41277153242): SUCCESS on the tested source.
- Local Python 3.12: 298 tests, 46.463 seconds; Python 3.13: 298 tests, 47.636 seconds.
- End-to-end coverage: independent LONG/SHORT markets; ten correlated and ten
  mixed independent positions; net targets, losses/gaps, partial entries/exits,
  TP nonfill, loss after a profitable partial slice, unavailable protection,
  leverage downgrade/rejection, NO_TRADE, pause, exact-once cash/campaign/funding,
  actual SIGKILL before commit, restart and identical replay.
- Five-hour virtual expiry, explicit rearm, passive entry tail cancellation,
  offline native MOCK close, duplicate WS/REST receipts, sibling uncertainty,
  authoritative exact fees and remaining protection are tested.
- Public snapshot recovery waits for a fresh REST snapshot while retaining strict
  contiguous L2 sequence verification. Failed observations can be quarantined;
  pinned exposure is never unsubscribed merely to make the test pass.

Commands: `python -m unittest discover -s tests -v` and
`python scripts/verify_v47.py --output-dir NEW_DIRECTORY`.
No five-hour real hosted runtime or economic edge is inferred from these tests.

## Actual public market smoke

[Run 41277153258](https://github.com/rzalags-maker/DAIINAS-pROJ/actions/runs/41277153258)
completed SUCCESS with independent cash verification, restart and identical replay.
The immutable reports are in [v47-runs/41277153258](v47-runs/41277153258/validation.json).

| Observation | Verified result |
|---|---:|
| Public catalog contracts | 717 |
| Journal duration | 130.571 seconds |
| Public trade executions | 133 |
| Sequence-validated L2 events | 37,549 |
| Bid/ask events | 2,049 |
| Source cursor | 40,053 |
| Independent deep decisions | 1,858 |
| Executed / rejected entry orders | 0 / 0 (no qualified candidate reached admission) |
| Closed / remaining open positions | 0 / 0 |
| Net P&L / fees / carry | 0 / 0 / 0 USDT |
| Maximum drawdown | 0% (no trades) |
| Final explicitly modeled cash | 200 USDT |
| Win rate / profit factor | Undefined: no closed trades |

The last catalog pulse independently marked 22 LONG, 15 SHORT and 680 NO_TRADE
**observation priorities**; none passed the deeper entry qualification. Unwarmed
5m/15m/1h horizons remain unknown. A short smoke is not an out-of-sample strategy
study. The cash is an explicitly named MOCK Futures scope, not the owner's real
balance: Model A R50/A150/six nominal places. There is no forced six/ten-order burst.

Both worker boots established three public connections/two reconciliations. First
boot received four pongs, restart received two. Snapshot bridges required 12/13
bounded retries; one later sequence gap was rebuilt. The only recorded connection
errors were four deliberate token renewals. Both sessions ended STOPPED_FLAT.
No symbol remained quarantined in the final report. Raw SQLite pairs, synthetic
fixtures, source digests, checksums and proof logs are retained in the run artifact
`v47-public-and-synthetic-paper-evidence` (14-day retention); immutable JSON evidence
and its checksums remain in Git. Source input digest:
`7dbe3dc4ee2301f55b945c979c98b85ea61c820f1e7c3c0fcf26cd2db95856c1`.

Earlier runs **41276729611 and 41276938484 failed** strict synchronization/smoke
acceptance. Their produced reports remain under `reports/v47-runs/`; the first
artifact's SHA-256/provenance is preserved. They were not relabeled successful.
Bounded snapshot backoff fixed the observed retry storm without accepting missing
sequences or treating REST snapshots as verified order flow. The separate existing
[v4/legacy acceptance run 41277153230](https://github.com/rzalags-maker/DAIINAS-pROJ/actions/runs/41277153230)
also completed SUCCESS: all eleven stages, 298 tests, original historical artifact
parity, actual public restart/replay, money/reserve audit and the identical-data
8/60/100 M0–M3 comparison. Its 100-USDT v4 account remained flat at 100 with zero
costs/net/drawdown over 230.227 seconds. This is distinct from the v4.7 smoke.

The **separate legacy 8-USDT account lost money**: five closed trades, zero wins,
net **−0.02358720524548885 USDT**, fees **0.016682568 USDT**, final cash
**7.976412794754511 USDT**, maximum drawdown **0.2948400655686134%**, no open
position. Win rate 0%, profit factor 0. These are actual-public-data PAPER results,
not real exchange fills and not v4.7 returns. The engine's consistency tests
passing does not turn these losses into profitable strategy evidence.

## Synthetic financial acceptance — not real returns

Same existing ledger, synthetic observations and MOCK account, immutable SQLite
backup and identical replay. These manufactured scenarios exercise code paths;
they are not historical or prospective trading performance.

| Fixture | Realized net USDT | Total fees USDT | Final cash USDT | Remaining legs |
|---|---:|---:|---:|---:|
| Net target | +0.532583999266593750 | 0.021615840000000000 | 60.532583999266593750 | 0 |
| Partial stop loss | −0.131717191601114584 | 0.021217020000000000 | 59.868282808398885416 | 0 |
| Ten positions | 0 | 0.125196000000000000 | 399.874804000000000000 | 10 |
| Per-position x5 / constrained margin | 0 | 0.008763720000000000 | 59.991236280000000000 | 1 |
| Partial IOC + net target | +0.062656941090187500 | 0.002543040000000000 | 60.062656941090187500 | 0 |

Carry is modeled and separately preserved in the JSON, not a real funding debit.
The gap-loss fixture demonstrates that realized stop loss can exceed planned loss;
there is no guaranteed execution price. Positive partial P&L cannot grant a WIN or
hide residual losses. Every scenario retains one INITIAL_FUNDING record.

## Remaining deployment dependencies

1. A supervised **on-demand** host with durable single-writer storage, backup and
   restore verification, heartbeat/alerts and an actual bounded-session run. No
   mandatory 24/7 trading. Five hours here is virtual-clock tested only; separate
   24-hour reliability acceptance is unrun.
2. An authenticated owner control channel returning effective worker ACK. Chat/mobile
   control is NOT_CONNECTED. Existing always-restart units need bounded-session
   configuration: normal STOP must not repeatedly restart/rearm; never put
   `--start-session` in an automatic crash-restart command.
3. Separately authorized General-only read-only KuCoin account/collateral,
   positions, orders, fills, actual fee tier/funding and capability normalization,
   plus complete snapshot/stream reconciliation. UTA remains unsupported.
4. A separately authorized and venue-tested real execution/protection adapter,
   including trigger reference, reduce-only sizing, actual stop/TP ACK, sibling
   cancellation, unknown outcomes and emergency handling. Currently only inert
   previews and normalized MOCK receipts exist; no private API or order transport.
5. Longer identical-data chronological/out-of-sample directional/NO_TRADE/hedge
   economic comparisons, actual cost/funding/latency and liquidation validation.
   Approximate 2% NET is a feasibility target, never a promised return. Same-token
   two-leg hedging is not enabled by this directional v4.7 implementation.
6. Reviewable draft PR creation remains blocked by repository policy recorded as
   GitHub **403: “GitHub Actions is not permitted to create or approve pull requests.”**
   No new PR is claimed. The prepared description is `V47_DRAFT_PR.md`; existing
   PR #7/#9 and stable branch remain unmerged.
