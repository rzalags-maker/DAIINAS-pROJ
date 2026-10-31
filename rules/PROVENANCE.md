# Public rules snapshot provenance

- File: `rules/binance-usdm-2026-10-31T114852Z-five-symbols.json`
- Source: Binance public market-data connector, `get_futures_usds_exchange_information` response.
- Source response `serverTime`: `1793447332065` milliseconds since Unix epoch (UTC 2026-10-31 11:48:52.068).
- The file retains exact returned individual symbol records for BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, with the provider `timezone` and `serverTime` values. It is a **five-symbol extract**, not the unmodified full exchange response.
- For this research-only test, contract filters reflect this snapshot, **not historical 2025-01-01 filters**. Execution in an actual exchange is not verified by this simulation.
- No keys, user-account data or private endpoint calls are involved. This snapshot must not be treated as a present-day order-permission check or as proof of current contract availability.
- The public historical candle files and their original publisher checksum files are downloaded separately from `data.binance.vision`.
