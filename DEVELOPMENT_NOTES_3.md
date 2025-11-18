# DEVELOPMENT_NOTES_3.md

## Wijzigingen sinds DEVELOPMENT_NOTES_2.md

### Belangrijkste nieuwe features en refactors (okt-nov 2025)

- **Live aggregators refactor:**
  - Live prijzen worden nu opgeslagen met `(ib_symbol, ib_currency)` als key (tuple).
  - Aggregators (aandelen, opties, sprinters) updaten nu correct met live prijzen, niet alleen bij app-start maar ook bij prijsupdates.
  - `update_live_price` methodes aangepast zodat ze altijd symbol én currency verwachten.
  - Fallback naar `last_prices` alleen als er geen live prijs is.

- **Filter menu/mixin refactor:**
  - Filtermenu- en contextmenulogica uit orders-tab generiek gemaakt en verplaatst naar een mixin (`HeaderFilterMenuMixin` in `filter_popup.py`).
  - Kan nu eenvoudig hergebruikt worden in andere tabbladen.
  - Orders-tab gebruikt nu deze mixin, oude code is opgeschoond.

- **UI/UX verbeteringen:**
  - Open opties tab: ITM/OTM-kleuring toegevoegd.
  - SmartCombo verplaatst zodat .ui-bestanden direct gebruikt kunnen worden zonder handmatige aanpassing.
  - Minder kolommen in sommige tabellen voor overzichtelijkheid.

- **Database & snapshot updates:**
  - Databasekeuze-knop toegevoegd aan orders-tab.
  - Bij databasewissel worden aggregators en snapshots correct geüpdatet met actuele live prijzen.
  - Diverse fixes in snapshot synchronisatie en transactieverwerking.

- **Codekwaliteit:**
  - Project opgeschoond met Ruff (linter/formatter).
  - Ongebruikte functies verwijderd, code opgeschoond.

- **Bugfixes:**
  - Fout met resetten/verwijderen/aanpassen orderaantallen opgelost.
  - Fout met dubbele of ontbrekende kolommen in tabellen opgelost.
  - Fout met verkeerde veldfocus na orderinvoer opgelost.

### Overige kleinere wijzigingen
- Logging verbeterd.
- Testfuncties en repository viewer toegevoegd.
- Diverse optimalisaties in polars-queries en data-aggregatie.

---

**Laatste update:** 18 november 2025

Zie commitgeschiedenis voor alle details en codevoorbeelden.