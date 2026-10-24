import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import subprocess
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
from unittest.mock import Mock
import polars as pl
from PySide6.QtWidgets import QApplication
from portefeuille_viewer.data.snapshot_store import SnapshotStore
from portefeuille_viewer.services import projection_worker as module


class InputSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait(self, condition):
        end = time.monotonic() + 4
        while not condition() and time.monotonic() < end:
            self.app.processEvents(); time.sleep(.002)
        self.assertTrue(condition())

    def test_copy_on_gui_thread_worker_sees_stable_nested_inputs(self):
        store = SnapshotStore()
        store.repository_snapshot_test_orders_cache = {'asset': {'quantity': 1}}
        gui = threading.get_ident(); captured = []; observed = []
        ready = threading.Event(); release = threading.Event()
        original = store.capture_inputs
        def capture():
            captured.append(threading.get_ident())
            return original()
        def compute(request):
            ready.set(); release.wait(3)
            observed.append(store.repository_snapshot_test_orders_cache['asset']['quantity'])
        with patch.object(module, 'SNAPSHOT_STORE', store), patch.object(store, 'capture_inputs', side_effect=capture):
            worker = module.ProjectionWorker(compute)
            worker.submit('runtime', dict(all=True, names=set(), keys=set(), reason='test'))
            self.assertTrue(ready.wait(1))
            store.repository_snapshot_test_orders_cache['asset']['quantity'] = 99
            release.set(); self.wait(lambda: not worker.busy)
            self.assertEqual(captured, [gui]); self.assertEqual(observed, [1])
            worker.shutdown()

    def test_callbacks_wait_for_publication_and_survive_request_merging(self):
        store = SnapshotStore(); ready = threading.Event(); release = threading.Event(); calls = []
        count = []
        def compute(request):
            count.append(1)
            if len(count) == 1:
                ready.set(); release.wait(3)
            store.safe_write('snapshot_aandelen_projection_v2', pl.DataFrame({'n': [len(count)]}))
        def callback(label):
            return lambda: calls.append((label, store.snapshot_aandelen_projection_v2['n'][0], threading.get_ident()))
        with patch.object(module, 'SNAPSHOT_STORE', store):
            worker = module.ProjectionWorker(compute)
            req = dict(all=True, names=set(), keys=set(), reason='test')
            worker.submit('runtime', {**req, 'callbacks': [callback('first')]})
            self.assertTrue(ready.wait(1)); self.assertEqual(calls, [])
            worker.submit('runtime', {**req, 'callbacks': [callback('second')]})
            worker.submit('runtime', {**req, 'callbacks': [callback('third')]})
            release.set(); self.wait(lambda: not worker.busy and not worker.pending)
            self.assertEqual(calls, [('first', 1, threading.get_ident()), ('second', 2, threading.get_ident()), ('third', 2, threading.get_ident())])
            worker.shutdown()

    def test_state_scripts_require_explicit_database_before_opening_it(self):
        root = Path(__file__).parents[1]
        scripts = ['create_state_engine_tables.py', 'debug_open_optie_v2.py',
                   'open_aandelen_state_v2.py', 'open_opties_state_v2.py',
                   'open_sprinters_state_v2.py', 'per_dag_asset_result_v2.py',
                   'validate_open_opties_v2_vs_v1.py']
        for script in scripts:
            with self.subTest(script=script):
                result = subprocess.run([sys.executable, str(root / 'state_engine' / script)],
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn('--db', result.stderr)
                self.assertIn('required', result.stderr)

    def test_overlay_seed_is_marked_only_after_actual_result_publication(self):
        from devtools.test_refresh_policy import main_callback
        store = SnapshotStore(); ready = threading.Event(); release = threading.Event()
        namespace = dict(SNAPSHOT_STORE=store, time=time, _log=Mock(),
                         _AANDELEN_TV_STARTUP_SEEDED=False)
        finish = main_callback('_finish_timevalue_seed', namespace)
        def compute(request):
            ready.set(); release.wait(3)
            store.safe_write('snapshot_aandelen_projection_v2',
                             pl.DataFrame({'optie_tijdswaarde_signed_eur': [17.]}))
        with patch.object(module, 'SNAPSHOT_STORE', store):
            worker = module.ProjectionWorker(compute)
            namespace.update(_PROJECTION_WORKER=worker, _PROJECTION_COVERAGE=Mock())
            main_callback('_runtime_recompute_selected', namespace)
            refresh = main_callback('refresh_aandelen_projection', namespace)
            refresh('startup_timevalue_seed', {'__TIMEVALUE_OVERLAY__'}, on_published=finish)
            self.assertTrue(ready.wait(1))
            self.assertFalse(namespace['_AANDELEN_TV_STARTUP_SEEDED'])
            release.set(); self.wait(lambda: not worker.busy)
            self.assertTrue(namespace['_AANDELEN_TV_STARTUP_SEEDED'])
            self.assertGreater(namespace['_AANDELEN_TV_SEED_TS'], 0)
            worker.shutdown()

    def test_failed_projection_cannot_acknowledge_an_old_overlay_result(self):
        from devtools.test_refresh_policy import main_callback
        publish = main_callback('_publish_runtime_projection_results', {})
        with self.assertRaisesRegex(RuntimeError, 'aandelen_v2: intentional'):
            publish([SimpleNamespace(success=False, projection_name='aandelen_v2', error='intentional')], 'test')


if __name__ == '__main__':
    unittest.main()
