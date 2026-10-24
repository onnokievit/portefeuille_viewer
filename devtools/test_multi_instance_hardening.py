"""Concurrency checks with synthetic Access files and a fake, network-free feed."""
import base64
from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QCoreApplication, QObject, Signal, QTimer, QProcess
from portefeuille_viewer.data.shared_database import connect_stockdata, read_versions
from portefeuille_viewer.services.price_feed import PriceFeedIB
from portefeuille_viewer.services.shared_quote_coordinator import QuoteHub, rpc, serve
from portefeuille_viewer.services.subscription_manager import SubscriptionManager


class FakeSignals(QObject):
    quoteReceived = Signal(str, str, float, dict)


class Transport:
    def __init__(self):
        self.next = 0
        self.active = set()
    def next_id(self):
        self.next += 1
        return self.next
    def start(self, request_id, spec, fallback):
        self.active.add(request_id)
    def cancel(self, request_id):
        self.active.discard(request_id)
    def details(self, *args):
        pass
    def forget_details(self, *args):
        pass
    def event(self, *args):
        pass


class FakeFeed(QObject):
    optionTickUpdated = Signal(dict)
    def __init__(self, host='fake', port=0, client_id=299, clock=time.time):
        super().__init__()
        self._feed = FakeSignals()
        self._feed.subscriptions = SubscriptionManager(Transport(), capacity=100, clock=clock)
        self._feed.subscriptions.reset(True)
        self.clock = clock
        self.series = []
        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
    def tick(self):
        self._feed.subscriptions.step()
        self._feed.quoteReceived.emit('SPCX', 'USD', 90.0, {'data_type':1})
    def ensure_subscriptions(self, rows):
        # Exercise the production normalizer and deduplication, not a copied one.
        PriceFeedIB.ensure_subscriptions(self._feed, rows)
    def ensure_option_subscriptions(self, rows):
        PriceFeedIB.ensure_option_subscriptions(self._feed, rows)
    def set_active_option_series_ids(self, ids):
        self.series = list(ids)
    def subscription_snapshot(self):
        return self._feed.subscriptions.snapshot()
    def configure_subscriptions(self, **values):
        self._feed.subscriptions.configure(**values)
    def connection_info(self):
        return {'status':'connected', 'is_ready':True, 'host':'fake', 'port':0, 'client_id':299}
    def shutdown(self):
        self.timer.stop()


# The normalizer is static and needs no network or DB.
FakeSignals._normalize_subscription_row = PriceFeedIB._normalize_subscription_row


class HubTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
    def setUp(self):
        self.now = 1000000.
        self.feed = FakeFeed(clock=lambda:self.now)
        self.feed.timer.stop()
        self.hub = QuoteHub(self.feed, clock=lambda:self.now)
        for key in ('onno', 'muriel', 'quinten'):
            self.command(key, 'join', profile=key)
    def command(self, key, op, **values):
        return self.hub.command({'client':key, 'op':op, **values})
    def asset(self, i):
        return (f'S{i}', 'USD', 'aandeel', 'SMART', '', i+1)
    def test_union_deduplicates_and_budget_is_global(self):
        for key in self.hub.clients:
            self.command(key, 'assets', rows=[self.asset(i) for i in range(150)])
        for _ in range(400):
            self.now += .2
            self.feed._feed.subscriptions.step()
        snapshot = self.command('onno','snapshot')
        self.assertEqual(len(snapshot['rows']),150)
        self.assertLessEqual(snapshot['occupied'],100)
        self.assertEqual(snapshot['occupied'],100)
        self.assertEqual(set(snapshot['shared_clients']), {'onno','muriel','quinten'})
    def test_first_client_can_leave_without_stopping_other_sources(self):
        self.command('onno','assets',rows=[self.asset(1)])
        self.command('muriel','assets',rows=[self.asset(1),self.asset(2)])
        self.command('onno','leave')
        self.assertEqual(len(self.command('muriel','snapshot')['rows']),2)
        self.hub.quote('SPCX','USD',90.,{'data_type':1})
        events=self.command('muriel','poll',since=0)['events']
        self.assertEqual(events[-1][2][1],90.)
    def test_option_contract_is_shared_with_all_series_ids(self):
        self.command('onno','options',rows=[(1,123,'SMART','USD','A')])
        self.command('muriel','options',rows=[(2,123,'SMART','USD','A')])
        rows=self.command('onno','snapshot')['rows']
        self.assertEqual(len(rows),1)
        record=next(iter(self.feed._feed.subscriptions.records.values()))
        self.assertEqual(set(record.spec['meta']['series_ids']),{1,2})
    def test_auxiliary_reservations_reduce_shared_feed_capacity_and_release(self):
        self.command('onno','reserve',amount=10)
        self.assertEqual(self.command('muriel','snapshot')['effective_capacity'],90)
        with self.assertRaises(RuntimeError):
            self.command('muriel','reserve',amount=100)
        self.command('onno','leave')
        self.assertEqual(self.command('muriel','snapshot')['effective_capacity'],100)
    def test_crashed_client_expires_and_survivor_keeps_subscription(self):
        self.command('onno','assets',rows=[self.asset(1)])
        self.command('muriel','assets',rows=[self.asset(2)])
        self.command('onno','reserve',amount=10)
        self.now += 11
        self.command('muriel','poll')
        self.hub.expire()
        self.assertEqual(list(self.hub.clients),['muriel'])
        self.assertEqual(len(self.command('muriel','snapshot')['rows']),1)
        self.assertEqual(self.hub.reserved,0)
    def test_failed_refresh_does_not_advance_watcher(self):
        from portefeuille_viewer.services.shared_data_watcher import SharedDataWatcher
        with patch('portefeuille_viewer.services.shared_data_watcher.get_stockdata_db_path',return_value='fake'):
            watcher=SharedDataWatcher()
        watcher.timer.stop()
        watcher.versions={'asset_rollup_data':1}
        with self.assertLogs(level='WARNING'):
            watcher._publish(None,'temporary read failure',None)
        self.assertEqual(watcher.versions,{'asset_rollup_data':1})
        watcher.stop()

    def test_idle_watcher_skips_access_but_hint_and_fallback_still_probe(self):
        from portefeuille_viewer.services import shared_data_watcher as module
        now=[10.0];token=['first']
        with patch.object(module,'get_stockdata_db_path',return_value='fake'), patch.object(module,'read_hint',side_effect=lambda path:token[0]), patch.object(module,'read_versions',return_value={}) as read, patch.object(module,'time',SimpleNamespace(monotonic=lambda:now[0])):
            watcher=module.SharedDataWatcher();watcher.timer.stop()
            def poll():
                watcher.poll()
                for _ in range(500):
                    self.app.processEvents()
                    if not watcher.busy:break
                    time.sleep(.002)
                self.assertFalse(watcher.busy)
            poll();self.assertEqual(read.call_count,1)
            now[0]=12;poll();self.assertEqual(read.call_count,1)
            token[0]='changed';poll();self.assertEqual(read.call_count,2)
            now[0]=73;poll();self.assertEqual(read.call_count,3)
            watcher.invalidate();poll();self.assertEqual(read.call_count,4)
            watcher.stop()
    def test_snapshot_staging_exposes_only_complete_batch(self):
        from portefeuille_viewer.data.snapshot_store import SnapshotStore
        store=SnapshotStore()
        with store.capture_writes() as values:
            store.safe_write('repository_snapshot_asset_rollup_data','new')
            self.assertIsNone(store.repository_snapshot_asset_rollup_data)
        store.publish_batch(values)
        self.assertEqual(store.repository_snapshot_asset_rollup_data,'new')

    def test_received_proxy_quote_updates_memory_without_dirtying_database(self):
        from portefeuille_viewer.data.asset_last_price_store import AssetLastPriceStore
        store=AssetLastPriceStore()
        store.update_price('SPCX','USD',90.,persist=False)
        self.assertEqual(store.get_snapshot()[('SPCX','USD')],90.)
        self.assertEqual(store.save_to_db(force=True),0)

    def test_late_contract_answer_cannot_resolve_a_different_attempt(self):
        from datetime import date
        from portefeuille_viewer.services.option_timevalue_service import OptionTimevalueService, OpenSeriesRow
        previous=[]
        def request(contract, detail, end):
            if not previous:
                previous.append(detail);end();return
            previous[0](SimpleNamespace(contract=SimpleNamespace(conId=777)))
            detail(SimpleNamespace(contract=SimpleNamespace(conId=888)))
            end()
        connection=MagicMock()
        connection.__enter__.return_value=connection
        service=SimpleNamespace(price_feed=SimpleNamespace(_feed=SimpleNamespace(request_contract_details=request)),
            _resolve_wait_sec=.01, _series_key=lambda row:row.series_id,
            _connect_stockdb=lambda:connection)
        row=OpenSeriesRow('broker','TEST','TEST','USD','call',100.,date(2027,1,15),1.,'SMART','TEST',100.,series_id=1)
        self.assertEqual(OptionTimevalueService._resolve_contracts(service,[row]),{})
        self.assertEqual(connection.cursor.return_value.execute.call_args.args[1][0],888)


class AccessConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])
        cls.temp=tempfile.TemporaryDirectory(prefix='pv-concurrency-test-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.path=Path(cls.temp.name)/'synthetic.accdb'
        escaped=str(cls.path).replace("'","''")
        script=f"$e=New-Object -ComObject DAO.DBEngine.120; $d=$e.CreateDatabase('{escaped}', ';LANGID=0x0409;CP=1252;COUNTRY=0',128); $d.Execute('CREATE TABLE counter_test (id LONG PRIMARY KEY, amount LONG)'); $d.Execute('INSERT INTO counter_test VALUES (1,0)'); $d.Close()"
        encoded=base64.b64encode(script.encode('utf-16-le')).decode('ascii')
        subprocess.run(['powershell','-NoProfile','-NonInteractive','-EncodedCommand',encoded],check=True,capture_output=True,timeout=30)
    def value(self):
        with connect_stockdata(self.path) as c:
            return c.execute('SELECT amount FROM counter_test WHERE id=1').fetchone()[0]
    def test_rollback_preserves_rows_and_revisions(self):
        from portefeuille_viewer.data.shared_change_hint import hint_path,read_hint
        before=read_versions(self.path)
        hint_before=read_hint(hint_path(self.path))
        value=self.value()
        with self.assertRaisesRegex(RuntimeError,'abort'):
            with connect_stockdata(self.path) as c:
                c.execute('DELETE FROM counter_test')
                raise RuntimeError('abort')
        self.assertEqual(self.value(),value)
        self.assertEqual(read_versions(self.path),before)
        self.assertEqual(read_hint(hint_path(self.path)),hint_before)
    def test_explicit_commit_is_visible_before_context_exit(self):
        from portefeuille_viewer.data.shared_change_hint import hint_path,read_hint
        hint_before=read_hint(hint_path(self.path))
        with connect_stockdata(self.path) as c:
            c.execute('UPDATE counter_test SET amount=amount+1 WHERE id=1')
            c.commit()
            self.assertGreater(self.value(),0)
        self.assertGreater(read_versions(self.path)['counter_test'],0)
        self.assertNotEqual(read_hint(hint_path(self.path)),hint_before)
    def test_three_processes_serialize_read_modify_write(self):
        before=self.value()
        code="from portefeuille_viewer.data.shared_database import connect_stockdata; import sys,time;\nfor i in range(8):\n with connect_stockdata(sys.argv[1]) as c:\n  c.begin_write(); n=c.execute('SELECT amount FROM counter_test WHERE id=1').fetchone()[0]; time.sleep(.015); c.execute('UPDATE counter_test SET amount=? WHERE id=1',n+1)"
        env={**os.environ,'PYTHONPATH':str(ROOT)}
        workers=[subprocess.Popen([sys.executable,'-c',code,str(self.path)],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(3)]
        for worker in workers:
            out,err=worker.communicate(timeout=40)
            self.assertEqual(worker.returncode,0,out+err)
        self.assertEqual(self.value(),before+24)
    def test_replacement_has_no_intermediate_commit(self):
        before=read_versions(self.path).get('counter_test',0)
        with connect_stockdata(self.path) as c:
            c.execute('DELETE FROM counter_test')
            c.execute('INSERT INTO counter_test VALUES (1,42)')
        self.assertEqual(self.value(),42)
        self.assertEqual(read_versions(self.path)['counter_test'],before+1)

    def test_master_rebuild_is_idempotent_and_resolution_holds_no_writer_lock(self):
        from datetime import date
        from portefeuille_viewer.services.option_timevalue_service import OptionTimevalueService, OpenSeriesRow
        with connect_stockdata(self.path) as c:
            c.execute('CREATE TABLE option_series_master (series_id COUNTER PRIMARY KEY, asset_rollup TEXT(50), underlying_symbol TEXT(50), strike DOUBLE, expiry DATETIME, exchange_code TEXT(50), trading_class TEXT(50), multiplier DOUBLE, ib_currency TEXT(10), optie_call_put TEXT(10), source_tag TEXT(50), resolver_locked YESNO, active YESNO, created_at DATETIME, updated_at DATETIME, conid LONG, local_symbol TEXT(50))')
        row=OpenSeriesRow('broker','TEST','TEST','USD','call',100.,date(2027,1,15),1.,'SMART','TEST',100.)
        def resolve(rows):
            code="import sys;from portefeuille_viewer.config.process_lock import ProcessLock,canonical_path;l=ProcessLock('stock-writer:'+canonical_path(sys.argv[1]));assert l.acquire();l.release()"
            result=subprocess.run([sys.executable,'-c',code,str(self.path)],cwd=ROOT,env={**os.environ,'PYTHONPATH':str(ROOT)},capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            with connect_stockdata(self.path) as c:
                c.execute('UPDATE option_series_master SET conid=123 WHERE series_id=?',rows[0].series_id)
            return {}
        service=SimpleNamespace(_connect_stockdb=lambda:connect_stockdata(self.path),
            _ensure_option_series_master_columns=lambda cur:None, _unresolved_series={},
            _series_key=lambda r:(r.asset_rollup,r.strike), _resolve_contracts=resolve,
            _set_unresolved=lambda *a:None, _clear_unresolved_for_resolved_rows=lambda rows:None)
        result=OptionTimevalueService._upsert_master_and_resolve(service,[row])
        self.assertEqual(result[0].conid,123)
        before=read_versions(self.path)
        OptionTimevalueService._upsert_master_and_resolve(service,[row])
        self.assertEqual(read_versions(self.path),before)

    def test_editor_refuses_a_stale_update(self):
        from portefeuille_viewer.data import asset_rollup_repository as editor
        with connect_stockdata(self.path) as c:
            names={r.table_name.lower() for r in c.cursor().tables()}
            if 'asset_rollup_data' not in names:
                c.execute('CREATE TABLE asset_rollup_data (Id COUNTER PRIMARY KEY, asset_rollup TEXT(50), sector TEXT(50))')
                c.execute("INSERT INTO asset_rollup_data (asset_rollup, sector) VALUES ('TEST','old')")
        with patch.object(editor.data_repository,'get_stockdata_connection',side_effect=lambda:connect_stockdata(self.path)), patch.object(editor,'_refresh_asset_rollup_snapshots'):
            original=editor.list_asset_rollup_rows()[0]
            with connect_stockdata(self.path) as c:
                c.execute("UPDATE asset_rollup_data SET sector='other user' WHERE Id=?",original['Id'])
            with self.assertRaisesRegex(RuntimeError,'andere instantie'):
                editor.upsert_asset_rollup_row({**original,'sector':'stale edit'})
            with connect_stockdata(self.path) as c:
                self.assertEqual(c.execute('SELECT sector FROM asset_rollup_data').fetchone()[0],'other user')

    def test_watcher_reloads_after_committed_change(self):
        from PySide6.QtWidgets import QApplication
        from portefeuille_viewer.services import shared_data_watcher as module
        from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
        app=QApplication.instance() or QApplication([])
        with connect_stockdata(self.path) as c:
            c.execute("UPDATE asset_rollup_data SET sector='watcher refresh'")
        with patch.object(module,'get_stockdata_db_path',return_value=str(self.path)), patch.object(module.repository,'get_stockdata_connection',side_effect=lambda:connect_stockdata(self.path)):
            watcher=module.SharedDataWatcher()
            watcher.timer.stop()
            seen=[];errors=[]
            watcher.refreshed.connect(seen.append)
            watcher.failed.connect(errors.append)
            watcher.poll()
            deadline=time.monotonic()+10
            while watcher.busy and time.monotonic()<deadline:
                app.processEvents();time.sleep(.01)
            watcher.stop()
            self.assertFalse(watcher.busy)
            self.assertEqual(errors,[])
            self.assertIn('asset_rollup_data',seen[0])
            frame=SNAPSHOT_STORE.repository_snapshot_asset_rollup_data
            self.assertEqual(frame['sector'][0],'watcher refresh')
            self.assertEqual(watcher.versions,read_versions(self.path))


class LeaseTests(unittest.TestCase):
    def test_maintenance_lease_is_exclusive_and_recovers_after_crash(self):
        from portefeuille_viewer.config.local_runtime import FileLease
        resource='test-maintenance-'+uuid4().hex
        with tempfile.TemporaryDirectory(prefix='pv-lease-test-') as temp, patch.dict(os.environ,{'PV_RUNTIME_ROOT':temp}):
            code="from portefeuille_viewer.config.local_runtime import FileLease;import sys,time; l=FileLease(sys.argv[1]);assert l.acquire();print('ready',flush=True);time.sleep(60)"
            worker=subprocess.Popen([sys.executable,'-c',code,resource],cwd=ROOT,env=os.environ.copy(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                self.assertEqual(worker.stdout.readline().strip(),'ready')
                lease=FileLease(resource)
                self.assertFalse(lease.acquire())
                worker.kill();worker.communicate(timeout=5)
                self.assertTrue(lease.acquire(2))
                # Qt completion may release a task claimed by a worker thread.
                thread=threading.Thread(target=lease.release);thread.start();thread.join(2)
                next_lease=FileLease(resource)
                self.assertTrue(next_lease.acquire())
                next_lease.release()
            finally:
                if worker.poll() is None:worker.kill();worker.communicate(timeout=5)

    def test_crashed_owner_kills_background_worker(self):
        import ctypes
        from ctypes import wintypes
        with tempfile.TemporaryDirectory(prefix='pv-job-test-') as temp:
            marker=Path(temp)/'child.json'
            code="""import os,sys,json
from PySide6.QtCore import QCoreApplication,QProcess,QTimer
from portefeuille_viewer.services.worker_guard import protect_worker
app=QCoreApplication([]);p=QProcess();guard=protect_worker(p)
p.setProgram(sys.executable);p.setArguments(['-c','import time;time.sleep(60)'])
def ready():
 if p._pv_worker_job.handle is None:os._exit(7)
 with open(sys.argv[1],'w') as f:json.dump(int(p.processId()),f)
 QTimer.singleShot(150,lambda:os._exit(0))
p.started.connect(ready);p.start();QTimer.singleShot(10000,lambda:os._exit(9));app.exec()
"""
            env={**os.environ,'PYTHONPATH':str(ROOT)}
            owner=subprocess.Popen([sys.executable,'-c',code,str(marker)],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            out,err=owner.communicate(timeout=15)
            self.assertEqual(owner.returncode,0,out+err)
            pid=json.loads(marker.read_text())
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
            kernel.CloseHandle.argtypes=[wintypes.HANDLE]
            handle=kernel.OpenProcess(0x00100000,False,pid)
            if handle:
                try:self.assertEqual(kernel.WaitForSingleObject(handle,5000),0)
                finally:kernel.CloseHandle(handle)


class PipeTests(unittest.TestCase):
    def test_actual_named_pipe_survives_client_exit_and_server_restart(self):
        with tempfile.TemporaryDirectory(prefix='pv-quote-pipe-test-') as temp:
            manifest=Path(temp)/'pipe.json'
            info={'pipe':r'\\.\pipe\pv-test-'+uuid4().hex,'auth':os.urandom(32).hex(),'host':'fake','port':0,'client_id':299}
            manifest.write_text(json.dumps(info),encoding='utf-8')
            env={**os.environ,'PYTHONPATH':str(ROOT),'PV_RUNTIME_ROOT':temp}
            code="import sys;from devtools.test_multi_instance_hardening import FakeFeed;from portefeuille_viewer.services.shared_quote_coordinator import serve;serve(sys.argv[1],FakeFeed)"
            def start():
                worker=subprocess.Popen([sys.executable,'-c',code,str(manifest)],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                deadline=time.monotonic()+15
                while time.monotonic()<deadline:
                    try:
                        rpc(manifest,{'op':'ping'});return worker
                    except OSError:
                        if worker.poll() is not None:
                            self.fail(str(worker.communicate()))
                        time.sleep(.1)
                worker.kill();self.fail('pipe did not start')
            worker=start()
            try:
                for key in ('onno','muriel','quinten'):
                    rpc(manifest,{'op':'join','client':key,'profile':key})
                    rpc(manifest,{'op':'assets','client':key,'rows':[(key,'USD','aandeel','SMART','',None)]})
                snapshot=rpc(manifest,{'op':'snapshot','client':'muriel'})
                self.assertEqual(len(snapshot['rows']),3)
                first_pid=snapshot['coordinator_pid']
                rpc(manifest,{'op':'leave','client':'onno'})
                self.assertEqual(len(rpc(manifest,{'op':'snapshot','client':'muriel'})['rows']),2)
                worker.kill();worker.communicate(timeout=5)
                worker=start()
                joined=rpc(manifest,{'op':'join','client':'muriel'})
                self.assertTrue(joined['info']['is_ready'])
                rpc(manifest,{'op':'assets','client':'muriel','rows':[('SPCX','USD','aandeel','SMART','',123)]})
                snapshot=rpc(manifest,{'op':'snapshot','client':'muriel'})
                self.assertNotEqual(snapshot['coordinator_pid'],first_pid)
                self.assertEqual(len(snapshot['rows']),1)
                # Exercise the actual Qt facade and client polling, with only DB and
                # server startup replaced; live ticks still pass through the pipe.
                from PySide6.QtWidgets import QApplication
                from portefeuille_viewer.services import shared_quote_client as client_module
                from portefeuille_viewer.services import price_feed
                app=QApplication.instance() or QApplication([])
                settings=SimpleNamespace(profile_database='test',get_market_data_settings=lambda:{'capacity':100,'batch_size':50,'rotation_seconds':30,'stale_seconds':180})
                with ExitStack() as stack:
                    stack.enter_context(patch.object(client_module,'get_settings',return_value=settings))
                    stack.enter_context(patch.object(client_module,'get_stockdata_db_path',return_value='synthetic.accdb'))
                    stack.enter_context(patch.object(client_module,'ensure_coordinator',return_value=manifest))
                    stack.enter_context(patch.object(price_feed.ASSET_LAST_PRICE_STORE,'ensure_loaded',return_value={}))
                    update=stack.enter_context(patch.object(price_feed.ASSET_LAST_PRICE_STORE,'update_price'))
                    stack.enter_context(patch.object(price_feed.PriceFeedService,'_load_option_last_prices_from_db'))
                    clients=[client_module.SharedPriceFeedService('fake',0,299) for _ in range(2)]
                    try:
                        for client in clients:
                            client.ensure_subscriptions([('SPCX','USD','aandeel','SMART','',123)])
                        deadline=time.monotonic()+10
                        while time.monotonic()<deadline and not all(c.is_ready() and c.get('SPCX','USD')==90. for c in clients):
                            app.processEvents();time.sleep(.01)
                        self.assertTrue(all(c.is_ready() and c.get('SPCX','USD')==90. for c in clients))
                        self.assertEqual(clients[0].endpoint(),clients[1].endpoint())
                        self.assertFalse(clients[0]._save_timer.isActive())
                        self.assertFalse(clients[0]._option_save_timer.isActive())
                        self.assertTrue(update.called)
                        self.assertTrue(all(call.kwargs.get("persist") is False for call in update.call_args_list))
                    finally:
                        for client in clients:client.shutdown()
            finally:
                worker.kill();worker.communicate(timeout=5)


if __name__=='__main__':
    unittest.main()
