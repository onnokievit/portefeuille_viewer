# PoC Volatility Dashboard

Standalone PySide6 proof of concept for the implied-volatility dashboard from the video.

## Data

Default mode is read-only DB access. The app reads portefeuille viewer 1.4 settings from:

- `portefeuille_viewer/portefeuille_viewer_1.4/portefeuille_viewer/config/settings_shared.ini`
- `portefeuille_viewer/portefeuille_viewer_1.4/portefeuille_viewer/config/.user_settings/settings_local.ini`

It then reads `historical_data_correct.implied_volatility` from the configured stockdata Access database.

IBKR mode is optional and requests:

```text
whatToShow = OPTION_IMPLIED_VOLATILITY
barSizeSetting = 1 day
```

No portefeuille viewer 1.4 code or database rows are modified by this PoC.

## Run

From `c:\python_coding`:

```powershell
python -m poc_volatility_dashboard
```

If you use the portefeuille viewer virtual environment:

```powershell
.\portefeuille_viewer\venv\Scripts\python.exe -m poc_volatility_dashboard
```

## Notes

The `Apply sqrt(252)` checkbox is off by default. Use it only if the source series is daily volatility rather than already annualized volatility.

