# Asset Dashboard 1.8 — eerste werkende bouwstap

Datum: 27 oktober 2026.

### Earningslabels naast dividend

Naast de drie dividendbadges staan nu Earnings en de komende earningsdatum.
Beide gebeurtenissen gebruiken `event_date_display`: rood 0–7 dagen, geel 8–30,
grijs ontbrekend/verstreken. De datum wordt per gebeurtenis afzonderlijk beoordeeld;
een ontbrekend dividendbedrag beïnvloedt earnings niet.

`asset_dashboard_earnings.py` leest alleen de bestaande STOCKDATA-feiten met
`earnings_schedule` of `earnings_source_row`, via de vaste databaseworker. De
nieuwste waargenomen planning vervangt oude planningsregels. Toekomstige
publicatieregels zonder actual kunnen als fallback dienen. Verwijderde of reeds
gerapporteerde regels worden niet als nieuwe toekomstverwachting gebruikt.
De tab leest op de achtergrond bij openen en iedere minuut zolang hij zichtbaar
is. Er wordt geen nieuwe Yahoo-ophaling of databasewijziging gestart.

33 tests slagen. De QtWebEngine-test toont onafhankelijke dividend-/earningskleuren
via de achtergrondpublicatie. Een alleen-lezen controle op de echte STOCKDATA
vond 91 assets met een komende earningsdatum.

### Periode bewaren en indicator bij opstarten

Van/Tot worden opgeslagen via SettingsManager in de profielvoorkeuren onder
`app.asset_dashboard_start_date` en `app.asset_dashboard_end_date`. De eerste
begindatum valt terug op de oude `single_asset_analyse_start_date`, zonder die te
wijzigen; de eerste einddatum is vandaag. Daarna worden beide gekozen datums
hersteld. De webpagina krijgt de beginwaarden voordat de eerste berekening start.
Andere payoffbedieningen blijven voorlopig alleen voor de huidige sessie gelden.

Direct na het tonen van het hoofdvenster vraagt de app via de bestaande
HistoryIndicatorRunner een achtergrondronde aan, inclusief herladen van historie.
`request_startup` wordt gedeeld met het eerste bezoek aan de indicatortab en dient
de initiële aanvraag eenmaal in. De bestaande gedeelde indicatorcache/coördinator
blijft van toepassing. Een handmatige run en vervolgupdates blijven mogelijk.

28 gerichte tests slagen. De QtWebEngine-test met instellingen in geheugen
bevestigt herstel van beide datums en opslaan na een wijziging via de echte bridge;
geen echte gebruikersinstellingen zijn tijdens de tests gewijzigd.

### Vervolg op de compacte indeling

Asset- en statusselector staan linksboven. De losse assetnaam is verwijderd,
ook uit de indicatorstrook; de positievelden blijven ongewijzigd. De doorgestreepte
sectiekoppen (payofftabel, payoffgrafiek, open posities, dagkoersen en totaalresultaat)
zijn verwijderd. De payoffgrafiek vult zijn paneel, behoudens de noodzakelijke
aslabels, en heeft een verticale legenda linksboven binnen het plotvlak, in de
volgorde Totaal / Totaal - Open opties / Open opties. De legenda neemt geen aparte
rij onder de grafiek meer in. QtWebEngine-controle bevestigt deze indeling.

## Compactere weergave, statusfilter en historiefout

De doorgestreepte bovenregel, sectorregel en zoekinvoer zijn verwijderd. De
koerskaarten, marges, tabelrijen en payoffgrafiek zijn compacter; dubbele
toelichtingen onder de payoffpanelen zijn weggehaald. De indicatorstrook is juist
iets hoger (minimaal 64 logische pixels). Dividenddatum en bedrag staan als badges
bij de assetnaam, met dezelfde datumvensters als de oude pagina: rood 0–7 dagen,
geel 8–30, grijs ontbrekend/verstreken, anders de neutrale achtergrond.

De selector active/niet active/all filtert op de bestaande `status` uit
`repository_snapshot_active_asset_rollup_data`; geen nieuwe definitie van actief.
Die snapshot bevat ondanks zijn naam de hele catalogus inclusief inactive-rijen.
Startwaarde is active. Bij wijzigen blijft de huidige asset indien passend behouden;
anders wordt de eerste passende asset gekozen. Een lege selectie wist oude grafieken
en maakt lopende berekeningsuitkomsten ongeldig.

