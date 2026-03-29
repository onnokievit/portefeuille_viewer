# Plan En Actie Updateflow

## Doel
Dit document is het operationele werkdocument voor de komende fase in `portefeuille_viewer_1.2`.

Doel van deze fase:
1. updateflow en rendergedrag systematisch in kaart brengen en optimaliseren,
2. daarna legacy tabs en bijbehorende load veilig uitfaseren,
3. zonder de 2.0 architectuur te beschadigen.

Dit document bevat daarom niet alleen acties, maar ook:
- inventaris,
- onderzoeksresultaten,
- tussenbeslissingen,
- verwijdermatrix,
- afvinklijst.

`roadmap.md` blijft het strategische document.
Dit bestand is de praktische uitvoering.

---

## Scope

### In scope
- startup updateflow
- order save updateflow
- live tick/update flow
- db switch flow
- tab switch gedrag
- alt-tab terugkeer en zichtbare UI-responsiviteit
- rendergedrag van actieve en inactieve tabs
- legacy tabs en legacy-gerelateerde producers/listeners

### Niet in scope voor deze fase
- nieuwe simulatie/beta-functies bouwen
- grote nieuwe features
- structurele DB-herontwerpen buiten wat nodig is voor stabiliteit of removal

---

## Werkstromen

## Werkstroom A: Updateflow en rendergedrag
Doel:
- exact begrijpen welke signalen, snapshots, services, projections en renders per trigger lopen,
- onnodige dubbele stappen verwijderen,
- actieve UI rustig en voorspelbaar maken,
- inactieve UI geen onnodige renderload laten veroorzaken.

## Werkstroom B: Legacy removal
Doel:
- bepalen welke legacy tabs en logica veilig verwijderd kunnen worden,
- consumers eerst verwijderen,
- daarna producers/listeners/timers die alleen nog voor legacy bestaan,
- compat- of bridge-code alleen laten staan als die nog echt gebruikt wordt.

---

## Aanpak in fases

## Fase 1: Inventaris en audit
- [x] feature inventory afronden
- [x] trigger inventory afronden
- [x] meetpunten vastzetten
- [x] per trigger updateketen beschrijven
- [x] verdachte dubbele of zware paden markeren

## Fase 2: Updateflow opschonen
- [x] order-save pad opschonen
- [x] live tick/update pad opschonen
- [x] render cadence / active tab gedrag bevestigen of corrigeren
- [x] logging/metrics stiller maken op defaults

## Fase 3: Legacy removal matrix
- [x] legacy tabs en bijbehorende logica in kaart
- [x] per legacy component afhankelijkheden bepalen
- [x] removal waves defini�ren

## Fase 4: Gefaseerde verwijdering
- [x] wave 1
- [x] smoke tests
- [x] wave 2
- [x] smoke tests

---

## Feature inventory

### 1. Officiële tabs in huidige 1.2 shell
Gebaseerd op `ui_logica/main_window_logica.py` en de huidige promotieflags.

| Tab | Huidige status | Opmerking |
|---|---|---|
| Orders | officieel | Qt tab |
| Single Asset Analyse | officieel | Qt/hybride, zwaar workflow-scherm |
| Aandelen | officieel modern | promoted web tab als flags aan staan |
| Open Opties (Live) | officieel modern | promoted web tab als flags aan staan |
| Optie Tijdswaarde | officieel modern | promoted web tab als flags aan staan |
| Portfolio Value | officieel | Qt tab |
| Sector Analysis | officieel | Qt tab |
| Sprinters Open | officieel modern | promoted web tab als flags aan staan |
| Optie Eind | officieel | Qt tab |
| Settings | officieel | Qt tab |
| Repository Tester | officieel | Qt tab |

### 2. Legacy tabs / legacy varianten die nog in code bestaan
| Component | Type | Huidige rol |
|---|---|---|
| `AandelenTab` | legacy tab/logica | fallback wanneer promoted web niet actief is |
| `OptiesOpenTab` | legacy tab/logica | fallback wanneer promoted web niet actief is |
| `OptieTijdswaardeTab` | legacy tab/logica | fallback wanneer promoted web niet actief is |
| `SprintersOpenTab` | legacy tab/logica | fallback wanneer promoted web niet actief is |
| `aandelen_web_pilot_tab` extra tab | overgangsvariant | alleen zichtbaar als web aan maar niet promoted |
| `opties_open_web_pilot_tab` extra tab | overgangsvariant | idem |
| `optie_tijdswaarde_web_pilot_tab` extra tab | overgangsvariant | idem |
| `sprinters_open_web_pilot_tab` extra tab | overgangsvariant | idem |

### 3. Belangrijkste producers / services / processen
| Component | Rol | Opmerking |
|---|---|---|
| `signals` | centrale event/signaal hub | `ordersCommitted`, `snapshotUpdated`, `databaseChanged`, `stateRebuildRequested` |
| `SnapshotStore.safe_write()` | snapshot publisher | emit `snapshotUpdated` |
| `PriceFeedService` / `PriceFeedIB` | live price ingest | aandelen, opties, contract details |
| `OptionTimevalueService` | optie universe / timevalue meta | luistert op `ordersCommitted` en gerichte `snapshotUpdated` keys |
| `state_engine_runner` | zware state rebuilds | luistert op `stateRebuildRequested`, database changed |
| `PortfolioEngine` | orchestrator/bridge | nog steeds aanwezig |
| live aggregators aandelen/opties/sprinters | compat/live data producers | worden nu expliciet aangestuurd door refresh-flow en `PortfolioEngine` |
| projection v2 modules | moderne tab-snapshots | worden gevoed via engine core runtime en snapshot updates |

### 4. Services/processen per relevante tab
Eerste inventaris, nog verder uit te werken tijdens audit.

| Tab | Belangrijkste data-inputs | Opmerking |
|---|---|---|
| Aandelen | aandelen projection v2, snapshot updates, prijsfeed-afgeleide data | promoted web |
| Open Opties (Live) | opties open projection v2, comment data, unresolved meta | promoted web |
| Optie Tijdswaarde | optie tijdswaarde projection v2, option timevalue service meta | promoted web |
| Sprinters Open | sprinters projection v2 | promoted web |
| Single Asset Analyse | repository snapshots, orders, live updates, test orders, comments, lokale modellen | hybride en waarschijnlijk gevoeligste scherm |
| Orders | transaction data, repository snapshots, state rebuild trigger | belangrijk order-save pad |
| Portfolio Value | snapshot-based Qt tab | luistert op gerichte `snapshotUpdated` keys |
| Sector Analysis | snapshot-based Qt tab | luistert op gerichte `snapshotUpdated` keys |

---

## Trigger inventory

Deze triggers worden in deze fase expliciet onderzocht.

| Trigger | Waarom relevant |
|---|---|
| App startup | veel initialisaties, subscriptions, seed/rebuild gedrag |
| Order save | functioneel cruciaal en vermoedelijk bron van onnodige load |
| Live tick/update | continue flow, mogelijk dubbel of te bursty |
| DB switch | zware en gevoelige herlaadactie |
| Tab switch | kan rendering of activatie van tabs triggeren |
| Alt-tab terug naar app | zichtbare responsiviteit voor gebruiker |

---

## Meetplan

Per trigger willen we minimaal het volgende vastleggen:
- welke signalen vertrekken,
- welke services reageren,
- welke snapshots worden geschreven,
- welke state rebuilds starten,
- welke projections recomputen,
- welke tabs renderen,
- welke stappen verplicht zijn,
- welke stappen verdacht dubbel of te zwaar zijn.

### Meetpunten
- [ ] app startup
- [ ] order save
- [ ] live tick/update
- [ ] db switch
- [ ] tab switch
- [ ] alt-tab terug naar app

### Meetvorm
Combinatie van:
1. code-audit,
2. bestaande logs/metrics,
3. gerichte tijdelijke instrumentatie waar nodig,
4. handmatige observatie in de UI.

---

## Updateflow audit template

Per trigger vullen we onderstaande tabel aan.

| Trigger | Signaal/startpunt | Reagerende services | Snapshot writes | Rebuilds/projections | Render targets | Verdacht dubbel? | Legacy betrokken? | Actie |
|---|---|---|---|---|---|---|---|---|
| startup | nog uit te werken |  |  |  |  |  |  |  |
| order save | nog uit te werken |  |  |  |  |  |  |  |
| live tick/update | nog uit te werken |  |  |  |  |  |  |  |
| db switch | nog uit te werken |  |  |  |  |  |  |  |
| tab switch | nog uit te werken |  |  |  |  |  |  |  |
| alt-tab terug | nog uit te werken |  |  |  |  |  |  |  |

---

## Auditresultaat: order save

Dit is de eerste volledig uitgeschreven auditstap, omdat `order save` functioneel kritiek is en tegelijk de meest waarschijnlijke bron van overlap, dubbele refreshes en onrustige UI-updates.

### 1. Functioneel startpunt

Bij `order save` zijn er in de huidige code twee primaire startpunten:

1. de repository schrijft de mutatie naar `transacties_bron_data_org` en emit daarna `signals.ordersCommitted.emit()`,
2. de Orders-tab bouwt daarnaast zelf een `stateRebuildRequested` payload op basis van `old_rows` en `new_rows` en queued die via `signals.queued_emit_stateRebuildRequested(payload)`.

Dat betekent dat een order-save nu niet één pad start, maar minstens twee parallelle ketens:
- een `ordersCommitted`-keten,
- een `stateRebuildRequested`-keten.

### 2. Directe order-save keten

#### 2.1 Repository-laag

Geobserveerd in `data/repository.py`:
- `insert_transaction(...)` commit DB-write en emit daarna `ordersCommitted`
- `update_transaction_one_or_two(...)` commit DB-write en emit daarna `ordersCommitted`
- `delete_transactions_by_ids(...)` commit DB-write en emit daarna `ordersCommitted`

Eerste conclusie:
- `ordersCommitted` is de centrale “transactie is committed” eventlaag,
- dit is logisch en functioneel correct,
- maar alles wat daarop reageert moet nu worden geaudit op overlap.

#### 2.2 Orders-tab

Geobserveerd in `ui_logica/orders_tab_widget.py`:
- Orders-tab doet bewust geen lokale snapshot-append/update/delete meer voor centrale transactiedata,
- commentaar in code geeft expliciet aan dat centrale refresh dit moet afhandelen,
- na insert/update/delete wordt daarnaast `_emit_state_rebuild_payload(...)` aangeroepen,
- deze bouwt een payload met:
  - `asset_classes`
  - `affected_assets`
  - `from_date`
  - `reason`
  - `mode="asset_incremental"`
- en queued daarna `signals.queued_emit_stateRebuildRequested(payload)`.

Eerste conclusie:
- Orders-tab start expliciet een incrementele state-engine keten naast `ordersCommitted`,
- dit is op zichzelf verdedigbaar,
- maar het vergroot de kans op dubbel werk als `ordersCommitted` óók al zware snapshot-refreshes start.

### 3. Directe listeners op `ordersCommitted`

Geobserveerd in `portefeuille_viewer_1.2.py`, `option_timevalue_service.py` en `single_asset_analyse_tab_logica.py`.

| Listener | Effect | Classificatie |
|---|---|---|
| `_reset_aandelen_tv_overlay_regime("orders_committed")` | reset overlay-regime voor aandelen/timevalue | waarschijnlijk verplicht/licht |
| `orders_refresh_timer.start()` -> `refresh_transaction_derived_snapshots({"reason":"orders_committed"})` | zware reload van transaction-derived snapshots | verdacht zwaar |
| `OptionTimevalueService.schedule_rebuild()` | rebuild van option-timevalue service | functioneel plausibel, maar mogelijk dubbel |
| `SingleAssetAnalyseTab.on_orders_committed()` | reset live summary + `update_opties_open_table()` | functioneel plausibel, mogelijk dubbel via snapshotflow |

