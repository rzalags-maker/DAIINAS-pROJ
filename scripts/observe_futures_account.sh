#!/bin/sh
# Run only on an owner-controlled interactive POSIX host. No credential arguments.
set +x
set -eu
umask 077
if [ "$#" -ne 2 ]; then
    printf '%s\n' 'Usage: sh scripts/observe_futures_account.sh PRIVATE_STATE_FILE NONSECRET_SCOPE_REF' >&2
    exit 2
fi
if [ ! -t 0 ] || [ ! -t 1 ]; then
    printf '%s\n' 'PRIVATE_SESSION_REQUIRES_TRUSTED_INTERACTIVE_TERMINAL' >&2
    exit 2
fi
python - <<'PY'
import os
from daiinas.bitsgap_account_state import _ci
if _ci():
    print('PRIVATE_SESSION_DISALLOWED_IN_CI')
    raise SystemExit(2)
if not os.environ.get('BITSGAP_PRIVATE_KEY_PEM'):
    print('CREDENTIAL_NOT_CONFIGURED')
    raise SystemExit(2)
PY
# The original observer emits sanitized final status and returns 2 intentionally:
# a successful observation never clears the capital/execution gate.
exec python -B -m daiinas.bitsgap_account_state --observe --seconds 60 \
    --state-file "$1" --scope-ref "$2"
