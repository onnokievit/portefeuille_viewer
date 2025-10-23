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
from portefeuille_viewer.ui.option_explorer import OptionChainTab
import logging
import os
from datetime import datetime
from portefeuille_viewer.signals import signals
from portefeuille_viewer.ui.single_asset_analyse_tab import SingleAssetAnalyseTab
 


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
        
        # self.aandelen_tab = AandelenPolarsTab(self.feed_service)
        self.settings_tab = SettingsTab()
        self.option_chain_tab = OptionChainTab(feed_service=self.feed_service)

        # SprintersTab importeren en toevoegen
        try:
            from portefeuille_viewer.ui.sprinters_tab import SprintersTab
            if self.portfolio_engine:
                self.sprinters_tab = SprintersTab(portfolio_engine=self.portfolio_engine)
            else:
                self.sprinters_tab = SprintersTab()
        except Exception as e:
            print(f"SprintersTab kon niet worden geladen: {e}")
            self.sprinters_tab = QWidget()

        # Lightweight test tab: Repository Aggregator Tester
        try:
            from portefeuille_viewer.ui.repository_aggretator_tester_tab import RepositoryAggregatorTesterTab
            # Use the exact name requested: repository_aggretator_tester_tab
            self.repository_aggretator_tester_tab = RepositoryAggregatorTesterTab()
        except Exception as e:
            print(f"RepositoryAggregatorTesterTab kon niet worden geladen: {e}")
            self.repository_aggretator_tester_tab = QWidget()
        
        self.tabs.addTab(self.orders_tab, "Orders")
        if self.portfolio_engine:
            self.tabs.addTab(AandelenTab2(portfolio_engine=self.portfolio_engine), "Aandelen (Live)")
        else:
            self.tabs.addTab(AandelenTab2(pricefeed=self.feed_service), "Aandelen")
        self.tabs.addTab(SingleAssetAnalyseTab(), "Single Asset Analyse")
        self.tabs.addTab(self.open_opties_tab, "Open Opties (Live)")
        self.tabs.addTab(self.sprinters_tab, "Sprinters (Live)")
        

        # Option Chain Explorer Tab (NEW - MVP)
        
        self.tabs.addTab(self.option_chain_tab, "Option Chain Explorer")
        self.tabs.addTab(self.settings_tab, "Settings")
        self.tabs.addTab(self.repository_aggretator_tester_tab, "Repository Aggregator Tester")

        self.setCentralWidget(self.tabs)

        # Koppeling: als Orders-tab iets opslaat of DB wijzigt → Live-tab herladen
        # Als orders_tab de database wijzigt, herlaad relevante tabs
        # Connect only if the tabs expose a reload_data method
        try:
            if hasattr(self.sprinters_tab, 'reload_data'):
                self.orders_tab.dbChanged.connect(self.sprinters_tab.reload_data)
        except Exception:
            pass
        try:
            if hasattr(self.open_opties_tab, 'reload_data'):
                self.orders_tab.dbChanged.connect(self.open_opties_tab.reload_data)
        except Exception:
            pass
        try:
            # AandelenTab2 exposes reload_data
            if hasattr(self.tabs, 'widget') and hasattr(self, 'tabs'):
                # Connect directly to the instantiated AandelenTab2 we added earlier (second tab or by reference)
                # We created AandelenTab2 instance when adding tabs above; try to find it among tabs
                for i in range(self.tabs.count()):
                    w = self.tabs.widget(i)
                    if w is not None and w.__class__.__name__ == 'AandelenTab2' and hasattr(w, 'reload_data'):
                        self.orders_tab.dbChanged.connect(w.reload_data)
        except Exception:
            pass
        
        # After creating the tabs, add these connections:
        try:
            if hasattr(self.sprinters_tab, 'reload_data'):
                self.orders_tab.ordersCommitted.connect(self.sprinters_tab.reload_data)
        except Exception:
            pass
        try:
            if hasattr(self.open_opties_tab, 'reload_data'):
                self.orders_tab.ordersCommitted.connect(self.open_opties_tab.reload_data)
        except Exception:
            pass
        try:
            for i in range(self.tabs.count()):
                w = self.tabs.widget(i)
                if w is not None and w.__class__.__name__ == 'AandelenTab2' and hasattr(w, 'reload_data'):
                    self.orders_tab.ordersCommitted.connect(w.reload_data)
        except Exception:
            pass


        # Connect settings changes (database config wijzigingen)
        self.settings_tab.configChanged.connect(self._on_database_config_changed)

        # Central databaseChanged signal: ensure tabs reload when DB changes
        try:
            signals.databaseChanged.connect(self._on_central_database_changed)
        except Exception:
            pass

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

    def _on_central_database_changed(self, db_name: str):
        """Called when the central signals.databaseChanged is emitted.
        Iterate over tabs and call reload_data() if available.
        """
        try:
            for i in range(self.tabs.count()):
                w = self.tabs.widget(i)
                if w is not None and hasattr(w, 'reload_data'):
                    try:
                        w.reload_data()
                    except Exception:
                        # Defensive: don't let one failing tab prevent others
                        pass
        except Exception:
            pass
    
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