from PySide6.QtWidgets import QMainWindow, QTabWidget, QWidget
from PySide6.QtGui import QAction
from portefeuille_viewer.services.price_feed import PriceFeedService
from portefeuille_viewer.ui.orders_tab import OrdersTab
from portefeuille_viewer.ui.live_tab import LiveViewTab
from portefeuille_viewer.ui.settings_tab import SettingsTab
from portefeuille_viewer.config import IB_HOST, IB_PORT, IB_CLIENT_ID
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.ui.open_options_tab import OpenOptiesPolarsTab
from portefeuille_viewer.ui.aandelen_tab import AandelenPolarsTab
from portefeuille_viewer.ui.aandelen_tab2 import AandelenTab2


APP_TITLE = "🧭 Portefeuille Viewer"

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1800, 950)

        # IB feed (gedeelde service)
        self.feed_service = PriceFeedService(IB_HOST, IB_PORT, IB_CLIENT_ID, self)
        self.feed_service._feed.log.connect(lambda s: self.statusBar().showMessage(s, 3000))
        self.feed_service._feed.ready.connect(lambda: self.statusBar().showMessage("IB-feed ready", 2000))

        # Tabs
        self.tabs = QTabWidget()
        self.orders_tab = OrdersTab()
        self.live_tab   = QWidget()
        self.open_opties_tab = OpenOptiesPolarsTab()
        #self.aandelen_tab = AandelenPolarsTab()
        
        self.aandelen_tab = AandelenPolarsTab(self.feed_service)
        
        self.settings_tab = SettingsTab()
        
        



        self.tabs.addTab(self.orders_tab, "Orders")
        self.tabs.addTab(self.aandelen_tab, "Open Aandelen (Polars)")
        self.tabs.addTab(AandelenTab2(pricefeed=self.feed_service), "Aandelen 2 (Agg)")
        self.tabs.addTab(self.live_tab, "Live view")
        self.tabs.addTab(self.open_opties_tab, "Open Opties (Polars)")
        #self.tabs.addTab(self.aandelen_tab, "Aandelen (Polars)")
        self.tabs.addTab(self.settings_tab, "Settings")
        

        self.setCentralWidget(self.tabs)

        # Koppeling: als Orders-tab iets opslaat of DB wijzigt → Live-tab herladen
        # self.orders_tab.ordersCommitted.connect(self.live_tab.reload_from_snapshots)
        # self.orders_tab.dbChanged.connect(self.live_tab.reload_from_db)

        # Menu
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(self.close)
        self.menuBar().addAction(act_quit)

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