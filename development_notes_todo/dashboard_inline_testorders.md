# Direct bewerkbare testorders in Asset Dashboard

De testordertabel is direct bewerkbaar. Toevoegen maakt via de oorspronkelijke functie een lege regel; Verwijderen verwijdert de geselecteerde regel via de oorspronkelijke handler. Incl is een checkbox per regel. Alleen opgenomen orders tellen mee wanneer Testorders toepassen aan staat.

De webinvoer gebruikt stabiele scenario_order_uid-sleutels en de bestaande Qt-delegates voor numerieke invoer, datumaanvulling en keuzelijsten. Opslag, scenarioselectie en payoff lopen door de bestaande Single Asset Analyse-handlers. Commentaar behoudt het gedeelde inline commentaar- en kleurenpad. Er is geen tweede database-schrijfroute.

Enter of veld verlaten bewaart de invoer; Escape herstelt de laatst bewaarde waarde. Foutieve invoer blijft zichtbaar gemarkeerd. Afsluiten wacht ook op testorderinvoer. De tabel wordt niet bij iedere update opnieuw opgebouwd.

Validatie: 76 gerichte Python-tests, JavaScript-layout- en assencontroles en de QtWebEngine desktop/laptop-smoketest met nepdata. Productiedatabases zijn voor deze tests niet aangepast.
