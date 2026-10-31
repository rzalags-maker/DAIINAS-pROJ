"""Synthetic end-to-end checks; not historical performance reports."""
import contextlib
from datetime import date, timedelta
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from daiinas.cli import main
from daiinas.data import digest, exchange_rules, load
from daiinas.models import SYMBOLS


def metadata():
    return {'serverTime': 0, 'symbols': [
        {'symbol': s, 'contractType': 'PERPETUAL', 'quoteAsset': 'USDT',
         'filters': [
             {'filterType': 'LOT_SIZE', 'minQty': '.01', 'maxQty': '1000', 'stepSize': '.01'},
             {'filterType': 'MARKET_LOT_SIZE', 'minQty': '.01', 'maxQty': '500', 'stepSize': '.02'},
             {'filterType': 'PRICE_FILTER', 'tickSize': '.01'},
             {'filterType': 'MIN_NOTIONAL', 'notional': '5'}]}
        for s in SYMBOLS]}


def make_archive(start, interval):
    stream = io.BytesIO()
    with ZipFile(stream,'w') as z:
        rows = ['open_time,open,high,low,close,volume']
        for i in range(86_400_000//interval):
            # Stable prior range; isolated directional sweeps cause real signals.
            vals = '99,101,97,100' if i%50==25 else '101,103,99,100' if i%50==40 else '100,102,98,100'
            rows.append(f'{start+i*interval},{vals},10')
        z.writestr('synthetic.csv','\n'.join(rows))
    return stream.getvalue()


class CliTests(unittest.TestCase):
    def test_public_metadata_parsing_and_rule_intersection(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            with patch('daiinas.data.fetch',return_value=json.dumps(metadata()).encode()):
                rules, meta = exchange_rules(p)
            self.assertEqual(set(rules),set(SYMBOLS))
            self.assertEqual(rules['SOLUSDT'].max_qty,'500')
            self.assertEqual(rules['SOLUSDT'].step_size,'0.02')
            self.assertFalse(rules['SOLUSDT'].valid(.03,1000))
            self.assertEqual(len(meta['sha256']),64)

    def test_full_cli_offline_reproducible_and_real_strategy(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            cfg = {'symbols':list(SYMBOLS),'interval':'5m','start':'1970-01-01',
                   'end':'1970-01-03','in_sample_fraction':.7,
                   'strategy':{'max_atr_fraction':.1},'risk':{'initial_capital':1000}}
            config = p/'config.json'
            config.write_text(json.dumps(cfg))
            archives = {'1970-01-01':make_archive(0,300_000),
                        '1970-01-02':make_archive(86_400_000,300_000)}
            def fetch(url):
                if url.endswith('exchangeInfo'):
                    return json.dumps(metadata()).encode()
                day = url.split('-')[-3]+'-'+url.split('-')[-2]+'-'+url.split('-')[-1].split('.')[0]
                blob = archives[day]
                return (digest(blob)+'  synthetic.zip').encode() if url.endswith('CHECKSUM') else blob
            base = ['--config',str(config),'--data-dir',str(p/'data')]
            with patch('daiinas.data.fetch',side_effect=fetch), contextlib.redirect_stdout(io.StringIO()):
                main(['download',*base])
            for name in ('a','b'):
                with patch('daiinas.data.fetch',side_effect=AssertionError('backtest must be offline')), contextlib.redirect_stdout(io.StringIO()):
                    main(['backtest',*base,'--output',str(p/name)])
            a,b = [json.loads((p/(x+'.json')).read_text()) for x in ('a','b')]
            self.assertEqual(a,b)
            for part in a['results'].values():
                self.assertGreater(part['metrics']['signals'],0)
                self.assertGreater(part['metrics']['total_trades'],0)
                self.assertAlmostEqual(sum(t['net_pnl'] for t in part['trades']),part['metrics']['net_pnl'])
            self.assertTrue((p/'a.md').exists())
            self.assertEqual(len(a['archives']),10)
            self.assertLessEqual(a['results']['in_sample']['metrics']['end_time'],
                                 a['results']['out_of_sample']['metrics']['start_time'])

    def test_supported_intervals_and_gap_rejection(self):
        for interval,ms in [('1m',60_000),('5m',300_000),('15m',900_000)]:
            with self.subTest(interval=interval), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                directory = root/'SOLUSDT'/interval
                directory.mkdir(parents=True)
                path = directory/f'SOLUSDT-{interval}-1970-01-01.zip'
                blob = make_archive(0,ms)
                path.write_bytes(blob)
                Path(str(path)+'.CHECKSUM').write_text(digest(blob))
                self.assertEqual(len(load('SOLUSDT',interval,date(1970,1,1),date(1970,1,2),root)),86_400_000//ms)
                # Complete boundary times but one internal candle omitted.
                stream = io.BytesIO()
                with ZipFile(io.BytesIO(blob)) as src, ZipFile(stream,'w') as dest:
                    lines = src.read('synthetic.csv').decode().splitlines()
                    del lines[10]
                    dest.writestr('synthetic.csv','\n'.join(lines))
                path.write_bytes(stream.getvalue())
                Path(str(path)+'.CHECKSUM').write_text(digest(stream.getvalue()))
                with self.assertRaisesRegex(ValueError,'Missing'):
                    load('SOLUSDT',interval,date(1970,1,1),date(1970,1,2),root)
