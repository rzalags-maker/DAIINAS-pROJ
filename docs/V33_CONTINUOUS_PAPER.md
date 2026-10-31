# DAIINAS v3.3 — Continuous Dynamic Paper Engine (#6)

**LIVE ORDERS DISABLED.** This is an experimental paper system, not established
alpha or a live-exchange execution service. Development baseline: `8587154e`.
Changes belong to `feature/v33-continuous-paper`, for review against `daiinas-v1`.
The five-pair v2 candle paper worker, its checkpoint, v3.2 one-scan research,
Binance archives, and previous results remain intact and separate.

## Architecture and decision-time contract

1. `continuous_stream.py` subclasses the existing public `Observer`, reusing its
   contract decoder, public execution/ticker normalization and L2 sequence checks.
2. Public contract/all-ticker scans run on a bounded cadence. The existing rank,
   dwell and hysteresis selector runs on the **single ledger writer thread** with
   current position/pending/exit pins, eliminating a scan-versus-fill pin race.
3. Selected 3–8 markets are reconciled with explicit per-topic ACKs in the same
   socket. New markets are snapshot-bridged before use; retired topics are removed
   only after checking current pins again. Pins can exceed the soft watchlist
   capacity (up to the provider hard budget); new entries are then blocked.
4. Full public snapshots, raw/normalized market frames, local clock/health events
   and operator commands enter `continuous_store.py`'s append-only source journal.
   Stable event IDs reject conflicting duplicates. Full canonical metadata and
   all-ticker snapshots plus SHA-256 hashes are retained as scan provenance.
5. `continuous_paper.py` processes this exact journal into a dedicated SQLite
   account with one 8 USDT starting balance and initially one position/pending
   entry at a time. It reuses `shadow_flow.observe`, `paper_micro.size_for_quote`,
   `finish_position`, and the adaptive controller's deposit-adjusted peak/HALT.
6. A single writer executor commits public inputs before applying account state.
   Fills, fees, carry, audit actions, input cursor and checkpoint commit in one
   paper transaction. A crash after the source commit is recovered by replay;
   a crash inside the paper transaction rolls the entire transition back.

**Authoritative action time is journal publication/availability time plus journal
sequence**, not exchange event time. Network receipt and provider timestamps are
retained independently. A frame waiting in a queue is not retroactively moved
before an already-published scan. Quotes must be fresh at decision availability,
and a modeled fill also requires an actual quote observed after the signal/exit
request plus configured latency. Disk/queue delay cannot turn a cached earlier
quote into a later fill. Equal millisecond timestamps use the source sequence as
a deterministic tie breaker. Replay does not consult the wall clock or newest
metadata. Every decision uses only the scan/specification available at that step.

## Entry, exit and account behavior

- Shadow pressure remains an **unvalidated paper hypothesis**. Eligibility is
  only an observation filter. No forced signal, profit or trade-count target.
- A deduplicated signal waits for a later observed quote, TTL, fresh verified book,
  aligned best bid/ask, enough actually displayed best-level liquidity, exact
  multiplier/lot/tick, source taker fee, drift/spread, net modeled target and risk.
- Margin is at most 80% of the shared account. Planned risk at 8 USDT is at most
  0.25% (0.02 USDT), halves after 3% drawdown, and latches HALT at 6%. Gaps can
  exceed planned risk. Leverage is never increased to force an executable lot.
- The controller's peak, HALT and money state are persisted atomically. Simulated
  external capital flows are distinct from trading P&L and do not release HALT.
  A reviewed reset requires a note, a flat account and positive equity; it creates
  an audited new reviewed peak. Historical maximum drawdown remains recorded.
- Stop has priority over target. Target, timeout, opposite pressure, spread/depth
  deterioration and stale-data conditions create exit requests. **Only a later
  valid quote can fill.** No price is invented at EOF, restart, scan or outage.
- Insufficient full displayed depth leaves an `UNRESOLVED` position and pending
  exit. Partial/deeper-book fills are deliberately unsupported, never fabricated.
  Adverse observed gaps fill at the later bid/ask plus modeled slippage/tick cost,
  not at the planned stop. Carry is an explicit elapsed-time model, not verified
  exchange funding. Entry and exit fees are charged once.
- Transient book recovery freezes new fills and records unresolved protection;
  a short gap need not close a position. Persistent stale data requests a later
  executable exit. Old-session frames cannot restore trust after reconnect.
- Open/pending/exit symbols remain pinned after losing shortlist eligibility.
  Delisted/unavailable or structurally changed contracts remain unresolved; old
  multipliers are never silently reinterpreted into a made-up closing trade.
- Metadata older than the bounded as-of limit blocks fills. A rejected scan
  preserves the prior timeline and subscriptions and retries with backoff.

## Run and inspect

Linux, Python 3.11+, existing checkout, no worktree needed:

```bash
python -m pip install '.[live]'
python -m unittest discover -s tests -v
python -m daiinas.continuous run --config configs/continuous.json \
  --source-db state/v33-source.sqlite3 --paper-db state/v33-paper.sqlite3 \
  --report reports/v33-last-run.json
python -m daiinas.continuous status
python -m daiinas.continuous stop
python -m daiinas.continuous resume
python -m daiinas.continuous reset-halt --review-note 'Reviewed incident and flat account'
```

