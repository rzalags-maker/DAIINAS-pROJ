# P09 — Bitsgap native TP/SL verification and execution feasibility

**Final decision: `INSUFFICIENT_PROVIDER_EVIDENCE`.** P06 remains **NO-GO**.

This is a read-only research result on top of P06 `7fe74ca08f482cafa1301c51b10a93f5e6a3fb17`,
P07 `91713640788051e2fd75be80e495c96180214be1`, and P08
`cd34c52efaa26052eb2afca8f622f1d3617a5ddf`. No order, cancellation, amend,
close, margin/leverage update, transfer, credential request, authenticated API
call, or live/demo action was performed.

## Evidence provenance and read-only limitation

| Source | Revision / retrieval | Method | Scope and limitation |
| --- | --- | --- | --- |
| Bitsgap official API docs | `Bitsgap/bitsgap-api-docs@d27611b63d56c65c9797e61d34b40b1f175a7664`, retrieved 2026-11-06 | Fresh clone, source/schema review | This is the same revision pinned by P06; public protocol documentation does not grant account-specific capability or write permission |
| KuCoin Universal SDK | `Kucoin/kucoin-universal-sdk@c2f39bdb8b7d5f31cfb3fd532f9baf2f09fd8f12`, P08 audit | Offline review of `spec/original/meta.json` | Official direct-KuCoin contract only; it does not establish Bitsgap mapping |
| Existing P05.1/P06 evidence | P06 report and repository tests | Read-only review | Earlier authenticated observation established REST/WS authentication but `orders` and `positions` were `PROVIDER_NO_DATA`; this is neither empty exposure nor protection proof |
| Current P09 execution environment | 2026-11-06 | Presence-only check for the already named Bitsgap credential variables | `BITSGAP_PRIVATE_KEY_PEM`, `BITSGAP_API_KEY`, and `BITSGAP_SECRET` are absent. No secret was requested, logged, or substituted, and no authenticated query was attempted |

The last row is an execution-environment limitation, not a statement about the
authorized GitHub Actions environment used by previous read-only work. P09 did
not trigger that environment because it could not establish a permitted
credential-bearing context locally.

## P09.1 provider-request status

**Status: `NOT_SUBMITTED`** — no Bitsgap ticket/reference exists.

