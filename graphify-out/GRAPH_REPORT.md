# Graph Report - C:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2  (2026-04-19)

## Corpus Check
- 133 files · ~401,953 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2597 nodes · 6517 edges · 56 communities detected
- Extraction: 73% EXTRACTED · 27% INFERRED · 0% AMBIGUOUS · INFERRED: 1772 edges (avg confidence: 0.75)
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
- `_apply_env_defaults_from_settings()` --calls--> `get_settings()`  [INFERRED]
  portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer_1.2.py → portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\config\settings_manager.py
- `SupportsProjectionRefresh` --uses--> `MainWindow`  [INFERRED]
  portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer_1.2.py → portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\ui_logica\main_window_logica.py
- `SupportsProjectionRefresh` --uses--> `PriceFeedService`  [INFERRED]
  portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer_1.2.py → portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\services\price_feed.py
- `SupportsProjectionRefresh` --uses--> `StateEngineRunner`  [INFERRED]
  portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer_1.2.py → portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\services\state_engine_runner.py
- `SupportsProjectionRefresh` --uses--> `OptionTimevalueService`  [INFERRED]
  portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer_1.2.py → portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\services\option_timevalue_service.py

## Hyperedges (group relationships)
- **Event-Driven Runtime Pipeline (Events -> StateStore -> ProjectionBus -> Projections -> WebEngine)** — development_notes_engine_core_runtime, development_notes_state_store, development_notes_projection_bus, development_notes_projection_v2, development_notes_webengine_tabs [EXTRACTED 1.00]
- **Scenario Simulation Flow (Buckets -> Resolver -> Overlay -> Snapshot)** — simulatieframework_bucket_1, simulatieframework_bucket_2, simulatieframework_bucket_3, development_notes_scenario_order_resolver, simulatieframework_scenario_overlay_service [EXTRACTED 0.95]
- **ML Roll Advisor Data Foundation (Time Value + History + Regime + Strategy)** — todo_ml_roll_advisor, todo_option_price_history, development_notes_option_timevalue_service, trading_strategy_theta_harvesting, trading_strategy_regime_sets [INFERRED 0.78]

## Communities

### Community 0 - "Community 0"
Cohesion: 0.02
Nodes (66): ColoredPolarsTableModel, ColumnFilterPopup, HeaderFilterMenuMixin, Vereist in de host-widget:     - self.tableView: QTableView     - self._table_, Klik op de hele rij (niet alleen het checkboxvakje) toggelt de checkstate., CheckableSortItem, _create_table(), _fill_filter_combo() (+58 more)

### Community 1 - "Community 1"
Cohesion: 0.03
Nodes (69): get_connection(), _refresh_active_scenario_overlays(), refresh_aandelen_scenario_overlay_snapshot(), mark_bucket23_out_of_sync(), _empty_resolved_orders_df(), _ensure_caches_loaded(), _get_scenario_name(), refresh_active_scenario_orders_snapshot() (+61 more)

### Community 2 - "Community 2"
Cohesion: 0.03
Nodes (114): hydrate_snapshots(), compact_float64(), Zet alle Float64 kolommen om naar Float32 om geheugen te besparen., LiveAggregatorAandelen, Gespecialiseerde aggregator voor aandelen live data processing., initialize_live_prices(), Vul SNAPSHOT_STORE.live_prices altijd eerst met de laatste bekende prijzen uit d, LiveAggregatorOpties (+106 more)

### Community 3 - "Community 3"
Cohesion: 0.03
Nodes (27): Ui_MainWindow, PolarsTableModel, Qt-model dat data rechtstreeks uit een Polars DataFrame toont.     Te gebruiken, Optioneel alternatieve header labels meegeven per kolomnaam., object, PolarsTableModel, PercentColoredPolarsModel, PortfolioValueTab (+19 more)

### Community 4 - "Community 4"
Cohesion: 0.04
Nodes (75): connect_access(), load_universe(), main(), parse_args(), write_table(), estimate_delta(), Schat delta op basis van moneyness.      - Ondersteunt option_type in variante, _asset_has_option_eom_flow() (+67 more)

### Community 5 - "Community 5"
Cohesion: 0.03
Nodes (103): normalize_numeric_columns(), parse_iso_date(), quantize_decimal(), column_names(), create_tables(), ensure_per_dag_asset_result_v2_schema(), ensure_stock_splits_schema(), main() (+95 more)

### Community 6 - "Community 6"
Cohesion: 0.03
Nodes (75): connect_access(), format_nl_3(), intrinsic_value(), load_latest_option_snapshot(), load_latest_underlying_close(), load_open_option_positions(), load_universe_map(), main() (+67 more)

