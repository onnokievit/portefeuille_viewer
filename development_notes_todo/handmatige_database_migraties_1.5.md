# Databaseonderhoud buiten de appstart

De normale appstart voert geen `DbMigrationService` meer uit en loopt niet langer
voor migraties alle ingestelde userdatabases langs. De overige laad- en
initialisatiecode is hiermee niet gewijzigd.

De bestaande migratievoorziening blijft als handmatig hulpmiddel beschikbaar:

```powershell
python devtools/migrate_user_database.py --db "C:\pad\userdatabase.accdb"
```

Dit commando voert de bestaande migratie alleen op het opgegeven bestand uit.
Het is niet nodig om het bij normaal gebruik te starten. De bestaande bootstrap
is behouden; toekomstige inhoudelijke schemawijzigingen krijgen een afzonderlijk,
gericht updatescript. Deze wijziging voert zelf geen databasemigraties uit.
