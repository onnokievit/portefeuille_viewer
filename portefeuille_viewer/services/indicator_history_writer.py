"""Write published indicator results independently of calculation and rendering."""
from collections import deque
import logging
import threading
from PySide6.QtCore import QObject, Signal

from portefeuille_viewer.services import asset_indicator_service


class IndicatorHistoryWriter(QObject):
    status_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lock = threading.Lock()
        self._pending = deque()
        self._thread = None
        self._closed = False

    def _status(self, payload, status, error=''):
        if not self._closed:
            self.status_changed.emit(dict(run_id=payload['run_id'], status=status, error=error))

    def enqueue(self, payload):
        start = None
        with self._lock:
            if self._closed:
                return
            overflow = len(self._pending) >= 16
            if not overflow:
                self._pending.append(payload)
            if not overflow and self._thread is None:
                # Already queued saves finish during normal app shutdown. Each
                # job owns and closes its Access connection on this thread.
                self._thread = threading.Thread(target=self._run, name='indicator-history-save', daemon=False)
                start = self._thread
        if overflow:
            self._status(payload, 'error', 'Opslagwachtrij vol; resultaat is niet opgeslagen')
            return
        self._status(payload, 'queued')
        if start is not None:
            start.start()

    def _run(self):
        while True:
            with self._lock:
                if not self._pending:
                    self._thread = None
                    return
                payload = self._pending.popleft()
            self._status(payload, 'saving')
            try:
                outcome = asset_indicator_service._persist_signal_history(**payload, raise_errors=True)
                self._status(payload, outcome or 'saved')
            except Exception as exc:
                logging.exception('Indicator history save failed for run %s', payload['run_id'])
                self._status(payload, 'error', f'{type(exc).__name__}: {exc}')

    @property
    def busy(self):
        with self._lock:
            return self._thread is not None

    def close(self):
        # No join on the GUI thread. The non-daemon worker drains already
        # accepted writes; it never waits for another Qt callback to proceed.
        self._closed = True
