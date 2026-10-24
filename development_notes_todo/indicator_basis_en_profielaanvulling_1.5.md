# Historische indicatorbasis en profielaanvulling — 25 oktober 2026

## Gedrag

De gedeelde cache bevat nu het volledige historische assetresultaat: scores,
historische IV/HV, trend, volume, generieke optieadviezen en delta-intervallen.
Dezelfde bestaande rekenfuncties en beslisregels blijven in gebruik. Eigen
optieposities komen niet in dit resultaat voor. Ook assetmetadata en de
indicatorrol tellen mee in de cachegeneratie, naast historie en rekenregels.

Iedere viewer bouwt daarboven een eigen aanvulling uit zijn bevroren
snapshot_optie_timevalue_live. Alleen gewijzigde assetrijen met bruikbare eigen
optiegegevens worden opnieuw door de bestaande berekening gehaald. Een
verwijderde positie herstelt de historische basis; een vorige optieserie of
vorige positieomvang wordt niet hergebruikt wanneer de huidige posities bekend
zijn. De aanvulling wordt niet naar STOCKDATA geschreven en staat niet in de
gedeelde cache.

De historische basis kan direct worden getoond. Een nieuwe kolom Eigen
optiegegevens onderscheidt laden, geen open opties, ontbrekende gegevens,
gedeeltelijke gegevens en beschikbaar. Bruikbaar betekent hier dat tijdswaarde,
IV en theta aanwezig zijn; ontbrekende waarden worden niet als nul behandeld.
De bestaande koersbron kan een databasefallback zijn. Daarom wordt bij
beschikbare gegevens expliciet aangegeven dat de actualiteit onbekend is; dit
is geen garantie voor live data.

De achtergrondrunner luistert naar optie- en positiepublicaties. Een begrensde
timer bundelt meldingen gedurende één seconde, zonder bij iedere tick opnieuw
te beginnen. Een notificatie tijdens de allereerste historische berekening
blijft behouden tot de basis is gepubliceerd. Ongewijzigde invoer veroorzaakt
geen nieuwe inhoudelijke rijberekening. Optieaanvullingen veroorzaken geen
historische opslag. De pagina hoeft niet opnieuw geopend te worden.

## Opslag zonder schemamigratie

Alleen de afzonderlijke historische DataFrame wordt aan de bestaande schrijver
meegegeven. De opslagfunctie weigert een profielresultaat met een gedeelde
generatiesleutel. Resultaten blijven vóór de opslag zichtbaar.

In de bestaande asset_indicator_service_runs.service_version past de tekst
asset-history-v2: gevolgd door de SHA-256-generatie. Onder de bestaande
STOCKDATA-schrijflock wordt de laatste succesvolle run gelezen. Is die versie
gelijk, dan volgt already_saved zonder nieuwe run of historische upserts. Bij
een andere versie worden resultaat en succesvolle registratie samen gecommit.
Een fout draait beide terug. De UI toont Historische basis al opgeslagen.
Er is geen nieuwe tabel, kolom of eenmalige migratie nodig. Bestaande oude
historische records worden niet opgeschoond; nieuw opgeslagen historische
resultaten bevatten geen profielaanvulling.

## Verificatie

- 119 gerichte regressietests geslaagd, waaronder negen nieuwe tests voor
  profielscheiding, ontbrekende Greeks, automatisch aanvullen, eerste-run-races,
  gewijzigde historie/rol, gesloten/vervangen posities en opslagafscherming.
- De 17 koersabonnemententests slaagden afzonderlijk met hun vereiste importpad.
- Geïsoleerde Access-test met 132 assets: historische scores en adviezen gelijk
  aan de eerdere implementatie zonder eigen theta; twee processen schreven
  dezelfde nieuwe generatie precies één keer. Een geïnjecteerde fout liet geen
  succesvolle registratie achter en de herhaling slaagde.
- In die test duurde eerste opslag circa 8 seconden en hergebruik circa 0,2
  seconde. Dit zijn databasecontroles op een kopie, geen garantie voor UI-laadtijd.
- Rapport: C:\python_coding\diagnostics\indicator_storage_test\report.json.
  Alle ODBC-verbindingen buiten de afzonderlijke testkopie waren geblokkeerd.
  Productiedatabases zijn tijdens deze controle niet gewijzigd.
- Een afzonderlijke echte QtWebEngine-controle toont een vroeg binnengekomen
  eerste resultaat zonder tabwissel, behoud van het optieadvies, automatische
  verversing van Eigen optiegegevens en het label Historische basis al opgeslagen.
  Rapport: C:\python_coding\diagnostics\indicator_storage_test\web_status.txt.

Voor gebruik alle viewers herstarten, zodat alle instanties dezelfde nieuwe
berekenings- en opslagroute gebruiken. Echte binnenkomende IBKR-data moet nog
tijdens een volgende praktijksessie worden beoordeeld.
