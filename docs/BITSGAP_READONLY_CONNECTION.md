# DAIINAS → Bitsgap API: authenticated REST handshake

**State:** existing signed catalog handshake retained; KuCoin Spot account checks implemented offline, but not yet live-verified. Reuse the existing key. No real order execution.

## Architecture

- Existing Bitsgap ↔ KuCoin connection stays unchanged.
- DAIINAS GitHub Actions manually tests the separate Bitsgap API using Ed25519 PKCS#8 PEM.
- Signed reads are restricted to **manual**, **conf_enums**, **balance** and **orders**. Catalog reads alone do not prove KuCoin account access; account reads require dynamic real Spot resolution and validated schemas.
- The Bitsgap private API key grants **trading authority on connected exchanges**, according to Bitsgap's official API documentation. Client-side read-only allowlists do NOT downgrade its privileges.

## Operator setup

Reuse the existing GitHub Actions secret `BITSGAP_PRIVATE_KEY_PEM`. Do not change
or regenerate API keys. Never paste credentials into chat, source files, or logs.
For one extended read-only run, follow the manual workflow instructions below.
The original handshake workflow remains unchanged for catalog-only verification.

## Safeguards

- No trading topics (order_place, order_cancel, position_close, leverage or margin changes, etc.) are permitted by daiinas/bitsgap_readonly.py.
- No account balances or identifiers are printed to logs.
- Workflow is manual-only, read-only GitHub contents permission, main branch guard, and checkout token not persisted.
- DAIINAS remains PAPER; a trade-capable credential remains hazardous even when the application code is read-only.
- The separate direct KuCoin key must be General-only and should have IP restriction restored or be revoked if unnecessary.

## Validation after a successful handshake

The extension below resolves KuCoin Spot dynamically and validates supported
balance/open-order structures. It does not reconcile Futures capital, add positions
access, or enable exchange writes. All live access remains unverified until the
manual authenticated workflow succeeds.

## Primary sources

- https://github.com/Bitsgap/bitsgap-api-docs
- https://github.com/Bitsgap/bitsgap-api-docs/blob/main/docs/rest/README.md
- https://github.com/Bitsgap/bitsgap-api-docs/blob/main/docs/topics/reference.md


## KuCoin Spot read-only extension (offline implementation)

The existing Ed25519 signer is preserved. The topic allowlist is now exactly
`manual`, `conf_enums`, `balance`, `orders`. The last two permit only
`{"em": <resolved real KuCoin Spot ID>}`. No `subs`, pair selector, caller-selected
exchange, demo/Futures ID, or mutating command is permitted. Dynamic resolution
requires a unique `KUCOIN` or `KUCOIN_SPOT` name (case-insensitive, spaces normalized
to underscores) in `market.items`, with `market.alias == "em"`. Unknown names and
ID aliases fail closed rather than guessing; catalog presence does not prove a
connected account identity.

### One manual authenticated verification run

After reviewing and merging the PR, use the **existing** GitHub Actions secret
`BITSGAP_PRIVATE_KEY_PEM`; do not regenerate keys or paste values into logs/chat.
In Actions choose **Bitsgap KuCoin Spot read-only verification (manual)** and run
once on `main`. No schedule, trading worker, artifacts, raw response logs or
account-state persistence is created. Offline regressions run before the secret
is provided to the probe step. Successful checks emit only:

```
READ_ONLY_SECURITY_TESTS=PASS
DAIINAS_ORDER_ROUTING=DISABLED
BITSGAP_API_AUTH=PASS
KUCOIN_EXCHANGE_RESOLVED=PASS
KUCOIN_BALANCE_ACCESS=PASS
KUCOIN_ORDERS_ACCESS=PASS
```

A workflow failure must be reported as a failure, never as authenticated access
based solely on HTTP 200. `HTTP_401` is an authentication rejection; `HTTP_403`
can mean revoked/unknown key or timestamp freshness, and does not independently
prove a permission problem. Other HTTP errors retain numeric categories only.
No raw error text is printed. Unknown JSON error objects are schema failures,
not empty accounts or inferred permission failures. There are no automatic retries.
The probe attempts orders independently after a balance schema/HTTP failure, but
makes no account calls after failed authentication or exchange resolution.

### Explicit protocol limits

The supplied 2026-11-01 documentation pack is a summary, not captured production
responses. Only the documented topic-value structures are supported, after exactly
one existing REST-envelope unwrap: balance `{"data": <currency records>}` and
orders `{"data": <pair arrays>, "cnt": <integer>}`. Direct maps, alternative
wrappers, unknown fields, malformed decimals and Futures order fields are rejected.
Order types must resolve from `conf_enums.order_type.items`; LIMIT needs a price.
Unspecified partial-fill/fee record fields fail as `UNVERIFIED_ORDER_OPTIONAL_SCHEMA`.
Count discrepancies fail as `ORDER_SNAPSHOT_COUNT_UNVERIFIED` without assuming a
complete snapshot was promised. Empty candidates fail as `EMPTY_BALANCE_UNVERIFIED`
or `EMPTY_ORDERS_UNVERIFIED`: the reference does not establish exact empty-account
semantics. Do not loosen these gates based only on synthetic fixture tests.
Further schema support requires authoritative documentation or a separately
approved secure validation, without exposing private responses in public logs.

Nonempty live responses can earn access PASS only after their full supported
structure validates. Offline mock PASS does not establish live account access.
No balances are returned to a ledger or treated as Model A capital. Spot inspection
does not verify Futures account access or position mode. The owner's manually set
Futures **ONE_WAY** requirement is preserved; this adapter never changes it.
No engine, strategy, sizing, risk, position lifecycle, or live-routing code changes.

The earlier two-topic handshake workflow remains available and unchanged. Its
two-topic status describes that workflow only, not the extended adapter allowlist.


### Final release-candidate audit

The audit additionally rejects duplicate JSON object members, NaN/Infinity and
outer REST envelopes containing unexpected fields (including error-plus-data).
This tightens response acceptance without changing Ed25519 key parsing, payload
serialization, canonical signing bytes, headers or HTTP transport. Unknown order
type names fail closed; MARKET records must omit price and LIMIT must include it.
Balance conservation uses a bounded high-precision local Decimal context.
The probe also emits `LIVE_TRADING=DISABLED`, `FUTURES_POSITION_MODE=ONE_WAY`, and
`FUTURES_POSITION_MODE_SOURCE=OWNER_CONFIGURATION_NOT_API_VERIFIED`.
These report this adapter's no-write boundary and the owner's Futures requirement,
not an authenticated Futures mode observation or a global audit of every engine.


### Order snapshot integrity (PR #18 follow-up)

The `eost` state and `eos` buy/sell side must match the dynamically retrieved
`conf_enums.order_state.items` and `conf_enums.order_side.items` with aliases
`eost` and `eos`, respectively. Missing, malformed, ambiguous, or unsupported
reference values produce `UNVERIFIED_ORDER_STATE_ENUM` or
`UNVERIFIED_ORDER_SIDE_ENUM`, never an account-access PASS.
Order IDs must be unique across all pairs in a single snapshot;
duplicates produce `DUPLICATE_ORDER_ID` even if the record count matches `cnt`.
These are strictly read-only validation changes, not permission to place orders.
