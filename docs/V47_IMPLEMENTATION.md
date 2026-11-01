# v4.7 executable PAPER conveyor

This implements the owner specification in the existing continuous engine.
`PortfolioLedger`, the immutable source journal, the single SQLite writer, funding,
Capital Ladder Model A and account reconciliation remain the financial runtime.
There is no second trader, wallet allocator, GUI or order transport.

## Run the existing service

```sh
python -m pip install -e '.[live]'
python -m daiinas.v47 --capital 200 --account-id paper-v47-200 --output /tmp/v47-paper.json
python -m daiinas.continuous run --config /tmp/v47-paper.json \
  --source-db state/v47-source.sqlite3 --paper-db state/v47-paper.sqlite3
```

`[live]` is the existing public-WebSocket dependency extra; it does **not** enable
live orders. `--capital` and a named PAPER account are required; there is no capital
default. This creates an explicitly **MOCK** Futures account, not a verified account
balance. Keep its config and both databases for restart; do not regenerate funding
or overwrite the v4.6/legacy databases. New default paths have a `v47-` namespace
and account identity hash. Existing identity guards reject an incompatible ledger.

The ordinary continuous-service `stop`, `resume`, `status`, `backup`,
`verify-backup`, replay and source-archive commands remain available. A stop/pause
blocks entries and preserves open-risk monitoring; it does not flatten exposure.
A CLI invocation is not proof of a deployed authenticated chat-control bridge.

```sh
python -m unittest discover -s tests -v
python scripts/verify_v47.py --output-dir /tmp/v47-proof
```

Use a fresh proof directory. The latter command is **synthetic market + MOCK
account acceptance**, with source/PAPER SQLite backups, checksums and identical
replay. It is not actual strategy performance. The separate GitHub v4.7 public
workflow records actual KuCoin public observations using explicit modeled capital.

## Leverage and economics

`adaptive_execution.LeverageSelection` evaluates
all x1–x5 alternatives using identical decision-time inputs. Each intent and filled
leg stores selected leverage, notional, reserved margin, stop/target, allocated
capital, costs and rejection/selection evidence. Account-snapshot `leverage` remains
the v4.6 historical baseline field: it is **not** reinterpreted as an account-wide
per-position permission. In v4.7 the explicit MOCK isolated account and public
per-instrument max leverage / initial-margin limits bound the paper selector.
Actual authenticated account capabilities remain unknown.

The selector sizes down against the strictest of campaign loss <=0.5% allocation,
per-leg <=0.25% effective ACTIVE and aggregate <=1%, correlation and free margin.
The 0.5% adverse **entry-price** stop is distinct from those monetary budgets.
A configured stop-gap allowance (default 5 bps), adverse slippage/tick rounding,
spread, both taker fees and modeled carry are included. Full posted allocation at
x5 is rejected when it violates money risk. Higher leverage cannot rescue an
unaffordable minimum lot. Among feasible alternatives the lowest leverage wins;
no quantity/leverage increase is allowed when repricing an admitted intent.

The target solves for +2% **NET on campaign allocation**, not a raw 2% token move
or 2% of a smaller posted margin. Fees/carry and actual fill quantity change the
required executable price. A historical move envelope from the symbol's own
micro/trend observations screens target reachability. It is an **uncalibrated
research proxy**, not expected-return/probability or a guarantee of future movement.
No forecast or no feasible cost/risk/target => NO_TRADE.

## Whole-market discovery, selective observation

The existing public `contracts/active` + `allTickers` scan covers the complete
catalog and audits unsupported/ineligible contracts. A bounded rolling quote pulse
classifies each token separately using available 1m/5m/15m/1h history. Unwarmed
horizons stay unknown. Volume/gainers/losers do not mechanically determine direction.
Low liquidity, stale/crossed quotes and abnormal spikes do not become entries.

