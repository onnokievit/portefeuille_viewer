# Graph Report - portefeuille_viewer/portefeuille_viewer_1.2  (2026-04-18)

## Corpus Check
- 152 files · ~192,085 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2587 nodes · 6498 edges · 58 communities detected
- Extraction: 73% EXTRACTED · 27% INFERRED · 0% AMBIGUOUS · INFERRED: 1767 edges (avg confidence: 0.75)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Table UI Components|Table UI Components]]
- [[_COMMUNITY_IB Historical Data Apps|IB Historical Data Apps]]
- [[_COMMUNITY_Scenario Order Management|Scenario Order Management]]
- [[_COMMUNITY_Option Orders Dialog|Option Orders Dialog]]
- [[_COMMUNITY_Portfolio Engine Core|Portfolio Engine Core]]
- [[_COMMUNITY_Data Normalization Utilities|Data Normalization Utilities]]
- [[_COMMUNITY_Snapshot Hydration & Equity|Snapshot Hydration & Equity]]
- [[_COMMUNITY_Table Filter & Highlighting|Table Filter & Highlighting]]
- [[_COMMUNITY_Option Chain & State Rebuild|Option Chain & State Rebuild]]
- [[_COMMUNITY_Main Window UI|Main Window UI]]
- [[_COMMUNITY_Stocks Web Pilot Tab|Stocks Web Pilot Tab]]
- [[_COMMUNITY_App Shell & Tab Management|App Shell & Tab Management]]
- [[_COMMUNITY_Universe & Rebuild Pipeline|Universe & Rebuild Pipeline]]
- [[_COMMUNITY_Aandelen Projection Engine|Aandelen Projection Engine]]
- [[_COMMUNITY_Live Stock Aggregator|Live Stock Aggregator]]
- [[_COMMUNITY_Asset Result Viewer|Asset Result Viewer]]
- [[_COMMUNITY_Architecture Documentation|Architecture Documentation]]
- [[_COMMUNITY_Options End Tab|Options End Tab]]
- [[_COMMUNITY_Universe Build & Comparison|Universe Build & Comparison]]
- [[_COMMUNITY_Date & Calendar Utilities|Date & Calendar Utilities]]
- [[_COMMUNITY_Open Series Rebuild|Open Series Rebuild]]
- [[_COMMUNITY_Roll Candidate Review V2|Roll Candidate Review V2]]
- [[_COMMUNITY_Roll Candidate Review V3|Roll Candidate Review V3]]
- [[_COMMUNITY_Assignment Candidate Review|Assignment Candidate Review]]
- [[_COMMUNITY_Roll Candidate Review V1|Roll Candidate Review V1]]
- [[_COMMUNITY_Event Bus Signals|Event Bus Signals]]
- [[_COMMUNITY_Sprinter Roll Candidates|Sprinter Roll Candidates]]
- [[_COMMUNITY_Sprinter Doorrol Review|Sprinter Doorrol Review]]
- [[_COMMUNITY_Month-End Matrix Tab|Month-End Matrix Tab]]
- [[_COMMUNITY_Contract Builder|Contract Builder]]
- [[_COMMUNITY_Expiry Candidate Review|Expiry Candidate Review]]
- [[_COMMUNITY_Open Options Web Bridge|Open Options Web Bridge]]
- [[_COMMUNITY_Sprinter State Processing|Sprinter State Processing]]
- [[_COMMUNITY_Option Time Value Web Bridge|Option Time Value Web Bridge]]
- [[_COMMUNITY_Order Issue Detection|Order Issue Detection]]
- [[_COMMUNITY_IB Historical Data Feed|IB Historical Data Feed]]
- [[_COMMUNITY_Option Tick Prober|Option Tick Prober]]
- [[_COMMUNITY_Live Asset Subscription|Live Asset Subscription]]
- [[_COMMUNITY_Live Options Subscription|Live Options Subscription]]
- [[_COMMUNITY_Time Value Projection|Time Value Projection]]
- [[_COMMUNITY_Option Series Seeding|Option Series Seeding]]
- [[_COMMUNITY_Viewer Apps & Settings|Viewer Apps & Settings]]
- [[_COMMUNITY_DB Merge Utilities|DB Merge Utilities]]
- [[_COMMUNITY_Diff Patch Contracts|Diff Patch Contracts]]
- [[_COMMUNITY_GBP Pence Bug Fix|GBP Pence Bug Fix]]
- [[_COMMUNITY_DB Migration & Constraints|DB Migration & Constraints]]
- [[_COMMUNITY_Scenario Bucket System|Scenario Bucket System]]
- [[_COMMUNITY_Deprecated AI Advisor|Deprecated AI Advisor]]
- [[_COMMUNITY_DB Cleanup Scripts|DB Cleanup Scripts]]
- [[_COMMUNITY_Test Utilities|Test Utilities]]
- [[_COMMUNITY_Package Init|Package Init]]
- [[_COMMUNITY_Package Init|Package Init]]
- [[_COMMUNITY_Market Data Subscriptions|Market Data Subscriptions]]
- [[_COMMUNITY_Option Market Data Start|Option Market Data Start]]
- [[_COMMUNITY_Package Init|Package Init]]
- [[_COMMUNITY_Package Init|Package Init]]
- [[_COMMUNITY_State Engine Runner|State Engine Runner]]
- [[_COMMUNITY_In-Memory Architecture Notes|In-Memory Architecture Notes]]

