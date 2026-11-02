"""Redacted integrated MOCK acceptance. No keys, provider requests or live orders."""
import argparse
import json
from pathlib import Path
import platform
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from test_p04_integration import GatewayTests


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path)
    args=p.parse_args(argv)
    names=('test_whole_cycle_settles_once_and_replacement_uses_same_ledger',
        'test_partial_entry_exit_and_native_duplicate_settle_only_final_close',
        'test_uncertain_ack_restart_stop_preserves_reserved_exposure_without_retry',
        'test_stop_ack_with_open_position_then_offline_close_and_replay',
        'test_model_a_200_keeps_reserve_and_original_funding_once',
        'test_loss_settlement_reduces_active_not_protected_reserve',
        'test_late_ack_after_stop_never_claims_flat_without_cancel_proof',
        'test_real_accountstate_type_bridges_to_mock_gate_without_funding_it')
    result=unittest.TestResult();unittest.TestSuite(GatewayTests(name) for name in names).run(result)
    report={'evidence':'SYNTHETIC_MARKET_AND_MOCK_LEDGER','python':platform.python_version(),
        'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'working_tree_dirty':bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT)),
        'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skips':len(result.skipped),
        'result':'PASS' if result.wasSuccessful() and not result.skipped else 'FAIL',
        'live_verified':False,'orders_enabled':False,'live_trading':'DISABLED',
        'terminal_parity':'PENDING_OWNER_VERIFICATION'}
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('x') as stream:json.dump(report,stream,indent=2);stream.write('\n')
    print(json.dumps(report,sort_keys=True))
    return 0 if report['result']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
