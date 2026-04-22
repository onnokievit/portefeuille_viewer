# Graph Report - C:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2  (2026-04-21)

## Corpus Check
- 138 files · ~433,305 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2848 nodes · 7038 edges · 91 communities detected
- Extraction: 73% EXTRACTED · 27% INFERRED · 0% AMBIGUOUS · INFERRED: 1926 edges (avg confidence: 0.75)
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
- [[_COMMUNITY_Community 73|Community 73]]
- [[_COMMUNITY_Community 74|Community 74]]
- [[_COMMUNITY_Community 75|Community 75]]
- [[_COMMUNITY_Community 76|Community 76]]
- [[_COMMUNITY_Community 77|Community 77]]
- [[_COMMUNITY_Community 78|Community 78]]
- [[_COMMUNITY_Community 79|Community 79]]
- [[_COMMUNITY_Community 80|Community 80]]
- [[_COMMUNITY_Community 81|Community 81]]
- [[_COMMUNITY_Community 82|Community 82]]
- [[_COMMUNITY_Community 83|Community 83]]
- [[_COMMUNITY_Community 84|Community 84]]
- [[_COMMUNITY_Community 85|Community 85]]
- [[_COMMUNITY_Community 86|Community 86]]
- [[_COMMUNITY_Community 87|Community 87]]
- [[_COMMUNITY_Community 88|Community 88]]
- [[_COMMUNITY_Community 89|Community 89]]
- [[_COMMUNITY_Community 90|Community 90]]

## God Nodes (most connected - your core abstractions)
1. `SingleAssetAnalyseTab` - 126 edges
2. `SectorAnalysisTab` - 71 edges
3. `SettingsManager` - 70 edges
4. `GeneratedOptionOrdersDialog` - 68 edges
5. `get_settings()` - 64 edges
6. `OrdersTabWidget` - 56 edges
7. `StateEngineRunner` - 55 edges
8. `ColumnFilterPopup` - 48 edges
9. `HeaderFilterMenuMixin` - 48 edges
10. `AandelenWebPilotTab` - 48 edges

## Surprising Connections (you probably didn't know these)
- `_apply_env_defaults_from_settings()` --calls--> `get_settings()`  [INFERRED]
  portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer_1.2.py → C:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\config\settings_manager.py
- `SupportsProjectionRefresh` --uses--> `MainWindow`  [INFERRED]
  portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer_1.2.py → C:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\ui_logica\main_window_logica.py
- `SupportsProjectionRefresh` --uses--> `PriceFeedService`  [INFERRED]
  portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer_1.2.py → portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\services\price_feed.py
- `SupportsProjectionRefresh` --uses--> `HistoricalPriceUpdateRunner`  [INFERRED]
  portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer_1.2.py → portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\services\historical_price_update_runner.py
- `SupportsProjectionRefresh` --uses--> `StateEngineRunner`  [INFERRED]
  portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer_1.2.py → portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\services\state_engine_runner.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.02
Nodes (162): hydrate_snapshots(), compact_float64(), Zet alle Float64 kolommen om naar Float32 om geheugen te besparen., LiveAggregatorAandelen, Gespecialiseerde aggregator voor aandelen live data processing., clear_live_prices(), initialize_live_prices(), Update de centrale live_prices store.     new_prices: dict met als key asset_id (+154 more)

### Community 1 - "Community 1"
Cohesion: 0.03
Nodes (54): ColoredPolarsTableModel, ColumnFilterPopup, HeaderFilterMenuMixin, Vereist in de host-widget:     - self.tableView: QTableView     - self._table_, Klik op de hele rij (niet alleen het checkboxvakje) toggelt de checkstate., ColoredPolarsTableModel, QDialog, QStyledItemDelegate (+46 more)

