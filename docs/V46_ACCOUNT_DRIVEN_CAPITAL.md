# v4.6 account-driven capital — Issue #15

Implemented on `feature/v4-ladder-integration`, following integration `1c4c508`.
Read Issue #15 (including its cycle-zero/continuous-loop amendment), updated
AGENTS, #10/#11/#12/#14, owner Model A source and v4.2/v4.5 policies before this
change. No stable merge, new engine, GUI, private request or order gateway.

## Runnable boundary and current truth

`FuturesAccountSnapshot` is a strict normalized **Classic USDT Futures** contract.
It includes complete balances, exposure inventories, settled cash events, equity,
net free margin, disjoint order/position locks, liabilities, collateral restrictions,
unrealized P&L, isolated mode, leverage, timestamp and canonical source digest.
Scope/identity, completeness, timestamps, provenance, cash/equity identities,
exposure margin totals and costs must reconcile. Borrowed/liable opening cash is
blocked pending verified owner-equity normalization; it cannot fund initial rungs.
UTA/Spot, Cross, unconfirmed or
>2x leverage are blocked. A digest detects mutation; it is **not authentication**.
Only the explicitly `MOCK` source is implemented. Even a snapshot claiming valid
signatures cannot claim real authentication: non-MOCK input is blocked.
`NotConnectedAdapter` returns no account; no balance is invented.

`PortfolioLedger.from_account_snapshot(...)` derives its opening amount and policy
from the snapshot, without a seed argument. It records equity, initial usable
margin, account/scope and snapshot provenance in the existing immutable exactly-once
INITIAL_FUNDING transaction. Then journal the snapshot through the existing
CONTROL source/ledger path. For restarts reuse the original stored policy/funding
identity and apply **new snapshots as events**; never call the initializer with a
new opening amount. Unknown/missing verification blocks entries, not monitoring.

`Pipeline.poll_account(adapter)` journals observations through the existing
single SQLite writer. `continuous.service(..., account_adapter=...)` polls at the
clock cadence for `portfolio.account_driven=true`. CLI supplies no authenticated
adapter, hence NOT_CONNECTED. Adapter errors disconnect safely without logging
sensitive exception text or stopping existing public position monitoring.
Existing named fixed-capital v4 profiles remain **hypothetical research controls**,
not account-connected operation. Legacy 8-USDT and historical public smoke evidence
are unchanged; none of those profiles proves current KuCoin account funds.

## Subsequent cycles and accounting

Each accepted complete snapshot plus cash events, dedup IDs, cursor and audit is
committed in the original checkpoint transaction. The existing local PAPER cash
and simulated campaign results remain separate from the exchange-account mirror:
a simulated fill must never be booked as an actual exchange balance change.

The account Model A ladder advances only from identified settled net trade/cost
events. Opening capital is not earned P&L. `REALIZED_NET_TRADE` requires gross,
fees and signed funding attribution matching net. Separate `CASH_COST` handles
fees/funding settled independently (never submit the same cost both ways).
`EXTERNAL_FLOW` changes true observed cash, not earned profit; deposits remain
unallocated. Withdrawal from unallocated funds is supported; one consuming ACTIVE,
PENDING or protected RESERVE blocks for operator reconciliation. **External
allocation is NOT_APPROVED**: `ALLOCATE_EXTERNAL_FUNDING` and unknown event types
are rejected. A future authorized policy must specify allocation and persistent
approval separately; this task does not authorize one.

Unexplained balance deltas, replay ID conflicts, missing data or identity changes
block entries without reseeding. Prior reconciled state stays intact; the report
retains `observed_unreconciled` separately. Unknown orders/positions immediately
pause entries; no cancellation, adoption or fake closing occurs. A fresh complete
consistent snapshot can recover reconciliation, but never clears risk HALT or
operator pause. Repeated old snapshots do not renew freshness or clear disconnect.

## Account-driven sizing and v4.5 units

Each scan uses current account capacity; each proposal and delayed paper fill
rechecks current reconciliation, freshness and free margin. Account Model A has
no 100/300 upper cap. Settled earnings follow existing reserve/pending/recovery
rules. Negative unrealized equity/liabilities reduce effective active/risk;
unrealized gains cannot fund growth. Paper losses tighten this independent
budget, while paper gains cannot masquerade as actual account earnings.

New margin is the tighter of uncommitted ACTIVE and **already-net exchange free
margin**, less incremental paper commitments and fees. Exchange locks are deducted
from ACTIVE, not deducted twice from exchange free margin. Real account and local
paper exposures are independent inventories; copying a paper ID into a fixture
is not evidence of an actual owned exchange fill. Unknown exposure blocks rather
than guessing its risk/ownership. Per-leg <=0.25%, aggregate <=1%, correlation,
3% half-risk and latched 6% HALT, reverse slots, min lot, multiplier, step, liquidity,
spread and all existing execution controls remain enforced.

Account profiles use confirmed ISOLATED 1–2x and a 0.5% adverse **entry-price** stop.
Separately cap fully costed planned loss at 0.5% of campaign allocation, sizing
down or refusing minimum lots. +2% net allocation target includes entry/exit fees,
slippage and modeled carry. It is a goal, not a calibrated expected return or proof
of reachability. Stops/targets still fill only on later observed executable
quotes; gaps can exceed the estimate. Existing research controls retain their
original execution identity and behavior. No strategy profitability is claimed.

## Reproduce acceptance

```sh
python -m unittest discover -s tests -v
python scripts/verify_v46_account.py --output-dir /tmp/daiinas-v46-proof
```

Use a fresh output directory. The bounded acceptance driver uses explicitly
synthetic account observations and a fixed test clock, **not real KuCoin data**.
It runs six changing-equity cycles, five restarts, duplicate delivery and full
source replay using the existing ledger. `status.json` contains exact source
hashes, opening funding, current equity/free margin, ACTIVE/RESERVE/PENDING/locks,
unallocated external funds, risk, connector status and `orders_enabled=false`.
Tests additionally cover the 17/60/99.99/100/175/450/1000/5000 matrix, deposits,
costs, stale/malformed/conflicting scope, margin-driven sizing, LONG/SHORT units,
2/3/5/10 simultaneous paper positions, unknown exposure and actual SIGKILL during
account reconciliation. Original funding SIGKILL tests are retained.

## Remaining authenticated-connection work

Coordinate #12/PR #13; do not merge its older branch over the audited portfolio.
Its offline `ExchangeMirror` already defines complete balances/orders/positions/
fills synchronization and unknown ownership. This change supplies its missing
strict financial projection and atomic portfolio consumer, not another exchange
transport or process. A future adapter must share those completed scopes and
proven ownership, buffer/reconcile private WS with paginated REST, normalize the
complete event/cash history into this snapshot contract, and prove timestamp/gap
and signature/transport validation. Prototype `resume_readonly` is not authority
to bypass this ledger's financial checks.

Still required: approved persistent host/secret manager, separately authorized
General-only read-only connector, actual Classic/UTA and collateral field mapping,
API schema/permissions verification, account-specific fee/funding/fill and isolated
leverage/auto-add-margin semantics, source-response digests, private disconnect/
resync and account-ownership acceptance. UTA remains unsupported until its shared
collateral can be normalized without double counting. No credentials, transfers,
wallet activity, live orders, authenticated account claim or 24h host claim is
included. Exchange RESERVE is virtual bookkeeping, not physical collateral
segregation. Actual account capital remains **NOT_CONNECTED**.
