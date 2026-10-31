"""KuCoin Classic Futures public REST schemas and loss-detecting L2 book."""
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
import json
from urllib.request import Request, urlopen
from urllib.parse import urlencode, urlsplit

from ..models import Candle
from ..risk import ContractRules
from ..flow import AggressiveTrade, BookSnapshot

MAPPING = {'BTCUSDT': 'XBTUSDTM', 'ETHUSDT': 'ETHUSDTM', 'SOLUSDT': 'SOLUSDTM',
           'BNBUSDT': 'BNBUSDTM', 'XRPUSDT': 'XRPUSDTM'}
REVERSE = {value: key for key, value in MAPPING.items()}
TOPICS = ('execution', 'tickerV2', 'level2')


class DataGap(ValueError):
    """Data is not safe to use; reset the connection and rebuild books."""


class SequenceGap(DataGap):
    def __init__(self, expected, actual):
        super().__init__(f'Order-book sequence gap: expected {expected}, received {actual}')


def number(value, zero=False):
    try:
        d = Decimal(str(value))
    except InvalidOperation as exc:
        raise DataGap('Invalid decimal') from exc
    if not d.is_finite() or d < 0 or (d == 0 and not zero):
        raise DataGap('Non-finite or non-positive market value')
    return d


def integer(value):
    if isinstance(value, bool) or not str(value).isdigit():
        raise DataGap('Expected non-negative integer')
    return int(value)


def timestamp(value, unit, received_ms, max_age_ms=15000):
    t = integer(value)
    if unit == 'ns':
        t //= 1_000_000
    elif unit != 'ms':
        raise ValueError('Explicit timestamp unit required')
    if t > received_ms+3000 or received_ms-t > max_age_ms:
        raise DataGap('Stale or future market timestamp')
    return t


def contracts(rows, symbols, leverage):
    """Normalize API lots to contract counts, multiplier to base units/contract.

    Futures metadata publishes lotSize as its minimum and increment. It does not
    publish Spot's minFunds. Zero means no additional notional floor was supplied;
    it never disables lotSize, maximum quantity, or account-risk checks.
    """
    found = {r['symbol']: r for r in rows}
    rules, normalized = {}, {}
    for symbol in symbols:
        r = found[MAPPING[symbol]]
        if (r['status'] != 'Open' or r['quoteCurrency'] != 'USDT' or
                r['settleCurrency'] != 'USDT' or r['isInverse'] is not False or
                r.get('expireDate') is not None or r['type'] != 'FFWCSX'):
            raise DataGap('Expected open, linear USDT perpetual contract')
        if leverage > float(r['maxLeverage']) or leverage*float(r['initialMargin']) > 1.00000001:
            raise DataGap('Configured leverage exceeds public contract limit')
        expected_base={'BTCUSDT':('XBT','BTC')}
        if r['baseCurrency'] not in expected_base.get(symbol,(symbol[:-4],)):
            raise DataGap('Wrong contract base currency mapping')
        if number(r.get('takerFixFee',0),zero=True) != 0:
            raise DataGap('Unsupported nonzero fixed taker fee')
        lot = integer(r['lotSize'])
        if lot < 1:
            raise DataGap('Contract lot must be positive')
        rule = ContractRules(symbol, str(lot), str(integer(r['maxOrderQty'])), str(lot),
                             str(number(r['tickSize'])), str(number(r.get('minNotional', 0), zero=True)),
                             str(number(r['multiplier'])))
        rules[symbol] = rule
        normalized[symbol] = {**asdict(rule), 'exchange_symbol': MAPPING[symbol],
                              'max_leverage': float(r['maxLeverage']),
                              'initial_margin': float(r['initialMargin']),
                              'taker_fee_rate': float(number(r['takerFeeRate'],zero=True)),
                              'min_notional_source': 'metadata' if 'minNotional' in r else 'not published; lotSize enforced'}
    return rules, normalized


class PublicRest:
    BASE = 'https://api-futures.kucoin.com'
    ALLOWED = {'/api/v1/contracts/active': 'GET', '/api/v1/timestamp': 'GET',
               '/api/v1/level2/snapshot': 'GET', '/api/v1/kline/query': 'GET',
               '/api/v1/bullet-public': 'POST'}

    def request(self, path, params=None):
        if path not in self.ALLOWED:
            raise ValueError('Only credential-free public market endpoints are permitted')
        method = self.ALLOWED[path]
        url = self.BASE+path+('?' + urlencode(params) if params else '')
        req = Request(url, method=method, data=b'' if method == 'POST' else None,
                      headers={'User-Agent':'DAIINAS-public-research/0.2'})
        with urlopen(req, timeout=15) as response:
            payload = response.read()
        body = json.loads(payload)
        if body.get('code') != '200000':
            raise DataGap(f'Public REST returned code {body.get("code")}')
        return body['data'], payload, url


