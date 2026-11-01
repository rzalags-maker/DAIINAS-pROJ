# DAIINAS v4.5 — Owner-approved BASIC Futures trading policy (design / PAPER acceptance)

**Decision source:** owner conversation 2026-11-01. **Priority:** P0; newer than v4.1 generic hedge experimentation and legacy 8-USDT exercises. **Status:** canonical *design and test specification*, NOT proof of a connected account, deployed worker, or live order authorization. LIVE ORDERS DISABLED.

This is a **headless, self-repeating, exchange-connected trading process**. Bitsgap is a functional analogy, not a dependency or UI requirement. Codex develops and supervises the system; a persistent runtime executes deterministic monitoring and order-lifecycle controls without requiring uninterrupted model sessions. Do not silently add a dashboard or change the ongoing v4 implementation branch. Link this policy from issues #10 (funded balance), #11 (market/strategy) and #12 (exchange control). All acceptance points are code-and-test requirements before any prospective activation.

## 1. Owner's economic objective and default trial configuration

| Dimension | Selected *PAPER pilot* | Unit and meaning |
| --- | --- | --- |
| Market scope | Entire actually supported/tradable KuCoin contract catalog | Discover instruments dynamically; filter status, contract lot/step/min, liquidity, depth, spread, volatility, mark/funding, API coverage and observed fees; do not force any token including BTC |
| Direction | LONG or SHORT, conditional | Token-specific regime; no forced hedge or simultaneous opposite-side legs |
| Margin | **ISOLATED** for pilot | Do NOT adopt all-account Cross Margin/no-stop strategy; verify exchange mode and prevent silent auto-add margin where configurable |
| Leverage | **1x–2x**, with **2x maximum pilot** | Set and verify before order preview; do not increase leverage to rescue weak opportunity or minimum lot |
| Take-profit goal | **+2% realized NET** | Of *campaign allocated margin capital* under the v4 Capital Ladder accounting; net of actual entry/exit fees, bid/ask, slippage, funding/carry and any other execution costs. This is a candidate target, not a guaranteed return or necessarily a 2% price move |
| Initial Stop Loss trial | **0.5% adverse ENTRY-PRICE movement** | Long: trigger around entry_price * (1 - 0.005); short: entry_price * (1 + 0.005), adjusted for validated tick/mark/trigger semantics. This interpretation is an explicit **PAPER design assumption**, since previous dialogue also discussed 0.5% *margin/allocated-capital loss*. Before live parameter approval, owner must expressly ratify denominator; never silently swap units |
| Campaign loss cap | Existing separate `campaign_loss_fraction=.005` | This is **0.5% of allocated capital**, NOT 0.5% price distance, and can conflict with a 2x 0.5%-price stop. The tighter financial policy must control sizing or forbid a trade; never assume both thresholds simultaneously hold for a fully funded slot |
| Portfolio risk | Existing <=0.25% *active* equity planned loss per leg, <=1% aggregate | Include estimated fees, slippage, carry, stop-market gap allowance and known exposure. At 3% active drawdown reduce risk; at >=6% latch HALT; no loosening without a separate accepted policy |
| After exit | Reconcile, account, rescan, re-enter only if new opportunity | New trade must independently satisfy *all* preflight gates; NO_TRADE is a valid outcome |

**Do not turn a target into a performance claim.** Existing public feed acceptance recorded zero qualifying trades in a short window; no demonstrated strategy edge or positive expected returns.

## 2. Real Futures capital — explicit source, no 8-USDT production default

- Funding wallet funds remain outside tradable Futures equity. Only funds **settled and verified in the actual eligible Futures trading scope** count toward the funded-v4 allocator. MetaMask, pending deposits, unarrived transfers and other account balances do not count. For Unified Trading Accounts, normalize collateral/account scope and avoid summing the same pool twice.
- A **single** typed `INITIAL_FUNDING` event must bind actual account and mode, source, settlement currency, opening equity/cash basis, reconciled snapshot ID/time, source digest and policy version; restart must not duplicate or silently re-seed. If private KuCoin read-only connection absent, ONLY a named PAPER scenario is valid, never a claimed live balance.
- Active, Reserve, Pending and Deficit live in the **Futures-scoped strategy ledger**; no automatic wallet transfer to Funding/Spot. Reserve is unavailable to strategy new entries, not guaranteed physically isolated exchange collateral. Cross/shared collateral can expose reserve; isolated margin still has contingent liquidation and exchange margin risks. Use actual free vs held/position margin, not total equity as spendable cash.
- Maintain selected v4 Capital Ladder Model A unless the owner explicitly changes it: under 100 funded => at most one *candidate*; at exactly 100 => R50/A50 two 25 allocation slots; at profit rungs expand to 10; thereafter alternate reserve/active. **These are allocation thresholds, NOT starting-capital limits or promised minimum tradable sizes.** The historical 8-USDT database is only an explicitly isolated regression fixture.

