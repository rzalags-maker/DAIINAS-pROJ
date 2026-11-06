# P06 — first real protected Futures order feasibility

Issue [#36](https://github.com/rzalags-maker/DAIINAS-pROJ/issues/36). Baseline: verified P05.1
`246e6a09d409bafd2bf7d224d1606baf6a0a89d7`, branch
`feature/p051-noninteractive-acceptance`, Draft PR #35. P06 branch:
`feature/p06-first-order-feasibility`; Draft PR targets P05.1, never main.
The stacked dependencies, P04 START_LIVE hard block, existing Ed25519 signing,
ONE_WAY requirement, one v4.7 Model A ledger, ladder and money-risk rules remain
binding. This is a read-only feasibility decision; it grants no trade authorization.

Reviewed 2026-11-05 via GitHub connector. Official provider repository main resolved to
`d27611b63d56c65c9797e61d34b40b1f175a7664` (commit date 2026-07-29). All citations below pin that exact commit.
No private API request, credentials, demo order, real order, cancel, close or
margin/leverage operation was performed. Provider examples were inspected as source,
never executed.

## Defensible decision

**NO-GO for the first real protected KuCoin Futures USDT order.**
Top decisive blocker: **BLOCKED_NATIVE_PROTECTION_CONTRACT_UNVERIFIED**.
The existing public Bitsgap developer API documentation establishes ordinary
Futures entry/cancel/detail/close operations and a reduce-only flag. It does not
establish a supported API contract to create exchange-native SL and TP triggers,
acknowledge both children at the venue, or guarantee independent persistence after
Bitsgap and DAIINAS disconnect/STOP.

This is **unavailable evidence**, not demonstrated unsupported functionality.
The reviewed enum examples contain ellipses and the runtime catalog may expose
more than the static documentation. No provider statement denying support was
found, and no account-specific command/protection proof was obtained.
Therefore do not use NOT_SUPPORTED_WITH_EVIDENCE for native TP/SL here.

## Evidence classes and meanings

- PUBLIC_DOC: provider source documents a mechanism; it has not been exercised for this account.
- READ_ONLY_LIVE_CATALOG_DECLARED: a historically or newly observed authenticated catalog actually declared the specific capability. This is not permission.
- ACCOUNT_VERIFIED: independently supported account-specific observation, bounded to the observed property, scope, cohort and time.
- UNVERIFIED: missing or insufficient proof.
- BLOCKED: resulting admission decision when a prerequisite is missing or contradicted.
- NOT_SUPPORTED_WITH_EVIDENCE: requires an explicit provider denial or a demonstrated supported-scope exclusion; absence from an example does not qualify.

Historical account auth is ACCOUNT_VERIFIED only for its 2026-11-01 read observation,
not current session health, money, order permission or native protection.
The historic FUTURES_CATALOG=PASS establishes market-discovery observation only;
it does not support labeling all four write/detail commands as live-catalog-declared
because no retained per-command schema/transport records were supplied.

The legacy `BitsgapCapabilityRegistry` state `UNSUPPORTED` means a topic was not
advertised by that catalog (or was declared demo-only for real Futures); it is not
proof that Bitsgap cannot implement native protection. P06 preserves that registry
behavior but does not elevate catalog absence to `NOT_SUPPORTED_WITH_EVIDENCE`.
A documented unsupported real-market scope can block the selected scope without
establishing global product incapability.

## One-order contract matrix

| Required capability | Public evidence | Classification for the future real pilot / missing proof |
| --- | --- | --- |
| Signed WS channel | [WS auth, lines 13–17](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/ws/README.md#L13-L17); [auth success and reconnect, 77–94](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/ws/README.md#L77-L94) | PUBLIC_DOC; historical ACCOUNT_VERIFIED auth on 2026-11-01. Fresh account-bound cohort/session is UNVERIFIED. Auth alone grants no demonstrated order permission. |
| Signed REST channel | [REST signing, 15–74](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/rest/README.md#L15-L74) | PUBLIC_DOC; unchanged existing signing should be reused. No command execution proof. |
| order_place availability/schema | [trading 317–355](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/trading.md#L317-L355) | PUBLIC_DOC. Real account permission, exact current command schema and chosen transport UNVERIFIED. Fields are em,pair,eot,eos,am,pr,epps,epm,lv,etif,ro,apiid. |
| order_cancel availability/schema | [trading 403–433](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/trading.md#L403-L433) | PUBLIC_DOC. Account permission/transport UNVERIFIED. Lookup is id OR eid+pair, not both. |
| order_detail availability/schema | [trading 481–516](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/trading.md#L481-L516) | PUBLIC_DOC. Read operation is known to registry but not existing protected read transport allowlist; do not silently widen it. Current account invocation/retention/completeness UNVERIFIED. |
| position_close availability/schema | [trading 522–566](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/trading.md#L522-L566) | PUBLIC_DOC. It creates a closing order; its ACK is not a closed position. Account permission/transport UNVERIFIED. |
| Transport resolution | [trading line 4](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/trading.md#L4) says commands WS-only; [REST 108–114](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/rest/README.md#L108-L114) allows commands asynchronously | BLOCKED if unresolved/ambiguous. Do not resolve using a write. A fresh scoped catalog plus supported provider semantics must resolve selected transport; REST success is task acceptance only. |
| Runtime manual schema | [reference 30–107](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/reference.md#L30-L107) defines effective topic catalog, transport.ws/rest, futures_only/demo_only, params | PUBLIC_DOC; historic discovery partly observed. Exact current per-command declarations are UNVERIFIED. Boolean flags only appear when true (94–96); absent params means validation is internal, not that every field is allowed. Declaration never proves venue protection semantics or account permission. |
| eot/enums and real market scope | [reference 109–145](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/reference.md#L109-L145) | PUBLIC_DOC; discovery must bind real KUCOIN_FUTURES (not demo/spot) dynamically. LIMIT/MARKET examples are nonexhaustive. No demonstrated native STOP/TP eot contract. |
| Native SL creation, trigger reference and trigger order type | [public order_place fields 337–355](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/trading.md#L337-L355) | UNVERIFIED → BLOCKED. Missing exact command/fields and market/last/index trigger semantics, stop-market versus stop-limit behavior, and venue acceptance. A mark-price topic would not establish a stop trigger parameter. |
| Native TP creation, trigger reference and trigger order type | [same schema](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/trading.md#L337-L355) | UNVERIFIED → BLOCKED. Need exact native TP mechanism; limit TP is not guaranteed close or proof of a bracket. |
| Reduce-only | [trading 130](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/trading.md#L130); [353](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/trading.md#L353) | PUBLIC_DOC: ro closes without flipping. Enforcement for both protective children/venue and residual exposure remains UNVERIFIED. |
| Child ACK and venue eid | [trading 119–139](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/trading.md#L119-L139); [321–326](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/trading.md#L321-L326); [359–399](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/trading.md#L359-L399) | PUBLIC_DOC for ordinary order IDs/stages only. Both protective children's acknowledged exchange IDs, parent/exposure linkage and native trigger state are UNVERIFIED. Demo eid=id is not venue proof. |
| Partial entry/exit child sizing | [trading 123–137](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/trading.md#L123-L137); [152–169](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/trading.md#L152-L169) | PUBLIC_DOC for remaining am/filled ame and reduce-only trim timestamps. Atomic/bracket sizing after partial entry/exit and residual SL/TP coverage UNVERIFIED. Reject mismatched coverage. |
| OCO / sibling cancellation | [order_cancel stages 403–477](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/trading.md#L403-L477) documents ordinary cancellation only | UNVERIFIED. Need supported sibling/OCO semantics and proof sibling cannot flip/reopen after other child fills. |
| Replacement/reconciliation | [cancel stages 403–477](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/trading.md#L403-L477); [detail retention 481–507](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/trading.md#L481-L507) | UNVERIFIED protection replacement/atomicity. Existing ordinary commands do not prove no unprotected gap or duplicate-order-safe replacement. |
| Protection survives Bitsgap/DAIINAS disconnect and STOP | [WS session TTL and reauth 93–94](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/ws/README.md#L93-L94) | UNVERIFIED → BLOCKED. Session reconnection guidance is not venue persistence. Need provider contract plus independent venue/remote-side record for native children; must survive loss of both applications. STOP must disarm entries without canceling protective children by default. |
| ACK versus placement/fill/close | [trading 141–150](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/trading.md#L141-L150); [315–326](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/trading.md#L315-L326); [530–531](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/trading.md#L530-L531) | PUBLIC_DOC. NEW/OPEN/OPENED are distinct; OPENED+eid proves ordinary placement, not fill/protection or settlement. CHECK_CLOSED is unresolved. Closed position evidence must come from reconciled subscriptions, not close ACK. |
| apiid/id/eid correlation, exactly-once safety | [trading 119–139](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/trading.md#L119-L139); [355](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/trading.md#L355); [portfolio 35,79–90](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/portfolio.md#L79-L90) | PUBLIC_DOC identifies three ID roles and exact apiid history filter. No documented idempotency guarantee for repeating order_place with apiid. Duplicate-safe recovery/ownership mapping remains UNVERIFIED; do not resend after uncertain ACK. |
| Exposure ownership / external orders | [orders scope 65–85](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/trading.md#L65-L85); [portfolio 79–90](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/portfolio.md#L79-L90) | PUBLIC_DOC: open orders account-wide by pair; history ext marks directly placed external order, absent apiid includes non-API/old records. Actual complete owned/external inventory UNVERIFIED. apiid-filtered history cannot exclude other exposure. |
| History fees, funding and delay | [portfolio 14–17](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/portfolio.md#L14-L17); [69–93](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/portfolio.md#L69-L93) | PUBLIC_DOC: filled/partial orders only, six months, delayed seconds, optional fee (absence not zero), pagination cap. Complete funding/equity/settled cost reconciliation UNVERIFIED; fee map is not funding proof. |
| Equity/free margin/committed collateral | [balance fields 57–63](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/trading.md#L57-L63); [isolated position margin 231–248](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/trading.md#L231-L248) | PUBLIC_DOC documents currency t/a and isolated msize; l is Spot-only. True Futures equity/free margin/cross collateral/committed margin semantics UNVERIFIED. Wallet a or t-a cannot fund Model A; self-entered/UI amounts cannot pass. |
| Provider-null orders/positions/settings completeness | [trading 18](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/trading.md#L18); [positions 188–248](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/trading.md#L188-L248) | Historical provider-null orders/positions are UNKNOWN, not zero. Supported authoritative complete inventory/current cohort is UNVERIFIED. Settings null cannot establish ONE_WAY. |
| Authorized ONE_WAY | [trading 173–184](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/trading.md#L173-L184) | PUBLIC_DOC says account epmd or per-pair epps; historical mode observation is partial. Need explicit owner scope plus fresh noncontradictory venue mode. No automatic mode/margin change. |
| Contract minimums and cost-risk budget | [reference 147–211](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/docs/topics/reference.md#L147-L211) | PUBLIC_DOC: price/amount/total steps/min/max, lot size, fees, no_place, limit_only; data cached minutes. Exact real contract and actual account fee/funding/gap bounds UNVERIFIED. Existing Model A/ladder/risk rules must decide feasibility, never be relaxed. |

## Required provider confirmation, smallest decisive ask (do not send automatically)

Ask Bitsgap for one supported developer-API example/contract, explicitly scoped to
real KUCOIN_FUTURES USDT ONE_WAY, that gives:

1. Exact native SL and TP create command names, transport and parameter schemas,
   trigger price/reference (mark/last/index), trigger order type and valid eot codes;
   whether both children can protect a partial fill without any unprotected interval.
2. Child/parent/exposure IDs, real venue eid/acknowledgment states and read-only query
   path; reduce-only enforcement, residual sizing, OCO/sibling behavior and safe replacement.
3. Explicit statement of where triggers live and that accepted protection continues
   after Bitsgap outages, client disconnect, DAIINAS process death and STOP.
4. Command/account permissions and whether apiid is merely a correlation label or
   a deduplication/idempotency key; how uncertain acceptance is resolved without blind resend.

An explicit vendor answer that this public API cannot create persistent venue-native
children would justify NOT_SUPPORTED_WITH_EVIDENCE with dated citation. Until then
the correct label is UNVERIFIED. User-facing Smart Trade/TP/SL help is UI-only;
it cannot fill any public-command proof cell above.

## Python example interpretation

[walkthrough.py:1–13](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/examples/python/examples/walkthrough.py#L1-L13)
explicitly resets and writes demo exchanges. [279–324](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/examples/python/examples/walkthrough.py#L279-L324)
changes leverage/margin, opens a market position, changes margin, closes it and checks
subscriptions. It does not create or validate SL/TP children. [408–420](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/examples/python/examples/walkthrough.py#L408-L420)
shows that replies can disappear across reconnect and outcome must be observed
independently. [327–365](https://github.com/Bitsgap/bitsgap-api-docs/blob/d27611b63d56c65c9797e61d34b40b1f175a7664/examples/python/examples/walkthrough.py#L327-L365)
shows delayed history/apiid filtering. This is PUBLIC_DOC example logic, never
account/venue proof; P06 must not execute the walkthrough.

## Preserved historical account evidence

At baseline 246e6a09d409bafd2bf7d224d1606baf6a0a89d7,
[BITSGAP_FUTURES_OBSERVE.md:87–102](https://github.com/rzalags-maker/DAIINAS-pROJ/blob/246e6a09d409bafd2bf7d224d1606baf6a0a89d7/docs/BITSGAP_FUTURES_OBSERVE.md#L87-L102) records
[run 41334246585](https://github.com/rzalags-maker/DAIINAS-pROJ/actions/runs/41334246585)
(2026-11-01 17:59 UTC): FUTURES_CATALOG=PASS, balance/settings validated,
orders/positions UNVERIFIED, Model A unreconciled and order routing disabled.
[Lines 177–210](https://github.com/rzalags-maker/DAIINAS-pROJ/blob/246e6a09d409bafd2bf7d224d1606baf6a0a89d7/docs/BITSGAP_FUTURES_OBSERVE.md#L177-L210) record
[run 41337235142](https://github.com/rzalags-maker/DAIINAS-pROJ/actions/runs/41337235142) (2026-11-01 18:34 UTC):
WS authorization PASS, wallet/settings updates validated, orders and positions
PROVIDER_NO_DATA. This is genuine historical read-only account evidence, not current
venue/account/protection readiness.

Audit d653362090fe3065585218da8b06344338ed2d40,
[system audit:206–220](https://github.com/rzalags-maker/DAIINAS-pROJ/blob/d653362090fe3065585218da8b06344338ed2d40/docs/DAIINAS_INDEPENDENT_SYSTEM_AUDIT_2026-11-02.md#L206-L220):
account identity/completeness, real collateral, fees/funding and persistent native
protection are unverified; AccountState is counts/modes rather than a full financial
inventory, and the standard observation pipeline does not invoke the new registry's
live discovery. Do not label static registry metadata as an actually observed catalog.

## Shortest future path

1. Existing read-only path: establish complete account-bound orders/positions/settings,
   authoritative true free margin/equity/committed collateral and freshness/cohort
   consistency. Preserve provider-null as unknown and external exposure as blocked.
2. Obtain above exact Bitsgap native protective-command contract; independently
   verify venue persistence and child lifecycle from supported existing evidence.
   This is the decisive vendor gate; repeated wallet probes cannot resolve it.
3. Only then separately review minimal execution mapping on the existing engine:
   chosen transport/permission, receipt versus venue-ID/fill/protection lifecycle,
   durable idempotency and uncertain-result recovery (apiid alone is not enough).
4. Apply existing Model A ledger and money caps, real contract minimums/fees,
   partial-fill/gap budget, and durable emergency STOP-with-exposure handling.
5. Only after review and separately scoped owner START_LIVE authorization permit
   one supervised protected real pilot. P06 implements none of these writes.

Concrete fork: first pursue Bitsgap-specific supported-command confirmation.
If explicitly unsupported, assess a supported venue-native alternative or a separately
approved minimal alternative gateway behind the existing execution interface; preserve
the one ledger/engine and existing risk contract. No direct KuCoin connector, browser
execution or unprotected entry is silently implemented in P06.

## P06 implementation and verification

`daiinas.bitsgap_first_order` is a pure, offline assessor over the existing
`BitsgapCapabilityRegistry`, redacted `AccountAcceptance`, and P05.1 session
projection. It neither imports nor exposes any command transport. Its report contains
only gate statuses, evidence classes, local source age, fixed missing-proof tokens and
reason codes; it never accepts money, IDs, credentials, UI claims or raw account data.
`scripts/verify_p06.py` intentionally supplies no account evidence and must report
`BLOCKED` with `orders_enabled=false`. The CI workflow saves that redacted report.

The 2026-11-06 deterministic suite covers declared-but-not-permitted commands,
transport mismatch, native-contract and persistence gaps, provider-null/open
inventory, stale cohorts, scope/demo/ONE_WAY/STOP conditions, malformed claims, and
partial-entry/exit protection-size mismatch. A fully consistent synthetic fixture is
only `SYNTHETIC_NOT_LIVE_VERIFIED`; a REAL fixture remains `BLOCKED`.

Local full regression: 539 tests passed on Python 3.11.17 (162.269s), 3.12.14
(151.000s), and 3.13.5 (164.317s). No provider, credential, order, cancellation,
close, leverage or margin call was made. P04 remains an inert MOCK gateway and
`START_LIVE` remains blocked.

