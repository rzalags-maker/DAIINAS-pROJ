# Bitsgap Futures protective TP/SL contract audit — issue #25

Read-only audit; no order, cancellation, close, leverage/margin change, transfer or
withdrawal executed. Terminal Smart Trade controls do not prove public API support.

## Primary sources

Official documentation revision: d27611b63d56c65c9797e61d34b40b1f175a7664.

- [Trading topics](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/trading.md)
- [REST](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/rest/README.md)
- [Catalog and enums](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/reference.md)
- [Authoritative issue #25](https://github.com/rzalags-maker/DAIINAS-pROJ/issues/25)

Issue #25 was read from its GitHub page; public docs were read from a pinned Git
clone. No authenticated live manual descriptors were obtained here. Existing
production auth/balance evidence does not establish protective support.

## Findings

VERIFIED below means public-contract verified, NOT a successful live test.

| Capability | Classification | Evidence and limit |
| --- | --- | --- |
| Reduce-only | VERIFIED in docs | trading.md lines 130 and 353 define ro: closes without flipping. No live enforcement demonstrated. |
| id/eid/apiid correlation | VERIFIED in docs | Separate provider/exchange/caller IDs; asynchronous acceptance and placement are different stages. Neither is proof of a fill. |
| Partial fill and fees | VERIFIED in docs | am remaining, ame filled, pre average price, tl last change, f fee map. Not a complete settled campaign or funding ledger. |
| Inspect an order | VERIFIED in docs | order_detail searches open/retained closed records. Scope, ownership and retention still require proof. Not enabled by this change. |
| Cancel an order | VERIFIED in docs; execution DISABLED | order_cancel has queued/sent/completed/error stages; acceptance is not cancellation. No command sent. |
| Close a position | VERIFIED in docs; execution DISABLED | position_close creates an order; actual outcome appears in positions updates. No command sent. |
| Command transport | UNVERIFIED: conflicting docs | trading.md introduction says commands are WS-only. rest/README.md lines 108–114 explicitly permits asynchronous REST commands. Runtime manual is the documented authority; do not resolve the conflict through writes. |
| Persistent native SL/TP | UNVERIFIED | Reviewed order_place fields do not establish trigger price/reference, SL/TP child linkage or venue persistence. Enum examples have ellipses; missing examples do not prove UNSUPPORTED. |
| Last/mark/index trigger; stop-market/stop-limit | UNVERIFIED | No complete protective trigger contract established. A UI control is not an API capability guarantee. |
| Protective child resizing after partial fill | UNVERIFIED | Partial-fill data exists; protective-child sizing and coverage acknowledgments are not established. |
| Sibling cancellation / OCO | UNVERIFIED | No sufficient linkage or atomic sibling-cancellation guarantee found. |
| Protection surviving worker/Bitsgap restart | UNVERIFIED | Need venue-vs-provider ownership/persistence evidence. Acceptance or a UI label is insufficient. |
| Account-specific KuCoin Futures support | UNVERIFIED | No new live manual/protective-record observation performed. |

No blanket UNSUPPORTED conclusion is justified for native TP/SL. The current
adapter's write transport is definitively disabled. Documentation conflicts remain
unresolved pending live catalog or provider clarification.

## Null is not zero

The trading reference says an exchange without data (for example no open orders)
may have no subscription; it also defines explicit orders.cnt and positions.cnt.
This distinguishes an explicit count from null, but does not prove WHY this account
returned null. Permissions, synchronization, account scope and async-state
explanations remain unverified. REST/WS agreement is non-atomic and covers only
the API market view, not full exchange collateral/protection completeness.

## Read-only follow-up

1. In the existing secure environment inspect sanitized live manual parameter,
   transport and order_type definitions, without private responses in public logs.
2. Obtain a provider contract for trigger reference, exchange persistence,
   reduce-only child ownership, resizing and sibling cancellation. Never use
   undocumented browser endpoints.
3. If pre-existing authorized protective orders exist, correlate scoped
   read-only observations with same-window terminal evidence privately. Do not
   create an order merely to manufacture test data.
4. Keep position_protection UNVERIFIED and Model A admission blocked. Existing
   PAPER protection simulation remains separate from venue confirmation.

## Shared read budget

The pinned trading reference specifies positions_settings: 1 request/second and
5/10 seconds; balance/orders/positions: 5/second and 20/10 seconds. REST documents
shared topic counters with WS. The AccountState worker installs a shared budget
for REST reads and WS subscription batches, retained across reconnects and stopped
on bounded shutdown. Default callers remain unchanged. These are pinned public
bounds, not observed live-manual limits; any stricter runtime limits remain an
operational validation prerequisite.
