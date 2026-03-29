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
- verdere cleanup van `SingleAssetAnalyseTab`
- inhoudelijke resolver-workflow uitbreiding
- verdere timing van `build_aandelen_tab_summary(asset_rollup=...)`

Deze punten blijven open voor een volgende werkstroom.
