# Roadmap: volledige markt- en portefeuillebriefing in zeven onderdelen

**Datum:** 25 oktober 2026. Bijlage bij
[het Wyse-bouwplan](plan_wyse_marktdataverzameling_portefeuille_extract_sync_en_ai_1.6.md).
**Status:** inhoudelijke specificatie en architectuurvoorwaarden; geen claim dat
de hieronder genoemde bronnen of berekeningen al geïmplementeerd zijn.

## Doel en dekking

Het uiteindelijke product is een dagelijkse briefing, een komende-gebeurtenissen-
overzicht en gerichte wijzigingssignalering. Het combineert een marktbrede blik
met ieder profiel en ondersteunt ook kansen in assets zonder positie. Inhoud en
actualiteit zijn controleerbaar: een leeg rapportonderdeel betekent niet dat er
niets gebeurt, maar kan ook betekenen dat de benodigde bron nog ontbreekt.

Het hoofdplan bevat de infrastructuur en eerste Yahoo-/portefeuille-integratie.
Daarmee is het volledige eindbeeld niet al gerealiseerd. De huidige Yahoo-code
verzamelt vooral bedrijfsfundamentals, earnings, consensus en analisteninformatie;
nog geen volledig marktbreed overnight-, macro-, flow- of nieuwsproduct. Ook een
losse gevonden Yahoo-koers bewijst geen bruikbare dekking, timing en historie
voor een complete briefing.

### 1. Wat is er overnacht gebeurd?

| Onderwerp | Vereiste gegevens en definitie | Nog te bouwen/onderzoeken |
|---|---|---|
| ES, NQ, RTY en Europese indexfutures | Contract-ID, expiry, actuele prijs, referentieslot/settlement, tijdstip en overnight-range | Futuresbron en contract-/sessiekalender; bestaande IBKR-waarnemingen zijn alleen actueel zolang een appverbinding ze aanlevert |
| 2- en 10-jaars Treasury yields, 2s10s | Rente als percentage, looptijd, noteringstijd, bron; curveverschil in basispunten | Marktbron selecteren; intraday notering onderscheiden van officiële dagreeks |
| DXY, EUR/USD, USD/JPY, olie en goud | Exact instrument: index, FX-paar, spot, future of expliciet gelabelde proxy | Instrumentregister uitbreiden, Yahoo-dekking toetsen en zo nodig andere bron toevoegen |
| Geopolitiek, centrale-bankuitspraken en bedrijfsnieuws na slot | Headline, publicatie-/waarnemingstijd, URL, uitgever, onderwerpen en betrokken assets | Nieuwsadapter, ontdubbelen en bronverwijzingen; geen bestaande nieuwscollector |

Een beweging wordt vergeleken met een vastgelegde referentie: cashslot, settlement
en vorige laatste tick zijn geen uitwisselbare waarden. Bewaar contractrolls en
definities van continue futures apart, zodat een rollgap niet als marktbeweging
wordt uitgelegd. Overnight is sessiegebonden en tijdzonebewust, niet simpelweg
alles sinds lokale middernacht.

Het antwoord op 'waarom?' bestaat uit brononderbouwde interpretaties. Een
gelijktijdig nieuwsbericht is geen bewezen oorzaak. Het rapport scheidt gemeten
beweging, geciteerde gebeurtenis en mogelijke verklaring. Een claim over yen-
carry/risk-off vereist meer onderbouwing dan alleen een beweging in USD/JPY.

### 2. Kalender: vandaag en deze week