Eerste conclusie:
- het aantal directe listeners op `ordersCommitted` is al substantieel,
- vooral de combinatie van:
  - directe full-ish transaction-derived refresh,
  - option timevalue rebuild,
  - directe UI-update in Single Asset Analyse
  maakt dit pad verdacht druk.

### 4. Zware refresh die uit `ordersCommitted` kan volgen

Geobserveerd in `portefeuille_viewer_1.2.py`.

Als `ORDERS_COMMIT_FULL_REFRESH_V1=1` staat, gebeurt na `ordersCommitted`:
- na 250 ms een call naar `refresh_transaction_derived_snapshots({"reason": "orders_committed"})`.

Deze functie doet onder meer:
- `repository.load_alle_transacties()`
- `repository.load_aandelen_from_tx()`
- `repository.load_open_opties_from_tx()`
- `repository.load_gesloten_opties_from_tx()`
- `repository.load_open_sprinters_from_tx()`
- `repository.build_repository_active_asset_rollup_data()`
- `live_aggregator_aandelen.process_live_update()`
- `live_aggregator_opties.process_live_update()`
- portfolio value rebuilds
- daarna projection recompute:
  - runtime exclusive: `_runtime_recompute_all("transaction_derived")`
  - anders losse recomputes voor aandelen/opties/tijdswaarde/sprinters

Eerste conclusie:
- dit is geen kleine refresh, maar een brede transaction-derived rebuildgolf,
- dit pad is functioneel zwaar,
- dit pad is zeer waarschijnlijk de belangrijkste kandidaat voor “te veel gebeurt direct na order save”.

### 5. Indirecte keten via `snapshotUpdated`

De bovenstaande transaction-derived refresh schrijft meerdere snapshots weg.
Die writes triggeren `signals.snapshotUpdated`.

Belangrijke geobserveerde listeners:
- Orders-tab:
  - reageert op `repository_snapshot_alle_transacties`
  - start `_orders_reload_timer` en daarna `_load_initial_records()`
- OptionTimevalueService:
  - reageert op onder meer:
    - `aggregator_snapshot_load_open_opties_from_tx_live`
    - `repository_snapshot_load_open_opties`
    - `repository_snapshot_historical_close`
    - `repository_snapshot_asset_rollup_data`
    - `repository_snapshot_optie_referentie_data`
  - doet daarna `schedule_rebuild()`
- `portefeuille_viewer_1.2.py`:
  - live snapshot handlers voor:
    - opties projection
    - optie tijdswaarde projection
    - sprinters projection
    - engine core snapshot update pad
- Single Asset Analyse:
  - luistert breed op `snapshotUpdated`

Eerste conclusie:
- zelfs als `ordersCommitted` maar één zware refresh start, veroorzaakt die daarna een brede tweede golf via `snapshotUpdated`,
- dit maakt `snapshotUpdated` de grootste load-multiplier in het order-save pad.

### 6. Parallelle state-engine keten

Geobserveerd in `orders_tab_widget.py`, `signals/__init__.py`, `portefeuille_viewer_1.2.py` en `services/state_engine_runner.py`.

Wat er gebeurt:

1. Orders-tab queued `stateRebuildRequested(payload)`.
2. `portefeuille_viewer_1.2.py` heeft:
   - `signals.stateRebuildRequested.connect(state_engine_runner.handle_rebuild_requested)`
3. `StateEngineRunner.handle_rebuild_requested(...)` normalizeert payload.
4. Voor order-driven reasons geldt:
   - `_auto_order_rebuild_enabled` staat standaard op `False`
   - `_should_defer_order_rebuild(...)` geeft dan `True` terug voor reasons als:
     - `order_insert`
     - `order_update`
     - `order_delete`
5. Dat betekent in de huidige default:
   - order-driven rebuilds worden niet direct uitgevoerd,
   - maar als pending payload in de queue-tabel vastgelegd,
   - en pas later handmatig of na expliciete enable uitgevoerd.

Daarna geldt:
- `stateRebuildFinished -> _schedule_snapshot_refresh(...)` bestaat wel,
- maar dat pad volgt alleen als er daadwerkelijk een succesvolle `asset_result_v2` run heeft plaatsgevonden,
- en dat gebeurt bij order-save standaard dus niet automatisch.

Eerste conclusie:
- de eerder vermoede tweede automatische transaction-derived refresh ná iedere order-save is in de huidige default-config niet bevestigd,
- de directe zware refresh na `ordersCommitted` blijft wél een duidelijke kostenpost,
- de state-engine orderketen is momenteel vooral een pending/mechanische backlog, geen tweede directe runtimegolf.

### 7. Geobserveerde order-save keten als geheel

Huidige werkhypothese, gebaseerd op code-audit:

1. gebruiker slaat order op in Orders-tab
2. repository commit naar DB
3. repository emit `ordersCommitted`
4. Orders-tab queued `stateRebuildRequested(order_insert/order_update/order_delete)`
5. directe `ordersCommitted` listeners reageren:
   - overlay reset
   - OptionTimevalueService rebuild scheduled
   - Single Asset Analyse update
   - optioneel full transaction-derived refresh timer
6. bij `ORDERS_COMMIT_FULL_REFRESH_V1=1` volgt een brede `refresh_transaction_derived_snapshots("orders_committed")`
7. die refresh schrijft snapshots weg
8. `snapshotUpdated` listeners reageren breed
9. order-driven rebuild payload wordt standaard alleen deferred vastgelegd
10. pas bij latere handmatige run of expliciete enable volgt state-engine uitvoering
11. dan pas zou `stateRebuildFinished(asset_result_v2, ok)` opnieuw een transaction-derived refresh kunnen plannen

### 8. Classificatie per stap

| Stap | Beoordeling |
|---|---|
| DB commit + `ordersCommitted` | verplicht |
| `stateRebuildRequested` payload bouwen in Orders-tab | waarschijnlijk verplicht |
| overlay reset | licht / acceptabel |
| directe `OptionTimevalueService.schedule_rebuild()` | plausibel, maar overlap verdacht |
| directe `SingleAssetAnalyse.update_opties_open_table()` | plausibel, maar overlap verdacht |
| directe `refresh_transaction_derived_snapshots("orders_committed")` | zwaar en verdacht dubbel |
| state-engine deferred rebuild | verplicht als pending-mechanisme, maar niet direct runtime-zwaar |
| tweede `refresh_transaction_derived_snapshots(...)` na `asset_result_v2` | alleen relevant bij expliciete run; geen standaard order-save dubbele golf |
| brede `snapshotUpdated` fan-out na directe refreshgolf | zwaar en verdacht multiplier-effect |

### 9. Eerste beslissingen uit deze audit

1. `ordersCommitted` en `stateRebuildRequested` blijven voorlopig beide bestaan.
   - Reden: functionele correctheid eerst behouden.
2. De eerste echte optimalisatiekandidaat is niet het verwijderen van signals, maar het verkleinen van de directe `ordersCommitted -> refresh_transaction_derived_snapshots(...)` golf.
3. `snapshotUpdated` moet in de volgende auditstap per listener worden uitgesplitst in:
   - noodzakelijk,
   - alleen voor actieve tab zinvol,
   - legacy,
   - verdacht dubbel.
4. Single Asset Analyse moet specifiek worden beoordeeld op directe order-save UI work versus indirecte snapshot-driven work.

### 10. Conclusie order-save audit

De huidige order-save flow is functioneel coherent, maar architectonisch waarschijnlijk te breed.

Sterkste observatie:
- er lijkt niet één bron van load te zijn, maar een cascade:
  - `ordersCommitted`
  - directe listeners
  - transaction-derived refresh
  - `snapshotUpdated` fan-out
- en optioneel pas later een aparte state-engine/pending keten

Dat betekent dat optimalisatie hier waarschijnlijk niet moet beginnen met micro-tuning in één tab, maar met:
1. bepalen of de directe `ordersCommitted` full refresh echt volledig nodig is of smaller kan,
2. daarna het snapshot fan-out effect per tab/service terugbrengen.

### 11. Uitsplitsing van `refresh_transaction_derived_snapshots(...)`

Geobserveerd in `portefeuille_viewer_1.2.py`.

De huidige order-save full refresh doet in vaste volgorde:

1. `repository.load_alle_transacties()`
2. `repository.load_aandelen_from_tx()`
3. `repository.load_open_opties_from_tx()`
4. `repository.load_gesloten_opties_from_tx()`
5. `repository.load_gesloten_opties_no_broker()`
6. `repository.load_open_sprinters_from_tx()`
7. `repository.load_gesloten_sprinters_from_tx()`
8. `repository.load_historical_close_snapshot()`
9. `repository.load_per_dag_asset_result_v2_snapshot()`
10. `repository.load_per_dag_asset_result()`
11. `repository.build_repository_active_asset_rollup_data()`
12. `live_aggregator_aandelen.process_live_update()`
13. `live_aggregator_opties.process_live_update()`
14. `repository.portfolio_value_asset_rollup_opties_put()`
15. `repository.portfolio_value_asset_rollup_aandelen()`
16. `repository.portfolio_value_asset_rollup_sprinters()`
17. `repository.portfolio_value_asset_rollup_combined()`
18. projection/runtime recompute

Belangrijke extra observatie:
- meerdere loaders ondersteunen al een `df_tx` parameter:
  - `load_aandelen_from_tx(df_tx)`
  - `load_open_opties_from_tx(df_tx)`
  - `load_gesloten_opties_from_tx(df_tx)`
  - `load_open_sprinters_from_tx(df_tx)`
  - `load_gesloten_sprinters_from_tx(df_tx)`
- de huidige refresh gebruikt dat nog niet
- dus transactiedata wordt nu eerst geladen in `repository_snapshot_alle_transacties`,
  en daarna lezen opvolgende loaders impliciet opnieuw uit de snapshotlaag in plaats van één expliciete gedeelde `df_tx` door te geven

### 12. Classificatie per stap in de directe refreshgolf

| Stap | Huidige rol | Beoordeling | Opmerking |
|---|---|---|---|
| `load_alle_transacties()` | bronlaag verversen | verplicht | moet als eerste; gecommitte DB-waarheid |
| `load_aandelen_from_tx()` | open aandelen snapshot | verplicht bij aandeel-order, plausibel breder inzetbaar | kan `df_tx` hergebruiken |
| `load_open_opties_from_tx()` | open opties snapshot | verplicht bij optie-order, plausibel breder inzetbaar | kan `df_tx` hergebruiken |
| `load_gesloten_opties_from_tx()` | gesloten opties snapshot | niet altijd direct nodig | vooral nodig voor schermen/analyses die gesloten opties tonen |
| `load_gesloten_opties_no_broker()` | afgeleide gesloten-opties rollup | niet direct nodig | tweede-orde afleiding; mag later/debounced |
| `load_open_sprinters_from_tx()` | open sprinters snapshot | alleen nodig bij sprinter-order | kan `df_tx` hergebruiken |
| `load_gesloten_sprinters_from_tx()` | gesloten sprinters snapshot | niet altijd direct nodig | mag later/debounced |
| `load_historical_close_snapshot()` | historische prijsbasis | verdacht onnodig bij order-save | order-save verandert deze DB-tabel niet |
| `load_per_dag_asset_result_v2_snapshot()` | user-specifieke state-engine output lezen | verdacht onnodig bij directe order-save refresh | nodig bij `db switch` om van user-context te wisselen; niet nodig direct na commit |
| `load_per_dag_asset_result()` | legacy/compat snapshot | verdacht onnodig bij directe order-save refresh | zelfde argument, plus legacy-drag |
| `build_repository_active_asset_rollup_data()` | status/actief-inactief basis | plausibel nodig | hangt af van open posities; kan na relevante open snapshots |
| `live_aggregator_aandelen.process_live_update()` | compat/live snapshot | nodig voor huidige app, maar overlapverdacht | niet per se voor alle ordertypes |
| `live_aggregator_opties.process_live_update()` | compat/live snapshot | nodig voor huidige app, maar overlapverdacht | idem |
| `portfolio_value_asset_rollup_opties_put()` | portfolio snapshot opties | plausibel nodig | gebruikt aggregator/live snapshots |
| `portfolio_value_asset_rollup_aandelen()` | portfolio snapshot aandelen | plausibel nodig | gebruikt aggregator/live snapshots |
| `portfolio_value_asset_rollup_sprinters()` | portfolio snapshot sprinters | alleen nodig bij sprinter-impact | kan conditioneel |
| `portfolio_value_asset_rollup_combined()` | gecombineerd portfolio snapshot | plausibel nodig | eindproduct voor meerdere schermen |
| projection/runtime recompute | moderne UI snapshots | nodig | maar alleen nadat bron/samenvattingssnapshots klaar zijn |

