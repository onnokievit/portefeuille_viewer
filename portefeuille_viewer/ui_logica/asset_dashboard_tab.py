"""Independent web view over existing snapshots. Created lazily on first visit."""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget, QMenu, QColorDialog, QMessageBox
from PySide6.QtGui import QColor, QCursor

from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.services.asset_dashboard_data import SOURCES, build_dashboard_payload, event_date_display
from portefeuille_viewer.services.asset_dashboard_earnings import load_next_earnings
from portefeuille_viewer.config.settings_manager import get_stockdata_db_path
from portefeuille_viewer.services.asset_dashboard_comments import DashboardComments
from portefeuille_viewer.services.asset_dashboard_test_orders import DashboardTestOrders
from portefeuille_viewer.services.asset_dashboard_controls import DashboardPayoffControls, DEFAULT_CONTROLS, validate_controls
from portefeuille_viewer.signals import signals
from portefeuille_viewer.config import get_settings
from portefeuille_viewer.services.asset_dashboard_analytics import (
    ANALYTIC_SOURCES, capture_analytics, calculate_analytics,
)

log = logging.getLogger(__name__)
# Both dashboard tabs share one calculation lane, including during tab switches.
DASHBOARD_ANALYTICS_POOL = QThreadPool()
DASHBOARD_ANALYTICS_POOL.setMaxThreadCount(1)


class _AnalyticsSignals(QObject):
    finished = Signal(int, object, str)


class _AnalyticsJob(QRunnable):
    def __init__(self, generation, request, history_cache):
        super().__init__()
        self.generation = generation
        self.cancelled = threading.Event()
        self.request = request
        self.history_cache = history_cache
        self.signals = _AnalyticsSignals()

    def run(self):
        if self.cancelled.is_set():
            self.signals.finished.emit(self.generation, None, 'cancelled')
            return
        try:
            result = calculate_analytics(*self.request, history_cache=self.history_cache)
            self.signals.finished.emit(self.generation, result, "")
        except Exception:
            log.exception("Asset Dashboard berekening mislukt")
            self.signals.finished.emit(self.generation, None, "Berekening mislukt; zie terminal voor details.")


class _EarningsJob(QRunnable):
    def __init__(self, path):
        super().__init__()
        self.path = path
        self.signals = _AnalyticsSignals()

    def run(self):
        try:
            self.signals.finished.emit(0, load_next_earnings(self.path), "")
        except Exception as exc:
            log.warning("Earningslabels konden niet worden geladen: %s", type(exc).__name__)
            self.signals.finished.emit(0, None, str(type(exc).__name__))


class DashboardBridge(QObject):
    updated = Signal(str)
    analyticsUpdated = Signal(str)
    commentResult = Signal(str)

    def __init__(self, tab):
        super().__init__(tab)
        self.tab = tab

    @Slot()
    def ready(self):
        self.tab._ready = True
        self.tab._publish(force=True)
        self.tab._request_earnings()

    @Slot(str, result=str)
    def savePositionColumns(self, raw):
        try:
            get_settings().set_asset_dashboard_position_columns(self.tab.layout_mode, json.loads(raw))
            return ''
        except Exception as exc:
            log.warning('Kolombreedtes konden niet worden bewaard: %s', type(exc).__name__)
            return str(exc)

    @Slot(str, result=str)
    def saveLayout(self, raw):
        try:
            if not self.tab.editable_layout:
                raise ValueError('Dit dashboard heeft een vaste indeling')
            get_settings().set_asset_dashboard_layout(self.tab.layout_mode, json.loads(raw))
            return ''
        except Exception as exc:
            log.warning('Dashboardindeling kon niet worden bewaard: %s', type(exc).__name__)
            return str(exc)

    @Slot(str, result=str)
    def testOrderAction(self, raw):
        try:
            request = json.loads(raw)
            if request.get('asset') != self.tab.selected_asset:
                raise ValueError('De geselecteerde asset is gewijzigd')
            if self.tab._test_orders is None:
                raise ValueError('Testorders zijn niet aangesloten')
            self.tab._test_orders.action(request['action'], request.get('value'))
            self.tab._publish(force=True)
            return ''
        except Exception as exc:
            log.exception('Dashboard testorderactie mislukt')
            return str(exc)

    @Slot(str)
    def selectAsset(self, asset):
        self.tab._publish(force=True, asset=asset)

    @Slot(str)
    def selectStatus(self, status):
        if status in {"active", "inactive", "all"}:
            self.tab._asset_status = status
            self.tab._publish(force=True)

    @Slot(str, result=str)
    def setTheme(self, value):
        try:
            get_settings().set_asset_dashboard_theme(value)
            return ""
        except Exception as exc:
            log.warning("Dashboardthema kon niet worden opgeslagen: %s", type(exc).__name__)
            return "Themakeuze kon niet worden opgeslagen"

    @Slot(str, str, str, result=str)
    def saveComment(self, identity, comment, request):
        return self.tab._save_comment(identity, comment, request)

    @Slot(str)
    def chooseCommentColor(self, identity):
        self.tab._choose_comment_colour(identity)

    @Slot(str)
    def commentsFlushed(self, error):
        self.tab._finish_comment_close(error)

    @Slot(str, result=str)
    def configure(self, raw):
        try:
            values = json.loads(raw)
            from datetime import date
            start = date.fromisoformat(values["start"])
            end = date.fromisoformat(values["end"])
            if start>end:
                raise ValueError("Begindatum ligt na einddatum")
            if values.get("changed") not in {None,"start","end"}:
                if values.get("asset")!=self.tab.selected_asset or self.tab._payoff_settings is None:
                    raise ValueError("Wacht tot de geselecteerde asset is geladen")
                cfg=validate_controls(values)
                self.tab._payoff_settings.save(self.tab.selected_asset,cfg)
            if (self.tab._controls.get("start"), self.tab._controls.get("end")) != (start.isoformat(), end.isoformat()):
                get_settings().set_asset_dashboard_period(start.isoformat(), end.isoformat())
            self.tab._controls = dict(start=start.isoformat(),end=end.isoformat())
            self.tab._publish()
            return ""
        except (ValueError,TypeError,KeyError) as exc:
            return str(exc)
        except Exception as exc:
            log.exception("Dashboardinstellingen konden niet worden bewaard")
            return "Instellingen konden niet worden bewaard: " + type(exc).__name__


