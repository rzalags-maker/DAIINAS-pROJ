# DAIINAS v4.6 — Capital Ladder inside the continuous Futures-funded trading loop

**Owner clarification: 2026-11-01. Priority P0.** Read together with Issue #15 (Futures account cycle-zero and rolling balance), Issue #10 (Capital Ladder Model A), `docs/V4_CAPITAL_LADDER.md`, and v4.5 PAPER strategy specification on `feature/v42-kucoin-control-plane`. This adds an **early-stage win-gated eligibility mechanism** to the existing capital-funded ladder; it does not authorize live trading, margin transfers, or automatic position openings.

## Meaning of a "win" versus a funded trade port

- A **WIN** is one **fully closed, reconciled campaign** with **strictly positive realized NET P&L after fees, slippage and funding**. An unrealized gain, open winning leg of an unfinished hedge/campaign, deposit, refund, positive mark, or partial exit does NOT count as a win.
- An **unlocked candidate trade port** is permission to consider one more concurrent position after a WIN. It is NOT free cash, margin, a guaranteed fill, or permission to exceed exchange minimum contract size, current account balance, risk/stop budget, and available Futures margin. Count campaign once, exactly once across restarts, by immutable campaign ID.
- An **actually openable trade port** requires ALL gates to pass: earned eligibility, currently capital-funded capacity, live existing position/pending count, strategy ACTIVE minus commitments, reserve exclusion, actual exchange available Futures margin, min lot, isolated leverage <=2x (PAPER pilot), per-leg <=0.25% active risk, <=1% aggregate planned risk, correlation, fresh market/stop validation, and an approved economic entry. `NO_TRADE` is acceptable.

## Stage A: small-capital bootstrap, actual Futures equity below 100 USDT

**Owner's refined win-gating rule supersedes the *old unconditionally fixed single-candidate* interpretation for the NEW v4 strategy, but not the independent v3.3 regression.**

1. Start a new account from the real *verified Futures funds at cycle zero*, with **one candidate trade port** (assuming a trade is financially feasible at all).
2. Each fully settled WIN increments `earned_port_ceiling` by **one** until a maximum of 10 eligible ports. Do not double count same campaign on replay/restart.
3. A losing campaign does not auto-destruct other positions. Recompute financial capacity and risk. A **material loss** reduces effective slots when the current ACTIVE affordability threshold is crossed, when adverse marks lower allowed funding, or when the existing 3%/6% risk controls intervene. Maintain a loss-latched ceiling for new entries until qualifying *realized* recovery; no fake redemption on unrealized rebound.
4. No arbitrary numerical cap is added to funded concurrency below 100: actually openable ports are limited by **current ACTIVE capital, real available Futures margin, nominal 25-USDT slot affordability where applicable, min contract size, risk and stop constraints**, never by a fictitious balance or forced leverage. If accumulated small-stage wins had enabled more than two funded positions immediately before crossing 100, the existing Model A 100-USDT allocation may lower the new-entry ceiling to two; preserve and safely manage open positions rather than invent instant exits. Below 25 or where min contracts/risk do not fit, even one unlocked port may result in NO_TRADE. The transition must be tested and explicitly handled rather than hidden by an invented bootstrap cap.
5. No position is opened solely because a WIN occurred. The scanner must identify a fresh market opportunity and pass full-cost validation.

Illustrative PAPER-only progression (before fills/order commitments):
- 60.00 Futures equity, 0 wins: 1 eligible; 1 funded candidate only if affordable/risk-viable.
- A full campaign closes +0.50 net => 60.50 current equity and 2 eligible; up to 2 funded candidates *only if* nominal budget and all market/risk gates permit.
- Second closes +0.50 => 61.00 current equity and 3 eligible; actual funded cap is derived from ACTIVE / available margin / nominal budget / full-cost risk, so a third candidate is **not automatically funded**. No borrowed margin or automatic leverage increase.
- One loss of -1.00 => 60.00 current equity; recalc effective slots; do not mechanically assume a successful stop fill or an automatic one-slot downgrade without crossing a defined capital/risk condition.

## Stage B: verified account reaches 100 USDT; preserve owner-selected Model A money mathematics

Crossing 100 USDT is a **policy stage transition, not a new bank account, initial funding, or loop restart**. Activate **Reserve 50 / Active 50**, with TWO nominal 25-USDT funded slots; reserve remains in the Futures strategy ledger and is not pledged to new orders. Respect any unfunded earned-port eligibility as audit history, not immediately usable position count. Subsequent capacity is driven by *settled NET profit and active-capital rungs*, not arbitrary trade count:

