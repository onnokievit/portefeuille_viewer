"""Database routing checks using synthetic data only; never open configured databases.

Run from the repository root: python -m unittest discover -s devtools -p test_stockdata_routing.py
The Access checks create their own temporary databases using the installed DAO engine.
"""
from contextlib import ExitStack, redirect_stdout
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
import base64
import importlib
import io
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import polars as pl
from polars.testing import assert_frame_equal
import pyodbc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "state_engine"))
import common
import open_aandelen_state_v2 as equities
import open_opties_state_v2 as options
import open_sprinters_state_v2 as sprinters
import per_dag_asset_result_v2 as results


class RoutingTests(unittest.TestCase):
    def test_state_engine_workflows_route_sources_and_writes_separately(self):
        shared = {
            equities: ("load_price_history", "load_stock_splits"),
            options: ("load_price_history", "load_stock_splits", "load_option_price_factor_overrides"),
            sprinters: ("load_price_history", "load_sprinter_reference", "load_asset_quote_unit"),
            results: (),
        }
        pipelines = {
            equities: ("drop_stale_temp_stage_tables", "load_equity_transactions", "apply_split_price_correction",
                       "build_state_intervals", "materialize_daily_rows", "aggregate_daily_transactions",
                       "attach_effective_close", "compute_valuation", "normalize_for_access", "insert_rows"),
            options: ("load_option_transactions", "build_open_series", "materialize_daily_open_rows",
                      "attach_raw_prices", "compute_split_factor", "attach_override_factor",
                      "compute_effective_prices_and_valuation", "normalize_for_access", "insert_v2_rows"),
            sprinters: ("drop_stale_temp_stage_tables", "load_sprinter_transactions", "build_state_intervals",
                        "materialize_daily_rows", "attach_effective_close", "compute_sprinter_values",
                        "normalize_for_access", "insert_rows"),
            results: ("drop_stale_temp_stage_tables", "ensure_asset_result_v2_schema", "load_aandelen_component",
                      "load_opties_component", "load_sprinters_component", "load_dividend_component",
                      "load_aantal_component", "build_final", "insert_rows"),
        }
        args = SimpleNamespace(db="user.accdb", stock_db="stock.accdb", insert_mode="executemany",
                               validate_v1=False, debug_uniek_id=None, to_date="2026-01-20")
        for module in shared:
            with self.subTest(module=module.__name__), ExitStack() as stack:
                user, stock = object(), object()
                for name, connection in (("get_connection", user), ("get_stockdata_connection", stock)):
                    boundary = stack.enter_context(patch.object(module, name))
                    boundary.return_value.__enter__.return_value = connection
                stack.enter_context(patch.object(module, "parse_args", return_value=args))
                scope = stack.enter_context(patch.object(module, "resolve_scope"))
                mocks = {}
                for name in (*pipelines[module], *shared[module], "delete_target_range", "update_state_engine_status"):
                    mocks[name] = stack.enter_context(patch.object(module, name))
                    mocks[name].return_value.is_empty.return_value = False
                with redirect_stdout(io.StringIO()):
                    module.main()
                for name in shared[module]:
                    self.assertIs(mocks[name].call_args.args[0], stock)
                for name in pipelines[module]:
                    if name.startswith(("load_", "insert_", "ensure_", "drop_")):
                        self.assertIs(mocks[name].call_args.args[0], user)
                for name in ("delete_target_range", "update_state_engine_status"):
                    self.assertIs(mocks[name].call_args.args[0], user)
                if module is results:
                    self.assertEqual(scope.call_args.args, (args, user, stock))
                    self.assertIs(mocks["load_aantal_component"].call_args.args[1], stock)

    def test_stock_path_is_required(self):
        with patch.object(common.pyodbc, "connect") as connect:
            for value in (None, "", " "):
                with self.assertRaises(ValueError):
                    common.get_stockdata_connection(value)
            connect.assert_not_called()

    def test_app_commands_keep_user_and_stock_paths_separate(self):
        # Block all ODBC during app imports too; config values never point at real DBs.
        with patch.object(pyodbc, "connect", side_effect=AssertionError("Unexpected database access")), \
             patch("portefeuille_viewer.config.get_databases", return_value={}), \
             patch("portefeuille_viewer.config.get_default_database", return_value=None):
            runner_module = importlib.import_module("portefeuille_viewer.services.state_engine_runner")
        repo = runner_module.repository
        with patch.object(repo, "db_path", "test-user.accdb"), \
             patch.object(repo, "get_stockdata_db_path", return_value="test-stock.accdb"):
            for name in ("_build_options_command", "_build_aandelen_command",
                         "_build_sprinters_command", "_build_asset_result_v2_command"):
                _, args = getattr(runner_module.StateEngineRunner, name)(None, {})
                self.assertEqual(args[args.index("--db") + 1], "test-user.accdb")
                self.assertEqual(args[args.index("--stock-db") + 1], "test-stock.accdb")

    def test_price_cache_survives_user_switch_and_tracks_stock_path(self):
        from portefeuille_viewer.data import repository
        from portefeuille_viewer.data.asset_last_price_store import AssetLastPriceStore
        store = AssetLastPriceStore()
        with patch.object(repository, "get_stockdata_db_path", return_value="stock-a.accdb") as path, \
             patch.object(store, "_read_from_db", return_value={}) as read, \
             patch.object(repository, "db_path", "user-a.accdb"):
            store.load_from_db(publish_snapshot=False)
            repository.db_path = "user-b.accdb"
            store.load_from_db(publish_snapshot=False)
            self.assertEqual(read.call_count, 1)
            path.return_value = "stock-b.accdb"
            store.load_from_db(publish_snapshot=False)
            self.assertEqual(read.call_count, 2)

    def test_last_prices_read_and_write_never_use_user_connection(self):
        from portefeuille_viewer.data import repository
        from portefeuille_viewer.data.asset_last_price_store import AssetLastPriceStore
        connection = MagicMock()
        connection.cursor.return_value.fetchall.return_value = [("ABC", "USD", 12.5)]
        connection.cursor.return_value.rowcount = 0
        with patch.object(repository, "get_connection", side_effect=AssertionError("User DB accessed")), \
             patch.object(repository, "get_stockdata_connection") as stock:
            stock.return_value.__enter__.return_value = connection
            self.assertEqual(AssetLastPriceStore._read_from_db(), {("ABC", "USD"): 12.5})
            AssetLastPriceStore._write_to_db({("ABC", "USD"): 13.5})
            sql = [call.args[0] for call in connection.cursor.return_value.execute.call_args_list]
            self.assertTrue(any(s.startswith("UPDATE asset_last_prices") for s in sql))
            self.assertTrue(any(s.startswith("INSERT INTO asset_last_prices") for s in sql))
            connection.commit.assert_called_once()

    def test_result_scope_uses_stock_prices_and_user_state(self):
        user, stock = object(), object()
        args = SimpleNamespace(to_date="2026-01-20", mode="full", asset_rollups=None)
        with patch.object(results, "clamp_to_available_price_date", return_value=date(2026, 1, 15)) as clamp, \
             patch.object(results, "fetch_min_state_date", return_value=date(2026, 1, 1)) as minimum:
            scope = results.resolve_scope(args, user, stock)
            self.assertIs(clamp.call_args.args[0], stock)
            self.assertTrue(all(call.args[0] is user for call in minimum.call_args_list))
            self.assertEqual(scope.to_date, date(2026, 1, 15))

    def test_result_quantities_read_splits_from_stock_and_positions_from_user(self):
        user, stock = object(), object()
        scope = results.RebuildScope(assets=None, from_date=date(2026, 1, 1),
                                     to_date=date(2026, 1, 20), mode="full")
        with patch.object(results, "load_stock_splits", return_value=pl.DataFrame()) as splits, \
             patch.object(results.pl, "read_database", return_value=pl.DataFrame()) as read:
            results.load_aantal_component(user, stock, scope)
            splits.assert_called_once_with(stock, scope)
            self.assertGreater(read.call_count, 0)
            self.assertTrue(all(call.args[1] is user for call in read.call_args_list))


class AccessHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="pv-stock-routing-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.stock_path = Path(cls.temp.name) / "synthetic-stock.accdb"
        cls.user_path = Path(cls.temp.name) / "synthetic-user.accdb"
        # Paths are generated by tempfile, escaped as PowerShell string literals.
        stock = str(cls.stock_path).replace("'", "''")
        user = str(cls.user_path).replace("'", "''")
        script = f"""
$ErrorActionPreference = 'Stop'
$engine = New-Object -ComObject DAO.DBEngine.120
$db = $engine.CreateDatabase('{stock}', ';LANGID=0x0409;CP=1252;COUNTRY=0', 128)
$db.Execute('CREATE TABLE asset_rollup_data (ib_symbol TEXT(50), asset_rollup TEXT(50))')
$db.Execute('CREATE TABLE historical_data_correct (symbol TEXT(50), asset_rollup TEXT(50), datum DATETIME, [close] DOUBLE, multiplier_close_price DOUBLE)')
$query = $db.CreateQueryDef('hist_data_per_asset_symbol', 'SELECT h.symbol, h.datum, h.[close], a.asset_rollup, h.multiplier_close_price FROM asset_rollup_data AS a INNER JOIN historical_data_correct AS h ON a.ib_symbol = h.symbol')
$query.Close()
$db.Close()
$db = $engine.CreateDatabase('{user}', ';LANGID=0x0409;CP=1252;COUNTRY=0', 128)
$db.Execute('CREATE TABLE user_marker (id LONG)')
$db.Close()
"""
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                       check=True, capture_output=True, text=True, timeout=30)
        cls.conn = common.get_stockdata_connection(str(cls.stock_path))
        cls.addClassCleanup(cls.conn.close)
        cursor = cls.conn.cursor()
        for symbol, asset in [("ABC", "MAIN"), ("ABC", "ALIAS"), ("XYZ", "OTHER")]:
            cursor.execute("INSERT INTO asset_rollup_data VALUES (?, ?)", symbol, asset)
        for symbol, day, price in [("ABC", 1, 10.0), ("ABC", 9, 11.0), ("ABC", 12, None),
                                   ("ABC", 20, 15.0), ("XYZ", 19, 20.0), ("UNMAPPED", 19, 99.0)]:
            cursor.execute("INSERT INTO historical_data_correct VALUES (?, ?, ?, ?, ?)",
                           symbol, "DENORMALIZED", datetime(2026, 1, day), price, 1.0)
        cls.conn.commit()

    def test_all_history_loaders_match_access_query_including_anchor_and_aliases(self):
        for module in (equities, options, sprinters):
            for assets in (None, ["MAIN"], ["MAIN", "ALIAS"], ["ABSENT"]):
                with self.subTest(module=module.__name__, assets=assets):
                    scope = module.RebuildScope(assets=assets, from_date=date(2026, 1, 20),
                                               to_date=date(2026, 1, 20), mode="full")
                    with patch.object(module, "PRICE_HISTORY_SOURCE", "hist_data_per_asset_symbol"):
                        expected = module.load_price_history(self.conn, scope)
                    actual = module.load_price_history(self.conn, scope)
                    assert_frame_equal(actual, expected)
                    self.assertNotIn("DENORMALIZED", actual.get_column("asset_rollup").to_list())

    def test_stock_price_date_without_any_user_links(self):
        # The user fixture has no STOCKDATA table links or saved history queries.
        self.assertEqual(results.fetch_max_price_date(self.conn, ["DENORMALIZED"]), date(2026, 1, 20))
        user = common.get_connection(str(self.user_path))
        try:
            self.assertEqual([r.table_name for r in user.cursor().tables(tableType="TABLE")], ["user_marker"])
        finally:
            user.close()


if __name__ == "__main__":
    unittest.main()
