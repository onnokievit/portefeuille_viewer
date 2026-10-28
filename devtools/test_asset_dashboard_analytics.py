"""Payoff/history regression checks without real databases or network access."""
import ast
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import unittest

import polars as pl

from portefeuille_viewer.services.asset_dashboard_analytics import capture_analytics, calculate_analytics
from portefeuille_viewer.services.asset_dashboard_logic import DashboardAssetLogic


def fixture():
    store = SimpleNamespace(
        repository_snapshot_aandelen=pl.DataFrame({"asset_rollup": ["AAPL"],
            "euro_koop": [-1000.], "aantal_koop": [10.], "euro_verkoop": [240.],
            "aantal_verkoop": [-2.], "fee_koop": [-2.], "fee_verkoop": [-1.]}),
        repository_snapshot_load_open_opties=pl.DataFrame({"asset_rollup": ["AAPL", "AAPL"],
            "optie_strike": [110., 90.], "optie_call_put": ["call", "put"],
            "SomVantransactie_aantal": [Decimal("-100"), Decimal("-100")],
            "SomVantransactie_euro_totaal": [200., 100.], "SomVantransactie_fee": [-1., -1.]}),
        repository_snapshot_gesloten_opties=pl.DataFrame({"asset_rollup": ["AAPL"],
            "clos_opt_transactie_euro_totaal": [150.], "clos_opt_transactie_fee": [-1.]}),
        repository_snapshot_open_sprinters=None, repository_snapshot_gesloten_sprinters=None,
        repository_portfolio_dividend=pl.DataFrame({"asset_rollup": ["AAPL"], "div_en_bel": [20.]}),
        repository_snapshot_historical_ohlcv=pl.DataFrame({"asset_rollup": ["AAPL"]*3,
            "datum": [date(2026,1,5),date(2026,1,6),date(2026,1,7)],
            "open_price": [99.,101.,None], "high_price": [102.,104.,None],
            "low_price": [98.,100.,None], "close_price": [100.,103.,104.]}),
        repository_snapshot_per_dag_asset_result_v2=pl.DataFrame({"asset_rollup": ["AAPL"]*2,
            "datum": [date(2026,1,5),date(2026,1,7)], "totaal_v2": [120.,240.],
            "totaal_aantal_bezit_v2": [8.,108.]}),
    )
    payload={"asset":"AAPL", "summary":{"koers":100.}, "reference":{"ib_currency":"USD"}}
    settings={"currency_factor":1.2, "start":"2026-01-01", "end":"2026-01-31", "step_pct":2.}
    return store,payload,settings


