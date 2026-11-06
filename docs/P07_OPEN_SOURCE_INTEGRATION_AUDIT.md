# P07 selective open-source integration audit

**Baseline:** P06 `7fe74ca08f482cafa1301c51b10a93f5e6a3fb17`  
**Scope:** development and offline PAPER research only. `LIVE_TRADING` remains
disabled. No provider credentials, market writes, orders, cancellations,
transfers, margin changes, or deployment were used.

## Decision matrix

| Candidate | Audited source (2026-11-06) | Licence / dependency impact | DAIINAS gap and comparison | Decision |
| --- | --- | --- | --- | --- |
| Hypothesis | `HypothesisWorks/hypothesis` `9ab0be61` | MPL-2.0; development extra only: `hypothesis>=6.100,<7` and transitive `sortedcontainers` | Existing example tests cover known safety cases but cannot economically enumerate decimal, ladder and inert-preview boundary combinations. Generated examples add deterministic shrinking on failure and do not alter runtime. | **ADOPT** |
| QuantStats | `ranaroussi/quantstats` `d1a214fb` | Apache-2.0; requires pandas, NumPy, SciPy, matplotlib, seaborn, tabulate and yfinance | Ledger is exact-decimal, campaign/account scoped and has no approved timestamped portfolio-return series. Converting synthetic legs to annualized portfolio analytics would risk misleading results. | **REJECT** |
| CCXT | `ccxt/ccxt` `a31f1689` | MIT; broad public/private exchange client and generated exchange adapters | It exposes a `kucoinfutures` public market abstraction, including market and precision metadata. DAIINAS currently routes account evidence through Bitsgap, and its tested KuCoin provider already normalizes contract data. No measured metadata gap, latency gain, or Bitsgap compatibility exists. | **REJECT** |
| Hummingbot | `hummingbot/hummingbot` `9af100d6` | Apache-2.0; full application/connector stack | Its KuCoin Perpetual connector is useful source evidence for client/exchange order-id correlation, REST/WS reconciliation, reconnect replay and partial-fill handling. It is a direct KuCoin connector, not Bitsgap. Embedding it would create a second execution/risk authority. | **REJECT as dependency; reference only** |

Upstream commits are audit pins, not vendored code. The P07 branch copies no
upstream source.

## Accepted integration: Hypothesis

`pyproject.toml` defines an optional `test` extra. Production dependencies
remain empty, and importing `daiinas` never imports Hypothesis. CI explicitly
installs `.[test]`; a missing optional library is therefore a CI failure rather
than a skipped pass.

`tests/test_p07_hypothesis_properties.py` uses the public
`hypothesis.given`, `settings` and strategy APIs to generate and shrink:

* valid exact Decimal capital and settled-P&L sequences, checking Capital
  Ladder snapshot/restart equivalence, non-negative reserve/active balances and
  the ten-slot ceiling;
* valid quantity, stop, target, side and x1--x5 leverage combinations,
  checking that `InertOrderGateway.preview` is deterministic and remains
  `PAPER_PREVIEW_ONLY` with `orders_enabled=False`;
* arbitrary non-empty position IDs, checking stable, distinct MOCK entry/stop/
  target identities without an order transport.

The generated tests are deliberately bounded (80 examples) and use no clock,
network, database, exchange, account, or secret. A counterexample will be
minimized and reported by Hypothesis as a normal failing test fixture. The
initial run completed three generated properties successfully on Python 3.12.

This improves validation coverage, not trading capability. It does not alter
Model A, the v4.7 selector, Capital Ladder policy, exposure caps, P04 gateway,
Bitsgap authentication or P06 feasibility gates.

## QuantStats assessment

QuantStats provides portfolio analytics, but its current public project
metadata declares the heavy scientific/plotting dependency set and `yfinance`.
DAIINAS does not have an approved production portfolio-return time series for
it: its journal is a source of exact settlement facts, while v4.7 scenarios are
explicitly PAPER. A trade-level series is not a portfolio return series, and
annualizing the short synthetic sessions would violate P07.

No adapter was added. A future request must first define a versioned,
timestamped, fully settled PAPER equity series and a non-annualized metric
contract that reconciles every point to `PortfolioLedger` journal facts. It
must then run identical baseline/variant data and retain QuantStats as an
offline optional environment. Until then the dependency cost and reporting risk
outweigh the benefit.

## CCXT assessment

The audited `kucoinfutures` source declares a KuCoin Futures public/swap
adapter and supports standard market discovery and precision conversion. That
does not establish compatibility with the Bitsgap API or improve the existing
DAIINAS public-provider pipeline. CCXT also contains private order and
transfer surfaces; installing it creates accidental capability and maintenance
scope with no measured benefit.

No CCXT package, credentials, requests, or adapter was added. A future public
metadata-only experiment needs a captured, redacted contract corpus and a
measurement showing that CCXT corrects an existing DAIINAS contract field
without regressing freshness, rate-limit behaviour or symbol mapping.

## Hummingbot reference findings

The KuCoin Perpetual connector source tracks `clientOid` alongside exchange
order ids, reconciles REST and user-stream updates, treats reconnects as replay
sources, and has code paths for partial fills and missing orders. These are
useful engineering patterns already aligned with P04's idempotent journal and
P06's fail-closed reconciliation requirements.

They do not establish a Bitsgap endpoint, authentication scope, exchange-native
TP/SL acknowledgement, or protection semantics. In particular, a direct
KuCoin connector cannot close P06's provider-evidence blocker. No Hummingbot
code, dependency, execution engine, connector, key, or order route was added.

## Reproducibility and results

The accepted property suite is run by the normal Python 3.11--3.13 CI matrix
after an explicit `.[test]` install. It supplements the preserved regression,
P04 MOCK, P06 blocked-readiness, v4.6 and v4.7 proof steps. It is a reliability
comparison: before P07, generated input coverage was zero; after P07, all
three bounded properties pass while every generated preview remains inert.

There is no new performance or profitability claim. QuantStats and CCXT have
no benchmark because their acceptance prerequisites were absent; reporting a
made-up latency, risk-adjusted return or strategy advantage would be invalid.

## Final recommendations

* **Hypothesis: ADOPT** as a removable development-only test extra.
* **QuantStats: REJECT** until reconciled PAPER equity-series requirements are
  supplied.
* **CCXT: REJECT** until a measured public-metadata gap is demonstrated.
* **Hummingbot: REJECT as integration; retain only the source-backed lifecycle
  patterns above as reference.**

All unaccepted projects remain absent, so P07 adds no competing ledger, bot,
execution gateway or risk authority.
