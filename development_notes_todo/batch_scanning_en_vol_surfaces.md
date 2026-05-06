# Batch Scanning en Vol Surfaces

## Status en richting

Dit document vervangt het eerdere plan waarin optiechains primair via `reqSecDefOptParams`
en brede market-data scans werden opgebouwd. De praktische tests in `vol_surf_poc` laten een
betere basis zien:

- optiecontracten ophalen via TWS API `reqContractDetails`;
- strike en multiplier leeg laten;
- voor grote chains per maand en per zijde ophalen;
- de volledige raw/normalized contractDetails per asset opslaan in parquet;
- Access alleen gebruiken voor runlogging en bestaande app-masterdata, niet als bulk-chainstore.

De chain-scanner wordt een aparte tool naast de portefeuilleviewer. De tool moet later ook vanuit
de portefeuilleviewer geopend kunnen worden.

Besluiten per 2026-05-05:

- scanner-horizon wordt instelbaar, default `3` maanden;
- laatst ingestelde horizon wordt opgeslagen in `settings_shared.ini`;
- parquet target directory wordt instelbaar, default `C:\Users\onno\OneDrive\Beleggen\asset_data_parquet`;
- alle oude contracten voorlopig bewaren;
- eerste scope is aandelen, maar het ontwerp moet later index- en futureopties kunnen dragen;
- scanner draait vanuit de portefeuilleviewer altijd in een apart proces;
- in `portefeuille_viewer_1.4` komt een standalone entrypoint `optie_scanner.py`.
- assetselectie gebruikt `asset_rollup_data.optie_scanner_incl`;
- onderliggend IBKR type gebruikt `asset_rollup_data.ib_asset_type`;
- default TWS poort voor de scanner is `7496`;
- parallelisme moet direct functioneel zijn, maar de default blijft `1` worker.
- right request mode wordt instelbaar: `separate` of `combined`.
- TWS bleek bij langere runs te kunnen vastlopen; daarom zijn batchgrootte, pauzes en random
  client-id range expliciete scannerinstellingen.

---

## Kernbeslissing

### Chain registry in parquet

De brede optiecontract-registry komt in parquet, met een bestand per asset:

```text
<chain_dir>/
  CHAIN_MSFT.parquet
  CHAIN_ABN.parquet
  CHAIN_BMW.parquet
```

Default directory:

```text
C:\Users\onno\OneDrive\Beleggen\asset_data_parquet
```

De GUI moet deze directory kunnen wijzigen en de waarde in settings bewaren. Omdat een
asset-parquet bij een refresh volledig wordt vervangen, moet schrijven via een tijdelijk bestand
in dezelfde directory gebeuren en daarna pas het bestaande parquet vervangen.

Elk bestand bevat alle bekende optiecontracten voor dat asset, inclusief contracten die in eerdere
runs gezien zijn maar in de meest recente run niet opnieuw terugkwamen. De registry is daarmee een
historische lokale contract-id cache.

Updateflow per asset:

1. Lees bestaand `CHAIN_<asset>.parquet` als het bestaat.
2. Haal actuele contractDetails op bij IBKR.
3. Normaliseer de nieuwe contracten naar hetzelfde schema.
4. Combineer bestaand + nieuw.
5. Dedup/update op `conid`.
6. Schrijf het volledige bestand opnieuw weg.

Parquet is hier bewust gekozen omdat dit bulkdata is. Access werd in eerdere projecten traag bij
grote aantallen row-by-row writes. Parquet kan deze chainbestanden snel lezen en herschrijven.

### `option_series_master` blijft voor gebruikte series

De bestaande Access-tabel `option_series_master` blijft de master voor series die de app concreet
gebruikt:

- series waarin orders/posities bestaan of bestonden;
- series die live optieprijzen nodig hebben;
- series die handmatig gekozen zijn bij ambiguiteit;
- eventueel series die expliciet vanuit chain parquet naar een watchlist/promoted set worden gezet.

Niet elke mogelijke MSFT strike/expiry hoeft in `option_series_master`.

De bestaande resolver-flow blijft relevant. Als een order binnenkomt:

1. Zoek eerst in de parquet chain registry.
2. Bij precies 1 kandidaat: koppel/importeer deze naar `option_series_master`.
3. Bij meerdere kandidaten: toon manual resolver met de parquet/IBKR kandidaten.
4. Bij geen kandidaat: fallback naar live `reqContractDetails` resolver.

