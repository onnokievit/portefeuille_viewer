"""Isolated data-contract tests; no real database, profile or IBKR connections."""
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import polars as pl

from portefeuille_viewer.services.asset_dashboard_data import POSITION_COLUMNS, build_dashboard_payload, dividend_display, json_safe


class DashboardTests(unittest.TestCase):
    def store(self):
        return SimpleNamespace(
            repository_snapshot_active_asset_rollup_data=pl.DataFrame({
                "asset_rollup": ["AAPL", "UVXY", "CORRECTIE-BENCHMARK"],
                "status": ["active", "inactive", "active"],
            }),
            aggregator_snapshot_aandelen_live=pl.DataFrame({
                "asset_rollup": ["AAPL", "AAPL", "UVXY"],
                "broker": ["a", "b", "a"], "aantal_bezit": [-2, 0, 5],
                "koers": [100., 100., 20.],
            }),
            aggregator_snapshot_load_open_opties_from_tx_live=pl.DataFrame({
                "asset_rollup": ["AAPL", "UVXY"], "SomVantransactie_aantal": [-100, -200],
                "optie_exp_date": [date(2026, 11, 20)] * 2,
                "broker": ["a", "b"], "optie_call_put": ["call", "put"],
                "optie_strike": [110., 20.], "Koers": [100., 20.],
                "SomVantransactie_euro_totaal": [300., 200.],
                "opt_total_result": [50., -20.], "SomVantransactie_fee": [-2., -3.],
                "ITM_OTM": [0., -40.],
            }),
            snapshot_aandelen_projection_v2=pl.DataFrame({
                "asset_rollup": ["AAPL", "UVXY"], "koers": [100., 20.],
            }),
        )

    def test_filter_scope_and_short_holdings(self):
        store = self.store()
        result = build_dashboard_payload(store, "AAPL")
        self.assertEqual(result["assets"], ["AAPL", "UVXY"])
        self.assertEqual(len(result["positions"]["stocks"]), 1)
        self.assertEqual(result["positions"]["stocks"][0]["waarde_bezit"], -200)
        self.assertEqual(len(result["positions"]["options"]), 1)
        self.assertEqual(result["positions"]["options"][0]["optie_exp_date"], "2026-11-20")
        self.assertNotIn("waarde_bezit", store.aggregator_snapshot_aandelen_live.columns)

    def test_asset_switch_does_not_retain_previous_values(self):
        store = self.store()
        result = build_dashboard_payload(store, "UVXY")
        self.assertEqual(result["summary"]["koers"], 20.)
        self.assertEqual(result["positions"]["stocks"][0]["aantal_bezit"], 5)
        self.assertEqual(result["indicator"], {})

    def test_access_decimal_quantities_with_live_float_quotes(self):
        store = self.store()
        store.aggregator_snapshot_aandelen_live = pl.DataFrame({
            "asset_rollup": ["AAPL", "AAPL", "UVXY"],
            "koers": [100.25, 100.25, 20.0],
            "aantal_bezit": [Decimal("-2.50"), Decimal("0"), Decimal("5")],
        })
        result = build_dashboard_payload(store, "AAPL")
        self.assertEqual(result["assets"], ["AAPL", "UVXY"])
        self.assertEqual(result["positions"]["stocks"][0]["waarde_bezit"], -250.625)
        self.assertEqual(len(result["positions"]["stocks"]), 1)
        json.dumps(result, allow_nan=False)

    def test_empty_startup_and_removed_asset(self):
        self.assertEqual(build_dashboard_payload(SimpleNamespace())["asset"], "")
        self.assertEqual(build_dashboard_payload(self.store(), "REMOVED")["asset"], "AAPL")

    def test_status_filter_uses_existing_status_and_handles_empty_selection(self):
        store = self.store()
        self.assertEqual(build_dashboard_payload(store, "UVXY", "active")["assets"], ["AAPL"])
        self.assertEqual(build_dashboard_payload(store, "AAPL", "inactive")["asset"], "UVXY")
        self.assertEqual(build_dashboard_payload(store, status="all")["assets"], ["AAPL", "UVXY"])
        store.repository_snapshot_active_asset_rollup_data = pl.DataFrame({
            "asset_rollup": ["AAPL"], "status": ["active"],
        })
        self.assertEqual(build_dashboard_payload(store, status="inactive")["asset"], "")

    def test_dividend_colours_match_legacy_date_windows(self):
        from datetime import timedelta
        today = date(2026,10,27)
        for days, expected in [(-1,"#D9D9D9"),(0,"#FF0000"),(7,"#FF0000"),
                               (8,"#FFFF00"),(30,"#FFFF00"),(31,None)]:
            with self.subTest(days=days):
                d = dividend_display({"next_dividend_date":today+timedelta(days=days),
                                      "next_dividend_amount":Decimal(".25")},today)
                self.assertEqual(d["background"],expected)
        self.assertEqual(dividend_display({},today)["background"],"#D9D9D9")

    def test_only_existing_visible_position_columns_are_exposed(self):
        result = build_dashboard_payload(self.store(), "AAPL")
        self.assertEqual([f for _,f,_ in POSITION_COLUMNS["stocks"]],
                         ["broker", "asset_rollup", "koers", "aantal_bezit", "waarde_bezit"])
        self.assertEqual(len(POSITION_COLUMNS["sprinters"]), 9)
        self.assertEqual([label for label,_,_ in POSITION_COLUMNS["options"]],
                         ["itm", "broker", "asset", "c/p", "exp date", "strike", "Koers", "delta",
                          "aantal", "premie", "result", "itm_otm", "tv/u", "time value", "comment", "updated"])
        for key,rows in result["positions"].items():
            for row in rows:
                self.assertEqual(set(row), {field for _,field,_ in POSITION_COLUMNS[key]})

    def test_option_timevalue_and_latest_cached_comment_match_series(self):
        from portefeuille_viewer.data.repository import build_uniek_id
        store = self.store()
        identity = build_uniek_id({"broker":"a", "asset_rollup":"AAPL", "asset_type":"optie",
                                   "optie_exp_date":date(2026,11,20), "optie_call_put":"call", "optie_strike":110.})
        store.repository_snapshot_open_optie_comments = pl.DataFrame({
            "uniek_id":[identity,identity], "optie_comment":["oud","nieuw"],
            "optie_comment_updated_at":[date(2026,10,1),date(2026,10,2)],
        })
        store.snapshot_optie_timevalue_live = pl.DataFrame({
            "broker":["A"], "asset":["aapl"], "exp":["20/11/2026"], "c_p":["call"],
            "strike":[110.], "time_per_unit":[.6], "time_total":[60.],
        })
        row = build_dashboard_payload(store,"AAPL")["positions"]["options"][0]
        self.assertEqual(row["time_per_unit"],.6)
        self.assertEqual(row["time_value"],60.)
        self.assertEqual(row["premie"],300.)
        self.assertEqual(row["totaal_resultaat_optie"],50.)
        self.assertEqual(row["optie_comment"],"nieuw")
        self.assertAlmostEqual(row["afwijking_pct"],(100-110)/110*100)

    def test_non_finite_values_are_missing_not_zero(self):
        result = json_safe({"values": [float("nan"), float("inf"), 0]})
        self.assertEqual(result["values"], [None, None, 0])
        json.dumps(result, allow_nan=False)


class DashboardLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_hidden_tab_is_lazy_and_updates_are_batched(self):
        from portefeuille_viewer.ui_logica.asset_dashboard_tab import AssetDashboardTab
        tab = AssetDashboardTab()
        self.assertFalse(tab._initialized)
        tab._snapshot_updated("snapshot_asset_indicator_live")
        self.assertFalse(tab._timer.isActive())
        tab._active = True
        tab._snapshot_updated("snapshot_asset_indicator_live")
        self.assertTrue(tab._timer.isActive())
        timer_id = tab._timer.timerId()
        tab._snapshot_updated("snapshot_asset_indicator_live")
        self.assertEqual(timer_id, tab._timer.timerId())
        tab.set_active(False)
        self.assertFalse(tab._timer.isActive())
        tab.deleteLater()

    def test_asset_selection_emits_price_focus_and_unchanged_data_is_not_sent(self):
        from portefeuille_viewer.ui_logica.asset_dashboard_tab import AssetDashboardTab, DashboardBridge
        tab = AssetDashboardTab()
        tab.bridge = DashboardBridge(tab)
        tab._active = tab._ready = True
        tab._asset_status = "all"
        selections, messages = [], []
        tab.assetChanged.connect(selections.append)
        tab.bridge.updated.connect(messages.append)
        with patch("portefeuille_viewer.ui_logica.asset_dashboard_tab.SNAPSHOT_STORE", DashboardTests().store()), \
                patch.object(tab, "_request_analytics"):
            tab._publish()
            tab._publish()
            self.assertEqual(len(messages), 1)
            tab.bridge.selectAsset("UVXY")
        self.assertEqual(selections, ["AAPL", "UVXY"])
        self.assertEqual(tab.selected_asset, "UVXY")
        tab.deleteLater()


if __name__ == "__main__":
    unittest.main()
