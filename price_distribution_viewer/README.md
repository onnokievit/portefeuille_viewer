# Price Distribution Viewer

Losstaande mini-app voor prijsverdeling op basis van `historical_data_correct`.

Doel:
- asset kiezen
- 3m / 6m / 9m / 12m koersverdelingen over elkaar tonen
- huidige koers als verticale marker laten zien

Benadering:
- per dag wordt de range tussen `low` en `high` gelijkmatig over de geraakte prijsbuckets verdeeld
- als OHLC deels ontbreekt, wordt teruggevallen op de beschikbare waarden
- als alleen `close` beschikbaar is, telt die dag als één punt in één bucket

Run:

```powershell
cd c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.2
python .\price_distribution_viewer\price_distribution_viewer.py
```
