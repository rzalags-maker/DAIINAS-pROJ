"""Synthetic protocol fixtures. Real evidence is produced only by the smoke CLI."""
import asyncio
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from daiinas.data import digest
from daiinas.models import RiskConfig
from daiinas.risk import size
from daiinas.service import Store, now_ms
from daiinas.providers.kucoin import (MAPPING,TOPICS,DataGap,PublicRest,OrderBook,
                                     contracts,execution,ticker,token_server,klines,timestamp)
from daiinas.kucoin_service import Engine,RenewConnection


def metadata():
    return [{'symbol':exchange,'baseCurrency':'XBT' if s=='BTCUSDT' else s[:-4],
             'status':'Open','quoteCurrency':'USDT','settleCurrency':'USDT',
             'isInverse':False,'expireDate':None,'type':'FFWCSX','maxLeverage':50,
             'initialMargin':.02,'lotSize':1,'maxOrderQty':100000,'tickSize':.1,
             'multiplier':.001,'takerFeeRate':.0006} for s,exchange in MAPPING.items()]


def config():
    return {'symbols':list(MAPPING),'interval':'1m','strategy':{'lookback':2,'atr_period':2},
            'risk':{},'poll_seconds':1,'max_catchup_bars':1000,'stale_seconds':30,
            'queue_size':1000,'token_renew_seconds':72000}


def snapshot(symbol, t, seq=100):
    return {'symbol':MAPPING[symbol],'sequence':seq,'ts':t*1_000_000,
            'bids':[['99',2]],'asks':[['101',2]]}


def event(symbol,channel,t,seq=101):
    data={'symbol':MAPPING[symbol],'sequence':seq,'ts':t*1_000_000}
    if channel=='execution':
        data.update(side='buy',size=2,price='100',tradeId=str(seq))
    elif channel=='tickerV2':
        data.update(bestBidPrice='99',bestAskPrice='101',bestBidSize=2,bestAskSize=3)
    else:
        data={'sequence':seq,'timestamp':t,'change':'99,buy,3'}
    return {'type':'message','topic':f'/contractMarket/{channel}:{MAPPING[symbol]}','data':data}


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.rules,self.normalized=contracts(metadata(),list(MAPPING),3)
        self.rule=self.rules['BTCUSDT']
        self.t=now_ms()
        self.book=OrderBook('BTCUSDT',self.rule)
        self.book.snapshot(snapshot('BTCUSDT',self.t),self.t)

    def test_mapping_contract_multiplier_and_minimum(self):
        self.assertEqual(MAPPING['BTCUSDT'],'XBTUSDTM')
        self.assertEqual(self.rule.contract_size,'0.001')
        self.assertEqual(self.rule.min_qty,'1')
        self.assertEqual(self.rule.min_notional,'0')
        self.assertEqual(self.normalized['BTCUSDT']['min_notional_source'],'not published; lotSize enforced')
        risk=RiskConfig()
        q=size(8,6.4,100000,99000,self.rule,risk)
        self.assertEqual(q,0)  # one contract exceeds BOTH capital and planned risk
        self.assertEqual(self.rule.quantity(3.99),3)

    def test_invalid_contract_or_leverage_rejected(self):
        for key,value in [('status','Paused'),('isInverse',True),('settleCurrency','BTC'),('multiplier',-1)]:
            rows=metadata();rows[0][key]=value
            with self.assertRaises(ValueError):contracts(rows,list(MAPPING),3)
        with self.assertRaises(DataGap):contracts(metadata(),list(MAPPING),51)

    def test_snapshot_is_not_yet_verified(self):
        self.assertFalse(self.book.verified)
        with self.assertRaises(DataGap):self.book.view()

    def test_buffer_bridge_duplicate_and_level_deletion(self):
        self.assertFalse(self.book.delta({'sequence':100},self.t))
        self.assertTrue(self.book.delta(event('BTCUSDT','level2',self.t)['data'],self.t))
        self.assertTrue(self.book.verified)
        view=self.book.view()
        self.assertEqual(view.bids[0],(99.0,.003))
        self.book.delta({'sequence':102,'timestamp':self.t,'change':'98,buy,4'},self.t)
        self.book.delta({'sequence':103,'timestamp':self.t,'change':'99,buy,0'},self.t)
        self.assertEqual(self.book.view().bids[0][0],98)

    def test_missing_sequence_invalidates_book(self):
        with self.assertRaisesRegex(DataGap,'sequence gap'):
            self.book.delta({'sequence':102,'timestamp':self.t,'change':'99,buy,2'},self.t)
        self.assertFalse(self.book.verified)
        self.assertIsNone(self.book.sequence)

    def test_crossed_book_invalidates(self):
        with self.assertRaises(DataGap):
            self.book.delta({'sequence':101,'timestamp':self.t,'change':'102,buy,2'},self.t)
        self.assertIsNone(self.book.sequence)

    def test_bad_tick_size_or_timestamp_invalidates(self):
        for row in [{'sequence':101,'timestamp':self.t,'change':'99.01,buy,2'},
                    {'sequence':101,'timestamp':self.t-20000,'change':'99,buy,2'}]:
            self.book.snapshot(snapshot('BTCUSDT',self.t),self.t)
            with self.assertRaises(DataGap):self.book.delta(row,self.t)
            self.assertFalse(self.book.verified)

    def test_nanosecond_and_millisecond_units(self):
        self.assertEqual(timestamp(self.t*1_000_000,'ns',self.t),self.t)
        for val,unit in [(self.t,'ns'),(self.t+4000,'ms'),(self.t-20000,'ms')]:
            with self.assertRaises(DataGap):timestamp(val,unit,self.t)

    def test_trade_and_bbo_normalize_base_sizes(self):
        trade=execution('BTCUSDT',event('BTCUSDT','execution',self.t)['data'],self.rule,self.t)
        self.assertEqual(trade.quantity,.002)
        self.assertFalse(trade.buyer_is_maker)
        quote=ticker('BTCUSDT',event('BTCUSDT','tickerV2',self.t)['data'],self.rule,self.t)
        self.assertEqual(quote['ask_base_size'],.003)

    def test_rest_closed_candle_completeness(self):
        rows=[[60000,100,101,99,100,2],[0,100,101,99,100,3]]
        bars=klines(rows,0,120000,60000,.001)
        self.assertEqual(bars[0].volume,.003)
        with self.assertRaises(DataGap):klines(rows[:1],0,120000,60000,.001)
        with self.assertRaises(DataGap):klines(rows+[rows[0]],0,120000,60000,.001)

    def test_token_endpoint_trust_boundary_and_no_order_api(self):
        server={'endpoint':'wss://ws-api-futures.kucoin.com','encrypt':True,'protocol':'websocket',
                'pingInterval':18000,'pingTimeout':10000}
        self.assertEqual(token_server({'token':'test','instanceServers':[server]}),server)
        for endpoint in ['ws://ws-api-futures.kucoin.com','wss://evil.example','wss://user@ws-api-futures.kucoin.com','wss://ws-api-futures.kucoin.com?token=bad']:
            with self.assertRaises(DataGap):token_server({'token':'test','instanceServers':[{**server,'endpoint':endpoint}]})
        with self.assertRaises(ValueError):PublicRest().request('/api/v1/orders')
        with self.assertRaises(ValueError):PublicRest().request('/api/v1/bullet-private')


