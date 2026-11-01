# v3.3 independent host acceptance — issue #8

**LIVE ORDERS DISABLED. 24h gate: BLOCKED — HOST NOT PROVISIONED.**
This kit is prepared, not deployed. Codex and bounded GitHub Actions are not the
independent host. No cloud purchase, remote server access or exchange credentials
are authorized by this document. An identified persistent host and explicit owner
hosting authorization are prerequisites.

## Prerequisites and budget

- Ubuntu 24.04 LTS or another supported Linux with systemd, Python 3.11–3.13,
  venv, git, CA certificates, NTP/chrony, SSH administrative access and journald.
- Starting planning allocation: 2 vCPU, 2 GiB RAM, persistent local SSD with
  at least 100 GiB for an initial nominal-rate rehearsal. This is a planning
  floor, not a load-test result or adequate capacity for every scenario.
  Size storage from the capture estimates in `reports/v33-risk-audit.json`.
  Budget active source + paper + WAL headroom + retained archives + two complete
  backups + logs; double for local recovery work, plus a separate off-host copy.
  If the measured 5x envelope exceeds this allocation, enlarge before the soak.
- An unprivileged `daiinas` user, state owner `daiinas:daiinas`, directories 0700,
  files 0600/umask 0077, no credentials in environment files or units.
- Outbound TLS-verified HTTPS to public KuCoin REST and WSS to the host returned
  by `/api/v1/bullet-public`. Preserve provider heartbeat/renewal settings.
  No inbound application port is required. Restrict administrative SSH.
- Confirm system clock synchronization, free disk/inodes, memory and backup space.
  The two default active-DB ceilings are **64 GiB each**, with a **1 GiB free-space
  reserve**. These ceilings are stop controls, not a retention policy or a
  guarantee against sudden filesystem exhaustion. Never delete WAL files online.
