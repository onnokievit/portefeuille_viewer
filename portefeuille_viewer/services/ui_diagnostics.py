"""Temporary, bounded local UI measurements. No arguments, SQL or portfolio data."""
from collections import deque
from datetime import datetime
from functools import wraps
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import threading
import time
import traceback
import ctypes

from PySide6.QtCore import QObject, QTimer


def timestamp():
    return datetime.now().astimezone().isoformat(timespec='milliseconds')


class UiDiagnostics(QObject):
    def __init__(self, app, directory, profile, *, sample_seconds=5):
        super().__init__(app)
        self.gui_thread = threading.get_ident()
        self.profile = profile
        self.lock = threading.Lock()
        self.metrics = {}
        self.events = deque(maxlen=128)
        self.dropped = 0
        self.stop_event = threading.Event()
        self.sample_seconds = sample_seconds
        self.last_heartbeat = time.monotonic()
        self.last_watchdog = self.last_heartbeat
        self.last_stack = 0.
        self.originals = []
        self.path = Path(directory) / (datetime.now().strftime('%Y%m%d_%H%M%S') + f'_{os.getpid()}.jsonl')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handler = RotatingFileHandler(self.path, maxBytes=5_000_000, backupCount=2, encoding='utf-8')
        self.handler.setFormatter(logging.Formatter('%(message)s'))
        try:
            import psutil
            self.process = psutil.Process()
            self.process.cpu_percent(None)
        except ImportError:
            self.process = None
        self._gui_resources = None
        if os.name == 'nt':
            kernel = ctypes.WinDLL('kernel32')
            user = ctypes.WinDLL('user32')
            kernel.GetCurrentProcess.restype = ctypes.c_void_p
            user.GetGuiResources.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            user.GetGuiResources.restype = ctypes.c_uint
            self._gui_resources = (user.GetGuiResources, kernel.GetCurrentProcess())
        self.mark_event('session_start', profile=profile, pid=os.getpid(),
                   process_metrics_available=self.process is not None,
                   heartbeat_ms=250, sample_seconds=sample_seconds)
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.heartbeat)
        self.timer.start()
        self.worker = threading.Thread(target=self._run, name='ui-diagnostics', daemon=True)
        self.worker.start()
        app.aboutToQuit.connect(self.stop)

    def mark_event(self, kind, **fields):
        with self.lock:
            if len(self.events) == self.events.maxlen:
                self.dropped += 1
            self.events.append(dict(type=kind, at=timestamp(), **fields))

    def record(self, name, duration, error=False):
        key = (name, threading.get_ident() == self.gui_thread)
        with self.lock:
            if key not in self.metrics and len(self.metrics) >= 256:
                self.dropped += 1
                return
            values = self.metrics.setdefault(key, [0, 0., 0., 0, 0])
            values[0] += 1
            values[1] += duration * 1000
            values[2] = max(values[2], duration * 1000)
            values[3] += duration >= .1
            values[4] += bool(error)
        if duration >= .1:
            self.mark_event('slow_action', name=name, gui=key[1], duration_ms=round(duration*1000, 2), error=bool(error))

    def wrap(self, owner, name, label):
        original = owner.get(name) if isinstance(owner, dict) else getattr(owner, name, None)
        if not callable(original):
            return
        @wraps(original)
        def measured(*args, **kwargs):
            start = time.perf_counter()
            error = False
            try:
                return original(*args, **kwargs)
            except BaseException:
                error = True
                raise
            finally:
                self.record(label, time.perf_counter()-start, error)
        if isinstance(owner, dict):
            owner[name] = measured
        else:
            setattr(owner, name, measured)
        self.originals.append((owner, name, original))

    def heartbeat(self):
        now = time.monotonic()
        elapsed = now - self.last_heartbeat
        self.last_heartbeat = now
        delay = max(0., elapsed - .250)
        self.record('qt.heartbeat_delay', delay)

    def wrap_history_cache(self, cache_class):
        original = cache_class.get
        @wraps(original)
        def measured(cache, history, assets, build, **kwargs):
            rebuilt = False
            def measured_build():
                nonlocal rebuilt
                rebuilt = True
                started = time.perf_counter()
                try:
                    return build()
                finally:
                    self.record('asset_indicator.historical_calculation', time.perf_counter()-started)
            started = time.perf_counter()
            try:
                result = original(cache, history, assets, measured_build, **kwargs)
                self.mark_event('historical_cache', reused=not rebuilt,
                                duration_ms=round((time.perf_counter()-started)*1000, 2))
                return result
            finally:
                self.record('asset_indicator.shared_history_lookup', time.perf_counter()-started)
        cache_class.get = measured
        self.originals.append((cache_class, 'get', original))

    def watchdog(self, now):
        # A gap in this independent thread may be sleep/resume or system-wide
        # starvation; do not label that as proven blocking by a UI callback.
        gap = now - self.last_watchdog
        self.last_watchdog = now
        if gap > 10:
            self.mark_event('pause_or_system_gap', seconds=round(gap, 2))
            self.last_stack = now
            return
        age = now - self.last_heartbeat
        if age < .75 or now - self.last_stack < 5:
            return
        self.last_stack = now
        frame = sys._current_frames().get(self.gui_thread)
        stack = [] if frame is None else [dict(file=Path(f.filename).name, line=f.lineno, function=f.name)
                                          for f in traceback.extract_stack(frame, limit=18)]
        self.mark_event('ui_unresponsive_sample', heartbeat_age_ms=round(age*1000, 2), stack=stack)

    def sample_process(self):
        if self.process is None:
            return {'available': False}
        try:
            with self.process.oneshot():
                result = dict(cpu_percent=self.process.cpu_percent(None),
                              rss_bytes=self.process.memory_info().rss,
                              threads=self.process.num_threads())
                if hasattr(self.process, 'num_handles'):
                    result['handles'] = self.process.num_handles()
                if self._gui_resources:
                    get_resources, handle = self._gui_resources
                    result['gdi_objects'] = get_resources(handle, 0)
                    result['user_objects'] = get_resources(handle, 1)
                from portefeuille_viewer.data.stockdata_worker import worker_telemetry
                result['stockdata_workers'] = worker_telemetry()
                return result
        except Exception as exc:
            return {'available': False, 'reason': type(exc).__name__}

    def flush(self, *, final=False):
        with self.lock:
            metrics, self.metrics = self.metrics, {}
            events, self.events = list(self.events), deque(maxlen=128)
            dropped, self.dropped = self.dropped, 0
        rows = [dict(name=name, gui=gui, calls=v[0], total_ms=round(v[1], 2),
                     max_ms=round(v[2], 2), calls_over_100ms=v[3], errors=v[4])
                for (name, gui), v in metrics.items()]
        payload = dict(type='measurement', at=timestamp(), profile=self.profile, pid=os.getpid(),
                       actions=rows, events=events, dropped=dropped,
                       process=self.sample_process(), final=final)
        record = logging.LogRecord('ui-diagnostics', logging.INFO, '', 0,
                                   json.dumps(payload, ensure_ascii=False), (), None)
        self.handler.handle(record)

    def _run(self):
        next_flush = time.monotonic() + self.sample_seconds
        try:
            while not self.stop_event.wait(.5):
                now = time.monotonic()
                self.watchdog(now)
                if now >= next_flush:
                    self.flush()
                    next_flush = now + self.sample_seconds
            self.flush(final=True)
        except Exception:
            logging.exception('UI diagnostics stopped; app continues')
        finally:
            self.handler.close()

    def stop(self):
        if self.stop_event.is_set():
            return
        self.timer.stop()
        self.mark_event('session_end')
        self.stop_event.set()
        for owner, name, original in reversed(self.originals):
            if isinstance(owner, dict):
                owner[name] = original
            else:
                setattr(owner, name, original)
        self.originals.clear()
        self.worker.join(timeout=2)


