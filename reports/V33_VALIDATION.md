# Issue #6 validation record

LIVE ORDERS DISABLED. Public KuCoin data only; all orders, fills, costs and
account balances described here are simulations. No private exchange keys.

## Revisions and evidence

The feature branch is `feature/v33-continuous-paper`, based on unchanged
`daiinas-v1` at `8587154e67a47c7924c133b1ef859ff675a9a50e`.
Existing strategy, risk, historical providers, five-pair service and their 148
tests are preserved. The full suite now has 180 passing tests, zero skipped.

The initial verified real-data run is
[41250115273](https://github.com/rzalags-maker/DAIINAS-pROJ/actions/runs/41250115273),
testing `25c60a1748eacc20d59eabcbec69c78950488705`.
Its immutable machine-readable reports are in `v33-runs/41250115273/`.
Two actual processes consumed 15 scans of 717 observed contracts, 159 public
execution events, 33,822 L2 events and 2,630 ticker events. Process restart,
full offline replay, quote provenance, shared-cash reconciliation and WAL-safe
backup verification passed. Replay matched the restarted ledger exactly.

That brief study closed four simulated trades, all losses: net P&L
-0.021393757195153455 USDT, final cash/equity 7.9786062428048465 USDT.
Two entry signals were rejected; no positions or entry/exit requests remained.
Fees were 0.0137803992 USDT and modeled carry 0.0000013579951535694444 USDT.
These totals include modeled execution effects; carry is not an actual exchange
funding settlement. Eight USDT does not make every contract executable: lot,
margin, depth and risk constraints reject individual candidates without rounding up.

The stream recovered sequence gaps and snapshot restore retries. Those failures
remain visible in reports and audit records. Insufficient verified depth becomes
UNRESOLVED; it never creates an invented closing fill. A short smoke is not a
production reliability or profitability result.

## Final runtime verification

[Run 41251111492](https://github.com/rzalags-maker/DAIINAS-pROJ/actions/runs/41251111492)
tested final runtime commit `81eb0aa89c690722ed48723625afa18431d0f0eb`.
All 180 tests, first process, restarted process, replay and independent
verification passed. Exact evidence is in `v33-runs/41251111492/`; the top-level
`v33-*.json` files currently mirror that run.

| Measurement | Observed / simulated result |
| --- | --- |
| Real public contract observations / scans | 717 / 15 |
| Execution / L2 / ticker events | 149 / 32,244 / 9,275 |
| Signals / rejected entries / expired unfilled entries | 9 / 5 / 1 |
| Opened / closed simulated positions | 3 / 3 |
| Winners / losers; win rate; profit factor | 0 / 3; 0%; 0 |
| Net simulated P&L after modeled costs | -0.011343333118507224 USDT |
| Final simulated cash and equity | 7.988656666881493 USDT |
| Entry + exit fees | 0.0090427848 USDT |
| Modeled carry | 0.000000548318507513889 USDT |
| Maximum marked account drawdown | 0.18861862853939426% |
| Open / pending entry / pending exit at end | 0 / 0 / 0 |
| Restart/replay/backup | Passed; full core report identical |

All five rejected entries lacked verified/aligned executable depth. Sixty-five
market events were rejected for normalization-rule version mismatches rather
than being interpreted under the wrong scan. There were 207 UNRESOLVED audit
transitions, including 161 insufficient-depth exit checks and 31 missing/stale
marks; these are transitions, not 207 separate positions. Three eventual closes
followed data-health exit requests. Sequence gaps and four snapshot-retry-limit
errors across both processes caused resynchronization/reconnect; no fatal error
was reported. This motivates the still-open long-duration reliability gate.

The first process ended with an open PEPEUSDTM position. The second process
resumed the same account and closed it on later observed data. Scan metadata
retained its position pin while it was open.
In-session rotation/unsubscribe is additionally verified by deterministic tests
and the initial real run's unsubscribe acknowledgements. Neither smoke proves
full exchange trade-tape completeness or long-term strategy performance.

## Open gates and review

- **24-hour persistent host: BLOCKED — HOST NOT PROVISIONED.** No independent
  host was deployed. The bounded Actions run does not satisfy this gate.
- Multi-day forward/out-of-sample performance and baseline comparisons are not
  established by this infrastructure smoke.
- Draft PR creation was rejected with HTTP 403: **GitHub Actions is not permitted
  to create or approve pull requests.** No merge was performed. Create the review
  from the [prepared comparison](https://github.com/rzalags-maker/DAIINAS-pROJ/compare/daiinas-v1...feature/v33-continuous-paper),
  or enable the repository setting allowing Actions to create PRs before an
  explicitly requested retry. No personal token is required by the engine.

See [the runbook](../docs/V33_CONTINUOUS_PAPER.md) for source/ledger replay,
operational stop/resume, health checks, backups, archives, host provisioning and
24-hour evidence requirements. Actions source/ledger database artifacts are retained
for 14 days; download them before expiry for long-term reproducibility. Reports
and hashes are committed, but are not substitutes for the raw database artifacts.
