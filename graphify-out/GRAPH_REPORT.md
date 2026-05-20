# Graph Report - C:\python_coding\portefeuille_viewer\portefeuille_viewer_1.4  (2026-05-19)

## Corpus Check
- 243 files · ~853,826 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 4091 nodes · 10849 edges · 66 communities detected
- Extraction: 70% EXTRACTED · 30% INFERRED · 0% AMBIGUOUS · INFERRED: 3271 edges (avg confidence: 0.76)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]

## God Nodes (most connected - your core abstractions)
1. `SingleAssetAnalyseTab` - 157 edges
2. `SettingsManager` - 101 edges
3. `get_settings()` - 89 edges
4. `SectorAnalysisTab` - 72 edges
5. `OrdersTabWidget` - 57 edges
6. `StateEngineRunner` - 55 edges
7. `GeneratedOptionOrdersDialog` - 50 edges
8. `Event` - 49 edges
9. `SettingsTab` - 49 edges
10. `ColumnFilterPopup` - 48 edges

## Surprising Connections (you probably didn't know these)
- `Minimal event-driven state store.      - Keeps a versioned bucket per namespace.` --uses--> `Event`  [INFERRED]
  C:\python_coding\portefeuille_viewer\portefeuille_viewer_1.4\portefeuille_viewer\domain\state_store.py → C:\python_coding\portefeuille_viewer\portefeuille_viewer_1.4\portefeuille_viewer\domain\events.py
- `Apply one event and return changed keys.          Convention:         - event.pa` --uses--> `Event`  [INFERRED]
  C:\python_coding\portefeuille_viewer\portefeuille_viewer_1.4\portefeuille_viewer\domain\state_store.py → C:\python_coding\portefeuille_viewer\portefeuille_viewer_1.4\portefeuille_viewer\domain\events.py
- `Minimal WebEngine pilot tab.      - Uses a lightweight HTML frame/card layout.` --uses--> `ColumnFilterPopup`  [INFERRED]
  C:\python_coding\portefeuille_viewer\portefeuille_viewer_1.4\portefeuille_viewer\ui_logica\aandelen_web_pilot_tab.py → C:\python_coding\portefeuille_viewer\portefeuille_viewer_1.4\portefeuille_viewer\ui\filter_popup.py
- `Exporteer de huidige zichtbare tabel naar Excel, met snapshotnaam in bestandsnaa` --uses--> `PolarsTableModel`  [INFERRED]
  C:\python_coding\portefeuille_viewer\portefeuille_viewer_1.4\portefeuille_viewer\ui_logica\repository_tester_tab_logica.py → C:\python_coding\portefeuille_viewer\portefeuille_viewer_1.4\portefeuille_viewer\ui\models.py
- `main()` --calls--> `get_stockdata_db_path()`  [INFERRED]
  C:\python_coding\portefeuille_viewer\portefeuille_viewer_1.4\margin_efficiency_tool.py → C:\python_coding\portefeuille_viewer\portefeuille_viewer_1.4\portefeuille_viewer\config\settings_manager.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.02
Nodes (65): ColoredPolarsTableModel, ColumnFilterPopup, HeaderFilterMenuMixin, Vereist in de host-widget:     - self.tableView: QTableView     - self._table_, Klik op de hele rij (niet alleen het checkboxvakje) toggelt de checkstate., ScenarioManagerDialog, Geeft de Id's terug van alle aangevinkte rijen., ColoredPolarsTableModel (+57 more)

### Community 1 - "Community 1"
Cohesion: 0.02
Nodes (99): TestApp, fetch_target(), FutureHistApp, FutureTarget, load_future_targets(), main(), parse_args(), save_df_to_access_temp() (+91 more)

### Community 2 - "Community 2"
Cohesion: 0.02
Nodes (131): AssetIndicatorChangesPayload, build_asset_indicator_changes(), build_changes(), build_timeline(), _change_reasons(), classify_change(), _comparison_window(), _dt_sort_value() (+123 more)

### Community 3 - "Community 3"
Cohesion: 0.02
Nodes (164): hydrate_snapshots(), compact_float64(), Zet alle Float64 kolommen om naar Float32 om geheugen te besparen., LiveAggregatorAandelen, Gespecialiseerde aggregator voor aandelen live data processing., LiveAggregatorOpties, Specialized aggregator voor opties met live price updates., LiveAggregatorSprinters (+156 more)

