# DAIINAS × Bitsgap — autonomous event-driven control contract (PAPER-only)

**Status:** design / acceptance contract, not implemented execution routing. Owner goal: an independently running DAIINAS worker that switches promptly between qualified order opportunities without repeated Codex prompts or GUI clicks. **LIVE_TRADING=DISABLED; DAIINAS_ORDER_ROUTING=DISABLED.** No authenticated account operations or orders are authorized by this document.

## P0 wallet/account visibility — mandatory starting state for DAIINAS (2026-11-01)

**Owner requirement:** Bitsgap is the operator's existing connected KuCoin trading interface. The autonomous DAIINAS worker and its secure private control panel **MUST** observe the account's current balance and all committed exposure before applying Capital Ladder Model A. The previous screenshot "Available: 61.07 USDT" is only historical context; do not hardcode it as current funding. **Use Bitsgap**, not a new direct private KuCoin login.

### Observations — exact provider fields, not invented wallet bookkeeping

For the dynamically identified real **KuCoin Futures** `em` (never Spot/demo), make an authenticated Bitsgap read-only REST snapshot and then subscribe to WS updates. The documented `balance` topic returns `value.data[currency]` with `t` = total and `a` = available, both decimal strings; optional `l` = locked is **Spot only**, not a reliable Futures encumbrance. Use `positions` for actual open position size, entry, leverage, position margin `msize` when isolated, margin type `epm`, side `eps` and liquidation when reported; use `positions_settings` for configured position/margin mode and `orders` for pending order commitments. `orders_history` can contribute execution fees and actual fills after its documented delay. Do **not** claim `t` is Futures equity, that `a` is strategy spendable ACTIVE, or that `t-a` is known open-order margin without verified venue-specific semantics.

All values must be scoped to the exact Bitsgap key / real market identity, settlement currency, timestamp, and reconciliation generation. Decimal arithmetic only. On loss of auth, incomplete/duplicate/foreign data, unexpected mode, stale timestamps, WS sequence uncertainty, or unresolved external orders, flag `ACCOUNT_UNVERIFIED` and block new order intent; continue monitoring any known exposure.

### Three financial layers must remain separate

1. **EXCHANGE OBSERVED:** latest real Bitsgap balance `t/a`, supported position/order records, associated margin, execution costs and explicit `UNVERIFIED` quantities. This answers "what Bitsgap reports now".
2. **DAIINAS STRATEGY LEDGER:** once a complete account-specific financial identity, actual equity/settled cash, free collateral, existing reservations and open exposure have been **independently reconciled**, apply the **existing** Model A allocation and persistent ledger. Never seed a MOCK account from an exchange read or overwrite earlier initial funding. Reserve and ACTIVE are bookkeeping allocations unless collateral is actually segregated; reserve must not be consumed by any entry.
3. **ADMISSION BUDGET:** `min(confirmed venue free margin after authoritative obligations, uncommitted Model A ACTIVE, available campaign/portfolio risk budgets)` AFTER avoiding double subtraction of already-net free margin. Apply slot count, min-order costs, contract rules and outstanding positions to determine whether another PAPER candidate can be admitted. Unknown inputs => `NO_TRADE`.

For VERIFIED **eligible settled portfolio capital below 100 USDT**, owner-selected Model A remains in BOOTSTRAP, at most one eligible candidate subject to independent risks; do **not** apply the 100-USDT R50/A50 allocation. At 100 USDT Model A activates R50/A50/2; at 300 R50/A250/10. No amount from an image may activate these transitions.

### Required private control-panel contract

