"""Offline shadow-signal research tests, not historical profitability evidence."""
import json
from pathlib import Path
import tempfile
import unittest
from daiinas.shadow_flow import ShadowPolicy, observe, replay
from daiinas.universe_observer import ObservationStore


def quote(*, bid=100,ask=100.02,bid_base_size=12,ask_base_size=4):
    return {'bid':str(bid),'ask':str(ask),
            'bid_base_size':bid_base_size,'ask_base_size':ask_base_size}


def trade(t,side,amount=10):
    return {'received_ms':t,'price':100,'quantity':amount/100,
            'buyer_is_maker':side=='sell'}


class ShadowTests(unittest.TestCase):
    def test_positive_pressure_is_only_diagnostic(self):
        x=observe(received_ms=1000,recent_trades=[trade(900,'buy'),trade(940,'buy'),trade(960,'buy')],
                  book_received_ms=900,quote=quote())
        self.assertEqual(x['direction'],'LONG_PRESSURE')
        self.assertFalse(x['execution_allowed'])
        self.assertIn('no_validated_net_edge',x['reason'])

    def test_short_pressure(self):
        x=observe(received_ms=1000,recent_trades=[trade(900,'sell'),trade(940,'sell'),trade(960,'sell')],
                  book_received_ms=900,quote=quote(bid_base_size=2,ask_base_size=15))
        self.assertEqual(x['direction'],'SHORT_PRESSURE')

    def test_divergent_book_blocks_pressure_alignment(self):
        x=observe(received_ms=1000,recent_trades=[trade(900,'buy'),trade(940,'buy'),trade(960,'buy')],
                  book_received_ms=900,quote=quote(bid_base_size=2,ask_base_size=15))
        self.assertEqual(x['state'],'NO_SIGNAL')
        self.assertEqual(x['direction'],'NONE')

    def test_recent_trades_minimum(self):
        x=observe(received_ms=1000,recent_trades=[trade(900,'buy')],
                  book_received_ms=900,quote=quote())
        self.assertEqual(x['reason'],'insufficient_executions')

    def test_stale_book_fails_closed(self):
        x=observe(received_ms=20_000,recent_trades=[trade(19_999,'buy')]*3,
                  book_received_ms=1,quote=quote())
        self.assertEqual(x['reason'],'missing_or_stale_verified_book')

    def test_wide_spread_blocks_even_strong_pressure(self):
        x=observe(received_ms=1000,recent_trades=[trade(900,'buy')]*3,
                  book_received_ms=900,quote=quote(ask=101))
        self.assertEqual(x['reason'],'spread_over_budget')

    def test_older_executions_not_used(self):
        x=observe(received_ms=50_000,recent_trades=[trade(0,'buy')]*3,
                  book_received_ms=50_000,quote=quote())
        self.assertEqual(x['reason'],'insufficient_executions')

    def test_future_receipt_rejected(self):
        with self.assertRaisesRegex(ValueError,'future-arriving'):
            observe(received_ms=1000,recent_trades=[trade(1001,'buy')]*3,
                    book_received_ms=900,quote=quote())

    def test_invalid_policy(self):
        with self.assertRaises(ValueError):
            ShadowPolicy(window_ms=0)

    def test_book_missing_blocks(self):
        self.assertEqual(observe(received_ms=1000,recent_trades=[trade(900,'buy')]*3,
                                 book_received_ms=None,quote=quote())['state'],'NO_SIGNAL')

    def test_sqlite_replay_only_prior_arrivals_and_no_order_actions(self):
        with tempfile.TemporaryDirectory() as d:
            db=ObservationStore(Path(d)/'replay.sqlite3')
            scan={'time_ms':100,'capital_usdt':8,'contracts_observed':1,
                  'preflight_eligible':1,'audit':[{'symbol':'PEPEUSDTM',
                  'estimated_round_trip_cost_bps':20}]}
            watch={'time_ms':100,'deep_symbols':['PEPEUSDTM']}
            db.record_scan(scan,watch)
            sym='PEPEUSDTM'
            data=[]
            for i in range(3):
                data.append((sym,'execution',str(i),100+i*5,100+i*5,
                             {'tradeId':str(i)},{'timestamp':100+i*5,'price':100,
                             'quantity':.1,'buyer_is_maker':False}))
            data.append((sym,'level2','1',115,115,{'sequence':1},
                         {'book_sequence':1,'verified':True,'best_bid':100,'best_ask':100.02}))
            data.append((sym,'tickerV2','1',120,120,{'sequence':1},
                         {'timestamp':120,**quote()}))
            db.record_events(data)
            r=replay(db.db)
            db.close()
            self.assertEqual(r['pressure_candidates'],1)
            self.assertFalse(r['market_orders_enabled'])
            self.assertEqual(r['paper_trade_count'],0)
            self.assertFalse(r['validated_positive_expectancy'])
            self.assertEqual(r['candidate_examples'][0]['estimated_minimum_round_trip_cost_bps'],20)

    def test_no_scan_must_fail(self):
        with tempfile.TemporaryDirectory() as d:
            db=ObservationStore(Path(d)/'no-scan.sqlite3')
            with self.assertRaisesRegex(ValueError,'No recorded'):
                replay(db.db)
            db.close()


if __name__=='__main__':
    unittest.main()
