# Future KuCoin account boundary — design only (issue #8)

**LIVE ORDERS DISABLED.** No signed requests, private connector implementation,
private WebSocket subscription, exchange account probe or live-mode switch is
introduced. Public token negotiation is anonymous public-feed access, not private
account authentication. Actual exchange balances are not paper capital flows.

The current worker holds at most one simulated position for one shared simulated
8-USDT account. It does not implement actual concurrent Hedge Mode. A successful
public feed or possession of an API key proves neither account mode nor access
eligibility. The owner's real 8 USDT remains completely outside this database.

A previous screenshot exposed a Futures-capable key/secret. Treat it as compromised:
revoke/rotate it out of band through the exchange before ANY future use. Do not
copy, request, log or put it into Codex, chats, this repository or GitHub Actions.
No exposed credential was used in this work. Future authorization requires secure
infrastructure, explicit owner review, verified legal/product eligibility including
applicable UK retail derivatives restrictions, and the exchange's current rules.

## Identity and proposed read-only reconciliation contract

Use namespace-separated identities, for example:

```
PUBLIC_FEED / provider / contract-symbol / event-id
PAPER / source-uuid / simulated-account-id / instrument-id / LONG-or-SHORT / position-id
ACTUAL_EXCHANGE / exchange-account-id / instrument-id / positionSide / exchange-position-id
```

`positionSide` must be explicit LONG or SHORT; direction on a single position is
not proof of Hedge Mode. Contract identity includes settlement currency, contract
kind, exact multiplier, lot/tick, metadata version and provider-native symbol.
Order identity must include client request ID and exchange order ID within its
account namespace; long-close cannot accidentally become a short-open.

A future **read-only** adapter, after a separate approval, would expose immutable
snapshots: account ID/mode/settlement/free balance/margin, per-instrument per-side
quantity/entry/margin/unrealized P&L, source timestamps and completeness flags.
No `place_order`, `cancel_order`, leverage-setting, account-mode change or transfer
method belongs in that initial interface. Unknown account mode, pagination gaps,
stale snapshots or identity conflicts must block reconciliation, not update paper
cash. Compare snapshots to a separately namespaced actual-account observation DB;
never merge exchange state into the simulation ledger as a restart shortcut.

## Migration prerequisites, not enabled features

1. Review current official Classic Futures product/account-mode and read-only
   permissions documentation at implementation time. Public contract endpoints
   cannot verify a private account's Hedge Mode. No assumption about support is
   encoded here; this design is not an API compatibility claim.
2. After the explicit review above, begin with isolated read-only snapshots and
   idempotent reconciliation, with least-privilege new credentials managed outside
   code and no Futures trading/withdrawal scope. Document version/rate limits,
   clock skew and namespace ownership. Private authentication remains unimplemented.
3. Before any two-leg PAPER experiment, introduce tested shared margin, gross/net
   exposure, liquidation-model limitations, correlated stops, per-side positions,
   fees/carry and simultaneous long/short risk aggregation. The same initial
   capital cannot be independently assigned to each leg. Preserve one-position
   defaults until this separate work is authorized and passes tests.
4. Any eventual actual-order connector is a separate future authorization and
   design/review gate. Public-paper success, CI, a completed soak or profit does
   not grant that authorization. Never reuse the compromised credential.
