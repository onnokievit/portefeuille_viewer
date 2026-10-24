# Achtergrondpad voor historie en asset-indicatoren

De UI-meting op 24 oktober 2026 liet blokkades zien bij het herladen van historie en het berekenen en opslaan van indicatoren. Daarom gebruiken deze acties nu `HistoryIndicatorRunner`, één instantie per Qt-app.

## Routes

- Na gewone prijsupdates: historie en beta herladen buiten de UI-thread.
- Na volatiliteit/historie-updates: historie herladen, indicatoren berekenen en signal-history opslaan buiten de UI-thread.
- Run indicator en eerste activatie van een nog lege indicator-tab: hetzelfde runnerpad, met de reeds geladen historie als invoer.
- Na lange historie- of IV/HV-opvraag voor één asset: hetzelfde achtergrondpad. De pipeline meldt pas voltooiing na publicatie en houdt tot dan zijn bestaande gedeelde taaklease vast.

De bestaande `ProjectionWorker` verzorgt veilige invoerkopie op de eigenaarthread, één lopend verzoek en maximaal één samengevoegd vervolgverzoek. Operaties en callbacks van vervolgverzoeken blijven behouden. De historie die de worker laadt is direct zichtbaar voor de daaropvolgende indicatorberekening via staging, terwijl de UI oude snapshots blijft gebruiken tot de volledige batch op de Qt-thread wordt gepubliceerd. Databaseverbindingen voor laden en opslag worden binnen de rekenthread geopend en gesloten.

De indicatorformules en bestaande opslagfunctie zijn hergebruikt. Bij een berekenings- of laadfout blijft de bestaande UI-snapshot behouden, verschijnt een foutmelding en kan een volgende aanvraag weer worden verwerkt. De knop toont ingepland/bezig en wordt na afloop hersteld. Inactieve indicator-tabs plannen geen directe JavaScript-publicatie na een automatische run.

## Scope

De initiële volledige laadfase vóór het hoofdvenster verschijnt blijft synchroon. De gedeelde databasewatcher laadde historie al op een achtergrondthread. Deze wijziging maakt niet alle overige scherm- en databaseacties asynchroon. De meetcode blijft aan om het gedrag na een herstart te vergelijken. CPU-werk verdwijnt niet; de UI-thread voert het niet meer zelf uit.

## Verificatie

Gerichte tests controleren dat laden en indicatorberekening op dezelfde achtergrondthread lopen, nieuwe historie binnen die berekening zichtbaar is, publicatie op de Qt-thread gebeurt, de heartbeat blijft lopen, bursts worden samengevoegd, fouten oude snapshots behouden, pipelines op publicatie wachten en de indicator-knop hetzelfde pad gebruikt.

De offline integratiecontrole gebruikt afzonderlijke Access-kopieën; productie- en netwerkverbindingen zijn geblokkeerd. Hij vergelijkt historie en de live-/summary-indicatoruitkomsten met de synchrone berekening (behalve tijdstempels), controleert dat precies één bijbehorende run is opgeslagen en meet de UI-heartbeat tijdens de achtergrondrun. Rapporten staan onder `C:\python_coding\portf_db_praktijktest\run_20261024_hardening_134303\history_<profiel>.json` en `.log`.

Resultaat: alle drie profielen geslaagd, telkens 132 indicator-assets met gelijke uitkomsten en gecontroleerde opslag. Grootste gemeten tussenpauzes van de UI-heartbeat tijdens de achtergrondrun: Onno 0,610 s, Muriel 0,532 s, Quinten 0,734 s. De heartbeat bleef gedurende laden, rekenen en opslaan actief. Dit is een offline test, geen garantie voor dezelfde tijden bij normaal gebruik. De suite van 135 tests slaagde; een aanvullende knoptest en de vijf gerichte runnertests slaagden daarna ook. Compilecontrole en git diff --check geslaagd. Graphify JSON/rapport bijgewerkt; de HTML-export overschrijdt de bestaande node-limiet.
