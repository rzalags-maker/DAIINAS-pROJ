# v4 durable Capital Ladder integration — issues #10/#11

**LIVE ORDERS DISABLED.** Opt-in public-data PAPER research. No exchange orders,
wallet transactions, private connector, secrets or live-mode switch.

## Source and lineage

Read [AGENTS.md](../AGENTS.md), the [complete 292-line owner source](OWNER_CAPITAL_LADDER_SOURCE_2026-11-01.md),
[canonical Model A mathematics](V4_CAPITAL_LADDER.md), and draft PR #9.
The unabridged owner source is preserved byte-for-byte. Alternative fixed-50%
Model B remains a counterfactual described in that source, not the executable
allocation policy. This branch starts from issue #8 audit commit `8101e5f`, then
cherry-picks PR #9's seven source/math/test/instruction commits, including its
condition-based ACK/scan/pong timing fix. It does not revert the audit lineage or
merge PRs #7/#9 or stable `daiinas-v1`.

## Existing machinery, new account version

`PortfolioLedger` subclasses the audited `PaperLedger` transaction/deduplication
engine. A narrow event hook lets the portfolio dispatch state while retaining
source digest/sequence validation, append-only audit, atomic checkpoint, FULL
SQLite synchronization and rollback (including SQLITE_FULL auto-rollback).
`Pipeline` still has one writer thread; the source commits before money state.
The same `ContinuousObserver` handles public tokens, heartbeat, renewal, metadata,
3–8 nominal deep markets, ACKed in-session rotation and verified L2 bridges.
Position/pending symbols become durable pins, up to ten gross legs. No collector,
backtester or legacy account was rebuilt.

New owned SQLite role: `v4-paper-portfolio`, with immutable source/policy/schema
and execution-version identity (`v4.1-decimal18-v2`). Prototype v4 account files
from earlier execution versions are refused; replay their public sources into a
new account file instead of deleting identity or silently migrating money. A v3.3 file is rejected, never migrated or reset. Legacy `v33-paper-ledger`
and Binance backtests remain available. New 8/60/100 scenarios have separate
initial capital, policy, source UUID and default paths:

| Configuration | New default source / paper files |
| --- | --- |
| `configs/v4-8.json` | `state/v4-8-source.sqlite3`, `state/v4-8-paper.sqlite3` |
| `configs/v4-60.json` | `state/v4-60-source.sqlite3`, `state/v4-60-paper.sqlite3` |
| `configs/v4-100.json` | `state/v4-100-source.sqlite3`, `state/v4-100-paper.sqlite3` |

Prices/public measurements reuse existing normalization and adverse tick fill
math. Money, fees, carry, allocation, reserve, pending and deficit are Decimal
strings, not float thresholds. Cash debits/credits use a fixed 10^-18 USDT ledger
quantum; fees/carry round upward and gross fill P&L rounds downward conservatively.
This disclosed model rounding prevents association-dependent repeating-decimal
carry from breaking exact reconciliation. It is not an exchange settlement rule.
Drawdown and descriptive statistical measurements
are numerical metrics; risk thresholds use Decimal active-equity calculations.

## Authoritative capital mathematics and invariants

- Below 100 settled USDT: one feasible candidate, including 8/29/60. At 100,
  reserve 50, active 50, two nominal 25 slots. No minimum-lot guarantee.
- Each +25 settled net increases funded capacity through 3/4/.../10 at totals
  125/150/.../300. At 300: R50/A250. Thereafter full +50 chunks alternate RESERVE,
  ACTIVE. Incomplete chunks stay pending and cannot finance fees/margin/losses.
- At 330: R50/A250/P30; 350: R100/A250; 400: R100/A300, ten nominal 30 budgets;
  450: R150/A300; 500: R150/A350; continue indefinitely, maximum ten legs.
- Debit active only. A250 -> -40 -> A210/8; +14 -> A224/8; +1 -> A225/9;
  +25 -> A250/10. After R100/A300 -> -60, restore A240 to the committed A300
  before more reserve/active growth. Loss beyond active is explicit deficit.
