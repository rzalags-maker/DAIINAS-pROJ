# DAIINAS v4 — Funded-account bootstrap: replace 8-USDT default for NEW account (P0)

Owner decision, 2026-11-01: The amount 8 USDT is a HISTORICAL v3.3 regression fixture only. It must not be the opening capital for the NEW v4 funded-account engine. A NEW v4 account starts from the amount genuinely available in the selected eligible trading account at the moment of onboarding, verified through a permitted read-only connection, or from an explicitly named USER-SUPPLIED paper scenario. There is no implicit 8, 29, 60 or 100 USDT default.

## Accounts / strict isolation

- LEGACY_V33_PAPER: keep the existing 8-USDT database, codepath, historical results and restart/replay tests unchanged.
- FUNDED_V4_PAPER: new account ID, policy version, distinct database path and funding event. Support any exact Decimal opening amount from a documented source. Do not silently migrate/copy 8 USDT.
- ACTUAL_EXCHANGE_READ_ONLY: separate, authorized KuCoin account-state observation only. Balance snapshots are not trading profits, and there must be no live orders or transfers.
- EXTERNAL_WALLET: MetaMask balances are not KuCoin trading capital. Do not count other wallets toward usable account balance unless a transfer has settled, is legally eligible, and is verified as available in the actual trading scope.

## Sources / actual start conditions

Public market APIs cannot reveal account balances. Actual KuCoin balance has status NOT_CONNECTED until a new authorized read-only API is secured on an approved server. Do not reuse an exposed trading-capable API credential. A user's intended 60 USDT is not proof that 60 is funded. If only 24 USDT is confirmed in KuCoin and 36 in MetaMask, eligible KuCoin trading cash is 24 USDT, not 60 USDT.

The read-only adapter must identify exchange account, account class Spot/Futures/Unified, settlement asset, current free and settled assets, frozen/borrowed/pledged/locked amounts, marked position equity, margin obligations, snapshot ID, timestamp, freshness, and completeness. No transfer or real trading is allowed. Distinguish current free cash from equity and leverage notional.

NEW funded-v4 startup must demand an explicit, typed source: verified_readonly_exchange_snapshot OR owner_confirmed_paper_scenario. The first mode can mirror the verified snapshot into a separate PAPER ledger for comparison. The second is a hypothetical paper scenario, never represented as real capital. Neither can silently select 8 USDT. Missing / stale / partial / conflicting source => BLOCK startup as verified-capital mode; independent paper scenario remains allowed.

At settled eligible capital below 100 USDT, BOOTSTRAP permits at most one candidate slot and no 50/50 reserve allocation. At 100 USDT, allocate protected R50 + A50 with two 25-USDT slots. With validated higher opening capital, use the original v4 absolute capital states: 125=>R50/A75/3, 300=>R50/A250/10, 350=>R100/A250/10, 400=>R100/A300/10. Reserve physical segregation is NOT achieved by naming a database field.

## Financial ledger invariants

Persist initial funding EXACTLY ONCE as an INITIAL_FUNDING event with source/type, account ID, currency, amount, timestamp, source evidence and policy ID in one atomic SQLite transaction. On restart load and reconcile the original event; never re-seed from a new balance snapshot, never duplicate opening funds, never mix legacy and funded account paths. Any conflicting identity/amount => HALT and report.

Later top-ups are EXTERNAL_DEPOSIT events and withdrawals are EXTERNAL_WITHDRAWAL events. Neither is trading profit and neither may automatically clear a HALT. Before owner specifies an explicit external-deposit allocation rule, credit subsequent deposits only into UNALLOCATED_EXTERNAL_FUNDS (not risk-bearing active capital or reserve); do NOT trigger +25 profit-funded slots or +50 alternating net-profit steps. If a later deposit first crosses 100, implement a separate formally approved activation event, not a fake +40 realized trading profit.

Profit ladder applies to SETTLED NET TRADING P&L only. Preserve fee accounting, pending unrealized positions, reverse slot shrinkage, 3%/6% risk halts, reserve non-use, exact Decimal money and deterministic replay. The identity must incorporate opening funding, external flows, realized net P&L, reserve/active/pending, deficit, and any unallocated external funds without double count.

## Required Codex implementation

1. Preserve legacy PaperPolicy initial 8 and its v3.3 constructor guard only under LEGACY_V33_PAPER. Do not change a legacy regression seed globally.
2. Create a separate versioned FUNDED_V4_PAPER bootstrap path with explicit seed source, runtime CLI/config, account identity and transactional opening funding event. No hard-coded 8 fallback. Review continuous.py and continuous_paper.py, which currently reject amounts other than 8.
3. Add a future actual-readonly snapshot interface and validation; until a real connector is authorized, the system may demonstrate correct startup using user-confirmed PAPER amounts clearly labelled hypothetical.
4. Add tests opening separate paper accounts with 29 / 60 / 99.99 / 100 / 125 / 300 / 350 / 400 USDT; multiple restarts, conflicting seed, duplicate credit, deposits not profits, 24+36 separate wallet example, crash halfway through initial transaction and full replay parity.
5. Preserve previous 180+ regression tests; Python 3.11/3.12/3.13; publish evidence that no actual trading or secret access occurred. Never merge stable without owner approval.

Acceptance is NOT satisfied by leaving 8 USDT as the NEW V4 default, or by simply editing displayed dashboard numbers. The v4 paper account must truly start from a verified/provenance-labelled capital value. LIVE ORDERS DISABLED.