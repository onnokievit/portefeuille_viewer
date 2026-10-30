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

## 29 oktober 2026 — apart dashboard met instelbare indeling

### Gebruik
- Nieuw tabblad `Asset Dashboard – Indeling` naast het oorspronkelijke dashboard; bestaande pagina blijft bruikbaar.
- Start met `python portefeuille_viewer_1.8.py --profile onno -desktop` (ook standaard zonder schermoptie), of `python portefeuille_viewer_1.8.py --profile onno -laptop`.
- `Indeling bewerken`: versleep de kopbalk van een blok, wijzig de omvang met de hoekgreep rechtsonder. Pijltjestoetsen werken op beide handgrepen; Escape annuleert een lopende sleepactie.
- Automatische opslag na verplaatsen/vergroten, met zichtbare bevestiging of fout. `Standaard herstellen` herstelt alleen de actieve schermindeling. Er zijn aparte beginindelingen voor laptop en desktop.

### Techniek en isolatie
- Dezelfde AssetDashboardTab, HTML, berekeningen, testordereditor en commentaaropslag; geen kopie van de dashboardfunctionaliteit.
- Alleen de extra tab laadt de rastermodule. Bestaande DOM-blokken worden verplaatst, niet gekopieerd. Charts houden hun bestaande ResizeObservers en interactie; buiten de bewerkmodus zijn handgrepen uitgeschakeld.
- 24 rasterkolommen, verticale eenheden van 20 px plus 7 px tussenruimte. Overlappende blokken worden bij verplaatsen naar beneden geschoven. Grenzen en onbekende/dubbele blokken worden gecontroleerd in JavaScript en Python.
- Opgeslagen in de bestaande profielinstellingen onder `[ui] asset_dashboard_layout_desktop` en `asset_dashboard_layout_laptop`, als versie-1-JSON. Geen extra database of schema-aanpassing.
- Lege positieblokken blijven in normale modus verborgen; in bewerkmodus kunnen ook die posities worden ingericht. Het opgeslagen raster behoudt hun ruimte zodat een assetwissel de indeling niet herschikt.
- Beide dashboards worden pas bij eerste opening als webpagina geladen. Alleen het zichtbare dashboard publiceert updates. Eén gedeelde QThreadPool met maximaal één thread voor dashboardberekeningen; een lopende taak mag afronden, achterhaalde wachtende taken worden overgeslagen.
- Afsluiten bevestigt invoer en layoutopslag van beide geladen dashboards voordat services en opslag worden afgesloten.

### Controle
- Node-controles met 2400 deterministische verplaatsingen/vergrotingen: grenzen, overlappingen en behoud van standaardindelingen.
- Python-controles: afzonderlijke modusopslag, corruptie, profielrouting, startopties, één rekenworker, afbreken van wachtende taken, activeringsvolgorde en afsluiten van beide dashboards.
- Echte QtWebEngine-testvensters met fictieve snapshots en uitsluitend instellingen in het geheugen: desktop/laptop renderen, slepen, vergroten, opslaan via QWebChannel en gescheiden indelingen. Screenshots onder `C:/python_coding/diagnostics/dashboard_layout_desktop.png` en `dashboard_layout_laptop.png`.
- Geen productie-app gestart of productiedatabase/profielinstelling gewijzigd voor deze tests.

### Compacte bediening en fijner horizontaal raster
- Bewerkknop naar de bovenbalk; aparte indelingsregel, moduslabel en zichtbare statustekst verwijderd. Opslagmelding blijft toegankelijk via knop-tooltip en screenreaderstatus; opslaan mislukt geeft een gekleurde knoprand.
- Herstellen is alleen zichtbaar tijdens de bewerkmodus.
- Horizontaal raster van 24 naar 240 eenheden (10× fijnere breedte/positie). Verticale stappen en bestaande tussenruimte blijven gelijk.
- Opslagversie 2. Versie-1-indelingen worden bij lezen omgerekend door x en breedte met 10 te vermenigvuldigen; y/hoogte blijven gelijk. Geen profielbestand tijdens ontwikkeling gemigreerd of gewijzigd.
- Python- en Node-regressiecontrole voor migratie met behoud van verhoudingen; QtWebEngine-smoketest op beide schermindelingen geslaagd.

### Fijne verticale maatvoering
- Hoogte en verticale positie nu ook 10× fijner: 2,7 px per rasterstap in plaats van 27 px.
- Versie 3 van de indeling: versie 1 en 2 worden bij lezen omgerekend met behoud van positie, hoogte en 7 px tussenruimte. Bestaande indelingen hoeven niet opnieuw ingericht te worden.

