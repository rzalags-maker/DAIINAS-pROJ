# v1 validation status

Implementation validation on Python 3.12:

- 34 automated tests passed, including a synthetic end-to-end CLI run with actual
  strategy signals, trade/account reconciliation, chronological separation,
  offline repeatability, publisher-checksum handling and all three intervals.
- Compilation and CLI help checks passed.
- Synthetic fixtures are mechanics tests, not historical performance evidence.

## Historical run: blocked, no performance claim

The configured real-data command was attempted:

```bash
python -m daiinas download --config configs/default.json
```

The environment's egress proxy returned **403 Forbidden** while connecting to
`data.binance.vision`. Public `fapi.binance.com` access was also denied by the
proxy. No actual market candles or exchange metadata were downloaded. Therefore
no historical backtest or measured performance report exists yet. The v1
historical-data success criterion remains unverified.

Required environment domains have been saved in the configuration draft:
`data.binance.vision` and `fapi.binance.com`. Review/save these changes in
environment settings and publish the environment. Then rerun:

```bash
python -m daiinas download --config configs/default.json
python -m daiinas backtest --config configs/default.json --output reports/default
```

Preserve the downloaded public rules snapshot and checksum-verified archives.
Commit the resulting report and a frozen public rule snapshot after verifying
that the run used real data. No real trades are possible through this project.