Historie zonder resultaatregels mislukte door ongetypeerde lege kolommen in de
private kopie van `load_asset_history`. De lege rechterkant van de join krijgt nu
expliciet Date, het assetdatatype van de koersreeks, en twee Float64-kolommen.
De originele Single Asset Analyse-code is niet gewijzigd. De AST-gelijkheidstest
geldt daarom nog voor payoff-/optie-methoden; historie heeft afzonderlijke
gedrags- en regressietests, inclusief ontbrekende, lege en niet-passende resultaatdata.

Negentien tests slagen. Een QtWebEngine-controle met fictieve snapshots bevestigt
compactere kaarten, de hogere indicatorstrook, rode dividendbadges, verwijderde
zoekinvoer en wisselen van active naar inactive via de daadwerkelijke bridge.

## Indeling en positiekolommen aangepast

Payofftabel links en payoffgrafiek rechts. De volledige positiesectie staat
eronder, met calls en puts apart, gevolgd door aandelen en sprinters. Bij
smalle vensters stapelen de payoffpanelen; brede tabellen scrollen intern.
De extra uitklapbare tabel met ruwe snapshotvelden is verwijderd.

De zichtbare velden en volgorde zijn nu gelijk aan de bestaande pagina:
vijf bij aandelen, negen bij sprinters en zestien bij calls/puts. De definitie
staat in `POSITION_COLUMNS` in `asset_dashboard_data.py`. Geen helper-ID's,
fee-helperkolommen of andere extra velden worden getoond.

De private `load_option_open_data`-methode is eveneens overgenomen naar de
dashboardmodule. Deze gebruikt de bestaande gedeelde `build_uniek_id` en
de bestaande tijdswaardesnapshot. Commentaar wordt uitsluitend uit de aanwezige
snapshot gelezen, laatste versie per ID; geen databaseophaling op dit pad.
Het dashboard reageert ook op tijdswaarde- en commentsnapshotwijzigingen.

Zestien tests slagen, inclusief kolomselectie, optieserie-koppeling van tijdswaarde,
laatste commentaar en vergelijking van de gekopieerde private methoden met de oude
pagina. De QtWebEngine-controle bevestigt payoffpanelen naast elkaar, posities
eronder en de kolomaantallen 16/5/9. Screenshot:
`C:/python_coding/diagnostics/asset_dashboard_1_8_payoff_naast_elkaar.png`.

## Uitbreiding: payoff en historie

Inmiddels aangesloten: de tien payoffrijen met zeventien koersstappen, inclusief
gesloten resultaten, dividenden en fees; de drie lijnen totaal, open opties en
totaal zonder open opties; historische dagcandles; aantal bezit en totaalresultaat.
Stappercentage, horizontale verschuiving, decimalen en historieperiode zijn instelbaar.
De instellingen gelden voorlopig alleen voor de huidige dashboard-sessie.

`asset_dashboard_logic.py` bevat een afzonderlijke kopie van negen private
payoff-/historie-methoden van de oude pagina. Een AST-regressietest controleert
dat die methoden inhoudelijk gelijk zijn (alleen de store is een expliciete input).
De vier gedeelde payofffuncties worden uit de bestaande service geïmporteerd.
De oude pagina en die gedeelde service zijn niet gewijzigd.

`asset_dashboard_analytics.py` werkt op vastgelegde Polars-snapshots. Berekeningen
draaien in maximaal één taak per dashboard, buiten de UI-thread. Bij nieuwe input
wordt alleen de nieuwste aanvraag bewaard en een achterhaalde uitkomst niet getoond.
Historie wordt per asset, periode, valutafactor en historische bronversie gecachet.
Prijsupdates vervangen de laatste weergave, maar maken de historische cache niet ongeldig.

Historisch resultaat gebruikt dezelfde join, forward fill en valutaconversie als
de oude pagina. Het actuele resultaat wordt niet nogmaals omgerekend. Aantal bezit
volgt de bestaande definitie: aandelen + sprinters + absolute aantallen open puts.
Een actuele quote is een los punt en wordt geen verzonnen OHLC-candle. Ontbrekende
historische OHLC wordt evenmin ingevuld. Bij ontbrekende actuele referentiekoers kan
de laatste beschikbare historische slotkoers de payoff-as bepalen; dat staat erbij.

De lokale canvasgrafieken vereisen geen CDN of extra pakket. Prijs, aantal en resultaat
delen zoom en verschuiven: muiswiel, slepen, dubbelklik en knoppen 3M/1J/Alles.
Een hover toont de bijbehorende datum en waarden. De selector wordt niet meer bij
iedere quote opnieuw opgebouwd, zodat het openen van de keuzelijst niet wordt onderbroken.