### Community 2 - "Community 2"
Cohesion: 0.03
Nodes (31): Ui_MainWindow, PolarsTableModel, Qt-model dat data rechtstreeks uit een Polars DataFrame toont.     Te gebruiken, Optioneel alternatieve header labels meegeven per kolomnaam., object, PolarsTableModel, PercentColoredPolarsModel, PortfolioValueTab (+23 more)

### Community 3 - "Community 3"
Cohesion: 0.03
Nodes (34): CheckableSortItem, ScenarioManagerDialog, _fmt(), LaatstTransactiesDialog, Geeft de Id's terug van alle aangevinkte rijen., QTableWidget — Space togglet vinkje op huidige rij, sortering via header., _TransactiesTable, QTableWidgetItem (+26 more)

### Community 4 - "Community 4"
Cohesion: 0.03
Nodes (87): OptieTijdswaardeProjectionV2, _prepare_df(), Versioned projection for Optie Tijdswaarde., _row_id_of(), _same_value(), _to_row_map(), OptiesOpenProjectionV2, _prepare_df() (+79 more)

### Community 5 - "Community 5"
Cohesion: 0.04
Nodes (53): get_connection(), _create_table(), _fill_filter_combo(), GeneratedOptionOrdersDialog, MultiSelectFilterDialog, _norm_option_exp(), open_scenario_dialog(), _scenario_content_safe_df() (+45 more)

### Community 6 - "Community 6"
Cohesion: 0.03
Nodes (55): close_scenario_dialog(), _append_today_if_needed(), close_month_end_chart_dialog(), _coerce_to_date(), _iter_daily_dates(), _iter_friday_dates(), _iter_month_end_dates(), _iter_quarter_end_dates() (+47 more)

### Community 7 - "Community 7"
Cohesion: 0.03
Nodes (103): normalize_numeric_columns(), parse_iso_date(), quantize_decimal(), column_names(), create_tables(), ensure_per_dag_asset_result_v2_schema(), ensure_stock_splits_schema(), main() (+95 more)

### Community 8 - "Community 8"
Cohesion: 0.03
Nodes (48): _build_returns_wide(), _build_snapshot_rows(), _ensure_beta_snapshot_table(), _infer_home_index(), _load_asset_metadata(), _load_historical_close(), _prepare_meta(), _prepare_prices() (+40 more)

### Community 9 - "Community 9"
Cohesion: 0.03
Nodes (26): HeaderFilterMenuMixin, HighlightingPandasTableModel, HighlightingPandasTableModel, MultiColFilterProxy, PandasTableModel, Houdt per kolom een set 'in'-waardes, 'eq' of 'contains' filter bij.     Werkt, Geef de geselecteerde rij als dict terug, of {} als out-of-range., Pandas model that can highlight specific rows by Id via BackgroundRole. (+18 more)

### Community 10 - "Community 10"
Cohesion: 0.03
Nodes (70): error(), historicalDataEnd(), _infer_sec_type(), _is_index_symbol(), kick_off_more(), main(), nextValidId(), Submit one historical-data request for all_data row idx. (+62 more)

### Community 11 - "Community 11"
Cohesion: 0.03
Nodes (22): MainWindow, _TabBarNoFocusRectStyle, exportSnapshot(), openResolverDialog(), _OptieTijdswaardeWebBridge, OptieTijdswaardeWebPilotTab, commentEditing(), exportSnapshot() (+14 more)

### Community 12 - "Community 12"
Cohesion: 0.03
Nodes (37): Standalone state engine tools for manual historical rebuilds., OptionChainTableModel, Option Chain Table Model Polars-based table model voor option chain display, Get all data for a specific row, Table model voor option chain data (Polars DataFrame), Update table met nieuwe DataFrame, OptionChainService, Option Chain Service Handles IBKR reqContractDetails for option chain retrieval (+29 more)

### Community 13 - "Community 13"
Cohesion: 0.05
Nodes (38): _AandelenWebBridge, AandelenWebPilotTab, _BetaScenarioWebBridge, BetaScenarioWebDialog, clearBrokers(), clearIndexShifts(), createBetaShiftScenario(), deleteActiveBetaShiftScenario() (+30 more)

