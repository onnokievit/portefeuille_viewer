Lees en gebruik deze drie documenten als primaire context voor deze codebase en het vervolgwerk:

1. `development_notes_todo/plan_en_actie_simulatieframework.md`
2. `development_notes_todo/development_notes.md`
3. `development_notes_todo/roadmap.md`

Werk vanuit deze uitgangspunten:

- De actieve codebase is `portefeuille_viewer_1.2`.
- De app is een portefeuille-analyse en simulatie-app met onder meer tabs voor `Single Asset Analyse`, `Aandelen`, `Portfolio Value`, `Sector Analysis`, `Open Opties`, `Sprinters Open` en `Optie Eind`.
- De gekozen scenario-architectuur loopt niet meer via injectie in de transactietabel als hoofdroute.
- De huidige route is:
  - test orders + scenario metadata/content als opslag
  - `Single Asset Analyse` met lokaal simulatiepad
  - app-brede overlays voor `Portfolio Value`, `Sector Analysis` en `Aandelen`
  - generated scenario builder voor:
    - bucket 1 = manual test orders
    - bucket 2 = generated open option actions
    - bucket 3 = derived option EOM effects
- De scenario/simulatie-V1 staat grotendeels, maar verdere uitbreiding moet nog gebeuren.
- Belangrijk open functioneel werk is onder meer:
  - `Sprinters Open` scenario-aware maken
  - verdere uitbreiding van generated scenario's buiten open opties
  - verdere validatie en opschoning van de simulatieflow
- Strategisch doel:
  - de app verder uitbouwen tot een samenhangend analyse-, scenario- en simulatieplatform
  - met goede updateflow, state-engine integratie en later verdere automation/advisory mogelijkheden

Gebruik de documenten om:

- te begrijpen wat al gebouwd is
- te onderscheiden wat nog openstaat
- te zien waarom bepaalde architectuurkeuzes gemaakt zijn
- vervolgvoorstellen te doen die aansluiten op de bestaande richting

Neem deze documenten als leidend en sluit aan op de huidige implementatie, niet op oudere hypothesen of eerdere experimenten.
