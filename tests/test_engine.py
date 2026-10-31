import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest.mock import patch
from io import BytesIO
from zipfile import ZipFile

from daiinas.models import Candle, RiskConfig, Signal, StrategyConfig
from daiinas.strategy import signal
from daiinas.risk import ContractRules, fill, size
from daiinas.backtest import run
from daiinas import data
from daiinas.cli import configuration

RULE = ContractRules('SOLUSDT', '.001', '100000', '.001', '.01', '5')
ZERO = RiskConfig(initial_capital=100, risk_fraction=.1, fee_rate=0,
                  spread_bps=0, slippage_bps=0, funding_8h_rate=0)


def bars(rows):
    return [Candle(i*60_000, *row, 10) for i,row in enumerate(rows)]


def fixture():
    return bars([(100,101,99,100), (100,101,99,100),
                 (100,110,90,100), (100,101,99,100)])


def one_signal(candles, i, config):
    return Signal('LONG',95,90,2) if i == 1 else None


class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.cfg = StrategyConfig(lookback=3, atr_period=3, min_atr_fraction=0,
                                  max_atr_fraction=1, sweep_atr=0, stop_atr=.25)
        self.prior = bars([(100,102,98,100)]*4)

    def test_atr_requires_a_previous_close_for_every_true_range(self):
        cfg = replace(self.cfg, lookback=2)
        # At i == atr_period the first prior true range has no previous close.
        # It must never accidentally read candles[-1] (the future tail).
        c = self.prior + [Candle(240_000,100,1000,1,100,10)]
        self.assertIsNone(signal(c,3,cfg))
        self.assertIsNone(signal(c[:4],3,cfg))

    def test_long_reversal(self):
        c = self.prior + [Candle(240_000,99,101,97,100,10)]
        self.assertEqual(signal(c,4,self.cfg).side,'LONG')
        self.assertLess(signal(c,4,self.cfg).stop,97)

    def test_short_reversal(self):
        c = self.prior + [Candle(240_000,101,103,99,100,10)]
        self.assertEqual(signal(c,4,self.cfg).side,'SHORT')

    def test_ambiguous_both_sweeps_rejected(self):
        c = self.prior + [Candle(240_000,99,103,97,100,10)]
        self.assertIsNone(signal(c,4,self.cfg))

    def test_no_return_no_signal(self):
        c = self.prior + [Candle(240_000,99,101,95,97,10)]
        self.assertIsNone(signal(c,4,self.cfg))

    def test_prefix_invariance(self):
        c = self.prior + [Candle(240_000,99,101,97,100,10)]
        expected = signal(c,4,self.cfg)
        c += [Candle(300_000,100,1000,1,100,10)]
        self.assertEqual(expected,signal(c,4,self.cfg))

    def test_volatility_filter(self):
        c = self.prior + [Candle(240_000,99,101,97,100,10)]
        self.assertIsNone(signal(c,4,replace(self.cfg,max_atr_fraction=.001)))

    def test_insufficient_history(self):
        self.assertIsNone(signal(self.prior,2,self.cfg))


class RiskTests(unittest.TestCase):
    def test_risk_budget_includes_costs(self):
        risk = RiskConfig()
        q = size(8,6.4,100,99,RULE,risk)
        stop = fill(99,False,risk)
        loss = q*((100-stop)+risk.fee_rate*(100+stop))
        self.assertLessEqual(loss,8*risk.risk_fraction)
        self.assertTrue(RULE.valid(q,100))

    def test_minimum_never_rounds_up(self):
        r = replace(RULE,min_notional='100')
        self.assertEqual(size(8,6.4,100,99,r,RiskConfig()),0)

    def test_loss_reduces_size(self):
        self.assertGreater(size(100,80,100,95,RULE,ZERO),size(50,40,100,95,RULE,ZERO))

    def test_margin_limit(self):
        q = size(100,1,100,99,RULE,ZERO)
        self.assertLessEqual(q*100/ZERO.leverage,1)

    def test_contract_multiplier(self):
        rule = replace(RULE,contract_size='10')
        q = size(100,80,100,95,rule,ZERO)
        self.assertLessEqual(q*10*5,10)

    def test_quantity_increment(self):
        self.assertEqual(RULE.quantity(.123999999),.123)
        self.assertFalse(RULE.valid(.1234,100))

    def test_config_validation(self):
        for kwargs in ({'leverage':10}, {'fee_rate':-1}, {'risk_fraction':.5}, {'initial_capital':float('nan')}):
            with self.assertRaises(ValueError):
                RiskConfig(**kwargs)
        with self.assertRaises(ValueError):
            Candle(0,100,90,80,100,1)


