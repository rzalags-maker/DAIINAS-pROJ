"""DAIINAS 2.0 public, manual-only intelligence vertical slice.

No credentials, account access, orders or execution permissions exist here.
"""
from dataclasses import dataclass, asdict
from decimal import Decimal
import hashlib, json, time

D=lambda x: Decimal(str(x))

@dataclass(frozen=True)
class PublicObservation:
    source: str; venue: str; symbol: str; event_ms: int; received_ms: int
    bid: str; ask: str; bid_size: str; ask_size: str; trade_buy: str='0'; trade_sell: str='0'
    def validate(self):
        if not self.source or not self.venue or not self.symbol or not isinstance(self.event_ms,int) or not isinstance(self.received_ms,int): raise ValueError('INVALID_PROVENANCE')
        if self.event_ms > self.received_ms or self.received_ms-self.event_ms>15000: raise ValueError('STALE_OR_FUTURE_OBSERVATION')
        if min(D(self.bid),D(self.ask),D(self.bid_size),D(self.ask_size),D(self.trade_buy),D(self.trade_sell))<0 or D(self.bid)>=D(self.ask): raise ValueError('INVALID_PUBLIC_MARKET')

def normalize(source, payload, *, received_ms=None):
    """Normalize injected Binance/Kraken-like public top-of-book fixtures."""
    now=int(time.time()*1000) if received_ms is None else received_ms
    if source=='BINANCE':
        o=PublicObservation('BINANCE','BINANCE_SPOT',payload['symbol'],int(payload['E']),now,payload['b'],payload['a'],payload['B'],payload['A'],payload.get('buyVolume','0'),payload.get('sellVolume','0'))
    elif source=='KRAKEN':
        o=PublicObservation('KRAKEN','KRAKEN_SPOT',payload['symbol'],int(payload['event_ms']),now,payload['bid'],payload['ask'],payload['bid_size'],payload['ask_size'],payload.get('buy_volume','0'),payload.get('sell_volume','0'))
    else: raise ValueError('UNSUPPORTED_PUBLIC_SOURCE')
    o.validate(); return o

def analyze(observations):
    """Three independent, explainable modules: flow, book, cross-venue structure."""
    if len(observations)<2: raise ValueError('SECOND_VENUE_REQUIRED')
    for o in observations:o.validate()
    mids=[(D(o.bid)+D(o.ask))/2 for o in observations]
    flows=[D(o.trade_buy)-D(o.trade_sell) for o in observations]
    books=[(D(o.bid_size)-D(o.ask_size))/(D(o.bid_size)+D(o.ask_size)) if D(o.bid_size)+D(o.ask_size)>0 else D(0) for o in observations]
    disagreement=max(mids)-min(mids)
    direction='LONG' if sum(flows)>0 and sum(books)>0 else 'SHORT' if sum(flows)<0 and sum(books)<0 else 'NEUTRAL'
    quality='COMPLETE' if disagreement/max(mids)<D('.002') else 'CROSS_VENUE_DISAGREEMENT'
    confidence='LOW' if direction=='NEUTRAL' or quality!='COMPLETE' else 'HYPOTHESIS_ONLY'
    midpoint=sum(mids)/len(mids); spread=max((D(o.ask)-D(o.bid))/((D(o.ask)+D(o.bid))/2)*10000 for o in observations)
    invalidation=midpoint*(D('.998') if direction=='LONG' else D('1.002')) if direction!='NEUTRAL' else None
    target=midpoint*(D('1.004') if direction=='LONG' else D('.996')) if direction!='NEUTRAL' else None
    evidence=[asdict(o) for o in observations]
    digest=hashlib.sha256(json.dumps(evidence,sort_keys=True).encode()).hexdigest()
    return {'mode':'INTELLIGENCE','orders_enabled':False,'bias':direction,'confidence':confidence,'data_quality':quality,
            'regime':'CROSS_VENUE_CONSISTENT' if quality=='COMPLETE' else 'UNKNOWN', 'mid_price':str(midpoint),
            'invalidation_level':str(invalidation) if invalidation else None,'target_level':str(target) if target else None,
            'expected_spread_bps':str(spread),'cvd_proxy':str(sum(flows)),'book_imbalance':str(sum(books)/len(books)),
            'entry_confirmation':'require_new_public_observation_and_manual_confirmation','manual_plan_only':True,
            'evidence':evidence,'evidence_sha256':digest,'available_ms':max(o.received_ms for o in observations)}
