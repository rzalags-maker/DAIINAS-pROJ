# DAIINAS v4 — Capital Ladder: owner-approved capital allocation

**Implemented here:** independent deterministic allocation controller and 15 automated financial transition tests. **NOT YET wired** to the running v3.3 paper engine, market entry signals or order execution. **LIVE ORDERS DISABLED.** Preserve the already-tested v3.3 engine and its separate account until Codex completes the audited integration stage.

## Agreed mathematical contract

1. **Bootstrap below 100 USDT:** at most **one candidate position**; this applies equally to 8, 29 or 60 USDT. A candidate is NOT a tradable minimum lot guarantee.
2. **At 100 USDT settled total:** begin with **50 USDT protected reserve and 50 USDT active capital**, funding two 25-USDT allocation slots. The 50/50 split applies **at activation only**, not as a perpetual percentage.
3. **First ladder:** every subsequent +25 USDT of genuinely realized **net P&L** into active capital can fund one additional slot. Maximum ten slots. No forced trades or leverage increases to fill slots.
4. **At ten slots:** active=250, reserve=50, total=300. All following realized net profits first accumulate in a protected-but-pending pool until +50 goes to reserve (total=350, reserve=100). The next full +50 goes to active (total=400, active=300): each of ten funded allocation budgets rises nominally from 25 to 30. Alternate +50 reserve / +50 active indefinitely. Keep the **ten-slot cap**.
5. **Reversal after losses:** negative realized P&L is debited from active capital only. A fall below a multiple of 25 lowers the maximum allowed slots: 250->10, 225->9, 200->8, ..., 25->1, below 25->0. Pending and reserve are never automatically depleted to cover losses. In bootstrap the number remains max one while active>0.
6. **Open-loss response:** an unrealized loss may latch the allowable slot count down. Unrealized gains **do not** reauthorize reduced slots. Reauthorization requires a subsequent *realized* positive result meeting the active-capital threshold. Existing excess positions require safe monitored exit handling; do not invent closing fills to achieve the reduced ceiling.
7. **Recovery before growth:** after ten-slot scaling begins, profits first rebuild active to the prior committed active rung (250, 300, 350, ...) before the pending step receives more profits. Reserves never finance recovery.
8. **Loss beyond active funds:** explicitly recognize the remaining deficit as liability, freeze new positions, never disguise the loss by debiting reserve. In real trading, contract/liquidation obligations may nevertheless reach other funds: **physical reserve isolation must be verified**.
9. **Risk is not allocation:** 25 USDT is a position *budget*, NOT an allowed loss or a mandatory trade size. Maximum planned candidate risk starts at 0.25% of effective *active* equity, aggregate portfolio planned exposure at <=1% of active equity, divided among available slots. Further v3.3 risk/lot/liquidity gates, 3% drawdown risk reduction and 6% latched HALT must remain operative. Losses can exceed planned stop risk in gaps, outages or liquidation.
10. **Profit target 1–2%:** an aspiration to validate net of spreads, fee, slippage and financing, NEVER a promised result, assumed daily yield, or excuse to bypass NO_TRADE.

## Golden states — USDT

| Total | Reserve | Active | Pending | Slot ceiling |
| ---: | ---: | ---: | ---: | ---: |
| 8 | 0 | 8 | 0 | 1 candidate |
| 60 | 0 | 60 | 0 | 1 candidate |
| 100 | 50 | 50 | 0 | 2 |
| 125 | 50 | 75 | 0 | 3 |
| 150 | 50 | 100 | 0 | 4 |
| 200 | 50 | 150 | 0 | 6 |
| 250 | 50 | 200 | 0 | 8 |
| 300 | 50 | 250 | 0 | 10 |
| 330 | 50 | 250 | 30 | 10 |
| 350 | 100 | 250 | 0 | 10 |
| 400 | 100 | 300 | 0 | 10 |
| 450 | 150 | 300 | 0 | 10 |
| 500 | 150 | 350 | 0 | 10 |

Reverse example: at 300 = 50 R + 250 A (ten slots). Settled net loss -40 => 50 R + 210 A (eight slots). Subsequent +14 => active 224 (still eight); +1 => active 225 (nine); +25 => active 250 (ten). Zero reserve transfers throughout.

## Deterministic financial identity

**Total = active + protected reserve + pending - explicit deficit = starting capital + cumulative realized net P&L.**

- Deterministic Python Decimal money, no float-based slot thresholds.
- Pure allocation policy: no exchange access, API keys, network calls, private orders, transfers or wallet access.
- JSON checkpoint export/restore uses exact decimal strings. Until integrated, **the caller must persist it atomically**; an in-memory module alone does NOT provide durable paper/live accounting.
- For replay, never count an order fee twice; a deposited USDT is external flow, not trading profit. Derive realized P&L from settled position-close records, not target prices or marks.
- Money physically held in Cross Margin or a connected custodial account may not be protected merely because paper accounting calls it RESERVE. Real reserves must be *nonpledged* and inaccessible to order execution.

## Run tests and explore the controller

From repository checkout:

~~~bash
python -m unittest discover -s tests -p test_capital_ladder.py -v
~~~

~~~python
from daiinas.capital_ladder import CapitalLadder
a = CapitalLadder('60')
a.realized_result('40')                # At 100: 50 reserve, 50 active, 2 slots.
for _ in range(8): a.realized_result('25')  # At 300: 10 slots.
a.realized_result('50')                # At 350: reserve=100.
a.realized_result('-40')               # Active=210, slots=8, reserve=100.
state = a.export_state()
assert CapitalLadder.restore(state).export_state() == state
~~~

## Remaining mandatory Codex integration (do not infer it is finished)

1. Perform the independent v3.3 risk-audit dependency (#8) and retain existing 180+ passing regression tests.
2. Wire CapitalLadder inside the **v3.3 single-writer SQLite paper account transaction** (append-only source event, idempotent fill/debit, checkpoint, audit and wallet-migration boundaries in one transaction). Add explicit 60 and 100 USDT virtual policy scenarios; **do not silently mutate the existing 8-USDT baseline account**.
3. Upgrade paper account from one simulated position to a *map of independent positions* up to ten. Track exposure, margin, min lot, fee, entry/exit pending, capital reservation and safe exit across all symbols. Position identity must permit future (symbol, positionSide) LONG and SHORT legs but no actual Futures Hedge Mode without independent authorization and legal evaluation.
4. Safe reversal: when current open positions exceed the allowed-slot count, freeze new entries, prioritize **real observed executable** risk-managed exits; never magically close or assume unobserved depth. Pin all open/pending exits during watchlist rotation.
5. Risk/correlation gates: portfolio planned loss <=1% of effective active equity (lower limit under v3.3 halt), per-position <=0.25%, no automatic reserve replenishment or margin cross-collateral, correlated-market concentration protection, cooldown and no forced trades.
6. Test multi-position P&L, recovery, 10-slot saturation, the alternating scale increments, reserve storage isolation, marked drawdown, contract minimums, fee costs, partial/unresolved exits, delisting, replay parity, restarts, strategy NO_TRADE, simulated external deposits separate from P&L.
7. Update reports, sample dashboard, and 24-hour host evidence gates. No private KuCoin API and no exchange credentials. Do NOT merge into stable or turn on LIVE.

**The stand-alone controller is executable and unit-tested; the integrated multi-position trading engine is not yet implemented.**