| Onderwerp | Benodigde opslag | Status en aanvulling |
|---|---|---|
| CPI, PCE, NFP, jobless claims, PMI's, retail sales | Land, statistiek, verslagperiode, geplande/werkelijke publicatie, consensus, vorige waarde, herziene vorige waarde, actual en revisies | Nieuw macro-eventmodel en providers; officiële publicaties en marktconsensus zijn verschillende bronnen |
| FOMC, ECB en speeches | Instantie, spreker, eventtype, gepland tijdstip, bevestiging en publicatielink | Centrale-bankkalenders toevoegen; speeches en rentebesluiten apart modelleren |
| Earnings voor opening/na sluiting | Asset, financiële periode, datumbereik, sessielabel, bevestigd/geschat, consensus en actuals | Yahoo ondersteunt al onderdelen; bronkwaliteit en before/after-market niet veronderstellen als het antwoord alleen een datum bevat |
| Implied move versus historische earningsbeweging | Samenhangende ATM-call/putquotes, dezelfde expiratie over het event, underlyingprijs, bid/ask, tijdstip; historische slot/open/slot rondom eerdere events | Nieuwe marktbrede optie-input en analyse; positiequotes alleen dekken dit niet |
| Maandelijkse opex, VIX-expiratie, grote gecombineerde expiraties en index-rebalancings | Instrument-/beurskalender, event-ID, bron, tijdzone en settlementtype | Officiële kalenders of gevalideerde kalenderprovider; niet blind alleen 'derde vrijdag' coderen |
| Ex-dividend, lock-up expiries, splits en buyback blackouts | Eventtype, asset, datum/periode, status, voorwaarden en herkomst | Dividend deels aanwezig; andere eventtypen nieuw. Blackoutgegevens als bronbevestigd of expliciete benadering labelen |

Een straddle-gebaseerde implied move is een gedefinieerde premie-indicatie,
geen gegarandeerd koersinterval. Documenteer selectie van strike/expiry,
prijsmethode en procentuele normalisatie. Vergelijk historische bewegingen op
dezelfde horizon: overnight gap en close-to-close zijn verschillende analyses.
Ex-dividendwaarnemingen zijn input voor assignmentanalyse, geen zekerheid dat
een short call geassigned wordt.

Consensus moet bewaard blijven zoals zij vóór publicatie bekend was. Een later
herziene vorige waarde mag de originele briefing niet herschrijven. Het bestaande
feitenframework moet hiervoor expliciete event-ID's, series-ID's en vintages
krijgen. FRED/ALFRED kan een kandidaat zijn voor officiële/revisiehistorie, maar
vervangt niet vanzelf een economische consensuskalender.

### 3. Volatiliteit

| Onderwerp | Benodigde data/definitie | Ontbrekend werk |
|---|---|---|
| VIX9D, VIX, VIX3M | Afzonderlijke index-ID's, looptijd/horizon, bron en peildatum | Beschikbaarheid/distributie en historie toetsen bij geschikte bron |
| VIX-termijnstructuur, contango/backwardation | Expliciet onderscheid tussen indices met verschillende horizons en de futurescurve met contractexpiraties | Curvemodel en vergelijkingsregels; geen contango-claim zonder te benoemen welke curve wordt bedoeld |
| VVIX, SKEW en MOVE | Exacte index, definitie, noteringstype en vertraagd/actueel | Providers en gebruiksvoorwaarden onderzoeken; niet als bestaande Yahoo-dekking presenteren |
| Implied versus realized volatility | IV-referentie en RV op vergelijkbare horizon, jaarlijkse schaal en methodiek | Bestaande asset-IV/historie eerst inhoudelijk toetsen; berekeningsversie opslaan |
| IV rank / IV percentile per watchlistasset | Consistente IV-reeks, lookback, aantallen geldige observaties en gekozen definitie | Historie opbouwen; kortere/onvolledige reeks expliciet melden |

Bewaar bijvoorbeeld `iv_reference_definition`, tenor, delta-/moneynessselectie,
lookback en berekeningsversie. IV van willekeurige aangehouden opties met
verschillende expiraties vormt geen consistente asset-IV-reeks. Historische
koersdata alleen levert geen historische implied volatility. Het systeem
mag geen volwaardige IV rank tonen voordat de gekozen historie en dekking bestaan.

### 4. Optiepositionering en flows

