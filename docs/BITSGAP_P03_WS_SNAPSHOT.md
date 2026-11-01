# P0.3 — explicit WebSocket account snapshots (draft)

## Cause and scope

The owner's prior live P0.2 Mac observation authenticated against KuCoin Futures.
REST balance validated, but WS receipt age exceeded the 15-second freshness TTL.
A later session retained previous-generation WS evidence and did not establish
current cross-transport balance evidence. Private financial amounts are omitted.

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

## Receive-time audit correction

A completed receive task can wait for processing while a periodic snapshot or its
shared-rate-budget wait runs. Snapshot provenance now compares the actual local
receive-completion monotonic time to the request-send time, not processing time.
A frame received before the new request cannot consume its pending topic or renew
unchanged evidence. The stored local receipt timestamp likewise remains the receive
time if processing is delayed. This cannot establish a server/exchange event time,
and the protocol's missing correlation ID remains an explicit limitation.
Null responses now pass the same strict envelope/metadata checks as non-null values
before any pending snapshot is consumed. Neither correction changes exposure-null
semantics, the signer, rate limits, Model A or execution permissions.

### Audit evidence (cloud-only; owner Mac acceptance pending)

The untouched P0.3 head `dcb4fde0df4f6e03cec50bccfebc951694e197e0`
passed 459/459 tests on Linux Python 3.13.5. A new watch-loop test reproduced
receive-time restamping against that untouched source; the corrected stream
passes the same scenario. Four new tests cover the timer race, pre-request frames,
delayed processing and malformed null envelopes. Final full regression: 463/463
PASS; focused stream regression: 22/22 PASS, ordinary unittest without timer helper.
Official WS/topic reference revision: `d27611b63d56c65c9797e61d34b40b1f175a7664`.

Cloud dependencies: cryptography 43.0.0, websockets 16.0 and certifi 2025.1.31.
The certifi trust context loads with CERT_REQUIRED and hostname checking enabled;
this is not a live Bitsgap TLS handshake result. No owner credential file was
accessed and no authenticated request was made. The owner must still run the
bounded observer on the trusted Mac, compare timestamps/counters privately,
check stop/reconnect generations and independently verify terminal parity.
