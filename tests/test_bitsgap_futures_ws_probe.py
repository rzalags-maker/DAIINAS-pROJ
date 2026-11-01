"""Offline acceptance for bounded, authenticated WS read-only topic inspection."""
import asyncio
import json
import unittest

from daiinas.bitsgap_futures_observe import BitsgapFuturesObserver
from daiinas.bitsgap_futures_ws_probe import probe_bounded
from test_bitsgap_futures_observe import FakeWire, new_pem
from test_bitsgap_futures_stream import FakeWS


class ReadOnlyWSProbeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _, pem = new_pem()
        self.w = FakeWire()
        self.api = BitsgapFuturesObserver(pem, transport=self.w,
                                          clock_ms=lambda: 1783000000000)
        self.api.discover()

    async def test_real_rest_null_scope_does_not_prevent_ws_auth_and_topic_inspection(self):
        self.w.orders = None
        self.w.positions = None
        fake = FakeWS([{"type":"auth_ok","sid":"PRIVATE_SESSION_ID"},
                       {"ok":True,"topic":"balance","params":{"em":72},
                        "value":self.w.balance},
                       {"ok":True,"topic":"orders","params":{"em":72},
                        "value":None},
                       {"ok":True,"topic":"positions","params":{"em":72},
                        "mes":"subscribed"}])
        r = await probe_bounded(observer=self.api, connect=lambda _:fake, seconds=2)
        self.assertEqual(r["websocket_auth"], "PASS")
        self.assertEqual(r["rest_balance"], "VALIDATED")
        self.assertEqual(r["rest_orders"], "UNVERIFIED")
        self.assertEqual(r["rest_positions"], "UNVERIFIED")
        self.assertEqual(r["websocket_topics"]["balance"], "VALIDATED_UPDATE")
        self.assertEqual(r["websocket_topics"]["orders"], "PROVIDER_NO_DATA")
        self.assertEqual(r["websocket_topics"]["positions"], "SUBSCRIBED")
        self.assertEqual(r["websocket_topics"]["positions_settings"],
                         "NO_EVENT_WITHIN_WINDOW")
        self.assertNotIn("61.07", json.dumps(r))
        self.assertNotIn("PRIVATE_SESSION_ID", json.dumps(r))
        self.assertFalse(r["absence_of_data_is_zero_exposure"])
        self.assertEqual(r["order_routing"], "DISABLED")
        self.assertEqual(len(fake.sent),2)

    async def test_invalid_auth_never_sends_subscription(self):
        fake = FakeWS([{"type":"auth_rejected","detail":"PRIVATE_SESSION_ID"}])
        r = await probe_bounded(observer=self.api, connect=lambda _:fake, seconds=2)
        self.assertEqual(r["websocket_auth"], "UNVERIFIED")
        self.assertEqual(r["diagnostic_outcome"], "WS_AUTH_UNVERIFIED")
        self.assertEqual(len(fake.sent),1)
        self.assertNotIn("PRIVATE_SESSION_ID", json.dumps(r))

    async def test_quiet_authenticated_feed_never_becomes_zero_orders(self):
        class QuietWS(FakeWS):
            async def recv(self):
                if self.frames:
                    return json.dumps(self.frames.pop(0))
                await asyncio.sleep(3)
        self.w.orders = None
        self.w.positions = None
        fake = QuietWS([{"type":"auth_ok","sid":"PRIVATE_SESSION_ID"}])
        r = await probe_bounded(observer=self.api,connect=lambda _:fake,seconds=1)
        self.assertEqual(r["websocket_auth"], "PASS")
        self.assertEqual(r["diagnostic_outcome"], "OBSERVATION_WINDOW_FINISHED")
        self.assertEqual(r["websocket_topics"]["orders"], "NO_EVENT_WITHIN_WINDOW")
        self.assertFalse(r["model_a_reconciled"])

    async def test_invalid_probe_window_does_not_contact_transport(self):
        with self.assertRaises(ValueError):
            await probe_bounded(observer=self.api,connect=lambda _:None,seconds=0)


if __name__=="__main__":
    unittest.main()
