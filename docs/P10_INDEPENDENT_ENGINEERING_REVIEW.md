# P10 independent Futures API engineering review brief

Review the offline-only `daiinas.execution_replay`, `ccxt_kucoin_futures`, and
`kucoin_native_futures` modules plus `tests/test_p10_execution_adapters.py`.

The reviewer must have KuCoin Futures REST/WS, conditional-order, reduce-only,
one-way position, partial-fill, idempotency and crash/restart reconciliation
experience. No credentials, account data, paid work or deployment is authorized.

Acceptance requires evidence that the replay never duplicates an event ID,
never treats unknown positions/free margin as safe, never calls protection
confirmed before two matching child receipts, never resubmits after ambiguity,
and never settles an exit until sibling state is terminal. The reviewer must
identify any unprotected exposure window and may not waive P06/P09 gates.

Reproduce with `python -m unittest tests/test_p10_execution_adapters.py -v`.
The fixtures prove code behavior only; native venue persistence/OCO and real
acceptance remain `VENUE_UNVERIFIED`.
