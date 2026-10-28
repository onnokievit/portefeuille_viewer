# Asset Dashboard 1.8 — eerste werkende bouwstap

Datum: 27 oktober 2026.

### Vier payoffinstellingen per asset

Het dashboard gebruikt voor Stap %, Stapvergroting, Verschuiving en Decimalen
de bestaande `_step_settings_by_asset`-cache van Single Asset Analyse. Die cache
wordt door de oude pagina geladen uit `single_asset_stepsize_settings` in STOCKDATA.
`DashboardPayoffControls` vertaalt de bestaande kolomnamen, gebruikt de bestaande
validatiemethoden en markeert uitsluitend wijzigingen aan de betreffende asset.
De bestaande `flush_step_settings_to_db` bewaart die cache bij afsluiten; er is
geen nieuwe tabel of tweede instellingenbestand gemaakt. Bij teruggaan naar de
oude tab worden haar controls uit dezelfde cache bijgewerkt.

De vier velden hebben vaste zichtbare omhoog/omlaag-knoppen en ondersteunen
de toetsenbordpijlen. Stap % verhoogt/verlaagt met de ingestelde Stapvergroting;
Stapvergroting zelf met 0,05, Verschuiving met 0,1 en Decimalen met 1, zoals de oude
controls. Tijdens een assetwissel zijn ze uitgeschakeld totdat de bijbehorende
gegevens gereed zijn. Het configure-verzoek bevat de asset-ID, zodat een late
wijziging nooit op een andere asset wordt toegepast.

Het aantal decimalen geldt ook voor koers/voorgaande koers, strikes/koersen in
de positietabellen, payoffheaders/-as en de koers-tooltip. De datumperiode blijft
afzonderlijk als profielinstelling bewaard. Bij afsluiten wordt ook een nog niet
verlaten instellingenveld eerst afgehandeld.

47 gerichte tests slagen. QtWebEngine bevestigt het laden van twee verschillende
assetconfiguraties, verhogen met de opgeslagen tick, wijzigen van alleen de
betreffende asset en herstellen van die wijziging bij terugselecteren. Alle
controles gebruikten fictieve caches; de echte database is niet aangepast.

### Afgeronde assen en zeven rasterlijnen

De drie tijdgrafieken gebruiken `asset_dashboard_axes.js`: precies zeven ticks
met zes gelijke, afgeronde intervallen. Stapgroottes schalen met het bereik
(1 / 1,25 / 2 / 2,5 / 5 maal een macht van tien). De aantallen-as gebruikt alleen
gehele stapgroottes en bevat altijd nul, ook na inzoomen of bij uitsluitend
positieve/negatieve aantallen. Voor koers/resultaat bepaalt het zichtbare bereik
de schaal; labeldecimalen volgen de stapgrootte.

De normale horizontale rasterlijnen zijn 0,5 logische pixel breed. Een aanwezige
nullijn is 1,25 pixel en krijgt de contrastrijkere marker-kleur. De payoff-as
is bij deze aanpassing niet veranderd.

Node-regressietests (`node devtools/test_dashboard_axes.cjs`) controleren zeven
ticks, dekking, nul en formatting, inclusief 1.500 deterministische bereiktests.
De 41 bestaande Python-tests slagen. QtWebEngine bevestigt daadwerkelijk getekende
labels 0/100/.../600 bij aantallen, -30.000/.../30.000 bij resultaat en
125/250/.../875 bij de gebruikte koersreeks. Er zijn uitsluitend fictieve
gegevens gebruikt.

### Thema Donker / Zand

