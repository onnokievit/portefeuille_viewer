# Plan en Actie Simulatieframework

## Doel en gebruik van dit document
Dit document beschrijft de aangepaste ontwerpkeuze en uitvoeringsvolgorde voor het simulatieframework in `portefeuille_viewer_1.2`.

Het document is bedoeld als:
- ontwerpdocument,
- werkdocument,
- afvinklijst voor implementatie.

De belangrijkste herijking is:
- scenario-opslag blijft gebaseerd op de bestaande test-order tabel;
- `SingleAssetAnalyseTab` houdt zijn eigen lokale simulatiepad;
- app-brede simulatie voor andere tabs wordt niet meer primair via transactietabel-injectie gebouwd;
- app-brede simulatie wordt opgebouwd via overlays op snapshot-/projectieniveau.

`optie eind` blijft buiten dit document als productiegericht administratief pad.

---

## 1. Samenvatting van de nieuwe ontwerpkeuze

### 1.1 Wat blijft
De bestaande test-order setup blijft het uitgangspunt:
- de huidige tabel met test orders blijft de bron van kandidaat-orders;
- comments op deze orders blijven bruikbaar;
- scenario-opslag via scenario-meta en scenario-content blijft een goede keuze;
- `SingleAssetAnalyseTab` blijft de primaire plek voor asset-level simulatie.

### 1.2 Wat verandert
De eerdere richting om actieve scenario-orders via een virtuele transactielaag in de hele engine te injecteren, wordt losgelaten als primaire route voor V1.

Nieuwe keuze:
1. scenario-opslag blijft op orderniveau;
2. `SingleAssetAnalyseTab` gebruikt een eigen lokaal simulatiepad;
3. app-brede tabs krijgen scenario-effecten via overlays op hun eigen afgeleide snapshots;
4. de transactietabel blijft productie-georiënteerde basis en wordt niet de centrale simulatie-ingang.

### 1.3 Waarom deze koerswijziging nodig is
In de eerdere poging ontstonden problemen door het vermengen van:
- lokale asset-simulatie,
- app-brede scenario-runtime,
- en afgeleide transactiesemantiek.

Gevolgen:
- dubbel tellen,
- omklappende states,
- verschillen tussen `SingleAssetAnalyseTab` en andere tabs,
- te veel afhankelijkheid van refresh-volgorde.

De bestaande lokale payoff-simulatie werkte inhoudelijk al goed. Dat pad moet leidend blijven.

---

## 2. Uitgangssituatie

## 2.1 Wat de app nu al goed kan
De app kan nu al:
- handmatige test orders persistent opslaan;
- comments op test orders opslaan;
- scenario's opslaan en terugladen;
- per asset in `SingleAssetAnalyseTab` snel orders aan- en uitzetten;
- direct payoff-effect laten zien op assetniveau.

Dat deel is functioneel waardevol en bewezen.

## 2.2 Wat nog ontbreekt
Nog niet goed opgelost is:
- verdere inhoudelijke validatie van de app-brede scenario-doorrekening;
- scenario-uitbreiding naar `Sprinters Open`;
- eventuele latere uitbreiding naar:
  - `Open Opties`,
  - `Optie Tijdswaarde`;
- verdere verbreding van generated scenario's buiten open opties.

`Open Opties` en `Optie Tijdswaarde` zijn nuttig, maar voor V1 niet essentieel.
`Sprinters Open` is de eerstvolgende logische functionele uitbreiding binnen de simulatieflow.

## 2.3 Welke tabs in scope zijn
Voor de nieuwe opzet zijn de primaire doel-tabs:
- `Aandelen`
- `Portfolio Value`
- `Sector Analysis`

Niet essentieel voor V1:
- `Open Opties`
- `Optie Tijdswaarde`

---

## 3. Kernbeslissing: twee paden in plaats van één

## 3.1 Pad A: lokale asset-simulatie
`SingleAssetAnalyseTab` krijgt zijn eigen pad.

Eigenschappen:
- directe injectie van actieve test orders in de lokale asset-logica;
- geen afhankelijkheid van app-brede scenario-runtime;
- payoff table en charts blijven snel en voorspelbaar;
- dit pad blijft leidend voor asset-level analyse.