Dit is belangrijk voor adjusted series, zoals ABN, waar dezelfde expiry/strike/right meerdere
contracten kan opleveren met verschillende `trading_class`, `local_symbol` en `multiplier`.

---

## IBKR ophaalstrategie

De basis komt uit `vol_surf_poc/basic_abn_option_chain.py`.

### ContractDetails request

Voor fase 1 wordt uitgegaan van opties op aandelen (`ib_asset_type = STK`). Per request wordt een
`Contract` object gebouwd met:

```python
contract.secType = "OPT"
contract.symbol = ib_symbol
contract.currency = ib_currency
contract.exchange = option_exchange
contract.right = "C"  # of "P"; bij combined mode niet zetten
contract.lastTradeDateOrContractMonth = "202606"  # maandniveau

# Niet zetten:
# contract.strike
# contract.multiplier
```

Voor kleine Europese chains kan `lastTradeDateOrContractMonth` leeg werken. Voor grote US chains
zoals MSFT bleek dat te breed en onbetrouwbaar. Daarom wordt de productiestrategie:

```text
per asset
  per maand binnen horizon
    per right C/P
      reqContractDetails
```

Voor 3 maanden zijn dat 6 requests per asset.

Right request mode:

```text
separate -> per maand 2 requests: C en P apart
combined -> per maand 1 request: right leeg, IBKR geeft C en P samen terug als dit werkt voor die chain
```

Voor sommige US aandelen lijkt `combined` goed en sneller te werken. De instelling blijft bewust
per tool beschikbaar, omdat brede requests per onderliggende kunnen verschillen in betrouwbaarheid.

### TWS pacing en client-id beleid

De scanner moet TWS defensief belasten. De eerste praktijkrun met `1` worker en `3` maanden liep na
ongeveer 26 assets vast in TWS zelf. De applicatie kan TWS niet betrouwbaar "unfreezen"; een
API-disconnect ruimt alleen de client-sessie op. Als TWS intern vastloopt of geheugen/queues vol
lopen, blijft handmatig herstarten of killen soms nodig.

Default pacing:

```text
request_pause_sec = 1.0
asset_pause_sec = 2.0
max_assets_per_start = 10
```

Per assetscan wordt een random client-id gekozen binnen een instelbare range:

```text
client_id_min = 1000
client_id_max = 10000
```

Een andere client-id kan sessieconflicten en oude request-state vermijden, maar is geen garantie
tegen TWS-overbelasting. De belangrijkste bescherming blijft: kleine batches, expliciete pauzes en
succesvolle assets automatisch uitvinken zodat een run hervat kan worden.

Latere asset types:

```text
ib_asset_type = STK  -> optiecontract secType OPT
ib_asset_type = IND  -> optiecontract secType OPT, onderliggende index
ib_asset_type = FUT  -> optiecontract secType FOP, future option
```

Index- en futureopties vragen extra mapping. De screenshots laten bijvoorbeeld zien:

- AEX/EOE indexopties: underlying `AEX IND`, option exchange `FTA`, trading class zoals `A5`;
- Micro Bitcoin future options: security type `Future Options`, exchange `CME`, multiplier `0.1`;
- Micro E-mini Nasdaq future options: security type `Future Options`, exchange `CME`, multiplier `2`.

Daarom is `ib_asset_type` bewust de IBKR security type van de onderliggende waarde, niet alleen een
vrije app-classificatie. Fase 1 mag `IND` en `FUT` skippen met duidelijke logging; de core moet
zodanig gescheiden blijven dat `FOP` later kan worden toegevoegd.

### Maandhorizon

De tool moet instelbaar maken hoeveel maanden vooruit gescand worden. Default:

```text
3 maanden
```

De laatst gebruikte waarde wordt opgeslagen in `settings_shared.ini`, zodat standalone tool en
portefeuilleviewer-integratie dezelfde default gebruiken.

Bij maandrequests komen meerdere expiries binnen, bijvoorbeeld voor MSFT met `202606`:

```text
20260605
20260612
20260618
```

### Exchangekeuze

De exchange komt uit bestaande referentiedata waar mogelijk:

- `optie_referentie_data.opt_exchange`;
- fallback op `SMART` voor US namen;
- fallback op bekende Europese exchanges zoals `FTA` of `EUREX` waar van toepassing.

De tool moet per asset loggen welke exchange gebruikt is. Later kan de GUI exchange overrides
ondersteunen.

Voorlopige fallback-regels:

```text
US aandelen          -> SMART
Amsterdam/Nederland  -> FTA
Duitsland            -> EUREX
```

Deze regels zijn defaults. `optie_referentie_data` en later GUI overrides moeten voorrang kunnen
krijgen.

---

## Parquet schema

Minimaal schema per `CHAIN_<asset>.parquet`:

```text
conid                       int64
asset_rollup                string
ib_symbol                   string
ib_currency                 string
sec_type                    string
exchange                    string
primary_exchange            string
local_symbol                string
trading_class               string
expiry                      date
last_trade_date_raw         string
right                       string
strike                      float64
multiplier                  float64
contract_month              string
source                      string      # tws_contract_details
first_seen_at               datetime
last_seen_at                datetime
last_refresh_run_id         string
last_request_month          string
last_request_right          string
raw_contract_json           string
```

Dedup key:

```text
conid
```

Als `conid` ontbreekt of ongeldig is, wordt het record niet als geldig contract opgeslagen maar in
de runlog als rejected geteld.

Updategedrag:

- nieuw `conid`: insert met `first_seen_at = now`, `last_seen_at = now`;
- bestaand `conid`: behoud `first_seen_at`, update `last_seen_at` en metadata;
- niet opnieuw gezien: laten staan, `last_seen_at` blijft oud.

Actueel filter later:

```text
last_seen_at >= laatste succesvolle refresh voor asset
```

of ruimer:

```text
last_seen_at >= vandaag - 30 dagen
```

---

## Access runlogging

De scanner schrijft geen bulkcontracten naar Access. Wel schrijft hij runlogging naar de stockdb.
De stockdb-locatie komt uit de bestaande settings:

```python
from portefeuille_viewer.config import get_settings
stock_db_path = get_settings().get_stockdata_db_path()
```

### Assetselectie

Voor scanner-deelname is een nieuwe kolom in `asset_rollup_data` gemaakt:

```sql
optie_scanner_incl
```

Aanbevolen Access type:

```text
YESNO
```

Als de kolom tijdelijk als tekst bestaat, moet de scanner robuust waarden zoals `1`, `true`, `yes`,
`ja`, `j`, `y` als aan behandelen. Structureel is `YESNO` beter dan tekst, omdat filters en UI
checkboxes dan eenvoudiger en minder foutgevoelig zijn.

Voor IBKR onderliggend type is ook een nieuwe tekstkolom gemaakt:

```sql
ib_asset_type TEXT
```

Aanbevolen waarden volgen IBKR secType:

```text
STK
IND
FUT
```

Fase 1 scant alleen:

```text
optie_scanner_incl = true
ib_asset_type = STK
```

Assets met `IND` of `FUT` worden in fase 1 nog niet opgehaald, maar wel zichtbaar/logbaar gemaakt
als skipped reason `unsupported_ib_asset_type`. Dit voorkomt stille verwarring.

Nieuwe tabellen:

```sql
CREATE TABLE option_chain_scan_runs (
    run_id TEXT(64) PRIMARY KEY,
    started_at DATETIME,
    finished_at DATETIME,
    status TEXT(32),
    tws_host TEXT(64),
    tws_port LONG,
    client_id LONG,
    parquet_dir LONGTEXT,
    asset_count LONG,
    contracts_seen LONG,
    contracts_inserted LONG,
    contracts_updated LONG,
    contracts_rejected LONG,
    error_message LONGTEXT
);
```

```sql
CREATE TABLE option_chain_scan_asset_log (
    id AUTOINCREMENT PRIMARY KEY,
    run_id TEXT(64),
    asset_rollup TEXT(64),
    ib_symbol TEXT(64),
    ib_currency TEXT(16),
    option_exchange TEXT(32),
    status TEXT(32),
    started_at DATETIME,
    finished_at DATETIME,
    months_requested LONG,
    requests_sent LONG,
    contracts_returned LONG,
    contracts_inserted LONG,
    contracts_updated LONG,
    contracts_rejected LONG,
    parquet_path LONGTEXT,
    error_message LONGTEXT
);
```