- Negative marks latch slot capacity downward. Positive unrealized rebound does
  not promote it; only settled positive results can restore rungs. Book/mark
  uncertainty blocks entries. Excess positions remain pinned with controlled
  later-quote exit requests; REDUCE currently closes whole legs, not partial lots.
- Before ten, a slot's allocation is capped at 25 (bootstrap uses its available
  active budget). After scaling, nominal cap is committed active / ten, further
  limited by current active per funded slot. Losses do not enlarge that cap.
  This budget is neither a margin mandate nor an allowed stop loss.
- All source forward/reverse tables through 700, deficits, exact partial 49.99,
  multi-step jumps and the illustrative `25 * 2% = .50; 25/.50 = 50` arithmetic
  are tests, never forecasts. Canonical exact rung thresholds take precedence
  over the archived optional suggestion for an additional unspecified buffer.

The engine keeps real cash movement separate from campaign allocation settlement:

```
ladder_total = R + A + P - deficit = initial + settled_campaign_net
cash = ladder_total + quarantined_external_flows
       + closed_leg_net_in_unsettled_campaigns - entry_fees_of_still_open_legs
marked_equity = cash + marked_open_gross - uncharged_exit_fees - accrued_model_carry
```

A leg entry debits its fee once. Margin is a reservation, not a second debit.
An exit credits gross minus exit fee/carry; its entry fee was already paid.
Individual leg results reconcile immediately in cash, but a campaign's net is
passed to `CapitalLadder.realized_result` only when all its legs/intents finalize.
A closed winner cannot fund a rung while its losing opposite leg remains exposed.
Settled campaigns move to an immutable table, not an unbounded checkpoint map;
source/dedup/audit history remains immutable. Recent reports are bounded; full
records stay in SQLite.

External simulated deposits are quarantined, not strategy profit, ladder growth,
margin or automatic HALT release. Withdrawals may remove only quarantined flows;
other capital reallocations require a future reviewed policy. There is no actual
wallet or exchange balance behind any scenario.

## Risk hierarchy and entry/exit lifecycle

1. Current contract identity, lots, multiplier, min notional, leverage limit,
   source taker fee and valid noncrossed two-sided quote.
2. Candidate signal/market quality, aligned verified L2, quote age, displayed
   opposite-side full depth, spread budget, drift and pending TTL.
3. Later actual wire receipt, later provider timestamp/source sequence and >=100ms
   latency after intent/request. Queued old quotes cannot become later fills.
4. Funded capacity (gross legs plus pending), active-only margin <=80%, nominal
   allocation cap, planned per-leg <=0.25% active (half after 3% active DD),
   aggregate <=1% active. Remaining aggregate risk is divided across free slots.
5. Full planned loss reserves both fees, adverse stop execution and modeled carry
   through maximum holding time. Fee/spread changes revalue remaining stop risk;
   violations request reduction. Gaps can exceed every planned limit.
6. Correlation uses aligned publication-time 1s return buckets, >=12 overlapping
   samples. Unknown correlation is conservatively grouped; |rho|>=.85 is grouped.
   Default grouped gross planned risk <=0.5% active, including opposite legs;
   no assumed margin/netting credit. Identical/correlated assets can be rejected
   even with funded slots free. Diversified 2/3/5/10 tests supply prior histories.
7. At >=6% active drawdown, latched HALT. Stops outrank targets; campaign emergency,
   capital reduction, regime invalidation, time and data-health exits follow.
   No fill unless an executable later quote exists. Shared same-side displayed
   liquidity is consumed across all fills in one event, not duplicated per leg.

All admission checks run again at fill. Intent size is never increased to chase
price/capital; a changed larger size requires a new signal. Tick/carry shrinking
also rechecks the minimum economic target. Unsupported partial/deeper-book fills
are UNRESOLVED, not invented closes. Carry continues during stale observations
without cash settlement or fictional funding payments. Freshness failure blocks
new risk throughout the portfolio.

