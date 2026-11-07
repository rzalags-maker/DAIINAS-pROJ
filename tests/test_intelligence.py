import unittest

from daiinas.intelligence import analyze, normalize


class IntelligenceTests(unittest.TestCase):
    def test_missing_provider_timestamps_are_explicit_and_fail_closed(self):
        b = normalize('BINANCE', {'symbol': 'BTCUSDT', 'canonical_symbol': 'BTCUSDT',
                      'b': '100', 'a': '101', 'B': '5', 'A': '2'}, received_ms=1001, request_latency_ms=8)
        k = normalize('KRAKEN', {'symbol': 'XBTUSDT', 'canonical_symbol': 'BTCUSDT',
                      'bid': '100.1', 'ask': '101.1', 'bid_size': '4', 'ask_size': '1'}, received_ms=1002)
        result = analyze([b, k])
        self.assertEqual(result['data_quality'], 'SOURCE_TIMESTAMP_UNAVAILABLE')
        self.assertEqual(result['bias'], 'NEUTRAL')
        self.assertIsNone(result['invalidation_level'])
        self.assertEqual(result['evidence'][0]['event_timestamp_status'], 'SOURCE_TIMESTAMP_UNAVAILABLE')

    def test_cross_quote_or_stale_evidence_never_becomes_complete(self):
        b = normalize('BINANCE', {'symbol': 'BTCUSDT', 'canonical_symbol': 'BTCUSDT', 'E': 1000,
                      'b': '100', 'a': '101', 'B': '5', 'A': '2'}, received_ms=1001)
        k = normalize('KRAKEN', {'symbol': 'XBTUSD', 'canonical_symbol': 'BTCUSD', 'event_ms': 1000,
                      'bid': '100.1', 'ask': '101.1', 'bid_size': '4', 'ask_size': '1'}, received_ms=1002)
        self.assertEqual(analyze([b, k])['data_quality'], 'CROSS_VENUE_REFERENCE_MISMATCH')
        with self.assertRaises(ValueError):
            normalize('BINANCE', {'symbol': 'BTCUSDT', 'E': 1, 'b': '1', 'a': '2', 'B': '1', 'A': '1'}, received_ms=20000)
