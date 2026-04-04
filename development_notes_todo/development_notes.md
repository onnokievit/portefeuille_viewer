# Development Notes

## Doel van dit document
Dit document beschrijft de actuele, gebouwde architectuur van `portefeuille_viewer_1.2` en de huidige scenario-/simulatie-opzet. Het vervangt de oude ontwikkelnotities als primaire technische referentie voor wat er nu in de app aanwezig is en hoe de onderdelen met elkaar samenwerken.

De nadruk ligt op:
- de huidige architectuur,
- ontwerpkeuzes,
- dataflow,
- signaal- en eventflow,
- UI-werking,
- belangrijke technische details en trade-offs.

Verouderde plannen, experimenten en historische tussenstappen zijn bewust weggelaten, tenzij ze nodig zijn om een huidige ontwerpkeuze te verklaren.

## Scope
Actieve codebasis:
- `c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2`

Belangrijkste hoofdstructuur:
- `portefeuille_viewer_1.2.py`: app-startup en orkestratie
- `portefeuille_viewer/domain/`: event/runtime/projectie-fundament
- `portefeuille_viewer/services/`: prijsfeeds, option timevalue, state-engine, migraties
- `portefeuille_viewer/data/`: repository, snapshot store, aggregators, caches
- `portefeuille_viewer/ui_logica/`: Qt- en WebEngine-tablogica
- `portefeuille_viewer/projections/`: projection-v2 per hoofdtab
- `state_engine/`: zwaardere batch/state rebuild scripts

## 1. Hoofdbeeld van de app

De app is een desktop portfolio-analyseomgeving op PySide6, met twee gelijktijdige architectuurlagen:

1. de bestaande Qt-gebaseerde applicatieschil en legacy-tablogica;
2. een nieuwere event/projection-laag met WebEngine-tabbladen voor de zwaarste live views.

De codebase is dus geen volledige greenfield-herbouw. De feitelijke strategie is een gecontroleerde doorontwikkeling waarbij:
- bestaande functionele paden intact blijven waar dat nodig is;
- nieuwe performancekritieke views via projections en WebEngine worden ontsloten;
- centrale snapshots in geheugen de brug vormen tussen repository-, service- en UI-lagen;
- feature flags en promoted/cutover-flags bepalen welke tab op een bepaald moment actief is.

De kern van de huidige architectuur is dat de app niet één enkel datapad heeft, maar een gelaagd model:
- repository/snapshot laden bij startup of databasewissel;
- live updates vanuit price feed en optie-tick feed;
- state-engine rebuilds voor zwaardere, deterministische dag- of transactieberekeningen;
- projections die snapshots omzetten naar tab-specifieke, snel renderbare views;
- UI-tabbladen die alleen renderen wanneer ze actief zijn.

Dit is een expliciete ontwerpkeuze geweest om twee problemen tegelijk op te lossen:
- de oorspronkelijke app werd te zwaar in de UI-thread;
- een volledige big-bang migratie zou te risicovol zijn geweest voor bestaande validaties en gebruik.

## 2. Ontwerpfilosofie en design keuzes

### 2.1 Geen big-bang rewrite
De app is gemigreerd via parallelle architectuur in plaats van een volledige vervanging. Oude en nieuwe paden bestaan tijdelijk naast elkaar, zodat:
- uitkomsten kunnen worden vergeleken,
- tabbladen gefaseerd kunnen worden overgezet,
- rollback eenvoudig blijft.

Die keuze zie je direct terug in:
- environment flags in [`portefeuille_viewer_1.2.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer_1.2.py)
- promoted flags in [`main_window_logica.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\ui_logica\main_window_logica.py)

### 2.2 Snapshots als centrale datalaag
In plaats van elke tab zijn eigen query- en aggregatielogica te laten uitvoeren, is de centrale keuze geworden:
- datasets in geheugen laden;
- deze centraal bewaren in `SNAPSHOT_STORE`;
- tabbladen en services laten reageren op snapshotveranderingen.

Hiermee ontstaat een duidelijke grens:
- repository/service bouwt of ververst de data;
- UI leest data, maar is niet eigenaar van de businessberekening.

### 2.3 Event-driven, maar pragmatisch
Er is een generieke event/runtime-laag gebouwd, maar niet alles is daar volledig doorheen getrokken. Dat is bewust. De nieuwe runtime is gebruikt waar deze direct waarde oplevert:
- projection-v2 tabs,
- snapshot-refresh topics,
- throttle/coalescing op updatebronnen.

Legacy-paden blijven bestaan waar de migratiekosten hoger zouden zijn dan de directe opbrengst.

### 2.4 WebEngine alleen waar het zin heeft
Niet de hele app is omgezet naar WebEngine. Alleen de data-intensieve views zijn moderner gemaakt via:
- Aandelen Web
- Open Opties Web
- Optie Tijdswaarde Web
- Sprinters Open Web

De reden hiervoor is technisch:
- grote tabellen met frequente celupdates renderen prettiger via een HTML/JS-gridachtige laag;
- de rest van de app blijft prima bruikbaar als klassieke Qt UI.

### 2.5 Multi-DB en compatibiliteit als harde randvoorwaarde
De app werkt met meerdere databases en heeft een scheiding tussen:
- user/portfolio database(s),
- STOCKDATA database voor referentie- en marktdata-gerelateerde objecten.

