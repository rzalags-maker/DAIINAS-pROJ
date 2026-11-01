"""KuCoin General-only API probe. GET-only; NO order routing or Model A funding."""
import argparse,base64,hashlib,hmac,json,os,re,time,urllib.error,urllib.parse,urllib.request
from dataclasses import dataclass
from decimal import Decimal,InvalidOperation

GENERAL='https://api.kucoin.com'
FUTURES='https://api-futures.kucoin.com'
ROUTES={'mode':(GENERAL,'/api/ua/v2/account/mode',()),
        'balance':(GENERAL,'/api/ua/v2/account/balance',('accountType','currency')),
        'positions':(FUTURES,'/api/v1/positions',('currency',)),
        'orders':(FUTURES,'/api/v1/orders',('status','currentPage','pageSize')),
        'stops':(FUTURES,'/api/v1/stopOrders',('currentPage','pageSize')),
        'fees':(FUTURES,'/api/v1/trade-fees',('symbol',))}

class APIError(RuntimeError):pass

@dataclass(frozen=True)
class Credentials:
    key:str
    secret:str
    passphrase:str
    version:str='2'
    @classmethod
    def from_env(cls,env=None):
        e=os.environ if env is None else env
        keys=('KUCOIN_API_KEY','KUCOIN_API_SECRET','KUCOIN_API_PASSPHRASE')
        if any(not e.get(k) for k in keys):raise APIError('NOT_CONNECTED: missing KuCoin environment secrets')
        v=e.get('KUCOIN_API_KEY_VERSION','2')
        if v not in ('2','3'):raise APIError('Unsupported API key version')
        return cls(*(e[k] for k in keys),version=v)

def headers(c,endpoint,ts):
    if not endpoint.startswith('/api/') or '#' in endpoint or '://' in endpoint:
        raise ValueError('Invalid signing endpoint')
    key=c.secret.encode()
    def sign(value):
        return base64.b64encode(hmac.new(key,value.encode(),hashlib.sha256).digest()).decode()
    return {'KC-API-KEY':c.key,'KC-API-TIMESTAMP':str(ts),
            'KC-API-SIGN':sign(str(ts)+'GET'+endpoint),
            'KC-API-PASSPHRASE':sign(c.passphrase),
            'KC-API-KEY-VERSION':c.version,'Content-Type':'application/json',
            'Accept':'application/json'}

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):return None

def https_get(url,h):
    req=urllib.request.Request(url,headers=h,method='GET')
    with urllib.request.build_opener(NoRedirect()).open(req,timeout=12) as r:
        b=r.read(2000001)
        if len(b)>2000000:raise APIError('Response too large')
        return b

class ReadOnly:
    def __init__(self,c,transport=https_get,clock=None):
        self.c=c;self.transport=transport;self.clock=clock or (lambda:int(time.time()*1000))
    def get(self,kind,**kw):
        if kind not in ROUTES:raise APIError('Non-allowlisted GET endpoint refused')
        host,path,allowed=ROUTES[kind]
        if set(kw)-set(allowed):raise APIError('Forbidden query parameter')
        if any(type(v) not in (str,int) or not re.fullmatch('[A-Za-z0-9_-]+',str(v)) for v in kw.values()):
            raise APIError('Invalid query parameter')
        if kind=='balance' and (kw.get('accountType'),kw.get('currency'))!=('FUTURES','USDT'):
            raise APIError('Only Classic Futures USDT scope allowed')
        if kind=='orders' and kw.get('status')!='active':raise APIError('Active orders only')
        if kind=='fees' and not re.fullmatch('[A-Z0-9]{3,25}',str(kw.get('symbol',''))):
            raise APIError('Invalid Futures symbol')
        endpoint=path+('?' + urllib.parse.urlencode(kw) if kw else '')
        try:
            payload=json.loads(self.transport(host+endpoint,headers(self.c,endpoint,self.clock())),
                               parse_float=Decimal)
        except urllib.error.HTTPError as e:
            raise APIError('HTTP_'+str(e.code)+' '+kind+' (permissions/IP restriction)') from None
        except urllib.error.URLError:raise APIError('NETWORK_UNAVAILABLE '+kind) from None
        except (ValueError,TypeError,UnicodeError):raise APIError('INVALID_RESPONSE '+kind) from None
        if not isinstance(payload,dict) or str(payload.get('code'))!='200000' or 'data' not in payload:
            code=str(payload.get('code','UNKNOWN')) if isinstance(payload,dict) else 'UNKNOWN'
            if not re.fullmatch('[A-Za-z0-9_-]{1,24}',code):code='UNKNOWN'
            raise APIError('API_'+code+' '+kind+' (General permission required)')
        return payload['data']
    def pages(self,kind,**kw):
        if kind not in ('orders','stops'):raise APIError('Not a paged order route')
        found=[];seen=set()
        for n in range(1,11):
            d=self.get(kind,**kw,currentPage=n,pageSize=50)
            if not isinstance(d,dict) or not isinstance(d.get('items'),list):
                raise APIError('Missing complete '+kind+' scope')
            for item in d['items']:
                if not isinstance(item,dict) or not item.get('id') or str(item['id']) in seen:
                    raise APIError('Invalid/duplicate order identity')
                seen.add(str(item['id']));found.append(item)
            try:total=int(d['totalPage'])
            except (KeyError,ValueError,TypeError):raise APIError('Missing pagination total') from None
            if total<1:raise APIError('Invalid page count')
            if n>=total:return found
        raise APIError('Incomplete order scope; page cap reached')