## God Nodes (most connected - your core abstractions)
1. `SingleAssetAnalyseTab` - 127 edges
2. `GeneratedOptionOrdersDialog` - 87 edges
3. `SectorAnalysisTab` - 71 edges
4. `StateEngineRunner` - 55 edges
5. `OrdersTabWidget` - 54 edges
6. `SettingsManager` - 50 edges
7. `ColumnFilterPopup` - 48 edges
8. `AandelenWebPilotTab` - 48 edges
9. `HeaderFilterMenuMixin` - 45 edges
10. `get_settings()` - 41 edges

## Surprising Connections (you probably didn't know these)
- `Exporteer de huidige zichtbare tabel naar Excel, met snapshotnaam in bestandsnaa` --uses--> `PolarsTableModel`  [INFERRED]
  portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\ui_logica\repository_tester_tab_logica.py → portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\ui\models.py
- `_apply_env_defaults_from_settings()` --calls--> `get_settings()`  [INFERRED]
  portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer_1.2.py → portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\config\settings_manager.py
- `SupportsProjectionRefresh` --uses--> `MainWindow`  [INFERRED]
  portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer_1.2.py → portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\ui_logica\main_window_logica.py
- `SupportsProjectionRefresh` --uses--> `PriceFeedService`  [INFERRED]
  portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer_1.2.py → portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\services\price_feed.py
- `SupportsProjectionRefresh` --uses--> `StateEngineRunner`  [INFERRED]
  portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer_1.2.py → portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\services\state_engine_runner.py

## Hyperedges (group relationships)
- **Event-Driven Runtime Pipeline (Events -> StateStore -> ProjectionBus -> Projections -> WebEngine)** — development_notes_engine_core_runtime, development_notes_state_store, development_notes_projection_bus, development_notes_projection_v2, development_notes_webengine_tabs [EXTRACTED 1.00]
- **Scenario Simulation Flow (Buckets -> Resolver -> Overlay -> Snapshot)** — simulatieframework_bucket_1, simulatieframework_bucket_2, simulatieframework_bucket_3, development_notes_scenario_order_resolver, simulatieframework_scenario_overlay_service [EXTRACTED 0.95]
- **ML Roll Advisor Data Foundation (Time Value + History + Regime + Strategy)** — todo_ml_roll_advisor, todo_option_price_history, development_notes_option_timevalue_service, trading_strategy_theta_harvesting, trading_strategy_regime_sets [INFERRED 0.78]

## Communities

### Community 0 - "Table UI Components"
Cohesion: 0.02
Nodes (65): ColoredPolarsTableModel, ColumnFilterPopup, HeaderFilterMenuMixin, Vereist in de host-widget:     - self.tableView: QTableView     - self._table_, Klik op de hele rij (niet alleen het checkboxvakje) toggelt de checkstate., ColoredPolarsTableModel, QStyledItemDelegate, fetch_open_optie_comments() (+57 more)

### Community 1 - "IB Historical Data Apps"
Cohesion: 0.02
Nodes (96): TestApp, fetch_target(), FutureHistApp, FutureTarget, load_future_targets(), main(), parse_args(), save_df_to_access_temp() (+88 more)

### Community 2 - "Scenario Order Management"
Cohesion: 0.04
Nodes (107): get_connection(), _scenario_content_safe_df(), _refresh_active_scenario_overlays(), estimate_delta(), Schat delta op basis van moneyness.      - Ondersteunt option_type in variante, _asset_has_option_eom_flow(), _asset_meta_map(), _base_combined_map() (+99 more)