### 13. Wat hier waarschijnlijk onnodig breed is

Op basis van de huidige code zijn dit de sterkste kandidaten:

1. **historische en state-engine snapshots direct opnieuw lezen**
- `load_historical_close_snapshot()`
- `load_per_dag_asset_result_v2_snapshot()`
- `load_per_dag_asset_result()`

Waarom verdacht:
- een order-save verandert deze tabellen niet direct
- `per_dag_asset_result_v2` hoort bij user-/DB-context en echte state-engine output
- bij `db switch` moet deze snapshot wel opnieuw geladen worden, zodat de app van user 1 naar user 2 wisselt
- direct na `ordersCommitted` is deze reload niet nodig zolang er niet eerst een nieuwe state-engine output is weggeschreven
- `historical_close` verandert niet door transacties

2. **gesloten-sets altijd meepakken**
- `load_gesloten_opties_from_tx()`
- `load_gesloten_opties_no_broker()`
- `load_gesloten_sprinters_from_tx()`

Waarom verdacht:
- niet elk order-save heeft direct impact op schermen die deze nodig hebben
- vooral relevant voor gesloten/afgeronde analyses

3. **transactiebron niet expliciet hergebruiken**
- `df_tx` wordt niet als gedeelde input doorgegeven

Waarom verdacht:
- dit vergroot niet alleen CPU-kosten
- het maakt ook de refreshgolf onnodig breed in de snapshotlaag

### 14. Eerste concrete optimalisatiesnede

De beste eerste snede is nu:

#### Snede A: maak de order-save refresh transaction-aware en reuse `df_tx`

Concreet:
1. `df_tx = repository.load_alle_transacties()` als expliciete variabele vasthouden
2. diezelfde `df_tx` doorgeven aan:
   - `load_aandelen_from_tx(df_tx)`
   - `load_open_opties_from_tx(df_tx)`
   - `load_gesloten_opties_from_tx(df_tx)`
   - `load_open_sprinters_from_tx(df_tx)`
   - `load_gesloten_sprinters_from_tx(df_tx)`
3. op basis van `payload["asset_classes"]` en/of `payload["reason"]` conditioneel laden:
   - aandeel-order: geen sprinter-open/gesloten reload
   - optie-order: geen sprinter-reload tenzij nodig
   - sprinter-order: geen gesloten-opties reload tenzij nodig

Reden:
- laag risico
- direct minder werk
- geen architectuurbreuk

#### Snede B: haal direct niet-transactiegedreven reads uit order-save full refresh

Concreet voorlopig verwijderen uit het order-save pad:
- `load_historical_close_snapshot()`
- `load_per_dag_asset_result_v2_snapshot()`
- `load_per_dag_asset_result()`

Reden:
- deze horen niet bij “DB-truth van transacties is gewijzigd”
- ze kunnen via hun eigen levenscyclus ververst blijven

#### Snede C: gesloten snapshots alleen nog wanneer functioneel nodig

Concreet:
- standaardpad focust op open posities + active asset rollup + portfolio snapshots
- gesloten-opties/sprinters snapshots alleen:
  - conditioneel,
  - of later in een tweede, lagere-prioriteitsrefresh

### 15. Keuze van de eerste implementatie

De eerste implementatie moet **Snede A + Snede B** zijn.

Waarom precies deze:
- hoogste verwachte winst
- laagste functionele risico
- nog geen afhankelijkheid van legacy removal
- past direct binnen de bestaande 2.0 architectuur

Nog niet als eerste doen:
- aggregators verwijderen of vervangen
- legacy tabs verwijderen
- service-triggerconsolidatie in `OptionTimevalueService`

Dat zijn vervolgstappen, maar niet de eerste snede.

### 16. Uitgevoerde eerste reductie

Uitgevoerd in `portefeuille_viewer_1.2.py`:

1. `load_historical_close_snapshot()` is uit `refresh_transaction_derived_snapshots(...)` gehaald
   - reden: order-save verandert `historical_data_correct` niet
   - deze reload hoort bij startup / price-update lifecycle, niet bij transactiemutatie

2. `load_per_dag_asset_result()` is in dezelfde refresh uitgecommentarieerd en gemarkeerd als obsolete-kandidaat
   - reden: niet meer direct nodig in order-save flow
   - belangrijke nuance: deze snapshot is nog niet volledig dood in de app
   - `Single Asset Analyse` gebruikt deze nu nog als fallback wanneer `repository_snapshot_historical_close` niet beschikbaar is
   - daarom nu nog niet uit de rest van de codebase verwijderd

Niet aangepast in deze eerste reductie:
- `load_per_dag_asset_result_v2_snapshot()`
- `load_alle_transacties()`

Reden:
- `per_dag_asset_result_v2` moet buiten directe order-save refresh blijven, maar wel actief blijven bij `db switch` en startup
- transactietabel reload blijft voorlopig veiligheidsmechanisme voor DB-truth sync

### 17. Uitgevoerde tweede reductie

Vervolg-audit op `repository_per_dag_asset_result` afgerond.

Functionele app-consumers gevonden:
- geen actieve consumers in moderne web tabs
- geen consumers in `Aandelen`, `Open Opties (Live)`, `Optie Tijdswaarde`, `Portfolio Value`, `Sector Analysis`
- wel exact 1 functionele read in `Single Asset Analyse`:
  - legacy fallback in `load_asset_history(...)`
  - pad: gebruik `repository_snapshot_historical_close` als primaire bron
  - alleen bij ontbrekende/lege historical-close snapshot terugval op `repository_per_dag_asset_result`

Infrastructuurverwijzingen die geen functionele consumer zijn:
- declaratie/reset in `snapshot_store.py`
- `snapshot_store_summary()`
- loaderdefinitie in `repository.py`

Uitgevoerde staged cleanup:

1. Legacy fallback in `Single Asset Analyse` is uitgezet
   - als `repository_snapshot_historical_close` ontbreekt of leeg is, retourneert `load_asset_history(...)` nu een lege dataframe
   - expliciete reden: de oorzaak moet worden opgelost in historical-close loading, niet via de oude `per_dag_asset_result` fallback

2. `load_per_dag_asset_result()` is nu ook in `refresh_everything()` uitgecommentarieerd
   - gemarkeerd als obsolete-kandidaat
   - nog niet definitief verwijderd uit de codebase
   - definitieve verwijdering pas na rooktest

Status na deze reductie:
- `per_dag_asset_result` wordt niet meer functioneel gebruikt in actieve app-paden
- de code is nog aanwezig als tijdelijke recovery-/verificatielaag
- bij succesvolle rooktest kan de volgende cleanup volgen:
  - fallbackcode definitief verwijderen
  - loaderdefinitie verwijderen
  - snapshot-store veld en summary-verwijzingen verwijderen

### 18. Definitieve cleanup per_dag_asset_result

Rooktest op de staged uitschakeling gaf geen regressie.

Daarom nu definitief verwijderd uit actieve codepaden:
- `repository_per_dag_asset_result` veld uit `SnapshotStore`
- reset- en summary-verwijzingen in `snapshot_store.py`
- `load_per_dag_asset_result()` uit `repository.py`
- resterende startup/refresh calls in runtime helpers
- resterende legacy comment in `Single Asset Analyse`
- twee devtool hydration-paden aangepast zodat ze niet meer van deze legacy snapshot afhangen

Nieuwe status:
- `per_dag_asset_result` hoort niet meer bij de actieve runtime van `portefeuille_viewer_1.2`
- de leidende paden zijn nu:
  - `repository_snapshot_historical_close`
  - `repository_snapshot_per_dag_asset_result_v2`

Volgende optimalisatiesnede:
- `load_per_dag_asset_result_v2_snapshot()` uit directe `ordersCommitted` / transaction-derived refresh halen
- behouden bij:
  - `db switch` voor user-contextwisseling
  - startup / `refresh_everything()`
  - na echte succesvolle state-engine update

### 19. Uitgevoerde derde reductie

Uitgevoerd:
- `load_per_dag_asset_result_v2_snapshot()` is uit `refresh_transaction_derived_snapshots(...)` gehaald

Reden:
- deze snapshot is niet transactiederived
- deze snapshot representeert user-specifieke state-engine output
- bij `db switch` moet hij geladen worden om van de ene user/DB-context naar de andere te wisselen
- direct na `ordersCommitted` is deze reload onnodig zolang er niet eerst nieuwe state-engine output is weggeschreven

Nieuwe status:
- directe order-save refresh richt zich nu strakker op transaction-derived snapshots
- `per_dag_asset_result_v2` blijft onderdeel van startup en `db switch`
- vervolgstap later: gerichte reload na echte succesvolle state-engine update

### 20. Uitgevoerde vierde reductie

Uitgevoerd:
- `ordersCommitted` geeft nu een payload mee met:
  - `changed_asset_types`
  - `changed_assets`
  - `changed_ids`
  - `row_count`
  - `reason`
- directe `ordersCommitted` refresh gebruikt die payload nu om transaction-derived rebuilds te versmallen

Nieuwe directe refresh-regels:
- `aandeel` order:
  - wel:
    - `load_aandelen_from_tx()`
    - `build_repository_active_asset_rollup_data()`
    - `live_aggregator_aandelen.process_live_update()`
    - `portfolio_value_asset_rollup_aandelen()`
    - `portfolio_value_asset_rollup_combined()`
    - `refresh_aandelen_projection(...)`
  - niet:
    - open/gesloten opties
    - open/gesloten sprinters
    - optie tijdswaarde / opties open projections
    - sprinters projection

- `optie` order:
  - wel:
    - `load_open_opties_from_tx()`
    - `load_gesloten_opties_from_tx()`
    - `load_gesloten_opties_no_broker()`
    - `build_repository_active_asset_rollup_data()`
    - `live_aggregator_opties.process_live_update()`
    - `portfolio_value_asset_rollup_opties_put()`
    - `portfolio_value_asset_rollup_combined()`
    - `refresh_opties_open_projection(...)`
    - `refresh_optie_tijdswaarde_projection(...)`
  - niet:
    - aandelen rebuild pad
    - sprinter rebuild pad

- `sprinter` order:
  - wel:
    - `load_open_sprinters_from_tx()`
    - `load_gesloten_sprinters_from_tx()`
    - `build_repository_active_asset_rollup_data()`
    - `portfolio_value_asset_rollup_sprinters()`
    - `portfolio_value_asset_rollup_combined()`
    - `refresh_sprinters_open_projection(...)`
  - niet:
    - aandelen rebuild pad
    - optie rebuild pad

