"""Provenance-preserving presentation helpers for the public Control Room.

This module deliberately does not turn an observation into an order.  A REST
top-of-book response without a provider timestamp is useful, but is never
represented as a contemporaneous exchange event.
"""
from dataclasses import asdict, dataclass
from decimal import Decimal
import hashlib
import json
import time

D = lambda value: Decimal(str(value))


@dataclass(frozen=True)
class PublicObservation:
    source: str
    venue: str
    symbol: str
    canonical_symbol: str
    event_ms: int | None
    event_timestamp_status: str
    received_ms: int
    request_latency_ms: int
    bid: str
    ask: str
    bid_size: str
    ask_size: str
    flow_status: str = 'UNKNOWN'

    def validate(self):
        if (not self.source or not self.venue or not self.symbol or
                not self.canonical_symbol or self.received_ms < 0 or
                self.request_latency_ms < 0):
            raise ValueError('INVALID_PROVENANCE')
        if self.event_ms is None:
            if self.event_timestamp_status != 'SOURCE_TIMESTAMP_UNAVAILABLE':
                raise ValueError('INVALID_TIMESTAMP_STATUS')
        elif (not isinstance(self.event_ms, int) or self.event_ms > self.received_ms
              or self.received_ms - self.event_ms > 15_000):
            raise ValueError('STALE_OR_FUTURE_OBSERVATION')
        if (min(D(self.bid), D(self.ask), D(self.bid_size), D(self.ask_size)) < 0
                or D(self.bid) >= D(self.ask)):
            raise ValueError('INVALID_PUBLIC_MARKET')


def normalize(source, payload, *, received_ms=None, request_latency_ms=0):
    """Normalize source fixtures without inventing source event timestamps."""
    now = int(time.time() * 1000) if received_ms is None else received_ms
    if source == 'BINANCE':
        event = payload.get('E')
        o = PublicObservation('BINANCE', 'BINANCE_SPOT', payload['symbol'],
            payload.get('canonical_symbol', payload['symbol']), event,
            'OBSERVED' if event is not None else 'SOURCE_TIMESTAMP_UNAVAILABLE', now,
            request_latency_ms, payload['b'], payload['a'], payload['B'], payload['A'],
            payload.get('flow_status', 'UNKNOWN'))
    elif source == 'KRAKEN':
        event = payload.get('event_ms')
        o = PublicObservation('KRAKEN', 'KRAKEN_SPOT', payload['symbol'],
            payload.get('canonical_symbol', payload['symbol']), event,
            'OBSERVED' if event is not None else 'SOURCE_TIMESTAMP_UNAVAILABLE', now,
            request_latency_ms, payload['bid'], payload['ask'], payload['bid_size'],
            payload['ask_size'], payload.get('flow_status', 'UNKNOWN'))
    else:
        raise ValueError('UNSUPPORTED_PUBLIC_SOURCE')
    o.validate()
    return o


def analyze(observations):
    """Report only what two comparable, timestamped venue observations establish."""
    if len(observations) < 2:
        raise ValueError('SECOND_VENUE_REQUIRED')
    for observation in observations:
        observation.validate()
    comparable = len({o.canonical_symbol for o in observations}) == 1
    timestamped = all(o.event_ms is not None for o in observations)
    mids = [(D(o.bid) + D(o.ask)) / 2 for o in observations]
    disagreement = max(mids) - min(mids)
    quality = ('COMPLETE' if comparable and timestamped and disagreement / max(mids) < D('.002')
               else 'SOURCE_TIMESTAMP_UNAVAILABLE' if comparable and not timestamped
               else 'CROSS_VENUE_REFERENCE_MISMATCH')
    evidence = [asdict(o) for o in observations]
    digest = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
    spread = max((D(o.ask)-D(o.bid)) / ((D(o.ask)+D(o.bid))/2)*10_000 for o in observations)
    return {
        'mode': 'INTELLIGENCE', 'orders_enabled': False, 'manual_plan_only': True,
        'bias': 'NEUTRAL', 'confidence': 'LOW', 'data_quality': quality,
        'regime': 'UNKNOWN', 'mid_price': str(sum(mids) / len(mids)),
        'invalidation_level': None, 'target_level': None,
        'scenario_status': 'NO_ACTIONABLE_SCENARIO_UNTIL_VALIDATED_STRUCTURE_AND_MODEL_A_RISK',
        'expected_spread_bps': str(spread), 'entry_confirmation':
            'require_timestamped_cross_venue_evidence_and_manual_confirmation',
        'evidence': evidence, 'evidence_sha256': digest,
        'available_ms': max(o.received_ms for o in observations),
    }
