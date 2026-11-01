# v4.1 per-market adaptive tactics and honest hedge research

**LIVE ORDERS DISABLED.** This is observable-state PAPER research, not an
intelligent price oracle, calibrated expected return model or verified hedge edge.
Dependencies: issue #8 audited transactions/risk and issue #10 integrated Ladder.

## Independent market state and time

Each token has its own bounded publication-time history and state:
UP_TREND, DOWN_TREND, RANGE, TRANSITION, DISLOCATED or UNKNOWN. One symbol's state
never sets another symbol's direction. Persistent state includes 30s momentum,
180s trend/persistence, 600s volatility context (up to 900s bounded history),
observed execution CVD, BBO imbalance, verified L2 pressure, bid/ask sizes,
spread, source fee/contract rules, freshness, transition time and reason.

One-second buckets limit memory/tick churn. All updates use journal availability
and sequence; original provider/actual wire times are independently retained.
No candles are relabeled as trade-flow data and no complete trade tape is claimed.
Cost/volatility-scaled thresholds respond to each asset's observed structure;
there are still heuristic shared model choices (horizons, persistence, confirmation,
correlation cap). They are disclosed assumptions, not empirically universal laws.
Confidence is an evidence category, never a fabricated probability.

- Directional state needs persistent movement exceeding its own volatility/cost
  threshold, compatible micro momentum, fresh book and aligned pressure at entry.
- Repeated reversals and sufficient amplitude may classify RANGE; classification
  itself is not evidence of profitable executable oscillation.
- Contradicting horizons become TRANSITION. Missing/unverified depth or abnormal
  price gaps become DISLOCATED. Insufficient/unreliable structure is UNKNOWN.
- A 3-second state confirmation, deduplicated pressure episodes where applicable,
  30-second campaign cooldown, pending TTL and 90-second default maximum hold
  guard fee-draining switching. These are configurable research assumptions.

## Exactly one policy action per accepted material quote

| Condition | Action / precedence |
| --- | --- |
| Flat control, stale/low-confidence/uneconomic observations | NO_TRADE |
| Existing risk exit or cap reduction | EXIT or REDUCE, before any new tactic |
| Existing one-side valid exposure | MAINTAIN |
| Opposing confirmed regime or dislocation | EXIT on a later executable quote |
| Fresh independent upward / downward state and flow/depth/cost/risk pass | ENTER_LONG / ENTER_SHORT |
| Existing one leg, RANGE, cooldown, two-slot/risk capacity and supported held-out advantage | ADD_OPPOSITE_LEG |
| Both same-symbol legs already open | MANAGE_HEDGE, including residual exposure |

The audit records DECISION once per accepted quote with symbol, regime, selected
action and reason. Fills, signals and exits are separate events. A global M0–M3
research mode selects capabilities, not a universal token direction. The `pressure`
decision model remains an explicit legacy research control; default v4 configs
use the new `adaptive` model.

## Campaign, not winning-leg, economics

A position key is `(symbol, positionSide)`; every leg consumes one funded slot,
its own gross margin/risk, fees and exit queue. Opposite legs do not share a free
slot or receive undocumented exchange margin offsets. A joint campaign ID binds
realized leg results and open exposure:

```
campaign_net_mark = closed_leg_net + sum(open_gross - open_entry_fee
                                       - uncharged_exit_fee - model_carry)
```

Entry fees are already paid in cash but are subtracted here because campaign
performance, unlike cash, starts at zero. A closed leg's net already includes its
entry/exit fees and carry; do not subtract those again. If any remaining leg lacks
a verified executable mark, campaign outcome is UNRESOLVED (`net_mark=null`), with
separately labeled conservative indicative exposure. Campaign gross/net notional,
margin, open planned risk, unresolved legs and realized/marked results are recorded.

Only full campaign finalization settles its net into the Ladder. Partial winners
cannot advance capital rungs. When a leg closes, the remaining side immediately
remains subject to standalone stop, active-capital and campaign emergency loss,
regime invalidation, maximum hold and data-health controls. There is no indefinite
hold awaiting return to breakeven. Exits require a later real quote with full
verified displayed liquidity. Insufficient opposite liquidity cannot be hidden.

The optional target is **2% net on campaign allocated capital**. It differs from
2% price movement or 2% on one slot. Ordinary per-leg stops/targets can exit sooner;
no mechanism manufactures 2% or holds a loser to force it. Default maximum planned
loss remains <=0.25% active per leg and <=1% gross aggregate; funding/carry and stop
slippage are included in the full-cost plan, and gaps can exceed it.