- Recurring price requires an actual regional provider quote. The audit workflow
  captures the official [AWS Lightsail pricing page](https://aws.amazon.com/lightsail/pricing/)
  into `reports/v33-host-pricing.json` where reachable, with retrieval time/hash.
  No host was purchased. Do not present a compute-only example as a full bill:
  add SSD expansion, off-host backups, transfer, taxes and monitoring. If pricing
  retrieval fails, recurring cost is **NOT VERIFIED**, not an invented estimate.

## Measured capacity and sourced recurring-cost example

The original source file was **86,556,672 bytes** over **229.749 seconds**:
about **376,744 bytes/s**, **32.55 GB/day (30.32 GiB/day)** at that same rate.
The journal had 41,668 MARKET events (about 181.36/s), including the observed
32,244 L2, 9,275 ticker and 149 execution events. A simple 5x burst planning
envelope is **162.75 GB/day (151.58 GiB/day)**; neither number is a measured
24-hour result. This is source-file growth only: paper DB, WAL write amplification,
archives, full backups and filesystem headroom add to it. Peak RSS/CPU and paper
write rate still require measurement on the chosen host.

The default 64 GiB SOURCE ceiling would be reached in roughly **50.7 hours** at
the nominal rate, or **10.1 hours** at 5x. Buying a larger disk does not change this
configured ceiling. At the higher rate, an uninterrupted 24h acceptance is not
possible with the default cap: pause safely and archive offline (recording the
interruption), or separately review a capacity/config change before the run.
Do not turn off the capacity guard to make the soak pass. Two retained backups
near both 64-GiB ceilings plus the active pair require about 384 GiB before WAL,
logs and headroom; plan **>=500 GiB** for that worst-case local retention layout,
or use a reviewed lower active footprint and off-host retention policy.

The official AWS Lightsail page captured on **2026-10-31 23:35 UTC** lists a
**$12 USD/month** Linux example with **2 vCPUs, 2 GB RAM, 60 GB SSD, 3 TB transfer**.
Source URL, exact excerpts and page SHA-256 are committed in
[`v33-host-pricing.json`](../reports/v33-host-pricing.json). That 60-GB disk does
**not** satisfy the above local retention budget. A source-backed recurring
compute-only floor is therefore $12/month, **plus unquoted additional SSD,
off-host backup, excess transfer and tax**. This is not an all-in deployment
quote; select region/network plan and obtain the required larger-storage quote
before purchase. No billable resource was provisioned.

## Release installation on an explicitly authorized NEW host

Keep immutable code releases separate from the existing mutable financial state.
Choose the reviewed audit commit from `reports/V33_RISK_AUDIT.md`, never an
unreviewed moving branch. The commands below are an operator procedure; they
were not executed against a server by this change.

```bash
# Administrative setup, once on a NEW host:
sudo useradd --system --home /var/lib/daiinas-v33 --shell /usr/sbin/nologin daiinas
sudo install -d -o root -g root -m 755 /opt/daiinas-releases
sudo install -d -o daiinas -g daiinas -m 700 /var/lib/daiinas-v33
# Set to the exact reviewed commit, not the literal example:
DAIINAS_REV=REPLACE_WITH_REVIEWED_COMMIT
git clone https://github.com/rzalags-maker/DAIINAS-pROJ.git /tmp/daiinas-release
git -C /tmp/daiinas-release checkout --detach "$DAIINAS_REV"
sudo cp -a /tmp/daiinas-release "/opt/daiinas-releases/$DAIINAS_REV"
sudo python3 -m venv "/opt/daiinas-releases/$DAIINAS_REV/.venv"
sudo "/opt/daiinas-releases/$DAIINAS_REV/.venv/bin/python" -m pip install "/opt/daiinas-releases/$DAIINAS_REV[live]"
sudo ln -s "/opt/daiinas-releases/$DAIINAS_REV" /opt/daiinas
cd /opt/daiinas
sudo install -m 644 deploy/daiinas-v33.service deploy/daiinas-v33-health.service deploy/daiinas-v33-health.timer deploy/daiinas-v33-sample.service deploy/daiinas-v33-sample.timer /etc/systemd/system/
sudo systemd-analyze verify /etc/systemd/system/daiinas-v33*.service /etc/systemd/system/daiinas-v33*.timer
sudo systemctl daemon-reload
sudo systemctl enable --now daiinas-v33.service daiinas-v33-health.timer daiinas-v33-sample.timer
```

Do not run these setup commands over an existing installation. Test pip/venv
permissions and the exact Python version, check dependency pinning
(`websockets==16.0`), archive the release SHA and config hash. No destructive or
automatic database migration is included. All five unit/timer templates passed
local `systemd-analyze verify` with the existing local interpreter substituted;
this is syntax validation, not evidence that `/opt/daiinas/.venv` exists on a host. Old v1/five-pair databases are separate.

Before beginning the clock, run a short real public-only session and inspect
actual ACKs, verified snapshots/sequence bridges, scans, source/paper identities,
contract lots, cash, latest quote ages and control state. NO_TRADE is valid.
Do not force a signal to satisfy the checklist.

## Operational controls and evidence capture

All commands on this host must use the same absolute database paths as the unit:

```bash
cd /opt/daiinas
sudo -u daiinas .venv/bin/python -m daiinas.continuous status --source-db /var/lib/daiinas-v33/source.sqlite3 --paper-db /var/lib/daiinas-v33/paper.sqlite3
sudo -u daiinas .venv/bin/python -m daiinas.continuous stop --source-db /var/lib/daiinas-v33/source.sqlite3 --paper-db /var/lib/daiinas-v33/paper.sqlite3
# stop above PAUSES NEW ENTRIES; public collection, pins and exits continue.
sudo -u daiinas .venv/bin/python -m daiinas.continuous resume --source-db /var/lib/daiinas-v33/source.sqlite3 --paper-db /var/lib/daiinas-v33/paper.sqlite3
sudo systemctl status daiinas-v33.service daiinas-v33-health.timer daiinas-v33-sample.timer
sudo journalctl -u daiinas-v33.service -u daiinas-v33-health.service --since today
```

`systemctl stop daiinas-v33.service` stops the process without fictitious closing
fills. Live risk becomes unresolved until observations resume. `systemctl restart`
recovers the same account; it must not create a fresh 8-USDT account. HALT is
latched; reset only after incident review, a flat account and an explicit note.
Capital-flow controls change **simulated** capital only and are excluded from P&L.
Do not add the owner's real balance to this ledger.

The sample timer writes fsynced 0600 JSONL health observations every 60 seconds to
`/var/lib/daiinas-v33/evidence/health.jsonl`. Samples contain source identity,
process/system boot IDs, cursor/digest, cash/mark status, pins, feed age, storage,
checkpoint lag and integrity. A missing/failing probe must alert the operator.
Monitor the timer itself using an independent host monitor. The existing health
unit exits nonzero on stale/unverified feeds; journald is a local signal, not
external alert delivery. Configure an operator-controlled systemd `OnFailure=`
hook or monitoring agent and test delivery; no messages or webhooks are sent by
this code. Capture alert proof, log rate limits and disk use without logging URLs
containing public session tokens. Bound journald retention on the host (for
example 256 MiB after reviewing other services' requirements).

## WAL-safe backup, restore and source retention rehearsal

Use a NEW destination each time. At least before fault rehearsal and at the end:

```bash
sudo -u daiinas /opt/daiinas/.venv/bin/python -m daiinas.continuous backup --source-db /var/lib/daiinas-v33/source.sqlite3 --paper-db /var/lib/daiinas-v33/paper.sqlite3 --destination /var/lib/daiinas-v33/backups/REPLACE_WITH_UNIQUE_ID
sudo -u daiinas /opt/daiinas/.venv/bin/python -m daiinas.continuous verify-backup --destination /var/lib/daiinas-v33/backups/REPLACE_WITH_UNIQUE_ID
```

Online backup copies PAPER before append-only SOURCE, holds a shared maintenance
lock against source replacement, validates source/account identity and integrity,
and records checksums. A failed/interrupted backup has no valid manifest; never
restore it. Hashes are integrity/provenance evidence, not signatures.

Copy the verified backup **and all source archives needed for full replay** to
owner-controlled off-host storage; verify hashes at the destination. Do not paste
storage secrets into commands, chats or CI. Prove restore on a separate directory
or spare machine first: run integrity checks, replay into a new replica, compare
cash/fees/cursor/digest, replay twice and confirm no duplicate fills/fees. Never
restore old paper while silently keeping a newer source/account pair or overwrite
an active ledger. For actual rollback stop the service, preserve the failed pair
for analysis, restore both matching files into a new state directory, set ownership,
verify, point the reviewed unit/config to that pair and restart. Document any
lost post-backup observations as unresolved; do not synthesize them.

Source archival is explicit and offline via `archive-source`, using a full verified
backup and continuing source identity/sequence. Keep all segments. Do not schedule
pruning of financial audit or source prefixes before a reviewed retention policy.
Backups consume space too: monitor them, offload verified older copies and check
capacity before every copy; no automatic deletion is provided. SQLITE_FULL fault
fixtures test rollback, but cannot establish power-loss behavior of an unknown SSD.

## Real >=24-hour acceptance procedure

1. Start after short preflight succeeds; preserve release/config hashes, initial
   source/account IDs, initial balance and first sample. Run at least 24 elapsed
   hours on the identified independent persistent host, with <=120-second sample
   gaps and >=99% healthy samples (a gate for this rehearsal, not an uptime SLA).
2. Preserve genuine chronological scans, actual shortlist changes/ACKs and position
   pins. If no position/rotation occurs naturally, mark those operational evidence
   gates untested; synthetic tests do not become real-market evidence.
3. Deliberately renew/reconnect the public socket using a reviewed temporary unit
   override `--renew-seconds 3600`; retain config/provenance. Restart the process at
   least once on the SAME pair. Compare position ID, cash, reserved margin, fees,
   pending exit, source cursor and digest before/after. A process exit/restart is
   distinct from an OS restart; document which was tested.
4. Rehearse a bounded public-feed outage with an operator-reviewed network fault on
   this host only. Preserve stale/sequence responses, blocked stop and later actual
   quote recovery. Do not invent missed stop fills. Avoid changing unrelated host
   routes or permanently disabling networking. Fault injection is not performed here.
5. Capture health/CPU/RSS/disk/WAL/DB rates and restoration times. Check rejected and
   unresolved reasons, ACK/queue gaps, rate limits, stale specs, fee changes, event
   duplication and latched HALT. Stop for corruption or unsupported fills.
6. Take a final online backup after the last sample; prove off-host restore and full
   replay. Preserve logs, SQL audit, raw sources, snapshots, costs, open risks and
   per-position reconciliation. Hash evidence files into a reviewed proof manifest.

Example proof manifest (paths are real host evidence, not example fixture data):

```json
{
  "independent_persistent_host": true,
  "restart": {"path": "/evidence/restart.json", "sha256": "ACTUAL_SHA256", "reviewed": true},
  "forced_reconnect": {"path": "/evidence/reconnect.json", "sha256": "ACTUAL_SHA256", "reviewed": true},
  "sequence_or_stale_fault": {"path": "/evidence/fault.json", "sha256": "ACTUAL_SHA256", "reviewed": true},
  "position_pin": {"path": "/evidence/pin.json", "sha256": "ACTUAL_SHA256", "reviewed": true},
  "ledger_replay": {"path": "/evidence/replay.json", "sha256": "ACTUAL_SHA256", "reviewed": true},
  "off_host_backup_restore": {"path": "/evidence/restore.json", "sha256": "ACTUAL_SHA256", "reviewed": true},
  "resource_budget": {"path": "/evidence/resources.json", "sha256": "ACTUAL_SHA256", "reviewed": true},
  "alert_delivery": {"path": "/evidence/alert.json", "sha256": "ACTUAL_SHA256", "reviewed": true}
}
```

```bash
python -m daiinas.host_acceptance evaluate --samples /var/lib/daiinas-v33/evidence/health.jsonl --backup /var/lib/daiinas-v33/backups/FINAL_UNIQUE_ID --proof /evidence/proof.json
```

The evaluator checks durations, gaps, source identity/cursor, distinct process
boots, integrity, health and evidence hashes. At most it returns
`EVIDENCE_READY_FOR_OWNER_REVIEW`; a hash cannot establish that a claim is true.
Owner review must inspect raw evidence before accepting the soak. This never
validates profitability or authorizes live trading.

## Rollback and remaining gates

A code-only rollback requires a reviewed compatible release and stopped service;
repoint `/opt/daiinas`, retaining mutable state. Do NOT roll back to the pre-audit
runtime on a money-state incident without assessing the fixed SQLITE_FULL and
external-flow defects. If policy identity/schema is incompatible, fail closed and
restore/replay separately; never delete identity/checkpoint to make it start.

Current independent statuses: code/test delivery separately recorded in audit;
**paper-soak-verified=false**, **economically-validated=false**,
**live-account-authorized=false**. Multi-day independent out-of-sample windows,
NO_TRADE and comparable fixed-five baselines, uncertainty intervals and stop-gap
tails remain later gates. PR #7 stays Draft and unmerged.
