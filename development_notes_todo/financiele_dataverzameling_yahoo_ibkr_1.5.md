# Financiële dataverzameling via Yahoo en IBKR — versie 1.5

Gebouwd op 25 oktober 2026. Eerste uitvoering: verzamelen en gestructureerd
bewaren, geen nieuwe kalender-, rapportage- of AI-schermen.

## Doel en grenzen

Alle records uit asset_rollup_data worden meegenomen, zonder profiel-, positie-
of INCL_EXCL-filter. De Yahoo-adapter bepaalt per instrumenttype welke onderdelen
van toepassing zijn. Ontbrekende symbolen en niet-toepasselijke onderdelen krijgen
een checkpoint. Een mislukte aanvraag bewijst niet dat een asset delisted is.
De bestaande yfinance_symbol wordt gebruikt; geen automatische tickergissingen.

De gedeelde feiten staan in STOCKDATA. Gegevens blijven beschikbaar voor assets
zonder positie, mogelijke instap, Asset Analyse, een kalender en latere signalering.
subject_type/subject_key ondersteunen ook andere onderwerpen dan assets.
Een toekomstige provider kan subjects(path) leveren voor bijvoorbeeld economieën
of centrale banken. Macro-ophaling, relatieve marktindicatoren en AI zijn nog
niet geïmplementeerd.

## Onderdelen

- services/financial_data_contract.py: providerneutrale feiten en normalisatie.
- services/yahoo_financial_provider.py: geïsoleerde Yahoo-bronadapter.
- services/financial_data_service.py: gedeelde, hervatbare ophaalrondes.
- data/financial_data_repository.py: incrementele opslag en historie.
- services/financial_comparisons.py: voorzichtige vergelijkingen met consensus.
- devtools/setup_financial_data_stockdata.py: expliciete schemamigratie.
- devtools/financial_data_status.py: technische controle en optionele handmatige ronde.

Yahoo-adapter getest met yfinance 1.7.0; dependency vastgelegd in
requirements-financial-data.txt. Publieke API's leveren de cijfers. Alleen voor
de concrete einddatum van forecastperioden gebruikt de adapter optionele
earningsTrend-metadata die de publieke DataFrames weglaten. Ontbreekt deze,
dan blijft de periode unresolved; er wordt geen kwartaal gegokt.

## Opgehaalde informatie

- Agenda: earningsdatum/datumbereik, ex-dividend en betaaldatum.
- EPS-/omzetconsensus: gemiddelde, laag/hoog, analistenaantal en overige
  beschikbare bronvelden per forecastperiode.
- EPS-trend en aantallen opwaartse/neerwaartse bijstellingen.
- Historische EPS-actuals, bijbehorende bronconsensus en source surprise.
- Historische en komende publicatieregels uit earnings_dates.
- Analistenverdeling, koersdoelen en beschikbare advies-/koersdoelwijzigingen.
- Kwartaal- en jaarcijfers: omzet, brutowinst, operationeel resultaat, nettowinst,
  basic/diluted EPS, EBIT/EBITDA indien aanwezig.
- Kwartaal-/jaarcashflow: operationele cashflow, vrije kasstroom en investeringen.
- Bruto-, operationele en nettomarge uit dezelfde bronperiode, als percentage.

De datum wordt niet automatisch als bevestigd aangemerkt. Datum-only blijft
datum-only. Een range is één onzeker tijdvenster, geen twee bevestigde events.
Noteringsvaluta en financiële rapportagevaluta blijven gescheiden; ontbrekende
valuta wordt niet uit IBKR aangenomen. GBP/GBp wordt niet blind geconverteerd.

## Tabellen

| Tabel | Inhoud |
| --- | --- |
| financial_data_schema | Expliciet geïnstalleerde schemaversie. |
| financial_facts_current | Laatste waarde per bron, onderwerp, categorie, metric, periode, basis, valuta en eenheid. Numerieke waarde is afzonderlijk bevraagbaar; payload_json bevat waarde/context. |
| financial_facts_history | Inhoudelijke versies van die feiten, met uniek fact_key/revision. |
| financial_fetch_state | Laatste poging/succes, status, volgende poging, fouten en laatste bronantwoord per bron/onderwerp/gegevensgroep. |

Categorieën omvatten event, estimate, actual, analyst, analyst_event,
estimate_trend, publication, calendar_estimate, report_comparison en
observed_comparison. De stabiele SHA-256-factsleutel bevat geen gebeurtenisdatum
voor een aan een concrete earningsperiode gekoppelde planning. Een datumwijziging
wordt daardoor een nieuwe versie van hetzelfde feit. Zonder concrete periode
blijft de eerstvolgende planning expliciet een rolling_next-bronwaarneming.
Historische rolling_next-versies zijn niet automatisch opgeloste afzonderlijke
kwartaalgebeurtenissen.