class ExecutionTests(unittest.TestCase):
    def run_case(self, candles=None, sig=one_signal, risk=ZERO, **kwargs):
        with patch('daiinas.backtest.signal',side_effect=sig):
            return run({'SOLUSDT': candles or fixture()}, {'SOLUSDT':RULE},risk=risk,**kwargs)

    def test_next_open_and_stop_first(self):
        r = self.run_case()
        t = r['trades'][0]
        self.assertEqual(t['entry_time'],120_000)
        self.assertEqual(t['entry'],100)
        self.assertEqual(t['exit'],95)
        self.assertEqual(t['reason'],'stop_loss')
        self.assertAlmostEqual(r['metrics']['net_pnl'],-10)

    def test_short_stop_first(self):
        r = self.run_case(sig=lambda c,i,p: Signal('SHORT',105,110,2) if i==1 else None)
        self.assertEqual(r['trades'][0]['exit'],105)
        self.assertEqual(r['trades'][0]['reason'],'stop_loss')

    def test_adverse_gap_stop(self):
        c = bars([(100,101,99,100)]*3+[(90,92,89,91)])
        t = self.run_case(c)['trades'][0]
        self.assertEqual(t['reason'],'stop_gap')
        self.assertEqual(t['exit'],90)

    def test_gap_beyond_entry_stop_rejected(self):
        c = bars([(100,101,99,100)]*2+[(90,92,89,91),(91,92,90,91)])
        r = self.run_case(c)
        self.assertEqual(r['metrics']['total_trades'],0)
        self.assertEqual(r['metrics']['rejections']['gap_invalid_stop'],1)

    def test_invalidation_next_open(self):
        c = bars([(100,101,99,100)]*2+[(100,101,98,99),(98,99,97,98)])
        r = self.run_case(c, sig=lambda c,i,p: Signal('LONG',90,99.5,2) if i==1 else None)
        t = r['trades'][0]
        self.assertEqual(t['reason'],'signal_invalidation')
        self.assertEqual(t['exit'],98)
        self.assertEqual(t['exit_time'],180_000)

    def test_fees_and_account_reconcile(self):
        risk = replace(ZERO,fee_rate=.001,spread_bps=2,slippage_bps=3)
        r = self.run_case(risk=risk)
        self.assertAlmostEqual(sum(t['net_pnl'] for t in r['trades']),r['metrics']['net_pnl'])
        self.assertLess(r['trades'][0]['exit'],95)
        self.assertGreater(r['trades'][0]['entry'],100)

    def test_halt_is_permanent(self):
        r = self.run_case(risk=replace(ZERO,max_drawdown=.05),
                          sig=lambda c,i,p: Signal('LONG',95,90,2))
        self.assertTrue(r['metrics']['drawdown_halted'])
        self.assertEqual(len(r['trades']),1)

    def test_oos_does_not_inherit_pending_signal(self):
        r = self.run_case(start=2)
        self.assertEqual(len(r['trades']),0)

    def test_prefix_execution_invariance(self):
        c = fixture()
        a = self.run_case(c)
        extended = c+[Candle(240_000,100,200,1,100,10)]
        b = self.run_case(extended,end=4)
        self.assertEqual(a,b)

    def test_funding_charged_to_both_sides(self):
        for side in ('LONG','SHORT'):
            c = [Candle((i+477)*60_000,100,101,99,100,10) for i in range(5)]
            sig = lambda c,i,p: Signal(side,90 if side=='LONG' else 110,80 if side=='LONG' else 120,2) if i==1 else None
            r = self.run_case(c,sig=sig,risk=replace(ZERO,funding_8h_rate=.001))
            self.assertGreater(r['trades'][0]['funding'],0)
            self.assertAlmostEqual(r['metrics']['net_pnl'],-r['trades'][0]['funding'])

    def test_portfolio_shared_margin(self):
        rule2 = replace(RULE,symbol='XRPUSDT')
        c = bars([(100,101,99,100)]*5)
        with patch('daiinas.backtest.signal',side_effect=lambda c,i,p: Signal('LONG',99.9,90,2) if i==1 else None):
            r = run({'SOLUSDT':c,'XRPUSDT':c},{'SOLUSDT':RULE,'XRPUSDT':rule2},risk=ZERO)
        entry_margin = sum(t['margin'] for t in r['trades'])
        self.assertLessEqual(entry_margin,100*.8)

    def test_two_hedge_legs(self):
        c = bars([(100,101,99,100)]*6)
        def sig(c,i,p):
            return Signal('LONG',90,80,2) if i==1 else Signal('SHORT',110,120,2) if i==2 else None
        r = self.run_case(c,sig=sig)
        self.assertEqual({t['side'] for t in r['trades']},{'LONG','SHORT'})
        self.assertLess(r['trades'][1]['entry_time'],r['trades'][0]['exit_time'])

    def test_alignment_validation(self):
        with self.assertRaises(ValueError):
            run({'SOLUSDT':fixture(),'XRPUSDT':fixture()[1:]}, {'SOLUSDT':RULE,'XRPUSDT':RULE})


