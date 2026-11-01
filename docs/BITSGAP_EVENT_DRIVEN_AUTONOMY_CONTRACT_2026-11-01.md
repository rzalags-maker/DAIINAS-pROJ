# DAIINAS × Bitsgap — autonomous event-driven control contract (PAPER-only)

**Status:** design / acceptance contract, not implemented execution routing. Owner goal: an independently running DAIINAS worker that switches promptly between qualified order opportunities without repeated Codex prompts or GUI clicks. **LIVE_TRADING=DISABLED; DAIINAS_ORDER_ROUTING=DISABLED.** No authenticated account operations or orders are authorized by this document.

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
