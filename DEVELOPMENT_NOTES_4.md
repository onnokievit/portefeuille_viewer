# Development Notes: Portefeuille Viewer Experiment 0.11

## Project Mapstructuur

- Hoofdmap: `C:\python_coding\portefeuille_viewer\portefeuille_viewer_experiment_0.11`
- Belangrijke submappen:
  - `ui_logica/` : UI-logica per tab, o.a. single_asset_analyse_tab_logica.py, opties_open_tab_logica.py
  - `data/` : Data repositories en snapshot_store
  - `ui/` : UI-bestanden gegenereerd uit Qt Designer
  - `services/` : Berekeningen en scenario-analyse
  - `programming/` : Overige scripts, zoals rekenmachine.py

## Belangrijkste ontwerpbeslissingen

- **In-memory data:** Asset history en opties worden bij het starten of bij database-wissel volledig in het geheugen geladen (Polars DataFrame). Filtering gebeurt in-memory voor snelle UI updates.
- **Polars DataFrame:** Alle tabellen en berekeningen werken met Polars voor snelheid en flexibiliteit.
- **PySide6/PyQt:** UI is opgebouwd met Qt Designer, widgets worden in Python gekoppeld en uitgebreid (o.a. pyqtgraph voor grafieken).
- **pyqtgraph PlotWidget:** Alle grafieken gebruiken PlotWidget, niet QWidget, voor correcte rendering en interactie.
- **Event-driven updates:** Asset-selectie, datumrange, en database-wissel triggeren directe updates van tabellen en grafieken.
- **TableModel/ProxyModel:** Filtering en sortering in tabellen gebeurt via PolarsTableModel en QSortFilterProxyModel.
- **Centrale data-opslag:** DataFrames voor asset history, opties_open, etc. worden centraal opgeslagen in SNAPSHOT_STORE, zodat ze overal in de app beschikbaar zijn.

## Huidige status

- **Single Asset Analyse Tab:**
  - Laadt alle asset history in-memory.
  - Filtert op asset en datumrange.
  - Grafieken worden direct geüpdatet bij selectie/wijziging.
  - Widget is een PlotWidget, met dual y-as voor koers en aantal.
  - Payoff-table wordt dynamisch gevuld en gevisualiseerd.
- **Opties Open Tab:**
  - Data wordt uit SNAPSHOT_STORE gehaald.
  - Filtering gebeurt via apply_filters() en reload_data(), met Polars.
  - TableModel en ProxyModel zorgen voor sortering en filtering.
  - Kleuring van cellen op basis van call/put en ITM/OTM.
- **Opties Eind Tab:**
  - Filtering gebeurt in reload_data() (zelfde patroon als opties_open).
- **Snapshot integratie:**
  - Alle relevante dataframes worden centraal opgeslagen en zijn overal beschikbaar.
- **Rekenmachine:**
  - Voorbeeldscript met PySide6, knoppen 0-9 en basisfuncties.

## Gebruikte technieken

- Python 3.11
- PySide6 (Qt Designer, widgets, slots/signals)
- Polars (DataFrame, filtering, berekeningen)
- pyqtgraph (PlotWidget, grafieken)
- QTableWidget/QTableView + TableModel/ProxyModel

## Belangrijke aandachtspunten

- Filtering gebeurt altijd in-memory, direct op Polars DataFrames.
- Data wordt centraal opgeslagen in SNAPSHOT_STORE.
- UI-widgets voor grafieken moeten PlotWidget zijn.
- Filtering in tabbladen gebeurt via apply_filters() en reload_data().
- Voor tab-overschrijdende data (zoals opties_open in single asset analyse) kun je het gefilterde DataFrame uit SNAPSHOT_STORE halen.

## Aanbevelingen voor verder werken

- Gebruik deze notes als context voor nieuwe features, refactors of bugfixes.
- Raadpleeg de mapstructuur en centrale data-opslag voor integratie tussen tabbladen.
- Houd rekening met event-driven updates en in-memory filtering voor performance.
- Voeg nieuwe tabbladen/dataframes toe aan SNAPSHOT_STORE voor centrale beschikbaarheid.

---
Deze samenvatting geeft een nieuw chat direct inzicht in de structuur, ontwerpkeuzes en status van jouw app. Gebruik dit bestand als startpunt voor verdere ontwikkeling en samenwerking.
