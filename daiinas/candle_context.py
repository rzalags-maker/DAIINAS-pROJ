"""Closed public OHLCV context. Candles never supply trade-flow/CVD evidence."""
import asyncio
from decimal import Decimal
import hashlib
from .continuous_store import digest

INTERVALS=(1,5,15)
COUNT=16


def summarize(rows,*,minutes,asof_ms,multiplier):
    """Strict contiguous closed bars as available at the request decision time."""
    interval=minutes*60000;end=asof_ms//interval*interval;start=end-COUNT*interval
    found={}
    for row in rows:
        if not isinstance(row,list) or len(row)<6 or type(row[0]) is not int:raise ValueError('Invalid OHLCV row')
        t=row[0]
        if t>=end:continue  # a live candle must never influence a decision
        if t<start:continue
        if t%interval or t in found:raise ValueError('Duplicate/misaligned closed candle')
        values=[Decimal(str(v)) for v in row[1:6]]
        if any(not x.is_finite() for x in values):raise ValueError('Nonfinite OHLCV')
        o,h,l,c,v=values
        if min(o,h,l,c)<=0 or v<0 or h<max(o,l,c) or l>min(o,h,c):raise ValueError('Invalid OHLCV range/volume')
        found[t]=values
    if sorted(found)!=list(range(start,end,interval)):raise ValueError('Missing closed candles; no gap fill')
    bars=[found[t] for t in sorted(found)];closes=[b[3] for b in bars]
    moves=(closes[-1]/closes[0]-1)*10000
    true_ranges=[max(b[1]-b[2],abs(b[1]-bars[i-1][3]),abs(b[2]-bars[i-1][3])) if i else b[1]-b[2] for i,b in enumerate(bars)]
    return {'status':'VERIFIED_CLOSED_OHLCV','minutes':minutes,'asof_ms':asof_ms,'closed_through_ms':end,'count':COUNT,
            'direction':'LONG' if moves>0 else 'SHORT' if moves<0 else 'RANGE','move_bps':str(moves),
            'atr_bps':str(sum(true_ranges)/COUNT/closes[-1]*10000),'recent_high':str(max(b[1] for b in bars)),
            'recent_low':str(min(b[2] for b in bars)),'swing_low':str(min(b[2] for b in bars[-3:])),'swing_high':str(max(b[1] for b in bars[-3:])),'base_volume':str(sum(b[4] for b in bars)*Decimal(str(multiplier))),
            'raw_rows_sha256':digest(rows),'order_flow_status':'NOT_OBSERVED_IN_OHLCV'}


def analyze(packet,*,now_ms,expected_multiplier):
    if packet.get('source')!='KuCoin public /api/v1/kline/query':raise ValueError('Unknown candle provenance')
    asof=packet['asof_ms']
    if type(asof) is not int or not 0<=now_ms-asof<=90000:raise ValueError('Future/stale candle receipt')
    if packet['multiplier']!=str(expected_multiplier):raise ValueError('Changed candle contract multiplier')
    frames={}
    for minutes in INTERVALS:
        raw=packet['frames'][str(minutes)]
        if raw.get('status')!='DOWNLOADED':raise ValueError('Candle download unavailable: '+str(minutes))
        if digest(raw['rows'])!=raw['rows_sha256']:raise ValueError('Candle provenance digest mismatch')
        frames[str(minutes)]=summarize(raw['rows'],minutes=minutes,asof_ms=asof,multiplier=expected_multiplier)
    return {'status':'VERIFIED_CLOSED_OHLCV','asof_ms':asof,'frames':frames,'packet_sha256':digest(packet)}


def admission(context,*,side,now_ms):
    if not context or context.get('status')!='VERIFIED_CLOSED_OHLCV':return 'missing_verified_closed_OHLCV'
    if not 0<=now_ms-context['asof_ms']<=90000:return 'stale_closed_OHLCV'
    opposite='SHORT' if side=='LONG' else 'LONG'
    if all(context['frames'][str(n)]['direction']==opposite for n in (5,15)):return 'closed_5m_15m_countertrend'
    return None


async def download(rest,symbols,specs,*,asof_ms,cache):
    """Only the bounded deep shortlist; 3 concurrent public calls, closed-bar cache."""
    semaphore=asyncio.Semaphore(3)
    async def frame(symbol,minutes):
        end=asof_ms//(minutes*60000)*(minutes*60000);key=(symbol,minutes,end)
        if key in cache:return cache[key]
        params={'symbol':symbol,'granularity':minutes,'from':end-COUNT*minutes*60000,'to':end-1}
        try:
            async with semaphore:rows,body,_=await asyncio.to_thread(rest.request,'/api/v1/kline/query',params)
            result={'status':'DOWNLOADED','rows':rows,'rows_sha256':digest(rows),
                    'body_sha256':hashlib.sha256(body).hexdigest() if body else None,'params':params}
            cache[key]=result;return result
        except (OSError,ValueError,KeyError,TypeError) as exc:
            return {'status':'UNAVAILABLE','exception_type':type(exc).__name__,'params':params}
    packets=[]
    for symbol in sorted(set(symbols)):
        if symbol not in specs:continue
        values=await asyncio.gather(*(frame(symbol,n) for n in INTERVALS))
        packets.append({'source':'KuCoin public /api/v1/kline/query','symbol':symbol,'asof_ms':asof_ms,
                        'multiplier':str(specs[symbol]['rules']['contract_size']),'frames':dict(zip(map(str,INTERVALS),values))})
    keep={(p['symbol'],n,asof_ms//(n*60000)*(n*60000)) for p in packets for n in INTERVALS}
    for key in list(cache):
        if key not in keep:del cache[key]
    return packets