| Onderwerp | Benodigde invoer | Randvoorwaarden |
|---|---|---|
| GEX en gamma flip | Optieketen met strikes/expiraties, gamma, OI, underlyingprijs, multiplier en dealerpositieaannames | Nieuwe modelanalyse; dealerposities zijn niet rechtstreeks uit openbare OI af te lezen |
| Call-/put-walls | OI of gekozen exposuremaat per strike, expiratieselectie en timestamp | Berekeningsdefinitie expliciet; een OI-cluster is geen gegarandeerde magneet/weerstand |
| 0DTE-volume en put/call-ratio's | Intraday optievolume met expiratie en afgesproken universum; onderscheid volume/OI en index/equity | Geschikte keten-/volumebron toetsen; geen marktbreed beeld afleiden uit alleen eigen posities |
| Ongebruikelijke activiteit, blokken en sweeps | Gedetailleerde transacties met tijd, beurs, omvang en classificatie | Waarschijnlijk aparte datavoorziening nodig; kosten, dekking en rechten vooraf verifiëren |
| OI-veranderingen van eigen tickers | Opeenvolgende, vergelijkbare ketensnapshots met OI-peildatum | Historie opbouwen; beschikbare OI niet automatisch als live intraday OI presenteren |

GEX, gamma flip en CTA-achtige schattingen horen als `model_estimate` te worden
gelabeld met modelversie, aannames en dekkingspercentage. Een door een provider
geleverde schatting blijft eveneens een schatting. Positieve/negatieve gamma
wordt niet als bewezen gedrag van alle dealers gerapporteerd.

Dit onderdeel valt buiten de eerste Yahoo-collector. Herhaald Yahoo ophalen
creëert ontbrekende intraday transactiedata niet alsnog. Voor iedere nieuwe bron
moeten daadwerkelijke toegang, granularity, limieten en kosten worden vastgesteld.
De Wyse hoeft zulke feeds niet zelf tot op tickniveau te verwerken als een
betrouwbare externe dienst de benodigde gegevens al levert.

### 5. Technische niveaus, marktbreedte en rotatie

| Onderwerp | Benodigde data | Voorbereiding |
|---|---|---|
| Vorige high/low/close en overnight-range | OHLCV met beurs-/sessiedefinitie en consistente corporate-actionbasis | Bestaande apphistorie kan input zijn; intraday/overnightdekking apart toetsen |
| VWAP, steun en weerstand | Voor echte intraday VWAP voldoende intraday prijs/volume; voor niveaus een vastgelegde methode | Geen VWAP uit alleen dagslotkoersen; onderscheid waarneming en modelniveau |
| MA20/50/200 op indices | Genoeg geldige dagobservaties, handelskalender, berekeningsversie | Bestaande indicatoruitkomsten hergebruiken waar zij dezelfde definitie hebben |
| Advance/decline en % boven MA200 | Vooraf gedefinieerd marktuniversum, constituentlijsten en prijzen per datum | Een nieuwe breadth-dataset; eigen portefeuille/watchlist is niet automatisch marktbreedte |
| Sectorrotatie | Sector-/indexinstrumenten, rendementshorizons, classificaties en vergelijking | Voortbouwen op assetcatalogus/indicatoren; SPY/RSP, growth/value en andere verhoudingen uitbreidbaar maken |
| Premarket gappers | Actuele premarketquotes, referentieslot, volume en bijbehorend nieuws | Premarket-dekking en liquiditeitsfilters toetsen; geen label 'live' bij oude data |

Voor historische vergelijkingen moeten universum en sectorindeling per datum
bekend zijn; uitsluitend de huidige indexleden gebruiken kan een vertekend
historisch beeld geven. Leg bij ratio's zoals SPY/RSP de richting vast: het
omkeren van teller/noemer keert ook de interpretatie om.

De bestaande door de app berekende indicatoren worden niet op de Wyse opnieuw
uitgerekend. Nieuwe marktbrede afgeleiden die de app nog niet levert kunnen
later een eigen analysejob krijgen. Dat is een bewuste uitbreiding, gescheiden
van reconstructie van de useradministratie, en wordt op de Wyse op belasting getest.

### 6. Het eigen boek

Dit blijft primair een exportvraagstuk: de app kent posities en berekeningen,
de server ontvangt een samenhangend resultaat. Ruwe transacties blijven lokaal.

