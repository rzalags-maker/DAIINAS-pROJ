"""Issue #6 / v3.3 continuous dynamic PAPER service and deterministic replay."""
import argparse
from contextlib import closing
import asyncio
from dataclasses import asdict
import hashlib
import heapq
import json
from pathlib import Path
import signal
import sqlite3
import time
from uuid import uuid4

from .continuous_store import SourceJournal,canonical,digest
from .continuous_paper import Pipeline,PaperLedger
from .continuous_stream import ContinuousObserver
from .continuous_ops import (status,backup_pair,rotate_source,readonly,file_bytes,source_maintenance)
from .paper_micro import PaperPolicy
from .shadow_flow import ShadowPolicy
from .service import single_worker


def settings(path):
    config=json.loads(Path(path).read_text())
    paper=PaperPolicy(**config.get('paper',{}));shadow=ShadowPolicy(**config.get('shadow',{}))
    if paper.initial_capital_usdt!=8 or paper.margin_fraction>.8:raise ValueError('One 8-USDT account, <=80% margin')
    if not 3<=config.get('deep',5)<=8 or not 30<=config.get('refresh_seconds',180)<=3600:
        raise ValueError('Deep watchlist 3..8; public scan cadence 30..3600 seconds')
    return config,paper,shadow


def source_rows(path):
    c=readonly(path)
    try:
        for seq,t,kind,key,payload,sha in c.execute('SELECT seq,available_ms,kind,event_key,payload,sha256 FROM journal ORDER BY seq'):
            yield seq,t,kind,key,json.loads(payload),sha
    finally:c.close()


def replay(sources,paper_path,policy=PaperPolicy(),shadow=ShadowPolicy()):
    ids=[]
    for path in sources:
        with closing(readonly(path)) as c:ids.append(c.execute("SELECT value FROM v33_meta WHERE key='source_id'").fetchone()[0])
    if len(set(ids))!=1:raise ValueError('Source archives belong to different runs')
    if any(Path(x).resolve()==Path(paper_path).resolve() for x in sources):raise ValueError('Replay output must remain separate')
    Path(paper_path).parent.mkdir(parents=True,exist_ok=True)
    with single_worker(paper_path):
        ledger=PaperLedger(paper_path,ids[0],policy,shadow)
        try:
            batch=[];last=None
            for row in heapq.merge(*(source_rows(p) for p in sources),key=lambda r:r[0]):
                if last and row[0]==last[0]:
                    if row[5]!=last[5]:raise ValueError('Conflicting archived source records')
                    continue
                batch.append(row);last=row
                if len(batch)>=100:ledger.apply(batch);batch=[]
            if batch:ledger.apply(batch)
            return ledger.report()
        finally:ledger.close()


async def service(args,config,paper,shadow):
    pipeline=Pipeline(args.source_db,args.paper_db,paper,shadow)
    observer=ContinuousObserver(pipeline,source_path=args.source_db,deep=config.get('deep',5),
        refresh_seconds=config.get('refresh_seconds',180),dwell_ms=config.get('dwell_seconds',120)*1000,
        queue_size=config.get('queue_size',20000))
    started=time.monotonic();boot=uuid4().hex;errors=[];fatal=None
    stop=asyncio.Event();loop=asyncio.get_running_loop()
    for sig in (signal.SIGINT,signal.SIGTERM):loop.add_signal_handler(sig,stop.set)
    async def loops():
        delay=1
        while not stop.is_set():
            previous_connections=observer.stream_stats['connections']
            try:
                await observer.preflight()
                await observer.session(renew_after=args.renew_seconds)
            except asyncio.CancelledError:raise
            except Exception as exc:
                leaf=exc
                while isinstance(leaf,BaseExceptionGroup):leaf=leaf.exceptions[0]
                reason=f'{type(leaf).__name__}: {leaf}'
                # No token-bearing WebSocket URLs go into an audit/report.
                if 'token=' in reason:reason=type(leaf).__name__+': public connection failed'
                errors.append(reason);del errors[:-20]
                await pipeline.append([('HEALTH',f'failure:{uuid4().hex}',{'state':'CONNECTION_LOSS','reason':reason})])
                observer.stream_stats['reconnects']+=1
            if stop.is_set():break
            try:await asyncio.wait_for(stop.wait(),delay)
            except asyncio.TimeoutError:pass
            delay=1 if observer.stream_stats['connections']>previous_connections else min(delay*2,30)
    async def clocks():
        tick=0
        while not stop.is_set():
            tick+=1
            runtime=observer.runtime()
            runtime.update({'boot_id':boot,'host_id':args.host_id,'elapsed_seconds':time.monotonic()-started,
                            'source_bytes':file_bytes(args.source_db),'paper_bytes':file_bytes(args.paper_db)})
            import shutil
            runtime['disk_free_bytes']=shutil.disk_usage(args.source_db.parent).free
            low=(runtime['source_bytes']>config.get('max_source_bytes',64*1024**3)
                 or runtime['paper_bytes']>config.get('max_paper_bytes',64*1024**3)
                 or runtime['disk_free_bytes']<config.get('min_free_bytes',1024**3))
            if low:
                await pipeline.append([('CONTROL',f'storage-pause:{boot}',{'action':'pause'}),
                    ('HEALTH',f'storage-halt:{boot}',{'state':'STORAGE_CAPACITY_HALT'})])
                raise OSError('Storage capacity guard: paper state retained; archive/restore required')
            await pipeline.append([('CLOCK',f'clock:{boot}:{tick}',{'service':runtime})])
            await asyncio.sleep(1)
    runner=asyncio.create_task(loops());clock=asyncio.create_task(clocks());waiting=asyncio.create_task(stop.wait())
    try:
        done,_=await asyncio.wait([runner,clock,waiting],timeout=args.seconds or None,return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if task is not waiting and task.exception():raise task.exception()
    except Exception as exc:fatal=f'{type(exc).__name__}: {exc}'
    finally:
        stop.set()
        for task in (runner,clock,waiting):task.cancel()
        await asyncio.gather(runner,clock,waiting,return_exceptions=True)
        result=await pipeline.report()
        result.update({'stream':observer.runtime(),'errors':errors,'fatal_error':fatal,
                       'elapsed_seconds':time.monotonic()-started,'boot_id':boot,
                       'source_path':str(args.source_db),'paper_path':str(args.paper_db),
                       'observed_contracts':observer.last_scan.get('observed_contracts',0) if observer.last_scan else 0,
                       'normalized_event_counts':dict(observer.stats),
                       'source_code_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
                           [Path(__file__),Path(__file__).with_name('continuous_paper.py'),Path(__file__).with_name('continuous_stream.py'),Path(__file__).with_name('continuous_store.py')]}})
        result['24h_host_gate']='PENDING — HOST ACCEPTANCE NOT RUN' if args.host_id else 'BLOCKED — HOST NOT PROVISIONED'
        if args.seconds:
            stats=observer.stream_stats
            no_candidates=not observer.watch or not observer.watch['deep_symbols']
            passed=(not fatal and stats['market_scans']>=2 and stats['connections']>=2
                    and stats['reconciliations']>=2 and result['source_cursor']>0
                    and (no_candidates or stats['pongs']>0 and stats['subscribe_acks']>=3
                         and observer.stats['level2']>0 and observer.stats['tickerV2']>0
                         and result['counts'].get('VERIFIED_BOOK',0)>0))
            result['smoke_status']='passed' if passed else 'not_verified'
        if args.report:
            args.report.parent.mkdir(parents=True,exist_ok=True)
            args.report.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
        print(json.dumps(result,indent=2,allow_nan=False))
        observer.close();pipeline.close()
    return 1 if fatal or args.seconds and result.get('smoke_status')!='passed' else 0