### Community 4 - "Community 4"
Cohesion: 0.02
Nodes (61): AssetResultViewer, main(), _range_with_aligned_zero(), resolve_db_path(), to_timestamp(), BetaMatrixViewer, main(), _CashChartWorker (+53 more)

### Community 5 - "Community 5"
Cohesion: 0.03
Nodes (38): HeaderFilterMenuMixin, Ui_MainWindow, object, PolarsTableModel, PortfolioBrokerFilterController, normalize_broker(), PortfolioBrokerFilterState, build_combined_portfolio_value_df() (+30 more)

### Community 6 - "Community 6"
Cohesion: 0.03
Nodes (79): _clean(), connect_access(), _fallback_option_exchange(), _load_option_reference(), load_scan_assets(), table_columns(), truthy(), chain_path() (+71 more)

### Community 7 - "Community 7"
Cohesion: 0.04
Nodes (71): _to_float(), _create_table(), _fill_filter_combo(), GeneratedOptionOrdersDialog, MultiSelectFilterDialog, _norm_option_exp(), open_scenario_dialog(), _scenario_content_safe_df() (+63 more)

### Community 8 - "Community 8"
Cohesion: 0.03
Nodes (25): AssetIndicatorChangesTab, _AssetIndicatorWebBridge, AssetIndicatorWebTab, MainWindow, _TabBarNoFocusRectStyle, exportSnapshot(), openResolverDialog(), _OptieTijdswaardeWebBridge (+17 more)

### Community 9 - "Community 9"
Cohesion: 0.03
Nodes (51): AssetLastPriceStore, _current_db_key(), _normalize_key(), Centrale coordinator voor asset_last_prices.      De Access tabel wordt gebruikt, _read_from_db(), _write_to_db(), clear_live_prices(), initialize_live_prices() (+43 more)

### Community 10 - "Community 10"
Cohesion: 0.03
Nodes (101): error(), historicalDataEnd(), _infer_sec_type(), _is_index_symbol(), kick_off_more(), main(), nextValidId(), Submit one historical-data request for all_data row idx. (+93 more)

### Community 11 - "Community 11"
Cohesion: 0.03
Nodes (34): HighlightingPandasTableModel, _fmt(), LaatstTransactiesDialog, QTableWidget — Space togglet vinkje op huidige rij, sortering via header., _TransactiesTable, HighlightingPandasTableModel, MultiColFilterProxy, PandasTableModel (+26 more)

### Community 12 - "Community 12"
Cohesion: 0.03
Nodes (41): _AandelenWebBridge, AandelenWebPilotTab, _BetaScenarioWebBridge, BetaScenarioWebDialog, clearBrokers(), clearIndexShifts(), createBetaShiftScenario(), deleteActiveBetaShiftScenario() (+33 more)

### Community 13 - "Community 13"
Cohesion: 0.03
Nodes (56): close_scenario_dialog(), _append_today_if_needed(), close_month_end_chart_dialog(), _coerce_to_date(), _iter_daily_dates(), _iter_friday_dates(), _iter_month_end_dates(), _iter_quarter_end_dates() (+48 more)

### Community 14 - "Community 14"
Cohesion: 0.03
Nodes (61): _chain_summary(), _FetchWorker, PySide6 main window for the Vol Surface POC.  Layout:   ┌─ top bar ─────────────, Captures sys.stdout writes and emits them as a Qt signal (thread-safe)., _StdoutRedirect, VolSurfWindow, _cfg(), get_ib_port() (+53 more)

### Community 15 - "Community 15"
Cohesion: 0.03
Nodes (65): AandelenProjectionV2, _all_brokers(), _apply_timevalue_overlay(), _expected_no_price_assets(), _has_technical_keys(), _normalize_changed_assets(), _price_diag(), Versioned projection for Aandelen view.      - Produces full snapshot DataFram (+57 more)

### Community 16 - "Community 16"
Cohesion: 0.05
Nodes (92): empty_asset_indicator_live_frame(), empty_asset_indicator_summary_frame(), Contract definitions for the asset indicator/advisor pipeline.  This module inte, ActionDecision, ActionInput, calculate_direction_score(), calculate_long_term_direction_score(), calculate_range_position_pct() (+84 more)

