"""Local, public-data-only DAIINAS Control Room (Milestone 1)."""
import json, sqlite3, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
from .intelligence import normalize, analyze

BINANCE='https://api.binance.com'; KRAKEN='https://api.kraken.com'
def get_json(url):
    with urlopen(Request(url,headers={'User-Agent':'DAIINAS-Control-Room/2.0'}),timeout=8) as r:return json.load(r)

class SignalStore:
 def __init__(self,path):
  self.db=sqlite3.connect(path);self.db.execute('CREATE TABLE IF NOT EXISTS intelligence_signals (id TEXT PRIMARY KEY,available_ms INTEGER NOT NULL,payload TEXT NOT NULL)')
 def append(self,payload):
  key=payload['evidence_sha256'];self.db.execute('INSERT OR IGNORE INTO intelligence_signals VALUES (?,?,?)',(key,payload['available_ms'],json.dumps(payload,sort_keys=True)));self.db.commit()
 def recent(self):return [json.loads(x[0]) for x in self.db.execute('SELECT payload FROM intelligence_signals ORDER BY available_ms DESC LIMIT 50')]

class PublicClient:
 def __init__(self,fetch=get_json):self.fetch=fetch
 def snapshot(self,symbol='BTCUSDT'):
  if not symbol.isalnum() or len(symbol)>20:raise ValueError('INVALID_SYMBOL')
  now=int(time.time()*1000); book=self.fetch(BINANCE+'/api/v3/ticker/bookTicker?symbol='+symbol);trades=self.fetch(BINANCE+'/api/v3/trades?symbol='+symbol+'&limit=100');
  buy=sum(float(x['qty']) for x in trades if not x['isBuyerMaker']);sell=sum(float(x['qty']) for x in trades if x['isBuyerMaker'])
  b=normalize('BINANCE',{'symbol':symbol,'E':now,'b':book['bidPrice'],'a':book['askPrice'],'B':book['bidQty'],'A':book['askQty'],'buyVolume':buy,'sellVolume':sell},received_ms=now)
  # Kraken uses XBT/USD for BTC; comparison remains explicitly cross-venue and USD-denominated.
  pair='XBTUSD' if symbol=='BTCUSDT' else 'ETHUSD' if symbol=='ETHUSDT' else None
  observations=[b]; errors=[]
  if pair:
   try:
    raw=self.fetch(KRAKEN+'/0/public/Ticker?pair='+pair)['result']; value=next(iter(raw.values()));
    observations.append(normalize('KRAKEN',{'symbol':pair,'event_ms':now,'bid':value['b'][0],'ask':value['a'][0],'bid_size':value['b'][2],'ask_size':value['a'][2]},received_ms=now))
   except Exception as e: errors.append('KRAKEN_UNAVAILABLE:'+type(e).__name__)
  result=analyze(observations) if len(observations)==2 else {'mode':'INTELLIGENCE','orders_enabled':False,'manual_plan_only':True,'bias':'NEUTRAL','confidence':'LOW','data_quality':'INCOMPLETE_SECOND_VENUE','evidence':[o.__dict__ for o in observations],'available_ms':now,'errors':errors}
  candles=self.fetch(BINANCE+'/api/v3/klines?symbol='+symbol+'&interval=1m&limit=80')
  result.update(symbol=symbol,candles=[{'t':x[0],'o':x[1],'h':x[2],'l':x[3],'c':x[4],'v':x[5]} for x in candles],order_flow={'aggressive_buy_volume':buy,'aggressive_sell_volume':sell,'cvd_proxy':buy-sell},depth={'bid':book['bidPrice'],'ask':book['askPrice'],'bid_size':book['bidQty'],'ask_size':book['askQty']},source_status='PUBLIC_NO_AUTH')
  return result

