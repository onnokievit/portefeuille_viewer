"""One computation at a time; merge pending work and publish only on the Qt thread."""
import threading
from collections import OrderedDict
from PySide6.QtCore import QObject, Signal, QThread
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE


class ProjectionWorker(QObject):
    completed = Signal(object, object, object)
    failed = Signal(str)
    started = Signal(object)
    published = Signal(object)

    def __init__(self, compute, parent=None):
        super().__init__(parent)
        self.compute = compute
        self.pending = OrderedDict()
        self.busy = False
        self.stopped = False
        self.completed.connect(self._publish)

    def submit(self, key, request):
        if QThread.currentThread() != self.thread():
            raise RuntimeError('Projection requests must originate on the owning Qt thread')
        if self.stopped:
            return
        if key in self.pending:
            old = self.pending[key]
            request = {**request, 'names': old['names'] | request['names'],
                       'keys': old['keys'] | request['keys'],
                       'all': old['all'] or request['all'],
                       'callbacks': old.get('callbacks', []) + request.get('callbacks', []),
                       'error_callbacks': old.get('error_callbacks', []) + request.get('error_callbacks', [])}
        self.pending[key] = request
        self._start()

    def _start(self):
        if self.busy or self.stopped or not self.pending:
            return
        _, request = self.pending.popitem(last=False)
        # Mutable caches are owned by the GUI thread. Copy before starting a
        # worker, never while the GUI can mutate them concurrently.
        inputs = SNAPSHOT_STORE.capture_inputs()
        self.busy = True
        self.started.emit(request)
        def run():
            try:
                with SNAPSHOT_STORE.capture_writes(inputs=inputs, skip_unchanged=True) as values:
                    self.compute(request)
                if not self.stopped:
                    self.completed.emit(values, None, request)
            except Exception as exc:
                if not self.stopped:
                    self.completed.emit(None, str(exc), request)
        threading.Thread(target=run, daemon=True, name='projection-compute').start()

    def _publish(self, values, error, request):
        if self.stopped:
            return
        try:
            if error:
                self.failed.emit(error)
                for callback in request.get('error_callbacks', []):
                    try:
                        callback(error)
                    except Exception as exc:
                        self.failed.emit(str(exc))
            else:
                SNAPSHOT_STORE.publish_batch(values)
                self.published.emit(request)
                for callback in request.get('callbacks', []):
                    try:
                        callback()
                    except Exception as exc:
                        self.failed.emit(str(exc))
        finally:
            self.busy = False
            self._start()

    def shutdown(self):
        self.stopped = True
        self.pending.clear()


def start_bounded_timer(timer):
    """First event sets the deadline; following events cannot postpone it."""
    if not timer.isActive():
        timer.start()
