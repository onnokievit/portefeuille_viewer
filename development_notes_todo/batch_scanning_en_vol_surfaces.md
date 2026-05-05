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

Per request wordt een `Contract` object gebouwd met:

```python
contract.secType = "OPT"
contract.symbol = ib_symbol
contract.currency = ib_currency
contract.exchange = option_exchange
contract.right = "C"  # of "P"
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

### Maandhorizon

De tool moet instelbaar maken hoeveel maanden vooruit gescand worden. Default voorstel:

```text
3 maanden voor korte IV-surface workflow
12 maanden voor algemene chain registry
```

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

of voorlopig:

```text
portefeuille_viewer/vol_surf_poc/option_chain_retriever/
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

### GUI-functionaliteit

Minimaal:

- stockdb-pad tonen uit settings;
- parquet target directory kiezen en opslaan in settings;
- TWS host/port/client-id instellen;
- assetlijst laden uit `asset_rollup_data`;
- filteren/selecteren: 1 asset, selectie assets, alle assets;
- horizon in maanden;
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
- [ ] Alleen aandelen selecteren.
- [ ] `ib_symbol`, `ib_currency`, optiereferentie/exchange bepalen.
- [ ] Stockdb-pad uit settings lezen.
- [ ] Parquet directory in settings opslaan.

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
- [ ] Window standalone kunnen starten of vanuit bestaande app openen.
- [ ] Geen gedeelde IB-verbinding verplicht; tool gebruikt eigen TWS client-id.

### Fase 6 - IV workflow

- [ ] IV-universe bouwen uit chain parquet.
- [ ] Contracten selecteren op DTE/moneyness/right.
- [ ] IV ophalen via conid met subscription-rotation.
- [ ] IV snapshots naar aparte parquet opslag.

---

## Nog te beslissen

1. Default horizon voor chain scanning: 3, 6 of 12 maanden?
2. Welke assets zijn "aandelen" in `asset_rollup_data`: bestaande typekolom of afleiden uit velden?
3. Welke exchange fallback per markt:
   - US: `SMART`
   - Amsterdam: `FTA`
   - Duitsland: `EUREX`
4. Moet de scanner verlopen contracten bewaren zonder limiet, of na bijvoorbeeld 2 jaar archiveren?
5. Moet de parquet directory lokaal blijven of ook onder OneDrive?
6. Moet de batch standaard sequentieel draaien, of mogen meerdere assets parallel met meerdere clientIds?

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
