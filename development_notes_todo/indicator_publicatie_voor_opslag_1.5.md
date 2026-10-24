# Indicatorresultaat tonen vóór Access-opslag

De praktijkmeting op 24 oktober liet cachehits van 13–17 ms en snapshotopbouw van circa 113 ms zien, maar publicatie wachtte op 6,2–6,4 seconden Access-opslag. Dat wachten is verwijderd.

## Werking

`HistoryIndicatorRunner` berekent met `persist_history=False`. Het resultaat en de metadata worden op de Qt-thread gepubliceerd. Dezelfde immutable Polars-frame en runmetadata worden daarna aangeboden aan `IndicatorHistoryWriter`. Deze schrijver heeft een aparte thread en een FIFO-wachtrij. Een lopende opslag blokkeert geen volgende berekening of publicatie.

De indicator-tab toont de uitkomst zodra de berekening voltooid is. Een apart label geeft Opslag ingepland, Opslaan, Opgeslagen of Niet opgeslagen aan. Een opslagfout verwijdert geen zichtbaar resultaat en wordt niet als berekeningsfout behandeld. Status van een oudere run kan de status van een nieuwere run niet overschrijven. De oude opslagfunctie wordt hergebruikt; de schrijver vraagt expliciet om het doorgeven van fouten in plaats van alleen een consolemelding.

Er blijven maximaal zestien wachtende saves naast één lopende save behouden. Bij een volle wachtrij verschijnt een expliciete opslagfout. Geaccepteerde writes worden bij normaal afsluiten zonder verdere Qt-callbacks afgerond. Het venster wacht daar niet op, maar het Python-proces kan nog even blijven bestaan totdat die writes klaar zijn. Een geforceerde proceskill biedt die afhandeling niet.

Dit verplaatst de historische berekening niet naar de koerscoordinator. De coordinator blijft de gedeelde koersdienst; de historische cache is een bestand dat door appinstanties onder een proceslock wordt opgebouwd en hergebruikt. De bestaande inhoudelijke theta-/optiekoppelingen in de bredere indicatorservice en UI zijn in deze stap niet gewijzigd.

## Controle

147 regressietests geslaagd, inclusief resultaten publiceren terwijl de opslag opzettelijk wordt vastgehouden, een tweede berekening tijdens die opslag, opslagfouten met behoud van resultaten, statusisolatie per run en afronden van geaccepteerde writes bij sluiten zonder Qt-eventloop. De offline integratiecontrole gebruikt Access-kopieën en blokkeert productie en netwerk. Zij vergelijkt uitkomsten met de oude code, registreert publicatie en verifieert de afzonderlijke commit daarna.

Alle drie integratieruns geslaagd. Na deze codewijziging bouwde Onno de cache opnieuw op en publiceerde na circa 3,95 seconden; de opslag werd circa 10,03 seconden later bevestigd. Muriel en Quinten hergebruikten de cache met nul historische herberekeningen en publiceerden ieder na circa 125 ms. Hun afzonderlijke opslag werd circa 6,44 respectievelijk 6,34 seconden later bevestigd. Dit betreft snapshotpublicatie, niet een browser-paintmeting. De bestaande renderbundeling blijft actief. Rapporten: `C:\python_coding\portf_db_praktijktest\run_20261024_hardening_134303\publish_first_<profiel>.json` en `.log`. Graphify JSON/rapport bijgewerkt; HTML-export blijft boven de node-limiet.

## Eerste tabactivatie vóór HTML-gereedheid

De praktijkronde vanaf 23:40 toonde een initialisatiefout: set_active startte alleen als de webpagina al gereed was, terwijl loadFinished alleen publiceerde en geen eerste aanvraag startte. Daardoor kon een vroege eerste opening leeg blijven tot opnieuw naar de tab werd geschakeld.

Hersteld: activeren start de eerste aanvraag onafhankelijk van HTML-gereedheid. Een vlag voorkomt dubbele aanvragen tijdens laden; bij een berekeningsfout kan opnieuw worden aangevraagd. Als HTML gereed komt, wordt de actuele actieve toestand verwerkt en een reeds beschikbaar resultaat gepubliceerd. Vier tests dekken beide eventvolgordes, een vroeg beschikbaar resultaat en retry na fouten. De 24 gerichte regressietests slaagden. Een echte QtWebEngine-integratietest op de Onno-databasekopie activeerde de tab vóór gereedheid en zag zonder tabwissel één aanvraag, 132 gerenderde tabelrijen en afgeronde opslag.

De praktijkmeting bevestigde daarnaast: Muriel gebruikte de cache (circa 20 ms), bouwde/publiceerde het resultaat in circa 124 ms en rondde de aparte opslag circa 8,1 seconden later af. Onno had een nieuwe historische cachegeneratie met circa 1,53 seconden berekening en circa 7,1 seconden opslag daarna.
