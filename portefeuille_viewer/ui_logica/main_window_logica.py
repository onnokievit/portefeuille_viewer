import contextlib
from PySide6.QtWidgets import QMainWindow, QProxyStyle, QTabBar
from PySide6.QtGui import QShortcut, QKeySequence, QGuiApplication
from PySide6.QtCore import Qt
from portefeuille_viewer.ui.main_window_ui import Ui_MainWindow
from portefeuille_viewer.ui_logica.repository_tester_tab_logica import RepositoryTesterTab
from portefeuille_viewer.ui_logica.settings_tab_logica import SettingsTab
from portefeuille_viewer.ui_logica.optie_eind_tab_logica import OptieEindTab
from portefeuille_viewer.ui_logica.aandelen_web_pilot_tab import AandelenWebPilotTab
from portefeuille_viewer.ui_logica.opties_open_web_pilot_tab import OptiesOpenWebPilotTab
from portefeuille_viewer.ui_logica.portfolio_value_tab_logica import PortfolioValueTab
from portefeuille_viewer.ui_logica.optie_tijdswaarde_web_pilot_tab import OptieTijdswaardeWebPilotTab
from portefeuille_viewer.ui_logica.sprinters_open_web_pilot_tab import SprintersOpenWebPilotTab
from portefeuille_viewer.ui_logica.maand_eind_web_tab import MaandEindWebTab
from portefeuille_viewer.ui_logica.asset_indicator_web_tab import AssetIndicatorWebTab

