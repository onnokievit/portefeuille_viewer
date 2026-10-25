"""Worker lifetime/ownership and real synthetic Access regression coverage."""
import threading
import subprocess
import sys
import shutil
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pyodbc

from portefeuille_viewer.data import stockdata_worker as workers
from portefeuille_viewer.data.shared_database import connect_stockdata, read_versions
from devtools import test_financial_storage as financial_tests


class WorkerStorageTests(financial_tests.FinancialStorageTests):
    """Run all existing financial storage scenarios through the new path too."""
    def setUp(self):
        super().setUp()
        enabled = patch.object(workers, '_enabled', True)
        enabled.start()
        self.addCleanup(enabled.stop)
        workers.enable_stockdata_workers()
        self.addCleanup(workers.shutdown_stockdata_workers)

    def job(self, fn):
        return workers.worker_for(self.path).call(fn)

    def test_many_jobs_reuse_connection_and_cannot_escape_to_other_thread(self):
        owner = []
        def read():
            with connect_stockdata(self.path) as conn:
                owner.append(threading.get_ident())
                return conn.execute('SELECT COUNT(*) FROM asset_rollup_data').fetchone()[0]
        for _ in range(60):
            self.assertEqual(self.job(read), 0)
        worker = workers.worker_for(self.path)
        self.assertEqual(worker.stats()['physical_opens'], 1)
        self.assertEqual(set(owner), {worker.thread.ident})
        self.assertNotEqual(owner[0], threading.get_ident())

    def test_two_callers_are_serialised_and_connection_closes_on_owner_thread(self):
        worker = workers.worker_for(self.path)
        owner = []
        errors = []
        def caller():
            try:
                for _ in range(10):
                    self.job(lambda: owner.append(threading.get_ident()) or read_versions(self.path))
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=caller) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
            self.assertFalse(t.is_alive())
        self.assertFalse(errors)
        self.assertEqual(set(owner), {worker.thread.ident})
        self.assertEqual(worker.stats()['physical_opens'], 1)
        worker.shutdown()
        self.assertFalse(worker.thread.is_alive())
        self.assertIsNone(worker._raw)
        with self.assertRaises(RuntimeError):
            worker.call(lambda: None)

    def test_failed_write_rolls_back_and_next_job_reconnects_without_replay(self):
        calls = []
        def fail():
            calls.append(1)
            with connect_stockdata(self.path) as conn:
                conn.execute("INSERT INTO asset_rollup_data (asset_rollup) VALUES ('rolled-back')")
                raise pyodbc.OperationalError('08S01', 'synthetic disconnected operation')
        with self.assertRaises(pyodbc.OperationalError):
            self.job(fail)
        self.assertEqual(calls, [1])
        self.assertEqual(self.job(lambda: self._count()), 0)
        self.assertEqual(workers.worker_for(self.path).stats()['physical_opens'], 2)
        self.assertNotIn('asset_rollup_data', read_versions(self.path))

    def _count(self):
        with connect_stockdata(self.path) as conn:
            return conn.execute('SELECT COUNT(*) FROM asset_rollup_data').fetchone()[0]

    def test_explicit_commit_is_not_replayed_or_undone_by_later_failure(self):
        def fail_after_commit():
            with connect_stockdata(self.path) as conn:
                conn.execute("INSERT INTO asset_rollup_data (asset_rollup) VALUES ('committed')")
                conn.commit()
                raise RuntimeError('failure after commit')
        with self.assertRaises(RuntimeError):
            self.job(fail_after_commit)
        self.assertEqual(self.job(self._count), 1)
        self.assertEqual(read_versions(self.path)['asset_rollup_data'], 1)

    def test_job_releases_read_transaction_for_other_connection_writer(self):
        self.job(self._count)
        # The physical worker connection stays open, but no transaction/lock does.
        with connect_stockdata(self.path) as conn:
            conn.execute("INSERT INTO asset_rollup_data (asset_rollup) VALUES ('external')")
        self.assertEqual(self.job(self._count), 1)

    def test_connection_and_cached_cursor_method_reject_other_thread(self):
        with connect_stockdata(self.path) as conn:
            cur = conn.cursor()
            fetch = cur.fetchone
            failures = []
            def bad_thread():
                for action in [conn.cursor, conn.commit, fetch]:
                    try:
                        action()
                    except RuntimeError:
                        failures.append(1)
            t = threading.Thread(target=bad_thread)
            t.start()
            t.join(5)
            self.assertEqual(len(failures), 3)

    def test_nested_lease_is_explicit_error_instead_of_corrupting_transaction(self):
        def nested():
            with connect_stockdata(self.path):
                with connect_stockdata(self.path):
                    pass
        with self.assertRaisesRegex(RuntimeError, 'Geneste'):
            self.job(nested)
        self.assertEqual(self.job(self._count), 0)

    def test_three_processes_do_not_overwrite_read_modify_write_results(self):
        with connect_stockdata(self.path) as conn:
            conn.execute('CREATE TABLE worker_counter (id LONG PRIMARY KEY, amount LONG)')
            conn.execute('INSERT INTO worker_counter VALUES (1,0)')
        script = '''
import sys
from portefeuille_viewer.data.stockdata_worker import enable_stockdata_workers, shutdown_stockdata_workers, stockdata_job
from portefeuille_viewer.data.shared_database import connect_stockdata
enable_stockdata_workers()
@stockdata_job
def increment(path):
    with connect_stockdata(path) as conn:
        conn.begin_write()
        value=conn.execute('SELECT amount FROM worker_counter WHERE id=1').fetchone()[0]
        conn.execute('UPDATE worker_counter SET amount=? WHERE id=1',value+1)
try:
    for i in range(12): increment(sys.argv[1])
finally: shutdown_stockdata_workers()
'''
        children = [subprocess.Popen([sys.executable, '-c', script, str(self.path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(3)]
        for child in children:
            out, err = child.communicate(timeout=45)
            self.assertEqual(child.returncode, 0, (out+err).decode(errors='replace'))
        def value():
            with connect_stockdata(self.path) as conn:
                return conn.execute('SELECT amount FROM worker_counter WHERE id=1').fetchone()[0]
        self.assertEqual(self.job(value), 36)

    def test_crashed_process_releases_writer_and_uncommitted_write(self):
        with connect_stockdata(self.path) as conn:
            conn.execute('CREATE TABLE worker_counter (id LONG PRIMARY KEY, amount LONG)')
            conn.execute('INSERT INTO worker_counter VALUES (1,0)')
        script = '''
import os,sys
from portefeuille_viewer.data.stockdata_worker import enable_stockdata_workers, stockdata_job
from portefeuille_viewer.data.shared_database import connect_stockdata
enable_stockdata_workers()
@stockdata_job
def crash(path):
    with connect_stockdata(path) as conn:
        conn.execute('UPDATE worker_counter SET amount=999 WHERE id=1')
        os._exit(23)
crash(sys.argv[1])
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.path)],
            capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 23)
        def recover():
            with connect_stockdata(self.path) as conn:
                conn.begin_write()
                value = conn.execute('SELECT amount FROM worker_counter WHERE id=1').fetchone()[0]
                conn.execute('UPDATE worker_counter SET amount=1 WHERE id=1')
                return value
        self.assertEqual(self.job(recover), 0)

    def test_distinct_paths_have_distinct_worker_threads_and_connections(self):
        other = self.path.with_name('other-'+self.path.name)
        shutil.copy2(self.base, other)
        @workers.stockdata_job
        def names(path):
            with connect_stockdata(path) as conn:
                return [r[0] for r in conn.execute('SELECT asset_rollup FROM asset_rollup_data')]
        self.assets()
        self.assertEqual(set(names(self.path)), {'A', 'B', 'C'})
        self.assertEqual(names(other), [])
        self.assertNotEqual(workers.worker_for(self.path).stats()['owner_thread'],
                            workers.worker_for(other).stats()['owner_thread'])

    def test_periodic_recycle_covers_writers_without_local_notification(self):
        self.job(self._count)
        worker = workers.worker_for(self.path)
        old = worker.stats()['physical_opens']
        raw = pyodbc.connect(rf'DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={self.path};')
        try:
            raw.execute("INSERT INTO asset_rollup_data (asset_rollup) VALUES ('manual-access')")
            raw.commit()  # Deliberately bypass shared revisions and local hints.
        finally:
            raw.close()
        worker.call(lambda: setattr(worker, '_opened_at', worker._opened_at-61))
        self.assertEqual(self.job(self._count), 1)
        self.assertEqual(worker.stats()['physical_opens'], old+1)

    def test_asset_price_store_read_and_write_use_worker_and_keep_other_prices(self):
        from portefeuille_viewer.data import repository
        from portefeuille_viewer.data.asset_last_price_store import AssetLastPriceStore
        with connect_stockdata(self.path) as conn:
            conn.execute('CREATE TABLE asset_last_prices (ib_symbol TEXT(32), ib_currency TEXT(8), '
                         'price DOUBLE, last_update DATETIME)')
        with patch.object(repository, 'get_stockdata_db_path', return_value=str(self.path)):
            AssetLastPriceStore._write_to_db({('A', 'USD'): 12.5})
            AssetLastPriceStore._write_to_db({('B', 'EUR'): 20})
            AssetLastPriceStore._write_to_db({('A', 'USD'): 13})
            self.assertEqual(AssetLastPriceStore._read_from_db(), {('A','USD'): 13, ('B','EUR'): 20})
        self.assertEqual(workers.worker_for(self.path).stats()['physical_opens'], 1)

    def test_option_price_persistence_uses_worker_with_legacy_schema(self):
        from portefeuille_viewer.data import repository
        from portefeuille_viewer.services.price_feed import PriceFeedService
        with connect_stockdata(self.path) as conn:
            conn.execute('CREATE TABLE option_series_master (series_id LONG, asset_rollup TEXT(64), '
                'optie_call_put TEXT(8), strike DOUBLE, expiry DATETIME)')
            conn.execute("INSERT INTO option_series_master (series_id,asset_rollup,optie_call_put,strike) "
                "VALUES (1,'A','C',100)")
            conn.execute('CREATE TABLE option_last_prices (series_id LONG PRIMARY KEY, asset_rollup TEXT(64), '
                'optie_call_put TEXT(8), optie_strike DOUBLE, optie_exp_date DATETIME, conid LONG, '
                'bid DOUBLE, ask DOUBLE, last_price DOUBLE, mid_price DOUBLE, underlying_price DOUBLE, '
                'iv DOUBLE, delta_greek DOUBLE, gamma DOUBLE, theta DOUBLE, ts DATETIME)')
        service = SimpleNamespace(_cleanup_expired_option_last_prices_if_due=lambda: None,
            _connect_option_last_prices_db=lambda: connect_stockdata(self.path),
            _ensure_option_last_prices_table=PriceFeedService._ensure_option_last_prices_table,
            _table_columns=PriceFeedService._table_columns)
        row = dict(series_id=1, bid=2., ask=3., last_px=2.4, conid=1001, delta=.5)
        with patch.object(repository, 'get_stockdata_db_path', return_value=str(self.path)):
            PriceFeedService._save_option_last_prices_to_db_sync(service, [row])
            PriceFeedService._save_option_last_prices_to_db_sync(service, [dict(row,last_px=2.6)])
        def read():
            with connect_stockdata(self.path) as conn:
                return [tuple(r) for r in conn.execute('SELECT series_id,last_price,mid_price,asset_rollup '
                    'FROM option_last_prices')]
        self.assertEqual(self.job(read), [(1, 2.6, 2.5, 'A')])
        self.assertEqual(workers.worker_for(self.path).stats()['physical_opens'], 1)


if __name__ == '__main__':
    unittest.main()