Doel:
- de oude V0-sterkte behouden.

## 3.2 Pad B: app-brede scenario-overlay
De andere tabs krijgen hun scenario-effect niet via de lokale asset-logica en ook niet primair via virtuele transacties, maar via overlays op afgeleide snapshots.

Doel-tabs:
- `Aandelen`
- `Portfolio Value`
- `Sector Analysis`

Eigenschappen:
- scenario-orders worden per asset vertaald naar overlay-effecten;
- base snapshots blijven bestaan;
- scenario snapshots worden daar bovenop gebouwd;
- deze overlays zijn los van de lokale payoff-engine.

## 3.3 Waarom deze splitsing beter is
Deze splitsing sluit beter aan op hoe de app echt is opgebouwd:
- `SingleAssetAnalyseTab` denkt in payoff en lokale assetdata;
- `Aandelen` denkt in summary-rows;
- `Portfolio Value` en `Sector Analysis` denken in asset-rollup-/waarderingssnapshots.

Dus:
- verschillende consumers,
- verschillende optimale injectiepunten,
- één gedeelde scenario-opslag,
- maar niet één gedeelde uitvoerroute.

---

## 4. Waarom de transactietabel niet het juiste injectiepunt is

## 4.1 Technisch bezwaar
Injectie op transactieniveau lijkt aantrekkelijk, maar zit te laag in de keten.

Problemen:
- te veel afgeleide repository-loaders hangen eraan;
- open/gesloten logica, aggregatie en waardering lopen allemaal mee;
- scenario-testdata gaat dan semantisch lijken op echte transacties;
- lokale en app-brede paden raken te sterk verstrengeld.

## 4.2 Praktisch bezwaar
Voor de tabs in scope is transactieniveau niet de natuurlijke bron:
- `Aandelen` draait op `build_aandelen_tab_summary()` / projection;
- `Portfolio Value` draait op `repository_snapshot_portfolio_value_total_combined_put`;
- `Sector Analysis` draait op datzelfde portfolio-value snapshot.

Dus:
- die tabs lezen al niet direct uit de transactietabel;
- injectie op transactieniveau is dan een omweg.

## 4.3 Nieuwe conclusie
Scenario-orders horen als bron op orderniveau te blijven bestaan, maar de app-brede doorvertaling hoort op snapshot-/projectieniveau plaats te vinden.

Kort:
- opslag op orderniveau;
- uitvoering op overlay-niveau.

---

## 5. Datamodel

## 5.1 Orders-tabel blijft basis
De bestaande test-order tabel blijft de basis.

Inhoudelijk betekent dit:
- de tabel is de centrale lijst met kandidaat-orders;
- actieve selectie hoort niet in de order zelf, maar in scenario-content;
- comments blijven gekoppeld aan de orderregels.

Voor V1 hoeft de bestaande tabel niet direct formeel hernoemd te worden.

## 5.2 Scenario-meta
Tabel:
- `scenarios`

Minimale velden:
- `scenario_id`
- `scenario_name`
- `description`
- `created_at`
- `updated_at`

## 5.3 Scenario-inhoud
Tabel:
- `scenario_content`

Minimale velden:
- `scenario_id`
- `position_change_id` of huidig order-id/uid
- `enabled`
- `execution_family`
- `expected_outcome`
- `override_price`
- `override_amount`
- `updated_at`

Voor V1 is `enabled` de belangrijkste kolom. De andere velden zijn voorbereidende ruimte.

## 5.4 Bucket-structuur
De eerdere bucket-denkwijze blijft inhoudelijk geldig:

### Bucket 1
- handmatige test orders
- dit is V1

### Bucket 2
- direct uit base-posities afgeleide kandidaat-orders

### Bucket 3
- afgeleide vervolgorders, zoals assign/exercise/expire-effecten

Voor nu bouwen we alleen V1 op bucket 1, maar de tabel mag voorbereid zijn op bucket-meta.

---

## 6. Welke bestaande snapshots en services relevant zijn

## 6.1 Voor `Aandelen`
Belangrijkste bron:
- `build_aandelen_tab_summary()`

