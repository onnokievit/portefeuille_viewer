# Bouwplan: Integratie Live Optie Engine
**Project:** Portefeuille Viewer AI Claude
**Map:** `C:\python_coding\portefeuille_viewer\portefeuille_viewer_AI_claude\`
**Status:** Nog te bouwen
**Doel:** Live tijdswaarde-monitoring van open optiereposities, volledig geïntegreerd in de bestaande app

---

## 1. Doel en Eindresultaat

### 1.1 Wat wordt gebouwd

Een volledig geïntegreerde optie live engine die:

1. **Automatisch** de universe van open optieseries bijhoudt na elke order
2. **Periodiek** live optiekoersen ophaalt via IBKR (Interactive Brokers) zonder het subscriptielimiet te raken
3. **Tijdswaarde berekent** per serie en totaal per asset
4. **Koershistorie** opbouwt op dagbasis (OHLC + Greeks)
5. **Een nieuwe tab** toont in de app met het tijdswaardeoverzicht

### 1.2 Eindresultaat voor de gebruiker

- Een tab "Optie Tijdswaarde" in de app met een tabel: per open optieserie de live optiekoers, intrinsieke waarde, tijdswaarde per eenheid, tijdswaarde totaal (qty × multiplier), IV, delta, gamma, theta
- Totaalrijen per valuta (EUR, USD) onderaan de tabel
- Automatische refresh elke X minuten zonder handmatige actie
- Opgebouwde daghistorie in de database voor latere analyse

### 1.3 Verband met het grotere doel (uit TODO.md)

Dit is de **datafundamentlaag** voor het uiteindelijke doorrol-adviessysteem:
- Betrouwbare live snapshot → `option_last_prices`
- Rijke historie → `option_price_history`
- Consistente series-identiteit → `option_series_master` + conid

---

## 2. Bestaande Codebase: Wat er al staat

### 2.1 Relevante bestaande bestanden

| Bestand | Locatie | Wat het doet |
|---------|---------|--------------|
| `portefeuille_viewer_AI_claude.py` | root | Startpunt, orkestratie, signaalverbindingen |
| `data/snapshot_store.py` | data/ | Centrale in-memory cache (SNAPSHOT_STORE singleton) |
| `data/repository.py` | data/ | Database queries, snapshot populatie |
| `data/live_aggregator_opties.py` | data/ | Live aggregator voor open opties (bestaand) |
| `services/price_feed.py` | services/ | IBKR prijsfeed: PriceFeedIB + PriceFeedService |
| `signals/__init__.py` | signals/ | Centrale Qt-signalen hub |
| `ui_logica/orders_tab_widget.py` | ui_logica/ | Orders CRUD, emits `ordersCommitted` na opslaan |
| `devtools/option_series_master_seed_from_positions.py` | devtools/ | Seed script (basis voor in-app logica) |
| `devtools/resolve_option_series_contracts_ib.py` | devtools/ | Conid resolve via IBKR reqContractDetails |
| `devtools/options_live_timevalue_monitor.py` | devtools/ | POC monitor (basis voor OptionSnapshotPoller) |
| `devtools/export_option_subscription_universe.py` | devtools/ | Export universe (vervangen door in-app versie) |

### 2.2 Relevante bestaande snapshots in SNAPSHOT_STORE

```python
# Al beschikbaar in SNAPSHOT_STORE na app-start:
SNAPSHOT_STORE.repository_snapshot_load_open_opties        # open opties zonder live koersen
SNAPSHOT_STORE.aggregator_snapshot_load_open_opties_from_tx_live  # open opties MET live koersen
SNAPSHOT_STORE.repository_snapshot_asset_rollup_data       # ib_symbol, ib_currency per asset
SNAPSHOT_STORE.repository_snapshot_optie_referentie_data   # exchange, trading_class per asset
```

De snapshot `repository_snapshot_load_open_opties` wordt ververst bij elke `ordersCommitted`.
De kolommen zijn: `broker, asset_rollup, asset_type, optie_exp_date, optie_strike, optie_call_put, SomVantransactie_aantal, SomVantransactie_euro_totaal, uniek_id, optie_waarde`

### 2.3 Bestaande IBKR connectie (PriceFeedIB / PriceFeedService)

De bestaande `PriceFeedService` (in `services/price_feed.py`) beheert de IBKR-verbinding:
- Gebruikt `reqMktData(..., snapshot=False, ...)` voor persistente streams (aandelen, indices, futures)
- Heeft al dispatcher-infra voor `reqContractDetails` (via `request_contract_details`)
- Emits `priceUpdated(ib_symbol, currency, price)` signaal bij elke koersupdate
- `tickOptionComputation` is **nog niet geïmplementeerd** in de bestaande `PriceFeedIB`

### 2.4 Databases

| Database | Pad | Inhoud relevant voor dit plan |
|----------|-----|-------------------------------|
| ONNO.accdb | `C:\Users\onno\OneDrive\Beleggen\2025 - portefeuille database 02.03 - ONNO.accdb` | Transacties, state engine tabellen, referentiedata |
| STOCKDATA.accdb | `C:\Users\onno\OneDrive\Beleggen\2025 - portefeuille database 02.03 - STOCKDATA.accdb` | `option_series_master`, `option_series_usage` |

De app configureert het pad naar ONNO.accdb via `settings_manager.py`. Het STOCKDATA.accdb-pad staat in meerdere devtools-scripts als constante en moet ook configureerbaar worden (zie stap 6.1).

---

## 3. Database Architectuur: Nieuwe Tabellen

Alle nieuwe tabellen komen in **ONNO.accdb**. De verbinding met STOCKDATA.accdb voor de `option_series_master` join wordt in Python gedaan met twee aparte pyodbc-connecties.

### 3.1 Tabel: `option_subscription_universe`

**Doel:** Universe van open optieseries met alle benodigde IBKR-data voor prijsopvraag. Wordt volledig herbouwd na elke relevante orderwijziging.

```sql
CREATE TABLE option_subscription_universe (
    id                AUTOINCREMENT PRIMARY KEY,
    broker            TEXT(32),
    user_name         TEXT(32),
    asset_rollup      TEXT(64),
    underlying_symbol TEXT(32),
    optie_call_put    TEXT(8),
    optie_strike      DOUBLE,
    optie_exp_date    DATETIME,
    ib_currency       TEXT(16),
    exchange_code     TEXT(32),
    trading_class     TEXT(32),
    multiplier        DOUBLE,
    conid             LONG,
    qty_open          DOUBLE,
    position_eur      DOUBLE,
    last_rebuilt_ts   DATETIME
);
```

**Bron bij opbouw:**
- `broker, asset_rollup, optie_call_put, optie_strike, optie_exp_date, qty_open, position_eur` → uit `SNAPSHOT_STORE.repository_snapshot_load_open_opties`
- `ib_symbol (→ underlying_symbol), ib_currency` → join met `SNAPSHOT_STORE.repository_snapshot_asset_rollup_data`
- `exchange_code, trading_class, multiplier` → join met `SNAPSHOT_STORE.repository_snapshot_optie_referentie_data`
- `conid` → join met `option_series_master` in STOCKDATA.accdb (via aparte connectie)

**Trigger:** `ordersCommitted` signaal → debounce 500ms → rebuild

### 3.2 Tabel: `option_last_prices`

**Doel:** Laatste bekende optiekoers per serie. Wordt ge-upsert bij elke ontvangen snapshot. Dient als fallback bij app-start en als input voor tijdswaarde-berekening.

```sql
CREATE TABLE option_last_prices (
    series_id         LONG PRIMARY KEY,
    asset_rollup      TEXT(64),
    optie_call_put    TEXT(8),
    optie_strike      DOUBLE,
    optie_exp_date    DATETIME,
    bid               DOUBLE,
    ask               DOUBLE,
    last_price        DOUBLE,
    mid_price         DOUBLE,
    underlying_price  DOUBLE,
    iv                DOUBLE,
    delta_greek       DOUBLE,
    gamma             DOUBLE,
    theta             DOUBLE,
    ts                DATETIME
);
```

**Update-patroon:** UPSERT (UPDATE WHERE series_id=?, INSERT als rowcount=0)

### 3.3 Tabel: `option_price_history`

**Doel:** Dagelijkse OHLC-prijs + Greeks per optieserie. Één rij per serie per handelsdag. Basis voor tijdswaardetrend-analyse en later ML-features.

```sql
CREATE TABLE option_price_history (
    id               AUTOINCREMENT PRIMARY KEY,
    series_id        LONG,
    datum            DATETIME,
    open_price       DOUBLE,
    high_price       DOUBLE,
    low_price        DOUBLE,
    close_price      DOUBLE,
    underlying_open  DOUBLE,
    underlying_close DOUBLE,
    iv               DOUBLE,
    delta_greek      DOUBLE,
    gamma            DOUBLE,
    theta            DOUBLE
);
```

**Unieke constraint:** `(series_id, datum)` — geen dubbele dagrecords
**Update-patroon:**
- Gedurende de dag: in-memory OHLC bijhouden per `series_id`
- Bij afsluiten app of bij dagwissel: INSERT rij voor die dag (als nog niet aanwezig)

### 3.4 Bestaande tabel: `option_series_master` (in STOCKDATA.accdb)

Deze tabel bestaat al. Relevante kolommen voor dit plan:

| Kolom | Type | Beschrijving |
|-------|------|--------------|
| series_id | LONG (PK, autoincrement) | Unieke sleutel |
| asset_rollup | TEXT | |
| underlying_symbol | TEXT | ib_symbol van het onderliggende |
| optie_call_put | TEXT | 'call' of 'put' |
| strike | DOUBLE | |
| expiry | DATETIME | |
| ib_currency | TEXT | |
| exchange_code | TEXT | |
| trading_class | TEXT | |
| multiplier | DOUBLE | |
| conid | LONG | IBKR contract ID (null totdat resolved) |
| active | BOOLEAN | |
| source_tag | TEXT | 'position' voor automatisch aangemaakt |
| created_at | DATETIME | |
| updated_at | DATETIME | |

---

## 4. Te Bouwen Componenten

### 4.1 Component: `OptionSeriesMasterService`

**Bestand:** `portefeuille_viewer/services/option_series_master_service.py`
**Taak:** Na elke order detecteren of er nieuwe optieseries zijn die nog niet in `option_series_master` staan, deze seeden, en de conid ophalen via IBKR.

**Logica:**

```
ordersCommitted signaal ontvangen
    ↓
