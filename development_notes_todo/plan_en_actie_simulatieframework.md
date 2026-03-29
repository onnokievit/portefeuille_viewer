# Plan en Actie Simulatieframework

## Doel en gebruik van dit document
Dit document beschrijft het ontwerp en de uitvoeringsvolgorde voor een app-breed simulatieframework in `portefeuille_viewer_1.2`.

Het document is bedoeld als werkdocument en afvinklijst voor de bouw van:
- centrale scenario-opslag,
- hergebruik van de bestaande test-order flow,
- app-brede scenario-injectie in de engine,
- behoud van de snelle payoff-simulatie in `SingleAssetAnalyseTab`.

Dit document beschrijft niet de administratieve bulkfunctie van `optie eind` als simulatiepad. `optie eind` blijft een afzonderlijk productiegericht hulpmiddel voor vrijdag-/zaterdagadministratie.

---

## 1. Samenvatting van de ontwerpkeuze

### 1.1 Wat blijft bestaan
De bestaande test-order flow in `SingleAssetAnalyseTab` blijft inhoudelijk de basis.

Die flow werkt nu al goed voor het belangrijkste niveau van simulatie:
- per asset snel verschillende ordercombinaties kunnen aan- en uitzetten,
- direct effect zien in de payoff table,
- comments op test orders kunnen vastleggen,
- test orders persistent opslaan in de database.

Deze bestaande flow wordt niet vervangen, maar gepromoveerd naar de basis van een breder simulatieframework.

### 1.2 Wat nieuw wordt gebouwd
Boven op de bestaande test-order tabel wordt een scenario-laag gebouwd.

Kern van de nieuwe opzet:
1. de huidige test-order tabel wordt hergebruikt als centrale tabel met kandidaat-mutaties;
2. er komt een aparte tabel met scenario-meta-data;
3. er komt een aparte tabel met scenario-inhoud;
4. er komt een centrale runtime-service die bepaalt welk scenario actief is;
5. de actieve scenario-orders worden in-memory in de engine geïnjecteerd;
6. dezelfde scenario-selectie wordt gebruikt door:
   - payoff-simulatie per asset,
   - en app-brede projections/tabellen.

### 1.3 Wat uit scope blijft voor deze eerste snede
De volgende zaken horen niet bij V1 van dit simulatieframework:
- automatische generatie van alle mogelijke positiechanges uit de base-posities;
- afgeleide generated changes voor assign/exercise/expire op brede schaal;
- volledige vervanging of herbouw van `optie eind`;
- meerdere tegelijk actieve scenario's;
- tab-specifieke scenarioselecties;
- een lokale scenario-override voor `SingleAssetAnalyseTab`.

---

## 2. Probleemdefinitie en uitgangssituatie

### 2.1 Wat de app nu al kan
De app heeft nu al een bruikbare, maar lokale simulatievoorziening in `SingleAssetAnalyseTab`.

Huidige eigenschappen:
- de tabel met test orders bevat persistent opgeslagen orderregels;
- per test order bestaat al een `include`-vinkje;
- een globale `Enable Test Orders` schakelaar zet de lokale simulatie aan of uit;
- de payoff table springt direct mee als een order aan of uit wordt gezet;
- de comments op test orders bestaan al en functioneren;
- de gebruiker kan handmatig verschillende combinaties van orders samenstellen.

Deze setup werkt goed voor asset-level beslisvorming en is functioneel zeer belangrijk.

### 2.2 Wat nu nog ontbreekt
Wat nog ontbreekt, is de stap van lokale payoff-simulatie naar app-brede scenario-simulatie.

Open tekortkomingen in de huidige situatie:
- een selectie van test orders heeft nog geen naam;
- een combinatie van orders kan niet als scenario worden opgeslagen en later teruggeladen;
- verschillende scenario-selecties zijn niet persistent als aparte entiteiten;
- de rest van de app rekent nog niet mee met dezelfde test-order selectie;
- `SingleAssetAnalyseTab` simuleert nu vooral payoff, maar nog niet dezelfde scenario-impact als de rest van de app;
- de bestaande `include`-kolom op de test-order tabel is nog de feitelijke werkselectie en nog niet losgekoppeld van scenario-opslag.

### 2.3 Waarom dit de juiste volgende stap is
De huidige payoff-simulatie laat al zien dat de kernlogica bruikbaar is.

