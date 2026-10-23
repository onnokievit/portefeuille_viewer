# Koersabonnementen in versie 1.5

## Gedrag

Eén `SubscriptionManager` verdeelt de capaciteit over het bestaande asset-universum
en het open-opties-universum. Standaard: maximaal 100 aangevraagde streams, elke
30 seconden maximaal 10 vervangen. Een slot is bezet zodra de aanvraag verstuurd
is; pas ontvangst van marktdata bevestigt de status `Ontvangt data`.

Gewenste universa worden vervangen, niet opgeteld. Afmeldingen worden vóór nieuwe
aanvragen verstuurd. Het werk draait buiten de GUI-thread, met maximaal één
beheeractie per 100 ms. Deze begrenzing betreft de manager; andere bestaande
IBKR-tools hebben hun eigen API-verkeer en delen mogelijk de accountlimiet.

De geselecteerde onderliggende waarde in de zichtbare Single Asset Analyse-tab
krijgt tijdelijk voorrang. Er is geen permanente kern. Na het verlaten van die
tab doet het instrument weer normaal mee. Instellingen zijn aanpasbaar in het
nieuwe tabblad **Koersabonnementen**, met zoekfilter en diagnosevelden.

## Handelsuren en actualiteit

Handelsuren en tijdzone komen geleidelijk uit IBKR ContractDetails.tradingHours.
Dat omvat de door IBKR gemelde extended hours voor aandelen. Bekend gesloten
contracten nemen geen slot in. Onbekende, onleesbare of verlopen schema's worden
nooit zonder bewijs als gesloten behandeld. Schema's worden elke zes uur opnieuw
opgevraagd, maximaal vier metadata-aanvragen tegelijk, met timeout.

Ontvangsttijden zijn lokale ontvangsttijden, geen beurs/transactietijden. Last,
bid en ask hebben onafhankelijke ontvangsttijden en datasoort. Aandelen houden
Last, eventueel een expliciete close-fallback, zonder stilzwijgende mid-substitutie.
FX kan bid/ask-mid gebruiken. Opties behouden hun mid-waardering, met verse,
bij elkaar horende bid/ask en onafhankelijke prijsouderdom; Greeks maken een
bestaande prijs niet kunstmatig nieuwer. Gegevens uit Access blijven fallback;
ze worden niet automatisch als nieuw ontvangen live ticks aangemerkt.

`Geen recente data` betekent verdacht stil, niet bewezen gestopt. Standaard na
180 seconden geen ontvangen marktdata; na tweemaal die termijn volgt een begrensde
herstelpoging via de wachtrij. Gesloten markten worden eerst uitgefilterd.

## Fouten en herstel

- 101 verlaagt het effectieve budget; aanvraag wordt geweigerd en later herprobeerd.
- Handmatig toepassen van capaciteit herstelt het ingestelde budget voor een nieuwe poging.
- 100 pauzeert nieuwe beheeracties tijdelijk.
- 200 kent maximaal één conId/FOP-fallback; verdere fouten krijgen backoff.
- Delayed/partial-data-waarschuwingen hoeven een bruikbare stream niet te beëindigen.
- 1100 pauzeert de manager; TWS-heartbeats mogen die toestand niet verbergen.
- 1101 bouwt het universum opnieuw op binnen budget; 1102 behoudt streams.
- Socket-reconnect start eveneens geleidelijk opnieuw. Oude request-ID's worden genegeerd.

Diagnostiek: `logs/ibkr_subscriptions_<pid>.log`, roterend tot 2 MB met twee backups.
Alleen beheeracties en fouten worden gelogd, geen complete tickstroom.

## Opslag en beperkingen

Geen databasewijzigingen. Wachtrij en status leven in geheugen. Alleen expliciet
bewaren vanuit het tabblad schrijft de sectie `[market_data]` in settings_local.ini,
via een atomische vervanging van het lokale bestand; settings_shared.ini wordt
daarbij niet herschreven. Dit is nog geen volledige multi-instance-isolatie.

Met 250 instrumenten en 100 plaatsen geeft de standaardroulatie circa vijf minuten
aansluiting en 7,5 minuut wachten, vóór correcties voor prioriteit, fouten en
handelsuren. 'Volgende beurt' is een schatting, geen actualiteitsgarantie.

De kolom `Verwerkt in app` bevestigt verwerking door PriceFeedService; het is geen
bewijs dat een specifieke webtabel al opnieuw gerenderd is. Voor opties staat de
gekozen prijs/bron in het register, maar nog geen afzonderlijke GUI-renderbevestiging.

## Offline validatie

Vanuit de projectroot:

```
python -m unittest discover -s devtools -p test_subscription_manager.py -v
python -m unittest discover -s devtools -p test_price_feed_subscriptions.py -v
```

Tests gebruiken een gesimuleerde klok en gemockte IBKR-/Access-grenzen, inclusief
250 instrumenten, capaciteit, roulatie, fouten, reset, oude callbacks, handelsuren,
zomertijd, een aandelen-Last van 100 naar 90, opties, lokale instellingen en Qt-UI.
Live validatie in TWS blijft nodig voor de werkelijk beschikbare accountlijnen,
contractspecifieke handelsuren en langlopende quote-ontvangst.
