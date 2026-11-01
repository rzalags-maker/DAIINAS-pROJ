# Bitsgap Futures account-state foundation (OBSERVE)

Baseline: `97af92639b6fe2f30b6f4289e9c5a6827f72da95`, incorporating the existing
Futures REST/WS observer. This change reuses its signer, transport, schemas and
reconnect loop. It does not rebuild the Spot/Futures adapter or change the engine.

## Evidence and the unresolved null exposure

The owner-provided production runs already established REST authentication,
Futures market resolution, `balance.t/a`, position settings and WS authentication
with balance/settings updates. REST and WS orders/positions returned null.
This increment has not authenticated a new account in the Codex sandbox.

Null cannot determine whether the exchange is empty, the public API lacks scope,
the account is synchronizing, or subscriptions have not yet produced records.
The supplied provider reference says data absence may prevent subscription, but
does not establish which explanation applies to this account. No order is placed
to manufacture data. No undocumented browser endpoint or private KuCoin API is used.

## Service and classification

`daiinas.bitsgap_account_state.AccountState` receives private in-process account
observations from the existing observer and stream, validates them with existing
schemas, and compares the same market, USDT scope and operator namespace.
`scope_ref` is an operator namespace for a key-bound market, not a provider-verified
account ID. The API's ability to identify the exact terminal account is unverified.

| Evidence | Classification |
| --- | --- |
| REST and WS null | `PROVIDER_NO_DATA`; private count remains `UNVERIFIED` |
| One channel missing/null/rejected/malformed | `UNVERIFIED`; never infer zero |
| Both channels contain matching validated explicit `cnt:0` records in the comparison window after subscribe + REST resync | `VERIFIED_EMPTY` for that Bitsgap API market view only |
| Both contain matching validated records with positive count | `VERIFIED_ACTIVE` for that view |
| Different data, mode conflicts, foreign scope or out-of-order evidence | `CONFLICT`; preserve reconciliation hold |
| Expired, slow-window, future-clock or previous-session evidence | `STALE` / `UNVERIFIED`, no current exposure authority |

`VERIFIED_EMPTY` does not prove account-wide exchange completeness or collateral
availability. `exposure_proof_scope` explicitly limits the proof to the API market
view. Account allocation is blocked even if both explicit counts are zero.
No disappearing open order, null frame, or unscoped `{ok,mes}` releases a slot.

Per-channel request-start/receipt windows, generation, quality and private
fingerprints preserve provenance. The clock is local, not provider-signed event
time. Original order `t0` is not reinterpreted as account-snapshot time. WS duplicate
frames do not keep stale evidence fresh; repeated explicitly requested REST reads
can refresh receipt freshness, not attest upstream freshness. Same-window REST/WS
agreement is NOT an atomic snapshot and cannot prove that no event occurred in
between. Unknown financial components remain explicitly `UNVERIFIED`.

After authentication/subscription, the connected account-state stream performs a
second REST observation to narrow the snapshot/subscription gap. It processes
validated WS updates and performs REST refreshes every five seconds while the
connection is active. Each reconnect reauthenticates, resubscribes, changes the
generation and obtains fresh REST observations. Old-generation exposure is never
reused as current. Terminal authentication failures retain the existing fail-closed
behaviour. No schema/validation allowlist was broadened.

## Financial interpretation and Model A

The private view displays `total_reported` and `available_reported` exactly as
validated wallet decimal strings. Neither is silently converted to equity, free
margin, collateral or ACTIVE. No committed-margin subtraction is performed, so
the provider's available figure cannot be debited twice by this service.

Equity, true free margin, committed margin, unrealized P&L, fees/funding and native
position protection remain `UNVERIFIED` until independently documented evidence
is available. Existing optional history/pair reads remain available, but are not
treated as a proven full fees/funding or collateral ledger.

`model_a_input()` consumes the normalized observation interface and returns
`NO_TRADE_ACCOUNT_NOT_RECONCILED`, no eligible capital, Reserve, ACTIVE or funded
slot count, and `funding_authorized=false`. It does not instantiate CapitalLadder,
create INITIAL_FUNDING, overwrite the MOCK ledger, clear risk HALTs, release a slot
or send an order. No existing portfolio/risk/strategy module is modified.
Future enrichment/command-gated execution is a separate layer, not an assertion
that read-only is DAIINAS's permanent functional limit.