## M0–M3 comparisons and evidence gate

- **M0:** NO_TRADE, unchanged trading balance (external quarantined flows separate).
- **M1:** per-symbol directional-only hypothesis, same financial controls.
- **M2:** symmetric matched-lot hedge control only in RANGE, never a directional
  fallback in UP/DOWN. A failed second entry requests a later executable exit of
  its unmatched first leg; failed matching is not relabeled successful hedging.
  This explicit negative control runs when the observed RANGE and
  capital/contract/risk/depth guards permit. It is not a deployment recommendation.
- **M3:** adaptive directional or flat; opposite leg only after an as-of held-out
  evidence certificate meets the strict guard. Defaults contain no such evidence.

`install-research-evidence` is an append-only local CONTROL record, not a private
exchange call. A record must bind the exact complete policy/source hash (portfolio, paper execution, shadow settings
and execution-money version), finite positive
lower confidence bounds for net return and advantage over directional and flat,
at least 30 held-out campaigns in >=2 windows spanning >=2 days, both leg exit
validation and strict train-before-validation-before-availability chronology.
The guard checks structure/chronology; the owner/research process must verify
artifact authenticity and statistical validity. It does not magically prove a
submitted claim. No positive certificate is manufactured from a short smoke and
`strategy_validated`/`production_ready` remain false. Current short-data expected
utility is a disclosed observed-movement-minus-cost heuristic, **not** an estimated
conditional expected return. Hedge is therefore UNSUPPORTED on current evidence.

Run the same source for all modes and all three separate capital accounts:

```bash
python -m daiinas.hedge_research --source state/v4-100-source.sqlite3 \
  --output-dir state/v41-comparison --report reports/V41_HEDGE_COMPARISON.json
```

The comparison reuses the actual ledger, fills and costs. It warms observable
state on the first chronological half and reports held-out entries from the
second half, without fitting return probabilities on the held-out data. All modes
consume identical records; account policy/eligibility can yield different actions.
A few minutes is not a trained multi-day walk-forward study. The report labels
sparse/dependent samples insufficient, confidence intervals null, hedge advantage
UNSUPPORTED; it never invents error bars or turns zero trades into a positive edge.
Longer independent windows/regimes, NO_TRADE and fixed-five comparisons, conditional
returns, credible uncertainty, correlation and adverse stop-gap tails remain gates.

## Mandatory negative controls and integrated tests

`illustrative_path` labels its outputs SYNTHETIC_ILLUSTRATION_NOT_ENGINE_APPROVED.
It reproduces the owner's 1x 25-notional-per-side arithmetic:

- Equal simultaneous LONG/SHORT at a single ideal mid mark has zero directional
  gross, and negative net after entry/exit spread, slippage and four fees.
- 100 -> 102 -> 105 after closing LONG leaves the losing SHORT; combined net is
  worse than -0.75 gross. A green winner is not a profitable campaign.
- 100 -> 102 -> 98 (and its mirror), with genuinely later quote samples for each
  requested exit, may close both green; costs reduce the 1.00 ideal gross to less
  than .94 net, below 2% on 50 campaign allocation.

Those illustrations do not bypass production-paper risk: ordinary engine stops
may preempt the hypothetical two-winner path. Integrated ledger tests instead
show full risk controls, two gross legs, stale/unfilled losing residual after a
winner close, no premature Ladder promotion, eventual adverse close, all costs,
margin, reserve isolation and source/restart/replay consistency. Bootstrap cannot
fund both control legs. Separate simultaneous-market fixtures test UP/DOWN/RANGE/
UNKNOWN and transition/reversal independently; synthetic histories are not real
public observations.

## Known limitations and independent statuses

No validated predictive edge, calibrated probabilities, full-depth execution beyond
the displayed top level, partial fill engine, exchange liquidation simulator,
actual funding settlements or private-account reconciliation. Correlation is a
rolling observational guard, not a tail-dependence guarantee. Stale marks are
indicative; no safe equity/profit claim is inferred from them. Current comparison
has no proven adaptive hedge advantage and cannot authorize economic expansion.

Implementation and deterministic tests are separate from **paper-soak-verified**,
**economically-validated** and **live-account-authorized**, all false until their
own evidence exists. Independent host: **BLOCKED — HOST NOT PROVISIONED**.
No UK product-eligibility claim, no previously exposed credential use, no merge
of stable or reviewed draft PRs, and no real transfer/order instruction.