Dat verklaart veel ontwerpkeuzes:
- additieve migraties,
- `DbMigrationService`,
- expliciete scheiding tussen portfolio-transactiedata en referentie-/masterdata,
- geen agressieve schemawijzigingen op legacy tabellen.

## 3. Startup en applicatielifecycle

De startupflow zit geconcentreerd in [`portefeuille_viewer_1.2.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer_1.2.py).

De belangrijke stappen zijn:

1. settings laden;
2. environment defaults uit de settingslaag (`settings_shared.ini` + lokale overrides) toepassen, tenzij shell env vars al gezet zijn;
3. globale services en aggregators initialiseren;
4. projection-v2 objecten en engine core runtime initialiseren;
5. databases migreren;
6. repositories en snapshots laden;
7. `PortfolioEngine`, `PriceFeedService`, `StateEngineRunner` en `OptionTimevalueService` koppelen;
8. hoofdvenster en tabs maken;
9. subscriptions naar de live price feed starten;
10. startup refresh/catchup processen uitvoeren.

Belangrijke ontwerpkeuze hier:
- settings leveren standaardwaarden;
- expliciete env vars overrulen deze defaults.

Dat maakt drie gebruiksvormen mogelijk:
- normaal starten zonder flags;
- tijdelijk debuggen met env overrides;
- gecontroleerde rollout van flags zonder codewijziging.

Bij afsluiten van de app doet `MainWindow.closeEvent()` nog expliciet flushes voor:
- test orders,
- open optie comments,
- single asset step settings,
- shutdown van price feed, portfolio engine en option timevalue service.

Hiermee is shutdown geen passieve UI-close, maar een gecoördineerde flush van in-memory state naar persistente opslag.


## 3A. Scenario testing architectuur

De scenario-architectuur in `portefeuille_viewer_1.2` is inmiddels expliciet opgesplitst in:
- persistente scenario-definities en scenario-content;
- een centrale scenario builder voor generated option orders;
- een runtime actieve scenario-selectie;
- app-brede overlay-services op snapshotniveau.

De codebase gebruikt dus niet langer alleen een lokaal experimenteel simulatiepad per tab. Het model is nu:
- test orders blijven fysiek opgeslagen in de bestaande test-order infrastructuur;
- scenario-meta staat los in een scenario-tabel;
- scenario-content wordt per `scenario_order_uid` opgeslagen;
- de runtime kiest exact één actief scenario;
- snapshot-overlays vertalen die keuze naar `Portfolio Value`, `Sector Analysis` en `Aandelen`.

### 3A.1 Persistente data en repositorylaag
De persistente scenario-opzet zit in [`test_order_repository.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\data\test_order_repository.py).

Belangrijke tabellen en velden:
- `transacties_test_order_scenarios`
- `transacties_test_order_scenario_content`
- `scenario_order_uid`
- bucket/source metadata op de test-order rijen zelf

Belangrijkste repositoryverantwoordelijkheden:
- schemahardening voor scenario-tabellen en missende uid's;
- laden van scenario-lijst en scenario-content naar snapshot-cache;
- in-memory create/rename/delete van scenario's;
- bewaren van scenario-content per zichtbare selectie;
- flush van dirty scenario-meta en dirty orders naar de database.

Hierdoor is het scenario-concept niet meer impliciet afgeleid uit één tabelweergave, maar een eerste-klas data-object met:
- scenario-meta;
- scenario-content;
- runtime actieve selectie.

### 3A.2 Runtime model
De actieve scenario-keuze leeft runtime in `SNAPSHOT_STORE` via:
- `runtime_active_test_order_scenario_id`
- `runtime_test_orders_enabled`

De resolverlaag in [`scenario_order_resolver.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\services\scenario_order_resolver.py) bepaalt op basis daarvan welke orders effectief actief zijn.

Dat is architectonisch belangrijk:
- UI kiest een scenario;
- repository levert scenario-meta en scenario-content;
- resolver maakt daar een effectieve orderset van;
- overlays projecteren dat naar scenario-aware tabbladen.

### 3A.3 Buckets en generated option flow
De bucket-opzet is nu:
- `bucket_1`: handmatige test orders;
- `bucket_2`: generated orders vanuit open optieposities;
- `bucket_3`: afgeleide child-effects van bucket 2, zoals EOM/market-close varianten.

De generated option sync zit in [`scenario_generated_option_sync.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\services\scenario_generated_option_sync.py) en wordt in de UI aangestuurd vanuit [`generated_option_orders_dialog.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\ui_logica\generated_option_orders_dialog.py).

Belangrijkste actuele status:
- de generated builder is nu een losse, centrale builder/editor;
- bucket 2 en 3 worden centraal opgebouwd en gesynchroniseerd;
- include/exclude-keuzes worden per scenario opgeslagen;
- de builder kan generated rows opnieuw syncen zonder handmatige bucket-1 orders kwijt te raken;
- bucket 3 checkstates lopen afgeleid mee met bucket 2 waar relevant.

Op dit moment is deze generated flow inhoudelijk gebouwd voor open opties.
Voor aandelen en sprinters bestaat nog geen equivalente generated scenario-builder.

### 3A.4 Builder-opzet en UI-integratie
De centrale builder zit in [`generated_option_orders_dialog.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\ui_logica\generated_option_orders_dialog.py) en wordt geopend vanuit `Single Asset Analyse`.