def decimal_nonnegative(x):
    try:
        d=Decimal(str(x))
        if not d.is_finite() or d<0:raise ValueError()
        return str(d)
    except (InvalidOperation,TypeError,ValueError):raise APIError('Unverified numeric field') from None

def classic_usdt(data):
    if not isinstance(data,dict) or data.get('accountType')!='FUTURES':raise APIError('Account mode/scope mismatch')
    rows=[]
    for a in data.get('accounts',[]):
        if not isinstance(a,dict):raise APIError('Invalid account group')
        for c in a.get('currencies',[]):
            if c.get('currency')=='USDT':rows.append(c)
    if len(rows)!=1:raise APIError('Futures USDT scope missing or ambiguous')
    try:return {x:decimal_nonnegative(rows[0][x]) for x in ('balance','equity','available')}
    except KeyError:raise APIError('Missing Futures balance fields') from None

def probe(api,fee_symbol='XBTUSDTM'):
    out={'status':'PROBING','mode':None,'connector':'KUCOIN_GENERAL_ONLY',
         'account_reconciled':False,'model_a_initialized':False,'orders_enabled':False,
         'checks':{},'errors':{}}
    try:
        d=api.get('mode');mode=d.get('selfAccountMode') if isinstance(d,dict) else None
        if mode not in ('CLASSIC','UNIFIED'):raise APIError('Unknown account mode')
        out['mode']=mode;out['checks']['mode']='OK'
    except APIError as e:
        out['status']='NOT_CONNECTED';out['errors']['mode']=str(e);return out
    if mode!='CLASSIC':out['status']='UNSUPPORTED_UTA';return out
    try:
        out['futures_usdt']=classic_usdt(api.get('balance',accountType='FUTURES',currency='USDT'))
        out['checks']['balance']='CURRENCY_ASSETS_ONLY'
    except APIError as e:out['errors']['balance']=str(e)
    try:
        p=api.get('positions',currency='USDT')
        if not isinstance(p,list) or any(not isinstance(x,dict) for x in p):
            raise APIError('Invalid positions scope')
        out['positions_count']=len(p);out['checks']['positions']='OK'
    except APIError as e:out['errors']['positions']=str(e)
    for route,field in (('orders','open_orders_count'),('stops','stop_orders_count')):
        try:
            out[field]=len(api.pages(route,**({'status':'active'} if route=='orders' else {})))
            out['checks'][route]='OK'
        except APIError as e:out['errors'][route]=str(e)
    try:
        d=api.get('fees',symbol=fee_symbol)
        if not isinstance(d,dict) or d.get('symbol')!=fee_symbol:raise APIError('Wrong fee symbol')
        out['futures_fees']={'symbol':fee_symbol,'maker':decimal_nonnegative(d['makerFeeRate']),
                             'taker':decimal_nonnegative(d['takerFeeRate'])}
        out['checks']['fees']='OK'
    except (APIError,KeyError,TypeError) as e:out['errors']['fees']=str(e)
    out['status']='PARTIAL_READ_ONLY' if out['errors'] else 'READ_ONLY_CONNECTED_NOT_RECONCILED'
    return out

def main(argv=None):
    parser=argparse.ArgumentParser(description='KuCoin General-only signed GET probe; no trades')
    parser.add_argument('--fee-symbol',default='XBTUSDTM')
    args=parser.parse_args(argv)
    try:result=probe(ReadOnly(Credentials.from_env()),args.fee_symbol)
    except APIError as e:result={'status':'NOT_CONNECTED','error':str(e),'orders_enabled':False}
    print(json.dumps(result,indent=2,sort_keys=True))
    return 0 if result['status']=='READ_ONLY_CONNECTED_NOT_RECONCILED' else 2

if __name__=='__main__':raise SystemExit(main())
