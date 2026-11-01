# P0.2: owner-private Futures acceptance

This extends PR #26 at `3f3baba04392a19946e73c84f4d8c80ea835b504`.
It reuses the existing Ed25519 REST/WS adapters and single-writer checkpoint.
No new provider adapter, trade command, position-mode switch or capital funding.

## Status of this increment

- IMPLEMENTED: live-reader operational verdict, per-source validation/receipt/age,
  exact private market scope and USDT, reported total/available, configured TTL,
  unknown/stale/conflicting exposure, observed ONE_WAY, private terminal comparison.
- SYNTHETICALLY TESTED: checkpoint reader alongside writer, loss/stale/reconnect,
  rounding/differences, scope/window checks, CI/non-TTY redaction and NO_TRADE.
- LIVE VERIFIED (historical, before this increment): run 41345909713 validated
  REST/WS balance/settings and ONEWAY normalization; exposure remained provider-null.
  This does not verify the new private view or terminal parity.
- OWNER COMPARISON PENDING: same-key-bound-market terminal comparison below.
- BLOCKED in Codex: no local BITSGAP_PRIVATE_KEY_PEM; enforced policy has no
  open.bitsgap.com/WS provider grant. Existing Actions secret remains intact.
  This does not imply the deployed observer is broken.

## Trusted host and credential provisioning

Use an owner-controlled POSIX computer with Python 3.11–3.13 and outbound HTTPS/WSS
access to the exact existing Bitsgap adapter endpoints (see source; no TLS bypass).
Use two private interactive terminals in the same checkout/virtual environment.
No terminal recording, CI, shared screen, shell tracing or automatic transcript
upload. The checkpoint and comparison are private financial files, never artifacts.

Install the existing dependencies in a virtual environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install 'cryptography>=42,<47' 'websockets==16.0'
umask 077
mkdir -p "$HOME/.local/state/daiinas-private"
chmod 700 "$HOME/.local/state/daiinas-private"
```

Provision the **existing** Bitsgap signing credential into the environment as
`BITSGAP_PRIVATE_KEY_PEM` using the owner's approved local secret manager and its
process-environment injection. No credential is accepted as a command argument.
Do not type it into chat, a shell command/history, source or an env file in Git.
Never extract/copy the GitHub Actions secret into Codex. If the existing credential
is available only in Actions and no secure owner copy is available, stop with
CREDENTIAL_NOT_CONFIGURED; arrange approved owner-side secret provisioning from
its original secure source. Do not regenerate/change keys as part of this task.
Only Terminal A needs the signing credential; Terminal B never loads one.

The executable session wrapper checks presence only and reports
CREDENTIAL_NOT_CONFIGURED before any provider request when absent. Other invalid
credential/transport failures use the existing redacted observer diagnostics.

## Terminal A: 60 seconds of read-only observation

From repository root, with the credential securely injected:

```sh
sh scripts/observe_futures_account.sh \
  "$HOME/.local/state/daiinas-private/acceptance.sqlite" p02-owner-futures
```

The wrapper invokes the existing bounded worker with --seconds 60. Discovery and
initial setup precede that bound; network setup has existing transport timeouts.
Private output remains forbidden in --observe. The worker alone writes checkpoint;
Terminal B uses SQLite read-only mode and does not contend for its writer lock.
Final observer exit code **2 is expected**, because NO_TRADE remains enforced.
Do not interpret it as funded capital or trade permission. An UNVERIFIED/error
status still requires investigation; the exit code alone is not success evidence.

## Terminal B: inspect at approximately 10, 30 and 50 seconds

Activate the same environment, but no API credential is needed. Execute this
command at each observation point, while Terminal A is still running:

```sh
python -B -m daiinas.bitsgap_account_visibility \
  --state-file "$HOME/.local/state/daiinas-private/acceptance.sqlite" \
  --scope-ref p02-owner-futures --private-panel
