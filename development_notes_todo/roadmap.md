# Roadmap

## Doel en gebruik van dit document
Dit document is de centrale roadmap voor verdere ontwikkeling van `portefeuille_viewer_1.2`.

Het document beschrijft alleen werk dat nog relevant is voor de huidige app:
- uitbreidingen op bestaande functionaliteit,
- architectuurverbeteringen die stabiliteit of performance verhogen,
- dataflow- en eventuitbreidingen die de app consistenter en voorspelbaarder maken,
- test- en stabiliteitswerk dat nodig is voor veilige doorontwikkeling.

Dit document vervangt de oude losse roadmap-documenten als leidende werklijst.

Bronnen voor deze roadmap:
- huidige code in `portefeuille_viewer_1.2`,
- `development_notes.md`,
- gearchiveerde plan- en notitiedocumenten in `development_notes_todo/archive/`.

Niet de bedoeling van dit document:
- geen historisch logboek,
- geen kladblok met losse ideeën,
- geen beschrijving van wat al af is behalve waar dat nodig is om een open punt te begrijpen.

`development_notes.md` beschrijft de huidige architectuur en wat al gebouwd is.
`TODO.md` blijft kladblok voor losse ideeën en tussengedachten.

---

## 1. High level plan & doel

### 1.1 Hoofddoel
De app moet uitkomen op één stabiele, rustige en uitbreidbare architectuur waarin:
- live data voorspelbaar wordt verwerkt,
- UI-tabs snel reageren zonder onrustig te worden,
- transacties, snapshots, state-engine outputs en projections logisch op elkaar aansluiten,
- nieuwe functionaliteit kan worden toegevoegd zonder legacy workflows te breken,
- data-integriteit over meerdere databases beheersbaar blijft.

### 1.2 North star
De gewenste eindtoestand is:
- PySide6 als shell en workflowlaag,
- moderne web-gebaseerde tabweergave voor de tabellen die veel live data tonen,
- een event- en projection-gedreven runtime als standaard updatepad,
- state-engine runs voor zware of historische recomputes,
- lichte, throttled, cache-gedreven updates voor live views,
- expliciete compatibiliteit voor databasecontracten die niet mogen breken.

### 1.3 Strategische richting
De modernisatie blijft gefaseerd. Geen big-bang vervanging.

De leidende ontwerpkeuzes blijven:
1. Stabiliteit gaat voor snelheid van uitrol.
2. Nieuwe paden komen eerst parallel naast oude paden.
3. Een tab wordt pas definitief gecutoverd als parity, performance en bediening op niveau zijn.
4. Oude database-objecten worden niet lichtvaardig aangepast als andere onderdelen daar nog op leunen.
5. Logging, metrics en diffing moeten regressies zichtbaar maken voordat ze een gebruikersprobleem worden.

### 1.4 Praktisch eindbeeld
Als deze roadmap volledig is uitgevoerd, moet de app in de praktijk het volgende doen:
- order toevoegen of wijzigen geeft een consistente update door de hele app,
- live koersen worden centraal verwerkt en niet ad hoc per tab opnieuw uitgerekend,
- tabellen blijven rustig, ook onder veel live events,
- unresolved optie-series zijn niet langer een blokkade maar een beheersbaar workflow-onderdeel,
- tabwissels en alt-tab terugkeer naar de app blijven responsief,
- simulatie- en scenariofunctionaliteit kan op de bestaande architectuur worden toegevoegd zonder opnieuw te hoeven verbouwen.

### 1.5 Expliciete hoofdlijnen voor de komende fase
De eerstvolgende ontwikkelfase bestaat uit twee expliciete werkstromen.

#### Werkstroom A: updateflow en rendergedrag stabiliseren
Doel:
- exact begrijpen wat er gebeurt na order save, live ticks, db switch, startup en tabwissel,
- dubbele of onnodige recompute- en renderpaden verwijderen,
- de UI rustiger en voorspelbaarder maken zonder informatieverlies,
- zware work uit de directe interactiepaden halen waar dat kan.

