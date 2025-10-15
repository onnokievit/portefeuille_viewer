import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont

from portefeuille_viewer.ui.main_window import MainWindow
from portefeuille_viewer.config import get_settings
from portefeuille_viewer.data import repository
from portefeuille_viewer.services.price_feed import PriceFeedService
from portefeuille_viewer.domain.portfolio_engine import PortfolioEngine
import time 
import pandas as pd
from PySide6.QtWidgets import QApplication, QTableView
from portefeuille_viewer.ui.models import PandasTableModel
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE 
import sys, os
from portefeuille_viewer.domain import engine

# # --- Forceer Python om deze map als eerste te gebruiken ---
# # Hierdoor wordt altijd de versie in portefeuille_viewer_experiment geladen
# sys.path.insert(0, os.path.dirname(__file__))

# # Controleer welke repository daadwerkelijk geladen wordt:
# print("✅ Repository geladen uit:", repository.__file__)



def load_datasets():
    start_time = time.time()            
    repository.load_alle_transacties()
    repository.load_aandelen_from_tx()
    repository.load_open_opties_from_tx()
    repository.load_gesloten_opties_from_tx()
    # engine.print_snapshot_columns("snapshot_gesloten_opties", SNAPSHOT_STORE.snapshot_gesloten_opties) # Debug: kolommen controleren
    # engine.print_snapshot_head("snapshot_gesloten_opties", SNAPSHOT_STORE.snapshot_gesloten_opties) # Debug: eerste rijen controleren
    repository.load_gesloten_opties_no_broker()
    # engine.print_snapshot_columns("snapshot_gesloten_opties_no_broker", SNAPSHOT_STORE.snapshot_gesloten_opties_no_broker) # Debug: kolommen controleren
    # engine.print_snapshot_head("snapshot_gesloten_opties_no_broker", SNAPSHOT_STORE.snapshot_gesloten_opties_no_broker) # Debug: eerste rijen controleren
    repository.load_asset_rollup_data()

    end_time = time.time()
    elapsed_time = end_time - start_time
    print(f"Datasets geladen in {elapsed_time:.2f} seconden.")
    print(SNAPSHOT_STORE.snapshot_store_summary())


def main():
    app = QApplication(sys.argv)
    # Globale app-font
    font = QFont()
    font.setPointSize(9)
    # PySide6 compat: nieuwe enum (Weight) óf oudere attribuut (DemiBold)
    try:
        font.setWeight(QFont.Weight.DemiBold)
    except AttributeError:
        font.setWeight(QFont.DemiBold)
    app.setFont(font)
    
    # Load datasets first
    load_datasets()
    
    # Get settings for IB configuration
    settings = get_settings()
    
    # Initialize centralized services
    price_feed = PriceFeedService(
        settings.get_ib_host(), 
        settings.get_ib_port(), 
        settings.get_ib_client_id()
    )
    portfolio_engine = PortfolioEngine(price_feed)
    
    # Create main window with centralized services FIRST
    w = MainWindow(portfolio_engine, price_feed)
    w.show()
    
    # Start live price subscriptions only after IB is ready
    if price_feed.is_ready():
        portfolio_engine.start_subscriptions()
    else:
        # Wait for IB ready signal, then start subscriptions once
        price_feed._feed.ready.connect(lambda: portfolio_engine.start_subscriptions())
    
    # Note: LiveAggregator automatically initializes its data on instantiation

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