### Community 14 - "Community 14"
Cohesion: 0.05
Nodes (39): connect_access(), format_nl_3(), intrinsic_value(), load_latest_option_snapshot(), load_latest_underlying_close(), load_open_option_positions(), load_universe_map(), main() (+31 more)

### Community 15 - "Community 15"
Cohesion: 0.03
Nodes (82): Archived Development Notes v1 (v0.5), Archived: Integratie Live Optie Engine Plan, Archived: Roadmap Engine + UI Modernisatie, asset_rollup_data Table, Beta/Market Simulation Feature (Planned), Beta Matrix Viewer, db_migration_service.py, Development Notes - Architecture Document (+74 more)

### Community 16 - "Community 16"
Cohesion: 0.06
Nodes (15): start_worker(), connect_access(), load_universe(), main(), parse_args(), write_table(), build_payload(), _connect() (+7 more)

### Community 17 - "Community 17"
Cohesion: 0.08
Nodes (36): AandelenProjectionV2, _all_brokers(), _apply_timevalue_overlay(), _expected_no_price_assets(), _has_technical_keys(), _normalize_changed_assets(), _price_diag(), Versioned projection for Aandelen view.      - Produces full snapshot DataFram (+28 more)

### Community 18 - "Community 18"
Cohesion: 0.07
Nodes (17): OptieEindSortProxy, OptieEindTab, OptieEindTableModel, _state_classes_from_asset_types(), Ui_OptieEindTab, PandasTableModel, AssetMeta, build_contract() (+9 more)

### Community 19 - "Community 19"
Cohesion: 0.1
Nodes (38): build_universe(), _clean(), compare_with_access_q3(), connect_access(), _friday_number(), load_asset_rollup_data(), load_latest_open_options_v2(), load_optie_referentie_data() (+30 more)

### Community 20 - "Community 20"
Cohesion: 0.09
Nodes (19): AssetRecord, build_contract(), build_yfinance_candidates(), DividendIbWorker, DividendResult, DividendToolWindow, ExceptionSuppressor, fetch_next_earnings_date() (+11 more)

### Community 21 - "Community 21"
Cohesion: 0.09
Nodes (10): AssetResultViewer, main(), _range_with_aligned_zero(), resolve_db_path(), to_timestamp(), BetaMatrixViewer, main(), IndexRegressionViewer (+2 more)

### Community 22 - "Community 22"
Cohesion: 0.16
Nodes (13): _asset_rollup_price_insensitive(), build_uniek_id_like_repository(), CandidatePair, _clean(), _date_for_id(), DoorrolApplier, DoorrolFinder, main() (+5 more)

### Community 23 - "Community 23"
Cohesion: 0.16
Nodes (13): _asset_rollup_price_insensitive(), build_uniek_id_like_repository(), CandidatePair, _clean(), _date_for_id(), DoorrolApplier, DoorrolFinder, main() (+5 more)

### Community 24 - "Community 24"
Cohesion: 0.16
Nodes (11): AssignApplier, AssignFinder, AssignPair, build_uniek_id_like_repository(), _clean(), _date_for_id(), main(), _norm_dec_for_id() (+3 more)

### Community 25 - "Community 25"
Cohesion: 0.16
Nodes (12): build_uniek_id_like_repository(), CandidatePair, _clean(), _date_for_id(), DoorrolApplier, DoorrolFinder, main(), _norm_dec_for_id() (+4 more)

### Community 26 - "Community 26"
Cohesion: 0.16
Nodes (11): _asset_rollup_price_insensitive(), build_uniek_id_like_repository(), CandidatePair, _clean(), DoorrolApplier, DoorrolFinder, main(), normalize_side() (+3 more)

### Community 27 - "Community 27"
Cohesion: 0.16
Nodes (11): Applier, build_uniek_id_like_repository(), _clean(), Finder, main(), _norm_dec_for_id(), normalize_side(), ReviewWindow (+3 more)