Waarom deze werkstroom eerst:
- de grootste actuele risico's zitten in onvoorspelbare updateketens,
- latency en hickups worden momenteel niet alleen door rendering veroorzaakt, maar ook door te veel of te overlappende vervolgacties,
- zonder deze opschoning is het te riskant om grote codeblokken te verwijderen.

#### Werkstroom B: legacy tabs en legacy-gerelateerde load verwijderen
Doel:
- oude tabs die functioneel vervangen zijn uit de app halen,
- gerelateerde listeners, producers, aggregators en refresh-paden uitschakelen of verwijderen,
- alleen code laten staan die nog echt nodig is voor de 2.0 architectuur of voor compatibiliteit.

Voorwaarde:
- deze werkstroom start pas echt na de eerste audit en opschoning van werkstroom A,
- omdat legacy anders te vroeg wordt verwijderd terwijl sommige runtimepaden nog onvoldoende begrepen zijn.

### 1.6 Uitvoeringsprincipe voor deze fase
De komende fase wordt niet ad hoc gedaan, maar via twee documenten:
- `roadmap.md`: strategische richting en prioriteiten,
- `plan_en_actie_updateflow.md`: concrete aanpak, onderzoeksresultaten, verwijdermatrix en afvinklijst.

De eerste actie in deze fase is daarom niet direct code verwijderen, maar:
1. feature inventory,
2. trigger inventory,
3. meetplan,
4. updateflow audit,
5. daarna pas gerichte refactors en legacy-afbouw.

---

## 2. Functionaliteit uitbreiding

Deze sectie beschrijft functionele uitbreidingen die boven op de huidige app moeten komen.

### 2.1 Transaction Engine V2
Dit is nog steeds een belangrijk open werkpakket.

Doel:
- transacties behandelen als expliciete commands,
- reproduceerbare en controleerbare updateflow na add/update/delete,
- duidelijke scheiding tussen testtransacties, productie-transacties en replay/debugging.

Nog te bouwen of af te ronden:
1. Command handlers voor:
   - add transaction,
   - update transaction,
   - delete transaction,
   - replay transaction set.
2. Deterministic replay tool:
   - vaste inputset,
   - vaste volgorde,
   - run-id,
   - vergelijking van outputs per run.
3. Test-transactie injectiepad als expliciete API:
   - niet alleen UI-gedrag,
   - maar ook een formele interne route voor injecteren, doorrekenen en valideren.
4. Verdere integratie met `optie eind`:
   - generated records naar test,
   - move to productie,
   - logging van remaps en verplaatsingen,
   - duidelijke command-flow in plaats van losse DB-acties.

Waarom dit nog relevant is:
- de app heeft nu nog meerdere paden waar transactiewijzigingen effect hebben,
- orderflow, testorders en derived snapshots zijn nog niet volledig onder één eenduidig contract gebracht,
- stabiliteit van Single Asset Analyse en order-workflows hangt hier direct mee samen.

### 2.2 Scenario- en simulatie-uitbreiding
Dit is geen direct stabiliteitswerk, maar wel een logische volgende uitbreidingsrichting die al eerder is bedacht en nog steeds relevant is.

Open uitbreidingen:
1. Markt-/beta-simulatie:
   - gebruiker definieert een marktshock,
   - per asset een formule of beta-relatie,
   - doorrekening naar aandelen, optieresultaat, portfolio value en sector views.
2. Scenario-context naast live-context:
   - live snapshot blijft onaangetast,
   - scenario draait als aparte projection context of aparte state-scope.
3. Rule-based roll advisor / strategie-assistent:
   - transparante scoringsregels,
   - geen black-box advies,
   - uit te breiden naar latere ML-laag.

Waarom dit nog relevant is:
- de app heeft al de nodige datasets en berekende outputs,
- de grootste ontbrekende stap is niet data, maar een gecontroleerd simulatiepad,
- hiervoor is een nette event/projection architectuur juist een sterke basis.

