# DAIINAS P0 v4.6 — Issue #15 implementation evidence

**Tested source:** [`b428a8b7702c60b65053d6b4d80d92249866ad05`](https://github.com/rzalags-maker/DAIINAS-pROJ/commit/b428a8b7702c60b65053d6b4d80d92249866ad05), existing `feature/v4-ladder-integration` branch. Owner instructions through `b76f9f2` were incorporated, including the WIN-gated single-runtime contract and Model A-only confirmation. No stable merge or PR #7/#9 merge.

**Result: implemented account boundary, current-account sizing and durable unified capital transitions. Actual authenticated KuCoin connection remains NOT_CONNECTED.** This is not completion of Issue #14's independently hosted 24-hour acceptance.

## Changes

- `daiinas/account_capital.py`: strict typed complete Classic Futures snapshot; exact Decimal cash/equity/margin/exposure validation; MOCK/not-connected adapter boundary; deterministic cash/campaign deduplication, net cost attribution, quarantined external flows, stale/disconnect/identity/provenance/discrepancy blocks and risk controls.
- `portfolio_paper.py`: current reconciled account drives scan capital, per-entry/re-fill margin, 1–2x isolated leverage, entry-price stop, full-cost risk and campaign net target. **One durable `state.ladder`**, not a second allocator/account/worker. Paper diagnostic cash cannot be relabeled as actual exchange earnings.
- Early bootstrap: unique fully closed positive-net campaigns earn candidate permissions; partial winning legs, deposits and nonpositive campaigns do not. No new fixed two-position sub-100 cap. Actual lot/margin/risk eligibility is checked per market.
- Same-account reserve activation emits `ACTIVATE_LADDER` once. Model A financial rungs/reverse/scaling remain; falling from 100 to 99.99 does not re-bootstrap. Reserve reclassification is drawdown-neutral. Genuine 6% active loss still latches HALT through later profits.
- Existing `Pipeline`/journal/single SQLite writer commits snapshot, cash event, campaign WIN, ladder, audit and cursor together. Polling failure/staleness stops new entries, preserves exposure and public monitoring. Actual positions/orders are pinned and consume capacity; unknown/unprotected exposure blocks.
- Existing `INITIAL_FUNDING`, immutable audit, startup SIGKILL, SQLite replay/backup, original 8-USDT regression and historical public research profiles are preserved. Funding now can originate directly from an explicit validated MOCK Futures snapshot, with equity and initially usable margin recorded separately.

## Executed checks

[GitHub Actions run 41270428566](https://github.com/rzalags-maker/DAIINAS-pROJ/actions/runs/41270428566) **SUCCESS**, exact tested source above:

| Python | Result | Evidence |
| --- | --- | --- |
| 3.11 | SUCCESS | [job](https://github.com/rzalags-maker/DAIINAS-pROJ/actions/runs/41270428566/job/124741900337) |
| 3.12 | SUCCESS | [job](https://github.com/rzalags-maker/DAIINAS-pROJ/actions/runs/41270428566/job/124741900077) |
| 3.13 | SUCCESS | [job](https://github.com/rzalags-maker/DAIINAS-pROJ/actions/runs/41270428566/job/124741900278) |

Full discovery executes **271 tests: 251 preserved + 20 new account tests**. The workflow also runs the bounded account proof and uploads each Python version's test log and `status.json` artifact. Local Python 3.12.14 and 3.13.5 full runs both independently reported **271 tests, OK**; log digests are in the JSON report.

```sh
python -m unittest discover -s tests -v
python scripts/verify_v46_account.py --output-dir /tmp/daiinas-v46-proof
```

The driver requires a fresh directory. It preserves source/PAPER/replay SQLite files and produces a machine-readable report with tested revision, code checksums, snapshot digests and opening provenance. The committed [JSON evidence](V46_ACCOUNT_VALIDATION.json) includes those outputs plus 18 executed opening/transition scenarios.

## Exact bounded account-loop proof — synthetic, not trading performance

**All account values below are deterministic MOCK observations. No authenticated account or real strategy returns were measured.** Each quoted net event already includes its fixture's 0.01 fee; it is not an engine profitability result.

| Cycle | Current Futures equity | Free margin | ACTIVE | RESERVE | PENDING |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 450.00 | 450 | 300 | 150 | 0 |
| 1 | 450.50 | 400 | 300 | 150 | 0.50 |
| 2 | 450.30 | 300 | 299.80 | 150 | 0.50 |
| 3 | 451.30 | 250 | 300 | 150 | 1.30 |
| 4 | 451.20 | 200 | 299.90 | 150 | 1.30 |
| 5 | 451.25 | 150 | 299.95 | 150 | 1.30 |

Five process reopenings, duplicate delivery and full independent source replay preserve the identical report, **one** historical INITIAL_FUNDING=450 and five distinct finalized campaign IDs. Synthetic net cash change is +1.25, synthetic attributed fees 0.05; **the bounded proof itself executed zero market-strategy paper trades**. Separate integration tests exercise paper LONG/SHORT entries, exits, fees and concurrent positions. Neither result establishes profitability.

Other executed acceptance cases:

| Case | Verified deterministic outcome |
| --- | --- |
| 60 → 60.50 → 61 | Earned candidate permissions 1 → 2 → 3; no fabricated 25-unit capital increments; replay cannot earn another WIN |
| Positive partial leg +2, remaining leg −3 | No WIN; whole campaign net −1 accounted once |
| 99.50 → 100 | Same account activates Model A R50/A50/2 once; earlier >2 paper legs remain tracked with controlled exit requests |
| 100 → 99.99 | EXPAND remains activated, R50/A49.99; no reserve release/reset |
| Opening 200 / 300 | Model A R50/A150/6 and R50/A250/10, explicitly different from rejected constant-50/50 B |
| 300 → 350 → 400 | R50/A250 → R100/A250 → R100/A300, ten slots maximum |
| 300 → 260 → 274 → 275 → 300 | ACTIVE 250 → 210 → 224 → 225 → 250; funded ceilings 10 → 8 → 8 → 9 → 10; genuine drawdown HALT stays latched |
| 60 plus settled external +100 | Current Futures equity 160; ACTIVE 60; unallocated external 100; no profit WIN or automatic activation |
| Free margin reduced below min lot | Size down or NO_TRADE despite unchanged equity; exchange-held margin is not subtracted twice from already-net free margin |
| Unknown/manual or unprotected exposure, stale/missing/conflicting snapshots | New entries blocked; existing local risk remains monitored/pinned; no invented closing price |
| 2/3/5/10 concurrent paper positions | Shared-account margin, risk, fees, positions and restart invariants pass |
| SIGKILL inside reconciliation; SIGKILL after WIN commit before next scan | Atomic rollback/replay or committed recovery respectively; no second funding, net debit, WIN or permission |

The opening matrix also executes 17/60/99.99/100/175/200/300/350/400/450/500/1000/5000. No new account uses an implicit default or caps opening capital at 100/300. Funding wallet/MetaMask are outside the accepted snapshot schema; they cannot inflate Futures funds. UTA is explicitly unsupported rather than double-counted.

## Concurrent next-stage specification

After the tested v4.6 source was pushed, owner documentation commits `5262d40` /
`27c8c6e` introduced the **v4.7** adaptive 1–5x research specification. Those
commits were preserved. This delivery implements the requested **v4.6 Issue #15**
and retains its expressly requested v4.5 isolated 1–2x execution policy. A 1–5x
selector, expanded forecasting/selection and protection-conveyor acceptance are
not implemented or claimed by this report; they are additional v4.7 work. No
risk limit was widened while reconciling documentation updates.

## Remaining authenticated KuCoin and hosting gates

1. Authorized persistent host, durable storage/backup/supervision and secure owner control channel. Codex/GitHub CI is not a 24/7 runtime; no deployed START ACK or 24h claim is made.
2. Separately authorized General-only read-only transport with host secret management, actual account/scope discovery, signature/transport validation and API permission tests. No credentials or private calls were used here.
3. Real Classic Futures field mapping, isolated 1–2x/protection semantics, fee/funding/fill history, pagination and private WS/REST reconciliation, gaps/timeouts/ownership recovery. The existing #12 `ExchangeMirror` remains the adapter coordination contract; its older branch was not merged over the audited engine.
4. UTA collateral normalization and borrowed opening-equity semantics are unsupported until verified. Deposits remain unallocated until a separately approved `ALLOCATE_EXTERNAL_FUNDING` policy exists; withdrawing allocated/protected money blocks for reconciliation.
5. Actual account-connected paper acceptance and independent 24h hosted evidence; market economic validation remains separate. No live order transport, transfers, wallet operation or guaranteed target return.

## Actual public-market regression — completed separately

[Run 41270428562](https://github.com/rzalags-maker/DAIINAS-pROJ/actions/runs/41270428562)
**SUCCESS**, all eleven required outcomes successful on the exact same source.
It independently recorded **271 tests, zero failures/errors/skips**. Immutable
source reports are preserved under `reports/v4-runs/41270428562/`, including
raw-source/backup digests; the JSON above links their checksums.

The public adaptive research capture covered **230.283 seconds**, **102,083 journal
records**: 237 actual trade prints, 97,094 L2 updates and 4,425 ticker updates.
First process, renewal/reconnect, second-process restart, independent replay,
cash/reserve reconciliation and backups passed. There were 799 rejected
rule-version-mismatch events; they were rejected rather than used for fills.
This was a public feed with explicitly hypothetical research capital, **not an
authenticated account test**.

All 12 historical 8/60/100 M0–M3 research profiles produced **zero closed trades,
zero net P&L/costs/drawdown and unchanged balances**. This supplies no positive
expectancy, hedge edge or multiday out-of-sample evidence.

The separate **legacy 8-USDT** public smoke was not profitable: four closed losing
paper trades, realized net **−0.01982871853311789 USDT**; total modeled fees
**0.0140774136**, carry **0.00000035933311762500005**, cash **7.978606227066882**.
One SHORT paper position remained open with an unresolved stale mark at the end;
marked equity **7.975272050107009** is indicative, not an executable final flat
balance. Recorded maximum drawdown was **0.32665946677400415%**. This remaining
simulated risk was preserved in restart/replay, not fictitiously closed.
Infrastructure integrity SUCCESS is not trading-profit or production-readiness
acceptance. Actual Futures account remains NOT_CONNECTED.

## Review delivery

Code is pushed to the existing feature branch. A reviewable [draft description](V46_DRAFT_PR.md) is included. Repository policy previously returned **403: “GitHub Actions is not permitted to create or approve pull requests.”** This preserved blocker was not retried without an owner settings change; no new Draft PR is falsely claimed. [Review comparison](https://github.com/rzalags-maker/DAIINAS-pROJ/compare/feature/v33-risk-acceptance...feature/v4-ladder-integration). No merge performed.
