# P0.3 — explicit WebSocket account snapshots (draft)

## Cause and scope

Owner's live P0.2 Mac observation (2026-11-01) authenticated against Bitsgap
KuCoin Futures `em=24`. REST balance was validated and showed a historical
61.076916622 USDT observation. The private view reported a current REST sample
but a WS sample ~23.6 seconds old, exceeding the 15-second freshness TTL.
The next completed 60-second session retained a WS record from a previous
generation and never established current cross-transport balance evidence.

Per the provider WS contract, `subs:true` creates an update subscription.
An account that does not change need not emit another update. Omitting
`subs` is an explicitly requested one-time WS snapshot; the same four
account topics support it. The provider's WS responses have no correlation ID.

Sources:
- https://github.com/Bitsgap/bitsgap-api-docs/blob/main/docs/ws/README.md
- https://github.com/Bitsgap/bitsgap-api-docs/blob/main/docs/topics/trading.md

## Implementation

- Retain the authenticated account WS subscription.
- After post-subscribe REST resync, request a separate WS snapshot batch for
  exactly `balance`, `orders`, `positions`, `positions_settings` at the
  already-discovered authenticated Futures `em`. No `subs` field, and no
  order/trading topic.
- Repeat the batch every 8 seconds while the WS session is alive.
- Consume the *existing shared* REST/WS per-topic request budget before each
  batch (settings 1/s and 5/10s; others 5/s and 20/10s).
- Only a validated, correctly scoped WS data frame received within 5 seconds
  of an outstanding explicit request can refresh an unchanged WS snapshot.
  An unsolicited identical subscription frame remains a duplicate, and
  never renews the timestamp. An explicit response is counted once per topic
  per batch; pending requests clear on reconnect/disconnect.
- Rate failures, provider-null exposure and invalid shapes still fail closed.
- Final worker output includes only safe WS auth/snapshot/rejection counts and
  fixed-vocabulary failure status; no keys, account IDs, balances, or raw frames.

**Protocol limitation:** the server does not echo request IDs for account
frames. Thus, any appropriately scoped data frame arriving during an outstanding
snapshot window may be a subscription update instead of its one-time response.
Both are fresh inbound server observations, but the code must not claim to
cryptographically prove which request produced the frame. Local timestamps are
receipt times, not exchange-signed timestamps.

## Acceptance gates

1. Offline: tests for no-write topic allowlist, rate control, snapshot requests
   without `subs`, original WS subscription still active, duplicate handling,
   explicit-WS refresh, disconnected/reconnected sessions, no credential output.
2. Owner-private Mac: rerun P0.2 60-second session on a locally configured
   `SSL_CERT_FILE`, then inspect the private viewer early and after 20–40 sec.
   Record `ws_snapshot_batches_sent` / `ws_snapshot_responses` and
   `balance_state` while connected. Do not infer success from final exit code 2.
3. Verify restored fresh REST/WS parity on a quiescent account, no false current
   balance after the observer stops, and independent provider-null handling.
4. Owner's same-window Bitsgap Futures terminal parity remains a separate
   acceptance gate. There is still no verified account identity, full margin,
   provider-complete exposure or native persistent TP/SL.

**Execution remains disabled.** No live order routing, Model A funding,
position modes, risk parameters, keys, Github secrets or main branch are changed.
Do not merge stacked PRs or run live order execution automatically.
