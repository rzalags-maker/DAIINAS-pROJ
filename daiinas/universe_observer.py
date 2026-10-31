"""DAIINAS v3 public-only rotating KuCoin Futures market observer.

A separate, read-only experiment. Does not attach to the v1 paper account,
emit buy/sell signals, call private exchange APIs, or place orders.
"""
import argparse
import asyncio
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
import ssl
import time
from urllib.parse import urlencode
from uuid import uuid4

from .providers.kucoin import (DataGap, SequenceGap, OrderBook, PublicRest,
                               execution, ticker, token_server)
from .risk import ContractRules
from .universe import Policy, public_get, scan
from .universe_rotation import RotationPolicy, select


def now_ms():
    return time.time_ns() // 1_000_000


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), allow_nan=False)


def contract_rule(row):
    """Real KuCoin lot units, not the Binance base-quantity convention."""
    if (row.get('status') != 'Open' or row.get('isInverse') is not False or
        row.get('quoteCurrency') != 'USDT' or row.get('settleCurrency') != 'USDT' or
        row.get('type') != 'FFWCSX' or row.get('expireDate') is not None):
        raise DataGap('Not an open USDT linear perpetual')
    lot = int(row['lotSize'])
    if lot < 1 or float(row['multiplier']) <= 0 or int(row['maxOrderQty']) < lot:
        raise DataGap('Invalid contract multiplier or lot')
    if float(row.get('takerFixFee', 0)) != 0:
        raise DataGap('Unsupported fixed taker commission')
    return ContractRules(row['symbol'], str(lot), str(int(row['maxOrderQty'])),
                         str(lot), str(row['tickSize']), '0', str(row['multiplier']))


class ObservationStore:
    """Independent WAL database. Never share the existing paper account DB."""
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True,exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=NORMAL')
        with self.db:
            self.db.executescript('''
                CREATE TABLE IF NOT EXISTS market_scans(
                    id INTEGER PRIMARY KEY, time_ms INTEGER, equity_usdt REAL,
                    contracts INTEGER, eligible INTEGER, raw_report TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS watchlists(
                    id INTEGER PRIMARY KEY, time_ms INTEGER, selection TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS raw_events(
                    symbol TEXT, channel TEXT, event_key TEXT, event_ms INTEGER,
                    received_ms INTEGER, raw TEXT NOT NULL, normalized TEXT NOT NULL,
                    PRIMARY KEY(symbol,channel,event_key));
                CREATE INDEX IF NOT EXISTS idx_raw_events_time ON raw_events(event_ms);
                CREATE TABLE IF NOT EXISTS failures(
                    id INTEGER PRIMARY KEY, time_ms INTEGER, category TEXT, reason TEXT);
            ''')
    def close(self):
        self.db.close()
    def record_scan(self, report, watch):
        with self.db:
            self.db.execute('INSERT INTO market_scans(time_ms,equity_usdt,contracts,eligible,raw_report) VALUES(?,?,?,?,?)',
                (report['time_ms'],report['capital_usdt'],report['contracts_observed'],
                 report['preflight_eligible'],canonical(report)))
            self.db.execute('INSERT INTO watchlists(time_ms,selection) VALUES (?,?)',
                            (watch['time_ms'],canonical(watch)))
    def record_failure(self, category, reason):
        with self.db:
            self.db.execute('INSERT INTO failures(time_ms,category,reason) VALUES(?,?,?)',
                            (now_ms(),category,str(reason)[:600]))
    def record_events(self, events):
        with self.db:
            for symbol,channel,key,t,received,raw,normalized in events:
                self.db.execute('INSERT OR IGNORE INTO raw_events VALUES (?,?,?,?,?,?,?)',
                                (symbol,channel,key,t,received,canonical(raw),canonical(normalized)))
    def latest(self):
        r=self.db.execute('SELECT selection FROM watchlists ORDER BY id DESC LIMIT 1').fetchone()
        return json.loads(r[0]) if r else None