### Community 3 - "Option Orders Dialog"
Cohesion: 0.03
Nodes (23): CheckableSortItem, _create_table(), _fill_filter_combo(), GeneratedOptionOrdersDialog, MultiSelectFilterDialog, _norm_option_exp(), ScenarioManagerDialog, _spot_lookup() (+15 more)

### Community 4 - "Portfolio Engine Core"
Cohesion: 0.03
Nodes (83): run_loop(), connect_access(), format_nl_3(), intrinsic_value(), load_latest_option_snapshot(), load_latest_underlying_close(), load_open_option_positions(), load_universe_map() (+75 more)

### Community 5 - "Data Normalization Utilities"
Cohesion: 0.03
Nodes (103): normalize_numeric_columns(), parse_iso_date(), quantize_decimal(), column_names(), create_tables(), ensure_per_dag_asset_result_v2_schema(), ensure_stock_splits_schema(), main() (+95 more)

### Community 6 - "Snapshot Hydration & Equity"
Cohesion: 0.04
Nodes (104): hydrate_snapshots(), coalesce_cols(), compact_float64(), compute_equity_flows(), print_snapshot_columns(), print_snapshot_head(), Druk de eerste `n` records van een snapshot af., Druk de kolommen van een snapshot af in tabelvorm. (+96 more)

### Community 7 - "Table Filter & Highlighting"
Cohesion: 0.03
Nodes (26): HeaderFilterMenuMixin, HighlightingPandasTableModel, HighlightingPandasTableModel, MultiColFilterProxy, PandasTableModel, PolarsTableModel, Qt-model dat data rechtstreeks uit een Polars DataFrame toont.     Te gebruiken, Optioneel alternatieve header labels meegeven per kolomnaam. (+18 more)

### Community 8 - "Option Chain & State Rebuild"
Cohesion: 0.03
Nodes (37): Standalone state engine tools for manual historical rebuilds., OptionChainTableModel, Option Chain Table Model Polars-based table model voor option chain display, Get all data for a specific row, Table model voor option chain data (Polars DataFrame), Update table met nieuwe DataFrame, OptionChainService, Option Chain Service Handles IBKR reqContractDetails for option chain retrieval (+29 more)

### Community 9 - "Main Window UI"
Cohesion: 0.05
Nodes (13): Ui_MainWindow, object, PolarsTableModel, QSortFilterProxyModel, QWidget, _on_selection_changed(), Snapshot tester tab gekoppeld aan repository_tester_ui.py     Dropdown toont sn, Exporteer de huidige zichtbare tabel naar Excel, met snapshotnaam in bestandsnaa (+5 more)

### Community 10 - "Stocks Web Pilot Tab"
Cohesion: 0.05
Nodes (37): _AandelenWebBridge, AandelenWebPilotTab, _BetaScenarioWebBridge, BetaScenarioWebDialog, clearBrokers(), clearIndexShifts(), createBetaShiftScenario(), deleteActiveBetaShiftScenario() (+29 more)

### Community 11 - "App Shell & Tab Management"
Cohesion: 0.04
Nodes (20): MainWindow, _TabBarNoFocusRectStyle, QProxyStyle, _load_db_config(), Laad database configuratie uit settings.ini., Herlaad database configuratie na wijzigingen in settings., reload_db_config(), add_database() (+12 more)

### Community 12 - "Universe & Rebuild Pipeline"
Cohesion: 0.05
Nodes (9): connect_access(), load_universe(), main(), parse_args(), write_table(), Run state-engine rebuilds asynchronously from central app signals., StateEngineRunner, _normalize_date() (+1 more)

### Community 13 - "Aandelen Projection Engine"
Cohesion: 0.04
Nodes (48): AandelenProjectionV2, _all_brokers(), _apply_timevalue_overlay(), _expected_no_price_assets(), _has_technical_keys(), _normalize_changed_assets(), _price_diag(), Versioned projection for Aandelen view.      - Produces full snapshot DataFram (+40 more)

### Community 14 - "Live Stock Aggregator"
Cohesion: 0.05
Nodes (22): LiveAggregatorAandelen, Gespecialiseerde aggregator voor aandelen live data processing., initialize_live_prices(), Vul SNAPSHOT_STORE.live_prices altijd eerst met de laatste bekende prijzen uit d, LiveAggregatorOpties, Specialized aggregator voor opties met live price updates., LiveAggregatorSprinters, Specialized aggregator voor sprinters met live price updates. (+14 more)