### Positieblokken met automatische hoogte
- Puts, calls en aandelen/sprinters vormen in de indelingspagina één verplaatsbare stapel met de breedte/startpositie van het eerste positieblok. Puts eerst, vervolgens calls, daarna aandelen/sprinters; lege onderdelen verdwijnen.
- Elke tabel neemt precies de benodigde inhoudshoogte in, met 7 px tussenruimte. Geen verticale interne scrollbar; een horizontale scrollbar bij te veel kolommen kan blijven bestaan.
- De grip van de stapel wijzigt alleen de breedte, hoogte volgt altijd de inhoud. Dezelfde globale indeling kan dus een klein blok voor één optie en een groter blok voor meerdere opties tonen.
- Groei voorbij de gereserveerde ruimte schuift de onderliggende blokken mee. Weergavehoogte wordt niet naar profielinstellingen geschreven; bij assetwissels worden alleen DOM-inhoud en afgeleide positie aangepast.
- ResizeObserver en gebundelde DOM-observatie volgen rijenaantallen, verborgen blokken en breedtewijzigingen; geen extra koersophaling of berekeningen.
- Gecontroleerd met pure rastertests voor groei, verschuiven en behoud van opslag, en in QtWebEngine met één/vier opties en verdwijnen van een optieblok. De oorspronkelijke vaste Asset Dashboard-pagina blijft ongewijzigd.

### Compact testorderblok
- Kop/inklappen en routinematige statustekst verwijderd; bediening en tabel staan permanent open. Actiefouten blijven zichtbaar.
- Scenarioselectie en actieknoppen dezelfde vaste hoogte (28 px).
- Indelingspagina: alleen de tabel scrolt, buitenste paneel en container niet. Tabelkop blijft staan tijdens scrollen.
- QtWebEngine-test met 60 fictieve regels bevestigt één interne verticale scrollbar en gelijke select-/knophoogte.

### Compacte payoffkolommen
- Naamkolom vast 112 px. Numerieke padding links/rechts van 6 naar 2 px; gelijke koerskolommen binnen beschikbare breedte. Rijhoogte/font behouden.
- Bij een extreem smal blok verschijnt een ellipsis in een te smalle cel; de volledige waarde staat in de tooltip. Er worden geen cijfers weggeknipt zonder aanduiding.
- QtWebEngine-controle bevestigt vaste naamkolombreedte, 2 px padding en geen horizontale scrollbar in de testindeling.

### Versleepbare kolommen in positietabellen
- De eerdere toevoeging aan de payofftabel is op verzoek verwijderd. Payoff behoudt de vaste naamkolom en compactere padding.
- Kolomranden van calls, puts, aandelen en sprinters zijn versleepbaar. Calls en puts delen dezelfde kolomverdeling voor identieke uitlijning; aandelen en sprinters hebben elk een eigen verdeling.
- Automatische opslag per profiel, apart voor desktop/laptop, onder `[ui] asset_dashboard_position_columns_desktop/laptop`. Oude payoff-kolomvoorkeuren worden niet meer gelezen.
- Pijltjestoetsen verstellen 2 px; dubbelklik verdeelt de twee aangrenzende kolommen gelijk. Escape annuleert de sleepactie. Bij sluiten wordt een nog lopende opslag bevestigd.
- Bestaande commentaarinvoer, kleuren en automatische hoogte blijven behouden. Geen databaseaanpassing.
- Gecontroleerd: validatie van alle drie tabelindelingen en daadwerkelijke QtWebEngine-pointerevents op optie-kolommen met opgeslagen breedtes. Geen slepen op de payofftabel.

### Testoptiecommentaar rechtstreeks bewerken
- Het commentaarveld van geldige testopties en testaandelen is direct bewerkbaar, met dezelfde editor als bij opties in bezit. Enter/blur bewaart, Escape annuleert en rechtsklik gebruikt de bestaande kleurkeuze.
- Metadata gebruikt exact `repository.build_uniek_id` op de bestaande `row_to_dict_db`-velden; opslag via DashboardComments en de bestaande commentaarcache/flush. Geen nieuw opslagpad.
- Testregels worden op hun bestaande UID hergebruikt in de DOM, zodat verversen een actieve invoer/cursor niet vervangt. Dubbelklik op commentaar opent de native testordereditor niet; de overige cellen blijven dat doen.
- De actuele gedeelde commentaarcache wordt batchgewijs gelezen voor de testtabel. De native editor ververst zijn testtabel bij openen, zodat beide weergaven dezelfde tekst en kleuren tonen.
- Gecontroleerd: gedeelde ID, actuele tekst/kleur en onvolledige orders in unittests; rechtstreeks typen, bewaren via QWebChannel en behoud van editor tijdens verversen in de QtWebEngine-smoketest met fictieve gegevens.

