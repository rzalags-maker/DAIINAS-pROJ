"""Explicit hypothetical funding fixtures. No exchange connection or real funds."""
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from daiinas.funding import paper_funding,ReadOnlySnapshot,validate_readonly_snapshot
from daiinas.portfolio_paper import PortfolioLedger,PortfolioPolicy
from daiinas.continuous_store import SourceJournal
from daiinas.continuous import replay,settings
from daiinas.paper_micro import PaperPolicy
D=lambda x:Decimal(str(x))

class FundingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.source=SourceJournal(self.root/'source.sqlite3')
    def tearDown(self):self.source.close();self.tmp.cleanup()
    def policy(self,capital='60',**kwargs):
        funding=paper_funding(capital,account_id='explicit-paper-'+capital,source_reference='User-selected synthetic unit scenario',timestamp_ms=0)
        return PortfolioPolicy(initial_capital=capital,funding=funding,**kwargs)
    def test_no_new_account_implicit_capital_or_funding(self):
        with self.assertRaises(ValueError):PortfolioLedger(self.root/'missing.sqlite3',self.source.source_id)
        self.assertFalse((self.root/'missing.sqlite3').exists())
        with self.assertRaises(TypeError):PortfolioPolicy()
        with self.assertRaises(ValueError):PortfolioPolicy(initial_capital='60',funding={})
        path=self.root/'bad.json';path.write_text(json.dumps({'engine':'v4','portfolio':{}}))
        with self.assertRaises(ValueError):settings(path)
        self.assertEqual(settings(Path(__file__).resolve().parents[1]/'configs/continuous.json')[1].initial_capital_usdt,8)
    def test_variable_exact_openings_and_one_funding_event(self):
        for cap,slots in [('29',1),('60',1),('99.99',1),('100',2),('125',3),('300',10),('350',10),('400',10),('60.123456789012345678',1)]:
            p=PortfolioLedger(self.root/(cap+'.sqlite3'),self.source.source_id,portfolio=self.policy(cap))
            try:
                self.assertEqual(D(p.report()['cash']),D(cap));self.assertEqual(p.ladder().slot_ceiling,slots)
                self.assertEqual(p.state['counts']['INITIAL_FUNDING'],1)
                self.assertEqual(p.db.execute('SELECT count(*) FROM initial_funding').fetchone()[0],1)
                self.assertEqual(p.state['initial_funding']['kind'],'owner_confirmed_paper_scenario')
                self.assertFalse(p.state['initial_funding']['verified_exchange_balance'])
                self.assertEqual(p.ladder().realized_net,0)
            finally:p.close()
    def test_restarts_and_replay_cannot_reseed(self):
        path=self.root/'account.sqlite3';policy=self.policy('100');expected=None
        for i in range(3):
            p=PortfolioLedger(path,self.source.source_id,portfolio=policy)
            try:
                if expected:self.assertEqual(p.report(),expected)
                expected=p.report()
            finally:p.close()
        replica=replay([self.source.path],self.root/'replica.sqlite3',PaperPolicy(initial_capital_usdt=100.),ledger_factory=PortfolioLedger,ledger_options={'portfolio':policy})
        self.assertEqual(replica,expected)
    def test_conflicting_identity_or_seed_refuses_without_mutation(self):
        path=self.root/'account.sqlite3';policy=self.policy('60');p=PortfolioLedger(path,self.source.source_id,portfolio=policy);expected=p.report();p.close()
        changed={**policy.funding,'source_reference':'Different proposed source'}
        for other in [self.policy('100'),replace(policy,funding=changed)]:
            with self.assertRaises(ValueError):PortfolioLedger(path,self.source.source_id,portfolio=other)
        p=PortfolioLedger(path,self.source.source_id,portfolio=policy)
        try:self.assertEqual(p.report(),expected)
        finally:p.close()
    def test_actual_kill_mid_initial_transaction_then_one_credit(self):
        code="""
import os,sys,signal
from pathlib import Path
from daiinas.portfolio_paper import PortfolioLedger,PortfolioPolicy
from daiinas.funding import paper_funding
root=Path(sys.argv[1]);source_id=sys.argv[2]
policy=PortfolioPolicy(initial_capital='29',funding=paper_funding('29',account_id='explicit-paper-29',source_reference='User-selected synthetic unit scenario',timestamp_ms=0))
old=PortfolioLedger.audit
def audit(self,action,**detail):
 old(self,action,**detail)
 if action=='INITIAL_FUNDING':os.kill(os.getpid(),signal.SIGKILL)
PortfolioLedger.audit=audit
PortfolioLedger(root/'account.sqlite3',source_id,portfolio=policy)
"""
        r=subprocess.run([sys.executable,'-c',code,str(self.root),self.source.source_id],capture_output=True,text=True,timeout=10)
        self.assertEqual(r.returncode,-signal.SIGKILL,r.stderr)
        with sqlite3.connect(self.root/'account.sqlite3') as c:
            self.assertEqual(c.execute('SELECT count(*) FROM initial_funding').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM checkpoint').fetchone()[0],0)
        p=PortfolioLedger(self.root/'account.sqlite3',self.source.source_id,portfolio=self.policy('29'))
        try:self.assertEqual(D(p.state['cash']),D(29));self.assertEqual(p.state['counts']['INITIAL_FUNDING'],1)
        finally:p.close()
    def test_external_flows_are_unallocated_not_ladder_profit(self):
        p=PortfolioLedger(self.root/'account.sqlite3',self.source.source_id,portfolio=self.policy('60'))
        try:
            old=p.ladder().snapshot()
            for t,amount in [(100,'100'),(200,'-25')]:
                with patch('daiinas.continuous_store.clock_ms',return_value=t):
                    rows=self.source.append([('CONTROL','flow:'+str(t),{'action':'capital-flow','amount':amount})])
                p.apply(rows);p.apply(rows)
            self.assertEqual(p.ladder().snapshot(),old);self.assertEqual(D(p.state['cash']),D(135))
            self.assertEqual(D(p.state['quarantined_flows']),D(75));self.assertEqual(p.state['counts']['INITIAL_FUNDING'],1)
            self.assertEqual(p.state['counts']['EXTERNAL_DEPOSIT'],1);self.assertEqual(p.state['counts']['EXTERNAL_WITHDRAWAL'],1)
            p.invariant()
        finally:p.close()
    def test_readonly_scope_validation_and_wallet_separation(self):
        s=ReadOnlySnapshot('kucoin-fixture','CLASSIC_FUTURES','USDT','fixture-snapshot',100,True,True,
                           '24','24','0','0','0','0','0','99')
        self.assertEqual(validate_readonly_snapshot(s,account_id='kucoin-fixture',now_ms=101),D(24))
        external_wallet=D(36)
        self.assertNotEqual(validate_readonly_snapshot(s,account_id='kucoin-fixture',now_ms=101),D(24)+external_wallet)
        self.assertEqual(validate_readonly_snapshot(replace(s,settled_cash='60',locked='36'),account_id='kucoin-fixture',now_ms=101),D(24))
        for bad in [replace(s,complete=False),replace(s,complete='false'),replace(s,free_cash='100'),replace(s,scope_eligible=False),replace(s,account_class='SPOT'),replace(s,timestamp_ms=100000)]:
            with self.assertRaises(ValueError):validate_readonly_snapshot(bad,account_id='kucoin-fixture',now_ms=101)
        with self.assertRaises(ValueError):validate_readonly_snapshot(s,account_id='different',now_ms=101)
        with self.assertRaises(ValueError):validate_readonly_snapshot(s,account_id='kucoin-fixture',now_ms=20000)
        f={**self.policy('24').funding,'kind':'verified_readonly_exchange_snapshot'}
        with self.assertRaisesRegex(ValueError,'NOT_CONNECTED'):PortfolioPolicy(initial_capital='24',funding=f)
        f={**self.policy('24').funding,'external_wallet':'36'}
        with self.assertRaises(ValueError):PortfolioPolicy(initial_capital='24',funding=f)
    def test_conflicting_checkpoint_cannot_masquerade_as_seeded_account(self):
        from daiinas.capital_ladder import CapitalLadder
        path=self.root/'account.sqlite3';policy=self.policy('100')
        p=PortfolioLedger(path,self.source.source_id,portfolio=policy);p.close()
        with sqlite3.connect(path) as c:
            original=c.execute('SELECT payload FROM checkpoint').fetchone()[0]
            state=json.loads(original);state['ladder']=CapitalLadder('8').export_state();state['cash']='8'
            c.execute('UPDATE checkpoint SET payload=?',(json.dumps(state),))
        with self.assertRaisesRegex(ValueError,'startup halted'):PortfolioLedger(path,self.source.source_id,portfolio=policy)
        with sqlite3.connect(path) as c:c.execute('UPDATE checkpoint SET payload=?',(original,))
        p=PortfolioLedger(path,self.source.source_id,portfolio=policy)
        try:self.assertEqual(D(p.state['cash']),D(100));self.assertEqual(p.state['counts']['INITIAL_FUNDING'],1)
        finally:p.close()

    def test_opening_event_is_immutable(self):
        p=PortfolioLedger(self.root/'account.sqlite3',self.source.source_id,portfolio=self.policy())
        try:
            with self.assertRaises(sqlite3.IntegrityError):p.db.execute('DELETE FROM initial_funding')
            with self.assertRaises(sqlite3.IntegrityError):p.db.execute("UPDATE initial_funding SET payload='{}'")
            p.invariant()
        finally:p.close()