### 2.3 Resolver workflow verder uitbouwen
De manual resolver flow voor unresolved optie-series is begonnen, maar nog niet af.

Open punten:
1. Resolver workflow in alle relevante tabs eenduidig maken:
   - Optie Tijdswaarde,
   - Open Opties (Live),
   - eventueel later andere tabellen die unresolved series tonen.
2. Candidate lookup verder verbeteren:
   - niet alleen vaste reference-mapping,
   - maar candidate-sets tonen rondom expiry/right/strike/asset.
3. Resolver UX verbeteren:
   - vanuit unresolved melding direct popup openen,
   - selectie bewaren zolang popup open is,
   - gekozen candidate netjes naar master schrijven.
4. Unresolved series structureel zichtbaar houden:
   - reden tonen,
   - actiepad tonen,
   - geen stil falen of eindeloos retry-gedrag.

Waarom dit nog relevant is:
- indexopties, weekopties en feestdag-expiries blijven randgevallen,
- deze problemen verdwijnen niet door meer code alleen in de automatische resolver,
- de app heeft een expliciete gebruikersworkflow nodig om dit beheersbaar te maken.

### 2.4 Optiedata verrijken en persistentie afronden
Er is al werk gedaan aan `option_last_prices`, master series en fallback-gedrag. Dit moet nog worden afgerond tot een robuuste feature.

Open punten:
1. `option_last_prices` volledig standaardiseren op STOCKDATA-gebruik waar nodig.
2. Schrijfpad formeel vastleggen:
   - welke DB,
   - welke kolommen verplicht,
   - hoe fallback wordt gebruikt buiten markttijd.
3. `option_price_history` opzetten of afronden:
   - voor daghistorie,
   - latere analyse,
   - mogelijk scenario/ML input.
4. Optieprijs fallback chain expliciet maken:
   - live price feed eerst,
   - dan opgeslagen last prices,
   - dan eventuele model/fallback logica.
5. Duidelijk onderscheid tussen:
   - snapshot voor UI,
   - persistent laatste bekende marktdata,
   - historische prijsopslag.

### 2.5 Single Asset Analyse verder afmaken
Single Asset Analyse is functioneel belangrijk en technisch nog een hybride zone.

Nog relevante open punten:
1. Tabellen volledig stabiel houden bij live updates:
   - waardes mogen updaten,
   - sorteervolgorde niet spontaan verspringen.
2. Edit-ervaring robuust maken:
   - comments,
   - test order velden,
   - locale decimal handling.
3. Duidelijke live-update controls:
   - sort lock,
   - live update toggle,
   - consistente throttling.
4. Stepsize / step tick configuratie per asset netjes afronden en borgen.
5. Betere aansluiting op projection outputs waar zinvol, zonder de tab onnodig hard te koppelen aan een ongeschikte view.

### 2.6 Functionele parity van moderne tabs verder afmaken
Niet alles wat functioneel mogelijk was in legacy is al even netjes of volledig in web tabs gebracht.

Open functionele uitbreidingen:
1. Verdere parity op filters, comment workflows en kleurgedrag.
2. Meer consistente filter-popups en selectielijsten.
3. Sorteren op betekenisvolle afgeleide waarden, zoals comment-kleur of classificaties.
4. Eventuele aanvullende exportmogelijkheden per tab.
5. Verdere parity in unresolved/diagnostiek workflows over tabs heen.

---

## 3. Architectuur herziening en optimalisatie

Deze sectie gaat niet over functionaliteit, maar over het opruimen, standaardiseren en beheersbaar maken van de technische basis.

### 3.1 Engine Core verder formaliseren
De basis van Event, StateStore en ProjectionBus bestaat inmiddels in code, maar de architectuur moet verder worden aangescherpt en gehard.

Open werk:
1. Uniform contract per event type vastleggen:
   - transaction events,
   - snapshot refresh events,
   - live price events,
   - state rebuild completion events.
