# KuCoin Classic Futures live market and paper engine

KuCoin is the primary **live public market-data** provider. Binance daily archive
research and the legacy REST worker remain separate and available. This adds
adapters around the existing strategy, shared-account risk engine, simulator,
SQLite store and checkpoint recovery; it does not replace them. No broker,
private credentials, live orders, or execution toggle exists.

## Run

Python 3.11+ on Linux, with the optional pinned WebSocket dependency:

```bash
python -m pip install '.[live]'
python -m unittest discover -s tests -v
python -m daiinas.kucoin_service smoke --seconds 120 --reconnect-after 40 --db state/kucoin-smoke.sqlite3 --report reports/kucoin-connection.json
python -m daiinas.kucoin_service run --config configs/kucoin.json --db state/kucoin.sqlite3
```

The default live interval is 1m; 5m and 15m are also supported. Default account
capital remains 8 USDT. A smoke test does not increase capital or loosen risk
limits to force trades. It can succeed with no trade opportunities; a fabricated
signal is never introduced to meet a trade-count target.

Host HTTPS access must allow `api-futures.kucoin.com` and WSS must allow the
`*.kucoin.com` instance hostname returned by `POST /api/v1/bullet-public`
(typically `ws-api-futures.kucoin.com`). The client preserves environment proxy
settings and verified TLS trust. It only accepts encrypted KuCoin WSS endpoints;
there is no proxy bypass. Tokens are public, ephemeral connection tickets, not
private API credentials. They are never printed or stored, including in SQLite.
No environment secret values are needed.

## Contracts and units

| Canonical market | KuCoin contract |
|---|---|
| BTCUSDT | XBTUSDTM |
| ETHUSDT | ETHUSDTM |
| SOLUSDT | SOLUSDTM |
| BNBUSDT | BNBUSDTM |
| XRPUSDT | XRPUSDTM |

Public `GET /api/v1/contracts/active` must contain all configured open, linear,
USDT-settled perpetual contracts. Base currency, contract type, expiration,
maximum leverage and initial margin are checked. Contract counts use `lotSize`
for both minimum quantity and increment, `maxOrderQty` for maximum, `tickSize`
for price increments, and `multiplier` for base units per contract. The existing
risk engine already multiplies contract count by contract size for P&L, fees,
margin and planned loss; quantity never rounds up to satisfy a minimum.

KuCoin Classic Futures metadata does not publish Spot's `minFunds`. An absent
additional notional minimum is represented explicitly as zero, while lot and
account-risk constraints remain enforced. This is not a claim that 8 USDT can
trade every contract. The 3x/default margin budget can reject even one contract.
Configured taker fees are raised to at least the largest public taker rate across
the selected contracts. A nonzero fixed taker fee is rejected as unsupported.
The existing fixed spread/slippage and conservative 8-hour funding charge remain
model assumptions; neither actual fills nor historical funding are verified.

Static normalized metadata and adapter source hashes identify each paper
account. Changing rules/config/code refuses reuse of that account; use a new DB
for a new experiment. Dynamic mark/last prices do not change the identity.
Metadata is rechecked on reconnection; a changed contract freezes advancement.

## Public stream, synchronization and recovery

Each connection uses a fresh public token. It waits for the welcome and explicit
acknowledgements for all 15 subscriptions (three per market):

- `/contractMarket/execution`: actual public matched trades, not submitted orders
- `/contractMarket/tickerV2`: best bid/ask and contract-sized top quantities
- `/contractMarket/level2`: full-depth incremental changes

The receiver buffers messages from the **subscribed** connection before taking
public full L2 snapshots via `/api/v1/level2/snapshot`. Changes at/before snapshot
sequence S are discarded. Only an exact S+1 delta verifies the snapshot bridge;
every subsequent accepted L2 delta must be exactly +1. Zero quantities remove
levels. Crossed/empty books, off-tick/off-lot data, sequence gaps, backwards or
stale/future timestamps invalidate trust and reconnect. All books are rebuilt on
every reconnect; persisted snapshots are never trusted blindly on restart.
"Verified" means sequence continuity, price/size validation and uncrossed books;
KuCoin's protocol here supplies no exchange book checksum to compare.