Optioneel detailniveau voor debugging:

```sql
CREATE TABLE option_chain_scan_request_log (
    id AUTOINCREMENT PRIMARY KEY,
    run_id TEXT(64),
    asset_rollup TEXT(64),
    request_month TEXT(8),
    right_code TEXT(1),
    status TEXT(32),
    contracts_returned LONG,
    duration_ms LONG,
    error_message LONGTEXT
);
```

Access writes blijven beperkt tot enkele rijen per run/asset/request. Dat voorkomt het bekende
performanceprobleem van grote row-by-row bulk writes.

---

## Standalone Qt tool

Werknaam:

```text
option_chain_retriever
```

Voorgestelde locatie:

```text
portefeuille_viewer/option_chain_retriever/
```

De tool moet standalone kunnen starten, maar ook vanuit de portefeuilleviewer geopend kunnen worden.
Daarom splitsen we UI en core:

```text
option_chain_retriever/
  chain_scanner.py          # IBKR/TWS scanner, geen Qt
  chain_store.py            # parquet read/merge/write
  chain_run_repository.py   # Access runlog
  asset_source.py           # asset_rollup_data + optie_referentie_data lezen
  parquet_viewer.py         # parquet inspectie helpers/model
  chain_retriever_window.py # Qt GUI
  main.py                   # standalone entrypoint
```

Daarnaast komt in de root van `portefeuille_viewer_1.4`:

```text
optie_scanner.py
```

Dit is het eenvoudige standalone startpunt:

```powershell
python optie_scanner.py
```

De portefeuilleviewer opent dezelfde tool via een knop in Settings, maar altijd als apart proces.
De hoofdapp deelt dus geen QApplication, geen UI thread en geen IB-verbinding met de scanner.

Procesmodel vanuit de hoofdapp:

```text
Settings knop
  -> QProcess/subprocess.Popen(...)
  -> python optie_scanner.py
  -> scanner heeft eigen process, eigen TWS client-id(s), eigen UI thread
```

Als de scanner crasht of hangt, moet de portefeuilleviewer blijven draaien.

### GUI-functionaliteit

Minimaal:

- stockdb-pad tonen uit settings;
- parquet target directory kiezen en opslaan in settings;
- TWS host/port/client-id instellen;
- client-id range instellen; per assetscan wordt random een client-id uit die range gebruikt;
- assetlijst laden uit `asset_rollup_data`;
- filteren/selecteren: 1 asset, selectie assets, alle assets;
- horizon in maanden;
- parallelisme instellen: `1` is sequentieel, `2+` gebruikt meerdere workers/clientIds;
- max assets per start instellen; succesvolle assets worden na afloop automatisch uitgevinkt;
- pauze tussen IBKR-requests en tussen assets instellen;
- calls/puts aan/uit;
- start/stop knop;
- live logpaneel;
- progress per asset;
- resultaatkolommen: status, returned, inserted, updated, rejected, parquet path;
- parquet viewer tab.

### Parquet viewer

De GUI moet parquet files kunnen tonen:

- asset kiezen of parquet file openen;
- tabelweergave met sort/filter;
- kolommen tonen/verbergen;
- snelle filters: expiry range, right, strike range, trading_class, multiplier;
- summary: aantal contracts, expiries, strikes, rights, laatste `last_seen_at`;
- export naar CSV optioneel.

Voor grote bestanden moet de viewer niet alles onnodig kopieren. Polars scan/read is de voorkeur.

### Settings

Nieuwe settings in `settings_shared.ini`:

```ini
[option_chain_scanner]
parquet_dir = C:\Users\onno\OneDrive\Beleggen\asset_data_parquet
horizon_months = 3
parallel_workers = 1
right_request_mode = separate
tws_host = 127.0.0.1
tws_port = 7496
client_id_min = 1000
client_id_max = 10000
request_pause_sec = 1.0
asset_pause_sec = 2.0
max_assets_per_start = 10
```

`parallel_workers = 1` betekent sequentieel. Ook in sequentiele modus krijgt iedere assetscan een
random client-id uit de ingestelde range. Bij `2+` wordt hetzelfde principe gebruikt per asset; de
workers delen dus geen vaste client-id.