De builder bevat nu:
- scenario-selector;
- scenario-beheer;
- bucket 1, 2 en 3 tabellen;
- filterdialogen en bulkselectie voor bucket 2;
- globale `Test Orders` enable-toggle;
- sync-pad voor generated option rows;
- save-pad dat scenario-content bewaart en overlays direct ververst.

Belangrijke ontwerpkeuze:
- de builder is los van de inhoudelijke editflow in `Single Asset Analyse`;
- `Single Asset Analyse` blijft de inhoudelijke tab waar handmatige scenario-orders en payoff-context leven;
- de generated builder fungeert als centrale editor/sync-tool voor scenario-definitie en generated buckets.

### 3A.5 Integratie in tabs
De scenario builder staat niet op zichzelf, maar is aangesloten op de rest van de app.

Huidige integratie:
- `Single Asset Analyse`
  - beheert scenario-selector en actieve scenario-keuze;
  - opent de centrale builder;
  - bewaart handmatige scenario-selectie vanuit zichtbare rijen;
  - schrijft runtime actieve scenario-id naar `SNAPSHOT_STORE`.
- `Portfolio Value`
  - consumeert scenario-overlay via [`scenario_portfolio_value_overlay.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\services\scenario_portfolio_value_overlay.py)
- `Sector Analysis`
  - consumeert scenario-overlays via [`scenario_sector_overlay.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\services\scenario_sector_overlay.py)
- `Aandelen`
  - consumeert scenario-overlay via [`scenario_aandelen_overlay.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\services\scenario_aandelen_overlay.py)

Nog niet op dezelfde architectuurlijn scenario-aware aangesloten:
- `Sprinters Open`
- `Open Opties`
- `Optie Tijdswaarde`

### 3A.6 Signalen en updateflow
De scenario-opzet gebruikt expliciet signalen om builder, selector en overlays synchroon te houden.

Belangrijke flows:
- builder of scenario-manager wijzigt scenario's;
- repository-cache wordt geflusht en herladen;
- `testOrderScenariosChanged` wordt gequeued geëmiteerd;
- `Single Asset Analyse` herlaadt selector en behoudt waar mogelijk actieve selectie;
- actieve scenario-overlay snapshots worden direct opnieuw opgebouwd.

Daarnaast werkt de globale enable-toggle voor test orders runtime-breed:
- builder zet `runtime_test_orders_enabled`;
- overlay-services voor `Portfolio Value`, `Sector Analysis` en `Aandelen` worden direct vernieuwd.

### 3A.7 Ontwerpreden
Deze architectuur is gekozen omdat:
- lokale payoff- en editlogica in `Single Asset Analyse` al waardevol en inhoudelijk rijk was;
- app-brede consumers geen natuurlijke transactietabel-consumers zijn;
- injectie op transactieniveau te snel tot dubbel tellen of sync-problemen leidt;
- scenario-overlays op snapshotniveau beter passen bij de bestaande projection- en webtabarchitectuur;
- een losse builder voor generated option orders de scenario-opzet centraler en beheersbaarder maakt.


## 4. Snapshot-architectuur

De centrale geheugenlaag staat in [`snapshot_store.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\data\snapshot_store.py).

`SNAPSHOT_STORE` bevat zowel:
- repository snapshots,
- live aggregator snapshots,
- projection snapshots,
- meta snapshots,
- patch snapshots,
- tijdelijke caches voor test orders en comments.

Voorbeelden van belangrijke snapshots:
- `repository_snapshot_alle_transacties`
- `repository_snapshot_aandelen`
- `aggregator_snapshot_aandelen_live`
- `repository_snapshot_load_open_opties`
- `aggregator_snapshot_load_open_opties_from_tx_live`
- `repository_snapshot_open_sprinters`
- `repository_snapshot_asset_rollup_data`
- `repository_snapshot_optie_referentie_data`
- `repository_snapshot_sprinter_referentie_data`
- `repository_snapshot_per_dag_asset_result_v2`
- `snapshot_optie_timevalue_live`
- `snapshot_optie_timevalue_summary`
- `snapshot_optie_timevalue_meta`

De store biedt:
- gecentraliseerde in-memory state,
- eenvoudige reset bij DB-wissel,
- een samenvatting voor logging/debug,
- `safe_write()` om een snapshot weg te schrijven én een centraal `snapshotUpdated` signaal te emitten.

Die `safe_write()` keuze is belangrijk: een snapshot-update is niet alleen data-mutatie, maar ook een formele notificatie naar de rest van de app dat een specifiek snapshot-key vernieuwd is.

## 5. Event- en runtime-architectuur

De generieke runtimefundering zit in:
- [`events.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\domain\events.py)
- [`state_store.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\domain\state_store.py)
- [`projection_bus.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\domain\projection_bus.py)
- [`engine_core_runtime.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\domain\engine_core_runtime.py)

### 5.1 Eventmodel
Events zijn kleine immutable records met:
- timestamp,
- event type,
- key,
- payload,
- source.

