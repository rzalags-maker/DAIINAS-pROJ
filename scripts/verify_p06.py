"""Offline P06 missing-evidence report; no credentials, network or order methods.

Exit zero means the fail-closed check passed, never that trading is ready.
This deliberately contains no account observation and asserts no real balance.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from daiinas.bitsgap_account_acceptance import AccountAcceptance, blocked_report
from daiinas.bitsgap_capabilities import BitsgapCapabilityRegistry
from daiinas.bitsgap_first_order import FirstOrderEvidenceBundle, assess_first_order


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    bundle = FirstOrderEvidenceBundle(
        registry=BitsgapCapabilityRegistry.documented(),
        account=AccountAcceptance(
            observed_ms=0, generation=0, account_scope_matches=False,
            balance='UNVERIFIED', orders='UNVERIFIED', positions='UNVERIFIED',
            position_mode='UNVERIFIED', connection='DISCONNECTED'),
        acceptance=blocked_report('NO_CURRENT_SESSION_EVIDENCE'),
        expected_market_id=0,
    )
    report = assess_first_order(bundle, now_ms=0)
    if report['first_order_readiness'] != 'BLOCKED' or report['orders_enabled'] is not False:
        raise RuntimeError('P06_FAIL_CLOSED_CHECK_FAILED')
    serialized = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n'
    if args.output:
        with args.output.open('x', encoding='utf-8') as stream:
            stream.write(serialized)
    print(serialized, end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