### Community 17 - "Community 17"
Cohesion: 0.03
Nodes (44): AssetVolatilityHistoryUpdateRunner, from_environment(), _parse_last_json_line(), Run the daily HV/IV DB update script in a separate process., request_startup_update(), connect_access(), format_nl_3(), intrinsic_value() (+36 more)

### Community 18 - "Community 18"
Cohesion: 0.04
Nodes (77): normalize_numeric_columns(), parse_iso_date(), quantize_decimal(), attach_override_factor(), attach_raw_prices(), build_open_series(), compute_effective_prices_and_valuation(), compute_split_factor() (+69 more)

### Community 19 - "Community 19"
Cohesion: 0.04
Nodes (29): Standalone state engine tools for manual historical rebuilds., _coerce_to_date(), _iter_daily_dates(), _iter_friday_dates(), _iter_third_friday_dates(), MaandEindTab, MaandEindTableModel, _schedule_dates() (+21 more)

### Community 20 - "Community 20"
Cohesion: 0.05
Nodes (4): Run state-engine rebuilds asynchronously from central app signals., StateEngineRunner, _normalize_date(), StateEngineTasksDialog

### Community 21 - "Community 21"
Cohesion: 0.05
Nodes (16): _AssetRollupDeleteWorker, AssetRollupEditorTab, _AssetRollupLoadWorker, _AssetRollupSaveWorker, _LongHistoryOutputDialog, _SortableTableItem, AssetRollupColumn, _bracket() (+8 more)

### Community 22 - "Community 22"
Cohesion: 0.05
Nodes (39): build_records(), build_target_dates(), get_connection(), insert_records(), iter_weekdays(), load_cashflows_until(), load_existing_balance_dates(), log() (+31 more)

### Community 23 - "Community 23"
Cohesion: 0.06
Nodes (41): column_names(), create_tables(), ensure_per_dag_asset_result_v2_schema(), ensure_stock_splits_schema(), main(), table_exists(), main(), _clean() (+33 more)

### Community 24 - "Community 24"
Cohesion: 0.06
Nodes (26): delete_account_daily_balance(), ensure_account_daily_balances_schema(), _get_connection_with_retry(), _index_exists(), list_account_daily_balances(), _table_exists(), upsert_account_daily_balance(), _AccountBalancesDeleteWorker (+18 more)

### Community 25 - "Community 25"
Cohesion: 0.08
Nodes (27): AssetRow, clean(), connect_access(), duration_to_days(), filter_duration(), load_assets(), load_volatility_history(), FigureCanvas (+19 more)

### Community 26 - "Community 26"
Cohesion: 0.07
Nodes (17): OptieEindSortProxy, OptieEindTab, OptieEindTableModel, _state_classes_from_asset_types(), Ui_OptieEindTab, PandasTableModel, AssetMeta, build_contract() (+9 more)

### Community 27 - "Community 27"
Cohesion: 0.09
Nodes (42): _clean(), connect_access(), load_assets(), load_latest_spot(), table_columns(), truthy(), _as_date(), _asset_last_price_candidates() (+34 more)

### Community 28 - "Community 28"
Cohesion: 0.08
Nodes (31): AppTaskScheduler, ScheduledTask, _connect(), DividendCalendarRow, ensure_dividend_calendar_schema(), load_asset_universe(), replace_current_and_append_history(), _row_values() (+23 more)

### Community 29 - "Community 29"
Cohesion: 0.09
Nodes (20): AssetRecord, build_contract(), build_yfinance_candidates(), DividendIbWorker, DividendResult, DividendToolWindow, ExceptionSuppressor, fetch_next_earnings_date() (+12 more)

### Community 30 - "Community 30"
Cohesion: 0.15
Nodes (31): discover_earnings_calendar_columns(), dolt_query(), fetch_dolt_earnings(), format_raw_excerpt(), log(), main(), parse_args(), resolve_target_assets() (+23 more)

### Community 31 - "Community 31"
Cohesion: 0.13
Nodes (29): build_universe(), _clean(), compare_with_access_q3(), connect_access(), _friday_number(), load_asset_rollup_data(), load_latest_open_options_v2(), load_optie_referentie_data() (+21 more)

### Community 32 - "Community 32"
Cohesion: 0.16
Nodes (13): _asset_rollup_price_insensitive(), build_uniek_id_like_repository(), CandidatePair, _clean(), _date_for_id(), DoorrolApplier, DoorrolFinder, main() (+5 more)

