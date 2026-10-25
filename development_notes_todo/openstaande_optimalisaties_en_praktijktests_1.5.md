# Openstaande optimalisaties en praktijktests — Portefeuille Viewer 1.5

Datum: 25 oktober 2026

Dit document legt het resterende werk vast om later op te pakken. De onderstaande
verbeteringen zijn hiermee niet uitgevoerd.

## Huidige uitgangssituatie

Historische assetindicatoren gebruiken een gedeelde basis met een aparte
optieaanvulling per profiel. Dezelfde historische versie wordt niet opnieuw
opgeslagen wanneer een tweede profiel deze gebruikt. Historie laden en
indicatoren berekenen/opslagen verlopen via achtergrondpaden.

De eerste praktijkronde met Onno, Muriel en Quinten is positief: indicatoren
verschijnen bij de tweede en derde app direct. Ook met de afzonderlijke
state-engines actief zijn in deze ronde geen muisstotters gemeld. Dit bewijst
nog niet dat de eerder incidenteel optredende stottering volledig is opgelost.

## Openstaande verbeteringen

| Prioriteit | Onderwerp | Vervolgwerk |
| --- | --- | --- |
| 1 | Resterende UI-belasting | Overige zware callbacks en tabverversingen meten. Niet alle databaseacties en aggregators draaien buiten de UI-thread. Alleen aantoonbaar blokkerend werk gericht verplaatsen of verminderen. |
| 2 | Dagstartbelasting | Meten hoeveel de afzonderlijke state-engines belasten en welke vervolgverversingen zij veroorzaken. Iedere user houdt zijn eigen verwerking; onderzoeken of werk daarbinnen kan worden verminderd of beter gespreid. |
| 3 | Threadgebruik van databaseverbindingen | Expliciet bewaken dat een verbinding uitsluitend wordt gebruikt op de thread waarop zij is geopend. Verkeerd gebruik moet direct een duidelijke fout geven, in plaats van een moeilijk verklaarbare lock-time-out. |
| 4 | Dubbele en oude updatepaden | Per onderdeel inventariseren welke producers, listeners, timers en alternatieve engine-routes nog nodig zijn. Een deel is al verwijderd. Eerst uitleggen welke aanvullende routes kunnen vervallen en waarom; daarna pas opschonen. |
| 5 | Meetcode afronden | Na de praktijktests bepalen welke diagnostiek standaard actief blijft. Snapshotinvoer kopiëren en de overhead van `__getattribute__` blijven meetpunten, geen bewezen knelpunten. |
| 6 | Fallback-delta | De eerder besproken onlogische sprongen in de benadering corrigeren. Dit heeft op verzoek van de gebruiker een lagere prioriteit dan UI-belasting. |

## Praktijktests tijdens beursuren

- Controleer of eigen optiegegevens per profiel automatisch worden aangevuld
  zodra bruikbare koersen en Greeks beschikbaar komen. Controleer ook
  verschillende optieposities op dezelfde asset bij twee profielen.
- Controleer bij drie profielen de gedeelde koersdienst, het gezamenlijke
  abonnementenbudget en ontvangen aandelen- en optiekoersen.
- Sluit de eerst gestarte app en controleer of de overige profielen koersen
  blijven ontvangen en normaal blijven werken.
- Controleer herstel na verlies van de TWS-verbinding.
- Controleer verversing van gedeelde gegevens tussen instanties na een wijziging
  en na een gezamenlijke achtergrondupdate.
- Observeer langdurig gebruik en een dagstart met meerdere profielen. Als de
  muisstottering terugkomt, leg het tijdstip vast en vergelijk dit met de
  diagnostiek van de betrokken processen.
- De eerdere gelijktijdigheidsproeven verder aanvullen met gecontroleerde
  crash- en herstartscenario's, op aparte databasekopieën.

## Aanbevolen volgende stap

Begin met een gerichte meting van de resterende UI-belasting, inclusief een
dagstart. Vergelijk één profiel met meerdere profielen en onderscheid
opstartwerk, state-engine-verwerking en normaal gebruik. Bepaal op basis van
de meting welk onderdeel aantoonbaar tijd kost voordat verdere code wordt
verplaatst of verwijderd.

## Relevante eerdere notities

- [Timers en projecties](optimalisatie_timers_projecties_1.5.md)
- [UI-belasting meten](ui_belasting_meting_1.5.md)
- [Historie en indicatoren op de achtergrond](achtergrond_historie_indicatoren_1.5.md)
- [Historische indicatorbasis en profielaanvulling](indicator_basis_en_profielaanvulling_1.5.md)
- [Multi-instance hardening](multi_instance_hardening_1.5.md)
