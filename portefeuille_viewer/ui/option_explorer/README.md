# Option Chain Explorer - MVP

**Version:** 0.7  
**Date:** October 15, 2025  
**Status:** MVP (Minimum Viable Product)

## 📋 Overzicht

De Option Chain Explorer is een nieuwe tab in de Portfolio Viewer waarmee je optie series kunt verkennen via IBKR.

## ✨ Features (MVP)

### ✅ Geïmplementeerd

- **Symbol Selectie:** Kies uit alle symbolen in `asset_rollup_data`
- **Expiry Range:** Selecteer van/tot datum met calendar picker
- **Strike Range:** Optioneel filter op min/max strike price
- **Call/Put Filter:** Radio buttons voor Both/Calls Only/Puts Only
- **Refresh Button:** Haalt option chain op van IBKR
- **Tabel Display:**
  - ConId (uniek IBKR contract ID)
  - Strike (uitoefenprijs)
  - Type (C/P)
  - Expiry (vervaldatum DD/MM/YYYY)
  - Trading Class (serie indicator)
  - Multiplier (contract size)
- **Kleurcodering:** Calls = lichtgroen, Puts = lichtrood
- **Sorteerbaar:** Alle kolommen sorteerbaar

### ❌ Nog Niet Geïmplementeerd (Toekomstige Versies)

- Live prijzen (Bid/Ask/Last)
- Volume & Open Interest
- Implied Volatility
- Greeks (Delta, Gamma, Theta, Vega)
- Export naar Excel
- Right-click menu acties

## 🏗️ Architectuur

### Bestandsstructuur

```
portefeuille_viewer/
└── ui/
    └── option_explorer/                    ← NIEUW
        ├── __init__.py                     ← Module export
        ├── option_chain_tab.py             ← Main UI (300 regels)
        ├── option_chain_service.py         ← IBKR logic (200 regels)
        └── option_chain_model.py           ← Table model (120 regels)
```

### Dependencies

- **SNAPSHOT_STORE:** Leest `snapshot_asset_rollup_data` (read-only)
- **PriceFeedService:** Gebruikt IBKR connectie voor `reqContractDetails`
- **Polars:** Voor DataFrame operaties
- **PySide6:** Voor GUI componenten

### Isolatie

✅ **Volledig geïsoleerd** van bestaande code:
- Eigen folder `ui/option_explorer/`
- Geen wijzigingen aan andere tabs
- Enige aanraking: `main_window.py` (3 regels)

## 🎯 Gebruik

### 1. Start de applicatie
```bash
python portefeuille-viewer-experiment_0.7.py
```

### 2. Ga naar "Option Chain Explorer" tab

### 3. Selecteer parameters
- **Symbol:** Kies uit dropdown (bijv. "AAPL")
- **Expiry Range:** Stel datum range in (default: vandaag + 3 maanden)
- **Strike Range:** Optioneel (bijv. 90-110)
- **Option Type:** Both / Calls Only / Puts Only

### 4. Klik "Refresh Option Chain"

### 5. Wacht op resultaten
- Loading indicator verschijnt
- IBKR stuurt contract details
- Tabel wordt gevuld met resultaten

### 6. Resultaten bekijken
- Sorteer op kolom (klik header)
- Calls = groen, Puts = rood
- Status bar toont aantal opties

## 🔧 Technische Details

### IBKR API Flow

```
1. User klikt Refresh
   ↓
2. Build Contract (zonder strike/right = ALL options)
   contract.symbol = "AAPL"
   contract.secType = "OPT"
   contract.exchange = "SMART"
   ↓
3. Send reqContractDetails(reqId, contract)
   ↓
4. IBKR callback: contractDetails() (meerdere keren)
   - Extract: conId, strike, right, expiry, etc.
   - Apply filters (date range, strike range, call/put)
   ↓
5. IBKR callback: contractDetailsEnd()
   - All contracts received
   ↓
6. Convert to Polars DataFrame
   ↓
7. Display in table
```

### Filters

**Client-side filtering** (na IBKR response):
- Expiry range: `expiry_from <= expiry_date <= expiry_to`
- Strike range: `strike_min <= strike <= strike_max`
- Option type: Filter op `right == "C"` of `"P"`

**Waarom client-side?**
- IBKR `reqContractDetails` accepteert geen ranges
- Je moet ALLE opties ophalen en dan filteren
- Of: specifieke strikes opgeven (maar dan mis je opties)

### Performance

**MVP (geen live prices):**
- Request: ~1-3 seconden (afhankelijk van aantal opties)
- Display: Instant (Polars is snel)
- Memory: ~1KB per optie contract

**Typische aantallen:**
- AAPL 3 maanden: ~500-1000 opties
- BMW 3 maanden: ~200-400 opties

## ⚠️ Known Issues

1. **Geen live prijzen:** Bid/Ask/Last kolommen bestaan niet (MVP)
2. **Europese opties:** Meerdere series (DA1, DA2) kunnen verschijnen
3. **Grote datasets:** >1000 opties kan tabel traag maken
4. **Geen caching:** Elke refresh = nieuwe IBKR call

## 🚀 Toekomstige Features

### Phase 2: Live Prijzen
- Subscribe naar geselecteerde opties
- Toon Bid/Ask/Last in tabel
- Auto-update bij prijswijzigingen

### Phase 3: Advanced
- Volume & Open Interest
- Implied Volatility
- Greeks display
- Export naar Excel
- Right-click menu (Copy conId, Add to portfolio)

## 📝 Code Statistieken

**Totaal:** ~620 regels Python code

- `option_chain_tab.py`: 300 regels
- `option_chain_service.py`: 200 regels
- `option_chain_model.py`: 120 regels

**Complexiteit:** Low-Medium (MVP)

## 🔍 Testing Checklist

- [ ] Symbol dropdown populated
- [ ] Date pickers work
- [ ] Strike filters work (optional)
- [ ] Radio buttons work
- [ ] Refresh button triggers IBKR call
- [ ] Table displays results
- [ ] Sorting works
- [ ] Calls = green, Puts = red
- [ ] Status messages show
- [ ] Error handling works
- [ ] Empty results handled gracefully

## 📚 Referenties

- IBKR API: `reqContractDetails()`
- Polars: DataFrame operations
- PySide6: Qt GUI framework

---

**Ontwikkelaar:** Portfolio Viewer Team  
**Branch:** experiment_0.7  
**Status:** Ready for Testing
