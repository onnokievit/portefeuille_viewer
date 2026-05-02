# Batch Scanning en Vol Surfaces — Planningsdocument

## Aanleiding

De huidige `PriceFeedService` werkt met **permanente market data subscriptions** via de IB API.
Elke asset krijgt een open verbinding die een "market data line" verbruikt.
IB limiteert het aantal gelijktijdige lijnen per account (standaard ~100, bijkopen mogelijk à ~$10/maand per 100).

Dit werkt voor de huidige portfolio (~135 assets + ~125 eigen optieposities), maar schaalt niet naar:

1. **Grote asset lijsten** (bijv. 1500 assets voor screening of universum-tracking)
2. **Volledige optiechains** voor dealer gamma exposure (GEX) of implied volatility surfaces (vol smile / IV surface)

Dit document beschrijft de benodigde architectuuruitbreiding en legt de basis voor latere implementatie.

---

## Probleemanalyse

### Huidige architectuur (PriceFeedService)

- Eén `ibapi.EClient` verbinding, één clientId
- Per asset: één permanente `reqMktData(..., snapshot=False)` subscription
- Throttle: 10ms sleep per subscription
- Setup tijd ~135 assets: ~1.35 seconden
- Geen batching, geen queue, geen multi-connection

### Waarom dit niet schaalt

| Schaalvraag | Contracts nodig | Probleem |
|---|---|---|
| 1500 assets live | 1500 | 15× IB-limiet overschreden |
| GEX voor SPX | ~8.000–15.000 | Onmogelijk met subscriptions |
| IV surface 50 underlyings | ~50.000+ | Orders of magnitude te veel |
| GEX voor eigen universe (50 namen) | ~5.000 | Onhaalbaar via live subscriptions |

### Wat IB wél ondersteunt op schaal

- **`reqMktData(..., snapshot=True)`** — haalt data eenmalig op, verbruikt **geen** permanente market data line
- **`reqSecDefOptParams(underlying)`** — haalt alle strikes + expiraties van een keten in één call op
- **Meerdere parallelle `EClient` verbindingen** — elk met eigen clientId, elk met eigen request-namespace

---

## Use cases

### 1. GEX — Dealer Gamma Exposure

**Wat is het:**
Het aggregeren van de delta-gecorrigeerde gamma van alle market makers (dealers) per strike,
opgeteld over de volledige optiereeks van een onderliggende waarde (bijv. AEX, SPX, individuele aandelen).
GEX geeft aan waar de markt door dealers mechanisch gehedged wordt, wat koersbewegingen kan
versterken of dempen.

**Wat heb je nodig:**
- Per underlying: alle actieve strikes × alle actieve expiraties
- Per contract: open interest + gamma (uit `tickOptionComputation`)
- Frequentie: dagelijkse snapshot (EOD) is voldoende voor tactische toepassing;
  intradagse refresh (bijv. elk uur) voor fijnere analyse

**Vereisten:**
- Volledige chain ophalen via `reqSecDefOptParams`
- Snapshot per contract: gamma + open interest
- Aggregatie per strike: `GEX(strike) = Σ(OI × gamma × multiplier × spotprice)` met tekentoewijzing call/put

---

### 2. IV Surface / Vol Smile

**Wat is het:**
De implied volatility als functie van strike en expiratie, voor een gegeven underlying.
Geeft inzicht in marktprijzen van tail risk, skew (asymmetrie call/put), en termijnstructuur van volatiliteit.

**Wat heb je nodig:**
- Per underlying: selectie van strikes (bijv. ±30% moneyness) × selectie van expiraties (bijv. eerste 6)
- Per contract: bid/ask spread + implied volatility (uit `tickOptionComputation`)
- Frequentie: periodieke snapshot tijdens markturen (bijv. elke 15–30 minuten)

**Vereisten:**
- Chain-structuur ophalen via `reqSecDefOptParams`
- Filter op moneyness en looptijd (niet elke strike nodig)
- IV per contract ophalen via snapshot

---

### 3. Groot asset-universum (1500+ namen)

**Wat is het:**
Tracking van koersen voor een breed universum van aandelen, ETFs of indices —
los van de huidige eigen posities. Gebruikt voor screening, relatieve sterkte, sectorrotatie etc.

**Wat heb je nodig:**
- Last of close koers per asset
- Frequentie: near-live (bijv. elke minuut refreshen) of EOD-batch

**Vereisten:**
- Snapshot-gebaseerde refresh in plaats van permanente subscriptions
- Meerdere parallelle IB-verbindingen om doorvoer te verhogen

---

## Voorgestelde architectuur: ChainDataService

### Ontwerp

Naast de bestaande `PriceFeedService` (die blijft voor eigen posities)
komt een aparte `ChainDataService` als onafhankelijke data-acquisitielaag.

