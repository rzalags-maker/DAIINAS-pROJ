# P05.1 implementation delivery

Baseline: `4d278da5b0ef13824982f380cb505403455a4ca2` (verified P05).
Implementation branch: `feature/p051-noninteractive-acceptance`.
Review target: `fix/p05-terminal-acceptance-input-20261102`; not main or the audit branch.
Contract: Section 10 of audit commit `d653362090fe3065585218da8b06344338ed2d40`.

## Implemented

- Existing `bitsgap_account_acceptance --observe --seconds 60` now owns signed
  dynamic scope discovery, registry declaration discovery, bounded REST/WS
  observation, redacted session evidence and cleanup. No prompts, market number,
  private checkpoint, second adapter or UI prerequisite. Legacy checkpoint
  reporting remains available. See the updated private acceptance runbook.
- PASS/PARTIAL/BLOCKED describe observation only, independently of permanently
  blocked financial admission. Null inventories remain unknown. Auth/catalog,
  wallet coherence, inventory topics, mode, sample times/counts, snapshot counters,
  terminal parity and financial uncertainty are separated. No amounts, IDs,
  fingerprints, raw frames, keys, signatures or exception values enter reports.
- F1: legacy Futures CLI and AccountState private CLI now enforce the existing
  dual-TTY/non-CI boundary before credential, network or checkpoint access.
- F2: a permanent sidecar lease carries a random writer incarnation; checkpoints
  carry that incarnation and heartbeat. Readers require the matching held lease
  and freshness, and recheck on status access. A new lease cannot revive old
  connected state. SQLite inode locking, schema version and money truth are unchanged.
- F3: the original budget is factored into a dependency-free module and re-exported
  for compatibility. Every stream factory installs/reuses it before REST setup,
  subscriptions and snapshots; reconnect shares the same topic windows. Existing
  read-only allowlists and Ed25519 canonical signing bytes are unchanged.
- The existing main-only manual workflow uses the redacted acceptance command.
  Standard CI installs the WS dependency and runs the full 3.11/3.12/3.13 matrix.
  No authenticated workflow was dispatched by this task.

## Offline evidence

Full Python 3.12 regression: **530 tests, PASS**. Full Python 3.13 regression:
**530 tests, PASS**. The 509 original tests remain; 21 tests were added for
headless session orchestration, redaction, normal stop, null/empty/active data,
invalid/schema/scope/stale/phase/reconnect evidence, private boundaries, lease
handoff/heartbeat, real parent/child missing-credential handling, hard deadline
and real budget saturation across reconnect. Existing protocol tests now wait
for budgeted startup instead of assuming unlimited requests; assertions remain.

P04 eight-scenario MOCK acceptance: PASS. Existing v4.6/v4.7 synthetic proofs:
PASS. Model A, capital/risk, P04/execution and signing source files match baseline.
No external timer helper or monkey-patched asyncio is used. Local commands used
a shell timeout as a fail-safe; standard GitHub CI needs no helper. Cloud sandbox
thread-wakeup restrictions required normal unsandboxed test execution, with no
network bypass. All fixtures/keys are synthetic; no owner checkpoint was read.

Python 3.11 is verified by the pushed-commit CI matrix, not claimed as a local
interpreter result. Consult the commit's GitHub Actions status for all three
versions and downloadable regression logs; no unexecuted CI result is asserted
in this pre-push report.

## Boundaries and unresolved external evidence

This increment has **not** performed authenticated live acceptance and does not
claim owner-Mac execution, terminal parity, complete exchange exposure, verified
free margin/equity, persistent native protection or Model A funding. Existing
provider-null semantics and financial/protection uncertainty remain explicit.
`NO_TRADE_ACCOUNT_NOT_RECONCILED`, routing/live DISABLED, owner-required ONE_WAY
and all native risk restrictions remain unchanged. No API key, margin, mode,
leverage, order, ledger funding, merge or deployment operation was performed.

The command's hard wall-clock ceiling is `seconds + 85`: setup allowance 65s,
requested observer window, cleanup allowance 20s. Expiry is BLOCKED with a fixed
reason; partial worker output/stderr is never forwarded. Ordinary bounded stop
is DISCONNECTED and retains historical during-session evidence without renewing
its timestamps. This command writes no account files by default.

## Review and integration

Review only this branch's diff against the exact P05 parent; the earlier Draft
PR dependency chain is still required. Do not merge directly into old main or
activate live routing. After reviewed integration, an already provisioned approved
host or the existing manually dispatched main-only workflow can execute the one
redacted command. No key extraction, new owner Mac test or account value is
requested for this delivery. Any PASS remains observation-only.
