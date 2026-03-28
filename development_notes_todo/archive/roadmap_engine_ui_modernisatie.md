# Roadmap Engine + Moderne UI (PySide6 + WebEngine)

## Status van documenten
- `optimalisatie engine.md` blijft de basis voor architectuurprincipes en migratieguardrails.
- Dit document is een uitbreiding met concrete roadmap, workstreams en uitvoerplanning.
- Dit document vervangt het oude niet; samen vormen ze het implementatiekader.

---

## Scope
Doel: tegelijk moderniseren van
1. rekenkern (event-driven engine + projections),
2. transactie-engine (inclusief test-injecties en onderhoud output tabellen),
3. UI-laag (frame/card-based, cell-delta updates via WebEngine),
zonder breuk voor multi-user databases en Access/Excel validatie.

---

## Target architectuur (2 functionele assen)

### As 1: Number crunching / engine
- Input lanes:
1. statisch: transacties, referentie tabellen, historisch.
2. live: tick koersen, optie ticks.
- Core:
1. event bus -> state store -> projections.
2. transaction engine (orders, test transacties, optie-eind).
3. scenario/strategie compute services (toekomst).
- Output:
1. in-memory snapshots met versions.
2. additieve engine metadata tabellen.

### As 2: UI / analyse
- UI shell in PySide6.
- Renderlaag in Qt WebEngine (geen klassieke QTableWidget als primaire UX).
- Delta protocol:
1. snapshot init.
2. cell/field patches met `row_id`, `field`, `value`, `version`.
- UI update alleen getroffen frame/component.

---

## Workstreams

## WS-A: Engine Core
Deliverables:
1. `Event`, `StateStore`, `ProjectionBus`.
2. Versioned snapshots + invalidation policy.
3. Coalescing/debounce policy per event type.

Kern-KPI:
- voorspelbare update-latency,
- geen full recompute op elke tick.

## WS-B: Transaction Engine
Deliverables:
1. transaction ingest pipeline.
2. test-transaction injection API.
3. deterministic recompute voor output tabellen (incl. optie eind).
4. replay tool voor debugging.

Kern-KPI:
- reproduceerbare uitkomsten per db + eventset.

## WS-C: UI Modernisatie
Deliverables:
1. PySide6 + WebEngine bridge (`QWebChannel`).
2. frontend component library (frames/cards, not table-first).
3. delta renderer voor cell-level updates.
4. fallback classic-tab achter feature flag.

Kern-KPI:
- vloeiende updates zonder UI stutter.

## WS-D: DB Migratie en Compat
Deliverables:
1. `DbMigrationService` over alle user db's.
2. versiebeheer `engine_meta_version`.
3. `DbCompatService` voor legacy views/contracten.
4. validatie suite voor Access/Excel compat.

Kern-KPI:
- zero-breaking changes voor oude validatiestromen.

## WS-E: Observability en Quality
Deliverables:
1. metrics: p50/p95 rebuild, publish, ui_apply.
2. parity checks oud vs nieuw (dual-run).
3. audit trail van migraties per user db.

Kern-KPI:
- meetbare regressiecontrole en veilige cutovers.

---

## Fases en planning

## Fase 0 (1 week): Baseline en contracten
1. Definieer event schema en delta schema.
2. Vastleggen "do not break" lijst legacy tabellen/kolommen.
3. Multi-user db discovery finaliseren.
4. KPI baseline meten in huidige app.

Exit criteria:
- contracten vastgelegd,
- baseline metrics beschikbaar.

## Fase 1 (2-3 weken): Engine fundering
1. Implementeer `StateStore` + `ProjectionBus`.
2. Bouw `AandelenProjectionV2` incremental.
3. Versioned snapshot publisher.
4. Dual-run met diff rapportage.

Exit criteria:
- Aandelen V2 output parity binnen tolerantie,
- geen db breaking changes.

## Fase 2 (2 weken): Transaction engine v2
1. Introduceer transactie-command handlers.
2. Test-transactie injectiepad.
3. Replay + deterministic validation.
4. Integratie met optie-eind onderhoud.