Nieuwe waarden worden onder dezelfde STOCKDATA-schrijflock met de opgeslagen
versie vergeleken. Ongewijzigde feiten krijgen geen nieuwe inhoudelijke versie.
Lege waarden wissen niets; nul is geldig. Sparse objecten vullen bestaande
velden aan. Feitwijzigingen, historie en fetch-checkpoint committen samen.
Bij fout wordt alles in die transactie teruggedraaid.

Nieuwe framework-timestamps zijn UTC zonder timezone in Access DATETIME.
source_at wordt alleen ingevuld bij een bruikbare bron-timestamp met tijdzone;
waarnemingstijd wordt niet als publicatietijd voorgesteld. Oude dividendtabellen
behouden hun bestaande lokale timestamps. Een bewaard raw_json-antwoord bevat
zijn eigen UTC-ontvangstmoment; een fout vervangt dat antwoord niet door null.

De oude tabellen blijven de bestaande dividendweergave bedienen. Hun volledige
regelvervanging is vervangen door gerichte updates met behoud van earnings en
beschikbare dividendwaarden. Historie groeit alleen bij wijzigingen in inhoud
of status, niet uitsluitend door een nieuwe timestamp. Een nieuwe dividenddatum
zonder bijpassend bedrag wordt niet gecombineerd met een oud bedrag: de oude
projectie blijft staan met een gedeeltelijk-status; het nieuwe losse datumfeit
is wel beschikbaar in de framework-opslag.

Na een IBKR-dividendronde worden de bronwaarnemingen ook in de nieuwe facthistorie
opgenomen, mits het schema expliciet geïnstalleerd is. De Yahoo-feiten worden
niet nog eens naar de oude next_earnings_date-kolom gekopieerd. Er is nog geen
nieuwe snapshot of kalenderweergave: feiten en checkpoints zijn rechtstreeks
via repositoryfuncties/controle-CLI beschikbaar.

## Vergelijkingen

EPS uit earnings_history wordt apart bewaard van reported basic/diluted EPS.
Een door Yahoo samen geleverd EPS-resultaat en schatting kan als bronpaar
worden vergeleken, maar is niet gepresenteerd als onze eigen waarneming vóór
publicatie. De aangeleverde source surprise wordt met broneenheid bewaard.

Een eigen observed comparison vereist dezelfde concrete periode, bron, basis,
valuta en eenheid en een eerder opgeslagen consensus. De cutoff is het begin
van de vroegste waargenomen geplande publicatiedag. Dit is bewust conservatief
en blijft een onzekere bronplanning, geen bewijs van de werkelijke publicatietijd.
Een later verschoven datum mag niet alsnog post-report verwachtingen meenemen.
Ontbrekende/ongelijke informatie levert not_comparable met reden op.
Bij nul/negatieve consensus geen misleidend procentueel verschil; marges krijgen
een verschil in procentpunten. Yahoo levert niet standaard margeconsensus:
zonder die consensus volgt geen marge-beat/miss.

## Planning en coördinatie

AppTaskScheduler start de financiële taak na 90 seconden en controleert iedere
5 minuten. De taak heeft eigen coördinatie en houdt geen algemene
onderhoudslease of database-schrijfslot vast tijdens netwerkverkeer.
Eén instantie verzamelt per STOCKDATA; checkpoints voorkomen dubbel werk.
Afsluiten/crashen geeft de OS-lease vrij. Een volgende ronde hervat open werk.

- Normaal: volgende UTC-kalenderdag opnieuw controleren.
- Analisteninformatie: iedere uur, plus maximaal de 5-minuten schedulervertraging.
- Earnings binnen zeven dagen: iedere vier uur voor beschikbare gegevens.
- Verwachte publicatiedag tot twee dagen erna: ieder uur.
- Geen data: zes uur; ontbrekende mapping/niet van toepassing: dagelijks.
- Fouten: exponentieel van 15 minuten tot maximaal 6 uur.
- Rate limit: gedeelde bron-cooldown van één uur.

