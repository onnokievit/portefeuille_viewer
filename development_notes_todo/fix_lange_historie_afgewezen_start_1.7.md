# Lange historie: blijvende bezig-status na geweigerde start

## Oorzaak

De Asset Rollup Data-tab zette de knoppen en het uitvoervenster al op bezig
voordat de runner de gedeelde onderhoudslock had verkregen. Bij een lopende
volatiliteits- of andere onderhoudstaak weigerde claim_task de aanvraag terecht.
Er startte dan geen QProcess en er volgde ook geen finished/failed-signaal voor
die geweigerde aanvraag. De UI bleef daardoor ten onrechte op bezig staan,
ook nadat de andere taak klaar was. Dit was geen achtergebleven eigen lock van
de geweigerde aanvraag en geen aangetoond XLY-contractprobleem.

## Correctie

- Beide handmatige runners hebben een expliciet boolean startresultaat.
- Een lege asset of ontbrekend script wordt gecontroleerd vóór lock-acquisitie.
- claim_task legt een begrijpelijke afwijzingsreden vast en spreekt niet meer
  uitsluitend over een andere appinstantie: dezelfde app kan ook een taak uitvoeren.
- Beide knoppen controleren het startresultaat. Bij afwijzing worden de runner-
  verwijzing en de bezig-status opgeruimd en worden de knoppen meteen bruikbaar.
- Het uitvoervenster toont dat de aanvraag niet gestart is. De aanvraag wordt
  niet automatisch in een wachtrij gezet; na afloop van de andere taak kan de
  gebruiker opnieuw klikken, zonder de app te herstarten.
- Een geweigerde aanvraag geeft nooit de lock van de andere taak vrij.
- Procesinitialisatiefouten lopen via het bestaande failed-signaal, dat ook de
  eigen onderhoudslease vrijgeeft.
- Een synchrone fout bij het aanvragen van de historie-/indicatorverversing zet
  refresh_pending terug en meldt failed. Een late succescallback na een fout
  wordt genegeerd.

De gedeelde onderhoudslock blijft gedurende een echte pipeline actief. Er is
geen onveilige vrijgave of parallel gebruik van de tijdelijke tabellen toegevoegd.

## Verificatie

6 nieuwe tests in `devtools/test_long_history_start.py` slagen: OHLCV- en
volatiliteitsaanvragen weigeren, later opnieuw starten zonder herstart,
procesinitialisatiefout, lege asset, verversingsinitialisatiefout en late callback.
De tests gebruiken een werkende Qt-interface en gesimuleerde processen/locks;
ze starten geen IBKR-download en schrijven niet naar de echte database.

Daarnaast slagen de 5 bestaande tests voor de historie-/indicatorrunner.
Voor ingebruikname de app eenmalig herstarten om de gewijzigde code te laden.