`maximum_drawdown` is the stricter **active-equity risk** metric;
`account_maximum_drawdown` separately measures total account marked equity,
including protected reserve/pending, with deposits removed from performance.
Unverified equity is indicative: `executable_equity=null`; no stale-positive mark
is claimed to be safely realizable.

Funded capacity does not establish positive expectancy. Default operational
expansion beyond the initial slot ceiling is blocked with
`expansion_requires_independently_supported_expectancy`. The explicit
`allow_research_expansion=true` switch is only for controlled PAPER research;
it never changes risk/reserve gates or establishes alpha. Tests use it where
necessary; default live public-data paper configurations do not.

## Run, stop, recover, replay

```bash
umask 077
python -m pip install '.[live]'
python -m unittest discover -s tests -v
python -m daiinas.continuous run --config configs/v4-100.json
python -m daiinas.continuous status --config configs/v4-100.json
python -m daiinas.continuous stop --config configs/v4-100.json
python -m daiinas.continuous resume --config configs/v4-100.json
python -m daiinas.continuous replay --config configs/v4-100.json \
  --source-db state/v4-100-source.sqlite3 --paper-db state/v4-100-replica.sqlite3 \
  --report reports/v4-100-replica.json
python -m daiinas.continuous backup --config configs/v4-100.json --destination backups/v4-UNIQUE
python -m daiinas.continuous verify-backup --config configs/v4-100.json --destination backups/v4-UNIQUE
```

Use 8/60 configs independently. Never point these commands at v3.3 DB files or
change financial policy to reopen an existing account. `stop` pauses entries;
protective exits and collection continue. SIGTERM retains positions. Recover
unapplied source records exactly once at next startup. Full replay requires every
archived source segment. Shared maintenance lock makes backup/rotation coherent;
PAPER copies before SOURCE. Replaying twice cannot repeat fees, fills or settlement.

Tests include actual process SIGKILL after OPENED/fee before checkpoint, actual
SQLite FULL, source-before-ledger recovery, explicit exception rollback, multiple
positions, later stop gaps and missing depth, fee refresh, stale carry, pending
pins across scan/unavailability, asynchronous writer/preflight, replay and backup.
Synthetic fixtures are identified as such; they are not actual market returns.

## Independent host and operational gates

`deploy/daiinas-v4.service`, health service/timer and sample service/timer use
unprivileged `daiinas`, hardened filesystem/address restrictions and a dedicated
`/var/lib/daiinas-v4-100` directory. They passed static systemd syntax verification
with the local interpreter substituted; no server was installed or started.

Apply [the audited host acceptance procedure](V33_HOST_ACCEPTANCE.md), substituting
v4 unit names, `configs/v4-100.json`, and explicit v4 database paths. Provision a
reviewed immutable release, persistent capacity, public HTTPS/WSS access, NTP,
off-host backups, independently monitored health timer and tested alert hook.
Health sampling now includes all portfolio positions/pending pins. Do not send
an alert containing session URLs/tokens. Financial history is not silently pruned.
The inherited 64-GiB DB ceilings and free-space reserve can stop a high-rate run;
size and review capacity before the soak, including WAL, archives and backups.

**24h gate remains BLOCKED — HOST NOT PROVISIONED.** New v4 needs its own real
24h position/pin/rotation/reconnect/restart/restore/resource evidence; neither
v3.3's prior smoke nor v4's bounded CI is that proof. Future reserve isolation
requires physically unpledged collateral, never a label within Cross Margin.
UK product eligibility remains OPEN. The previously exposed key must be revoked
out of band and never used here.

See [v4.1 tactics and limitations](V41_HEDGE_STRATEGY.md) and
[verified results](../reports/V4_INTEGRATION_VALIDATION.md). No merge or live
account authorization follows from code, unit tests or a paper result.