| Field | Record |
| --- | --- |
| Attempted at | 2026-11-06 13:27 UTC |
| Official destination verified | [Bitsgap Developer API GitHub issues](https://github.com/Bitsgap/bitsgap-api-docs/issues). The official repository already uses this channel for a native-protection API question: [issue #1](https://github.com/Bitsgap/bitsgap-api-docs/issues/1). |
| Subject prepared | `KuCoin Futures: Developer API support for exchange-native TP/SL protection?` |
| Submission result | GitHub API returned `403 Resource not accessible by integration`. No request body, credential, account identifier or private account message was exposed. |
| Ticket/reference | None — the provider did not receive or acknowledge a ticket. |
| Exact external blocker | The connected GitHub integration has read access to `Bitsgap/bitsgap-api-docs` but lacks permission to create issues in that repository. |
| Next authorized action | Submit the unchanged nine-point request at the official issues URL from a Bitsgap-authorized GitHub account, or use an authenticated Bitsgap Helpdesk channel and retain its ticket reference. When receipt or a response is available, add only that evidence and classify it against the P09 matrix. |

## Bitsgap Futures protection capability matrix

`DOCUMENTED_ONLY` means a public schema describes the generic mechanism but
does not prove KuCoin Futures behavior for this account. `UNVERIFIED` means the
review found no authoritative provider contract. `UNSUPPORTED` is deliberately
not used: absence from public documentation is not an affirmative limitation.

| Required capability | Bitsgap source and field | Classification | P06 impact / limitation |
| --- | --- | --- | --- |
| Generic Futures order request | [`trading.md#order_place`](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/trading.md#order_place--placing-an-order): `em`, `pair`, `eot`, `eos`, `am`, optional `pr`; Futures `epps`, `epm`, `lv`, `etif`, `ro`, `apiid` | DOCUMENTED_ONLY | Generic entry/exit placement is not a native protective-bracket contract |
| Order type, side, quantity and placement price | `eot`, `eos`, `am`, `pr` fields in the same table | DOCUMENTED_ONLY | Exact KuCoin Futures contract unit/precision and trigger price precision need account/catalog and contract evidence |
| Position side and margin mode | `epps`, `epm`, `lv` | DOCUMENTED_ONLY | Existing P05.1 ONE_WAY observation does not prove a safe mapping or order acceptance |
| Reduce-only | `ro`: “only closes the position without flipping it” | DOCUMENTED_ONLY | No proof of exchange enforcement for a native conditional child, sizing after partial fill, or surviving state changes |
| Client identity | `apiid`, user-side ID (length <=250); [`portfolio.md`](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/portfolio.md) documents history filtering | DOCUMENTED_ONLY | Client correlation does not create parent/child ownership or exactly-once settlement proof |
| Bitsgap/exchange identity and acknowledgement | `order_place` stages document Bitsgap `id` at `eost=3` and exchange `eid` at `eost=4` | DOCUMENTED_ONLY | `eost=4` is placement acknowledgement, not fill, TP/SL activation, protection or settlement |
| Native TP creation | No TP trigger field/command in documented `order_place`, manual catalog example, or documented topic list | UNVERIFIED | Decisive P06 blocker stays open |
| Native SL creation | No SL trigger field/command in documented public contract | UNVERIFIED | Decisive P06 blocker stays open |
| Trigger price and reference (last/mark/index) | No documented Bitsgap equivalent of trigger price/reference | UNVERIFIED | Cannot compute or audit stop activation semantics |
| Parent/protective child relationship | No child/parent/attached-order fields | UNVERIFIED | Cannot establish that protection belongs to an entry |
| Protection quantities after partial fills | `tl` mentions partial fill/reduce-only trim in order state, but no child resize contract | UNVERIFIED | Cannot prove children match actual exposure |
| OCO / sibling cancellation | No documented OCO, sibling or cancel-on-fill behavior | UNVERIFIED | Cannot prove the residual TP/SL becomes harmless |
| Reconciliation after reconnect/restart | Generic `orders`, `positions`, `order_detail` and WS topics are documented; P05.1 historical topics were provider-null | UNVERIFIED | No verified complete read model for owned protection/exposure after reconnect |
| Persistence after DAIINAS/Bitsgap disconnect | No provider assertion of venue-resident protective lifecycle in the API contract | UNVERIFIED | No proof a stop/TP remains armed when controller or provider session disappears |
| Explicit unsupported result | None found | **Not claimed** | P09 makes no false rejection |

## Native KuCoin comparison

The KuCoin official spec declares `POST /api/v1/st-orders` as a direct native
take-profit/stop-loss route. Its request schema includes `clientOid`, `side`,
`symbol`, `type`, `leverage`, `stopPriceType` (`TP`, `MP`, `IP`), `reduceOnly`,
`closeOrder`, `marginMode`, `price`, `size`/`qty`/`valueQty`,
`triggerStopUpPrice` and `triggerStopDownPrice`. This comparison records an API
shape difference; it does not license or implement direct KuCoin trading.

| Field/lifecycle concern | Native KuCoin `/api/v1/st-orders` | Bitsgap documented contract | Compatibility conclusion |
| --- | --- | --- | --- |
| Type and side | `type`, `side` | `eot`, `eos` | Generic concepts documented; semantic mapping UNVERIFIED |
| Contract quantity | `size`/`qty`/`valueQty` with contract restrictions | decimal `am` | Unit conversion and precision mapping UNVERIFIED |
| Limit price / precision | `price`; contract metadata required | `pr`; `conf_pairs` documents pair steps generally | Exact Futures trigger and contract precision mapping UNVERIFIED |
| Take profit / stop loss | `triggerStopUpPrice`, `triggerStopDownPrice` | no corresponding documented fields | UNVERIFIED through Bitsgap |
| Trigger reference | `stopPriceType`: trade/mark/index | no corresponding documented field | UNVERIFIED through Bitsgap |
| Reduce-only / close position | `reduceOnly`, `closeOrder` | `ro` | DOCUMENTED_ONLY generic equivalent; native behavior mapping UNVERIFIED |
| Margin / position mode | `marginMode`, leverage | `epm`, `epps`, `lv` | DOCUMENTED_ONLY generic equivalent; compatibility UNVERIFIED |
| Client/exchange IDs | `clientOid`; direct response contract | `apiid`; Bitsgap `id` then `eid` at `eost=4` | DOCUMENTED_ONLY correlation, no protection-child relation |
| ACK vs acceptance/fill | native API response is not a fill proof | `eost=3` accepted / `eost=4` exchange placed | Both require later reconciliation; Bitsgap protected state UNVERIFIED |
| Partial protection / sibling cancellation | not established by this endpoint alone | not established | UNVERIFIED |
| Cancellation / post-disconnect persistence | needs venue-specific lifecycle proof | no Bitsgap provider contract found | UNVERIFIED |

## Protection lifecycle assessment

| Stage | Available evidence | Result |
| --- | --- | --- |
| 1. Submit entry | Bitsgap documents generic `order_place` | DOCUMENTED_ONLY |
| 2. Exchange acknowledges entry | `eost=4` supplies `eid` after exchange placement | DOCUMENTED_ONLY; not fill proof |
| 3. Partial/full fill | Order topic/state fields exist, but no authenticated complete Futures observation in P09 | UNVERIFIED |
| 4. Native TP/SL active at exchange | No Bitsgap trigger/child schema | UNVERIFIED |
| 5. Quantity follows exposure | No partial-fill child-resize contract | UNVERIFIED |
| 6. Protection survives STOP/disconnect | No provider persistence contract | UNVERIFIED |
| 7. Restart restores ownership | Generic reads exist; provider-null exposure topics remain unresolved | UNVERIFIED |
| 8. One protective child executes | No native child evidence | UNVERIFIED |
| 9. Sibling is cancelled/harmless | No OCO/sibling contract | UNVERIFIED |
| 10. Ledger reconciles final costs/position | P04 MOCK ledger path exists; live receipt mapping absent | UNVERIFIED |

No offline lifecycle test was added because it would only be a synthetic model
of fields the provider has not documented. Such a fixture could wrongly imply
that an exchange-native contract exists.

## Exact provider-facing clarification request

> **Subject:** KuCoin Futures API — native TP/SL protection contract
>
> For a `KUCOIN_FUTURES` USDT account connected through the signed Bitsgap
> Developer API, we need to confirm whether the API supports
> **exchange-native Take Profit and Stop Loss protection**, equivalent to KuCoin
> Futures `POST /api/v1/st-orders`.
>
> Please provide the exact supported API commands, parameter schema and redacted
> request/response examples covering:
>
> 1. Native TP/SL trigger prices and trigger reference types (last, mark or index).
> 2. Exchange-enforced reduce-only/close-position behavior, including contract
>    precision and position mode.
> 3. Parent entry and protective child order IDs, including exchange-side
>    confirmation.
> 4. How TP/SL quantities are created or adjusted after partial fills.
> 5. OCO or automatic cancellation/neutralisation of the remaining protective
>    order after execution.
> 6. Whether protective orders remain active on KuCoin after the originating
>    API/WebSocket client disconnects or the process terminates.
> 7. The REST/WS endpoints that provide authoritative order, position and
>    protective-order states after reconnect or restart.
> 8. Complete open-position and pending-order inventories, available Futures
>    margin and trading costs, particularly when `orders` or `positions` return
>    null or no provider data.
> 9. Which capabilities are unavailable through the Developer API despite being
>    available in the Bitsgap user interface.
>
> If the Developer API does not support exchange-native TP/SL for KuCoin Futures,
> please confirm this explicitly. Documentation and read-only examples only are
> requested; no trading operation, account credential or account modification is
> requested.

The smallest permitted follow-up, after such a provider answer, is to ingest it
as redacted **read-only** capability evidence and extend the P06 registry/tests
to classify the response. It must still not authorize `order_place`.

## P06 blocker assessment and engineering conclusion

| P06 blocker | P09 result |
| --- | --- |
| Native protection contract | Still unresolved; public Bitsgap docs do not specify it |
| Full orders/positions inventory | Still unresolved; historical provider-null is not zero |
| Equity/free margin/costs | Still unresolved; P09 made no account query |
| Idempotent live receipts / fill settlement | Still unresolved; generic IDs/ACK stages are insufficient |
| STOP with remaining exposure | Still unresolved; persistence and sibling behavior unknown |

`BITSGAP_PATH_FEASIBLE` cannot be concluded because mandatory native-protection
semantics lack provider evidence. `BITSGAP_PATH_BLOCKED` cannot be concluded
because Bitsgap has not authoritatively said that those semantics are
unavailable. Therefore `INSUFFICIENT_PROVIDER_EVIDENCE` is the only defensible
P09 conclusion. The smallest future alternative architecture, only if Bitsgap
answers that it cannot expose the feature, is a separately approved single
protected-order gateway using a documented direct venue contract and the
existing P04 journal—never a parallel bot or ledger. It is not implemented or
authorized here.
