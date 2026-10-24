# Tijdelijke UI-meting

Start de app opnieuw met de normale profielkeuze. De meting is tijdens deze onderzoeksfase standaard aan. De console vermeldt `[ui-diagnostics] meting actief:` met het exacte logpad.

## Wat wordt gemeten

- Qt-heartbeat elke 250 ms: extra wachttijd boven dit interval.
- Onafhankelijke watchdog elke 500 ms: bij minstens 750 ms zonder heartbeat een stack-sample van de Qt-thread, maximaal eens per vijf seconden. Alleen bestandsnaam, functienaam en regelnummer; geen lokale variabelen of bronregels.
- Duur, aantal, maximum en fouten van instrumenteerde functies. Acties vanaf 100 ms krijgen een tijdstempel. Registratie onderscheidt de Qt-thread en achtergrondthreads.
- Repository-loads (inclusief lezen en omzetten van queries), openen van verbindingen, live aggregators, projecties, snapshotkopieën, tijdswaarde en belangrijke schermverversingen.
- Iedere vijf seconden CPU, werkgeheugen, threads en Windows-handles van het betreffende Python UI-proces via psutil. CPU 100% betekent één volledig gebruikte logische CPU; dit is niet het percentage van de totale pc. QtWebEngine-subprocessen en de gedeelde coordinator zijn geen onderdeel van deze procescijfers.

Schermmetingen betreffen de Python/Qt-aanlevering. Ze meten niet de volledige asynchrone JavaScript-rendering of GPU-presentatie. De generieke heartbeat/watchdog helpt ook vertraging buiten de gekozen meetpunten te herkennen. Timings zijn inclusief onderliggende gemeten functies: tel total_ms van geneste acties niet bij elkaar op.

## Logs en belasting

Lokale map: `C:\python_coding\portefeuille_viewer\.portefeuille_runtime\<computer-id>\ui_diagnostics\<profiel>`. Een runtime-override voor tests wordt gerespecteerd. Bestandsnaam bevat starttijd en PID. Geen portfolio-inhoud, SQL, functieargumenten of exceptionteksten worden opgeslagen.

De UI registreert alleen kleine tellingen en events in geheugen. Een achtergrondthread schrijft elke vijf seconden. Maximaal 128 wachtende events en 256 timingcategorieën; het aantal verdrongen registraties staat in `dropped`. Per sessie maximaal circa 15 MB door rotatie (5 MB plus twee backups). Oude sessies blijven voor vergelijking bewaard. De meting voegt één achtergrondthread per app toe. Bij normaal afsluiten wordt een laatste batch geschreven; bij een crash kan de laatste batch ontbreken. Opstart- en window_shown-events onderscheiden het laden van normaal gebruik.

Een grote onderbreking in de watchdog wordt als `pause_or_system_gap` gemarkeerd: standby of algemene systeemvertraging is daarmee niet automatisch een bewezen blokkade door de app. Een ontbrekende psutil-installatie schakelt alleen procescijfers uit en wordt in het sessie-event vermeld.

Uitschakelen voor een nieuwe appstart in PowerShell: `$env:PV_UI_DIAGNOSTICS='0'`. Inschakelen: `$env:PV_UI_DIAGNOSTICS='1'`. Dezelfde setting geldt voor alle vanuit die shell gestarte profielen. Bestaande vensters moeten opnieuw worden gestart om de meetcode te laden.

## Praktijkstap

1. Begin met één profiel. Laat het circa vijf minuten met rust en gebruik daarna de gebruikelijke tabs, filters en scenario's.
2. Open de andere twee profielen en herhaal dit. Noteer bij stotteren het tijdstip en wat je deed.
3. Laat de apps langer draaien als het probleem pas later optreedt. Er hoeft geen beurs open te zijn voor deze eerste meting.

De meetcode schrijft niet naar databases en start zelf geen marktdata-aanvragen. Gewone appactiviteiten blijven wel hun normale werking behouden.

## Validatie

131 regressietests geslaagd, inclusief detectie van bewust geblokkeerde eventloop, begrensde buffers, scheiding van GUI/worker-timings, uitschakelen en behoud van functie-uitkomsten en fouten. De echte app is offline gestart op databasekopieën voor Onno, Muriel en Quinten: alle runs slaagden, de vier projectie-uitkomsten bleven gelijk en de meetlogs bevatten actie- en procescijfers. Productieverbindingen en netwerk waren in die test geblokkeerd. Graphify JSON en rapport bijgewerkt; HTML-export overschrijdt de ingebouwde node-limiet.