Lees huidige open opties uit SNAPSHOT_STORE.repository_snapshot_load_open_opties
    ↓
Open STOCKDATA.accdb connectie
    ↓
Voor elke unieke (asset_rollup, strike, expiry, call_put, ib_currency):
    Zoek in option_series_master WHERE asset_rollup=? AND strike=? AND expiry=? AND optie_call_put=? AND ib_currency=?
    ↓
    Niet gevonden:
        INSERT stub record (zonder conid, active=True, source_tag='position')
        Voeg toe aan resolve-queue
    ↓
    Gevonden maar conid IS NULL of conid=0:
        Voeg toe aan resolve-queue
    ↓
    Gevonden met conid > 0:
        Geen actie
    ↓
Verwerk resolve-queue async via PriceFeedIB.request_contract_details
    ↓
Voor elk ontvangen contractDetails resultaat:
    UPDATE option_series_master SET conid=?, updated_at=? WHERE series_id=?
    ↓
Emit optionSeriesMasterUpdated signaal
```

**Verbinding met bestaande code:**
- Gebruikt `SNAPSHOT_STORE.repository_snapshot_load_open_opties` als bron
- Gebruikt `SNAPSHOT_STORE.repository_snapshot_asset_rollup_data` voor ib_symbol lookup
- Gebruikt `SNAPSHOT_STORE.repository_snapshot_optie_referentie_data` voor exchange/trading_class
- Gebruikt `PriceFeedIB.request_contract_details()` voor async conid resolve (methode bestaat al)
- Bouwt een `Contract` object met secType='OPT', symbol, currency, strike, expiry, right, exchange, tradingClass

**Contract bouwen voor OPT type:**
```python
c = Contract()
c.secType = "OPT"
c.symbol = underlying_symbol          # bv. "ASML"
c.currency = ib_currency              # bv. "EUR"
c.strike = float(strike)
c.lastTradeDateOrContractMonth = expiry.strftime("%Y%m%d")
c.right = "C" if optie_call_put == "call" else "P"
c.exchange = exchange_code            # bv. "EURONEXT"
c.tradingClass = trading_class        # bv. "ASML"
c.multiplier = str(int(multiplier))   # bv. "100"
```

**Klasse-structuur:**
```python
class OptionSeriesMasterService(QObject):
    optionSeriesMasterUpdated = Signal()  # emitted nadat series geseed + resolved zijn

    def __init__(self, price_feed: PriceFeedService, stock_db_path: str):
        ...

    def on_orders_committed(self):
        """Slot voor ordersCommitted signaal. Debounced via QTimer."""
        ...

    def _run_seed_and_resolve(self):
        """Detecteer nieuwe series, seed, trigger resolve."""
        ...

    def _on_contract_resolved(self, series_id: int, conid: int):
        """Callback van PriceFeedIB.request_contract_details."""
        ...
