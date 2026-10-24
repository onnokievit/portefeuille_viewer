"""Unique local IB client IDs and shared line reservations for auxiliary clients."""
import threading
import time
from uuid import uuid4

from portefeuille_viewer.config.local_runtime import FileLease, canonical_host


class LineReservation:
    def __init__(self, host, port, amount):
        from portefeuille_viewer.config import get_stockdata_db_path, get_settings
        from portefeuille_viewer.services.shared_quote_coordinator import ensure_coordinator, rpc
        self.rpc = rpc
        self.key = uuid4().hex
        self.manifest = ensure_coordinator(get_stockdata_db_path(), host, port, get_settings().get_ib_client_id())
        self.stop = threading.Event()
        self.thread = None
        rpc(self.manifest, {'op':'join', 'client':self.key, 'profile':'achtergrondtaak'})
        try:
            self.call('reserve', amount=int(amount))
            self.thread = threading.Thread(target=self._heartbeat, daemon=True, name='quote-budget-lease')
            self.thread.start()
            deadline = time.monotonic()+15
            while not self.call('snapshot')['reservations_ready']:
                if time.monotonic()>deadline:
                    raise TimeoutError('Koersbudget kwam niet tijdig vrij; achtergrondaanvraag gestopt')
                time.sleep(.1)
        except BaseException:
            self.close()
            raise

    def call(self, op, **values):
        return self.rpc(self.manifest, {'op':op, 'client':self.key, **values})

    def _heartbeat(self):
        while not self.stop.wait(2):
            try:
                self.call('poll')
            except Exception:
                # Fail closed: notify the owning auxiliary client immediately.
                callback = getattr(self, 'on_lost', None)
                if callback:
                    callback()
                return

    def close(self):
        self.stop.set()
        try:
            self.call('leave')
        except Exception:
            pass  # server removes dead clients after its heartbeat timeout
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=3)


def connect_ib(app, host, port, preferred_id, *, line_budget=1, managed_feed=False):
    """Attach leases to the connection, releasing after disconnect or process crash."""
    host = canonical_host(host)
    lease = None
    for candidate in range(max(1,int(preferred_id)), max(1,int(preferred_id))+10000):
        lease = FileLease(f'ib-client:{str(host).lower()}:{int(port)}:{candidate}')
        if lease.acquire():
            break
    else:
        raise RuntimeError('Geen vrij lokaal IBKR client-ID')
    original_disconnect = app.disconnect
    reservation = None
    original_request = app.reqMktData
    original_cancel = app.cancelMktData
    auxiliary = not managed_feed
    active = set()
    lock = threading.RLock()

    def disconnect(*args, **kwargs):
        nonlocal reservation
        try:
            return original_disconnect(*args, **kwargs)
        finally:
            with lock:
                if reservation is not None:
                    reservation.close()
                    reservation = None
            lease.release()

    def request(req_id, *args, **kwargs):
        nonlocal reservation
        with lock:
            if auxiliary and reservation is None:
                reservation = LineReservation(host, port, line_budget)
                reservation.on_lost = disconnect
            # Keep reservations until disconnect, including cancellation grace.
            if auxiliary and req_id not in active and len(active) >= int(line_budget):
                raise RuntimeError('Achtergrondtaak vraagt meer koerslijnen aan dan gereserveerd')
            active.add(req_id)
        try:
            return original_request(req_id, *args, **kwargs)
        except BaseException:
            with lock:
                active.discard(req_id)
            raise

    def cancel(req_id, *args, **kwargs):
        result = original_cancel(req_id, *args, **kwargs)
        with lock:
            active.discard(req_id)
        return result

    app.disconnect = disconnect
    app.reqMktData = request
    app.cancelMktData = cancel
    try:
        app.connect(host, int(port), clientId=candidate)
    except BaseException:
        disconnect()
        raise
    return candidate
