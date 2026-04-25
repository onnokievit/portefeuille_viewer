# Cash Management Plan

## Doel

Er moeten twee nieuwe functionele gebieden bijkomen in de user database:

1. cash management entries
   stortingen, opnames en later ook valuta-conversies
2. dagelijkse eindstanden per account
   handmatig ingevoerd of later deels via broker API opgehaald

Deze data moet later gebruikt worden voor:

- handmatige bijwerking in de app
- controle op accountontwikkeling
- charting en analyse
- performance-analyse gecorrigeerd voor cashflows


## Kernbeslissing: geen brede Excel-structuur in Access

De huidige Excel-opzet gebruikt per broker een eigen kolom. Dat is voor Access en app-logica niet handig.

De opslag in de database moet genormaliseerd worden als records per datum/broker/account.

Dus niet:

- datum | IBKR | DEGIRO | SAXO

Maar wel:

- datum | broker | account | bedrag

Voordelen:

- onbeperkt brokers toevoegen zonder schemawijziging
- eenvoudiger filters, queries en grafieken
- eenvoudiger onderhoud in de UI
- eenvoudiger import vanuit Excel
- minder speciale code per broker


## Tabel 1: cash_management_entries

Doel:

- cash-in en cash-out opslaan
- later ook FX-conversies ondersteunen

Voorgestelde kolommen:

- `id`
- `datum`
- `broker`
- `account_name`
- `entry_type`
- `amount`
- `currency`
- `fx_rate`
- `transfer_group`
- `comment`
- `created_at`
- `updated_at`

### Betekenis per veld

- `datum`
  boekingsdatum of verwerkingsdatum
- `broker`
  brokernaam, bijvoorbeeld `IBKR`, `DEGIRO`
- `account_name`
  rekeningnaam of account-id
- `entry_type`
  type cashbeweging
- `amount`
  positief of negatief bedrag
- `currency`
  valuta van het bedrag
- `fx_rate`
  optioneel, voor handmatige vastlegging van wisselkoers
- `transfer_group`
  optioneel, om gekoppelde regels bij elkaar te houden
- `comment`
  vrije toelichting

### Voorgestelde entry types

- `deposit`
- `withdrawal`
- `fx_conversion_in`
- `fx_conversion_out`

Later eventueel uitbreidbaar met:

- `interest`
- `fee_manual`
- `tax_manual`
- `internal_transfer`


## FX-conversies

Valutaconversies moeten niet als 1 regel worden opgeslagen, maar als 2 gekoppelde regels.

Voorbeeld EUR naar USD:

1. `fx_conversion_out`, `-1000`, `EUR`
2. `fx_conversion_in`, `1085`, `USD`

Beide regels krijgen dezelfde `transfer_group`.

Waarom dit beter is:

- sluit aan op echte cash-bewegingen
- totalen per valuta blijven correct
- auditing en controle worden eenvoudiger
- charting per valuta of per account blijft mogelijk

`fx_rate` wordt optioneel opgeslagen voor traceerbaarheid, maar hoeft in eerste instantie niet overal verplicht te zijn.


## Tabel 2: account_daily_balances

Doel:

- dagelijkse eindstand per brokeraccount vastleggen
- handmatige invoer ondersteunen
- later deels API-import ondersteunen

Voorgestelde kolommen:

- `id`
- `datum`
- `broker`
- `account_name`
- `ending_balance`
- `currency`
- `source`
- `comment`
- `created_at`
- `updated_at`

### Betekenis per veld

- `datum`
  datum van de eindstand
- `broker`
  brokernaam
- `account_name`
  rekeningnaam of account-id
- `ending_balance`
  totale eindstand van die rekening op die datum
- `currency`
  valuta van de eindstand
- `source`
  bijvoorbeeld `manual` of `api`
- `comment`
  vrije toelichting


## Belangrijke ontwerpkeuze: broker en account scheiden

Alleen `broker` opslaan is niet genoeg zodra een broker meerdere rekeningen heeft.

Daarom moet naast `broker` ook `account_name` of `account_id` worden opgeslagen.

Anders ontstaan later problemen bij:

- meerdere IBKR accounts
- meerdere cash-rekeningen per broker
- koppeling aan API-import
- charting per rekening


## Database-locatie

Deze twee tabellen horen in de user database.

Reden:

- het zijn gebruikersspecifieke administratieve gegevens
- deze data is geen marktdata
- deze data hoort bij persoonlijke cashflows en persoonlijke brokerstanden


## Gewenste UI-opzet

Er moet uiteindelijk een nieuwe chart-/beheerpagina komen in de app.

Voorgesteld patroon:

1. nieuwe tab voor cash/account charts
2. knop `Bijwerken`
3. knop opent een los popup-venster, vergelijkbaar met andere editorvensters in de app
4. popup bevat twee beheersecties:
   - cash management entries
   - account daily balances

Per sectie:

- tabel met bestaande records
- mogelijkheid om record te selecteren
- knop nieuw
- knop wijzigen
- knop verwijderen
- invoervelden voor datum, broker, account, bedrag/stand, valuta, comment


## Mogelijke latere uitbreidingen

### API-import accountstanden

Voor sommige brokers kunnen eindstanden mogelijk automatisch worden opgehaald.

Waarschijnlijk scenario:

- 2 brokers deels via API
- DEGIRO waarschijnlijk handmatig

Daarom moet de opslag generiek zijn:

- handmatige invoer en API-import schrijven naar dezelfde tabel
- verschil wordt aangegeven via `source`

### Cashflow- en performance-analyse

Met deze twee tabellen kunnen later onder meer de volgende analyses gebouwd worden:

- netto stortingen per maand
- netto opnames per maand
- totale eindstand per broker
- totale eindstand over alle brokers
- ontwikkeling cash-in versus portefeuilleontwikkeling
- performance gecorrigeerd voor stortingen en opnames
- controle tussen broker-eindstand en portefeuillewaarde


## Voorgestelde bouwvolgorde

### Fase 1: database

- tabellen toevoegen aan user-db
- indices toevoegen op datum, broker, account

### Fase 2: data layer

- repositories voor lezen/schrijven
- validatie van verplichte velden
- helpers voor upsert/update/delete

### Fase 3: handmatige editor

- popup-venster bouwen
- records tonen in tabellen
- records toevoegen/wijzigen/verwijderen

### Fase 4: chart-tab

- nieuwe tab maken voor cash/account-analyse
- knop `Bijwerken`
- tabellen en charts laden vanuit de database

### Fase 5: API-import

- broker-specifieke account balance import toevoegen
- wegschrijven naar `account_daily_balances`
- bestaande handmatige workflow intact houden


## Samenvatting ontwerpkeuze

De juiste richting is:

- geen brede broker-per-kolom tabellen
- wel genormaliseerde records per datum/broker/account
- cash management en daily balances los van elkaar opslaan
- FX-conversies modelleren als twee gekoppelde cashregels
- UI bouwen als aparte beheerpopup vanuit een nieuwe chart-tab

Dit model is flexibel genoeg voor:

- extra brokers
- extra accounts
- handmatige invoer
- latere API-import
- latere charting en performance-analyse