```

---

### 4.2 Component: `OptionUniverseBuilder`

**Bestand:** `portefeuille_viewer/services/option_universe_builder.py`
**Taak:** Bouwt de `option_subscription_universe` tabel in ONNO.accdb vanuit de in-memory snapshots en de `option_series_master` join.

**Logica:**

```
Trigger: optionSeriesMasterUpdated OF ordersCommitted (met debounce 1000ms)
    ↓
Lees uit SNAPSHOT_STORE:
    - repository_snapshot_load_open_opties         (qty_open, position_eur per serie)
    - repository_snapshot_asset_rollup_data        (ib_symbol, ib_currency)
    - repository_snapshot_optie_referentie_data    (exchange, trading_class, multiplier)
    ↓
Open STOCKDATA.accdb connectie
    Lees option_series_master WHERE active=True AND conid > 0
    Filter op asset_rollup + strike + expiry + call_put + ib_currency
    ↓
Join in Polars:
    open_opties → join asset_rollup_data → join optie_referentie_data → join option_series_master
    ↓
Resultaat: DataFrame met alle kolommen voor option_subscription_universe
    ↓
Schrijf naar ONNO.accdb (DROP + CREATE + INSERT, zoals in build_options_live_universe_py.py)
    Voeg last_rebuilt_ts = datetime.now() toe
    ↓