| Field | Origin | Meaning |
| --- | --- | --- |
| Provider / exchange / account type | Bitsgap `conf_enums`, authenticated context | Real KuCoin Futures vs Spot vs demo, observed/verified |
| Last snapshot age and connection state | REST + WS source | LIVE, STALE, UNVERIFIED, DISCONNECTED |
| **Total reported (`t`) / Available reported (`a`)** | Bitsgap `balance` | Raw exact USDT observation, privately display numeric amounts |
| Equity / true net free margin | Verified account reconciliation if supported | Never synthesize when Bitsgap API lacks needed fields; display UNVERIFIED |
| Open positions / pending orders | `positions` / `orders` | Exposure, ownership, known locks |
| Margin committed / fees / unrealized P&L | Validated position/history/other authoritative sources | Display numeric only when fully supported, else UNVERIFIED |
| Model A Reserve / ACTIVE / pending / deficit | Existing single Capital Ladder ledger | Protected fund and uncommitted active allocation; not just `available` |
| Eligible slots / active slots / next candidate | Existing v4.7 conveyor & risk selector | No double-funded orders; max 10 |
| **Next entry status** | Combined evidence and risk | `PAPER_ELIGIBLE` or `NO_TRADE(reason)`; real order routing DISABLED |
| Last verified account event | Event journal | Immutable timestamp, deduplicated changes and source |

The user must be able to read **real numeric total and available** in the authenticated **private** control panel once actually retrieved, without manually copying screenshots. Public CI output / issues / PRs must display only sanitized success/failure categories, never private raw balances or keys. On WS disconnect reauthenticate/resubscribe and obtain a fresh authoritative account snapshot before releasing slots or admitting new entries.

### Implement, test, and demonstrate

- Extend the existing **Bitsgap** read-only observation adapter/worker; do not use direct private KuCoin access.
- Resolve `em` dynamically; read `balance` + `orders` + `positions` + `positions_settings`; verify schema and exchange identity; use snapshot + WS stream for continuity.
- Map `t`/`a`/Spot-only `l` correctly; validate decimal precision, incomplete/unknown fields, negative amounts, duplicate IDs, mismatched scopes and staleness.
- Build private (not public log) status output with `t` and `a` as read-only live observation; add explicit provenance and `UNVERIFIED` fields for unsupported equity/free-margin semantics.
- **Do not** transfer a real observed number into the Model A funded journal until real account financial reconciliation is implemented and owner-reviewed. For PAPER, synthetic funding must remain named `MOCK`.
- Tests: observed available 61.07 while total/equity or outstanding positions differ; 61.07 example remains below Model A activation **only if eligible capital is independently verified**; both present and absent `l` (Futures), stale/disconnected WS, open order/position, duplicate snapshots, recovery/reconnect, protected reserve, exact-once cash events and source mismatch.
- Acceptance: after authorized authenticated Bitsgap read, private control panel reports *what balance is observed now*, associated timestamps and open exposure; state clearly whether strategy-financial reconciliation is complete and whether next PAPER intent is eligible. Never claim authentication PASS based on mocked response or UI screenshot.
- No order writes, position close, leverage/margin changes, deposits, transfers or real trading activation.

Primary evidence: https://github.com/Bitsgap/bitsgap-api-docs/blob/main/docs/topics/trading.md (balance t/a/l, orders, positions) and https://github.com/Bitsgap/bitsgap-api-docs/blob/main/docs/topics/portfolio.md (orders_history).

---

## P0 verified 2026-11-01 — the exact Bitsgap terminal-to-exchange control protocol

**Owner direction:** the existing linked Bitsgap ↔ KuCoin connection is the chosen integration route. No additional direct private KuCoin API login is a precondition for researching/using the documented Bitsgap API. Do not revive `feature/kucoin-futures-startup-preflight-20261101` as a required path. The operator reports active trading already works through the terminal. Our task is to learn/control the **Bitsgap command interface**, not challenge that observed terminal behavior.

**Found the function window:** the official signed `{"topic":"manual"}` response is the **runtime topic/function catalog**, containing topic descriptions, `transport.ws/rest`, `subs`, per-topic limits, required parameters and examples. The signed `{"topic":"conf_enums"}` is the dynamic parameter/enum catalog, including `market.items` → exchange `em`, `order_side` → `eos`, `order_type` → `eot`, `order_state` → `eost`. This is not a secret browser bundle or an undocumented internal endpoint.

