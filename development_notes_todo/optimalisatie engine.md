# Migratieplan Naar Event-Driven Engine (zonder big-bang)

Aanvullende roadmap: zie `development_notes_todo/roadmap_engine_ui_modernisatie.md` voor workstreams, planning en cutover-volgorde voor gecombineerde engine + moderne UI migratie.

## Doelbeeld
We migreren naar een architectuur met:
- centrale state-store (events + snapshots),
- projection services per tab (incremental updates),
- asynchrone verwerking buiten de UI-thread,
- diff-based UI updates (geen full reset bij elke tick),
- duidelijke observability (latency, queue, dropped/coalesced updates).

Randvoorwaarden:
- meerdere users/databases blijven ondersteund,
- bestaande Access/Excel-validatie mag niet breken,
- oude tabellen blijven backward compatible.

---

## Niet-onderhandelbare DB-principes
1. Geen breaking wijzigingen op oude tabellen.
2. Oude kolommen/typen blijven bestaan zolang Access/Excel-validatie die gebruikt.
3. Nieuwe functionaliteit via:
- nieuwe tabellen, of
- additieve kolommen (nullable/default) op bestaande tabellen.
4. Elke migratie is idempotent (`IF NOT EXISTS`-stijl check).
5. Per user-db dezelfde migratieversie afdwingen (ook niet-Onno DB’s).
6. Altijd een compatibiliteitslaag aanbieden (views/adapters) richting oude query-verwachtingen.

---

## Mapstructuur (target)
```text
portefeuille_viewer/
  domain/
    events.py
    state_store.py
    projection_bus.py
    portfolio_engine_v2.py
  projections/
    aandelen_projection.py
    opties_projection.py
    sprinters_projection.py
    portfolio_value_projection.py
  services/
    market_data_service.py
    snapshot_publish_service.py
    db_migration_service.py
    db_compat_service.py
  ui/
    models/
      diff_polars_model.py
  ui_logica/
    aandelen_tab_logica_v2.py
  development_notes_todo/
    optimalisatie engine.md
```

---

## Interfaces per service (target contract)

### 1) Event ingest / state
```python
class Event(NamedTuple):
    ts: datetime
    type: str
    key: str
    payload: dict

class StateStore:
    def apply(self, event: Event) -> set[str]:
        """Returns changed entity keys (asset_rollup ids)."""
```

### 2) Projection layer
```python
class Projection:
    name: str
    depends_on: set[str]
    def recompute(self, changed_keys: set[str]) -> None: ...
    def snapshot(self) -> pl.DataFrame: ...
```

### 3) UI adapter
```python
class TabViewAdapter:
    def get_snapshot(self, tab_name: str) -> pl.DataFrame: ...
    def get_patch(self, tab_name: str, since_version: int) -> list[dict]: ...
```

### 4) Migratie/compat
```python
class DbMigrationService:
    def migrate_all_user_dbs(self) -> None: ...
    def get_db_version(self, db_path: str) -> int: ...

class DbCompatService:
    def ensure_legacy_views(self, db_path: str) -> None: ...
```

---

## Uitvoering in 3 iteraties

## Iteratie 1: Stabiliseren en meetbaar maken (laag risico)
Doel: performance verbeteren zonder functionele breuk.

Scope:
1. Event coalescing en throttle beleid expliciet maken per datastroom:
- price ticks (hoogfrequent),
- option-timevalue updates,
- order/database wijzigingen.
2. Metrics toevoegen:
- `build_ms`, `publish_ms`, `ui_apply_ms`, queue lengte, drop/coalesce count.
3. Aandelen-tab:
- async rebuild behouden,
- partial UI-update pad opnieuw introduceren voor price-only updates (geen full model reset).
4. Snapshot versioning:
- elk snapshot krijgt `version` + `updated_at`.

DB-impact:
- geen schemawijzigingen nodig.

Acceptatiecriteria:
- UI blijft responsief bij hoge tick-rate.
- geen regressie in bestaande outputs.
- logging toont bottleneck-locaties.

---

## Iteratie 2: Projection-engine introduceren (parallel naast huidige pad)
Doel: nieuwe architectuur naast bestaande laten draaien, vergelijkbaar output.