class DataTests(unittest.TestCase):
    def archive(self):
        stream = BytesIO()
        with ZipFile(stream,'w') as z:
            rows = ['open_time,open,high,low,close,volume']
            rows += [f'{i*60_000},100,101,99,100,1' for i in range(1440)]
            z.writestr('candles.csv','\n'.join(rows))
        return stream.getvalue()

    def test_verified_download_cache_and_load(self):
        payload = self.archive()
        checksum = (data.digest(payload)+'  candles.zip\n').encode()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with patch('daiinas.data.fetch',side_effect=[checksum,payload]) as fetch:
                data.download('SOLUSDT','1m',date(1970,1,1),date(1970,1,2),root)
                self.assertEqual(fetch.call_count,2)
            with patch('daiinas.data.fetch',side_effect=AssertionError('cache must be offline')):
                data.download('SOLUSDT','1m',date(1970,1,1),date(1970,1,2),root)
            self.assertEqual(len(data.load('SOLUSDT','1m',date(1970,1,1),date(1970,1,2),root)),1440)
            path = next(root.rglob('*.zip'))
            path.write_bytes(b'corrupted')
            with self.assertRaises(ValueError):
                data.load('SOLUSDT','1m',date(1970,1,1),date(1970,1,2),root)

    def test_checksum_mismatch_not_saved(self):
        with tempfile.TemporaryDirectory() as d:
            with patch('daiinas.data.fetch',side_effect=[b'0'*64,b'bad']):
                with self.assertRaises(ValueError):
                    data.download('SOLUSDT','1m',date(1970,1,1),date(1970,1,2),Path(d))
            self.assertFalse(list(Path(d).rglob('*.zip')))

    def test_config_expands_defaults(self):
        cfg = configuration('configs/default.json')
        self.assertEqual(cfg['risk']['initial_capital'],8)
        self.assertEqual(len(cfg['symbols']),5)


if __name__ == '__main__':
    unittest.main()
