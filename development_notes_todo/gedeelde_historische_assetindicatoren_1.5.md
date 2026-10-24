# Gedeelde historische asset-indicatoren

De zware historische kenmerken en scores worden gedeeld door alle profielen op dezelfde computer en voor dezelfde STOCKDATA-bron. Er is geen extra server of Access-tabel toegevoegd.

## Wat wordt gedeeld

Per asset: historische richting en lange/korte trend, rangepositie, trendfase, volumescore en volatiliteitskenmerken zoals gerealiseerde volatiliteit, ATR en choppiness. De berekening gebruikt de bestaande functies en regels. De historische IV/HV-proxies horen ook bij deze brongegevens.

Niet in de cache: eigen opties, theta, gemiddelde IV uit eigen opties, profieladvies, tijdstempels van de huidige run of gebruikersposities. De bestaande profielberekening combineert het gedeelde historische resultaat met de eigen optiegegevens. De huidige opslag van de samengestelde indicatorrun blijft via de bestaande functie lopen.

De bestaande assetselectie is behouden: de huidige normalisatie sluit onder meer index, future/futures, cash en rol ignore uit. Centraliseren voegt geen nieuwe instrumenttypen toe. De selectie is gebaseerd op gedeelde asset_rollup_data, niet op bezit van een profiel.

## Hergebruik en geldigheid

Cache: `C:\python_coding\portefeuille_viewer\.portefeuille_runtime\<computer-id>\asset_indicator_history\<stockdata-id>\current.json`. Runtime-overrides van tests worden gerespecteerd. Het bestand is een afgeleid, opnieuw op te bouwen resultaat en wordt niet via Git of OneDrive gedeeld. Op een andere computer wordt zo nodig eenmaal een eigen resultaat opgebouwd.

De sleutel bevat de geselecteerde assets, de genormaliseerde historische invoer inclusief IV/HV en de inhoudsversie van service, regels, contract, cachecode en Polars. Historische correcties, nieuwe data, een andere assetselectie, replay-cutoff of gewijzigde rekenregels maken het oude resultaat ongeldig. Gelijkheid wordt op inhoud bepaald; alleen een datum of aantal regels is onvoldoende.

Een Windows-procesmutex beschermt lezen, controleren, berekenen en publiceren van een ontbrekende generatie. Andere aanvragen wachten in hun achtergrondthread en lezen daarna het resultaat. Er is één actuele generatie per STOCKDATA-cache; een andere historische cutoff kan die vervangen. De genormaliseerde brondata moeten nog per app worden gecontroleerd, maar bij een cachehit vervallen groepering naar Python-historieregels en de historische feature-/scoreberekening per asset.

Publicatie gebruikt een tijdelijk bestand, flush/fsync en atomische vervanging. Een mislukte berekening overschrijft geen geldige cache. Een onleesbaar of beschadigd cachebestand wordt opnieuw opgebouwd; een checksum controleert de resultaatinhoud. Verzoeken en publicatie blijven via de bestaande achtergrondrunner lopen. Dit verandert geen databaseschema's en past geen productiegegevens toe tijdens de tests.

## Controle

Tests controleren hergebruik, invalidatie door bron-/regelwijziging, herstel bij beschadiging, behoud bij een mislukte build, drie gelijktijdige processen die eenmaal rekenen en profielgebonden theta naast gelijke historische scores.

De integratietest vergelijkt op aparte Access-kopieën met de code van vóór deze wijziging, zonder cache in die referentieberekening. Hij telt hoeveel historische assetberekeningen de nieuwe code uitvoert voor Onno, Muriel en Quinten. Productieverbindingen en netwerk zijn geblokkeerd. Rapporten: `C:\python_coding\portf_db_praktijktest\run_20261024_hardening_134303\central_<profiel>.json` en `.log`.

Resultaat: alle drie vergelijkingen geslaagd, inclusief de bestaande opslag en actieve UI-heartbeat. Onno berekende 132 historische assetresultaten; Muriel en Quinten gebruikten dezelfde cache en voerden nul nieuwe historische assetberekeningen uit. De volledige suite van 140 tests slaagde, plus een aanvullende test voor gewijzigde historische IV en uitbreiding van de assetselectie. Alle vijf cachetests zijn na die toevoeging opnieuw geslaagd. Graphify JSON/rapport bijgewerkt; de HTML-export overschrijdt de node-limiet.