def start_ui_diagnostics(app, namespace):
    """Enabled for the current measurement phase; PV_UI_DIAGNOSTICS=0 opts out."""
    if os.getenv('PV_UI_DIAGNOSTICS', '1').strip() != '1':
        return None
    from portefeuille_viewer.config.local_runtime import runtime_root
    from portefeuille_viewer.config.profile_session import get_profile_session
    session = get_profile_session()
    profile = session.profile if session is not None else 'unknown'
    monitor = UiDiagnostics(app, runtime_root() / 'ui_diagnostics' / profile, profile)
    for name in list(namespace):
        if name.startswith(('refresh_', '_refresh_phase_', '_runtime_recompute_')):
            monitor.wrap(namespace, name, 'main.'+name)
    repository = namespace['repository']
    for name in vars(repository):
        if name.startswith(('load_', 'portfolio_value_')) or name in {'get_connection', 'get_stockdata_connection', 'build_repository_active_asset_rollup_data'}:
            monitor.wrap(repository, name, 'repository.'+name)
    for name in ('live_aggregator_aandelen', 'live_aggregator_opties', 'live_aggregator_sprinters'):
        monitor.wrap(type(namespace[name]), 'process_live_update', name+'.process_live_update')
    monitor.wrap(type(namespace['SNAPSHOT_STORE']), 'capture_inputs', 'snapshot.capture_inputs')
    targets = {
        'aandelen_web_pilot_tab': ('AandelenWebPilotTab', ['_flush_scheduled_render', '_publish_full_snapshot', '_publish_patch']),
        'opties_open_web_pilot_tab': ('OptiesOpenWebPilotTab', ['_flush_scheduled_render']),
        'optie_tijdswaarde_web_pilot_tab': ('OptieTijdswaardeWebPilotTab', ['_flush_scheduled_render']),
        'sprinters_open_web_pilot_tab': ('SprintersOpenWebPilotTab', ['_flush_scheduled_render']),
        'portfolio_value_tab_logica': ('PortfolioValueTab', ['reload_snapshot']),
        'sector_analysis_tab_logica': ('SectorAnalysisTab', ['reload_data']),
        'single_asset_analyse_tab_logica': ('SingleAssetAnalyseTab', ['on_asset_selected', '_reload_summary_if_needed', '_reload_opties_if_needed']),
        'maand_eind_web_tab': ('MaandEindWebTab', ['_flush_scheduled_render']),
        'asset_indicator_web_tab': ('AssetIndicatorWebTab', ['run_indicator', '_publish_snapshot']),
    }
    for module, (classname, methods) in targets.items():
        loaded = sys.modules.get('portefeuille_viewer.ui_logica.'+module)
        cls = getattr(loaded, classname, None)
        if cls is not None:
            for name in methods:
                monitor.wrap(cls, name, classname+'.'+name)
    monitor.wrap(namespace['OptionTimevalueService'], '_publish_snapshot', 'timevalue.publish')
    monitor.wrap(namespace['OptionTimevalueService'], '_rebuild_universe_worker', 'timevalue.rebuild')
    indicator_module = sys.modules.get('portefeuille_viewer.services.asset_indicator_service')
    if indicator_module is not None:
        monitor.wrap(indicator_module.AssetIndicatorService, 'rebuild', 'asset_indicator.calculate')
        monitor.wrap(indicator_module.AssetIndicatorService, '_build_live_snapshot', 'asset_indicator.build_snapshot')
        monitor.wrap(indicator_module, '_persist_signal_history', 'asset_indicator.persist_history')
    from portefeuille_viewer.services.shared_asset_history import SharedAssetHistory
    monitor.wrap_history_cache(SharedAssetHistory)
    monitor.mark_event('instrumentation', targets=len(monitor.originals))
    return monitor