### Community 7 - "Community 7"
Cohesion: 0.03
Nodes (58): _build_returns_wide(), _build_snapshot_rows(), _ensure_beta_snapshot_table(), _infer_home_index(), _load_asset_metadata(), _load_historical_close(), _prepare_meta(), _prepare_prices() (+50 more)

### Community 8 - "Community 8"
Cohesion: 0.03
Nodes (23): HeaderFilterMenuMixin, HighlightingPandasTableModel, HighlightingPandasTableModel, MultiColFilterProxy, PandasTableModel, Houdt per kolom een set 'in'-waardes, 'eq' of 'contains' filter bij.     Werkt, Geef de geselecteerde rij als dict terug, of {} als out-of-range., Pandas model that can highlight specific rows by Id via BackgroundRole. (+15 more)

### Community 9 - "Community 9"
Cohesion: 0.03
Nodes (37): Standalone state engine tools for manual historical rebuilds., OptionChainTableModel, Option Chain Table Model Polars-based table model voor option chain display, Get all data for a specific row, Table model voor option chain data (Polars DataFrame), Update table met nieuwe DataFrame, OptionChainService, Option Chain Service Handles IBKR reqContractDetails for option chain retrieval (+29 more)

### Community 10 - "Community 10"
Cohesion: 0.04
Nodes (22): MainWindow, _TabBarNoFocusRectStyle, exportSnapshot(), openResolverDialog(), _OptieTijdswaardeWebBridge, OptieTijdswaardeWebPilotTab, commentEditing(), exportSnapshot() (+14 more)

### Community 11 - "Community 11"
Cohesion: 0.03
Nodes (61): error(), historicalDataEnd(), _infer_sec_type(), _is_index_symbol(), kick_off_more(), main(), nextValidId(), Submit one historical-data request for all_data row idx. (+53 more)

### Community 12 - "Community 12"
Cohesion: 0.05
Nodes (37): _AandelenWebBridge, AandelenWebPilotTab, _BetaScenarioWebBridge, BetaScenarioWebDialog, clearBrokers(), clearIndexShifts(), createBetaShiftScenario(), deleteActiveBetaShiftScenario() (+29 more)

### Community 13 - "Community 13"
Cohesion: 0.04
Nodes (48): AandelenProjectionV2, _all_brokers(), _apply_timevalue_overlay(), _expected_no_price_assets(), _has_technical_keys(), _normalize_changed_assets(), _price_diag(), Versioned projection for Aandelen view.      - Produces full snapshot DataFram (+40 more)

### Community 14 - "Community 14"
Cohesion: 0.06
Nodes (19): AssetResultViewer, main(), _range_with_aligned_zero(), resolve_db_path(), to_timestamp(), BetaMatrixViewer, main(), IndexRegressionViewer (+11 more)

### Community 15 - "Community 15"
Cohesion: 0.05
Nodes (48): Dev Notes v0.5: CRUD + Snapshot Sync Architecture, Dev Notes v0.10: Repository + Snapshot Store Architecture, Dev Notes v0.10: Live Aggregator Refactor, Archived: Live Optie Engine Integration Plan, Archived: Optimalisatie Engine (Migration Plan), Archived: Roadmap Engine + UI Modernisatie, Archived: Roadmap Modernisatie TODO, EngineCoreRuntime (+40 more)

### Community 16 - "Community 16"
Cohesion: 0.07
Nodes (13): OptieEindSortProxy, OptieEindTab, OptieEindTableModel, _state_classes_from_asset_types(), Ui_OptieEindTab, PandasTableModel, _build_default_state(), Reset alle snapshots naar leeg. (+5 more)

### Community 17 - "Community 17"
Cohesion: 0.1
Nodes (38): build_universe(), _clean(), compare_with_access_q3(), connect_access(), _friday_number(), load_asset_rollup_data(), load_latest_open_options_v2(), load_optie_referentie_data() (+30 more)

### Community 18 - "Community 18"
Cohesion: 0.12
Nodes (11): _apply_rebuild_result(), _clean(), _intrinsic(), _now_ts(), OpenSeriesRow, _option_week(), OptionTimevalueService, _pick_option_price() (+3 more)

### Community 19 - "Community 19"
Cohesion: 0.11
Nodes (20): _append_today_if_needed(), _coerce_to_date(), _date_label(), _iter_daily_dates(), _iter_friday_dates(), _iter_month_end_dates(), _iter_quarter_end_dates(), _iter_third_friday_dates() (+12 more)

### Community 20 - "Community 20"
Cohesion: 0.16
Nodes (13): _asset_rollup_price_insensitive(), build_uniek_id_like_repository(), CandidatePair, _clean(), _date_for_id(), DoorrolApplier, DoorrolFinder, main() (+5 more)

