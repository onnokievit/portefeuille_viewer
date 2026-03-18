import sys  
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from PySide6.QtCore import QTimer, qInstallMessageHandler
import inspect
from portefeuille_viewer.signals import signals

# Importeer hoofdvenster en benodigde modules
from portefeuille_viewer.ui_logica.main_window_logica import MainWindow
from portefeuille_viewer.config import get_settings
from portefeuille_viewer.data import repository
from portefeuille_viewer.services.price_feed import PriceFeedService
from portefeuille_viewer.services.historical_price_update_runner import HistoricalPriceUpdateRunner
from portefeuille_viewer.services.historical_price_update_runner import STOCKDATA_DB_PATH
from portefeuille_viewer.services.state_engine_runner import StateEngineRunner
from portefeuille_viewer.services.option_timevalue_service import OptionTimevalueService
from portefeuille_viewer.domain.portfolio_engine import PortfolioEngine
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.data.live_aggregator_aandelen import LiveAggregatorAandelen
from portefeuille_viewer.data.live_aggregator_opties import LiveAggregatorOpties
from portefeuille_viewer.data.live_aggregator_asset_prices import start_live_price_updater
from portefeuille_viewer.data.test_order_repository import flush_dirty_test_orders_to_db, load_test_orders_cache_from_db

# from portefeuille_viewer.data import live_aggregator_asset_rollup_data
import time

# Qt warning filter: onderdruk specifieke QSortFilterProxyModel warning
def qt_message_handler(mode, context, message):
    if "QSortFilterProxyModel: index from wrong model passed to mapToSource" in message:
        return
    print(message)

qInstallMessageHandler(qt_message_handler)

# Forceer Python om deze map als eerste te gebruiken
#sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(inspect.getfile(inspect.currentframe())))

print("✅ Repository geladen uit:", repository.__file__)


# Persistent aggregators for the whole app
live_aggregator_aandelen = LiveAggregatorAandelen()
live_aggregator_opties = LiveAggregatorOpties()

def refresh_everything():
    start_time = time.time()
    flush_dirty_test_orders_to_db()
    load_test_orders_cache_from_db()
    repository.load_alle_transacties()
    repository.load_aandelen_from_tx()
    repository.load_open_opties_from_tx()
    repository.load_gesloten_opties_from_tx()
    repository.load_gesloten_opties_no_broker()
    repository.load_open_sprinters_from_tx()
    repository.load_gesloten_sprinters_from_tx()
    repository.load_asset_rollup_data()
    repository.load_sprinter_referentie_data()
    repository.load_dividend_data()
    repository.load_historical_close_snapshot()
    repository.load_per_dag_asset_result_v2_snapshot()
    repository.load_per_dag_asset_result()
    repository.load_optie_referentie_data()
    repository.build_repository_active_asset_rollup_data()
    live_aggregator_aandelen.process_live_update()
    live_aggregator_opties.process_live_update()
    repository.portfolio_value_asset_rollup_opties_put()
    repository.portfolio_value_asset_rollup_aandelen()
    repository.portfolio_value_asset_rollup_sprinters()
    repository.portfolio_value_asset_rollup_combined()  
    end_time = time.time()
    elapsed_time = end_time - start_time
    print(SNAPSHOT_STORE.snapshot_store_summary())
    print(f"Datasets geladen in {elapsed_time:.2f} seconden.")


def refresh_transaction_derived_snapshots(payload: dict | None = None):
    start_time = time.time()
    try:
        # Zorg dat afgeleide snapshots altijd vanaf de gecommitte DB-waarheid worden opgebouwd.
        # Dit voorkomt race-gedrag waarbij ordersCommitted eerder komt dan lokale snapshot-sync in de UI.
        repository.load_alle_transacties()
        repository.load_aandelen_from_tx()
        repository.load_open_opties_from_tx()
        repository.load_gesloten_opties_from_tx()
        repository.load_gesloten_opties_no_broker()
        repository.load_open_sprinters_from_tx()
        repository.load_gesloten_sprinters_from_tx()
        repository.load_historical_close_snapshot()
        repository.load_per_dag_asset_result_v2_snapshot()
        repository.load_per_dag_asset_result()
        repository.build_repository_active_asset_rollup_data()
        live_aggregator_aandelen.process_live_update()
        live_aggregator_opties.process_live_update()
        repository.portfolio_value_asset_rollup_opties_put()
        repository.portfolio_value_asset_rollup_aandelen()
        repository.portfolio_value_asset_rollup_sprinters()
        repository.portfolio_value_asset_rollup_combined()
    except Exception as exc:
        print(f"[snapshot-refresh] failed: {exc}")
        raise
    elapsed_time = time.time() - start_time
    reason = (payload or {}).get("reason", "unknown")
    print(f"[snapshot-refresh] transaction-derived snapshots refreshed in {elapsed_time:.2f}s ({reason})")
    


