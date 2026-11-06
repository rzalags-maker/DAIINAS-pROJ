# P08 specialized trading-infrastructure audit

**Validated dependency chain:** P06 `7fe74ca08f482cafa1301c51b10a93f5e6a3fb17`, then
P07 `91713640788051e2fd75be80e495c96180214be1`.  
**Decision:** no P08 runtime integration is justified. `LIVE_TRADING` remains
disabled; this audit made no network provider call, exchange write, order,
cancellation, position change, transfer, margin/leverage change, credential
request, merge, or deployment.

## Compatibility matrix

| Candidate | Audited pin | Licence / Python support | Existing DAIINAS boundary | Demonstrated gap / benefit | Decision |
| --- | --- | --- | --- | --- | --- |
| KuCoin Universal SDK | `Kucoin/kucoin-universal-sdk@c2f39bdb` | MIT; generated SDKs include Python | P04 remains the only order lifecycle; P06 is the Bitsgap-specific live-readiness gate | Official direct-KuCoin documentation establishes a native contract, but not Bitsgap access or persistence | **EXPERIMENT** (provider evidence only) |
| HftBacktest | `nkaz001/hftbacktest@5f3ec40b` | MIT; Python package declares >=3.11 through 3.13, Rust/maturin plus NumPy, Numba, Polars and plotting stack | v4.7/P04 model PAPER IOC/limit outcomes, costs, latency assumptions and protective state | Queue-position and partial-fill simulation would improve limit realism only with authentic tick/L2/L3 data | **EXPERIMENT** (data-gated) |
| Pydantic | `pydantic/pydantic@9895381a` | MIT; project declares Python 3.11--3.13 | Existing manual parsers reject unknown envelopes, duplicate JSON fields, non-finite decimals and provider nulls fail closed | No reproducible validation weakness was found; coercive defaults risk concealing provider drift | **REJECT** |
| prometheus-client | `prometheus/client_python@e2f2bf9d` | Apache-2.0; project declares Python 3.11--3.13 | Redacted structured CLI/WS diagnostic status already exposes connection, provider-null and verification state | No session runtime or protected scrape endpoint exists; metrics could create sensitive labels and a second operational surface | **REJECT** |

No upstream code is copied, vendored or installed by P08. Thus the core runtime
dependency set remains unchanged and every candidate is removable because none
is present.

## 1. KuCoin native TP/SL contract matrix