### Community 21 - "Community 21"
Cohesion: 0.16
Nodes (13): _asset_rollup_price_insensitive(), build_uniek_id_like_repository(), CandidatePair, _clean(), _date_for_id(), DoorrolApplier, DoorrolFinder, main() (+5 more)

### Community 22 - "Community 22"
Cohesion: 0.16
Nodes (11): AssignApplier, AssignFinder, AssignPair, build_uniek_id_like_repository(), _clean(), _date_for_id(), main(), _norm_dec_for_id() (+3 more)

### Community 23 - "Community 23"
Cohesion: 0.16
Nodes (12): build_uniek_id_like_repository(), CandidatePair, _clean(), _date_for_id(), DoorrolApplier, DoorrolFinder, main(), _norm_dec_for_id() (+4 more)

### Community 24 - "Community 24"
Cohesion: 0.15
Nodes (2): _normalize_date(), StateEngineTasksDialog

### Community 25 - "Community 25"
Cohesion: 0.16
Nodes (11): _asset_rollup_price_insensitive(), build_uniek_id_like_repository(), CandidatePair, _clean(), DoorrolApplier, DoorrolFinder, main(), normalize_side() (+3 more)

### Community 26 - "Community 26"
Cohesion: 0.16
Nodes (11): Applier, build_uniek_id_like_repository(), _clean(), Finder, main(), _norm_dec_for_id(), normalize_side(), ReviewWindow (+3 more)

### Community 27 - "Community 27"
Cohesion: 0.07
Nodes (2): Central application signals.      Keep this module minimal and free of project, Signals

### Community 28 - "Community 28"
Cohesion: 0.12
Nodes (9): _coerce_to_date(), _iter_daily_dates(), _iter_friday_dates(), _iter_third_friday_dates(), MaandEindTab, MaandEindTableModel, _schedule_dates(), _third_friday() (+1 more)

### Community 29 - "Community 29"
Cohesion: 0.16
Nodes (8): _clean(), ExpireApplier, ExpireCandidate, ExpireFinder, main(), ReviewWindow, _to_date(), to_float()

### Community 30 - "Community 30"
Cohesion: 0.16
Nodes (22): attach_effective_close(), build_state_intervals(), compute_sprinter_values(), create_temp_stage_table(), delete_target_range(), drop_stale_temp_stage_tables(), drop_temp_stage_table(), fetch_min_transaction_date() (+14 more)

### Community 31 - "Community 31"
Cohesion: 0.19
Nodes (8): _clean(), DoorrolOrderIssue, find_orders_with_call_put_mix(), IssueApplier, load_doorrol_rows(), main(), _normalize_cp(), ReviewWindow

### Community 32 - "Community 32"
Cohesion: 0.19
Nodes (13): AssetMeta, build_contract(), HistVolApp, load_asset_meta(), main(), parse_args(), print_summary(), resolve_exchange() (+5 more)

### Community 33 - "Community 33"
Cohesion: 0.23
Nodes (7): _build_contract(), main(), OptionProbeApp, parse_args(), _parse_market_data_types(), _to_num(), _ts()

### Community 34 - "Community 34"
Cohesion: 0.21
Nodes (12): _best_last(), _build_contract(), _connect_access(), _ensure_snapshot_table(), _load_universe(), main(), OptionLiveApp, parse_args() (+4 more)

### Community 35 - "Community 35"
Cohesion: 0.21
Nodes (10): AssetMeta, build_contract(), LiveAssetApp, load_asset_meta(), main(), parse_args(), resolve_exchange(), resolve_sec_type() (+2 more)

### Community 36 - "Community 36"
Cohesion: 0.2
Nodes (6): OptieTijdswaardeProjectionV2, _prepare_df(), Versioned projection for Optie Tijdswaarde., _row_id_of(), _same_value(), _to_row_map()

### Community 37 - "Community 37"
Cohesion: 0.42
Nodes (9): _clean(), connect_access(), fetch_open_option_series(), main(), parse_args(), seed_into_master(), SeedStats, _to_date() (+1 more)

### Community 38 - "Community 38"
Cohesion: 0.22
Nodes (8): coalesce_cols(), compute_equity_flows(), print_snapshot_columns(), print_snapshot_head(), Druk de eerste `n` records van een snapshot af., Druk de kolommen van een snapshot af in tabelvorm., Combineer meerdere kolommen in volgorde van prioriteit.     De eerste niet-null, Bereken cumulatieve equity flows (aandelen).     Output bevat buy/sell totals e