### Community 33 - "Community 33"
Cohesion: 0.16
Nodes (13): _asset_rollup_price_insensitive(), build_uniek_id_like_repository(), CandidatePair, _clean(), _date_for_id(), DoorrolApplier, DoorrolFinder, main() (+5 more)

### Community 34 - "Community 34"
Cohesion: 0.16
Nodes (12): build_uniek_id_like_repository(), CandidatePair, _clean(), _date_for_id(), DoorrolApplier, DoorrolFinder, main(), _norm_dec_for_id() (+4 more)

### Community 35 - "Community 35"
Cohesion: 0.16
Nodes (11): AssignApplier, AssignFinder, AssignPair, build_uniek_id_like_repository(), _clean(), _date_for_id(), main(), _norm_dec_for_id() (+3 more)

### Community 36 - "Community 36"
Cohesion: 0.13
Nodes (21): AssetMeta, build_contract(), build_temp_rows(), clean(), ensure_temp_volatility_table(), execute_update_count(), fetch_volatility_series_windowed(), HistVolSeriesApp (+13 more)

### Community 37 - "Community 37"
Cohesion: 0.13
Nodes (26): aggregate_daily_transactions(), apply_split_price_correction(), attach_effective_close(), build_state_intervals(), compute_valuation(), create_temp_stage_table(), delete_target_range(), drop_stale_temp_stage_tables() (+18 more)

### Community 38 - "Community 38"
Cohesion: 0.16
Nodes (11): Applier, build_uniek_id_like_repository(), _clean(), Finder, main(), _norm_dec_for_id(), normalize_side(), ReviewWindow (+3 more)

### Community 39 - "Community 39"
Cohesion: 0.16
Nodes (8): _clean(), ExpireApplier, ExpireCandidate, ExpireFinder, main(), ReviewWindow, _to_date(), to_float()

### Community 40 - "Community 40"
Cohesion: 0.17
Nodes (9): _days_in_month(), main(), _nice_step(), PriceDistributionViewer, PriceRow, resolve_db_path(), _safe_date(), _safe_float() (+1 more)

### Community 41 - "Community 41"
Cohesion: 0.19
Nodes (8): _clean(), DoorrolOrderIssue, find_orders_with_call_put_mix(), IssueApplier, load_doorrol_rows(), main(), _normalize_cp(), ReviewWindow

### Community 42 - "Community 42"
Cohesion: 0.26
Nodes (12): build_payload(), _dt_sort_value(), _dt_value(), find_changes(), _fmt_dt(), _fmt_num(), load_history_rows(), main() (+4 more)

### Community 43 - "Community 43"
Cohesion: 0.22
Nodes (8): coalesce_cols(), compute_equity_flows(), print_snapshot_columns(), print_snapshot_head(), Druk de eerste `n` records van een snapshot af., Druk de kolommen van een snapshot af in tabelvorm., Combineer meerdere kolommen in volgorde van prioriteit.     De eerste niet-null, Bereken cumulatieve equity flows (aandelen).     Output bevat buy/sell totals e

### Community 44 - "Community 44"
Cohesion: 0.5
Nodes (3): CellPatchPayload, SnapshotInitPayload, ViewPatchPayload

### Community 45 - "Community 45"
Cohesion: 1.0
Nodes (1): Deprecated placeholder.  De OpenAI-adviesfunctie is verwijderd uit deze variant

### Community 46 - "Community 46"
Cohesion: 1.0
Nodes (0): 

### Community 47 - "Community 47"
Cohesion: 1.0
Nodes (0): 

### Community 48 - "Community 48"
Cohesion: 1.0
Nodes (0): 

### Community 49 - "Community 49"
Cohesion: 1.0
Nodes (0): 

### Community 50 - "Community 50"
Cohesion: 1.0
Nodes (0): 

### Community 51 - "Community 51"
Cohesion: 1.0
Nodes (0): 

### Community 52 - "Community 52"
Cohesion: 1.0
Nodes (0): 

### Community 53 - "Community 53"
Cohesion: 1.0
Nodes (0): 

### Community 54 - "Community 54"
Cohesion: 1.0
Nodes (0): 

### Community 55 - "Community 55"
Cohesion: 1.0
Nodes (0): 

### Community 56 - "Community 56"
Cohesion: 1.0
Nodes (0): 