**Official endpoints:**
- WebSocket: `wss://stream.bitsgap.com/`; Ed25519-authenticated session, subscription and commands, with a fresh signed auth frame upon reconnect.
- REST: `POST https://open.bitsgap.com/api/v1/topic`; one topic per signed request using a canonical Ed25519 signature. REST does not accept subscriptions.
- Both are the client's **Bitsgap** connection. Bitsgap's separate server-side link to KuCoin is not directly visible from the browser's Network inspector; order lifecycle and exchange-assigned identifiers give its observable evidence.

**Documented control-plane function map:**

| Operator maneuver | Bitsgap topic | Required observation / identity |
| --- | --- | --- |
| Discover supported functions and limits | `manual` | Parse dynamic capabilities, not static assumptions |
| Resolve connected market codes and buy/sell/state enums | `conf_enums` | Dynamically discover **real KuCoin Futures** `em`; never substitute Spot or a demo constant |
| Resolve instrument tick/lot/minimum constraints | `conf_pairs` | Validate exact pair/config and costs before any strategy admission |
| Observe funds | `balance` | Exchange-scoped currency records (not automatically Model A ACTIVE) |
| Observe open orders | `orders` | Per-pair order state, `id`, `eid`, `apiid` and statuses |
| Observe open positions and mode | `positions`, `positions_settings` | Pair/side/size/leverage/margin, `epmd` when account-wide |
| Request creation (DOCUMENTED BUT DISABLED) | `order_place` | Futures fields `em,pair,eot,eos,am`, optional `epps,epm,lv,etif,ro,apiid`, price `pr` for limit |
| Request cancellation (DISABLED) | `order_cancel` | Bitsgap `id` or exchange `eid`+pair, not an unverified symbol-only command |
| Inspect a specific order | `order_detail` | `eost`, IDs, pair/side/amount/price |
| Request position close (DISABLED) | `position_close` | Closing request, not proof of a flat position |
| Request leverage/margin changes (DISABLED) | `leverage_change`, `margin_type_change`, `margin_size_change` | Re-read settings and risks; not owner authorization to mutate ONE_WAY |
| Confirm settled execution/costs | `orders_history` | `order_id`, `apiid`, `ext` (external), filled amount, fee map and timestamps |

**Observable packet chain:** `order_place` → `value.res=true,eost=3,id=<bitsgap-order-id>` = Bitsgap accepted/processing; `value.res=true,eost=4,id=<bitsgap-order-id>,eid=<exchange-order-id>` = placement reached exchange. **Neither event proves fill or protected position.** For each order, wait for `orders` and `positions` subscription updates and reconcile `orders_history`, fee attribution and no unrecognized external orders. `apiid` is a documented correlation identifier (up to 250 characters). Never release a conveyor slot solely on an order response or disappearance from the Open Orders list.

**Official executable proof of mechanics:** `Bitsgap/bitsgap-api-docs/examples/python/examples/walkthrough.py`, `phase_futures` (approx. lines 279–324), uses a **demo** venue to subscribe to `positions`/`positions_settings`, submit `order_place`, observe `eost=4`, wait for position update, call `position_close`, then wait until positions report closure. Spot phase (approx. lines 140–274) traces `apiid`, Bitsgap order ID, order acknowledgement, balance lock, cancellation, and settled amounts. The reference code is vendor-supplied test evidence, NOT proof our own account or latency meets acceptance.

**Hard gap:** the publicly documented `order_place` field list does NOT expose an explicit native bracket/stop-loss/take-profit set of parameters. Bitsgap's Smart Trade GUI capabilities must **not** be assumed equivalent to `order_place`. Before allowing even a demo autonomous full round-trip, determine from the live topic catalog and official vendor supported examples exactly how protective orders can be created, acknowledged, persisted after client disconnect and sized reduce-only. Otherwise the controller may observe and PAPER model but must not risk an unprotected real entry. A future close request is not equivalent to an acknowledged exchange-native SL.

**Where to inspect the real browser exchange (read-only observation):** in the already logged-in Bitsgap Trading terminal, Chrome Developer Tools → Network → Fetch/XHR and WS → Messages. Identify interface-to-Bitsgap command/status packets and match topic names, order IDs and timestamps. Never copy Authorization headers, Cookies, signed frames, PEM material or private payloads; do not send a live order just to generate a test trace. **Do not assume** the site's private browser wire format equals the public developer API format.

