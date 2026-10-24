import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import polars as pl
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from portefeuille_viewer.data.snapshot_store import SnapshotStore
from portefeuille_viewer.services import projection_worker
from portefeuille_viewer.services import history_indicator_runner as module


class HistoryIndicatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait(self, condition):
        end = time.monotonic()+4
        while not condition() and time.monotonic()<end:
            self.app.processEvents(); time.sleep(.002)
        self.assertTrue(condition())

    def test_history_and_calculation_off_gui_publish_atomically_and_keep_ui_alive(self):
        store = SnapshotStore(); ids=[]; pulses=[]; publications=[]
        gui=threading.get_ident()
        old=pl.DataFrame({'close':[10.]})
        store.repository_snapshot_historical_ohlcv=old
        def load():
            ids.append(threading.get_ident());time.sleep(.08)
            store.safe_write('repository_snapshot_historical_ohlcv',pl.DataFrame({'close':[20.]}))
        def calculate(**kwargs):
            ids.append(threading.get_ident());time.sleep(.08)
            self.assertEqual(store.repository_snapshot_historical_ohlcv['close'][0],20.)
            store.safe_write('snapshot_asset_indicator_live',pl.DataFrame({'score':[7]}))
            return SimpleNamespace(status='ok')
        timer=QTimer();timer.setInterval(10);timer.timeout.connect(lambda:pulses.append(1));timer.start()
        try:
            with patch.object(projection_worker,'SNAPSHOT_STORE',store), \
                 patch.object(module.repository,'load_historical_ohlcv_snapshot',side_effect=load), \
                 patch.object(module,'rebuild_asset_indicator_snapshots',side_effect=calculate):
                runner=module.HistoryIndicatorRunner()
                runner.finished.connect(lambda payload:publications.append((threading.get_ident(),store.snapshot_asset_indicator_live['score'][0])))
                runner.request(reload_history=True)
                self.assertIs(store.repository_snapshot_historical_ohlcv,old)
                self.wait(lambda:not runner.worker.busy)
                self.assertTrue(all(tid!=gui for tid in ids));self.assertEqual(len(set(ids)),1)
                self.assertEqual(publications,[(gui,7)]);self.assertGreater(len(pulses),4)
                runner.shutdown()
        finally:timer.stop()

    def test_burst_is_serialized_with_all_required_operations_retained(self):
        store=SnapshotStore();ready=threading.Event();release=threading.Event();count=[]
        def calculate(**kwargs):
            count.append(1)
            if len(count)==1:ready.set();release.wait(3)
            return SimpleNamespace(status='ok')
        with patch.object(projection_worker,'SNAPSHOT_STORE',store), \
             patch.object(module,'rebuild_asset_indicator_snapshots',side_effect=calculate), \
             patch.object(module.repository,'load_historical_ohlcv_snapshot') as history, \
             patch.object(module.repository,'load_asset_driver_beta_snapshot') as beta:
            runner=module.HistoryIndicatorRunner();runner.request()
            self.assertTrue(ready.wait(1))
            runner.request(reload_history=True,rebuild_indicators=False)
            runner.request(reload_beta=True)
            for _ in range(30):runner.request()
            self.assertEqual(len(runner.worker.pending),1)
            release.set();self.wait(lambda:not runner.worker.busy and not runner.worker.pending)
            self.assertEqual(len(count),2);history.assert_called_once();beta.assert_called_once()
            runner.shutdown()

    def test_failure_keeps_old_snapshots_and_recovers(self):
        store=SnapshotStore();old=pl.DataFrame({'score':[9]});store.snapshot_asset_indicator_live=old
        errors=[];success=[]
        def calculate(**kwargs):
            store.safe_write('snapshot_asset_indicator_live',pl.DataFrame())
            return SimpleNamespace(status='error',error='intentional')
        with patch.object(projection_worker,'SNAPSHOT_STORE',store), \
             patch.object(module,'rebuild_asset_indicator_snapshots',side_effect=calculate), \
             patch.object(module.repository,'load_historical_ohlcv_snapshot'):
            runner=module.HistoryIndicatorRunner()
            runner.request(on_failed=errors.append,on_published=lambda:success.append(1))
            self.wait(lambda:not runner.worker.busy)
            self.assertEqual(errors,['intentional']);self.assertEqual(success,[])
            self.assertIs(store.snapshot_asset_indicator_live,old)
            runner.request(rebuild_indicators=False,reload_history=True,on_published=lambda:success.append(1))
            self.wait(lambda:not runner.worker.busy)
            self.assertEqual(success,[1])
            runner.shutdown()

    def test_pipeline_finished_is_delayed_until_history_is_published(self):
        from portefeuille_viewer.services import single_asset_long_history_runner as pipeline
        store=SnapshotStore();ready=threading.Event();release=threading.Event()
        def load():ready.set();release.wait(3)
        with patch.object(projection_worker,'SNAPSHOT_STORE',store), \
             patch.object(module.repository,'load_historical_ohlcv_snapshot',side_effect=load), \
             patch.object(module,'rebuild_asset_indicator_snapshots',return_value=SimpleNamespace(status='ok')):
            runner=module.HistoryIndicatorRunner()
            owner=SimpleNamespace(output=Mock(),finished=Mock(),failed=Mock())
            with patch.object(pipeline,'get_history_indicator_runner',return_value=runner):
                pipeline._refresh_after_pipeline(owner,{'status':'ok'},'done')
            self.assertTrue(ready.wait(1));self.assertTrue(owner._refresh_pending)
            owner.finished.emit.assert_not_called()
            release.set();self.wait(lambda:not runner.worker.busy)
            self.assertFalse(owner._refresh_pending);owner.finished.emit.assert_called_once_with({'status':'ok'})
            runner.shutdown()

    def test_tab_button_uses_same_runner_and_restores_controls_after_publication(self):
        from portefeuille_viewer.ui_logica.asset_indicator_web_tab import AssetIndicatorWebTab as Tab
        store=SnapshotStore();ready=threading.Event();release=threading.Event()
        def calculate(**kwargs):
            ready.set();release.wait(3)
            return SimpleNamespace(status='ok',assets_total=3,assets_scored=2,
                                   assets_insufficient_data=1,duration_ms=100.)
        with patch.object(projection_worker,'SNAPSHOT_STORE',store), \
             patch.object(module,'rebuild_asset_indicator_snapshots',side_effect=calculate):
            runner=module.HistoryIndicatorRunner()
            tab=SimpleNamespace(_runner=runner,btn_run=Mock(),status_label=Mock(),storage_label=Mock(),_publish_snapshot=Mock(),_schedule_render=Mock())
            runner.started.connect(lambda request:Tab._on_run_started(tab,request))
            runner.finished.connect(lambda payload:Tab._on_run_finished(tab,payload))
            Tab.run_indicator(tab)
            self.assertTrue(ready.wait(1))
            tab.btn_run.setEnabled.assert_called_with(False)
            tab._publish_snapshot.assert_not_called()
            release.set();self.wait(lambda:not runner.worker.busy)
            tab.btn_run.setEnabled.assert_called_with(True)
            tab._schedule_render.assert_called_once()
            tab._publish_snapshot.assert_not_called()
            self.assertIn('OK',tab.status_label.setText.call_args.args[0])
            runner.shutdown()


if __name__=='__main__':unittest.main()
