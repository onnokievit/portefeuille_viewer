# Inventaris databaseverbindingen Portefeuille Viewer 1.6

Gegenereerd met `python -m devtools.inventory_database_connections`. Statische AST-inventaris; tests en graphify-uitvoer uitgesloten. Dit zijn aanroepplaatsen, geen aantallen verbindingen per minuut.

Totaal: 211 aanroepplaatsen in 62 bestanden.

Categorieën: STOCKDATA: 69, factory/direct: controleren: 94, userdatabase: 48.

| Bestand | Regel | Functie | Aanroep | Route |
|---|---:|---|---|---|
| `beta_matrix_viewer/beta_matrix_viewer.py` | 84 | `_connect` | `repository.get_stockdata_connection` | STOCKDATA |
| `beta_matrix_viewer/beta_matrix_viewer.py` | 88 | `_load_source_data` | `self._connect` | factory/direct: controleren |
| `beta_matrix_viewer/index_regression_viewer.py` | 95 | `_connect` | `repository.get_stockdata_connection` | STOCKDATA |
| `beta_matrix_viewer/index_regression_viewer.py` | 99 | `_load_source_data` | `self._connect` | factory/direct: controleren |
| `dividend_tool/dividend_tool_codex.py` | 89 | `get_connection` | `pyodbc.connect` | factory/direct: controleren |
| `dividend_tool/dividend_tool_codex.py` | 107 | `load_assets` | `get_connection` | factory/direct: controleren |
| `dividend_tool/dividend_tool_codex.py` | 217 | `reset_earnings_rows` | `get_connection` | factory/direct: controleren |
| `dividend_tool/dividend_tool_codex.py` | 226 | `upsert_earnings_row` | `get_connection` | factory/direct: controleren |
| `dividend_tool/dividend_viewer.py` | 88 | `_load_assets` | `pyodbc.connect` | factory/direct: controleren |
| `dividend_tool/earnings_dates_cli.py` | 56 | `connect_access` | `pyodbc.connect` | factory/direct: controleren |
| `dividend_tool/earnings_dates_cli.py` | 74 | `load_assets` | `connect_access` | factory/direct: controleren |
| `dividend_tool/ibkr_wsh_earnings_cli.py` | 47 | `connect_access` | `pyodbc.connect` | factory/direct: controleren |
| `dividend_tool/ibkr_wsh_earnings_cli.py` | 73 | `lookup_asset` | `connect_access` | factory/direct: controleren |
| `margin_efficiency_tool.py` | 94 | `_connect_access_readonly` | `pyodbc.connect` | factory/direct: controleren |
| `margin_efficiency_tool.py` | 100 | `_table_exists` | `_connect_access_readonly` | factory/direct: controleren |
| `margin_efficiency_tool.py` | 137 | `load_open_option_positions` | `_connect_access_readonly` | factory/direct: controleren |
| `margin_efficiency_tool.py` | 191 | `load_asset_map` | `_connect_access_readonly` | factory/direct: controleren |
| `margin_efficiency_tool.py` | 220 | `load_spot_quotes` | `_connect_access_readonly` | factory/direct: controleren |
| `margin_efficiency_tool.py` | 262 | `load_option_market_quotes` | `_connect_access_readonly` | factory/direct: controleren |
| `poc_volatility_dashboard/data/db_volatility_source.py` | 29 | `connect_access` | `pyodbc.connect` | factory/direct: controleren |
| `poc_volatility_dashboard/data/db_volatility_source.py` | 40 | `load_assets` | `connect_access` | factory/direct: controleren |
| `poc_volatility_dashboard/data/db_volatility_source.py` | 65 | `load_volatility_history` | `connect_access` | factory/direct: controleren |
| `portefeuille_viewer/data/account_daily_balance_repository.py` | 35 | `_get_connection_with_retry` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/account_daily_balance_repository.py` | 47 | `ensure_account_daily_balances_schema` | `_get_connection_with_retry` | factory/direct: controleren |
| `portefeuille_viewer/data/account_daily_balance_repository.py` | 102 | `list_account_daily_balances` | `_get_connection_with_retry` | factory/direct: controleren |
| `portefeuille_viewer/data/account_daily_balance_repository.py` | 165 | `upsert_account_daily_balance` | `_get_connection_with_retry` | factory/direct: controleren |
| `portefeuille_viewer/data/account_daily_balance_repository.py` | 232 | `delete_account_daily_balance` | `_get_connection_with_retry` | factory/direct: controleren |
| `portefeuille_viewer/data/asset_last_price_store.py` | 43 | `_read_from_db` | `repository.get_stockdata_connection` | STOCKDATA |
| `portefeuille_viewer/data/asset_last_price_store.py` | 61 | `_write_to_db` | `repository.get_stockdata_connection` | STOCKDATA |
| `portefeuille_viewer/data/asset_rollup_repository.py` | 46 | `_get_connection_with_retry` | `data_repository.get_stockdata_connection` | STOCKDATA |
| `portefeuille_viewer/data/asset_rollup_repository.py` | 59 | `list_asset_rollup_columns` | `_get_connection_with_retry` | factory/direct: controleren |
| `portefeuille_viewer/data/asset_rollup_repository.py` | 120 | `list_asset_rollup_rows` | `_get_connection_with_retry` | factory/direct: controleren |
| `portefeuille_viewer/data/asset_rollup_repository.py` | 170 | `upsert_asset_rollup_row` | `_get_connection_with_retry` | factory/direct: controleren |
| `portefeuille_viewer/data/asset_rollup_repository.py` | 199 | `delete_asset_rollup_row` | `_get_connection_with_retry` | factory/direct: controleren |
| `portefeuille_viewer/data/beta_shift_scenario_repository.py` | 43 | `ensure_beta_shift_scenario_schema` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/beta_shift_scenario_repository.py` | 96 | `list_beta_shift_scenarios` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/beta_shift_scenario_repository.py` | 114 | `load_beta_shift_scenarios_cache_from_db` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/beta_shift_scenario_repository.py` | 158 | `create_beta_shift_scenario` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/beta_shift_scenario_repository.py` | 191 | `rename_beta_shift_scenario` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/beta_shift_scenario_repository.py` | 208 | `delete_beta_shift_scenario` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/beta_shift_scenario_repository.py` | 258 | `save_beta_shift_scenario_content` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/cash_management_repository.py` | 35 | `_get_connection_with_retry` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/cash_management_repository.py` | 47 | `ensure_cash_management_schema` | `_get_connection_with_retry` | factory/direct: controleren |
| `portefeuille_viewer/data/cash_management_repository.py` | 108 | `list_cash_management_entries` | `_get_connection_with_retry` | factory/direct: controleren |
| `portefeuille_viewer/data/cash_management_repository.py` | 188 | `upsert_cash_management_entry` | `_get_connection_with_retry` | factory/direct: controleren |
| `portefeuille_viewer/data/cash_management_repository.py` | 263 | `delete_cash_management_entry` | `_get_connection_with_retry` | factory/direct: controleren |
| `portefeuille_viewer/data/dividend_calendar_repository.py` | 32 | `_connect` | `repository.get_stockdata_connection` | STOCKDATA |
| `portefeuille_viewer/data/dividend_calendar_repository.py` | 36 | `ensure_dividend_calendar_schema` | `_connect` | factory/direct: controleren |
| `portefeuille_viewer/data/dividend_calendar_repository.py` | 108 | `replace_current_and_append_history` | `_connect` | factory/direct: controleren |
| `portefeuille_viewer/data/dividend_calendar_repository.py` | 168 | `load_asset_universe` | `_connect` | factory/direct: controleren |
| `portefeuille_viewer/data/financial_data_repository.py` | 18 | `schema_ready` | `connect_stockdata` | STOCKDATA |
| `portefeuille_viewer/data/financial_data_repository.py` | 30 | `load_assets` | `connect_stockdata` | STOCKDATA |
| `portefeuille_viewer/data/financial_data_repository.py` | 44 | `facts_for` | `connect_stockdata` | STOCKDATA |
| `portefeuille_viewer/data/financial_data_repository.py` | 55 | `fetch_states` | `connect_stockdata` | STOCKDATA |
| `portefeuille_viewer/data/financial_data_repository.py` | 73 | `store_result` | `connect_stockdata` | STOCKDATA |
| `portefeuille_viewer/data/option_reference_repository.py` | 46 | `_get_connection_with_retry` | `data_repository.get_stockdata_connection` | STOCKDATA |
| `portefeuille_viewer/data/option_reference_repository.py` | 59 | `list_option_reference_columns` | `_get_connection_with_retry` | factory/direct: controleren |
| `portefeuille_viewer/data/option_reference_repository.py` | 118 | `list_option_reference_rows` | `_get_connection_with_retry` | factory/direct: controleren |
| `portefeuille_viewer/data/option_reference_repository.py` | 172 | `upsert_option_reference_row` | `_get_connection_with_retry` | factory/direct: controleren |
| `portefeuille_viewer/data/option_reference_repository.py` | 201 | `delete_option_reference_row` | `_get_connection_with_retry` | factory/direct: controleren |
| `portefeuille_viewer/data/repository.py` | 73 | `switch_database` | `pyodbc.connect` | factory/direct: controleren |
| `portefeuille_viewer/data/repository.py` | 117 | `load_asset_rollup_data` | `get_stockdata_connection` | STOCKDATA |
| `portefeuille_viewer/data/repository.py` | 126 | `load_historical_ohlcv_snapshot` | `get_stockdata_connection` | STOCKDATA |
| `portefeuille_viewer/data/repository.py` | 185 | `load_asset_driver_beta_snapshot` | `get_stockdata_connection` | STOCKDATA |
| `portefeuille_viewer/data/repository.py` | 259 | `load_asset_dividend_calendar_snapshot` | `get_stockdata_connection` | STOCKDATA |
| `portefeuille_viewer/data/repository.py` | 316 | `load_per_dag_asset_result_v2_snapshot` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/repository.py` | 448 | `load_sprinter_referentie_data` | `get_stockdata_connection` | STOCKDATA |
| `portefeuille_viewer/data/repository.py` | 461 | `load_optie_referentie_data` | `get_stockdata_connection` | STOCKDATA |
| `portefeuille_viewer/data/repository.py` | 475 | `load_dividend_data` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/repository.py` | 511 | `load_alle_transacties` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/repository.py` | 885 | `get_connection` | `pyodbc.connect` | factory/direct: controleren |
| `portefeuille_viewer/data/repository.py` | 890 | `get_stockdata_connection` | `connect_stockdata` | STOCKDATA |
| `portefeuille_viewer/data/repository.py` | 1029 | `insert_transactions_atomic` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/repository.py` | 1071 | `delete_transactions_by_order_id` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/repository.py` | 1090 | `delete_transactions_by_ids` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/repository.py` | 1129 | `get_distinct_values` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/repository.py` | 1259 | `fetch_records_page` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/repository.py` | 1284 | `load_brokers` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/repository.py` | 1305 | `_load_stock_reference_lists` | `get_stockdata_connection` | STOCKDATA |
| `portefeuille_viewer/data/repository.py` | 1360 | `update_transactions_atomic` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/repository.py` | 1525 | `load_open_optie_comments_cache` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/repository.py` | 1706 | `flush_dirty_open_optie_comments_to_db` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/repository.py` | 1764 | `get_next_order_id` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/repository.py` | 1774 | `get_next_order_item_no` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/shared_database.py` | 86 | `__init__` | `pyodbc.connect` | factory/direct: controleren |
| `portefeuille_viewer/data/shared_database.py` | 216 | `read_versions` | `connect_stockdata` | STOCKDATA |
| `portefeuille_viewer/data/stockdata_worker.py` | 69 | `borrow` | `pyodbc.connect` | factory/direct: controleren |
| `portefeuille_viewer/data/test_order_repository.py` | 68 | `ensure_test_order_scenario_schema` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/test_order_repository.py` | 176 | `list_test_order_scenarios` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/test_order_repository.py` | 193 | `load_test_order_scenarios_cache_from_db` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/test_order_repository.py` | 353 | `save_test_order_scenario` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/test_order_repository.py` | 401 | `get_test_order_scenario_content_map` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/test_order_repository.py` | 478 | `flush_dirty_test_order_scenarios_to_db` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/test_order_repository.py` | 567 | `get_test_orders` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/test_order_repository.py` | 648 | `flush_dirty_test_orders_to_db` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/test_order_repository.py` | 734 | `insert_test_order` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/test_order_repository.py` | 750 | `update_test_order` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/test_order_repository.py` | 756 | `delete_test_order` | `get_connection` | userdatabase |
| `portefeuille_viewer/data/update_run_repository.py` | 13 | `_connect` | `repository.get_stockdata_connection` | STOCKDATA |
| `portefeuille_viewer/data/update_run_repository.py` | 17 | `ensure_update_runs_schema` | `_connect` | factory/direct: controleren |
| `portefeuille_viewer/data/update_run_repository.py` | 58 | `has_successful_run_today` | `_connect` | factory/direct: controleren |
| `portefeuille_viewer/data/update_run_repository.py` | 83 | `start_update_run` | `_connect` | factory/direct: controleren |
| `portefeuille_viewer/data/update_run_repository.py` | 119 | `finish_update_run` | `_connect` | factory/direct: controleren |
| `portefeuille_viewer/data/update_run_repository.py` | 162 | `log_update_run_once` | `_connect` | factory/direct: controleren |
| `portefeuille_viewer/option_workbench/asset_source.py` | 15 | `connect_access` | `connect_stockdata` | STOCKDATA |
| `portefeuille_viewer/option_workbench/asset_source.py` | 39 | `load_scan_assets` | `connect_access` | factory/direct: controleren |
| `portefeuille_viewer/option_workbench/chain_run_repository.py` | 15 | `ensure_schema` | `connect_access` | factory/direct: controleren |
| `portefeuille_viewer/option_workbench/chain_run_repository.py` | 24 | `start_run` | `connect_access` | factory/direct: controleren |
| `portefeuille_viewer/option_workbench/chain_run_repository.py` | 52 | `log_asset` | `connect_access` | factory/direct: controleren |
| `portefeuille_viewer/option_workbench/chain_run_repository.py` | 85 | `finish_run` | `connect_access` | factory/direct: controleren |
| `portefeuille_viewer/option_workbench/db_access.py` | 13 | `connect_access` | `connect_stockdata` | STOCKDATA |
| `portefeuille_viewer/option_workbench/db_access.py` | 37 | `load_assets` | `connect_access` | factory/direct: controleren |
| `portefeuille_viewer/option_workbench/db_access.py` | 73 | `load_latest_spot` | `connect_access` | factory/direct: controleren |
| `portefeuille_viewer/option_workbench/spot_resolver.py` | 183 | `load_asset_last_price` | `connect_access` | factory/direct: controleren |
| `portefeuille_viewer/services/asset_display_settings.py` | 12 | `_connect_stockdb` | `repository.get_stockdata_connection` | STOCKDATA |
| `portefeuille_viewer/services/asset_display_settings.py` | 23 | `load_price_decimals_map` | `_connect_stockdb` | STOCKDATA |
| `portefeuille_viewer/services/asset_indicator_change_service.py` | 106 | `load_history_rows` | `repository.get_stockdata_connection` | STOCKDATA |
| `portefeuille_viewer/services/asset_indicator_service.py` | 1029 | `_persist_signal_history` | `repository.get_stockdata_connection` | STOCKDATA |
| `portefeuille_viewer/services/beta_snapshot_service.py` | 35 | `rebuild_asset_driver_beta_snapshot` | `repository.get_stockdata_connection` | STOCKDATA |
| `portefeuille_viewer/services/cash_management_chart_service.py` | 40 | `_load_cash_entries_df` | `get_connection` | userdatabase |
| `portefeuille_viewer/services/cash_management_chart_service.py` | 73 | `_load_daily_balances_df` | `get_connection` | userdatabase |
| `portefeuille_viewer/services/db_migration_service.py` | 53 | `migrate_db` | `self._connect` | factory/direct: controleren |
| `portefeuille_viewer/services/db_migration_service.py` | 67 | `get_db_version` | `self._connect` | factory/direct: controleren |
| `portefeuille_viewer/services/db_migration_service.py` | 74 | `_connect` | `pyodbc.connect` | factory/direct: controleren |
| `portefeuille_viewer/services/option_timevalue_service.py` | 322 | `_connect_stockdb` | `repository.get_stockdata_connection` | STOCKDATA |
| `portefeuille_viewer/services/option_timevalue_service.py` | 450 | `apply_manual_resolution` | `self._connect_stockdb` | STOCKDATA |
| `portefeuille_viewer/services/option_timevalue_service.py` | 588 | `_upsert_master_and_resolve` | `self._connect_stockdb` | STOCKDATA |
| `portefeuille_viewer/services/option_timevalue_service.py` | 725 | `_upsert_master_and_resolve` | `self._connect_stockdb` | STOCKDATA |
| `portefeuille_viewer/services/option_timevalue_service.py` | 811 | `_resolve_contracts` | `self._connect_stockdb` | STOCKDATA |
| `portefeuille_viewer/services/price_feed.py` | 1022 | `_connect_option_last_prices_db` | `repository.get_stockdata_connection` | STOCKDATA |
| `portefeuille_viewer/services/price_feed.py` | 1089 | `_load_option_last_prices_from_db` | `self._connect_option_last_prices_db` | STOCKDATA |
| `portefeuille_viewer/services/price_feed.py` | 1163 | `_cleanup_expired_option_last_prices_if_due` | `self._connect_option_last_prices_db` | STOCKDATA |
| `portefeuille_viewer/services/price_feed.py` | 1207 | `_save_option_last_prices_to_db_sync` | `self._connect_option_last_prices_db` | STOCKDATA |
| `portefeuille_viewer/services/state_engine_runner.py` | 106 | `get_pending_order_rebuild_summary` | `pyodbc.connect` | factory/direct: controleren |
| `portefeuille_viewer/services/state_engine_runner.py` | 229 | `_ensure_state_rebuild_queue_table` | `pyodbc.connect` | factory/direct: controleren |
| `portefeuille_viewer/services/state_engine_runner.py` | 281 | `_ensure_state_runs_table` | `pyodbc.connect` | factory/direct: controleren |
| `portefeuille_viewer/services/state_engine_runner.py` | 328 | `_enqueue_order_rebuild_payload` | `pyodbc.connect` | factory/direct: controleren |
| `portefeuille_viewer/services/state_engine_runner.py` | 389 | `_claim_pending_order_rebuild_bundle` | `pyodbc.connect` | factory/direct: controleren |
| `portefeuille_viewer/services/state_engine_runner.py` | 444 | `_recover_state_from_db` | `pyodbc.connect` | factory/direct: controleren |
| `portefeuille_viewer/services/state_engine_runner.py` | 537 | `_get_today_startup_price_fetch_start_date` | `repository.get_stockdata_connection` | STOCKDATA |
| `portefeuille_viewer/services/state_engine_runner.py` | 723 | `_has_successful_startup_daily_catchup_today` | `pyodbc.connect` | factory/direct: controleren |
| `portefeuille_viewer/services/state_engine_runner.py` | 772 | `_get_assets_by_type` | `pyodbc.connect` | factory/direct: controleren |
| `portefeuille_viewer/services/state_engine_runner.py` | 798 | `_get_open_assets_by_type` | `pyodbc.connect` | factory/direct: controleren |
| `portefeuille_viewer/services/state_engine_runner.py` | 816 | `_get_shared_last_price_dates` | `repository.get_stockdata_connection` | STOCKDATA |
| `portefeuille_viewer/services/state_engine_runner.py` | 838 | `_get_local_state_status` | `pyodbc.connect` | factory/direct: controleren |
| `portefeuille_viewer/services/state_engine_runner.py` | 864 | `_get_local_v2_max_dates` | `pyodbc.connect` | factory/direct: controleren |
| `portefeuille_viewer/services/state_engine_runner.py` | 885 | `_get_first_tx_date` | `pyodbc.connect` | factory/direct: controleren |
| `portefeuille_viewer/services/state_engine_runner.py` | 1163 | `_start_run_journal` | `pyodbc.connect` | factory/direct: controleren |
| `portefeuille_viewer/services/state_engine_runner.py` | 1189 | `_finish_run_journal` | `pyodbc.connect` | factory/direct: controleren |
| `portefeuille_viewer/services/state_engine_runner.py` | 1211 | `_finalize_queue_after_run` | `pyodbc.connect` | factory/direct: controleren |
| `portefeuille_viewer/services/year_result_vs_indices_service.py` | 87 | `list_index_asset_rollups` | `get_stockdata_connection` | STOCKDATA |
| `portefeuille_viewer/services/year_result_vs_indices_service.py` | 298 | `_load_index_series` | `get_stockdata_connection` | STOCKDATA |
| `portefeuille_viewer/ui_logica/optie_eind_tab_logica.py` | 194 | `_collect_test_account_scope` | `pyodbc.connect` | factory/direct: controleren |
| `portefeuille_viewer/ui_logica/optie_eind_tab_logica.py` | 252 | `move_records_to_productie` | `pyodbc.connect` | factory/direct: controleren |
| `portefeuille_viewer/ui_logica/optie_eind_tab_logica.py` | 391 | `clear_test_account` | `pyodbc.connect` | factory/direct: controleren |
| `portefeuille_viewer/ui_logica/optie_eind_tab_logica.py` | 845 | `add_records_to_db` | `pyodbc.connect` | factory/direct: controleren |
| `portefeuille_viewer/ui_logica/orders_tab_widget.py` | 869 | `_update_transaction_in_snapshot` | `get_connection` | userdatabase |
| `portefeuille_viewer/ui_logica/orders_tab_widget.py` | 916 | `_fetch_transactions_from_db_by_ids` | `get_connection` | userdatabase |
| `portefeuille_viewer/ui_logica/orders_tab_widget.py` | 924 | `_append_transactions_to_snapshot_by_ids` | `get_connection` | userdatabase |
| `portefeuille_viewer/ui_logica/orders_tab_widget.py` | 1147 | `on_table_select` | `get_connection` | userdatabase |
| `portefeuille_viewer/ui_logica/orders_tab_widget.py` | 1164 | `on_table_select` | `get_connection` | userdatabase |
| `portefeuille_viewer/ui_logica/single_asset_analyse_tab_logica.py` | 4454 | `_connect_stockdb` | `get_stockdata_connection` | STOCKDATA |
| `portefeuille_viewer/ui_logica/single_asset_analyse_tab_logica.py` | 4488 | `_load_step_settings_cache` | `self._connect_stockdb` | STOCKDATA |
| `portefeuille_viewer/ui_logica/single_asset_analyse_tab_logica.py` | 4640 | `flush_step_settings_to_db` | `self._connect_stockdb` | STOCKDATA |
| `portefeuille_viewer/ui_logica/state_engine_tasks_dialog.py` | 195 | `_load_assets` | `pyodbc.connect` | factory/direct: controleren |
| `price_distribution_viewer/price_distribution_viewer.py` | 175 | `_connect` | `pyodbc.connect` | factory/direct: controleren |
| `price_distribution_viewer/price_distribution_viewer.py` | 186 | `_load_assets` | `self._connect` | factory/direct: controleren |
| `price_distribution_viewer/price_distribution_viewer.py` | 220 | `_fetch_asset_rows` | `self._connect` | factory/direct: controleren |
| `price_update_scripts/1 A - stockprice ibkr fetch 1.1 - optimized.py` | 308 | `save_df_to_access_temp` | `get_stockdata_connection` | STOCKDATA |
| `price_update_scripts/1 A - stockprice ibkr fetch 1.1 - optimized.py` | 333 | `main` | `get_stockdata_connection` | STOCKDATA |
| `price_update_scripts/1 B - stockprice merge into historical data correct.py` | 116 | `main` | `get_stockdata_connection` | STOCKDATA |
| `price_update_scripts/1 C - delete temp stock price table.py` | 17 | `delete_all_records` | `get_stockdata_connection` | STOCKDATA |
| `price_update_scripts/1A_fetch_historical_futures.py` | 95 | `load_future_targets` | `get_stockdata_connection` | STOCKDATA |
| `price_update_scripts/1A_fetch_historical_futures.py` | 239 | `save_df_to_access_temp` | `get_stockdata_connection` | STOCKDATA |
| `price_update_scripts/1A_fetch_historical_index.py` | 95 | `load_index_targets` | `get_stockdata_connection` | STOCKDATA |
| `price_update_scripts/1A_fetch_historical_index.py` | 239 | `save_df_to_access_temp` | `get_stockdata_connection` | STOCKDATA |
| `price_update_scripts/build_continuous_fut_close.py` | 424 | `write_to_temp_table` | `connect_stockdata` | STOCKDATA |
| `price_update_scripts/build_continuous_fut_close.py` | 424 | `write_to_temp_table` | `get_stockdata_connection` | STOCKDATA |
| `price_update_scripts/build_continuous_fut_close.py` | 476 | `upsert_to_historical_data_correct` | `connect_stockdata` | STOCKDATA |
| `price_update_scripts/build_continuous_fut_close.py` | 476 | `upsert_to_historical_data_correct` | `get_stockdata_connection` | STOCKDATA |
| `price_update_scripts/fetch_asset_volatility_history_to_db.py` | 220 | `main` | `connect_access` | factory/direct: controleren |
| `price_update_scripts/fetch_asset_volatility_history_to_db.py` | 361 | `load_assets` | `connect_access` | factory/direct: controleren |
| `price_update_scripts/fetch_asset_volatility_history_to_db.py` | 392 | `update_historical_data_correct` | `connect_access` | factory/direct: controleren |
| `price_update_scripts/fetch_asset_volatility_history_to_db.py` | 594 | `connect_access` | `get_stockdata_connection` | STOCKDATA |
| `price_update_scripts/fetch_asset_volatility_history_to_db.py` | 595 | `connect_access` | `connect_stockdata` | STOCKDATA |
| `price_update_scripts/startup_price_update.py` | 36 | `get_oldest_last_price_date` | `_connect` | factory/direct: controleren |
| `price_update_scripts/startup_price_update.py` | 50 | `_connect` | `get_stockdata_connection` | STOCKDATA |
| `price_update_scripts/startup_price_update.py` | 61 | `has_successful_run_today` | `_connect` | factory/direct: controleren |
| `price_update_scripts/startup_price_update.py` | 83 | `log_price_update_run` | `_connect` | factory/direct: controleren |
| `price_update_scripts_single_stock_fetch_long_history/21 - stockprice ibkr fetch 1.1 - single stock 10Y.py` | 298 | `save_df_to_access_temp` | `get_stockdata_connection` | STOCKDATA |
| `price_update_scripts_single_stock_fetch_long_history/21 - stockprice ibkr fetch 1.1 - single stock 10Y.py` | 323 | `main` | `get_stockdata_connection` | STOCKDATA |
| `price_update_scripts_single_stock_fetch_long_history/22 - stockprice merge into historical data correct.py` | 115 | `main` | `get_stockdata_connection` | STOCKDATA |
| `price_update_scripts_single_stock_fetch_long_history/23 - delete temp stock price table.py` | 16 | `delete_all_records` | `get_stockdata_connection` | STOCKDATA |
| `state_engine/common.py` | 14 | `get_connection` | `pyodbc.connect` | factory/direct: controleren |
| `state_engine/common.py` | 36 | `get_stockdata_connection` | `connect_stockdata` | STOCKDATA |
| `state_engine/create_state_engine_tables.py` | 302 | `create_tables` | `get_connection` | userdatabase |
| `state_engine/debug_open_optie_v2.py` | 25 | `main` | `get_connection` | userdatabase |
| `state_engine/open_aandelen_state_v2.py` | 805 | `main` | `get_connection` | userdatabase |
| `state_engine/open_aandelen_state_v2.py` | 805 | `main` | `get_stockdata_connection` | STOCKDATA |
| `state_engine/open_opties_state_v2.py` | 634 | `main` | `get_connection` | userdatabase |
| `state_engine/open_opties_state_v2.py` | 634 | `main` | `get_stockdata_connection` | STOCKDATA |
| `state_engine/open_sprinters_state_v2.py` | 574 | `main` | `get_connection` | userdatabase |
| `state_engine/open_sprinters_state_v2.py` | 574 | `main` | `get_stockdata_connection` | STOCKDATA |
| `state_engine/per_dag_asset_result_v2.py` | 1325 | `main` | `get_connection` | userdatabase |
| `state_engine/per_dag_asset_result_v2.py` | 1325 | `main` | `get_stockdata_connection` | STOCKDATA |
| `state_engine/validate_open_opties_v2_vs_v1.py` | 48 | `main` | `get_connection` | userdatabase |
| `transactie_analyse/data_loader.py` | 32 | `connect_read_only` | `pyodbc.connect` | factory/direct: controleren |
| `vol_surf_poc/archive/cp_chain_reader.py` | 150 | `load_spot_from_db` | `pyodbc.connect` | factory/direct: controleren |
| `vol_surf_poc/archive/db_reader.py` | 10 | `_connect` | `pyodbc.connect` | factory/direct: controleren |
| `vol_surf_poc/archive/db_reader.py` | 15 | `load_assets` | `_connect` | factory/direct: controleren |
| `vol_surf_poc/archive/db_reader.py` | 31 | `load_optie_referentie` | `_connect` | factory/direct: controleren |

## Grenzen van de inventaris

Aliassen en dynamische factories vragen handmatige controle. Factory/direct moet met de verbindingsstring worden beoordeeld. Ook losse hulpscripts staan in de lijst; een aanroepplaats bewijst niet dat een timer deze gebruikt. DAO/ADO-COM en verbindingen binnen dependencies staan niet in deze lijst. Zie het uitvoeringsverslag voor de beoordeelde groepen en de daadwerkelijk omgezette paden.

Niet geparseerd: geen.
