"""Fail-closed v4.2 exchange state reducer tests; OFFLINE only, no API keys."""
import unittest

from daiinas.exchange_control_state import ExchangeMirror


class ExchangeMirrorTests(unittest.TestCase):
    def make(self, *, orders=None, mode='UTA'):
        m = ExchangeMirror('acct-1', mode)
        m.register_client_oid('daiinas-00001')
        m.start_sync()
        m.ingest_snapshot(scope='balances', account_id='acct-1', timestamp_ms=2000,
                          records=[{'id': 'USDT', 'free': '60.00', 'locked': '0'}])
        m.ingest_snapshot(scope='orders', account_id='acct-1', timestamp_ms=2000,
                          records=orders or [])
        m.ingest_snapshot(scope='positions', account_id='acct-1', timestamp_ms=2000,
                          records=[])
        m.ingest_snapshot(scope='fills', account_id='acct-1', timestamp_ms=2000,
                          records=[])
        return m

    def test_account_modes_explicit(self):
        for mode in ('UTA', 'CLASSIC_SPOT', 'CLASSIC_FUTURES'):
            m = self.make(mode=mode)
            self.assertEqual(m.complete_sync()['health'], 'RECONCILED_READONLY')
        with self.assertRaises(ValueError):
            ExchangeMirror('acct-1', 'MAGIC')

    def test_incomplete_snapshots_never_ready(self):
        m = ExchangeMirror('acct-1', 'UTA')
        m.start_sync()
        with self.assertRaises(RuntimeError):
            m.complete_sync()
        self.assertEqual(m.health, 'SYNCING')
        self.assertTrue(m.status()['block_new_entries'])

    def test_owned_order_snapshot_is_safe_but_cannot_trade(self):
        owned = {'id': 'O-A', 'clientOid': 'daiinas-00001', 'symbol': 'BTC-USDT',
                 'status': 'OPEN'}
        m = self.make(orders=[owned])
        r = m.complete_sync()
        self.assertEqual((r['health'], r['external_or_unknown_orders']),
                         ('RECONCILED_READONLY', 0))
        self.assertFalse(r['execution_enabled'])
        self.assertEqual(m.orders['O-A']['ownership'], 'DAIINAS')

    def test_manual_and_bitsgap_not_attributable(self):
        ext = {'id': 'O-B', 'clientOid': 'unknown', 'symbol': 'ETH-USDT', 'status': 'OPEN'}
        m = self.make(orders=[ext])
        r = m.complete_sync()
        self.assertEqual(r['health'], 'EXTERNAL_INTERVENTION')
        self.assertEqual(m.orders['O-B']['ownership'], 'UNKNOWN_EXTERNAL')
        self.assertTrue(r['operator_pause'])

    def test_private_ws_event_before_snapshot_finish(self):
        m = ExchangeMirror('acct-1', 'UTA')
        m.start_sync()
        event = {'id': 'ws:1', 'account_id': 'acct-1', 'timestamp_ms': 2100,
                 'scope': 'orders', 'action': 'UPSERT',
                 'record': {'id': 'O-X', 'clientOid': 'outside-client', 'status': 'OPEN'}}
        self.assertTrue(m.ingest_event(event))
        m.ingest_snapshot(scope='balances', account_id='acct-1', timestamp_ms=2000,
                          records=[{'id': 'USDT', 'free': '60', 'locked': '0'}])
        m.ingest_snapshot(scope='orders', account_id='acct-1', timestamp_ms=2000,
                          records=[])
        m.ingest_snapshot(scope='positions', account_id='acct-1', timestamp_ms=2000,
                          records=[])
        m.ingest_snapshot(scope='fills', account_id='acct-1', timestamp_ms=2000,
                          records=[])
        m.complete_sync()
        self.assertIn('O-X', m.orders)
        self.assertEqual(m.status()['health'], 'EXTERNAL_INTERVENTION')
        self.assertFalse(m.ingest_event(event))

    def test_partial_fill_from_external_order_fails_closed(self):
        m = self.make()
        m.complete_sync()
        m.ingest_event({'id': 'evt1', 'account_id': 'acct-1', 'scope': 'orders',
                        'timestamp_ms': 2100, 'action': 'UPSERT',
                        'record': {'id': 'order-2', 'clientOid': 'other',
                                   'status': 'PARTIALLY_FILLED'}})
        self.assertEqual(m.orders['order-2']['status'], 'PARTIALLY_FILLED')
        self.assertEqual(m.health, 'EXTERNAL_INTERVENTION')
        self.assertTrue(m.status()['block_new_entries'])

    def test_manual_position_close_does_not_reopen(self):
        m = self.make()
        m.complete_sync()
        m.ingest_event({'id': 'evt1', 'account_id': 'acct-1', 'scope': 'positions',
                        'timestamp_ms': 2100, 'action': 'UPSERT',
                        'record': {'id': 'BTC-USDT:LONG', 'size': '0.5'}})
        m.ingest_event({'id': 'evt2', 'account_id': 'acct-1', 'scope': 'positions',
                        'timestamp_ms': 2200, 'action': 'DELETE',
                        'record': {'id': 'BTC-USDT:LONG', 'size': '0'}})
        self.assertEqual(m.positions, {})
        self.assertEqual(m.status()['health'], 'EXTERNAL_INTERVENTION')

    def test_balance_change_forces_pause(self):
        m = self.make()
        m.complete_sync()
        m.ingest_event({'id': 'evt3', 'account_id': 'acct-1', 'scope': 'balances',
                        'timestamp_ms': 2100, 'action': 'UPSERT',
                        'record': {'id': 'USDT', 'free': '24', 'locked': '36'}})
        self.assertEqual(m.balances['USDT']['free'], '24')
        self.assertTrue(m.operator_pause)

    def test_mismatched_account_degrades_and_blocks(self):
        m = self.make()
        m.complete_sync()
        with self.assertRaises(ValueError):
            m.ingest_event({'id': 'bad', 'account_id': 'other', 'scope': 'orders',
                            'timestamp_ms': 2100, 'action': 'DELETE',
                            'record': {'id': 'O-1'}})
        self.assertEqual(m.health, 'DEGRADED')
        self.assertTrue(m.status()['block_new_entries'])

    def test_stale_event_cannot_override_snapshot(self):
        m = self.make(orders=[{'id': 'A', 'clientOid': 'daiinas-00001',
                               'status': 'FILLED'}])
        m.complete_sync()
        m.ingest_event({'id': 'stale1', 'account_id': 'acct-1', 'scope': 'orders',
                        'timestamp_ms': 1000, 'action': 'UPSERT',
                        'record': {'id': 'A', 'clientOid': 'daiinas-00001',
                                   'status': 'OPEN'}})
        self.assertEqual(m.orders['A']['status'], 'FILLED')
        self.assertEqual(m.health, 'RECONCILED_READONLY')

    def test_disabled_order_cancel_transfer(self):
        m = self.make()
        m.complete_sync()
        self.assertFalse(m.preview_order(symbol='BTC-USDT')['allowed'])
        for op in (m.place_order, m.cancel_order, m.transfer):
            with self.assertRaises(PermissionError):
                op()

    def test_duplicate_event_and_duplicate_snapshot(self):
        m = self.make()
        m.complete_sync()
        event = {'id': 'once', 'account_id': 'acct-1', 'scope': 'fills',
                 'timestamp_ms': 2400, 'action': 'UPSERT',
                 'record': {'id': 'fill-1', 'amount': '1'}}
        self.assertTrue(m.ingest_event(event))
        self.assertFalse(m.ingest_event(event))
        self.assertEqual(len(m.fills), 1)
        m.start_sync()
        m.ingest_snapshot(scope='fills', account_id='acct-1', timestamp_ms=2600,
                          records=[])
        with self.assertRaises(ValueError):
            m.ingest_snapshot(scope='fills', account_id='acct-1', timestamp_ms=2600,
                              records=[])


    def test_old_ws_event_does_not_resurrect_snapshot_absent_order(self):
        m = ExchangeMirror('acct-1', 'UTA')
        m.start_sync()
        m.ingest_event({'id': 'old-order', 'account_id': 'acct-1',
                        'scope': 'orders', 'timestamp_ms': 1000,
                        'action': 'UPSERT',
                        'record': {'id': 'already-cancelled', 'status': 'OPEN'}})
        for scope, records in (
            ('balances', [{'id': 'USDT', 'free': '60', 'locked': '0'}]),
            ('orders', []), ('positions', []), ('fills', [])):
            m.ingest_snapshot(scope=scope, account_id='acct-1',
                              timestamp_ms=2000, records=records)
        m.complete_sync()
        self.assertNotIn('already-cancelled', m.orders)
        self.assertEqual(m.health, 'RECONCILED_READONLY')


if __name__ == '__main__':
    unittest.main()