### Vast dashboardtabblad verwijderd
- Er is nog één tabblad `Asset Dashboard`: de versie met versleepbare indeling. De extra vaste dashboardinstantie en registratie zijn verwijderd.
- Bestaande desktop/laptop-indelingen en kolomvoorkeuren blijven behouden. De interne tab-ID `asset_dashboard_layout` blijft gelijk, zodat de opgeslagen positie van de overblijvende tab intact blijft. Oude tabvolgordes met alleen `asset_dashboard` worden bij starten omgezet.
- De gedeelde dashboardcode blijft nodig voor de overblijvende pagina. Single Asset Analyse blijft beschikbaar.

### Payoffmarges en vorige koers
- Payoff-as gebruikt nu 5% van de uiteindelijke plothoogte als vrije ruimte boven en onder de uiterste payoffwaarden, in plaats van de oude tekenafhankelijke 25%-formule. Ronde aslabels blijven behouden.
- De bestaande vorige koers (`koers_prev`) gaat mee naar de workeruitvoer; wijzigingen van die koers tellen ook mee in de vernieuwingssleutel. Ontbrekende waarden worden niet ingevuld.
- Vorige koers als lichtere stippellijn (45% dekking), huidige koers als bestaande stippellijn. Een dunne pijl (1 px) op halve grafiekhoogte loopt van vorige naar huidige koers, groen bij stijging en rood bij daling. Bij gelijke/ontbrekende koersen geen pijl.
- Controles op exacte 5%-marges bij positieve/negatieve bereiken en doorgifte van vorige koers; QtWebEngine-smoketest met fictieve daling van 110 naar 100.

### Payofftabel en grafiek horizontaal uitgelijnd
- Naamkolom van 112 naar 84 px; labels ingekort tot Open aand./sp./opt., Gesl. aand./sp./opt. en Tot. no fees. Originele namen blijven beschikbaar als tooltip.
- Koers- en bedragkolommen gecentreerd. Rechts een gedeelde ruimte voor procentwaarden; het woord Verdeling uit de grafiek verwijderd.
- De grafiek neemt de gemeten linker/rechter tabelmarges over. Bij onder elkaar geplaatste blokken met dezelfde breedte vallen de linkerplotgrens, rechterplotgrens en alle 17 kolommiddelpunten binnen 1 px samen.
- Payoffpunten volgen de koerskolommiddelpunten; vorige/huidige koers, pijl, histogram en hover gebruiken dezelfde prijs-naar-x-interpolatie. Ronde/ongelijk afgeronde prijsstappen zijn meegenomen.
- Controle via Node op prijsinterpolatie en via echte QtWebEngine-geometrie op alle kolommen; geen opgeslagen gebruikersindeling aangepast voor de test.

### Dashboardvoorkeuren exporteren en importeren
- Onder `Indeling bewerken` staan Exporteren en Importeren. JSON-export bevat beide schermindelingen (desktop/laptop), positie-kolombreedtes, dashboardthema en datumselectie.
- Bestand kan bij Onno geëxporteerd worden en bij Muriel/Quinten geïmporteerd. Verbindingen, client-ID's, profielkeuze, databasepaden, orders, transacties en overige instellingen worden niet geëxporteerd of overgenomen.
- Hele bestand wordt gevalideerd vóór wijziging; één settings-save. Bij mislukte opslag wordt de configuratie in het geheugen teruggezet. Niet ingestelde schermindelingen worden als standaardinstellingen overgenomen.
- Lopende invoer/layout/kolomopslag wordt eerst bevestigd. Na import herlaadt alleen de dashboardpagina, met behoud van de geselecteerde asset, zodat de nieuwe indeling direct geldt.
- Tests: overdracht tussen twee fictieve profielen, uitsluiten van geheimen, ongeldige import zonder gedeeltelijke wijziging, rollback bij save-fout. QtWebEngine-smoketest exporteert naar een tijdelijk JSON-bestand, importeert en controleert het herladen; geen echte profielbestanden gewijzigd tijdens testen.