ONE_WAY is the owner's configuration requirement. Independently observed position
mode is displayed separately if validated; no mode change is implemented. LONG
and SHORT remain different directional choices, without simultaneous opposite
positions in the same contract under ONE_WAY.

## Private checkpoint and independent bounded worker

Normalized amounts, counts and provenance may be persisted only when an operator
explicitly supplies a local checkpoint path. No raw account frame, credential,
signature, order ID or free-text provider response is stored. The SQLite file is
0600, owned by the current user, regular, non-symlink and single-link. A writer lock
prevents concurrent account observers. SQLite commits checkpoints atomically.
The checkpoint worker requires a POSIX host (fcntl), such as Linux/WSL.
Use a trusted owner-controlled directory and encrypted storage/backups where
required. Do not commit, upload or share this private state file.

Existing REST reads run in a thread. Their state commits are marshalled onto the
same event loop/SQLite writer as WS updates. Bounded shutdown disables late commits
before closing the store, restores the observer's original sink and marks the
connection disconnected. A new worker never trusts a restored authenticated
session: cached data is stale until fresh REST/WS reconciliation. A read-only
status process can inspect a running writer's checkpoint; writer liveness plus
receipt TTL bounds that status, not an independent network request.

On an owner-authorized trusted host with the EXISTING secure Bitsgap key binding:

```sh
python -B -m daiinas.bitsgap_account_state --observe --seconds 300 \
  --scope-ref owner-futures --state-file /private/daiinas/futures-state.sqlite
```

The worker independently processes observations during that bounded interval;
Codex prompts are not needed per event. The host/operator must manage the process.
The default interval is eight seconds; the maximum is one hour per invocation.
This is not a deployment or a cloud-runtime uptime guarantee.

From a second trusted terminal, repeatedly inspect:

```sh
python -B -m daiinas.bitsgap_account_state --status --scope-ref owner-futures \
  --state-file /private/daiinas/futures-state.sqlite --private-panel
```

`--status` reads only the checkpoint and does not load an API key. Private output
requires an interactive terminal and explicit `--private-panel`; it is blocked in
GitHub Actions/CI and on redirected stdout. Cached amounts have their receipt time
and `wallet_amounts_status`; stale/disconnected values must never be called current
free margin. Default output is redacted, excluding balances and account/order IDs.
No path or arbitrary exception text is printed on failure.

## Secure Actions diagnostic

`.github/workflows/bitsgap-account-state.yml` is manual-only, main-branch guarded,
and reuses the existing secret after focused offline tests. It runs eight seconds,
prints only redacted status and never creates a private checkpoint or uploads data.
Private output and checkpoint storage are prohibited in CI at the code boundary.
Exit 2 means the account/financial gate is not reconciled; a failed Actions job
must not be relabeled success merely because balance observations validated.
The script deliberately does not authorize allocation even after a valid balance.

## Tests and verification limits

New synthetic tests cover both-null, explicit zero, active exposure, malformed
balances, dynamic enums/duplicate orders, scope/currency mismatch, stale/duplicate
and out-of-order observations, REST/WS and mode conflicts, subscription gap,
reconnect, private checkpoint recovery, writer exclusion, private CLI redaction,
thread marshalling, preserved optional reads and rejection of all mutation topics.
Existing signing, WS authentication and no-write regressions are preserved.

Normal CI command (Python 3.11/3.12/3.13, existing matrix):

```sh
python -B -m unittest discover -s tests -v
```

The current Codex sandbox returns EPERM when a thread writes to asyncio's local
socketpair, which explains the previously hanging thread-based tests. An external
delivery-only test harness adds periodic LOCAL timer wakeups so thread callbacks
and executor shutdown can progress. It grants no network access, changes no tests
or assertions, and is not installed into production. Report harness use explicitly;
ordinary GitHub runners should use normal unittest. See delivery test logs for
version-specific results and any incomplete runs; never infer live API access
from synthetic tests.

## Remaining acceptance gates

1. Run the new manual diagnostic in the existing secure Actions environment;
   this sandbox has not verified the new service against a live account.
2. Run the bounded worker and private status on a trusted owner host and compare
   terminal/API scope and amounts in the same observation window, without publishing
   them. This establishes repeated private visibility, not automatic funding.
