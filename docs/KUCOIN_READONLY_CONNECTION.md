# DAIINAS KuCoin General-only authenticated API connection

Current stage: implemented read-only account **probe**. This is not a full Model A
authenticated account reconciler, a trading connection, or permission to send orders.
It never upgrades the existing MOCK FuturesAccountSnapshot to real authenticated
capital. The implementation has no POST, DELETE, order execution or withdrawal route.

## KuCoin owner setup

1. Sign into KuCoin > profile > API Management > Create API (API-Based Trading).
2. Create a separate key named DAIINAS-READONLY and grant only **General**.
3. Do not grant Futures, Spot, Margin, Transfer, Withdrawal or Unified trading permissions.
4. Keep the API KEY, API SECRET and user-created API PASSPHRASE confidential.
5. Put those values into the secure environment where the probe is running.
   Never post credentials in chats, GitHub files, Issues, Actions logs or screenshots.
6. Configure the version matching KuCoin API Management (2 or 3).
7. Run the one-time probe in that trusted, network-enabled environment:

    python -m daiinas.kucoin_readonly --fee-symbol XBTUSDTM

Environment variable **names**:
- KUCOIN_API_KEY
- KUCOIN_API_SECRET
- KUCOIN_API_PASSPHRASE
- KUCOIN_API_KEY_VERSION

Do not upload raw CLI reports containing balances to public GitHub artifacts.

The probe uses the official signed HMAC-SHA256 General-only GET endpoints:
account mode, Classic USDT Futures currency balance, Futures positions, active
orders, stop orders and actual per-instrument maker/taker fees. It does not try
Classic /api/v1/account-overview, because KuCoin documentation requires Futures
permission for that endpoint. General-only account balance is observational:
actual available isolated-margin, full fills/funding history, external positions,
risk and protective order identity still need complete normalization and audit.

Statuses: READ_ONLY_CONNECTED_NOT_RECONCILED, PARTIAL_READ_ONLY,
UNSUPPORTED_UTA and NOT_CONNECTED. UTA is deliberately not implemented.
A complete probe **cannot** activate Model A from real cash and **cannot** submit
live orders. The next separately tested task is account-data normalization and
exact-once reconciliation into the existing v4.7 ledger.

Offline tests: python -m unittest discover -s tests -p test_kucoin_readonly.py -v
