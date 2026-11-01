# DAIINAS v4.7 — Adaptive x1–x5 leverage, whole-market LONG/SHORT research, and continuous position conveyor

**Owner decision:** 2026-11-01. **Priority:** P0 new strategy specification. Implement within the SAME v4.6 account-driven Model A / single-writer PAPER engine, not a second trader. Replaces older v4.5 **x2 maximum pilot** with a new **x5 maximum PAPER research/testing ceiling**. This does NOT enable real Futures orders, override licensing/product-eligibility gates, or constitute evidence that x5 is profitable or safe.

**Original owner objective:** Human can manually supervise only a few positions; DAIINAS should independently scan the full supported Futures market, identify LONG and SHORT opportunities, choose candidate and leverage, enter with protective stop and profit target, monitor up to TEN simultaneous funded positions, close after a verified net-profit objective or stop, reconcile, then seek a new candidate, continuously. Owner's historical manual maximum has been x5; select leverage via objective cost/risk/forecast assessment, **not permanently x5**. The system must autonomously decide NO_TRADE when risk or opportunity fails.

## Owner confirmation — event-driven ten-slot replenishment from KuCoin order state

**2026-11-01 owner emphasis:** The purpose of ten Model A-funded positions is **an event-driven, reusable opportunity conveyor**. It is NOT ten unique one-time trades, and no manual operator intervention is expected to notice a remotely confirmed TP/SL and replace a position during an active session. KuCoin Classic Futures exposes [private trade-order WebSocket updates](https://www.kucoin.com/docs-new/3470090w0) plus [GET order by id](https://www.kucoin.com/docs-new/rest/futures-trading/orders/get-order-by-orderld), [open-order history](https://www.kucoin.com/docs-new/rest/futures-trading/orders/get-order-list), and [untriggered stop orders](https://www.kucoin.com/docs-new/rest/futures-trading/orders/get-stop-order-list). Implement event-driven provisional updates, validated against authoritative position/fill/order snapshots before **actually** releasing capacity.

**Atomic vacancy-release transaction (paper/mock first):**
1. Observe private WS order/position change or bounded REST poll; map its `orderId`/`clientOid` to the existing **owned** position/campaign, deduplicate across WS and REST; a triggered stop order or `match` alone is **not** a complete position close.
2. Confirm remaining position quantity = 0 (or appropriately reduce partially filled leg capacity only under tested accounting), all fees/funding/executed exit quantities and sibling TP/SL state. Cancel or reconcile stale alternative exits; avoid reverse accidental exposure. If unknown, block replacement and expose `PENDING_RECONCILIATION`.
3. Persist exactly-once closed-campaign REALIZED NET outcome; update SAME account-driven Model A ACTIVE/RESERVE, realized-win permission where eligible, risk/aggregate exposure, free margin and capacity. Simulated PAPER activity must never increase *actual* exchange-verified equity.
4. Recompute `min(model_a_funded_eligibility, genuinely free margin, remaining margin/risk/correlation/min-lot/market gates) - open/pending/reserved legs`. If positive and session still ARMED and worker confirmed alive, run fresh whole-universe candidate ranking for new independent LONG/SHORT/NO_TRADE. Admit best **verified** candidate only; never automatically re-enter stopped symbol, force ten occupied, or assume a vacancy will certainly arise within five hours.
5. Repeat for every verified close event during session, with priority monitoring of all remaining open positions. After session STOP/expiry, exchange-native ACKed TP/SL may execute while worker is offline, but **no new entry search** can occur without a live worker. On next START reconcile all remote closes and late statuses **before** releasing slots or creating any new intent.

**Five-hour test cases:** ten occupied positions -> one remote TP fully closes -> exactly one slot released and at most one new qualifying intent; one stop closes with net loss -> Model A funded ceiling may shrink and no replacement; duplicate WS/REST event -> no double slot/net P&L; partial exit -> no phantom vacancy; orphan stop -> NO_TRADE; controller offline -> remote TP/SL may close but zero new intents until restart; resumed session detects missing position and correctly books result. Add public WS event only as a monitoring mechanism; write transport remains inert until separate authorized phase.

---

## Five-hour owner-controlled session acceptance and exchange-native protection

**New owner clarifying decision, 2026-11-01:** Test DAIINAS with `START(duration=5h)`, uninterrupted PAPER autonomous market discovery/entry/exits while a verified worker is running, and `STOP`/expiry by design. A permanent 24h continuously trading process is NOT required. Codex may orchestrate bounded tests while user's desktop is off, but its Cloud task VM and credit allowance **do not guarantee five hours of persistent runtime or reliable remote STOP**. Validate actual liveness; if longer sessions are required, a minimal on-demand worker is permissible without committing to always-on trading.

**KuCoin-native exits separate risk handling from next candidate selection:** Classic Futures has [combined Take Profit and Stop Loss entry endpoint](https://www.kucoin.com/docs-new/rest/futures-trading/orders/add-take-profit-and-stop-loss-order/) (`POST /api/v1/st-orders`) and supports Market/Limit. A remotely **accepted and verified** protective order may execute while Codex is off; no manual exit command should be required in normal conditions. But do not claim risk-free protection or a guaranteed stop fill: verify trigger reference, stop-market/limit execution, fill/position amount, reduce-only and whether OCO sibling is canceled. If position entry is a pending Limit and not filled, conditional exits may not provide the assumed protection. Confirm full or partial fill linkage and avoid orphan child/TP/SL orders; never open an accidental reverse position.

**Correct five-hour cycle:** `START` -> verify actual worker ACK / account or mock snapshot -> existing Model A ledger -> per-token LONG/SHORT + x1..x5 fully costed risk -> Market/Limit entry -> confirm fill and venue-equivalent TP/SL protection -> monitor -> when actual TP/SL exit confirmed, book realized NET after fees/funding exactly once -> refill only if a fresh market signal and budget permit. `STOP` or fifth-hour expiration blocks NEW entries and safely resolves/cancels unfilled entries; existing filled positions with valid remotely acknowledged TP/SL may remain protected under explicit owner-approved stop mode; response must explicitly show remaining risk as `STOPPED_WITH_EXPOSURE` or account flat as `STOPPED_FLAT`. Once worker stopped, there is NO continuous new-market scanning, no further owner STOP effect on already accepted exchange orders and no guaranteed trailing/sliding risk management by DAIINAS.

**Restart:** read complete KuCoin positions/open orders/conditional TP-SL/fills and account updated equity, verify if any position closed while worker offline, cancel/reconcile orphan exits as appropriate, persist into same ledger, re-evaluate Model A and resume new opportunities without duplicate WIN/fees. Replaying a stop or profit order must never create two gains or double margin release.

**Required tests:** controlled virtual-clock five-hour PAPER run (not a claim of 5h real Cloud uptime); concurrently filled 2–10 legs, a confirmed TP exit -> independent replacement, a confirmed SL exit -> reassessed new entry or NO_TRADE; expiry while pending LIMIT, expiry while protected open position, no replacement after expiry, remote mock exchange closes position while worker is offline, next session ledger/positions exact reconciliation, OCO/non-OCO mode simulation, partial fills/uncertain ACK, unrecoverable stop-reporting. All code kept with the same v4.6 engine; mock/inert exchange transport, live execution disabled.

---

## OWNER 2026-11-01 SESSION-BASED EXECUTION INTERFACE (SUPERSEDES 24/7 TRADING ASSUMPTION)

**Operator flow:** START once from the Codex DAIINAS project (web or phone); while a **verified running** DAIINAS session worker exists, it independently reconciles, scouts the market, chooses leverage/side and risk, and repeats entry->protected TP/SL->confirmed exit->Model A updates. PAUSE/STOP is explicit, durably acknowledged by the actual worker (not merely a chat response); on STOP, no new orders, reconcile existing open/pending exposure, and report STOPPED_FLAT or STOPPED_WITH_EXPOSURE. The next START must fetch all actual KuCoin state and continue the same journal and current capital without fictional new initial funding. No owner requirement to trade continuously 24/7.

**Codex limitation:** Codex Cloud can run coding tasks with user PC off, but is not a guaranteed persistent trading daemon or runtime that automatically pauses when Codex credits run out. Saved VM state is not running supervision, and mobile chat alone does not prove immediate exchange stop. A short, bounded PAPER experiment may run as a Codex Cloud task if it demonstrably meets that test's lifetime; **do not send real orders in such a task**. For future live sessions, build an independently managed on-demand runtime with durable state, verified authenticated phone control/ACK, tested liveness and safe recovery if Codex Cloud cannot meet those criteria; this need not trade or accrue compute charges 24/7.

**Engineering scope unification:** The owner treats adaptive x1–x5 selection and MARKET/LIMIT entry with native exchange-confirmed TP/SL, reduce-only exit, partial fills, fees, idempotent clientOid, unknown ACK, risk/deadman gate, and confirmed NET close as **one module / lifecycle and one set of acceptance tests**. Include fail-closed inert order-gateway adapter and contract tests now alongside Paper simulator; read-only exchange connector precedes authorization of any real transport. Neither an inactive Codex task nor a time/credit limit counts as independent protective supervision. Exchange-native stops may continue after a session stops only if independently ACKed, and execution remains subject to market conditions; report residual exposure honestly.

**Acceptance:** Session-bound PAPER START/PAUSE/STOP/resume tests; user phone/computer-off task test if supported; no duplicate new entries across session boundary; Model A balance and ledger preserved; per-leg x1–x5 + TP/SL tests; all simulated orders inert; clear NOT_CONNECTED vs RECONCILED_MOCK vs authenticated read-only labels. No mandatory always-on server. Keep long-duration resilience as a later reliability gate, without promising cloud-task runtime duration.

---

## 1. Definitions that must not drift

- **Capital source:** ACTUAL verified and continually reconciled usable Futures account, not fixed 8/60/100; immutable `INITIAL_FUNDING` is audit history, not an entry budget. Until authenticated connector exists, explicit/mock Futures PAPER accounts only. Keep `MODEL A`: at 200 USDT R50/A150/6 nominal slots; at 300 R50/A250/10; +25 realized net stages to ten then alternating +50 Reserve/Active.
- **Direction:** Per-token independently select `LONG`, `SHORT`, `NO_TRADE`; optional same-instrument `HEDGE` (simultaneous LONG+SHORT) is a distinct TWO-leg tactic permitted in PAPER only if the exchange position mode/contract and genuinely positive after-cost hedge economics have been validated. Being able to short an asset does **not** require holding a long simultaneously. Opposing sides across different tokens are not inherently a hedge; correlated gross losses and net beta must be modeled.
- **Leverage choices:** initial PAPER experiment `{1,2,3,4,5}` with hard maximum **5x**, and lower per-contract/account limits if applicable. Do not infer a requirement to use all five levels or raise leverage to satisfy min order. **ISOLATED** remains the trial mode; verify `marginMode`, position mode, max leverage, any auto-add margin feature, actual available collateral and contract-specific risk limits, with NO_TRADE if unsupported.
- **Take-profit target:** +2% **REALIZED NET campaign return on ALLOCATED campaign capital** (after entry and exit fees, spread, market impact, carry/funding, slippage). Not 2% underlying-token price movement; not a guaranteed return. Price trigger/limit derived from actual notional, contract multiplier and expected worst-case costs; after fill, reconcile actual net, partials and fees before marking success. A hypothetical mark crossing 2% is not a realized result.
- **Stop-loss:** retain previously selected **0.5% adverse entry-PRICE** as explicit **PAPER trial hypothesis** pending owner confirmation of final units, but retain separately the financial `campaign_loss_fraction=0.005` = **0.5% of campaign allocation** and independent per-position `<=0.25% of active equity`, total planned `<=1% active`. Respect the strictest monetary cap; if price stop cannot fit at x5/contract minimum, reduce position notional, choose less leverage or **NO_TRADE**. Exchange-native stops are not guaranteed to fill at trigger on volatility gaps.
- **Position slot:** Model A funded 10 slots is a concurrency ceiling, NOT a target for ten orders. Reserve is never allocated for fresh trade margin. Pending entries and partially filled legs count. Opposite legs in a supported hedge count as two gross slots and consume total/gross risk budget.

## 2. Dynamic leverage selector — compare all feasible choices before entry

For each eligible `(contract, direction, entry opportunity)`, build a **feasibility vector per candidate leverage L = 1..5**:

1. Fresh symbol contract mode, funding schedule, min lot, quantity increment, multiplier, tick size and actual fee tier/market-maker eligibility; margin availability in the correct Futures account.
2. Independently estimated favorable market movement and holding horizon from **observed data**, not from leverage. Estimate plausible net returns conditional on current regime and liquidity. Clearly mark unknown/un-calibrated forecasts; do not invent win probabilities.
3. Compute **proposed notional and margin** from current campaign allocation, existing position commitments, real spendable free margin and contract lot minimum. Leverage mostly changes margin efficiency and ROI denominator; it does NOT generate a more predictive signal or turn bad execution costs into a good trade.
4. Compute net profit at candidate TP execution, adverse P&L at stop with realistic price gap/slippage and estimated entry/exit fees, spread, funding. Derive actual price move needed for **+2% NET on the campaign allocation**, and whether likely reachable before stop within justified horizon.
5. Derive fully costed stop loss in USDT and compare against all simultaneous loss limits; enforce `risk_usdt <= min(0.005 * campaign_allocated, 0.0025 * effective_active_equity, remaining_aggregate_risk, stricter product/account gates)` plus correlation and existing exposure. This is a planned-loss budget, not a guarantee against gap/liquidation.
6. Compare feasible choices on expected risk-adjusted net outcome, likelihood of actual TP fill, expected holding time, probability of stop (only when calibrated), tail loss, liquidity and portfolio correlation. Reject all choices if none passes. Prefer smallest leverage / notional that delivers sufficient achievable expected net economics; **never choose x5 just to accelerate 2% mark-ROI or maximize volume**.
7. Log every decision with alternative L scenarios and reject reasons in replayable source/policy records, e.g. `x5 rejected: stop loss exceeds risk budget`, `x2 accepted: sufficient net reward/risk`, or `NO_TRADE: target cannot be reached after costs`. Do not optimize on in-sample backtests only.

**Illustrative simplified full-allocation sanity math** (linear USDT contract, 25 USDT margin allocation actually posted in full, flat prices, both sides taker at assumed 0.06% of notional, no separate spread/impact/funding; NOT a live quote):
`notional = 25 * L`; desired +2% NET on 25 = 0.50 USDT; round-trip fees = `0.0012 * notional`. Approx favorable PRICE movement for +0.50 net = `0.02/L + 0.0012`: 1x **2.12%**, 2x **1.12%**, 3x **0.7867%**, 4x **0.62%**, 5x **0.52%**. But a 0.5% adverse price stop at 5x full posted margin yields -2.5% margin BEFORE costs and about -3.1% including assumed round-trip taker costs; this VIOLATES the separate 0.5% campaign-money loss cap. Consequently full-size x5 + 0.5% price-stop is inadmissible under existing constraints. It can only be re-sized to a sufficiently smaller notional/posted margin if all limits and min lot permit, whereupon the target market movement must be recalculated on the actual smaller notional (and may become unfeasible). **Do not silently change stop denominator or loosen budget to make a x5 candidate pass.**

## 3. Whole-market scanner: broad discovery, selective deep analysis (not "top gainers only")

**Universe = all currently available, supported, tradable contracts on the detected KuCoin account mode**, not a fixed manually selected token list. KuCoin Classic Futures public `GET /api/v1/contracts/active` supplies tradable catalog and symbol constraints; `GET /api/v1/allTickers` supports broad ticker discovery. For UTA, detect mode and use current matching API interface; do not mix protocols.

**Tier 0 — universe health:** dynamically refresh tradability, suspension/delist, settlement currency, contract multiplier, min lot, tick, supported leverage/margin mode, API product/account permission, volume, risk limits. Never count symbols delisted or disallowed.

**Tier 1 — economical whole-universe pulse:** collect summary prices, recent movement/volume, spread/freshness, trend/volatility context for ALL supported instruments on a bounded rolling schedule. Compute independent per-symbol market state (UP/DOWN/RANGE/TRANSITION/DISLOCATED/UNKNOWN), rank both upward and downward opportunities; top gainers, top losers and volume are **features**, not mandatory source categories or trading signals. A sudden gainer may be late/overextended; a loser may be downtrending rather than a good reversal LONG.

**Tier 2 — shortlisted multi-timeframe intelligence:** rank candidates and inspect OHLCV, realized volatility, momentum/regime transition, relevant trend horizons, funding/carry, bid-ask spread, tick/trade tape, market order flow (where supported), and liquidity/depth. Use 1m/5m/15m/1h as configurable research horizons, not magic thresholds. Do not interpret a rendered chart image; analyze timestamped market data and data provenance.

**Tier 3 — executable preflight:** only for bounded highest-quality candidates verify sequence-consistent live L2 depth, book impact at actual expected position/exit size, spread/slippage, fees, contract min lot, leverage-specific risk, actual exchange available margin, correlation and existing exposure/position limits. Market-wide high-depth streaming is neither necessary nor feasible under API/rate-limit budgets; prioritize existing open/pending positions as **pinned** subscriptions throughout.

**Portfolio selection:** prefer distinct, net-profitable opportunities and impose cluster/concentration controls. Ten long altcoin positions correlated to BTC are NOT ten independent bets. Support LONG in some symbols and SHORT in others when justified, but recognize both can lose concurrently. For true same-token hedge, require independent proof of edge after two-leg fees and funding; default to simpler directional positions until evidence.

## 4. Conveyor: protection first, 10 slots maximum, no forced turnover

```text
while owner_state == ARMED_PAPER and worker_healthy:
    account = reconcile_verified_futures_scope_or_mock_paper()
    ledger = reconcile_realized_fills_costs_funding_campaigns_and_Model_A(account)
    monitor_all_open_and_pending_positions_FIRST()
    if unknown orders, missing protection, stale feeds or emergency latches:
        block_new_entries_and_preserve_existing_risk_monitoring()
    else:
        free_slots = max(0, minimum_of_earned_or_Model_A_funded_slots,
                        cash_free_margin_slots, risk_available_slots) - open_pending_legs
        if free_slots > 0:
            universe = scan_supported_all_contracts_with_bounded_budget()
            best = shortlist_and_validate_costs_regimes_depth_and_correlation(universe)
            for candidate in best:
                evaluate_direction_LONG_SHORT_or_NO_TRADE()
                compare_leverage_1_to_5_and_safe_position_sizes()
                if ALL safeguards permit:
                    prepare_one_PAPER_entry_intent()
                    reconcile modeled fill, stop and TP protection acknowledgment
                else:
                    emit_NO_TRADE_with_reason()
    on_fully_settled_closed_campaign:
        settle_NET_once_and_update_the_same_Model_A_ladder()
        cooldown_that_symbol_and_rescan_fresh_opportunities()
    on_restart:
        restore_existing_identity_ledger_and_reconcile_before_any_new_entries()
```

- **No fixed 10-order burst.** Existing positions and their risk monitoring have priority over searching for new symbols. Entries are independently ranked, time-gated and capped by available allocation and risk; maintain budget so that 10 simultaneous positions do not create unaccounted leverage and funding costs.
- **Protective order lifecycle:** entry request is not a fill; TP/SL requested is not exchange-ACKed protection. Model and future connector must track fill quantity, stop coverage for partial fills, reduce-only, trigger reference (mark/last/index where supported), TP limit risk of nonfill, stop-market slippage, canceled/expired/partial exits, and uncertain ACK. On missing protection freeze all NEW entries and invoke pretested bounded emergency response; never report a guaranteed stop.
- **2% exit:** do not merely place a simplistic limit at +2% raw price or count TP touched as net realized profit. Compute actual executable target allowing both-side costs. On confirmed close book realized NET; update win-gated early-stage permissions when relevant, ACTIVE/RESERVE and funded slot counts; search fresh candidates. If a position stops out, don't revenge trade into same unconfirmed trend: invalidate/reassess the original signal, cooldown and rescan the **whole** universe including alternative SHORT where evidence warrants.
- **Hard failure:** NO_TRADE/PAUSE_NEW_ENTRIES if read-only account reconciliation absent, stale/missing L2, spread extreme, unknown external orders, insufficient minimum size/risk, funding unpredictably dominates target, latency exceeds bound, or host restart not reconciled.
- **Concurrency and reproducibility:** single writer, durable clientOid/intent IDs, exactly-once net settlement, independent per-symbol state, no duplicate orders or fake fills, deterministic Decimal tests, restart recoverability, sampled 24-hour PAPER host evidence.

## 5. Test/acceptance requirements (CODING, not documentation completion)

1. **Leverage scenario matrix** L=1..5 for LONG and SHORT, various price/fee/funding/book/stop conditions, including x5 fail under full 25 allocation plus 0.5% price SL and 0.5% campaign max money loss. Verify correctly resized x5 and lower L if feasible; invalid min lot => NO_TRADE.
2. **Real target calculation:** +2% REALIZED NET on allocated capital, not mark price, account portfolio ROI or raw 2% token price. Partial target fills, fees and slippage may produce <2% actual; do not mark a WIN without strictly positive reconciled net. Validate TP limit nonfill and stop-after-TP pending transitions.
3. **Full-universe selection:** include top winner, top loser, most liquid, high-volume sideways and low-liquidity spike; demonstrate that top ranks are evidence-based executable opportunities, not 'gainers first' or a hardcoded symbol list. Ensure universe completeness/freshness, adaptive deep subscriptions and rate-limit safety.
4. **10 correlated vs independent candidates:** aggregate planned risk never >1% ACTIVE; each leg <=0.25% ACTIVE; campaign loss <=0.5% allocated; reservations/margins included; same-token HEDGE counts two slots and two sides of fees.
5. **Conveyor state:** 1–10 independently managed PAPER legs, native-protection simulated ACK, TP after costs, stop trigger, missing confirmation, exact closed-PnL once, failed new entry NO_TRADE, replacement fresh market scan, time and inventory bound, no forced entry.
6. **Capital interplay:** actual mock Futures CYCLE 0 from 60/200/300/450; current account dynamic updates on wins/losses, Model A at 200 R50/A150 six nominal and 300 R50/A250 ten; loss reduces funded slots; early (<100) win candidate increments; restart/kill without repeated fills/ports. No app UI or duplicate bot.
7. **No unsupported claims:** offline/PAPER fills, simulated stops, hypothetical token forecasts and CI successes must be labelled; no live orders, private connector or 24h host claimed until independently proven. Publish code diff and actual test results with separate P&L evidence and failures.

**Precedence:** This v4.7 owner update supersedes ONLY the older v4.5 x2 ceiling for PAPER testing; preserves all previously adopted Model A allocation, financial loss caps, account source, stop-unit ambiguity, and no-live-execution constraints. If dynamic x5 cannot pass these limits, the valid result is x1/x2/smaller size/NO_TRADE, not risk-rule changes.
