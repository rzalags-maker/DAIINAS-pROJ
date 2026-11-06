import unittest
from daiinas.intelligence import normalize,analyze
class IntelligenceTests(unittest.TestCase):
 def test_two_public_venues_emit_manual_hypothesis_with_provenance(self):
  b=normalize('BINANCE',{'symbol':'BTCUSDT','E':1000,'b':'100','a':'101','B':'5','A':'2','buyVolume':'8','sellVolume':'1'},received_ms=1001)
  k=normalize('KRAKEN',{'symbol':'BTC/USD','event_ms':1000,'bid':'100.1','ask':'101.1','bid_size':'4','ask_size':'1','buy_volume':'7','sell_volume':'1'},received_ms=1002)
  r=analyze([b,k]);self.assertEqual(r['mode'],'INTELLIGENCE');self.assertFalse(r['orders_enabled']);self.assertEqual(r['bias'],'LONG');self.assertTrue(r['manual_plan_only']);self.assertEqual(len(r['evidence']),2)
 def test_stale_or_single_venue_fails_closed(self):
  with self.assertRaises(ValueError): normalize('BINANCE',{'symbol':'BTCUSDT','E':1,'b':'1','a':'2','B':'1','A':'1'},received_ms=20000)
  x=normalize('KRAKEN',{'symbol':'BTC/USD','event_ms':1,'bid':'1','ask':'2','bid_size':'1','ask_size':'1'},received_ms=2)
  with self.assertRaises(ValueError): analyze([x])