Sla ook in-memory op: SNAPSHOT_STORE.snapshot_option_subscription_universe
    ↓
Emit optionUniverseRebuilt signaal
```

**Nieuw snapshot in SNAPSHOT_STORE:**
```python
# In snapshot_store.py toevoegen:
self.snapshot_option_subscription_universe: pl.DataFrame | None = None
```

**Klasse-structuur:**
```python
class OptionUniverseBuilder(QObject):
    optionUniverseRebuilt = Signal()

    def __init__(self, onno_db_path: str, stock_db_path: str):
        ...

    def rebuild(self):
        """Bouwt universe opnieuw vanuit snapshots en schrijft naar DB."""
        ...
```

---

### 4.3 Component: `OptionSnapshotPoller`

**Bestand:** `portefeuille_viewer/services/option_snapshot_poller.py`
**Taak:** Haalt periodiek optiekoersen op via IBKR met `reqMktData(..., snapshot=True, ...)`. Verwerkt `tickPrice` en `tickOptionComputation` callbacks. Slaat op in `option_last_prices` en in-memory OHLC buffer.

**Waarom snapshot=True:**
- `snapshot=True` geeft één koersbericht terug zonder persistente subscription
- Telt niet mee als subscription slot (IBKR limiet ~100 concurrent)
- Geeft dezelfde datakwaliteit als betaalde real-time feed (of delayed, afhankelijk van entitlement)
- Perfect voor opties: periodieke refresh, geen milliseconde-nauwkeurigheid nodig

**Logica:**

```
Trigger: optionUniverseRebuilt (initialiseer lijst) + QTimer elke 5 minuten
    ↓
Lees SNAPSHOT_STORE.snapshot_option_subscription_universe
    Filter: alleen rows met conid > 0
    ↓