Ondersteunde eventtypes zijn onder andere:
- `PRICE_TICK`
- `OPTION_TICK`
- `TRANSACTION_COMMITTED`
- `SNAPSHOT_REFRESH`
- `DB_CHANGED`
- `REBUILD_REQUESTED`

### 5.2 StateStore
`StateStore` is bewust klein gehouden:
- per namespace een bucket,
- versionering per namespace,
- changed keys teruggeven op basis van wat werkelijk gewijzigd is.

Dit betekent dat de store niet probeert een volledige domaintoestand te modelleren. Hij is een lichte event-absorber met changed key tracking, primair bedoeld om projections incrementeel aan te sturen.

### 5.3 ProjectionBus
`ProjectionBus` registreert projections en roept deze sequentieel aan. Elke projection geeft:
- een naam,
- `depends_on`,
- een `recompute()` methode.

De bus ondersteunt topic-filtering:
- als een snapshot-key of topic wordt meegegeven, krijgen alleen projections die daarvan afhankelijk zijn een recompute.

### 5.4 EngineCoreRuntime
`EngineCoreRuntime` hangt dit samen:
- event -> state store apply -> changed keys
- changed keys -> projection bus run
- bij snapshot refresh wordt per snapshot-key throttling toegepast

De throttle wordt gestuurd via:
- `ENGINE_CORE_SNAPSHOT_THROTTLE_MS`

Ontwerpintentie:
- veel bronnen kunnen updates genereren;
- niet elke update mag direct tot een projection recompute leiden;
- snapshot topics moeten kunnen worden teruggedrongen naar een beheersbare frequentie.

## 6. Projection-v2 architectuur

De projection-laag zit in:
- [`aandelen_projection_v2.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\projections\aandelen_projection_v2.py)
- [`opties_open_projection_v2.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\projections\opties_open_projection_v2.py)
- [`optie_tijdswaarde_projection_v2.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\projections\optie_tijdswaarde_projection_v2.py)
- [`sprinters_open_projection_v2.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\projections\sprinters_open_projection_v2.py)

Elke projection is verantwoordelijk voor:
- tab-specifieke datasetopbouw,
- patchgeneratie,
- metasamenvatting,
- beperkte, incrementele recompute op basis van changed keys of snapshot topics.

Het outputpatroon is per tab vergelijkbaar:
- volledige snapshot,
- patch snapshot,
- meta snapshot.

Dat is de cruciale contractlaag naar de WebEngine tabs.

### 6.1 Waarom projections?
Voorheen deden tabs veel werk zelf:
- joins,
- filtering,
- formatconversies,
- totalen,
- live merges.

Met projections is dit verplaatst naar een expliciete backendlaag, zodat de UI:
- minder businesslogica bevat,
- alleen data consumeert,
- eenvoudiger throttlebaar is,
- minder full resets hoeft te doen.

### 6.2 Metrics en observability
De projection-laag is ook meetbaar gemaakt. In `portefeuille_viewer_1.2.py` bestaan metrics-queues en logbestanden voor onder andere:
- aandelen projection
- open opties projection
- optie tijdswaarde projection
- sprinters projection

Daarmee kunnen recompute-, publish- en total timings worden gevolgd.

## 7. Service-laag

De service-laag bevat het grootste deel van de runtime-intelligentie.

### 7.1 Price feed
[`price_feed.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\services\price_feed.py) beheert:
- verbinding met IBKR,
- equity/index/future prijsupdates,
- option ticks,
- contract detail requests,
- secdef option parameter requests,
- local caches voor last/bid/ask/close,
- option last-price persistence.

Belangrijke ontwerpkeuzes:
- price feed is bron voor live updates, maar niet de enige bron voor alle berekeningen;
- voor opties bestaat expliciet ook een fallback naar `option_last_prices`;
- voor aandelen en asset rollups lopen subscriptions via de verzamelde symbolen uit `asset_rollup_data`.

### 7.2 Option timevalue service
[`option_timevalue_service.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\services\option_timevalue_service.py) is een kerncomponent.

Deze service:
- bouwt de universe van open optieseries;
- verrijkt deze met data uit master- en referentietabellen;
- subscribeert indirect op option ticks;
- berekent live time value, intrinsic, greeks en samenvattingen;
- publiceert snapshots voor de optie tijdswaarde-laag;
- beheert unresolved series en de handmatige resolverflow.

De service heeft interne timers voor:
- rebuild coalescing,
- publish batching,
- periodieke full publish.

Ook de unresolved flow zit hier:
- een serie wordt geclassificeerd als unresolved met een concrete reden;
- voorbeelden zijn `missing_reference_mapping` of ontbrekende contractdetails;
- unresolved series komen in `snapshot_optie_timevalue_meta`;
- UI kan daarop een badge/melding tonen;
- via een handmatige resolverdialoog kan een kandidaat-contract naar `option_series_master` worden weggeschreven.

Daarnaast bestaat expliciet de kolom/flag `resolver_locked`, zodat handmatige masterdata niet zomaar door de automatische resolver overschreven wordt.

