"""v3.3 source journal: chronological availability, immutable IDs, as-of specs.

Independent from both legacy paper accounts. PUBLIC DATA / SIMULATION ONLY.
"""
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

from .paper_micro import prepare_rules
from .universe_rotation import RotationPolicy, select


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def clock_ms():
    return time.time_ns()//1_000_000


def connect_owned(path, owner):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(path,timeout=5,isolation_level=None)
    tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    if tables and 'v33_meta' not in tables:
        c.close()
        raise ValueError('Refusing an existing legacy/unknown database; v3.3 needs dedicated files')
    if 'v33_meta' in tables:
        row=c.execute("SELECT value FROM v33_meta WHERE key='owner'").fetchone()
        if not row or row[0]!=owner:
            c.close();raise ValueError('Source and paper database roles must remain separate')
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA synchronous=FULL')
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('CREATE TABLE IF NOT EXISTS v33_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    c.execute('INSERT OR IGNORE INTO v33_meta VALUES (?,?)',('owner',owner))
    return c


class SourceJournal:
    def __init__(self,path):
        self.path=Path(path)
        self.db=connect_owned(path,'v33-public-source')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS journal(
            seq INTEGER PRIMARY KEY AUTOINCREMENT, available_ms INTEGER NOT NULL,
            kind TEXT NOT NULL,event_key TEXT NOT NULL UNIQUE,payload TEXT NOT NULL,
            sha256 TEXT NOT NULL,semantic_hash TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS market_scans(
            id INTEGER PRIMARY KEY,time_ms INTEGER,equity_usdt REAL,contracts INTEGER,
            eligible INTEGER,raw_report TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS watchlists(id INTEGER PRIMARY KEY,time_ms INTEGER,selection TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS raw_events(
            symbol TEXT,channel TEXT,event_key TEXT,event_ms INTEGER,received_ms INTEGER,
            raw TEXT NOT NULL,normalized TEXT NOT NULL,PRIMARY KEY(symbol,channel,event_key));
          CREATE TABLE IF NOT EXISTS failures(id INTEGER PRIMARY KEY,time_ms INTEGER,category TEXT,reason TEXT);
          CREATE TRIGGER IF NOT EXISTS journal_no_update BEFORE UPDATE ON journal
            BEGIN SELECT RAISE(ABORT,'Source audit is append-only'); END;
          CREATE TRIGGER IF NOT EXISTS journal_no_delete BEFORE DELETE ON journal
            BEGIN SELECT RAISE(ABORT,'Archive the complete source; audit cannot be deleted'); END;
        ''')
        self.db.execute('INSERT OR IGNORE INTO v33_meta VALUES (?,?)',('source_id',uuid4().hex))
        self.source_id=self.db.execute("SELECT value FROM v33_meta WHERE key='source_id'").fetchone()[0]

    def append(self,packets):
        """Writer publication time + seq is authoritative, not exchange event time.

        Original network receipt/exchange times stay in payload. A late queued
        frame is never moved before a scan that was already published.
        """
        rows=[]
        self.db.execute('BEGIN IMMEDIATE')
        try:
            last=self.db.execute('SELECT available_ms FROM journal ORDER BY seq DESC LIMIT 1').fetchone()
            base=self.db.execute("SELECT value FROM v33_meta WHERE key='base_available_ms'").fetchone()
            previous=last[0] if last else int(base[0]) if base else -1
            for kind,key,payload in packets:
                if kind not in ('SCAN','SNAPSHOT','MARKET','HEALTH','CLOCK','CONTROL'):
                    raise ValueError('Unknown source journal record')
                semantic=payload.get('raw',payload) if kind=='MARKET' else payload
                semantic_hash=digest(semantic)
                old=self.db.execute('SELECT semantic_hash FROM journal WHERE event_key=?',(key,)).fetchone()
                if old:
                    if old[0]!=semantic_hash:raise ValueError('Conflicting source event ID')
                    continue
                available=clock_ms()
                if available<previous:raise ValueError('Writer clock regressed; refusing reordered availability')
                previous=available
                body=canonical(payload)
                sha=digest({'kind':kind,'key':key,'available_ms':available,'payload':payload})
                cur=self.db.execute('INSERT INTO journal(available_ms,kind,event_key,payload,sha256,semantic_hash) VALUES(?,?,?,?,?,?)',
                                    (available,kind,key,body,sha,semantic_hash))
                seq=cur.lastrowid
                if kind=='SCAN':
                    report,watch=payload['report'],payload['watch']
                    self.db.execute('INSERT INTO market_scans VALUES (?,?,?,?,?,?)',
                        (seq,available,report['capital_usdt'],report['contracts_observed'],report['preflight_eligible'],canonical(report)))
                    self.db.execute('INSERT INTO watchlists VALUES (?,?,?)',(seq,available,canonical(watch)))
                elif kind=='MARKET':
                    p=payload
                    self.db.execute('INSERT OR IGNORE INTO raw_events VALUES (?,?,?,?,?,?,?)',
                        (p['symbol'],p['channel'],p['event_key'],p['event_ms'],p['received_ms'],canonical(p['raw']),canonical(p['normalized'])))
                elif kind=='HEALTH':
                    self.db.execute('INSERT INTO failures VALUES (?,?,?,?)',(seq,available,payload['state'],canonical(payload)))
                rows.append((seq,available,kind,key,payload,sha))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK');raise
        return rows

    def after(self,seq,limit=500):
        return [(i,t,k,key,json.loads(p),sha) for i,t,k,key,p,sha in self.db.execute(
            'SELECT seq,available_ms,kind,event_key,payload,sha256 FROM journal WHERE seq>? ORDER BY seq LIMIT ?',
            (seq,limit))]

    def close(self):self.db.close()


class Timeline:
    @staticmethod
    def scan(payload,available_ms):
        report,watch=payload['report'],payload['watch']
        if report['time_ms']>available_ms or watch['time_ms']>available_ms:
            raise ValueError('Future scan/watchlist cannot be used as-of an earlier decision')
        specs=report.get('paper_contract_specs',{})
        rules=prepare_rules(report) if specs else {}
        if len(watch['deep_symbols'])!=len(set(watch['deep_symbols'])):
            raise ValueError('Ambiguous duplicate watch symbol')
        for sym,spec in specs.items():
            if spec['captured_ms']>available_ms:
                raise ValueError('Future contract specification')
        unavailable=set(payload.get('unavailable',[]))
        if any(s not in rules and s not in unavailable for s in watch['deep_symbols']):
            raise ValueError('Missing as-of contract specification')
        return {'available_ms':available_ms,'report_time_ms':report['time_ms'],
                'watch':watch,'specs':specs,'unavailable':sorted(unavailable)}


def pinned_selection(report,previous,pins,policy):
    pins=sorted(set(pins))
    if len(pins)>20:
        raise ValueError('Pinned exposures exceed provider hard capacity; operator intervention required')
    effective=replace(policy,deep_slots=max(policy.deep_slots,len(pins)))
    result=select(report,now_ms=report['time_ms'],previous=previous.get('deep_symbols',()),
                  entered_at=previous.get('entered_at',{}),pinned=pins,policy=effective)
    result['capacity_exhausted']=len(pins)>=policy.deep_slots
    if result['capacity_exhausted']:
        result['blocked_new_entries']=sorted(set(result['blocked_new_entries'])|set(result['deep_symbols']))
    return result