Deze gebruikt onder meer:
- `aggregator_snapshot_aandelen_live`
- `aggregator_snapshot_load_open_opties_from_tx_live`
- `aggregator_snapshot_open_sprinters_live`
- `repository_snapshot_gesloten_opties`
- `repository_snapshot_gesloten_sprinters_no_asset_detail`
- `repository_portfolio_dividend`
- `repository_snapshot_portfolio_value_total_combined_put`

Conclusie:
- `Aandelen` denkt in samenvattingsrows per asset;
- scenario-overlay hoort op summary-niveau te komen.

## 6.2 Voor `Portfolio Value`
Belangrijkste bron:
- `repository_snapshot_portfolio_value_total_combined_put`

Deze wordt opgebouwd uit:
- `repository_snapshot_portfolio_value_aandelen`
- `repository_snapshot_portfolio_value_optie`
- `repository_snapshot_portfolio_value_sprinters`

Conclusie:
- scenario-overlay hoort op portfolio-value snapshotniveau te komen.

## 6.3 Voor `Sector Analysis`
Belangrijkste bron:
- sector-output leunt inhoudelijk op portfolio-value data, maar gebruikt in de praktijk ook eigen broncombinaties en afgeleide snapshots

Conclusie:
- `Sector Analysis` kan niet alleen als simpele alias van `Portfolio Value` worden aangesloten;
- er is een eigen sector-overlay nodig, wel op dezelfde snapshot-architectuur.

---

## 7. Nieuwe runtime-architectuur

## 7.1 Centrale resolver
De eerste centrale bouwsteen wordt geen transactieruntime, maar een resolver.

Werknaam:
- `ScenarioOrderResolver`

Verantwoordelijkheden:
1. actieve scenario-id laden;
2. scenario-content laden;
3. orders-tabel koppelen aan scenario-content;
4. actieve orders per scenario bepalen;
5. actieve orders groeperen per asset.

Belangrijkste output:
- `asset_rollup -> actieve scenario-orders`

Dit is de gedeelde basis voor:
- lokale asset-simulatie;
- app-brede overlays.

## 7.2 Overlay-service
Tweede centrale bouwsteen:
- `ScenarioOverlayService`

Verantwoordelijkheden:
1. base snapshots lezen;
2. actieve orders per asset ophalen via resolver;
3. per getroffen asset scenario-effect berekenen;
4. scenario-overlays publiceren voor doel-tabs.

Belangrijk: deze service schrijft niet naar productie-DB en hoeft geen echte orderflow te simuleren.

---

## 8. Concrete uitvoerlaag voor V1

## 8.1 Single Asset Analyse
Blijft lokaal.

V1-regel:
- geen afhankelijkheid van app-brede overlay-service voor payoff;
- payoff table en charts blijven direct op lokale scenario-orders reageren;
- dit pad blijft autonoom.

## 8.2 Portfolio Value overlay
Nieuwe output:
- scenario-aware variant van `repository_snapshot_portfolio_value_total_combined_put`

Bijvoorbeeld conceptueel:
- base snapshot blijft bestaan;
- scenario snapshot wordt apart gepubliceerd.

Deze overlay moet per asset minimaal correcte wijzigingen verwerken in:
- `aand_aantal_bezit`
- `aantal_sprinters`
- `opt_aantal_ITM_put`
- `opt_aantal_OTM_put`
- lineaire waarde
- delta waarde
- portfolio percentages

## 8.3 Sector Analysis
Sector Analysis leest vervolgens uit die scenario-aware portfolio-value output.

Daardoor hoeft Sector Analysis zelf geen eigen scenario-engine te krijgen.

## 8.4 Aandelen overlay
Voor `Aandelen` bouwen we een scenario-aware summary pad:
- base summary row per asset;
- patch voor getroffen assets;
- daarna percentages en totalen opnieuw afleiden.

Dus:
- niet via transacties,
- maar via scenario-aware summary-output.

---

## 9. Hoe de scenario-effecten worden berekend

## 9.1 Niet full engine-herbouw
We bouwen geen volledige simulatie van alle transactielogica.

We doen dit per getroffen asset:
1. neem base toestand van dat asset;
2. neem actieve scenario-orders voor dat asset;
3. bereken mutatie op relevante metriek;
4. patch alleen dat asset in de overlay-output.