2. Coalescing policy per event-type expliciet maken:
   - welke topics mogen samenvallen,
   - welke topics moeten direct door,
   - welke topics alleen de cache bijwerken.
3. Projection invalidation policy centraliseren:
   - welke changed keys leiden tot partial recompute,
   - wanneer moet full recompute worden geforceerd.
4. Meerdere ad hoc updatepaden verder terugbrengen naar één runtimepad.

### 3.2 Dubbele refresh-paden verder verwijderen
Een terugkerend probleem in de app is dat dezelfde betekenisvolle wijziging nog via meerdere routes kan doorlopen.

Dat leidt tot:
- dubbele recomputes,
- onrustige UI,
- lastige debugging,
- niet altijd voorspelbare timing.

Open werk:
1. Identificeren waar snapshots én rebuilds én handmatige refreshes nog dezelfde tab beïnvloeden.
2. Documenteren welk pad de bron van waarheid is per dataset.
3. Oude of tijdelijke refresh-routes afbouwen zodra parity bevestigd is.
4. Speciale aandacht voor:
   - orderflow,
   - transaction-derived refreshes,
   - timevalue overlay,
   - live aggregator snapshots.

Aanvulling voor de huidige fase:
- de audit moet expliciet per trigger vastleggen wat er gebeurt na:
  - app startup,
  - order save,
  - live tick/update,
  - db switch,
  - tab switch,
  - alt-tab terug naar de app.

Het order-save pad verdient extra nadruk, omdat daar zowel functionele juistheid als onnodige load kunnen samenkomen.

### 3.3 PortfolioEngine / aggregators / runtime beter afgrenzen
De huidige app bevat een mix van:
- oude orchestratorlogica,
- snapshot store,
- live aggregators,
- engine core runtime,
- state engine runner.

Dat werkt functioneel, maar de verantwoordelijkheden zijn nog niet overal strak.

Open optimalisaties:
1. Heldere service boundaries vastleggen:
   - wat hoort in `PortfolioEngine`,
   - wat hoort in losse services,
   - wat hoort in runtime/projections.
2. Aggregators verder terugbrengen tot dataproviders of compat-bronnen.
3. Projection tabs zoveel mogelijk laten leunen op gestandaardiseerde snapshots in plaats van tab-specifieke side effects.
4. Documenteren welke services nog bridge-/compat-rollen hebben en later opgeschoond mogen worden.

### 3.4 UI-cutover verder structureren
Een deel van de modernisatie is technisch al gedaan, maar de cutover moet nog netter worden beheerd.

Open werk:
1. Per tab expliciet vastleggen:
   - status: legacy, pilot, promoted, cutover candidate, afgerond.
2. Voor elke tab een parity checklist:
   - velden,
   - sorting,
   - filtering,
   - edit gedrag,
   - totals,
   - export,
   - performance.
3. Legacy tab pas uitzetten als:
   - parity akkoord,
   - performance akkoord,
   - geen functionele regressie in workflows.
4. Resterende hybride tabs beoordelen:
   - welke blijven Qt-tabellen,
   - welke moeten naar web/grid,
   - welke hebben vooral logische en niet visuele modernisatie nodig.

Aanvulling voor de komende fase:
1. expliciet vastleggen welke tabs nu officieel zijn,
2. expliciet vastleggen welke tabs legacy zijn,
3. per legacy tab vastleggen:
   - welke code alleen UI-consument is,
   - welke code nog producer of bridge is,
   - welke code voor load zorgt ook als de tab niet zichtbaar is.

### 3.5 Database compatibiliteit expliciet als architectuurlaag
De oude planbestanden hadden terecht veel aandacht voor DB-compat. Dat blijft relevant.

Open werk:
1. `DbCompatService` of equivalente compat-laag afronden.
2. Formele `do-not-break` lijst van tabellen/kolommen/objecten.
3. Additieve schema-evolutie als vaste regel blijven hanteren.
4. Scheiding tussen:
   - user database,
   - STOCKDATA,
   - tijdelijke runtime metadata,
   - persistent market data.
