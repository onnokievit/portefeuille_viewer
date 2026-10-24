import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import threading
import time
import unittest
from unittest.mock import patch
from unittest.mock import Mock
from types import SimpleNamespace
from datetime import date
import polars as pl
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from portefeuille_viewer.data.snapshot_store import SnapshotStore
from portefeuille_viewer.services import projection_worker as module


class SchedulingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait(self, condition, seconds=3):
        end=time.monotonic()+seconds
        while not condition() and time.monotonic()<end:
            self.app.processEvents();time.sleep(.002)
        self.assertTrue(condition())

    def test_continuous_events_cannot_postpone_deadline(self):
        fired=[]
        timer=QTimer();timer.setSingleShot(True);timer.setInterval(30)
        timer.timeout.connect(lambda:fired.append(time.monotonic()))
        spam=QTimer();spam.setInterval(3)
        spam.timeout.connect(lambda:module.start_bounded_timer(timer))
        spam.start()
        try:self.wait(lambda:len(fired)>=3)
        finally:spam.stop();timer.stop()

    def test_one_worker_and_one_merged_followup_publish_on_gui(self):
        store=SnapshotStore();started=threading.Event();release=threading.Event();calls=[];publish_threads=[]
        gui=threading.get_ident()
        def compute(request):
            calls.append((threading.get_ident(),request))
            if len(calls)==1:
                started.set();release.wait(2)
            store.safe_write('snapshot_aandelen_projection_v2',pl.DataFrame({'n':[len(calls)]}))
        original=store.publish_batch
        def publish(values):
            publish_threads.append(threading.get_ident());original(values)
        with patch.object(module,'SNAPSHOT_STORE',store),patch.object(store,'publish_batch',side_effect=publish):
            worker=module.ProjectionWorker(compute)
            req=lambda name:{'all':False,'names':{name},'keys':{name},'reason':name}
            worker.submit('runtime',req('first'));self.assertTrue(started.wait(1))
            for i in range(30):worker.submit('runtime',req(str(i)))
            self.assertEqual(len(worker.pending),1)
            release.set();self.wait(lambda:not worker.busy and not worker.pending)
            self.assertEqual(len(calls),2)
            self.assertTrue(all(tid!=gui for tid,_ in calls))
            self.assertEqual(publish_threads,[gui,gui])
            self.assertEqual(calls[1][1]['names'],{str(i) for i in range(30)})
            worker.shutdown()

    def test_inputs_remain_frozen_and_followup_gets_new_input(self):
        store=SnapshotStore();store.live_prices={('ABC','USD'):10}
        with store.capture_writes(freeze_inputs=True,skip_unchanged=True) as values:
            # Simulate a main-thread publication using the underlying dictionary.
            store.__dict__['live_prices']={('ABC','USD'):20}
            self.assertEqual(store.get_live_prices_snapshot()[('ABC','USD')],10)
            store.safe_write('snapshot_aandelen_projection_v2',pl.DataFrame({'price':[10]}))
            self.assertEqual(store.snapshot_aandelen_projection_v2['price'][0],10)
        self.assertEqual(store.live_prices[('ABC','USD')],20)
        self.assertIsNone(getattr(store, "snapshot_aandelen_projection_v2", None))
        store.publish_batch(values)
        with store.capture_writes(freeze_inputs=True,skip_unchanged=True) as unchanged:
            store.safe_write('snapshot_aandelen_projection_v2',pl.DataFrame({'price':[10]}))
        self.assertEqual(unchanged,{})

    def test_failed_job_does_not_block_followup(self):
        store=SnapshotStore();count=[];errors=[]
        def compute(request):
            count.append(1)
            if len(count)==1:raise ValueError('intentional')
            store.safe_write('snapshot_aandelen_projection_v2',pl.DataFrame({'ok':[True]}))
        with patch.object(module,'SNAPSHOT_STORE',store):
            worker=module.ProjectionWorker(compute);worker.failed.connect(errors.append)
            req={'all':True,'names':set(),'keys':set(),'reason':'test'}
            worker.submit('runtime',req);worker.submit('runtime',req)
            self.wait(lambda:len(count)==2 and not worker.busy)
            self.assertEqual(errors,['intentional'])
            self.assertTrue(store.snapshot_aandelen_projection_v2['ok'][0])
            worker.shutdown()

    def test_unchanged_option_tick_does_not_schedule_more_work(self):
        from portefeuille_viewer.services.option_timevalue_service import OptionTimevalueService
        timer=Mock();timer.isActive.return_value=False
        service=SimpleNamespace(_ticks={},_lock=threading.Lock(),_publish_timer=timer,_publish_dirty=False)
        tick={'series_id':1,'field':'last','value':10.}
        OptionTimevalueService._on_option_tick(service,tick)
        timer.start.assert_called_once()
        OptionTimevalueService._on_option_tick(service,tick)
        timer.start.assert_called_once()
        self.assertTrue(service._publish_dirty)

    def test_idle_timevalue_heartbeat_skips_calculation(self):
        from portefeuille_viewer.services.option_timevalue_service import OptionTimevalueService
        # Deliberately has no calculation inputs: an idle heartbeat must return first.
        service=SimpleNamespace(_publish_dirty=False,_last_publish_date=date.today())
        OptionTimevalueService._publish_snapshot(service,'full_publish_timer')

    def test_unchanged_frame_does_not_emit_snapshot_event(self):
        store=SnapshotStore();frame=pl.DataFrame({'x':[1]})
        store.repository_snapshot_asset_rollup_data=frame
        with patch.object(store,'safe_write') as write:
            self.assertFalse(store.safe_write_if_changed('repository_snapshot_asset_rollup_data',frame.clone()))
            write.assert_not_called()


if __name__=='__main__':unittest.main()
