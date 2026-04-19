# Graph Report - C:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2  (2026-04-19)

## Corpus Check
- 134 files · ~403,837 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2657 nodes · 6674 edges · 73 communities detected
- Extraction: 72% EXTRACTED · 28% INFERRED · 0% AMBIGUOUS · INFERRED: 1875 edges (avg confidence: 0.74)
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
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 69|Community 69]]
- [[_COMMUNITY_Community 70|Community 70]]
- [[_COMMUNITY_Community 71|Community 71]]
- [[_COMMUNITY_Community 72|Community 72]]

## God Nodes (most connected - your core abstractions)
1. `SingleAssetAnalyseTab` - 127 edges
2. `GeneratedOptionOrdersDialog` - 90 edges
3. `SectorAnalysisTab` - 71 edges
4. `SettingsManager` - 62 edges
5. `OrdersTabWidget` - 56 edges
6. `StateEngineRunner` - 55 edges
7. `HeaderFilterMenuMixin` - 53 edges
8. `get_settings()` - 52 edges
9. `ColumnFilterPopup` - 49 edges
10. `AandelenWebPilotTab` - 48 edges

## Surprising Connections (you probably didn't know these)
- `Minimal WebEngine pilot tab.      - Uses a lightweight HTML frame/card layout.` --uses--> `GeneratedOptionOrdersDialog`  [INFERRED]
  portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\ui_logica\aandelen_web_pilot_tab.py → C:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\ui_logica\generated_option_orders_dialog.py
- `_apply_env_defaults_from_settings()` --calls--> `get_settings()`  [INFERRED]
  portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer_1.2.py → C:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\config\settings_manager.py
- `SupportsProjectionRefresh` --uses--> `MainWindow`  [INFERRED]
  portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer_1.2.py → C:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\ui_logica\main_window_logica.py
- `SupportsProjectionRefresh` --uses--> `PriceFeedService`  [INFERRED]
  portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer_1.2.py → portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\services\price_feed.py
- `SupportsProjectionRefresh` --uses--> `StateEngineRunner`  [INFERRED]
  portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer_1.2.py → portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\services\state_engine_runner.py

## Hyperedges (group relationships)
- **Event-Driven Runtime Pipeline (Events -> StateStore -> ProjectionBus -> Projections -> WebEngine)** — development_notes_engine_core_runtime, development_notes_state_store, development_notes_projection_bus, development_notes_projection_v2, development_notes_webengine_tabs [EXTRACTED 1.00]
- **Scenario Simulation Flow (Buckets -> Resolver -> Overlay -> Snapshot)** — simulatieframework_bucket_1, simulatieframework_bucket_2, simulatieframework_bucket_3, development_notes_scenario_order_resolver, simulatieframework_scenario_overlay_service [EXTRACTED 0.95]
- **ML Roll Advisor Data Foundation (Time Value + History + Regime + Strategy)** — todo_ml_roll_advisor, todo_option_price_history, development_notes_option_timevalue_service, trading_strategy_theta_harvesting, trading_strategy_regime_sets [INFERRED 0.78]

## Communities

### Community 0 - "Community 0"
Cohesion: 0.02
Nodes (75): Minimal WebEngine pilot tab.      - Uses a lightweight HTML frame/card layout., ColoredPolarsTableModel, ColumnFilterPopup, Klik op de hele rij (niet alleen het checkboxvakje) toggelt de checkstate., ColoredPolarsTableModel, QDialog, QStyledItemDelegate, QTableWidgetItem (+67 more)

### Community 1 - "Community 1"
Cohesion: 0.02
Nodes (155): hydrate_snapshots(), compact_float64(), Zet alle Float64 kolommen om naar Float32 om geheugen te besparen., HistoricalPriceUpdateRunner, _parse_last_json_line(), Run startup historical price update entirely in a separate process., request_startup_update(), LiveAggregatorAandelen (+147 more)

### Community 2 - "Community 2"
Cohesion: 0.03
Nodes (106): get_connection(), CheckableSortItem, _create_table(), _fill_filter_combo(), GeneratedOptionOrdersDialog, MultiSelectFilterDialog, _norm_option_exp(), _scenario_content_safe_df() (+98 more)

