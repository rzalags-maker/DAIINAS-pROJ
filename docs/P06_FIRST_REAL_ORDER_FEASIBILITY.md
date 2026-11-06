# P06 — First real protected KuCoin Futures order feasibility

**Status: NO-GO for a live order.** This deliverable is a source-backed API capability assessment and a pure, offline-testable diagnostic gate. It is **not** a live trading implementation, proof of account completeness, or authorization to submit a trade.

| Identity | Value |
|---|---|
| Base | P05.1 `246e6a09d409bafd2bf7d224d1606baf6a0a89d7` |
| Branch | `feature/p06-first-order-feasibility` |
| Owner Issue | [#36](https://github.com/rzalags-maker/DAIINAS-pROJ/issues/36) |
| Existing strategy | Model A / v4.7 single ledger, **unchanged** |
| Existing live gate | START_LIVE blocked; no real write transport, **unchanged** |
| Credential / account tests | None; no secret, MAC session, provider order or money movement |

## 1. Executive answer

The Bitsgap developer API publicly describes Futures order creation, cancellation, detail and position closing. The supplied `order_place` fields document `ro` (reduce-only) but do not establish an end-to-end exchange-native protective SL/TP child-order contract. **Absence of that evidence is not proof that Bitsgap does not support the function.** It is enough to block an unattended real entry.

**Top decisive blocker:** `BLOCKED_NATIVE_PROTECTION_CONTRACT_UNVERIFIED`.

Separately, the existing owner's historical read-only Bitsgap observation had `orders=PROVIDER_NO_DATA` and `positions=PROVIDER_NO_DATA`; those JSON nulls do not certify that the account has no open exposure. Real free margin/equity and costs are also unverified. Hence even proving native TP/SL later would not, alone, grant first-order readiness.

There is no P06 API trade connector, automatic live authorization, or account-capital activation. P06's `status=BLOCKED` means **no-go to live**, not a failed P05.1 observer. Passing deterministic tests does not certify a real exchange.

## 2. Source-pinned provider contract

Official vendor repository: [Bitsgap/bitsgap-api-docs](https://github.com/Bitsgap/bitsgap-api-docs). The already integrated registry pins `Bitsgap/bitsgap-api-docs@d27611b63d56c65c9797e61d34b40b1f175a7664`; links below identify concrete source sections and public documentation. This review makes no private live-manual or API account-specific claim.

| Capability | Evidence and classification | Missing real-Futures acceptance proof |
|---|---|---|
| Public signed read catalog | [reference.md, manual and conf_enums](https://github.com/Bitsgap/bitsgap-api-docs/blob/main/docs/topics/reference.md#manual--topic-catalog) — **PUBLIC_DOC** | Actual authenticated session's market identity, `transport` flags, valid `eot` codes, schemas, limits and account privileges |
| Place order | [trading.md, order_place](https://github.com/Bitsgap/bitsgap-api-docs/blob/main/docs/topics/trading.md#order_place--placing-an-order) — **PUBLIC_DOC** | Exact real `KUCOIN_FUTURES` scope; trade-capable permission; exchange accepted response. No order sent |
| Cancel / order detail / close | [trading.md](https://github.com/Bitsgap/bitsgap-api-docs/blob/main/docs/topics/trading.md) — **PUBLIC_DOC** | Correct `id/eid/apiid` correlation, ownership, async receipt and actual effect. No command sent |
| Command transport | [trading.md line 4](https://github.com/Bitsgap/bitsgap-api-docs/blob/main/docs/topics/trading.md#L3-L4) calls commands WS-only; [rest/README.md lines 108–114](https://github.com/Bitsgap/bitsgap-api-docs/blob/main/docs/rest/README.md#L108-L114) describes asynchronous REST commands — **UNVERIFIED** for an account-specific executable contract | Reconcile with exact authenticated `manual` transport declarations and supported vendor response; a WS catalog declaration alone does not prove permission |
| ACK and exchange ID | [trading.md lines 317–400](https://github.com/Bitsgap/bitsgap-api-docs/blob/main/docs/topics/trading.md#L317-L400) — **PUBLIC_DOC** | `eost=3` + Bitsgap `id`: accepted/processing; `eost=4` + exchange `eid`: placed, **not filled or protected** |
| Reduce-only `ro` | [trading.md lines 339–355](https://github.com/Bitsgap/bitsgap-api-docs/blob/main/docs/topics/trading.md#L339-L355) — **PUBLIC_DOC** | Live enforcement and whether protective stop/TP are distinct reduce-only orders or linked native child orders |
| Stop loss / take profit trigger creation | No complete trigger-price, trigger-reference and native child/bracket fields in documented `order_place` field list — **UNVERIFIED**, **not** demonstrated unsupported | Vendor-confirmed supported API commands, order type/trigger schema (mark/last/index), venue acknowledgement, ownership |
| Native protective order persistence | **UNVERIFIED** | Exchange-side stop/TP remains present and executable after Bitsgap/DAIINAS disconnect, process loss and STOP |
| Partial fills and resizing | Order state / positions read support documented; child linkage and auto-resizing **UNVERIFIED** | Protection matches actual filled exposure without over-closing; sibling/OCO cancel/replace behavior and recovery |
| Full real exposure | Historical Bitsgap read-only `orders` and `positions` both `PROVIDER_NO_DATA` — **UNVERIFIED** | Complete inventory of owned and external positions, pending orders, costs, position/settings mode and account identity |
| Futures margin | `balance.t/a` documented, but does not prove equity/true spendable margin. [trading.md account topics](https://github.com/Bitsgap/bitsgap-api-docs/blob/main/docs/topics/trading.md) — **UNVERIFIED** | Authoritative settled equity, independent available collateral after commitments, fee/funding history, no double subtraction |
| Historical fills and fees | [portfolio.md orders_history](https://github.com/Bitsgap/bitsgap-api-docs/blob/main/docs/topics/portfolio.md#orders_history) — **PUBLIC_DOC** | Real venue event-to-intent mapping, delayed records, partial fills, funding and exactly-once P&L |
| Reliable STOP | Local P04 MOCK stop/restart tested — **MOCK_ONLY** | Authenticated runtime owner STOP ACK, order state reconciliation, independent protection for remaining open exposure |

**Important distinction:** The Bitsgap GUI's Smart Trade TP/SL feature cannot certify the public developer API's exchange-native bracket and trigger behavior. A provider enum such as `MARKET` or `LIMIT` likewise cannot prove trigger semantics. No direct KuCoin private API reconnect is introduced or demanded by this review.

## 3. New executable diagnostic boundary

`daiinas/p06_first_order_feasibility.py` exports:

- `assess_first_order(registry, acceptance, now_ms=..., protection_evidence=None)`
- `from_p051_report(registry, report, now_ms=...)`

The inputs are the existing `BitsgapCapabilityRegistry` and **redacted** P05.1 observation report. This module performs **no networking, signing, file access, order submission, cancellation or ledger operations**.

Output is a sanitized `first_order_readiness` with `decision=NO_GO`, per-gate status, named reason, evidence kind and age where available. It cannot echo private provider payloads or user amounts, and does not interpret `PROVIDER_NO_DATA` as zero. It does not elevate simulated Model A protection, manually entered numbers or a forged `VERIFIED` string to real authority.

This is intentionally **never a LIVE admission gate**: even an optimistic injected catalog/state fixture ends `BLOCKED`. No trusted signed venue-protection attestation or live order control transport exists here. A subsequent separately reviewed implementation would need to establish those, and should not reuse any fixture-generated `DECLARED_ONLY` as trading permission.

Illustrative *classification*, not a real account result:

```json
{
  "first_order_readiness": {
    "status": "BLOCKED",
    "decision": "NO_GO",
    "reason": "BLOCKED_NATIVE_PROTECTION_CONTRACT_UNVERIFIED",
    "account_verified": false,
    "native_tp_sl_verified": false,
    "orders_enabled": false,
    "live_trading": "DISABLED",
    "new_entry": "NO_TRADE_ACCOUNT_NOT_RECONCILED"
  }
}
```

The full report includes additional redacted gates and reasons. Never infer that the illustration is a measured account snapshot.

## 4. Smallest credible route to one first real protected order

1. **Provider proof, no writes:** Obtain a supported vendor contract for KuCoin Futures native SL/TP creation, trigger type/reference, reduce-only, partial-fill sizing, order child IDs, cancellation of siblings and independent venue persistence. Reconcile REST/WS command description against read-only `manual` and explicit vendor confirmation. If Bitsgap cannot provide this API contract, record **unavailable** versus **affirmatively unsupported** and evaluate an explicitly approved alternative gateway; do not silently add KuCoin keys or UI click automation.
2. **Authoritative inventory and capital:** Close the `orders` / `positions` provider-null gap, reconcile all external and owned obligations, actual equity/free margin, collateral, fees/funding and settlement; preserve one existing Model A ledger. Keep true free margin distinct from `balance.a`.
3. **Reviewed real transport and event mapping:** Only after (1)–(2), specify an isolated mode-gated, idempotent transport using existing P04 journal / intent-ACK-fill state machine; no second bot or finance store. Validate the venue's actually reported `apiid/id/eid` and protective receipt lifecycle in a safe separately authorized acceptance environment.
4. **One-order pilot safety:** Compute owner-approved quantity from minimum contract size, leverage/margin requirements and current monetary loss limits; validate protect-first or equivalent supported native bracket semantics, emergency handling of unprotected partial fills, stop-gap/slippage, trade fees and TP costs. Verify native protection survives process/transport loss and STOP-with-exposure.
5. **Separate owner authorization:** Only after reviewed proof and an authenticated owner-scoped START_LIVE session decision may a supervised one-order pilot be considered. No authorization exists now.

## 5. Regression and release boundaries

Focused tests in `tests/test_p06_first_order_feasibility.py` exercise 23 no-key/no-network cases: synthetic records, documented-only commands, REST/WS ambiguity, absent schema, wrong market, provider-null, explicit active exposure, stale samples, scope mismatch, WebSocket auth loss, ONE_WAY mismatch, fake equity, mock/GUI protection, partial child mismatch, fake signed assertion, stale catalog, redaction and disabled live gate.

**Tests are proof of fail-closed code only**, not economic performance or provider readiness. CI must run Python 3.11, 3.12, 3.13; report exact branch SHA and matrix conclusion. No modifications to Model A, P04 order state, signing, money, live gateway or deployment.

**Release:** review as Draft PR against `feature/p051-noninteractive-acceptance`. Do not merge, deploy, submit real/demo orders or use owner credentials.
