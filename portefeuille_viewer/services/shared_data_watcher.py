"""Reload committed shared changes; failed/inconsistent loads retry next poll."""
import logging
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal

from portefeuille_viewer.config import get_stockdata_db_path
from portefeuille_viewer.config.local_runtime import maintenance_lease
from portefeuille_viewer.data import repository
from portefeuille_viewer.data.shared_database import read_versions
from portefeuille_viewer.data.shared_change_hint import hint_path, read_hint
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE


class SharedDataWatcher(QObject):
    refreshed = Signal(object)
    failed = Signal(str)
    _loaded = Signal(object, object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path = get_stockdata_db_path()
        # Start empty so a change during startup cannot be missed.
        self.versions = {}
        self.busy = False
        self.stopped = False
        self._hint_path = hint_path(self.path)
        self._last_hint = None
        self._next_probe = 0.0
        self._deferred = False
        self._loaded.connect(self._publish)
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.poll)
        self.timer.start()

    def stop(self):
        self.stopped = True
        self.timer.stop()

    def invalidate(self):
        self.versions = {}
        self._next_probe = 0.0

    def poll(self):
        if self.busy or self.stopped:
            return
        self.busy = True
        baseline = dict(self.versions)
        def load():
            try:
                hint = read_hint(self._hint_path)
                now = time.monotonic()
                if hint == self._last_hint and now < self._next_probe:
                    if not self._deferred:
                        self._loaded.emit(None, None, None)
                        return
                    probe = maintenance_lease(self.path)
                    available = probe.acquire()
                    probe.release()
                    if not available:
                        self._loaded.emit(None, None, None)
                        return
                before = read_versions(self.path)
                changed = {key for key, value in before.items() if baseline.get(key) != value}
                loaders = {
                    'asset_rollup_data': repository.load_asset_rollup_data,
                    'optie_referentie_data': repository.load_optie_referentie_data,
                    'sprinters_referentie_data': repository.load_sprinter_referentie_data,
                    'historical_data_correct': repository.load_historical_ohlcv_snapshot,
                    'asset_driver_beta_snapshot': repository.load_asset_driver_beta_snapshot,
                    'asset_dividend_calendar_current': repository.load_asset_dividend_calendar_snapshot,
                }
                relevant = set(loaders) | {'option_series_master', 'stock_splits', 'option_price_factor_overrides'}
                if not changed & relevant:
                    self._loaded.emit(({}, before, set()), None, (hint, now, False))
                    return
                probe = maintenance_lease(self.path)
                busy = not probe.acquire()
                probe.release()
                # Historical pipelines commit intermediate stages. Publish their
                # results only after the owning task has released its lease.
                deferred = changed & {'historical_data_correct', 'asset_driver_beta_snapshot'} if busy else set()
                changed -= deferred
                with SNAPSHOT_STORE.capture_writes() as values:
                    for domain in sorted(changed):
                        if domain in loaders:
                            loaders[domain]()
                after = read_versions(self.path)
                if any(before.get(k) != after.get(k) for k in relevant - deferred):
                    raise RuntimeError('STOCKDATA veranderde tijdens verversen; nieuwe poging volgt')
                accepted = dict(before)
                for domain in deferred:
                    if domain in baseline:
                        accepted[domain] = baseline[domain]
                    else:
                        accepted.pop(domain, None)
                self._loaded.emit((values, accepted, changed & relevant), None, (hint, now, bool(deferred)))
            except Exception as exc:
                self._loaded.emit(None, str(exc), None)
        threading.Thread(target=load, daemon=True, name='shared-data-refresh').start()

    def _publish(self, result, error, unused):
        self.busy = False
        if self.stopped:
            return
        if error:
            logging.warning('Shared data refresh: %s', error)
            self.failed.emit(error)
            return
        if result is None:
            return
        values, versions, domains = result
        SNAPSHOT_STORE.publish_batch(values)
        self.versions = versions
        if unused is not None:
            self._last_hint, checked_at, self._deferred = unused
            self._next_probe = checked_at + 60.0
        if domains:
            self.refreshed.emit(domains)
