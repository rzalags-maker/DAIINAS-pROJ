"""Local, public-data-only DAIINAS Control Room (Milestone 1)."""
import json
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from .intelligence import analyze, normalize
from .market_intelligence import update as update_market_intelligence
from .moneyflow import BestQuotes, Execution, snapshot as flow_snapshot

# Official public-market-data host.  It avoids the region-restricted trading API;
# this module has no authenticated or order endpoints.
BINANCE = 'https://data-api.binance.vision'
KRAKEN = 'https://api.kraken.com'
SYMBOLS = {'BTCUSDT': ('BTCUSDT', 'XBTUSDT'), 'ETHUSDT': ('ETHUSDT', 'ETHUSDT')}


def get_json(url):
    with urlopen(Request(url, headers={'User-Agent': 'DAIINAS-Control-Room/2.0'}), timeout=8) as response:
        return json.load(response)


class SignalStore:
    """Short-lived connections avoid cross-thread SQLite ownership entirely."""
    def __init__(self, path):
        self.path = str(path)
        self._initialize()

    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute('PRAGMA busy_timeout=5000')
        return connection

    def _initialize(self):
        with self._connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS intelligence_signals '
                       '(id TEXT PRIMARY KEY, available_ms INTEGER NOT NULL, payload TEXT NOT NULL)')

    def append(self, payload):
        with self._connection() as db:
            db.execute('INSERT OR IGNORE INTO intelligence_signals VALUES (?,?,?)',
                       (payload['evidence_sha256'], payload['available_ms'],
                        json.dumps(payload, sort_keys=True)))

    def recent(self):
        with self._connection() as db:
            return [json.loads(row[0]) for row in db.execute(
                'SELECT payload FROM intelligence_signals ORDER BY available_ms DESC LIMIT 50')]


class PublicClient:
    def __init__(self, fetch=get_json, clock=lambda: int(time.time() * 1000)):
        self.fetch, self.clock, self.market_state = fetch, clock, {}

    def _fetch(self, url):
        started = self.clock()
        value = self.fetch(url)
        received = self.clock()
        return value, received, max(0, received - started)

    def snapshot(self, symbol='BTCUSDT'):
        if symbol not in SYMBOLS:
            raise ValueError('UNSUPPORTED_SYMBOL')
        binance_symbol, kraken_symbol = SYMBOLS[symbol]
        book, book_received, book_latency = self._fetch(BINANCE + '/api/v3/ticker/bookTicker?symbol=' + binance_symbol)
        raw_trades, trades_received, trades_latency = self._fetch(BINANCE + '/api/v3/trades?symbol=' + binance_symbol + '&limit=100')
        executions = [Execution(int(t['time']), float(t['price']), float(t['qty']), 1.0,
                      'sell' if t['isBuyerMaker'] else 'buy', str(t['id']))
                      for t in sorted(raw_trades, key=lambda item: int(item['time']))]
        quote = BestQuotes(book_received, float(book['bidPrice']), float(book['askPrice']),
                           float(book['bidQty']), float(book['askQty']), 1.0)
        try:
            flow = flow_snapshot(now_ms=trades_received, period_ms=30_000, trades=executions, quote=quote)
            flow_data = {'status': 'OBSERVED_RECENT_WINDOW_NOT_CUMULATIVE_CVD',
                         'recent_100_trade_quote_notional_delta': flow.cvd_notional,
                         'recent_100_trade_quote_notional': flow.traded_notional,
                         'trade_count': len(executions), 'spread_bps': flow.spread_bps}
        except (ValueError, KeyError):
            flow_data = {'status': 'UNKNOWN_UNVERIFIED_TRADE_WINDOW'}
        binance = normalize('BINANCE', {'symbol': binance_symbol, 'canonical_symbol': symbol,
            'b': book['bidPrice'], 'a': book['askPrice'], 'B': book['bidQty'], 'A': book['askQty'],
            'flow_status': flow_data['status']}, received_ms=book_received, request_latency_ms=book_latency)
        observations, errors = [binance], []
        try:
            raw, kraken_received, kraken_latency = self._fetch(KRAKEN + '/0/public/Ticker?pair=' + kraken_symbol)
            value = next(iter(raw['result'].values()))
            observations.append(normalize('KRAKEN', {'symbol': kraken_symbol, 'canonical_symbol': symbol,
                'bid': value['b'][0], 'ask': value['a'][0], 'bid_size': value['b'][2], 'ask_size': value['a'][2]},
                received_ms=kraken_received, request_latency_ms=kraken_latency))
        except Exception as exc:
            errors.append('KRAKEN_UNAVAILABLE:' + type(exc).__name__)
        result = analyze(observations) if len(observations) == 2 else {
            'mode': 'INTELLIGENCE', 'orders_enabled': False, 'manual_plan_only': True, 'bias': 'NEUTRAL',
            'confidence': 'LOW', 'data_quality': 'INCOMPLETE_SECOND_VENUE', 'evidence': [o.__dict__ for o in observations],
            'available_ms': book_received, 'errors': errors,
            'scenario_status': 'NO_ACTIONABLE_SCENARIO_UNTIL_VALIDATED_STRUCTURE_AND_MODEL_A_RISK'}
        candles, candle_received, candle_latency = self._fetch(BINANCE + '/api/v3/klines?symbol=' + binance_symbol + '&interval=1m&limit=80')
        candle_rows = [{'t': row[0], 'o': row[1], 'h': row[2], 'l': row[3], 'c': row[4], 'v': row[5]} for row in candles]
        core = update_market_intelligence(self.market_state.get(symbol), now=candle_received,
            quote={'bid': book['bidPrice'], 'ask': book['askPrice'], 'bid_base_size': book['bidQty'], 'ask_base_size': book['askQty']},
            book={'available_ms': book_received, 'bid_base_size': book['bidQty'], 'ask_base_size': book['askQty']},
            trades=[{'price': trade.price, 'quantity': trade.contracts, 'buyer_is_maker': trade.aggressor_side == 'sell',
                     'received_ms': trade.time_ms} for trade in executions], fee_rate=0.0, slippage_bps=0.0)
        self.market_state[symbol] = core
        result.update(symbol=symbol, candles=candle_rows, order_flow=flow_data,
            depth={'bid': book['bidPrice'], 'ask': book['askPrice'], 'bid_size': book['bidQty'], 'ask_size': book['askQty'],
                   'source_event_timestamp_status': 'SOURCE_TIMESTAMP_UNAVAILABLE'},
            core_analysis={'engine': 'daiinas.market_intelligence.update', 'regime': core['regime'],
                           'reason': core['reason'], 'spread_bps': core['spread_bps'], 'data_fresh': core['data_fresh']},
            source_status='PUBLIC_NO_AUTH', request_latency_ms={'binance_book': book_latency,
                'binance_trades': trades_latency, 'kraken_ticker': observations[-1].request_latency_ms if len(observations) == 2 else None,
                'binance_candles': candle_latency})
        return result


