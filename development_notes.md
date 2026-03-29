# Development Notes

## Status 2026-03-29

Deze notitie beschrijft de huidige stand van de app na de updateflow- en legacy-cleanup snede.

### 1. Order-save updateflow

Gebouwd:

- order-save refresh is versmald per assettype
- combo/doorrol inserts zijn transaction-safe gemaakt
- `ordersCommitted` payload bevat nu committed DB-resultaat
- `repository_snapshot_alle_transacties` wordt patch-first bijgewerkt
- `refresh_transaction_derived_snapshots(...)` gebruikt de gepatchte in-memory transactiesnapshot
- fallback naar `load_alle_transacties()` blijft alleen bestaan als veilige lokale patch niet kan

Resultaat:

- normale order-save doet geen full transactiereload meer
- aandelen insert ging van ongeveer `1.17s` naar ongeveer `0.26s`
- optie insert zit rond `0.05-0.06s`

### 2. Historische snapshots en Aandelen-tab

Gebouwd:

- `repository_snapshot_historical_close` en `repository_snapshot_per_dag_asset_result_v2` worden bij load opgeschoond
- datumvelden worden gecast/parset
- `asset_rollup` wordt genormaliseerd
- numerieke velden worden vooraf gecast
- extra latest-per-asset snapshots toegevoegd:
  - `repository_snapshot_historical_close_latest`
  - `repository_snapshot_per_dag_asset_result_v2_latest`

Gevolg:

- Aandelen-tab hoeft bij een aandelenorder niet meer door de volle historische tabellen
- `aandelen_tab_summary.py` gebruikt voor `koers_prev` en historisch totaal alleen nog de kleine latest snapshots

### 3. Moderne live-tab architectuur

De runtime gebruikt voor de live tabellen nu alleen nog de moderne web tabs:

- `AandelenWebPilotTab`
- `OptiesOpenWebPilotTab`
- `OptieTijdswaardeWebPilotTab`
- `SprintersOpenWebPilotTab`

De oude live-tab Qt modules en bijbehorende oude UI-bestanden zijn verwijderd.

### 4. Live aggregators

De live aggregators zijn geconsolideerd:

- `PortfolioEngine` gebruikt nu dezelfde live aggregator instanties als de rest van de app
- dubbele instanties van:
  - `LiveAggregatorAandelen`
  - `LiveAggregatorOpties`
  - `LiveAggregatorSprinters`
  zijn verwijderd
- directe `snapshotUpdated` / `databaseChanged` listeners zijn uit deze aggregators gehaald

Nieuwe opzet:

1. startup / repository refresh pad
- repository snapshots worden herschreven
- daarna worden de relevante aggregators expliciet aangeroepen

2. live tick pad
- `PriceFeedService -> PortfolioEngine`
- `PortfolioEngine` batcht ticks
- dezelfde aggregators verwerken daarna de live update

### 5. OptionTimevalueService

Versmald:

- rebuild-trigger op `repository_snapshot_load_open_opties` verwijderd
- service gebruikt nu `repository_snapshot_historical_close_latest` in plaats van de volle `repository_snapshot_historical_close`
- directe `databaseChanged` listener verwijderd

De service rebuildt nu op gerichte snapshots en op `ordersCommitted`.

### 6. Database switch flow

Versmald:

- directe `databaseChanged` reloads verwijderd uit:
  - `OptionTimevalueService`
  - `PortfolioValueTab`
  - `SectorAnalysisTab`

Bewust behouden:

- `SingleAssetAnalyseTab.on_database_changed()`
  - voor comment-cache, test-order-cache en UI reset
- `StateEngineRunner.handle_database_changed()`
  - voor catchup/state-engine gedrag

### 7. Gevalideerde uitkomst

Smoke test geslaagd:

- DB-switch heen en terug werkt
- Aandelen werkt
- Single Asset Analyse werkt
- asset selector werkt
- test orders werken
- Open Opties werkt
- Optie Tijdswaarde werkt
- Portfolio Value werkt
- Sector Analysis werkt
- geen CLI errors

### 8. Open vervolgpunten

Niet in deze snede meegenomen:

- order-validatie / sanity checks
- inhoudelijke resolver-workflow uitbreiding
- verdere timing van `build_aandelen_tab_summary(asset_rollup=...)`

### 9. SingleAssetAnalyseTab cleanup gestart

Uitgevoerd als eerste opschoningsstap:

- `on_database_changed()` is opgesplitst in:
  - lokale/cache reset
  - filter/selector reset
  - post-switch view refresh
- `on_orders_committed()` doet niet meer direct `update_opties_open_table()`
  - maar gebruikt nu het bestaande dirty/timer patroon
- de code maakt nu explicieter onderscheid tussen:
  - snapshot-driven subviews
  - lokale/cached subviews

Concreet:

- snapshot-driven:
  - summary/aandelen refresh
  - open opties refresh
- lokaal/cached:
  - test orders
  - payoff
  - history charts
  - sprinters tabel

Deze cleanup is bewust nog geen volledige refactor, maar wel de eerste structurele versmalling van deze hybride tab.

Vervolgrefactor uitgevoerd:

- asset-selectie gebruikt nu expliciete helpers voor:
  - snapshot-driven redraw
  - test-orders view
  - lokale/cached subviews
- de directe vertakking in `on_asset_selected()` is kleiner geworden
- DB-switch gebruikt nu ook dezelfde test-orders helper in plaats van losse tabelvulling

Hierdoor is de updateflow in deze tab consistenter geworden, zonder functionele herbouw.

Gevalideerde uitkomst:

- assetwissel werkt correct
- `Single Asset Analyse` blijft goed en snel functioneren
- test orders werken correct:
  - add order
  - delete order
  - enable op assetniveau
  - enable per individuele order
- DB-switch werkt ook voor deze tab correct
- geen CLI errors

### 10. Open vervolgpunten

Open voor de volgende werkstroom:

- verdere cleanup van `SingleAssetAnalyseTab`
- order-validatie / sanity checks
- inhoudelijke resolver-workflow uitbreiding
- verdere timing van `build_aandelen_tab_summary(asset_rollup=...)`