3. Resolve the provider's null semantics or obtain authoritative complete exposure
   records. Until then, orders/positions remain unknown.
4. Verify collateral/free margin, equity, fees/funding, protection and exact account
   identity before any Model A funding. An amount alone is insufficient.
5. Review the patch on the latest main, run ordinary CI including Python 3.11 and
   submit a draft PR. No merge, deployment or live execution is authorized here.


## Issue #25: ordered state and non-mutating admission preview

The authoritative issue was read at https://github.com/rzalags-maker/DAIINAS-pROJ/issues/25.
Fresh Git main was independently verified at the pinned 97af926 commit. Each
accepted state mutation has a durable increasing state_version. Per-field
provenance records the exact LOCAL_RECEIPT_CLOCK_NOT_PROVIDER label; unavailable
financial/protection fields explicitly have no authoritative source or timestamp.
Conflicting evidence is CONFLICT, never a cleared obligation or tradable state.

bitsgap_capital_preview.capital_admission_preview returns a typed, redacted-by-
default report. It reuses CapitalLadder, account_capital.exact and the existing
InertOrderGateway status; it performs no writes or financial settlement. With an
existing ladder object/export it restores a detached copy, preserving activated
stage, reserve, losses and slot latches. It never re-seeds from current wallet
balance, invents deposits or applies P&L to the real ledger.

Without a supplied ledger context, projection is absent. An explicitly selected
initial_scenario can show counterfactual first-allocation math for a fresh reported
wallet total, labelled HYPOTHETICAL_INITIAL_ALLOCATION_FROM_REPORTED_TOTAL. That
number is NOT independently eligible capital. At hypothetical eligible 200, the
unchanged rules compute R50/A150/6 nominal slots; at 300 R50/A250/10. Neither
projection authorizes actual slots, risk budget, funding or orders.

The trusted private status CLI can request this counterfactual view with
--capital-preview --hypothetical-initial alongside --status --private-panel and
the existing private checkpoint/scope arguments. Without --private-panel the
projection's financial values are redacted. Existing-history preview is available
through the typed in-process API; it does not automatically read or modify the
PAPER ledger. Unknown exposure/equity/free margin/fees/protection always yields
NO_TRADE_ACCOUNT_NOT_RECONCILED.

See BITSGAP_FUTURES_PROTECTION_AUDIT.md for the pinned public-contract audit,
including contradictory transport documentation and unresolved native TP/SL
persistence. No write command or protective-order transport was added.


## Authenticated AccountState verification and mode-label fix (2026-11-01)

[Read-only authenticated run 41344889512](https://github.com/rzalags-maker/DAIINAS-pROJ/actions/runs/41344889512)
confirmed the **new AccountState service** captured actual Futures USDT balance
on both REST and WS as `VALIDATED`, while `orders` and `positions`
remained `PROVIDER_NO_DATA` on both transports. It preserved
`READ_ONLY_SAFETY=PASS` and `SIGNED_BALANCE_OBSERVATION=PASS`;
no private account amounts were logged. This is a PASS for authenticated
observation, **not** reconciled collateral, positions or live trading.

Follow-up [authenticated diagnosis run 41345423585](https://github.com/rzalags-maker/DAIINAS-pROJ/actions/runs/41345423585)
proved the existing provider adapter accepted `positions_settings` but the
new AccountState normalized result was `UNVERIFIED`. The live dynamic
Bitsgap `position_mode` enum label is **`ONEWAY`**, whereas the new
service initially required `ONE_WAY`. The bounded normalization maps only
`ONEWAY` to the internal Model A `ONE_WAY` label. Unknown enum labels
remain unknown, and no on-exchange position settings are modified.
Follow-up [authenticated run 41345665215](https://github.com/rzalags-maker/DAIINAS-pROJ/actions/runs/41345665215) verified **positions_settings=VALIDATED** over both REST and WS following the explicit ONEWAY normalization. It also confirmed the observed margin mode remains **UNVERIFIED**, not guessed. [Full GitHub regression run 41345616369](https://github.com/rzalags-maker/DAIINAS-pROJ/actions/runs/41345616369) passed **432/432** tests on Python 3.11, 3.12 and 3.13.

All private capital authorization, venue-wide exposure reconciliation,
persistent TP/SL protection and real order routing remain disabled or
unverified as appropriate.