Veertien tests slagen (`devtools.test_asset_dashboard` en
`devtools.test_asset_dashboard_analytics`), inclusief gemengde Access Decimal/float,
payofftotalen, kosten, optieknikken, historie-uitlijning, cache-invalidatie en actuele
resultaatconversie. De QtWebEngine-test met fictieve snapshots bevestigt tien tabelrijen,
170 waardecellen en vier grafieken, zonder horizontale pagina-overloop op 1600 en
680 logische pixels. Screenshot: `C:/python_coding/diagnostics/asset_dashboard_1_8_charts.png`.
Productiegegevens en de bestaande database zijn voor deze tests niet geopend.

Nog niet aangesloten: testorders/scenario's, brokerselectie, payoffverdelings-overlay,
marktdata en bewerken van comments. Vergelijk met de oude pagina met testorders uit
en alle brokers geselecteerd. De oudere beschrijving hieronder documenteert de
oorspronkelijke eerste bouwstap; bovenstaande uitbreiding is de actuele stand.

De nieuwe tab staat naast Single Asset Analyse. De oude pagina en zijn eigen
code zijn niet aangepast. Alleen de registratie, activering en koersfocus in
het hoofdvenster zijn uitgebreid. De titel vermeldt nu versie 1.8.

## Beschikbaar

- Responsive webpagina, assetzoekveld en selector over de bestaande actieve assetcatalogus.
- Koers, vorige koers, dagverschil, net change, pct lineair en pct delta uit de
  bestaande `snapshot_aandelen_projection_v2`. Ontbrekende gegevens blijven leeg.
- Bestaande indicatorvelden en toelichting uit `snapshot_asset_indicator_live`.
- Dividenddatum en bedrag uit de bestaande dividendkalendersnapshot.
- Werkelijke open aandelen, opties en sprinters voor het geselecteerde asset,
  over alle brokers. Shortposities blijven behouden; nulposities worden weggelaten.
- Uitklapbare volledige positiedetails.

## Architectuur

`services/asset_dashboard_data.py` maakt uitsluitend een leesmodel van bestaande
snapshots. Het opent geen database en start geen berekeningen of datacollectie.
`ui_logica/asset_dashboard_tab.py` verzorgt activering en QWebChannel.
`ui/web/asset_dashboard.html` bevat presentatie en interactie. Tekst uit de
datasets wordt via `textContent` weergegeven, zonder HTML-injectie.

De webview wordt pas bij het eerste tabbezoek gemaakt. Binnenkomende wijzigingen
worden gebundeld met een niet-herstartende timer van 350 ms. Verborgen stopt die
timer; bij terugkeer leest de pagina de nieuwste snapshots. Identieke payloads
worden niet opnieuw verstuurd. Assetselectie gebruikt de bestaande koersfocus;
de tab bezit geen aparte IBKR-verbinding of abonnementen.

## Nog aan te sluiten

Payofftabel en grafiek, scenario's en testorders, candles met zoom en aantallen,
historisch totaalresultaat, broker-/periodefilters, portefeuillebrede optielijst,
commentaarbewerking, earnings en analisteninformatie. Die plekken zijn expliciet
als gepland aangeduid en bevatten geen fictieve cijfers. Voor deze functies
blijft Single Asset Analyse de werkpagina. Deze bouwstap vervangt die pagina niet.

## Validatie

`python -m unittest devtools.test_asset_dashboard -v`: zes tests geslaagd:
assetfiltering en wisselen, behoud shortposities, nulposities, geen mutatie van
brondata, ontbrekende gegevens, JSON, uitgesteld laden, timerbundeling en stoppen,
koersfocus-signaal en overslaan identieke publicaties.

Daarnaast een geïsoleerde echte QtWebEngine-test met fictieve snapshots: bridge,
zes cijferkaarten, twee positierijen, assetwissel en geen horizontale pagina-overloop
op 1600 en 650 logische pixels. Schermafbeeldingen in
`C:/python_coding/diagnostics/asset_dashboard_1_8_desktop.png` en
`asset_dashboard_1_8_narrow.png`. Geen productie-DB of IBKR gebruikt.
De sandbox blokkeerde de Chromium-renderer zelfs bij een lege pagina; buiten de
sandbox slaagde deze test zonder beveiligingsinstellingen van de app te wijzigen.

Praktijkcontrole: start `portefeuille_viewer_1.8.py`, open Asset Dashboard
(bij een bestaande tabvolgorde mogelijk achteraan), selecteer enkele assets en
vergelijk kerncijfers en posities met Single Asset Analyse. Controle met echte
profielen en een langdurige sessie is nog niet uitgevoerd.

Graphify-update uitgevoerd. De extractie slaagt, maar de HTML-export van 1.8
loopt tegen de bestaande grens van 5.000 nodes aan. De verplichte 1.4-update slaagt.