Rechtsboven staat een themaselector voor alleen Asset Dashboard. Zand gebruikt
een warme beige achtergrond (#f1e7d5), crèmekleurige panelen (#fff9ee), donkere
tekst en warme randen. De kleuren zijn centraal als CSS-variabelen gedefinieerd.
Canvasgrafieken lezen dezelfde palettevariabelen voor assen, raster, lijnen en
candles. De legenda en tooltips wisselen mee; zoom en inhoud blijven behouden.
Dividenden/earnings, ITM-cellen en gebruikerscommentaar houden hun eigen betekenis
en opgeslagen kleuren.

De keuze wordt via SettingsManager opgeslagen in de profielvoorkeur
`ui.asset_dashboard_theme` (dark/sand). De HTML krijgt de bewaarde keuze vóór
laden mee, zodat de pagina niet eerst kort met een ander thema verschijnt.
Een wissel verandert alleen CSS en grafiekpresentatie, zonder herberekening of
opnieuw opbouwen van de pagina.

41 gerichte tests slagen. QtWebEngine-test met fictieve data en instellingen in
geheugen bevestigt herstel van Zand, heen en terug schakelen, opslaan van de keuze
en ongewijzigde ITM-kleuren. Het zandpalet is visueel gecontroleerd via
`C:/python_coding/diagnostics/asset_dashboard_zand_thema.png`.

### Optiecommentaar bewerken en kleuren

De commentcellen zijn bewerkbaar. Enter of verlaten van de cel bewaart de tekst;
Escape annuleert de nog niet bewaarde tekst. Rechtsklikken opent hetzelfde Qt-menu
met de bestaande `get_comment_colors()`-instellingen, inclusief Geen en Kies kleur.
Opgeslagen achtergrond- en tekstkleuren worden ook bij de eerste weergave getoond.

Er zijn geen extra zichtbare kolommen toegevoegd. De exacte serie-ID en de
commentkleuren reizen als aparte metadata naast de bestaande optievelden mee.
`DashboardComments` gebruikt de bestaande `_on_comment_commit` van de oude tab
en `update_open_optie_comment_color`. Daardoor blijven historie, caches,
modelpatches, de bestaande 60-seconden flush-timer en databaseopslag gelijk.
Deze tijdelijke afhankelijkheid moet worden losgemaakt voordat de oude tab ooit
verwijderd wordt; de oude Single Asset Analyse-code is niet aangepast.

Binnenkomende koersupdates overschrijven een actieve editor niet. Bewaren geeft
een bevestiging of zichtbare fout aan de cel. De nieuwe tekst en kleur verschijnen
ook in de bestaande modellen. Bij afsluiten wordt een actieve webeditor eerst
afgehandeld; pas na bevestiging loopt de normale closeEvent en de bestaande flush.
Bij een fout of een ontbrekende bevestiging blijft de app open.

38 gerichte tests slagen. De QtWebEngine-controle met fictieve data en commentcache
in geheugen bevestigt typen tijdens een refresh, bewaren via de echte webbridge,
de ingestelde rode kleur en het bewaren van een actieve editor vóór afsluiten.
De kleurmenukeuze was geautomatiseerd; er is niet naar de echte database geschreven.

### Vaste indicator en rustige assetwissels

De indicator heeft een vaste hoogte van 132 logische pixels en twee gestapelde
delen: labels/scores boven en de twee toelichtingsregels onder, gescheiden door
een subtiele horizontale lijn. Lange labels en scores blijven op hun eigen regel
met horizontale scroll; lange toelichting krijgt een ellipsis en volledige tooltip.

De pagina werd niet opnieuw geladen, maar veel DOM-inhoud werd met replaceChildren
weggehaald en opgebouwd. Bovendien wiste clearAnalytics de payofftabel en grafieken
voordat de nieuwe berekening klaar was. Dit is vervangen door blijvende componenten
in `asset_dashboard_view.js`: cijferkaarten, indicatorpills/scores, badges, tabelkoppen
en containers blijven staan. Alleen gewijzigde tekst, celstijl en benodigde
positierijen veranderen. De payofftabel behoudt zijn cellen. Canvasafmetingen worden
alleen aangepast bij een echte formaatwijziging, en ongewijzigde reeksen worden
niet opnieuw getekend.

Bij assetwisselen blijft de oude weergave staan met status Laden totdat de nieuwe
analyse gereed is. Daarna verschijnen nieuwe basisgegevens, posities en grafieken
in één browsertaak. De selectie zelf reageert onmiddellijk. Verouderde resultaten
worden genegeerd. Bij fouten worden oude grafiekgegevens niet als nieuwe gepresenteerd.
De afgesproken zichtbaarheid van lege positiesecties blijft gelden; daardoor kan de
pagina-inhoud nog van hoogte veranderen, maar de scrollpositie blijft waar mogelijk
behouden. Handmatig zoomen blijft intact bij updates van dezelfde asset.

33 bestaande tests slagen. De echte QtWebEngine-test met fictieve AAPL/UVXY-data
bevestigt dezelfde kaart-, pill-, tabel- en celobjecten vóór en na een assetwissel,
geen lege tussenfase, indicatorhoogte 132 bij beide assets en behoud van scrollY=100.

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

## Payoffgrafiek: oude schaal en prijsdistributie
- Oude 25%-formule voor de verticale marge en 2% horizontale marge overgenomen; ronde aslabels binnen het bereik.
- Volumegewogen prijsverdeling: balken 24/12 maanden, stippellijnen 6/3 maanden, afzonderlijke procentas met dezelfde dubbele headroom.
- Berekeningsmethoden ongewijzigd gekopieerd uit de oude UI naar een dashboardservice; uitgevoerd op de bestaande achtergrondworker, zonder databasewrites.
- Ontbrekende historie geeft geen fictieve verdeling. De oude Single Asset Analyse blijft ongewijzigd.

## Testorders en scenario’s vanuit het dashboard
- Sectie met bestaande testorders, globale aan/uit-schakelaar, assetfilter en scenarioselectie.
- Bewerken/toevoegen/verwijderen opent een apart venster met de originele Qt-tabel en originele bediening. De bestaande delegates, commentkleuren, filters, scenarioverwerking, validatie en opslag worden hergebruikt. Widgets worden bij sluiten teruggezet op hun oorspronkelijke plek; oude broncode blijft intact.
- Scenario builder en scenario manager blijven de bestaande dialogen.
- Payoff ontvangt effectieve scenario-orders op de UI-thread als Polars clone. De worker gebruikt de overgenomen legacy augmentatie, zonder globale caches of echte posities te wijzigen. Alleen aangevinkte orders tellen mee; historie blijft werkelijke historie.
- Automatische regressiecontrole op identieke legacy berekeningscode, aan/uit en include, EUR-omrekening, behoud van snapshots en terugplaatsen van de oorspronkelijke widgets (zowel absolute geometrie als layouts).
- Praktijktest: herstart, vergelijk dezelfde asset/scenario in beide pagina’s; test toevoegen, wijzigen, include, verwijderen, commentkleur, scenarioselectie en afsluiten/herstarten. Geen echte databasegegevens aangepast tijdens ontwikkelingstests.
