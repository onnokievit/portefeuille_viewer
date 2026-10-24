# Timers en projecties: 24 oktober 2026

## Uitgevoerd

- Single-shot timers voor runtimeprojecties, resultaatverversing en optie-tijdswaarde worden alleen gestart als ze nog niet actief zijn. Nieuwe events bundelen werk zonder de eerste deadline te verschuiven. Bestaande intervallen blijven gelden; een bezette Qt-thread kan uitvoering nog steeds vertragen.
- Een gedeelde projection-worker per app verwerkt maximaal één berekening tegelijk. Tijdens die berekening worden nieuwe verzoeken samengevoegd tot één vervolgverzoek, met behoud van betrokken projecties en gewijzigde sleutels.
- Aandelen-, open-opties-, optie-tijdswaarde- en sprinterprojecties rekenen na de initiële laadfase buiten de Qt UI-thread. De worker leest vastgelegde snapshotinputs en publiceert de verzamelde resultaten op de Qt-thread. De eerste laadfase blijft synchroon.
- Ongewijzigde optie-ticks plannen geen extra publicatie. De periodieke tijdswaardepublicatie slaat een ongewijzigde toestand binnen dezelfde kalenderdag over. Gelijke DataFrames leveren geen nieuwe snapshotpublicatie op.
- Dit verplaatst niet alle database-I/O, aggregators of UI-callbacks naar achtergrondthreads. Het verband met de gemelde muisstottering is nog niet bewezen.

## Controle

116 gerichte tests geslaagd: scheduling, foutafhandeling, snapshots, multi-instance hardening, koersabonnementen, profielen, database-routing, imports en Access-constraints. De offline integratietest start de echte app op databasekopieën met productieverbindingen, netwerk en subprocessen geblokkeerd. Voor Onno, Muriel en Quinten waren alle vier projectie-uitkomsten gelijk tussen synchrone en achtergrondberekeningen. Alle drie runs eindigden zonder geregistreerde fouten. Dit is geen live-koersen- of langdurige belastingtest.

Graphify AST-update vernieuwde graph.json en GRAPH_REPORT.md. De HTML-export is niet vernieuwd: de grafiek overschrijdt de ingebouwde visualisatielimiet.

## Vervolg: overlap binnen een app verminderen

- `SnapshotCoverage` registreert bij expliciete projectieaanvragen welke live bron-snapshot al wordt meegenomen. Automatische timerafhandeling vergelijkt de snapshotreferentie opnieuw: dezelfde bron overslaan, een nieuwe bron wel verwerken. Dit werkt ook wanneer het snapshot-signaal pas na de expliciete aanvraag wordt afgeleverd. Bij een databasewissel of workerfout wordt de registratie gewist.
- Na voltooiing van `asset_result_v2` worden de dagresultaten en aandelenprojectie gebundeld ververst. Als de snelle `ordersCommitted`-route actief is, volgt geen tweede volledige transactieverversing. Met die route uit blijft de transactieverversing als fallback bestaan.
- Gedeelde wijzigingen gebruiken een domeinplan: assetmetadata ververst alle aggregators en abonnementen; optiereferenties alleen de optie-aggregator; sprinterreferenties alleen de sprinter-aggregator. Historie ververst het optie-universum en vraagt de bestaande user-catchup aan. Beta en dividendkalender starten geen aggregators of subscription-rebuild. De vier projecties en actieve scenario-overlays worden voorlopig conservatief behouden bij gedeelde wijzigingen.
- De app start de twee-seconden-koerskopie-thread niet meer. `PriceFeedService._on_price` werkt via `AssetLastPriceStore.update_price` de centrale koersopslag direct bij, ook voor de gedeelde feedproxy. De helper blijft beschikbaar voor eventuele afzonderlijke scripts.
- Het ongebruikte `PortfolioEngine.dataUpdated`-signaal, de bijbehorende tien-seconden-notificatietimer en aansluitingen zijn verwijderd. De koersbatchtimer, aggregators, snapshot-signalen en scherm-render-timers blijven actief.
- Controle: bestaande suite van 116 tests plus zes regressietests voor brondekking, state-completion, domeincombinaties, werkelijke gedeelde callback en directe koersverwerking. Geen productie-databasewijzigingen in deze optimalisatiestap.

## Database

De afzonderlijke, handmatig gestarte migratie is op de echte STOCKDATA uitgevoerd. Er zijn 162 inhoudelijk identieke overtollige historische records verwijderd, met behoud van het laagste Id. Vijf ontbrekende unieke indexen zijn toegevoegd. Rapport: `C:\python_coding\diagnostics\constraints_1_5\production_applied.json`. Backup staat naast STOCKDATA. De app voert deze migratie niet bij het starten uit.

## Vervolg

- Praktijkmeting met live koersen en meerdere profielen; resultaten en belasting volgen.
- Verdere legacyverwijdering en het uitschakelen van alternatieve engine-core-routes vallen buiten deze gerichte optimalisatie.
- Fallback-delta valt buiten deze wijziging.