Voor elke serie in universe:
    Bouw Contract object (secType='OPT', conId=conid, exchange=exchange_code)
    req_id = next_tid()
    Registreer: req_id_to_series[req_id] = series_row
    Roep: app.reqMktData(req_id, contract, "", snapshot=True, False, [])
    Sleep 50ms (IBKR rate limiting)
    ↓
Ontvang tickPrice callback:
    Sla bid/ask/last op per req_id in _pending_prices dict
    ↓
Ontvang tickOptionComputation callback:
    Sla iv/delta/gamma/theta/underlying_price op per req_id in _pending_greeks dict
    ↓
Ontvang tickSnapshotEnd callback (tickType=57):
    Serie is klaar → bereken mid_price = (bid+ask)/2 als geen last
    Sla op in option_last_prices (UPSERT naar ONNO.accdb)
    Update in-memory OHLC buffer voor vandaag
    Verwijder req_id uit pending
    ↓
Na verwerking alle series:
    Update SNAPSHOT_STORE.snapshot_option_last_prices
    Emit optionPricesUpdated signaal
```

**Vereiste uitbreiding van PriceFeedIB:**
`tickOptionComputation` en `tickSnapshotEnd` zijn nog niet geïmplementeerd in `PriceFeedIB`. Voeg toe:

```python
# In de inner App klasse van PriceFeedIB._start():

def tickOptionComputation(self, reqId, tickType, tickAttrib,
                          impliedVol, delta, optPrice, pvDividend,
                          gamma, vega, theta, undPrice):
    handler = feed._option_tick_handlers.get(reqId)
    if handler:
        handler(reqId, tickType, impliedVol, delta, gamma, theta, undPrice)

def tickSnapshotEnd(self, reqId):
    handler = feed._snapshot_end_handlers.pop(reqId, None)
    feed._option_tick_handlers.pop(reqId, None)
    if handler:
        handler(reqId)
```

En in `PriceFeedIB.__init__`:
```python
self._option_tick_handlers = {}    # reqId -> on_option_tick
self._snapshot_end_handlers = {}   # reqId -> on_snapshot_end
```

En een nieuwe methode:
```python
def request_option_snapshot(self, contract: Contract, on_tick, on_end) -> int:
    """Vraag één optie snapshot op. on_tick(reqId, tickType, iv, delta, gamma, theta, undPrice),
    on_end(reqId) worden aangeroepen vanuit IB-thread."""
    tid = self.next_tid()
    self._option_tick_handlers[tid] = on_tick
    self._snapshot_end_handlers[tid] = on_end
    self._app.reqMktData(tid, contract, "", True, False, [])  # snapshot=True
    return tid
```

**OHLC in-memory buffer:**
```python
# In OptionSnapshotPoller:
_ohlc_today: dict[int, dict] = {}
# key: series_id
# value: {"open": float, "high": float, "low": float, "close": float,
#         "underlying_open": float, "underlying_close": float,
#         "iv": float, "delta": float, "gamma": float, "theta": float,
#         "datum": date}
```

Bij elke ontvangen prijs: update high/low/close; sla open alleen de eerste keer van die dag.

**Klasse-structuur:**
```python
class OptionSnapshotPoller(QObject):
    optionPricesUpdated = Signal()

    def __init__(self, price_feed: PriceFeedService, onno_db_path: str, poll_interval_ms: int = 300_000):
        # poll_interval_ms default = 5 minuten
        ...

    def start_polling(self):
        """Start de QTimer."""
        ...

    def stop_polling(self):
        ...

    def _poll(self):
        """Haalt alle optiekoersen op."""
        ...

    def _on_snapshot_end(self, req_id: int):
        """Verwerkt één afgeronde snapshot: upsert DB, update OHLC buffer."""
        ...

    def flush_ohlc_to_history(self):
        """Schrijft huidige OHLC buffer naar option_price_history. Aanroepen bij dagwissel of app-afsluiten."""
        ...
```

---

### 4.4 Component: `OptionTimevalueAggregator`

**Bestand:** `portefeuille_viewer/data/live_aggregator_opties_timevalue.py`
**Taak:** Combineert `snapshot_option_subscription_universe` + `snapshot_option_last_prices` + live aandelenkoersen (SNAPSHOT_STORE.aggregator_snapshot_aandelen_live) tot één tijdswaarde DataFrame.

**Berekeningen:**
```python
intrinsic = max(0, und_px - strike)  # call
intrinsic = max(0, strike - und_px)  # put

