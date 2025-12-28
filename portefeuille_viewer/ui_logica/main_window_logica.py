import contextlib
from PySide6.QtWidgets import QMainWindow, QProxyStyle, QTabBar
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
from portefeuille_viewer.ui_logica.sector_analysis_tab_logica import SectorAnalysisTab
from portefeuille_viewer.ui_logica.orders_tab_widget import OrdersTabWidget
from portefeuille_viewer.config import get_settings
from portefeuille_viewer.signals import signals




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
        self.opties_open_tab = OptiesOpenTab(self.portfolio_engine)
        self.tabWidget.addTab(self.opties_open_tab, "Open Opties (Live)")
        self.portfolio_value_tab = PortfolioValueTab()
        self.tabWidget.addTab(self.portfolio_value_tab, "Portfolio Value")
        self.sector_analysis_tab = SectorAnalysisTab()
        self.tabWidget.addTab(self.sector_analysis_tab, "Sector Analysis")
        


        self.sprinters_open_tab = SprintersOpenTab(self.portfolio_engine)
        self.tabWidget.addTab(self.sprinters_open_tab, "Sprinters Open")
        self.optie_eind_tab = OptieEindTab()
        self.tabWidget.addTab(self.optie_eind_tab, "Optie Eind")
        self.settings_tab = SettingsTab()
        self.tabWidget.addTab(self.settings_tab, "Settings")
        self.repository_tester_tab = RepositoryTesterTab()
        self.tabWidget.addTab(self.repository_tester_tab, "Repository Tester")

        self.tabWidget.currentChanged.connect(self._on_tab_changed)
        self._on_tab_changed(self.tabWidget.currentIndex())
        self.tabWidget.tabBar().setStyle(_TabBarNoFocusRectStyle())
        self._apply_tab_style()
        signals.uiStyleChanged.connect(self._on_ui_style_changed)

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

    def _on_tab_changed(self, index):
        if hasattr(self, "single_asset_analyse_tab") and hasattr(self.single_asset_analyse_tab, "set_active"):
            self.single_asset_analyse_tab.set_active(index == self.tabWidget.indexOf(self.single_asset_analyse_tab))
        if hasattr(self, "aandelen_tab") and hasattr(self.aandelen_tab, "set_active"):
            self.aandelen_tab.set_active(index == self.tabWidget.indexOf(self.aandelen_tab))
        if hasattr(self, "opties_open_tab") and hasattr(self.opties_open_tab, "set_active"):
            self.opties_open_tab.set_active(index == self.tabWidget.indexOf(self.opties_open_tab))
        if hasattr(self, "sprinters_open_tab") and hasattr(self.sprinters_open_tab, "set_active"):
            self.sprinters_open_tab.set_active(index == self.tabWidget.indexOf(self.sprinters_open_tab))

    def _apply_tab_style(self):
        settings = get_settings()
        inactive = settings.get_tab_inactive_bg()
        active = settings.get_tab_active_bg()
        hover = settings.get_tab_hover_bg()
        self.tabWidget.setStyleSheet(
            "QTabBar::tab {"
            f"background: {inactive};"
            "padding: 3px 12px;"
            "border: 1px solid #bfbfbf;"
            "border-radius: 4px;"
            "margin-right: 2px;"
            "}"
            "QTabBar::tab:selected {"
            f"background: {active};"
            "}"
            "QTabBar::tab:hover {"
            f"background: {hover};"
            "}"
            "QTabBar::tab:focus {"
            "outline: none;"
            "border: 1px solid #000000;"
            "border-radius: 6px;"
            "}"
        )

    def _on_ui_style_changed(self, key: str):
        if key in {"tab_inactive_bg", "tab_active_bg", "tab_hover_bg"}:
            self._apply_tab_style()

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


class _TabBarNoFocusRectStyle(QProxyStyle):
    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QProxyStyle.PE_FrameFocusRect and isinstance(widget, QTabBar):
            return
        super().drawPrimitive(element, option, painter, widget)

    def closeEvent(self, event):
        super().closeEvent(event)