def main(argv=None):
    p=argparse.ArgumentParser(description='Continuous dynamic paper engine. LIVE ORDERS DISABLED.')
    p.add_argument('command',choices=['run','replay','stop','resume','status','reset-halt','capital-flow','backup','archive-source'])
    p.add_argument('--config',type=Path,default=Path('configs/continuous.json'))
    p.add_argument('--source-db',type=Path,default=Path('state/v33-source.sqlite3'))
    p.add_argument('--paper-db',type=Path,default=Path('state/v33-paper.sqlite3'))
    p.add_argument('--source-archive',type=Path,action='append',default=[])
    p.add_argument('--report',type=Path)
    p.add_argument('--seconds',type=int,default=0)
    p.add_argument('--renew-seconds',type=int,default=72000)
    p.add_argument('--review-note',default='')
    p.add_argument('--amount',type=float)
    p.add_argument('--destination',type=Path)
    p.add_argument('--host-id')
    a=p.parse_args(argv)
    if a.source_db.resolve()==a.paper_db.resolve():p.error('Independent source/paper databases required')
    if a.seconds<0 or not 1<=a.renew_seconds<=72000:p.error('Invalid duration or token renewal')
    if a.command=='run':
        cfg,paper,shadow=settings(a.config)
        a.paper_db.parent.mkdir(parents=True,exist_ok=True);a.source_db.parent.mkdir(parents=True,exist_ok=True)
        with single_worker(a.paper_db),single_worker(a.source_db):return asyncio.run(service(a,cfg,paper,shadow))
    if a.command=='replay':
        cfg,paper,shadow=settings(a.config)
        result=replay([*a.source_archive,a.source_db],a.paper_db,paper,shadow)
        if a.report:
            a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2));return 0
    if a.command=='status':
        result=status(a.source_db,a.paper_db);print(json.dumps(result,indent=2));return 0 if result['healthy'] else 1
    if a.command in ('backup','archive-source'):
        if a.destination is None:p.error('A new --destination is required')
        result=(backup_pair if a.command=='backup' else rotate_source)(a.source_db,a.paper_db,a.destination)
        print(json.dumps(result,indent=2));return 0
    if not a.source_db.exists():p.error('Source journal does not exist')
    action='pause' if a.command=='stop' else a.command
    payload={'action':action}
    if action=='reset-halt':
        if len(a.review_note.strip())<8:p.error('Explicit --review-note required')
        payload['review_note']=a.review_note
    if action=='capital-flow':
        if a.amount is None:p.error('Explicit simulated --amount required')
        payload['amount']=a.amount
    with source_maintenance(a.source_db):
        source=SourceJournal(a.source_db)
        try:rows=source.append([('CONTROL',f'operator:{uuid4().hex}',payload)])
        finally:source.close()
    print(canonical({'accepted_source_seq':rows[0][0],'action':action,
                     'note':'Applied by the running worker or recovered at next start; open exits remain active.'}))
    return 0


if __name__=='__main__':raise SystemExit(main())
