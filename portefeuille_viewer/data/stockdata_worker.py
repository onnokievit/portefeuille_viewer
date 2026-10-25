"""Serial database jobs, with a connection owned and closed by one fixed thread.

Opted in by the app; standalone migration/maintenance scripts keep their existing
connection lifetime. Jobs return materialised data, never connections/cursors.
"""
import atexit
from concurrent.futures import Future
from functools import wraps
import logging
import os
import queue
import threading
import time

import pyodbc

from portefeuille_viewer.config.process_lock import canonical_path, ProcessLock
from .shared_change_hint import hint_path, read_hint

_local = threading.local()
_registry_lock = threading.Lock()
_workers = {}
_enabled = False
_stopping = False


class StockdataWorker:
    def __init__(self, path):
        self.path = canonical_path(path)
        self._queue = queue.Queue(maxsize=128)
        self._state_lock = threading.Lock()
        self._accepting = True
        self._stop_requested = False
        self._raw = None
        self._borrowed = False
        self._opens = 0
        self._jobs = 0
        self._hint_path = hint_path(self.path)
        self._last_hint = None
        self._opened_at = 0.0
        self.thread = threading.Thread(target=self._run, name='stockdata-db', daemon=True)
        self.thread.start()

    def call(self, function, *args, **kwargs):
        if threading.current_thread() is self.thread:
            return function(*args, **kwargs)
        future = Future()
        with self._state_lock:
            if not self._accepting:
                raise RuntimeError('STOCKDATA-worker is afgesloten')
            try:
                self._queue.put_nowait((future, function, args, kwargs))
            except queue.Full:
                raise RuntimeError('STOCKDATA-wachtrij is vol; probeer opnieuw') from None
        return future.result()

    def borrow(self):
        self._assert_thread()
        if self._borrowed:
            raise RuntimeError('Geneste STOCKDATA-transacties op dezelfde worker zijn niet toegestaan')
        hint = read_hint(self._hint_path)
        # ACE caches pages on a physical connection. An external cooperating
        # writer must invalidate that cache before a read/modify/write job.
        # The periodic recycle also covers Access/manual writers without hints.
        if self._raw is not None and (hint != self._last_hint or
                time.monotonic() - self._opened_at >= 60):
            self._discard()
        if self._raw is None:
            self._raw = pyodbc.connect(
                rf'DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={self.path};', timeout=10)
            self._opens += 1
            self._opened_at = time.monotonic()
        self._last_hint = hint
        self._borrowed = True
        return self._raw

    def release(self, broken=False):
        self._assert_thread()
        self._borrowed = False
        if broken:
            self._discard()
        else:
            self._last_hint = read_hint(self._hint_path)

    def _assert_thread(self):
        if threading.current_thread() is not self.thread:
            raise RuntimeError('STOCKDATA-verbinding hoort bij een andere thread')

    def _discard(self):
        self._assert_thread()
        raw, self._raw = self._raw, None
        if raw is not None:
            try:
                raw.close()
            except pyodbc.Error:
                logging.exception('Sluiten van STOCKDATA-verbinding mislukt')

    def _run(self):
        _local.worker = self
        try:
            while True:
                job = self._queue.get()
                if job is None:
                    break
                future, function, args, kwargs = job
                lock = ProcessLock('stock-writer:' + self.path)
                try:
                    # Reserve the existing cross-process writer mutex for this
                    # short DB job, including its initial read. This prevents an
                    # external commit between cache validation and begin_write.
                    # SharedConnection's own acquisition is recursive on this
                    # same owning OS thread and remains independently balanced.
                    if not lock.acquire(15000):
                        raise TimeoutError('STOCKDATA wordt bijgewerkt door een andere instantie')
                    result = function(*args, **kwargs)
                    if self._borrowed:
                        raise RuntimeError('Databasejob heeft een verbinding niet afgesloten')
                except BaseException as exc:
                    # Never replay a failed write: its commit outcome may be unknown.
                    # The next job opens a fresh connection; application retry policy
                    # remains responsible for retries of the actual operation.
                    self._discard()
                    self._borrowed = False
                    future.set_exception(exc)
                else:
                    future.set_result(result)
                finally:
                    lock.release()
                    self._jobs += 1
        finally:
            self._discard()
            del _local.worker

    def stats(self):
        return self.call(lambda: dict(jobs=self._jobs, physical_opens=self._opens,
            owner_thread=threading.get_ident(), connection_open=self._raw is not None))

    def shutdown(self, timeout=10):
        with self._state_lock:
            self._accepting = False
            if not self._stop_requested:
                # Queue has a bounded number of short DB jobs, no HTTP or compute.
                self._queue.put(None, timeout=timeout)
                self._stop_requested = True
        if threading.current_thread() is not self.thread:
            self.thread.join(timeout)
            if self.thread.is_alive():
                raise TimeoutError('STOCKDATA-worker sluit nog af; actieve opdracht niet afgebroken')


def current_worker(path):
    worker = getattr(_local, 'worker', None)
    return worker if worker is not None and worker.path == canonical_path(path) else None


def enable_stockdata_workers():
    global _enabled, _stopping
    with _registry_lock:
        if any(w.thread.is_alive() for w in _workers.values()) and _stopping:
            raise RuntimeError('Vorige STOCKDATA-workers sluiten nog af')
        _stopping = False
        _enabled = os.environ.get('PV_STOCKDATA_WORKERS', '1') != '0'
    return _enabled


def worker_for(path):
    path = canonical_path(path)
    with _registry_lock:
        if _stopping:
            raise RuntimeError('STOCKDATA-workers worden afgesloten')
        if path not in _workers:
            _workers[path] = StockdataWorker(path)
        return _workers[path]


def worker_telemetry():
    """Approximate counters only; no queued job, DB access or process enumeration."""
    with _registry_lock:
        return [dict(physical_opens=w._opens, jobs=w._jobs, pending=w._queue.qsize(),
                     alive=w.thread.is_alive()) for w in _workers.values()]


def stockdata_job(function):
    """For repository functions with an explicit database path as first argument."""
    @wraps(function)
    def run(path, *args, **kwargs):
        if not _enabled:
            return function(path, *args, **kwargs)
        if current_worker(path) is not None:
            return function(path, *args, **kwargs)
        return worker_for(path).call(function, path, *args, **kwargs)
    return run


def current_stockdata_job(function):
    """For short DB-only jobs that use the configured STOCKDATA repository."""
    @wraps(function)
    def run(*args, **kwargs):
        if not _enabled:
            return function(*args, **kwargs)
        from . import repository
        path = repository.get_stockdata_db_path()
        if current_worker(path) is not None:
            return function(*args, **kwargs)
        return worker_for(path).call(function, *args, **kwargs)
    return run


def shutdown_stockdata_workers():
    global _stopping
    with _registry_lock:
        _stopping = True
        workers = list(_workers.items())
    for path, worker in workers:
        try:
            worker.shutdown()
        except (TimeoutError, queue.Full):
            logging.exception('STOCKDATA-worker nog bezig bij afsluiten')
        if not worker.thread.is_alive():
            with _registry_lock:
                if _workers.get(path) is worker:
                    del _workers[path]


atexit.register(shutdown_stockdata_workers)
