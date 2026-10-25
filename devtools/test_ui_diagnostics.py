import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from portefeuille_viewer.services.ui_diagnostics import UiDiagnostics, start_ui_diagnostics


class UiDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_wrapping_preserves_result_errors_and_restores_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            monitor = UiDiagnostics(self.app, tmp, 'test', sample_seconds=.1)
            namespace = {'ok': lambda secret: secret+1}
            original = namespace['ok']
            monitor.wrap(namespace, 'ok', 'operation')
            try:
                self.assertEqual(namespace['ok'](7), 8)
                def fail(secret):
                    raise ValueError(secret)
                namespace['fail'] = fail
                monitor.wrap(namespace, 'fail', 'failure')
                with self.assertRaises(ValueError):
                    namespace['fail']('SECRET_PORTFOLIO_CONTENT')
            finally:
                monitor.stop()
            self.assertIs(namespace['ok'], original)
            text = monitor.path.read_text(encoding='utf-8')
            self.assertNotIn('SECRET_PORTFOLIO_CONTENT', text)
            records = [json.loads(line) for line in text.splitlines()]
            metrics = [a for record in records for a in record['actions']]
            self.assertEqual(next(a for a in metrics if a['name']=='failure')['errors'], 1)
            self.assertTrue(records[-1]['final'])

    def test_worker_calls_are_distinguished_and_buffer_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            monitor = UiDiagnostics(self.app, tmp, 'test', sample_seconds=30)
            try:
                thread = threading.Thread(target=lambda: monitor.record('worker', .01))
                thread.start(); thread.join()
                for i in range(300):
                    monitor.mark_event('test', n=i)
                self.assertEqual(len(monitor.events), 128)
            finally:
                monitor.stop()
            record = json.loads(monitor.path.read_text(encoding='utf-8').splitlines()[-1])
            self.assertGreater(record['dropped'], 0)
            self.assertFalse(next(a for a in record['actions'] if a['name']=='worker')['gui'])

    def test_blocked_event_loop_is_recorded_without_ui_file_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            monitor = UiDiagnostics(self.app, tmp, 'test', sample_seconds=.1)
            try:
                time.sleep(1.2)  # No processEvents: intentional GUI delay.
                monitor.heartbeat()
            finally:
                monitor.stop()
            records = [json.loads(line) for line in monitor.path.read_text(encoding='utf-8').splitlines()]
            events = [event for record in records for event in record['events']]
            self.assertTrue(any(e['type']=='ui_unresponsive_sample' for e in events))
            actions = [a for record in records for a in record['actions']]
            self.assertGreater(next(a for a in actions if a['name']=='qt.heartbeat_delay')['max_ms'], 500)

    def test_disabled_mode_creates_no_session(self):
        with patch.dict(os.environ, {'PV_UI_DIAGNOSTICS':'0'}):
            self.assertIsNone(start_ui_diagnostics(self.app, {}))

    def test_resource_sample_does_not_submit_database_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            monitor = UiDiagnostics(self.app, tmp, 'test', sample_seconds=30)
            try:
                with patch('portefeuille_viewer.data.stockdata_worker.worker_for',
                           side_effect=AssertionError('diagnostics must not open a database')):
                    sample = monitor.sample_process()
                self.assertIn('stockdata_workers', sample)
                if os.name == 'nt':
                    self.assertGreaterEqual(sample['gdi_objects'], 0)
            finally:
                monitor.stop()

    def test_cache_probe_records_reuse_without_changing_results(self):
        class Cache:
            value = None
            def get(self, history, assets, build, **kwargs):
                if self.value is None:
                    self.value = build()
                return self.value
        with tempfile.TemporaryDirectory() as tmp:
            monitor = UiDiagnostics(self.app, tmp, 'test', sample_seconds=30)
            original = Cache.get
            monitor.wrap_history_cache(Cache)
            try:
                cache = Cache()
                self.assertEqual(cache.get(None, [], lambda: {'score':7}), {'score':7})
                self.assertEqual(cache.get(None, [], lambda: {'score':99}), {'score':7})
            finally:
                monitor.stop()
            self.assertIs(Cache.get, original)
            records = [json.loads(line) for line in monitor.path.read_text(encoding='utf-8').splitlines()]
            events = [event for record in records for event in record['events'] if event['type']=='historical_cache']
            self.assertEqual([event['reused'] for event in events], [False, True])


if __name__ == '__main__':
    unittest.main()