Pulse priority feeds the existing dwell/hysteresis rotation. Only a limited
shortlist receives deep trade/BBO/sequence-verified L2 analysis; open/pending risks
are pinned **in addition** to that shortlist, up to the existing provider hard cap
of 20 symbols. Capacity replacements release only obsolete unpinned streams,
with durable-pin checks before unsubscribe. The engine ranks fresh qualified deep
candidates by observed movement versus costs, validates financial feasibility in
rank order and admits at most one new intent per material quote. It never emits a
fixed ten-order burst. Every open position is marked/managed before discovery.

Summary quotes are **not order-flow data**. CVD uses the public execution feed;
BBO/L2 pressure uses the separate verified streams. Historical candle/archive
capability is preserved separately; this release does not invent candle-derived
trade flow or claim a calibrated OHLCV forecast. Rolling pulse history stays in
immutable SCAN records, not duplicated in every financial checkpoint. After
archiving a segment without its preceding scan, pulse history safely warms again.

## Paper lifecycle and financial recurrence

Entry is modeled market IOC on a later quote after the existing latency and drift
checks. It may partially fill at displayed lot-normalized depth; the unused tail
is canceled and explicitly audited, releasing its proportional allocation. There
is no invented full fill or untracked partial intent. Filled quantity receives a
`REQUESTED` modeled stop; a later fresh wire/provider observation acknowledges
`MODELED_ACKED` coverage. Missing/failed coverage freezes new entries and requests
a later-quote controlled exit. This is **not an exchange protection ACK**.

TP touch is not a fill. A resting modeled target must remain executable at its
net threshold on a later quote; insufficient depth yields partial execution,
while a price retreat gives `TP_NOT_FILLED`. A stop supersedes an unfilled TP.
Exits consume shared displayed liquidity, keep the residual position/stop pinned,
and allocate entry fees exactly across slices. The existing maximum time-at-risk
safety exit remains; no trade has to remain open for a fixed duration.

Entry fees and each exit's gross/fees/carry are posted as modeled cash components
when paid. A partial winning exit cannot advance Model A or earn a WIN. The final
campaign component settles the combined net **once** through the unchanged v4.6
reconciler; it cannot debit entry costs again. If timestamps coincide with a prior
snapshot, the queued cash event waits for the next valid journal time and blocks
new entries meanwhile. Opening funding, cash components, fills, protection state,
source cursor, campaign ID and allocation persist in the same transaction.

`paper_settlement=true` authorizes this local **MOCK cash projection only**. The
raw snapshot's cash/external scope is distinguished from virtual positions and
their reserved margin/exit-cost marks. STATUS exposes effective ACTIVE after paper
marks, paper net equity and commitments alongside raw snapshot fields; no actual
KuCoin position/balance is claimed. Current reconciled cash and commitments drive
the next cycle. Losses never borrow Reserve, re-seed funding, clear HALT, or trigger
martingale. Positive partial hedge/leg marks cannot become a campaign WIN.

## Compatibility and remaining dependencies

- The 271-test baseline and old account policy identities are retained. v4.7 is
  opt-in/version-bound; no automatic migration, opening reset or Model A change.
- Existing M0/M1/M2/M3 v4.6 research controls remain. v4.7 is directional/adaptive;
  simultaneous same-token hedge is not authorized by LONG/SHORT capability and
  remains unsupported without independent economic/mode/protection evidence.
- Public fees/spread are observed; actual private fee tier, funding settlements,
  maintenance/liquidation and exchange-native trigger/coverage semantics are not
  verified. Carry is a configurable estimate, not a real funding debit. Stop gaps
  can exceed planned loss. The selector explicitly marks liquidation unverified.
- Independently hosted deployment still needs durable storage, supervised single
  worker, backups, heartbeat/alert routing, an owner-authenticated command bridge
  and an actual 24h acceptance run. Existing hardened `deploy/daiinas-v4*` units
  can be configured with the new profile/paths; none was deployed by this task.
- Real Futures account capital needs the separately approved General-only read-only
  connector and verified per-symbol/account scope/collateral/capability mapping.
  UTA remains unsupported. No credentials, private exchange calls or live orders
  are introduced. Multi-day held-out economic validation remains open.
