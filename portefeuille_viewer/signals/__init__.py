from PySide6.QtCore import QObject, Signal, Qt, Slot


class Signals(QObject):
    """Central application signals.

    Keep this module minimal and free of project-level imports to avoid
    circular dependencies. Use the queued_emit_* helpers when emitting
    from worker threads.
    """


    # Emitted when the active database changes. Payload: database name (str)
    databaseChanged = Signal(str)

    # Emitted when a snapshot key is updated. Payload: snapshot key (str)
    snapshotUpdated = Signal(str)

    # Emitted when orders are committed (insert/update/delete). Payload: dict with affected asset types/assets.
    ordersCommitted = Signal(dict)

    # Emitted when a state-engine rebuild is requested. Payload: dict with scope/context.
    stateRebuildRequested = Signal(dict)

    # Emitted when a state-engine rebuild actually starts. Payload: dict with scope/context.
    stateRebuildStarted = Signal(dict)

    # Emitted when a state-engine rebuild finishes. Payload: dict with scope/context/result.
    stateRebuildFinished = Signal(dict)

    # Emitted when a state-engine rebuild fails. Payload: error message.
    stateRebuildFailed = Signal(str)

    # Emitted when a historical price update is requested. Payload: dict with scope/context.
    priceUpdateRequested = Signal(dict)

    # Emitted when a historical price update actually starts. Payload: dict with scope/context.
    priceUpdateStarted = Signal(dict)

    # Emitted when a historical price update finishes. Payload: dict with scope/context/result.
    priceUpdateFinished = Signal(dict)

    # Emitted when a historical price update fails. Payload: error message.
    priceUpdateFailed = Signal(str)

    # Optional debug signal
    debugSignal = Signal(str)

    # Emitted when UI style settings change. Payload: setting key (str)
    uiStyleChanged = Signal(str)

    # Emitted when aandelen projection backend filter changes. Payload: dict
    aandelenProjectionFilterChanged = Signal(dict)

    # Emitted when a background projection result is ready to publish on main thread.
    # Payload: projection/view key (str)
    projectionPublishTick = Signal(str)

    # Emitted when test-order scenario definitions change (create/rename/delete).
    testOrderScenariosChanged = Signal()

    # Emitted when the global test-orders enabled state changes.
    testOrdersEnabledChanged = Signal(bool)

    _databaseChangedRequested = Signal(str)
    _snapshotUpdatedRequested = Signal(str)
    _stateRebuildRequestedRequested = Signal(dict)
    _stateRebuildStartedRequested = Signal(dict)
    _stateRebuildFinishedRequested = Signal(dict)
    _stateRebuildFailedRequested = Signal(str)
    _priceUpdateRequestedRequested = Signal(dict)
    _priceUpdateStartedRequested = Signal(dict)
    _priceUpdateFinishedRequested = Signal(dict)
    _priceUpdateFailedRequested = Signal(str)
    _aandelenProjectionFilterChangedRequested = Signal(dict)
    _projectionPublishTickRequested = Signal(str)
    _testOrderScenariosChangedRequested = Signal()
    _testOrdersEnabledChangedRequested = Signal(bool)

    def __init__(self):
        super().__init__()
        self._databaseChangedRequested.connect(self._emit_databaseChanged, Qt.QueuedConnection)
        self._snapshotUpdatedRequested.connect(self._emit_snapshotUpdated, Qt.QueuedConnection)
        self._stateRebuildRequestedRequested.connect(self._emit_stateRebuildRequested, Qt.QueuedConnection)
        self._stateRebuildStartedRequested.connect(self._emit_stateRebuildStarted, Qt.QueuedConnection)
        self._stateRebuildFinishedRequested.connect(self._emit_stateRebuildFinished, Qt.QueuedConnection)
        self._stateRebuildFailedRequested.connect(self._emit_stateRebuildFailed, Qt.QueuedConnection)
        self._priceUpdateRequestedRequested.connect(self._emit_priceUpdateRequested, Qt.QueuedConnection)
        self._priceUpdateStartedRequested.connect(self._emit_priceUpdateStarted, Qt.QueuedConnection)
        self._priceUpdateFinishedRequested.connect(self._emit_priceUpdateFinished, Qt.QueuedConnection)
        self._priceUpdateFailedRequested.connect(self._emit_priceUpdateFailed, Qt.QueuedConnection)
        self._aandelenProjectionFilterChangedRequested.connect(
            self._emit_aandelenProjectionFilterChanged,
            Qt.QueuedConnection,
        )
        self._projectionPublishTickRequested.connect(self._emit_projectionPublishTick, Qt.QueuedConnection)
        self._testOrderScenariosChangedRequested.connect(
            self._emit_testOrderScenariosChanged,
            Qt.QueuedConnection,
        )
        self._testOrdersEnabledChangedRequested.connect(
            self._emit_testOrdersEnabledChanged,
            Qt.QueuedConnection,
        )

    
    # In signals.py
    #liveDataShouldUpdate = Signal()

    @Slot(str)
    def _emit_databaseChanged(self, db_name: str):
        self.databaseChanged.emit(db_name)

    @Slot(str)
    def _emit_snapshotUpdated(self, snapshot_key: str):
        self.snapshotUpdated.emit(snapshot_key)

    @Slot(dict)
    def _emit_stateRebuildRequested(self, payload: dict):
        self.stateRebuildRequested.emit(payload)

    @Slot(dict)
    def _emit_stateRebuildStarted(self, payload: dict):
        self.stateRebuildStarted.emit(payload)

    @Slot(dict)
    def _emit_stateRebuildFinished(self, payload: dict):
        self.stateRebuildFinished.emit(payload)

    @Slot(str)
    def _emit_stateRebuildFailed(self, message: str):
        self.stateRebuildFailed.emit(message)

    @Slot(dict)
    def _emit_priceUpdateRequested(self, payload: dict):
        self.priceUpdateRequested.emit(payload)

    @Slot(dict)
    def _emit_priceUpdateStarted(self, payload: dict):
        self.priceUpdateStarted.emit(payload)

    @Slot(dict)
    def _emit_priceUpdateFinished(self, payload: dict):
        self.priceUpdateFinished.emit(payload)

    @Slot(str)
    def _emit_priceUpdateFailed(self, message: str):
        self.priceUpdateFailed.emit(message)

    @Slot(dict)
    def _emit_aandelenProjectionFilterChanged(self, payload: dict):
        self.aandelenProjectionFilterChanged.emit(payload)

    @Slot(str)
    def _emit_projectionPublishTick(self, view_key: str):
        self.projectionPublishTick.emit(view_key)

    @Slot()
    def _emit_testOrderScenariosChanged(self):
        self.testOrderScenariosChanged.emit()

    @Slot(bool)
    def _emit_testOrdersEnabledChanged(self, enabled: bool):
        self.testOrdersEnabledChanged.emit(bool(enabled))

    def queued_emit_databaseChanged(self, db_name: str):
        self._databaseChangedRequested.emit(db_name)

    def queued_emit_snapshotUpdated(self, snapshot_key: str):
        self._snapshotUpdatedRequested.emit(snapshot_key)

    def queued_emit_stateRebuildRequested(self, payload: dict):
        self._stateRebuildRequestedRequested.emit(payload)

    def queued_emit_stateRebuildStarted(self, payload: dict):
        self._stateRebuildStartedRequested.emit(payload)

    def queued_emit_stateRebuildFinished(self, payload: dict):
        self._stateRebuildFinishedRequested.emit(payload)

    def queued_emit_stateRebuildFailed(self, message: str):
        self._stateRebuildFailedRequested.emit(message)

    def queued_emit_priceUpdateRequested(self, payload: dict):
        self._priceUpdateRequestedRequested.emit(payload)

    def queued_emit_priceUpdateStarted(self, payload: dict):
        self._priceUpdateStartedRequested.emit(payload)

    def queued_emit_priceUpdateFinished(self, payload: dict):
        self._priceUpdateFinishedRequested.emit(payload)

    def queued_emit_priceUpdateFailed(self, message: str):
        self._priceUpdateFailedRequested.emit(message)

    def queued_emit_aandelenProjectionFilterChanged(self, payload: dict):
        self._aandelenProjectionFilterChangedRequested.emit(payload)

    def queued_emit_projectionPublishTick(self, view_key: str):
        self._projectionPublishTickRequested.emit(view_key)

    def queued_emit_testOrderScenariosChanged(self):
        self._testOrderScenariosChangedRequested.emit()

    def queued_emit_testOrdersEnabledChanged(self, enabled: bool):
        self._testOrdersEnabledChangedRequested.emit(bool(enabled))



signals = Signals()
