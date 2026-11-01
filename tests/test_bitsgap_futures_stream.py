import asyncio
import base64
import json
import unittest
from unittest.mock import patch
from daiinas.bitsgap_readonly import BitsgapError
from daiinas.bitsgap_futures_stream import BitsgapFuturesStream, read_only_ws_topics
from daiinas.bitsgap_futures_observe import BitsgapFuturesObserver
from test_bitsgap_futures_observe import FakeWire, new_pem


class FakeWS:
    def __init__(self, frames):
        self.frames = list(frames)
        self.sent = []
    async def __aenter__(self):return self
    async def __aexit__(self, exc_type, exc, tb):return False
    async def send(self, msg):self.sent.append(json.loads(msg))
    async def recv(self):
        if self.frames:
            return json.dumps(self.frames.pop(0))
        raise ConnectionError("synthetic disconnect secret-not-for-logs")


class StreamTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.key, self.pem = new_pem()
        self.w = FakeWire()
        self.api = BitsgapFuturesObserver(self.pem, transport=self.w, clock_ms=lambda:1783000000000)
        self.api.discover()
        self.stream = BitsgapFuturesStream(self.api)

    async def test_exact_ed25519_ws_auth_signing(self):
        a=self.stream.auth_frame(ts=1783000000,nonce="nonce123")
        canonical=f'btg-ws-auth\nv1\n{a["pubkey"]}\n{a["ts"]}\n{a["nonce"]}'.encode()
        self.key.public_key().verify(base64.b64decode(a["signature"]),canonical)
        self.assertNotIn(self.pem,json.dumps(a))

    async def test_connect_observe_only_and_private_balance_not_emitted(self):
        ws=FakeWS([{"type":"auth_ok","sid":"session-id"},
                   {"ok":True,"topic":"balance","params":{"em":72},"mes":"subscribed"},
                   {"ok":True,"topic":"balance","params":{"em":72},"value":self.w.balance},
                   {"ok":True,"topic":"orders","params":{"em":72},"value":self.w.orders}])
        events=[]
        await self.stream.watch_once(lambda url:ws,on_event=lambda event:self._record(events,event),max_messages=3)
        self.assertFalse(self.stream.connected)
        self.assertEqual(len(ws.sent),3)
        self.assertEqual(ws.sent[0]["type"],"auth")
        self.assertEqual([x["topic"] for x in ws.sent[1]],list(read_only_ws_topics()))
        self.assertTrue(all(x["params"]=={"em":72} and x["subs"] is True for x in ws.sent[1]))
        self.assertEqual([x["topic"] for x in ws.sent[2]], list(read_only_ws_topics()))
        self.assertTrue(all(x["params"] == {"em":72} and "subs" not in x for x in ws.sent[2]))
        self.assertEqual([x["event"] for x in events],["SUBSCRIBED","VALIDATED_UPDATE","VALIDATED_UPDATE"])
        self.assertNotIn("61.07",json.dumps(events))
        self.assertEqual(self.stream.last_rest_observation.total_usdt,"61.07")
        self.assertTrue(all(x["funding_authorized"] is False for x in events))

    async def _record(self, events, event):events.append(event)

    async def test_rest_null_exposure_does_not_block_ws_subscription(self):
        # Exact observed production anomaly: REST orders and positions JSON null.
        self.w.orders = None
        self.w.positions = None
        ws=FakeWS([{"type":"auth_ok","sid":"synthetic"},
                   {"ok":True,"topic":"orders","params":{"em":72},"value":None},
                   {"ok":True,"topic":"positions","params":{"em":72},"mes":"subscribed"},
                   {"ok":False,"topic":"positions_settings","params":{"em":72},"mes":"no data"}])
        events=[]
        await self.stream.watch_once(lambda url:ws,on_event=lambda e:self._record(events,e),max_messages=3)
        self.assertTrue(self.stream.authenticated)
        self.assertEqual([x["event"] for x in events],
                         ["PROVIDER_NO_DATA","SUBSCRIBED","SUBSCRIPTION_REJECTED"])
        self.assertTrue(all(not x["funding_authorized"] for x in events))
        self.assertEqual(self.stream.last_rest_observation.orders_reason, "PROVIDER_NULL_RESPONSE")
        self.assertEqual(self.stream.last_rest_observation.positions_reason, "PROVIDER_NULL_RESPONSE")
        self.assertEqual(len(ws.sent),3)
        self.assertTrue(all(x["subs"] is True for x in ws.sent[1]))
        self.assertTrue(all("subs" not in x for x in ws.sent[2]))
        self.assertNotIn("61.07",json.dumps(events))

    async def test_foreign_and_unknown_topic_rejected_before_event_classification(self):
        for msg in (
                {"ok":False,"topic":"orders","params":{"em":71},"mes":"no data"},
                {"ok":True,"topic":"order_place","params":{"em":72},"value":None}):
            with self.assertRaisesRegex(BitsgapError,"WS_FOREIGN_EXCHANGE_SCOPE|WS_UNVERIFIED_TOPIC_FRAME"):
                self.stream._ingest(msg)

    async def test_rejected_ws_envelope_diagnostic_never_prints_remote_values(self):
        from daiinas.bitsgap_futures_stream import _safe_envelope_shape
        details = _safe_envelope_shape({"ok":True, "topic":"orders",
                    "params":{"em":72,"account_id":"PRIVATE_ACCOUNT_ID"},
                    "value":{"USDT":"PRIVATE_BALANCE"},
                    "secret_key_PRIVATE":"PRIVATE_SESSION"})
        raw = json.dumps(details)
        self.assertEqual(details["topic_class"], "ACCOUNT")
        self.assertEqual(details["params_class"], "OBJECT")
        self.assertEqual(details["value_class"], "OBJECT")
        self.assertEqual(details["other_field_count"], 1)
        for forbidden in ("PRIVATE_ACCOUNT_ID","PRIVATE_BALANCE","PRIVATE_SESSION",
                          "secret_key_PRIVATE","72", "USDT"):
            self.assertNotIn(forbidden, raw)

    async def test_real_unscoped_control_response_is_not_counted_as_topic_data(self):
        self.w.orders = None
        self.w.positions = None
        ws = FakeWS([{"type":"auth_ok","sid":"SENSITIVE"},
                     {"ok":True,"mes":"server-control-message-with-private-text"},
                     {"ok":True,"topic":"balance","params":{"em":72},
                      "value":self.w.balance}])
        events=[]
        await self.stream.watch_once(lambda _:ws, on_event=lambda e:self._record(events,e),
                                     max_messages=2)
        self.assertEqual([e["event"] for e in events],
                         ["UNSCOPED_OK_RESPONSE","VALIDATED_UPDATE"])
        self.assertEqual(self.stream.unscoped_control_responses, 1)
        self.assertFalse(events[0]["funding_authorized"])
        self.assertNotIn("server-control-message",json.dumps(events))
        self.assertNotIn("SENSITIVE",json.dumps(events))

    async def test_unscoped_negative_response_does_not_authorize_subscription(self):
        ws=FakeWS([{"type":"auth_ok","sid":"SENSITIVE"},
                   {"ok":False,"mes":"hidden remote denial"}])
        with self.assertRaisesRegex(BitsgapError,"WS_UNSCOPED_REJECTION"):
            await self.stream.watch_once(lambda _:ws,
                                         on_event=lambda e:self._record([],e),max_messages=1)
        self.assertEqual(self.stream.unscoped_control_responses,0)
        self.assertEqual(self.stream.last_frame_shape["topic_class"],"NONE")

    async def test_topic_value_with_optional_messaging_field_is_validated(self):
        event = self.stream._ingest({"ok": True, "topic": "balance",
                  "params":{"em":72}, "value":self.w.balance,
                  "mes":"SENSITIVE_PROVIDER_MESSAGE_DO_NOT_ECHO"})
        self.assertEqual(event["event"], "VALIDATED_UPDATE")
        self.assertEqual(event["topic"], "balance")
        self.assertNotIn("SENSITIVE_PROVIDER_MESSAGE", json.dumps(event))
        with self.assertRaisesRegex(BitsgapError, "WS_UNVERIFIED_TOPIC_FRAME"):
            self.stream._ingest({"ok": True, "topic": "balance",
                   "params":{"em":72}, "value":self.w.balance,
                   "mes": {"private":"SECRET"}})

    async def test_real_ws_topic_payload_with_nullable_message_metadata(self):
        event = self.stream._ingest({"ok": True, "topic": "balance",
                  "params":{"em":72}, "value":self.w.balance, "mes":None})
        self.assertEqual(event["event"],"VALIDATED_UPDATE")
        self.assertEqual(event["record_count"],1)
        self.assertFalse(event["funding_authorized"])
    async def test_foreign_exchange_event_is_denied(self):
        ws=FakeWS([{"type":"auth_ok","sid":"ok"},
                   {"ok":True,"topic":"balance","params":{"em":71},"value":self.w.balance}])
        with self.assertRaisesRegex(BitsgapError,"WS_FOREIGN_EXCHANGE_SCOPE"):
            await self.stream.watch_once(lambda url:ws,on_event=lambda e:self._record([],e),max_messages=1)
        self.assertFalse(self.stream.connected)

    async def test_mutating_topic_frame_does_not_invoke_or_pass(self):
        ws=FakeWS([{"type":"auth_ok","sid":"ok"},
                   {"ok":True,"topic":"order_place","params":{"em":72},"value":{"res":True}}])
        with self.assertRaisesRegex(BitsgapError,"WS_UNVERIFIED_TOPIC_FRAME"):
            await self.stream.watch_once(lambda url:ws,on_event=lambda e:self._record([],e),max_messages=1)
        self.assertEqual(len(ws.sent),3)

    async def test_failed_auth_blocks_subscription(self):
        ws=FakeWS([{"type":"auth_failed","message":"secret"}])
        with self.assertRaisesRegex(BitsgapError,"WS_AUTH_UNVERIFIED"):
            await self.stream.watch_once(lambda url:ws,on_event=lambda e:self._record([],e))
        self.assertEqual(len(ws.sent),1)

    async def test_bad_json_duplicate_and_non_json_constant(self):
        from daiinas.bitsgap_futures_stream import _parse_json
        for s in ('{"ok":true,"ok":false}', '{"x":NaN}', '{not-json}'):
            with self.assertRaisesRegex(BitsgapError,"WS_BAD_FRAME"):_parse_json(s)

    async def test_revoked_key_is_terminal_not_infinite_reconnect(self):
        class Revoked(Exception):
            def __init__(self):
                self.rcvd = type("CloseFrame", (), {"code": 4403})()
        class RevokedWS(FakeWS):
            async def recv(self):
                raise Revoked()
        sessions=[]
        stop=asyncio.Event()
        events=[]
        def connect(url):
            ws=RevokedWS([])
            sessions.append(ws)
            return ws
        async def handle(e):
            events.append(e)
        await asyncio.wait_for(self.stream.observe_forever(connect,on_event=handle,stop_event=stop),2)
        self.assertEqual(len(sessions),1)
        self.assertEqual(events[-1]["category"],"WS_TERMINAL_AUTH_FAILURE")

    async def test_restart_renews_rest_snapshot_and_disconnect_event(self):
        sessions=[]
        stop=asyncio.Event()
        events=[]
        def connect(url):
            ws=FakeWS([{"type":"auth_ok","sid":"new"},
                       {"ok":True,"topic":"orders","params":{"em":72},"value":self.w.orders}])
            sessions.append(ws)
            return ws
        async def handle(e):
            events.append(e)
            if len(sessions)>=2 and e.get("event")=="VALIDATED_UPDATE":stop.set()
        # Tests reconnect path with no real waiting by overriding asyncio.wait_for
        # would be intrusive; a 1s bound is acceptable for offline regression.
        await asyncio.wait_for(self.stream.observe_forever(connect,on_event=handle,stop_event=stop,delay_seconds=1),4)
        self.assertGreaterEqual(len(sessions),2)
        self.assertEqual(len([x for x in self.w.calls if x[0]=="balance"]),len(sessions))
        self.assertTrue(any(x["event"]=="DISCONNECTED" for x in events))
        self.assertEqual([x["type"] for ws in sessions for x in ws.sent if isinstance(x,dict)],["auth"]*len(sessions))


    async def test_explicit_snapshot_response_not_subscription_duplicate(self):
        observed = []
        self.stream.observation_sink = lambda **kw: observed.append(kw)
        ws = FakeWS([{"type":"auth_ok","sid":"synthetic"},
                     {"ok":True,"topic":"balance","params":{"em":72},"value":self.w.balance},
                     {"ok":True,"topic":"balance","params":{"em":72},"value":self.w.balance}])
        await self.stream.watch_once(lambda _:ws,
            on_event=lambda e:self._record([],e),max_messages=2)
        self.assertEqual([v["snapshot_response"] for v in observed], [True, False])
        self.assertEqual(self.stream.snapshot_responses,1)
        self.assertEqual(self.stream.subscription_updates,1)
        self.assertEqual(self.stream.diagnostic_status()["ws_snapshot_batches_sent"],1)
        self.assertNotIn("61.07",json.dumps(self.stream.diagnostic_status()))

    async def test_idle_socket_requests_periodic_one_off_snapshots(self):
        class IdleWS(FakeWS):
            def __init__(self):
                super().__init__([])
                self.queue = asyncio.Queue()
                self.queue.put_nowait(json.dumps({"type":"auth_ok","sid":"synthetic"}))
            async def recv(self):
                return await self.queue.get()
        ws = IdleWS()
        async def later_frame():
            await asyncio.sleep(0.07)
            await ws.queue.put(json.dumps({"ok":True,"topic":"balance",
                "params":{"em":72},"value":self.w.balance}))
        task = asyncio.create_task(later_frame())
        try:
            with patch("daiinas.bitsgap_futures_stream._SNAPSHOT_INTERVAL_SECONDS",0.01):
                await self.stream.watch_once(lambda _:ws,
                    on_event=lambda e:self._record([],e),max_messages=1)
        finally:
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
        self.assertGreaterEqual(len(ws.sent),4)
        self.assertTrue(all(isinstance(batch,list) and
                            all("subs" not in item for item in batch)
                            for batch in ws.sent[2:]))
        self.assertGreaterEqual(self.stream.snapshot_batches,2)
        self.assertFalse(self.stream.connected)

    async def test_retry_session_clears_snapshot_pending(self):
        self.stream._snapshot_pending = {"balance": 0.0}
        ws = FakeWS([{"type":"auth_ok","sid":"new-session"},
                     {"ok":True,"topic":"balance","params":{"em":72},"value":self.w.balance}])
        await self.stream.watch_once(lambda _:ws,
            on_event=lambda e:self._record([],e),max_messages=1)
        self.assertEqual(self.stream.snapshot_responses,1)
        self.assertEqual(self.stream._snapshot_pending,{})
        self.assertTrue(all("subs" not in entry for entry in ws.sent[2]))

    async def test_received_before_request_cannot_refresh_or_consume_pending_snapshot(self):
        observed = []
        self.stream.observation_sink = lambda **kw: observed.append(kw)
        self.stream._snapshot_pending = {"balance": 100.0}
        message = {"ok":True, "topic":"balance", "params":{"em":72},
                   "value":self.w.balance}
        self.stream._ingest(message, received_monotonic=99.0, received_ms=1783000000000)
        self.assertFalse(observed[-1]["snapshot_response"])
        self.assertEqual(self.stream.snapshot_responses, 0)
        self.assertIn("balance", self.stream._snapshot_pending)
        self.stream._ingest(message, received_monotonic=101.0, received_ms=1783000000000)
        self.assertTrue(observed[-1]["snapshot_response"])
        self.assertEqual(self.stream.snapshot_responses, 1)

    async def test_delayed_processing_preserves_actual_receive_time(self):
        observed = []
        self.stream.observation_sink = lambda **kw: observed.append(kw)
        self.stream._snapshot_pending = {"balance": 100.0}
        message = {"ok":True, "topic":"balance", "params":{"em":72},
                   "value":self.w.balance}
        with patch("daiinas.bitsgap_futures_stream.time.monotonic", return_value=120.0):
            self.stream._ingest(message, received_monotonic=101.0, received_ms=1782999990000)
        self.assertEqual(observed[-1]["received_ms"], 1782999990000)
        self.assertTrue(observed[-1]["snapshot_response"])

    async def test_null_snapshot_rejects_unexpected_envelope_before_pending_consumption(self):
        self.stream._snapshot_pending = {"orders": 100.0}
        with self.assertRaisesRegex(BitsgapError, "WS_UNVERIFIED_TOPIC_FRAME"):
            self.stream._ingest({"ok":True, "topic":"orders", "params":{"em":72},
                                 "value":None, "unexpected":"SYNTHETIC_PRIVATE"})
        self.assertIn("orders", self.stream._snapshot_pending)

    async def test_watch_keeps_receive_time_when_snapshot_timer_delays_processing(self):
        now = [1783000000000]
        self.api._clock_ms = lambda: now[0]
        observed = []
        self.stream.observation_sink = lambda **kw: observed.append(kw)
        ws = FakeWS([{"type":"auth_ok", "sid":"synthetic"},
                     {"ok":True, "topic":"balance", "params":{"em":72},
                      "value":self.w.balance}])
        original = self.stream._request_snapshots
        async def delayed_snapshot(socket):
            await original(socket)
            if self.stream.snapshot_batches >= 2:
                now[0] += 10000
        with patch.object(self.stream, "_request_snapshots", delayed_snapshot), \
             patch("daiinas.bitsgap_futures_stream._SNAPSHOT_INTERVAL_SECONDS", 0):
            await self.stream.watch_once(lambda _:ws,
                on_event=lambda e:self._record([],e), max_messages=1)
        self.assertGreaterEqual(self.stream.snapshot_batches, 2)
        self.assertLess(observed[-1]["received_ms"], now[0])
        self.assertEqual(observed[-1]["received_ms"], 1783000000000)

if __name__ == "__main__":unittest.main()