option_px = last_price of mid_price of 0

time_value_unit  = max(0, option_px - intrinsic)
time_value_total = time_value_unit * abs(qty_open) / 100 * multiplier
```

**Output snapshot:**
```python
SNAPSHOT_STORE.snapshot_opties_timevalue_live  # nieuw toe te voegen
```

Kolommen: `broker, asset_rollup, optie_exp_date, optie_strike, optie_call_put, qty_open, multiplier, ib_currency, option_px, bid, ask, und_px, intrinsic, time_value_unit, time_value_total, iv, delta_greek, gamma, theta`

**Trigger:** `optionPricesUpdated` signaal → herbereken en schrijf naar snapshot

---

### 4.5 Component: Nieuwe UI Tab "Optie Tijdswaarde"

**Bestanden:**
- `portefeuille_viewer/ui/optie_tijdswaarde_tab_ui.py` (gegenereerd of handmatig)
- `portefeuille_viewer/ui_logica/optie_tijdswaarde_tab_logica.py`

**Inhoud van de tabel (kolommen):**

| Kolom | Bron |
|-------|------|
| broker | snapshot |
| asset | asset_rollup |
| expiry | optie_exp_date |
| c/p | optie_call_put |
| strike | optie_strike |
| qty_open | qty_open |
| mult | multiplier |
| ccy | ib_currency |
| last_px | option_px |
| bid | bid |
| ask | ask |
| und_px | und_px |
| intrinsic | intrinsic |
| time/unit | time_value_unit |
| time_total | time_value_total |
| iv | iv |
| delta | delta_greek |
| gamma | gamma |
| theta | theta |

**Totaalrijen:** Per valuta (EUR, USD) → som van `time_value_total`
**Optionele EUR-schatting:** Als USD/EUR-koers beschikbaar: gecombineerd EUR-totaal

**Verversing:** Luistert op `snapshotUpdated('snapshot_opties_timevalue_live')` → herlaad tabel

**Tabelmodel:** Gebruik bestaand `ColoredPolarsTableModel` (reeds aanwezig in `ui/models.py`)

---

## 5. Signaalflow Overzicht

```
BESTAANDE SIGNALEN (ongewijzigd):
  ordersCommitted  →  debounce  →  refresh_transaction_derived_snapshots()
                                    └→ snapshotUpdated('repository_snapshot_load_open_opties')

NIEUWE SIGNAALKETENS:

  ordersCommitted
      ↓ (debounce 500ms)
      OptionSeriesMasterService.on_orders_committed()
          ↓ (async, via IBKR reqContractDetails)
          optionSeriesMasterUpdated
              ↓
              OptionUniverseBuilder.rebuild()
                  ↓
                  optionUniverseRebuilt
                      ↓
                      OptionSnapshotPoller._update_universe()  (herlaad lijst)

  QTimer elke 5 minuten
      ↓
      OptionSnapshotPoller._poll()
          ↓ (per serie: reqMktData snapshot=True)
          IB callbacks: tickPrice + tickOptionComputation + tickSnapshotEnd
              ↓ (alle series klaar)
              optionPricesUpdated
                  ↓
                  OptionTimevalueAggregator.recalculate()
                      ↓
                      SNAPSHOT_STORE.safe_write('snapshot_opties_timevalue_live', df)
                          ↓
                          snapshotUpdated('snapshot_opties_timevalue_live')
                              ↓
                              OptiesTijdswaardeTabLogica.reload_data()
                                  ↓
                                  UI tabel ververst

  App sluit / dagwissel
      ↓
      OptionSnapshotPoller.flush_ohlc_to_history()
          ↓
          INSERT naar option_price_history in ONNO.accdb
