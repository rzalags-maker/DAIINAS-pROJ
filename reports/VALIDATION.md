# Historical validation and service readiness

Continued from `daiinas-v1` commit `3c8421636d44347345b4858c2c729ebdaf130e06`.
The existing engine was retained. Batch defaults remain unchanged; optional
checkpoint continuation supports the read-only service.

## Actual-data attempt: still blocked

The requested download was executed and exited 1 on the first archive checksum:

```text
URL: https://data.binance.vision/data/futures/um/daily/klines/BNBUSDT/5m/BNBUSDT-5m-2025-01-01.zip.CHECKSUM
URLError: <urlopen error Tunnel connection failed: 403 Forbidden>
```

The documented public REST alternative was tested, also without credentials:

```text
https://fapi.binance.com/fapi/v1/klines?symbol=BNBUSDT&interval=5m&startTime=1735689600000&endTime=1735775999999&limit=288
URLError: <urlopen error Tunnel connection failed: 403 Forbidden>
```

Public contract metadata was tested independently:

```text
https://fapi.binance.com/fapi/v1/exchangeInfo
URLError: <urlopen error Tunnel connection failed: 403 Forbidden>
```

Binance documents `/fapi/v1/klines` as the USD-M archive data source in its
[public-data README](https://github.com/binance/binance-public-data#futures).
Its [official connector source](https://github.com/binance/binance-futures-connector-python/blob/main/binance/um_futures/market.py)
also documents the endpoint. Both documents were fetched successfully (HTTP 200),
and their SHA-256 hashes and the exact failed URLs/errors are preserved in
[evidence/historical-access.json](evidence/historical-access.json).

The requested backtest command was also executed and exited 1:

```text
FileNotFoundError: [Errno 2] No such file or directory: 'data/BTCUSDT/5m/BTCUSDT-5m-2025-01-01.zip.CHECKSUM'
```

Zero actual archives, zero publisher checksum files, and no exchange-rule
snapshot were downloaded. No synthetic replacement, spot-data substitution,
policy bypass, fabricated metrics, or profitability claim was made.

## Requested historical performance

These are **unmeasured**, not zero-trade backtest results:

| Measure | In sample | Out of sample |
|---|---|---|
| Executed trades | Not measured | Not measured |
| Rejected signals/orders | Not measured | Not measured |
| Net P&L after modeled costs | Not measured | Not measured |
| Win rate | Not measured | Not measured |
| Profit factor | Not measured | Not measured |
| Maximum drawdown | Not measured | Not measured |
| Average profit per trade | Not measured | Not measured |
| Final simulated balance | Not measured | Not measured |

The configuration starts each sample with 8 USDT, but an initial condition is not
a measured final balance. Whether 8 USDT meets actual contract minimums remains
**unverified** without the public exchange-rule snapshot and entry prices.
With the default margin fraction, leverage, and entry fee, a flat 8 USDT account
has an approximate initial notional cap of `6.4 / (1/3 + 0.0005) = 19.1712 USDT`,
before per-trade stop-risk and quantity-step constraints. This arithmetic does
not establish that any specific Binance contract is executable.

## Environment action required

The saved configuration draft already contains `data.binance.vision` and
`fapi.binance.com`. The current instance reports no custom allowed hosts and a
network-policy state initially `unknown`, then `enforced` with no custom domains;
the concrete proxy denials establish that
this worker still cannot access the required endpoints. Apply/publish the saved
configuration and reconnect or start a task on the updated instance. No new API
secret is needed. Once access works, run:

```bash
python -m daiinas download --config configs/default.json
python -m daiinas backtest --config configs/default.json --output reports/default
```

Keep the raw archive ZIPs, publisher checksum files, `data/manifest.json` and
`data/exchangeInfo.json`. Freeze the **downloaded** rules snapshot in a versioned
public metadata file and use `--rules-file` to reproduce that experiment. Commit
the resulting historical report and provenance after the actual-data run.

## Offline verification and hosting foundation

49 automated tests passed on Python 3.12. Tests include all prior engine tests,
synthetic end-to-end reporting, checkpoint/batch equivalence, pending orders,
both hedge legs, invalidations and funding across restarts, persistent drawdown
halt, restart idempotency, atomic rollback/retry, missing data, clock/backlog
limits, a stop arriving during fetch, persistent stop/resume, stale health,
exclusive ownership and public-only source endpoints. Compilation, CLI help, and static systemd unit
verification also passed. These are synthetic
mechanics tests, not historical performance results.

The continuously running scanner/paper worker has persistent SQLite state,
checksummed public REST response provenance, local health and stop/resume/backup
commands, and systemd deployment/monitoring templates. See
[the service runbook](../docs/SERVICE.md). Independent hosting, live-provider
acceptance, supervisor behavior and multi-day operation have **not** been
verified. No service was deployed and no live orders are possible.