| Actual settled capital state (before locked commitments) | Reserve | Active | Capital-funded slots |
|---:|---:|---:|---:|
| 100 | 50 | 50 | 2 |
| 125 | 50 | 75 | 3 |
| 150 | 50 | 100 | 4 |
| 200 | 50 | 150 | 6 |
| 300 | 50 | 250 | 10 |
| 350 | 100 | 250 | 10 |
| 400 | 100 | 300 | 10 |
| 450 | 150 | 300 | 10 |

**Do not silently rewrite Model A as “one tiny winning trade funds one entire new 25-USDT slot.”** E.g. a +2% realized net win on a 25 allocation is about +0.50, not +25. The WIN may count for track record/eligibility; a **NEW funded slot** above 100 occurs only after the relevant capital step is actually funded. External deposits do not count as trading P&L, and require explicit allocation authorization.

At ten, continue existing alternating complete +50 net-to-Reserve / +50 net-to-Active scaling; keep max ten slots and scale position budgets only as ACTIVE increases. For a verified initial Futures balance already above 100 (e.g. 450), initialize **directly in the corresponding Model A stage**. Do not force a 60, 100, or 300-USDT bootstrap sequence, and do not invent past winning campaigns.

## Loss reversal and loop continuity

- If active capital falls across a 25-USDT rung, reduce `capital_funded_slot_ceiling`, block fresh entries exceeding it; if current existing exposure is above cap, pin positions and exit in an auditable safe order using real quotes and order/fill status. Never pretend a position vanished or immediately market-close on unverified liquidity.
- After ten-slot scaling, the existing committed-active recovery rule applies before further profit distribution to Reserve/Active. Pending and reserve are never automatically drawn down to cover trading losses.
- Reconcile KuCoin Futures cash/equity/free margin/orders/fills before EVERY material allocation decision. `INITIAL_FUNDING` remains one immutable historical event; current funds after each result are the new cycle's input. Restart reloads the identical campaign win IDs, slot eligibility, funding and money states and reconciles the exchange.
- The software Reserve is strategy-unspendable capital but is not physically isolated from exchange Cross/UTA collateral or liquidation. The pilot strategy calls for ISOLATED 1–2x and full-cost protective exits. No guarantee stop order fill.
- The goal of a campaign remains +2% realized NET on allocated capital. Initial 0.5% adverse entry-price SL is a PAPER trial assumption pending exact user approval; it must not be confused with the existing 0.5% campaign-capital loss gate. Sizing obeys the tighter financial risk constraint.

## Required implementation and tests for Codex

1. Preserve existing Model A code and old regression without accidentally changing all accounts. Add explicit new-v4 `earned_port_ceiling` and `funded_slot_ceiling` with typed phase/provenance, immutable campaign-win dedup and anti-replay.
2. Sub-100 small-capital: start one; WIN unlocks one *candidate* up to ten; actual positions stay constrained by verified available capital/margin/lot and full-cost risk, **without invented extra numeric slot limits**; loss/risk latches reduce capacity; no exchange transaction for a mere unlock.
3. Crossing 100: same account, staged allocation R50/A50, no re-initialization; above 100 +25 settled net rung steps to 10; above 10 alternate +50 R/+50 A. Starting at 450 jumps directly to corresponding Model A allocation without invented old trades.
4. Test deterministic 60→60.50→61.00 (candidate permissions 1→2→3; actual funded count derived from ACTIVE, free margin, minimum lot, and risk); 99.50→100.00 including funding-capacity reduction at reserve activation without fictitious exits; 100→125→300 then -40 loss: 10→8 funded slots with old positions retained and managed, +14 still8, +1 9, +25 10. Validate 450 initial account mapping R150/A300/10 and later 450.50 current vs initial 450, with all margin held and risk gates included. Reconcile any existing realized-profit handling during the stage transition to avoid duplicates.
5. Crash/restart when win was committed but the next scan was not: no double WIN or double unlock. Distinguish settled campaign WIN from leg WIN, partial exits, fee-only roundtrips and cost-negative campaigns. Keep active/reserve source records atomic and correct.
6. Full test matrix and actual code evidence; do not merely repeat desired behavior in documentation. No interface/dashboard and no real API/orders at this stage.

**Important interpretation caveat:** The single-win candidate unlock *below 100* is a new owner-directed behavior and has not been implemented or economically validated. It changes the prior Model A bootstrap restriction. Capital-affordability, reserve activation and stop-risk constraints—not a new arbitrary numeric bootstrap ceiling—determine actual funded concurrency.