class FakeRest:
    def __init__(self):
        self.t=now_ms()
        self.calls=[]
        self.gap=False

    def request(self,path,params=None):
        self.calls.append((path,params))
        if path.endswith('/active'):data=metadata()
        elif path.endswith('/timestamp'):data=self.t
        elif path.endswith('/bullet-public'):
            data={'token':'PUBLIC_TOKEN_MUST_NOT_BE_SAVED','instanceServers':[{
                'endpoint':'wss://ws-api-futures.kucoin.com','encrypt':True,'protocol':'websocket',
                'pingInterval':1000,'pingTimeout':1000}]}
        elif path.endswith('/snapshot'):
            symbol=next(s for s,v in MAPPING.items() if v==params['symbol'])
            data=snapshot(symbol,self.t)
        elif path.endswith('/query'):
            step=params['granularity']*60000
            data=[[t,100,101,99,100,10] for t in range(params['from'],params['to']+1,step)]
            if self.gap:data=data[:-1]
        else:raise AssertionError(path)
        return data,json.dumps({'code':'200000','data':data}).encode(),'https://api-futures.kucoin.com'+path


class FakeSocket:
    def __init__(self,rest,pong=True):
        self.rest,self.pong=rest,pong
        self.queue=asyncio.Queue()
        self.subscriptions=[]
        self.feeder=None

    async def __aenter__(self):
        await self.queue.put({'type':'welcome'})
        return self

    async def __aexit__(self,*args):
        if self.feeder:
            self.feeder.cancel()
            try:await self.feeder
            except asyncio.CancelledError:pass

    def __aiter__(self):return self

    async def __anext__(self):
        return json.dumps(await self.queue.get())

    async def send(self,text):
        msg=json.loads(text)
        if msg['type']=='subscribe':
            self.subscriptions.append(msg['topic'])
            await self.queue.put({'type':'ack','id':msg['id']})
            if len(self.subscriptions)==len(MAPPING)*3:
                self.feeder=asyncio.create_task(self.feed())
        elif msg['type']=='ping' and self.pong:
            await self.queue.put({'type':'pong','id':msg['id']})

    async def feed(self):
        seq=101
        while True:
            for symbol in MAPPING:
                for channel in TOPICS:
                    await self.queue.put(event(symbol,channel,self.rest.t,seq))
            seq+=1
            await asyncio.sleep(.05)


class EngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'kucoin.sqlite3'
        self.store=Store(self.path)
        self.rest=FakeRest()
        self.engine=Engine(self.store,config(),self.rest)
        await self.engine.initialize()

    async def asyncTearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def make_ready(self):
        self.engine.connected=True
        seq=101+getattr(self,'ready_count',0)*1000
        self.ready_count=getattr(self,'ready_count',0)+1
        for symbol,book in self.engine.books.items():
            book.snapshot(snapshot(symbol,self.rest.t,seq-1),self.rest.t)
            for channel in TOPICS:self.engine.ingest(event(symbol,channel,self.rest.t,seq))

    async def test_paper_checkpoint_audit_and_atomic_failure(self):
        self.make_ready()
        n=await self.engine.paper_once()
        self.assertEqual(n,1)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM paper_decisions').fetchone()[0],1)
        first=self.store.get('checkpoint')
        self.rest.t+=60000
        with patch('daiinas.kucoin_service.now_ms',return_value=self.rest.t),patch('daiinas.service.now_ms',return_value=self.rest.t):
            self.make_ready()
            with patch.object(self.store,'event',side_effect=OSError('disk failure')):
                with self.assertRaises(OSError):await self.engine.paper_once()
            self.assertEqual(self.store.get('checkpoint'),first)
            self.assertEqual(await self.engine.paper_once(),1)
        self.assertGreater(self.store.get('checkpoint')['last_time'],first['last_time'])

    async def test_pause_and_gaps_never_advance_account(self):
        self.make_ready()
        self.store.control(True)
        self.assertEqual(await self.engine.paper_once(),0)
        self.assertIsNone(self.store.get('checkpoint'))
        self.store.control(False)
        self.rest.gap=True
        with self.assertRaises(DataGap):await self.engine.paper_once()
        self.assertIsNone(self.store.get('checkpoint'))

    async def test_unverified_book_blocks_paper(self):
        self.make_ready()
        self.engine.books['BTCUSDT'].reset()
        self.assertFalse(self.engine.ready())
        self.assertEqual(await self.engine.paper_once(),0)

    async def test_duplicate_conflict_and_stream_monotonicity(self):
        self.make_ready()
        msg=event('BTCUSDT','execution',self.rest.t)
        before=self.store.db.execute('SELECT count(*) FROM market_events').fetchone()[0]
        self.engine.ingest(msg)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM market_events').fetchone()[0],before)
        bad=event('BTCUSDT','execution',self.rest.t,100)
        with self.assertRaises(DataGap):self.engine.ingest(bad)
        bad=event('BTCUSDT','execution',self.rest.t)
        bad['data']['price']='100.1'
        with self.assertRaises(DataGap):self.engine.ingest(bad)

    async def test_restarted_engine_restores_account_and_never_restores_book_trust(self):
        self.make_ready()
        await self.engine.paper_once()
        checkpoint=self.store.get('checkpoint')
        self.store.close();self.store=Store(self.path)
        self.engine=Engine(self.store,config(),self.rest)
        await self.engine.initialize()
        self.assertEqual(self.store.get('checkpoint'),checkpoint)
        self.assertFalse(self.engine.ready())
        self.assertFalse(any(b.verified for b in self.engine.books.values()))

    async def test_changed_multiplier_does_not_reuse_existing_account(self):
        self.make_ready();await self.engine.paper_once()
        original=self.rest.request
        def changed(path,params=None):
            data,payload,url=original(path,params)
            if path.endswith('/active'):
                data[0]['multiplier']=.01
                payload=json.dumps({'code':'200000','data':data}).encode()
            return data,payload,url
        self.rest.request=changed
        with self.assertRaisesRegex(ValueError,'identity changed'):
            await Engine(self.store,config(),self.rest).initialize()

    async def test_socket_subscription_pong_token_renewal_and_checkpoint_resume(self):
        self.engine.connector=lambda *args,**kwargs:FakeSocket(self.rest)
        await self.engine.run(seconds=3.3,reconnect_after=1)
        self.assertGreaterEqual(self.engine.counts['connections'],2)
        self.assertGreater(self.engine.counts['pongs'],0)
        self.assertGreater(self.engine.counts['checkpoint_resumes'],0)
        self.assertGreaterEqual(self.engine.counts['verified_sessions'],2)
        self.assertTrue(self.store.get('checkpoint'))
        bodies=b''.join(row[0] for row in self.store.db.execute('SELECT payload FROM responses'))
        self.assertNotIn(b'PUBLIC_TOKEN_MUST_NOT_BE_SAVED',bodies)
        self.assertEqual(self.engine.report(True)['status'],'passed')
        self.assertFalse(self.engine.ready())  # shutdown invalidates every book

    async def test_missing_pong_forces_reconnect(self):
        self.engine.connector=lambda *args,**kwargs:FakeSocket(self.rest,pong=False)
        await self.engine.run(seconds=2.8)
        self.assertTrue(any('pong timeout' in e for e in self.engine.errors))
        self.assertFalse(self.engine.ready())

    async def test_report_does_not_claim_connectivity_from_metadata(self):
        self.assertEqual(self.engine.report()['status'],'not_verified')
        self.assertEqual(self.engine.counts['connections'],0)


if __name__=='__main__':unittest.main()
