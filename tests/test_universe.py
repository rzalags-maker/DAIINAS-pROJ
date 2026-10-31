import unittest
from daiinas.universe import Policy, scan

NOW=1_800_000_000_000

def contract(symbol='TESTUSDTM', *, turnover=20_000_000, multiplier=.01, lot=1,
             age_days=365, fee=.0006, **extra):
    c={'symbol':symbol,'status':'Open','type':'FFWCSX','quoteCurrency':'USDT',
       'settleCurrency':'USDT','isInverse':False,'expireDate':None,'marketStage':'NORMAL',
       'firstOpenDate':NOW-age_days*86_400_000,'turnoverOf24h':turnover,
       'multiplier':multiplier,'lotSize':lot,'tickSize':.0001,'takerFeeRate':fee}
    c.update(extra)
    return c

def ticker(symbol='TESTUSDTM', *, bid=1, ask=1.0002, bid_size=100,ask_size=100, ts=None):
    return {'symbol':symbol,'bestBidPrice':str(bid),'bestAskPrice':str(ask),
            'bestBidSize':bid_size,'bestAskSize':ask_size,'ts': (NOW if ts is None else ts)*1_000_000}

class UniverseTests(unittest.TestCase):
    def check(self, c=None, t=None, equity=8, policy=None):
        return scan([c or contract()], [t or ticker()], now_ms=NOW, equity=equity,
                    policy=policy or Policy())
    def test_small_executable_contract_can_be_observed_not_traded(self):
        res=self.check()
        self.assertEqual(res['preflight_eligible'],1)
        self.assertEqual(res['status'],'READY_TO_OBSERVE')
        self.assertEqual(len(res['selected_for_deeper_observation']),1)
    def test_large_minimum_contract_rejected_with_8(self):
        res=self.check(c=contract(multiplier=100))
        self.assertIn('minimum_lot_exceeds_margin_budget',res['audit'][0]['reasons'])
        self.assertEqual(res['selected_for_deeper_observation'],[])
    def test_fat_spread_rejected(self):
        res=self.check(t=ticker(ask=1.003))
        self.assertIn('wide_spread',res['audit'][0]['reasons'])
    def test_low_turnover_rejected_even_when_spread_tight(self):
        res=self.check(c=contract(turnover=1000))
        self.assertIn('insufficient_24h_turnover',res['audit'][0]['reasons'])
    def test_expired_inverse_spot_and_prelisting_rejected(self):
        for opts in ({'isInverse':True},{'quoteCurrency':'BTC'},
                     {'expireDate':NOW},{'status':'Closed'}, {'age_days':2}):
            with self.subTest(opts=opts):
                res=self.check(c=contract(**opts))
                self.assertEqual(res['preflight_eligible'],0)
    def test_stale_ticker_rejected(self):
        res=self.check(t=ticker(ts=NOW-60_000))
        self.assertIn('stale_or_future_quote',res['audit'][0]['reasons'])
    def test_absent_ticker_rejected(self):
        res=scan([contract()], [],now_ms=NOW,equity=8)
        self.assertIn('missing_ticker',res['audit'][0]['reasons'])
    def test_duplicate_ticker_not_silently_double_counted(self):
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            scan([contract()], [ticker(),ticker()],now_ms=NOW,equity=8)
    def test_unreasonable_contract_metadata_fail_closed(self):
        res=self.check(c=contract(multiplier=-1))
        self.assertIn('invalid_ticker_or_contract_units',res['audit'][0]['reasons'])
    def test_rejected_if_assumed_stop_exceeds_small_risk_budget(self):
        res=self.check(c=contract(multiplier=8))
        self.assertIn('minimum_lot_exceeds_assumed_stop_budget',res['audit'][0]['reasons'])
    def test_capital_change_changes_executable_universe(self):
        a=self.check(c=contract(multiplier=8),equity=8)
        b=self.check(c=contract(multiplier=8),equity=100)
        self.assertEqual(a['preflight_eligible'],0)
        self.assertEqual(b['preflight_eligible'],1)
    def test_scoring_does_not_pick_ineligible_coin(self):
        a=contract('AUSDTM',turnover=100_000_000,multiplier=100)
        b=contract('BUSDTM',turnover=20_000_000,multiplier=.01)
        res=scan([a,b], [ticker('AUSDTM'),ticker('BUSDTM')],now_ms=NOW,equity=8)
        self.assertEqual(res['selected_for_deeper_observation'][0]['symbol'],'BUSDTM')
    def test_missing_turnover_fails_closed(self):
        c=contract();del c['turnoverOf24h']
        self.assertIn('missing_24h_turnover',self.check(c=c)['audit'][0]['reasons'])
    def test_bad_policy_and_equity_rejected(self):
        with self.assertRaises(ValueError):Policy(max_spread_bps=float('nan'))
        with self.assertRaises(ValueError):self.check(equity=0)

if __name__ == '__main__':unittest.main()
