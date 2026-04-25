# Hardening Setup Run Multiple Instance App

Doel: de app veilig en voorspelbaar laten draaien wanneer twee of meer instances tegelijk open staan, terwijl user-databases gescheiden zijn maar `STOCKDATA.accdb` gedeeld is.

Dit document beschrijft wat later nog gebouwd moet worden, waarom dat nodig is, en in welke volgorde het zinvol is.

## Scope

Deze hardening gaat over gelijktijdig gebruik van meerdere app-instances op dezelfde gedeelde stock database.

Belangrijkste gedeelde schrijfpunten:

- `asset_last_prices`
- `option_last_prices`
- `option_series_master`
- `asset_dividend_calendar_current`
- `asset_dividend_calendar_history`
- `update_runs`
- `asset_driver_beta_snapshot`
- `single_asset_stepsize_settings`
- gedeelde ini-settings zoals beta-driver selectie

## Hoofdproblemen

Er zijn in de code meerdere patronen van het type:

- eerst `SELECT` of `UPDATE`
- daarna, als niets gevonden is, `INSERT`

Dat is niet instance-safe als twee processen tegelijk schrijven.

Er zijn ook processen die volledige snapshots vervangen met:

- `DELETE`
- daarna `INSERT`

Dat geeft `last writer wins` gedrag en tijdelijke lege toestand voor lezers.

Daarnaast zijn er instellingen die shared worden opgeslagen terwijl ze feitelijk user- of instance-specifiek zijn.

## Prioriteit

1. Database-constraints en upsert-hardening
2. Scheduler locking
3. Snapshot rebuild locking
4. Shared settings opschonen
5. Observability en foutafhandeling

## 1. Unieke indexen toevoegen op gedeelde tabellen

### 1.1 `asset_last_prices`

Toevoegen:

- unieke index op `(ib_symbol, ib_currency)`

Waarom:

- twee instances kunnen nu tegelijk dezelfde rij missen en beide een `INSERT` doen
- zonder unieke index kunnen duplicate rows ontstaan

Gevolg na invoering:

- duplicates worden database-side voorkomen
- code moet daarna duplicate-insert netjes opvangen en fallbacken naar `UPDATE`

### 1.2 `option_last_prices`

Toevoegen:

- unieke index op `(series_id)`

Waarom:

- huidige code doet `UPDATE`, daarna `INSERT` als niets gevonden is
- twee processen kunnen tegelijk dezelfde `series_id` inserten

### 1.3 `option_series_master`

Toevoegen:

- unieke business key op:
  `asset_rollup, optie_call_put, strike, expiry, ib_currency`

Waarom:

- deze tabel wordt nu gevuld met `SELECT TOP 1 ...` en daarna `INSERT`
- bij twee instances die tegelijk een nieuwe serie zien, kunnen duplicate master-rows ontstaan

Let op:

- vóór toevoegen van de unieke index eerst bestaande duplicates detecteren en opschonen

## 2. Upsert-patronen vervangen door instance-safe write-flow

Alle plekken met:

- `UPDATE ...`
- `if rowcount == 0: INSERT ...`

moeten hardened worden.

Nieuwe aanpak:

1. probeer `UPDATE`
2. als geen rij geraakt:
   probeer `INSERT`
3. als `INSERT` faalt op unieke index:
   doe nogmaals `UPDATE`

Waarom:

- dit is de simpelste manier om met Access en meerdere writers om te gaan zonder echte `MERGE`

Toepassen op:

- `asset_last_prices`
- `option_last_prices`
- `option_series_master`

## 3. Scheduler locking in de database

Huidige situatie:

- elke app-instance start zijn eigen scheduler
- de check `has_successful_run_today(task_name)` en daarna `start_update_run(...)` is niet atomair

Gevolg:

- twee instances kunnen dezelfde daily task tegelijk starten

Benodigde aanpassing:

- maak een DB-side lock-mechanisme in `update_runs` of een aparte tabel `scheduled_task_locks`

Mogelijke aanpak:

1. lock-record per `task_name + run_day`
2. unieke index op `(task_name, run_day)`
3. task mag alleen starten als lock succesvol geclaimd wordt

Waarom:

- dan draait bijvoorbeeld `dividend_calendar_refresh` hooguit 1 keer per dag, ook met meerdere app-instances

## 4. Dividend calendar writes idempotent maken

Huidige situatie:

- per asset: `DELETE current`, dan `INSERT current`, dan `INSERT history`

Risico:

- dubbele scheduler-run geeft dubbele history-records
- current blijft vaak functioneel goed, history niet

Benodigde aanpassing:

- voeg idempotentie toe aan history

Opties:

- unieke index op een business key zoals `(asset_rollup, fetched_at)`
- of een `run_id` koppelen aan alle history writes en unieke index op `(run_id, asset_rollup)`

Waarom:

- voorkomt dubbele history door dubbele scheduler-run of retry

## 5. Beta snapshot rebuild beschermen

Huidige situatie:

- `asset_driver_beta_snapshot` wordt volledig geleegd en opnieuw gevuld