The official source is the SDK's generated API specification at
[`spec/original/meta.json`](https://github.com/Kucoin/kucoin-universal-sdk/blob/main/spec/original/meta.json)
from the pinned commit. It is direct-KuCoin documentation, not a Bitsgap
contract and not a live verification.

| Capability | Official direct-KuCoin evidence | P06 / Bitsgap applicability |
| --- | --- | --- |
| Native conditional endpoint | `POST /api/v1/st-orders`, described as a take-profit/stop-loss order and accepting limit or market type | **Documented for KuCoin direct API only; unavailable evidence for Bitsgap** |
| Trigger prices | `triggerStopUpPrice` is take profit; `triggerStopDownPrice` is stop loss | Bitsgap `order_place` has no documented equivalent full trigger/bracket schema |
| Trigger reference | `stopPriceType` enumerates `TP` (last trade), `MP` (mark) and `IP` (index) | **Unverified** through Bitsgap |
| Position reduction | `reduceOnly=true` requires a size and cancels excess over position; `closeOrder=true` can infer close side/size | Bitsgap documents `ro`, but not native conditional-child semantics or enforcement |
| Identity | `clientOid` is required in this spec, max 40, with documented allowed characters; submit response includes exchange `orderId` | Bitsgap `id`/`eid` mapping is still P06-unverified |
| Side / quantity / mode | request includes `side`, contract `symbol`, `size`/`qty`/`valueQty`, leverage and `marginMode` | Cannot map safely without a provider-owned schema and contract precision evidence |
| Limit execution | `price`, `timeInForce`, `postOnly`, `hidden` and `iceberg` are documented | A trigger touch does not prove a limit fill; this remains a v4.7 PAPER scenario and is unverified through Bitsgap |
| ACK / lifecycle | ordinary order docs describe HTTP acknowledgement with `orderId`, followed by partial/full matching and WS/status reconciliation; cancellation only requests cancellation and must be confirmed by status/WS | P06 requires provider/exchange receipt correlation, fill state and child protection evidence; not established |
| Client disconnect persistence | the endpoint is exchange-native by its contract, but this source contains no evidence that a specific submitted protective order persists after a Bitsgap/DAIINAS disconnect | **Unverified**; cannot be inferred from native endpoint existence |
| OCO, sibling cancel, partial resizing | not established by the examined endpoint schema | **Unverified** and a P06 blocker |

### P06 result and smallest credible next step

This improves the diagnosis: native KuCoin *does* publish a conditional-order
surface, but it does **not** resolve the P06 question, which is whether the
existing signed Bitsgap API exposes it with exact semantics. The P06 decision
therefore remains **NO-GO**.

The smallest next step is a **read-only provider evidence request**: obtain a
Bitsgap-maintained Futures schema or written API contract that maps its command
to `/api/v1/st-orders` (or identifies another supported native route), including
all trigger fields, trigger reference, reduce-only/close behavior, child IDs,
partial-fill resizing, sibling cancellation, status reconciliation and
post-disconnect persistence. Compare that document to a redacted Bitsgap
catalog. If absent, mark the feature unavailable; do not add direct KuCoin keys
or a second gateway.

## 2. HftBacktest execution-quality assessment

The pinned README states that it reconstructs L2 Market-By-Price/L3
Market-By-Order books and models tick-by-tick feed/order latency and queue
position. Its Python package is a Rust extension (`maturin`) and lists NumPy,
Numba, Polars, matplotlib and holoviews. The upstream Rust README also warns
that its live-bot feature is not comprehensively tested; no live component was
evaluated or enabled.

DAIINAS v4.7 already uses explicit maker/taker costs, spread, adverse slippage,
IOC/limit scenarios, stop gaps and fails closed when a protection state is not
reconciled. It cannot answer queue priority or whether a touched passive target
would fill. HftBacktest could answer those questions **only** from contiguous,
timestamped, venue-specific trades plus L2/L3 book changes and measured feed
and order latency. This workspace has no such dataset; closed OHLCV must not be
invented into order-book events. Consequently no comparison, performance claim,
adapter or dependency is added.

A future offline experiment must freeze the same entry/exit intents, fee tier,
funding, contract metadata and latency model for both engines; use checksummed
raw tick/L2/L3 data; then report fill ratio, partial/unprotected duration,
touched-but-unfilled TP count, stop-gap loss, net P&L and drawdown. It must
remain offline and use no HftBacktest live connector.

## 3. Pydantic assessment

Pydantic supplies a mature typed validation library, but P08 found no
demonstrated external-boundary defect that its addition would fix. The existing
Bitsgap WS parser explicitly rejects malformed JSON and duplicate object keys;
the account state uses `PROVIDER_NO_DATA` rather than treating null as zero;
P06 keeps unknown protection/account evidence blocked; financial calculations
remain exact Decimal strings. Rewriting these paths around permissive model
coercion would be a broad change with a risk of accepting strings, defaults or
nullable values that currently fail closed.

**Reject:** retain the existing narrowly scoped validators and generated P07
edge tests. Reconsider only if a minimized real sanitized envelope is rejected
incorrectly or accepted unsafely and a strict (`extra=forbid`, no numeric
coercion) Pydantic adapter demonstrably fixes that one boundary.

## 4. Prometheus assessment

DAIINAS already produces redacted structured observation and diagnostic states:
connection, authentication result, topic validation, `PROVIDER_NO_DATA`,
reconnect diagnostics, P06 gate reasons and `orders_enabled=false`. It does not
run a mandatory 24/7 service, and P08 may not add one. A Prometheus exporter
would need a scrape listener, label/cardinality policy and authentication model;
account/symbol/order identifiers, balances and signals must never become labels.

**Reject:** existing structured status is sufficient for this session-scoped,
PAPER-only system. Reconsider only with a separately approved runtime-control
and metrics threat model that proves a localhost/private endpoint and a finite,
non-sensitive metric schema.

## Regression impact and final decision

P08 changes only this audit. There is no new private route, write function,
financial authority, ledger, bot, risk policy, data parser or core dependency.
The full preserved test suite remains the acceptance evidence; a passing MOCK
test remains insufficient evidence of live exchange functionality.

Final recommendations: **KuCoin SDK: EXPERIMENT** for the read-only provider
contract question; **HftBacktest: EXPERIMENT** only when authentic L2/L3/tick
data exists; **Pydantic: REJECT**; **Prometheus: REJECT**. P06's native
Bitsgap-protection, account reconciliation, receipt and STOP-with-exposure
blockers remain open.
