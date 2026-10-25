# Databaseworkers, resourcegroei en praktijktest — 1.6

Datum: 25 oktober 2026. Eerste gerichte ombouw na de Windows-stotteranalyse.

## Probleem en bewijs

Op deze computer veroorzaakte herhaald openen/sluiten van de Microsoft Access
ODBC-driver groei van GDI-objecten en handles, ook met expliciete sluiting,
garbage collection, zonder Qt-interface en zonder OneDrive. Uitschakelen van
ODBC-pooling loste dit in het losse experiment niet op. Vijftig leesacties op
dezelfde verbinding vertoonden die groei niet; vijftig nieuwe verbindingen wel.

Dit bewijst een bron van resourcegroei. Het bewijst nog niet dat deze groei de
Windows-brede muisstotters veroorzaakt. De stotters bestonden al voor Yahoo en
traden ook op zonder PS Tray Factory en de externe procesmonitor.

## Inventarisatie

Zie [de gegenereerde inventaris](inventaris_databaseverbindingen_1.6.md):
211 aanroepplaatsen in 62 Python-bestanden, inclusief losse hulpmiddelen.
Geen bewijs dat al die paden tijdens normaal gebruik actief zijn.

| Groep | Beoordeling en uitvoering |
|---|---|
| Financiële opslag: schema-check, assets, feiten, historie, fetch-states en store-result | Omgezet naar korte databasejobs op de vaste STOCKDATA-worker. Yahoo/netwerk en vergelijkingsberekeningen blijven bij de aanroeper. |
| Gedeelde wijzigingsdetectie | `read_versions` via dezelfde worker. De snapshot-loaders en `capture_writes` blijven in hun bestaande refresh-thread; klakkeloos verplaatsen zou de threadgebonden snapshot-capture breken. |
| `asset_last_prices` | Lezen en opslaan via de worker; cache/dirty-selectie blijft op zijn bestaande plek. |
| `option_last_prices` | De bestaande save-functie, inclusief de voorafgaande verlopen-koersenopruiming, via de worker. Ook actief in een nieuw gestarte centrale quote-coordinator. Initiële optieprijs-load nog bestaand pad. |
| Run-log, dividendrepository, referentie-editors, historische indicatoropslag, workbench | Nog bestaande STOCKDATA-verbindingen. Dit zijn volgende gerichte kandidaten, niet stilzwijgend volledig omgezet. |
| Userdatabase via `repository.get_connection` | Transacties, cash, accountbalansen, orders en comments blijven usergebonden. Geen verbinding tussen profielen gedeeld. Nog niet naar een vaste userdatabaseworker omgezet. |
| Rechtstreekse `pyodbc.connect` in state-engine-runner en UI-dialogen | Veelal userdatabase; expliciete verbindingsstring gecontroleerd in pending-summary en optie-eind. Bestaande route. Niet automatisch door de STOCKDATA-decorators onderschept. |
| Losse state-engine-/prijs-/migratiescripts | Eigen proces en eigen levensduur. Geen appworker geactiveerd door alleen importeren; expliciete migratielevensduur blijft behouden. |

Er is dus een complete statische inventaris en een eerste geteste ombouw van
frequente paden, geen integrale herschrijving van alle databasecode.

## Ontwerp

- `data/stockdata_worker.py`: één vaste thread per canoniek STOCKDATA-pad en per
  proces, met een begrensde wachtrij van 128 opdrachten. Geen losse thread of
  nieuwe verbinding per opdracht. Verschillende profielen hebben eigen processen
  en workers; de bestaande gezamenlijke quote-coordinator heeft zijn eigen worker.
- Alleen expliciet gemarkeerde repository-/opslagfuncties gaan naar de worker.
  Een opdracht omvat het volledige databasewerk en retourneert gematerialiseerde
  resultaten; cursors en verbindingen worden niet doorgegeven aan UI of callers.
- Netwerk en zware indicatorberekeningen horen niet in deze worker.
- De fysieke `pyodbc.Connection` wordt uitsluitend op de eigenaarthread gemaakt,
  gebruikt en gesloten. `SharedConnection` en `SharedCursor` controleren tevens
  thread-eigendom, ook voor eerder opgehaalde bound methods.
- Iedere bestaande `with connect_stockdata(...)` blijft een aparte logische unit
  of work. Commit, rollback en afsluiten van cursors blijven per unit plaatsvinden.
  `close()` geeft alleen binnen deze worker de fysieke verbinding terug voor
  hergebruik. Andere aanroepplaatsen sluiten nog fysiek.
- Elke korte workerjob reserveert de bestaande cross-process STOCKDATA-mutex,
  inclusief de eerste read. De bestaande transactiemutex binnen SharedConnection
  wordt op dezelfde OS-thread recursief gebruikt. Beide worden vrijgegeven.
  Hierdoor kan geen samenwerkende schrijver tussen cachecontrole en de eerste
  read/modify/write komen. Netwerk wacht nooit binnen dit slot.
