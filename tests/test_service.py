"""Offline lifecycle checks. Synthetic candles are never market validation."""
import contextlib
import io
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from daiinas.backtest import run
from daiinas.data import exchange_rules
from daiinas.models import Candle, RiskConfig, Signal, StrategyConfig
from daiinas.service import Store, Worker, PublicFuturesSource, single_worker, main
from test_cli import metadata


class FakeSource:
    def __init__(self, ms, gap=False):
        self.ms, self.gap, self.responses = ms, gap, []

    def clock(self):
        return self.ms

    def candles(self, symbol, interval, start, end):
        result = []
        for t in range(start,end,300_000):
            i = t//300_000
            o,h,l,c = (99,101,97,100) if i%50==25 else (101,103,99,100) if i%50==40 else (100,102,98,100)
            if i%50 == 30:
                o,h,l,c = 100,110,90,100
            result.append(Candle(t,o,h,l,c,10))
        return result[:-1] if self.gap else result


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        from daiinas.risk import ContractRules
        self.rules = {'SOLUSDT': ContractRules('SOLUSDT','.001','10000','.001','.01','5')}
        self.risk = RiskConfig(initial_capital=1000)
        self.strategy = StrategyConfig(lookback=3,atr_period=3,max_atr_fraction=.1)
        self.c = [Candle(i*60_000,100,101,99,100,10) for i in range(490)]

    def test_checkpoint_restores_open_positions_pending_orders_and_funding(self):
        def signals(c,i,cfg):
            if i in (475,478):
                return Signal('LONG',90,80,2)
            if i == 477:
                return Signal('SHORT',110,120,2)
        with patch('daiinas.backtest.signal',side_effect=signals):
            full = run({'SOLUSDT':self.c},self.rules,self.strategy,self.risk)
            a = run({'SOLUSDT':self.c[:478]},self.rules,self.strategy,self.risk,finalize=False)
            checkpoint = json.loads(json.dumps(a['checkpoint']))
            self.assertTrue(checkpoint['positions'])
            self.assertTrue(checkpoint['pending'])
            b = run({'SOLUSDT':self.c},self.rules,self.strategy,self.risk,start=478,checkpoint=checkpoint)
        self.assertEqual(a['trades']+b['trades'],full['trades'])
        for key in ('net_pnl','final_balance','maximum_drawdown','win_rate','total_trades'):
            self.assertAlmostEqual(full['metrics'][key],b['metrics'][key])
        self.assertGreater(sum(t['funding'] for t in b['trades']),0)

    def test_checkpoint_restores_invalidation(self):
        c = self.c[:10]
        c[5] = Candle(5*60_000,100,101,98,99,10)
        with patch('daiinas.backtest.signal',side_effect=lambda c,i,p: Signal('LONG',90,99.5,2) if i==4 else None):
            a = run({'SOLUSDT':c[:6]},self.rules,self.strategy,self.risk,finalize=False)
            self.assertTrue(a['checkpoint']['invalid_exits'])
            b = run({'SOLUSDT':c},self.rules,self.strategy,self.risk,start=6,checkpoint=a['checkpoint'])
        self.assertEqual(b['trades'][0]['reason'],'signal_invalidation')

    def test_drawdown_halt_survives_restart(self):
        c = self.c[:10]
        c[5] = Candle(5*60_000,100,110,80,100,10)
        risk = replace(self.risk,risk_fraction=.1,max_drawdown=.05)
        with patch('daiinas.backtest.signal',side_effect=lambda c,i,p: Signal('LONG',95,90,2)):
            a = run({'SOLUSDT':c[:6]},self.rules,self.strategy,risk,finalize=False)
            self.assertTrue(a['checkpoint']['halted'])
            b = run({'SOLUSDT':c},self.rules,self.strategy,risk,start=6,
                    checkpoint=json.loads(json.dumps(a['checkpoint'])),finalize=False)
        self.assertTrue(b['checkpoint']['halted'])
        self.assertEqual(b['trades'],[])
        self.assertEqual(b['checkpoint']['cash'],a['checkpoint']['cash'])

    def test_incompatible_or_duplicate_continuation_rejected(self):
        a = run({'SOLUSDT':self.c[:20]},self.rules,self.strategy,self.risk,finalize=False)
        for start,risk in [(19,self.risk),(21,self.risk),(20,replace(self.risk,leverage=2))]:
            with self.assertRaises(ValueError):
                run({'SOLUSDT':self.c},self.rules,self.strategy,risk,start=start,checkpoint=a['checkpoint'])


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root/'paper.sqlite3'
        self.store = Store(self.path)
        self.payload = json.dumps(metadata()).encode()
        self.snapshot = self.root/'rules.json'
        self.snapshot.write_bytes(self.payload)
        self.rules,_ = exchange_rules(self.root,snapshot=self.snapshot)
        self.cfg = {'symbols':['SOLUSDT','XRPUSDT'],'interval':'5m',
                    'strategy':{'max_atr_fraction':.1},'risk':{'initial_capital':1000},
                    'poll_seconds':10,'max_catchup_bars':1000}
        self.source = FakeSource(500*300_000)
        self.worker = Worker(self.store,self.cfg,self.rules,self.payload,self.source)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def tick(self):
        with patch('daiinas.service.now_ms',return_value=self.source.ms):
            return self.worker.tick()

    def test_persistent_restart_and_no_duplicate_bars(self):
        self.assertEqual(self.tick(),1)
        self.assertEqual(self.tick(),0)
        first = self.store.get('checkpoint')
        self.store.close()
        self.store = Store(self.path)
        self.worker = Worker(self.store,self.cfg,self.rules,self.payload,self.source)
        self.source.ms += 50*300_000
        self.assertEqual(self.tick(),50)
        self.assertGreater(self.store.get('checkpoint')['last_time'],first['last_time'])
        self.assertGreater(self.store.db.execute('SELECT count(*) FROM trades').fetchone()[0],0)
        n = self.store.db.execute('SELECT count(*) FROM candles').fetchone()[0]
        self.assertEqual(self.tick(),0)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM candles').fetchone()[0],n)

    def test_stop_survives_restart_then_resume_recovers(self):
        self.tick()
        checkpoint = self.store.get('checkpoint')
        self.store.control(True)
        self.store.close()
        self.store = Store(self.path)
        self.worker = Worker(self.store,self.cfg,self.rules,self.payload,self.source)
        self.source.ms += 10*300_000
        self.assertEqual(self.tick(),0)
        self.assertEqual(checkpoint,self.store.get('checkpoint'))
        self.assertEqual(self.store.get('heartbeat')['status'],'stopped')
        self.store.control(False)
        self.assertEqual(self.tick(),10)

    def test_missing_data_does_not_advance_or_trade(self):
        self.tick()
        before = self.store.get('checkpoint')
        self.source.ms += 300_000
        self.source.gap = True
        with self.assertRaisesRegex(ValueError,'Missing'):
            self.tick()
        self.assertEqual(before,self.store.get('checkpoint'))

    def test_transaction_failure_rolls_back_inputs_and_checkpoint(self):
        self.tick()
        before = self.store.get('checkpoint')
        count = self.store.db.execute('SELECT count(*) FROM candles').fetchone()[0]
        self.source.ms += 300_000
        with patch.object(self.store,'event',side_effect=RuntimeError('simulated disk failure')):
            with self.assertRaises(RuntimeError):
                self.tick()
        self.assertEqual(before,self.store.get('checkpoint'))
        self.assertEqual(count,self.store.db.execute('SELECT count(*) FROM candles').fetchone()[0])
        self.assertEqual(self.tick(),1)

    def test_stop_race_during_fetch_prevents_commit(self):
        original = self.source.candles
        def stopping_fetch(*args):
            self.store.control(True)
            return original(*args)
        self.source.candles = stopping_fetch
        self.assertEqual(self.tick(),0)
        self.assertIsNone(self.store.get('checkpoint'))

    def test_health_staleness_and_stop_visibility(self):
        self.tick()
        with patch('daiinas.service.now_ms',return_value=self.source.ms):
            self.assertTrue(self.store.health()['healthy'])
        with patch('daiinas.service.now_ms',return_value=self.source.ms+10*300_000):
            self.assertFalse(self.store.health()['healthy'])
        self.store.control(True)
        self.tick()
        with patch('daiinas.service.now_ms',return_value=self.source.ms):
            self.assertTrue(self.store.health()['stopped'])

    def test_identity_and_single_worker_lock(self):
        with self.assertRaisesRegex(ValueError,'identity changed'):
            Worker(self.store,{**self.cfg,'interval':'15m'},self.rules,self.payload,self.source)
        with single_worker(self.path):
            with self.assertRaisesRegex(RuntimeError,'Another worker'):
                with single_worker(self.path):
                    pass

    def test_clock_drift_and_excess_backlog_fail_closed(self):
        with patch('daiinas.service.now_ms',return_value=0):
            with self.assertRaisesRegex(ValueError,'clock'):
                self.worker.tick()
        self.tick()
        self.source.ms += 1001*300_000
        with self.assertRaisesRegex(ValueError,'backlog'):
            self.tick()

    def test_operator_cli_and_consistent_backup(self):
        self.tick()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(['stop','--db',str(self.path)]),0)
            self.assertTrue(self.store.get('stop'))
            self.assertEqual(main(['resume','--db',str(self.path)]),0)
            self.assertFalse(self.store.get('stop'))
            target = self.root/'backup.sqlite3'
            self.assertEqual(main(['backup','--db',str(self.path),'--backup-to',str(target)]),0)
            with patch('daiinas.service.now_ms',return_value=self.source.ms):
                self.assertEqual(main(['health','--db',str(self.path)]),0)
        backup = Store(target)
        try:
            self.assertEqual(backup.get('checkpoint'),self.store.get('checkpoint'))
        finally:
            backup.close()

    def test_once_failure_is_unhealthy_and_preserves_error(self):
        cfgpath = self.root/'service.json'
        cfgpath.write_text(json.dumps(self.cfg))
        with patch('daiinas.service.os_signal.signal'), patch('daiinas.service.Worker.tick',side_effect=OSError('public data unavailable')), contextlib.redirect_stdout(io.StringIO()):
            code = main(['run','--once','--db',str(self.path),'--config',str(cfgpath),
                         '--rules-file',str(self.snapshot)])
        self.assertEqual(code,1)
        self.assertFalse(self.store.health()['healthy'])
        self.assertEqual(self.store.get('heartbeat')['error'],'OSError: public data unavailable')
        self.assertIsNone(self.store.get('checkpoint'))

    def test_only_public_get_endpoints(self):
        src = PublicFuturesSource()
        with self.assertRaises(ValueError):
            src.read('/fapi/v1/order')
        row = [0,'100','101','99','100','10',299999]
        with patch('daiinas.service.fetch',return_value=json.dumps([row]).encode()) as fetch:
            candles = src.candles('SOLUSDT','5m',0,300_000)
        self.assertEqual(candles[0].time,0)
        self.assertIn('/fapi/v1/klines?',fetch.call_args.args[0])
        self.assertEqual(len(src.responses),1)


if __name__ == '__main__':
    unittest.main()