### Community 39 - "Community 39"
Cohesion: 0.28
Nodes (9): Beta Matrix Viewer App, historical_data_correct (STOCKDATA.accdb), Index Regression Viewer App, settings_shared.ini (beta drivers config), SettingsManager (shared/local ini), Price Distribution Viewer App, Market/Beta Simulation (Shock Scenarios), Asset Categories (Value/Growth/Speculative) (+1 more)

### Community 40 - "Community 40"
Cohesion: 0.48
Nodes (6): ensure_indexes(), main(), merge_delete_append(), merge_update_insert(), null_safe_diff(), Bouwt een NULL-veilige verschil-expressie voor Access/ODBC:       (main.col <>

### Community 41 - "Community 41"
Cohesion: 0.5
Nodes (3): CellPatchPayload, SnapshotInitPayload, ViewPatchPayload

### Community 42 - "Community 42"
Cohesion: 0.67
Nodes (3): DbMigrationService, Rationale: Multi-DB and Compatibility as Hard Constraint, User Database (portfolio, transactions)

### Community 43 - "Community 43"
Cohesion: 0.67
Nodes (3): Scenario Bucket 1 (Manual Test Orders), Scenario Bucket 2 (Generated Option Orders), Scenario Bucket 3 (Derived EOM Effects)

### Community 44 - "Community 44"
Cohesion: 0.67
Nodes (3): asset_rollup_data (ib_currency field), Sprinter GBP Pence-to-Pounds Bug, price_multiplier (GBP pence correction factor)

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
Nodes (1): Vraag marktdata aan voor subscriptions.          Ondersteunt:         - legacy:

### Community 51 - "Community 51"
Cohesion: 1.0
Nodes (1): Start option market-data subscriptions.          rows format: (series_id, conid,

### Community 52 - "Community 52"
Cohesion: 1.0
Nodes (0): 

### Community 53 - "Community 53"
Cohesion: 1.0
Nodes (0): 

### Community 54 - "Community 54"
Cohesion: 1.0
Nodes (1): StateEngineRunner

### Community 55 - "Community 55"
Cohesion: 1.0
Nodes (1): Dev Notes v0.11: In-Memory Polars Architecture

## Knowledge Gaps
- **156 isolated node(s):** `Standalone E2E helper to fetch executions from the last N days.     Returns a li`, `Laad config uit settings_shared.ini en settings_local.ini.`, `Sla huidige config gesplitst op naar shared en local.`, `Haal alle databases op als dictionary.`, `Haal naam van default database op.` (+151 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 45`** (2 nodes): `Deprecated placeholder.  De OpenAI-adviesfunctie is verwijderd uit deze variant`, `ai_option_advisor.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 46`** (2 nodes): `delete_all_records()`, `1 C - delete temp stock price table.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 47`** (1 nodes): `test_functions_to_be_copied_to_other_files.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 48`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 49`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 50`** (1 nodes): `Vraag marktdata aan voor subscriptions.          Ondersteunt:         - legacy:`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 51`** (1 nodes): `Start option market-data subscriptions.          rows format: (series_id, conid,`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 52`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 53`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 54`** (1 nodes): `StateEngineRunner`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 55`** (1 nodes): `Dev Notes v0.11: In-Memory Polars Architecture`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `MainWindow` connect `Community 10` to `Community 0`, `Community 1`, `Community 3`, `Community 6`, `Community 8`, `Community 12`, `Community 14`, `Community 16`, `Community 19`?**
  _High betweenness centrality (0.043) - this node is a cross-community bridge._
- **Why does `SectorAnalysisTab` connect `Community 3` to `Community 0`, `Community 1`, `Community 10`?**
  _High betweenness centrality (0.042) - this node is a cross-community bridge._
- **Why does `SingleAssetAnalyseTab` connect `Community 1` to `Community 8`, `Community 0`, `Community 10`, `Community 3`?**
  _High betweenness centrality (0.042) - this node is a cross-community bridge._
- **Are the 8 inferred relationships involving `SingleAssetAnalyseTab` (e.g. with `._register_tabs()` and `ColumnFilterPopup`) actually correct?**
  _`SingleAssetAnalyseTab` has 8 INFERRED edges - model-reasoned connections that need verification._
- **Are the 40 inferred relationships involving `GeneratedOptionOrdersDialog` (e.g. with `._open_generated_option_orders_popup()` and `._open_generated_options_dialog()`) actually correct?**
  _`GeneratedOptionOrdersDialog` has 40 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `SectorAnalysisTab` (e.g. with `._register_tabs()` and `PolarsTableModel`) actually correct?**
  _`SectorAnalysisTab` has 6 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `StateEngineRunner` (e.g. with `main()` and `SupportsProjectionRefresh`) actually correct?**
  _`StateEngineRunner` has 4 INFERRED edges - model-reasoned connections that need verification._