```
ChainDataService
├── RequestQueue          — prioriteitswachtrij voor snapshot-requests
├── ConnectionPool        — N parallelle EClient verbindingen (elk eigen clientId)
├── ChainResolver         — haalt strikes/expiraties op via reqSecDefOptParams
├── SnapshotWorker(s)     — verdeelt requests over pool, verwerkt callbacks
└── ResultStore           — schrijft naar DB (chain_snapshots, gex_data, iv_surface)
```

### ConnectionPool

- Stel bijv. 5–10 parallelle `EClient` instanties in, elk met clientId 20, 21, 22 ...
- Elke verbinding verwerkt max 50 gelijktijdige snapshot-requests (IB soft limit)
- Pool verdeelt inkomende requests round-robin of op basis van load

### RequestQueue

- Priority levels:
  - `HIGH` — huidige posities, intradag refresh
  - `NORMAL` — GEX-chains, IV surface refresh
  - `LOW` — bulk universe scan, EOD batch
- Rate limiting: max 50 requests/seconde per verbinding (IB API limiet)
- Retry-logica voor tijdout of error 162 (Historical data farm)

### ChainResolver

1. `reqSecDefOptParams(underlying, "", "OPT", exchange)` → geeft alle strikes + expiraties
2. Filter strikes op moneyness (bijv. spot ± 25%)
3. Filter expiraties op looptijd (bijv. 0–180 dagen)
4. Genereer lijst van te fetchen contracten → door naar queue

### Snapshot vs. Subscription Rotation

Twee technieken voor het ophalen van data zonder permanente lijnen te verbruiken:

**Snapshot (`snapshot=True`)**
- IB handelt de lifecycle af: jij vraagt, IB stuurt wat het heeft, verbinding sluit automatisch
- Snel en eenvoudig te implementeren
- Nadeel: IB stuurt wat er op dat moment beschikbaar is — bij onvolledig geladen data krijg je een
  onvolledig of leeg antwoord
- **Kritiek nadeel voor opties:** `tickOptionComputation` (greeks: IV, delta, gamma) wordt bij snapshots
  niet altijd geretourneerd. IB berekent greeks pas na een korte actieve subscriptie-periode.

**Subscription rotation (handmatig cyclen)**
- Roep `reqMktData(..., snapshot=False)` aan — gewone persistente subscription
- Wacht tot de gewenste tick-types zijn ontvangen (bijv. `tickOptionComputation` met IV + gamma)
- Roep daarna `cancelMktData(tid)` aan, ga door naar volgend contract
- Voordeel: je bepaalt zelf wanneer je genoeg data hebt — betrouwbaarder voor optie-greeks
- Nadeel: subscribe → wacht → cancel logica moet je zelf implementeren en bewaken

**Welke methode per use case:**

| Use case | Methode | Reden |
|---|---|---|
| 1500 asset-koersen (last/close) | Snapshot | Snel, simpel, greeks niet nodig |
| GEX (gamma + OI per strike) | Rotation | `tickOptionComputation` vereist actieve subscriptie |
| IV surface (IV per strike/expiry) | Rotation | Zelfde reden |

**Conclusie:** de `ChainDataService` heeft twee workers nodig:
- `SnapshotWorker` — voor aandelen, ETFs, indices
- `RotationWorker` — voor optie-chains (GEX, IV surface), beheert subscribe/wacht/cancel cyclus per contract

Beide workers draaien op dezelfde `ConnectionPool`.

---

### SnapshotWorker

- Per contract: `reqMktData(tid, contract, "", False, True, [])` (snapshot=True)
- Callback `tickPrice` → sla op in buffer
- Na ontvangst: vrij request ID, markeer als afgerond
- Timeout: 5 seconden, daarna retry of skip

### RotationWorker

- Per contract: `reqMktData(tid, contract, "", False, False, [])` (persistente subscriptie)
- Wacht op `tickOptionComputation` met minimaal IV + gamma (of timeout)
- Na ontvangst: roep `cancelMktData(tid)` aan, ga door naar volgend contract in queue
- Timeout per contract: 8 seconden (greeks komen soms later dan tickPrice)
- Max gelijktijdige rotatie-subscripties per verbinding: ~20 (conservatief, greeks zijn zwaarder)

---

## Schattingen doorvoer en timing

| Scenario | Contracts | Verbindingen | Requests/sec | Geschatte looptijd |
|---|---|---|---|---|
| GEX SPX (dagelijks) | 10.000 | 5 | 250 | ~40 seconden |
| IV surface 20 namen | 8.000 | 5 | 250 | ~32 seconden |
| Universe 1500 assets | 1.500 | 5 | 250 | ~6 seconden |
| Alles gecombineerd (EOD) | ~20.000 | 10 | 500 | ~40 seconden |

