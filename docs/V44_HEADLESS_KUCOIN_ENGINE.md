# DAIINAS — Owner decision: HEADLESS KuCoin Trading Engine (2026-11-01)

## Objective: KuCoin API is the operational interface; no Bitsgap-like GUI

The owner supplied Bitsgap interface screenshots **solely as a functional architecture reference**: demonstrate what information and order-management capabilities an external exchange API integration can make available internally. They are NOT an invitation to audit screenshot balances, trading status, permissions, account eligibility, leverage or specific order counts. Do not reproduce or rely on screenshot numbers; discover the actual exchange context later through an authorized API connection.

The owner explicitly rejects designing a graphical trading dashboard: charts/order books/balances/positions are **internal machine-readable inputs** for automated strategy, market interpretation and risk control; do not spend time recreating TradingView charting, portfolio tiles, grid/combo bot GUI, Bitsgap account hub or broad UI. The native KuCoin app remains the external visual source for actual orders/positions. The ChatGPT conversation, through a future authenticated connector, is the desired START/PAUSE/STOP/STATUS control plane; a minimal owner-only diagnostics endpoint/CLI is necessary as a safety fallback, not a visualization product.

## Architecture / bounded exchange functionality

Source code (Codex/GitHub, not the daemon) -> always-running independently hosted **headless** DAIINAS service -> KuCoin public/private REST+WS with persistent, atomic account journal; ChatGPT owner commands -> authenticated scoped control API -> daemon; KuCoin app and external Bitsgap actions may modify exchange account concurrently. No withdrawal or transfer API methods are to be compiled into any DAIINAS command surface.

### 1. Market data ingestion

- Discover listed Spot pairs and Futures contracts *separately* with statuses, symbol identity, quote/base/settlement, contract multiplier, tick size, lot/min funds, market limits and delisting flags.
- Continuously observe candle OHLCV timeframes, tick/trades, BBO, sequence-verified L2 depth, trade aggressor pressure, volume, spread, realized volatility, index/mark and funding only when product applies. These data **feed** internal analytics; NO chart rendering required.
- Maintain per-token independent market regime (UP/DOWN/RANGE/TRANSITION/UNKNOWN), as-of timestamps, confidence based on evidence, invalidation and NO_TRADE. Do not use Futures-only data as if instruments and contract parameters were identical to Spot.
- Rate limit, timestamp and sequence correctness; replayable public source journal. Pin any symbol with open/pending order/position even if watchlist changes. Existing KuCoin public adapter and v4.1 intelligence are mandatory reuse; do not rebuild.

### 2. Private account read and orientation

- Account model discovery first: Classic Spot, Classic Futures and UTA require distinct permission/protocol/market/collateral mappings. KuCoin UTA V2 differs from Classic and some fields change version (ms/ns, types). Do not guess mode. Derive owner-account scope from authenticated response.
- At cold start obtain full, paginated, versioned and timestamped snapshot of account assets/balances (free, held, pledged, borrowed), open orders including conditional/TP/SL if supported, open positions LONG/SHORT per instrument, trade/fill history and exchange execution restrictions. Start/buffer private WS order/position/balance pushes and reconcile them against REST; validate coverage and receipt time. On reconnect repeat.
- External/manual/Bitsgap actions: detect changes without claiming reliable provenance (manual vs Bitsgap may not be exposed by API). Only DAIINAS-issued clientOid+exchange order ID mappings prove ownership. Any unknown new order/position or reconciliation discrepancy must block automated NEW entries and notify via status; never auto-cancel, rearm or replace an external order.
- Obtain balances, available capital and account scopes **directly through the future authorized API** and use those normalized responses in the internal trading engine. Account initialization must use an explicitly confirmed capital source, never the historical 8-USDT default or figures copied from demonstration screenshots; external funding must not be misreported as strategy profit.

### 3. Trading execution: internal full capability, strict permission gate

