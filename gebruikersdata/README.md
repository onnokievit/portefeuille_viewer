# Instellingen per profiel — Portefeuille Viewer 1.5

Start ieder profiel in een eigen venster vanuit de appmap:

```powershell
python .\portefeuille_viewer_1.5.py --db onno
python .\portefeuille_viewer_1.5.py --db muriel
python .\portefeuille_viewer_1.5.py --db quinten
```

`--database` en `--profile` zijn alternatieven voor `--db`. `onno` verwijst ook naar
de bestaande database-alias `onno-productie`. Zonder argument wordt het laatst op
deze computer geopende profiel gebruikt, met de catalogusstandaard als fallback.

## Bestanden

| Pad onder gebruikersdata | Inhoud | Git |
|---|---|---|
| `gedeeld/settings_shared.ini` | Databasecatalogus, STOCKDATA-pad, brokerlijst, commentkleuren, featureflags en gezamenlijk koersbudget | Ja |
| `profielen/<naam>/settings.ini` | Voorkeuren, tabvolgorde, filters en grafiekinstellingen | Ja |
| `computers/<computer-id>/<naam>/settings_local.ini` | Vensterposities, kolombreedtes, lettergrootte en IBKR-verbindingsinstellingen | Nee |
| `computers/<computer-id>/startup.ini` | Laatst geopend profiel op deze computer | Nee |
| `runtime/<computer-id>/<instantie>/session.json` | Diagnostische procesgegevens | Nee |

De bestaande bestanden in `portefeuille_viewer/config` zijn behouden als bron voor
eenmalige initialisatie en compatibiliteit met oude losse hulpmiddelen. De normale
app gebruikt na profielkeuze de bestanden hierboven. Bestaande profielbestanden
worden niet opnieuw uit de oude INIs gevuld. Wijzig de gedeelde instellingen voor
de normale app voortaan in `gebruikersdata/gedeeld/settings_shared.ini` of via Settings.

Alle drie de profielen hebben bij de eerste omzetting de bestaande voorkeuren als
startpunt gekregen. Daarna worden ze onafhankelijk opgeslagen. Computerinstellingen
en runtimebestanden worden niet via Git naar een andere computer overgenomen.

## Bescherming

De app verkrijgt vóór het laden van portefeuilledata een Windows-mutex op basis
van het canonieke userdatabasepad. Een tweede instantie voor hetzelfde bestand
wordt geweigerd, ook vanuit een andere appmap die deze bescherming ondersteunt.
Verschillende userdatabases kunnen tegelijk geopend worden. Windows geeft de lock
vrij na afsluiten of een procescrash; achtergebleven `session.json`-bestanden zijn
geen locks en blokkeren geen herstart.

Een venster blijft aan zijn startprofiel gebonden. De databaseselector in Orders is
daarom uitgeschakeld; het profiel staat ook in de venstertitel. Gebruik een ander
venster voor een ander profiel. Profielkeuze opent geen Access-database en voert
geen migraties uit. Het actieve databasepad kan niet via Settings worden gewijzigd
zolang dit profiel geopend is.

Voorkeuren worden alleen bij wijzigingen opgeslagen, met een tijdelijke file en
vervanging van het doelbestand. Gedeelde INIs worden onder een Windows-mutex per
bestand bijgewerkt; alleen gewijzigde sleutels worden samengevoegd. Zo kan een
verouderd venster geen ongewijzigde gedeelde instellingen terugschrijven.

## Gedeelde taken en koersen

Alle profielen gebruiken samen een koersdienst op deze computer. De eerste instantie
start die automatisch; volgende instanties sluiten aan. De dienst blijft draaien als
het eerste venster sluit en stopt na circa 15 seconden zonder aangesloten clients.
Een gecrashte client wordt na circa 10 seconden verwijderd. Een gecrashte dienst wordt
opnieuw gestart door een overgebleven client; die meldt zijn instrumenten opnieuw aan.
Het budget en de weigeringstellers op Koersabonnementen gelden voor alle profielen samen.
Achtergrondaanvragen reserveren tijdelijk ruimte binnen hetzelfde budget.

De centrale runtime staat onder
`C:\python_coding\portefeuille_viewer\.portefeuille_runtime\<computer-id>`.
Daar staan lokale locks, het verbindingsmanifest en de log van de koersdienst.
Dit pad ligt naast de versiemappen zodat compatibele versies dezelfde dienst vinden;
het is geen AppData- of OneDrive-map. Profielvoorkeuren blijven in versie 1.5.
`PV_RUNTIME_ROOT` kan voor tests of een andere installatie een gezamenlijke lokale
runtimemap aanwijzen. Verplaats of wis actieve lockbestanden niet.

STOCKDATA-writes gebruiken een mutex per database. De app maakt bij de eerste
schrijfactie een kleine tabel `pv_shared_versions` voor gecommitte revisies.
Andere instanties controleren iedere twee seconden een klein lokaal wijzigingssignaal
en lezen bij een wijziging de gecommitte revisies. Zonder wijzigingen wordt Access
overgeslagen; iedere minuut blijft er een databasecontrole als vangnet. Zo leidt
een crash tussen commit en signalering hoogstens tot vertraagde verversing. Een mislukte verversing wordt opnieuw geprobeerd. Assets en
optiereferenties worden bij opslaan gecontroleerd tegen de eerder geladen rij;
een verouderde wijziging wordt geweigerd met het verzoek te herladen.

Historie-, volatiliteit-, beta-, dividend- en ketenupdates worden gecoördineerd.
Een dubbele aanvraag wordt overgeslagen of met een melding geweigerd. Werkprocessen
van een app worden via een Windows Job Object beëindigd als hun eigenaar crasht.
De koersdienst heeft een eigen levensduur, onafhankelijk van dat eerste venster.

## Grenzen en ingebruikname

Sluit alle bestaande vensters voordat u deze code voor het eerst gebruikt. Start
vervolgens de profielen met de opdrachten hierboven. Oudere code die de beveiliging
niet gebruikt kan nog buiten deze afspraken schrijven of eigen abonnementen openen.

De coördinatie geldt op dezelfde computer, voor dezelfde STOCKDATA-database en
TWS-host/poort. Andere handelsprogramma's en handelingen in Access gebruiken deze
locks en revisies niet. De opgegeven capaciteit blijft afhankelijk van de werkelijke
IBKR-limiet en eventueel elders gebruikte koerslijnen. Desktop/laptop-overdracht via
OneDrive vereist dat de vorige computer afgesloten is en synchronisatie voltooid is.
Een wijziging van het STOCKDATA-pad wordt voor een draaiend profiel pas na herstart
actief, zodat locks en koersdienst aan dezelfde database gebonden blijven.

Zie ook `development_notes_todo/multi_instance_hardening_1.5.md` voor de testresultaten
en de resterende controle met echte TWS-koersen.