5. Migratieroutines verder standaardiseren over alle user DB's.

### 3.6 Rendering en updatebelasting verder verlagen
Een belangrijk architectuurdoel blijft dat de UI rustig blijft, ook als er veel events binnenkomen.

Open optimalisaties:
1. Inactieve tabs alleen snapshot-cache laten bijwerken, niet renderen.
2. Actieve tabs met vaste render cadence blijven werken.
3. Live events eerst licht cachen per instrument, daarna pas projections voeden.
4. UI-thread beschermen tegen bursts van data en onnodige full redraws.
5. Vooral kijken naar:
   - alt-tab responsiviteit,
   - tabwissels,
   - order entry performance,
   - langdurig openstaande sessies.

---

## 4. Data flow en event uitbreiding

Deze sectie beschrijft wat aan de datastromen en eventarchitectuur nog moet worden uitgebreid of aangescherpt.

### 4.1 Gewenst standaardpad voor live data
De gewenste datastroom voor live marktdatabase moet zijn:
1. tick komt binnen in price feed,
2. laatste waarde wordt licht opgeslagen per instrument,
3. throttled snapshot/event update volgt,
4. projection herberekent alleen wat relevant is,
5. actieve tab rendert op vaste cadence,
6. inactieve tabs renderen niet, maar kunnen wel een recente snapshot klaar hebben staan.

Open werk:
1. Volledig controleren of alle tabs dit patroon volgen.
2. Analyse van onregelmatige updatefrequentie voor tabellen die nog te vaak of te bursty lijken.
3. Expliciete tuningpunten centraal maken:
   - snapshot throttle,
   - active render interval,
   - eventueel later per datastroom eigen throttles.

### 4.2 Transaction events en derived data
Na transactiewijzigingen moeten de juiste datasets ververst worden, maar niet meer en niet minder.

Gewenst pad:
1. transactie verandert,
2. command/event wordt vastgelegd,
3. relevante state-engine run of light refresh wordt ingepland,
4. derived snapshots worden vernieuwd,
5. UI krijgt alleen de benodigde updates.

Open werk:
1. Precies vastleggen wat na add/update/delete moet gebeuren.
2. Eenduidige volgorde afdwingen:
   - transactiedata,
   - snapshot refresh,
   - state rebuild,
   - projection refresh,
   - UI update.
3. Dubbele of strijdige paden na order commit verder verminderen.
4. User-/DB-context expliciet respecteren bij state-engine snapshots:
   - `per_dag_asset_result_v2` hoort niet bij directe transactiemutatie,
   - maar wel bij startup en `db switch`,
   - omdat de app bij wissel van database ook moet wisselen naar de state-engine output van die andere user.

### 4.3 Daily catchup en startup flow aanscherpen
De startup en daily catchup logica is functioneel aanwezig, maar de guards en betekenis moeten verder worden aangescherpt.

Open werk:
1. Daily skip alleen toestaan als alle relevante engine classes succesvol zijn afgerond.
2. Startup-/db-switch flow verder expliciteren:
   - wanneer fullscope catchup,
   - wanneer incremental,
   - wanneer alleen price update,
   - wanneer geen actie.
3. Verduidelijken welke datasets hierdoor wel of niet gegarandeerd actueel zijn.
4. Catchup- en startup-status beter zichtbaar maken voor debugging en support.

### 4.4 Unresolved option series als formele dataflow
Unresolved series moeten niet langer als randgeval in losse logica zitten, maar als volwaardig event/dataflow-onderdeel.

Gewenst pad:
1. service detecteert unresolved serie,
2. serie wordt in meta snapshot gezet met reden,
3. UI toont dit in relevante tabs,
4. gebruiker kan resolver popup openen,
5. candidate selectie schrijft master,
6. refresh draait opnieuw,
7. unresolved melding verdwijnt automatisch wanneer opgelost.

