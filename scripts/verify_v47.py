"""Bounded SYNTHETIC v4.7 PAPER acceptance; never market-return evidence.

The test event builder supplies artificial quotes/prints/account state. Trading,
fees, protection, reconciliation and replay use the actual existing engine.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from test_v47_conveyor import ConveyorTests,LeverageTests
from daiinas.continuous import replay
from daiinas.continuous_ops import backup_pair


def run(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    result={'evidence_kind':'SYNTHETIC_MARKET_AND_MOCK_FUTURES_ACCOUNT','actual_exchange_account':'NOT_CONNECTED',
            'live_orders_enabled':False,'strategy_validated':False,'production_ready':False,
            'tested_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
            'python':platform.python_version(),'scenarios':{},'leverage_matrix':{}}
    for name in ('net_target','partial_stop_loss','ten_positions','x5','partial_ioc'):
        case=ConveyorTests();case.setUp()
        try:
            symbols=tuple('UP'+str(i)+'USDTM' for i in range(10)) if name=='ten_positions' else ('UPUSDTM',)
            case.start('400' if name=='ten_positions' else '60',symbols,free='3' if name=='x5' else None)
            t=case.train(n=18 if name=='x5' else 15 if name=='ten_positions' else 17,entry_depth=2 if name=='partial_ioc' else None)
            if name=='ten_positions':
                for round in range(10):
                    base=t+round*250;case.heartbeat(base)
                    for j,symbol in enumerate(symbols):case.quote(symbol,base+j*10,1.003**14)
                assert len(case.paper.state['positions'])==10
            elif name!='x5':
                p=case.paper.state['positions']['UPUSDTM|LONG']
                if name=='partial_stop_loss':
                    stop=float(p['planned_stop_mid'])-.001
                    case.quote('UPUSDTM',t+200,stop,bid_size=2)
                    case.quote('UPUSDTM',t+400,stop,bid_size=2)
                    case.reopen();case.quote('UPUSDTM',t+600,stop)
                    assert not case.paper.state['positions'] and float(case.paper.state['realized'])<0
                else:
                    target=float(p['planned_target_mid'])+.002
                    case.quote('UPUSDTM',t+200,target);case.quote('UPUSDTM',t+400,target)
                    assert not case.paper.state['positions'] and float(case.paper.state['realized'])>0
            else:assert next(iter(case.paper.state['positions'].values()))['leverage']==5
            case.paper.invariant();case.reopen()
            report=case.paper.report();directory=output/name
            manifest=backup_pair(case.source.path,case.root/'paper.sqlite3',directory)
            replica=replay([case.source.path],directory/'replayed.sqlite3',case.policy,ledger_factory=type(case.paper),ledger_options={'portfolio':case.pp})
            assert replica==report
            (directory/'report.json').write_text(json.dumps(report,indent=2)+'\n')
            result['scenarios'][name]={'cash':report['cash'],'realized_net_pnl':report['realized_net_pnl'],
                'fees':report['fees'],'carry':report['modeled_carry'],'maximum_drawdown':report['maximum_drawdown'],
                'closed_summary':report['closed_summary'],'open_positions':len(report['positions']),
                'leverage':[p['leverage'] for p in report['positions']],'account_status':report['account_status'],
                'counts':report['counts'],'conveyor':report['conveyor'],'initial_funding_count':report['counts']['INITIAL_FUNDING'],
                'replay_identical':True,'backup':manifest}
        finally:case.tearDown()
    helper=LeverageTests()
    for side in ('LONG','SHORT'):
        result['leverage_matrix'][side]=[helper.select(side,margin).payload() for margin in ('20','10','5','4','3')]
        assert [row['selected']['leverage'] for row in result['leverage_matrix'][side]]==[1,2,3,4,5]
    result['source_sha256']={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [
        Path('daiinas/portfolio_paper.py'),Path('daiinas/adaptive_execution.py'),Path('daiinas/position_conveyor.py'),
        Path('daiinas/market_pulse.py'),Path('tests/test_v47_conveyor.py')]}
    result['status']='PASS';(output/'status.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output-dir',required=True,type=Path)
    args=parser.parse_args();result=run(args.output_dir)
    print(json.dumps({'status':result['status'],'evidence_kind':result['evidence_kind'],'scenarios':list(result['scenarios']),'report':str(args.output_dir/'status.json')}))
