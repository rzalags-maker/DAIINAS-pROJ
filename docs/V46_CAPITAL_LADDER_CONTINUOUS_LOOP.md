# DAIINAS v4.6 — Capital Ladder inside the continuous Futures-funded trading loop

**Owner clarification: 2026-11-01. Priority P0.** Read together with Issue #15 (Futures account cycle-zero and rolling balance), Issue #10 (Capital Ladder Model A), `docs/V4_CAPITAL_LADDER.md`, and v4.5 PAPER strategy specification on `feature/v42-kucoin-control-plane`. This adds an **early-stage win-gated eligibility mechanism** to the existing capital-funded ladder; it does not authorize live trading, margin transfers, or automatic position openings.

## FINAL OWNER SELECTED CAPITAL MODEL — A (NOT B)

**Owner re-confirmed 2026-11-01: use MODEL A.** This selection is **final for the current DAIINAS v4/v4.6 specification**. Model B, the constant 50/50 active/reserve distribution, is an archived alternative **not to be implemented or offered as a runtime selector**. This does not replace the below-100 candidate win-gating addition, and does not force actual trade entries.

| Eligible settled Futures capital | Reserve | Active | Maximum nominal funded slots |
| ---:| ---:| ---:| ---:|
| 100 | 50 | 50 | 2 |
| 125 | 50 | 75 | 3 |
| 150 | 50 | 100 | 4 |
| **200** | **50** | **150** | **6** |
| **300** | **50** | **250** | **10** |
| 350 | 100 | 250 | 10 |
| 400 | 100 | 300 | 10 |
| 450 | 150 | 300 | 10 |
| 500 | 150 | 350 | 10 |

- At and above 100 USDT, retain the selected Model A mathematical allocation (100 activates R50/A50; 25-USDT realized net-profit rungs to ten positions at 300; after ten alternating +50 net-profit deposits to Reserve then Active). The 50/50 split happens only at the 100 activation threshold, **not on every account balance**.
- An account that starts at 200 USDT immediately computes **R50/A150, 6 nominal slots** from the verified Futures opening account, with no fabricated campaign wins. It MUST NOT start Model B **R100/A100, 4 slots**.
- An account that starts at 300 USDT immediately computes **R50/A250, 10 nominal slots**, not Model B R150/A150/6. At 300 +50 settled net gain, Model A R100/A250/10; another +50, R100/A300/10.
- Every new cycle uses reconciled CURRENT Futures equity, exchange free margin, committed exposure, and the persistent ledger. Initial funding is history, not the ongoing spending balance. External deposits are accounted for separately, not invented as wins, and need an explicit allocation authorization. Losses reduce position eligibility without arbitrary account reset or unsafe instant closes.
- **Funding 6 or 10 nominal slots is not an order-placement instruction:** new trades still require independent market/risk/cost/lot/margin gates. Remain PAPER and live-order-disabled.

**Acceptance tests must assert the A/B discriminatory counterexamples at balances 200 and 300, plus 300 -> 350 -> 400, direct startup at 450 and post-loss recovery.** Preserve original standalone Model A tests and new v4.6 integrated loop acceptance.

---

## ONE EXECUTABLE RUNTIME CONTRACT — NO COMPETING LADDER MODELS

This is **ONE state machine**, not a request to choose between original PR #9 and newer v4.6. Original Model A remains the financial allocation algorithm for the funded stage. The owner's subsequent per-winning-campaign unlock is the **early-stage capacity policy**, implemented in front of the same ledger. Both consume the **same current Futures account reconciliation** and the same journal, with a single worker/transaction writer. **Do not create a second strategy, account, reserve allocator, or separate loop.**

### Canonical state and precedence

Track `account_identity`, immutable `initial_funding`, `current_futures_equity`, `verified_free_margin`, `active`, `reserve`, `pending`, `external_unallocated`, `deficit`, `allocation_stage`, `earned_early_ports`, `funded_slot_ceiling`, `risk_allowed_slot_ceiling`, `open_and_pending_slots`, deduplicated closed `campaign_ids`, and `reconciliation_status`. Never use current equity as a substitute for free margin or vice versa.

For every cycle, first atomically reconcile balance / fills / fees / funding / external flows / owned and unknown orders. Then update the existing Capital Ladder ledger **once** for newly finalized net P&L; only then recompute slot capacity, allocation and the next entry size. No account re-initialization occurs on any stage transition or restart.