Open werk:
1. Deze keten in alle relevante tabs consistent maken.
2. Candidate search slimmer maken voor feestdag- en weekopties.
3. Locked master entries respecteren zonder race-gedrag.
4. Resolver logging en status verduidelijken.

### 4.5 Persistente market data flow voor opties
Voor aandelen is last price opslag al een normaal patroon. Voor opties moet dit even beheerst en expliciet worden.

Open werk:
1. Schrijfpad voor option last prices formeel maken.
2. Fallback bij avond/weekend/geen live ticks verbeteren.
3. Expliciet vastleggen welke bron wordt gebruikt voor:
   - live optieprijs,
   - onderliggende prijs,
   - opgeslagen laatste prijs,
   - historische prijs.
4. `und_px` en afgeleiden consistent laten leunen op dezelfde bronhiërarchie.

### 4.6 Eventuitbreiding voor toekomstige features
De roadmap moet ruimte houden voor latere features zonder dat opnieuw een losse architectuurlaag ontstaat.

Daarom relevant om in de dataflow al rekening te houden met:
1. scenario events,
2. simulation context events,
3. advisor/recommendation events,
4. background analytics jobs,
5. parity/diff report events.

Deze hoeven nu nog niet allemaal gebouwd te worden, maar de architectuur moet ze kunnen dragen.

---

## 5. Testen en stabiliteit

Deze sectie beschrijft het werk dat nodig is om de app veilig te blijven veranderen.

### 5.1 Release gates als vaste discipline
Een wijziging is pas klaar als deze langs een vaste release gate is gegaan.

Minimale gate:
1. functionele parity op betrokken tab of workflow,
2. performance binnen acceptabele bandbreedte,
3. geen regressie in orderflow,
4. geen nieuwe log-spam op defaults,
5. geen DB- of migratiebreuk.

Dit moet niet impliciet blijven, maar expliciet als checklist per wijzigingsgroep worden vastgelegd.

### 5.2 Contracttests voor DB en legacy afhankelijkheden
Oude documenten legden terecht nadruk op bescherming van Access/Excel-validaties en andere vaste databasecontracten.

Nog relevant werk:
1. Contracttest-set opzetten voor kritieke tabellen, kolommen en typen.
2. Do-not-break baseline vastleggen.
3. Kernwaardes of kernqueries vergelijken voor en na wijzigingen.
4. User DB's en STOCKDATA beide meenemen waar relevant.

Dit blijft belangrijk, ook als de app zelf vooral op `_v2` of snapshots draait, omdat downstream validatie nog kan leunen op oudere objecten.

### 5.3 Parity tooling verder operationaliseren
Dual-run en diffing zijn niet alleen een eenmalig hulpmiddel, maar moeten structureel inzetbaar blijven.

Open werk:
1. Dagelijkse parity-report pipeline.
2. Duidelijke diff-output:
   - per tab,
   - per projection,
   - per belangrijke kolom.
3. Schakelbare diff mode voor ontwikkel- en releasegebruik.
4. Metrics en diffing koppelen aan acceptatiecriteria.

### 5.4 Performance- en stress-tests
De app heeft baat bij vaste testscenario's, niet alleen incidenteel handmatig gebruik.

Open werk:
1. Bench-scenario's definiëren:
   - markt open,
   - markt dicht,
   - veel live ticks,
   - veel open opties,
   - order toevoegen tijdens live feed,
   - db-switch,
   - lange sessie.
2. UI stress-tests opnemen:
   - tabwissel,
   - alt-tab terugkeer,
   - filter popup open tijdens updates,
   - inline edit tijdens updates,
   - sorteren en updategedrag.
3. KPI's per tab structureel loggen en interpreteren:
   - recompute p50/p95,
   - publish time,
   - update frequency,
   - render cadence.

### 5.5 Logging en observability verfijnen
De app heeft metrics en logging, maar deze moeten bruikbaar blijven.

