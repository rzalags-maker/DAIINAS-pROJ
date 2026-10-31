"""WAL-safe two-file backup, immutable source segments, and read-only status."""
from contextlib import contextmanager,closing
from pathlib import Path
import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
import time
from uuid import uuid4

from .continuous_store import SourceJournal,canonical
from .service import single_worker


def file_digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def readonly(path):
    return sqlite3.connect(f'file:{Path(path).resolve()}?mode=ro',uri=True,timeout=5)


def state_at(path):
    with closing(readonly(path)) as c:
        owner=c.execute("SELECT value FROM v33_meta WHERE key='owner'").fetchone()
        if not owner or owner[0]!='v33-paper-ledger':raise ValueError('Not a v3.3 paper ledger')
        row=c.execute('SELECT payload FROM checkpoint WHERE id=1').fetchone()
        return json.loads(row[0]) if row else None


def status(source_path,paper_path):
    state=state_at(paper_path)
    if state is None:return {'healthy':False,'reason':'No committed checkpoint','live_orders_enabled':False}
    with closing(readonly(source_path)) as c:
        seq=c.execute('SELECT COALESCE(MAX(seq),0) FROM journal').fetchone()[0]
        base=c.execute("SELECT value FROM v33_meta WHERE key='segment_base'").fetchone()
        seq=max(seq,int(base[0]) if base else 0)
    now=time.time_ns()//1_000_000;service=state.get('service',{})
    age=now-state['now_ms'];pos=state['position']
    active=service.get('active',[]);verified=service.get('verified_books',[])
    healthy=(0<=age<15000 and seq==state['cursor'] and service.get('connected',False) and state.get('connected',False)
             and set(active)<=set(verified) and not (pos and pos.get('unresolved')))
    return {'healthy':healthy,'live_orders_enabled':False,'checkpoint_age_ms':age,
            'unprocessed_records':seq-state['cursor'],'paused_new_entries':state['paused'],
            'halted':state['halted'],'cash':state['cash'],'equity_last_mark':state['last_equity'],
            'mark_status':state['mark_status'],'open_position':pos,'pending_entry':state['pending'],
            'pending_exit':state['exit_request'],'service':service,
            'disk_free_bytes':shutil.disk_usage(Path(source_path).parent).free,
            'source_bytes':file_bytes(source_path),'paper_bytes':file_bytes(paper_path)}


def file_bytes(path):
    return sum(p.stat().st_size for p in [Path(path),Path(str(path)+'-wal'),Path(str(path)+'-shm')] if p.exists())


@contextmanager
def source_maintenance(path,exclusive=False):
    with open(str(path)+'.maintenance.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:yield
        finally:fcntl.flock(lock,fcntl.LOCK_UN)


def backup_pair(source,paper,destination):
    """Copy PAPER first, SOURCE second. Append-only source can be ahead, never behind."""
    dest=Path(destination)
    if dest.exists():raise ValueError('Backup destination must be new; never overwrite evidence')
    dest.mkdir(parents=True)
    for src,name in [(paper,'paper.sqlite3'),(source,'source.sqlite3')]:
        a=readonly(src);b=sqlite3.connect(dest/name)
        try:a.backup(b)
        finally:b.close();a.close()
    p=readonly(dest/'paper.sqlite3');s=readonly(dest/'source.sqlite3')
    try:
        for c in (p,s):
            if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Backup integrity failed')
        row=p.execute('SELECT payload FROM checkpoint WHERE id=1').fetchone()
        state=json.loads(row[0]) if row else {'cursor':0,'input_digest':''}
        source_id=s.execute("SELECT value FROM v33_meta WHERE key='source_id'").fetchone()[0]
        identity=json.loads(p.execute("SELECT value FROM v33_meta WHERE key='identity'").fetchone()[0])
        if identity['source_id']!=source_id:raise ValueError('Backup source/account mismatch')
        max_seq=s.execute('SELECT COALESCE(MAX(seq),0) FROM journal').fetchone()[0]
        base=s.execute("SELECT value FROM v33_meta WHERE key='segment_base'").fetchone()
        max_seq=max(max_seq,int(base[0]) if base else 0)
        if max_seq<state['cursor']:raise ValueError('Source backup is behind paper checkpoint')
    finally:p.close();s.close()
    manifest={'source_id':source_id,'paper_cursor':state['cursor'],'source_max_seq':max_seq,
              'paper_input_digest':state['input_digest'],
              'sha256':{name:file_digest(dest/name) for name in ('source.sqlite3','paper.sqlite3')}}
    (dest/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


def verify_backup(directory):
    root=Path(directory);manifest=json.loads((root/'manifest.json').read_text())
    for name,expected in manifest['sha256'].items():
        if file_digest(root/name)!=expected:raise ValueError('Backup checksum mismatch')
    return manifest


def rotate_source(source,paper,archive):
    """Explicit offline rotation. Keep the full immutable segment and money state.

    Only a stopped worker may rotate. Full replay requires archived segments;
    ordinary restart needs only the current checkpoint and current source segment.
    """
    source=Path(source)
    with single_worker(paper),single_worker(source),source_maintenance(source,exclusive=True):
        manifest=backup_pair(source,paper,archive)
        if manifest['paper_cursor']!=manifest['source_max_seq']:
            raise ValueError('Recover all source records before rotation')
        current=readonly(source)
        try:
            last=current.execute('SELECT available_ms FROM journal ORDER BY seq DESC LIMIT 1').fetchone()
            last_ms=last[0] if last else 0
        finally:current.close()
        temp=source.with_name(source.name+'.new-'+uuid4().hex)
        new=SourceJournal(temp)
        try:
            new.db.execute("UPDATE v33_meta SET value=? WHERE key='source_id'",(manifest['source_id'],))
            new.db.execute('INSERT INTO v33_meta VALUES (?,?)',('segment_base',str(manifest['source_max_seq'])))
            new.db.execute('INSERT INTO v33_meta VALUES (?,?)',('base_available_ms',str(last_ms)))
            new.db.execute('INSERT INTO sqlite_sequence(name,seq) VALUES(?,?)',('journal',manifest['source_max_seq']))
        finally:new.close()
        # Force any old WAL into the verified source before replacing its main file.
        old=sqlite3.connect(source)
        try:
            if old.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]:raise ValueError('Source is still busy')
        finally:old.close()
        os.replace(temp,source)
        for suffix in ('-wal','-shm'):
            side=Path(str(source)+suffix)
            if side.exists():side.unlink()
        return manifest
