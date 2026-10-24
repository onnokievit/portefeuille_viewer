# Meerdere profielen tegelijk — 24 oktober 2026

## Uitvoering van stap 3, 4 en 5

**Schrijven en achtergrondtaken.** `data/shared_database.py` is de gezamenlijke
STOCKDATA-verbinding voor de app, updatepipelines en optiewerkbank. Een Windows-mutex
serialiseert schrijvers per canoniek databasepad. Commit schrijft data en revisies
in dezelfde Access-transactie; rollback publiceert geen wijziging. Context-exit
sluit de fysieke verbinding. De beta-vervanging doet delete en insert in één
transactie. Expliciete commit houdt de gebruikelijke directe zichtbaarheid.

De editors voor assets en optiereferenties controleren onder dezelfde schrijflock
of de rij nog gelijk is aan de geladen versie. Bij een conflict moet de gebruiker
herladen; bestaande invoer wordt niet stil over een nieuwere rij geschreven.
Option-master aanmaak heeft een beschermd read/insert-blok. Netwerkwachten voor
contractresolutie gebeurt buiten verbindingen en locks. Late antwoorden blijven
aan hun eigen aanvraag gebonden. Ongewijzigde mappings produceren geen revisies
voor alleen een nieuwe timestamp.

`shared_tasks.py` en `config/local_runtime.py` geven onderhoudspipelines een
procesoverschrijdende taaklease. De lease omvat alle stappen van een historische
update, inclusief gedeelde tijdelijke tabellen. De scheduler controleert de
dagelijkse voltooiingsstatus opnieuw na verkrijgen van de lease. Ketenscans
gebruiken diezelfde onderhoudslease. Handmatige aanvragen tijdens een actieve
pipeline krijgen een melding; ze worden niet automatisch in een wachtrij gezet.
Periodieke controles kunnen later opnieuw starten. `worker_guard.py` koppelt
QProcess-kinderen en hun nakomelingen aan een Windows Job Object, zodat een crash
van het appvenster geen los doorwerkende update achterlaat.

**Wijzigingsdetectie.** `shared_data_watcher.py` controleert revisies iedere twee
seconden in een achtergrondthread. Assets, optie- en sprinterreferenties, historie,
beta's en dividendkalender worden opnieuw geladen. Nieuwe frames worden eerst
verzameld en pas samen op de Qt-thread gepubliceerd. Als relevante revisies tijdens
laden veranderen of een leesfout optreedt, blijft de oude checkpoint staan en volgt
een nieuwe poging. Historie en beta worden pas na vrijgave van een actieve
onderhoudstaak gepubliceerd. Elke user start daarna zijn eigen dagelijkse state-
catchup, ook wanneer zijn aanvraag voor een gedeelde update was overgeslagen.
Option-masterwijzigingen triggeren een rebuild; historie en
referenties verversen ook de afgeleide berekeningen, abonnementen en indexcache.
Leesfouten en succesvolle verversingen verschijnen in de statusbalk.

**Koersdienst.** `shared_quote_coordinator.py` start één lokaal achtergrondproces
per STOCKDATA-pad en TWS-endpoint. Het hergebruikt de bestaande `PriceFeedService`
en `SubscriptionManager`, inclusief roulatie, handelsuren, fout 101 en data-type
registratie. Het voegt de instrumentlijsten van alle aangesloten vensters samen;
contracten worden door de bestaande normalisatie ontdubbeld. Tijdelijke focus is
de verzamelde focus van de clients. Lokale named-pipe-communicatie heeft een
authenticatiesleutel in het lokale runtime-manifest en een protocolversie.

`shared_quote_client.py` levert dezelfde Qt-interface aan het appvenster. Een client
werkt zijn geheugencaches bij zonder quotes voor databaseopslag te markeren.
Alleen de dienst schrijft de ontvangen live koersen weg. Clienttimers voor opslag
staan uit. Niet opgeslagen opties blijven beschikbaar bij afmelden van het laatste
profiel; een tick tijdens opslag blijft als gewijzigd gemarkeerd. De afsluitflush
wacht op een reeds lopende optieschrijfopdracht.

Clients melden zich af of verlopen na circa tien seconden zonder heartbeat.
De dienst stopt na circa vijftien seconden zonder clients. Na een procescrash
start een aangesloten client de dienst opnieuw en meldt zijn gewenste instrumenten
opnieuw aan. Een nog levende maar niet reagerende dienst behoudt zijn manifest;
clients proberen opnieuw verbinding te maken zonder een tweede server te starten.

`ib_connection_guard.py` reserveert unieke lokale client-ID's, ook voor historie,
dividenden en optiewerkbank. Extra marktdataverbindingen reserveren lijnen bij de
dienst voordat zij aanvragen sturen. De reguliere feed maakt daarvoor ruimte;
reserveringen vervallen bij disconnect of verlopen client-heartbeats. Aanvragen
boven de eigen reservering worden geweigerd. Capaciteit is gezamenlijk opgeslagen
onder `[market_data]` in `gebruikersdata/gedeeld/settings_shared.ini`.