class AnalyticsTests(unittest.TestCase):
    def test_private_payoff_and_option_methods_remain_exact_legacy_copies(self):
        root=Path(__file__).resolve().parents[1]/"portefeuille_viewer"
        old=ast.parse((root/"ui_logica/single_asset_analyse_tab_logica.py").read_text(encoding="utf-8"))
        new=ast.parse((root/"services/asset_dashboard_logic.py").read_text(encoding="utf-8").replace("self.store", "SNAPSHOT_STORE"))
        old_cls=next(n for n in old.body if isinstance(n,ast.ClassDef) and n.name=="SingleAssetAnalyseLogic")
        new_cls=next(n for n in new.body if isinstance(n,ast.ClassDef))
        methods={n.name:n for n in old_cls.body if isinstance(n,ast.FunctionDef)}
        for method in new_cls.body:
            # History intentionally fixes the legacy untyped-empty-frame join bug;
            # its behaviour is covered by regression tests below.
            if isinstance(method,ast.FunctionDef) and method.name not in {"__init__","_filter_broker_snapshot","load_asset_history"}:
                self.assertEqual(ast.dump(method), ast.dump(methods[method.name]),method.name)

    def test_payoff_totals_fees_currency_and_option_kinks(self):
        store,payload,settings=fixture();result=calculate_analytics(store,payload,settings)
        p=result["payoff"]
        self.assertEqual(p["steps"][8],100.)
        self.assertAlmostEqual(p["values"][8][8],-6/1.2)
        self.assertAlmostEqual(p["values"][0][8],0.)
        self.assertAlmostEqual(p["values"][3][8],40/1.2)
        self.assertAlmostEqual(p["values"][2][8],300/1.2)
        self.assertAlmostEqual(p["values"][9][8],(40+300+150+20-6)/1.2)
        self.assertLess(p["values"][2][0],p["values"][2][8])
        self.assertLess(p["values"][2][-1],p["values"][2][8])

    def test_history_matches_legacy_alignment_and_currency(self):
        store,payload,settings=fixture();result=calculate_analytics(store,payload,settings)
        history=result["history"]
        self.assertEqual([r["result"] for r in history],[100.,100.,200.])
        self.assertEqual([r["quantity"] for r in history],[8.,8.,108.])
        self.assertEqual(history[0]["open"],99.)
        self.assertIsNone(history[2]["open"])
        self.assertEqual(history[2]["close"],104.)

    def test_price_history_without_user_result_rows_has_typed_join_keys(self):
        for mode in ("missing", "empty", "other_asset"):
            with self.subTest(mode=mode):
                store,payload,settings=fixture()
                if mode=="missing":
                    store.repository_snapshot_per_dag_asset_result_v2=None
                elif mode=="empty":
                    store.repository_snapshot_per_dag_asset_result_v2=pl.DataFrame()
                else:
                    store.repository_snapshot_per_dag_asset_result_v2=store.repository_snapshot_per_dag_asset_result_v2.with_columns(pl.lit("OTHER").alias("asset_rollup"))
                result=calculate_analytics(store,payload,settings)
                self.assertEqual(len(result["history"]),3)
                self.assertEqual([r["result"] for r in result["history"]],[0.,0.,0.])
                self.assertEqual(len(result["payoff"]["steps"]),17)

    def test_snapshot_capture_and_history_cache_invalidation(self):
        store,payload,settings=fixture();cache={};frozen,_=capture_analytics(store)
        first=calculate_analytics(frozen,payload,settings,cache)
        store.repository_snapshot_historical_ohlcv=store.repository_snapshot_historical_ohlcv.with_columns(pl.lit(200.).alias("close_price"))
        self.assertEqual(calculate_analytics(frozen,payload,settings,cache)["history"], first["history"])
        updated,_=capture_analytics(store)
        self.assertEqual(calculate_analytics(updated,payload,settings,cache)["history"][0]["close"],200.)

    def test_missing_quote_uses_actual_historical_close(self):
        store,payload,settings=fixture();payload["summary"]={}
        result=calculate_analytics(store,payload,settings)
        self.assertEqual(result["payoff"]["price"],104.)
        self.assertEqual(result["payoff"]["price_source"],"laatste historische slotkoers")

    def test_asset_price_precision_is_carried_to_the_chart_and_table(self):
        store,payload,settings=fixture()
        payload["summary"]["koers"]=1.0725
        settings.update(step_pct=.5,decimals=4)
        p=calculate_analytics(store,payload,settings)["payoff"]
        self.assertEqual(p["decimals"],4)
        self.assertEqual(p["steps"][8],1.0725)

    def test_zero_step_matches_legacy_one_percent_fallback(self):
        store,payload,settings=fixture();settings["step_pct"]=0.
        p=calculate_analytics(store,payload,settings)["payoff"]
        self.assertEqual(p["steps"],[float(v) for v in range(92,109)])

    def test_live_result_is_not_converted_twice_and_is_not_a_fake_candle(self):
        store,payload,settings=fixture()
        today=date.today()
        settings["end"]=today.isoformat()
        payload["summary"].update(koers=105., totaal_inc_fee=123.)
        store.snapshot_portfolio_value_total_combined_put=pl.DataFrame({
            "asset_rollup":["AAPL"], "aand_aantal_bezit":[8.], "aantal_sprinters":[0.],
            "opt_aantal_ITM_put":[-100.], "opt_aantal_OTM_put":[0.],
        })
        result=calculate_analytics(store,payload,settings)
        latest=result["history"][-1]
        self.assertEqual(latest["date"],today.isoformat())
        self.assertEqual(latest["result"],123.)
        self.assertEqual(latest["quantity"],108.)
        self.assertIsNone(latest["open"])
        self.assertIsNone(latest["high"])
        self.assertIsNone(latest["low"])

    def test_history_period_does_not_append_today_outside_selection(self):
        store,payload,settings=fixture()
        settings.update(start="2026-01-06",end="2026-01-07")
        payload["summary"]["totaal_inc_fee"]=123.
        result=calculate_analytics(store,payload,settings)
        self.assertEqual([r["date"] for r in result["history"]],["2026-01-06","2026-01-07"])


if __name__=="__main__":unittest.main()