### Community 15 - "Asset Result Viewer"
Cohesion: 0.06
Nodes (19): AssetResultViewer, main(), _range_with_aligned_zero(), resolve_db_path(), to_timestamp(), BetaMatrixViewer, main(), IndexRegressionViewer (+11 more)

### Community 16 - "Architecture Documentation"
Cohesion: 0.05
Nodes (48): Dev Notes v0.5: CRUD + Snapshot Sync Architecture, Dev Notes v0.10: Repository + Snapshot Store Architecture, Dev Notes v0.10: Live Aggregator Refactor, Archived: Live Optie Engine Integration Plan, Archived: Optimalisatie Engine (Migration Plan), Archived: Roadmap Engine + UI Modernisatie, Archived: Roadmap Modernisatie TODO, EngineCoreRuntime (+40 more)

### Community 17 - "Options End Tab"
Cohesion: 0.07
Nodes (13): OptieEindSortProxy, OptieEindTab, OptieEindTableModel, _state_classes_from_asset_types(), Ui_OptieEindTab, PandasTableModel, _build_default_state(), Reset alle snapshots naar leeg. (+5 more)

### Community 18 - "Universe Build & Comparison"
Cohesion: 0.1
Nodes (38): build_universe(), _clean(), compare_with_access_q3(), connect_access(), _friday_number(), load_asset_rollup_data(), load_latest_open_options_v2(), load_optie_referentie_data() (+30 more)

### Community 19 - "Date & Calendar Utilities"
Cohesion: 0.11
Nodes (20): _append_today_if_needed(), _coerce_to_date(), _date_label(), _iter_daily_dates(), _iter_friday_dates(), _iter_month_end_dates(), _iter_quarter_end_dates(), _iter_third_friday_dates() (+12 more)

### Community 20 - "Open Series Rebuild"
Cohesion: 0.12
Nodes (11): _apply_rebuild_result(), _clean(), _intrinsic(), _now_ts(), OpenSeriesRow, _option_week(), OptionTimevalueService, _pick_option_price() (+3 more)

### Community 21 - "Roll Candidate Review V2"
Cohesion: 0.16
Nodes (13): _asset_rollup_price_insensitive(), build_uniek_id_like_repository(), CandidatePair, _clean(), _date_for_id(), DoorrolApplier, DoorrolFinder, main() (+5 more)

### Community 22 - "Roll Candidate Review V3"
Cohesion: 0.16
Nodes (13): _asset_rollup_price_insensitive(), build_uniek_id_like_repository(), CandidatePair, _clean(), _date_for_id(), DoorrolApplier, DoorrolFinder, main() (+5 more)

### Community 23 - "Assignment Candidate Review"
Cohesion: 0.16
Nodes (11): AssignApplier, AssignFinder, AssignPair, build_uniek_id_like_repository(), _clean(), _date_for_id(), main(), _norm_dec_for_id() (+3 more)

### Community 24 - "Roll Candidate Review V1"
Cohesion: 0.16
Nodes (12): build_uniek_id_like_repository(), CandidatePair, _clean(), _date_for_id(), DoorrolApplier, DoorrolFinder, main(), _norm_dec_for_id() (+4 more)

### Community 25 - "Event Bus Signals"
Cohesion: 0.07
Nodes (2): Central application signals.      Keep this module minimal and free of project, Signals

### Community 26 - "Sprinter Roll Candidates"
Cohesion: 0.16
Nodes (11): _asset_rollup_price_insensitive(), build_uniek_id_like_repository(), CandidatePair, _clean(), DoorrolApplier, DoorrolFinder, main(), normalize_side() (+3 more)

### Community 27 - "Sprinter Doorrol Review"
Cohesion: 0.16
Nodes (11): Applier, build_uniek_id_like_repository(), _clean(), Finder, main(), _norm_dec_for_id(), normalize_side(), ReviewWindow (+3 more)

### Community 28 - "Month-End Matrix Tab"
Cohesion: 0.12
Nodes (9): _coerce_to_date(), _iter_daily_dates(), _iter_friday_dates(), _iter_third_friday_dates(), MaandEindTab, MaandEindTableModel, _schedule_dates(), _third_friday() (+1 more)

### Community 29 - "Contract Builder"
Cohesion: 0.15
Nodes (16): build_contract(), _cell_decimals(), connect_access(), _fmt_nl(), _intrinsic(), load_latest_underlying_close(), load_universe(), main() (+8 more)

