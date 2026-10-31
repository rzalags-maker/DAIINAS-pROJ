# DAIINAS v2 — Micro Scalping, Money Flow & Adaptive Capital

**Status 2026-10-31:** research design and new isolated modules only. The live KuCoin scanner, paper-worker integration, server deployment and profitability validation have **not** been completed. This does not change the verified v1 historical baseline: two 8-USDT simulations lost approximately 1.60 and 1.56 USDT respectively, with ~20% drawdown stops.

## Objective

Frequent *small net profitable* trades only where measurable, after commissions, spread, slippage and funding — **not** compulsory high turnover. Start at 8 USDT, allow external funding separately from earned profits, gradually scale absolute exposure when the account and proven signal quality permit. Always de-escalate on losing periods and bad liquidity. Maintain Hedge Mode architecture but do not automatically open a second opposing leg. No Bitsgap, no live orders or private keys.

## Verified versus proposed market inputs

- **KuCoin Classic Futures public WS verified** in the GitHub connectivity workflow: public token, contract metadata for 5 symbols, tickerV2 subscription acknowledgment and real ticker event. 24/7 continuity, execution-feed capture and full orderbook replay are **not yet verified**.
- **P0 live trades:** `/contractMarket/execution:{symbol}` for aggressor buy/sell and trade sizes; convert `contracts * multiplier * price` to notional; do not confuse taker side with opened LONG/SHORT.
- **P0 bid/ask and spread:** `/contractMarket/tickerV2:{symbol}`; best-quote imbalance does not equal full orderbook liquidity. For full depth use a documented currently-supported incremental depth channel plus REST snapshot, verify sequence synchronization, reset on gaps and persist provenance.
- **P1 Open Interest:** KuCoin public `/api/ua/v2/market/open-interest` (or verified compatible route). Verify from execution host and store timestamped snapshots. Intraday historical retention is limited; acquire forward history ourselves. Rising OI is *not* net new longs.
- **P1 Funding:** Classic public `/api/v1/funding-rate/{symbol}/current`; avoid assuming fixed eight-hour settlement timing or that predicted rates are final. Funding is cost/context, not entry signal.
- **P2 liquidations:** no validated complete public market-wide stream; exclude it from required entry gating until verified. Third-party CoinGlass optional only with measured additional benefit and acceptable cost.
- TradingView is optional for charts/webhook alerts, **not** the core low-latency trade/order-book feed.

**Documentation:** [KuCoin Classic trade stream](https://www.kucoin.com/en-au/docs-new/3470084w0), [KuCoin tickerV2](https://www.kucoin.com/docs-new/3470080w0), [KuCoin orderbook snapshot](https://www.kucoin.com/docs-new/rest/futures-trading/market-data/get-full-orderbook), [KuCoin public WS token](https://www.kucoin.com/docs-new/websocket-api/base-info/get-public-token-futures), [KuCoin OI](https://www.kucoin.com/docs-new/v2/rest/ua/get-futures-open-interest), [KuCoin current funding](https://www.kucoin.com/docs-new/rest/futures-trading/funding-fees/get-current-funding-rate), [KuCoin contract multiplier/lot](https://www.kucoin.com/en-au/docs-new/rest/futures-trading/market-data/get-symbol).

## Implemented but not yet wired to paper service

`daiinas/moneyflow.py` computes research-only CVD notional, CVD ratio, actual spread, *top-of-book* imbalance and optional relative OI change from valid timestamps and contract multipliers. It blocks duplicate executions, future observations, stale quotes/OI and inconsistent units. Adapter must additionally prove no gaps/disconnects; the feature module **cannot prove stream completeness** on its own.

`daiinas/adaptive.py` implements experimental capital risk ceilings and deposit-adjusted drawdown. It is **opt-in, in-memory, not linked to the existing v1 worker and not a production risk guard**. Before any paper-worker integration, checkpoint its peak, halt and external flows transactionally in SQLite, retain recovery semantics and add restart tests. An external deposit is **not** a trading profit.

## Illustrative capital ceilings (NOT optimized)

| Equity | Maximum proposed planned loss/trade | Mode |
|---|---:|---|
| 8–<20 USDT | 0.25% of equity | MICRO if contract executable |
| 20–<50 USDT | 0.35% | MICRO |
| 50–<100 USDT | 0.50% | MICRO; EXTENDED only for validated trend |
| >=100 USDT | 0.75% | MICRO or validated EXTENDED |

At deposit-adjusted equity drawdown >=3%, halve risk ceiling. At >=6%, **latched halt**, requiring explicit review. These are hypotheses, not universally safe settings. Data stale, no verified net edge, unacceptable execution costs, market regime unfavorable or too-large minimum order => **no new order**. A higher balance does not mandate larger percentage risk or higher leverage. A hedged second leg must consume its own costs/margin and be preferable to closing the first leg based on modeled total account risk.

## Micro-execution economics

A two-way taker trade with illustrative entry/exit fees of **0.06% each**, full spread **2 bps** and adverse slippage **2 bps each fill** requires approximately **18 bps favorable mid-to-mid move just to break even**. At **20 USDT notional**, this costs about **0.036 USDT**. Earning 0.01 USDT net then requires ~0.046 USDT gross (=23 bps); 0.05 net requires ~0.086 USDT gross (=43 bps). These are *not verified current user fees*. Limit/maker fills need partial-fill, nonfill, latency and adverse-selection handling — never assume each passive order gets filled.

KuCoin lot sizes are contract counts; multiplier can make the smallest trade too large for 8 USDT and a 0.02-USDT planned loss budget. If so report `INSUFFICIENT_EXECUTABLE_CAPITAL` and **do not round up to force a trade**. Keep absolute USDT net results separate from percentage return, collateral and notional.

## Market modes and hedge comparison

- `MICRO`: acceptable execution costs, validated local buying/selling pressure, liquid spread and sufficiently large expected favorable movement. No forced number of trades or fixed position duration.
- `EXTENDED`: independently validated trend/momentum regime, with better opportunity to hold longer; only with sufficient risk budget and signal evidence.
- `STANDBY`: uncertain edge, cost, market data or adverse regime. Never trade only because an account has grown.
- `HEDGE`: optional protection *only* when separate modeling shows opening a counter-position beats closing outright after both legs' fees, funding, margin and tail risk. Opposite same-size positions do not erase the initial loss.

## Acceptance gates in order

1. Implement KuCoin Classic public `execution` + `tickerV2` streams with reconnects, sequence-gap proof, timestamps, contract conversion and durable raw-event recording. Add depth synchronization later without using deprecated channels.
2. Verify host access to public OI and funding, document rate limits and lag. Do not silently substitute synthetic values for unavailable feed.
3. Run real WebSocket capture -> independent deterministic replay -> paper signal ledger, with health, stop/resume, recovered state and market-data quality flags in SQLite. No private credentials, no real orders.
4. Enforce executable contract minima, true cost model, stop-risk sizing, max exposure, deposit-adjusted peak, drawdown latch and strategy health before paper entries. Test graceful restarts.
5. Compare multiple independently separated time windows, forward paper samples, high/low liquidity, maker nonfill/taker adverse execution and rejected signals. Reject nonpositive net expectancy. Report trade count, uncertainty, net P&L, drawdown and cost breakdown. Preserve the previous loss-making v1 baseline.
6. Deploy an independent persistent host with verified network access and monitoring; GitHub Actions and Codex tasks are **not** 24/7 hosting. Keep live execution disabled.

**No DOLF indicator combination has been proven profitable in our data yet.** Order-flow features are an improvement in observability, not guaranteed predictive signals.