```

---

## 6. Implementatiestappen (Volgorde)

### Stap 1: Database setup (eenmalig script)

**Bestand:** `portefeuille_viewer/services/create_option_tables.py`
Maak een script dat de 3 nieuwe tabellen aanmaakt in ONNO.accdb als ze nog niet bestaan (gebruik `CREATE TABLE IF NOT EXISTS` of `try/except` zoals in bestaande scripts):
- `option_subscription_universe`
- `option_last_prices`
- `option_price_history`

Dit script ook aanroepen bij app-start (in `portefeuille_viewer_AI_claude.py`) als een eenmalige "ensure tables" check.

### Stap 2: Settings uitbreiden

In `settings_manager.py`: voeg `stock_db_path` toe als instelbare waarde (analoog aan de bestaande database-instelling voor ONNO.accdb). Huidig STOCKDATA-pad staat hardcoded in diverse devtools-scripts; centraliseer dit.

### Stap 3: PriceFeedIB uitbreiden

In `services/price_feed.py`:
- Voeg `_option_tick_handlers` en `_snapshot_end_handlers` dicts toe aan `PriceFeedIB.__init__`
- Voeg `tickOptionComputation` toe aan inner `App` klasse
- Voeg `tickSnapshotEnd` toe aan inner `App` klasse
- Voeg `request_option_snapshot(contract, on_tick, on_end)` methode toe aan `PriceFeedIB`
- Voeg `request_option_snapshot` door aan `PriceFeedService`

### Stap 4: OptionSeriesMasterService

Bouw `portefeuille_viewer/services/option_series_master_service.py` zoals beschreven in 4.1.
Verbind in `portefeuille_viewer_AI_claude.py`:
```python
option_master_service = OptionSeriesMasterService(price_feed_service, stock_db_path)
signals.ordersCommitted.connect(option_master_service.on_orders_committed)
```

### Stap 5: SnapshotStore uitbreiden

In `data/snapshot_store.py` voeg toe:
```python
self.snapshot_option_subscription_universe: pl.DataFrame | None = None
self.snapshot_option_last_prices: pl.DataFrame | None = None
self.snapshot_opties_timevalue_live: pl.DataFrame | None = None
```
Ook toevoegen aan `clear()` en `snapshot_store_summary()`.

### Stap 6: OptionUniverseBuilder

Bouw `portefeuille_viewer/services/option_universe_builder.py` zoals beschreven in 4.2.
Verbind in `portefeuille_viewer_AI_claude.py`:
```python
universe_builder = OptionUniverseBuilder(onno_db_path, stock_db_path)
option_master_service.optionSeriesMasterUpdated.connect(universe_builder.rebuild)
signals.ordersCommitted.connect(universe_builder.rebuild)  # ook direct bij order (als master al up-to-date)
```

### Stap 7: OptionSnapshotPoller

Bouw `portefeuille_viewer/services/option_snapshot_poller.py` zoals beschreven in 4.3.
Verbind in `portefeuille_viewer_AI_claude.py`:
```python
option_poller = OptionSnapshotPoller(price_feed_service, onno_db_path, poll_interval_ms=300_000)
universe_builder.optionUniverseRebuilt.connect(option_poller._update_universe)
option_poller.start_polling()
```

Verbind bij app-afsluiten:
```python
app.aboutToQuit.connect(option_poller.flush_ohlc_to_history)
```

### Stap 8: OptionTimevalueAggregator

Bouw `portefeuille_viewer/data/live_aggregator_opties_timevalue.py` zoals beschreven in 4.4.
Verbind:
```python
timevalue_aggregator = OptionTimevalueAggregator()
option_poller.optionPricesUpdated.connect(timevalue_aggregator.recalculate)
```

### Stap 9: UI Tab

Bouw de UI tab in `ui_logica/optie_tijdswaarde_tab_logica.py`.
Voeg toe aan het hoofdvenster in `ui_logica/main_window_logica.py` (analoog aan de bestaande tabs).

---

## 7. Hergebruik van Bestaande Devtools

| Devtools script | Hergebruik in app |
|-----------------|-------------------|
| `option_series_master_seed_from_positions.py` | Logica van `seed_into_master()` overnemen in `OptionSeriesMasterService._run_seed_and_resolve()` |
| `resolve_option_series_contracts_ib.py` | Patroon van `ContractResolverApp.resolve()` en contract-building overnemen in `OptionSeriesMasterService._on_contract_resolved()` |
| `options_live_timevalue_monitor.py` | Patroon van `_pick_option_price()`, `_intrinsic()`, `build_contract()` overnemen in `OptionSnapshotPoller` en `OptionTimevalueAggregator` |
| `build_options_live_universe_py.py` | Niet meer nodig — vervangen door `OptionUniverseBuilder` |
| `export_option_subscription_universe.py` | Niet meer nodig — vervangen door `OptionUniverseBuilder` |

---

## 8. Aandachtspunten en Randgevallen

### 8.1 IBKR Rate Limiting
Bij het opvragen van snapshots: voeg een `time.sleep(0.05)` (50ms) toe tussen elke `reqMktData` aanroep om pacing errors (error code 162) te vermijden. IBKR staat ~50 requests/seconde toe.

### 8.2 Conid nog niet resolved
Als `option_subscription_universe` een serie bevat zonder conid (conid IS NULL of 0), skip deze bij de snapshot poll. De volgende rebuild van de universe na conid-resolve neemt hem alsnog mee.

### 8.3 Marktgesloten / geen koers
Gebruik de fallback-prioriteit uit de POC: `last → delayed_last → close → delayed_close → (bid+ask)/2`. Als geen enkele prijs beschikbaar is, gebruik de meest recente waarde uit `option_last_prices` als fallback.

### 8.4 Dagwissel OHLC
Controleer bij elke poll of `datum` in de OHLC-buffer overeenkomt met `date.today()`. Zo niet: schrijf de vorige dag weg naar `option_price_history` en reset de buffer voor vandaag.

### 8.5 Thread-safety
`OptionSnapshotPoller._on_snapshot_end` wordt aangeroepen vanuit de IB-thread (niet de GUI-thread). Gebruik `threading.Lock()` voor de `_pending_prices` en `_pending_greeks` dicts, en gebruik `signals.queued_emit_*` voor het emitten van `optionPricesUpdated` (zoals het bestaande patroon in `SnapshotStore.safe_write`).

### 8.6 Database-pad configuratie
Voeg in `settings_manager.py` toe:
```ini
[databases]
onno_db_path = C:\Users\onno\OneDrive\Beleggen\2025 - portefeuille database 02.03 - ONNO.accdb
stock_db_path = C:\Users\onno\OneDrive\Beleggen\2025 - portefeuille database 02.03 - STOCKDATA.accdb
```
Beide paden doorgeven aan alle nieuwe services via de constructor.

---

## 9. Testplan

| Test | Verwacht resultaat |
|------|--------------------|
| Start app zonder IBKR verbinding | Universe builder loopt, snapshot_option_subscription_universe gevuld, geen crash |
| Maak een optie order aan | OptionSeriesMasterService triggert, serie toegevoegd aan option_series_master als nieuw |
| Conid resolve check | Na serie-add: series_id met conid > 0 zichtbaar in STOCKDATA.accdb |
| Universe rebuild check | option_subscription_universe in ONNO.accdb gevuld na order |
| Snapshot poll met IBKR verbonden | option_last_prices gevuld na eerste poll |
| Tijdswaarde tab | Tabel toont correcte intrinsic + time_value per serie |
| Totaalrijen | EUR en USD totalen kloppen met handmatige som |
| Dagwissel simulatie | flush_ohlc_to_history schrijft rij naar option_price_history |
| App-herstart | option_last_prices geladen als fallback, tabel direct gevuld zonder poll |

---

## 10. Bestandsoverzicht Nieuwe Bestanden

```
portefeuille_viewer/
├── services/
│   ├── option_series_master_service.py    (NIEUW - stap 4)
│   ├── option_universe_builder.py         (NIEUW - stap 6)
│   ├── option_snapshot_poller.py          (NIEUW - stap 7)
│   └── create_option_tables.py            (NIEUW - stap 1)
├── data/
│   └── live_aggregator_opties_timevalue.py  (NIEUW - stap 8)
└── ui_logica/
    └── optie_tijdswaarde_tab_logica.py    (NIEUW - stap 9)

Gewijzigde bestanden:
├── services/price_feed.py                 (uitgebreid - stap 3)
├── data/snapshot_store.py                 (uitgebreid - stap 5)
├── config/settings_manager.py             (uitgebreid - stap 2)
└── portefeuille_viewer_AI_claude.py       (verbindingen toegevoegd)
```