Trade/ticker sequences must be monotonic within their own stream, but are not
assumed contiguous: those feeds do not guarantee a +1 per-topic sequence. This
cannot prove every trade was delivered. Conflicting duplicates and envelope
`sn`/data sequence mismatches are rejected. Events are deduplicated persistently.
Timestamp units are explicit (trade/ticker/snapshot ns, L2 delta ms), with a
3-second future tolerance and 15-second accepted event-age limit. Missing
required trade/quote/book streams make readiness false after the configured
staleness threshold. Buffering is bounded and overflow fails closed.

Application JSON pings use the server's `pingInterval`; matching pongs are
required within `pingTimeout`. Reconnect uses bounded exponential backoff and
fresh subscriptions/snapshots. Public tokens are renewed by reconnecting before
the 24-hour lifetime (default 20 hours). The smoke test forces shorter renewals
to exercise this path. SIGTERM/interrupt cancels async tasks and closes the socket;
committed SQLite state remains recoverable.

## Strategy, paper decisions and persistence

Live trades and book data implement the existing `FlowSource` interfaces, in
base quantities. **No new order-flow alpha is invented.** The existing Micro
Liquidity Reversal strategy still runs on completed OHLCV. Verified fresh public
WebSocket data for all configured markets gates paper processing. Public KuCoin
`/api/v1/kline/query` warms the indicators and supplies closed candles; gaps and
duplicates fail validation with no synthetic candles or forward-filling.

The existing `Worker` and conservative simulator handle LONG/SHORT hedge legs,
account-wide margin, sizing, invalidation, costs, stops, targets and permanent
account drawdown halts. Fills are recorded after a candle closes using the prior
signal and next candle open; they are **candle-model paper fills**, not executed
quotes. L2 data is collected/validated but does not falsely certify candle fills
or implement a flow-based signal. Restored missed candles are explicitly
retrospective recovery accounting, not observed live fills during an outage.

The existing SQLite store is extended additively:

- `market_events`: raw public payload, normalized flow, event and receipt times,
  session identity, deduplication keys
- `responses`: public REST bodies with source URLs and SHA-256; token response
  records are explicitly redacted, never raw token bytes
- `paper_decisions`: batch decisions/metrics inside the **same transaction** as
  the existing candles, signals, trades, equity and simulator checkpoint
- Existing `kv`, `events`, checkpoint and account ledger remain authoritative

One process owns each DB through the existing file lock; do not run concurrent
workers against the same paper account or share the DB over a network filesystem.
An outage never silently resets account cash, pending decisions or open legs.

Existing operational controls work with the new DB:

```bash
python -m daiinas.service health --db state/kucoin.sqlite3
python -m daiinas.service stop --db state/kucoin.sqlite3
python -m daiinas.service resume --db state/kucoin.sqlite3
python -m daiinas.service backup --db state/kucoin.sqlite3 --backup-to backups/kucoin-001.sqlite3
```

Stop freezes paper accounting persistently while market collection/heartbeats
continue. Resume can account for missed closed candles within the configured
recovery limit. Health also requires live feed readiness; a persisted account
checkpoint alone is insufficient. Intentional stopped status is explicit.

`deploy/daiinas-paper.service` and the health unit now target KuCoin. Install the
optional live dependency in the host's Python environment before using them;
no Binance metadata snapshot is needed for KuCoin. The general hosting,
backup/restore, capacity and monitoring guidance in `SERVICE.md` still applies,
but its old Binance startup command describes only the retained legacy worker.
No independent host is automatically provisioned by these templates.

## Evidence

The smoke CLI writes an honest JSON report, exiting nonzero unless it observed
all configured trade/quote/book channels, verified snapshot bridges, pongs,
paper decisions and (when requested) a second healthy connection with a persisted
checkpoint. A 120-second run is a connectivity/recovery check, not a strategy
profitability test, continuous-hosting guarantee, or production soak.

`.github/workflows/kucoin-paper-smoke.yml` runs tests and a bounded real smoke on
GitHub Actions, retains a database/report artifact for seven days, and commits
only the public report if the branch has not advanced. It records the tested
commit and run URL. Report-only commits do not retrigger the live smoke. An
Actions run is temporary verification, not the continuously hosted service.

Local Codex connectivity failures are recorded separately in
`reports/kucoin-local-connection.json`. They never count as a passed Actions run.
Synthetic protocol tests are labeled as tests, not real connection evidence.

Protocol reference: KuCoin's [Universal SDK](https://github.com/Kucoin/kucoin-universal-sdk),
`spec/ws/openapi-futures-public.json` and
`spec/rest/api/openapi-futures-market.json` (Classic Futures), especially full L2
snapshot, incremental book, execution, tickerV2, public token and kline schemas.