### 7.3 State engine runner
[`state_engine_runner.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\services\state_engine_runner.py) coördineert zware rebuilds buiten de UI.

De runner ondersteunt:
- queueing van rebuild payloads,
- normalisatie van asset classes en affected assets,
- deferred order-driven rebuilds,
- pending order rebuild queue in Access,
- startup daily catchup flow,
- DB-wissel catchup flow,
- state run registratie.

Dit is een belangrijk scheidingsvlak in de architectuur:
- lichte live UI/projectie updates lopen in-memory;
- zwaardere consistente state rebuilds worden apart, asynchroon en expliciet uitgevoerd.

### 7.4 DB migration service
[`db_migration_service.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\services\db_migration_service.py) zorgt voor:
- startup migraties,
- versiecontrole per user DB,
- success/fail logging.

De migratiestrategie is additief en compatibiliteitsgericht. Dat is een harde ontwerpregel in de codebase.

## 8. Portfolio engine en aggregators

De oudere live-aggregatorlaag is nog steeds relevant en vormt een brug tussen price feed en snapshot/presentation data.

[`portfolio_engine.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\domain\portfolio_engine.py) orkestreert:
- `LiveAggregatorAandelen`
- `LiveAggregatorOpties`
- `LiveAggregatorSprinters`

De engine doet nadrukkelijk niet meer:
- eigen DataFrame beheer,
- zelfstandige businessberekeningen,
- directe opslag.

Wel doet hij:
- subscriptions verzamelen,
- live prices doorzetten naar aggregators,
- updates batchen,
- één gecombineerd `dataUpdated` signaal uitsturen.

Dit is architectonisch belangrijk, omdat het laat zien dat de oude monolithische “portfolio engine” opgesplitst is in:
- orchestratie,
- gespecialiseerde aggregators,
- snapshots,
- projection-laag erbovenop.

## 9. UI-architectuur

### 9.1 Qt shell
De applicatieschil is nog steeds PySide6. `MainWindow` maakt de tabs, verzorgt tab switching en handelt shutdown af.

### 9.2 Feature flags en promoted tabs
In [`main_window_logica.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\ui_logica\main_window_logica.py) wordt per tab bepaald:
- gebruik ik de legacy tab?
- gebruik ik de web tab als extra pilot?
- of promoot ik de web tab zodat deze de legacy tab vervangt?

Dat gebeurt met flags zoals:
- `PV_UI_AANDELEN_WEB_V1`
- `UI_AANDELEN_PROMOTED_V1`
- `UI_OPTIES_WEB_V1`
- `UI_OPTIES_PROMOTED_V1`
- `UI_OPTIE_TIJDSWAARDE_WEB_V1`
- `UI_OPTIE_TIJDSWAARDE_PROMOTED_V1`
- `UI_SPRINTERS_WEB_V1`
- `UI_SPRINTERS_PROMOTED_V1`

Hierdoor kan dezelfde codebase meerdere deploymentstanden ondersteunen.

### 9.3 Actieve en inactieve tabs
Een belangrijke optimalisatie is dat tabs een `set_active()` patroon hebben. Het hoofdvenster roept bij tabwissel voor relevante tabs `set_active(True/False)` aan.

Doel:
- inactieve tabs hoeven niet voortdurend te renderen;
- snapshots kunnen wel worden bijgewerkt;
- de tab haalt een actuele snapshot op zodra deze weer actief wordt.

Dit is cruciaal voor performance en voorkomt onnodige WebEngine renders.

## 10. WebEngine tabs

De moderne tabbladen zijn geen pure browserapplicaties, maar embedded HTML/JS views binnen PySide6.

Voorbeelden:
- [`aandelen_web_pilot_tab.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\ui_logica\aandelen_web_pilot_tab.py)
- [`opties_open_web_pilot_tab.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\ui_logica\opties_open_web_pilot_tab.py)
- [`optie_tijdswaarde_web_pilot_tab.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\ui_logica\optie_tijdswaarde_web_pilot_tab.py)
- [`sprinters_open_web_pilot_tab.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\ui_logica\sprinters_open_web_pilot_tab.py)

Gemeenschappelijk patroon:
- `QWebEngineView`
- optioneel `QWebChannel`
- `renderSnapshot(...)`
- `applyPatch(...)`
- `renderMeta(...)`
- pending JS queue totdat de pagina klaar is
- active render timer via `UI_WEB_ACTIVE_RENDER_MS`

Dat betekent concreet:
- de backend bouwt snapshots,
- de web tab vertaalt die naar JSON,
- JavaScript rendert de tabel/metadata,
- patches kunnen cellen of beperkte delen bijwerken zonder volledige herbouw.

Voor Open Opties is bewust gekozen om patches soms alsnog als volledige rerender toe te passen, omdat die tab een legacy-shaped getransformeerde dataset gebruikt. Dat is een pragmatische keuze: functioneel correct en eenvoudiger te beheren dan een half-correcte ingewikkelde patchlogica.

