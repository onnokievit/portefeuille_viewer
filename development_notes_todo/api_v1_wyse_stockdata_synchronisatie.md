# API v1: Wyse → permanente opslag in STOCKDATA

## Definitieve opslagroute

De 1.7-app ontvangt via `/api/v1/manifest` en `/api/v1/changes` marktgegevens van
de Wyse en schrijft die rechtstreeks naar de bestaande STOCKDATA-tabellen:

| Tabel | Inhoud |
| --- | --- |
| financial_facts_current | Actuele gegevens, inclusief herkomst en serverrevisie |
| financial_facts_history | Inhoudelijke wijzigingen, met behoud van eerder verzamelde historie |
| financial_fetch_state | Streamidentiteit, bevestigde cursor, laatste synchronisatie en datasetcatalogus |

Er is geen extra SQLite-ontvangstdatabase en geen afzonderlijk nieuw tabelschema.
De oude lokale ontvangstlaag is vervangen. Aanmaak van tabellen gebeurt niet
automatisch bij het starten: dit pad vereist het bestaande financiële schema v1.

## Desktop en laptop

De gegevens en de voortgang reizen samen mee in STOCKDATA via OneDrive. Nadat
OneDrive de database op de laptop heeft bijgewerkt, hervat de app vanaf de
cursor in die database. Er wordt geen computergebonden cursor gebruikt.
De cursor is ook niet afhankelijk van het serveradres: hetzelfde systeem kan
later via een intern adres of een extern HTTPS-adres worden benaderd.
De serverstream moet wel dezelfde identiteit hebben.

Alleen `connection.json` met enabled/server_url/api_token staat lokaal onder de
bestaande runtime-map `market-exchange-v1`. Dit bestand bevat geen marktgegevens
en geen voortgang. Voor een laptop moeten deze verbindingsinstellingen eenmalig
worden ingericht. Het bestand blijft buiten Git. De afgesproken werkwijze is
één computer tegelijk gebruiken en eerst OneDrive volledig laten synchroniseren.

## Transacties, threads en profielen

HTTP wordt uitgevoerd op een vaste achtergrondthread. Er wordt nooit een
databaseverbinding of STOCKDATA-schrijfmutex vastgehouden tijdens netwerkverkeer.
`StockdataInbox` is slechts een facade zonder eigen verbinding. Elk databasewerk
loopt via `@stockdata_job` en de bestaande databaseworker; verbindingen blijven
op hun eigenaarthread en worden hergebruikt volgens het bestaande beleid.

Na ontvangst van een pagina wordt eerst de actuele cursor binnen de bestaande
schrijfbeveiliging gelezen. De pagina wordt gecontroleerd en feiten, historie en
nieuwe cursor worden in dezelfde transactie vastgelegd. Een fout in bijvoorbeeld
de historieopslag draait ook de actuele gegevens en cursor terug. Een tweede
profiel kan dezelfde pagina niet dubbel verwerken. De OS-lease voor ontvangst
is gekoppeld aan STOCKDATA; na afsluiten kan een ander profiel verdergaan.

De standaard lokale Yahoo-ophaling wordt overgeslagen wanneer de Wyse-verbinding
is ingeschakeld. Bij een netwerkfout wordt geen tweede eigenaar stilzwijgend
geactiveerd; eerder opgeslagen gegevens blijven behouden en ontvangst probeert
later opnieuw. IBKR-gegevens en dividendtaken worden hierdoor niet uitgeschakeld.
De 1.6-code is niet aangepast.

## Bestaande historie en bronversies

STOCKDATA kan al feiten bevatten die de lokale collector heeft verzameld. De
primaire fact_key wordt hergebruikt. Een reeds aanwezige identieke actuele waarde
krijgt geen dubbele historieregel. Een inhoudelijke wijziging krijgt een nieuwe
lokale revisie; bestaande lokale historie wordt niet verwijderd of hernummerd.
De serverrevisie en het wijzigingsnummer worden afzonderlijk bewaard in het
payload-metadataveld `__wyse_envelope__`. Serverrevisie en lokale revisie mogen
dus verschillen. Bekende schema-v1-inhoud wordt gecontroleerd met de inhoudshash.