Fallback-regel:
- als payload ontbreekt of onbekende `asset_type` bevat, blijft de oude brede refresh van kracht
- dit houdt de eerste snede veilig en voorkomt regressie bij onverwachte transactiesoorten

Belangrijke keuze:
- `future` wordt nu nog als onbekend behandeld en forceert dus brede refresh
- dat is bewust conservatief; futures moeten later expliciet geclassificeerd worden in plaats van stilzwijgend onder `aandeel` vallen

Verwachte winst:
- minder afgeleide snapshot-loads per commit
- minder `snapshotUpdated` fan-out vanuit niet-relevante domeinen
- vooral winst bij grote gebruikersdatabases met veel transacties

Testfocus na deze snede:
- aandeel-order
- optie-order
- sprinter-order
- delete/update van die orders
- db switch
- controleren of alleen relevante tabs/snapshots zichtbaar bijwerken

### 21. Uitgevoerde vijfde reductie

Uitgevoerd:
- in engine-core exclusive mode gebruikt het order-save pad niet langer `_runtime_recompute_all("transaction_derived")`
- in plaats daarvan wordt nu alleen de relevante projection-set gerecomputed:
  - `aandeel` order -> `aandelen_v2`
  - `optie` order -> `opties_open_v2` + `optie_tijdswaarde_v2`
  - `sprinter` order -> `sprinters_open_v2`

Belangrijk:
- `refresh_everything()` gebruikt nog steeds full runtime recompute
- deze snede geldt alleen voor directe `ordersCommitted` / transaction-derived refresh
- onbekende gevallen blijven via de bestaande brede fallback lopen

Waarom dit relevant is:
- timingmeting liet zien dat `_runtime_recompute_all` na de eerdere reducties de grootste resterende kostenpost was
- daardoor zat nog steeds veel order-save latency in irrelevante projection recomputes

Verwachte winst:
- directe reductie in order-save latency
- minder onnodige projection publish/persist-paden
- rustiger updategedrag na save, vooral bij enkelvoudige orders

Nieuwe meetfocus:
- vergelijk oude `_runtime_recompute_all` timings met nieuwe `_runtime_recompute_selected`
- kijk per ordertype of runtime nu in lijn ligt met alleen de relevante projection-set

---


## Auditresultaat: live tick / update

Dit is de tweede auditstap, omdat dit het continue runtime-pad is dat de app de hele sessie belast.

Belangrijk onderscheid:
- ruwe tick-ingest is niet hetzelfde als zichtbare UI-update,
- de echte belasting ontstaat pas wanneer ticks zich vertalen naar snapshots, projections en renders.

### 1. Live startpunten

Er zijn in de huidige code twee hoofdsoorten live input:

1. aandelen/onderliggende prijsupdates via `priceUpdated`
2. optieticks via `optionTickUpdated`

Geobserveerd in `services/price_feed.py`:
- `PriceFeedIB` emit:
  - `priceUpdated(sym, cur, px)`
  - `optionTickUpdated(payload)`
- `PriceFeedService` vangt die op en doet:
  - `_on_price(...)`
  - `_on_option_tick(payload)`

### 2. Direct tickgedrag in `PriceFeedService`

#### 2.1 `priceUpdated`

Geobserveerd:
- `_on_price(sym, cur, px)` doet alleen:
  - `self.store.set(sym, cur, px)`
  - `self.priceUpdated.emit(sym, cur, px)`

Eerste conclusie:
- dit is een licht pad,
- hier zit niet direct de zware belasting.

#### 2.2 `optionTickUpdated`

Geobserveerd:
- `_on_option_tick(payload)`:
  - normaliseert `series_id`
  - update `_option_prices[sid]` in memory
  - bewaart velden zoals:
    - `bid`
    - `ask`
    - `last`
    - `delayed_last`
    - `model_price`
    - `underlying_price`
    - `iv`, `delta`, `gamma`, `theta`
  - berekent `last_px` en `px_source`
  - slaat `last_update` op
  - emit daarna opnieuw `self.optionTickUpdated.emit(payload)`

Eerste conclusie:
- ook dit directe tickpad is relatief licht,
- het is vooral een in-memory cache/update pad,
- de echte runtime-last zit verderop in wat andere services en projections op basis hiervan doen.

### 3. Periodieke persistence in `PriceFeedService`

Geobserveerd:
- aandelen last prices worden periodiek weggeschreven via `save_last_prices_to_db()`
- optieprijzen worden periodiek weggeschreven via `save_option_last_prices_to_db()`
- save timers:
  - aandelen: elke 60 sec
  - opties: elke 5 min
  - plus flush op shutdown

Eerste conclusie:
- DB-persist van live prijzen is niet de primaire bron van continue UI-load,
- dit is periodiek en relatief los van de renderproblematiek.

### 4. Service die het meest direct op optieticks reageert

Geobserveerd in `services/option_timevalue_service.py`:
- `price_feed.optionTickUpdated.connect(self._on_option_tick)`
- service heeft:
  - `_rebuild_timer` = 350 ms single-shot
  - `_publish_timer` = 300 ms single-shot
  - `_full_publish_timer` = 1500 ms repeating
- service luistert ook op `snapshotUpdated`

Belangrijke observatie:
- deze service vormt de brug tussen ruwe optieticks en de `snapshot_optie_timevalue_live` snapshotlaag,
- dus optieticks leiden niet direct tot UI-renders, maar eerst tot service-level rebuild/publish gedrag.

Eerste conclusie:
- `OptionTimevalueService` is een centrale live aggregator/coalescer voor opties,
- dit is functioneel logisch,
- maar kan bij overlap met andere snapshot-driven rebuilds alsnog een load multiplier worden.

### 5. Live snapshot -> projection pad in `portefeuille_viewer_1.2.py`

Geobserveerd:

#### 5.1 Niet-engine-core exclusive pad

Bij `signals.snapshotUpdated`:
- `aggregator_snapshot_load_open_opties_from_tx_live`
  - start debounced `refresh_opties_open_projection("live_opties_snapshot")`
  - timer = 500 ms
- `snapshot_optie_timevalue_live`
  - start debounced `refresh_optie_tijdswaarde_projection("live_optie_tijdswaarde_snapshot")`
  - timer = 500 ms
- `aggregator_snapshot_open_sprinters_live`
  - start debounced `refresh_sprinters_open_projection("live_sprinters_snapshot")`
  - timer = 500 ms

#### 5.2 Engine core runtime pad

`_on_snapshot_updated_engine_core(snapshot_key)`:
- publiceert snapshot refresh als event naar engine core runtime
- `EngineCoreRuntime.publish_snapshot_update(...)` heeft per snapshot-key throttling:
  - env: `ENGINE_CORE_SNAPSHOT_THROTTLE_MS`
  - default: 500 ms
- als exclusive runtime aan staat:
  - alleen toegestane live topics worden meegenomen:
    - `aggregator_snapshot_load_open_opties_from_tx_live`
    - `snapshot_optie_timevalue_live`
    - `aggregator_snapshot_open_sprinters_live`

Eerste conclusie:
- er is al throttling aanwezig op live snapshot-eventniveau,
- maar:
  - die geldt per snapshot-key,
  - niet per totale UI- of servicebelasting,
  - en niet automatisch voor alle niet-engine-core listeners.

### 6. Aandelen heeft een afwijkend live pad

Geobserveerd in `_on_snapshot_updated_engine_core(...)`:
- `snapshot_optie_timevalue_live` kan extra aandelen refreshes triggeren voor de timevalue overlay:
  - `startup_timevalue_seed`
  - `timevalue_overlay_tick`
- dit pad gebruikt:
  - warmup window
  - overlay lock
  - minimum interval

Eerste conclusie:
- aandelen reageert niet alleen op aandelenprijzen, maar ook op optie-timevalue live data,
- dit is functioneel verklaarbaar,
- maar maakt het live pad van aandelen complexer dan de andere web tabs.

### 7. Web tabs: renderdiscipline actieve vs inactieve tabs

Geobserveerd in:
- `aandelen_web_pilot_tab.py`
- `opties_open_web_pilot_tab.py`
- `optie_tijdswaarde_web_pilot_tab.py`
- `sprinters_open_web_pilot_tab.py`
- `main_window_logica.py`

#### 7.1 Activatie

Main window roept bij tabwissel:
- `set_active(True/False)` aan voor:
  - Single Asset Analyse
  - Aandelen
  - Open Opties
  - Optie Tijdswaarde
  - Sprinters Open

#### 7.2 Rendergedrag web tabs

Alle moderne web tabs hebben:
- `_is_active`
- `_active_render_ms = UI_WEB_ACTIVE_RENDER_MS` (default 1000 ms)
- `signals.snapshotUpdated.connect(self._on_snapshot_updated)`
- lokale `_needs_snapshot`, `_needs_patch`, `_needs_meta`
- `_render_timer`

Gedrag:
- bij inactief:
  - timer stopt
  - geen flush van render
- bij actief:
  - snapshot updates markeren alleen dirty state
  - render gebeurt op cadence of direct bij activering

Bij Open Opties specifiek:
- comment editing blokkeert render tijdelijk via `_comment_editing`

Eerste conclusie:
- de moderne web tabs lijken architectonisch correct opgezet:
  - inactieve tabs renderen niet doorlopend,
  - actieve tabs renderen gecadence?d,
  - dirty state wordt losgekoppeld van directe JS-render.

Dus:
- als er nog live onrust of load is, komt die waarschijnlijk niet primair van de web-tab renderlaag zelf,
- maar eerder van snapshot/projection recompute en bredere signal fan-out.

### 8. Waarschijnlijk bron van onregelmatige updates

Op basis van de audit tot nu toe is de meest waarschijnlijke verklaring voor door jou ervaren onregelmatige updates:

1. ticks komen asynchroon binnen, niet op een vaste klok
2. meerdere snapshotsoorten publiceren onafhankelijk van elkaar
3. per snapshot-key bestaat throttling/debounce, maar niet ??n uniforme globale cadence
4. sommige schermen luisteren direct op snapshots, andere indirect via projections, andere ook nog direct op `ordersCommitted`
5. daardoor ontstaat een patroon van:
   - soms snelle bursts,
   - soms langere stilte,
   - en soms twee verschillende updategolven die visueel als ?random? aanvoelen

Eerste conclusie:
- de huidige architectuur heeft wel losse throttles,
- maar nog geen volledig uniform ???n live cadence voor zichtbare UI? model.

### 9. Geobserveerde live keten als geheel

Werkhypothese voor live updateflow:

1. tick komt binnen via IB / price feed
2. `PriceFeedService` schrijft lichte in-memory store/update
3. relevante live service of aggregator publiceert snapshot-update
4. `snapshotUpdated` listeners reageren
5. projection recompute wordt per topic gestart of gedebounced
6. projection snapshot/meta/patch worden opnieuw gepubliceerd
7. moderne web tab markeert dirty state
8. alleen actieve tab rendert op `UI_WEB_ACTIVE_RENDER_MS`

Belangrijke nuancering:
- tussen stap 3 en 6 kan nog veel variatie zitten,
- en juist daar zit waarschijnlijk de resterende optimalisatieruimte.

### 10. Classificatie live tick/update pad

| Stap | Beoordeling |
|---|---|
| ruwe tick ingest in `PriceFeedService` | licht / acceptabel |
| in-memory option price cache update | licht / acceptabel |
| `OptionTimevalueService` rebuild/publish mechaniek | waarschijnlijk verplicht |
| snapshot publish naar `snapshotUpdated` | verplicht, maar multiplier |
| projection recomputes per live snapshot | functioneel plausibel, te auditen op overlap |
| web-tab dirty marking | licht / acceptabel |
| web-tab active-only cadence render | goed patroon |
| extra aandelen overlay refresh op basis van optie-timevalue | plausibel, maar specifiek te beoordelen |

