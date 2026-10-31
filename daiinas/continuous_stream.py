"""v3.3 continuous dynamic public streams, reusing the v3 Observer decoder.

Only public REST and public WebSocket subscriptions. LIVE ORDERS DISABLED.
"""
import asyncio
from collections import Counter
from dataclasses import asdict
from pathlib import Path
import ssl
import time
from urllib.parse import urlencode
from uuid import uuid4
import json

from .universe_observer import Observer,public_get,now_ms,canonical
from .universe import Policy
from .universe_rotation import RotationPolicy
from .providers.kucoin import OrderBook,DataGap,SequenceGap,token_server
from .risk import ContractRules

CHANNELS=('execution','tickerV2','level2')


class ContinuousObserver(Observer):
    def __init__(self,pipeline,*,source_path,deep=5,refresh_seconds=180,dwell_ms=120000,
                 connector=None,rest=None,market_get=None,ack_timeout=15,queue_size=20000):
        if not 3<=deep<=8 or refresh_seconds<1 or not 1<=ack_timeout<=60 or not 100<=queue_size<=100000:
            raise ValueError('Invalid continuous subscription bounds')
        super().__init__(equity=8,deep=deep,db=source_path,connector=connector,rest=rest,dwell_ms=dwell_ms)
        self.pipeline=pipeline
        self.refresh_seconds=refresh_seconds
        self.market_get=market_get or public_get
        self.ack_timeout=ack_timeout
        self.queue_size=queue_size
        self.active=set();self.retired=set();self.acks={};self.session_id=None
        self.connected=False;self.snapshot_buffers={};self.snapshotting=set()
        self.reconcile_lock=asyncio.Lock()
        self.last_seen={};self.last_wire={}
        self.stream_stats=Counter()

    async def preflight(self,pinned=()):
        # Actual pins are selected atomically on the ledger writer thread, not
        # a stale caller-provided position list. Metadata never moves backwards.
        rows,ticks=await asyncio.gather(asyncio.to_thread(self.market_get,'/api/v1/contracts/active'),
                                      asyncio.to_thread(self.market_get,'/api/v1/allTickers'))
        result=await self.pipeline.scan(rows,ticks,self.policy,self.rotation)
        self.watch=result['watch'];self.last_scan=result
        for sym,spec in result['specs'].items():self.contracts[sym]=ContractRules(**spec['rules'])
        self.stream_stats['market_scans']+=1
        return result

    async def health_event(self,state,symbol=None,reason=None):
        payload={'state':state,'session_id':self.session_id,'symbol':symbol}
        if reason:payload['reason']=str(reason)[:500]
        await self.pipeline.append([('HEALTH',f'health:{uuid4().hex}',payload)])

    def acknowledge(self,msg):
        ident=str(msg.get('id'))
        future=self.acks.get(ident)
        if future is None:raise DataGap('Unexpected subscription ACK')
        if not future.done():future.set_result(True)

    async def command(self,ws,symbol,operation):
        waiting=[]
        try:
            for channel in CHANNELS:
                ident=uuid4().hex
                future=asyncio.get_running_loop().create_future()
                self.acks[ident]=future;waiting.append((ident,future))
                await ws.send(canonical({'id':ident,'type':operation,'topic':f'/contractMarket/{channel}:{symbol}',
                                         'privateChannel':False,'response':True}))
            await asyncio.wait_for(asyncio.gather(*(future for _,future in waiting)),self.ack_timeout)
            self.stream_stats[operation+'_acks']+=len(waiting)
        finally:
            for ident,_ in waiting:self.acks.pop(ident,None)

    async def snapshot(self,symbol):
        data,_,_=await asyncio.to_thread(self.rest.request,'/api/v1/level2/snapshot',{'symbol':symbol})
        self.books[symbol].snapshot(data,now_ms())
        self.stream_stats['snapshots']+=1

    def normalize(self,msg,wire_received):
        sym=msg['topic'].split(':',1)[1]
        channel=msg['topic'].split(':',1)[0].removeprefix('/contractMarket/')
        old=super()._process(msg)
        if old is None:return None
        symbol,channel,key,t,received,raw,normalized=old
        if channel=='level2':
            book=self.books[sym];unit=float(self.contracts[sym].contract_size)
            normalized={**normalized,'bid_base_size':float(book.bids[max(book.bids)])*unit,
                        'ask_base_size':float(book.asks[min(book.asks)])*unit}
        self.last_seen[(sym,channel)]=received
        payload={'symbol':symbol,'channel':channel,'event_key':key,'event_ms':t,
                 'received_ms':received,'wire_received_ms':wire_received,
                 'session_id':self.session_id,'raw':raw,'normalized':normalized}
        return ('MARKET',f'market:{symbol}:{channel}:{key}',payload)

    async def reconcile(self,ws):
        async with self.reconcile_lock:
            account=await self.pipeline.report()
            desired=set(self.watch['deep_symbols'])|set(account['pins'])
            if len(desired)>20:raise DataGap('Pinned risks exceed provider hard capacity')
            additions=desired-self.active
            removals=self.active-desired
            # Add first whenever possible; unprotected removals never remove pins.
            if len(self.active|additions)>20:
                raise DataGap('Temporary subscription capacity exhausted; new entries blocked')
            changed=[s for s in self.active&desired if s in self.books and self.books[s].rule!=self.contracts[s]]
            for sym in changed:
                self.snapshotting.add(sym);self.snapshot_buffers[sym]=[]
                self.books[sym]=OrderBook(sym,self.contracts[sym],exchange_symbol=sym)
                await self.health_event('CONTRACT_BOOK_RESET',sym)
                await self.restore_book(sym)
            for sym in sorted(additions):
                if sym not in self.contracts:raise DataGap('Pinned symbol has no last-known public contract rules')
                self.books[sym]=OrderBook(sym,self.contracts[sym],exchange_symbol=sym)
                self.snapshotting.add(sym);self.snapshot_buffers[sym]=[]
                self.active.add(sym);self.retired.discard(sym)
                await self.command(ws,sym,'subscribe')
                await self.restore_book(sym)
            for sym in sorted(removals):
                # A ledger transition could have pinned this symbol while ACKs
                # were pending. Recheck before ANY unsubscribe.
                if sym in (await self.pipeline.report())['pins']:continue
                await self.command(ws,sym,'unsubscribe')
                self.active.discard(sym);self.retired.add(sym)
                self.books.pop(sym,None);self.snapshot_buffers.pop(sym,None)
                self.snapshotting.discard(sym)
                for key in list(self.sequences):
                    if key[0]==sym:self.sequences.pop(key,None);self.last_event_times.pop(key,None)
                self.stream_stats['retired_markets']+=1
            self.stream_stats['reconciliations']+=1

    async def restore_book(self,symbol):
        self.snapshotting.add(symbol)
        self.snapshot_buffers.setdefault(symbol,[])
        for attempt in range(3):
            await self.snapshot(symbol)
            buffered=self.snapshot_buffers[symbol];self.snapshot_buffers[symbol]=[]
            packets=[]
            try:
                for msg,received in buffered:
                    packet=self.normalize(msg,received)
                    if packet:packets.append(packet)
                # Release the buffer BEFORE yielding to the writer: newer
                # deltas then follow this batch in the serialized write queue.
                self.snapshotting.discard(symbol)
                if packets:await self.pipeline.append(packets)
                self.stream_stats['book_resyncs']+=1
                return
            except SequenceGap:
                self.snapshot_buffers[symbol]=buffered+self.snapshot_buffers[symbol]
                if len(self.snapshot_buffers[symbol])>self.queue_size:raise DataGap('Book restore overflow')
        raise DataGap('Book restore retry limit exceeded')

    async def session(self,*,seconds=None,renew_after=72000):
        if not 1<=renew_after<=72000:raise ValueError('Public token renewal must be before 24 hours')
        if self.connector is None:
            from websockets.asyncio.client import connect
            self.connector=connect
        info,_,_=await asyncio.to_thread(self.rest.request,'/api/v1/bullet-public')
        server=token_server(info)
        self.session_id=uuid4().hex
        uri=server['endpoint'].rstrip('/')+'/?'+urlencode({'token':info['token'],'connectId':self.session_id})
        queue=asyncio.Queue(maxsize=self.queue_size)
        welcome=asyncio.Event();ping={'id':None,'sent':0.}
        self.active.clear();self.retired.clear();self.sequences.clear();self.last_event_times.clear()
        self.books.clear();self.snapshotting.clear();self.snapshot_buffers.clear();self.last_seen.clear()
        started=time.monotonic()
        async with self.connector(uri,ssl=ssl.create_default_context(),proxy=True,open_timeout=15,
                                  close_timeout=3,ping_interval=None,max_queue=2048,max_size=2**20,compression=None) as ws:
            async def receive():
                while True:
                    msg=json.loads(await ws.recv());kind=msg.get('type')
                    if kind=='welcome':welcome.set()
                    elif kind=='ack':self.acknowledge(msg)
                    elif kind=='pong' and str(msg.get('id'))==ping['id']:
                        ping['id']=None;self.stream_stats['pongs']+=1
                    elif kind=='error':raise DataGap('Public subscription error frame')
                    elif kind=='message':
                        try:queue.put_nowait((msg,now_ms()))
                        except asyncio.QueueFull as exc:raise DataGap('Bounded market queue overflow') from exc

            async def consume():
                while True:
                    batch=[await queue.get()]
                    for _ in range(99):
                        try:batch.append(queue.get_nowait())
                        except asyncio.QueueEmpty:break
                    packets=[]
                    for msg,received in batch:
                        sym=msg.get('topic','').split(':')[-1]
                        if sym not in self.active:
                            if sym in self.retired:self.stream_stats['late_retired_frames']+=1;continue
                            raise DataGap('Unknown active subscription')
                        channel=msg['topic'].split(':')[0].removeprefix('/contractMarket/')
                        if channel=='level2' and sym in self.snapshotting:
                            self.snapshot_buffers[sym].append((msg,received))
                            if len(self.snapshot_buffers[sym])>self.queue_size:raise DataGap('Book buffer overflow')
                            continue
                        try:
                            packet=self.normalize(msg,received)
                            if packet:packets.append(packet)
                        except SequenceGap as exc:
                            self.stream_stats['book_gaps']+=1
                            if packets:await self.pipeline.append(packets);packets=[]
                            await self.health_event('BOOK_GAP',sym,str(exc))
                            self.snapshotting.add(sym);self.snapshot_buffers[sym]=[(msg,received)]
                            tasks.create_task(self.restore_book(sym))
                    if packets:await self.pipeline.append(packets)

            async def refresh():
                delay=self.refresh_seconds
                while True:
                    await asyncio.sleep(delay)
                    try:
                        await self.preflight()
                        delay=self.refresh_seconds
                    except (OSError,ValueError) as exc:
                        # An invalid/stale scan never replaces as-of state. Pins
                        # and currently acknowledged subscriptions stay alive.
                        self.stream_stats['scan_failures']+=1
                        await self.health_event('SCAN_UNAVAILABLE',reason=type(exc).__name__)
                        delay=min(300,max(self.refresh_seconds,delay*2))
                    else:
                        await self.reconcile(ws)

            async def heartbeat():
                last_ping=time.monotonic()
                while True:
                    await asyncio.sleep(.2);t=time.monotonic()
                    if ping['id'] and t-ping['sent']>server['pingTimeout']/1000:raise DataGap('Public pong timeout')
                    if not ping['id'] and t-last_ping>=server['pingInterval']/1000*.75:
                        ping['id']=uuid4().hex;ping['sent']=last_ping=t
                        await ws.send(canonical({'id':ping['id'],'type':'ping'}))
                    if t-started>=renew_after:raise ConnectionError('Scheduled public token renewal')

            try:
                async with asyncio.TaskGroup() as tasks:
                    tasks.create_task(receive());tasks.create_task(heartbeat());tasks.create_task(consume())
                    await asyncio.wait_for(welcome.wait(),self.ack_timeout)
                    self.connected=True;self.stream_stats['connections']+=1
                    await self.health_event('CONNECTED')
                    await self.reconcile(ws)
                    tasks.create_task(refresh())
                    await asyncio.Future()
            finally:
                self.connected=False
                for book in self.books.values():book.reset()
                await self.health_event('DISCONNECTED')

    def runtime(self):
        now=now_ms()
        return {'connected':self.connected,'session_id':self.session_id,'active':sorted(self.active),
                'verified_books':sorted(s for s,b in self.books.items() if b.verified),
                'feed_age_ms':{s:{k:now-self.last_seen.get((s,k),0) for k in CHANNELS} for s in sorted(self.active)},
                'stream_counts':dict(self.stream_stats),'unavailable':self.last_scan.get('unavailable',[]) if self.last_scan else []}