### Assetselector en gebeurtenissen als verplaatsbaar blok
- De bestaande assetselector, dividendlabels en earningslabels zijn uit de bovenbalk naar één nieuw blok `Asset · dividend · earnings` verplaatst. Dezelfde DOM-elementen en eventhandlers blijven in gebruik.
- Assetstatus, periode, thema en indelingsknoppen blijven bovenaan.
- Indelingsversie 4 voegt `asset_info` toe onder de payofftabel en vóór de payoffgrafiek; maakt daar ruimte met behoud van bestaande breedtes. Het blok kan vervolgens zelfstandig versleept en in omvang aangepast worden.
- Oudere opgeslagen indelingen en geïmporteerde layoutbestanden worden aangevuld; desktop en laptop blijven onafhankelijk opgeslagen.
- Controles: migratie van eerdere indelingen, Node-rastertests en QtWebEngine-smoketest met verplaatste selector en beide datumgroepen plus export/import.

### Procentweergave van de kerncijfers
- Dagverschil, Pct lineair en Pct delta ontvangen verhoudingsgetallen (zoals 0,13) uit de bestaande snapshots. De weergave vermenigvuldigt deze nu met 100 vóór het procentteken; bronberekeningen en bedragen blijven ongewijzigd.
- QtWebEngine-regressiecontrole: -0,0076 → -0,76%, 0,13 → 13,00%, 0,15 → 15,00%.

### Bewerken via onzichtbare randzones
- Kopbalk en losse rechtsonder-knop verwijderd. Bewerkmodus voegt geen padding of andere gereserveerde ruimte meer toe; echte inhoudshoogte blijft gelijk.
- Bovenrand (tussen de hoeken) verplaatst het blok. Zijranden/onderrand en hoeken wijzigen de omvang, inclusief de linker- en bovenhoeken met behoud van de tegenoverliggende rand. Cursors en randaccent geven de actie aan.
- Positiestapel houdt automatische hoogte: randbediening wijzigt alleen de breedte, de bovenrand verplaatst de stapel.
- Randzones zijn transparant en nemen geen layoutruimte in. Toetsenbordbediening blijft beschikbaar op bovenrand en rechteronderhoek.
- Node-tests controleren alle resize-richtingen en begrenzing; QtWebEngine-smoketest bevestigt gelijke afmetingen en scrollruimte van payofftabel, assetblok en indicator vóór/na inschakelen van bewerkmodus, plus verplaatsen/vergroten en opslag.

### Compact assetblok met twee regels en oorspronkelijke kleuren
- De zes kerncijfers zijn uit de bovenkant van de pagina naar de tweede regel van het verplaatsbare assetblok verhuisd. Eerste regel blijft assetselector plus dividend/earnings.
- Volgorde tweede regel zoals Single Asset Analyse: Pct. Change, Koers, Koers Prev., Net. Change, Pct Lineair, Pct Delta.
- Alle vijf gebeurtenisvakjes en zes waardevelden 72×28 px, font 12 px; datum/bedrag met 2 px horizontale padding. De assetselector blijft breder voor leesbare assetnamen.
- Achtergrondkleuren via een adapter naar de bestaande `_color_green_red` en `_get_portfolio_value_pct_color`; vorige koers dezelfde lichtblauwe QColor. Geen nieuwe financiële kleurregels of berekeningen.
- Indelingsversie 5 vergroot te lage bestaande assetblokken tot minimaal 40 rastereenheden voor beide regels, met verschuiving van onderliggende blokken. Desktop/laptop-export en import blijven compatibel met oudere indelingen.
- 75 Python-tests slagen; QtWebEngine controleert tweede regel, gelijke afmetingen/font, volledige datum/bedrag zonder afkappen en kleuren.

### Vaste indeling binnen het assetblok
- Eerste regel: asset/dividend/earnings links, Pct Lineair en Pct Delta rechts uitgelijnd. Alle bestaande waardevelden en kleuren blijven dezelfde DOM-componenten.
- Vaste dunne separator in dezelfde kleur als de assetindicator. Tweede regel: Pct. Change, Koers, Koers Prev., één leeg vak (72 px), Net. Change.
- Geen interne sleepfunctionaliteit voor de losse vakjes: vaste CSS-indeling. Het volledige blok blijft verplaatsbaar.
- Indelingsversie 6 maakt het basisblok minimaal 48 rastereenheden hoog; bij smallere schermen groeit alleen de weergavehoogte als de linker gebeurtenissenrij moet afbreken. ResizeObserver voert uitsluitend presentatiewerk uit.
- Gecontroleerd op rechtsuitlijning, separator, lege vakbreedte, behoud van kleuren/groottes en geen interne verticale scrollbar in QtWebEngine. Oudere exportbestanden blijven importeerbaar.
