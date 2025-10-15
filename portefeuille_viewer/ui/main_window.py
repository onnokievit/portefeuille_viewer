from PySide6.QtWidgets import QMainWindow, QTabWidget, QWidget
from PySide6.QtGui import QAction
from portefeuille_viewer.services.price_feed import PriceFeedService
from portefeuille_viewer.ui.orders_tab import OrdersTab

from portefeuille_viewer.ui.settings_tab import SettingsTab
from portefeuille_viewer.config import get_settings
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.ui.open_options_tab import OpenOptiesPolarsTab
# from portefeuille_viewer.ui.aandelen_tab import AandelenPolarsTab
from portefeuille_viewer.ui.aandelen_tab2 import AandelenTab2
import logging
import os
from datetime import datetime


APP_TITLE = "🧭 Portefeuille Viewer"

class MainWindow(QMainWindow):
    def __init__(self, portfolio_engine=None, price_feed=None):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1800, 950)
        
        # Setup logging
        self._setup_logging()

        # Get settings for IB configuration
        settings = get_settings()

        # Use provided services or create new ones for backward compatibility
        if price_feed is not None:
            self.feed_service = price_feed
            self.feed_service.setParent(self)  # Set parent for Qt lifecycle
        else:
            # Fallback: create own feed service (backward compatibility)
            self.feed_service = PriceFeedService(
                settings.get_ib_host(), 
                settings.get_ib_port(), 
                settings.get_ib_client_id(), 
                self
            )
        
        # Store portfolio engine reference
        self.portfolio_engine = portfolio_engine
        
        # Connect feed service signals with improved logging
        self.feed_service._feed.log.connect(self._log_message)
        self.feed_service._feed.ready.connect(lambda: self._log_message("IB-feed ready"))

        # Tabs
        self.tabs = QTabWidget()
        self.orders_tab = OrdersTab()

        
        # Pass portfolio_engine to OpenOptiesPolarsTab for live updates
        if self.portfolio_engine:
            self.open_opties_tab = OpenOptiesPolarsTab(portfolio_engine=self.portfolio_engine)
        else:
            self.open_opties_tab = OpenOptiesPolarsTab()
        
        #self.aandelen_tab = AandelenPolarsTab()
        
        # self.aandelen_tab = AandelenPolarsTab(self.feed_service)
        
        self.settings_tab = SettingsTab()
        
        



        self.tabs.addTab(self.orders_tab, "Orders")
        # self.tabs.addTab(self.aandelen_tab, "Open Aandelen (Polars)")
        
        # Pass the centralized portfolio_engine if available, otherwise let tab create its own
        if self.portfolio_engine:
            self.tabs.addTab(AandelenTab2(portfolio_engine=self.portfolio_engine), "Aandelen 2 (Agg)")
        else:
            self.tabs.addTab(AandelenTab2(pricefeed=self.feed_service), "Aandelen 2 (Agg)")
            

        self.tabs.addTab(self.open_opties_tab, "Open Opties (Polars)")
        #self.tabs.addTab(self.aandelen_tab, "Aandelen (Polars)")
        self.tabs.addTab(self.settings_tab, "Settings")
        

        self.setCentralWidget(self.tabs)

        # Koppeling: als Orders-tab iets opslaat of DB wijzigt → Live-tab herladen
        # self.orders_tab.ordersCommitted.connect(self.live_tab.reload_from_snapshots)
        # self.orders_tab.dbChanged.connect(self.live_tab.reload_from_db)
        
        # Connect settings changes (database config wijzigingen)
        self.settings_tab.configChanged.connect(self._on_database_config_changed)

        # Menu
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(self.close)
        self.menuBar().addAction(act_quit)
    
    def _on_database_config_changed(self):
        """Herlaad database configuratie na wijzigingen in settings."""
        from portefeuille_viewer.data import repository
        
        # Herlaad DB config
        repository.reload_db_config()
        
        # Update dropdown in orders tab
        current = self.orders_tab.db_choice.currentText()
        self.orders_tab.db_choice.blockSignals(True)  # Voorkom dubbele triggers
        self.orders_tab.db_choice.clear()
        self.orders_tab.db_choice.addItems(list(repository.DB_MAP.keys()))
        
        # Kies welke database te selecteren
        if current in repository.DB_MAP:
            # Oude selectie bestaat nog
            target_db = current
        else:
            # Oude selectie bestaat niet meer, kies default
            target_db = repository.DEFAULT_DB_NAME
        
        # Selecteer in dropdown
        self.orders_tab.db_choice.setCurrentText(target_db)
        self.orders_tab.db_choice.blockSignals(False)  # Re-enable signals
        
        # Wissel daadwerkelijk naar de database (via apply_database_by_name)
        self.orders_tab.apply_database_by_name(target_db)
        
        self.logger.info(f"✅ Database configuratie herladen: {len(repository.DB_MAP)} databases, actief: {target_db}")

    def closeEvent(self, event):
        try:
            if hasattr(self.live_tab, "_kpi_timer") and self.live_tab._kpi_timer is not None:
                self.live_tab._kpi_timer.stop()
        except Exception:
            pass

        try:
            if hasattr(self, "feed_service") and self.feed_service is not None:
                self.feed_service.shutdown()
        except Exception:
            pass

        super().closeEvent(event)
    
    def _setup_logging(self):
        """Setup file logging voor IB feed meldingen."""
        # Create logs directory if it doesn't exist
        log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")
        os.makedirs(log_dir, exist_ok=True)
        
        # Setup logger
        self.logger = logging.getLogger("PortfolioViewer")
        self.logger.setLevel(logging.INFO)
        
        # Clear existing handlers
        self.logger.handlers.clear()
        
        # File handler with timestamp
        today = datetime.now().strftime("%Y%m%d")
        log_file = os.path.join(log_dir, f"portfolio_viewer_{today}.log")
        
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        
        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        
        self.logger.addHandler(file_handler)
        
        # Log startup
        self.logger.info("=== Portfolio Viewer Started ===")
    
    def _log_message(self, message):
        """Log message to both file and statusbar with longer display time."""
        # Log to file
        self.logger.info(f"IB-Feed: {message}")
        
        # Show in statusbar for 10 seconds (was 2-3 seconds)
        self.statusBar().showMessage(f"📡 {message}", 10000)
        
        # Also print to console for immediate visibility
        print(f"[{datetime.now().strftime('%H:%M:%S')}] IB-Feed: {message}")