## 9.2 Waarom per asset
Voordelen:
- sneller;
- beter beheersbaar;
- sluit aan op jouw huidige denkwijze;
- minder risico op dubbele of tegenstrijdige interpretatie.

## 9.3 Wat in V1 voldoende is
V1 hoeft niet alles perfect generiek te maken.

Voldoende is:
- alleen bucket 1 orders;
- correcte impact op de doel-tabs;
- duidelijke scheiding tussen lokale asset-simulatie en app-brede overlays.

---

## 10. UI-opzet V1

## 10.1 Scenario-opslag en beheer
De huidige scenario-opzet blijft:
- scenario selector;
- scenario manager;
- scenario-content;
- caching.

Dit stuk is al de juiste basis.

## 10.2 Single Asset Analyse
Blijft:
- scenario editor;
- test-order editor;
- primaire payoff-simulator per asset.

## 10.3 Andere tabs
Later in V1:
- de bestaande scenario-selector in `SingleAssetAnalyseTab` blijft de bedieningsplek;
- app-brede tabs lezen scenario-aware snapshots als bron;
- geen aparte globale selector toegevoegd in deze V1.

Niet nodig als eerste bouwstap:
- `Open Opties`
- `Optie Tijdswaarde`

---

## 11. Fases

### Fase 1: ontwerp en resolverbasis
Doel:
- één betrouwbare actieve-scenario resolver maken.

Werk:
- orders + scenario-content samenbrengen;
- actieve orders per asset opleveren;
- geen injectie in tabs nog.

Tussenresultaat:
- centrale waarheid: welke orders zijn actief in welk asset.

Afvinklijst:
- [x] orders-tabel als bron bevestigd
- [x] scenario-content koppeling bevestigd
- [x] resolver levert actieve orders per asset
- [x] resolver werkt volledig in-memory

### Fase 2: `SingleAssetAnalyseTab` expliciet los houden
Doel:
- lokale asset-simulatie formeel scheiden van app-brede simulatie.

Werk:
- lokale payoff-logica blijft op eigen pad;
- geen app-brede runtime-afhankelijkheid in payoff.

Tussenresultaat:
- lokale asset-simulatie is stabiel en onafhankelijk.

Afvinklijst:
- [x] payoff reageert alleen op lokaal scenario-pad
- [x] asset-level charts blijven stabiel
- [x] scenario-opslag blijft dezelfde bron gebruiken

### Fase 3: Portfolio Value overlay
Doel:
- app-brede scenario-impact zichtbaar maken in Portfolio Value.

Werk:
- base `repository_snapshot_portfolio_value_total_combined_put` lezen;
- scenario-effect per getroffen asset berekenen;
- scenario-overlay snapshot publiceren.

Tussenresultaat:
- Portfolio Value wordt scenario-aware zonder transactietabelinjectie.

Afvinklijst:
- [x] overlay service leest actieve scenario-orders
- [x] overlay service patcht portfolio-value rows
- [x] base snapshot blijft ongemoeid
- [x] scenario snapshot apart beschikbaar

### Fase 4: Sector Analysis aansluiten
Doel:
- Sector Analysis scenario-aware maken via dezelfde overlay-richting.

Werk:
- sector-overlay snapshots bouwen;
- `Sector Analysis` daarop laten lezen.

Tussenresultaat:
- sectorblootstelling en sectorwaarden bewegen mee met scenario.

Afvinklijst:
- [x] Sector Analysis leest scenario-aware bron
- [x] waarden en totalen bewegen consistent mee

### Fase 5: Aandelen-tab overlay
Doel:
- Aandelen-tab scenario-aware maken via summary-overlay.

Werk:
- scenario-aware variant van `build_aandelen_tab_summary()` of output daarvan;
- getroffen rows patchen;
- percentages opnieuw bepalen.

Tussenresultaat:
- Aandelen-tab toont scenario-effect app-breed.

Afvinklijst:
- [x] summary-overlay bestaat
- [x] getroffen assets worden correct gepatcht
- [x] percentages worden correct herberekend

### Fase 6: optioneel later
Doel:
- verdere verbreding.

Mogelijke uitbreiding:
- `Sprinters Open`
- `Open Opties`
- `Optie Tijdswaarde`
- bucket 2 en 3 buiten open opties
- generated candidate changes voor aandelen en sprinters
- scenario-actieknoppen vanuit posities

