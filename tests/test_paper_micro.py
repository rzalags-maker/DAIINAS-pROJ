"""v3.2 research-only micro paper: deterministic event-by-event accounting."""
from pathlib import Path
import sqlite3
import tempfile
import unittest
from daiinas.paper_micro import (PaperPolicy, tier_risk_fraction, prepare_rules,
                                  size_for_quote, finish_position, simulate, record_study)
from daiinas.risk import ContractRules
from daiinas.universe_observer import ObservationStore


SYM='TESTUSDTM'


def bbo(bid=1.0,ask=1.0002,bid_size=100,ask_size=10):
    return {'timestamp':0,'bid':str(bid),'ask':str(ask),
            'bid_base_size':bid_size,'ask_base_size':ask_size}


def specs(*, multiplier='1',lot='1',fee=.0006):
    return {SYM:{'rules':{'symbol':SYM,'min_qty':lot,'max_qty':'100000',
                        'step_size':lot,'tick_size':'0.0001','min_notional':'0',
                        'contract_size':multiplier},
                 'taker_fee_rate':fee,
                 'captured_ms':0,'source':'test fixture, synthetic'}}


class PaperStudyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'source.sqlite3'
        self.store=ObservationStore(self.path)
        scan={'time_ms':0,'capital_usdt':8,'contracts_observed':1,
              'preflight_eligible':1,
              'audit':[{'symbol':SYM,'estimated_round_trip_cost_bps':20}],
              'paper_contract_specs':specs()}
        self.store.record_scan(scan,{'time_ms':0,'deep_symbols':[SYM]})
        self.rows=[]
    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def add(self,channel,t,idx,data):
        self.rows.append((SYM,channel,str(idx),t,t,{'sequence':idx},data))

    def signals(self,side='buy'):
        for i in range(3):
            self.add('execution',100+i,i+1,{'timestamp':100+i,'price':1.0,
                    'quantity':10.,'buyer_is_maker':side=='sell'})
        self.add('level2',110,1,{'book_sequence':1,'verified':True})
        self.add('tickerV2',120,1,bbo(bid_size=100 if side=='buy' else 10,
                                     ask_size=10 if side=='buy' else 100))

    def replay(self,**kwargs):
        self.store.record_events(self.rows)
        return simulate(self.store.db,**kwargs)

    def test_long_target_on_later_observed_quote(self):
        self.signals()
        self.add('tickerV2',221,2,bbo())
        self.add('level2',480,2,{'book_sequence':2,'verified':True})
        self.add('tickerV2',500,3,bbo(bid=1.01,ask=1.0102))
        x=self.replay()
        self.assertEqual(x['completed_paper_trades'],1)
        tr=x['completed_trades'][0]
        self.assertEqual(tr['direction'],'LONG')
        self.assertEqual(tr['exit_reason'],'TARGET')
        self.assertGreater(tr['net_pnl_usdt'],0)
        self.assertGreater(tr['entry_price'],1.0002)
        self.assertLess(tr['exit_price'],1.01)
        self.assertAlmostEqual(x['final_cash_including_open_entry_fee_usdt'],
                               8+tr['net_pnl_usdt'])
        self.assertFalse(x['live_orders_enabled'])
        self.assertFalse(x['strategy_validated'])

    def test_stop_and_full_cost_accounting(self):
        self.signals()
        self.add('tickerV2',221,2,bbo())
        self.add('level2',480,2,{'book_sequence':2,'verified':True})
        self.add('tickerV2',500,3,bbo(bid=.992,ask=.9922))
        x=self.replay()
        t=x['completed_trades'][0]
        self.assertEqual(t['exit_reason'],'STOP')
        self.assertLess(t['net_pnl_usdt'],0)
        self.assertAlmostEqual(t['net_pnl_usdt'],
             t['gross_pnl_usdt']-t['entry_fee_usdt']-t['exit_fee_usdt']-t['modeled_carry_usdt'])
        self.assertLess(x['final_cash_including_open_entry_fee_usdt'],8)

    def test_short_direction_and_ask_exit(self):
        self.signals('sell')
        self.add('tickerV2',221,2,bbo(bid_size=10,ask_size=100))
        self.add('level2',480,2,{'verified':True,'book_sequence':2})
        self.add('tickerV2',500,3,bbo(bid=.99,ask=.9902,bid_size=10,ask_size=100))
        x=self.replay()
        tr=x['completed_trades'][0]
        self.assertEqual(tr['direction'],'SHORT')
        self.assertEqual(tr['exit_reason'],'TARGET')
        self.assertGreater(tr['exit_price'],.9902)
        self.assertGreater(tr['net_pnl_usdt'],0)

    def test_no_same_quote_entry_and_no_fabricated_end_close(self):
        self.signals()
        self.add('tickerV2',221,2,bbo())
        x=self.replay()
        self.assertEqual(x['completed_paper_trades'],0)
        self.assertEqual(x['signals_and_rejections']['opened'],1)
        self.assertIsNotNone(x['open_simulated_position'])
        self.assertLess(x['final_cash_including_open_entry_fee_usdt'],8)

    def test_no_later_quote_means_unfilled_not_order(self):
        self.signals()
        x=self.replay()
        self.assertEqual(x['signals_and_rejections']['experimental_signals'],1)
        self.assertEqual(x['completed_paper_trades'],0)
        self.assertEqual(x['final_cash_including_open_entry_fee_usdt'],8)
        self.assertIsNone(x['open_simulated_position'])
        self.assertIn('UNFILLED',[d['action'] for d in x['decisions']])

    def test_not_eligible_with_large_minimum_contract(self):
        self.signals()
        self.add('tickerV2',221,2,bbo())
        r=self.store.db.execute('SELECT raw_report FROM market_scans ORDER BY id DESC LIMIT 1').fetchone()
        import json
        data=json.loads(r[0]);data['paper_contract_specs']=specs(multiplier='1000')
        self.store.db.execute('UPDATE market_scans SET raw_report=?',(json.dumps(data),))
        x=self.replay()
        self.assertEqual(x['completed_paper_trades'],0)
        self.assertEqual(x['signals_and_rejections']['minimum_lot_exceeds_account_risk_or_margin'],1)

    def test_price_drift_refuses_late_fill(self):
        self.signals()
        self.add('tickerV2',221,2,bbo(bid=1.02,ask=1.0202))
        x=self.replay()
        self.assertEqual(x['signals_and_rejections']['late_or_adverse_price_drift'],1)
        self.assertEqual(x['completed_paper_trades'],0)

    def test_signal_expires(self):
        self.signals()
        self.add('tickerV2',6000,2,bbo())
        x=self.replay()
        self.assertEqual(x['signals_and_rejections']['signal_expired'],1)
        self.assertEqual(x['completed_paper_trades'],0)

    def test_stale_book_skips_entry(self):
        self.signals()
        self.add('tickerV2',9900,2,bbo())
        x=self.replay(policy=PaperPolicy(entry_ttl_ms=20000))
        self.assertEqual(x['signals_and_rejections']['unverified_book_at_entry'],1)
        self.assertEqual(x['completed_paper_trades'],0)

    def test_unvalidated_alpha_never_enables_exchange_orders(self):
        self.signals()
        x=self.replay()
        self.assertFalse(x['live_orders_enabled'])
        self.assertFalse(x['strategy_validated'])
        self.assertEqual(x['status'],'PAPER_REPLAY_ONLY')

    def test_tier_risk_and_deescalation(self):
        self.assertAlmostEqual(tier_risk_fraction(8,8),.0025)
        self.assertAlmostEqual(tier_risk_fraction(50,50),.005)
        self.assertAlmostEqual(tier_risk_fraction(100,100),.0075)
        self.assertAlmostEqual(tier_risk_fraction(96,100),.0025)
        self.assertEqual(tier_risk_fraction(93,100),0)

    def test_high_fee_rejects_net_target(self):
        rule=ContractRules(**specs()['TESTUSDTM']['rules'])
        q,reason=size_for_quote(equity=8,peak=8,quote=bbo(),
                 direction='LONG',rules=rule,observed_fee=.05,policy=PaperPolicy())
        self.assertIsNone(q)
        self.assertEqual(reason,'target_not_net_profitable_after_costs')

    def test_maximum_stop_budget_never_rounds_up_minimum_lot(self):
        rule=ContractRules(**specs(multiplier='500')[SYM]['rules'])
        q,reason=size_for_quote(equity=8,peak=8,quote=bbo(),
                 direction='LONG',rules=rule,observed_fee=.0006,policy=PaperPolicy())
        self.assertIsNone(q)
        self.assertEqual(reason,'minimum_lot_exceeds_account_risk_or_margin')

    def test_any_missing_actual_contract_metadata_fails_closed(self):
        self.signals()
        self.store.db.execute("UPDATE market_scans SET raw_report='{}'")
        with self.assertRaisesRegex(ValueError,'No recorded verified'):
            self.replay()

    def test_funding_model_explicit_not_actual_debit(self):
        rule=ContractRules(**specs()[SYM]['rules'])
        pos,_=size_for_quote(equity=8,peak=8,quote=bbo(),
              direction='LONG',rules=rule,observed_fee=.0006,policy=PaperPolicy())
        pos.update(entry_received_ms=100)
        r=finish_position(pos,bbo(bid=1.02,ask=1.0202),100+28_800_000,'TIME',PaperPolicy())
        self.assertGreater(r['modeled_carry_usdt'],0)

    def test_run_idempotent_separate_paper_ledger(self):
        self.signals()
        x=self.replay()
        path=Path(self.temp.name)/'study.sqlite3'
        a=record_study(self.path,path,x)
        b=record_study(self.path,path,x)
        self.assertEqual(a,b)
        c=sqlite3.connect(path)
        self.assertEqual(c.execute('SELECT COUNT(*) FROM paper_runs').fetchone()[0],1)
        c.close()
        with self.assertRaises(ValueError):record_study(self.path,self.path,x)

    def test_invalid_policy_rejected(self):
        with self.assertRaises(ValueError):PaperPolicy(initial_capital_usdt=0)
        with self.assertRaises(ValueError):PaperPolicy(stop_bps=10_000)


if __name__=='__main__':
    unittest.main()
