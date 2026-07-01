# Improve TWS Connection Handling

## Context

De app gebruikt een centrale IBKR/TWS-connectie via `PriceFeedService` en `PriceFeedIB` in `portefeuille_viewer/services/price_feed.py`.

Bij app-start wordt `PriceFeedService` aangemaakt in `portefeuille_viewer_1.4.py` met:

- `settings.get_ib_host()`
- `settings.get_ib_port()`
- `settings.get_ib_client_id()`

De huidige `PriceFeedIB` maakt een inner `App(EWrapper, EClient)`, doet `connect()`, start een daemon-thread met `app.run()`, en zet `_is_ready = True` bij `nextValidId()`.

Belangrijk huidig risico:

- `_subscribed` en `_option_subscribed` betekenen nu feitelijk "al aangevraagd".
- Na een TWS crash/herstart bestaan die subscriptions niet meer aan TWS-kant.
- De app kan administratief nog denken dat ze actief zijn, waardoor opnieuw subscriben wordt overgeslagen.
- Daardoor kunnen live prijzen stilvallen terwijl de UI oude/cached prijzen blijft tonen.

## Doel

De app moet robuust omgaan met:

- TWS herstart
- TWS crash
- socket disconnect
- client-id conflict
- handmatige reset van IBKR-connectie
- handmatig switchen tussen meerdere TWS-poorten, bijvoorbeeld `7496` en `7498`

De belangrijkste eis: na reconnect moeten alle gewenste market-data subscriptions opnieuw naar de nieuwe TWS-sessie worden gestuurd.

## Eerste Implementatie

Deze fase is bedoeld als minimale, robuuste verbetering zonder groot herontwerp.

### 1. Scheid gewenste en actieve subscriptions

In `PriceFeedIB` de huidige sets splitsen:

```python
_desired_subscriptions: set[tuple]
_active_subscriptions: set[tuple]

_desired_option_subscriptions: set[tuple]
_active_option_subscriptions: set[tuple]
```

Betekenis:

- `desired`: wat de app wil hebben, blijft behouden over reconnects.
- `active`: wat in de huidige concrete TWS-sessie is aangevraagd.

Aanpassing in `ensure_subscriptions(rows)`:

1. Normaliseer de subscription naar een label.
2. Voeg het label altijd toe aan `_desired_subscriptions`.
3. Als de feed ready/connected is en het label niet in `_active_subscriptions` staat, stuur `reqMktData`.
4. Voeg pas na de request toe aan `_active_subscriptions`.

Aanpassing in `ensure_option_subscriptions(rows)`:

1. Bouw gewenste option-labels.
2. Vervang of sync `_desired_option_subscriptions` met de actieve option-universe.
3. Cancel stale actieve option subscriptions alleen binnen de huidige sessie.
4. Vraag ontbrekende desired option subscriptions aan als de feed connected is.

### 2. Connection status toevoegen

In `PriceFeedIB`:

```python
statusChanged = Signal(str)
connectionLost = Signal(str)
```

Interne velden:

```python
_status = "disconnected"
_is_ready = False
_last_connected_at = None
_last_disconnect_reason = ""
```

Statuswaarden:

- `connecting`
- `connected`
- `reconnecting`
- `disconnected`

### 3. `connectionClosed()` implementeren

In de inner `App(EWrapper, EClient)`:

```python
def connectionClosed(self):
    feed._handle_connection_lost("connectionClosed")
```

`_handle_connection_lost(reason)` doet:

1. `_is_ready = False`
2. status naar `reconnecting`
3. `_active_subscriptions.clear()`
4. `_active_option_subscriptions.clear()`
5. pending IB request handlers opschonen of laten verlopen
6. reconnect starten met backoff

### 4. Reconnect met nieuwe `App()`

Niet opnieuw `connect()` doen op hetzelfde `App` object.

Nieuwe flow:

```text
oude app disconnect
oude run-thread join timeout
oude app weggooien
nieuwe App()
connect(host, port, client_id)
nieuwe run-thread starten
wachten op nextValidId
resubscribe desired subscriptions
```

Waarom:

- ibapi client/socket/read-thread state wordt schoon opnieuw opgebouwd.
- oude pending callbacks en half-dode reader state worden niet meegenomen.
- de nieuwe TWS-sessie krijgt expliciet alle gewenste subscriptions opnieuw.

### 5. Resubscribe na `nextValidId()`

Bij `nextValidId()`:

1. `_is_ready = True`
2. status naar `connected`
3. `reqMarketDataType(3)` opnieuw zetten
4. `_resubscribe_all_desired()` aanroepen
5. `ready.emit()`

`_resubscribe_all_desired()`:

- kopieert desired subscriptions onder lock
- stuurt alle ontbrekende stock/index/future/cash subscriptions naar TWS
- stuurt alle ontbrekende option subscriptions naar TWS
- vult `_active_*` opnieuw

### 6. Publieke reset/reconnect API

In `PriceFeedService`:

```python
def reconnect(self, host=None, port=None, client_id=None):
    self._feed.reconnect(host=host, port=port, client_id=client_id)

def connection_status(self) -> str:
    return self._feed.connection_status()
```

In `PriceFeedIB`:

```python
def reconnect(self, host=None, port=None, client_id=None):
    # update endpoint indien meegegeven
    # force close huidige app
    # clear active subscriptions
    # start nieuwe App
```

### 7. Settings-tab knoppen

In de Settings-tab toevoegen:

- statuslabel: `IBKR: connected/reconnecting/disconnected`
- label huidig endpoint: `127.0.0.1:7496 clientId=299`
- knop `Reconnect`
- knop `Switch 7496`
- knop `Switch 7498`

Acties:

```python
price_feed.reconnect()
price_feed.reconnect(port=7496)
price_feed.reconnect(port=7498)
```

Bij poort-switch eventueel ook settings opslaan via `set_ib_settings(...)`, zodat de gekozen poort bij volgende app-start behouden blijft.

### 8. MainWindow koppeling

Nu krijgt `MainWindow` al `price_feed`. De `SettingsTab` wordt nu zonder argumenten gemaakt.

Aanpak:

- of `SettingsTab(price_feed=price_feed)` ondersteunen
- of na tab-creatie `self.settings_tab.set_price_feed(self.price_feed)` aanroepen

Voorkeur: setter, omdat dit minder constructor-wijzigingen door de UI-tabstructuur trekt.

## Complete Implementatie

Deze fase maakt de connectie niet alleen herstelbaar, maar ook observeerbaar en beter testbaar.

### 1. Heartbeat/watchdog

Alleen `connectionClosed()` is niet genoeg. Sommige disconnects of half-open sockets kunnen stil zijn.

Toevoegen:

- watchdog-thread of Qt timer
- elke 15 seconden `reqCurrentTime()`
- callback `currentTime()` update `_last_heartbeat_at`
- als heartbeat niet binnen 30 seconden terugkomt: status `stale`
- als twee heartbeats achter elkaar missen: force reconnect

Nieuwe status:

- `stale`

Belangrijk:

- niet alleen op "geen ticks" vertrouwen, want buiten markttijden kunnen ticks normaal stilvallen.
- heartbeat moet klein en goedkoop blijven.

### 2. CurrentTime request routing

In de inner `App`:

```python
def currentTime(self, time_):
    feed._handle_heartbeat_ok(time_)
```

In watchdog:

```python
app.reqCurrentTime()
```

Velden:

```python
_last_heartbeat_request_at
_last_heartbeat_response_at
_missed_heartbeats
```

### 3. Backoff en reconnect-limieten

Reconnect-loop:

- poging 1: direct of na 2 sec
- poging 2: 5 sec
- poging 3: 10 sec
- daarna max 30 sec

Bij succesvolle connect:

- backoff resetten
- `_reconnect_attempts = 0`

Bij client-id conflict `326`:

- bestaande gedrag behouden, maar integreren in dezelfde reconnect-flow
- maximaal 1 automatische client-id increment per endpoint reset
- duidelijke log/statusmelding

### 4. Pending request policy

Bij reconnect zijn bestaande IB request ids ongeldig.

Voor deze dicts:

- `_cd_handlers`
- `_cd_end_handlers`
- `_sd_handlers`
- `_sd_end_handlers`