def main():
    refresh_everything()
    state_engine_runner = StateEngineRunner(fallback_refresh=refresh_everything)
    SNAPSHOT_STORE.state_engine_runner = state_engine_runner
    historical_price_update_runner = HistoricalPriceUpdateRunner()
    
    # Koppel signalen aan orchestrator:
    # 1) request -> alleen state-engine starten
    # 2) finished(ok) -> daarna afgeleide snapshots verversen
    signals.stateRebuildRequested.connect(state_engine_runner.handle_rebuild_requested)
    signals.priceUpdateFinished.connect(state_engine_runner.handle_price_update_finished)
    signals.databaseChanged.connect(lambda db_name: refresh_everything())
    signals.databaseChanged.connect(state_engine_runner.handle_database_changed)
    # Debounce snapshot refreshes: bij een wave van price_catchup jobs
    # willen we niet na elke asset-run opnieuw alle snapshots/aggregators herladen.
    pending_refresh_payload: dict = {"reason": "unknown"}
    refresh_timer = QTimer()
    refresh_timer.setSingleShot(True)
    refresh_timer.setInterval(1200)
    orders_refresh_timer = QTimer()
    orders_refresh_timer.setSingleShot(True)
    orders_refresh_timer.setInterval(250)

    def _run_debounced_refresh():
        refresh_transaction_derived_snapshots(dict(pending_refresh_payload))

    def _run_orders_refresh():
        refresh_transaction_derived_snapshots({"reason": "orders_committed"})

    def _schedule_orders_refresh():
        # Herstel oud gedrag: na order-write direct transaction-derived snapshots verversen.
        # Debounced om korte bursts (bijv. gekoppelde writes) samen te nemen.
        orders_refresh_timer.start()

    def _schedule_snapshot_refresh(payload):
        if (payload or {}).get("status") != "ok":
            return
        # Refresh pas na aggregate-stap om dubbele UI-herlaadgolven te voorkomen.
        # Basis-engines (aandelen/opties/sprinters) worden direct gevolgd door
        # asset_result_v2; tussentijds refreshen is overbodig en kost UI-performance.
        engine_class = str((payload or {}).get("engine_class") or "").strip().lower()
        if engine_class != "asset_result_v2":
            return
        pending_refresh_payload.clear()
        pending_refresh_payload.update(payload or {})
        # Restart timer so bursts collapse into one refresh.
        refresh_timer.start()

    refresh_timer.timeout.connect(_run_debounced_refresh)
    orders_refresh_timer.timeout.connect(_run_orders_refresh)
    signals.ordersCommitted.connect(_schedule_orders_refresh)
    signals.stateRebuildFinished.connect(_schedule_snapshot_refresh)
    signals.stateRebuildFinished.connect(
        lambda payload: print(f"[state-engine] rebuild finished: {payload}")
    )
    signals.stateRebuildFailed.connect(
        lambda message: print(f"[state-engine] rebuild failed: {message}")
    )
    signals.priceUpdateStarted.connect(
        lambda payload: print(f"[price-update] started: {payload}")
    )
    signals.priceUpdateFinished.connect(
        lambda payload: print(f"[price-update] finished: {payload.get('status')} ({payload.get('fetch_start_date', 'n/a')} -> today)")
    )
    signals.priceUpdateFailed.connect(
        lambda message: print(f"[price-update] failed: {message}")
    )
    import faulthandler
    faulthandler.enable()
    app = QApplication(sys.argv)
    font = QFont()
    font.setPointSize(9)
    try:
        font.setWeight(QFont.Weight.DemiBold)
    except AttributeError:
        font.setWeight(QFont.DemiBold)
    app.setFont(font)
    settings = get_settings()
    price_feed = PriceFeedService(
        settings.get_ib_host(),
        settings.get_ib_port(),
        settings.get_ib_client_id()
    )
    stop_event, thread = start_live_price_updater(price_feed)
    portfolio_engine = PortfolioEngine(price_feed)
    option_timevalue_service = OptionTimevalueService(price_feed, STOCKDATA_DB_PATH)
    w = MainWindow(portfolio_engine, price_feed, live_price_updater_stop_event=stop_event)
    w.option_timevalue_service = option_timevalue_service
    w.show()
    # Start price-update pas nadat UI volledig staat en event-loop idle is.
    QTimer.singleShot(5000, historical_price_update_runner.request_startup_update)
    if price_feed.is_ready():
        portfolio_engine.start_subscriptions()
    else:
        price_feed._feed.ready.connect(lambda: portfolio_engine.start_subscriptions())
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