### Community 3 - "Community 3"
Cohesion: 0.02
Nodes (29): HeaderFilterMenuMixin, MultiColFilterProxy, PolarsTableModel, Qt-model dat data rechtstreeks uit een Polars DataFrame toont.     Te gebruiken, Optioneel alternatieve header labels meegeven per kolomnaam., Houdt per kolom een set 'in'-waardes, 'eq' of 'contains' filter bij.     Werkt, object, PolarsTableModel (+21 more)

### Community 4 - "Community 4"
Cohesion: 0.03
Nodes (47): _build_returns_wide(), _build_snapshot_rows(), _ensure_beta_snapshot_table(), _infer_home_index(), _load_asset_metadata(), _load_historical_close(), _prepare_meta(), _prepare_prices() (+39 more)

### Community 5 - "Community 5"
Cohesion: 0.03
Nodes (73): error(), historicalDataEnd(), _infer_sec_type(), _is_index_symbol(), kick_off_more(), main(), nextValidId(), Submit one historical-data request for all_data row idx. (+65 more)

### Community 6 - "Community 6"
Cohesion: 0.04
Nodes (39): HeaderFilterMenuMixin, Vereist in de host-widget:     - self.tableView: QTableView     - self._table_, HighlightingPandasTableModel, _fmt(), LaatstTransactiesDialog, Geeft de Id's terug van alle aangevinkte rijen., QTableWidget — Space togglet vinkje op huidige rij, sortering via header., _TransactiesTable (+31 more)

### Community 7 - "Community 7"
Cohesion: 0.03
Nodes (95): normalize_numeric_columns(), parse_iso_date(), quantize_decimal(), column_names(), create_tables(), ensure_per_dag_asset_result_v2_schema(), ensure_stock_splits_schema(), main() (+87 more)

### Community 8 - "Community 8"
Cohesion: 0.04
Nodes (45): build_continuous_series(), choose_conid_for_date(), ensure_temp_table(), FutContractInfo, IBSyncApp, main(), normalize_bar_date(), parse_args() (+37 more)

### Community 9 - "Community 9"
Cohesion: 0.05
Nodes (16): connect_access(), load_universe(), main(), parse_args(), write_table(), build_payload(), _connect(), get_oldest_last_price_date() (+8 more)

### Community 10 - "Community 10"
Cohesion: 0.05
Nodes (36): _AandelenWebBridge, AandelenWebPilotTab, _BetaScenarioWebBridge, BetaScenarioWebDialog, clearBrokers(), clearIndexShifts(), createBetaShiftScenario(), deleteActiveBetaShiftScenario() (+28 more)

### Community 11 - "Community 11"
Cohesion: 0.04
Nodes (48): AandelenProjectionV2, _all_brokers(), _apply_timevalue_overlay(), _expected_no_price_assets(), _has_technical_keys(), _normalize_changed_assets(), _price_diag(), Versioned projection for Aandelen view.      - Produces full snapshot DataFram (+40 more)

### Community 12 - "Community 12"
Cohesion: 0.05
Nodes (23): _clean(), connect_access(), load_table(), main(), _norm_cp(), _norm_float(), parse_args(), prep() (+15 more)

### Community 13 - "Community 13"
Cohesion: 0.04
Nodes (11): Central application signals.      Keep this module minimal and free of project, Signals, PandasTableModel, Geef de geselecteerde rij als dict terug, of {} als out-of-range., OptieEindSortProxy, OptieEindTab, OptieEindTableModel, _state_classes_from_asset_types() (+3 more)

### Community 14 - "Community 14"
Cohesion: 0.05
Nodes (26): Standalone state engine tools for manual historical rebuilds., OptionChainTableModel, Option Chain Table Model Polars-based table model voor option chain display, Get all data for a specific row, Table model voor option chain data (Polars DataFrame), Update table met nieuwe DataFrame, OptionChainService, Option Chain Service Handles IBKR reqContractDetails for option chain retrieval (+18 more)

### Community 15 - "Community 15"
Cohesion: 0.06
Nodes (17): _connect_option_last_prices_db(), _ensure_option_last_prices_table(), ensure_subscriptions(), _fx_aliases(), _on_option_tick(), _on_price(), _parse_cash_pair(), _pick_option_price_from_entry() (+9 more)

### Community 16 - "Community 16"
Cohesion: 0.05
Nodes (48): Dev Notes v0.5: CRUD + Snapshot Sync Architecture, Dev Notes v0.10: Repository + Snapshot Store Architecture, Dev Notes v0.10: Live Aggregator Refactor, Archived: Live Optie Engine Integration Plan, Archived: Optimalisatie Engine (Migration Plan), Archived: Roadmap Engine + UI Modernisatie, Archived: Roadmap Modernisatie TODO, EngineCoreRuntime (+40 more)