**Bestanden.** Projectiemetingen staan in de eigen instantiemap. Parquet-bestanden
gebruiken unieke tijdelijke namen; chain read/merge/write is per bestand beschermd.
IV-snapshots hebben unieke bestandsnamen. Handmatige exports blijven onder controle
van de bestaande bestandsdialoog. De lokale coordinator-runtime staat naast de
versiemappen en wordt niet met profielvoorkeuren of via Git gedeeld.

## Verificatie

De gecombineerde regressieset slaagt met **103 tests**.

Geautomatiseerde tests gebruiken synthetische Access-bestanden, tijdelijke lokale
processen en een fictieve koersbron. Ze controleren onder andere:

- Drie processen die dezelfde teller via read/modify/write bijwerken, zonder verloren updates.
- Commit-zichtbaarheid, rollback, revisies en atomair vervangen van een dataset.
- Weigeren van een verouderde editorwijziging en opnieuw laden na een commit.
- Idempotente option-master rebuild en vrijgave van locks vóór contractresolutie.
- Eén gedeeld budget, contractontdubbeling en meerdere series voor hetzelfde contract.
- Vrijgave van reserveringen, verlopen clients en behoud van de overige subscriptions.
- Echt Windows named-pipe-transport, servercrash/herstart en Qt-clientontvangst.
- Leases na een crash en beëindigen van werkprocessen na een eigenaarcrash.
- Profielisolatie, bestaande koersverwerking, brokerfilters en quote-diagnostiek.

De offline GUI-controle voor Onno, Muriel en Quinten gebruikt aparte databasekopieën
onder `C:\python_coding\portf_db_praktijktest\run_20261024_hardening_134303`.
Alle 18 tabbladen zijn per profiel geopend. Daarna zijn de drie echte
app-entrypoints tegelijk gestart met een fictieve koersinterface. Alle drie
sluiten af met exitcode 0, zonder Qt-excepties of geblokkeerde databasepogingen.
Een wijziging in de test-STOCKDATA triggert cacheverversing; ieder profiel roept
zijn eigen dagelijkse state-catchup aan. De daadwerkelijke updateprocessen waren
in deze startproef vervangen door registrerende testfuncties. Productie-ODBC en netwerktoegang zijn
in die controle geblokkeerd. De aangeleverde analysebestanden zijn geen appbronnen.

Regressieopdracht vanuit de repository:

```powershell
$env:PYTHONPATH = "$PWD;$PWD\devtools"
python -m unittest devtools.test_multi_instance_hardening devtools.test_stockdata_routing devtools.test_profile_sessions devtools.test_price_feed_subscriptions devtools.test_cash_broker_selection devtools.test_subscription_manager devtools.test_quote_delivery_trace
```

## Nog te controleren met echte koersen

Start na sluiten van alle oude vensters drie bijgewerkte 1.5-profielen. Controleer
op Koersabonnementen dezelfde koersdienst-PID, het gezamenlijke budget en ontvangen
koersen. Controleer een overlappend aandeel en een optie. Sluit het eerst geopende
profiel en controleer dat de andere twee blijven ontvangen. Wijzig een onschuldig
assetveld en controleer verversing in de andere vensters; herstel het veld daarna.
Test vervolgens TWS-verbindingsverlies en herstel, plus een achtergrondupdate.

De offline tests bewijzen geen echte IBKR-entitlements, werkelijke markturen of de
capaciteit van TWS. Ander programma- of Access-gebruik neemt niet deel aan deze
locks/revisies. Oudere appcode neemt ook niet automatisch deel. De coördinatie is
lokaal; gebruik op desktop en laptop vereist afzonderlijke overdracht via OneDrive.
Het eerder apart besproken timerprobleem en fallback-delta vallen buiten deze stap.

## Performancecorrectie wijzigingscontrole

Een functiemeting van de draaiende Onno-app liet herhaald openen van Access in
`SharedDataWatcher` zien, ook zonder wijzigingen. De watcher gebruikte tweemaal
per twee seconden een verbinding. Dit is extra relevant bij een OneDrive-database.
Het oorzakelijke verband met de gemelde muisstottering is nog niet vastgesteld.

Na een geslaagde data-commit publiceert de schrijver nu een uniek lokaal token.
Watchers controleren dat kleine bestand iedere twee seconden en slaan Access over
als het token ongewijzigd is. Een databasecontrole iedere minuut blijft als vangnet
voor een verloren signaal of een crash direct na commit. Bij rollback verandert
het token niet; bij foutieve lezingen blijft de checkpoint staan. Uitgestelde
historieverversing controleert tevens of de onderhoudslease vrijgekomen is.

De periodieke Access-aanroepen bij drie volledig ongewijzigde vensters dalen zo
van circa 180 naar circa 3 per minuut. Dit is geen claim over totale CPU-besparing
of bewezen oplossing van de muisstottering. Hiervoor moet de nieuwe code na een
herstart opnieuw tijdens het probleem gemeten worden. Appinstellingen en threads
zijn voor deze correctie niet beperkt. De tijdelijke profiler staat buiten de app
onder `C:\python_coding\diagnostics\py_spy_tool`; de opname is
`C:\python_coding\diagnostics\onno_17760_cpu.txt`.