### 11. Eerste beslissingen uit deze audit

1. De moderne web-tab renderlaag is voorlopig niet de eerste optimalisatiekandidaat.
   - De basisdiscipline `inactief = niet renderen` en `actief = cadence` staat er al.
2. De volgende live-optimalisatie moet zich richten op:
   - service/snapshot/projection overlap,
   - niet op oppervlakkige UI-render tuning.
3. Er moet expliciet worden onderzocht:
   - welke live snapshots elkaar functioneel overlappen,
   - welke projection recomputes echt nodig zijn per topic,
   - of sommige live listeners alleen voor legacy nog waarde hebben.
4. Aandelen krijgt een aparte sub-audit vanwege het timevalue-overlay pad.

### 12. Conclusie live tick/update audit

De live updateflow lijkt in architectuur al beter gedisciplineerd dan het order-save pad.

Belangrijkste bevinding:
- de directe ticklaag is relatief licht,
- de echte belasting ontstaat in:
  - snapshot publication,
  - projection recompute,
  - brede listener fan-out.

Daarom moet de optimalisatie van live gedrag waarschijnlijk gericht zijn op:
1. reduceren van overlap in snapshot/projection reacties,
2. expliciet onderscheiden van:
   - noodzakelijke live recompute,
   - legacy/live compat reacties,
   - alleen-render-als-actief gedrag.

---


## Auditresultaat: db switch

Dit is de derde hoofd-auditstap, omdat `db switch` in de praktijk een van de zwaarste functionele acties is:
- actieve database wisselt,
- transactiedata wisselt,
- referentielijsten wisselen,
- services resetten of herladen,
- en daarna volgen meestal brede snapshot-updates en mogelijk state-engine catchup.

### 1. Functioneel startpunt

Het primaire UI-startpunt zit in `ui_logica/orders_tab_widget.py`.

Gebruiker kiest een andere database in `comboDatabase`.
Dat triggert:
- `OrdersTab.apply_database_by_name(name)`

Binnen die methode gebeurt:
1. `repo.switch_database(name)`
2. daarna `repo.load_alle_transacties()`
3. referentielijsten opnieuw laden
4. form resetten
5. orders tabel initialiseren/herladen
6. test orders cache opnieuw laden
7. lokaal `dbChanged.emit()`
8. daarnaast lokaal `self.dbChanged.emit()` (lijkt nergens op aangesloten)

Belangrijke observatie:
- `repo.switch_database(name)` emit zelf al centraal een queued `databaseChanged(name)`.
- `OrdersTab.apply_database_by_name(...)` deed eerder lokaal nog extra emit-logica, maar dat bleek geen echte tweede centrale trigger.

Eerste verdenking was dat dit een dubbele centrale trigger was. Nader gecontroleerd blijkt de centrale extra emit in `OrdersTab` dode code te zijn: `active_db_name` bestaat daar niet, dus dat pad loopt in praktijk niet.

### 2. Repository-switch pad

Geobserveerd in `data/repository.py`.

`switch_database(name)` doet:
- validatie van DB-naam
- flush dirty open-optie-comments naar huidige DB
- flush dirty test orders naar huidige DB
- test connectie naar nieuwe DB
- vervangt `db_path` en `conn_str`
- reset comment-cache in `SNAPSHOT_STORE`
- reset test-order cache in `SNAPSHOT_STORE`
- zet `SNAPSHOT_STORE.active_database_name = name`
- emit daarna `signals.queued_emit_databaseChanged(name)`

Classificatie:
- flushes: verplicht
- connectie-test: verplicht
- cache-reset: verplicht
- centrale queued `databaseChanged`: logisch en waarschijnlijk voldoende als centrale switch-trigger

Eerste conclusie:
- het repository-pad zelf is coherent,
- en de centrale switch-notificatie komt effectief uit de repository-laag. De extra centrale emit in Orders-tab bleek dode code en is verwijderd.

### 3. Direct vervolg in Orders-tab

Na `repo.switch_database(name)` doet `apply_database_by_name(...)` direct extra werk:
- `repo.load_alle_transacties()`
- `load_reference_lists()`
- combobox items voor orderregels opnieuw vullen
- kleur van DB-selector aanpassen
- `reset_form()`
- `_load_initial_records()`
- `load_test_orders_cache_from_db()`
- `self.dbChanged.emit()`
- lokaal `self.dbChanged.emit()` (voor zover zichtbaar zonder listeners)

Classificatie:
- `load_alle_transacties()`: functioneel plausibel, maar potentieel overlappend met bredere refresh
- referentielijsten herladen: verplicht voor Orders-tab
- `_load_initial_records()`: verplicht voor Orders-tab zelf
- lokale `dbChanged.emit()`: vooralsnog vermoedelijk inert / zonder effect

Eerste conclusie:
- Orders-tab doet zowel lokale UI-herlaadacties als centrale app-brede herlaadacties,
- dat is verdedigbaar,
- maar de concrete overlap zit dus niet in een tweede centrale emit vanuit Orders-tab. De echte zwaarte zit eerder in de brede centrale refresh- en follow-up keten.

### 4. Centrale app-reactie op `databaseChanged`

Geobserveerd in `portefeuille_viewer_1.2.py`.

Er zijn twee directe centrale listeners:

1. `_on_database_changed_refresh(db_name)`
   - `_reset_aandelen_tv_overlay_regime(f"database_changed:{db_name}")`
   - `refresh_everything()`

2. `state_engine_runner.handle_database_changed`
   - start `request_daily_full_catchup_for_active_db(...)`

#### 4.1 `refresh_everything()`

Dit is breed en zwaar.
Geobserveerd eerder in startup/order-save audit:
- transacties herladen
- aandelen/open opties/gesloten opties/open sprinters enz. opnieuw laden
- historische/prijs/asset-rollup snapshots laden
- live aggregators opnieuw initialiseren/processen
- portfolio value datasets opnieuw bouwen
- projection recomputes of runtime recompute-all

Classificatie:
- functioneel zwaar maar logisch voor een DB-switch,
- wel zeer kostbaar,
- en gevoelig voor dubbel triggeren als `databaseChanged` tweemaal vertrekt.

#### 4.2 `state_engine_runner.handle_database_changed(...)`

Geobserveerd in `services/state_engine_runner.py`:
- roept `request_daily_full_catchup_for_active_db(reason=STARTUP_DAILY_CATCHUP_REASON)` aan
- als vandaag al succesvol gedraaid: skip
- anders bouwt het payloads voor daily full catchup en queued die

Classificatie:
- functioneel plausibel,
- tweede zware fase n? of naast `refresh_everything()`.

Eerste conclusie:
- `db switch` heeft al minimaal ??n brede reloadfase (`refresh_everything()`),
- en mogelijk een tweede zware fase (`daily full catchup`) als voor die DB nog geen succesvolle run vandaag bestaat.

### 5. Directe service listeners op `databaseChanged`

#### 5.1 `OptionTimevalueService`

Geobserveerd in `services/option_timevalue_service.py`:
- `_on_database_changed(_db)` doet:
  - `_clear_unresolved("database_changed")`
  - `schedule_rebuild()`

Classificatie:
- functioneel logisch,
- maar potentieel overlappend met bredere snapshotherlaadgolf uit `refresh_everything()`.

#### 5.2 Live aggregators

Geobserveerd in:
- `data/live_aggregator_aandelen.py`
- `data/live_aggregator_opties.py`
- `data/live_aggregator_sprinters.py`

Alle drie luisteren op `signals.databaseChanged` en doen bij DB-switch:
- `refresh_data()`

Ze luisteren daarnaast ook op relevante `snapshotUpdated` keys.

Classificatie:
- functioneel plausibel,
- maar verdacht voor overlap omdat ze:
  - direct op `databaseChanged` refreshen,
  - en later mogelijk opnieuw refreshen na nieuwe repository snapshots uit `refresh_everything()`.

Eerste conclusie:
- aggregators zijn een concrete kandidaat voor dubbele DB-switch-refresh:
  - ??n keer direct op `databaseChanged`,
  - nog eens indirect op `snapshotUpdated`.

### 6. Directe UI listeners op `databaseChanged`

#### 6.1 Single Asset Analyse

Geobserveerd in `ui_logica/single_asset_analyse_tab_logica.py`.

`on_database_changed` doet onder meer:
- filter-combo?s verversen
- `_on_filter_changed()`
- status naar `active`
- open-optie-comments cache herladen
- `update_opties_open_table()`
- test orders cache herladen
- test orders tabel verversen
- live summary velden resetten

Classificatie:
- functioneel logisch voor dit scherm,
- maar mogelijk deels overlappend met bredere centrale snapshot-refresh.

#### 6.2 Portfolio Value / Sector Analysis / legacy Qt tabs

Code-audit laat zien dat meerdere Qt tabs direct op `databaseChanged` luisteren.
Voorbeelden:
- `portfolio_value_tab_logica.py`
- `sector_analysis_tab_logica.py`
- legacy `opties_open_tab_logica.py`

Classificatie:
- functioneel plausibel,
- maar dit bevestigt dat `databaseChanged` nu een brede UI-fan-out veroorzaakt, ook buiten de moderne web tabs.

### 7. Geobserveerde db-switch keten als geheel

Huidige werkhypothese op basis van code-audit:

1. gebruiker kiest andere DB in Orders-tab
2. `repo.switch_database(name)`:
   - flush dirty data
   - wissel verbinding
   - reset caches
   - emit queued `databaseChanged(name)`
3. Orders-tab doet lokale herlaadactie:
   - transacties opnieuw laden
   - referenties/combo?s opnieuw laden
   - form reset
   - orders tabel herladen
   - test orders cache laden
4. Orders-tab doet daarna alleen lokale herlaadacties en een lokale `dbChanged.emit()`
5. centrale listeners reageren:
   - `_on_database_changed_refresh(...)` -> `refresh_everything()`
   - `state_engine_runner.handle_database_changed(...)`
6. services reageren:
   - `OptionTimevalueService.schedule_rebuild()`
   - live aggregators `refresh_data()`
7. meerdere Qt tabs reageren direct op `databaseChanged`
8. `refresh_everything()` schrijft snapshots weg
9. `snapshotUpdated` listeners reageren opnieuw breed
10. optioneel volgt daarna nog daily full catchup voor actieve DB

### 8. Classificatie per stap

| Stap | Beoordeling |
|---|---|
| repository flush + DB switch + cache reset | verplicht |
| queued `databaseChanged` uit repository | logisch / waarschijnlijk voldoende |
| Orders-tab lokale herlaadactie | grotendeels verplicht voor eigen scherm |
| extra centrale emit uit Orders-tab | ontkracht; bleek dode code |
| `refresh_everything()` na `databaseChanged` | zwaar maar functioneel plausibel |
| `state_engine_runner.handle_database_changed()` | zwaar maar functioneel plausibel |
| `OptionTimevalueService.schedule_rebuild()` | plausibel, mogelijk overlap |
| live aggregators direct `refresh_data()` op `databaseChanged` | verdacht dubbel |
| brede `snapshotUpdated` tweede golf na `refresh_everything()` | zwaar / multiplier |

### 9. Eerste beslissingen uit deze audit

1. De eerdere verdenking op een dubbele centrale `databaseChanged` emit is ontkracht. Dat pad in Orders-tab bleek dode code en is verwijderd.
2. Aggregators moeten expliciet worden beoordeeld op:
   - direct refreshen op `databaseChanged`,
   - versus alleen reageren op vernieuwde snapshots.
3. `db switch` moet als tweefasenpad worden gezien:
   - directe switch/herlaadfase,
   - eventuele catchup-fase.
4. Net als bij order-save is hier de brede `snapshotUpdated` fan-out een kernvermenigvuldiger van de load.

### 10. Conclusie db-switch audit