### Community 17 - "Community 17"
Cohesion: 0.09
Nodes (22): _append_today_if_needed(), _coerce_to_date(), _date_label(), _iter_daily_dates(), _iter_friday_dates(), _iter_month_end_dates(), _iter_quarter_end_dates(), _iter_third_friday_dates() (+14 more)

### Community 18 - "Community 18"
Cohesion: 0.1
Nodes (38): build_universe(), _clean(), compare_with_access_q3(), connect_access(), _friday_number(), load_asset_rollup_data(), load_latest_open_options_v2(), load_optie_referentie_data() (+30 more)

### Community 19 - "Community 19"
Cohesion: 0.09
Nodes (10): AssetResultViewer, main(), _range_with_aligned_zero(), resolve_db_path(), to_timestamp(), BetaMatrixViewer, main(), IndexRegressionViewer (+2 more)

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
Cohesion: 0.16
Nodes (11): _asset_rollup_price_insensitive(), build_uniek_id_like_repository(), CandidatePair, _clean(), DoorrolApplier, DoorrolFinder, main(), normalize_side() (+3 more)

### Community 25 - "Community 25"
Cohesion: 0.16
Nodes (11): Applier, build_uniek_id_like_repository(), _clean(), Finder, main(), _norm_dec_for_id(), normalize_side(), ReviewWindow (+3 more)

### Community 26 - "Community 26"
Cohesion: 0.12
Nodes (9): _coerce_to_date(), _iter_daily_dates(), _iter_friday_dates(), _iter_third_friday_dates(), MaandEindTab, MaandEindTableModel, _schedule_dates(), _third_friday() (+1 more)

### Community 27 - "Community 27"
Cohesion: 0.14
Nodes (17): build_close_order(), build_contract_lookup(), build_parser(), _clean_ib_field(), estimate_relief(), IbSettings, load_ib_settings(), main() (+9 more)

### Community 28 - "Community 28"
Cohesion: 0.16
Nodes (8): _clean(), ExpireApplier, ExpireCandidate, ExpireFinder, main(), ReviewWindow, _to_date(), to_float()

### Community 29 - "Community 29"
Cohesion: 0.16
Nodes (22): attach_effective_close(), build_state_intervals(), compute_sprinter_values(), create_temp_stage_table(), delete_target_range(), drop_stale_temp_stage_tables(), drop_temp_stage_table(), fetch_min_transaction_date() (+14 more)

### Community 30 - "Community 30"
Cohesion: 0.17
Nodes (9): _days_in_month(), main(), _nice_step(), PriceDistributionViewer, PriceRow, resolve_db_path(), _safe_date(), _safe_float() (+1 more)

### Community 31 - "Community 31"
Cohesion: 0.19
Nodes (8): _clean(), DoorrolOrderIssue, find_orders_with_call_put_mix(), IssueApplier, load_doorrol_rows(), main(), _normalize_cp(), ReviewWindow

### Community 32 - "Community 32"
Cohesion: 0.2
Nodes (3): exportSnapshot(), _SprintersOpenWebBridge, SprintersOpenWebPilotTab

### Community 33 - "Community 33"
Cohesion: 0.19
Nodes (13): AssetMeta, build_contract(), HistVolApp, load_asset_meta(), main(), parse_args(), print_summary(), resolve_exchange() (+5 more)

### Community 34 - "Community 34"
Cohesion: 0.23
Nodes (7): _build_contract(), main(), OptionProbeApp, parse_args(), _parse_market_data_types(), _to_num(), _ts()

### Community 35 - "Community 35"
Cohesion: 0.21
Nodes (10): AssetMeta, build_contract(), LiveAssetApp, load_asset_meta(), main(), parse_args(), resolve_exchange(), resolve_sec_type() (+2 more)

### Community 36 - "Community 36"
Cohesion: 0.2
Nodes (6): OptieTijdswaardeProjectionV2, _prepare_df(), Versioned projection for Optie Tijdswaarde., _row_id_of(), _same_value(), _to_row_map()

### Community 37 - "Community 37"
Cohesion: 0.29
Nodes (3): DbMigrationService, MigrationResult, Minimal multi-user DB migration bootstrap.      Rules:     - Additive only.

