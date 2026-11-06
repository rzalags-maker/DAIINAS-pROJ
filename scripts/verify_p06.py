"""Offline P06 missing-evidence report; no credentials, network or order methods.

Exit zero means the fail-closed check passed, never that trading is ready.
This deliberately contains no account observation and asserts no real balance.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from daiinas.bitsgap_account_acceptance import blocked_report
from daiinas.bitsgap_capabilities import BitsgapCapabilityRegistry
from daiinas.p06_first_order_feasibility import assess_first_order


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    report = assess_first_order(BitsgapCapabilityRegistry.documented(),
                                blocked_report('NO_CURRENT_SESSION_EVIDENCE'),
                                now_ms=0)
    readiness = report['first_order_readiness']
    if readiness['status'] != 'BLOCKED' or readiness['orders_enabled'] is not False:
        raise RuntimeError('P06_FAIL_CLOSED_CHECK_FAILED')
    serialized = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n'
    if args.output:
        with args.output.open('x', encoding='utf-8') as stream:
            stream.write(serialized)
    print(serialized, end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