- Design order lifecycle engine for market/limit, modify where supported, cancel **owned** pending order, close/reduce **owned** position, protective stop/TP/SL conditional intents, partial fills, fees/funding and order/position reconcile on retry. This is a FUTURE controlled execution component, not authorization to place real orders during implementation.
- Independent preflight checks: exchange product/country eligibility, explicit operator permission, trade-only API scope, account mode, 25 nominal slot/active equity and isolated protected reserve, max position/aggregate risk, current free funds/held funds, open exposure including manual orders, lot/tick/multiplier/min notional, slippage/depth, net target, no stale mark, order ownership. Same-instrument LONG+SHORT hedge are TWO position legs if supported and legally eligible; never default to it.
- Order state machine includes PREPARED / PREVIEWED / APPROVED / SUBMITTED / ACK_UNCERTAIN / OPEN / PARTIAL / FILLED / CANCELLED / CLOSED / UNKNOWN. Durable `clientOid` and post-timeout query prevent duplicate live orders on reboot; new entry only under healthy fully reconciled state; never fabricate exchange fills.
- KuCoin API permissions: `General` for read-only, `Spot` for order execution where separately approved, `Futures` and `Unified` where applicable only if legal/product access is independently confirmed. **Never grant/use `Withdrawal`, `Transfer`, `Earn`, account-to-account funds movement, general `Margin` borrowing, or private wallet send operations.** No generic HTTP forwarder should be able to bypass these endpoint allowlists. Implement strict no-transfer/no-withdraw negative tests.
- Actual exchange trading is OFF by default. Implement and test only read-only + PAPER/shadow order intents first. Any real eligible Spot trade requires separate owner opt-in, runbook, trade-key restrictions/IP and independent reliability gate. UK retail crypto derivative/Futures and same-instrument Futures Hedge live execution are BLOCKED absent verified legal/product eligibility (FCA COBS 22.6).

### 4. Monitoring and operator interaction without GUI

- Provide machine-readable `STATUS` result: service health, KuCoin account mode per scope, recent public/private sync timestamps, total/free/held eligible funds, external order count, owned order IDs, positions and residual risks, realized/unrealized after-cost P&L, ladder A/R/P/deficit and slot capacity, data gaps/alerts, actual permission scopes, operator DESIRED vs OBSERVED and whether live-execution_enabled=false.
- `START` initial PAPER only, `PAUSE` new entries while monitoring and protected orders remain, `STOP`/`DISARM` persistent no new entries (NOT implicit flatten), `EMERGENCY_STOP` latch no new entries until explicit audited release. All commands are future ChatGPT authenticated connector actions; never claim they work merely because we write in a chat or create GitHub issue. KuCoin mobile app is the owner’s independent real-exposure view and manual contingency.
- No charting UI, portfolio dashboard, human indicator widgets, grid/combo bot interface or graphical strategy builder. If needed to recover after ChatGPT connector outage, ship a **small authenticated CLI / read-only diagnostics** with explicit STOP input control and audit, without recreating GUI.

## End-to-end stages and acceptance

**P0 A (now):** Existing public source + v4 Capital Ladder + per-symbol regime + headless market-state/owned-object models. Offline tests and replays, no external secrets.
**P0 B:** A secure `General` private REST/WS connector, tested in mock mode then authenticated from actual separately selected cloud runtime where user enters keys locally in host secret manager (never ChatGPT/GitHub). Prove full context startup, Spot/Futures mode labeling, balances, orders, positions, fills, manual/Bitsgap changes and crash gap handling. No real exchange write methods.
**P0 C:** Durable cloud worker/DB, single writer/leader fence, remote chat command integration and no-GUI status, offline/restart/readiness reliability. Must be tested with user PC and phone off. Codex Cloud sessions are NOT continuous production workers.
**P0 D:** Order intent/risk/execution side-effect-free tests and futures paper; trade-only API adapter fully disabled. Later eligible Spot live activation needs explicit distinct approval and legal verification. No withdrawal/transfer route at any stage.

**Security tests:** scan all codepaths to prove transfer and withdrawal requests are forbidden; nontrading key does not authorize writes; trade-preview cannot invoke exchange POST; unknown external order not owned; restart cannot duplicate, overwrite or force-close a manual position; no credentials logged; account-type confusion fails closed. All trading state and fees use exact Decimal. No simulated prices reported as real exchange quotes.

**Nonnegotiable:** This is a **HEADLESS TRADING PLATFORM**, not another trading terminal. Full exchange-context ingestion and internal control remain; visual/control-panel UI development is OUT OF SCOPE.