Scope:
1. Nieuwe `StateStore` + `ProjectionBus` toevoegen.
2. `AandelenProjectionV2` bouwen met incremental updates op `asset_rollup`.
3. Dual-run modus:
- bestaande summary blijft actief,
- V2 projection rekent parallel,
- dagelijkse diff-check script vergelijkt resultaten per asset.
4. Tab adapter:
- feature flag `USE_AANDELEN_PROJECTION_V2` (per user/db aan/uit).

DB-impact:
1. Nieuwe metadata-tabellen (additief):
- `engine_meta_version`,
- `engine_projection_state`,
- `engine_projection_metrics`.
2. Geen wijzigingen aan oudste validatietabellen.

Multi-user aanpak:
1. Centrale user-db discovery implementeren (niet hardcoded op Onno).
2. Migraties draaien over alle geconfigureerde user db’s.
3. Per db migratieresultaat loggen (success/fail/version).

Acceptatiecriteria:
- V2 output binnen afgesproken tolerantie vs current.
- Geen impact op Access/Excel-validatie.
- Feature flag fallback naar oude pad werkt direct.

---

## Iteratie 3: Cutover per tab + compatibiliteitscontract
Doel: gecontroleerd overstappen zonder legacy te breken.

Scope:
1. `Aandelen` volledig op projection-engine.
2. Daarna gefaseerd `Opties`, `Sprinters`, `Portfolio Value`.
3. UI overal naar diff-based model updates.
4. Oude heavy summary-paden markeren als deprecated, niet direct verwijderen.

DB-impact:
1. Alleen additieve uitbreidingen.
2. `DbCompatService` onderhoudt legacy views/exports voor Access/Excel.
3. Backfill jobs voor nieuwe tabellen zonder oude data te muteren.

Acceptatiecriteria:
- performance KPI gehaald (bijv. P95 tab refresh < 300ms bij normale load),
- functionele parity bevestigd,
- legacy validatiebestanden blijven werken.

---

## Migratiestrategie voor meerdere user DB’s
1. Definieer bron van waarheid voor db-locaties (`settings`/registry/config map).
2. Bouw `discover_user_databases()` die alle actieve db’s retourneert.
3. Voor elke db:
- lock/check,
- versie lezen,
- ontbrekende migraties uitvoeren,
- compatibiliteitsviews valideren,
- healthcheck + logging.
4. Falen van 1 db blokkeert andere db’s niet; wel duidelijke rapportage.
5. In UI: waarschuwing tonen als db achterloopt qua migratie.

---

## Legacy Access/Excel bescherming
1. “Do not break list” documenteren:
- tabellen/kolommen die Access/Excel gebruikt.
2. Contracttests toevoegen:
- exporteer legacy query-resultaten voor en na wijziging,
- vergelijk kolomnamen/typen/waarden (met tolerantie voor floats).
3. Nooit rename/drop op legacy objecten in-place.
4. Als nieuwe semantiek nodig is:
- nieuwe tabel/view toevoegen,
- oude output desnoods via adapter transformatie behouden.
5. Elke release: “legacy validation checklist” verplicht.

---

## Risico’s en mitigaties
1. Risico: inconsistentie tussen oude en nieuwe engine.
- Mitigatie: dual-run + diff-rapportage + feature flags.
2. Risico: schema drift tussen user db’s.
- Mitigatie: verplichte migratieversie check bij startup.
3. Risico: regressie in Access/Excel validatie.
- Mitigatie: compat contracttests en immutable legacy objecten.
4. Risico: UI-jitter door te frequente updates.
- Mitigatie: debounce/coalesce + patch-based model updates.

---

## Concreet startpakket (volgende 2 weken)
1. `DbMigrationService` met multi-db discovery en version table.
2. Metrics/logging op huidige Aandelen-keten.
3. Partial update pad terugbrengen in `PolarsTableModel` + `AandelenTab`.
4. Feature flag infrastructuur voor dual-run.
5. Eerste `AandelenProjectionV2` skeleton + parity diff tool.

---

## Beslisregels voor schemawijzigingen
1. Is wijziging nodig voor oude tabel?
- Nee: maak nieuwe tabel.
- Ja: alleen additieve kolom, nullable/default.
2. Wordt oude Access/Excel validatie geraakt?
- Ja: eerst compat view + contracttest maken.
3. Meer dan 1 user-db betrokken?
- Altijd migratie over alle db’s uitvoeren vóór feature enable.