Een expliciete toekomstige verwijdering wordt als tombstone bewaard. De gewone
financiële leesfunctie verbergt die voor actuele resultaten; historie blijft
beschikbaar. Ontbrekende gegevens worden niet als verwijdering behandeld.

## Nieuwe bronnen en datasets

De transportenvelop bevat source, dataset, typed subject, schema_version,
effective_at, published_at, observed_at, id, revision, sequence en payload.
Een subject hoeft geen asset te zijn. Dezelfde tabellen ondersteunen bijvoorbeeld
een economie, markt of CFTC-marktcode. Onbekende datasets en payloadversies worden
bewaard; de app hoeft daarvoor geen nieuw endpoint te krijgen. Velden die nog
geen inhoudelijke interpretatie hebben blijven in de payload staan.

Voor verdere bronnenuitbreiding moeten inhoudelijke schemas en bronadapters nog
worden toegevoegd. Access-tekstveldlimieten worden expliciet gecontroleerd: een
te groot identificatieveld geeft een fout en schuift de cursor niet door.
Geen stille afkapping van bronnamen, identifiers of perioden.

## Netwerk en herstel

HTTP met Bearer-sleutel is nu intern op `192.168.2.160:18180` ingesteld. Voor
buitenhuis is HTTPS vereist; TLS wordt gecontroleerd en redirects zijn geweigerd.
Cloudflare/publicatie is nog niet ingericht. De bestaande browserroutes zijn
LAN-routes en vallen niet onder de nieuwe API-sleutel.

De server levert maximaal 500 wijzigingen per pagina. Een appcyclus verwerkt
maximaal 20 pagina's; bij achterstand volgt een nieuwe cyclus, anders na een minuut.
Netwerkonderbrekingen hervatten vanaf de laatste succesvolle STOCKDATA-commit.
Een verkeerde stream of cursor vóór een herstelde serverstand geeft een fout.
Bij herstel van een oudere serverbackup moet bewust een nieuwe bootstrap worden
gepland. Een cursor los resetten met behoud van oude servermetadata is onvoldoende.
De serverhistorie mag niet worden gesnoeid zonder een nieuw bootstrapprotocol.

## Bediening

Start 1.7; na 20 seconden begint ontvangst. De statusbalk noemt expliciet STOCKDATA.
Voor handmatige controle vanuit de 1.7-map:

```powershell
python devtools/market_exchange_status.py
python devtools/market_exchange_status.py --sync --pages 20
python -m unittest discover -s devtools -p test_market_exchange.py -v
```

De eerste eenmalige productiesynchronisatie is voorafgegaan door een backup naast
de echte STOCKDATA met `.before-wyse-stockdata-` in de naam. De backup is gemaakt
met exclusieve bestandstoegang via `backup_stockdata_for_exchange.py`.

De 11 opslagtests gebruiken geïsoleerde echte Access-databases. Ze controleren
rollback na een schrijffout, hervatten na een netwerkfout, gelijktijdige profielen,
bestaande lokale historie, nieuwe datasets, tombstones en het kopiëren van de
database naar een laptop. Daarnaast slagen 16 bestaande financiële opslagtests
en 15 provider-/vergelijkingstests.

Productiecontrole op 27 oktober 2026: 71.929 wijzigingen verwerkt, met 70.552
actuele Wyse-records in STOCKDATA. De gesorteerde controle over fact_key,
serverrevisie en inhoudshash is exact gelijk aan de Wyse; nul inhoudshashafwijkingen.
De bestaande lokale financiële gegevens zijn behouden: totaal 70.911 actuele
records en 74.974 historieregels na de import. Een volgende synchronisatie
ontving nul wijzigingen. De oude lokale `.sqlite3`-ontvangstdatabase is na deze
controle verwijderd; in de betreffende runtime-map blijft alleen connection.json.

## Nog te bouwen

Profiel-extract-upload, catalogusuitwisseling, inhoudelijke schemas voor nieuwe
datasets en publieke HTTPS/Cloudflare-bereikbaarheid. De server-API blijft gelijk.
Graphify JSON en rapport zijn vernieuwd; de HTML-export van 1.7 overschrijdt de
bestaande limiet van 5.000 nodes.