Dat betekent:
- er hoeft geen compleet nieuw simulatiesysteem te worden uitgevonden;
- het bestaande test-order mechaniek kan worden hergebruikt;
- de volgende winst zit in centralisatie, scenario-opslag en engine-injectie;
- `SingleAssetAnalyseTab` blijft de belangrijkste ingang voor asset-level simulatie, maar wordt niet langer de enige consumer van de test orders.

---

## 3. Ontwerpkeuze

## 3.1 Splitsing tussen productie en simulatie
Er wordt bewust een harde scheiding gemaakt tussen:

### A. Productie / administratieve bulkverwerking
Dit blijft de rol van `optie eind`.

Doel:
- expire/assign-afhandeling voor werkelijke vrijdagavond- en zaterdagadministratie;
- wegschrijven van echte orders naar de productie-transactietabel;
- correctness belangrijker dan snelheid;
- handmatige controle tegen broker-rapporten blijft acceptabel.

`optie eind` is dus geen kernonderdeel van het simulatieframework.

### B. Simulatie / scenario-architectuur
Dit wordt een apart, app-breed framework.

Doel:
- hypothetische orders persistent opslaan als kandidaat-mutaties;
- scenario's opslaan als benoemde selecties van die mutaties;
- actieve scenario's in-memory in projections injecteren;
- payoff en app-brede tabellen op dezelfde scenario-selectie laten reageren.

## 3.2 Eén actief scenario tegelijk
Voor V1 wordt uitgegaan van precies één actief scenario tegelijk.

Dat betekent:
- er is één globale scenario-selector in de app;
- er is één globale scenario-aan/uit schakelaar;
- als op één tab een ander scenario wordt gekozen, geldt dat voor de hele app;
- `SingleAssetAnalyseTab` volgt dezelfde scenario-context als de rest van de app.

Deze keuze voorkomt verwarring tussen tabs die anders met verschillende scenario-bases zouden rekenen.

## 3.3 `SingleAssetAnalyseTab` blijft level 0 van simulatie
De payoff table is niet optioneel of later werk, maar blijft de kern van de simulatie.

Daarom geldt:
- de bestaande snelle payoff-reactie op test-order selectie moet behouden blijven;
- de nieuwe scenario-architectuur moet payoff vanaf de eerste fase blijven voeden;
- asset-level simulatie en app-wide simulatie worden niet als concurrerende paden gezien, maar als twee consumers van dezelfde scenario-basis.

---

## 4. Datamodel V1

### 4.1 Hergebruik van de huidige test-order tabel
De bestaande test-order tabel wordt hergebruikt als eerste versie van een centrale tabel met kandidaat-mutaties.

Werknaam in dit document:
- `position_changes`

Pragmatische keuze voor V1:
- de huidige tabelstructuur hoeft niet direct volledig te worden hernoemd;
- de bestaande database-opslag kan worden hergebruikt;
- comments op deze orders kunnen eveneens worden hergebruikt.

Voor V1 starten we met de bestaande handmatige test orders als inhoud van `position_changes`.

### 4.2 Tabel `scenarios`
Doel:
- scenario-meta-data opslaan.

Minimale velden:
- `scenario_id`
- `scenario_name`
- `description`
- `created_at`
- `updated_at`

Eventueel later:
- `created_by`
- `sort_order`
- `is_archived`
- `scenario_type`

### 4.3 Tabel `scenario_content`
Doel:
- per scenario vastleggen welke candidate changes actief zijn en hoe ze uitgevoerd worden.

Minimale velden:
- `scenario_id`
- `position_change_id`
- `enabled`
- `execution_family`
- `expected_outcome`
- `override_price`
- `override_amount`
- `updated_at`

Praktische betekenis:
- `scenarios` bevat de lijst met scenario's;
- `scenario_content` bevat de inhoud van elk scenario;
- hetzelfde `position_change_id` kan in meerdere scenario's voorkomen met een andere aan/uit status of andere uitvoermodus.

### 4.4 Comments
De bestaande comment-opzet op test orders blijft uitgangspunt.

Voor V1 kan dit pragmatisch zo blijven:
- comments horen aan de test order / position change;
- comments zijn scenario-onafhankelijk;
- append-only commenthistorie blijft gewenst.

Eventueel latere verbreding:
- comments formeel generiek maken voor aandelen, sprinters en opties;
- desnoods later losser trekken van alleen de huidige open-optie-commentstructuur.

