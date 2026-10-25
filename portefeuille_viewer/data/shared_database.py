"""Atomic STOCKDATA units of work, cross-process writers and committed revisions."""
from datetime import datetime
import re
import threading

import pyodbc

from portefeuille_viewer.config.process_lock import ProcessLock, canonical_path
from .stockdata_worker import current_worker, stockdata_job

VERSION_TABLE = 'pv_shared_versions'


def changed_table(sql):
    sql = re.sub(r'/\*.*?\*/|--[^\n]*', ' ', str(sql), flags=re.S).strip()
    match = re.match(r'(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|CREATE\s+(?:UNIQUE\s+)?(?:TABLE|INDEX)|ALTER\s+TABLE|DROP\s+TABLE)\s+\[?([\w]+)', sql, re.I)
    if match:
        return match.group(1).lower()
    if re.match(r'SELECT\b', sql, re.I) and re.search(r'\bINTO\s+\[?\w+', sql, re.I):
        return 'schema'
    return None


class SharedCursor:
    def __init__(self, connection, cursor):
        object.__setattr__(self, 'connection', connection)
        object.__setattr__(self, '_cursor', cursor)

    def __getattr__(self, name):
        self.connection._check_thread()
        value = getattr(self._cursor, name)
        if callable(value):
            def call(*args, **kwargs):
                self.connection._check_thread()
                return value(*args, **kwargs)
            return call
        return value

    def __setattr__(self, name, value):
        self.connection._check_thread()
        setattr(self._cursor, name, value)

    def __iter__(self):
        while True:
            self.connection._check_thread()
            row = self._cursor.fetchone()
            if row is None:
                return
            yield row

    def execute(self, sql, *args, parameters=None):
        if parameters is not None:
            if args:
                raise TypeError('Gebruik positional parameters of parameters=, niet beide')
            args = (parameters,)
        self._execute('execute', sql, args)
        return self

    def executemany(self, sql, rows):
        self._execute('executemany', sql, (rows,))
        return self

    def _execute(self, method, sql, args):
        self.connection._check_thread()
        table = changed_table(sql)
        if table:
            self.connection.begin_write()
        getattr(self._cursor, method)(sql, *args)
        if table and self._cursor.rowcount != 0:
            self.connection._dirty.add(table)


class SharedConnection:
    """Serialize writers for their unit of work and publish revisions at commit.

    Explicit commit retains its DB-API meaning, including immediate visibility
    to follow-up snapshot reads. Replacement operations must commit once after
    their delete AND insert. Worker jobs return the physical connection to their
    owning worker; other callers still close it physically on context exit.
    """
    def __init__(self, path):
        self.path = canonical_path(path)
        self._owner_thread = threading.get_ident()
        self._worker = current_worker(self.path)
        self._raw = (self._worker.borrow() if self._worker else
            pyodbc.connect(rf'DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={self.path};'))
        self._cursors = []
        self._writer = ProcessLock('stock-writer:' + self.path)
        self._dirty = set()
        self._context = False
        self._closed = False

    def __getattr__(self, name):
        self._check_thread()
        value = getattr(self._raw, name)
        if callable(value):
            def call(*args, **kwargs):
                self._check_thread()
                return value(*args, **kwargs)
            return call
        return value

    def _check_thread(self):
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError('Databaseverbinding gebruikt vanuit een andere thread')
        if self._closed:
            raise RuntimeError('Databaseverbinding is gesloten')

    def cursor(self):
        return SharedCursor(self, self._new_raw_cursor())

    def _new_raw_cursor(self):
        self._check_thread()
        cur = self._raw.cursor()
        self._cursors.append(cur)
        return cur

    def execute(self, sql, *args, **kwargs):
        return self.cursor().execute(sql, *args, **kwargs)

    def begin_write(self):
        self._check_thread()
        if not self._writer.owned:
            self._raw.commit()  # release earlier read locks before waiting for another writer
            if not self._writer.acquire(15000):
                raise TimeoutError('STOCKDATA wordt bijgewerkt door een andere instantie; probeer opnieuw')
            try:
                cur = self._new_raw_cursor()
                if not any(r.table_name.lower() == VERSION_TABLE for r in cur.tables(table=VERSION_TABLE)):
                    cur.execute(f'CREATE TABLE {VERSION_TABLE} (domain TEXT(100) PRIMARY KEY, revision LONG, updated_at DATETIME)')
                    self._raw.commit()  # schema bootstrap is separate from the following data transaction
            except BaseException:
                self._writer.release()
                raise

    def _commit(self):
        self._check_thread()
        changed = bool(self._dirty)
        try:
            if self._dirty:
                cur = self._new_raw_cursor()
                for domain in sorted(self._dirty | {'all'}):
                    cur.execute(f'UPDATE {VERSION_TABLE} SET revision=revision+1, updated_at=? WHERE domain=?', datetime.now(), domain)
                    if cur.rowcount == 0:
                        cur.execute(f'INSERT INTO {VERSION_TABLE} (domain, revision, updated_at) VALUES (?, 1, ?)', domain, datetime.now())
            self._raw.commit()
            self._dirty.clear()
            if changed:
                from .shared_change_hint import publish_hint
                publish_hint(self.path)
        except BaseException:
            self._raw.rollback()
            self._dirty.clear()
            raise
        finally:
            if not self._context:
                self._writer.release()

    def commit(self):
        self._commit()

    def rollback(self):
        self._check_thread()
        try:
            self._raw.rollback()
            self._dirty.clear()
        finally:
            self._writer.release()

    def close(self):
        if not self._closed:
            self._check_thread()
            broken = False
            try:
                self.rollback()
            except BaseException:
                broken = True
                raise
            finally:
                try:
                    for cur in self._cursors:
                        try:
                            cur.close()
                        except pyodbc.Error:
                            pass  # explicit caller close, or a broken connection
                    self._cursors.clear()
                    if self._worker:
                        self._worker.release(broken=broken)
                    else:
                        self._raw.close()
                finally:
                    self._closed = True

    def __enter__(self):
        self._check_thread()
        self._context = True
        return self

    def __exit__(self, typ, value, tb):
        try:
            if typ is None:
                self._commit()
            else:
                self.rollback()
        finally:
            self._context = False
            self.close()


def connect_stockdata(path):
    return SharedConnection(path)


@stockdata_job
def read_versions(path):
    with connect_stockdata(path) as conn:
        cur = conn.cursor()
        if not any(r.table_name.lower() == VERSION_TABLE for r in cur.tables(table=VERSION_TABLE)):
            return {}
        return {str(r[0]): int(r[1]) for r in cur.execute(f'SELECT domain, revision FROM {VERSION_TABLE}')}
