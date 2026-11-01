# DAIINAS × Bitsgap KuCoin Futures — OBSERVE increment (2026-11-01)

**Implemented:** an isolated read-only Futures observer and optional authenticated WebSocket observation stream. It reuses the existing Ed25519 REST signing function. The reviewed Spot adapter and its caller-level allowlist remain unchanged; the shared signing primitive has an independent hard **non-mutating topic ceiling**. There is no Bitsgap order placement, cancellation, close, margin, leverage, transfer or withdrawal method.

## What the observer does

1. Read signed `manual` and `conf_enums` metadata, discover exactly one `KUCOIN_FUTURES` market ID from the live catalog; fail on demo, Spot, ambiguous IDs or missing capabilities.
2. Read Bitsgap `balance` (`value.data.USDT.t` total and `.a` available), `orders`, `positions` and `positions_settings` under that resolved Futures `em`. Explicitly *do not* apply Spot-only `l` to Futures margin.
3. Validate dynamic order enums, duplicate order IDs, partial fills and fee maps; validate position/setting scope, counts, known enum codes and conflicting position/margin mode reports. Empty lists with `cnt=0` are permitted as **observed** data, not proof of complete account reconciliation.
4. Produce a confidential, private-panel-friendly object with raw observed USDT total/available, positions/orders count and recognized settings, **plus explicit `UNVERIFIED` for financial equity, free margin, Model A Reserve/Active and trading eligibility**. Default CI/status output is redacted.
5. Optionally connect to authenticated WebSocket, subscribe ONLY to `balance`, `orders`, `positions`, `positions_settings`, validate each frame and on disconnect authenticate anew and re-read REST. No WS command packets are sent.

## How to run

Use a **trusted private** execution environment with the existing `BITSGAP_PRIVATE_KEY_PEM` already configured as a secret. Never send the PEM in chat or put it in the repository, public logs or a screenshot. Do not use this on an untrusted remote host.

```sh
python -m pip install 'cryptography>=42,<47'
python -m daiinas.bitsgap_futures_cli
```

The default output is safe, contains no account amounts, and says `capital_reconciled=false` even after a successful observation.

To display the actual observed `t`/`a` in a **trusted local terminal only**:

```sh
python -m daiinas.bitsgap_futures_cli --private-panel
```