| Onderwerp | Export/bron | Nog nodig |
|---|---|---|
| Totale delta, gamma, vega en theta | Beschikbare contract-/positie-Greeks, aantallen, multipliers, valuta, FX en timestamps | Eenduidige aggregatie en eventuele beta-gecorrigeerde exposure; ontbrekende Greeks niet als nul behandelen |
| Scenario markt -3%, volatiliteit +5 punten | Vastgelegde schokdefinitie, prijs-/vol-input en rekenmodel | Bestaande appscenario's exporteren of een apart gevalideerd model ontwerpen; +5 volpunten is iets anders dan +5% |
| Expiraties en assignment | Contracten, expiraties, short/long, underlyingprijs, tijdswaarde en dividend-events | Regel-/risicosignalering met bronkwaliteit; geen assignment voorspellen als feit |
| Margin en buying power | Werkelijke accountwaarnemingen van de broker met peildatum | Niet afleiden uit alleen posities of Greeks; dekking per broker vaststellen |
| Margin bij volatiliteitsschok | Broker-what-if of expliciete stressmethodiek | Geschatte P&L niet gelijkstellen aan gewijzigde brokermargin |
| Concentratie per sector/event | Posities, blootstelling, classificatie en eventkoppelingen | Bepalen of weging op marktwaarde, notional of delta-exposure berust |
| Stops en exitplan | Handmatig vastgelegde intentie en eventuele echte brokerorders, apart gelabeld | Nieuwe exportvelden/gebruikersinvoer; geen fictieve stoporders of automatisch ingestelde exits |

Een Greeks-benadering is een lokale schatting; grotere schokken kunnen volledige
herwaardering vragen. Bewaar horizon, model, prijsbasis en ontbrekende inputs.
Voor meerdere profielen worden resultaten standaard apart getoond; samenvoegen
gebeurt alleen expliciet. IBKR-accountwaarden dekken niet automatisch andere
brokers. Nachtelijke assignments blijven onbekend totdat de administratie is
bijgewerkt, zoals in het hoofdplan afgesproken.

### 7. Sentiment en positionering, bijvoorbeeld wekelijks

| Onderwerp | Bron en opslag | Aandachtspunt |
|---|---|---|
| CFTC Commitments of Traders | Officiële rapportreeksen met contract/markt, categorie, report-date, release-date en vintage | Publicatiedatum en positiepeildatum zijn verschillend; geen realtime positionering |
| CTA-positionering | Bronrapport of expliciet model met aannames | Geen publiek waargenomen totaal suggereren als het een modelinschatting is |
| Fund flows | Gedefinieerd fonds-/ETF-universum, periode, flowdefinitie en valuta | Koersstijging/AUM-verandering is niet zonder meer netto instroom |
| AAII-sentiment | Enquêteperiode, publicatie, bullish/neutral/bearish en bron | Beschikbaarheid, toegang en toegestane opslag/distributie vooraf controleren |

Een wekelijkse cadans kan passen, maar de planner volgt de werkelijke
publicatiekalender. COT heeft normaal een andere peildatum dan publicatiedatum;
bewaar beide en houd rekening met gewijzigde releaseschema's.

## Architectuurvoorwaarden die vanaf de eerste bouwfase gelden

1. **Meer soorten onderwerpen.** Ondersteun instrumenten, landen/regio's,
   economische reeksen, centrale banken, indices, universums en profielen.
   Niet alle informatie krijgt een fictieve asset_rollup.
2. **Identiteit en relaties.** Voeg onafhankelijke event-, series-, universe- en
   contract-ID's toe en koppel via relaties. Eén earningskolom is geen kalender.
3. **Tijd en revisies.** Bewaar verslagperiode, sessie, bronpublicatie,
   waarneming, geplande tijd, daadwerkelijke tijd, tijdzone en revisie afzonderlijk.
   Tijdstippen blijven UTC plus oorspronkelijke tijdzone waar relevant; geen
   vaste Amerikaanse publicatietijd omrekenen zonder zomertijdkalender.
4. **Feit, schatting en interpretatie.** Scheid bronwaarnemingen, gereviseerde
   actuals, consensus, modeluitkomsten en AI-duiding. Bewaar afleidingen met
   inputversies, formule en modelversie.
5. **Dekking is data.** Houd een matrix bij per bron, gegevensgroep en universum:
   live/delayed/EOD, laatst gelukt, ontbreekt, niet van toepassing en beperking.
   Toon niet-aangesloten onderdelen expliciet als nog niet beschikbaar.
6. **Momentopname voor rapporten.** Pin portefeuille-snapshot en marktwatermark.
   Een later gewijzigd earnings-event of herzien macrocijfer verandert een reeds
   gemaakt rapport niet ongemerkt. Rapporten krijgen hun eigen versie.
