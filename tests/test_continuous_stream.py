"""v3.3 synthetic transport/rotation fixtures; no real exchange data claims."""
import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import json
from daiinas.continuous_paper import Pipeline
from daiinas.continuous_stream import ContinuousObserver
from daiinas.providers.kucoin import DataGap
from daiinas.universe import Policy
from daiinas.universe_rotation import RotationPolicy
from test_continuous_paper import market,scan,SYM


def metadata(sym):
    now=__import__('time').time_ns()//1_000_000
    return {'symbol':sym,'status':'Open','type':'FFWCSX','isInverse':False,'expireDate':None,
            'quoteCurrency':'USDT','settleCurrency':'USDT','firstOpenDate':now-30*86400000,
            'turnoverOf24h':10000000,'lotSize':1,'maxOrderQty':100000,'tickSize':.0001,
            'multiplier':.001,'takerFeeRate':.0006,'initialMargin':.02,'maxLeverage':50}


class Rest:
    def __init__(self):self.sequences={}
    def request(self,path,params=None):
        now=__import__('time').time_ns()//1_000_000
        if path.endswith('bullet-public'):
            return {'token':'ephemeral-not-logged','instanceServers':[{'endpoint':'wss://ws-api-futures.kucoin.com',
                    'protocol':'websocket','encrypt':True,'pingInterval':1000,'pingTimeout':1000}]},b'','public-token'
        if path.endswith('snapshot'):
            s=params['symbol'];self.sequences.setdefault(s,100)
            return {'symbol':s,'sequence':self.sequences[s],'ts':now*1_000_000,
                    'bids':[[1.,100]],'asks':[[1.0002,100]]},b'','public-book'
        raise AssertionError(path)


class Socket:
    def __init__(self,rest,ack=True,gap=False):
        self.rest,self.ack=rest,ack;self.gap=gap;self.gapped=False;self.queue=asyncio.Queue();self.active=set();self.sent=[];self.feeder=None
    async def __aenter__(self):
        await self.queue.put({'type':'welcome'});self.feeder=asyncio.create_task(self.feed());return self
    async def __aexit__(self,*args):
        self.feeder.cancel()
        try:await self.feeder
        except asyncio.CancelledError:pass
    async def recv(self):return json.dumps(await self.queue.get())
    async def send(self,text):
        m=json.loads(text);self.sent.append(m)
        if m['type']=='ping':await self.queue.put({'type':'pong','id':m['id']});return
        if self.ack:await self.queue.put({'type':'ack','id':m['id']})
        if m['type']=='subscribe':self.active.add(m['topic'])
        if m['type']=='unsubscribe':self.active.discard(m['topic'])
    async def feed(self):
        while True:
            t=__import__('time').time_ns()//1_000_000
            for topic in sorted(self.active):
                channel,s=topic.split(':');channel=channel.split('/')[-1]
                seq=self.rest.sequences.get(s,100)+1
                if channel=='level2':
                    if self.gap and not self.gapped and seq>=105:
                        seq+=2;self.gapped=True
                    self.rest.sequences[s]=seq
                data={'symbol':s,'sequence':seq,'ts':t*1_000_000}
                if channel=='execution':data.update(tradeId=f'{s}:{seq}',side='buy',size=1,price='1')
                elif channel=='tickerV2':data.update(bestBidPrice='1',bestAskPrice='1.0002',bestBidSize=100,bestAskSize=100)
                else:data={'sequence':seq,'timestamp':t,'change':'1,buy,100'}
                await self.queue.put({'type':'message','topic':topic,'data':data})
            await asyncio.sleep(.05)


class ContinuousStreamTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.pipeline=Pipeline(self.root/'source.sqlite3',self.root/'paper.sqlite3')
        self.rest=Rest();self.sockets=[]
        self.calls=0
        def get(path):
            t=__import__('time').time_ns()//1_000_000
            # The first market disappears on the second scan; all others remain.
            names=['AAAUSDTM','BBBUSDTM','CCCUSDTM'] if self.calls<2 else ['DDDUSDTM','BBBUSDTM','CCCUSDTM']
            self.calls+=1
            if path.endswith('active'):return [metadata(s) for s in names]
            return [{'symbol':s,'ts':t*1_000_000,'bestBidPrice':'1','bestAskPrice':'1.0002',
                     'bestBidSize':100,'bestAskSize':100} for s in names]
        def connector(*args,**kwargs):
            sock=Socket(self.rest);self.sockets.append(sock);return sock
        self.observer=ContinuousObserver(self.pipeline,source_path=self.root/'source.sqlite3',
                      deep=3,refresh_seconds=1,dwell_ms=0,connector=connector,rest=self.rest,market_get=get,ack_timeout=1)
    async def asyncTearDown(self):
        self.observer.close();self.pipeline.close();self.tmp.cleanup()

    async def test_multi_scan_rotation_is_acknowledged_in_same_connection(self):
        await self.observer.preflight()
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(self.observer.session(),2.4)
        self.assertEqual(len(self.sockets),1)
        sent=self.sockets[0].sent
        unsub=[x for x in sent if x['type']=='unsubscribe']
        self.assertEqual(len(unsub),3)
        self.assertTrue(all(x['topic'].endswith('AAAUSDTM') for x in unsub))
        self.assertGreaterEqual(self.observer.stream_stats['market_scans'],3)
        self.assertGreater(self.observer.stream_stats['pongs'],0)
        report=await self.pipeline.report()
        self.assertEqual(report['counts']['SCAN'],self.observer.stream_stats['market_scans'])

    async def test_missing_ack_cannot_claim_subscription_or_protection(self):
        self.observer.connector=lambda *a,**kw:Socket(self.rest,ack=False)
        await self.observer.preflight()
        with self.assertRaises(ExceptionGroup):await self.observer.session()
        self.assertEqual(self.observer.stream_stats['subscribe_acks'],0)
        report=await self.pipeline.report()
        self.assertFalse(report['service'])
        self.assertFalse(self.observer.connected)

    async def test_open_position_pin_is_selected_atomically_even_if_ineligible(self):
        # Initialize a real ledger transition with explicitly synthetic quotes.
        now=__import__('time').time_ns()//1_000_000
        packet=scan(now)
        packet[2]['report']['paper_contract_specs'][SYM]['captured_ms']=now
        await self.pipeline.append([packet])
        for i in range(3):await self.pipeline.append([market('execution',now,i+1)])
        await self.pipeline.append([market('level2',now,1)])
        await self.pipeline.append([market('tickerV2',now,1)])
        await asyncio.sleep(.12)
        now=__import__('time').time_ns()//1_000_000
        await self.pipeline.append([market('tickerV2',now,2)])
        self.assertIn(SYM,(await self.pipeline.report())['pins'])
        result=await self.observer.preflight()
        self.assertIn(SYM,result['watch']['deep_symbols'])
        self.assertIn(SYM,result['unavailable'])
        self.assertIsNotNone((await self.pipeline.report())['open_position'])

    async def test_pin_remains_subscribed_after_real_ledger_position_and_rotation(self):
        await self.test_open_position_pin_is_selected_atomically_even_if_ineligible()
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(self.observer.session(),2.2)
        sent=self.sockets[0].sent
        self.assertTrue(any(m['type']=='subscribe' and m['topic'].endswith(SYM) for m in sent))
        self.assertFalse(any(m['type']=='unsubscribe' and m['topic'].endswith(SYM) for m in sent))
        self.assertIn(SYM,(await self.pipeline.report())['pins'])

    async def test_book_gap_resync_does_not_reconnect_or_claim_missing_deltas(self):
        self.observer.connector=lambda *a,**k:Socket(self.rest,gap=True)
        await self.observer.preflight()
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(self.observer.session(),.9)
        self.assertEqual(self.observer.stream_stats['connections'],1)
        self.assertEqual(self.observer.stream_stats['book_gaps'],1)
        self.assertGreaterEqual(self.observer.stream_stats['book_resyncs'],4)

    async def test_storage_writer_runs_off_the_event_loop(self):
        import threading
        main=threading.get_ident()
        old=self.pipeline.source.append
        ids=[]
        def record(*a):ids.append(threading.get_ident());return old(*a)
        with patch.object(self.pipeline.source,'append',side_effect=record):
            await self.observer.preflight()
        self.assertTrue(ids);self.assertTrue(all(x!=main for x in ids))
