import sys
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont

# Importeer hoofdvenster en benodigde modules
from portefeuille_viewer.ui_logica.main_window_logica import MainWindow
from portefeuille_viewer.config import get_settings
from portefeuille_viewer.data import repository
from portefeuille_viewer.services.price_feed import PriceFeedService
from portefeuille_viewer.domain.portfolio_engine import PortfolioEngine
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.data.live_aggregator_aandelen import LiveAggregatorAandelen
from portefeuille_viewer.data.live_aggregator_opties import LiveAggregatorOpties
from portefeuille_viewer.data.live_aggregator_asset_prices import start_live_price_updater
import time

# Forceer Python om deze map als eerste te gebruiken
sys.path.insert(0, os.path.dirname(__file__))

print("✅ Repository geladen uit:", repository.__file__)

def load_datasets():
    start_time = time.time()
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
    repository.load_optie_referentie_data()
    live_aggregator_aandelen = LiveAggregatorAandelen()
    live_aggregator_opties = LiveAggregatorOpties()
    live_aggregator_aandelen.process_live_update
    live_aggregator_opties.process_live_update
    end_time = time.time()
    elapsed_time = end_time - start_time
    print(f"Datasets geladen in {elapsed_time:.2f} seconden.")
    print(SNAPSHOT_STORE.snapshot_store_summary())

def main():
    app = QApplication(sys.argv)
    font = QFont()
    font.setPointSize(9)
    try:
        font.setWeight(QFont.Weight.DemiBold)
    except AttributeError:
        font.setWeight(QFont.DemiBold)
    app.setFont(font)
    load_datasets()
    settings = get_settings()
    price_feed = PriceFeedService(
        settings.get_ib_host(),
        settings.get_ib_port(),
        settings.get_ib_client_id()
    )
    
    stop_event, thread = start_live_price_updater(price_feed)
    portfolio_engine = PortfolioEngine(price_feed)
    w = MainWindow(portfolio_engine,price_feed, live_price_updater_stop_event=stop_event) 
    
    
    w.show()
    if price_feed.is_ready():
        portfolio_engine.start_subscriptions()
    else:
        price_feed._feed.ready.connect(lambda: portfolio_engine.start_subscriptions())
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