7. **Herkomst en toegang.** Providers hebben configureerbare capabilities,
   pollingbudget, benodigde credentials en gebruiksvoorwaarden. Een betaalde of
   nog niet onderzochte feed wordt geen impliciete gratis Yahoo-functie.
8. **Nieuwe berekeningen bewust plaatsen.** Appuitkomsten worden hergebruikt.
   Nieuwe marktanalyses krijgen aparte, begrensde jobs; zware keten-/intraday-
   verwerking wordt niet vanzelf onderdeel van de lichte collector.

De bestaande generieke feitenstructuur biedt een begin, maar bovenstaande
event-, tijdreeks-, model- en universumonderdelen vragen nog concrete schema's
en contracttests. 'Voorbereid' betekent hier een vastgelegde ontwerpeis, niet
dat alle ondersteunende tabellen al bestaan.

## Gefaseerde inhoudelijke oplevering

| Uitbreiding | Resultaat | Voorwaarde |
|---|---|---|
| Basis, hoofdplan A–F | Yahoo-bedrijfsfeiten, dividend, analyse-extract, veilige sync en eerste briefing | Huidige code losmaken en server/client bouwen |
| Kalender en overnight | Onderdeel 1 en 2 met betrouwbare brondekking; earningsdeel uit de basis hergebruikt | Macro-, markt- en nieuwsbronnen selecteren; events/tijdreeksen toevoegen |
| Volatiliteit en technische context | Onderdeel 3 en 5, plus bestaande app-indicatoren | Consistente volhistorie, marktuniversums, intraday waar vereist |
| Boekrisico verdiepen | Onderdeel 6 volledig genoeg voor gevalideerde scenario's en marginweergave | Brokerdekking, units en exportvelden toetsen |
| Flows en sentiment | Onderdeel 4 en 7, per beschikbare bron | Keten-/transactiedata, OI-historie en eventuele aanvullende abonnementen |
| Proactieve signalering | Relevante wijziging detecteren, ontdubbelen en uitleggen | Betrouwbare datasets, rapporthistorie en gevalideerde analysemethodiek |

Deze volgorde is geen verplichting om deel 6 laat op te leveren: de basis bevat
al het positie-extract en beschikbare Greeks. Uitbreidingen kunnen per bewezen
databron eerder worden toegevoegd. Het eindrapport houdt altijd de zeven rubrieken
aan, met onderscheid tussen gevuld, verouderd, ontbrekend en nog niet aangesloten.

## Aanvullende acceptatiecriteria

- Iedere regel uit de zeven rubrieken heeft een toegewezen bron of expliciete
  status 'bron nog te selecteren'; geen stil ontbrekende onderdelen.
- Een briefing kan uitsluitend met aangewezen snapshots/vintages worden
  gereproduceerd; latere correcties zijn als latere correcties herkenbaar.
- 'Vorige', 'consensus', 'actual', eventtijd en publicatietijd zijn niet verwisseld.
- Marktbreedte, GEX, OI, implied move en Greeks vermelden hun universum,
  peildatum en definitie, en weigeren misleidende uitkomsten bij ontbrekende input.
- De server blijft zonder volledige userdatabases werken. De app blijft leidend
  voor administratie en bestaande indicator-/resultaatberekeningen.
- De assistent verwijst naar bronfeiten en onderscheidt interpretatie. Een
  ontbrekende feed wordt niet met plausibel klinkende tekst ingevuld.

## Geraadpleegde primaire bronnen

- [CFTC: releasekalender](https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm)
  en [rapportbeschrijvingen](https://www.cftc.gov/MarketReports/CommitmentsofTraders/AbouttheCOTReports/index.htm).
- [ALFRED: historische vintages](https://alfred.stlouisfed.org/help)
  en [FRED API: vintage dates](https://fred.stlouisfed.org/docs/api/fred/series_vintagedates.html).

Dit zijn onderbouwingen voor het gegevensmodel, geen toezegging dat deze bronnen
al aangesloten zijn. Voor alle overige feeds volgt een concrete bronnenproef
voordat dekking, kosten of bruikbaarheid worden toegezegd.
