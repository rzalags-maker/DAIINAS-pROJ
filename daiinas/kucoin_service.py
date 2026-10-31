"""Primary live provider: KuCoin Classic public Futures; simulation only."""
import argparse
import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import ssl
import time
from urllib.parse import urlencode
from uuid import uuid4

from .data import digest
from .models import INTERVALS, RiskConfig, StrategyConfig
from .flow import AggressiveTrade
from .service import Store, Worker, canonical, now_ms, single_worker
from .providers.kucoin import (PublicRest, DataGap, MAPPING, REVERSE, TOPICS,
                               OrderBook, contracts, execution, ticker, integer,
                               timestamp, token_server, klines)


class RenewConnection(Exception):
    pass


class CandleCache:
    def __init__(self):
        self.responses, self.bars = [], {}
        self.server_time = 0

    def clock(self):
        return self.server_time

    def candles(self, symbol, interval, start, end):
        return self.bars[(symbol,start,end)]


class Engine:
    def __init__(self, store, config, rest=None, connector=None):
        self.store, self.config = store, config
        self.rest, self.connector = rest or PublicRest(), connector
        self.symbols = sorted(config['symbols'])
        if not self.symbols or len(set(self.symbols)) != len(self.symbols) or not set(self.symbols) <= set(MAPPING):
            raise ValueError('Unique supported canonical symbols required')
        self.interval = INTERVALS[config['interval']]
        strategy = StrategyConfig(**config.get('strategy',{}))
        if max(strategy.lookback,strategy.atr_period+1) > 499:
            raise ValueError('KuCoin warm-up must fit the 500-candle public REST page')
        RiskConfig(**config.get('risk',{}))
        self.stale_ms = int(config.get('stale_seconds',30)*1000)
        if not 5000 <= self.stale_ms <= 120000:
            raise ValueError('Staleness threshold must be 5..120 seconds')
        self.renew_seconds = config.get('token_renew_seconds',72000)
        if not 30 <= self.renew_seconds <= 72000:
            raise ValueError('Renew before the documented 24-hour lifetime (30..72000 seconds)')
        self.poll_seconds = config.get('poll_seconds',10)
        if not 1 <= self.poll_seconds <= 60:
            raise ValueError('Paper poll interval must be 1..60 seconds')
        self.queue_size = config.get('queue_size',20000)
        if not isinstance(self.queue_size,int) or not 100 <= self.queue_size <= 100000:
            raise ValueError('Bounded event queue must be 100..100000')
        self.rules, self.normalized, self.books = {}, {}, {}
        self.last, self.sequences, self.event_times = {}, {}, {}
        self.worker = None
        self.cache = CandleCache()
        self.connected = False
        self.session_id = None
        self.counts = {'public_tokens':0,'connections':0,'reconnects':0,'pongs':0,
                       'renewals':0,'errors':0,'paper_batches':0,'verified_sessions':0,'checkpoint_resumes':0}
        self.verified_symbols, self.acked_topics = set(), set()
        self.errors = []
        store.db.executescript('''
            CREATE TABLE IF NOT EXISTS market_events (
              symbol TEXT, channel TEXT, event_key TEXT, timestamp INTEGER,
              received_at INTEGER, session TEXT, raw TEXT, normalized TEXT,
              PRIMARY KEY(symbol,channel,event_key));
            CREATE TABLE IF NOT EXISTS paper_decisions (
              time INTEGER PRIMARY KEY, session TEXT, payload TEXT NOT NULL);
        ''')

    async def request(self, path, params=None):
        data, payload, url = await asyncio.to_thread(self.rest.request,path,params)
        if path == '/api/v1/bullet-public':
            # Public connection tokens are ephemeral and never logged or persisted.
            payload = canonical({'code':'200000','token_received':bool(data.get('token')),
                                 'instanceServers':data.get('instanceServers',[])}).encode()
            self.counts['public_tokens'] += 1
        self.store.db.execute('INSERT INTO responses(fetched_at,url,sha256,payload) VALUES (?,?,?,?)',
                              (now_ms(),url,digest(payload),payload))
        return data

    async def initialize(self):
        rows = await self.request('/api/v1/contracts/active')
        risk = RiskConfig(**self.config.get('risk',{}))
        self.rules,self.normalized = contracts(rows,self.symbols,risk.leverage)
        # One conservative taker rate serves the existing shared-account model.
        effective_fee = max(risk.fee_rate,*(r['taker_fee_rate'] for r in self.normalized.values()))
        cfg = {**self.config,'provider':'kucoin-classic-futures',
               'risk':{**asdict(risk),'fee_rate':effective_fee},
               'adapter_sha256':{p.name:digest(p.read_bytes()) for p in
                                 (Path(__file__),Path(__file__).parent/'providers'/'kucoin.py')}}
        # Stable static metadata identity: do not pin changing mark/last prices.
        payload = canonical(self.normalized).encode()
        self.worker = Worker(self.store,cfg,self.rules,payload,self.cache,self.decisions)
        self.books = {s:OrderBook(s,self.rules[s]) for s in self.symbols}
        self.store.set('kucoin_contracts',self.normalized)
        self.health()

    def book(self, symbol):
        return self.books[symbol].view()

    def trades(self, symbol, start, end):
        return [AggressiveTrade(**json.loads(row[0])) for row in self.store.db.execute(
            "SELECT normalized FROM market_events WHERE symbol=? AND channel='execution' AND timestamp>=? AND timestamp<? ORDER BY timestamp,event_key",
            (symbol,start,end))]

    def ready(self):
        t = now_ms()
        return (self.connected and len(self.books)==len(self.symbols) and all(
            self.books[s].verified and all(t-self.last.get((s,k),0) < self.stale_ms
                                           for k in TOPICS) for s in self.symbols))

    def health(self):
        ready = self.ready()
        self.store.set('kucoin_health',{'time':now_ms(),'ready':ready,'connected':self.connected,
                                      'session':self.session_id,'verified_books':[s for s,b in self.books.items() if b.verified],
                                      'counts':self.counts})
        stopped = self.store.get('stop',False)
        self.store.set('heartbeat',{'time':now_ms(),'status':'stopped' if stopped else 'running' if ready else 'waiting',
                                    'error':None})
        return ready

    def decisions(self, result, window, start):
        # Invoked INSIDE the existing worker's account/checkpoint transaction.
        last = result['checkpoint']['last_time']
        candidates = [json.loads(row[0]) for row in self.store.db.execute(
            'SELECT payload FROM signals WHERE time>=? AND time<=?',(window[self.symbols[0]][start].time,last))]
        payload = {'simulation_only':True,'model':'existing closed-candle simulator; no order-flow alpha',
                   'market_ready_at_processing':self.ready(),'batch_bars':len(result['equity_curve']),
                   'candidate_signals':candidates,'closed_trades':len(result['trades']),
                   'metrics':result['metrics'],'positions':result['checkpoint']['positions'],
                   'recovery_accounting':self.paper_recovery}
        self.store.db.execute('INSERT INTO paper_decisions VALUES (?,?,?)',
                              (last,self.session_id,canonical(payload)))

    def ingest(self, msg):
        try:
            return self._ingest(msg)
        except (ValueError,KeyError):
            self.connected=False
            for book in self.books.values():book.reset()
            raise

    def _ingest(self, msg):
        topic = msg['topic']
        prefix,exchange = topic.split(':',1)
        channel = prefix.removeprefix('/contractMarket/')
        if exchange not in REVERSE or REVERSE[exchange] not in self.symbols or channel not in TOPICS:
            raise DataGap('Unsubscribed market topic')
        symbol = REVERSE[exchange]
        row, received = msg['data'],now_ms()
        seq = integer(row['sequence'])
        if 'sn' in msg and integer(msg['sn']) != seq:
            raise DataGap('Envelope/data sequence mismatch')
        key = (symbol,channel)
        raw = canonical(row)
        event_key = str(row['tradeId']) if channel == 'execution' else str(seq)
        if channel != 'level2':
            previous = self.sequences.get(key)
            if previous is not None and seq <= previous:
                prior = self.store.db.execute('SELECT raw FROM market_events WHERE symbol=? AND channel=? AND event_key=?',
                                               (symbol,channel,event_key)).fetchone()
                if seq == previous and prior and prior[0] == raw:
                    return
                raise DataGap('Non-monotonic market stream sequence')
            t = timestamp(row['ts'],'ns',received)
            if t < self.event_times.get(key,0):
                raise DataGap('Market stream timestamp moved backwards')
            normalized = asdict(execution(symbol,row,self.rules[symbol],received)) if channel == 'execution' else ticker(symbol,row,self.rules[symbol],received)
            self.event_times[key] = t
        else:
            if not self.books[symbol].delta(row,received):
                return
            t = self.books[symbol].time
            normalized = {'sequence_verified':True,'sequence':seq}
            self.verified_symbols.add(symbol)
        existing = self.store.db.execute('SELECT raw FROM market_events WHERE symbol=? AND channel=? AND event_key=?',
                                         (symbol,channel,event_key)).fetchone()
        if existing and existing[0] != raw:
            raise DataGap('Conflicting duplicate market event')
        self.store.db.execute('INSERT OR IGNORE INTO market_events VALUES (?,?,?,?,?,?,?,?)',
                              (symbol,channel,event_key,t,received,self.session_id,raw,canonical(normalized)))
        self.sequences[key],self.last[key] = seq,received

    async def paper_once(self):
        if self.store.get('stop',False) or not self.ready():
            return 0
        server_time = integer(await self.request('/api/v1/timestamp'))
        if abs(server_time-now_ms()) > 60000:
            raise DataGap('Host/exchange clock drift exceeds 60 seconds')
        latest = server_time//self.interval*self.interval-self.interval
        checkpoint = self.store.get('checkpoint')
        next_time = checkpoint['last_time']+self.interval if checkpoint else latest-self.worker.warmup*self.interval
        if next_time > latest:
            return 0
        if checkpoint and (latest-next_time)//self.interval+1 > self.config.get('max_catchup_bars',1000):
            raise DataGap('Missing-candle backlog exceeds recovery limit')
        end = min(latest+self.interval,next_time+500*self.interval)
        self.cache.bars.clear()
        for symbol in self.symbols:
            rows = await self.request('/api/v1/kline/query',{'symbol':MAPPING[symbol],
                      'granularity':self.interval//60000,'from':next_time,'to':end-1})
            self.cache.bars[(symbol,next_time,end)] = klines(rows,next_time,end,self.interval,
                                                            float(self.rules[symbol].contract_size))
        if not self.ready() or self.store.get('stop',False):
            return 0
        self.cache.server_time = server_time
        self.paper_recovery = checkpoint is not None and latest > next_time
        n=self.worker.tick()
        if n:self.counts['paper_batches'] += 1
        return n

    async def session(self, reconnect_after=None):
        if self.connector is None:
            from websockets.asyncio.client import connect
            self.connector = connect
        if self.counts['connections']:
            rows=await self.request('/api/v1/contracts/active')
            _,current=contracts(rows,self.symbols,self.worker.risk.leverage)
            if current != self.normalized:
                raise DataGap('Contract metadata changed; existing account frozen')
        info = await self.request('/api/v1/bullet-public')
        server = token_server(info)
        self.session_id = uuid4().hex
        if self.store.get('checkpoint') is not None:
            self.counts['checkpoint_resumes'] += 1
        uri = server['endpoint']+('' if server['endpoint'].endswith('/') else '/')+'?'+urlencode(
            {'token':info['token'],'connectId':self.session_id})
        self.sequences.clear();self.event_times.clear();self.last.clear()
        for book in self.books.values():
            book.reset()
        queue = asyncio.Queue(maxsize=self.queue_size)
        welcome,all_acks = asyncio.Event(),asyncio.Event()
        subscriptions = {f'{channel}-{symbol}':f'/contractMarket/{channel}:{MAPPING[symbol]}'
                         for symbol in self.symbols for channel in TOPICS}
        acked = set()
        ping = {'id':None,'sent':0.0}
        self.connected = False
        self.health()

        async with self.connector(uri,ssl=ssl.create_default_context(),proxy=True,
                                  open_timeout=15,close_timeout=3,ping_interval=None,
                                  max_queue=1024,max_size=2**20,compression=None) as ws:
            async def receive():
                async for payload in ws:
                    msg = json.loads(payload)
                    kind = msg.get('type')
                    if kind == 'welcome':
                        welcome.set()
                    elif kind == 'ack':
                        if str(msg.get('id')) not in subscriptions:
                            raise DataGap('Unknown subscription acknowledgement')
                        acked.add(str(msg['id']))
                        self.acked_topics.add(subscriptions[str(msg['id'])])
                        if len(acked)==len(subscriptions):all_acks.set()
                    elif kind == 'pong':
                        if str(msg.get('id')) == ping['id']:
                            ping['id']=None
                            self.counts['pongs'] += 1
                    elif kind == 'message':
                        try:queue.put_nowait(msg)
                        except asyncio.QueueFull as exc:raise DataGap('Bounded event buffer overflow') from exc
                    elif kind == 'error':
                        raise DataGap('WebSocket error frame')
                raise ConnectionError('Public WebSocket closed')

            async def heartbeat():
                interval = server['pingInterval']/1000*.8
                timeout = server['pingTimeout']/1000
                last_ping = time.monotonic()
                while True:
                    await asyncio.sleep(.2)
                    t = time.monotonic()
                    if ping['id'] is not None and t-ping['sent'] > timeout:
                        raise DataGap('Public WebSocket pong timeout')
                    if ping['id'] is None and t-last_ping >= interval:
                        ping['id'],ping['sent'] = uuid4().hex,t
                        await ws.send(canonical({'id':ping['id'],'type':'ping'}))
                        last_ping=t

            async def consume():
                while True:
                    first = await queue.get()
                    batch=[first]
                    for _ in range(99):
                        try:batch.append(queue.get_nowait())
                        except asyncio.QueueEmpty:break
                    with self.store.transaction():
                        for message in batch:self.ingest(message)
                    await asyncio.sleep(0)

            async def paper():
                while True:
                    await self.paper_once()
                    await asyncio.sleep(self.poll_seconds)

            async def monitor():
                start = time.monotonic()
                verified = False
                while True:
                    await asyncio.sleep(1)
                    ready = self.health()
                    if ready and not verified:
                        self.counts['verified_sessions'] += 1;verified=True
                    age=time.monotonic()-start
                    if age > self.stale_ms/1000 and not ready:
                        raise DataGap('Stale or missing required trade/quote/book stream')
                    if age >= min(self.renew_seconds,reconnect_after or self.renew_seconds):
                        self.counts['renewals'] += 1
                        raise RenewConnection('Public token renewal/reconnect')

            try:
                async with asyncio.TaskGroup() as tasks:
                    tasks.create_task(receive());tasks.create_task(heartbeat())
                    await asyncio.wait_for(welcome.wait(),15)
                    self.counts['connections'] += 1
                    for sub_id,topic in subscriptions.items():
                        await ws.send(canonical({'id':sub_id,'type':'subscribe','topic':topic,
                                                'privateChannel':False,'response':True}))
                    await asyncio.wait_for(all_acks.wait(),15)
                    # Receiver buffers changes from the already subscribed socket.
                    for symbol in self.symbols:
                        snapshot=await self.request('/api/v1/level2/snapshot',{'symbol':MAPPING[symbol]})
                        self.books[symbol].snapshot(snapshot,now_ms())
                    self.connected=True
                    tasks.create_task(consume());tasks.create_task(paper());tasks.create_task(monitor())
            finally:
                self.connected=False
                for book in self.books.values():book.reset()
                self.health()

    async def run(self,seconds=None,reconnect_after=None):
        started=time.monotonic()
        await self.initialize()
        delay=1
        while seconds is None or time.monotonic()-started < seconds:
            remaining=None if seconds is None else seconds-(time.monotonic()-started)
            try:
                if remaining is None:
                    await self.session(reconnect_after)
                else:
                    await asyncio.wait_for(self.session(reconnect_after),remaining)
            except asyncio.TimeoutError:
                if seconds is not None and time.monotonic()-started >= seconds:break
                self.record_error('TimeoutError: public connection or acknowledgement timed out')
            except Exception as exc:
                leaf=exc
                while isinstance(leaf,BaseExceptionGroup):leaf=leaf.exceptions[0]
                if not isinstance(leaf,RenewConnection):
                    text=re.sub(r'([?&]token=)[^&\s]+',r'\1[redacted]',str(leaf))
                    self.record_error(f'{type(leaf).__name__}: {text}')
            self.counts['reconnects'] += 1
            remaining=delay if seconds is None else min(delay,max(0,seconds-(time.monotonic()-started)))
            await asyncio.sleep(remaining)
            delay=1 if self.counts['verified_sessions'] else min(delay*2,30)

    def record_error(self,text):
        self.counts['errors'] += 1
        self.errors.append(text)
        self.errors=self.errors[-20:]
        self.store.event('kucoin_error',text)
        self.store.set('heartbeat',{'time':now_ms(),'status':'error','error':text})

    def report(self,require_reconnect=False):
        rows=self.store.db.execute('SELECT symbol,channel,count(*) FROM market_events GROUP BY symbol,channel').fetchall()
        counts={s:{k:0 for k in TOPICS} for s in self.symbols}
        for symbol,channel,n in rows:counts[symbol][channel]=n
        decisions=self.store.db.execute('SELECT count(*) FROM paper_decisions').fetchone()[0]
        passed=(len(self.normalized)==len(self.symbols) and self.counts['verified_sessions'] >= (2 if require_reconnect else 1)
                and all(all(v>0 for v in c.values()) for c in counts.values())
                and self.counts['pongs']>0 and decisions>0 and self.counts['paper_batches']>0
                and (not require_reconnect or self.counts['checkpoint_resumes']>0))
        return {'status':'passed' if passed else 'not_verified','simulation_only':True,
                'provider':'KuCoin Classic Futures public WebSocket','runner':'github-actions' if os.getenv('GITHUB_ACTIONS') else 'local',
                'counts':dict(self.counts),'market_event_counts':counts,'subscription_acks':sorted(self.acked_topics),
                'sequence_verified_symbols':sorted(self.verified_symbols),'paper_decision_batches':decisions,
                'paper_metrics':self.store.get('metrics'),'contracts':self.normalized,
                'errors':self.errors,'reconnect_required':require_reconnect,
                'rest_provenance':[{'fetched_at':t,'url':url,'sha256':sha} for t,url,sha in self.store.db.execute(
                    'SELECT fetched_at,url,sha256 FROM responses ORDER BY id')],
                'source_sha256':{str(p):digest(p.read_bytes()) for p in (Path(__file__),Path(__file__).parent/'providers'/'kucoin.py')},
                'limitations':['Bounded connectivity/persistence check, not a profitability test or production soak.',
                  'Strategy uses KuCoin closed OHLCV via REST; WebSocket trade/quote/L2 feeds gate readiness, not order-flow signals.',
                  'Candle-simulated fills, fixed spread/slippage, conservative funding scenario; no executable quote or liquidation guarantee.',
                  'Restart/outage candle catch-up is retrospective paper accounting, not live fills observed during an outage.',
                  'Trade/ticker sequence monotonicity is checked; their gaps are not assumed contiguous. L2 requires exact +1 bridging.',
                  'No private credentials, live orders, or external trading actions.']}


def main(argv=None):
    parser=argparse.ArgumentParser(description='KuCoin public Futures stream and paper service; no live orders')
    parser.add_argument('command',choices=['run','smoke'])
    parser.add_argument('--config',type=Path,default=Path('configs/kucoin.json'))
    parser.add_argument('--db',type=Path,default=Path('state/kucoin.sqlite3'))
    parser.add_argument('--seconds',type=int,default=120)
    parser.add_argument('--reconnect-after',type=int,default=40)
    parser.add_argument('--report',type=Path,default=Path('reports/kucoin-connection.json'))
    args=parser.parse_args(argv)
    if not 30 <= args.seconds <= 300 or not 15 <= args.reconnect_after < args.seconds:
        parser.error('Smoke requires 30..300 seconds and reconnect-after in [15, seconds)')
    config=json.loads(args.config.read_text())
    store=Store(args.db)
    engine=Engine(store,config)
    fatal = False
    async def managed_run():
        import signal
        loop = asyncio.get_running_loop()
        task = asyncio.current_task()
        loop.add_signal_handler(signal.SIGTERM,task.cancel)
        await engine.run(args.seconds if args.command=='smoke' else None,
                         args.reconnect_after if args.command=='smoke' else None)
    try:
        with single_worker(args.db):
            try:
                asyncio.run(managed_run())
            except (KeyboardInterrupt,asyncio.CancelledError):
                pass
            except Exception as exc:
                fatal = True
                engine.record_error(f'{type(exc).__name__}: {exc}')
            report=engine.report(require_reconnect=args.command=='smoke')
            report['recorded_at_ms']=now_ms()
            report['duration_seconds_requested']=args.seconds if args.command=='smoke' else None
            args.report.parent.mkdir(parents=True,exist_ok=True)
            args.report.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
            print(json.dumps(report,indent=2,allow_nan=False))
            store.set('heartbeat',{'time':now_ms(),'status':'shutdown','error':None})
            return 0 if not fatal and (args.command=='run' or report['status']=='passed') else 1
    finally:
        store.close()


if __name__=='__main__':
    raise SystemExit(main())
