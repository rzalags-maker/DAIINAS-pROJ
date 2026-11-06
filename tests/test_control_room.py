import tempfile,unittest
from daiinas.control_room import PublicClient,SignalStore
class ControlRoomTests(unittest.TestCase):
 def test_public_snapshot_persists_manual_signal(self):
  def f(u):
   if 'bookTicker' in u:return {'bidPrice':'100','askPrice':'101','bidQty':'5','askQty':'2'}
   if '/trades' in u:return [{'qty':'2','isBuyerMaker':False},{'qty':'1','isBuyerMaker':True}]
   if 'Kraken' in u or 'kraken' in u:return {'result':{'XXBTZUSD':{'b':['100.1','1','4'],'a':['101.1','1','1']}}}
   return [[1,'99','102','98','101','5']]*80
  r=PublicClient(f).snapshot();self.assertFalse(r['orders_enabled']);self.assertTrue(r['manual_plan_only']);self.assertEqual(len(r['candles']),80)
  with tempfile.TemporaryDirectory() as d:
   s=SignalStore(d+'/x.sqlite');s.append(r);self.assertEqual(len(s.recent()),1)
