"""One computation at a time; merge pending work and publish only on the Qt thread."""
import threading
from collections import OrderedDict
from PySide6.QtCore import QObject, Signal
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE


class ProjectionWorker(QObject):
    completed = Signal(object, object)
    failed = Signal(str)

    def __init__(self, compute, parent=None):
        super().__init__(parent)
        self.compute = compute
        self.pending = OrderedDict()
        self.busy = False
        self.stopped = False
        self.completed.connect(self._publish)

    def submit(self, key, request):
        if self.stopped:
            return
        if key in self.pending:
            old = self.pending[key]
            request = {**request, 'names': old['names'] | request['names'],
                       'keys': old['keys'] | request['keys'],
                       'all': old['all'] or request['all']}
        self.pending[key] = request
        self._start()

    def _start(self):
        if self.busy or self.stopped or not self.pending:
            return
        _, request = self.pending.popitem(last=False)
        self.busy = True
        def run():
            try:
                with SNAPSHOT_STORE.capture_writes(freeze_inputs=True, skip_unchanged=True) as values:
                    self.compute(request)
                if not self.stopped:
                    self.completed.emit(values, None)
            except Exception as exc:
                if not self.stopped:
                    self.completed.emit(None, str(exc))
        threading.Thread(target=run, daemon=True, name='projection-compute').start()

    def _publish(self, values, error):
        if self.stopped:
            return
        try:
            if error:
                self.failed.emit(error)
            else:
                SNAPSHOT_STORE.publish_batch(values)
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
