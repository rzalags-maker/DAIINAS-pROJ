"""Synthetic normalized state only; never authenticates an exchange account."""
import asyncio
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from daiinas.bitsgap_account_state import (
    AccountState, AccountStateError, AccountReadBudget, BLOCKED, PrivateStore, main, observe_bounded,
)
from daiinas.bitsgap_futures_observe import BitsgapFuturesObserver
from daiinas.bitsgap_futures_stream import BitsgapFuturesStream
from daiinas.bitsgap_readonly import BitsgapError
from test_bitsgap_futures_observe import FakeWire, new_pem
from test_bitsgap_futures_stream import FakeWS


class AccountStateTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000
        _, pem = new_pem()
        self.wire = FakeWire()
        self.wire.balance = {"data": {"USDT": {"t": "913.2468", "a": "812.1357"}}}
        self.observer = BitsgapFuturesObserver(pem, transport=self.wire, clock_ms=lambda: self.now)
        self.observer.discover()
        self.state = self.make_state()

    def make_state(self, **kwargs):
        return AccountState(self.observer, scope_ref="synthetic-owner-scope",
                            clock_ms=lambda: self.now, **kwargs)

    def connect(self):
        self.state.connection("CONNECTING")
        self.state.connection("SUBSCRIBED")
        self.state.connection("REST_RESYNC_COMPLETE")

    def push(self, topic, value, source="REST", when=None, quality="VALIDATED", **kwargs):
        when = self.now if when is None else when
        self.now = max(self.now, when)
        return self.state.ingest(topic=topic, value=value, source=source,
             market_id=kwargs.pop("market_id", 72), started_ms=when,
             received_ms=when, quality=quality, **kwargs)

    def pair(self, topic, value):
        self.push(topic, value)
        self.push(topic, value, "WS")

    def topic(self, name):
        return self.state.status()["topics"][name]

    def test_rest_ws_null_remains_no_data_not_zero(self):
        self.connect()
        for topic in ("orders", "positions"):
            self.pair(topic, None)
            self.assertEqual(self.topic(topic)["state"], "PROVIDER_NO_DATA")
        status = self.state.status(private=True)
        self.assertEqual(status["open_positions"], "UNVERIFIED")
        self.assertEqual(status["pending_orders"], "UNVERIFIED")
        self.assertEqual(status["new_entry"], BLOCKED)

    def test_explicit_zero_compares_both_channels_but_never_funds(self):
        self.connect()
        self.pair("orders", self.wire.orders)
        self.pair("positions", self.wire.positions)
        self.assertEqual(self.topic("orders")["state"], "VERIFIED_EMPTY")
        self.assertEqual(self.topic("positions")["state"], "VERIFIED_EMPTY")
        self.assertEqual(self.state.status(private=True)["open_positions"], 0)
        self.assertFalse(self.state.model_a_input()["funding_authorized"])
        self.assertIsNone(self.state.model_a_input()["eligible_capital"])

    def test_live_bitsgap_oneway_enum_alias_normalized_without_changing_venue(self):
        # 2026-11-01 authenticated API returned ONEWAY (not ONE_WAY).
        self.observer._futures_enums["position_mode"]["items"] = {
            "ONEWAY": 1, "HEDGE": 2}
        raw_count, raw_mode, raw_margin = self.observer._positions(
            self.wire.settings, settings=True)
        self.assertEqual(raw_mode, "ONEWAY")
        self.connect()
        self.pair("positions_settings", self.wire.settings)
        settings = self.topic("positions_settings")
        self.assertEqual(settings["state"], "VALIDATED")
        self.assertEqual(self.state.status()["observed_position_mode"], "ONE_WAY")
        self.assertEqual(self.state.status()["new_entry"], BLOCKED)

    def test_unknown_bitsgap_mode_stays_unverified_not_relabelled_one_way(self):
        self.observer._futures_enums["position_mode"]["items"] = {
            "NET_CUSTOM": 1, "HEDGE": 2}
        self.connect()
        self.pair("positions_settings", self.wire.settings)
        self.assertEqual(self.topic("positions_settings")["state"], "UNVERIFIED")
        self.assertEqual(self.state.status()["new_entry"], BLOCKED)

    def test_active_order_validates_dynamic_enums_and_duplicate_identity(self):
        self.connect()
        orders = {"data": {"BTC_USDT": [{"id": "SYNTHETIC_ORDER", "eost": 4,
            "eot": 1, "eos": 1, "epps": 1, "t0": 1, "pr": "2", "am": "3"}]}, "cnt": 1}
        self.pair("orders", orders)
        self.assertEqual(self.topic("orders")["state"], "VERIFIED_ACTIVE")
        orders["data"]["BTC_USDT"] *= 2
        orders["cnt"] = 2
        self.now += 1
        self.pair("orders", orders)
        self.assertEqual(self.topic("orders")["state"], "UNVERIFIED")

    def test_active_position_count_and_settings(self):
        self.connect()
        positions = {"data": {"BTC_USDT": [{"epps": 1, "eps": 1,
                         "am": "3", "pr": "2"}]}, "cnt": 1, "epmd": 1, "epm": 2}
        self.pair("positions", positions)
        self.pair("positions_settings", self.wire.settings)
        self.assertEqual(self.topic("positions")["state"], "VERIFIED_ACTIVE")
        self.assertEqual(self.state.status()["observed_position_mode"], "ONE_WAY")
        self.assertEqual(self.state.status()["margin_committed"], "UNVERIFIED")

    def test_order_permutation_and_balance_decimal_scale_do_not_create_false_conflict(self):
        self.connect()
        order = {"id": "A", "eost":4, "eot":1, "eos":1, "epps":1, "t0":1, "pr":"2"}
        other = dict(order, id="B")
        self.push("orders", {"data":{"BTC_USDT":[order,other]}, "cnt":2})
        self.push("orders", {"data":{"BTC_USDT":[other,order]}, "cnt":2}, "WS")
        self.assertEqual(self.topic("orders")["state"], "VERIFIED_ACTIVE")
        self.push("balance", {"data":{"USDT":{"t":"1.00", "a":"0.50"}}})
        self.push("balance", {"data":{"USDT":{"t":"1", "a":"0.5"}}}, "WS")
        self.assertEqual(self.topic("balance")["state"], "VALIDATED")

    def test_ordered_state_version_and_explicit_field_provenance(self):
        self.connect()
        before = self.state.state_version
        self.pair("balance", self.wire.balance)
        after = self.state.state_version
        self.assertGreater(after, before)
        self.push("balance", self.wire.balance, "WS")
        self.assertEqual(self.state.state_version, after)
        state = self.state.status()
        self.assertEqual(state["timestamp_source"], "LOCAL_RECEIPT_CLOCK_NOT_PROVIDER")
        self.assertEqual(state["field_provenance"]["total_reported"]["sources"], ["REST", "WS"])
        self.assertEqual(state["field_provenance"]["free_margin"]["state"], "UNVERIFIED")

    def test_null_and_explicit_zero_do_not_prove_empty(self):
        self.connect()
        self.push("orders", None)
        self.push("orders", self.wire.orders, "WS")
        self.assertEqual(self.topic("orders")["state"], "UNVERIFIED")

    def test_scope_and_currency_mismatch_latch_hold(self):
        self.connect()
        self.pair("balance", self.wire.balance)
        for kwargs in ({"market_id": 71}, {"currency": "BTC"}, {"market_id": True}):
            with self.assertRaises(AccountStateError):
                self.push("balance", self.wire.balance, **kwargs)
        self.assertEqual(self.topic("balance")["state"], "CONFLICT")

    def test_stale_records_and_duplicate_ws_do_not_refresh_age(self):
        self.connect()
        self.pair("orders", self.wire.orders)
        self.assertEqual(self.push("orders", self.wire.orders, "WS", when=15000), "DUPLICATE")
        self.now = 17000
        self.assertEqual(self.topic("orders")["state"], "STALE")

    def test_out_of_order_and_same_time_conflict_fail_closed(self):
        self.connect()
        self.pair("balance", self.wire.balance)
        self.assertEqual(self.push("balance", self.wire.balance, "WS", when=999), "OUT_OF_ORDER")
        self.assertEqual(self.topic("balance")["state"], "CONFLICT")

    def test_cross_transport_conflict_not_atomic(self):
        self.connect()
        self.push("balance", self.wire.balance)
        other = {"data": {"USDT": {"t": "914", "a": "813"}}}
        self.push("balance", other, "WS", when=1001)
        self.assertEqual(self.topic("balance")["reason"], "REST_WS_CONFLICT")
        self.assertEqual(self.state.status()["snapshot_atomicity"], "NOT_ATOMIC")

    def test_rest_before_subscribe_cannot_close_gap(self):
        self.state.connection("CONNECTING")
        self.push("orders", self.wire.orders)
        self.now += 10
        self.state.connection("SUBSCRIBED")
        self.state.connection("REST_RESYNC_COMPLETE")
        self.push("orders", self.wire.orders, "WS")
        self.assertEqual(self.topic("orders")["state"], "UNVERIFIED")
        self.push("orders", self.wire.orders)
        self.assertEqual(self.topic("orders")["state"], "VERIFIED_EMPTY")

    def test_settings_contradiction_is_not_reconciled(self):
        self.connect()
        self.pair("positions", self.wire.positions)
        settings = copy.deepcopy(self.wire.settings)
        settings["epmd"] = 2
        self.pair("positions_settings", settings)
        self.assertEqual(self.topic("positions")["state"], "CONFLICT")
        self.assertEqual(self.topic("positions_settings")["reason"], "POSITION_SETTINGS_CONFLICT")

    def test_position_mode_falls_back_to_validated_positions_without_inventing_it(self):
        self.connect()
        self.pair("positions", self.wire.positions)
        self.pair("positions_settings", {"data":{}, "cnt":0})
        status = self.state.status()
        self.assertEqual(status["observed_position_mode"], "ONE_WAY")
        self.assertEqual(status["field_provenance"]["observed_position_mode"]["topic"], "positions")

    def test_wallet_display_is_not_free_margin_and_is_redacted_by_default(self):
        self.connect()
        self.pair("balance", self.wire.balance)
        private = self.state.status(private=True)
        self.assertEqual(private["available_reported"], "812.1357")
        self.assertEqual(private["free_margin"], "UNVERIFIED")
        self.assertEqual(private["model_a_active"], "NOT RECONCILED")
        safe = json.dumps(self.state.status()) + repr(self.state)
        for text in ("913.2468", "812.1357", "synthetic-owner-scope"):
            self.assertNotIn(text, safe)

    def test_inconsistent_balance_and_unknown_schema_not_accepted(self):
        self.connect()
        for value in ({"data": {"USDT": {"t": "1", "a": "2"}}}, {}, {"error": "PRIVATE"}):
            self.now += 1
            self.pair("balance", value)
            self.assertEqual(self.topic("balance")["state"], "UNVERIFIED")

    def test_disconnect_restart_requires_new_rest_ws_generation(self):
        self.connect()
        self.pair("orders", self.wire.orders)
        self.state.connection("DISCONNECTED")
        self.assertEqual(self.topic("orders")["state"], "UNVERIFIED")
        self.state.connection("CONNECTING")
        self.assertEqual(self.topic("orders")["state"], "STALE")

    def test_all_commands_still_rejected_by_existing_adapter(self):
        before = len(self.wire.calls)
        for topic in ("order_place", "order_cancel", "position_close", "leverage_change",
                      "margin_size_change", "margin_type_change", "transfer", "withdraw"):
            with self.assertRaises(BitsgapError):
                self.observer.read(topic)
        self.assertEqual(len(self.wire.calls), before)

    def test_rest_private_sink_captures_real_null_classification(self):
        self.observer.observation_sink = self.state.ingest
        self.wire.orders = self.wire.positions = None
        self.observer.wallet_observation()
        self.assertEqual(self.state.records[("orders", "REST")].quality, "PROVIDER_NO_DATA")
        self.assertEqual(self.state.status(private=True)["available_reported"], "812.1357")

    def test_optional_catalog_and_history_reads_not_broken_by_state_sink(self):
        self.observer.observation_sink = self.state.ingest
        self.assertEqual(self.observer.read("conf_pairs"), self.wire.pairs)
        self.assertEqual(self.observer.read("orders_history", pair="BTC_USDT"), self.wire.history)
        self.assertEqual(self.state.records, {})

    def test_rest_sink_is_captured_before_a_bounded_worker_detaches_it(self):
        self.observer.observation_sink = self.state.ingest
        original = self.observer._transport
        def detach(*args):
            self.observer.observation_sink = None
            return original(*args)
        self.observer._transport = detach
        self.observer.read("balance")
        self.assertIn(("balance", "REST"), self.state.records)

    def test_private_checkpoint_single_writer_recovery_and_status_reader(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / "private.sqlite"
            store = PrivateStore(path)
            try:
                self.state = self.make_state(store=store)
                self.connect()
                self.pair("balance", self.wire.balance)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                with self.assertRaises(AccountStateError):
                    PrivateStore(path)
                reader = PrivateStore(path, readonly=True)
                try:
                    view = self.make_state(store=reader, status_reader=True)
                    self.assertEqual(view.status()["connection"], "CONNECTED")
                    self.assertEqual(view.status(private=True)["available_reported"], "812.1357")
                    with self.assertRaises(AccountStateError):
                        AccountState(self.observer, scope_ref="foreign-scope", store=reader)
                finally:
                    reader.close()
            finally:
                store.close()
            recovered_store = PrivateStore(path)
            try:
                recovered = self.make_state(store=recovered_store)
                self.assertEqual(recovered.status()["topics"]["balance"]["state"], "STALE")
                self.assertEqual(recovered.status(private=True)["wallet_amounts_status"], "LAST_OBSERVED_NOT_CURRENT")
                self.assertEqual(recovered.model_a_input()["decision"], BLOCKED)
            finally:
                recovered_store.close()

    def test_unsafe_checkpoint_and_ci_private_output_blocked(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / "unsafe.sqlite"
            path.touch(mode=0o644)
            path.chmod(0o644)  # Make the test independent of the executor umask.
            with self.assertRaises(AccountStateError):
                PrivateStore(path)
        output = io.StringIO()
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}), contextlib.redirect_stdout(output):
            self.assertEqual(main(["--status", "--private-panel", "--scope-ref", "test"]), 2)
        self.assertIn("PRIVATE_OUTPUT_DISALLOWED", output.getvalue())

    def test_private_status_reads_checkpoint_without_loading_api_credentials(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / "status.sqlite"
            store = PrivateStore(path)
            try:
                self.state = self.make_state(store=store)
                self.connect()
                self.pair("balance", self.wire.balance)
                output = io.StringIO()
                with contextlib.redirect_stdout(output), patch.object(output, "isatty", return_value=True), \
                     patch("daiinas.bitsgap_account_state.time.time", return_value=1), \
                     patch("daiinas.bitsgap_account_state.BitsgapFuturesObserver", side_effect=AssertionError("No API key access")):
                    code = main(["--status", "--private-panel", "--state-file", str(path),
                                 "--scope-ref", "synthetic-owner-scope"])
                self.assertEqual(code, 2)
                self.assertEqual(json.loads(output.getvalue())["available_reported"], "812.1357")
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    main(["--status", "--capital-preview", "--hypothetical-initial",
                          "--state-file", str(path), "--scope-ref", "synthetic-owner-scope"])
                self.assertNotIn("812.1357", output.getvalue())
                self.assertNotIn("913.2468", output.getvalue())
                self.assertIn("capital_admission_preview", output.getvalue())
            finally:
                store.close()


class AccountStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_ws_stream_feeds_private_service_without_public_payloads(self):
        _, pem = new_pem()
        wire = FakeWire()
        wire.orders = wire.positions = None
        api = BitsgapFuturesObserver(pem, transport=wire, clock_ms=lambda: 1000)
        api.discover()
        state = AccountState(api, scope_ref="mock", clock_ms=lambda:1000)
        api.observation_sink = state.ingest
        # Direct watch test uses no SQLite; production bounded worker marshals
        # REST thread writes to its event loop before touching private storage.
        stream = BitsgapFuturesStream(api, observation_sink=state.ingest,
                                      connection_sink=state.connection)
        ws = FakeWS([{"type":"auth_ok", "sid":"SYNTHETIC"},
                     {"ok":True, "topic":"balance", "params":{"em":72}, "value":wire.balance},
                     {"ok":True, "topic":"orders", "params":{"em":72}, "value":None}])
        events = []
        async def event(value):
            events.append(value)
        await stream.watch_once(lambda _:ws, on_event=event, max_messages=2)
        self.assertEqual(len([t for t,_,_ in wire.calls if t == "balance"]), 2)
        self.assertEqual(state.records[("balance", "WS")].quality, "VALIDATED")
        self.assertEqual(state.records[("orders", "WS")].quality, "PROVIDER_NO_DATA")
        self.assertNotIn("61.07", json.dumps(events) + json.dumps(state.status()))
        self.assertFalse(state.connected)
        self.assertTrue(all(packet["topic"] in ("balance", "orders", "positions", "positions_settings")
                            for packet in ws.sent[1]))

    async def test_bounded_worker_private_store_thread_marshalling_and_disconnect(self):
        _, pem = new_pem()
        wire = FakeWire()
        api = BitsgapFuturesObserver(pem, transport=wire)
        api.discover()
        sessions = []
        def connect(_):
            ws = FakeWS([{"type":"auth_ok", "sid":"MOCK"},
                         {"ok":True, "topic":"balance", "params":{"em":72}, "value":wire.balance}])
            sessions.append(ws)
            return ws
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            store = PrivateStore(Path(directory) / "state.sqlite")
            try:
                result = await observe_bounded(api, connect, seconds=6, scope_ref="mock", store=store)
                self.assertGreaterEqual(len(sessions), 2)
                self.assertEqual(result.status()["connection"], "DISCONNECTED")
                self.assertEqual(store.load()["currency"], "USDT")
                self.assertFalse(result.model_a_input()["funding_authorized"])
                self.assertIsNone(api.observation_sink)
                self.assertIsNone(api.request_budget)
            finally:
                store.close()


class AccountReadBudgetTests(unittest.TestCase):
    def test_settings_one_second_and_ten_second_windows_are_shared(self):
        now = [0.0]
        budget = AccountReadBudget(clock=lambda:now[0])
        waits = []
        class ClockWait:
            def is_set(self): return False
            def wait(self, seconds):
                waits.append(seconds)
                now[0] += seconds
        budget.stopped = ClockWait()
        for _ in range(6):
            budget.acquire(("positions_settings",))
        grants = budget.events["positions_settings"]
        self.assertTrue(waits)
        self.assertGreaterEqual(grants[-1], 10)
        self.assertTrue(all(b-a >= 1 for a,b in zip(grants,grants[1:])))

    def test_batch_reserves_all_topics_at_one_time_and_stop_unblocks(self):
        budget = AccountReadBudget(clock=lambda:0)
        budget.acquire(("balance", "orders", "positions", "positions_settings"))
        self.assertTrue(all(times == [0] for times in budget.events.values()))
        budget.stop()
        with self.assertRaises(AccountStateError):
            budget.acquire(("positions_settings",))
        with self.assertRaises(AccountStateError):
            budget.acquire(("order_place",))


if __name__ == "__main__":
    unittest.main()
