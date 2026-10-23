"""Exercise real IB wrapper callbacks with every network/DB boundary mocked."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication
from ibapi.client import EClient
from portefeuille_viewer.services import price_feed as module
from portefeuille_viewer.ui_logica.subscriptions_tab import SubscriptionsTab
from test_subscription_manager import Clock


class FeedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        settings = SimpleNamespace(get_market_data_settings=lambda: {
            "capacity": 3, "batch_size": 1, "rotation_seconds": 30, "stale_seconds": 180})
        self.patches = [patch("portefeuille_viewer.config.get_settings", return_value=settings),
                        patch.object(module, "_subscription_logger", return_value=logging.getLogger("test")),
                        patch.object(module.threading.Thread, "start"),
                        patch.object(module.threading.Thread, "join"),
                        patch.object(module.ASSET_LAST_PRICE_STORE, "ensure_loaded", return_value={}),
                        patch.object(module.ASSET_LAST_PRICE_STORE, "update_price"),
                        patch.object(module.PriceFeedService, "_load_option_last_prices_from_db")]
        for name in ("connect", "reqMktData", "cancelMktData", "reqContractDetails",
                     "reqMarketDataType", "disconnect"):
            self.patches.append(patch.object(EClient, name))
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.service = module.PriceFeedService("test", 0, 299)
        self.feed = self.service._feed
        self.feed._app.nextValidId(1)
        self.clock = Clock()
        self.feed.subscriptions.clock = self.clock
        self.feed.subscriptions.last_rotation = self.clock()
        self.addCleanup(self.feed.shutdown)

    def steps(self, count=10):
        for _ in range(count):
            self.clock.now += .2
            self.feed.subscriptions.step()

    def asset(self):
        self.service.ensure_subscriptions([("SPCX", "USD", "aandeel", "SMART", "NASDAQ", 123)])
        self.steps()
        return next(iter(self.feed.subscriptions.by_request))

    def test_falling_share_last_reaches_store_and_diagnostics(self):
        req_id = self.asset()
        app = self.feed._app
        app.marketDataType(req_id, 1)
        app.tickPrice(req_id, 4, 100., None)
        app.tickPrice(req_id, 1, 89., None)
        app.tickPrice(req_id, 2, 91., None)
        self.assertEqual(self.service.get("SPCX", "USD"), 100.)
        app.tickPrice(req_id, 4, 90., None)
        self.assertEqual(self.service.get("SPCX", "USD"), 90.)
        row = self.service.subscription_snapshot()["rows"][0]
        self.assertEqual(row["fields"]["display"]["source"], "last")
        self.assertEqual(row["fields"]["last"]["value"], 90.)
        self.assertIsNotNone(row["processed_at"])

    def test_1101_rebuilds_but_1102_does_not_duplicate_streams(self):
        old = self.asset()
        self.feed._app.error(-1, 1102, "Restored, data maintained")
        self.steps()
        self.assertEqual(set(self.feed.subscriptions.by_request), {old})
        self.feed._app.error(-1, 1101, "Restored, data lost")
        self.steps()
        new = next(iter(self.feed.subscriptions.by_request))
        self.assertNotEqual(new, old)
        self.feed._app.tickPrice(old, 4, 1., None)
        self.assertIsNone(self.service.get("SPCX", "USD"))
        self.feed._app.tickPrice(new, 4, 90., None)
        self.assertEqual(self.service.get("SPCX", "USD"), 90.)

    def test_heartbeat_cannot_mask_backend_outage(self):
        self.asset()
        self.feed._app.error(-1, 1100, "IB connection lost")
        self.feed._app.currentTime(1700000000)
        self.assertEqual(self.feed.connection_status(), "stale")
        self.assertFalse(self.feed.subscriptions.connected)

    def test_old_socket_callbacks_cannot_reset_new_session(self):
        self.asset()
        old_app = self.feed._app
        self.feed._app = object()
        try:
            old_app.error(-1, 1100, "obsolete session")
            old_app.connectionClosed()
            self.assertTrue(self.feed.subscriptions.connected)
            self.assertEqual(self.feed.connection_status(), "connected")
        finally:
            self.feed._app = old_app

    def test_delayed_option_bid_ask_are_used_without_mixing_old_live_quotes(self):
        self.service.ensure_option_subscriptions([(1, 555, "SMART", "USD")])
        self.steps()
        req_id = next(iter(self.feed.subscriptions.by_request))
        self.feed._app.tickPrice(req_id, 66, 4., None)
        self.feed._app.tickPrice(req_id, 67, 6., None)
        row = self.service.get_option_last(1)
        self.assertEqual(row["last_px"], 5.)
        self.assertEqual(row["px_source"], "delayed_mid")

    def test_empty_universe_removes_requested_and_diagnostic_records(self):
        self.asset()
        self.service.ensure_subscriptions([])
        self.steps()
        self.assertEqual(self.service.subscription_snapshot()["rows"], [])
        self.assertEqual(self.feed._tid_by_key, {})

    def test_all_supported_error_signatures(self):
        for args in [(101, "limit"), (101, "limit", ""),
                     (1700000000, 101, "limit"), (1700000000, 101, "limit", "")]:
            req_id = self.asset()
            self.feed._app.error(req_id, *args)
            self.assertNotIn(req_id, self.feed.subscriptions.by_request)
            self.feed.subscriptions.records[next(iter(self.feed.subscriptions.records))].retry_at = 0

    def test_options_same_contract_share_one_stream_and_fan_out(self):
        self.service.ensure_option_subscriptions([(1, 555, "SMART", "USD"), (2, 555, "SMART", "USD")])
        self.steps()
        self.assertEqual(len(self.feed.subscriptions.by_request), 1)
        req_id = next(iter(self.feed.subscriptions.by_request))
        self.feed._app.marketDataType(req_id, 1)
        self.feed._app.tickPrice(req_id, 1, 4., None)
        self.feed._app.tickPrice(req_id, 2, 6., None)
        for sid in (1, 2):
            self.assertEqual(self.service.get_option_last(sid)["last_px"], 5.)

    def test_option_uses_app_notation_before_and_after_ib_details(self):
        from datetime import date
        import threading
        # Import the real order formatter without loading machine settings or DBs.
        with patch("portefeuille_viewer.config.get_databases", return_value={}), \
             patch("portefeuille_viewer.config.get_default_database", return_value=None), \
             patch("pyodbc.connect", side_effect=AssertionError("DB access forbidden")):
            from portefeuille_viewer.services import option_timevalue_service as option_module
            row = SimpleNamespace(series_id=2813, conid=555, exchange_code="SMART", ib_currency="USD",
                                  broker="lynx", asset_rollup="AAPL", expiry=date(2026, 12, 18),
                                  strike=250.5, optie_call_put="call")
            worker = SimpleNamespace(_extract_open_series=lambda: [row],
                                     _upsert_master_and_resolve=lambda rows: rows,
                                     _load_underlying_close_map=lambda: {}, _state_lock=threading.Lock())
            with patch.object(option_module.repository, "build_uniek_id",
                              wraps=option_module.repository.build_uniek_id) as formatter, \
                 patch.object(option_module.QMetaObject, "invokeMethod"):
                option_module.OptionTimevalueService._rebuild_universe_worker(worker)
                formatter.assert_called_once_with({"broker": "lynx", "asset_rollup": "AAPL",
                    "asset_type": "optie", "optie_exp_date": date(2026, 12, 18),
                    "optie_strike": 250.5, "optie_call_put": "call"})
            label = worker._pending_rebuild_result["subs"][0][4]
            self.assertEqual(label, "lynx-AAPL-optie-18-12-2026-call-250.5")
        self.service.ensure_option_subscriptions([(2813, 555, "SMART", "USD", label)])
        self.steps()
        record = next(iter(self.feed.subscriptions.records.values()))
        record.spec["description"] = "AAPL  261218C00250500"
        tab = SubscriptionsTab(self.service, settings=Mock())
        self.assertEqual(tab.table.item(0, 0).text(), label)
        tab.close()

    def test_option_greeks_do_not_refresh_old_bid_ask_price_time(self):
        self.service.ensure_option_subscriptions([(1, 555, "SMART", "USD")])
        self.steps()
        req_id = next(iter(self.feed.subscriptions.by_request))
        app = self.feed._app
        app.tickPrice(req_id, 1, 4., None)
        app.tickPrice(req_id, 2, 6., None)
        before = self.service.get_option_last(1)["last_update"]
        app.tickOptionComputation(req_id, 13, 0, .2, .5, 5., 0, .1, .1, -.1, 100.)
        self.assertEqual(self.service.get_option_last(1)["last_update"], before)

    def test_contract_schedule_closes_stream(self):
        req_id = self.asset()
        key = self.feed.subscriptions.by_request[req_id]
        record = self.feed.subscriptions.records[key]
        detail_id = record.details_req_id
        self.assertIsNotNone(detail_id)
        self.feed._app.contractDetails(detail_id, SimpleNamespace(
            tradingHours="20231114:CLOSED", timeZoneId="UTC",
            contract=SimpleNamespace(localSymbol="SPCX", conId=123)))
        self.feed._app.contractDetailsEnd(detail_id)
        self.steps()
        self.assertIsNone(record.req_id)
        self.assertEqual(record.status, "closed")

    def test_diagnostic_tab_offscreen(self):
        req_id = self.asset()
        self.feed._app.marketDataType(req_id, 3)
        self.feed._app.tickPrice(req_id, 68, 90., None)
        settings = Mock()
        tab = SubscriptionsTab(self.service, settings=settings)
        tab.resize(1450, 650)
        tab.show()
        tab.set_active(True)
        self.app.processEvents()
        self.assertEqual(tab.table.rowCount(), 1)
        self.assertEqual(tab.table.item(0, 7).text(), "Delayed")
        tab.search.setText("nonexistent")
        self.assertEqual(tab.table.rowCount(), 0)
        tab.search.clear()
        tab.inputs["rotation_seconds"].setValue(15)
        tab._apply()
        self.assertEqual(self.feed.subscriptions.rotation_seconds, 15)
        tab.set_active(False)
        self.assertFalse(tab.timer.isActive())
        tab.close()


class SettingsTests(unittest.TestCase):
    def test_market_settings_only_touch_temp_local_file(self):
        from portefeuille_viewer.config import settings_manager as module
        import configparser
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shared = root / "shared.ini"
            local = root / "local.ini"
            shared.write_text("[comment_colors]\n4 = Rood,#f8d7da,#000000\n", encoding="utf-8")
            local.write_text("[ui]\ntheme = light\n", encoding="utf-8")
            original = shared.read_bytes()
            with patch.object(module, "SHARED_CONFIG_PATH", shared), \
                 patch.object(module, "LOCAL_CONFIG_PATH", local), \
                 patch.object(module, "LOCAL_CONFIG_DIR", root):
                manager = module.SettingsManager.__new__(module.SettingsManager)
                manager.config = configparser.ConfigParser()
                manager._reload_from_disk()
                manager.set_market_data_settings({"capacity": 90, "batch_size": 10,
                    "rotation_seconds": 30, "stale_seconds": 180})
                self.assertEqual(shared.read_bytes(), original)
                self.assertIn("theme = light", local.read_text())
                self.assertEqual(manager.get_market_data_settings()["capacity"], 90)
                shared_cfg, local_cfg = manager._split_config(manager.config)
                self.assertFalse(shared_cfg.has_section("market_data"))
                self.assertTrue(local_cfg.has_section("market_data"))


if __name__ == "__main__":
    unittest.main()