Risico:

- twee rebuilds tegelijk geven `last writer wins`
- lezers kunnen tijdelijk een lege tabel zien

Benodigde aanpassing:

- voeg rebuild lock toe voor beta snapshot

Voorkeursoptie:

1. claim DB-lock `beta_snapshot_rebuild`
2. alleen lock-owner mag rebuild uitvoeren

Aanvullend:

- overweeg staged rebuild via tijdelijke tabel en daarna swap/replace

Waarom:

- voorkomt dubbele rebuild
- verkleint venster waarin de snapshot leeg of inconsistent is

## 6. `single_asset_stepsize_settings` user-specifiek maken

Huidige situatie:

- stepsize settings staan in gedeelde `STOCKDATA.accdb`
- elke app-instance laadt een lokale cache en flusht later bulk terug

Risico:

- user A zet instelling X
- user B zet instelling Y
- laatste flush overschrijft de andere zonder waarschuwing

Benodigde aanpassing:

Voorkeursoptie:

- maak deze settings local per user, niet in gedeelde stock database

Bijvoorbeeld:

- in `settings_local.ini`
- of aparte local sqlite/access per user

Als gedeeld moet blijven:

- voeg kolom `owner_user` of `profile_name` toe
- sleutel wordt dan `(owner_user, asset_rollup)`

Waarom:

- dit zijn analyse- en UI-voorkeuren, geen gedeelde marktdata
- shared opslag maakt hier functioneel weinig zin

## 7. Gedeelde ini-settings opschonen

Controleer alle settings die nu shared geschreven worden maar feitelijk user-specifiek zijn.

In ieder geval heroverwegen:

- beta-driver enabled map
- eventuele chart selectors en view state die nog niet local-only zijn

Benodigde aanpassing:

- alles wat persoonlijke UI/analytische voorkeur is naar local settings verplaatsen

Waarom:

- anders krijg je last-write-wins tussen twee users of twee app-instances van dezelfde user

## 8. Access lock/retry laag toevoegen

Access kan bij gelijktijdige writes tijdelijke lock errors geven.

Benodigde aanpassing:

- centrale retry helper voor writes naar shared stock DB

Gedrag:

- vang bekende pyodbc/Access lock errors af
- retry 2-5 keer met korte backoff

Waarom:

- veel concurrency-problemen in Access zijn transient
- zonder retry krijg je onnodige user-visible fouten

Toepassen op:

- live price saves
- option series writes
- dividend scheduler writes
- beta snapshot writes

## 9. Shared-writer observability toevoegen

Benodigde logging:

- welke instance schrijft
- naar welke gedeelde tabel
- hoeveel rijen
- lock/retry events
- duplicate-prevented events

Praktisch:

- voeg `instance_id` toe bij startup
- log die mee in scheduler runs en shared-db writes

Waarom:

- zonder instance-identiteit is multi-instance gedrag moeilijk te debuggen

## 10. Startup policy bepalen

Er moet een expliciet ontwerpbesluit komen:

- mag elke instance alle background jobs draaien
- of mag maar 1 instance de shared background jobs draaien

Voorkeur:

- user-facing app instances mogen allemaal lezen
- maar shared background jobs moeten door DB-locking effectief single-writer worden

Waarom:

- dit houdt architectuur simpel
- voorkomt dat je “primary app instance” concept kunstmatig moet introduceren

## Aanpak in uitvoerbare volgorde

### Fase 1

- inventariseer en dedup bestaande data in:
  - `asset_last_prices`
  - `option_last_prices`
  - `option_series_master`
- voeg unieke indexen toe

### Fase 2

- vervang update-then-insert code door retry-safe upsert flow
- voeg lock-retry helper toe

### Fase 3

- bouw scheduler DB-locking
- maak dividend history idempotent

### Fase 4

- bescherm beta snapshot rebuild met lock
- verbeter snapshot replace patroon waar nodig

### Fase 5

- verplaats `single_asset_stepsize_settings` naar local/user-scope
- verplaats overige shared user settings naar local-only

### Fase 6

- voeg instance-id logging toe
- test met 2 gelijktijdige app-instances

## Testscenario’s

Na implementatie expliciet testen:

1. Twee app-instances tegelijk open, beide met live prices aan
2. Twee app-instances tegelijk open, beide laten draaien tot `asset_last_prices` en `option_last_prices` meerdere save-cycli hebben gedaan
3. Twee app-instances tegelijk open rond scheduler startmoment
4. Twee app-instances tegelijk open, beide openen/wijzigen single asset analyse settings
5. Twee app-instances tegelijk open, beide laden optie-universum met nieuwe serie
6. Tijdens beta rebuild tegelijk lezen vanuit UI

## Gewenst eindresultaat

Als deze hardening klaar is:

- geen duplicate rows meer in shared live price/master tabellen
- background jobs draaien effectief 1 keer per dag per task
- tijdelijke Access lock conflicts worden opgevangen met retries
- user-voorkeuren overschrijven elkaar niet meer
- multi-instance draaien is functioneel veilig en voorspelbaar