- Geneste logische transacties op dezelfde worker worden expliciet geweigerd,
  in plaats van onbedoeld dezelfde transactie te committen.
- Bij een fout wordt de verbinding weggegooid. De volgende opdracht kan opnieuw
  verbinden; een mislukte schrijfopdracht wordt **niet automatisch herhaald**,
  omdat een commitresultaat onzeker kan zijn.
- Bij afsluiten worden nieuwe opdrachten geweigerd, geaccepteerde opdrachten
  afgewerkt en verbindingen door de eigen thread gesloten. Na een beperkte
  afsluitwachttijd wordt een vastzittende driver gemeld, niet vanuit een andere
  thread geforceerd gesloten. Een Access-driver kan tijdslimieten negeren.

## Access-cache: waarom herverbinden soms nodig blijft

De integratietest liet zien dat een open Access-verbinding oude gegevens kan
blijven lezen na een commit via een andere verbinding. Alleen hergebruik was
daarom onjuist. De worker bewaart nu de lokale wijzigingstoken:

1. Een eigen succesvolle commit houdt de verbinding bruikbaar en actualiseert
   de bekende token.
2. Een andere samenwerkende schrijver verandert de token. Voor het volgende
   gebruik wordt de oude verbinding gesloten en opnieuw geopend, onder de
   gezamenlijke mutex.
3. Ook zonder een tokenwijziging wordt een verbinding na maximaal 60 seconden
   bij de volgende databaseactie vernieuwd. Dat is de fallback voor handmatige
   Access-wijzigingen of een ontbrekende lokale melding.

Deze fallback is geen garantie voor onmiddellijk zichtbare handmatige wijzigingen.
Access/andere niet-samenwerkende schrijvers volgen de appmutex niet. Sluit de app
voor schemawijzigingen en offline onderhoud zoals voorheen.

Er blijven dus enkele driverinitialisaties bestaan. De resourcegroei wordt sterk
verminderd, maar het onderliggende lek in de driver is hiermee niet gerepareerd.
Ook nog niet omgezette apppaden kunnen GDI-objecten blijven toevoegen.