Voor V1 hoeft dit nog geen nieuwe commentarchitectuur te worden als hergebruik van de huidige opslag praktisch goed werkt.

---

## 5. Runtime-architectuur

### 5.1 Centrale service
Er komt één centrale service, werknaam:
- `ScenarioService`

Verantwoordelijkheden:
1. laden van scenario-meta-data;
2. laden van scenario-inhoud;
3. bepalen welk scenario actief is;
4. bepalen of simulatie globaal aan of uit staat;
5. ophalen van de actieve position changes voor een scenario;
6. omzetten van actieve scenarioregels naar virtuele transactierecords;
7. publiceren van scenario-gerelateerde snapshots of events;
8. beschikbaar maken van asset-subsets voor payoff-logica.

### 5.2 Belangrijke runtime-functies
De service moet conceptueel in ieder geval het volgende kunnen:
- `get_active_scenario_id()`
- `is_scenario_enabled()`
- `get_active_scenario_changes()`
- `get_active_scenario_changes_for_asset(asset_rollup)`
- `build_virtual_transactions_global()`
- `build_virtual_transactions_for_asset(asset_rollup)`

Hiermee kan dezelfde scenarioselectie twee kanten op werken:
- lokaal voor payoff per asset,
- en globaal voor projections/tabellen.

### 5.3 Injectie in de engine
Als scenario-simulatie aan staat, worden de actieve scenario-orders in-memory in de engine geïnjecteerd.

Gewenst pad:
1. productie-transacties blijven de echte base;
2. actieve scenario-orders worden omgezet naar virtuele transacties;
3. projections rekenen met `base + scenario`;
4. de app toont daarmee scenario-effecten zonder de productie-DB te wijzigen.

Belangrijk:
- dit pad moet lichter zijn dan echte DB-based order-save;
- een testscenario hoeft niet de hele productie-orderflow te doorlopen.

---

## 6. UI-gedrag V1

### 6.1 `SingleAssetAnalyseTab`
Deze tab blijft de primaire editor/view voor test orders en asset-level simulatie.

V1-uitbreidingen:
- scenario selector toevoegen;
- scenario opslaan / nieuw scenario maken;
- bestaand scenario laden;
- huidige `include`-selectie gebruiken als werkselectie in de builder;
- payoff table blijft direct reageren op de actieve scenario-inhoud voor dat asset.

Belangrijke eis:
- de snelle visuele feedback van de payoff table mag niet slechter worden.

### 6.2 Andere tabs
In de tabs die centraal met projections rekenen, komt minimaal:
- een globale scenario selector;
- een globale enable/disable simulatie knop.

Deze selector en toggle zijn geharmoniseerd:
- wijziging op één tab geldt voor de hele app.

Relevante tabs voor V1:
- Aandelen
- Open Opties
- Optie Tijdswaarde
- Portfolio Value
- Sector Analysis
- eventueel later andere tabs

### 6.3 Wat V1 nog niet hoeft te doen
Nog niet nodig in V1:
- tab-specifieke scenario-selecties;
- meerdere tegelijk actieve scenario's;
- lokale override van `SingleAssetAnalyseTab` ten opzichte van de rest van de app;
- geavanceerde scenario-vergelijking naast elkaar.

---

## 7. Fasering

### Fase 1: Scenario-opslag boven op bestaande test orders
Doel:
- scenario's kunnen opslaan en terugladen zonder al app-breed te injecteren.

Werk:
- tabel `scenarios` maken;
- tabel `scenario_content` maken;
- scenario selector in `SingleAssetAnalyseTab` toevoegen;
- huidige selectie van test orders kunnen opslaan als scenario;
- scenario kunnen terugladen naar de bestaande `include`-selectie.

Tussenresultaat:
- payoff-scenario's krijgen een naam;
- scenario-combinaties zijn persistent;
- de bestaande payoff-workflow blijft intact;
- gebruiker kan snel wisselen tussen opgeslagen asset-level selecties.

Afvinklijst fase 1:
- [ ] `scenarios` tabel bestaat
- [ ] `scenario_content` tabel bestaat
- [ ] scenario selector zichtbaar in `SingleAssetAnalyseTab`
- [ ] scenario opslaan werkt
- [ ] scenario laden werkt
- [ ] payoff table reageert nog steeds direct
- [ ] comments op test orders blijven werken