Private output is blocked in GitHub Actions. For read-only WS monitoring (requires the project's `websockets==16.0` optional live dependency):

```sh
python -m pip install -e '.[live,bitsgap]'
python -m daiinas.bitsgap_futures_cli --watch
```

The existing manually dispatched GitHub workflow can run the **redacted snapshot probe only**; do not store balances, IDs, raw responses, keys or auth signatures in workflow artifacts.

## Explicit limitations / release gates

- This increment is tested on **synthetic account responses**. The actual `KUCOIN_FUTURES` enum label, current Bitsgap topic availability and live response schema are not authenticated yet. If the vendor uses another real market label, discovery deliberately returns `UNVERIFIED`; only update the resolver after trusted evidence.
- The read sequence is **not an atomic venue snapshot**. The last REST observation timestamp is the local capture time; no provider revision/sequence or exchange account identity has been independently authenticated. WS update events are sanitized and are **not** currently merged into an authoritative financial account journal.
- `balance.t` is not necessarily Futures equity and `balance.a` is **not Model A ACTIVE or assured free trading margin**. Position margin (`msize`) and pending orders do not establish a complete Futures collateral/fee/funding ledger. No real account value is promoted to a mock `FuturesAccountSnapshot`, and existing Model A historical funding is never re-seeded.
- A validated order-state code does not establish full protective TP/SL coverage, exact fills, economic profitability or exchange write permission. `orders_history` and `conf_pairs` are explicitly allowlisted for future one-shot reads but not automatically converted into financial authority.
- No interactive browser dashboard has been shipped. The private `private_panel()` data contract is ready for an authenticated future control panel; do not expose it on a public endpoint.
- No live-account integration into the existing `Pipeline.poll_account` was made because the current reconciler rejects real sources; bypassing it would silently create false capital and exposures.
- DAIINAS remains in **OBSERVE** for exchange data and **PAPER** for trading simulation. No real commands, automatic entry/exit, leverage or margin changes are enabled.
- Read-only scope is a code safeguard, **not** a limitation of the underlying Bitsgap credential's permissions.

## Tests

```sh
python -m unittest discover -s tests -p 'test_bitsgap_futures_observe.py' -v
python -m unittest discover -s tests -p 'test_bitsgap_futures_stream.py' -v
python -m unittest discover -s tests -p 'test_bitsgap_readonly.py' -v
```

Synthetic tests include valid/invalid wallet, Spot/demo separation, duplicate IDs, strict enum checks, filled-order fees, empty exposure, settings contradiction, Ed25519 canonical REST and WS signatures, authentication denial, disallowed mutating frames, and reconnect/resubscription with a fresh REST snapshot. Full repository CI remains the authoritative regression gate.

## Next precise task

One owner-authorized **redacted real Bitsgap Futures snapshot**. Compare vendor-real field shapes against strict mock fixtures without publishing private amounts. Then implement a complete account-specific collateral and settlement reconciler in the existing single-writer ledger, before ever allowing an `ALLOW` decision for real money. Verify TP/SL protected order semantics separately.

Primary sources: https://github.com/Bitsgap/bitsgap-api-docs/tree/main/docs/topics and https://github.com/Bitsgap/bitsgap-api-docs/blob/main/docs/ws/README.md

## Authenticated account observation — live evidence (2026-11-01)

The signed Bitsgap API key successfully resolved the actual `KUCOIN_FUTURES` market
and validated the USDT `balance` `t/a` values. The `positions_settings` structure
also validated. On the same real account, `orders` and `positions` returned
literal JSON `null`, **not** the documented `{data: ..., cnt: ...}` structures.
This does **not** prove zero orders or zero positions; these scopes remain
`UNVERIFIED`. Sanitized evidence: [GitHub run 41333637776](https://github.com/rzalags-maker/DAIINAS-pROJ/actions/runs/41333637776).

Use `python -m daiinas.bitsgap_futures_cli` for a redacted safe observation summary.
For exact USDT `total/available`, the owner may run
`python -m daiinas.bitsgap_futures_cli --private-panel` on a trusted local
operator computer with securely provisioned Bitsgap credentials. Private
amounts are forbidden from GitHub Actions logs and public artifacts.

An authenticated `balance` observation remains distinct from proved free
margin/equity, Capital Ladder reserve/active funding, or valid order scope.
`UNVERIFIED` orders and positions block every real new-entry decision.
No mock balances are overwritten; order mutation remains disabled.


### Verified partial-wallet runtime check — 2026-11-01 17:59 UTC

[Authenticated GitHub Actions run 41334246585](https://github.com/rzalags-maker/DAIINAS-pROJ/actions/runs/41334246585)
**succeeded** against the integrated `wallet_observation()` code:
`FUTURES_CATALOG=PASS`,
`FUTURES_OBSERVE_STATUS=PARTIAL_OBSERVATION_NOT_RECONCILED`,
`OBSERVE_BALANCE=VALIDATED`,
`OBSERVE_ORDERS=UNVERIFIED`,
`OBSERVE_POSITIONS=UNVERIFIED`,
`OBSERVE_POSITIONS_SETTINGS=VALIDATED`,
`MODEL_A_ACCOUNT_RECONCILED=NO`,
`ORDER_ROUTING=DISABLED`.
This is **not** a full account or strategy authorization PASS. No financial
amounts, IDs, keys or order details were printed. The temporary one-off workflow
was created for live discovery and removed after completion; the
`bitsgap-futures-observe.yml` **manual** workflow remains.



## Safe error taxonomy and provenance (2026-11-01)

The integrated observer separates **authenticated observed wallet** from unknown Futures
exposure scope. Literal JSON `null` for `orders`, `positions` or
`positions_settings` now yields the fixed `PROVIDER_NULL_RESPONSE` category, not
a fabricated zero count. Redacted status reports identify which topic failed
individually. Other fixed categories differentiate missing/invalid key,
`AUTHENTICATION_REJECTED`, `TRANSPORT_OR_RATE_LIMIT`,
`FUTURES_MARKET_UNRESOLVED`, `CAPABILITY_UNVERIFIED`, and
`SCHEMA_OR_RESPONSE_UNVERIFIED`. Remote response content is never reflected in
these labels.

Private `received_unix_ms` is explicitly labeled
`LOCAL_RECEIPT_CLOCK_NOT_PROVIDER`. **This is not a provider-signed API
timestamp.** The private operator output can show the actual authenticated
`balance.t` and `balance.a` values using `--private-panel` on a trusted
local machine only; the GitHub Actions workflow deliberately redacts amounts.
There is no user-facing authenticated web dashboard yet. Until a verified venue
contract explicitly confirms whether `balance.a` equals the Futures terminal's
`Available` / actual free-margin value, display it as
**Bitsgap-reported USDT available**, not withdrawable funds or trading
allocation. Do not use historical screenshot value 61.07 as current.
No Model A real funding, order routing, or account write access is enabled.

Codex agent operating on an older checkout MUST read the top P0 status in
`AGENTS.md`, fetch current GitHub `main`, and stop proposing the
old Spot-only `_spot_em` solution as though Futures read access did not exist.
A Codex sandbox without Bitsgap keys or network does not block authenticated
status checking by the existing GitHub Actions deployment.
