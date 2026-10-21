"""Run from project root: python -m unittest discover -s devtools -p test_cash_broker_selection.py"""
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch, Mock
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import polars as pl
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication, QComboBox

from portefeuille_viewer.services import cash_management_chart_service as service
from portefeuille_viewer.services import year_result_vs_indices_service as indices
from portefeuille_viewer.ui_logica import cash_management_web_tab as dashboard
from portefeuille_viewer.config import settings_manager as settings
from portefeuille_viewer.ui_logica.cash_management_entries_dialog import CashManagementEntriesDialog


class BrokerSelectionTests(TestCase):
    def setUp(self):
        self.cash = pl.DataFrame({
            "datum": [date(2025, 12, 31)] * 4,
            "broker": ["degiro", "interactive", "lynx", "new"],
            "amount": [100., 200., 300., 400.],
        })
        self.balances = pl.DataFrame({
            "datum": [date(2025, 12, 31)] * 4 + [date(2026, 1, 2)],
            "broker": ["degiro", "interactive", "lynx", "new", "new"],
            "ending_balance": [110., 220., 330., 440., 480.],
        })
        self.a = patch.object(service, "_load_cash_entries_df", return_value=self.cash)
        self.b = patch.object(service, "_load_daily_balances_df", return_value=self.balances)
        self.a.start(); self.b.start()
        self.addCleanup(self.a.stop); self.addCleanup(self.b.stop)

    def test_totals_and_stacking_follow_selection(self):
        for selection, expected in [(["new"], 480.), (["degiro", "new"], 590.),
                                    (["degiro", "interactive", "lynx"], 660.),
                                    (["degiro", "interactive", "lynx", "new"], 1140.)]:
            payload = service.build_cash_management_chart_payload(selection)
            last = max(p["date"] for p in payload["points"])
            points = [p for p in payload["points"] if p["date"] == last]
            self.assertEqual({p["broker"] for p in points}, set(selection))
            self.assertEqual(points[0]["total_value"], expected)
            self.assertEqual(points[0]["total_profit"], sum(p["profit"] for p in points))
            self.assertEqual(max(p["invested_stacked"] for p in points), points[0]["total_invested"])

    def test_missing_broker_and_empty_selection(self):
        for selection in ([], ["missing"]):
            self.assertEqual(service.build_cash_management_chart_payload(selection)["points"], [])
        self.assertEqual(service.build_cash_management_chart_payload(["degiro", "missing"]),
                         service.build_cash_management_chart_payload(["degiro"]))

    def test_selection_bridge_rebuilds_and_rejects_empty(self):
        parent = QObject()
        parent.publish_payload = Mock()
        bridge = dashboard._CashDashboardBridge(parent)
        manager = Mock()
        manager.get_chart_visible_series_by_chart.return_value = {}
        with patch.object(dashboard, "get_settings", return_value=manager), \
             patch.object(dashboard.broker_repository, "load_brokers", return_value=["new", "lynx"]):
            bridge.setBrokers('["new", "unknown"]')
            manager.set_cash_selected_brokers.assert_called_once_with(dashboard.broker_repository.db_path, ["new"])
            parent.publish_payload.assert_called_with(force_reload=True)
            manager.set_year_result_vs_indices_selected_portfolio.assert_called_with(["total", "new"])
            manager.set_cash_selected_brokers.reset_mock()
            bridge.setBrokers('[]')
            manager.set_cash_selected_brokers.assert_not_called()
            self.assertTrue(parent.publish_payload.call_args.kwargs['reuse_cache'])

    def test_database_switch_discards_cached_payload(self):
        from types import SimpleNamespace
        tab = SimpleNamespace(_payload_cache={'old': 'data'}, _needs_force_reload=False,
                              _is_active=True, _js_ready=True, publish_payload=Mock())
        with patch.object(dashboard, 'clear_year_result_vs_indices_cache') as clear:
            dashboard.CashManagementWebTab._on_database_changed(tab, 'muriel')
            clear.assert_called_once()
        self.assertIsNone(tab._payload_cache)
        self.assertTrue(tab._needs_force_reload)
        self.assertTrue(tab.publish_payload.call_args.kwargs['force_reload'])

    def test_existing_entry_keeps_unlisted_broker(self):
        app = QApplication.instance() or QApplication([])
        combo = QComboBox()
        combo.addItems(['degiro', 'new'])
        CashManagementEntriesDialog._set_combo_value(None, combo, 'historical')
        self.assertEqual(combo.currentText(), 'historical')
        CashManagementEntriesDialog._set_combo_value(None, combo, 'new')
        self.assertEqual(combo.currentText(), 'new')
        self.assertEqual(combo.count(), 3)

    def test_indices_accept_new_broker_and_filtered_total(self):
        payload = service.build_cash_management_chart_payload(["new"])
        series = indices._build_portfolio_series(payload, ["total", "new"])
        self.assertEqual([s["id"] for s in series], ["portfolio:total", "portfolio:new"])
        self.assertEqual(series[0]["points"], series[1]["points"])
        self.assertTrue(series[0]["points"])

    def test_pivot_filters_and_keeps_missing_column(self):
        rows = [{"id": 1, "datum": date(2026, 1, 2), "broker": "new", "ending_balance": 480.},
                {"id": 2, "datum": date(2026, 1, 2), "broker": "lynx", "ending_balance": 330.}]
        with patch.object(dashboard, "list_account_daily_balances", return_value=rows):
            pivot = dashboard._build_pivot_rows(["new", "missing"])
        self.assertEqual(pivot[0]["total"], 480.)
        self.assertEqual(set(pivot[0]["brokers"]), {"new", "missing"})
        self.assertIsNone(pivot[0]["brokers"]["missing"])

    def test_settings_per_database_and_external_edit(self):
        with TemporaryDirectory() as directory:
            shared = Path(directory) / "shared.ini"
            local = Path(directory) / "local.ini"
            shared.write_text("[brokers]\nlist = degiro\n", encoding="utf-8")
            local.write_text("", encoding="utf-8")
            with patch.object(settings, "SHARED_CONFIG_PATH", shared), patch.object(settings, "LOCAL_CONFIG_PATH", local):
                manager = settings.SettingsManager.__new__(settings.SettingsManager)
                manager._reload_from_disk()
                shared.write_text("[brokers]\nlist = degiro, new\n", encoding="utf-8")
                manager.set_cash_selected_brokers(r"C:\data\ONNO.accdb", ["new"])
                manager.set_cash_selected_brokers(r"C:\data\MURIEL.accdb", ["degiro"])
                manager._reload_from_disk()
                self.assertEqual(manager.get_brokers(), ["degiro", "new"])
                self.assertEqual(manager.get_cash_selected_brokers(r"C:\data\ONNO.accdb"), ["new"])
                self.assertEqual(manager.get_cash_selected_brokers(r"C:\data\MURIEL.accdb"), ["degiro"])
                self.assertIsNone(manager.get_cash_selected_brokers("quinten"))


if __name__ == "__main__":
    main()