### Community 28 - "Community 28"
Cohesion: 0.07
Nodes (2): Central application signals.      Keep this module minimal and free of project, Signals

### Community 29 - "Community 29"
Cohesion: 0.12
Nodes (9): _coerce_to_date(), _iter_daily_dates(), _iter_friday_dates(), _iter_third_friday_dates(), MaandEindTab, MaandEindTableModel, _schedule_dates(), _third_friday() (+1 more)

### Community 30 - "Community 30"
Cohesion: 0.15
Nodes (16): build_contract(), _cell_decimals(), connect_access(), _fmt_nl(), _intrinsic(), load_latest_underlying_close(), load_universe(), main() (+8 more)

### Community 31 - "Community 31"
Cohesion: 0.14
Nodes (17): build_close_order(), build_contract_lookup(), build_parser(), _clean_ib_field(), estimate_relief(), IbSettings, load_ib_settings(), main() (+9 more)

### Community 32 - "Community 32"
Cohesion: 0.16
Nodes (8): _clean(), ExpireApplier, ExpireCandidate, ExpireFinder, main(), ReviewWindow, _to_date(), to_float()

### Community 33 - "Community 33"
Cohesion: 0.16
Nodes (22): attach_effective_close(), build_state_intervals(), compute_sprinter_values(), create_temp_stage_table(), delete_target_range(), drop_stale_temp_stage_tables(), drop_temp_stage_table(), fetch_min_transaction_date() (+14 more)

### Community 34 - "Community 34"
Cohesion: 0.17
Nodes (9): _days_in_month(), main(), _nice_step(), PriceDistributionViewer, PriceRow, resolve_db_path(), _safe_date(), _safe_float() (+1 more)

### Community 35 - "Community 35"
Cohesion: 0.19
Nodes (8): _clean(), DoorrolOrderIssue, find_orders_with_call_put_mix(), IssueApplier, load_doorrol_rows(), main(), _normalize_cp(), ReviewWindow

### Community 36 - "Community 36"
Cohesion: 0.29
Nodes (3): DbMigrationService, MigrationResult, Minimal multi-user DB migration bootstrap.      Rules:     - Additive only.

### Community 37 - "Community 37"
Cohesion: 0.42
Nodes (9): _clean(), connect_access(), fetch_open_option_series(), main(), parse_args(), seed_into_master(), SeedStats, _to_date() (+1 more)

### Community 38 - "Community 38"
Cohesion: 0.22
Nodes (8): coalesce_cols(), compute_equity_flows(), print_snapshot_columns(), print_snapshot_head(), Druk de eerste `n` records van een snapshot af., Druk de kolommen van een snapshot af in tabelvorm., Combineer meerdere kolommen in volgorde van prioriteit.     De eerste niet-null, Bereken cumulatieve equity flows (aandelen).     Output bevat buy/sell totals e