### 10.1 Maand Eind webtab
`Maand Eind` is inmiddels ook een volwaardige WebEngine-tab geworden via [`maand_eind_web_tab.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\ui_logica\maand_eind_web_tab.py).

Deze tab leest uit:
- `repository_snapshot_per_dag_asset_result_v2`
- `repository_snapshot_asset_rollup_data`

De tab bouwt geen projection-v2 output, maar een eigen, snapshotgedreven webview met een relatief zware matrixopbouw. Daarom is gekozen voor:
- lazy rendering alleen wanneer de tab actief is;
- debounce/coalescing via een lokale render timer;
- web-rendering in plaats van een grote Qt `QTableView`.

### 10.2 Functionele opzet van Maand Eind
De tab toont historische eindwaardematrices en verschilmatrices op twee niveaus:
- assetniveau
- sectorniveau

Per niveau zijn er twee tabellen:
- links de eindwaarden;
- rechts het verschil ten opzichte van de vorige meetdatum.

De huidige layout is dus:
- asset eindwaarden
- asset diff
- sector totaal
- sector diff

De sectorblokken staan onder de assetblokken en gebruiken dezelfde kolomstructuur, zodat horizontale scroll per zijde kan worden gesynchroniseerd.

### 10.3 Data-opbouw
De tab bouwt de matrix rechtstreeks op uit `per_dag_asset_result_v2.totaal_v2`, verrijkt met metadata uit `asset_rollup_data`.

Belangrijke metadata:
- `asset_rollup`
- `value_grow`
- `sector`
- `regio`

Belangrijke berekeningskeuzes:
- voor assets met `regio == "US"` wordt `totaal_v2` gedeeld door `EURUSD` uit de settings, zodat de weergegeven waarde aansluit op de rest van de app;
- meetmomenten worden als schedule opgebouwd op basis van de gekozen frequentie;
- als een meetmoment geen exacte rij heeft, wordt de laatst bekende waarde via carry-forward gebruikt;
- als de gekozen einddatum vandaag omvat, wordt `vandaag` als extra laatste meetkolom toegevoegd;
- diff-kolommen worden berekend als verschil met de vorige zichtbare meetkolom.

Voor sectorniveau wordt eerst gefilterd op assets en daarna gegroepeerd naar exact één regel per sector. Regio- en value/grow-filters werken dus door op de sector-totalen, maar de sectorfilter bovenin geldt alleen voor de assettabellen.

### 10.4 Frequenties
De frequentieplanner in de tab ondersteunt nu:
- `Elke dag`
- `Elke vrijdag`
- `3e vrijdag maand`
- `Laatste dag maand`
- `Laatste dag kwartaal`
- `Laatste dag jaar`

Hiermee kan de tab dezelfde brondata op meerdere rapportagemomenten projecteren zonder aparte opslag per rapportagefrequentie.

### 10.5 UI-gedrag en interactie
De tab heeft een web-toolbar met:
- start date
- eind date
- frequentie
- filters voor regio, value/grow en sector
- asset filter
- refresh knop

Daarnaast bevat de tab:
- sticky header;
- sticky eerste kolom;
- sticky totaalrij onderaan;
- sortering op waarden en diff-kolommen;
- gescheiden sortering voor asset- en sectorblokken;
- gesynchroniseerde verticale scroll binnen linker/rechter paren;
- gesynchroniseerde horizontale scroll tussen boven- en onderblokken per zijde.

De diff-tabellen tonen bewust minder metadata dan de waarde-tabellen, maar onder water blijft de volledige dataset behouden voor filtering en sortering.

## 11. Signal flow

De app gebruikt Qt-signalen als ruggegraat tussen subsystemen.

Belangrijke signalen en flows:

### 11.1 Snapshot flow
- repository/service schrijft nieuwe snapshot naar `SNAPSHOT_STORE`
- `SNAPSHOT_STORE.safe_write()` emit `snapshotUpdated(snapshot_key)`
- runtime/services/tabs reageren op specifieke snapshot keys

### 11.2 Price flow
- IBKR tick komt binnen in `PriceFeedIB`
- price feed emit `priceUpdated(...)` of `optionTickUpdated(payload)`
- aggregators en option timevalue service reageren
- nieuwe live data wordt in snapshots verwerkt
- projections worden via topics/snapshot refresh aangestuurd

### 11.3 Order flow
- gebruiker commit een order
- order komt in database
- `ordersCommitted` wordt geëmit
- afhankelijk van configuratie:
  - repositories en test order caches verversen,
  - option universe rebuild start,
  - state rebuild wordt aangevraagd,
  - projections en tabs trekken nieuwe snapshots binnen

### 11.4 DB-wissel
- actieve database wijzigt
- snapshots worden gecleard en opnieuw geladen
- migrations/checks draaien
- startup/daily catchup flow wordt opnieuw bepaald
- tabs en services resetten of rebuilden relevante state

### 11.5 Resolver flow
- option timevalue service detecteert unresolved serie
- meta snapshot bevat unresolved list
- web UI toont melding/badge
- gebruiker opent handmatige resolver
- kandidaat-contract wordt gekozen
- service schrijft kandidaat weg naar master en kan lock zetten
- rebuild wordt opnieuw uitgevoerd

## 12. Dataflow

De belangrijkste dataflow in de huidige app is als volgt:

### 12.1 Persistente brondata
Bronnen:
- user DB: transacties, outputtabellen, comments, test orders
- STOCKDATA DB: referentiedata, series master, price history/last prices
- IBKR: live asset- en option ticks

### 12.2 In-memory snapshots
Bij startup en DB-wissel worden de belangrijkste datasets geladen in `SNAPSHOT_STORE`.

### 12.3 Verrijking en live merge
Aggregators en services verrijken de statische snapshots met:
- live prices,
- calculated portfolio values,
- option timevalue velden,
- projection-specifieke meta-informatie.

### 12.4 Projection output
Projection-v2 zet die interne datasets om naar UI-geschikte taboutputs.

### 12.5 UI render
Tabs renderen uitsluitend hun eigen projection snapshot of hun eigen centrale snapshot.

Belangrijk gevolg:
- dezelfde brondata kan door meerdere tabs op verschillende manieren worden gepresenteerd,
- zonder dat elke tab opnieuw het volledige businesspad hoeft te draaien.

## 13. Rol van Single Asset Analyse

`Single Asset Analyse` blijft een hybride tab en is technisch gezien bijzonder:
- het is een klassieke Qt-tab;
- het combineert tabellen, payoff-tabellen, test-orderinvoer en grafieken;
- het gebruikt deels moderne projection/snapshot data en deels eigen UI-logica.

De tab is nog niet gemigreerd naar WebEngine en heeft daarom een andere karakteristiek:
- intensieve UI-bewerkbaarheid,
- veel lokale formatting/delegates,
- direct editgedrag op test orders,
- tabellen voor open/gesloten posities, calls, puts, aandelen en sprinters.

Daarmee is deze tab functioneel rijk, maar architectonisch nog gemengd. Dit is relevant voor toekomstig modernisatiewerk.

## 14. Database-strategie

De app werkt niet met één databaseverhaal.

Er is een functionele scheiding tussen:

### 14.1 User DB
Bevat onder andere:
- transacties,
- outputtabellen,
- test order gegevens,
- portfolio-data,
- state-engine resultaten.

### 14.2 STOCKDATA DB
Bevat onder andere:
- `option_series_master`
- `option_last_prices`
- referentietabellen en marktgerelateerde objecten

Deze scheiding is bewust en blijft relevant. Niet alle data hoort thuis in de user DB. Vooral optie-masterdata en bredere markt/prijsreferenties worden buiten de user DB gehouden.

Daarmee is de app niet alleen een GUI boven één portfoliofile, maar een applicatie die bewust meerdere datadomeinen combineert.

## 15. Belangrijke technische details

### 15.1 Settings manager en configuratiebestanden
De settingslaag zit in [`settings_manager.py`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\config\settings_manager.py) en is recent herwerkt naar een expliciete twee-bestandenopzet:
- [`settings_shared.ini`](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\portefeuille_viewer\config\settings_shared.ini)
- `portefeuille_viewer/config/.user_settings/settings_local.ini`

De oude situatie met twee verschillende `settings.ini`-bestanden bleek te onduidelijk, omdat dezelfde keys op meerdere plekken konden voorkomen. De huidige opzet maakt het onderscheid expliciet:
- shared settings zijn bedoeld om mee te gaan met de codebase en desgewenst in Git te staan;
- local settings zijn machine-specifiek en worden lokaal aangemaakt.

### 15.1.1 Laad- en migratiemodel
De settingsmanager werkt nu als volgt:
1. laad `settings_shared.ini`;
2. laad daarna `settings_local.ini`;
3. als `settings_local.ini` nog niet bestaat, maak die automatisch aan;
4. als een oude setup met `config/settings.ini` en/of `.user_settings/settings.ini` wordt aangetroffen, migreer die éénmalig naar de nieuwe shared/local-bestanden.

Belangrijke ontwerpkeuze:
- dezelfde key hoort in principe óf in shared óf in local;
- de code splitst config actief op tijdens save, in plaats van willekeurig twee volledige configbestanden naast elkaar te laten bestaan.

### 15.1.2 Verdeling shared versus local
De settingsmanager splitst momenteel grofweg als volgt:

Shared:
- `databases`
- `comment_colors`
- `env_defaults`
- `app.eurusd`
- `ui.tab_order`

Local:
- `interactive_brokers`
- visuele `ui`-settings zoals theme, font size en tabkleuren
- `aandelen_web_col_widths`
- `app.last_database`

Deze verdeling sluit aan op het beoogde gebruik:
- functionele instellingen en portfolio-inrichting wil je vaak tussen machines delen;
- machine- en schermafhankelijke UI-afstellingen juist niet.

### 15.1.3 Save-gedrag
`SettingsManager.save()` schrijft niet simpelweg één ini weg, maar splitst de actuele config opnieuw in:
- shared-config;
- local-config.

Dat betekent dat de settingsmanager niet alleen een read-API is, maar ook de architectonische grens bewaakt tussen gedeelde en lokale settings.

### 15.1.4 Relatie met startup en env defaults
Bij startup worden env defaults uit de settings geladen via `_apply_env_defaults_from_settings()`. Daardoor werkt de app:
- zonder lange startup-flagregel,
- met consistente gedeelde defaults uit `settings_shared.ini`,
- maar blijft shell override mogelijk voor debugging en experiments.

### 15.1.5 Tabvolgorde
De hoofdwindow ondersteunt inmiddels versleepbare tabs. De volgorde wordt opgeslagen via `ui.tab_order` in de settingsmanager.

Architectonisch betekent dit:
- `MainWindow` kent stabiele tab-id's;
- de actuele visuele volgorde wordt uit de `QTabWidget` gelezen;
- die volgorde wordt persistent opgeslagen;
- bij startup wordt de tabbar in die volgorde hersteld;
- keyboardnavigatie via `ESC`, pijltjes en `Ctrl+PageUp/PageDown` volgt automatisch de actuele visuele volgorde.

### 15.2 Logging en metrics
Projection metrics bestaan, maar console logging ervan is togglebaar. De code is ingericht zodat metrics wel verzameld kunnen worden zonder standaard de terminal te spammen.

### 15.3 Throttling
Er zijn meerdere throttlelagen:
- engine core snapshot throttle,
- web tab active render timer,
- option timevalue service rebuild/publish timers,
- batching in `PortfolioEngine`.

Deze lagen zijn er omdat zonder throttling de combinatie van IBKR live feed, option ticks, snapshot updates en tab renders te zwaar wordt.

### 15.4 Manual resolver en locking
De manual resolverflow is technisch belangrijker dan alleen UX:
- sommige optieseries kunnen niet betrouwbaar puur uit datum/weekmapping worden afgeleid;
- handmatige correctie moet persistente en stabiele masterdata opleveren;
- `resolver_locked` voorkomt dat een automatisch pad dit later weer kapot maakt.

### 15.5 Defensive schema hardening
Bij Access-tabellen wordt vaak additieve schemahardening gebruikt:
- kolom toevoegen als deze nog niet bestaat,
- defaults invullen als nodig,
- niet destructief migreren.

Dit past bij de compatibiliteitsstrategie van de app.

## 16. Huidige sterktes van de architectuur

De huidige architectuur is sterk in:
- gefaseerde migratie zonder stilstand,
- centrale snapshotgedachte,
- duidelijker scheiding tussen businessberekening en renderlaag,
- runtime flags voor gecontroleerde cutover,
- ondersteuning van meerdere databases,
- bruikbare unresolved optie-resolverflow,
- WebEngine-tabbladen voor de zwaarste live grids.

## 17. Huidige grenzen en bewuste concessies

Niet alles is volledig “schoon” of uniform, en dat is bekend:
- de codebase bevat nog legacy Qt-tabs naast moderne web tabs;
- sommige updatepaden zijn pragmatisch en niet volledig generiek;
- Single Asset Analyse is nog een hybride component;
- niet elke projection gebruikt exact hetzelfde patchgedrag;
- zowel aggregators als projections bestaan naast elkaar.

Dit is geen toeval, maar een gevolg van de gekozen migratiestrategie: eerst stabiliteit en functionaliteit behouden, daarna pas verder vereenvoudigen.

## 18. Samenvatting

`portefeuille_viewer_1.2` is technisch gezien nog steeds een overgangsarchitectuur, maar wel een bewuste en volwassen overgangsarchitectuur met een inmiddels expliciet scenario-/simulatiepad.

De app bestaat uit:
- een PySide6 shell,
- centrale snapshots in geheugen,
- live aggregators,
- een lichte event/state/projection runtime,
- projection-v2 taboutputs,
- WebEngine renderlagen voor de zwaarste tabellen,
- aparte services voor prijsfeed, option timevalue, migraties en state rebuilds,
- gecontroleerde multi-DB en compatibiliteitslogica.

De belangrijkste designkeuze is niet “alles nieuw”, maar:
- computationele logica naar expliciete services en projections trekken,
- UI lichter maken,
- updates coalescen,
- tabbladen gefaseerd moderniseren,
- en tegelijk de bestaande productiewaarde van de app behouden.

Dit document beschrijft daarmee niet alleen wat er gebouwd is, maar ook waarom de huidige code is zoals deze is.

## Historische documenten
De volgende documenten zijn gearchiveerd en gelden niet meer als primaire bron:
- [DEVELOPMENT_NOTES_1.md](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\development_notes_todo\archive\DEVELOPMENT_NOTES_1.md)
- [DEVELOPMENT_NOTES_2.md](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\development_notes_todo\archive\DEVELOPMENT_NOTES_2.md)
- [DEVELOPMENT_NOTES_3.md](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\development_notes_todo\archive\DEVELOPMENT_NOTES_3.md)
- [DEVELOPMENT_NOTES_4.md](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\development_notes_todo\archive\DEVELOPMENT_NOTES_4.md)
- [integratie_live_optie_engine.md](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\development_notes_todo\archive\integratie_live_optie_engine.md)
- [optimalisatie engine.md](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\development_notes_todo\archive\optimalisatie engine.md)
- [roadmap_engine_ui_modernisatie.md](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\development_notes_todo\archive\roadmap_engine_ui_modernisatie.md)
- [roadmap_modernisatie_TODO.md](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\development_notes_todo\archive\roadmap_modernisatie_TODO.md)

Voor openstaand werk en visie:
- [roadmap.md](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\development_notes_todo\roadmap.md)

Voor vrije ideeën en klad:
- [TODO.md](c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2\development_notes_todo\TODO.md)


## Statusupdate 2026-03-29 overgenomen uit voormalig root-document

Deze sectie is verplaatst uit het eerdere root-bestand development_notes.md, zodat de ontwikkelnotities weer op één plek staan.

# Development Notes

Deze tekst is verplaatst naar:

- `development_notes_todo/development_notes.md`

Reden:

- de ontwikkelnotities stonden dubbel
- de inhoud van 2026-03-29 hoort als update thuis in de centrale notities onder `development_notes_todo`

