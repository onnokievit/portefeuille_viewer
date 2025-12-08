1) 
aantallen aandelen / aantallen sprinters / aantallen opties put overzicht maken, 
om exposure te berekenen (portefeuille waarde)

1.1 obv van synthetische delta 1 voor put opties
1.2 later, delta's ophalen uit IBKR, en een delta overzicht maken


overzichten, verdeling share van assets in totale portfolio, % overzicht
%overzichten met delta 1, delta opgehaald, na opties. 

change tov gistereren toevoegen

1.3 uitbreiden single assset analyse met % share, absoluut share in portefeuille
    uitgeschreven in aantal puts itm, aantal puts otm, aantal aandelen sprinters etc
    voor opties, na opties, 

2) 
currency in historisch resultaat chart op single asset_analyse toepassen

3) 
een systeem opzetten om proeforders in te voeren, 
en deze aan/uit te zetten in de database / in de analyses. vooral in de single asset analyse
voor opties
voor sprinters
voor aandelen

4) 
een tradelog systeem op uniek_id, voor opties. bij single_asset of opties_open, 
een 2e tabel tonen/ editable velden tonen, 
waar comments geplaatst kunnen worden wat te doen met een bepaald uniek_id voor de volgend optie expiratie



5) 
optie live prijzen aan de subscriber toevoegen, 
price_feed aanpassen tussen het switchen van verschillende lijsten met subscriptions

6) 
Index ophalen AEX / DAX / etc uit IBKR en gaan implementeren in de app. 
subscription in price_feed implementeren

7) 
overzichten voor portfolio analyse, overzichten obv sector, value_grow, regio
overzicht resultaat, en overzicht portfolio share

8) 
dividend overzicht toevoegen aan single asset analys
NEXT dividend implementeren in db (tabel), app (pagina om dit bij te houden, misschien automatiseren?), 
single asset overview toevoegen, met kleur codering oranje / rood

9) 
singe asset overview uitbreiden met per_dag_asset_result change t.o.v. per_dag_asset_result vorige dag? 

10) 
hist stock check en per_dag_asset_result integreren? of aanroepen vanuit app? in achtergrond? 

11) 
zoekveld zoals in orders, ook in aandelen implementeren




Optimelisatie voorgesteld door CODEX
Optimalisatie-ideeën

Live aggregators doen nu row-wise Python werk. In data/live_aggregator_opties.py en data/live_aggregator_aandelen.py wordt pl.struct(...).map_elements gebruikt om prijzen op te halen; dat loopt per rij door Python en remt CPU/GIL. Vervang dit door een Polars-join met een vooraf gebouwde last_prices DataFrame (pl.DataFrame({"ib_symbol":..., "ib_currency":..., "price":...})) en neem daarna pl.col("price").fill_null(0) → pure Rust-code, veel sneller en vloeiender UI updates. Idem voor fallback naar SNAPSHOT_STORE.live_prices: maak er één Polars frame van en join.

PortfolioEngine stuurt veel signalen: refresh_everything() in portefeuille_viewer_0_11.py laadt alle datasets en roept zowel LiveAggregator* als repository-aggregates aan, en ordersCommitted triggert én refresh_everything én opnieuw de aggregators via signals.ordersCommitted in elke aggregator. Dit is dubbel werk. Laat ordersCommitted slechts één pad triggeren (bijv. alleen refresh_everything) of laat aggregators deze signal niet opnieuw verwerken.

Batch-signalen verder aanscherpen: Signals.snapshotUpdated gaat voor elke safe_write af; UI slots laden soms volledige tabellen opnieuw. Gebruik per-tab snapshot keys en return vroeg als key niet relevant (bijv. in ui_logica/single_asset_analyse_tab_logica.py alleen reageren op aggregator_snapshot_load_open_opties_from_tx_live). Of voeg een throttling timer zoals in PortfolioEngine.dataUpdated voor UI-tabellen.

Tabelupdates in ui_logica/single_asset_analyse_tab_logica.py zijn zwaar: update_opties_open_table bouwt telkens nieuwe modellen, sorteert en zet widths na elke reset. Cache het gefilterde DF en hergebruik het model; pas alleen sort/filter toe via QSortFilterProxyModel zonder het model te vervangen. Dit voorkomt flicker en CPU spikes.

Filters zijn breed: _filter_dataframe zoekt over alle kolommen met .str.contains en meerdere date-format tries. Beperk kolommen (bv. alleen zichtbare kolommen), compileer regexp vooraf en vermijd herhaalde date-strptime; sla geparste datums in snapshot op zodat filtering geen strptime per call hoeft te doen.

Historische data laden: SingleAssetAnalyseLogic.load_asset_history converteert de volledige kolom datum naar datetime bij elke call. Doe deze conversie één keer bij het vullen van SNAPSHOT_STORE.repository_per_dag_asset_result en houd een “is_parsed” vlag, of sla een tweede kolom datum_dt op. Dit vermindert wachttijd bij het verschuiven van de datumrange slider.

Geheugen/CPU: loop overal de engine.compact_float64 over snapshots die live in UI komen (prijzen, posities) om Float32 te gebruiken; dit maakt Polars-kopieën kleiner en snellere groupbys mogelijk.

Live update frequentie: PortfolioEngine._update_timer staat op 10s; _data_update_timer ook. Als CPU spikes optreden, houd 10s maar filter updates (alleen publish bij echte koersverandering). Als de UI “stottert”, verlaag interval of gebruik een “coalesce identical data” check in de aggregators (vergelijk hash/rowcount met vorige snapshot en emit alleen bij verschil).

Payoff-plot: update_payoff_table berekent matrices elke asset-klik en herbouwt alle QTableWidgetItems. Als de koersen/asset niet wijzigen, sla de laatste matrix per asset op en hergebruik bij kleine veranderingen (bv. alleen stepSize). Dit scheelt renderwerk.

Aanpak om te verbeteren

Pas de prijs-joins aan in data/live_aggregator_aandelen.py en data/live_aggregator_opties.py zodat alles via Polars-joins loopt.
Ontdubbel signal-flow: kies één refresh-pad voor ordersCommitted en filter snapshotUpdated in UI-slots.
Parse datums/float32 éénmalig bij snapshot-build en hergebruik.
Optimaliseer tabelupdates (model hergebruik + kolomrestricties in filters).
Uit te voeren tests: start app, wissel asset/filter in Single Asset tab, observeer CPU; plaats debug-log op aantal snapshotUpdated emits per minuut om overbodige triggers te vinden. Natural next steps: 1) Implement join-based prijsopbouw in de aggregators. 2) Beperk signal-handlers per tab/snapshot en voorkom dubbele refresh. 3) Preparse datum/float32 in snapshots.