### Fase 2: Centrale scenario runtime-service
Doel:
- scenario-selectie niet meer alleen lokaal gebruiken, maar centraal beschikbaar maken.

Werk:
- `ScenarioService` bouwen;
- globale scenario-enabled state invoeren;
- actieve scenario-id centraal opslaan;
- service laten leveren:
  - alle actieve scenario changes,
  - asset-subset voor payoff,
  - virtuele transacties voor globale injectie.

Tussenresultaat:
- scenario-selectie bestaat niet meer alleen als lokale tabelstate;
- payoff en engine kunnen dezelfde scenario-basis lezen;
- foundation voor app-brede simulatie ligt klaar.

Afvinklijst fase 2:
- [ ] `ScenarioService` bestaat
- [ ] actieve scenario-id is centraal beschikbaar
- [ ] globale scenario aan/uit state bestaat
- [ ] asset-subset voor payoff kan centraal worden opgevraagd
- [ ] virtuele transacties kunnen centraal worden opgebouwd

### Fase 3: Injectie in projections en app-brede simulatie
Doel:
- actieve scenario-orders laten doorwerken in de hele app.

Werk:
- injectie van virtuele transacties vóór projections;
- projections laten rekenen met `base + scenario` wanneer scenario actief is;
- globale selector/toggle op hoofdtabellen toevoegen;
- controleren dat Aandelen, Portfolio Value, Sector en andere relevante tabs scenario-effecten tonen.

Tussenresultaat:
- payoff-simulatie bestaat nog steeds;
- app-brede metriek beweegt nu mee met hetzelfde scenario;
- scenario's kunnen over meerdere assets tegelijk worden geëvalueerd.

Afvinklijst fase 3:
- [ ] engine accepteert scenario-injectie in-memory
- [ ] Aandelen-tab reageert op actief scenario
- [ ] Open Opties reageert op actief scenario
- [ ] Portfolio Value reageert op actief scenario
- [ ] Sector Analysis reageert op actief scenario
- [ ] globale scenario selector werkt app-breed geharmoniseerd
- [ ] globale enable/disable knop werkt app-breed geharmoniseerd

### Fase 4: Verbreding van de candidate set
Doel:
- niet alleen handmatige test orders, maar ook generated candidate changes gaan gebruiken.

Werk:
- bestaande base-posities kunnen kandidaatchanges genereren;
- later ook derived changes toevoegen voor assign/exercise/expire-uitkomsten;
- sync-logica op `ordersCommitted` uitwerken zodat generated kandidaatregels persistent maar actueel blijven.

Tussenresultaat:
- scenario builder bevat niet alleen handmatig ingevoerde ideeën;
- ook bestaande portefeuilleposities kunnen direct als scenario-mutaties worden gekozen;
- de stap naar bredere portfolio-simulatie wordt veel krachtiger.

Afvinklijst fase 4:
- [ ] base-posities kunnen kandidaatchanges genereren
- [ ] generated changes worden persistent opgeslagen of gesynchroniseerd bijgehouden
- [ ] obsolete generated changes verdwijnen wanneer base-posities verdwijnen
- [ ] assign/exercise/expire-uitkomsten kunnen als kandidaatregels worden gemodelleerd

### Fase 5: Verdere UX en workflow-uitbreiding
Doel:
- scenario builder prettiger en krachtiger maken.

Mogelijke uitbreidingen:
- `Test Close` acties achter open optie-/aandelen-/sprinterregels;
- partiële close;
- scenario clonen;
- scenario hernoemen;
- scenario archiveren;
- betere weergave van scenario-details per asset;
- integratie met latere beta-sensitiviteit.

Tussenresultaat:
- scenarioframework is niet meer alleen technisch bruikbaar, maar ook prettig in dagelijks gebruik.

Afvinklijst fase 5:
- [ ] snelle generate-acties vanuit positie-tabellen
- [ ] scenario beheer (clone/rename/archive)
- [ ] verbeterde detailweergave per asset
- [ ] voorbereiding op beta-sensitiviteit opgenomen

---

## 8. Tussenresultaten en eindresultaat

### 8.1 Verwachte tussenresultaten
Na fase 1:
- de bestaande payoff-selecties zijn benoembaar en persistent als scenario.

Na fase 2:
- payoff en centrale runtime lezen dezelfde scenario-basis.

