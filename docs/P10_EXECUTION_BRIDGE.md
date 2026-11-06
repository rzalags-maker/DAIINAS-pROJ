# P10 offline execution bridge

Issue #44 implementation uses one deterministic, network-free replay state
machine. It is not a trading gateway and exposes no send/cancel/credential API.

| Candidate | Code result | Classification |
| --- | --- | --- |
| CCXT | `CCXTKucoinFuturesAdapter` normalizes recorded market precision/contract data and treats advertised attached TP/SL as non-acceptance | `DOCUMENTED_ONLY` |
| KuCoin native | `KucoinNativeFuturesAdapter` validates the documented `/api/v1/st-orders` fixture shape and produces no transport | `REPLAY_VERIFIED` for fixtures; `VENUE_UNVERIFIED` |
| Hummingbot | Reference only: its KuCoin Perpetual connector correlates client/exchange IDs and processes REST/WS updates (`kucoin_perpetual_derivative.py`, pinned P07 source); no verified native TP/SL/OCO primitive is imported | `DOCUMENTED_ONLY` |
| Bitsgap | Existing P06/P09 path unchanged | `BLOCKED` |

The common replay accepts entry ACK, exact fills, two acknowledged TP/SL child
IDs and terminal sibling state. It blocks partial/mismatched coverage,
unprotected exposure, ambiguous submission, external exposure, unavailable
positions/free margin and unconfirmed sibling state. Duplicate event IDs are
exactly-once. `new_entries_allowed` is always false: the prototype cannot
authorize an order.

**Preferred future architecture:** native KuCoin adapter shape plus the existing
P04 journal, only after separately authorized authenticated venue evidence.
**Current decision:** `NO_SAFE_ADAPTER_PROVEN` for live use. Missing evidence is
real native conditional-order acceptance, persistence, OCO/sibling behavior,
complete account reconciliation and protected restart recovery.
