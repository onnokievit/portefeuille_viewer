import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from datetime import datetime
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import polars as pl
from PySide6.QtWidgets import QApplication
from portefeuille_viewer.data.snapshot_store import SnapshotStore
from portefeuille_viewer.services import asset_indicator_service as service
from portefeuille_viewer.services import history_indicator_runner as module
from portefeuille_viewer.services import projection_worker
from portefeuille_viewer.services.indicator_history_writer import IndicatorHistoryWriter


class BackgroundSaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def wait(self, condition):
        end=time.monotonic()+4
        while not condition() and time.monotonic()<end:
            self.app.processEvents();time.sleep(.002)
        self.assertTrue(condition())

    def test_publication_and_next_calculation_do_not_wait_for_database_save(self):
        store=SnapshotStore();entered=threading.Event();release=threading.Event()
        published=[];saved=[];gui=threading.get_ident();count=[]
        def calculate(**kwargs):
            self.assertFalse(kwargs['persist_history'])
            count.append(1)
            store.safe_write('snapshot_asset_indicator_live',pl.DataFrame({'score':[len(count)]}))
            store.safe_write('snapshot_asset_indicator_meta',pl.DataFrame({'last_run_at':[datetime(2026,1,1)]}))
            return service.AssetIndicatorRunResult(str(len(count)),'ok',1,1,0,10.,
                historical_df=store.snapshot_asset_indicator_live.clone())
        def save(**payload):
            self.assertNotEqual(threading.get_ident(),gui)
            self.assertTrue(published)
            entered.set();release.wait(3)
            saved.append((payload['run_id'],payload['live_df']['score'][0]))
        runner=None
        try:
            with patch.object(projection_worker,'SNAPSHOT_STORE',store), \
                 patch.object(module,'rebuild_asset_indicator_snapshots',side_effect=calculate), \
                 patch.object(service,'_persist_signal_history',side_effect=save):
                runner=module.HistoryIndicatorRunner()
                runner.finished.connect(lambda payload:published.append(store.snapshot_asset_indicator_live['score'][0]))
                runner.request();self.wait(lambda:len(published)==1)
                self.assertTrue(entered.wait(1));self.assertEqual(saved,[])
                runner.request();self.wait(lambda:len(published)==2)
                self.assertEqual(store.snapshot_asset_indicator_live['score'][0],2)
                self.assertEqual(saved,[])
                release.set();self.wait(lambda:not runner.writer.busy)
                self.assertEqual(saved,[('1',1),('2',2)])
        finally:
            release.set()
            if runner is not None:runner.shutdown()

    def test_failed_save_reports_error_and_preserves_visible_results(self):
        store=SnapshotStore();statuses=[];calculation_errors=[]
        def calculate(**kwargs):
            store.safe_write('snapshot_asset_indicator_live',pl.DataFrame({'score':[7]}))
            store.safe_write('snapshot_asset_indicator_meta',pl.DataFrame({'last_run_at':[datetime(2026,1,1)]}))
            return service.AssetIndicatorRunResult('run','ok',1,1,0,10.,
                historical_df=store.snapshot_asset_indicator_live.clone())
        with patch.object(projection_worker,'SNAPSHOT_STORE',store), \
             patch.object(module,'rebuild_asset_indicator_snapshots',side_effect=calculate), \
             patch.object(service,'_persist_signal_history',side_effect=OSError('intentional')), \
             self.assertLogs(level='ERROR'):
            runner=module.HistoryIndicatorRunner()
            try:
                runner.storage_status.connect(statuses.append)
                runner.failed.connect(calculation_errors.append)
                runner.request()
                self.wait(lambda:any(s['status']=='error' for s in statuses))
                self.assertEqual(store.snapshot_asset_indicator_live['score'][0],7)
                self.assertEqual(calculation_errors,[])
            finally:runner.shutdown()

    def test_closing_drains_already_accepted_jobs_without_qt_callbacks(self):
        entered=threading.Event();release=threading.Event();saved=[]
        def save(**payload):
            entered.set();release.wait(3);saved.append(payload['run_id'])
        writer=IndicatorHistoryWriter()
        with patch.object(service,'_persist_signal_history',side_effect=save):
            try:
                writer.enqueue({'run_id':'1'});self.assertTrue(entered.wait(1))
                writer.enqueue({'run_id':'2'});writer.close();release.set()
                end=time.monotonic()+3
                while writer.busy and time.monotonic()<end:time.sleep(.005)
                self.assertEqual(saved,['1','2'])
            finally:release.set();writer.close()

    def test_old_save_status_cannot_overwrite_new_run_status(self):
        from portefeuille_viewer.ui_logica.asset_indicator_web_tab import AssetIndicatorWebTab
        tab=SimpleNamespace(_last_run_id='new',storage_label=Mock())
        AssetIndicatorWebTab._on_storage_status(tab,{'run_id':'old','status':'error','error':'old failure'})
        tab.storage_label.setText.assert_not_called()
        AssetIndicatorWebTab._on_storage_status(tab,{'run_id':'new','status':'saving'})
        tab.storage_label.setText.assert_called_once_with('Opslaan...')

    def test_strict_persistence_propagates_connection_errors(self):
        with patch.object(module.repository,'get_stockdata_connection',side_effect=OSError('intentional')):
            with self.assertRaises(OSError):
                service._persist_signal_history(run_id='x',started_at=datetime.now(),duration_ms=0,
                    status='ok',error='',live_df=pl.DataFrame({'score':[1]}),raise_errors=True)


if __name__=='__main__':unittest.main()
