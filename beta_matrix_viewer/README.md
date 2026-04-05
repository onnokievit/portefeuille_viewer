# Beta Matrix Viewer

Losstaande mini-app voor een index-beta-matrix op basis van `historical_data_correct` in `STOCKDATA.accdb`.

Run:

```powershell
cd c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2
python .\beta_matrix_viewer\beta_matrix_viewer.py
```

Wat de app doet:

- leest de geactiveerde beta-drivers uit `[beta]` in `settings_shared.ini`
- gebruikt alleen index-assets uit `asset_rollup_data`
- berekent per lookback (`3m`, `6m`, `12m`) een matrix:
  - rijen = target index
  - kolommen = driver index
  - cel = `beta(target, driver)`
- laat de diagonaal leeg