Vendor primary sources:
- https://github.com/Bitsgap/bitsgap-api-docs/blob/main/docs/topics/reference.md
- https://github.com/Bitsgap/bitsgap-api-docs/blob/main/docs/topics/trading.md
- https://github.com/Bitsgap/bitsgap-api-docs/blob/main/docs/topics/portfolio.md
- https://github.com/Bitsgap/bitsgap-api-docs/blob/main/docs/ws/README.md
- https://github.com/Bitsgap/bitsgap-api-docs/blob/main/docs/rest/README.md
- https://github.com/Bitsgap/bitsgap-api-docs/blob/main/examples/python/examples/walkthrough.py
- https://bitsgap.com/blog/bitsgap-api-explained-bring-your-own-trading-strategy

**Next implementation (separate reviewed code, not enabled here):** extend the existing Bitsgap Ed25519 **read-only** adapter with `manual` capability introspection, dynamic actual KuCoin Futures enum identification, and read-only `balance/orders/positions/positions_settings/orders_history/conf_pairs` requests, backed by malformed and partial-response tests. **No order commands, no live trades, no account secrets in logs**.

---

## 1. Existing system is the authority; do not build a second trading bot

Reuse `PortfolioLedger`, the v4.7 `ConveyorMixin` and single-writer durable journal, `CapitalLadder` Model A, `adaptive_execution.select_sniper`, the existing market/quote/deep-data observation path and `execution_boundary.InertOrderGateway`. The current `tests/test_v47_conveyor.py` already includes cycle turnover, partial fills, protection gating, ten-slot portfolio risk, crash/restart, pause/stop and pinned-stream tests. Their synthetic PAPER passes do **not** prove live exchange execution or latency.

The previous `PR #18` adds strictly read-only **Spot** balance/open-order REST validation and independent order enum/duplicate ID checks. It does not verify **Futures** positions, account scope, exchange-native protection, exchange write authorization, or live trading.

Codex = code/research/test agent; DAIINAS worker = deterministic event-driven runtime. A Codex conversation cannot substitute for a persistent worker or an authenticated operator STOP acknowledgment.

## 2. Control-plane vs observation-plane vs venue execution

| Function | Primary authority | Method | Failure behavior |
| --- | --- | --- | --- |
| Whole supported Futures universe | Existing KuCoin catalog/tickers observer | Bounded scanner, do not treat price mover list as a signal | NO_TRADE if scope unverified |
| Fast per-symbol quotes/trades/L2/candles | Existing sequence/continuity-validated public provider streams | Prioritize pinned exposures; deep-observe bounded shortlist | STALE/UNKNOWN => block new entries |
| Bitsgap account observations | Documented WS `balance`, `orders`, future `positions`/ `positions_settings`; REST fallback snapshot | One signed authenticated session and authorized subscriptions, read-only first | Reject unknown schemas/identities; freeze slot release |
| Venue order/fill/fee truth | Eventually verified exchange-native account reconciliation, not a chart pixel | Durable idempotent identifiers, compare WS event with authoritative REST/state | Do not infer a close, fill, TP/SL or freed slot from a UI highlight |
| Capital and eligibility | Current durable DAIINAS Model A portfolio ledger | Realized fully settled net after fees/funding; current actual equity/free margin and reservation | Reserve is protected; loss reduces capacity |
| Signal + risk | Existing v4.7 sniper selector and risk/cost/lot/portfolio gates | LONG / SHORT / NO_TRADE; adaptive x1–x5 PAPER feasibility, exact net +2% of campaign allocation | NO_TRADE when infeasible |
| Order state machine | Existing Conveyor and single journal writer | One event-to-intent transaction, no additional bot/wallet state | HALT when protection or lifecycle unverified |
| GUI terminal | Operator verification/observability only | One-time documented mapping for Trading, chart, pair, order form, Positions, Open Orders, settings | Never depend on browser clicking in a latency-critical execution path |