from portefeuille_viewer.ui_logica.single_asset_analyse_tab_logica import SingleAssetAnalyseTab
from portefeuille_viewer.ui_logica.sector_analysis_tab_logica import SectorAnalysisTab
from portefeuille_viewer.ui_logica.orders_tab_widget import OrdersTabWidget
from portefeuille_viewer.ui_logica.maand_eind_chart_dialog import close_month_end_chart_dialog
from portefeuille_viewer.ui_logica.maand_eind_diff_chart_dialog import close_month_end_diff_chart_dialog
from portefeuille_viewer.ui_logica.generated_option_orders_dialog import close_scenario_dialog
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
        self._tab_specs = []
        self._tab_ids_by_widget = {}
        self._restoring_tab_order = False
        
        self._register_tabs()
        self._apply_saved_tab_order()
        self._restore_geometry()

        self.tabWidget.currentChanged.connect(self._on_tab_changed)
        self._on_tab_changed(self.tabWidget.currentIndex())
        self.tabWidget.tabBar().setStyle(_TabBarNoFocusRectStyle())
        self.tabWidget.setMovable(True)
        self.tabWidget.tabBar().tabMoved.connect(self._on_tab_moved)
        self._apply_tab_style()
        signals.uiStyleChanged.connect(self._on_ui_style_changed)

        self.shortcut_focus_tabbar = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self.shortcut_focus_tabbar.activated.connect(lambda: self.tabWidget.tabBar().setFocus())

    
    def _restore_geometry(self):
        geo = get_settings().get_main_window_geometry()
        if geo:
            screens = QGuiApplication.screens()
            on_screen = any(s.geometry().contains(geo['x'] + 50, geo['y'] + 50) for s in screens)
            if on_screen:
                self.setGeometry(geo['x'], geo['y'], geo['w'], geo['h'])
                state = geo.get('state', 'normal')
                if state == 'fullscreen':
                    self.showFullScreen()
                elif state == 'maximized':
                    self.showMaximized()
                return
        self.resize(1280, 800)

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

    def _register_tabs(self):
        self.orders_tab = OrdersTabWidget()
        self.single_asset_analyse_tab = SingleAssetAnalyseTab()
        self.aandelen_tab = AandelenWebPilotTab()
        self.opties_open_tab = OptiesOpenWebPilotTab()
        self.optie_tijdswaarde_tab = OptieTijdswaardeWebPilotTab()
        self.asset_indicator_tab = AssetIndicatorWebTab()
        self.portfolio_value_tab = PortfolioValueTab()
        self.maand_eind_tab = MaandEindWebTab()
        self.sector_analysis_tab = SectorAnalysisTab()
        self.sprinters_open_tab = SprintersOpenWebPilotTab()
        self.optie_eind_tab = OptieEindTab()
        self.settings_tab = SettingsTab()
        self.repository_tester_tab = RepositoryTesterTab()

        self._tab_specs = [
            ("orders", "Orders", self.orders_tab),
            ("single_asset_analyse", "Single Asset Analyse", self.single_asset_analyse_tab),
            ("aandelen", "Aandelen", self.aandelen_tab),
            ("opties_open_live", "Open Opties (Live)", self.opties_open_tab),
            ("optie_tijdswaarde", "Optie Tijdswaarde", self.optie_tijdswaarde_tab),
            ("asset_indicator", "Asset Indicator", self.asset_indicator_tab),
            ("portfolio_value", "Portfolio Value", self.portfolio_value_tab),
            ("maand_eind", "Maand Eind", self.maand_eind_tab),
            ("sector_analysis", "Sector Analysis", self.sector_analysis_tab),
            ("sprinters_open", "Sprinters Open", self.sprinters_open_tab),
            ("optie_eind", "Optie Eind", self.optie_eind_tab),
            ("settings", "Settings", self.settings_tab),
            ("repository_tester", "Repository Tester", self.repository_tester_tab),
        ]
        for tab_id, title, widget in self._tab_specs:
            self.tabWidget.addTab(widget, title)
            self._tab_ids_by_widget[widget] = tab_id

    def _apply_saved_tab_order(self):
        saved_order = get_settings().get_tab_order()
        if not saved_order:
            self._persist_tab_order()
            return
        widget_by_id = {tab_id: widget for tab_id, _title, widget in self._tab_specs}
        ordered_ids = [tab_id for tab_id in saved_order if tab_id in widget_by_id]
        for tab_id, _title, _widget in self._tab_specs:
            if tab_id not in ordered_ids:
                ordered_ids.append(tab_id)
        desired_widgets = [widget_by_id[tab_id] for tab_id in ordered_ids]
        self._restoring_tab_order = True
        try:
            for target_index, widget in enumerate(desired_widgets):
                current_index = self.tabWidget.indexOf(widget)
                if current_index >= 0 and current_index != target_index:
                    self.tabWidget.tabBar().moveTab(current_index, target_index)
        finally:
            self._restoring_tab_order = False
        self._persist_tab_order()

    def _current_tab_order(self) -> list[str]:
        out: list[str] = []
        for index in range(self.tabWidget.count()):
            widget = self.tabWidget.widget(index)
            tab_id = self._tab_ids_by_widget.get(widget)
            if tab_id:
                out.append(tab_id)
        return out

    def _persist_tab_order(self):
        get_settings().set_tab_order(self._current_tab_order())

    def _on_tab_moved(self, _from: int, _to: int):
        if self._restoring_tab_order:
            return
        self._persist_tab_order()

    def _on_tab_changed(self, index):
        if hasattr(self, "single_asset_analyse_tab") and hasattr(self.single_asset_analyse_tab, "set_active"):
            self.single_asset_analyse_tab.set_active(index == self.tabWidget.indexOf(self.single_asset_analyse_tab))
        if hasattr(self, "aandelen_tab") and hasattr(self.aandelen_tab, "set_active"):
            self.aandelen_tab.set_active(index == self.tabWidget.indexOf(self.aandelen_tab))
        if hasattr(self, "opties_open_tab") and hasattr(self.opties_open_tab, "set_active"):
            self.opties_open_tab.set_active(index == self.tabWidget.indexOf(self.opties_open_tab))
        if hasattr(self, "optie_tijdswaarde_tab") and hasattr(self.optie_tijdswaarde_tab, "set_active"):
            self.optie_tijdswaarde_tab.set_active(index == self.tabWidget.indexOf(self.optie_tijdswaarde_tab))
        if hasattr(self, "asset_indicator_tab") and hasattr(self.asset_indicator_tab, "set_active"):
            self.asset_indicator_tab.set_active(index == self.tabWidget.indexOf(self.asset_indicator_tab))
        if hasattr(self, "sprinters_open_tab") and hasattr(self.sprinters_open_tab, "set_active"):
            self.sprinters_open_tab.set_active(index == self.tabWidget.indexOf(self.sprinters_open_tab))
        if hasattr(self, "maand_eind_tab") and hasattr(self.maand_eind_tab, "set_active"):
            self.maand_eind_tab.set_active(index == self.tabWidget.indexOf(self.maand_eind_tab))

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

    def _close_standalone_dialogs(self):
        candidates = [
            (self.orders_tab, '_laatste_transacties_dlg'),
            (self.opties_open_tab, '_timevalue_chart_web_dialog'),
            (self.aandelen_tab, '_beta_scenario_dialog'),
        ]
        for tab, attr in candidates:
            with contextlib.suppress(Exception):
                dlg = getattr(tab, attr, None)
                if dlg is not None:
                    dlg._force_close = True
                    dlg.close()
        with contextlib.suppress(Exception):
            close_month_end_chart_dialog()
        with contextlib.suppress(Exception):
            close_month_end_diff_chart_dialog()
        with contextlib.suppress(Exception):
            close_scenario_dialog()

    def closeEvent(self, event):
        self._close_standalone_dialogs()
        # Stop hier je services, threads, timers, etc.
        if hasattr(self, 'price_feed'):
            with contextlib.suppress(Exception):
                self.price_feed.shutdown()
        if hasattr(self, 'portfolio_engine'):
            with contextlib.suppress(Exception):
                self.portfolio_engine.shutdown()
        if hasattr(self, "option_timevalue_service"):
            with contextlib.suppress(Exception):
                self.option_timevalue_service.shutdown()
        if hasattr(self, 'live_price_updater_stop_event'):
            self.live_price_updater_stop_event.set()

        # Flush test orders cache naar DB
        with contextlib.suppress(Exception):
            from portefeuille_viewer.data.test_order_repository import (
                flush_dirty_test_order_scenarios_to_db,
                flush_dirty_test_orders_to_db,
            )
            flush_dirty_test_orders_to_db()
            flush_dirty_test_order_scenarios_to_db()

        # Flush open optie comments naar DB en refresh cache
        with contextlib.suppress(Exception):
            from portefeuille_viewer.data.repository import (
                flush_dirty_open_optie_comments_to_db,
                load_open_optie_comments_cache,
            )
            flush_dirty_open_optie_comments_to_db()
            load_open_optie_comments_cache()
        # Flush single-asset step settings naar stock DB
        with contextlib.suppress(Exception):
            if hasattr(self, "single_asset_analyse_tab") and hasattr(self.single_asset_analyse_tab, "flush_step_settings_to_db"):
                self.single_asset_analyse_tab.flush_step_settings_to_db()

        # Save window geometry and state
        with contextlib.suppress(Exception):
            ws = self.windowState()
            if ws & Qt.WindowFullScreen:
                state = 'fullscreen'
            elif ws & Qt.WindowMaximized:
                state = 'maximized'
            else:
                state = 'normal'
            g = self.geometry()
            get_settings().set_main_window_geometry(g.x(), g.y(), g.width(), g.height(), state)

        print("closeEvent triggered!")
        super().closeEvent(event)


class _TabBarNoFocusRectStyle(QProxyStyle):
    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QProxyStyle.PE_FrameFocusRect and isinstance(widget, QTabBar):
            return
        super().drawPrimitive(element, option, painter, widget)

    def closeEvent(self, event):
        super().closeEvent(event)