### Community 57 - "Community 57"
Cohesion: 1.0
Nodes (0): 

### Community 58 - "Community 58"
Cohesion: 1.0
Nodes (0): 

### Community 59 - "Community 59"
Cohesion: 1.0
Nodes (0): 

### Community 60 - "Community 60"
Cohesion: 1.0
Nodes (0): 

### Community 61 - "Community 61"
Cohesion: 1.0
Nodes (1): Vraag marktdata aan voor subscriptions.          Ondersteunt:         - legacy:

### Community 62 - "Community 62"
Cohesion: 1.0
Nodes (1): Start option market-data subscriptions.          rows format: (series_id, conid,

### Community 63 - "Community 63"
Cohesion: 1.0
Nodes (0): 

### Community 64 - "Community 64"
Cohesion: 1.0
Nodes (0): 

### Community 65 - "Community 65"
Cohesion: 1.0
Nodes (0): 

## Knowledge Gaps
- **165 isolated node(s):** `Standalone web report for asset indicator history changes.  Run:     python devt`, `Standalone E2E helper to fetch executions from the last N days.     Returns a li`, `Run AssetIndicatorService once from the command line.  This is a devtool for ins`, `Dividend Viewer — standalone tool. Laadt assets uit de portefeuille-database (as`, `Parseert IBKR dividend string: trailing12m,forward12m,nextDate,nextAmount` (+160 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 45`** (2 nodes): `Deprecated placeholder.  De OpenAI-adviesfunctie is verwijderd uit deze variant`, `ai_option_advisor.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 46`** (1 nodes): `optie_scanner.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 47`** (1 nodes): `option_workbench.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 48`** (1 nodes): `test_functions_to_be_copied_to_other_files.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 49`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 50`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 51`** (1 nodes): `asset_source.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 52`** (1 nodes): `chain_retriever_window.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 53`** (1 nodes): `chain_run_repository.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 54`** (1 nodes): `chain_scanner.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 55`** (1 nodes): `chain_store.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 56`** (1 nodes): `date_utils.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 57`** (1 nodes): `main.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 58`** (1 nodes): `models.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 59`** (1 nodes): `orchestrator.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 60`** (1 nodes): `parquet_viewer.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 61`** (1 nodes): `Vraag marktdata aan voor subscriptions.          Ondersteunt:         - legacy:`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 62`** (1 nodes): `Start option market-data subscriptions.          rows format: (series_id, conid,`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 63`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 64`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 65`** (1 nodes): `iv_surface_app.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_stockdata_connection()` connect `Community 10` to `Community 0`, `Community 1`, `Community 2`, `Community 3`, `Community 4`, `Community 6`, `Community 9`, `Community 42`, `Community 15`, `Community 16`, `Community 17`, `Community 20`, `Community 26`, `Community 28`, `Community 31`?**
  _High betweenness centrality (0.030) - this node is a cross-community bridge._
- **Why does `SingleAssetAnalyseTab` connect `Community 0` to `Community 8`, `Community 5`, `Community 7`?**
  _High betweenness centrality (0.026) - this node is a cross-community bridge._
- **Why does `main()` connect `Community 3` to `Community 2`, `Community 4`, `Community 5`, `Community 8`, `Community 9`, `Community 14`, `Community 17`, `Community 20`, `Community 28`?**
  _High betweenness centrality (0.026) - this node is a cross-community bridge._
- **Are the 7 inferred relationships involving `SingleAssetAnalyseTab` (e.g. with `MainWindow` and `_TabBarNoFocusRectStyle`) actually correct?**
  _`SingleAssetAnalyseTab` has 7 INFERRED edges - model-reasoned connections that need verification._
- **Are the 79 inferred relationships involving `get_settings()` (e.g. with `_apply_env_defaults_from_settings()` and `_resolve_database_alias()`) actually correct?**
  _`get_settings()` has 79 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `SectorAnalysisTab` (e.g. with `MainWindow` and `_TabBarNoFocusRectStyle`) actually correct?**
  _`SectorAnalysisTab` has 6 INFERRED edges - model-reasoned connections that need verification._
- **Are the 7 inferred relationships involving `OrdersTabWidget` (e.g. with `MainWindow` and `_TabBarNoFocusRectStyle`) actually correct?**
  _`OrdersTabWidget` has 7 INFERRED edges - model-reasoned connections that need verification._