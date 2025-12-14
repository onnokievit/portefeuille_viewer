import contextlib
from PySide6.QtWidgets import QMainWindow
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtCore import Qt
from portefeuille_viewer.ui.main_window_ui import Ui_MainWindow
from portefeuille_viewer.ui_logica.repository_tester_tab_logica import RepositoryTesterTab
from portefeuille_viewer.ui_logica.settings_tab_logica import SettingsTab
from portefeuille_viewer.ui_logica.sprinters_open_tab_logica import SprintersOpenTab
from portefeuille_viewer.ui_logica.opties_open_tab_logica import OptiesOpenTab
from portefeuille_viewer.ui_logica.optie_eind_tab_logica import OptieEindTab
from portefeuille_viewer.ui_logica.aandelen_tab_logica import AandelenTab
from portefeuille_viewer.ui_logica.portfolio_value_tab_logica import PortfolioValueTab

from portefeuille_viewer.ui_logica.single_asset_analyse_tab_logica import SingleAssetAnalyseTab
from portefeuille_viewer.ui_logica.orders_tab_widget import OrdersTabWidget




class MainWindow(QMainWindow, Ui_MainWindow):
    def __init__(self , portfolio_engine, price_feed, live_price_updater_stop_event=None): #  price_feed,
        super().__init__()
        self.setupUi(self)
        self.installEventFilter(self)
        self.price_feed = price_feed
        self.portfolio_engine = portfolio_engine
        self.live_price_updater_stop_event = live_price_updater_stop_event
        
    # Hier kun je later echte tab-klassen toevoegen
        self.orders_tab = OrdersTabWidget() 
        self.tabWidget.addTab(self.orders_tab, "Orders")
        self.single_asset_analyse_tab = SingleAssetAnalyseTab()
        self.tabWidget.addTab(self.single_asset_analyse_tab, "Single Asset Analyse")
        self.aandelen_tab = AandelenTab(self.portfolio_engine, self.price_feed)
        self.tabWidget.addTab(self.aandelen_tab, "Aandelen")
        self.portfolio_value_tab = PortfolioValueTab()
        self.tabWidget.addTab(self.portfolio_value_tab, "Portfolio Value")


        self.opties_open_tab = OptiesOpenTab(self.portfolio_engine)
        self.tabWidget.addTab(self.opties_open_tab, "Open Opties (Live)")
        self.sprinters_open_tab = SprintersOpenTab(self.portfolio_engine)
        self.tabWidget.addTab(self.sprinters_open_tab, "Sprinters Open")
        self.optie_eind_tab = OptieEindTab()
        self.tabWidget.addTab(self.optie_eind_tab, "Optie Eind")
        self.settings_tab = SettingsTab()
        self.tabWidget.addTab(self.settings_tab, "Settings")
        self.repository_tester_tab = RepositoryTesterTab()
        self.tabWidget.addTab(self.repository_tester_tab, "Repository Tester")


        self.shortcut_focus_tabbar = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self.shortcut_focus_tabbar.activated.connect(lambda: self.tabWidget.tabBar().setFocus())

    
    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent, Qt
        if event.type() == QEvent.KeyPress:
            #print(f"Key ingerukt: {event.key()}, modifiers: {event.modifiers()}")
            if event.modifiers() == Qt.ControlModifier:
                if event.key() == Qt.Key_PageDown:
                    self.tabWidget.setCurrentIndex((self.tabWidget.currentIndex() + 1) % self.tabWidget.count())
                    return True  # event is handled
                elif event.key() == Qt.Key_PageUp:
                    self.tabWidget.setCurrentIndex((self.tabWidget.currentIndex() - 1) % self.tabWidget.count())
                    return True  # event is handled
        return super().eventFilter(obj, event)
    
    def closeEvent(self, event):
        # Stop hier je services, threads, timers, etc.
        if hasattr(self, 'price_feed'):
            with contextlib.suppress(Exception):
                self.price_feed.shutdown()
        if hasattr(self, 'portfolio_engine'):
            with contextlib.suppress(Exception):
                self.portfolio_engine.shutdown()
        if hasattr(self, 'live_price_updater_stop_event'):
            self.live_price_updater_stop_event.set()

        # Flush test orders cache naar DB
        with contextlib.suppress(Exception):
            from portefeuille_viewer.data.test_order_repository import flush_dirty_test_orders_to_db
            flush_dirty_test_orders_to_db()

        print("closeEvent triggered!")
        super().closeEvent(event)

