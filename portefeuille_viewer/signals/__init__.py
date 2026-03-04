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

    # Emitted when orders are committed (insert/update/delete). No payload
    ordersCommitted = Signal()

    # Emitted when a state-engine rebuild is requested. Payload: dict with scope/context.
    stateRebuildRequested = Signal(dict)

    # Emitted when a state-engine rebuild actually starts. Payload: dict with scope/context.
    stateRebuildStarted = Signal(dict)

    # Emitted when a state-engine rebuild finishes. Payload: dict with scope/context/result.
    stateRebuildFinished = Signal(dict)

    # Emitted when a state-engine rebuild fails. Payload: error message.
    stateRebuildFailed = Signal(str)

    # Optional debug signal
    debugSignal = Signal(str)

    # Emitted when UI style settings change. Payload: setting key (str)
    uiStyleChanged = Signal(str)
    
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


signals = Signals()