Exit criteria:
- test injecties en replay stabiel,
- output tabellen correct bijgewerkt.

## Fase 3 (2-3 weken): UI pilot modern
1. Bouw WebEngine host tab (pilot: Aandelen).
2. Snapshot init + cell-delta updates.
3. Frame/card UX met kritieke KPI blokken.
4. Feature flag `UI_AANDELEN_WEB_V1`.

Exit criteria:
- UI voelt vloeiend onder live updates,
- fallback naar klassieke tab werkt.

## Fase 4 (2-4 weken): Schalen naar andere tabs
1. Opties/Sprinters/Portfolio Value adapters.
2. Hergebruik delta protocol.
3. Componentbibliotheek uitbreiden.

Exit criteria:
- 3+ tabs op nieuwe UI dataflow.

## Fase 5 (doorlopend): Scenario/strategie engine
1. Introduceer scenario definitions.
2. Run scenarios as separate projection context.
3. UI vergelijk live vs scenario state.

Exit criteria:
- eerste bruikbare scenario-analyse workflow.

---

## Beslislogica: uitbreiding of vervanging
- `optimalisatie engine.md`: architectuurprincipes + guardrails + migratieregels.
- `roadmap_engine_ui_modernisatie.md` (dit document): planning, workstreams, fasering, deliverables.
- Conclusie: uitbreiding, geen vervanging.

---

## Feature flags (verplicht)
1. `USE_AANDELEN_PROJECTION_V2`
2. `USE_TRANSACTION_ENGINE_V2`
3. `UI_AANDELEN_WEB_V1`
4. `UI_OPTIES_WEB_V1`
5. `ENABLE_DUAL_RUN_DIFF_REPORT`

Regel:
- nooit tegelijk alle flags hard aanzetten op alle db's.
- gefaseerd per user db, met rollback pad.
- huidige implementatie publiceert bij `USE_AANDELEN_PROJECTION_V2=1`:
- `snapshot_aandelen_projection_v2`
- `snapshot_aandelen_projection_v2_patch`
- `snapshot_aandelen_projection_v2_meta`

---

## Multi-user DB strategie
1. Discover alle geconfigureerde db's via settings.
2. Migratiebatch per db met resultaatregistratie:
- start_ts, end_ts, old_version, new_version, status, error.
3. Startup guard:
- waarschuw als db migration mismatch heeft.
4. Cutover policy:
- eerst test db, dan beperkte user set, dan breed.

---

## Legacy Access/Excel beschermingsplan
1. Nooit drop/rename op oude validatietabellen.
2. Alleen additieve schemawijzigingen of nieuwe tabellen.
3. Compat views/adapters voor oude queryverwachtingen.
4. Contracttests per release:
- kolomnamen,
- datatypen,
- kernwaarden.
5. Handmatige validatiechecklist voor oudste tabellen verplicht.

---

## Technische contracten (minimum)

### Delta payload
```json
{
  "view": "aandelen",
  "version": 10231,
  "changes": [
    {"row_id": "WDS", "field": "koers", "value": 22.75},
    {"row_id": "WDS", "field": "pct_change", "value": 0.0053}
  ]
}
```

### Snapshot init
```json
{
  "view": "aandelen",
  "version": 10200,
  "rows": [...]
}
```

---

## Team ritme en governance
1. Wekelijkse architecture review (engine + ui + db).
2. Dagelijkse parity rapporten tijdens dual-run.
3. Release gates:
- parity ok,
- perf ok,
- legacy tests ok,
- migratie over alle user db's ok.

---

## Eerstvolgende concrete taken
1. Maak `Event` + `ProjectionBus` skeleton modules.
2. Maak `DiffPolarsModel` contract in Python (engine-side).
3. Zet WebEngine pilot tab op met dummy snapshot + delta stream.
4. Bouw `DbMigrationService.migrate_all_user_dbs()`.
5. Voeg release checklist toe aan `TODO.md`.