### Community 30 - "Expiry Candidate Review"
Cohesion: 0.16
Nodes (8): _clean(), ExpireApplier, ExpireCandidate, ExpireFinder, main(), ReviewWindow, _to_date(), to_float()

### Community 31 - "Open Options Web Bridge"
Cohesion: 0.14
Nodes (7): commentEditing(), exportSnapshot(), openCommentColorMenu(), openResolverDialog(), _OptiesOpenWebBridge, OptiesOpenWebPilotTab, saveComment()

### Community 32 - "Sprinter State Processing"
Cohesion: 0.16
Nodes (22): attach_effective_close(), build_state_intervals(), compute_sprinter_values(), create_temp_stage_table(), delete_target_range(), drop_stale_temp_stage_tables(), drop_temp_stage_table(), fetch_min_transaction_date() (+14 more)

### Community 33 - "Option Time Value Web Bridge"
Cohesion: 0.17
Nodes (4): exportSnapshot(), openResolverDialog(), _OptieTijdswaardeWebBridge, OptieTijdswaardeWebPilotTab

### Community 34 - "Order Issue Detection"
Cohesion: 0.19
Nodes (8): _clean(), DoorrolOrderIssue, find_orders_with_call_put_mix(), IssueApplier, load_doorrol_rows(), main(), _normalize_cp(), ReviewWindow

### Community 35 - "IB Historical Data Feed"
Cohesion: 0.17
Nodes (15): error(), historicalDataEnd(), _infer_sec_type(), _is_index_symbol(), kick_off_more(), main(), nextValidId(), Submit one historical-data request for all_data row idx. (+7 more)

### Community 36 - "Option Tick Prober"
Cohesion: 0.23
Nodes (7): _build_contract(), main(), OptionProbeApp, parse_args(), _parse_market_data_types(), _to_num(), _ts()

### Community 37 - "Live Asset Subscription"
Cohesion: 0.21
Nodes (10): AssetMeta, build_contract(), LiveAssetApp, load_asset_meta(), main(), parse_args(), resolve_exchange(), resolve_sec_type() (+2 more)

### Community 38 - "Live Options Subscription"
Cohesion: 0.21
Nodes (12): _best_last(), _build_contract(), _connect_access(), _ensure_snapshot_table(), _load_universe(), main(), OptionLiveApp, parse_args() (+4 more)

### Community 39 - "Time Value Projection"
Cohesion: 0.2
Nodes (6): OptieTijdswaardeProjectionV2, _prepare_df(), Versioned projection for Optie Tijdswaarde., _row_id_of(), _same_value(), _to_row_map()

### Community 40 - "Option Series Seeding"
Cohesion: 0.42
Nodes (9): _clean(), connect_access(), fetch_open_option_series(), main(), parse_args(), seed_into_master(), SeedStats, _to_date() (+1 more)

### Community 41 - "Viewer Apps & Settings"
Cohesion: 0.28
Nodes (9): Beta Matrix Viewer App, historical_data_correct (STOCKDATA.accdb), Index Regression Viewer App, settings_shared.ini (beta drivers config), SettingsManager (shared/local ini), Price Distribution Viewer App, Market/Beta Simulation (Shock Scenarios), Asset Categories (Value/Growth/Speculative) (+1 more)