---

## Afbakening t.o.v. bestaande code

| Component | Verantwoordelijkheid | Aanpassen? |
|---|---|---|
| `PriceFeedService` | Live koersen eigen posities | Nee — blijft ongewijzigd |
| `OptionTimevalueService` | Greeks eigen posities | Nee — blijft ongewijzigd |
| `ChainDataService` (nieuw) | Batch snapshots, chains, GEX, IV surface | Nieuw te bouwen |
| DB schema | Opslag chain-data | Nieuwe tabellen toevoegen |

De twee services draaien naast elkaar. `ChainDataService` schrijft naar eigen DB-tabellen.
Geen gedeelde staat, geen gedeelde IB-verbindingen.

---

## DB-tabellen (nieuw)

```sql
-- Dagelijkse GEX-snapshots per underlying per strike
CREATE TABLE gex_snapshots (
    underlying      TEXT,
    snapshot_date   DATE,
    expiry          DATE,
    strike          REAL,
    right           TEXT,   -- 'C' of 'P'
    open_interest   INTEGER,
    gamma           REAL,
    gex_contribution REAL,
    fetched_at      TIMESTAMP
);

-- IV surface snapshots
CREATE TABLE iv_surface_snapshots (
    underlying      TEXT,
    snapshot_ts     TIMESTAMP,
    expiry          DATE,
    strike          REAL,
    right           TEXT,
    bid             REAL,
    ask             REAL,
    mid             REAL,
    iv              REAL,
    delta           REAL,
    days_to_expiry  INTEGER
);

-- Universe koersen (bulk assets)
CREATE TABLE universe_prices (
    symbol          TEXT,
    currency        TEXT,
    price           REAL,
    fetched_at      TIMESTAMP
);
```

---

## Implementatiefasen (aanzet)

### Fase 0 — Voorbereiding (geen code)
- [ ] Beslissen welke underlyings voor GEX/IV surface (eigen universe vs. index + top-50)
- [ ] Beslissen welke frequentie per use case (EOD vs. intradag)
- [ ] IB account checken: hoeveel market data lines beschikbaar / hoeveel bijkopen indien nodig
- [ ] Checken of IB snapshot-modus werkt voor alle asset types (STK, IND, FUT, OPT, FOP)

### Fase 1 — ConnectionPool + SnapshotWorker
- [ ] `IbConnectionPool` klasse: beheert N EClient instanties
- [ ] `SnapshotWorker`: snapshot-request dispatch + callback verwerking
- [ ] Testen met klein universum (bijv. 50 assets, 1 optieketen)

### Fase 2 — ChainResolver
- [ ] `reqSecDefOptParams` wrapper
- [ ] Moneyness + expiry filter logica
- [ ] Integratie met RequestQueue

### Fase 3 — GEX berekening
- [ ] Ophalen chain + OI + gamma via SnapshotWorker
- [ ] GEX aggregatie per strike: `Σ(OI × gamma × multiplier × spot)`
- [ ] Opslaan in `gex_snapshots`
- [ ] Eenvoudige visualisatie (bar chart per strike)

### Fase 4 — IV Surface
- [ ] Ophalen chain + IV + bid/ask via SnapshotWorker
- [ ] Opslaan in `iv_surface_snapshots`
- [ ] Visualisatie: surface plot of heatmap (strike × expiry → IV)

### Fase 5 — Universe scanning (1500 assets)
- [ ] Bulk asset lijst importeren (bijv. uit CSV of screener export)
- [ ] Periodieke refresh via ChainDataService
- [ ] Koppeling aan bestaande screening/filtering logica

---

## Open vragen

- Welke underlyings voor GEX prioriteit? (AEX index, individuele namen, SPX?)
- Willen we intradagse GEX (bijv. elk uur) of volstaat dagelijks EOD?
- Kosten snapshots: IB rekent **niet per snapshot-call**. Je betaalt een maandelijks exchange-abonnement
  (bijv. $1–$15/maand per beurs). Als je al geabonneerd bent op de beurzen waar je handelt, zijn snapshots
  daar gratis. Extra kosten ontstaan alleen als de universe beurzen bevat waarvoor je nog geen abonnement hebt.
  → **Actie fase 0:** inventariseer op welke exchanges de 1500 assets noteren, check welke abonnementen je al hebt.
- Hoe integreren we de ChainDataService in de Qt event loop vs. aparte thread/process?
- Willen we de universe-scan koppelen aan een alert of signaallaag?

---

## Status

**Fase:** Planningsdocument — nog niet geïmplementeerd  
**Datum aangemaakt:** 2026-05-02  
**Prioriteit:** Later — na afronding lopende updateflow en indicator-work