def token_server(info):
    if not isinstance(info.get('token'), str) or not info['token']:
        raise DataGap('Missing public token')
    for server in info.get('instanceServers', []):
        u = urlsplit(server['endpoint'])
        # Never forward a public token to an arbitrary URL from a malformed response.
        if (u.scheme == 'wss' and u.hostname and u.hostname.endswith('.kucoin.com')
                and u.username is None and u.password is None and u.port in (None,443)
                and not u.query and not u.fragment and server.get('encrypt') is True
                and server.get('protocol') == 'websocket'):
            if 1000 <= integer(server['pingInterval']) <= 120000 and 1000 <= integer(server['pingTimeout']) <= 120000:
                return server
    raise DataGap('No trusted public Futures WebSocket server')


def klines(rows, start, end, interval, multiplier):
    bars = [Candle(integer(r[0]), *(float(number(v)) for v in r[1:5]),
                   float(number(r[5],zero=True))*multiplier) for r in rows
            if start <= integer(r[0]) < end]
    bars.sort(key=lambda b: b.time)
    if [b.time for b in bars] != list(range(start,end,interval)):
        raise DataGap('Missing or duplicate KuCoin closed candles; no synthetic gap fill')
    return bars


class OrderBook:
    def __init__(self, symbol, rule):
        self.symbol, self.rule = symbol, rule
        self.reset()

    def reset(self):
        self.sequence = None
        self.bids, self.asks = {}, {}
        self.verified = False
        self.time = 0

    def level(self, price, qty):
        p, q = number(price), number(qty, zero=True)
        if p % Decimal(self.rule.tick_size) or q % Decimal(self.rule.step_size):
            raise DataGap('Book price/size not aligned to contract tick/lot')
        return p, q

    def check(self):
        if not self.bids or not self.asks or max(self.bids) >= min(self.asks):
            raise DataGap('Empty or crossed order book')

    def snapshot(self, row, received_ms):
        self.reset()
        if row['symbol'] != MAPPING[self.symbol]:
            raise DataGap('Wrong snapshot symbol')
        self.time = timestamp(row['ts'],'ns',received_ms)
        for side in ('bids','asks'):
            for price, qty in row[side]:
                p,q = self.level(price,qty)
                if q:
                    getattr(self,side)[p] = q
        self.check()
        self.sequence = integer(row['sequence'])
        # Only a contiguous post-snapshot WebSocket delta verifies the bridge.

    def delta(self, row, received_ms):
        try:
            return self._delta(row, received_ms)
        except (ValueError, KeyError):
            self.reset()
            raise

    def _delta(self, row, received_ms):
        if self.sequence is None:
            raise DataGap('Book delta without subscribed snapshot')
        seq = integer(row['sequence'])
        if seq <= self.sequence:
            return False  # subscription buffer at/before the REST snapshot
        if seq != self.sequence+1:
            expected=self.sequence+1
            self.reset()
            raise SequenceGap(expected,seq)
        t = timestamp(row['timestamp'],'ms',received_ms)
        if t < self.time:
            self.reset()
            raise DataGap('Book timestamp moved backwards')
        price, side, qty = row['change'].split(',')
        if side not in ('buy','sell'):
            raise DataGap('Unknown book side')
        p,q = self.level(price,qty)
        levels = self.bids if side == 'buy' else self.asks
        if q:
            levels[p] = q
        else:
            levels.pop(p,None)
        try:
            self.check()
        except DataGap:
            self.reset()
            raise
        self.sequence, self.time, self.verified = seq, t, True
        return True

    def view(self):
        if not self.verified:
            raise DataGap('Book is not sequence-verified')
        unit = float(self.rule.contract_size)
        return BookSnapshot(self.symbol,self.time,
                            tuple((float(p),float(q)*unit) for p,q in sorted(self.bids.items(),reverse=True)),
                            tuple((float(p),float(q)*unit) for p,q in sorted(self.asks.items())))


def execution(symbol, row, rule, received_ms):
    if row['symbol'] != MAPPING[symbol] or row['side'] not in ('buy','sell'):
        raise DataGap('Invalid execution symbol/side')
    t = timestamp(row['ts'],'ns',received_ms)
    qty = number(row['size'])
    if qty % Decimal(rule.step_size):
        raise DataGap('Trade size not aligned to contract lots')
    price = number(row['price'])
    if price % Decimal(rule.tick_size):
        raise DataGap('Trade price not aligned to price tick')
    return AggressiveTrade(symbol,t,float(price),float(qty)*float(rule.contract_size),row['side']=='sell')


def ticker(symbol, row, rule, received_ms):
    if row['symbol'] != MAPPING[symbol]:
        raise DataGap('Invalid ticker symbol')
    t = timestamp(row['ts'],'ns',received_ms)
    bid,ask = number(row['bestBidPrice']),number(row['bestAskPrice'])
    if bid >= ask or bid % Decimal(rule.tick_size) or ask % Decimal(rule.tick_size):
        raise DataGap('Crossed or off-tick quote')
    for key in ('bestBidSize','bestAskSize'):
        if number(row[key]) % Decimal(rule.step_size):
            raise DataGap('Off-lot quote size')
    return {'timestamp': t, 'bid':str(bid), 'ask':str(ask),
            'bid_base_size':float(row['bestBidSize'])*float(rule.contract_size),
            'ask_base_size':float(row['bestAskSize'])*float(rule.contract_size)}
