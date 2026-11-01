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
`verify-backup`, replay and source-archive commands remain available. In v4.7,
`pause` blocks entries while the worker continues risk monitoring; `stop` disarms
the bounded session and ends the worker, retaining/reporting PAPER exposure.
Legacy `stop` retains its original pause semantics.
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
40 coupled alternatives: x1–x5, 0.5%/1% price stops, and maker/maker, maker/taker, taker/maker, taker/taker paths using identical decision-time inputs. Each intent and filled
leg stores selected leverage, notional, reserved margin, stop/target, allocated
capital, costs and rejection/selection evidence. Account-snapshot `leverage` remains
the v4.6 historical baseline field: it is **not** reinterpreted as an account-wide
per-position permission. In v4.7 the explicit MOCK isolated account and public
per-instrument max leverage / initial-margin limits bound the paper selector.
Actual authenticated account capabilities remain unknown.

The selector sizes down against the strictest of campaign loss <=0.5% allocation,
per-leg <=0.25% effective ACTIVE and aggregate <=1%, correlation and free margin.
The 0.5% and 1% adverse **entry-price** stop hypotheses are distinct from those monetary budgets. Widening the stop shrinks permissible notional; it never widens the monetary cap.
A configured stop-gap allowance (default 5 bps), adverse slippage/tick rounding,
spread, path-specific entry/target fees, conservative taker stop fees and modeled carry are included. Maker 0.02% / taker 0.06% are named owner PAPER scenarios (public contract metadata takes precedence with the existing taker floor), not an authenticated fee tier. All four paths are retained for analysis; the executable quote model uses taker/taker. POST_ONLY_LIMIT maker/taker requires a normalized authoritative MOCK receipt, never a quote touch. Maker-TP paths are cost scenarios only. Full posted allocation at
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
  and a verified bounded-session acceptance run. A separate 24h reliability test remains unrun; 24/7 trading is not mandatory. Existing hardened `deploy/daiinas-v4*` units
  can be configured with the new profile/paths; none was deployed by this task.
- Real Futures account capital needs the separately approved General-only read-only
  connector and verified per-symbol/account scope/collateral/capability mapping.
  UTA remains unsupported. No credentials, private exchange calls or live orders
  are introduced. Multi-day held-out economic validation remains open.


## Bounded START/STOP sessions and inert venue boundary

A fresh explicit PAPER profile starts one durable session on its first modeled
account reconciliation. Default duration is five hours; policy permits a shorter
bounded duration, never more than five hours. Expiry cancels known unfilled
entries, disarms entries, persists STOPPED_FLAT or STOPPED_WITH_EXPOSURE and ends
the worker. Normal worker exit also disarms. To deliberately start another session
on the SAME config/databases, use `continuous run --start-session ...`. This never
clears operator PAUSE, risk HALT, funds or reconciliation holds. Existing `stop`
is a durable entry PAUSE; it continues risk monitoring and does not flatten.
Session START/STOP source controls require actor/idempotency and report durable
ledger ACK; they are local tests/CLI, **not a deployed authenticated mobile API**.
A five-hour virtual-clock regression is not a five-hour real host uptime claim.

`execution_boundary.InertOrderGateway` previews the same accepted intent (stable
clientOid, instrument/side, quantity, leverage, isolated mode, stop/target and
reduce-only children). Every place/cancel/modify method raises: no transport exists.
Native exit handling is **MOCK_NATIVE only**, with owned IDs, actual receipt fee
and liquidity role, immutable fill-ID deduplication, authoritative remaining
position/cash/free-margin, child-size and sibling-cancellation proof. An uncertain
ACK creates a durable reconciliation hold, blocks quote fills/replacements and
preserves exposure. Updated authority may finish the same immutable receipt once;
WS/REST duplication cannot book another close. Partial exits retain the occupied
slot and residual coverage. Free margin authority can tighten the local model.
Passive entries require receipt proof plus filled quantity, canceled partial tail
and child coverage; no maker fill is inferred from a touching quote. Entry after
disarm/unknown ownership remains a reconciliation blocker, never invented flat.

Native MOCK receipts carry no invented BBO: absent spread decomposition is marked
UNAVAILABLE. All fee amounts are accounted exactly once. Normal quote-model exits
remain explicitly modeled taker execution. Native sibling cancellation/protection
is validated data in a simulator, **not KuCoin OCO or native-order verification**.
When no worker runs there is no observation, discovery, replacement or modeled
quote exit. Tests can inject a reconciled offline native MOCK fill after restart;
actual exchange-native protection requires a separately authorized implementation
and venue verification. Live routing, keys and private API activation remain off.


Full-universe transport isolates an unbridged symbol in a 30-second quarantine
rather than letting it repeatedly tear down healthy markets. REST snapshot retries
wait 1 then 2 seconds for a fresh snapshot; **only contiguous post-snapshot deltas**
verify L2. Unpinned failed observations are unsubscribed, while owned/pending
exposure stays subscribed, untrusted and pinned for recovery. Quarantine and exact
expected/received gap diagnostics appear in runtime/health evidence. No synthetic
bridge, skipped sequence or snapshot-only trust is used. Legacy transport semantics
remain unchanged outside v4.7.


## Closed OHLCV confirmation and actual local session commands

New profiles generated by `python -m daiinas.v47` set
`require_candle_context=true`. Existing saved profiles/checkpoints retain their
original policy identity; no account is reset or silently migrated. The deep
shortlist (including pinned symbols) now downloads public KuCoin **closed**
1m/5m/15m candles. Three concurrent calls maximum and per-closed-interval caching
bound REST use. Sixteen contiguous bars per interval are required; missing candles
are not synthesized, and live/future bars cannot influence a decision. Each raw
response/body hash, normalized rows digest and request parameters are retained in
the same immutable source journal. Financial checkpoints retain only summaries.

Each qualified candidate additionally checks closed 5m/15m countertrend evidence,
1m ATR/noise and the last three closed swing highs/lows. A stop inside that closed
structure is rejected; widening to 1% must still pass the SAME monetary caps,
net target, margin, market-envelope and leverage tests. These are observational
confirmation heuristics, not calibrated forecasts. Selected positions retain the
exact candle context digest. Stale/unavailable context blocks new entries and
never disables existing position management. OHLCV provides no CVD/order flow;
those still require actual public execution and verified order-book feeds.

With the same config/source/PAPER paths, local commands now distinguish:

```sh
python -m daiinas.continuous start --config /tmp/v47-paper.json --session-seconds 18000 --actor local-owner
python -m daiinas.continuous pause --config /tmp/v47-paper.json
python -m daiinas.continuous status --config /tmp/v47-paper.json
python -m daiinas.continuous stop --config /tmp/v47-paper.json
```

`start`/`stop` queue source commands; they do not start an absent process and do
not claim effective worker ACK. Output explicitly says
`SOURCE_ACCEPTED_AWAITING_WORKER`. STATUS exposes the committed session and ACK
freshness. START never clears PAUSE/HALT; `resume` clears only PAUSE. An operator
must still run/supervise the existing worker. This is local filesystem-authorized
control, not an authenticated mobile endpoint, a private exchange connection, or
guaranteed real venue protection when the PAPER worker is stopped.
