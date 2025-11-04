import contextlib
from PySide6.QtWidgets import QMainWindow, QWidget
from portefeuille_viewer.ui.main_window_ui import Ui_MainWindow
from portefeuille_viewer.ui_logica.repository_tester_tab_logica import RepositoryTesterTab
from portefeuille_viewer.ui_logica.settings_tab_logica import SettingsTab

class MainWindow(QMainWindow, Ui_MainWindow):
    def __init__(self , price_feed,portfolio_engine, live_price_updater_stop_event=None): #  price_feed,
        super().__init__()
        self.setupUi(self)
        self.price_feed = price_feed
        self.portfolio_engine = portfolio_engine
        self.live_price_updater_stop_event = live_price_updater_stop_event
        # Dummy tab toevoegen (optioneel)
        dummy_tab = QWidget()
        self.tabWidget.addTab(dummy_tab, "Dummy tab")
        
        # Hier kun je later echte tab-klassen toevoegen
        self.repository_tester_tab = RepositoryTesterTab()
        self.tabWidget.addTab(self.repository_tester_tab, "Repository Tester")
        self.settings_tab = SettingsTab()
        self.tabWidget.addTab(self.settings_tab, "Settings")
    
    def closeEvent(self, event):
        # Stop hier je services, threads, timers, etc.
        if hasattr(self, 'price_feed'):
            with contextlib.suppress(Exception):
                self.price_feed.shutdown()  # Of een eigen stop-methode
        if hasattr(self, 'portfolio_engine'):
            with contextlib.suppress(Exception):
                self.portfolio_engine.shutdown()  # of stop(), of een andere naam
        if hasattr(self, 'live_price_updater_stop_event'):
            self.live_price_updater_stop_event.set()
        # Voeg hier eventueel meer cleanup toe
        print("closeEvent triggered!")
        super().closeEvent(event)
    
