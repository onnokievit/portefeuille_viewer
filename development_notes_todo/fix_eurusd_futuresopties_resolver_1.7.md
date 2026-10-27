# EUR/USD-futuresopties: gedeelde automatische en handmatige resolver

## Oorzaak en oplossing

De orderresolver nam voor EURUSD-FUT het algemene assetsymbool 6E over, terwijl
IBKR voor deze FOP-contractaanvragen EUR verwacht. De referentietabel bevat
meerdere handelsklassen onder opt_week=0; de oude dictionary behield alleen
de laatste regel (5EU). De handmatige knop probeerde bovendien uitsluitend
SMART/FTA, niet de opgegeven CME-beurs.

`services/option_contract_resolver.py` verzorgt nu beide zoekpaden. De
optiespecifieke productmapping voor EURUSD-FUT is EUR/FOP/CME/125000. De algemene
assetmapping en het symbool 6E voor bestaande prijsberekeningen worden niet
gewijzigd. Er zijn geen nieuwe databasekolommen of tabellen nodig.

Referentieregels blijven als lijsten bestaan. Exacte weekregels en fallbackregels
blijven beschikbaar; identieke zoekvarianten worden gededupliceerd. Eerst wordt
het exact gespecificeerde contract zonder vaste handelsklasse gezocht. Als dat
geen resultaat geeft, worden de relevante handelsklassen geprobeerd.

Contract-ID, symbool, type, beurs voor de productoverride, datum, strike,
call/put, valuta en multiplier worden gecontroleerd. Alleen één volledig
ontvangen, passende kandidaat wordt automatisch opgeslagen. Meerdere matches
worden handmatig gekozen; time-outs geven geen automatische selectie. Een
late callback van een vorige aanvraag kan de volgende aanvraag niet vervuilen.

## Opslag en interface

Nieuwe resoluties schrijven conid, local_symbol, werkelijke trading_class,
exchange_code, multiplier en underlying_symbol naar option_series_master.
Een bestaande conid of handmatige resolver-lock wordt niet overschreven.
Ook een rebuild overschrijft zulke bevestigde contractgegevens niet meer met
een willekeurige referentieregel. Een weer gebruikte inactieve rij wordt actief.

De handmatige knop gebruikt dezelfde resolver op een achtergrondthread. Tijdens
zoeken kunnen geen andere serie of kandidaat worden toegepast. Resultaten en
fouten worden via een Qt-signaal aan het venster teruggegeven. De selectie
wordt vóór opslag opnieuw gecontroleerd op de opgegeven optie.

IBKR-contractfouten worden via de gedeelde coördinator aan de aanvrager
doorgegeven. Bijvoorbeeld fout 200 blijft herkenbaar en verschijnt niet alleen
als een generieke time-out. Zonder IBKR-verbinding worden geen lange series
aanvragen ingepland; bij opnieuw verbinden wordt opnieuw opbouwen aangevraagd.

## Verificatie op 27 oktober 2026

Met de echte referentiedata zijn via uitsluitend contractdetails beide puts
voor 20 november 2026 gevonden:

| Strike | Contract-ID | Local symbol | Handelsklasse |
| --- | --- | --- | --- |
| 1,125 | 936030866 | 3EUX6 P1125 | 3EU |
| 1,1275 | 936031030 | 3EUX6 P1127 | 3EU |

Daarbij zijn geen orders, koersabonnementen of wijzigingen in de echte database
uitgevoerd. De opslagtests gebruiken aparte synthetische Access-databases.

Geslaagde tests: 16 resolver-/dialoog-/opslagtests, 20 gelijktijdigheidstests,
17 koersabonnemententests en 7 publicatie-/schedulingtests: 60 totaal.
Een eerste run van de bestaande drieproces-Access-test gaf native lockfout
-3810; de afzonderlijke herhaling en daarna de volledige set van 20 tests
slaagden. De algemene databaseverbindingscode is in deze wijziging niet aangepast.

## In gebruik nemen

Sluit alle Portefeuille Viewer-profielen. Wacht tot de gedeelde koerscoördinator
zich na de laatste client afsluit (normaal circa 15 seconden, eventueel langer
bij tijdelijke achtergrondclients). Start daarna de bijgewerkte 1.7-code.
De automatische resolver verwerkt ontbrekende contracten bij het opbouwen.
De knop voor handmatige resolutie gebruikt dezelfde zoeklogica.

Voor een laptop eerst de bijgewerkte code ophalen nadat deze is gecommit en
gepusht. Er is geen handmatige aanpassing van de referentietabel vereist voor
de onderzochte EUR/USD-opties.
