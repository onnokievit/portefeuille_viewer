# Directe STOCKDATA-toegang — stap A en B

De app gebruikt voor de omgezette koers- en referentieroutes rechtstreeks de
geconfigureerde STOCKDATA-database. De gekoppelde Access-tabellen worden hierbij
niet verwijderd en de databasestructuur wordt niet gewijzigd.

## Stap A

- `asset_last_price_store`: lezen en schrijven op STOCKDATA; cache-identiteit is
  het STOCKDATA-pad, onafhankelijk van de actieve portefeuille.
- `asset_rollup_repository`: kolominformatie en alle CRUD-acties op STOCKDATA.
- `repository`: assetreferenties, OHLCV, sprinterreferenties en de bijbehorende
  keuzelijsten op STOCKDATA. Brokers en transacties blijven usergebonden.
- `year_result_vs_indices_service`: indexreferenties en historische indexkoersen
  op STOCKDATA.

## Stap B

De vier state-engineprocessen ontvangen van `StateEngineRunner` zowel `--db`
(userdatabase) als `--stock-db` (STOCKDATA). Bij handmatig starten van deze vier
scripts is `--stock-db` nu ook verplicht; er is geen fallback naar de userdatabase.

- Aandelen: historische koersen en splits op STOCKDATA.
- Opties: historische koersen, splits en prijsfactoroverrides op STOCKDATA.
- Sprinters: historische koersen, sprinterreferenties en quote units op STOCKDATA.
- Dagresultaat: laatste beschikbare koersdatum en splits op STOCKDATA; posities,
  transacties en resultaten op de userdatabase.

`state_engine/common.py` bevat de gedeelde bronselectie die de opgeslagen query
`hist_data_per_asset_symbol` vervangt. De oorspronkelijke join op symbool blijft
behouden, inclusief meerdere rollups voor hetzelfde symbool. De koersvensters,
filters en de eerdere ankerkoers voor aandelen blijven gelijk.

Transacties, berekende state, statusregistratie en tijdelijke berekeningstabellen
blijven op de userverbinding. `transacties_bron_data` en het historische hulpmiddel
`create_state_engine_tables.py` worden niet aangepast of uitgevoerd.

## Verificatie

`python -m unittest discover -s devtools -p test_stockdata_routing.py -v`

Deze tests controleren de scheiding van beide databasepaden, de workflows van de
vier engines, usergebonden schrijfacties en de koerscache. Ze vergelijken de nieuwe
historische koersselecties met een opgeslagen Access-query in zelf aangemaakte
tijdelijke databases. Hiervoor zijn Windows, de Access ODBC-driver en DAO nodig.
De tests openen geen geconfigureerde productie- of aangeleverde analyse-databases.

Dit is de omzetting van de toegangsroutes. Onderlinge schrijfcoördinatie en het
verversen van caches tussen afzonderlijke appprocessen vallen onder de volgende
hardeningstap.