Een ronde heeft standaard maximaal 200 gegevensgroep-aanvragen/180 seconden;
een lopende bibliotheekaanvraag kan die tijdgrens overschrijden. Oude checkpoints
worden eerst behandeld. Een initiële import kan meerdere rondes duren.
Yahoo-aanvragen worden rustig opeenvolgend uitgevoerd, met 250 ms pauze tussen
gegevensgroepen. Eén Ticker wordt binnen een ronde hergebruikt. Zowel Ticker-
caches als de procesbrede HTTP-LRU van yfinance worden bij een nieuwe ronde
ververst, zodat volgende controles geen oude earningspagina blijven lezen.

De app moet draaien voor ophalen. Bij herstart wordt achterstallig werk
ingehaald. Een zelfstandig ochtendrapport vóór appstart vraagt later een
afzonderlijke geplande taak; rapportweergave is nog niet gebouwd.

## Installatie en controle

Sluit alle Portefeuille Viewers en Access vóór toepassing op echte STOCKDATA.
De app maakt dit schema niet automatisch aan. Het script heeft geen standaardpad.
Eerst plan tonen, daarna expliciet toepassen; --apply maakt eerst een backup.

```powershell
python -m pip install -r requirements-financial-data.txt
python devtools/setup_financial_data_stockdata.py --db "C:\pad\STOCKDATA.accdb"
python devtools/setup_financial_data_stockdata.py --db "C:\pad\STOCKDATA.accdb" --apply
python devtools/financial_data_status.py --db "C:\pad\STOCKDATA.accdb"
```

Expliciete handmatige ronde (schrijft opgehaalde feiten naar de opgegeven DB):

```powershell
python devtools/financial_data_status.py --db "C:\pad\STOCKDATA.accdb" --collect --max-seconds 180 --max-jobs 200
```

De schema-aanpassing voegt vier tabellen met primaire/unieke sleutels en indexen
toe, zonder bestaande bedrijfsgegevens te verwijderen of te migreren.

## Verificatie

Tests: devtools/test_financial_data.py en devtools/test_financial_storage.py.
Zij dekken normalisatie, valuta, forecastperioden, wijzigingen, null/zero,
dividendcompatibiliteit, rollback, twee processen, lease, retries, mappingwijziging,
budget/resume, rate limits, planning, HTTP-cacheverversing, macro-uitbreidbaarheid
en het ontbreken van automatische schema-aanmaak.
De brede regressieronde slaagde met 162 tests. Volledige uitvoer:
C:\python_coding\diagnostics\financial_regressions_1_5.log.

Live proef uitsluitend op een afgeschermde Access-kopie:
C:\python_coding\diagnostics\financial_data_20261025_114733\report.json.
42 gegevensgroepen gecontroleerd voor Ahold, Apple en Unilever; 1781 feiten/
versies opgeslagen in die eerste proef. Analistenwijzigingen voor Ahold en
Unilever gaven HTTP 404, zonder verlies van de overige data. Unilever leverde
voor enkele kwartaalonderdelen geen data. Deze dekking is een proefwaarneming,
geen garantie voor actuele/volledige dekking van alle assets.
Alle ODBC-verbindingen buiten de testkopie waren in deze proef geblokkeerd.
Een tweede collector op dezelfde checkpoints voerde nul netwerk-aanvragen uit
en liet de historie ongewijzigd. Graphify JSON en rapport zijn bijgewerkt;
HTML-generatie overschrijdt de bestaande limiet van 5000 nodes.

## Bewust later

Assetrapport, kalender, ochtendoverzicht, contextuele impactanalyse, profiel-
blootstelling, macroproviders, ratio's/spreads, AI, bronprioriteitsresolver en
handmatige correctieschermen. Ook beheer/archivering van langdurig groeiende
Access-historie verdient later een aparte onderhoudsstap.

## Productie-installatie

Op 25 oktober 2026 om circa 12:02 lokale tijd, na bevestiging en procescontrole
dat Viewer/Access gesloten waren, is schema 1 op de echte STOCKDATA geïnstalleerd.
De vier tabellen en bijbehorende primaire/unieke sleutels en indexen zijn
geverifieerd. Recordaantallen van 24 bestaande tabellen bleven gelijk aan de
vooraf gemaakte backup; pv_shared_versions is als technische revisietabel
uitgezonderd. Er is nog geen financiële ophaalronde op productie handmatig gestart.

Extra backup:
C:\Users\onno\OneDrive\Beleggen\2025 - portefeuille database 02.03 - STOCKDATA.before-financial-data-20261025_120225_103310.accdb

Verificatierapport:
C:\python_coding\diagnostics\financial_data_production_activation.json

Na starten van de bijgewerkte app begint de eerste geplande financiële ronde
na circa 90 seconden. Een volledige initiële import kan meerdere rondes duren.