`db switch` is functioneel coherent, maar nu waarschijnlijk breder dan nodig.

Belangrijkste observaties:
- de eerder vermoede dubbele centrale trigger in Orders-tab bleek geen echte runtime-trigger te zijn,
- aggregators reageren waarschijnlijk zowel direct als indirect,
- meerdere UI-schermen reageren los van elkaar op hetzelfde event,
- daarna volgt opnieuw brede snapshotfan-out,
- en daar bovenop kan nog daily full catchup komen.

Dat betekent dat `db switch` waarschijnlijk niet traag is door ??n dure stap,
maar door een gelaagde keten van:
1. switch + lokale Orders-tab reload,
2. centrale databaseChanged-reacties,
3. brede snapshot-refresh,
4. snapshot fan-out,
5. optionele catchup.

---


## Geconsolideerde snapshotUpdated fan-out matrix

Nu de drie hoofdtriggers zijn uitgeschreven (`order save`, `live tick/update`, `db switch`) is de eerstvolgende stap het expliciet maken van de `snapshotUpdated` fan-out.

Doel van deze matrix:
- per listener vastleggen of hij noodzakelijk is,
- of hij vooral legacy ondersteunt,
- of hij alleen voor actieve UI zinvol is,
- of hij waarschijnlijk dubbel werk veroorzaakt.

### 1. Uitleg bij classificaties

| Label | Betekenis |
|---|---|
| nodig | functioneel noodzakelijk in huidige architectuur |
| alleen actief scherm | render/reactie is alleen zinvol voor actieve tab of zichtbare UI |
| legacy | hoort bij oude tab/logica of compat-pad |
| verdacht dubbel | lijkt hetzelfde functionele werk nogmaals te doen via ander pad |

### 2. Matrix per listener

| Listener | Luistert op | Reactie | Classificatie | Opmerking |
|---|---|---|---|---|
| `_on_snapshot_updated_engine_core` in `portefeuille_viewer_1.2.py` | alle `snapshotUpdated`, feitelijk relevant voor `snapshot_optie_timevalue_live` | aandelen overlay/timevalue seed en overlay refresh | nodig, maar specifiek te bewaken | moderne runtimebrug; geen brede listener qua logica, wel gevoelig omdat hij aandelenprojection forceert |
| `_on_snapshot_updated_for_opties_projection` | `aggregator_snapshot_load_open_opties_from_tx_live` | start debounced opties projection refresh | nodig | alleen van toepassing wanneer runtime niet exclusive is |
| `_on_snapshot_updated_for_optie_tijdswaarde_projection` | `snapshot_optie_timevalue_live` | start debounced optie-tijdswaarde projection refresh | nodig | idem |
| `_on_snapshot_updated_for_sprinters_projection` | `aggregator_snapshot_open_sprinters_live` | start debounced sprinters projection refresh | nodig | idem |
| `AandelenWebPilotTab._on_snapshot_updated` | projection v2 snapshot/patch/meta | mark dirty / render op cadence | nodig, alleen actief scherm | goed patroon; niet eerste optimalisatiekandidaat |
| `OptiesOpenWebPilotTab._on_snapshot_updated` | projection v2 snapshot/patch/meta | mark dirty / render op cadence | nodig, alleen actief scherm | goed patroon; beschermt ook comment-editing |
| `OptieTijdswaardeWebPilotTab._on_snapshot_updated` | projection v2 snapshot/patch/meta | mark dirty / render op cadence | nodig, alleen actief scherm | goed patroon |
| `SprintersOpenWebPilotTab._on_snapshot_updated` | projection v2 snapshot/patch/meta | mark dirty / render op cadence | nodig, alleen actief scherm | goed patroon |
| `OrdersTabWidget._on_snapshot_updated` | `repository_snapshot_alle_transacties` | start `_orders_reload_timer` -> reload orders tabel | nodig | functioneel logisch; directe UI-reactie op transactiesnapshot |
| `SingleAssetAnalyseTab._on_snapshot_updated` | `aggregator_snapshot_load_open_opties_from_tx_live`, `snapshot_optie_timevalue_live` | schedule opties reload als actief, anders dirty flag | nodig, alleen actief scherm | modern patroon; niet breed, wel belangrijk voor ervaren UI-rust |
| `PortfolioValueTab` snapshot listener | portfolio-value snapshots | debounced reload snapshot | nodig, maar UI-only | Qt tab; directe reactie kan later tegen actieve-tab-strategie worden gehouden |
| `SectorAnalysisTab._on_snapshot_updated` | watched portfolio/optie/sprinter snapshots | reload data | nodig, maar UI-only | Qt tab; kandidaat voor actief/inactief onderscheid in latere fase |
| `OptionTimevalueService._on_snapshot_updated` | `aggregator_snapshot_load_open_opties_from_tx_live`, `repository_snapshot_load_open_opties`, `repository_snapshot_historical_close`, `repository_snapshot_asset_rollup_data`, `repository_snapshot_optie_referentie_data` | clear unresolved voor subset + `schedule_rebuild()` | nodig, maar deels verdacht dubbel | kernservice; wel sterke kandidaat om triggers te versmallen of samen te voegen |
| `LiveAggregatorAandelen._on_snapshot_updated` | `repository_snapshot_aandelen` | `refresh_data()` | verdacht dubbel | doet directe refresh op repository snapshot; kan overlappen met bredere refreshpaden en moderne projectionlaag |
| `LiveAggregatorOpties._on_snapshot_updated` | `repository_snapshot_load_open_opties` | `refresh_data()` | verdacht dubbel | idem; expliciete compat/legacy kandidaat |
| `LiveAggregatorSprinters._on_snapshot_updated` | `repository_snapshot_open_sprinters` | `refresh_data()` | verdacht dubbel | idem |
| `AandelenTab._on_snapshot_updated` | aandelen projection v2 snapshot/patch/meta plus `snapshot_optie_timevalue_live` | reload legacy aandelen UI | legacy | oude tab/logica; niet aan raken voordat removal wave start, maar duidelijk geen einddoel |
| `OptiesOpenTab._on_snapshot_updated` | opties projection v2 snapshot/patch/meta | reload legacy opties UI | legacy | oude tab/logica |
| `OptieTijdswaardeTab._on_snapshot_updated` | projection v2 keys of oude timevalue keys | reload legacy Qt tabel | legacy | oude tab/logica |

### 3. Belangrijkste patronen uit de matrix

#### 3.1 Moderne web tabs

De moderne web tabs gedragen zich redelijk netjes:
- reageren alleen op hun eigen projection snapshot/patch/meta,
- markeren vooral dirty state,
- renderen alleen wanneer actief.

Conclusie:
- dit is niet de primaire bron van structurele fan-out-problemen.

#### 3.2 Services en aggregators

De echte multiplier zit eerder hier:
- `OptionTimevalueService`
- `LiveAggregatorAandelen`
- `LiveAggregatorOpties`
- `LiveAggregatorSprinters`

Waarom:
- deze reageren niet alleen op UI-gerichte projection snapshots,
- maar op repository/aggregator snapshots,
- en kunnen zelf weer vervolgwerk of nieuwe snapshots veroorzaken.

Conclusie:
- hier zit de grootste kans op ontdubbeling.

#### 3.3 Legacy listeners

Legacy tabs luisteren nog steeds op `snapshotUpdated`.
Dat betekent:
- ook al zijn de moderne tabs promoted,
- de oude schermlogica kan nog steeds aan de snapshot-bus hangen zolang die objecten bestaan of zolang fallbackcode actief is.

Conclusie:
- legacy removal is niet alleen UI-opruiming,
- maar ook fan-out reductie.

#### 3.4 Qt tabs buiten de gemoderniseerde web tabs

`Single Asset Analyse`, `Portfolio Value` en `Sector Analysis` zijn nog Qt-gedreven en reageren op snapshots.
Daar geldt:
- functioneel logisch,
- maar later waarschijnlijk aanscherpen naar actiever/inactiever gedrag.

Belangrijke nuance:
- `Single Asset Analyse` doet dit al relatief gedisciplineerd voor open-opties/timevalue,
- `Portfolio Value` en `Sector Analysis` lijken nog klassieker direct te reloaden.

### 4. Eerste overlapconclusies

Op basis van de matrix zijn de sterkste overlapkandidaten nu:

1. **Live aggregators**
- reageren direct op repository snapshots,
- reageren ook op `databaseChanged`,
- en leven naast de moderne projection/runtimelaag.

Beoordeling:
- sterk verdacht dubbel,
- waarschijnlijk deels compat/legacy drag.

2. **OptionTimevalueService triggerbreedte**
- luistert op meerdere snapshot-keys,
- schedulet rebuilds relatief breed,
- is functioneel nodig, maar mogelijk te ruim getriggerd.

Beoordeling:
- nodig,
- maar goede kandidaat voor trigger-consolidatie.

3. **Legacy tab listeners**
- blijven UI-reloads doen via `snapshotUpdated`.

Beoordeling:
- duidelijk legacy,
- latere removal levert directe fan-out winst op.

4. **Dubbele triggerpaden buiten `snapshotUpdated` die daarna alsnog fan-out veroorzaken**
- dubbele `transaction_derived refresh` na order save
- brede databaseChanged-reactieketen (ook zonder echte dubbele emit)

Beoordeling:
- dit zijn geen `snapshotUpdated` listeners zelf,
- maar ze voeden wel de brede fan-out-golf.

### 5. Beslissing: eerste concrete optimalisatiesnede

Op basis van de drie trigger-audits plus de fan-out matrix is de eerste logische optimalisatiesnede:

1. **dubbele triggerpaden buiten de listenerlaag reduceren**
   - order-save `transaction_derived refresh` pad kiezen en ontdubbelen
   - `databaseChanged` keten versmallen waar services nu zowel direct als indirect reageren

2. **daarna pas de service-fan-out versmallen**
   - met name `OptionTimevalueService`
   - daarna live aggregators

Reden voor deze volgorde:
- als je eerst listeners gaat tunen, maar dezelfde brede snapshotgolven twee keer blijft starten,
  blijft de architectuur fundamenteel onrustig.

### 6. Praktische vervolgstap

De eerstvolgende implementatie-onderzoekssnede moet dus zijn:

**A. trigger overlap bevestigen**
- hoe groot is de directe `ordersCommitted -> refresh_transaction_derived_snapshots(...)` golf precies, en welke delen daarvan zijn echt nodig?
- welke `databaseChanged` listeners doen nu direct werk dat later nogmaals via refreshed snapshots terugkomt?

**B. daarna pas serviceconsolidatie**
- `OptionTimevalueService` trigger-set versmallen
- aggregators beoordelen op directe snapshotlisteners versus moderne projectionlaag

---

## Eerste codebevindingen

### 1. Main window shell
Gebaseerd op `ui_logica/main_window_logica.py`.

Relevante observaties:
1. promoted web tabs zijn al leidend als flags aan staan:
   - `PV_UI_AANDELEN_WEB_V1`
   - `UI_AANDELEN_PROMOTED_V1`
   - `UI_OPTIES_WEB_V1`
   - `UI_OPTIES_PROMOTED_V1`
   - `UI_OPTIE_TIJDSWAARDE_WEB_V1`
   - `UI_OPTIE_TIJDSWAARDE_PROMOTED_V1`
   - `UI_SPRINTERS_WEB_V1`
   - `UI_SPRINTERS_PROMOTED_V1`
2. tabwissel loopt via `tabWidget.currentChanged -> _on_tab_changed()`
3. `set_active()` wordt alleen expliciet aangeroepen voor:
   - Single Asset Analyse
   - Aandelen
   - Open Opties
   - Optie Tijdswaarde
   - Sprinters Open