### Community 39 - "Community 39"
Cohesion: 0.48
Nodes (6): ensure_indexes(), main(), merge_delete_append(), merge_update_insert(), null_safe_diff(), Bouwt een NULL-veilige verschil-expressie voor Access/ODBC:       (main.col <>

### Community 40 - "Community 40"
Cohesion: 0.5
Nodes (3): CellPatchPayload, SnapshotInitPayload, ViewPatchPayload

### Community 41 - "Community 41"
Cohesion: 0.5
Nodes (4): LiveAggregatorAandelen, LiveAggregatorOpties, LiveAggregatorSprinters, portfolio_engine.py

### Community 42 - "Community 42"
Cohesion: 1.0
Nodes (1): Deprecated placeholder.  De OpenAI-adviesfunctie is verwijderd uit deze variant

### Community 43 - "Community 43"
Cohesion: 1.0
Nodes (0): 

### Community 44 - "Community 44"
Cohesion: 1.0
Nodes (2): AGENTS.md Graphify Rules, CLAUDE.md Graphify Rules

### Community 45 - "Community 45"
Cohesion: 1.0
Nodes (2): optie_tijdswaarde_projection_v2.py, Optie Tijdswaarde Tab

### Community 46 - "Community 46"
Cohesion: 1.0
Nodes (2): opties_open_projection_v2.py, Open Opties Tab

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
Nodes (1): Vraag marktdata aan voor subscriptions.          Ondersteunt:         - legacy:

### Community 52 - "Community 52"
Cohesion: 1.0
Nodes (1): Start option market-data subscriptions.          rows format: (series_id, conid,

### Community 53 - "Community 53"
Cohesion: 1.0
Nodes (0): 

### Community 54 - "Community 54"
Cohesion: 1.0
Nodes (0): 

### Community 55 - "Community 55"
Cohesion: 1.0
Nodes (1): Laad config uit settings_shared.ini en settings_local.ini.

### Community 56 - "Community 56"
Cohesion: 1.0
Nodes (1): Sla huidige config gesplitst op naar shared en local.

### Community 57 - "Community 57"
Cohesion: 1.0
Nodes (1): Haal alle databases op als dictionary.

### Community 58 - "Community 58"
Cohesion: 1.0
Nodes (1): Haal naam van default database op.

### Community 59 - "Community 59"
Cohesion: 1.0
Nodes (1): Voeg nieuwe database toe.

### Community 60 - "Community 60"
Cohesion: 1.0
Nodes (1): Update database configuratie.

### Community 61 - "Community 61"
Cohesion: 1.0
Nodes (1): Stel database in als default.

### Community 62 - "Community 62"
Cohesion: 1.0
Nodes (1): Zet alle is_default flags naar false.

### Community 63 - "Community 63"
Cohesion: 1.0
Nodes (1): Haal brokerlijst op uit settings.ini (comma-separated).

### Community 64 - "Community 64"
Cohesion: 1.0
Nodes (1): Retourneer lijst van (priority, label, bg_hex, fg_hex) voor comment-kleuren.

### Community 65 - "Community 65"
Cohesion: 1.0
Nodes (1): Map hex -> priority (int).

### Community 66 - "Community 66"
Cohesion: 1.0
Nodes (1): Map achtergrondkleur hex -> tekstkleur hex.

### Community 67 - "Community 67"
Cohesion: 1.0
Nodes (1): Sla comment-kleuren op naar user settings.          `colors` mag zijn:         -

### Community 68 - "Community 68"
Cohesion: 1.0
Nodes (1): Haal singleton settings manager op.

### Community 69 - "Community 69"
Cohesion: 1.0
Nodes (1): Laad config uit settings_shared.ini en settings_local.ini.

### Community 70 - "Community 70"
Cohesion: 1.0
Nodes (1): Sla huidige config gesplitst op naar shared en local.

### Community 71 - "Community 71"
Cohesion: 1.0
Nodes (1): Haal alle databases op als dictionary.

### Community 72 - "Community 72"
Cohesion: 1.0
Nodes (1): Haal naam van default database op.

### Community 73 - "Community 73"
Cohesion: 1.0
Nodes (1): Voeg nieuwe database toe.

### Community 74 - "Community 74"
Cohesion: 1.0
Nodes (1): Update database configuratie.

### Community 75 - "Community 75"
Cohesion: 1.0
Nodes (1): Stel database in als default.

### Community 76 - "Community 76"
Cohesion: 1.0
Nodes (1): Zet alle is_default flags naar false.

### Community 77 - "Community 77"
Cohesion: 1.0
Nodes (1): Haal brokerlijst op uit settings.ini (comma-separated).

### Community 78 - "Community 78"
Cohesion: 1.0
Nodes (1): Retourneer lijst van (priority, label, bg_hex, fg_hex) voor comment-kleuren.

### Community 79 - "Community 79"
Cohesion: 1.0
Nodes (1): Map hex -> priority (int).

### Community 80 - "Community 80"
Cohesion: 1.0
Nodes (1): Map achtergrondkleur hex -> tekstkleur hex.

### Community 81 - "Community 81"
Cohesion: 1.0
Nodes (1): Sla comment-kleuren op naar user settings.          `colors` mag zijn:         -

### Community 82 - "Community 82"
Cohesion: 1.0
Nodes (1): Haal singleton settings manager op.

### Community 83 - "Community 83"
Cohesion: 1.0
Nodes (1): Geeft de Id's terug van alle aangevinkte rijen.

### Community 84 - "Community 84"
Cohesion: 1.0
Nodes (1): Handmatige kolombreedtes voor `testOrdersTable`.         Pas de dict hieronder

### Community 85 - "Community 85"
Cohesion: 1.0
Nodes (1): Maak alleen deze tab scrollbaar (handig op laptop-schermen).          De UI va

### Community 86 - "Community 86"
Cohesion: 1.0
Nodes (1): Debug helper om cache/dirty status te loggen naar CLI.

### Community 87 - "Community 87"
Cohesion: 1.0
Nodes (1): Klik op asset in test-orders tabel: stel asset_selector in en reload.

### Community 88 - "Community 88"
Cohesion: 1.0
Nodes (1): Sla bewerkte comment op en herlaad de tabellen zodat alle views synchroon blijve

### Community 89 - "Community 89"
Cohesion: 1.0
Nodes (1): Werk comment/timestamp bij in alle optie modellen zonder volledige reload.

### Community 90 - "Community 90"
Cohesion: 1.0
Nodes (1): Header-menu met extra sorteeropties op kleur voor de commentkolom.

## Knowledge Gaps
- **202 isolated node(s):** `Standalone E2E helper to fetch executions from the last N days.     Returns a li`, `Dividend Viewer — standalone tool. Laadt assets uit de portefeuille-database (as`, `Parseert IBKR dividend string: trailing12m,forward12m,nextDate,nextAmount`, `Wordt aangeroepen wanneer het script met --worker wordt gestart.     Verbindt me`, `Laad config uit settings_shared.ini en settings_local.ini.` (+197 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 42`** (2 nodes): `Deprecated placeholder.  De OpenAI-adviesfunctie is verwijderd uit deze variant`, `ai_option_advisor.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 43`** (2 nodes): `delete_all_records()`, `1 C - delete temp stock price table.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 44`** (2 nodes): `AGENTS.md Graphify Rules`, `CLAUDE.md Graphify Rules`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 45`** (2 nodes): `optie_tijdswaarde_projection_v2.py`, `Optie Tijdswaarde Tab`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 46`** (2 nodes): `opties_open_projection_v2.py`, `Open Opties Tab`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 47`** (1 nodes): `test_functions_to_be_copied_to_other_files.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 48`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 49`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 50`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 51`** (1 nodes): `Vraag marktdata aan voor subscriptions.          Ondersteunt:         - legacy:`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 52`** (1 nodes): `Start option market-data subscriptions.          rows format: (series_id, conid,`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 53`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 54`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 55`** (1 nodes): `Laad config uit settings_shared.ini en settings_local.ini.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 56`** (1 nodes): `Sla huidige config gesplitst op naar shared en local.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 57`** (1 nodes): `Haal alle databases op als dictionary.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 58`** (1 nodes): `Haal naam van default database op.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 59`** (1 nodes): `Voeg nieuwe database toe.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 60`** (1 nodes): `Update database configuratie.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 61`** (1 nodes): `Stel database in als default.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 62`** (1 nodes): `Zet alle is_default flags naar false.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 63`** (1 nodes): `Haal brokerlijst op uit settings.ini (comma-separated).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 64`** (1 nodes): `Retourneer lijst van (priority, label, bg_hex, fg_hex) voor comment-kleuren.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 65`** (1 nodes): `Map hex -> priority (int).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 66`** (1 nodes): `Map achtergrondkleur hex -> tekstkleur hex.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 67`** (1 nodes): `Sla comment-kleuren op naar user settings.          `colors` mag zijn:         -`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 68`** (1 nodes): `Haal singleton settings manager op.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 69`** (1 nodes): `Laad config uit settings_shared.ini en settings_local.ini.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 70`** (1 nodes): `Sla huidige config gesplitst op naar shared en local.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 71`** (1 nodes): `Haal alle databases op als dictionary.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 72`** (1 nodes): `Haal naam van default database op.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 73`** (1 nodes): `Voeg nieuwe database toe.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 74`** (1 nodes): `Update database configuratie.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 75`** (1 nodes): `Stel database in als default.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 76`** (1 nodes): `Zet alle is_default flags naar false.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 77`** (1 nodes): `Haal brokerlijst op uit settings.ini (comma-separated).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 78`** (1 nodes): `Retourneer lijst van (priority, label, bg_hex, fg_hex) voor comment-kleuren.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 79`** (1 nodes): `Map hex -> priority (int).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 80`** (1 nodes): `Map achtergrondkleur hex -> tekstkleur hex.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 81`** (1 nodes): `Sla comment-kleuren op naar user settings.          `colors` mag zijn:         -`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 82`** (1 nodes): `Haal singleton settings manager op.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 83`** (1 nodes): `Geeft de Id's terug van alle aangevinkte rijen.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 84`** (1 nodes): `Handmatige kolombreedtes voor `testOrdersTable`.         Pas de dict hieronder`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 85`** (1 nodes): `Maak alleen deze tab scrollbaar (handig op laptop-schermen).          De UI va`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 86`** (1 nodes): `Debug helper om cache/dirty status te loggen naar CLI.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 87`** (1 nodes): `Klik op asset in test-orders tabel: stel asset_selector in en reload.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 88`** (1 nodes): `Sla bewerkte comment op en herlaad de tabellen zodat alle views synchroon blijve`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 89`** (1 nodes): `Werk comment/timestamp bij in alle optie modellen zonder volledige reload.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 90`** (1 nodes): `Header-menu met extra sorteeropties op kleur voor de commentkolom.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `SingleAssetAnalyseTab` connect `Community 1` to `Community 0`, `Community 2`, `Community 3`, `Community 5`, `Community 9`, `Community 11`?**
  _High betweenness centrality (0.051) - this node is a cross-community bridge._
- **Why does `GeneratedOptionOrdersDialog` connect `Community 5` to `Community 1`, `Community 2`, `Community 3`, `Community 13`?**
  _High betweenness centrality (0.046) - this node is a cross-community bridge._
- **Why does `SectorAnalysisTab` connect `Community 2` to `Community 11`, `Community 5`?**
  _High betweenness centrality (0.037) - this node is a cross-community bridge._
- **Are the 7 inferred relationships involving `SingleAssetAnalyseTab` (e.g. with `MainWindow` and `_TabBarNoFocusRectStyle`) actually correct?**
  _`SingleAssetAnalyseTab` has 7 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `SectorAnalysisTab` (e.g. with `MainWindow` and `_TabBarNoFocusRectStyle`) actually correct?**
  _`SectorAnalysisTab` has 6 INFERRED edges - model-reasoned connections that need verification._
- **Are the 18 inferred relationships involving `GeneratedOptionOrdersDialog` (e.g. with `AandelenWebPilotTab` and `._open_generated_option_orders_popup()`) actually correct?**
  _`GeneratedOptionOrdersDialog` has 18 INFERRED edges - model-reasoned connections that need verification._
- **Are the 55 inferred relationships involving `get_settings()` (e.g. with `_apply_env_defaults_from_settings()` and `_aandelen_tv_totals_in_sync()`) actually correct?**
  _`get_settings()` has 55 INFERRED edges - model-reasoned connections that need verification._