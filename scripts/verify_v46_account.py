"""Bounded deterministic MOCK account-loop acceptance. No network/credentials.

Run: python scripts/verify_v46_account.py --output-dir /tmp/daiinas-v46-proof
Reuses the existing source journal, portfolio, SQLite transactions and replay.
A fixed test clock is intentional; these are synthetic ACCOUNT observations.
"""
import argparse
from dataclasses import asdict
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from daiinas.account_capital import mock_snapshot,MockFuturesAdapter
from daiinas.continuous_store import SourceJournal
from daiinas.portfolio_paper import PortfolioLedger
from daiinas.continuous import replay


def run(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    source=SourceJournal(output/'source.sqlite3');paper=None
    account='MOCK-FUTURES';observations=[]
    for n,(cash,net,free) in enumerate([('450',None,'450'),('450.50','.50','400'),('450.30','-.20','300'),('451.30','1','250'),('451.20','-.10','200'),('451.25','.05','150')]):
        events=[] if net is None else [dict(id=f'trade-{n}',type='REALIZED_NET_TRADE',
            account_id=account,timestamp_ms=n*1000,net=net,gross=str(Decimal(net)+Decimal('.01')),fees='.01',funding='0',campaign_id=f'campaign-{n}',campaign_complete=True)]
        observations.append(mock_snapshot(cash=cash,timestamp_ms=n*1000,snapshot_id=f'cycle-{n}',free_margin=free,cash_events=events))
    statuses=[];adapter=MockFuturesAdapter(observations);policy=portfolio=None
    try:
        for i in range(len(observations)):
            snap=adapter.snapshot()
            if i==0:
                paper=PortfolioLedger.from_account_snapshot(output/'paper.sqlite3',source.source_id,snap)
                policy,portfolio=paper.policy,paper.portfolio
            else:paper=PortfolioLedger(output/'paper.sqlite3',source.source_id,policy,portfolio=portfolio)
            with patch('daiinas.continuous_store.clock_ms',return_value=snap.timestamp_ms):
                rows=source.append([('CONTROL','account:'+snap.snapshot_id,{'action':'account-snapshot','snapshot':snap.payload()})])
            paper.apply(rows);paper.apply(rows)
            status=paper.report()['account_status']
            assert status['current_futures_equity']==snap.equity and status['orders_enabled'] is False
            assert paper.state['counts']['INITIAL_FUNDING']==1
            statuses.append(status);expected=paper.report();paper.close();paper=None
        replica=replay([source.path],output/'replay.sqlite3',policy,ledger_factory=PortfolioLedger,ledger_options={'portfolio':portfolio})
        assert replica==expected
        result=dict(status='PASS',evidence_kind='SYNTHETIC_MOCK_ACCOUNT_NOT_REAL_KUCOIN',
            python=platform.python_version(),tested_revision=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
            source_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path('daiinas/account_capital.py'),Path('daiinas/portfolio_paper.py'),Path('daiinas/funding.py')]},
            opening_funding=expected['initial_funding'],cycles=statuses,restarts=5,
            immutable_initial_funding_count=1,realized_net_account_pnl='1.25',mock_fees='.05',
            paper_trades=expected['closed_summary']['count'],paper_net_pnl=expected['realized_net_pnl'],
            replay_identical=True,orders_enabled=False,authenticated_connection='NOT_CONNECTED',
            deposit_allocation_policy='NOT_APPROVED',production_ready=False)
        (output/'status.json').write_text(json.dumps(result,indent=2)+'\n')
        return result
    finally:
        if paper:paper.close()
        source.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',required=True,type=Path)
    args=parser.parse_args();result=run(args.output_dir)
    print(json.dumps(dict(status=result['status'],restarts=result['restarts'],replay_identical=result['replay_identical'],
                         authenticated_connection=result['authenticated_connection'],report=str(args.output_dir/'status.json'))))
