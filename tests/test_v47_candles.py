"""Synthetic OHLCV/session fixtures, never actual-market return evidence."""
import asyncio
import contextlib
from dataclasses import asdict
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from daiinas.candle_context import summarize,analyze,admission,download,COUNT,INTERVALS
from daiinas.continuous_store import digest,SourceJournal
from daiinas.continuous import main,settings,account_factory
from daiinas.continuous_paper import Pipeline
from daiinas.v47 import configuration
import test_v47_conveyor as v

NOW=172800000

def rows(minutes,side=1,asof=NOW):
    interval=minutes*60000;end=asof//interval*interval
    out=[]
    for i in range(COUNT):
        price=1+side*i*.001
        out.append([end-(COUNT-i)*interval,str(price),str(price+.0002),str(price-.0002),str(price),'10','10'])
    return out


def packet(symbol='UPUSDTM',asof=NOW,side=1):
    frames={str(n):{'status':'DOWNLOADED','rows':rows(n,side,asof),'rows_sha256':digest(rows(n,side,asof))} for n in INTERVALS}
    return dict(symbol=symbol,asof_ms=asof,multiplier='1',source='KuCoin public /api/v1/kline/query',frames=frames)


class CandleTests(unittest.TestCase):
    def test_only_closed_contiguous_bars_with_actual_multiplier_and_no_orderflow(self):
        source=rows(1);base=summarize(source,minutes=1,asof_ms=NOW,multiplier='0.01')
        source.append([NOW,'999','1000','900','999','999'])
        result=summarize(source,minutes=1,asof_ms=NOW,multiplier='0.01')
        for key in ('direction','atr_bps','move_bps','recent_high','recent_low','base_volume'):self.assertEqual(result[key],base[key])
        self.assertEqual(result['count'],16);self.assertEqual(result['base_volume'],'1.60')
        self.assertEqual(result['order_flow_status'],'NOT_OBSERVED_IN_OHLCV')
    def test_missing_duplicate_malformed_and_digest_changed_reject_without_gap_fill(self):
        for bad in (rows(1)[:-1],rows(1)+[rows(1)[-1]],[[NOW-60000,'nan','1','1','1','10']],[[NOW-60000,'1','0.9','1','1','10']]):
            with self.subTest(bad=bad):
                with self.assertRaises((ValueError,ArithmeticError)):summarize(bad,minutes=1,asof_ms=NOW,multiplier='1')
        p=packet();p['frames']['1']['rows'][0][1]='2'
        with self.assertRaises(ValueError):analyze(p,now_ms=NOW,expected_multiplier='1')
    def test_multiframe_countertrend_future_stale_and_changed_contract_fail_closed(self):
        p=packet();context=analyze(p,now_ms=NOW,expected_multiplier='1')
        self.assertIsNone(admission(context,side='LONG',now_ms=NOW))
        self.assertEqual(admission(context,side='SHORT',now_ms=NOW),'closed_5m_15m_countertrend')
        self.assertEqual(admission(context,side='LONG',now_ms=NOW+90001),'stale_closed_OHLCV')
        for now,multiplier in ((NOW-1,'1'),(NOW+90001,'1'),(NOW,'2')):
            with self.assertRaises(ValueError):analyze(p,now_ms=now,expected_multiplier=multiplier)
    def test_stop_structure_filters_fixed_money_risk_without_forcing_wider_stop(self):
        helper=v.LeverageTests();state=v.market_state();state['closed_candle_structure']={'swing_low':'.993','swing_high':'1.01'}
        self.assertIsNone(helper.select(market=state).selected) # 0.5% sits inside the closed swing
        wider=helper.select(market={**state,'momentum_bps':600,'trend_bps':600},stop_fraction='.01')
        self.assertIsNotNone(wider.selected);self.assertLessEqual(float(wider.selected['planned_loss_usdt']),.125)


class CandleLedgerTests(unittest.TestCase):
    def test_missing_context_blocks_entry_then_verified_context_enables_full_net_close_and_replay(self):
        from daiinas.continuous import replay
        case=v.ConveyorTests();case.setUp()
        try:
            case.start('60',symbols=('UPUSDTM',),require_candle_context=True)
            import test_continuous_paper as f
            specs={s:{**spec,'captured_ms':NOW} for s,spec in case.paper.state['scan']['specs'].items()}
            case.send(NOW,f.scan(t=NOW,symbol='UPUSDTM',extra=specs))
            t=case.train(start=NOW+100);self.assertFalse(case.paper.state['positions'])
            self.assertFalse(case.paper.state['pending_entries'])
            bid=1.003**16;p=packet(asof=t)
            for f in p['frames'].values():
                for row in f['rows']:row[1:5]=[str(bid),str(bid+.0002),str(bid-.0002),str(bid)]
                f['rows_sha256']=digest(f['rows'])
            case.send(t,('CONTROL','closed-context',{'action':'public-candles','packet':p}))
            for delay in (100,250,400):case.quote('UPUSDTM',t+delay,bid)
            self.assertIn('UPUSDTM|LONG',case.paper.state['positions'],str({k:case.paper.report().get(k) for k in ('reason_counts','account_status','conveyor','candle_contexts','leverage_selections')}))
            position=case.paper.state['positions']['UPUSDTM|LONG']
            self.assertIn('candle_context_sha256',position)
            target=float(position['planned_target_mid'])+.002
            case.quote('UPUSDTM',t+600,target);case.quote('UPUSDTM',t+800,target)
            self.assertFalse(case.paper.state['positions']);self.assertGreaterEqual(float(case.paper.state['realized']),.5)
            case.reopen();case.paper.invariant()
            replica=replay([case.source.path],case.root/'closed-replay.sqlite3',case.policy,ledger_factory=type(case.paper),ledger_options={'portfolio':case.pp})
            self.assertEqual(replica,case.paper.report());self.assertEqual(replica['counts']['INITIAL_FUNDING'],1)
        finally:case.tearDown()


class CandleTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_bounded_download_cache_and_failed_requests_are_not_verified(self):
        class Rest:
            calls=[];active=peak=0
            def request(self,path,params):
                self.calls.append(params);return rows(params['granularity']),b'public-fixture','public-fixture'
        rest=Rest();cache={};specs={'UPUSDTM':{'rules':{'contract_size':'1'}}}
        result=await download(rest,['UPUSDTM'],specs,asof_ms=NOW,cache=cache)
        self.assertEqual(len(rest.calls),3);self.assertEqual(analyze(result[0],now_ms=NOW,expected_multiplier='1')['status'],'VERIFIED_CLOSED_OHLCV')
        await download(rest,['UPUSDTM'],specs,asof_ms=NOW+1000,cache=cache);self.assertEqual(len(rest.calls),3)
        await download(rest,['UPUSDTM'],specs,asof_ms=NOW+60000,cache=cache);self.assertEqual(len(rest.calls),4)
        class Failed:
            def request(self,*args):raise OSError('fixture network unavailable')
        failed=await download(Failed(),['UPUSDTM'],specs,asof_ms=NOW,cache={})
        with self.assertRaises(ValueError):analyze(failed[0],now_ms=NOW,expected_multiplier='1')
    async def test_configured_runtime_journals_candles_and_replays_same_context(self):
        import test_universe as u
        from daiinas.continuous_stream import ContinuousObserver
        from daiinas.continuous import replay
        from daiinas.universe_rotation import RotationPolicy
        from dataclasses import replace
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);config=configuration('200','candle-runtime',timestamp_ms=u.NOW)
            path=root/'config.json';path.write_text(json.dumps(config));_,policy,shadow=settings(path)
            pipe=Pipeline(root/'source.db',root/'paper.db',policy,shadow,**account_factory(config))
            class Rest:
                def request(self,path,params):return rows(params['granularity'],asof=u.NOW),b'fixture','fixture'
            def market_get(path):
                return [u.contract(s,maxLeverage=5,initialMargin=.2,maxOrderQty=100000) for s in ('UPUSDTM','DOWNUSDTM','FLATUSDTM')] if path.endswith('active') else [u.ticker(s) for s in ('UPUSDTM','DOWNUSDTM','FLATUSDTM')]
            observer=ContinuousObserver(pipe,source_path=root/'source.db',rest=Rest(),market_get=market_get,deep=3,refresh_seconds=30)
            try:
                with patch('daiinas.continuous_store.clock_ms',return_value=u.NOW),patch('daiinas.continuous_stream.now_ms',return_value=u.NOW):
                    await pipe.poll_account();await observer.preflight()
                report=await pipe.report();self.assertEqual(len(report['candle_contexts']),3)
                self.assertTrue(all(c['status']=='VERIFIED_CLOSED_OHLCV' for c in report['candle_contexts'].values()))
                replica=replay([root/'source.db'],root/'replay.db',policy,shadow,**account_factory(config));self.assertEqual(report,replica)
            finally:observer.close();pipe.close()


class SessionCliTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_pause_stop_queue_then_durable_runtime_ack_and_no_reseed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);cfg=configuration('200','session-cli',timestamp_ms=0);path=root/'config.json';path.write_text(json.dumps(cfg))
            _,policy,shadow=settings(path);pipe=Pipeline(root/'source.db',root/'paper.db',policy,shadow,**account_factory(cfg))
            try:
                with patch('daiinas.continuous_store.clock_ms',return_value=100):await pipe.poll_account()
                args=['--config',str(path),'--source-db',str(root/'source.db'),'--paper-db',str(root/'paper.db')]
                for time,command in ((200,'pause'),(300,'stop'),(400,'start')):
                    output=io.StringIO()
                    with patch('daiinas.continuous_store.clock_ms',return_value=time),contextlib.redirect_stdout(output):self.assertEqual(main([command,*args]),0)
                    ack=json.loads(output.getvalue());self.assertFalse(ack['runtime_effect_confirmed']);self.assertEqual(ack['ack'],'SOURCE_ACCEPTED_AWAITING_WORKER')
                    with patch('daiinas.continuous_store.clock_ms',return_value=time):await pipe.append([('CLOCK','clock:'+command,{})])
                    report=await pipe.report()
                    if command=='stop':self.assertEqual(report['session']['state'],'STOPPED_FLAT')
                    if command=='start':self.assertEqual(report['session']['desired'],'ARMED_PAPER');self.assertTrue(report['paused_new_entries'])
                self.assertEqual(report['counts']['INITIAL_FUNDING'],1)
            finally:pipe.close()
