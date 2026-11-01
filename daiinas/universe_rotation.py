"""Deterministic read-only rotating watchlist for the KuCoin Futures universe.

Preflight eligibility is for deeper observation, NEVER a trade entry signal.
Open-position symbols passed as pins remain subscribed even when ineligible.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class RotationPolicy:
    deep_slots: int = 5
    minimum_residence_ms: int = 120_000
    promotion_margin: float = 2.0

    def __post_init__(self):
        if not 1 <= self.deep_slots <= 20 or self.minimum_residence_ms < 0 or self.promotion_margin < 0:
            raise ValueError('Invalid watchlist rotation policy')


class CapacityError(ValueError):
    pass


def select(report, *, now_ms, previous=(), entered_at=None, pinned=(),
           policy=RotationPolicy()):
    """Returns selected symbols + persisted entry timestamps, no exchange actions.

    - Pins consume slots before anything else, even if preflight-ineligible.
    - Ineligible unpinned symbols are evicted immediately.
    - Existing eligible symbols are retained until dwell expires.
    - Thereafter, outsiders must beat the weakest replaceable symbol by
      promotion_margin to avoid noisy subscription churn.
    """
    if now_ms < 0 or not isinstance(now_ms, int):
        raise ValueError('Invalid decision timestamp')
    if report.get('time_ms', 0) > now_ms or now_ms-report.get('time_ms', 0) > 120_000:
        raise ValueError('Stale or future whole-market preflight')
    candidates = report['selected_for_deeper_observation']
    ranked = {}
    for item in candidates:
        sym = item['symbol']
        if sym in ranked:
            raise ValueError('Duplicate universe candidate')
        if not item.get('eligible') or item.get('liquidity_score_not_alpha') is None:
            raise ValueError('Invalid shortlisted candidate')
        ranked[sym] = float(item.get('selection_score',item['liquidity_score_not_alpha']))
    pinned = sorted(set(pinned))
    if len(pinned) > policy.deep_slots:
        raise CapacityError('Open-position pins exceed depth subscription capacity')
    entered_at = entered_at or {}
    result = list(pinned)
    for sym in previous:
        if sym in result or sym not in ranked or len(result) >= policy.deep_slots:
            continue
        result.append(sym)
    for sym in sorted(ranked, key=lambda s:(-ranked[s],s)):
        if len(result) >= policy.deep_slots:
            break
        if sym not in result:
            result.append(sym)
    # Only promote outsiders when a retained symbol is old enough and inferior.
    for challenger in sorted(ranked, key=lambda s:(-ranked[s],s)):
        if challenger in result:
            continue
        replaceable = [s for s in result if s not in pinned
                       and (now_ms-int(entered_at.get(s, 0))) >= policy.minimum_residence_ms]
        if not replaceable:
            continue
        weakest = min(replaceable,key=lambda s:(ranked.get(s,float('-inf')),s))
        if ranked[challenger] > ranked.get(weakest,float('-inf')) + policy.promotion_margin:
            result.remove(weakest)
            result.append(challenger)
    result.sort(key=lambda s:(0 if s in pinned else 1,-ranked.get(s,float('-inf')),s))
    result_time = {s:int(entered_at[s]) if s in previous and s in entered_at else now_ms for s in result}
    return {'time_ms':now_ms,'deep_symbols':result,'entered_at':result_time,
            'pinned':pinned, 'blocked_new_entries': sorted(s for s in pinned if s not in ranked),
            'watch_pool':list(ranked), 'no_trade':True,
            'reason':'Snapshot-based candidate rotation only; no strategy edge validated'}