### Community 38 - "Community 38"
Cohesion: 0.42
Nodes (9): _clean(), connect_access(), fetch_open_option_series(), main(), parse_args(), seed_into_master(), SeedStats, _to_date() (+1 more)

### Community 39 - "Community 39"
Cohesion: 0.22
Nodes (8): coalesce_cols(), compute_equity_flows(), print_snapshot_columns(), print_snapshot_head(), Druk de eerste `n` records van een snapshot af., Druk de kolommen van een snapshot af in tabelvorm., Combineer meerdere kolommen in volgorde van prioriteit.     De eerste niet-null, Bereken cumulatieve equity flows (aandelen).     Output bevat buy/sell totals e

### Community 40 - "Community 40"
Cohesion: 0.28
Nodes (9): Beta Matrix Viewer App, historical_data_correct (STOCKDATA.accdb), Index Regression Viewer App, settings_shared.ini (beta drivers config), SettingsManager (shared/local ini), Price Distribution Viewer App, Market/Beta Simulation (Shock Scenarios), Asset Categories (Value/Growth/Speculative) (+1 more)

### Community 41 - "Community 41"
Cohesion: 0.48
Nodes (6): ensure_indexes(), main(), merge_delete_append(), merge_update_insert(), null_safe_diff(), Bouwt een NULL-veilige verschil-expressie voor Access/ODBC:       (main.col <>

### Community 42 - "Community 42"
Cohesion: 0.8
Nodes (4): main(), _p95(), _summary(), _summary_by_reason()

### Community 43 - "Community 43"
Cohesion: 0.5
Nodes (3): CellPatchPayload, SnapshotInitPayload, ViewPatchPayload

### Community 44 - "Community 44"
Cohesion: 0.67
Nodes (3): DbMigrationService, Rationale: Multi-DB and Compatibility as Hard Constraint, User Database (portfolio, transactions)

### Community 45 - "Community 45"
Cohesion: 0.67
Nodes (3): Scenario Bucket 1 (Manual Test Orders), Scenario Bucket 2 (Generated Option Orders), Scenario Bucket 3 (Derived EOM Effects)

### Community 46 - "Community 46"
Cohesion: 0.67
Nodes (3): asset_rollup_data (ib_currency field), Sprinter GBP Pence-to-Pounds Bug, price_multiplier (GBP pence correction factor)

### Community 47 - "Community 47"
Cohesion: 1.0
Nodes (1): Deprecated placeholder.  De OpenAI-adviesfunctie is verwijderd uit deze variant

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
Nodes (1): Vraag marktdata aan voor subscriptions.          Ondersteunt:         - legacy:

### Community 54 - "Community 54"
Cohesion: 1.0
Nodes (1): Start option market-data subscriptions.          rows format: (series_id, conid,

### Community 55 - "Community 55"
Cohesion: 1.0
Nodes (0): 

### Community 56 - "Community 56"
Cohesion: 1.0
Nodes (0): 

### Community 57 - "Community 57"
Cohesion: 1.0
Nodes (1): Laad config uit settings_shared.ini en settings_local.ini.

### Community 58 - "Community 58"
Cohesion: 1.0
Nodes (1): Sla huidige config gesplitst op naar shared en local.

### Community 59 - "Community 59"
Cohesion: 1.0
Nodes (1): Haal alle databases op als dictionary.

### Community 60 - "Community 60"
Cohesion: 1.0
Nodes (1): Haal naam van default database op.

### Community 61 - "Community 61"
Cohesion: 1.0
Nodes (1): Voeg nieuwe database toe.

### Community 62 - "Community 62"
Cohesion: 1.0
Nodes (1): Update database configuratie.

### Community 63 - "Community 63"
Cohesion: 1.0
Nodes (1): Stel database in als default.

### Community 64 - "Community 64"
Cohesion: 1.0
Nodes (1): Zet alle is_default flags naar false.

### Community 65 - "Community 65"
Cohesion: 1.0
Nodes (1): Haal brokerlijst op uit settings.ini (comma-separated).

### Community 66 - "Community 66"
Cohesion: 1.0
Nodes (1): Retourneer lijst van (priority, label, bg_hex, fg_hex) voor comment-kleuren.

### Community 67 - "Community 67"
Cohesion: 1.0
Nodes (1): Map hex -> priority (int).

### Community 68 - "Community 68"
Cohesion: 1.0
Nodes (1): Map achtergrondkleur hex -> tekstkleur hex.

### Community 69 - "Community 69"
Cohesion: 1.0
Nodes (1): Sla comment-kleuren op naar user settings.          `colors` mag zijn:         -

### Community 70 - "Community 70"
Cohesion: 1.0
Nodes (1): Haal singleton settings manager op.

### Community 71 - "Community 71"
Cohesion: 1.0
Nodes (1): StateEngineRunner

### Community 72 - "Community 72"
Cohesion: 1.0
Nodes (1): Dev Notes v0.11: In-Memory Polars Architecture

## Knowledge Gaps
- **172 isolated node(s):** `Standalone E2E helper to fetch executions from the last N days.     Returns a li`, `Laad config uit settings_shared.ini en settings_local.ini.`, `Sla huidige config gesplitst op naar shared en local.`, `Haal alle databases op als dictionary.`, `Haal naam van default database op.` (+167 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 47`** (2 nodes): `Deprecated placeholder.  De OpenAI-adviesfunctie is verwijderd uit deze variant`, `ai_option_advisor.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 48`** (2 nodes): `delete_all_records()`, `1 C - delete temp stock price table.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 49`** (1 nodes): `test_functions_to_be_copied_to_other_files.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 50`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 51`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 52`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 53`** (1 nodes): `Vraag marktdata aan voor subscriptions.          Ondersteunt:         - legacy:`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 54`** (1 nodes): `Start option market-data subscriptions.          rows format: (series_id, conid,`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 55`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 56`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 57`** (1 nodes): `Laad config uit settings_shared.ini en settings_local.ini.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 58`** (1 nodes): `Sla huidige config gesplitst op naar shared en local.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 59`** (1 nodes): `Haal alle databases op als dictionary.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 60`** (1 nodes): `Haal naam van default database op.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 61`** (1 nodes): `Voeg nieuwe database toe.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 62`** (1 nodes): `Update database configuratie.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 63`** (1 nodes): `Stel database in als default.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 64`** (1 nodes): `Zet alle is_default flags naar false.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 65`** (1 nodes): `Haal brokerlijst op uit settings.ini (comma-separated).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 66`** (1 nodes): `Retourneer lijst van (priority, label, bg_hex, fg_hex) voor comment-kleuren.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 67`** (1 nodes): `Map hex -> priority (int).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 68`** (1 nodes): `Map achtergrondkleur hex -> tekstkleur hex.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 69`** (1 nodes): `Sla comment-kleuren op naar user settings.          `colors` mag zijn:         -`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 70`** (1 nodes): `Haal singleton settings manager op.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 71`** (1 nodes): `StateEngineRunner`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 72`** (1 nodes): `Dev Notes v0.11: In-Memory Polars Architecture`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `OrdersTabWidget` connect `Community 6` to `Community 0`, `Community 2`, `Community 3`, `Community 4`?**
  _High betweenness centrality (0.047) - this node is a cross-community bridge._
- **Why does `SingleAssetAnalyseTab` connect `Community 0` to `Community 2`, `Community 3`, `Community 4`, `Community 6`?**
  _High betweenness centrality (0.037) - this node is a cross-community bridge._
- **Why does `MainWindow` connect `Community 4` to `Community 32`, `Community 0`, `Community 1`, `Community 3`, `Community 6`, `Community 10`, `Community 12`, `Community 13`, `Community 17`, `Community 19`?**
  _High betweenness centrality (0.037) - this node is a cross-community bridge._
- **Are the 8 inferred relationships involving `SingleAssetAnalyseTab` (e.g. with `MainWindow` and `_TabBarNoFocusRectStyle`) actually correct?**
  _`SingleAssetAnalyseTab` has 8 INFERRED edges - model-reasoned connections that need verification._
- **Are the 41 inferred relationships involving `GeneratedOptionOrdersDialog` (e.g. with `AandelenWebPilotTab` and `BetaScenarioWebDialog`) actually correct?**
  _`GeneratedOptionOrdersDialog` has 41 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `SectorAnalysisTab` (e.g. with `MainWindow` and `_TabBarNoFocusRectStyle`) actually correct?**
  _`SectorAnalysisTab` has 6 INFERRED edges - model-reasoned connections that need verification._
- **Are the 7 inferred relationships involving `OrdersTabWidget` (e.g. with `MainWindow` and `_TabBarNoFocusRectStyle`) actually correct?**
  _`OrdersTabWidget` has 7 INFERRED edges - model-reasoned connections that need verification._