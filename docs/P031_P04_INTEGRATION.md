# P03.1 / P04 integrated foundation — OBSERVE / PAPER / MOCK only

Baseline: `dff5f8b247c3a52c404a6e9d3b7ebf44c75868f7` (Draft PR #30).
Dependency chain: #26 AccountState → #28 private visibility → #29 macOS lock fix
→ #30 explicit WS snapshots. These remain separate Draft PRs; no automatic merge.
`main` was independently checked at `97af92639b6fe2f30b6f4289e9c5a6827f72da95`.

## One existing engine, not another bot

`continuous.Pipeline` retains its existing single SQLite writer thread,
`SourceJournal`, `PortfolioLedger`, Model A, adaptive selector and conveyor.
An explicit `p04_mock` configuration installs `P04MockWorker` on those same
objects. It does not create a second financial ledger or replace account funding.
All transitions are CONTROL events in the existing append-only source and are
checkpointed by the existing ledger transaction. Gateway submission metadata lives
in the existing `venue_orders`; intents, fills, positions, costs, campaigns and
reconciliation holds reuse the existing structures. Financial settlement remains
in the existing `position_conveyor` / `account_capital` logic.

Profiles without `p04_mock` and ledgers without explicit P04 initialization retain
their existing PAPER behavior. Model A, risk policy, x1–x5 selection, stop candidates,
profit objective, Reserve restrictions and the read-only Bitsgap adapters are not
changed. No real transport is implemented or selectable.

## P03.1 account evidence and unresolved fields

Owner-provided authenticated Mac evidence is preserved as **OWNER-REPORTED LIVE
EVIDENCE**, not independently rerun by this cloud task:

| Field | Existing evidence | Remaining interpretation |
| --- | --- | --- |
| WS connection | 12/12 CONNECTED | Does not prove complete account reconciliation |
| REST/WS balance | 9/12 VALIDATED | Intermittent; freshness and non-atomic windows still matter |
| ONE_WAY | 10/12 recognized | Never automatically change the mode |
| Orders | 12/12 PROVIDER_NO_DATA | Unknown exposure, never zero |
| Positions | 12/12 PROVIDER_NO_DATA | Unknown exposure, never zero |
| Account readiness | PARTIAL / BLOCKED | No live capital admission |

The official trading contract defines the account topics scoped by `em`; the
existing adapter requests the dynamically resolved real KUCOIN_FUTURES code.
No additional account ID or undocumented request parameter has been established
as necessary. Signature/key binding identifies provider scope, not independent
proof of complete venue account identity. The provider documents absence of data
as a possible reason for no subscription, but that does not establish the cause
of this account's null responses or certify a flat account. Do not open a position
to create test data. Do not add a direct private KuCoin connector.

`AccountAcceptance.from_state` consumes the existing AccountState, preserving
VALIDATED / VERIFIED_EMPTY / VERIFIED_ACTIVE / PROVIDER_NO_DATA / UNVERIFIED /
STALE / CONFLICT. It returns redacted field states and exact missing-data reasons.
Evidence age uses original receipt time, not the time the report was created.
Scope, generation, disconnect and expiry remain explicit. A gateway can consume
this evidence through `observe_account` or `Pipeline.observe_account_acceptance`;
only redacted evidence enters the MOCK journal, never wallet values or raw frames.
Optional observed-account blockers can tighten PAPER admission, never fund it.

Equity, true free margin, eligible collateral, full exposure completeness, funding,
settled fees and native protection remain UNVERIFIED. `balance.a` is reported
available for trading, not Model A ACTIVE. `balance.t-a` is not proven committed
margin. Positions' optional isolated-margin fields and delayed order history do
not by themselves constitute a complete financial ledger.

On a trusted owner host, the following outputs a **redacted** P03.1 report from an
existing private checkpoint (the expected market code must come from validated
private discovery, not a hardcoded example):

```sh
python -m daiinas.bitsgap_account_acceptance \
  --state-file /private/path/acceptance.sqlite --scope-ref owner-futures \
  --expected-market-id VALIDATED_FUTURES_CODE
```

Use `docs/BITSGAP_FUTURES_PRIVATE_ACCEPTANCE.md` for the owner-private 60s session
and comparison. Terminal parity remains PENDING_OWNER_VERIFICATION unless the
owner actually completes that same-window comparison. Keep its amounts, account
identifiers and files outside Git/CI/chat. No owner checkpoint or credential was
accessed in the cloud implementation task.

## Typed provider capability registry

`BitsgapCapabilityRegistry` represents documented account/market observations,
order_place, order_detail, order_cancel, position_close, leverage/margin controls,
reduce-only, enum order types and protective semantic dependencies. It records
transport, required parameter types, enum definitions, real Futures market scope,
safety/permission, validation time, rate limits, evidence and verification status.

- DOCUMENTED: public contract or explicitly synthetic catalog; not a live result.
- LIVE_DISCOVERED: authenticated manual/conf_enums declared the capability; no write.
- LIVE_VERIFIED: only fresh validated AccountState **read** observations can promote
  read capabilities. No command write is verified by this release.
- UNVERIFIED: missing/ambiguous schema or unresolved semantic contract.
- UNSUPPORTED: topic not advertised by that catalog, or demo-only on real Futures;
  this is not a blanket assertion that all venue functionality is unsupported.

`discover(existing_observer)` calls only the original signed allowlisted `manual`
and `conf_enums` reads. It never sends a trading command. `validate_parameters`
validates a future request shape but does not send it. Unknown parameters, foreign
em, invalid enums/decimals, missing required fields and unknown transport/schema
are rejected. Omitted params schema is not invented: provider procedure validation
may exist, but local serialization remains unverified. Enum codes are resolved
from conf_enums rather than hardcoded. All runtime write flags remain false.

The gateway receives registry metadata at initialization; default continuous
PAPER integration uses the explicitly DOCUMENTED/SYNTHETIC registry. This is not
new authenticated discovery. Actual catalog metadata can be supplied to the same
worker API on an authorized host; an unavailable order capability blocks intent
submission. Contract changes cannot silently replace the stored permission model.

Official reference reviewed at `d27611b63d56c65c9797e61d34b40b1f175a7664`.
Runtime transport declarations are recorded separately from the public docs'
REST/WS command contradiction. Persistent native TP/SL, trigger reference, partial
child resizing, sibling/OCO cancellation and restart survival remain UNVERIFIED.
Reduce-only being documented/discovered does not verify exchange enforcement.
See `BITSGAP_FUTURES_PROTECTION_AUDIT.md`. No test writes were used for discovery.

## Modes and submission lifecycle

- OBSERVE: boot/restart default. Market/account observation continues; no new entry.
- START_PAPER: explicit local owner command arms existing PAPER, MOCK transport only.
- START_LIVE: explicit BLOCKED result; no live transport exists in this release.
- PAUSE: blocks new entries; existing position reconciliation/risk handling continues.
- STOP: durably disarms, reports STOPPED_FLAT or STOPPED_WITH_EXPOSURE.
- HALT: fail-closed; does not clear existing risk HALT or borrow Reserve.

The existing strategy creates intents with stable source/campaign identities.
The gateway rechecks the existing planner against current risk, quantities,
leverage, lot rules and free-margin budgets. A durable submission claim precedes
the MOCK transport. ACK is not a fill. The original quote/native MOCK lifecycle
provides partial/full fills and modeled protection; no quote touch is a venue fill.
Identical source events/commands cannot resubmit or repeat financial settlement.
Uncertain submission, worker crash or timeout retains an owned reconciliation hold;
restart disarms entries and never blindly retries the uncertain command.

Claimed/ACKed pending orders are not silently canceled or released at TTL/STOP.
Only confirmed no-fill MOCK cancellation/rejection or validated existing native
MOCK fill evidence can release their obligations. A late ACK after STOP retains
STOPPED_WITH_EXPOSURE. Confirmed partial exits retain the residual position and
coverage, and no WIN/slot release occurs before final reconciliation. External
MOCK closure after a restart is fed through the same native receipt validator,
fee attribution and exact-once campaign settlement. Pending unknown outcomes block
replacement. Existing native MOCK fill IDs and owned order IDs are reused.

Invalid/conflicting gateway commands are transactionally quarantined with a fixed
redacted rejection reason using a SAVEPOINT inside the existing ledger transaction.
They cannot poison the append-only input journal or partially post money.

STOP acknowledgment means the running single writer committed the command, with
its source sequence in status. The CLI's SOURCE_ACCEPTED_AWAITING_WORKER is NOT
that acknowledgment. Actor/idempotency here is a local filesystem-authorized MOCK
control contract, not a deployed authenticated mobile/remote control bridge.
Disconnect/reconnect resets new-entry authorization to OBSERVE; fresh evidence
alone does not re-arm. Startup never resets funding or historical campaigns.

## Run without changing existing funding

Add only an explicit `"p04_mock": {}` section to a reviewed copy of the existing
v4.7 MOCK profile. Keep its funding identity and the same source/paper databases.
Do not regenerate opening funding or overwrite historical checkpoints. An empty
section selects explicitly modeled TP/SL/reduce-only support, not real protection.
Set `protective_tp_sl:false` to verify missing MOCK protection blocks admission.

```sh
python -m daiinas.continuous run --config /path/reviewed-v47-p04.json \
  --source-db /path/existing-source.sqlite --paper-db /path/existing-paper.sqlite
# From a second owner terminal while the worker is actually running:
python -m daiinas.continuous p04-mode --mode START_PAPER --actor local-owner \
  --command-id unique-owner-request --config /path/reviewed-v47-p04.json \
  --source-db /path/existing-source.sqlite --paper-db /path/existing-paper.sqlite
```

`--start-session` explicitly starts PAPER at worker launch. Without it the worker
keeps observing. `start`, `pause`, `stop` also map to the P04 mode control when the
profile explicitly enables it. `resume` clears only existing PAUSE; it does not
clear HALT or replace the need to re-arm. START_LIVE is blocked even at the CLI
before a command is journaled. Do not queue START while the worker is offline and
assume it is active: restart disarms and requires a new explicit command.
An explicit --session-seconds duration remains honored; zero means until STOP.
Normal worker exit durably STOPs. Gateway and existing observations share the one
writer thread; there is no additional trading runtime or live order transport.

Offline reproducibility:

```sh
python -m unittest discover -s tests -v
python scripts/verify_p04.py
```

The proof uses generated synthetic market/account fixtures with the actual engine,
not an alternative strategy. It reports no private values and is included in the
ordinary Python 3.11–3.13 regression workflow. PAPER results do not prove profit,
live protection, production latency, uptime or autonomous deployment readiness.

## Release assessment

The implemented foundation is reviewable for OBSERVE/PAPER/MOCK integration.
It is not FULLY READY for live trading. Supported command shapes suggest a future
Bitsgap gateway may be technically possible, but account-specific permissions,
complete financial/exposure reconciliation, live schema/transport semantics,
persistent native protection and an owner-authorized supervised control plane
must be independently proven. No native persistence claim follows from MOCK TP/SL.
No live write transport or auto-mode/margin change is implemented. All current
live admission remains NO_TRADE_ACCOUNT_NOT_RECONCILED.
