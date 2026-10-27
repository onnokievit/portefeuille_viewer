"""Manual history start/rejection lifecycle; no IBKR or production DB access."""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QObject,Signal
from PySide6.QtWidgets import QApplication,QWidget,QPushButton,QComboBox,QLabel
from portefeuille_viewer.services import single_asset_long_history_runner as module
from portefeuille_viewer.services import shared_tasks
from portefeuille_viewer.ui_logica.asset_rollup_editor_tab import AssetRollupEditorTab as Tab


class Lease:
    def __init__(self,state):self.state=state;self.owned=False
    def acquire(self):
        if self.state.held:return False
        self.state.held=True;self.owned=True;return True
    def release(self):
        if self.owned:self.state.held=False;self.owned=False


class Process(QObject):
    readyReadStandardOutput=Signal();readyReadStandardError=Signal()
    finished=Signal(int,object);errorOccurred=Signal(object)
    calls=[]
    def setProgram(self,value):pass
    def setArguments(self,value):self.args=value
    def setWorkingDirectory(self,value):pass
    def start(self):self.calls.append(self)
    def readAllStandardOutput(self):return b''
    def readAllStandardError(self):return b''


class Editor(QWidget):
    _run_long_history_for_selection=Tab._run_long_history_for_selection
    _run_long_iv_hv_for_selection=Tab._run_long_iv_hv_for_selection
    _on_long_history_not_started=Tab._on_long_history_not_started
    _on_long_history_started=Tab._on_long_history_started
    _on_long_history_step_started=Tab._on_long_history_step_started
    _on_long_history_output=Tab._on_long_history_output
    _on_long_history_finished=Tab._on_long_history_finished
    _on_long_history_failed=Tab._on_long_history_failed
    _append_history_output=Tab._append_history_output
    _history_is_running=Tab._history_is_running
    _set_history_busy=Tab._set_history_busy
    def __init__(self):
        super().__init__();self._selected_id=440;self._history_runner=None;self._history_dialog=None
        for name in ('btn_long_history','btn_long_iv_hv','btn_reload','btn_new','btn_save','btn_delete'):
            setattr(self,name,QPushButton(self))
        self.combo_long_iv_hv_duration=QComboBox(self);self.combo_long_iv_hv_duration.addItem('10 Y','10 Y')
        self.lbl_status=QLabel(self)
    def _selected_asset_rollup(self):return 'XLY'


class HistoryStartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.state=SimpleNamespace(held=False)
        self.patches=[patch.object(shared_tasks,'maintenance_lease',side_effect=lambda path:Lease(self.state)),
            patch.object(shared_tasks,'get_stockdata_db_path',return_value='synthetic.accdb'),
            patch.object(module,'QProcess',Process),
            patch('portefeuille_viewer.services.worker_guard.protect_worker',side_effect=lambda process:process),
            patch('portefeuille_viewer.ui_logica.asset_rollup_editor_tab.QMessageBox.warning')]
        for item in self.patches:item.start()
        Process.calls=[];self.editor=Editor()
    def tearDown(self):
        if self.editor._history_runner:shared_tasks.release_task(self.editor._history_runner)
        self.editor.close();self.editor.deleteLater();self.app.processEvents()
        for item in reversed(self.patches):item.stop()

    def check_busy_rejection_and_retry(self,method):
        self.state.held=True
        getattr(self.editor,method)()
        self.assertIsNone(self.editor._history_runner)
        self.assertTrue(self.editor.btn_long_history.isEnabled())
        self.assertTrue(self.editor.btn_long_iv_hv.isEnabled())
        self.assertTrue(self.editor.btn_reload.isEnabled())
        self.assertIn('niet gestart',self.editor.lbl_status.text())
        self.assertIn('niet gestart',self.editor._history_dialog.lbl_status.text())
        self.assertTrue(self.state.held)  # Never release someone else's lease.
        self.assertEqual(Process.calls,[])
        self.state.held=False  # Simulate the background volatility run finishing.
        getattr(self.editor,method)()
        self.assertTrue(self.editor._history_is_running())
        self.assertEqual(len(Process.calls),1)
        self.assertFalse(self.editor.btn_long_history.isEnabled())
        runner=self.editor._history_runner
        runner._process.finished.emit(1,None)
        self.assertIsNone(self.editor._history_runner)
        self.assertTrue(self.editor.btn_long_history.isEnabled())
        self.assertFalse(self.state.held)

    def test_ohlcv_rejected_then_retries_without_app_restart(self):
        self.check_busy_rejection_and_retry('_run_long_history_for_selection')
    def test_volatility_rejected_then_retries_without_app_restart(self):
        self.check_busy_rejection_and_retry('_run_long_iv_hv_for_selection')

    def test_process_setup_failure_releases_lease_and_restores_controls(self):
        for method in ('_run_long_history_for_selection','_run_long_iv_hv_for_selection'):
            with self.subTest(method=method),patch.object(module,'QProcess',side_effect=RuntimeError('injected setup failure')):
                getattr(self.editor,method)()
                self.assertFalse(self.state.held)
                self.assertIsNone(self.editor._history_runner)
                self.assertTrue(self.editor.btn_long_history.isEnabled())
                self.assertIn('injected setup failure',self.editor.lbl_status.text())

    def test_empty_asset_never_claims_shared_task(self):
        for factory in (module.SingleAssetLongHistoryRunner,module.SingleAssetLongVolatilityRunner):
            runner=factory();self.assertFalse(runner.start(''))
            self.assertFalse(self.state.held);self.assertFalse(runner.is_running)

    def test_refresh_setup_failure_releases_lease(self):
        runner=module.SingleAssetLongHistoryRunner()
        self.assertTrue(shared_tasks.claim_task(runner))
        errors=[];runner.failed.connect(errors.append)
        with patch.object(module,'get_history_indicator_runner',side_effect=RuntimeError('refresh setup failed')):
            module._refresh_after_pipeline(runner,{'status':'ok'},'done')
        self.assertEqual(errors,['refresh setup failed'])
        self.assertFalse(runner.is_running);self.assertFalse(self.state.held)

    def test_late_refresh_callback_after_failure_is_ignored(self):
        runner=module.SingleAssetLongHistoryRunner()
        self.assertTrue(shared_tasks.claim_task(runner))
        callbacks={}
        def request(**kwargs):callbacks.update(kwargs)
        finished=[];errors=[];runner.finished.connect(finished.append);runner.failed.connect(errors.append)
        with patch.object(module,'get_history_indicator_runner',return_value=SimpleNamespace(request=request)):
            module._refresh_after_pipeline(runner,{'status':'ok'},'done')
        callbacks['on_failed']('failed')
        callbacks['on_published']()
        self.assertEqual(errors,['failed']);self.assertEqual(finished,[])
        self.assertFalse(runner.is_running);self.assertFalse(self.state.held)


if __name__=='__main__':unittest.main()