Eerste conclusie:
- de actieve/inactieve discipline is al deels aanwezig,
- maar moet per tab auditmatig worden bevestigd op echt rendergedrag en niet alleen op API-niveau.

### 2. Signaalniveau
Uit `signals/__init__.py` en `portefeuille_viewer_1.2.py`.

Belangrijke globale signalen:
- `ordersCommitted`
- `snapshotUpdated`
- `databaseChanged`
- `stateRebuildRequested`

Eerste conclusie:
- dit zijn de hoofdassen van de audit,
- vermoedelijke inefficiëntie zit niet in te veel soorten signalen, maar in te veel listeners en overlap in wat ze daarna doen.

### 3. Orde-save gerelateerde hooks
Uit eerste grep op `portefeuille_viewer_1.2.py` en gerelateerde code.

Zichtbaar:
1. `ordersCommitted` reset aandelen timevalue overlay regime
2. `ordersCommitted` kan een full refresh timer starten
3. `ordersCommitted` hangt aan `OptionTimevalueService.schedule_rebuild`
4. `ordersCommitted` hangt aan Single Asset Analyse
5. repository-methodes emitten `ordersCommitted`

Eerste conclusie:
- order save is inderdaad een primaire verdachte voor overlap,
- dit triggerpad moet als eerste diep worden uitgeschreven.

### 4. SnapshotUpdated als brede trigger
Veel componenten luisteren op `snapshotUpdated`, onder andere:
- live aggregators,
- legacy tabs,
- web tabs,
- option timevalue service,
- orders tab,
- portfolio value,
- sector analysis,
- single asset analyse.

Eerste conclusie:
- `snapshotUpdated` is waarschijnlijk de belangrijkste multiplier van load,
- audit moet vaststellen welke listeners nog echt nodig zijn,
- waarschijnlijk zit hier een deel van de dubbele of onrustige updateflow.

---

## Beslissingen tot nu toe

1. Eerst updateflow audit, daarna pas echte legacy removal.
2. `db switch` is expliciet onderdeel van de audit.
3. `order save` krijgt prioriteit binnen werkstroom A.
4. Legacy removal gebeurt gefaseerd en alleen op basis van een remove-matrix.
5. `plan_en_actie_updateflow.md` is het werkdocument voor bevindingen en afvinken.

---

## Verwijdermatrix legacy code

Wordt later ingevuld.

| Component | UI consumer | Producer/listener | Nog nodig voor 2.0? | Verwijderbaar | Opmerking |
|---|---|---|---|---|---|
| AandelenTab | ja | onbekend | nog te bepalen | nog te bepalen |  |
| OptiesOpenTab | ja | onbekend | nog te bepalen | nog te bepalen |  |
| OptieTijdswaardeTab | ja | onbekend | nog te bepalen | nog te bepalen |  |
| SprintersOpenTab | ja | onbekend | nog te bepalen | nog te bepalen |  |

---

## Actielijst eerstvolgende stap

- [x] `roadmap.md` aanvullen met 2 hoofdlijnen
- [x] `plan_en_actie_updateflow.md` aanmaken
- [x] eerste feature inventory vastleggen
- [x] eerste trigger inventory vastleggen
- [x] eerste codebevindingen vastleggen
- [ ] order-save flow volledig uitschrijven
- [ ] live tick/update flow volledig uitschrijven
- [ ] db-switch flow volledig uitschrijven
- [ ] tab-switch/active-render gedrag per tab bevestigen
- [ ] eerste lijst met verdachte dubbele paden maken

---

## Statusupdate 2026-03-29: order-save refresh versneld

Afgerond in deze snede:

1. Order-save refresh versmald per assettype.
2. Multi-row inserts voor combo/doorrol transaction-safe gemaakt.
3. `ordersCommitted` payload verrijkt met:
   - `operation`
   - `committed_rows`
   - `deleted_ids`
4. `repository_snapshot_alle_transacties` wordt nu lokaal gepatcht op basis van committed DB-resultaat.
5. `refresh_transaction_derived_snapshots(...)` gebruikt nu patch-first en valt alleen terug op `load_alle_transacties()` als fallback.
6. Historische full snapshots voor:
   - `repository_snapshot_historical_close`
   - `repository_snapshot_per_dag_asset_result_v2`
   worden nu bij load opgeschoond (datum cast/parsen, `asset_rollup` normaliseren, numerieke casts).
7. Voor Aandelen-tab zijn extra latest-per-asset snapshots toegevoegd:
   - `repository_snapshot_historical_close_latest`
   - `repository_snapshot_per_dag_asset_result_v2_latest`
8. `aandelen_tab_summary.py` gebruikt voor Aandelen-tab niet meer de volledige historische tabellen, maar alleen deze kleine latest snapshots.

Resultaat:

- eerdere aandelen insert baseline:
  - ongeveer `1.17s`
  - waarvan `~0.90s` in `load_alle_transacties()`
- na snapshot patching:
  - aandelen insert ongeveer `0.49s`
- na latest-snapshot refactor voor Aandelen-tab:
  - aandelen insert ongeveer `0.26s`
  - met `_runtime_recompute_selected` ongeveer `215ms`
- optie insert zit nu rond `0.05-0.06s`

Conclusie:

- de bottleneck `load_alle_transacties()` is uit het normale order-save pad gehaald,
- de Aandelen-tab gebruikt niet langer per order de volledige historische datasets voor `net_change` en `koers_prev`,
- deze optimalisatiesnede kan als afgerond worden beschouwd.

Open toekomstig optimalisatiepunt, bewust niet nu opgepakt:

- verdere uitsplitsing van `build_aandelen_tab_summary(asset_rollup=...)`
- met name equity-side single-asset summary intern timen
- en eventueel later verder cachen / overlayen als dat nog nodig blijkt

---

## Auditresultaat: live tick / update flow

Deze audit beschrijft het pad van een gewone live prijsupdate vanaf de price feed tot aan projections en tabs.

### 1. Functioneel startpunt

De live tick-flow start in `PriceFeedService` / `PriceFeedIB`.

Belangrijk:
- `PriceFeedIB.tickPrice(...)` emit `priceUpdated(sym, cur, px)` voor:
  - `last`
  - delayed `last`
  - `close` als fallback
  - bid/ask midpoint als er nog geen `last` is
- `PriceFeedService` is de Qt-wrapper rond deze feed

In `portefeuille_viewer_1.2.py` wordt vervolgens:
- `price_feed = PriceFeedService(...)` aangemaakt
- `PortfolioEngine(pricefeed=price_feed)` gebruikt als centrale consumer
- daarnaast draait `start_live_price_updater(price_feed)` die periodiek `SNAPSHOT_STORE.live_prices` bijwerkt

### 2. Live price pad via PortfolioEngine

Geobserveerd in `domain/portfolio_engine.py`:

1. `pricefeed.priceUpdated -> PortfolioEngine._on_live_price(...)`
2. die schrijft de prijs in drie aggregators:
   - `LiveAggregatorAandelen.update_live_price(...)`
   - `LiveAggregatorOpties.update_live_price(...)`
   - `LiveAggregatorSprinters.update_live_price(...)`
3. daarna wordt niet direct gerecompute, maar gebatcht via `_update_timer`
4. bij timer-fire draait:
   - `live_aggregator_aandelen.process_live_update()`
   - `live_aggregator_opties.process_live_update()`
   - `live_aggregator_sprinters.process_live_update()`

Belangrijke observatie:
- `PortfolioEngine` batcht live price verwerking
- interval staat nu op `10000ms`
- de comment in code noemt nog `1500ms`, maar de feitelijke waarde is `10000`

Dat betekent:
- live ticks gaan niet 1-op-1 naar UI recompute
- er zit al een duidelijke batchlaag tussen

### 3. Wat aggregators daarna doen

Geobserveerd in:
- `data/live_aggregator_aandelen.py`
- `data/live_aggregator_opties.py`
- `data/live_aggregator_sprinters.py`

Alle drie volgen hetzelfde patroon:

1. repository snapshot lezen
2. live prices + last prices combineren via `build_prices_df(...)`
3. berekende live dataset opbouwen
4. `SNAPSHOT_STORE.safe_write(...)` doen naar:
   - `aggregator_snapshot_aandelen_live`
   - `aggregator_snapshot_load_open_opties_from_tx_live`
   - `aggregator_snapshot_open_sprinters_live`
5. daarna `snapshotUpdated` emit via `safe_write`

### 4. Tweede live pad: centrale `live_prices`

Los van PortfolioEngine draait ook:
- `start_live_price_updater(price_feed, interval_sec=2)`

Dit pad:
- leest `price_feed.get_all_prices()`
- schrijft naar `SNAPSHOT_STORE.live_prices`

Belangrijke observatie:
- deze write gebruikt geen `safe_write`
- dus er komt géén directe `snapshotUpdated` op `live_prices`
- consumers lezen deze centrale prijsdict alleen wanneer zij zelf recomputen

Dat betekent:
- `live_prices` is cache/state
- geen directe snapshot-bus trigger

### 5. Wat `snapshotUpdated` daarna met live aggregators doet

In `portefeuille_viewer_1.2.py` geldt in runtime exclusive mode:

- alleen deze live topics gaan door naar engine core:
  - `aggregator_snapshot_load_open_opties_from_tx_live`
  - `snapshot_optie_timevalue_live`
  - `aggregator_snapshot_open_sprinters_live`

Belangrijke observatie:
- `aggregator_snapshot_aandelen_live` gaat niet via `engine_core_runtime.publish_snapshot_update(...)`
- Aandelen live projection refresh loopt dus niet via deze generic snapshot topic route
- Aandelen-tab wordt in de moderne setup vooral bijgewerkt via bredere transaction-derived refreshes en eigen projection logica

Voor niet-exclusive mode zijn er losse snapshot listeners:
- opties projection refresh op `aggregator_snapshot_load_open_opties_from_tx_live`
- optie tijdswaarde projection refresh op `snapshot_optie_timevalue_live`
- sprinters projection refresh op `aggregator_snapshot_open_sprinters_live`

### 6. OptionTimevalueService als live multiplier

Geobserveerd in `services/option_timevalue_service.py`:

- luistert op `ordersCommitted`
- luistert op `databaseChanged`
- luistert op `snapshotUpdated`

Bij live/snapshot-updates reageert de service op:
- `aggregator_snapshot_load_open_opties_from_tx_live`
- `repository_snapshot_load_open_opties`
- `repository_snapshot_historical_close`
- `repository_snapshot_asset_rollup_data`
- `repository_snapshot_optie_referentie_data`

Daarna doet de service:
- `schedule_rebuild()`
- en publiceert weer `snapshot_optie_timevalue_live`

Conclusie:
- de optie live-flow heeft een extra service-laag
- die is functioneel nodig
- maar ook een duidelijke fan-out multiplier

### 7. Welke UI-consumers reageren op live snapshots

Moderne web tabs:
- `AandelenWebPilotTab`
- `OptiesOpenWebPilotTab`
- `OptieTijdswaardeWebPilotTab`
- `SprintersOpenWebPilotTab`

Die luisteren op snapshot/projection-updates en renderen alleen actief.

Qt / hybride tabs die nog direct luisteren:
- `AandelenTab`
- `OptiesOpenTab`
- `OptieTijdswaardeTab`
- `SprintersOpenTab`
- `SingleAssetAnalyseTab`
- `PortfolioValueTab`
- `SectorAnalysisTab`

Belangrijke observatie:
- live fan-out komt niet alleen in de moderne web tabs terecht
- er zijn nog steeds meerdere Qt listeners en legacy listeners op de bus

### 8. Conclusie live tick/update flow

De live tick-flow is gelaagd en functioneel coherent:

1. price feed ontvangt tick
2. PortfolioEngine batcht ticks
3. aggregators bouwen live snapshots
4. snapshot bus triggert vervolgwerk
5. OptionTimevalueService kan opnieuw publiceren
6. projections en tabs reageren daarop

Belangrijkste conclusies:

1. De live tick-flow is niet primair het probleem van de oude `load_alle_transacties` bottleneck.
2. Er is al batching aanwezig in PortfolioEngine.
3. De live fan-out multiplier zit vooral in:
   - aggregators
   - OptionTimevalueService
   - brede set snapshot listeners
4. Legacy tabs hangen nog steeds in de snapshot-listenerlaag zolang fallbackcode bestaat en die tabs instantiated kunnen worden.

### 9. Betekenis voor legacy removal

Met deze audit is de situatie nu scherper:

Wat al relatief veilig voorbereid kan worden:
- legacy tab UI consumers:
  - `AandelenTab`
  - `OptiesOpenTab`
  - `OptieTijdswaardeTab`
  - `SprintersOpenTab`
- en fallback/pilot-wiring in `main_window_logica.py`

Wat nog niet in dezelfde eerste wave moet worden verwijderd:
- `LiveAggregatorAandelen`
- `LiveAggregatorOpties`
- `LiveAggregatorSprinters`
- `OptionTimevalueService`

Reden:
- deze zitten nog echt in de live dataflow van de moderne architectuur
- dit zijn niet alleen legacy UI-consumers

Praktische conclusie:
- een eerste legacy removal wave kan zich richten op oude tab-klassen en fallback-instantiatie
- maar niet op aggregators/services die nog producent zijn in de live flow

### 10. Statusupdate 2026-03-29: legacy removal wave 1

Uitgevoerd:

- `main_window_logica.py` instantiateert voor:
  - Aandelen
  - Open Opties
  - Optie Tijdswaarde
  - Sprinters Open
  nu alleen nog de moderne web tabs
- fallback-instantiatie naar de oude Qt legacy tabs is verwijderd
- extra “Web Pilot” dubbeltabs via fallback-wiring zijn ook verwijderd

Bewust nog niet verwijderd:

- de legacy tab-bestanden zelf
- live aggregators
- `OptionTimevalueService`

Reden:

- deze eerste wave verwijdert alleen shell-level consumers en fallback-wiring
- producenten en services in de live dataflow blijven nog staan

### 11. Wave 2 voorbereiding: wat nu echt weg kan

Na wave 1 zijn de volgende oude tab-modules in runtime niet meer in gebruik:

- `ui_logica/aandelen_tab_logica.py`
- `ui_logica/opties_open_tab_logica.py`
- `ui_logica/optie_tijdswaarde_tab_logica.py`
- `ui_logica/sprinters_open_tab_logica.py`

Bijbehorende oude UI-bestanden die daarna ook removal candidates zijn:

- `ui/aandelen_tab_ui.py`
- `ui/opties_open_ui.py`
- `ui/sprinters_open_ui.py`
- `ui_designs/aandelen_tab.ui`
- `ui_designs/opties_open.ui`
- `ui_designs/sprinters_open.ui`

Beoordeling snapshot/listener-risico:

1. Oude tab-listeners zelf
- snapshot listeners in deze modules zijn nu effectief inert
- reden: de bijbehorende classes worden niet meer geinstantieerd vanuit `main_window_logica.py`

2. Unieke functionaliteit per oude tab

- `AandelenTab`
  - eigen snapshot listener op `snapshotUpdated`
  - broker filter popup + `aandelenProjectionFilterChanged`
  - oude async worker rond `build_aandelen_tab_summary`
  - conclusie: module zelf is removal candidate, maar broker-filter UX moet eerst expliciet geborgd zijn in de web tab

- `OptiesOpenTab`
  - snapshot/databaseChanged listeners
  - comment editing / kleur / filterlogica
  - conclusie: alleen verwijderen als bevestigd is dat web tab alle benodigde comment/filter workflows dekt

- `OptieTijdswaardeTab`
  - directe tabelweergave van timevalue snapshot
  - beperkte zelfstandige logica
  - conclusie: laag risico, waarschijnlijk directe removal candidate

- `SprintersOpenTab`
  - reageert via aggregator signal, niet via centrale snapshot-bus
  - beperkte zelfstandige logica
  - conclusie: laag risico, waarschijnlijk directe removal candidate

### 12. Praktische wave 2 volgorde

Veiligste volgorde:

1. Eerst verwijderen:
- `optie_tijdswaarde_tab_logica.py`
- `sprinters_open_tab_logica.py`
- bijbehorende oude UI-bestanden

2. Daarna pas verwijderen na korte functionele check:
- `aandelen_tab_logica.py`
- `opties_open_tab_logica.py`
- bijbehorende oude UI-bestanden

Reden:
- Aandelen en Open Opties hadden historisch de meeste interactieve legacy UX
- daar zit het grootste risico op een vergeten nichefunctie

### 13. Statusupdate 2026-03-29: wave 2a uitgevoerd

Uitgevoerd:

- `ui_logica/optie_tijdswaarde_tab_logica.py` verwijderd
- `ui_logica/sprinters_open_tab_logica.py` verwijderd

Controle:

- geen runtime-verwijzingen meer in app-code
- compilecheck op `main_window_logica.py` en `portefeuille_viewer_1.2.py` schoon

Nog bewust niet gedaan in deze wave:

- oude UI-bestanden verwijderen
- `aandelen_tab_logica.py` verwijderen
- `opties_open_tab_logica.py` verwijderen

Reden:

- eerst de laagste-risico tab-logica opruimen
- daarna pas de twee zwaardere legacy tabs met meer historische UX

### 14. Statusupdate 2026-03-29: wave 2b uitgevoerd

Uitgevoerd:

- `ui_logica/aandelen_tab_logica.py` verwijderd
- `ui_logica/opties_open_tab_logica.py` verwijderd
- verweesde oude UI-bestanden verwijderd:
  - `ui/aandelen_tab_ui.py`
  - `ui/opties_open_ui.py`
  - `ui/sprinters_open_ui.py`
  - `ui_designs/aandelen_tab.ui`
  - `ui_designs/opties_open.ui`
  - `ui_designs/sprinters_open.ui`

Controle:

- geen runtime-verwijzingen meer naar:
  - `aandelen_tab_logica`
  - `opties_open_tab_logica`
  - `optie_tijdswaarde_tab_logica`
  - `sprinters_open_tab_logica`
- compilecheck op shell en moderne web tabs schoon

Gevolg:

- de vier oude live-tab modules zijn nu verwijderd
- de shell en runtime gebruiken alleen nog de moderne web tabs voor:
  - Aandelen

### 15. Statusupdate 2026-03-29: live aggregator consolidatie

Uitgevoerd:

- `PortfolioEngine` gebruikt nu dezelfde live aggregators als de rest van de app
- dubbele instantie-opzet voor:
  - `LiveAggregatorAandelen`
  - `LiveAggregatorOpties`
  - `LiveAggregatorSprinters`
  is verwijderd
- directe `snapshotUpdated` / `databaseChanged` listeners zijn uit deze drie live aggregators gehaald

Reden:

- order-save refresh en startup refresh roepen `process_live_update()` al expliciet aan
- live price batching in `PortfolioEngine` roept dezelfde aggregators al expliciet aan
- de oude listeners veroorzaakten dubbele initialisatie/refresh en extra fan-out zonder eigen functionele meerwaarde

Nieuwe situatie:

1. repository/state refresh pad
- schrijft repository snapshots
- roept daarna expliciet de relevante live aggregators aan

2. live tick pad
- `PriceFeedService -> PortfolioEngine`
- `PortfolioEngine` batcht ticks
- dezelfde gedeelde live aggregators verwerken de live update

Wat bewust nog niet is aangepakt:

- verdere versmalling van snapshot fan-out in overige Qt tabs

Conclusie:

- de compat/live aggregator-laag is nu eenvoudiger
- dubbele aggregator-instanties zijn weg
- de volgende cleanup-kandidaat is nu vooral overige brede snapshot listeners

### 16. Statusupdate 2026-03-29: OptionTimevalueService versmald

Uitgevoerd:

- `OptionTimevalueService` rebuildt niet meer op `repository_snapshot_load_open_opties`
- `OptionTimevalueService` gebruikt voor underlying close nu `repository_snapshot_historical_close_latest`
  in plaats van de volle `repository_snapshot_historical_close`
- de snapshot-trigger set is daarmee versmald naar:
  - `aggregator_snapshot_load_open_opties_from_tx_live`
  - `repository_snapshot_historical_close_latest`
  - `repository_snapshot_asset_rollup_data`
  - `repository_snapshot_optie_referentie_data`

Reden:

- `repository_snapshot_load_open_opties` was in de huidige flow redundant naast
  `aggregator_snapshot_load_open_opties_from_tx_live`
- voor timevalue rebuild is alleen de laatste bekende underlying close per asset nodig,
  niet de volledige historical-close tabel

Gevolg:

- minder dubbele rebuild scheduling in de optie-timevalue service
- smallere dependency op historische close

### 17. Statusupdate 2026-03-29: Qt snapshot listeners herbeoordeeld

Uitkomst:

- `PortfolioValueTab` luistert al alleen op relevante portfolio-value snapshots
- `SectorAnalysisTab` luistert al alleen op relevante portfolio-value snapshots
- `SingleAssetAnalyseTab` luistert al alleen op:
  - `aggregator_snapshot_load_open_opties_from_tx_live`
  - `snapshot_optie_timevalue_live`
- `OrdersTabWidget` luistert al alleen op `repository_snapshot_alle_transacties`

Conclusie:

- er is op dit moment geen even veilige extra cleanup in de Qt listeners zoals bij de aggregators
- de volgende echte kandidaat zit eerder in:
  - verdere versmalling van `databaseChanged` effecten
  - of specifiek nog in services rond option timevalue / resolver workflow

### 18. Statusupdate 2026-03-29: databaseChanged fan-out versmald

Uitgevoerd:

- `OptionTimevalueService` reageert niet meer direct op `databaseChanged`
- `PortfolioValueTab` reageert niet meer direct op `databaseChanged`
- `SectorAnalysisTab` reageert niet meer direct op `databaseChanged`

Reden:

- bij DB-switch draait centraal al `refresh_everything()`
- die rewrite van snapshots triggert daarna toch al de relevante `snapshotUpdated` paden
- directe `databaseChanged` reloads in deze componenten waren daardoor dubbel werk

Wat bewust blijft staan:

- `SingleAssetAnalyseTab.on_database_changed()`
  - nodig voor comment-cache reload
  - nodig voor test-order-cache reload
  - nodig voor UI/filter reset op actieve DB
- `StateEngineRunner.handle_database_changed()`
  - nodig voor startup/daily catchup logica op DB-wissel

Conclusie:

- de database-switch keten is nu smaller
- de resterende `databaseChanged` listeners hebben nog een functionele reden buiten pure snapshot-reload

### 19. Statusupdate 2026-03-29: eindsmoke test geslaagd

Functioneel bevestigd:

- DB-switch naar andere DB: ok
- DB-switch terug: ok
- `Aandelen` tab correct gevuld
- `Single Asset Analyse` correct gevuld
- asset selector correct gevuld
- test orders correct gevuld
- `Open Opties` correct geupdate
- `Optie Tijdswaarde` correct geupdate
- `Portfolio Value` correct geupdate
- `Sector Analysis` correct geupdate
- geen fouten in de CLI

Eindoordeel:

- Werkstroom A (`updateflow en rendergedrag`) is voor deze snede afgerond
- Werkstroom B (`legacy removal`) is voor de live-tab UI-laag en de bijbehorende fan-out cleanup afgerond
- dit document kan voor deze snede als uitgevoerd worden beschouwd

---

## Laatste update
2026-03-29