class Observer:
    def __init__(self, *, equity=8.0, deep=5, db='state/universe-observer.sqlite3',
                 connector=None, rest=None, policy=None, dwell_ms=120000):
        self.equity=equity
        self.policy=policy or Policy()
        self.rotation=RotationPolicy(deep_slots=deep,minimum_residence_ms=dwell_ms)
        self.store=ObservationStore(db)
        self.connector=connector
        self.rest=rest or PublicRest()
        self.watch=None
        self.contracts={}
        self.books={}
        self.stats=Counter()
        self.sequences={}
        self.last_event_times={}
        self.verified=set()
        self.started_ms=now_ms()
        self.last_scan=None

    def close(self):
        self.store.close()

    async def preflight(self, pinned=()):
        rows,ticks=await asyncio.gather(
            asyncio.to_thread(public_get,'/api/v1/contracts/active'),
            asyncio.to_thread(public_get,'/api/v1/allTickers'))
        ts=now_ms()
        report=scan(rows,ticks,now_ms=ts,equity=self.equity,policy=self.policy)
        previous=self.watch or self.store.latest() or {}
        decision=select(report,now_ms=ts,
                        previous=previous.get('deep_symbols',()),
                        entered_at=previous.get('entered_at',{}),
                        pinned=pinned,policy=self.rotation)
        source={row['symbol']:row for row in rows}
        validated={}
        for sym in decision['deep_symbols']:
            if sym not in source:
                raise DataGap('Pinned symbol removed from provider contract metadata')
            validated[sym]=contract_rule(source[sym])
        # Real KuCoin contract metadata is mandatory for later executable
        # virtual lot-sizing. Older captures without this fail closed in v3.2.
        # Store only selected public specs to avoid a giant static universe copy.
        report['paper_contract_specs']={sym:{
            'rules':asdict(validated[sym]),
            'taker_fee_rate':float(source[sym]['takerFeeRate']),
            'source':'KuCoin Classic Futures public contracts/active',
            'captured_ms':ts,
        } for sym in decision['deep_symbols']}
        self.store.record_scan(report,decision)
        self.watch=decision
        self.contracts=validated
        self.last_scan=report
        self.stats['universe_scans']+=1
        return decision

    def _process(self,msg):
        topic=msg.get('topic','')
        if not topic.startswith('/contractMarket/') or ':' not in topic:
            raise DataGap('Invalid market topic')
        prefix,symbol=topic.split(':',1)
        channel=prefix.removeprefix('/contractMarket/')
        if symbol not in self.contracts or channel not in ('execution','tickerV2','level2'):
            raise DataGap('Unsubscribed market event')
        received=now_ms()
        data=msg['data']
        if not isinstance(data,dict):
            raise DataGap('Unexpected market payload')
        # Channel sequence non-contiguity differs from L2 snapshot sequence.
        seq=int(data['sequence'])
        if seq<0 or (msg.get('sn') is not None and int(msg['sn'])!=seq):
            raise DataGap('Invalid stream sequence')
        key=(symbol,channel)
        event_key=str(data['tradeId']) if channel=='execution' else str(seq)
        if channel=='level2':
            book=self.books[symbol]
            accepted=book.delta(data,received)
            if not accepted:
                return None
            self.verified.add(symbol)
            t=book.time
            normalized={'book_sequence':book.sequence,'verified':book.verified,
                        'best_bid':float(max(book.bids)),
                        'best_ask':float(min(book.asks))}
        else:
            prev=self.sequences.get(key)
            if prev is not None and seq<=prev:
                # Exact duplicates are harmless; unknown reorders are not.
                old=self.store.db.execute(
                    'SELECT raw FROM raw_events WHERE symbol=? AND channel=? AND event_key=?',
                    (symbol,channel,event_key)).fetchone()
                if old and old[0]==canonical(data):return None
                raise DataGap('Nonmonotonic trade/quote sequence')
            rule=self.contracts[symbol]
            if channel=='execution':
                obj=execution(symbol,data,rule,received,exchange_symbol=symbol)
                normalized=asdict(obj)
            else:
                normalized=ticker(symbol,data,rule,received,exchange_symbol=symbol)
            t=normalized['timestamp']
            if t<self.last_event_times.get(key,0):
                raise DataGap('Provider event timestamp regressed')
            self.last_event_times[key]=t
        self.sequences[key]=seq
        self.stats[channel]+=1
        return (symbol,channel,event_key,t,received,data,normalized)

    async def _snapshot(self,symbol):
        data,_,_=await asyncio.to_thread(self.rest.request,'/api/v1/level2/snapshot',
                                        {'symbol':symbol})
        self.books[symbol].snapshot(data,now_ms())
        self.stats['book_snapshots']+=1

    async def session(self, *, seconds=45):
        if self.watch is None:
            await self.preflight()
        symbols=list(self.watch['deep_symbols'])
        if not symbols:
            self.stats['no_candidates']+=1
            return
        self.books={s:OrderBook(s,self.contracts[s],exchange_symbol=s) for s in symbols}
        self.sequences.clear()
        self.last_event_times.clear()
        self.verified.clear()
        token,_,_=await asyncio.to_thread(self.rest.request,'/api/v1/bullet-public')
        server=token_server(token)
        if self.connector is None:
            from websockets.asyncio.client import connect
            self.connector=connect
        uri=server['endpoint'].rstrip('/')+'/?'+urlencode(
            {'token':token['token'],'connectId':uuid4().hex})
        subscriptions={}
        for sym in symbols:
            for channel in ('execution','tickerV2','level2'):
                subscriptions[f'{sym}-{channel}']=f'/contractMarket/{channel}:{sym}'
        end=time.monotonic()+seconds
        async with self.connector(uri,ssl=ssl.create_default_context(),proxy=True,
                open_timeout=15,close_timeout=3,ping_interval=None,
                compression=None,max_queue=2048,max_size=2**20) as ws:
            # Buffer public events from the moment the connection opens.
            pending=[]
            welcome=False
            while not welcome:
                msg=json.loads(await asyncio.wait_for(ws.recv(),timeout=15))
                if msg.get('type')=='welcome':welcome=True
                elif msg.get('type')=='message':pending.append(msg)
            for sub_id,topic in subscriptions.items():
                await ws.send(canonical({'id':sub_id,'type':'subscribe','topic':topic,
                                         'privateChannel':False,'response':True}))
            acked=set()
            while len(acked)<len(subscriptions):
                msg=json.loads(await asyncio.wait_for(ws.recv(),timeout=20))
                kind=msg.get('type')
                if kind=='ack':
                    if str(msg.get('id')) not in subscriptions:
                        raise DataGap('Unrecognized topic ACK')
                    acked.add(str(msg['id']))
                elif kind=='message':
                    pending.append(msg)
                    if len(pending)>20_000:
                        raise DataGap('Subscription buffer overflow')
                elif kind=='error':
                    raise DataGap('Provider rejected subscription')
            # REST snapshot must be obtained AFTER WS subscribed. Buffered
            # L2 deltas <=snapshot sequence are ignored, only +1 bridges trust.
            for sym in symbols:
                await self._snapshot(sym)
            self.stats['socket_sessions']+=1
            ping_id=None
            ping_sent=0.0
            last_ping=time.monotonic()
            while time.monotonic()<end:
                if time.monotonic()-last_ping >= server['pingInterval']/1000*0.75 and ping_id is None:
                    ping_id=uuid4().hex
                    ping_sent=last_ping=time.monotonic()
                    await ws.send(canonical({'id':ping_id,'type':'ping'}))
                if ping_id is not None and time.monotonic()-ping_sent>server['pingTimeout']/1000:
                    raise DataGap('Missing application-level ping response')
                try:
                    if pending:msg=pending.pop(0)
                    else:msg=json.loads(await asyncio.wait_for(ws.recv(),timeout=min(1,max(.01,end-time.monotonic()))))
                except asyncio.TimeoutError:
                    continue
                kind=msg.get('type')
                if kind=='pong':
                    if str(msg.get('id'))==ping_id:
                        ping_id=None
                        self.stats['pongs']+=1
                    continue
                if kind=='error':raise DataGap('Provider error frame')
                if kind!='message':continue
                try:
                    normalized=self._process(msg)
                except SequenceGap as exc:
                    symbol=msg['topic'].split(':',1)[1]
                    self.stats['book_gaps']+=1
                    self.store.record_failure('book_gap',f'{symbol}: {exc}')
                    # Do not accept unverifiable sequence data. Fresh REST
                    # snapshot; only a subsequent contiguous delta proves sync.
                    await self._snapshot(symbol)
                    continue
                if normalized is not None:
                    self.store.record_events([normalized])
            self.stats['verified_books']=len(self.verified)

    def report(self):
        result={'status':'observation_only','simulation_only':True,'live_orders':False,
                'provider':'KuCoin Classic Futures public',
                'started_ms':self.started_ms,'ended_ms':now_ms(),
                'capital_assumption_usdt':self.equity,
                'observed_contracts':self.last_scan['contracts_observed'] if self.last_scan else 0,
                'eligible':self.last_scan['preflight_eligible'] if self.last_scan else 0,
                'deep_symbols':self.watch['deep_symbols'] if self.watch else [],
                'counts':dict(self.stats),
                'verified_book_symbols':sorted(self.verified),
                'comment':'Price/feed observation, not proven entry edge, not paper trades'}
        return result


