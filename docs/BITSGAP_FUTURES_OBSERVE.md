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