class AssetDashboardTab(QWidget):
    assetChanged = Signal(str)

    def __init__(self, parent=None, *, editable_layout=False, layout_mode='desktop'):
        super().__init__(parent)
        self.editable_layout = editable_layout
        self.layout_mode = layout_mode if layout_mode in {'desktop', 'laptop'} else 'desktop'
        self.selected_asset = ""
        self._asset_status = "active"
        self._active = self._ready = False
        self._initialized = False
        self._last_payload = None
        self._controls = {}
        self._analytics_key = None
        self._generation = 0
        self._pending_analytics = None
        self._job = None
        self._history_cache = {}
        self._comment_editor = None
        self._payoff_settings = None
        self._test_orders = None
        self._comment_close_callback = None
        self._comment_close_timer = QTimer(self)
        self._comment_close_timer.setSingleShot(True)
        self._comment_close_timer.setInterval(5000)
        self._comment_close_timer.timeout.connect(lambda: self._finish_comment_close("Commentaar kon niet tijdig worden bevestigd; probeer opnieuw."))
        self._earnings = {}
        self._earnings_path = None
        self._earnings_job = None
        self._earnings_timer = QTimer(self)
        self._earnings_timer.setInterval(60_000)
        self._earnings_timer.timeout.connect(self._request_earnings)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(350)
        self._timer.timeout.connect(self._publish)
        signals.snapshotUpdated.connect(self._snapshot_updated)
        signals.databaseChanged.connect(self._reset_earnings)

    def set_comment_target(self, legacy_tab):
        self._comment_editor = DashboardComments(legacy_tab)

    def set_payoff_target(self, legacy_tab):
        self._payoff_settings = DashboardPayoffControls(legacy_tab)
        self._test_orders = DashboardTestOrders(legacy_tab, self)
        signals.testOrderScenariosChanged.connect(self._test_orders.changed)
        signals.testOrdersEnabledChanged.connect(self._test_orders.changed)

    def _comment_result(self, identity, operation, request, result=None, error=""):
        result = result or {}
        raw = json.dumps({"id": identity, "operation": operation,
            "request": request, "error": error, "text": result.get("optie_comment") or "",
            "background": result.get("optie_comment_color") or "",
            "foreground": result.get("optie_comment_textcolor") or ""}, default=str)
        self.bridge.commentResult.emit(raw)
        return raw

    def _save_comment(self, identity, comment, request):
        try:
            if self._comment_editor is None:
                raise RuntimeError("Commentaaropslag is niet aangesloten")
            result = self._comment_editor.save_text(identity, comment)
            response = self._comment_result(identity, "text", request, result)
            signals.snapshotUpdated.emit("repository_snapshot_open_optie_comments")
            self._publish(force=True)
            return response
        except Exception as exc:
            return self._comment_result(identity, "text", request, error=str(exc))

    def flush_comments_before_close(self, callback):
        if not self._ready or self._comment_editor is None:
            return False
        if self._comment_close_callback is None:
            self._comment_close_callback = callback
            self._comment_close_timer.start()
            self.web.page().runJavaScript("flushDashboardComments()")
        return True

    def _finish_comment_close(self, error):
        callback, self._comment_close_callback = self._comment_close_callback, None
        self._comment_close_timer.stop()
        if callback is None:
            return
        if error:
            QMessageBox.warning(self, "Commentaar niet bewaard", error)
        else:
            QTimer.singleShot(0, callback)

    def _choose_comment_colour(self, identity):
        try:
            if self._comment_editor is None:
                raise RuntimeError("Commentaaropslag is niet aangesloten")
            latest = self._comment_editor.latest(identity)
            menu = QMenu(self)
            for _priority, label, background, _foreground in get_settings().get_comment_colors():
                menu.addAction(label).setData(background)
            menu.addSeparator()
            custom = menu.addAction("Kies kleur...")
            chosen = menu.exec(QCursor.pos())
            if chosen is None:
                return
            if chosen == custom:
                colour = QColorDialog.getColor(QColor(latest.get("optie_comment_color") or "#ffffff"), self, "Kies kleur")
                if not colour.isValid():
                    return
                background = colour.name()
            else:
                background = chosen.data() or ""
            foreground = get_settings().get_comment_color_text_map().get(background, "")
            result = self._comment_editor.save_colour(identity, background, foreground)
            self._comment_result(identity, "colour", "", result)
            signals.snapshotUpdated.emit("repository_snapshot_open_optie_comments")
            self._publish(force=True)
        except Exception as exc:
            self._comment_result(identity, "colour", "", error=str(exc))

    def _initialize(self):
        self._initialized = True
        try:
            from PySide6.QtWebChannel import QWebChannel
            from PySide6.QtWebEngineWidgets import QWebEngineView
        except ImportError:
            self._layout.addWidget(QLabel("Asset Dashboard vereist QtWebEngine en QtWebChannel."))
            return
        self.web = QWebEngineView(self)
        self.channel = QWebChannel(self.web.page())
        self.bridge = DashboardBridge(self)
        self.channel.registerObject("dashboard", self.bridge)
        self.web.page().setWebChannel(self.channel)
        self._layout.addWidget(self.web)
        template = Path(__file__).parents[1] / "ui" / "web" / "asset_dashboard.html"
        chart_script = template.with_name("asset_dashboard_charts.js").read_text(encoding="utf-8")
        chart_script = template.with_name("asset_dashboard_axes.js").read_text(encoding="utf-8") + "\n" + chart_script
        view_script = template.with_name("asset_dashboard_view.js").read_text(encoding="utf-8")
        self._controls.update(get_settings().get_asset_dashboard_period())
        page = template.read_text(encoding="utf-8").replace("{{START_DATE}}", self._controls["start"]).replace("{{END_DATE}}", self._controls["end"])
        page = page.replace("{{DASHBOARD_THEME}}", get_settings().get_asset_dashboard_theme())
        column_config = json.dumps(get_settings().get_asset_dashboard_position_columns(self.layout_mode))
        view_script += '\nwindow.dashboardPositionColumnConfig=' + column_config + ';\n' + template.with_name('asset_dashboard_columns.js').read_text(encoding='utf-8')
        if self.editable_layout:
            layout_script = template.with_name('asset_dashboard_layout.js').read_text(encoding='utf-8')
            engine_script = template.with_name('asset_dashboard_layout_engine.js').read_text(encoding='utf-8')
            config = json.dumps(dict(mode=self.layout_mode, layout=get_settings().get_asset_dashboard_layout(self.layout_mode)))
            view_script += '\nwindow.dashboardLayoutConfig=' + config + ';\n' + engine_script + '\n' + layout_script
        self.web.setHtml(page.replace("<!-- DASHBOARD_CHARTS -->", "<script>" + chart_script + "</script>").replace(
            "<!-- DASHBOARD_VIEW -->", "<script>" + view_script + "</script>"))

    def set_active(self, active):
        self._active = bool(active)
        if self._active:
            self._analytics_key = None
            if not self._initialized:
                self._initialize()
            self._publish()
            self._earnings_timer.start()
            self._request_earnings()
        else:
            self._timer.stop()
            self._earnings_timer.stop()
            self._pending_analytics = None
            self._generation += 1
            if self._job is not None:
                self._job.cancelled.set()

    def _snapshot_updated(self, key):
        # Leading edge batching: repeated ticks do not restart a pending render.
        if self._active and key in (*SOURCES.values(), *ANALYTIC_SOURCES, "repository_snapshot_test_orders_cache", "snapshot_active_scenario_orders") and not self._timer.isActive():
            self._timer.start()

    def _publish(self, force=False, asset=None):
        if not self._active or not self._ready:
            return
        try:
            payload = build_dashboard_payload(SNAPSHOT_STORE, self.selected_asset if asset is None else asset,
                                              status=self._asset_status)
            earnings = self._earnings.get(payload["asset"], {})
            payload["earnings_display"] = dict(event_date_display(earnings.get("date")),
                                                source=earnings.get("source", ""))
            payload["payoff_controls"] = self._payoff_settings.get(payload["asset"]) if self._payoff_settings else dict(DEFAULT_CONTROLS)
            if self._comment_editor is not None:
                self._comment_editor.remember(payload["option_comments"])
            if self._test_orders is not None:
                payload['test_orders'] = self._test_orders.state(payload['asset'])
                if self._comment_editor is not None:
                    self._comment_editor.remember([cell['comment'] for cells in payload['test_orders']['rows']
                        for cell in cells if cell.get('comment')])
            encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, default=str)
            if force or encoded != self._last_payload:
                previous_asset = self.selected_asset
                self.selected_asset = payload["asset"]
                self._last_payload = encoded
                self.bridge.updated.emit(encoded)
                if previous_asset != self.selected_asset:
                    self._analytics_key = None
                    self.assetChanged.emit(self.selected_asset)
            self._request_analytics(payload)
        except Exception:
            log.exception("Asset Dashboard snapshot kon niet worden opgebouwd")

    def _reset_earnings(self, *_args):
        if self._comment_editor is not None:
            self._comment_editor.known_ids.clear()
        self._earnings = {}
        self._earnings_path = None
        self._publish()
        self._request_earnings()

    def _request_earnings(self):
        if not self._active or not self._ready or self._earnings_job is not None:
            return
        path = get_stockdata_db_path()
        if path != self._earnings_path:
            self._earnings = {}
            self._earnings_path = path
        self._earnings_job = _EarningsJob(path)
        self._earnings_job.signals.finished.connect(self._earnings_finished)
        QThreadPool.globalInstance().start(self._earnings_job)

    @Slot(int, object, str)
    def _earnings_finished(self, _generation, result, error):
        path = self._earnings_job.path
        self._earnings_job = None
        if path != self._earnings_path:
            self._request_earnings()
            return
        if not error:
            self._earnings = result
            self._publish()

    def _request_analytics(self, payload):
        if not payload["asset"]:
            self._generation += 1
            self._pending_analytics = None
            self._analytics_key = None
            return
        settings = dict(self._controls)
        settings.update(payload.get("payoff_controls", DEFAULT_CONTROLS))
        settings["currency_factor"] = (get_settings().get_eurusd()
                                       if payload["reference"].get("ib_currency") == "USD" else 1.)
        frozen, token = capture_analytics(SNAPSHOT_STORE)
        settings['test_orders_enabled'] = bool(payload.get('test_orders', {}).get('enabled'))
        settings['test_order_scenario'] = payload.get('test_orders', {}).get('scenario')
        if self._test_orders is not None:
            frozen.dashboard_test_orders = self._test_orders.capture(payload['asset'])
            settings['test_order_signature'] = (frozen.dashboard_test_orders.write_json()
                if frozen.dashboard_test_orders is not None else '')
        summary = payload.get("summary", {})
        key = (payload["asset"], token, json.dumps(settings, sort_keys=True),
               summary.get("koers"), summary.get("totaal_inc_fee"))
        if key == self._analytics_key:
            return
        self._analytics_key = key
        self._generation += 1
        self._pending_analytics = (self._generation, (frozen, payload, settings))
        self._start_analytics()

    def _start_analytics(self):
        if self._job is not None or self._pending_analytics is None or not self._active:
            return
        generation, request = self._pending_analytics
        self._pending_analytics = None
        self._job = _AnalyticsJob(generation, request, self._history_cache)
        self._job.signals.finished.connect(self._analytics_finished)
        DASHBOARD_ANALYTICS_POOL.start(self._job)

    @Slot(int, object, str)
    def _analytics_finished(self, generation, result, error):
        self._job = None
        if generation == self._generation and self._active:
            payload = result if not error else {"asset": self.selected_asset, "error": error}
            self.bridge.analyticsUpdated.emit(json.dumps(payload, ensure_ascii=False, allow_nan=False))
        self._start_analytics()