Policy:

- bij reconnect opschonen
- optioneel callbacks met foutmelding laten eindigen
- manual resolve in `OptionTimevalueService` moet bij timeout leeg teruggeven, niet hangen

Voor optie subscriptions:

- actieve TWS reqIds zijn sessiegebonden
- bij reconnect alle oude option reqIds weggooien
- nieuwe reqIds aanmaken voor desired option labels

### 5. UI status en logging

Status zichtbaar maken op Settings-tab:

- connected endpoint
- status
- laatste connect tijd
- laatste heartbeat tijd
- reconnect attempt count
- laatste disconnect reason

Daarnaast console-logregels:

```text
[ibkr] status=connected endpoint=127.0.0.1:7496 clientId=299
[ibkr] connection lost reason=connectionClosed
[ibkr] reconnect attempt=1 delay=2.0s endpoint=127.0.0.1:7496
[ibkr] resubscribe stocks=123 options=48
```

### 6. Stale price indicator

De app gebruikt cached prices als fallback. Dat is goed, maar de UI moet kunnen weten of prijzen live of stale zijn.

Toevoegen:

- laatste tick timestamp in `PriceFeedService`
- status in `SNAPSHOT_STORE` of signal naar tabs
- eventueel label in live tabs: `IBKR stale since HH:MM:SS`

Niet in eerste implementatie nodig, maar belangrijk voor vertrouwen.

### 7. Multi-TWS endpoint presets

Voor de setup met twee TWS-instanties:

- preset 1: `127.0.0.1:7496`
- preset 2: `127.0.0.1:7498`

Settings-uitbreiding:

```ini
[interactive_brokers]
host = 127.0.0.1
port = 7496
client_id = 299
alternate_ports = 7496,7498
```

Of simpel houden met hardcoded buttons in de Settings-tab, zolang dit alleen lokaal gebruikt wordt.

### 8. Tests en simulaties

Handmatige testscenario's:

1. App starten met TWS op `7496`.
2. Controleren dat live prijzen binnenkomen.
3. TWS volledig sluiten.
4. Verwacht:
   - status naar `reconnecting` of `disconnected`
   - geen crash
   - active subscriptions leeg
5. TWS opnieuw starten op `7496`.
6. Verwacht:
   - app reconnect vanzelf
   - `nextValidId()` ontvangen
   - alle desired subscriptions opnieuw aangevraagd
   - live prijzen komen terug
7. Tijdens draai switchen naar `7498`.
8. Verwacht:
   - oude sessie disconnect
   - nieuwe connectie naar `7498`
   - resubscribe
   - live prijzen blijven terugkomen

Technische testpunten:

- `_desired_subscriptions` blijft gevuld na disconnect.
- `_active_subscriptions` wordt geleegd bij disconnect.
- `_active_subscriptions` wordt opnieuw gevuld na resubscribe.
- `_option_tid_meta` krijgt nieuwe reqIds na reconnect.
- oude reqIds worden niet hergebruikt als actieve sessie-state.

## Implementatievolgorde

Aanbevolen volgorde:

1. Subscription-state splitsen in desired/active.
2. `connectionClosed()` en `_handle_connection_lost()` toevoegen.
3. Reconnect met nieuwe `App()` implementeren.
4. Resubscribe na `nextValidId()`.
5. Publieke `PriceFeedService.reconnect(...)`.
6. Settings-tab reset/switch-knoppen.
7. Handmatig testen met TWS sluiten/herstarten en poort-switch.
8. Heartbeat/watchdog toevoegen.
9. UI status uitbreiden met heartbeat/stale details.
10. Eventuele config voor alternate ports toevoegen.

## Belangrijkste Ontwerpkeuze

De concrete IB `App(EWrapper, EClient)` moet worden behandeld als wegwerpbare socket-sessie.

De persistente app-state hoort in `PriceFeedIB` / `PriceFeedService`:

- gewenste subscriptions
- laatst bekende prijzen
- option last price cache
- endpoint settings
- reconnect status

Bij elke nieuwe TWS-sessie wordt een nieuwe `App()` gemaakt en worden de gewenste subscriptions opnieuw afgespeeld.