**Source limitation:** Bitsgap `market_price` WS whole-exchange updates are sent at most **once every 10 seconds per subscriber**. It is a coarse discovery/overview feed, not a micro-entry tick/L2 source. Bitsgap per-pair `price` and its `balance/orders/positions` topic subscriptions are distinct. Obtain required high-frequency trade/BBO/sequence-verified L2 from the existing compatible public provider and measure actual freshness. Do not describe this as HFT until independently benchmarked.

**WebSocket contract:** `wss://stream.bitsgap.com/`, signed auth frame, no secrets in URL; reauthenticate and resubscribe after disconnect; handle 4413 slow-consumer, 4429 rate limiting, 4403 revoked key. Per-topic limits shared with REST; at most 100 messages / 10 seconds per WS connection and 100 topics / message. Real account auth has potentially trade-capable underlying key privileges even with read-only application allowlists.

**Unresolved provider-contract discrepancy:** official top-level API README describes commands on REST and WS, while `docs/topics/trading.md` states trading commands only on WS. Do NOT implement a live command transport until this is reconciled with current vendor documentation, supported tests, account permissions and explicit owner/legal authorization. Neither path is authorized in this phase.

## 3. Event-driven opportunity turnover

Maintain a bounded prepared candidate queue for observation only; precompute feasibility on fresh market inputs, but **do not reserve funds for unapproved candidates**.

Event order within the existing atomic journal writer:

1. **Ingress:** classify venue/provider event by exchange, market, pair, immutable event/sequence, receipt timestamp and data freshness. Deduplicate and quarantine gaps and foreign account identity.
2. **Reconcile:** update owned open orders, partial fills, positions, native protective siblings, fees/funding, free collateral and unknown exposures. A quote touching TP is NOT a fill.
3. **Finalize:** only a fully reconciled close (position quantity zero, fills accounted, stale/unknown order siblings resolved and costs booked **once**) may release a funded slot. Partial close or UNKNOWN protection never releases a complete slot.
4. **Ladder:** apply fully settled campaign net P&L to the **same** Model A ledger; losses first shrink ACTIVE capacity; protected RESERVE does not cover drawdown.
5. **Market shortlist:** rank independent qualified symbols and directions; retain pinned existing open exposures even when another symbol becomes more attractive.
6. **Risk recheck:** verify fresh evidence, actual free margin, lot/tick/min notional, maker/taker/exit costs, potential funding/gap/slippage, position limits, correlation, stop money-loss cap and target feasibility.
7. **Decision:** at most one new PAPER intent for each newly confirmed eligible slot; duplicate/replay/stale/crossed book/unsafe minimum lot => NO_TRADE. Never manufacture wins or open ten orders just because ten slots exist.
8. **Protect:** modeled PAPER child ACK is not an exchange ACK. Missing protection disarms new entries, preserves marked exposure and requires safe exit reconciliation.
9. **Persist:** transactionally journal every status and timing marker before acknowledging STOP/PAUSE and before considering a next entry.

Representative state progression: `OBSERVED -> QUALIFIED -> RISK_GATED -> PAPER_RESERVED -> ENTRY_PENDING -> PARTIAL/FILLED -> PROTECTION_PENDING -> PROTECTED -> EXIT_PENDING -> RECONCILING -> CLOSED_SETTLED -> SLOT_ELIGIBLE`. Every transition is guarded. `UNKNOWN`, `STALE`, `HALT`, `PAUSED`, `STOPPING` are safety states; none opens a new position.

**ONE_WAY** remains an owner-configured Futures requirement, not verified by Spot reads, and must never be mutated by the read-only adapter.

## 4. Trading UI mapping — for operator training, not automated order execution

Official Bitsgap user-facing terminal: `Trading` → exchange/pair selector, chart/Technicals, entry order form (Market/Limit/conditional types, size, leverage/margin when available), protective TP/SL, `Positions` and `Open Orders`, `Trade History`. Top-right settings gear → `Layout` / `Settings`, Futures One-way/Hedge. Demo Mode may be enabled from the profile menu. **Actual user-account layout and KuCoin capabilities still require sanitized screenshot/observed proof.** Do not equate Smart Orders, standard entry and native reduce-only protective order lifecycle. Browser control is for setup audit and visual cross-check, never the fast event loop.