### Community 42 - "DB Merge Utilities"
Cohesion: 0.48
Nodes (6): ensure_indexes(), main(), merge_delete_append(), merge_update_insert(), null_safe_diff(), Bouwt een NULL-veilige verschil-expressie voor Access/ODBC:       (main.col <>

### Community 43 - "Diff Patch Contracts"
Cohesion: 0.5
Nodes (3): CellPatchPayload, SnapshotInitPayload, ViewPatchPayload

### Community 44 - "GBP Pence Bug Fix"
Cohesion: 0.67
Nodes (4): asset_rollup_data (ib_currency field), open_sprinters_state_v2.py, Sprinter GBP Pence-to-Pounds Bug, price_multiplier (GBP pence correction factor)

### Community 45 - "DB Migration & Constraints"
Cohesion: 0.67
Nodes (3): DbMigrationService, Rationale: Multi-DB and Compatibility as Hard Constraint, User Database (portfolio, transactions)

### Community 46 - "Scenario Bucket System"
Cohesion: 0.67
Nodes (3): Scenario Bucket 1 (Manual Test Orders), Scenario Bucket 2 (Generated Option Orders), Scenario Bucket 3 (Derived EOM Effects)

### Community 47 - "Deprecated AI Advisor"
Cohesion: 1.0
Nodes (1): Deprecated placeholder.  De OpenAI-adviesfunctie is verwijderd uit deze variant

### Community 48 - "DB Cleanup Scripts"
Cohesion: 1.0
Nodes (0): 

### Community 49 - "Test Utilities"
Cohesion: 1.0
Nodes (0): 

### Community 50 - "Package Init"
Cohesion: 1.0
Nodes (0): 

### Community 51 - "Package Init"
Cohesion: 1.0
Nodes (0): 

### Community 52 - "Market Data Subscriptions"
Cohesion: 1.0
Nodes (1): Vraag marktdata aan voor subscriptions.          Ondersteunt:         - legacy:

### Community 53 - "Option Market Data Start"
Cohesion: 1.0
Nodes (1): Start option market-data subscriptions.          rows format: (series_id, conid,

### Community 54 - "Package Init"
Cohesion: 1.0
Nodes (0): 

### Community 55 - "Package Init"
Cohesion: 1.0
Nodes (0): 

### Community 56 - "State Engine Runner"
Cohesion: 1.0
Nodes (1): StateEngineRunner

### Community 57 - "In-Memory Architecture Notes"
Cohesion: 1.0
Nodes (1): Dev Notes v0.11: In-Memory Polars Architecture

## Knowledge Gaps
- **154 isolated node(s):** `Standalone E2E helper to fetch executions from the last N days.     Returns a li`, `Laad config uit settings_shared.ini en settings_local.ini.`, `Sla huidige config gesplitst op naar shared en local.`, `Haal alle databases op als dictionary.`, `Haal naam van default database op.` (+149 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Deprecated AI Advisor`** (2 nodes): `Deprecated placeholder.  De OpenAI-adviesfunctie is verwijderd uit deze variant`, `ai_option_advisor.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `DB Cleanup Scripts`** (2 nodes): `delete_all_records()`, `1 C - delete temp stock price table.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Test Utilities`** (1 nodes): `test_functions_to_be_copied_to_other_files.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Package Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Package Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Market Data Subscriptions`** (1 nodes): `Vraag marktdata aan voor subscriptions.          Ondersteunt:         - legacy:`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Option Market Data Start`** (1 nodes): `Start option market-data subscriptions.          rows format: (series_id, conid,`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Package Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Package Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `State Engine Runner`** (1 nodes): `StateEngineRunner`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `In-Memory Architecture Notes`** (1 nodes): `Dev Notes v0.11: In-Memory Polars Architecture`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `GeneratedOptionOrdersDialog` connect `Option Orders Dialog` to `Table UI Components`, `Main Window UI`, `Scenario Order Management`, `Stocks Web Pilot Tab`?**
  _High betweenness centrality (0.050) - this node is a cross-community bridge._
- **Why does `MainWindow` connect `App Shell & Tab Management` to `Table UI Components`, `Option Time Value Web Bridge`, `Scenario Order Management`, `Option Orders Dialog`, `Portfolio Engine Core`, `Table Filter & Highlighting`, `Main Window UI`, `Stocks Web Pilot Tab`, `Asset Result Viewer`, `Options End Tab`, `Date & Calendar Utilities`, `Open Options Web Bridge`?**
  _High betweenness centrality (0.050) - this node is a cross-community bridge._
- **Why does `SingleAssetAnalyseTab` connect `Table UI Components` to `Scenario Order Management`, `Option Orders Dialog`, `Table Filter & Highlighting`, `Main Window UI`, `App Shell & Tab Management`?**
  _High betweenness centrality (0.040) - this node is a cross-community bridge._
- **Are the 8 inferred relationships involving `SingleAssetAnalyseTab` (e.g. with `MainWindow` and `_TabBarNoFocusRectStyle`) actually correct?**
  _`SingleAssetAnalyseTab` has 8 INFERRED edges - model-reasoned connections that need verification._
- **Are the 40 inferred relationships involving `GeneratedOptionOrdersDialog` (e.g. with `AandelenWebPilotTab` and `BetaScenarioWebDialog`) actually correct?**
  _`GeneratedOptionOrdersDialog` has 40 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `SectorAnalysisTab` (e.g. with `MainWindow` and `_TabBarNoFocusRectStyle`) actually correct?**
  _`SectorAnalysisTab` has 6 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `StateEngineRunner` (e.g. with `SupportsProjectionRefresh` and `ProjectionRefreshConfig`) actually correct?**
  _`StateEngineRunner` has 4 INFERRED edges - model-reasoned connections that need verification._