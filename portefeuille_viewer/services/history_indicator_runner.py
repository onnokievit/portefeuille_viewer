"""One background refresh path per viewer for history and asset indicators."""
from PySide6.QtCore import QObject, Signal, QCoreApplication, QTimer

from portefeuille_viewer.data import repository
from portefeuille_viewer.services.asset_indicator_service import rebuild_asset_indicator_snapshots
from portefeuille_viewer.services.projection_worker import ProjectionWorker
from portefeuille_viewer.services import projection_worker
from portefeuille_viewer.services.indicator_history_writer import IndicatorHistoryWriter
from portefeuille_viewer.services.asset_indicator_service import AssetIndicatorService
from portefeuille_viewer.signals import signals


class HistoryIndicatorRunner(QObject):
    started = Signal(object)
    finished = Signal(object)
    failed = Signal(str)
    storage_status = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = ProjectionWorker(self._compute, self)
        self.worker.started.connect(self.started.emit)
        self.worker.published.connect(self._published)
        self.worker.failed.connect(self.failed.emit)
        self.writer = IndicatorHistoryWriter(self)
        self.writer.status_changed.connect(self.storage_status.emit)
        self._options_dirty = False
        self._option_timer = QTimer(self)
        self._option_timer.setSingleShot(True)
        self._option_timer.setInterval(1000)
        self._option_timer.timeout.connect(self._refresh_options)
        signals.snapshotUpdated.connect(self._on_snapshot_updated)

    def _on_snapshot_updated(self, key):
        if key in {'snapshot_optie_timevalue_live', 'aggregator_snapshot_load_open_opties_from_tx_live',
                   'repository_snapshot_load_open_opties'}:
            self._options_dirty = True
            if not self._option_timer.isActive():
                self._option_timer.start()

    def _refresh_options(self):
        if projection_worker.SNAPSHOT_STORE.snapshot_asset_indicator_basis is None:
            return
        self._options_dirty = False
        self.worker.submit('history_indicators', dict(all=False, names={'option_overlay'},
            keys=set(), reason='profile_options_changed', callbacks=[], error_callbacks=[]))

    def request(self, *, reload_history=False, reload_beta=False,
                rebuild_indicators=True, reason='manual', on_published=None, on_failed=None):
        names = set()
        if reload_history:
            names.add('history')
        if reload_beta:
            names.add('beta')
        if rebuild_indicators:
            names.add('indicators')
        if not names:
            return
        self.worker.submit('history_indicators', dict(
            all=False, names=names, keys=set(), reason=reason,
            callbacks=[on_published] if on_published is not None else [],
            error_callbacks=[on_failed] if on_failed is not None else []))

    def _compute(self, request):
        # ProjectionWorker owns a frozen input view and stages all safe_write
        # calls. A history load here is visible to the following calculation,
        # while no observer sees half of the new dataset.
        if 'history' in request['names']:
            repository.load_historical_ohlcv_snapshot()
        if 'beta' in request['names']:
            repository.load_asset_driver_beta_snapshot()
        if 'indicators' in request['names']:
            result = rebuild_asset_indicator_snapshots(persist_history=False)
            if result.status != 'ok':
                raise RuntimeError(result.error or 'Asset-indicatorberekening mislukt')
            request['indicator_result'] = result
            store = projection_worker.SNAPSHOT_STORE
            live = getattr(result, 'historical_df', None)
            meta = getattr(store, 'snapshot_asset_indicator_meta', None)
            if live is not None and not live.is_empty() and meta is not None and not meta.is_empty():
                request['save_payload'] = dict(run_id=result.run_id,
                    started_at=meta.item(0, 'last_run_at'), duration_ms=result.duration_ms,
                    status='ok', error='', live_df=live.clone(),
                    generation_key=getattr(result, 'generation_key', ''))
        elif 'option_overlay' in request['names']:
            store = projection_worker.SNAPSHOT_STORE
            service = AssetIndicatorService()
            live = service.apply_profile_overlay(store.snapshot_asset_indicator_basis)
            previous = store.snapshot_asset_indicator_live
            if previous is not None and previous.equals(live):
                return
            store.safe_write_if_changed('snapshot_asset_indicator_live', live)
            store.safe_write_if_changed('snapshot_asset_indicator_summary',
                service._build_summary_snapshot(live, live.item(0, 'as_of')))

    def _published(self, request):
        self.finished.emit(dict(reason=request['reason'], operations=sorted(request['names']),
                                indicator_result=request.get('indicator_result')))
        if request.get('save_payload') is not None:
            self.writer.enqueue(request['save_payload'])
        # Option data can arrive while the FIRST historical run still has no
        # published basis. Keep that notification until publication is complete.
        if self._options_dirty and not self._option_timer.isActive():
            self._option_timer.start()

    def shutdown(self):
        self.worker.shutdown()
        self._option_timer.stop()
        signals.snapshotUpdated.disconnect(self._on_snapshot_updated)
        self.writer.close()


def get_history_indicator_runner():
    app = QCoreApplication.instance()
    if app is None:
        raise RuntimeError('A Qt application is required for background refresh')
    runner = getattr(app, '_history_indicator_runner', None)
    if runner is None:
        runner = HistoryIndicatorRunner(app)
        app._history_indicator_runner = runner
        app.aboutToQuit.connect(runner.shutdown)
    return runner