Open werk:
1. Projection metrics standaard rustig houden.
2. Debug logging alleen via expliciete opt-in.
3. Runtime/refresh logs scheiden van foutmeldingen.
4. Duidelijke logregels voor:
   - unresolved resolver,
   - catchup beslissingen,
   - transaction move/remap,
   - DB migraties,
   - fallback usage.

### 5.6 Stabiliteitsissues expliciet blijven volgen
Niet elk open punt is een nieuwe feature; sommige zijn structurele stabiliteitsissues die nog niet definitief dicht zijn.

Open stabiliteitsthema's:
1. Onregelmatige updatefrequentie van sommige tabellen.
2. Popup/filter gedrag tijdens live updates.
3. Edit-velden die uit edit mode vallen bij updates.
4. Locale decimal handling in hybride Qt-tabellen.
5. Langdurige sessies waarin UI-hickups pas na tijd zichtbaar worden.

Deze punten horen in de roadmap thuis omdat ze direct de bruikbaarheid beïnvloeden.

---

## 6. Uitvoeringsvolgorde

Onderstaande volgorde is pragmatisch: eerst de basis stabieler en consistenter maken, daarna verder uitbreiden.

### Fase A: Updateflow audit en meetbasis
1. Feature inventory maken:
   - officiële tabs,
   - legacy tabs,
   - services/processen per tab,
   - snapshot/projection/event afhankelijkheden per tab.
2. Trigger inventory opstellen:
   - startup,
   - order save,
   - live tick/update,
   - db switch,
   - tab switch,
   - alt-tab terugkeer.
3. Meetplan vastzetten:
   - welk pad wordt gemeten,
   - welke metrics tellen,
   - waar logging of tijdelijke instrumentatie nodig is.

### Fase B: Stabiliseren van updateflow en runtimegedrag
1. Analyse en standaardisering van updatepaden per tab.
2. Order-save flow opschonen en versimpelen.
3. Uniform coalescing/throttle beleid formaliseren.
4. Inactieve-tab render discipline verder afdwingen.
5. Logging en metrics defaults opschonen.

### Fase C: Legacy tabs en load gefaseerd afbouwen
1. Legacy remove-matrix opstellen.
2. Eerst legacy consumers verwijderen die geen producerrol meer hebben.
3. Daarna legacy listeners, timers en aggregators uitschakelen die nog load geven.
4. Na elke wave parity en smoke-tests uitvoeren.

### Fase D: Transaction Engine V2 en orderflow
1. Command handlers add/update/delete.
2. Replay tool.
3. Test-transactie injectie API.
4. Verdere integratie met `optie eind`.

### Fase E: Resolver en optiedata hard maken
1. Unresolved flow volledig uitbouwen.
2. Candidate picker in relevante tabs uniform.
3. Master/lock workflow verbeteren.
4. `option_last_prices` en fallback chain standaardiseren.

### Fase F: UI cutover en parity afronden
1. Cutoverstatus per tab expliciet maken.
2. Parity-checklists aflopen.
3. Legacy tabs alleen uitzetten na expliciete acceptatie.

### Fase G: DB compat en quality gates
1. DbCompat / contracttests.
2. Multi-DB migratie checks.
3. Release gates en parity pipeline operationaliseren.

### Fase H: Nieuwe functionele uitbreidingen
1. Scenario/beta simulatie.
2. Rule-based advisor / roll ondersteuning.
3. Eventuele verdere analysetools boven op de gestabiliseerde architectuur.

---

## 7. Wat bewust niet meer op deze roadmap staat

De volgende soorten items zijn niet opnieuw opgenomen:
- oude versie-specifieke implementatieplannen voor andere projectmappen,
- onderdelen die aantoonbaar al in de huidige code zitten en geen open vervolg meer hebben,
- tijdelijke experimentstructuren die niet meer de richting van `portefeuille_viewer_1.1` bepalen.

Deze informatie blijft alleen als archief/context bestaan.

---

## Laatste update
2026-03-28
