"""Deterministic v3 universe observer tests; no exchange access and no orders."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from daiinas.universe_rotation import select, RotationPolicy, CapacityError
from daiinas.universe_observer import ObservationStore, Observer, contract_rule, now_ms
from daiinas.providers.kucoin import DataGap, OrderBook


def report(now, *candidates):
    return {'time_ms':now,'selected_for_deeper_observation':[
        {'symbol':name,'eligible':True,'liquidity_score_not_alpha':score}
        for name,score in candidates]}


def contract(symbol='PEPEUSDTM'):
    return {'symbol':symbol,'status':'Open','isInverse':False,'quoteCurrency':'USDT',
            'settleCurrency':'USDT','type':'FFWCSX','expireDate':None,
            'lotSize':1,'maxOrderQty':10000,'multiplier':'1000',
            'tickSize':'.0000001','takerFixFee':0}


class RotationTests(unittest.TestCase):
    def test_initial_selection_respects_rank_not_alphabetical(self):
        s=select(report(1000,('A',10),('B',30),('C',20)),now_ms=1000,
                 policy=RotationPolicy(deep_slots=2))
        self.assertEqual(s['deep_symbols'],['B','C'])
        self.assertTrue(s['no_trade'])

    def test_minimum_residency_prevents_churn(self):
        p=RotationPolicy(deep_slots=2,minimum_residence_ms=10_000)
        a=select(report(1_000,('A',20),('B',18)),now_ms=1000,policy=p)
        b=select(report(2_000,('A',20),('B',18),('C',25)),now_ms=2000,
                 previous=a['deep_symbols'],entered_at=a['entered_at'],policy=p)
        self.assertEqual(b['deep_symbols'],['A','B'])

    def test_after_residency_promote_better_market(self):
        p=RotationPolicy(deep_slots=2,minimum_residence_ms=10_000,promotion_margin=2)
        a=select(report(1000,('A',20),('B',18)),now_ms=1000,policy=p)
        b=select(report(12_000,('A',20),('B',18),('C',25)),now_ms=12_000,
                 previous=a['deep_symbols'],entered_at=a['entered_at'],policy=p)
        self.assertEqual(set(b['deep_symbols']),{'A','C'})

    def test_small_score_improvement_no_churn(self):
        p=RotationPolicy(deep_slots=2,minimum_residence_ms=0,promotion_margin=5)
        a=select(report(1000,('A',20),('B',18)),now_ms=1000,policy=p)
        b=select(report(2000,('A',20),('B',18),('C',21)),now_ms=2000,
                 previous=a['deep_symbols'],entered_at=a['entered_at'],policy=p)
        self.assertEqual(set(b['deep_symbols']),{'A','B'})

    def test_ineligible_not_pinned_evicted_even_during_dwell(self):
        p=RotationPolicy(deep_slots=2,minimum_residence_ms=30_000)
        a=select(report(1000,('A',20),('B',18)),now_ms=1000,policy=p)
        b=select(report(2000,('A',20),('C',17)),now_ms=2000,
                 previous=a['deep_symbols'],entered_at=a['entered_at'],policy=p)
        self.assertEqual(set(b['deep_symbols']),{'A','C'})

    def test_pinned_position_never_unsubscribed(self):
        s=select(report(1000,('B',20),('C',18)),now_ms=1000,
                 pinned=['OLD'],policy=RotationPolicy(deep_slots=2))
        self.assertIn('OLD',s['deep_symbols'])
        self.assertEqual(s['blocked_new_entries'],['OLD'])
        self.assertIn('B',s['deep_symbols'])

    def test_pins_exceed_capacity_fail_closed(self):
        with self.assertRaises(CapacityError):
            select(report(1000,('A',20)),now_ms=1000,pinned=('A','B'),
                   policy=RotationPolicy(deep_slots=1))

    def test_stale_report_rejected(self):
        with self.assertRaisesRegex(ValueError,'Stale'):
            select(report(1000,('A',20)),now_ms=200000)

    def test_empty_watchlist_is_valid_no_trade(self):
        s=select(report(1000),now_ms=1000)
        self.assertEqual(s['deep_symbols'],[])
        self.assertTrue(s['no_trade'])


class ObserverTests(unittest.TestCase):
    def test_dynamic_unknown_symbol_contract_supported_without_global_mapping_mutation(self):
        rule=contract_rule(contract('PEPEUSDTM'))
        book=OrderBook('PEPEUSDTM',rule,exchange_symbol='PEPEUSDTM')
        t=now_ms()
        book.snapshot({'symbol':'PEPEUSDTM','sequence':100,
                       'ts':t*1_000_000,'bids':[['.0000099','2']],
                       'asks':[['.0000101','3']]},t)
        self.assertFalse(book.verified)
        self.assertTrue(book.delta({'sequence':101,'timestamp':t,'change':'.0000099,buy,4'},t))
        self.assertEqual(book.view().symbol,'PEPEUSDTM')

    def test_dynamic_execution_and_ticker_normalize_contract_multiplier(self):
        from daiinas.providers.kucoin import execution, ticker
        t=now_ms()
        rule=contract_rule(contract())
        ex=execution('PEPEUSDTM',{'symbol':'PEPEUSDTM','side':'buy',
              'ts':t*1_000_000,'size':1,'price':'.0000099'},rule,t,
              exchange_symbol='PEPEUSDTM')
        self.assertAlmostEqual(ex.quantity,1000)
        q=ticker('PEPEUSDTM',{'symbol':'PEPEUSDTM','ts':t*1_000_000,
                 'bestBidPrice':'.0000099','bestAskPrice':'.0000101',
                 'bestBidSize':3,'bestAskSize':2},rule,t,exchange_symbol='PEPEUSDTM')
        self.assertAlmostEqual(q['ask_base_size'],2000)

    def test_separate_db_persists_audited_watchlist_and_events(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'observation.sqlite3'
            db=ObservationStore(path)
            r={'time_ms':1000,'capital_usdt':8,'contracts_observed':10,'preflight_eligible':2}
            s={'time_ms':1000,'deep_symbols':['A'],'entered_at':{'A':1000}}
            db.record_scan(r,s)
            db.record_events([('A','execution','1',1000,1000,{'tradeId':'1'},{'price':1})])
            db.close()
            db=ObservationStore(path)
            self.assertEqual(db.latest()['deep_symbols'],['A'])
            self.assertEqual(db.db.execute('SELECT count(*) FROM raw_events').fetchone()[0],1)
            db.close()

    def test_invalid_contract_rejected(self):
        with self.assertRaises(DataGap):
            contract_rule({**contract(),'isInverse':True})

    def test_real_preflight_is_injectable_with_no_private_api(self):
        from daiinas.universe import Policy
        import asyncio
        ts=now_ms()
        c={**contract(),'firstOpenDate':ts-40*86400000,'turnoverOf24h':10000000,
           'takerFeeRate':.0006}
        # A broader ticker with enough unit liquidity for hypothetical 8-USDT screening.
        t={'symbol':c['symbol'],'ts':ts*1_000_000,
           'bestBidPrice':'.0000099','bestAskPrice':'.0000100',
           'bestBidSize':100000,'bestAskSize':100000}
        # This synthetic pair is deliberately too spread-expensive: zero deep subscriptions.
        with tempfile.TemporaryDirectory() as d:
            o=Observer(db=Path(d)/'db.sqlite3',deep=1)
            try:
                with patch('daiinas.universe_observer.public_get',side_effect=[[c],[t]]):
                    decision=asyncio.run(o.preflight())
                self.assertEqual(decision['deep_symbols'],[])
            finally:
                o.close()


if __name__=='__main__':
    unittest.main()