Na fase 3:
- de hele app rekent met het actieve scenario.

Na fase 4:
- scenario's zijn niet meer alleen handmatige test-orderlijsten, maar echte portefeuillemutatie-sets.

Na fase 5:
- het framework is volwassen genoeg voor bredere simulatie- en analysetoepassingen.

### 8.2 Gewenst eindresultaat
Het eindresultaat van dit werkpakket is:
- één app-breed simulatieframework;
- hergebruik van de bestaande snelle payoff-simulatie;
- scenario's als benoemde, persistent opgeslagen selecties;
- een centrale service die scenario's in-memory in de engine injecteert;
- dezelfde scenario-context zichtbaar in payoff, Aandelen, Portfolio Value, Sector en andere relevante tabs;
- `optie eind` blijft een los productiegericht administratief pad;
- de architectuur is daarna geschikt om later:
  - beta-sensitiviteit,
  - bredere test-order flows,
  - generated candidate changes,
  - en complexere scenario-tools toe te voegen.

---

## 9. Open ontwerpbeslissingen voor later
Deze punten hoeven nog niet voor fase 1 te worden opgelost, maar moeten later wel expliciet gekozen worden:
- of de bestaande test-order tabel direct wordt hernoemd of pas later;
- of comments formeel generiek worden gemaakt voor alle `position_changes`;
- of `include` op de test-order tabel een tijdelijke werkkolom blijft of later helemaal verdwijnt;
- hoe generated candidate changes exact persistent en gesynchroniseerd worden;
- hoe option expiry/assign-uitkomsten exact als scenario-keuze worden gemodelleerd;
- of `SingleAssetAnalyseTab` later een optionele lokale scenario-override krijgt;
- hoe beta-sensitiviteit precies op dezelfde scenario-basis wordt aangesloten.

---

## 10. Beslissingen die nu al vastliggen
Voor deze eerste ontwerpfase liggen de volgende keuzes al vast:
- `optie eind` blijft productiegericht en staat los van simulatie;
- de bestaande test-order tabel wordt hergebruikt;
- de bestaande payoff-simulatie blijft behouden en is kernfunctionaliteit;
- er komt een aparte scenario-meta tabel;
- er komt een aparte scenario-inhoud tabel;
- er komt één actief scenario tegelijk;
- scenario-selectie is app-breed en geharmoniseerd;
- injectie gebeurt centraal vóór projections;
- `SingleAssetAnalyseTab` volgt in V1 hetzelfde globale scenario als de rest van de app.

---

## Laatste update
2026-03-29

## 11. Nuance: `include` verhuist van opslaglaag naar weergavelaag
In de nieuwe opzet blijft de vinkkolom in de UI voorlopig bestaan, maar niet meer als bron van waarheid in de test-order / `position_changes` tabel.

Dat betekent:
- de huidige `include`-kolom op de bestaande test-order tabel is in V1 niet langer de formele scenario-opslag;
- de echte scenario-selectie wordt opgeslagen in `scenario_content`;
- per scenario staat daar dus welke `position_change_id` aan of uit staat en met welke uitvoermodus.

Voorbeeld:
- scenario 1 activeert orders `1, 2, 3`;
- scenario 2 activeert orders `4, 5`;
- dezelfde order kan dus in meerdere scenario's met andere status voorkomen.

### 11.1 Consequentie voor de UI in V1
De gebruiker mag in V1 zo min mogelijk verandering ervaren in de bestaande test-order workflow.

Daarom blijft de weergave in `SingleAssetAnalyseTab` voorlopig zoveel mogelijk hetzelfde:
- dezelfde tabelvorm;
- dezelfde vinkkolom (`Incl`);
- dezelfde directe payoff-reactie;
- dezelfde comments op de regels.

Wat verandert, is de databron achter die tabel:
- nu toont de tabel direct de DB-tabel met test orders;
- straks toont de tabel effectief de join tussen:
  - `position_changes`
  - en de selectie van het gekozen scenario uit `scenario_content`.

Praktisch gedrag:
- de gebruiker kiest een scenario in een combobox;
- de vinkjes in de tabel springen mee naar de inhoud van dat scenario;
- het aanpassen van een vinkje schrijft niet meer naar `position_changes.include`, maar naar `scenario_content.enabled` voor het gekozen scenario;
- de payoff table blijft direct reageren op die wijziging.
