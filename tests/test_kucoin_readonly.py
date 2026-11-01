import base64,hashlib,hmac,json,unittest
from daiinas.kucoin_readonly import Credentials,ReadOnly,APIError,headers,probe,classic_usdt,GENERAL,FUTURES,NoRedirect

class Wire:
    def __init__(self,mode='CLASSIC',denied=None,pages=1):
        self.mode=mode;self.denied=denied;self.pages=pages;self.calls=[]
    def __call__(self,url,h):
        self.calls.append((url,h))
        if self.denied and self.denied in url:return json.dumps({'code':'400100'})
        if '/account/mode' in url:data={'selfAccountMode':self.mode}
        elif '/account/balance' in url:data={'accountType':'FUTURES','accounts':[{'currencies':[{'currency':'USDT','balance':'115.25','equity':'118','available':'108.5'}]}]}
        elif '/positions' in url:data=[{'id':'p1'}]
        elif '/orders?' in url or '/stopOrders?' in url:
            from urllib.parse import urlsplit,parse_qs
            n=int(parse_qs(urlsplit(url).query)['currentPage'][0]);data={'totalPage':self.pages,'items':[{'id':'o'+str(n)}]}
        elif '/trade-fees?' in url:data={'symbol':'XBTUSDTM','makerFeeRate':'0.0002','takerFeeRate':'0.0006'}
        else:raise AssertionError(url)
        return json.dumps({'code':'200000','data':data})

class GeneralOnlyTests(unittest.TestCase):
    def setUp(self):
        self.w=Wire();self.c=Credentials('key','secret','pass','3')
        self.api=ReadOnly(self.c,transport=self.w,clock=lambda:1700000000000)
    def test_signatures(self):
        end='/api/v1/trade-fees?symbol=XBTUSDTM';h=headers(self.c,end,1700000000000)
        def digest(s):return base64.b64encode(hmac.new(b'secret',s.encode(),hashlib.sha256).digest()).decode()
        self.assertEqual(h['KC-API-SIGN'],digest('1700000000000GET'+end))
        self.assertEqual(h['KC-API-PASSPHRASE'],digest('pass'))
        self.assertEqual(h['KC-API-KEY-VERSION'],'3')
    def test_complete_probe_still_no_real_account_ledger(self):
        r=probe(self.api)
        self.assertEqual(r['status'],'READ_ONLY_CONNECTED_NOT_RECONCILED')
        self.assertEqual(r['futures_usdt']['equity'],'118')
        self.assertEqual(r['futures_fees']['maker'],'0.0002')
        self.assertEqual((r['positions_count'],r['open_orders_count'],r['stop_orders_count']),(1,1,1))
        self.assertFalse(r['account_reconciled']);self.assertFalse(r['orders_enabled'])
        self.assertEqual(len(self.w.calls),6)
    def test_uta(self):
        self.w.mode='UNIFIED'
        self.assertEqual(probe(self.api)['status'],'UNSUPPORTED_UTA')
        self.assertEqual(len(self.w.calls),1)
    def test_denied_balance_not_faked(self):
        self.w.denied='/account/balance';r=probe(self.api)
        self.assertEqual(r['status'],'PARTIAL_READ_ONLY')
        self.assertNotIn('futures_usdt',r)
    def test_mode_failure_is_terminal(self):
        self.w.denied='/account/mode'
        self.assertEqual(probe(self.api)['status'],'NOT_CONNECTED')
        self.assertEqual(len(self.w.calls),1)
    def test_forbidden_write_routes_and_scope(self):
        for route,kw in [('add-order',{}),('mode',{'action':'withdraw'}),
                         ('orders',{'status':'done'}),('fees',{'symbol':'../bad'}),
                         ('balance',{'accountType':'SPOT','currency':'USDT'})]:
            with self.subTest(route=route),self.assertRaises(APIError):self.api.get(route,**kw)
        self.assertFalse(self.w.calls)
    def test_pagination(self):
        self.w.pages=3
        self.assertEqual(len(self.api.pages('orders',status='active')),3)
        self.w.pages=11
        with self.assertRaisesRegex(APIError,'Incomplete'):self.api.pages('orders',status='active')
    def test_balance_and_no_secrets(self):
        with self.assertRaises(APIError):classic_usdt({'accountType':'SPOT','accounts':[]})
        with self.assertRaises(APIError):Credentials.from_env({})
        self.assertIsNone(NoRedirect().redirect_request(None,None,302,'Found',{},'https://evil.example'))