The default paths are new v3.3 files. Unknown/legacy database roles, identical
source/paper paths or changed financial-policy identities are rejected. The source
and account each have an exclusive worker lock. `stop` pauses **new entries**;
quotes, pins and protective exits continue. Commands enter the durable source
journal and are applied by the worker (normally within a clock tick), or at next
startup if stopped. Inspect status to confirm application. SIGTERM stops collection
with account state retained; it does not close positions at a fictitious quote.

Health reports checkpoint age, source backlog, feed ages, book verification,
reconnects, pending exits, unresolved risk, cash/mark status and storage capacity.
A stopped process is not healthy just because its old checkpoint exists. Stale
mark-to-market is labeled unresolved; cash is not presented as current equity.

## Deterministic replay and backups

```bash
python -m daiinas.continuous replay --source-db state/v33-source.sqlite3 \
  --paper-db state/v33-replay.sqlite3 --report reports/v33-replay.json
python -m daiinas.continuous backup --destination backups/v33-001
python -m daiinas.continuous verify-backup --destination backups/v33-001
```

Replaying the same journal again verifies old hashes and does not duplicate
signals, fees, fills or P&L. A replica uses the same source UUID and policy. The
backup copies PAPER first and append-only SOURCE second, so the source can be
ahead of the money checkpoint but cannot be behind it. Both use SQLite's online
backup API, `integrity_check`, role/source checks and file checksums. Never copy
only the main file of an active WAL database. Stop the service before restoring
both files from a verified backup, preserve filenames/config and file ownership,
and restart; committed but unapplied source events will be recovered once.

Source retention is lossless and explicit, not deletion of financial evidence:

```bash
# Stop the OS service first; operator stop above only pauses new entries.
python -m daiinas.continuous archive-source --destination archives/v33-through-N
python -m daiinas.continuous replay --source-archive archives/v33-through-N/source.sqlite3 \
  --source-db state/v33-source.sqlite3 --paper-db state/full-replay.sqlite3
```

Archiving requires exclusive stopped-worker locks and a caught-up checkpoint,
creates a verified full backup, then atomically starts a new source segment with
the same identity and continuing sequence. Positions/cash stay in the paper DB.
Keep **all** source segments for a complete replay. A missing prefix fails closed.
Paper audit/deduplication history is not silently pruned. Configured hard ceilings
(default 64 GiB per active DB and 1 GiB free-space reserve) stop collection with
retained unresolved risk before storage exhaustion; archival/capacity intervention
is required. Offload archives off-host under a reviewed retention policy. No
unsupported automatic audit compaction is claimed. Size disk capacity from the
measured event rate before the 24-hour host acceptance run.

## Independent Linux hosting

`deploy/daiinas-v33.service` and health service/timer are separate from the old
five-pair units. Provision a dedicated `daiinas` user, persistent local storage,
`/opt/daiinas` checkout and `.venv` with the optional live dependency. Units use
`/var/lib/daiinas-v33`; source and paper files must be owned only by that user.
Review Python/checkout paths, disk ceilings, network proxy and trusted CA setup.
Public destinations are `api-futures.kucoin.com` and the public ticket's encrypted
KuCoin Futures WSS instance. No API secret values or private endpoint access.

Install/enable the three v3.3 units after reviewing the host setup. Use journald
and the health unit's nonzero status for host monitoring/alerting. Back up off-host
and rehearse recovery. After creating the dedicated user and the venv, install the units on that host:

```bash
sudo install -m 644 deploy/daiinas-v33.service deploy/daiinas-v33-health.service deploy/daiinas-v33-health.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now daiinas-v33.service daiinas-v33-health.timer
sudo journalctl -u daiinas-v33.service
```

Use explicit `/var/lib/daiinas-v33/...` database arguments for CLI controls on
that host, matching the unit, rather than the development `state/...` defaults.
Static unit syntax was checked with the local interpreter path substituted;
the actual `/opt/daiinas/.venv` runtime remains a host provisioning step.

No server was provisioned or independently deployed by
this code change, and no alerts are sent externally by the application.

## Acceptance/evidence gates

- Existing tests are preserved. New fixtures explicitly label synthetic input;
  they cover multi-scan as-of rules, minimum lots, both sides, ACK failure,
  in-session rotation/pins, gaps, stale/future data, late cached quotes, unsupported
  partial depth, adverse gaps, TTL, fees/carry, actual SIGKILL between fill/checkpoint,
  source-before-ledger crash, deterministic replay, backup and archive restore.
- The bounded GitHub Actions public-data smoke records independent source and paper
  files, snapshots, source hashes, ledger reports, a second process restart and a
  full offline replay comparison. **Zero paper trades is a valid safe outcome.**
- The real 24-hour independent-host gate is **BLOCKED — HOST NOT PROVISIONED**.
  A bounded Actions job is not a 24-hour hosting result. Once a host exists, retain
  at least 24 hours of logs, genuine scans/rotations, a forced socket renewal and
  process restart, pins, ledger uniqueness, resource/health and backup evidence.
- Multi-day forward/out-of-sample performance remains a later gate. Neither
  infrastructure success nor modeled positive target P&L establishes profitability.

Review through the focused feature PR. Do not merge before tests and short real
public-data verification pass; leave unverified host/performance gates open.