1. **Not yet activated (verified Futures portfolio total <100 USDT):** `allocation_stage=BOOTSTRAP`; `reserve=0`; one candidate is initially eligible. Each *unique completely settled, net-positive campaign* increments `earned_early_ports` by one, capped at 10. Losing campaigns/marked drawdown can reduce actually allowed new entries through funded-margin and risk gates, without erasing open exchange positions.
2. **First reach of 100 USDT settled, eligible allocated capital:** perform one idempotent `ACTIVATE_LADDER` **inside the existing account**, `reserve=50, active=50, funded_slot_ceiling=2` at exactly 100, with delta handled by the accepted Model A. Keep earned wins as historical audit only: from this point **funded capacity is governed by Model A**, not winner count. Candidate permissions never create capital or override margin/risk. If there are already >2 real open/pending legs, block additional entry and manage existing positions safely, no fabricated close or automatic account reset.
3. **Above 100 USDT in Model A:** each full additional 25 USDT *eligible settled net trading profit* allocated to ACTIVE finances one more slot, max 10 at 300 total; after ten, complete +50 profit steps alternate `RESERVE` then `ACTIVE`. When account starts *already above 100*, initialize directly into the appropriate Model A allocation **based on actual verified initial equity**; do not invent prior winning campaigns. A 450-USDT verified opening leads directly to its corresponding stage.
4. **Losing or dropping below a previous threshold:** remain in the **previously activated stage** and reverse available *financial* slot capacity/risk; **DO NOT return to bootstrap or unlock reserve** merely because equity falls from 100 to 99.99. Losses reduce ACTIVE and entry limits; any unrecoverable excess is explicit deficit; only realized recovery can reauthorize loss-latched slots. Reserve stays budget-restricted.
5. **New-entry decision:** `entry_slots = max(0, min(stage_eligible_ceiling, capital_funded_ceiling, risk_eligible_ceiling) - open_and_pending_slots)`; for BOOTSTRAP stage, `stage_eligible_ceiling=earned_early_ports`; for ACTIVATED, use Model A `funded_slot_ceiling`. `capital_funded_ceiling` is computed using *current* strategy ACTIVE budget, actual spendable free Futures margin, existing commitments, required minimum lot and full stop/cost accounting. No arbitrary extra sub-100 slot cap. If any verified data missing, zero new entries and keep existing-risk monitoring. Individual trade margin/risk sizing must still pass strict independent checks. **The count is the maximum eligible number, never a command to place that many orders.**
6. **Next cycle:** after a close (profit or loss), market change or restart, use the updated *reconciled* account and persistent ladder/campaign journal; rescan the market and create a new PAPER intent only if the present opportunity passes all gates. Current balance is not permanently capped by initial funding. External deposits never masquerade as profit or auto-scale an unapproved budget.

### Required nonconflicting acceptance matrix

- 60 initial / no wins => 1 candidate; +0.50 realized net => 60.50 and 2 candidate permissions; +0.50 => 61 and 3 earned. **Actually financeable slots still depend on true ACTIVE, free margin, contract min and current risks.** Replay same campaign does not add a fourth permission.
- 99.50 actual verified account +0.50 settled net => existing ledger activates once at 100, R50/A50 and 2 funded slots; the historical early-win counter persists but does not override the new stage. If >2 positions existed at transition, no new entries, existing positions remain tracked until safe confirmed exits.
- 100 start -> 125 -> 300 => R50/A250 and max 10 funded slots, **only** on actual finalized monetary rungs; a +0.50 winning 25-USDT slot does NOT become a funded +25 slot above 100.
- 300 -> 260 (realized -40): R50/A210, cap 8; +14 => active224/cap8; +1 => active225/cap9; +25 => active250/cap10. No reserve movement.
- 100 -> 99.99 after realized loss => remain in activated stage, R50/A49.99; **no bootstrap reset**, cap decreases as its monetary/risk gates dictate.
- 450 actual starting Futures funds => direct Model A R150/A300, 10 maximum nominal slots; after +0.50 net => current total 450.50; after -0.20 => 450.30; process restart resumes 450.30 and same historical INITIAL_FUNDING and campaign IDs, not a new 8/100/450 seed.
- Unknown manual KuCoin position, stale data, missing protection or insufficient min-lot exposure => NO_TRADE, no duplicate entries and no fictitious fills. Existing positions remain tracked.

**Implementation delivery, not prose-only:** wire this transition into the existing `PortfolioLedger`/CapitalLadder with explicit versioned execution policy and atomic events; test the cases above end-to-end on a mocked Futures account stream and run existing v3.3/v4 test suites. An unimplemented diagram, separate standalone calculator, or only green historical tests do NOT satisfy this acceptance. Live API/orders remain disabled.

---

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
