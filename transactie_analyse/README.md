# Transactie Analyse

Losstaande PySide6 app voor read-only analyse van `transacties_bron_data_org`.

Starten:

```powershell
cd c:\python_coding\portefeuille_viewer\portefeuille_viewer_1.4
python .\transactie_analyse\main.py
```

De app opent de actieve portefeuille database uit de settings met een read-only
ODBC connectie. De analyse koppelt `transacties_bron_data_org.asset_rollup` aan
`asset_rollup_data.asset_rollup` en gebruikt `asset_rollup_data.ib_currency` als
currency.

Standaard rapport:

- periode: jaar, maand, week of dag
- kolommen: broker en currency
- waarden: aantal transactierijen en signed som van `transactie_fee`
- filters: broker, currency, asset type, sector, regio en waarde/groei
- pivotvelden: sleep velden tussen `Beschikbaar`, `Rijen` en `Kolommen`
- de rijvelden links blijven vast staan; de meetkolommen scrollen horizontaal
