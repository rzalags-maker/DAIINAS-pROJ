"""Synthetic market asymmetry and campaign negative controls; not alpha evidence."""
from dataclasses import asdict,replace
from decimal import Decimal
import math
import unittest
from daiinas.market_intelligence import update,correlation,supported_hedge
from daiinas.hedge_research import illustrative_path
from daiinas.continuous_store import digest
from daiinas.portfolio_paper import PortfolioPolicy
from daiinas.funding import paper_funding

D=lambda x:Decimal(str(x))

class IntelligenceTests(unittest.TestCase):
    def classify(self,path):
        state=None
        for i,mid in enumerate(path):
            t=1000*i;quote={'bid':mid*.99999,'ask':mid*1.00001,'bid_base_size':100,'ask_base_size':100}
            book={'available_ms':t,'bid_base_size':100,'ask_base_size':100}
            state=update(state,now=t,quote=quote,book=book,trades=[],fee_rate=.0006,slippage_bps=2)
        return state

    def test_simultaneous_independent_up_down_range_unknown(self):
        paths={'A':[100*(1+.0004*i) for i in range(60)],'B':[100*(1-.0004*i) for i in range(60)],
               'C':[100+math.sin(i*math.pi/3)*1 for i in range(60)],'D':[100 for i in range(60)]}
        states={k:self.classify(v) for k,v in paths.items()}
        self.assertEqual(states['A']['regime'],'UP_TREND');self.assertEqual(states['B']['regime'],'DOWN_TREND')
        self.assertEqual(states['C']['regime'],'RANGE');self.assertEqual(states['D']['regime'],'UNKNOWN')
        self.assertNotEqual(states['A']['momentum_bps'],states['B']['momentum_bps'])
        self.assertEqual(states['C']['expected_net_status'],'UNSUPPORTED_UNTIL_HELD_OUT_VALIDATION')

    def test_reversal_asof_and_unverified_book(self):
        up=self.classify([100+i*.05 for i in range(50)])
        state=up
        observed=[]
        for i in range(50,150):
            mid=102.5-(i-50)*.06;t=i*1000
            state=update(state,now=t,quote={'bid':mid-.001,'ask':mid+.001,'bid_base_size':100,'ask_base_size':100},
                         book={'available_ms':t,'bid_base_size':100,'ask_base_size':100},trades=[],fee_rate=.0006,slippage_bps=2)
            observed.append(state['regime'])
        self.assertIn('TRANSITION',observed);self.assertEqual(state['regime'],'DOWN_TREND')
        stale=update(state,now=151000,quote={'bid':96,'ask':96.01,'bid_base_size':100,'ask_base_size':100},book=None,trades=[],fee_rate=.0006,slippage_bps=2)
        self.assertEqual(stale['regime'],'DISLOCATED')

    def test_evidence_never_from_future_or_50_50_guess(self):
        policy=PortfolioPolicy(initial_capital='100',funding=paper_funding('100',account_id='fixture-100',source_reference='explicit-unit-fixture',timestamp_ms=0))
        e={'sample_kind':'observed_public','source_sha256':'a'*64,'policy_sha256':digest(asdict(policy)),
           'training_end_ms':10,'validation_start_ms':20,'validation_end_ms':172800020,'held_out_windows':2,'held_out_campaigns':30,
           'net_return_lower_95pct':.001,'advantage_over_directional_lower_95pct':.0001,
           'advantage_over_flat_lower_95pct':.0001,'both_leg_exits_validated':True}
        self.assertFalse(supported_hedge(e,172800019,digest(asdict(policy))))
        self.assertTrue(supported_hedge(e,172800021,digest(asdict(policy))))
        e['net_return_lower_95pct']=0
        self.assertFalse(supported_hedge(e,172800021,digest(asdict(policy))))
        self.assertFalse(supported_hedge({'probability_up':.5},101,digest(asdict(policy))))

    def test_correlation_does_not_align_future_buckets(self):
        a=[[i*1000,1+.001*i*i] for i in range(20)]
        self.assertAlmostEqual(correlation(a,a),1)
        self.assertIsNone(correlation(a,[[t+100000,p] for t,p in a]))

class HedgeNegativeControls(unittest.TestCase):
    def test_equal_pair_single_mark_zero_gross_negative_net(self):
        for path in [[100,100,100],[100,101],[100,99]]:
            r=illustrative_path(path)
            self.assertTrue(all(D(x['equal_pair_gross_at_single_mark'])==0 for x in r['rows']))
            self.assertLess(D(r['net_campaign_mark']),0)

    def test_winner_does_not_hide_losing_residual(self):
        r=illustrative_path([100,102,102,105])
        self.assertGreater(D(r['rows'][-1]['realized_net']),0)
        self.assertIn('SHORT',r['rows'][-1]['open_sides'])
        self.assertLess(D(r['net_campaign_mark']),D('-.75'))

    def test_bidirectional_path_costs_and_no_fixed_two_percent(self):
        for path in [[100,102,102,98,98],[100,98,98,102,102]]:
            r=illustrative_path(path)
            self.assertEqual(r['rows'][-1]['open_sides'],[])
            self.assertGreater(D(r['net_campaign_mark']),0)
            self.assertLess(D(r['net_campaign_mark']),D('.94'))
            self.assertLess(D(r['return_on_campaign_allocation']),D('.02'))

class ExactMoneyTests(unittest.TestCase):
    def test_repeating_carry_reconciles_cash_and_allocation_exactly(self):
        from daiinas.portfolio_paper import money
        e1=D('.0057471');e2=D('.005457');exitfee=D('.0027465');gross=D('.013613')
        carry=money(D(10822)/D(288000000000),cost=True)
        cash=D(100)-e1-e2+gross-exitfee-carry
        net=gross-e1-exitfee-carry
        self.assertEqual(cash,D(50)+(D(50)+net)-e2)
        self.assertGreaterEqual(carry,D(10822)/D(288000000000))