```

Private input and output must both be TTYs. CI or redirected private output is
rejected before reading checkpoint. Never use tee, redirection or log collection
for this command. The JSON is a point-in-time operational view, not an auto-refresh
UI. Re-run it to obtain a new checkpoint read. It shows:

- market_id (the dynamically discovered authenticated Futures `em`), USDT,
  non-secret operator namespace; namespace is not an independently verified account ID;
- current total_reported/available_reported only with coherent fresh REST+WS and
  connected observer; cached amounts under last_observed, explicitly labelled;
- each source's schema validation, local receipt time, age and fresh flag;
- TTL and comparison window from the writer's persisted configuration;
- orders/positions/mode states, blockers, disabled live routing and NO_TRADE.

Receipt timestamps are LOCAL_RECEIPT_CLOCK_NOT_PROVIDER. Freshness defaults to
15s; REST/WS comparison window is 5s. Identical cached WS frames never renew age.
A provider may not emit unchanged wallet updates: later views can honestly become
STALE/UNVERIFIED despite a healthy connection. Do not widen TTL or fabricate
updates merely to force parity. Resolve provider heartbeat/snapshot semantics if
this prevents the acceptance window.

## Private same-window terminal comparison

In Bitsgap verify **KuCoin Futures, USDT, same key-bound account/market**. Corroborate
identity privately using the owner's existing connection configuration. If it
cannot be established, answer NO; comparison stays NOT_VERIFIED. No account/key
identifiers are requested or saved. Verify UI rounding and decimal precision.

While the observer is active:

```sh
python -B -m daiinas.bitsgap_account_visibility \
  --state-file "$HOME/.local/state/daiinas-private/acceptance.sqlite" \
  --scope-ref p02-owner-futures --private-panel --compare \
  --comparison-file "$HOME/.local/state/daiinas-private/comparison.sqlite"
```

The prompts first request account corroboration, precision and mode. Then enter
one live sample line: TOTAL AVAILABLE ORDERS POSITIONS UTC_MS. Use ? for unknown
counts. NOW records the actual local input-confirmation time only when you confirm
you just sampled the live terminal; it is not a provider/UI event timestamp. An
explicit UTC Unix millisecond observation time is also accepted. Read the terminal at that time; do not substitute an old screenshot.
Entering data takes time: stale results are valid failures; repeat with a current
terminal sample rather than replacing timestamps. The checkpoint is loaded after
entry to avoid comparing against a snapshot captured before the operator inputs.
ROUND_HALF_UP is an explicit comparison assumption that the owner must confirm;
if the UI truncates or uses other rounding, do not assert parity with this tool.
Difference is API amount minus the entered terminal amount; the entered value
must already reflect UI precision. `balance.a` remains reported available for
trading, never independently established free margin or Model A ACTIVE.

The comparison file is a separate 0600 SQLite private record. It includes terminal
inputs/time, API state/version/receipt times/precision, differences, same-window
checks and MATCH/MISMATCH/STALE/NOT_VERIFIED. No provider frames, signatures or
credentials are saved. The record cannot overwrite the active observer checkpoint.
It is a local operator assertion, not a signed independent account-identity proof.
balance_terminal_parity reports the balance result alone. terminal_parity requires
balance, exposure and mode comparisons all to match in their own same-time windows.
Balance parity, exposure parity and mode parity are separate results. Provider-null
remains NOT_VERIFIED exposure even when the operator reports zero in the UI.

To re-evaluate a saved comparison without prompting:

```sh
python -B -m daiinas.bitsgap_account_visibility \
  --state-file "$HOME/.local/state/daiinas-private/acceptance.sqlite" \
  --scope-ref p02-owner-futures --private-panel \
  --comparison-file "$HOME/.local/state/daiinas-private/comparison.sqlite"
```

Saved parity expires with the comparison window, disconnect or generation change.
New receipts cannot refresh an old terminal sample. Default (without private-panel)
output is redacted and omits all numeric balances and counts.

## After stop, expiry and reconnect

Immediately after Terminal A exits, repeat the private view. CONNECTION must be
DISCONNECTED, current amounts UNVERIFIED and last_observed.current false. Run it
again after >15s; expired evidence cannot become current. If the observer is killed,
loss of its writer lock likewise prevents readers from reusing its saved connection.

For controlled reconnect, interrupt the worker with Ctrl-C (never create orders),
inspect the disconnected status, then repeat Terminal A's command using the same
checkpoint. Re-run Terminal B at 10/30/50s. Old generations cannot satisfy fresh
REST/WS evidence. For an actual WSS transport interruption, use the trusted host's
ordinary network controls; document real times privately, observe loss/recovery
and never claim the synthetic reconnect test proves a live outage recovery.

## Acceptance and next gates

Record Gate 1 code/security audit, Gate 2 live observation/recovery, Gate 3 private
terminal parity and Gate 4 operator view separately as PASS/PARTIAL/BLOCKED.
read_only_safety=PASS describes the code's restricted observation path, not a live
exchange permission audit. account_readiness remains PARTIAL at best; full identity,
collateral/equity/free margin/costs and persistent native TP/SL are unverified.
Model A remains PREVIEW ONLY; this view never funds slots or clears NO_TRADE.
Use the existing non-mutating preview only after owner parity acceptance; eligible
capital remains unverified and any first-allocation scenario remains hypothetical.
Do not merge automatically or activate live routing. Persistent native protection
is a separate future release gate.