Microsoft documenteert cachevertraging en het onderscheid tussen commit en
zichtbaarheid bij deze driver:
[Access SQLSetConnectOption](https://learn.microsoft.com/en-us/sql/odbc/microsoft/sqlsetconnectoption-access-driver),
[Access-driveropties](https://learn.microsoft.com/en-us/sql/odbc/microsoft/setting-options-programmatically-for-the-access-driver).

## Automatische validatie

Alle writes in deze tests gebruiken nieuw gemaakte synthetische Access-databases;
geen wijzigingen aan productie-STOCKDATA of userdatabases en geen schema-migratie.

- Bestaande financiële opslagtests nogmaals via de worker: deduplicatie,
  rollback, sparse merge, hervatten, mappingwijziging en bronfouten.
- Drie aparte processen met herhaald read/modify/write: alle 36 increments blijven
  behouden. Een tijdens een transactie hard beëindigd testproces laat geen
  onvoltooide wijziging achter; de volgende schrijver kan verder.
- Eigendom van verbinding/cursor, seriële opdrachten van drie callerthreads,
  afzonderlijke databasepaden, expliciete commit gevolgd door fout, verbinding
  opnieuw openen na fout, afsluiten en weigeren van geneste transacties.
- Cache-invalidatie door een andere verbinding, fallback voor een schrijver
  zonder melding en zichtbaarheid van externe writes na een leesopdracht.
- Echte synthetische asset- en optieprijsopslag via hetzelfde workerpad.
- Bestaande profiel-, koers-, refresh-, indicator- en projectietests.

### Resourcevergelijking op deze computer

Dezelfde leesopdracht, ieder experiment in een apart proces, met een aparte nieuwe
testdatabase en zonder UI. Getallen zijn groei **na de eerste warm-upverbinding**.
De baseline gebruikt de oude open/lees/sluit-aanpak; dit is geen volledige
vijfminutenrun van de 1.5-interface.

| Duur en opdrachten | Oude aanpak: GDI-groei | Worker: GDI-groei | Nieuwe pyodbc-verbindingen: oud / worker |
|---|---:|---:|---:|
| 2 minuten, 300 | +299 | +1 | 300 / 2 |
| 5 minuten, 1.000 | +999 | +4 | 1.000 / 5 |

Bij de vijfminutentest groeiden handles na warm-up met 2.999 bij de baseline en
34 bij de worker. De +4 GDI-objecten passen bij de vier periodieke herverbindingen.
Dit is een gerichte duur-/belastingtest, geen bewijs dat de volledige app na
uren gebruik vlak blijft of dat de muisstotters verholpen zijn.

Meetbestanden en testlogs staan onder `C:\python_coding\diagnostics`, met prefix
`worker_1_6_`. De laatste transactie-/hardeningrun slaagde met 49 tests; de
aanvullende koers-/diagnosticatierun met 57 en de profiel-/indicator-/projectierun
met 55. Deze groepen overlappen en zijn geen op te tellen uniek testtotaal.
Graphify JSON en rapport zijn bijgewerkt (5.364 knopen); HTML-export kon door
de bestaande limiet van 5.000 knopen niet worden vernieuwd. De voorgeschreven
AST-update van de 1.4-graaf is ook uitgevoerd, zonder wijzigingen aan 1.4-code.

Herhalen vanuit deze repository:

```powershell
$env:PYTHONPATH='.;devtools'
python -m unittest devtools.test_stockdata_worker.WorkerStorageTests -q
python -m devtools.measure_stockdata_worker_resources --mode worker --iterations 1000 --duration 300 --output C:\python_coding\diagnostics\worker_repeat.json
python -m devtools.measure_stockdata_worker_resources --mode direct --iterations 1000 --duration 300 --output C:\python_coding\diagnostics\direct_repeat.json
```

## Praktijktest 1.6: nog uit te voeren met de gebruiker

1. Sluit alle 1.5-vensters; geef de bestaande koerscoordinator circa een halve
   minuut om vanzelf te stoppen. Anders kan 1.6 een nog draaiende 1.5-coordinator
   blijven gebruiken. Geen processen blind beëindigen.
2. Start één profiel vanuit **de map 1.6**. Het startbestand is inmiddels door de
   gebruiker hernoemd naar `portefeuille_viewer_1.6.py`:

   ```powershell
   cd C:\python_coding\portefeuille_viewer\portefeuille_viewer_1.6
   C:\Python311\python.exe .\portefeuille_viewer_1.6.py --db onno
   ```

3. De workers staan voor de app standaard aan. Controleer de instellingenlog op
   paden onder 1.6. Laat circa 15 minuten rusten en gebruik daarna de tabs zoals
   normaal. Laat vervolgens, indien mogelijk, een tot drie uur draaien.
4. De bestaande diagnostiek onder
   `C:\python_coding\portefeuille_viewer\.portefeuille_runtime\<computer>\ui_diagnostics\<profiel>`
   registreert per vijf seconden CPU, geheugen, handles, `gdi_objects`,
   `user_objects` en `stockdata_workers` met `physical_opens`/`jobs`/`pending`.
   Dit bemonstert alleen het eigen proces; geen zware externe all-process-monitor.
5. Meld het tijdstip van eventuele stotters. Vergelijk GDI-/handlegroei na de
   opstartfase met de opgeslagen 1.5-metingen. Verwacht een sterke afname voor
   omgezette paden, niet nu al een volledig horizontale totale GDI-lijn.
6. Open daarna Muriel en Quinten, controleer data/koersen en sluit de eerste
   app. De andere profielen en de centrale quote-coordinator moeten doorwerken.
   Test een normale afsluiting/herstart. Crashherstel is automatisch met een
   testproces gecontroleerd; forceer geen productiecrash tijdens een databasewrite.
7. Als de resourcegroei/stotters blijven, gebruik de inventaris voor de volgende
   gerichte omzetting. Verplaats niet blind snapshot-capture, signalen of
   IBKR-netwerkcallbacks naar de databaseworker.

Een vergelijking met hetzelfde 1.6-programma maar de oude verbindingsroute kan
voor één nieuwe sessie via `$env:PV_STOCKDATA_WORKERS='0'`. Verwijder de variabele
na de vergelijking met `Remove-Item Env:PV_STOCKDATA_WORKERS`; herstart alle app-
en coordinatorprocessen voor een eerlijke vergelijking. Geen INI-aanpassing nodig.

Geen commits of pushes door de agent. Al bestaande ongecommitteerde Yahoo-code
in de 1.6-kopie is behouden; deze branch bevat dus ook die vooraf aanwezige wijzigingen.

## Aanvulling: native COM-melding bij opstart

Ook met Microsoft Access gesloten verscheen `0x8001010D` opnieuw. Het actieve
pad in beide dumps was snapshotUpdated -> OrdersTabWidget._reload_reference_lists
-> repository.load_reference_lists -> pyodbc.connect op de GUI-thread.
De databaseworker wachtte op een opdracht; de dump bewijst niet dat een
workeropdracht de uitzondering veroorzaakte.

Referentielijsten worden nu eerst uit de bestaande asset-, sprinter- en
transactiesnapshots gelezen. De ordertab gebruikt bij snapshotmeldingen expliciet
`snapshot_only=True`, zonder databasefallback, en reageert ook op ververste
sprinterreferenties. Bestaande ingevoerde comboboxteksten blijven behouden.
Alleen buiten snapshotcallbacks, als referenties werkelijk nog ontbreken, blijft
een STOCKDATA-fallback via de bestaande databaseworker beschikbaar.

Vijf nieuwe gedragstests en de bestaande broker-, routing- en refreshtests
slagen: 28 tests totaal. Tests uitsluitend met mocks/synthetische databases.
Geen productiedatabase of schema aangepast. Een echte herstart moet nog bevestigen
dat de native melding op dit pad niet terugkomt. Dit is geen bewezen oplossing
voor alle mogelijke COM-fouten of de oorspronkelijke Windows-muisstotters.
