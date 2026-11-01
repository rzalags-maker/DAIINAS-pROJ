"""Read-only persistent-host acceptance evidence. No deployment or exchange orders."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import socket
import time

from .continuous_ops import status,readonly,verify_backup


def sample(source,paper,host_id):
    if not host_id.strip():raise ValueError('Explicit independently provisioned host id required')
    result=status(source,paper)
    with closing(readonly(paper)) as c:
        state=json.loads(c.execute('SELECT payload FROM checkpoint WHERE id=1').fetchone()[0])
        identity=json.loads(c.execute("SELECT value FROM v33_meta WHERE key='identity'").fetchone()[0])
        result.update(source_id=identity['source_id'],counts=state['counts'],pins=sorted({x['symbol'] for x in
            (state['position'],state['pending'],state['exit_request'],*state.get('positions',{}).values(),*state.get('pending_entries',{}).values()) if x}),
            source_cursor=state['cursor'],input_digest=state['input_digest'],
            current_paper_integrity=c.execute('PRAGMA quick_check').fetchone()[0])
    result.update(observed_ms=time.time_ns()//1000000,host_id=host_id,
                  hostname=socket.gethostname(),boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                  strategy_validated=False,production_ready=False)
    return result


def evaluate(samples,manifest,proof):
    if len(samples)<2:raise ValueError('Need multiple actual host samples')
    s=sorted(samples,key=lambda r:r['observed_ms'])
    if any(x['observed_ms']<=s[i-1]['observed_ms'] for i,x in enumerate(s) if i):raise ValueError('Duplicate/regressed sample time')
    healthy_fraction=sum(bool(x['healthy']) for x in s)/len(s)
    checks={
      'at_least_99pct_healthy_samples':healthy_fraction>=.99,
      'independent_host_attested':proof.get('independent_persistent_host') is True,
      'single_host':len({x['host_id'] for x in s})==1 and all(x['host_id'] for x in s),
      'at_least_24h':s[-1]['observed_ms']-s[0]['observed_ms']>=86400000,
      'sample_gaps_bounded':max(b['observed_ms']-a['observed_ms'] for a,b in zip(s,s[1:]))<=120000,
      'no_live_orders':all(x['live_orders_enabled'] is False for x in s),
      'source_advanced':s[-1]['source_cursor']>s[0]['source_cursor'],
      'same_source_identity':bool(s[0].get('source_id')) and len({x.get('source_id') for x in s})==1,
      'no_cursor_regression':all(b['source_cursor']>=a['source_cursor'] for a,b in zip(s,s[1:])),
      'multiple_process_boots':len({x.get('service',{}).get('boot_id') for x in s}-{None})>=2,
      'multiple_scans':s[-1]['counts'].get('SCAN',0)-s[0]['counts'].get('SCAN',0)>=2,
      'integrity':all(x['current_paper_integrity']=='ok' for x in s),
      'closing_health':s[-1]['healthy'] is True,
      'backup_not_behind_last_sample':manifest['paper_cursor']>=s[-1]['source_cursor'],
    }
    # Explicit reviewed evidence files, not a boolean assertion or synthetic test.
    for name in ('restart','forced_reconnect','sequence_or_stale_fault','position_pin',
                 'ledger_replay','off_host_backup_restore','resource_budget','alert_delivery'):
        ref=proof.get(name,{})
        path=Path(ref.get('path','/nonexistent'))
        checks[name]=bool(ref.get('reviewed') is True and path.is_file() and
            hashlib.sha256(path.read_bytes()).hexdigest()==ref.get('sha256'))
    healthy_fraction=sum(bool(x['healthy']) for x in s)/len(s)
    return {'24h_host_gate':'EVIDENCE_READY_FOR_OWNER_REVIEW' if all(checks.values()) else 'NOT_VERIFIED',
        'checks':checks,'sample_count':len(s),'healthy_fraction':healthy_fraction,
        'unhealthy_samples':sum(not x['healthy'] for x in s),
        'duration_seconds':(s[-1]['observed_ms']-s[0]['observed_ms'])/1000,
        'live_orders_enabled':False,'production_ready':False,'strategy_validated':False,
        'note':'Evidence hashes establish identity, not truth; owner review required. No automatic live authorization.'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['sample','evaluate'])
    p.add_argument('--source-db',type=Path,default=Path('/var/lib/daiinas-v33/source.sqlite3'))
    p.add_argument('--paper-db',type=Path,default=Path('/var/lib/daiinas-v33/paper.sqlite3'))
    p.add_argument('--host-id',default='');p.add_argument('--samples',type=Path,required=True)
    p.add_argument('--backup',type=Path);p.add_argument('--proof',type=Path)
    a=p.parse_args()
    if a.command=='sample':
        r=sample(a.source_db,a.paper_db,a.host_id)
        a.samples.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(a.samples,os.O_WRONLY|os.O_APPEND|os.O_CREAT,0o600)
        with os.fdopen(fd,'a') as f:f.write(json.dumps(r,sort_keys=True)+'\n');f.flush();os.fsync(f.fileno())
    else:
        if not a.backup or not a.proof:p.error('Verified backup and reviewed proof manifest required')
        r=evaluate([json.loads(x) for x in a.samples.read_text().splitlines() if x],
                   verify_backup(a.backup),json.loads(a.proof.read_text()))
        print(json.dumps(r,indent=2))
        return 0 if r['24h_host_gate']=='EVIDENCE_READY_FOR_OWNER_REVIEW' else 1
    return 0

if __name__=='__main__':raise SystemExit(main())
