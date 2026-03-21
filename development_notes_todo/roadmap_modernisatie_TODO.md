# Roadmap Modernisatie TODO

Doel: uitvoerbaar werkoverzicht voor engine + UI modernisatie, los van oude kladnotities.

Status-legenda:
- `DONE`: opgeleverd en in gebruik
- `IN_PROGRESS`: deels gebouwd, nog open punten
- `TODO`: nog niet gestart / niet af

## 1. Engine Core
- `IN_PROGRESS` Projection-v2 per tab actief:
  - `AandelenProjectionV2`
  - `OptiesOpenProjectionV2`
  - `OptieTijdswaardeProjectionV2`
  - `SprintersOpenProjectionV2`
- `DONE` Versioned snapshots + patch snapshots + meta snapshots.
- `DONE` Metrics logging + summarize scripts voor projection performance.
- `TODO` Generieke `Event` + centrale `StateStore` module.
- `TODO` Generieke `ProjectionBus` module (in plaats van tab-specifieke wiring).
- `TODO` Uniform coalescing policy per event-type in centrale core.

## 2. Transaction Engine V2
- `TODO` Transaction command handlers (add/update/delete/replay).
- `TODO` Test-transactie injectie API.
- `TODO` Deterministic replay tool met run-id en output-vergelijking.
- `TODO` Volledige integratie met `optie eind` onderhoudspad.

## 3. UI Modernisatie
- `IN_PROGRESS` WebEngine pilot tabs actief:
  - Aandelen (Web Pilot)
  - Open Opties (Web Pilot)
  - Optie Tijdswaarde (Web Pilot)
  - Sprinters Open (Web Pilot)
- `DONE` Snapshot init + patch updates in WebEngine tabs.
- `DONE` Kolomsortering/filtering in pilots.
- `DONE` Oude tabel look-and-feel deels teruggebracht waar gevraagd.
- `IN_PROGRESS` Diagnostiek in UI-data:
  - `px_source` toegevoegd in Optie Tijdswaarde.
- `TODO` Definitieve cutover-strategie per tab (classic -> web).
- `TODO` UI performance stress-tests als vaste checklist.

## 4. DB Migratie + Compat
- `IN_PROGRESS` `DbMigrationService` draait over user DB's en logt resultaat.
- `DONE` Startup migratie uitgevoerd met success/fail rapportage.
- `IN_PROGRESS` Daily fullscope state-catchup logica:
  - startup en db-wissel triggeren rebuilds over alle asset classes.
- `TODO` `DbCompatService` voor expliciete legacy compatibility layer.
- `TODO` Contracttests voor Access/Excel-validatie:
  - kolomnamen
  - datatypes
  - kernwaardes
- `TODO` Formele "do-not-break" objectlijst als testbare baseline.

## 5. Daily Catchup Mechanisme
- `DONE` Startup price update check met skip als al gedaan vandaag.
- `DONE` Daily fullscope state-engine follow-up met nieuwe reason:
  - `startup_daily_catchup_fullscope_v1`
- `DONE` DB-wissel gebruikt dezelfde fullscope-catchup flow.
- `DONE` Handmatige fullscope window run uitgevoerd voor `2026-03-13` t/m `2026-03-21`.
- `IN_PROGRESS` Catchup robustness:
  - dividend baseline bug in incremental venster gefixt.
- `TODO` Extra guard: daily skip alleen als alle 4 engine-runs `ok` zijn:
  - `aandelen`
  - `opties`
  - `sprinters`
  - `asset_result_v2`

## 6. Kwaliteit en Observability
- `DONE` Projection metrics logging + summarizers aanwezig.
- `IN_PROGRESS` Handmatige parity checks uitgevoerd op kritieke tabwaarden.
- `TODO` Geautomatiseerde parity-report pipeline (dagelijks).
- `TODO` Release gate checklist:
  - parity ok
  - performance ok
  - migratie ok
  - legacy compat ok

## 7. Concrete Next Steps (uitvoer volgorde)
1. `TODO` Daily catchup skip-condition aanscherpen op 4/4 succesvolle engine classes.
2. `TODO` Access/Excel contracttest-set opzetten voor legacy validatie.
3. `TODO` Centrale `Event` + `StateStore` + `ProjectionBus` skeleton toevoegen.
4. `TODO` Transaction-engine v2 basis (command + replay) starten.
5. `TODO` Cutover-plan per tab uitwerken met rollback instructie.

## 8. Feature Flags (huidige stand)
- `DONE` `USE_AANDELEN_PROJECTION_V2`
- `DONE` `USE_OPTIES_OPEN_PROJECTION_V2`
- `DONE` `USE_OPTIE_TIJDSWAARDE_PROJECTION_V2`
- `DONE` `USE_SPRINTERS_OPEN_PROJECTION_V2`
- `DONE` `PV_UI_AANDELEN_WEB_V1`
- `DONE` `UI_OPTIES_WEB_V1`
- `DONE` `UI_OPTIE_TIJDSWAARDE_WEB_V1`
- `DONE` `UI_SPRINTERS_WEB_V1`
- `TODO` `ENABLE_DUAL_RUN_DIFF_REPORT` als structurele daily run.

## 9. Opmerking
- Oud document `TODO.md` blijft bestaan als klad.
- Dit document is de primaire werklijst voor modernisatie-implementatie.
