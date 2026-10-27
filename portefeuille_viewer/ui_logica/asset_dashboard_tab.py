"""Independent web view over existing snapshots. Created lazily on first visit."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.services.asset_dashboard_data import SOURCES, build_dashboard_payload, event_date_display
from portefeuille_viewer.services.asset_dashboard_earnings import load_next_earnings
from portefeuille_viewer.config.settings_manager import get_stockdata_db_path
from portefeuille_viewer.signals import signals
from portefeuille_viewer.config import get_settings
from portefeuille_viewer.services.asset_dashboard_analytics import (
    ANALYTIC_SOURCES, capture_analytics, calculate_analytics,
)

log = logging.getLogger(__name__)


class _AnalyticsSignals(QObject):
    finished = Signal(int, object, str)


class _AnalyticsJob(QRunnable):
    def __init__(self, generation, request, history_cache):
        super().__init__()
        self.generation = generation
        self.request = request
        self.history_cache = history_cache
        self.signals = _AnalyticsSignals()

    def run(self):
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

    def __init__(self, tab):
        super().__init__(tab)
        self.tab = tab

    @Slot()
    def ready(self):
        self.tab._ready = True
        self.tab._publish(force=True)
        self.tab._request_earnings()

    @Slot(str)
    def selectAsset(self, asset):
        self.tab._publish(force=True, asset=asset)

    @Slot(str)
    def selectStatus(self, status):
        if status in {"active", "inactive", "all"}:
            self.tab._asset_status = status
            self.tab._publish(force=True)

    @Slot(str)
    def configure(self, raw):
        try:
            values = json.loads(raw)
            step = float(values.get("step_pct", 2))
            shift = float(values.get("shift", 0))
            decimals = int(values.get("decimals", 2))
            from datetime import date
            start = date.fromisoformat(values["start"])
            end = date.fromisoformat(values["end"])
            if not (.01 <= step <= 50 and -1e9 <= shift <= 1e9 and 0 <= decimals <= 6 and start <= end):
                return
            if (self.tab._controls.get("start"), self.tab._controls.get("end")) != (start.isoformat(), end.isoformat()):
                get_settings().set_asset_dashboard_period(start.isoformat(), end.isoformat())
            self.tab._controls = dict(step_pct=step, shift=shift, decimals=decimals,
                                      start=start.isoformat(), end=end.isoformat())
            self.tab._publish()
        except (ValueError, TypeError, KeyError):
            return


class AssetDashboardTab(QWidget):
    assetChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
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
        self._controls.update(get_settings().get_asset_dashboard_period())
        page = template.read_text(encoding="utf-8").replace("{{START_DATE}}", self._controls["start"]).replace("{{END_DATE}}", self._controls["end"])
        self.web.setHtml(page.replace("<!-- DASHBOARD_CHARTS -->", "<script>" + chart_script + "</script>"))

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

    def _snapshot_updated(self, key):
        # Leading edge batching: repeated ticks do not restart a pending render.
        if self._active and key in (*SOURCES.values(), *ANALYTIC_SOURCES) and not self._timer.isActive():
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
        settings["currency_factor"] = (get_settings().get_eurusd()
                                       if payload["reference"].get("ib_currency") == "USD" else 1.)
        frozen, token = capture_analytics(SNAPSHOT_STORE)
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
        QThreadPool.globalInstance().start(self._job)

    @Slot(int, object, str)
    def _analytics_finished(self, generation, result, error):
        self._job = None
        if generation == self._generation and self._active:
            payload = result if not error else {"asset": self.selected_asset, "error": error}
            self.bridge.analyticsUpdated.emit(json.dumps(payload, ensure_ascii=False, allow_nan=False))
        self._start_analytics()