PAGE = '''<!doctype html><meta charset="utf-8"><title>DAIINAS Control Room</title><style>body{margin:0;background:#09111d;color:#d8e5f3;font:14px system-ui}header,main{max-width:1440px;margin:auto;padding:16px}.grid{display:grid;grid-template-columns:2fr 1fr;gap:12px}.card{background:#101d2d;border:1px solid #28405c;border-radius:8px;padding:12px}canvas{width:100%;height:360px;background:#07101a}button,input{padding:8px;background:#172b40;color:#fff;border:1px solid #476984}pre{white-space:pre-wrap}</style><header><b>DAIINAS Control Room</b> · Public data · Manual decisions only · <span id="status">loading</span> <input id="symbol" value="BTCUSDT"><button onclick="load()">Refresh</button></header><main class="grid"><section class="card"><canvas id="chart" width="900" height="360"></canvas><p id="summary"></p></section><aside><div class="card"><b>Evidence-based status</b><pre id="scenario"></pre></div><div class="card"><b>Existing DAIINAS analysis</b><pre id="flow"></pre></div><div class="card"><b>Evidence / alerts</b><pre id="evidence"></pre></div></aside></main><script>function chart(c){let x=document.querySelector('#chart'),q=x.getContext('2d');if(!c||!c.length)return;let lo=Math.min(...c.map(z=>+z.l)),hi=Math.max(...c.map(z=>+z.h));if(hi===lo){hi+=1;lo-=1}let w=x.width/c.length,Y=v=>x.height-(v-lo)/(hi-lo)*x.height;q.clearRect(0,0,x.width,x.height);q.fillStyle='#9db2c8';q.fillText('low '+lo.toFixed(2)+' / high '+hi.toFixed(2),8,16);for(let[i,z]of c.entries()){let up=+z.c>=+z.o;q.strokeStyle=q.fillStyle=up?'#42d392':'#ec6270';q.beginPath();q.moveTo(i*w+w/2,Y(+z.h));q.lineTo(i*w+w/2,Y(+z.l));q.stroke();q.fillRect(i*w+w*.2,Y(Math.max(+z.o,+z.c)),w*.6,Math.max(1,Math.abs(Y(+z.o)-Y(+z.c))))}}async function load(){let s=document.querySelector('#symbol').value;try{let r=await fetch('/api/snapshot?symbol='+encodeURIComponent(s)),d=await r.json();if(!r.ok)throw Error(d.error);chart(d.candles);status.textContent=d.source_status;summary.textContent='Bias: '+d.bias+' · '+d.data_quality+' · received '+new Date(d.available_ms).toLocaleTimeString();scenario.textContent=JSON.stringify({status:d.scenario_status,bias:d.bias,confidence:d.confidence,levels:'none: no validated structure / Model A risk sizing'},null,2);flow.textContent=JSON.stringify({core:d.core_analysis,flow:d.order_flow,depth:d.depth},null,2);evidence.textContent=JSON.stringify(d.evidence,null,2)}catch(e){status.textContent='PUBLIC DATA UNAVAILABLE: '+e.message}}load();setInterval(load,15000)</script>'''


def build_server(host='127.0.0.1', port=0, db='control-room.sqlite3', client=None):
    client, store = client or PublicClient(), SignalStore(Path(db))
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def send_payload(self, code, payload, kind='application/json'):
            raw = payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()
            self.send_response(code); self.send_header('Content-Type', kind); self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store'); self.send_header('X-Content-Type-Options', 'nosniff'); self.end_headers(); self.wfile.write(raw)
        def do_GET(self):
            path = urlparse(self.path)
            if path.path == '/': return self.send_payload(200, PAGE, 'text/html; charset=utf-8')
            if path.path == '/api/snapshot':
                try:
                    result = client.snapshot(parse_qs(path.query).get('symbol', ['BTCUSDT'])[0]); store.append(result); return self.send_payload(200, result)
                except ValueError as exc: return self.send_payload(400, {'error': str(exc)})
                except Exception: return self.send_payload(503, {'error': 'PUBLIC_DATA_UNAVAILABLE'})
            if path.path == '/api/history': return self.send_payload(200, store.recent())
            return self.send_payload(404, {'error': 'NOT_FOUND'})
    return ThreadingHTTPServer((host, port), Handler)


def serve(host='127.0.0.1', port=8765, db='control-room.sqlite3'):
    server = build_server(host, port, db)
    print('DAIINAS Control Room: http://%s:%s (public/manual only)' % (host, port))
    server.serve_forever()
