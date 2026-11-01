"""Create an explicit MOCK v4.7 profile for the EXISTING continuous service.

No capital default, credentials, private API or second runtime. Keep this config
unchanged across restarts: its immutable opening provenance identifies the account.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time
from .account_capital import mock_snapshot
from .portfolio_paper import PortfolioPolicy
from .funding import snapshot_funding


def configuration(capital,account_id,*,timestamp_ms=None):
    snapshot=mock_snapshot(cash=capital,account_id=account_id,snapshot_id='explicit-v47-paper-origin',
                           timestamp_ms=int(time.time()*1000) if timestamp_ms is None else timestamp_ms)
    portfolio=PortfolioPolicy(initial_capital=str(capital),funding=snapshot_funding(snapshot),
                               strategy_version='v47',account_driven=True,paper_settlement=True,require_candle_context=True)
    return dict(engine='v4',portfolio=asdict(portfolio),paper={'initial_capital_usdt':float(capital),
                'leverage':2,'stop_bps':50},deep=5,refresh_seconds=30,dwell_seconds=60,
                account_notice='MOCK PAPER account. Real authenticated KuCoin account NOT_CONNECTED. Live orders disabled.')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capital',required=True,help='Explicit hypothetical USDT capital, exact decimal string')
    parser.add_argument('--account-id',required=True,help='Named isolated PAPER scenario identity')
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args(argv);result=configuration(args.capital,args.account_id)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps({'config':str(args.output),'account_kind':'MOCK_PAPER','actual_account':'NOT_CONNECTED','live_orders_enabled':False}))
    return 0


if __name__=='__main__':raise SystemExit(main())