PAGE='''<!doctype html><meta charset="utf-8"><title>DAIINAS Control Room</title><style>body{margin:0;background:#09111d;color:#d8e5f3;font:14px system-ui}header,main{max-width:1440px;margin:auto;padding:16px}.grid{display:grid;grid-template-columns:2fr 1fr;gap:12px}.card{background:#101d2d;border:1px solid #28405c;border-radius:8px;padding:12px}canvas{width:100%;height:360px;background:#07101a}button,input{padding:8px;background:#172b40;color:#fff;border:1px solid #476984}pre{white-space:pre-wrap}.good{color:#55e6a5}.warn{color:#ffcf66}</style><header><b>DAIINAS Control Room</b> · Public data · Manual decisions only · <span id="status">loading</span> <input id="symbol" value="BTCUSDT"><button onclick="load()">Refresh</button></header><main class="grid"><section class="card"><canvas id="chart" width="900" height="360"></canvas><p id="summary"></p></section><aside><div class="card"><b>Scenario</b><pre id="scenario"></pre></div><div class="card"><b>Order flow & liquidity</b><pre id="flow"></pre></div><div class="card"><b>Evidence / alerts</b><pre id="evidence"></pre></div></aside></main><script>function chart(c){let x=document.querySelector('#chart'),q=x.getContext('2d'),a=c.map(z=>+z.c),lo=Math.min(...c.map(z=>+z.l)),hi=Math.max(...c.map(z=>+z.h)),w=x.width/c.length;q.clearRect(0,0,x.width,x.height);for(let[i,z]of c.entries()){let Y=v=>x.height-(v-lo)/(hi-lo)*x.height,up=+z.c>=+z.o;q.strokeStyle=up?'#42d392':'#ec6270';q.beginPath();q.moveTo(i*w+w/2,Y(+z.h));q.lineTo(i*w+w/2,Y(+z.l));q.stroke();q.fillStyle=q.strokeStyle;q.fillRect(i*w+w*.2,Y(Math.max(+z.o,+z.c)),w*.6,Math.max(1,Math.abs(Y(+z.o)-Y(+z.c))))}}async function load(){let s=document.querySelector('#symbol').value;try{let r=await fetch('/api/snapshot?symbol='+s),d=await r.json();if(!r.ok)throw Error(d.error);chart(d.candles);status.textContent=d.source_status;summary.textContent='Bias: '+d.bias+' · '+d.data_quality+' · '+new Date(d.available_ms).toLocaleTimeString();scenario.textContent=JSON.stringify({bias:d.bias,confidence:d.confidence,invalidation:d.invalidation_level,target:d.target_level,manual_only:d.manual_plan_only},null,2);flow.textContent=JSON.stringify({flow:d.order_flow,depth:d.depth},null,2);evidence.textContent=JSON.stringify(d.evidence,null,2)}catch(e){status.textContent='PUBLIC DATA UNAVAILABLE: '+e.message}}load();setInterval(load,15000)</script>'''

def serve(host='127.0.0.1',port=8765,db='control-room.sqlite3'):
 client,store=PublicClient(),SignalStore(Path(db))
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*a):pass
  def send(self,code,payload,kind='application/json'):
   raw=payload.encode() if isinstance(payload,str) else json.dumps(payload).encode();self.send_response(code);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
  def do_GET(self):
   path=urlparse(self.path)
   if path.path=='/':return self.send(200,PAGE,'text/html; charset=utf-8')
   if path.path=='/api/snapshot':
    try:r=client.snapshot(parse_qs(path.query).get('symbol',['BTCUSDT'])[0]);store.append(r);return self.send(200,r)
    except Exception as e:return self.send(503,{'error':'PUBLIC_DATA_UNAVAILABLE','type':type(e).__name__})
   if path.path=='/api/history':return self.send(200,store.recent())
   return self.send(404,{'error':'NOT_FOUND'})
 print('DAIINAS Control Room: http://%s:%s (public/manual only)'%(host,port));ThreadingHTTPServer((host,port),Handler).serve_forever()