Afvinklijst:
- [ ] scope voor V2/V3 vastgesteld

---

## 12. Status van wat werkelijk gebouwd is

### 12.1 Gebouwd in deze V1

Gereed:

- centrale `ScenarioOrderResolver`
- scenario-opslag op basis van bestaande test-order tabel en scenario-content
- `SingleAssetAnalyseTab` blijft lokaal simulatiepad
- `Portfolio Value` scenario-aware via overlay-service
- `Sector Analysis` scenario-aware via eigen overlay-pad
- `Aandelen` scenario-aware via overlay/projectiepad
- scenario manager verbeterd:
  - rename stabieler
  - meervoudig deleten werkt
  - nieuw scenario start leeg
- generated scenario builder voor open opties:
  - bucket 1 zichtbaar in dezelfde editor
  - bucket 2 generated open option orders
  - bucket 3 derived ITM EOM-effects
  - scenario selector, filters, multiselects en scenario-beheer vanuit dezelfde popup
  - modeless venster met eigen enable-toggle
- state rebuild queue stabilisatie:
  - deduplicerend enqueue-gedrag
  - lichtere claim-query zonder grote `IN (...)` lijst

### 12.2 Bewust niet meer gedaan

Niet gekozen:

- scenario-injectie via `transacties_bron_data` als hoofdroute
- één gedeelde runtime waarin lokale payoff en app-brede scenario-injectie door elkaar lopen

Reden:

- dat pad gaf dubbel tellen, syncproblemen en onstabiel gedrag;
- de nieuwe overlay-opzet sluit beter aan op de echte bronnen van de doel-tabs.

---

## 13. Tussenresultaten en eindresultaat

## 13.1 Tussenresultaten
Na fase 1:
- één centrale actieve-scenario resolver.

Na fase 2:
- `SingleAssetAnalyseTab` stabiel en losgekoppeld van app-brede scenario-uitvoer.

Na fase 3:
- `Portfolio Value` scenario-aware.

Na fase 4:
- `Sector Analysis` scenario-aware.

Na fase 5:
- `Aandelen` scenario-aware.

## 13.2 Gewenst eindresultaat
Het gewenste eindresultaat is:
- één gedeelde scenario-opslag;
- één gedeelde actieve-order resolver;
- lokale asset-simulatie blijft autonoom;
- app-brede overlays voor de relevante tabs;
- geen primaire afhankelijkheid van transactietabelinjectie;
- uitbreidbaar naar bucket 2/3 en bredere scenario-tools.

---

## 14. Beslissingen die nu vastliggen

- de bestaande orders-tabel blijft uitgangspunt;
- scenario-meta en scenario-content blijven geldig ontwerp;
- `SingleAssetAnalyseTab` houdt zijn eigen lokale simulatiepad;
- app-brede simulatie gaat naar snapshot-/projectieniveau;
- de transactietabel is niet het primaire injectiepunt voor V1;
- V1 richt zich op:
  - `Aandelen`
  - `Portfolio Value`
  - `Sector Analysis`

---

## 15. Open punten

- `Sprinters Open` nog scenario-aware maken op dezelfde overlay-architectuur;
- generated scenario-uitbreiding buiten open opties:
  - aandelen
  - sprinters
- verdere inhoudelijke validatie van bucket 2/3 bij opties;
- hoe percentages in `Aandelen` exact opnieuw worden afgeleid na overlay-patches;
- of `Open Opties` en `Optie Tijdswaarde` in een latere fase dezelfde overlay-architectuur volgen;
- of scenario-aware snapshots op termijn nog verder gestandaardiseerd moeten worden.

---

## Laatste update
2026-03-31


## 16. Praktische status voor vervolggesprek
Voor een nieuw gesprek is de relevante samenvatting:
- de actieve codebasis is `c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2`;
- de gekozen simulatie-architectuur is orderopslag + scenario-content + overlays, niet transactietabelinjectie;
- bucket 1 is handmatig;
- bucket 2/3 zijn nu alleen gebouwd voor open opties;
- `Portfolio Value`, `Sector Analysis` en `Aandelen` zijn aangesloten;
- eerstvolgende logische uitbreiding binnen simulatie is `Sprinters Open`.