## 3. Numerical dimensional sanity check (paper illustrative; do not hardcode exchange fees)

With 25 USDT **allocated margin**, 2x leverage => 50 USDT notional. **Illustrative** 0.06% taker fee on each side of 50 notional: round trip = 0.06 USDT, before spread/slippage/funding.

- A 0.5% **adverse PRICE** change loses 0.25 USDT before fees, about 0.31 USDT net loss = **1.24% of allocated 25 margin** under this simplified illustrative assumption.
- A 0.5% **margin net loss** cap means only 0.125 USDT permitted loss; fees of 0.06 leave 0.065 USDT for price movement => around **0.13% adverse price move**. It is a fundamentally different stop.
- +2% NET of 25 means 0.50 USDT net gain: with 0.06 assumed fees, a favorable price move of about **1.12%** on a 50-USDT position would be needed. Funding/spread/slippage widen this threshold.
- Thus a full 25-margin, 2x slot with 0.5% price stop **fails** an independent 0.5% allocated-capital loss cap under this illustration. Resolve by reducing *exposure* (not forced to use full margin), changing the intended stop unit with owner approval, or **NO_TRADE**; do not hide the contradiction.

All computations must use exact Decimal, instrument contract multiplier/min lot and *actual* fee schedule and stop trigger type. Test both LONG/SHORT, linear vs any supported inverse contract, and tick/quantity rounding. A stop is not guaranteed fill at its trigger; gaps and slippage can exceed planned loss.

## 4. Market-wide entry selection — why volatility is not enough

1. Obtain public contract catalog and low-cost market summary for **all** actually supported instruments; schedule bounded incremental refresh and respect rate limits. Do not pull unlimited high-depth streams for every token; shortlist dynamically, pin existing exposures.
2. Rank candidates by fresh executable bid/ask depth, size feasible at lot/tick and account margin, net target reachability *within a justified time horizon*, spread/slippage, fees/funding, regime consistency and invalidation, available risk budget and correlation. BTC can qualify when executable economics justify it; altcoins do not automatically qualify because they are more volatile.
3. Check all account-scoped active/reserve/locked margin, owned and external orders, confirmed isolated mode/leverage, direction, clientOid uniqueness and protective-order lifecycle before proposing entry.
4. Derive size from tighter of allocation budget, affordable actual margin, stop-distance **fully costed risk**, instrument minimums and correlated aggregate risk. If min order would violate any risk rule => NO_TRADE; do not raise leverage or tap reserve.
5. Account for exchange native protective orders: entry requested != filled; stop requested != stop active. Track submitted/partial/full, protection acknowledgement, confirmed trigger configuration, and stop/close outcome. On protection failure freeze new entries and handle existing exposure under a pretested bounded emergency procedure. No fake exchange fills.
6. Once closed, reconcile *actual* order fills + fees + carry + funding, update realized campaign net and allocation ladder exactly once, unpin settled exposure, cooldown and return to scanner. Stop can be hit repeatedly; don't force immediate revenge re-entry.

## 5. Acceptance and integration gates

- [ ] NEW v4 has no implicit 8-USDT seed anywhere; explicit funding and provenance is enforced once, legacy 8 scenario isolated.
- [ ] A complete Futures cash/equity/available/locked account map; no Funding/MetaMask counted as tradable Futures; no duplicate UTA collateral.
- [ ] Isolated mode and 1–2x verified as explicit PAPER trial execution constraints; Cross/no-stop strategy excluded.
- [ ] +2% net on campaign allocated capital, *different* 0.5% entry-price stop and 0.5% campaign-allocation loss are separately named, calculated and testable; fail-closed policy conflict resolution.
- [ ] Exact 25-margin/50-notional/0.5%-price examples above; test long, short, low liquidity, actual fees, leverage-dependent loss, min-lot no-trade and stale-data risk.
- [ ] Full supported market catalog, opportunistic rank/filter, NO_TRADE, cooldown, repeated cycle, 2/3/5/10 positions subject to existing v4 slot and risk limits.
- [ ] Durable clientOid, partial fills, independent stop confirmation, unexpected exchange-side/manual changes, disconnect/restart reconciled without duplicate orders.
- [ ] Long-duration PAPER run, actual open/close samples and nonzero economically meaningful held-out evaluation; green offline tests alone do not prove profit.
- [ ] No live KuCoin orders, financial transfers, keys in source/GitHub, or claim that the independent hosting/API is already connected.

**Implementation coordination:** Codex changes existing feature/v4-ladder-integration and v4.2 boundaries after reviewing this policy; this file deliberately does NOT modify a running engine or authorize any real exchange action.