## 5. Observability and performance contract

Record sanitized structured timing and outcomes for every synthetic state transition, not balances, keys or private data:
`source_event_ts`, `wire_receipt_ts`, `decision_ready_ts`, `journal_commit_ts`, `event_sequence`, `symbol_token_hash`, `action_category`, `deny_reason`, `source_freshness_ms`, `pending_count`, `eligible_slot_count`, `reconciliation_state`, `worker_heartbeat_age_ms`. Distinguish provider delay from local CPU delay and from actual venue ACK.

Initial **engineering targets to measure, not achieved claims**: local PAPER event-receipt-to-decision p95 <= 250 ms and p99 <= 1000 ms on a declared test host; no unbounded queue growth or stale decisions in burst/replay tests. End-to-end venue latency, exchange fill speed, and effective freshness must be measured independently; local latency cannot compensate for a 10-second vendor aggregate update cadence.

Safety wins over speed. STOP acknowledged only after a running, authenticated worker durably disarms entries, reports whether simulated/native exposure remains, and either confirms STOPPED_FLAT or STOPPED_WITH_EXPOSURE; never claim an offline Codex reply is a worker ACK.

## 6. Mandatory acceptance before any live-capable adapter

- **Control-plane tabletop:** repeatably map each terminal control to the exact validated DAIINAS field/risk rule; never reuse UI PNL % as +2% NET campaign allocation.
- **Read-only WS prototype:** authenticate without emitting credentials; dynamic demo/real venue distinction; subscribe only to explicitly permitted topics; reconcile REST snapshot vs stream; test broken messages/duplicate IDs/unknown enums; rate-limit and reconnect.
- **Synthetic PAPER turn-over:** ten occupied slots, one fully confirmed net close, exactly one eligible next intent; partial close, unconfirmed sibling, late cancel and unknown external order => zero new intents.
- **Adverse paths:** stale feeds, dropped WS sequence, slow-consumer disconnect, auth failure, new/duplicate events, partial fill, TP touch/nonfill, stop gap, missing native protective ACK, owner STOP during entry, crash after journal write and replay; verify no double financial posting, no reserve use.
- **Repeatable performance:** capture p50/p95/p99 local event-to-decision on specified hardware, load profile, symbol count, quoted-source freshness and daily session; publish limits and failure reasons, never invent high-frequency capability.
- **Deployment contract:** standalone on-demand durable worker, backup/single-writer recovery, authentic START/PAUSE/STOP ACK and emergency no-new-entry latch independent of Codex tasks.
- **Financial/legal gate:** authenticated Futures capability, actual per-contract fees, ONE_WAY and protection semantics plus UK retail derivatives regulatory eligibility must be established separately. Otherwise remain PAPER. Do not enable any actual exchange write calls without new explicit owner authorization.

## Sources

- Bitsgap official API docs: https://github.com/Bitsgap/bitsgap-api-docs (docs/ws/README.md, docs/topics/public.md, docs/topics/trading.md, docs/rest/README.md).
- Bitsgap terminal: https://bitsgap.com/helpdesk/article/21090079586076-Trading-Terminal-Settings
- Bitsgap manual order form: https://bitsgap.com/en/helpdesk/article/18033964614812-How-to-Place-an-Order-Manually
- Bitsgap demo: https://bitsgap.com/helpdesk/article/13512068818332-How-to-use-Bitsgap-Demo-Mode
- FCA COBS 22.6: https://handbook.fca.org.uk/handbook/cobs22/cobs22s6
- Existing repository owner contracts: AGENTS.md, docs/V47_IMPLEMENTATION.md, docs/V47_ADAPTIVE_LEVERAGE_WHOLE_MARKET_CONVEYOR.md, docs/V46_CAPITAL_LADDER_CONTINUOUS_LOOP.md.
