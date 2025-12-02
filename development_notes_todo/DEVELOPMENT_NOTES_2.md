## Ontwikkelingsoverzicht Portfolio Viewer (experiment_0.10)

### 1. Start van het project
De app is opgezet als een desktopapplicatie voor portefeuillebeheer, geschreven in Python met gebruik van het PySide6-framework (Qt for Python). De structuur is modulair opgezet met een duidelijke scheiding tussen data, business logic (engine), services en de gebruikersinterface (UI).

### 2. Gebruik van Qt Designer
- Voor het ontwerpen van de gebruikersinterface is Qt Designer gebruikt. Hiermee zijn `.ui`-bestanden gemaakt voor de hoofdvensters en tabbladen.
- Deze `.ui`-bestanden zijn omgezet naar Python-code met behulp van het commando `pyside6-uic` of via een build-stap, zodat ze direct in de applicatie geïmporteerd kunnen worden.
- De UI-logica is gescheiden van de gegenereerde UI-code: de gegenereerde klassen worden geërfd in eigen Python-klassen waar de logica en signaalverwerking wordt toegevoegd.

### 3. Belangrijkste ontwikkelstappen tot nu toe
- Opzetten van de basisstructuur: mappen voor data, services, domain (engine), UI en configuratie.
- Implementatie van het hoofdvenster (`MainWindow`) en de tabbladen (orders, aandelen, opties, sprinters), elk met hun eigen model en logica.
- CRUD-functionaliteit voor transacties (orders) geïmplementeerd, inclusief snapshot-architectuur voor snelle UI-updates.
- Integratie van IBKR (Interactive Brokers) API voor het ophalen van live prijzen en het beheren van abonnementen op marktsymbolen.
- Implementatie van een in-memory snapshot store voor snelle data-aggregatie en UI-synchronisatie.
- Gebruik van Polars voor snelle dataframe-bewerkingen.
- Implementatie van centrale signalen (Qt signals) voor het synchroniseren van UI-componenten bij database- of snapshot-wijzigingen.
- Refactoring van tabbladen om consistent gebruik te maken van proxy-modellen, sortering en live updates.

### 4. Huidige opbouw van de app
- **UI**: Gemaakt met Qt Designer, omgezet naar Python, logica toegevoegd in aparte klassen.
- **Data**: Alle database-interacties via een repository-laag, snapshots voor snelle toegang.
- **Business logic**: PortfolioEngine coördineert live updates, aggregatie en signaalverwerking.
- **Services**: Prijsfeedservice voor IBKR, live aggregators voor aandelen, opties en sprinters.
- **Synchronisatie**: Qt signals zorgen dat wijzigingen in data direct doorwerken in de UI.

### 5. Volgende stappen
- Verdere verfijning van de UI met Qt Designer (meer tabbladen, dialogs, instellingenvensters).
- Uitbreiding van testdekking (unit/integratietests).
- Verbeteren van logging en foutafhandeling.
- Mogelijk toevoegen van export/import-functionaliteit en meer rapportages.