Parallelisme moet vanaf de eerste implementatie functioneel zijn, maar de default staat op `1` om
datakwaliteit en reproduceerbaarheid eerst te bewaken. Later kan de GUI naar `2+` gezet worden voor
snellere batches of load balancing over meerdere TWS/Gateway instanties.

---

## Relatie met IV / vol surfaces

De IV job leest straks direct uit de chain parquet registry.

Flow:

```text
CHAIN_MSFT.parquet
  -> filter expiry <= vandaag + 60 dagen
  -> filter vrijdag / maandselectie
  -> filter moneyness op basis van spot
  -> filter C/P
  -> request IV via conid
  -> schrijf IV snapshot naar parquet
```

IV-output hoort in aparte opslag, niet in de chain registry:

```text
option_iv_snapshots/
  asset_rollup=MSFT/
    IV_MSFT_2026-05-05_153000.parquet
```

De chain registry is contract-identiteit. IV snapshots zijn meetdata/tijdreeks.

---

## Implementatiefasen

### Fase 1 - Core scanner zonder GUI

- [ ] `basic_abn_option_chain.py` logica extraheren naar herbruikbare scanner.
- [ ] Per asset/month/right `reqContractDetails` ophalen.
- [ ] Normaliseren naar DataFrame.
- [ ] Per asset parquet merge/dedup/write.
- [ ] Runlog tabellen in Access aanmaken en vullen.
- [ ] CLI entrypoint voor 1 asset en batch assets.

### Fase 2 - Asset source en settings

- [ ] Assetlijst lezen uit `asset_rollup_data`.
- [ ] Kolom `optie_scanner_incl` lezen als scanner-inclusievlag.
- [ ] Kolom `ib_asset_type` lezen als IBKR onderliggend secType.
- [ ] In fase 1 alleen aandelen/STK selecteren.
- [ ] `ib_symbol`, `ib_currency`, optiereferentie/exchange bepalen.
- [ ] Stockdb-pad uit settings lezen.
- [ ] Parquet directory in settings opslaan.
- [ ] Horizon en parallelisme in settings opslaan.

### Fase 3 - Qt GUI

- [ ] Standalone window bouwen.
- [ ] Assetselectie, target directory, TWS instellingen.
- [ ] Worker thread zodat UI niet blokkeert.
- [ ] Logpaneel en progressweergave.
- [ ] Stop/cancel mechanisme.

### Fase 4 - Parquet viewer

- [ ] Parquet file openen vanuit GUI.
- [ ] Tabelweergave + summary.
- [ ] Filters voor expiry/right/strike/trading_class/multiplier.

### Fase 5 - Integratie portefeuilleviewer

- [ ] Knop in settings of tools-menu: "Option Chain Retriever".
- [ ] Tool starten via apart proces, niet als child widget in dezelfde processruimte.
- [ ] Standalone entrypoint `optie_scanner.py`.
- [ ] Geen gedeelde IB-verbinding; tool gebruikt eigen TWS client-id(s).

### Fase 6 - IV workflow

- [ ] IV-universe bouwen uit chain parquet.
- [ ] Contracten selecteren op DTE/moneyness/right.
- [ ] IV ophalen via conid met subscription-rotation.
- [ ] IV snapshots naar aparte parquet opslag.

---

## Nog te beslissen

1. Of `optie_scanner_incl` in Access wordt omgezet van tekst naar `YESNO`.
2. Welke extra mappingvelden nodig zijn voor `IND` en `FUT`:
   option product, option exchange, trading class, future localSymbol/conId.
3. Welke bewaartermijn later voor verlopen contracten; voorlopig alles bewaren.
4. Of parallel workers alleen meerdere clientIds gebruiken op dezelfde poort, of later ook meerdere
   poorten/TWS instanties mogen verdelen.

---

## Samenvatting

De nieuwe architectuur:

```text
TWS reqContractDetails
  -> option_chain_retriever
  -> per asset parquet chain registry
  -> Access runlog
  -> resolver/import naar option_series_master wanneer de app een serie echt gebruikt
  -> IV jobs lezen direct uit parquet
```

Dit houdt bulkdata snel en goedkoop in parquet, terwijl de bestaande Access-gebaseerde app-logica
voor orders, resolver en live optieprijzen intact blijft.
