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

    # Optional debug signal
    debugSignal = Signal(str)

    def queued_emit_databaseChanged(self, db_name: str):
        # Ensure the emit happens on the Qt event loop / main thread
        QTimer.singleShot(0, lambda: self.databaseChanged.emit(db_name))

    def queued_emit_snapshotUpdated(self, snapshot_key: str):
        QTimer.singleShot(0, lambda: self.snapshotUpdated.emit(snapshot_key))


signals = Signals()