async def run(args):
    observer=Observer(equity=args.equity,deep=args.deep,db=args.db,
                      dwell_ms=args.dwell_seconds*1000)
    failure=None
    try:
        await observer.preflight()
        if args.seconds:
            await observer.session(seconds=args.seconds)
        else:
            # Persistent read-only scanner: re-evaluate the full universe at a
            # bounded cadence. A new public WebSocket session follows a scan.
            while True:
                await observer.session(seconds=args.refresh_seconds)
                await observer.preflight()
    except Exception as exc:
        failure=f'{type(exc).__name__}: {exc}'
        observer.store.record_failure('observer',failure)
    finally:
        result=observer.report()
        result['status']='failed' if failure else ('observed' if result['counts'].get('execution',0)
                 and result['counts'].get('tickerV2',0) and result['verified_book_symbols']
                 else 'partial_market_observation')
        if failure:result['error']=failure
        if args.report:
            args.report.parent.mkdir(parents=True,exist_ok=True)
            args.report.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2))
        observer.close()
    return 1 if failure or (args.seconds and result['status']!='observed') else 0


def main(argv=None):
    p=argparse.ArgumentParser(description='Read-only dynamic KuCoin Futures market observer')
    p.add_argument('--equity',type=float,default=8.0)
    p.add_argument('--deep',type=int,default=5)
    p.add_argument('--seconds',type=int,default=0,help='Finite real-market smoke length; 0 loops')
    p.add_argument('--refresh-seconds',type=int,default=180)
    p.add_argument('--dwell-seconds',type=int,default=120)
    p.add_argument('--db',type=Path,default=Path('state/universe-observer.sqlite3'))
    p.add_argument('--report',type=Path)
    args=p.parse_args(argv)
    if args.seconds<0 or args.refresh_seconds<30 or args.dwell_seconds<0:
        p.error('Invalid runtime interval')
    return asyncio.run(run(args))


if __name__=='__main__':
    raise SystemExit(main())
