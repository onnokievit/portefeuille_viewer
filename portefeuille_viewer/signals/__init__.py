from PySide6.QtCore import QObject, Signal, QTimer


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
    
    # In signals.py
    #liveDataShouldUpdate = Signal()

    def queued_emit_databaseChanged(self, db_name: str):
        # Ensure the emit happens on the Qt event loop / main thread
        QTimer.singleShot(0, lambda: self.databaseChanged.emit(db_name))

    def queued_emit_snapshotUpdated(self, snapshot_key: str):
        QTimer.singleShot(0, lambda: self.snapshotUpdated.emit(snapshot_key))

    def queued_emit_stateRebuildRequested(self, payload: dict):
        QTimer.singleShot(0, lambda: self.stateRebuildRequested.emit(payload))

    def queued_emit_stateRebuildStarted(self, payload: dict):
        QTimer.singleShot(0, lambda: self.stateRebuildStarted.emit(payload))

    def queued_emit_stateRebuildFinished(self, payload: dict):
        QTimer.singleShot(0, lambda: self.stateRebuildFinished.emit(payload))

    def queued_emit_stateRebuildFailed(self, message: str):
        QTimer.singleShot(0, lambda: self.stateRebuildFailed.emit(message))

    def queued_emit_priceUpdateRequested(self, payload: dict):
        QTimer.singleShot(0, lambda: self.priceUpdateRequested.emit(payload))

    def queued_emit_priceUpdateStarted(self, payload: dict):
        QTimer.singleShot(0, lambda: self.priceUpdateStarted.emit(payload))

    def queued_emit_priceUpdateFinished(self, payload: dict):
        QTimer.singleShot(0, lambda: self.priceUpdateFinished.emit(payload))

    def queued_emit_priceUpdateFailed(self, message: str):
        QTimer.singleShot(0, lambda: self.priceUpdateFailed.emit(message))

    def queued_emit_aandelenProjectionFilterChanged(self, payload: dict):
        QTimer.singleShot(0, lambda: self.aandelenProjectionFilterChanged.emit(payload))

    def queued_emit_projectionPublishTick(self, view_key: str):
        QTimer.singleShot(0, lambda: self.projectionPublishTick.emit(view_key))


signals = Signals()
