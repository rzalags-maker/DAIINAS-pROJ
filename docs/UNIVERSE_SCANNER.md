# DAIINAS v3 — Dynamic Universe & Opportunity Selection

Status: Standalone public-market read-only filter implemented in daiinas/universe.py. Not integrated into live KuCoin paper worker. Not a trade signal and not deployed 24/7.

## Objective
Scan ALL currently tradable KuCoin USDT-margined linear Futures contracts instead of permanently limiting the opportunity set to BTC/ETH/SOL/BNB/XRP. Surface executable candidates, then wait for a verified signal. Many small net-positive trades is the objective; high turnover by itself is not. A system that has no acceptable candidates must remain flat.

## Public inputs
1. GET https://api-futures.kucoin.com/api/v1/contracts/active — contract status, quote/settlement currency, listing date, multiplier, lot size, taker fee, max leverage, 24h turnover.
2. GET https://api-futures.kucoin.com/api/v1/allTickers — market-wide best bid/ask, displayed best quantities, last market event timestamp.
3. KuCoin public WebSocket execution, tickerV2 and synchronized level2 book subscriptions, only for the selected candidates. No private credentials.
Documentation: https://www.kucoin.com/docs-new/rest/futures-trading/market-data/get-all-symbols and https://www.kucoin.com/docs-new/rest/futures-trading/market-data/get-all-tickers

## Already implemented — standalone preflight
Run: python -m daiinas.universe --equity 8 --top 20 --output reports/universe-8.json

It reads two public data snapshots and writes the full audit for every contract, including all rejection reasons. Preliminary eligible symbols must be open linear USDT perps, older than 7 days, with valid fresh best quotes, 24h turnover >=1m USDT, spread <=8 bps, valid lot and multiplier, and minimum lot feasible under illustrative 3x margin and 0.25% equity risk with an assumed 20-bps stop. These settings are HYPOTHESES, not empirically validated optimal filters. The output status READY_TO_OBSERVE means only that a symbol deserves richer monitoring. NO_EXECUTABLE_CANDIDATES is an acceptable outcome. The ranking is liquidity/spread priority for data collection, NOT a profitability or alpha score.

A required caution: A minimum lot that fits an ASSUMED 20-bps stop may fail a real strategy's wider stop. Real bid/ask depth, slippage, extra contract rules, funding and shared portfolio exposure must still be checked at the precise decision instant. The tool never sends orders or forecasts earnings.

## Next-stage dynamic streaming (not yet implemented)
- Tier A: examine all active contracts periodically using a rate-limited, cached public metadata + all-tickers snapshot.
- Tier B: shortlist up to 20 contracts. Keep a small hysteresis/minimum-residency window to avoid constantly switching.
- Tier C: subscribe 3–8 candidates to detailed trade, quote and synchronized depth streams, with throughput/rate limits; always retain subscriptions needed for open paper positions.
- Compute price momentum/volatility, CVD/aggressor flow, OI/funding if observed, orderbook depth, spread and timestamp quality. Missing required data => no trade.
- Opportunity ranking must reward VERIFIED net expectancy after costs, not the strongest 24h percentage gain. Never force a preset daily trade count.
- Entry plan must produce side LONG/SHORT/NO_TRADE, rationale, quote validity, exact affordable quantity, real stop level, target or dynamic exit plan, expected net edge, rejection reason and signal expiry. Trade execution is NOT yet implemented.
- Exit conditions: stop, reversal/invalidation, spread/depth deterioration, funding cost, account risk stop, stale data, take-profit and dynamic trailing/profit protection. No mandatory fixed hold time. Maker order fills cannot be assumed.
- Capital escalation/de-escalation follows separate adaptive controller, with deposit-adjusted high-water mark and account-wide risk, never increasing leverage merely to force a minimum trade.

## Acceptance gates
1. Verify complete real snapshot coverage and report observed/eligible/rejected counts for 8/50/100 USDT separately from the same snapshot.
2. Deterministic timestamp and unit normalization tests; no look-ahead, stale or duplicate market events.
3. Prove dynamic subscribe/unsubscribe safety, reconnect and book resynchronization while keeping active paper positions watched.
4. Reliable independent forward paper trading and trade ledger after spread, fees, slippage, funding, minimum lot and maker nonfill; reject non-positive expectancy. Preserve losing v1 baseline.
5. Keep live orders, private exchange credentials and Bitsgap disabled until separate authorization and validation.
