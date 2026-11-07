import json
import tempfile
import threading
import unittest
from queue import Queue
from urllib.request import urlopen

from daiinas.control_room import PublicClient, build_server


class Clock:
    def __init__(self): self.value = 1_000_000
    def __call__(self):
        self.value += 10
        return self.value


def fixture_fetch(url):
    if 'bookTicker' in url:
        return {'bidPrice': '100', 'askPrice': '101', 'bidQty': '5', 'askQty': '2'}
    if '/trades' in url:
        return [{'id': 1, 'time': 999_990, 'price': '100', 'qty': '2', 'isBuyerMaker': False},
                {'id': 2, 'time': 1_000_000, 'price': '101', 'qty': '1', 'isBuyerMaker': True}]
    if 'kraken' in url:
        return {'result': {'XBTUSDT': {'b': ['100.1', '1', '4'], 'a': ['101.1', '1', '1']}}}
    return [[1, '99', '102', '98', '101', '5']] * 80


class ControlRoomTests(unittest.TestCase):
    def test_snapshot_uses_existing_core_and_explicit_provenance(self):
        result = PublicClient(fixture_fetch, Clock()).snapshot()
        self.assertFalse(result['orders_enabled'])
        self.assertEqual(result['core_analysis']['engine'], 'daiinas.market_intelligence.update')
        self.assertEqual(result['order_flow']['status'], 'OBSERVED_RECENT_WINDOW_NOT_CUMULATIVE_CVD')
        self.assertEqual(result['evidence'][0]['event_ms'], None)
        self.assertEqual(result['evidence'][1]['symbol'], 'XBTUSDT')
        self.assertEqual(result['data_quality'], 'SOURCE_TIMESTAMP_UNAVAILABLE')

    def test_threaded_loopback_snapshot_history_and_concurrent_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            server = build_server(db=directory + '/signals.sqlite', client=PublicClient(fixture_fetch, Clock()))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = 'http://127.0.0.1:%s' % server.server_port
            try:
                responses = Queue()
                def snapshot():
                    with urlopen(base + '/api/snapshot?symbol=BTCUSDT', timeout=3) as response:
                        responses.put((response.status, json.load(response)))
                workers = [threading.Thread(target=snapshot) for _ in range(6)]
                for worker in workers: worker.start()
                for worker in workers: worker.join()
                received = [responses.get_nowait() for _ in workers]
                self.assertTrue(all(status == 200 and body['source_status'] == 'PUBLIC_NO_AUTH'
                                    for status, body in received))
                with urlopen(base + '/api/history', timeout=3) as response:
                    history = json.load(response)
                    self.assertEqual(response.status, 200)
                self.assertGreaterEqual(len(history), 1)
                self.assertFalse(history[0]['orders_enabled'])
                with self.assertRaises(Exception):
                    urlopen(base + '/api/snapshot?symbol=NOT_A_PAIR', timeout=3)
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=3)
