from __future__ import annotations

from collections import defaultdict
from contextlib import suppress
from datetime import date, datetime

import pyodbc
from PySide6.QtCore import QDate, QTimer, Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDateEdit,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from portefeuille_viewer.data import repository
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.signals import signals


CLASS_TYPE_MAP = {
    "aandelen": {"aandeel", "future"},
    "opties": {"optie"},
    "sprinters": {"sprinter"},
}


class StateEngineTasksDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("State Engine Tasks")
        self.setModal(False)
        self.resize(980, 760)
        self._assets: list[dict] = []
        self._setting_up = False

        self._build_ui()
        self._connect_signals()
        self._load_assets()
        self._refresh_runtime_status()

        self._status_timer = QTimer(self)
        self._status_timer.setInterval(1000)
        self._status_timer.timeout.connect(self._refresh_runtime_status)
        self._status_timer.start()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        top_group = QGroupBox("Handmatige rebuild")
        top_layout = QGridLayout(top_group)

        self.checkAandelen = QCheckBox("Aandelen")
        self.checkOpties = QCheckBox("Opties")
        self.checkSprinters = QCheckBox("Sprinters")
        self.checkAandelen.setChecked(True)
        self.checkOpties.setChecked(True)
        self.checkSprinters.setChecked(True)
        self.checkAllAssets = QCheckBox("Alle assets")
        self.checkAllAssets.setChecked(True)

        self.dateFrom = QDateEdit()
        self.dateFrom.setCalendarPopup(True)
        self.dateFrom.setDisplayFormat("yyyy-MM-dd")
        self.dateFrom.setDate(QDate.currentDate().addDays(-5))

        self.editFilter = QLineEdit()
        self.editFilter.setPlaceholderText("Filter asset...")

        top_layout.addWidget(QLabel("Asset classes"), 0, 0)
        classes_row = QHBoxLayout()
        classes_row.addWidget(self.checkAandelen)
        classes_row.addWidget(self.checkOpties)
        classes_row.addWidget(self.checkSprinters)
        classes_row.addStretch(1)
        classes_widget = QWidget()
        classes_widget.setLayout(classes_row)
        top_layout.addWidget(classes_widget, 0, 1, 1, 3)

        top_layout.addWidget(QLabel("Vanaf datum"), 1, 0)
        top_layout.addWidget(self.dateFrom, 1, 1)
        top_layout.addWidget(self.checkAllAssets, 1, 2)
        top_layout.addWidget(self.editFilter, 1, 3)

        root.addWidget(top_group)

        self.tableAssets = QTableWidget(self)
        self.tableAssets.setColumnCount(3)
        self.tableAssets.setHorizontalHeaderLabels(["Asset", "Type(s)", "Eerste tx"])
        self.tableAssets.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tableAssets.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tableAssets.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tableAssets.verticalHeader().setVisible(False)
        self.tableAssets.setAlternatingRowColors(True)
        self.tableAssets.horizontalHeader().setStretchLastSection(True)
        self.tableAssets.setSortingEnabled(True)
        root.addWidget(self.tableAssets, 1)

        info_row = QHBoxLayout()
        self.labelVisibleAssets = QLabel("Zichtbaar: 0")
        self.labelPending = QLabel("Pending: 0")
        self.labelRunning = QLabel("Running: nee")
        info_row.addWidget(self.labelVisibleAssets)
        info_row.addWidget(self.labelPending)
        info_row.addWidget(self.labelRunning)
        info_row.addStretch(1)
        root.addLayout(info_row)

        button_row = QHBoxLayout()
        self.buttonQueue = QPushButton("Taak klaarzetten")
        self.buttonQueueRun = QPushButton("Taak klaarzetten + Run")
        self.buttonRunPending = QPushButton("Run pending")
        self.buttonRefresh = QPushButton("Refresh")
        self.buttonClearLog = QPushButton("Clear log")
        button_row.addWidget(self.buttonQueue)
        button_row.addWidget(self.buttonQueueRun)
        button_row.addWidget(self.buttonRunPending)
        button_row.addWidget(self.buttonRefresh)
        button_row.addStretch(1)
        button_row.addWidget(self.buttonClearLog)
        root.addLayout(button_row)

        self.logOutput = QPlainTextEdit(self)
        self.logOutput.setReadOnly(True)
        font = QFont("Consolas", 9)
        self.logOutput.setFont(font)
        self.logOutput.setMinimumHeight(220)
        root.addWidget(self.logOutput)

    def _connect_signals(self) -> None:
        self.checkAandelen.toggled.connect(self._apply_asset_filters)
        self.checkOpties.toggled.connect(self._apply_asset_filters)
        self.checkSprinters.toggled.connect(self._apply_asset_filters)
        self.checkAllAssets.toggled.connect(self._on_toggle_all_assets)
        self.editFilter.textChanged.connect(self._apply_asset_filters)

        self.buttonQueue.clicked.connect(self._on_queue_clicked)
        self.buttonQueueRun.clicked.connect(self._on_queue_run_clicked)
        self.buttonRunPending.clicked.connect(self._on_run_pending_clicked)
        self.buttonRefresh.clicked.connect(self._on_refresh_clicked)
        self.buttonClearLog.clicked.connect(self.logOutput.clear)

        signals.stateRebuildStarted.connect(self._on_state_rebuild_started)
        signals.stateRebuildFinished.connect(self._on_state_rebuild_finished)
        signals.stateRebuildFailed.connect(self._on_state_rebuild_failed)
        signals.stateRebuildOutput.connect(self._on_state_rebuild_output)
        signals.databaseChanged.connect(self._on_database_changed)

    def closeEvent(self, event) -> None:
        with suppress(Exception):
            signals.stateRebuildStarted.disconnect(self._on_state_rebuild_started)
        with suppress(Exception):
            signals.stateRebuildFinished.disconnect(self._on_state_rebuild_finished)
        with suppress(Exception):
            signals.stateRebuildFailed.disconnect(self._on_state_rebuild_failed)
        with suppress(Exception):
            signals.stateRebuildOutput.disconnect(self._on_state_rebuild_output)
        with suppress(Exception):
            signals.databaseChanged.disconnect(self._on_database_changed)
        if hasattr(self, "_status_timer") and self._status_timer.isActive():
            self._status_timer.stop()
        super().closeEvent(event)

    def _load_assets(self) -> None:
        db_path = getattr(repository, "db_path", None)
        self._assets = []
        if not db_path:
            self._append_log("Geen actieve database voor assetlijst.", "warn")
            self._rebuild_asset_table()
            return

        conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path}"
        query = """
            SELECT asset_rollup, asset_type, MIN(datum) AS first_tx_date
            FROM transacties_bron_data
            WHERE asset_rollup IS NOT NULL
            GROUP BY asset_rollup, asset_type
            ORDER BY asset_rollup
        """
        grouped: dict[str, dict] = defaultdict(lambda: {"types": set(), "first_tx_date": None})
        try:
            with pyodbc.connect(conn_str) as conn:
                rows = conn.cursor().execute(query).fetchall()
        except Exception as exc:
            self._append_log(f"Assetlijst laden mislukt: {exc}", "stderr")
            self._rebuild_asset_table()
            return

        for asset_rollup, asset_type, first_tx_date in rows:
            asset = str(asset_rollup or "").strip()
            raw_type = str(asset_type or "").strip().lower()
            if not asset or not raw_type:
                continue
            current = grouped[asset]
            current["types"].add(raw_type)
            parsed = self._normalize_date(first_tx_date)
            if parsed is not None:
                old = current["first_tx_date"]
                if old is None or parsed < old:
                    current["first_tx_date"] = parsed

        self._assets = [
            {
                "asset_rollup": asset,
                "types": sorted(data["types"]),
                "first_tx_date": data["first_tx_date"],
            }
            for asset, data in sorted(grouped.items(), key=lambda item: item[0].lower())
        ]
        self._rebuild_asset_table()

    def _rebuild_asset_table(self) -> None:
        self._setting_up = True
        try:
            self.tableAssets.setSortingEnabled(False)
            self.tableAssets.setRowCount(len(self._assets))
            for row_idx, row in enumerate(self._assets):
                asset = row["asset_rollup"]
                types = ",".join(row["types"])
                first_tx = row["first_tx_date"].isoformat() if row["first_tx_date"] else ""

                asset_item = QTableWidgetItem(asset)
                asset_item.setData(Qt.UserRole, asset)
                asset_item.setData(Qt.UserRole + 1, list(row["types"]))
                self.tableAssets.setItem(row_idx, 0, asset_item)
                self.tableAssets.setItem(row_idx, 1, QTableWidgetItem(types))
                self.tableAssets.setItem(row_idx, 2, QTableWidgetItem(first_tx))
            self.tableAssets.setSortingEnabled(True)
        finally:
            self._setting_up = False
        self._apply_asset_filters()

    def _selected_classes(self) -> list[str]:
        classes: list[str] = []
        if self.checkAandelen.isChecked():
            classes.append("aandelen")
        if self.checkOpties.isChecked():
            classes.append("opties")
        if self.checkSprinters.isChecked():
            classes.append("sprinters")
        return classes

    def _apply_asset_filters(self) -> None:
        selected_classes = self._selected_classes()
        filter_text = (self.editFilter.text() or "").strip().lower()
        visible_count = 0
        for row in range(self.tableAssets.rowCount()):
            asset_item = self.tableAssets.item(row, 0)
            asset = str(asset_item.data(Qt.UserRole) or "").strip() if asset_item else ""
            raw_types = asset_item.data(Qt.UserRole + 1) if asset_item else []
            matches_text = not filter_text or filter_text in asset.lower()
            matches_class = self._asset_matches_classes(raw_types, selected_classes)
            visible = matches_text and matches_class
            self.tableAssets.setRowHidden(row, not visible)
            if visible:
                visible_count += 1
        self.labelVisibleAssets.setText(f"Zichtbaar: {visible_count}")

    def _asset_matches_classes(self, raw_types: list[str], selected_classes: list[str]) -> bool:
        if not selected_classes:
            return True
        raw_type_set = {str(x).strip().lower() for x in raw_types if str(x).strip()}
        for asset_class in selected_classes:
            if raw_type_set & CLASS_TYPE_MAP.get(asset_class, set()):
                return True
        return False

    def _on_toggle_all_assets(self, checked: bool) -> None:
        self.tableAssets.setDisabled(bool(checked))
        if checked:
            self.tableAssets.clearSelection()

    def _resolve_selected_assets(self) -> list[str]:
        if self.checkAllAssets.isChecked():
            assets: list[str] = []
            for row in range(self.tableAssets.rowCount()):
                if self.tableAssets.isRowHidden(row):
                    continue
                asset_item = self.tableAssets.item(row, 0)
                asset = str(asset_item.data(Qt.UserRole) or "").strip() if asset_item else ""
                if asset:
                    assets.append(asset)
            return sorted(set(assets))

        selected_rows = sorted({index.row() for index in self.tableAssets.selectionModel().selectedRows()})
        assets: list[str] = []
        for row in selected_rows:
            if self.tableAssets.isRowHidden(row):
                continue
            asset_item = self.tableAssets.item(row, 0)
            asset = str(asset_item.data(Qt.UserRole) or "").strip() if asset_item else ""
            if asset:
                assets.append(asset)
        return sorted(set(assets))

    def _build_payload(self) -> dict | None:
        selected_classes = self._selected_classes()
        if not selected_classes:
            QMessageBox.warning(self, "State Engine", "Selecteer minimaal één asset class.")
            return None

        selected_assets = self._resolve_selected_assets()
        if not selected_assets:
            QMessageBox.warning(self, "State Engine", "Selecteer minimaal één asset of gebruik 'Alle assets'.")
            return None

        from_date = self.dateFrom.date().toString("yyyy-MM-dd")
        return {
            "asset_classes": selected_classes,
            "affected_assets": selected_assets,
            "from_date": from_date,
            "reason": "order_manual_ui",
            "mode": "asset_incremental",
        }

    def _queue_payload(self, payload: dict) -> bool:
        runner = getattr(SNAPSHOT_STORE, "state_engine_runner", None)
        if runner is None:
            QMessageBox.warning(self, "State Engine", "State engine runner is niet beschikbaar.")
            return False
        queued = runner.queue_pending_rebuild(payload)
        if queued:
            self._append_log(
                f"Queued: classes={','.join(payload['asset_classes'])} assets={len(payload['affected_assets'])} from={payload['from_date']}",
                "info",
            )
            self._refresh_runtime_status()
        return bool(queued)

    def _on_queue_clicked(self) -> None:
        payload = self._build_payload()
        if payload is None:
            return
        self._queue_payload(payload)

    def _on_queue_run_clicked(self) -> None:
        payload = self._build_payload()
        if payload is None:
            return
        if not self._queue_payload(payload):
            return
        self._run_pending()

    def _on_run_pending_clicked(self) -> None:
        self._run_pending()

    def _run_pending(self) -> None:
        runner = getattr(SNAPSHOT_STORE, "state_engine_runner", None)
        if runner is None:
            QMessageBox.warning(self, "State Engine", "State engine runner is niet beschikbaar.")
            return
        started = runner.run_pending_order_rebuild_now()
        if started:
            self._append_log("Pending queue gestart.", "info")
        else:
            self._append_log("Geen pending queue om te draaien.", "warn")
        self._refresh_runtime_status()

    def _on_refresh_clicked(self) -> None:
        self._load_assets()
        self._refresh_runtime_status()
        self._append_log("Assets en status ververst.", "info")

    def _refresh_runtime_status(self) -> None:
        runner = getattr(SNAPSHOT_STORE, "state_engine_runner", None)
        if runner is None:
            self.labelPending.setText("Pending: -")
            self.labelRunning.setText("Running: nee")
            return
        summary = runner.get_pending_order_rebuild_summary()
        pending_from = summary.get("from_date") or "-"
        pending_classes = ",".join(summary.get("pending_classes") or []) or "-"
        self.labelPending.setText(
            f"Pending: {summary.get('pending_assets', 0)} | classes: {pending_classes} | from: {pending_from}"
        )

        runtime = runner.get_runtime_status()
        if runtime.get("running"):
            engine = runtime.get("engine_class") or "-"
            from_date = runtime.get("from_date") or "-"
            asset_count = len(runtime.get("affected_assets") or [])
            self.labelRunning.setText(
                f"Running: ja | class: {engine} | assets: {asset_count} | from: {from_date}"
            )
        else:
            self.labelRunning.setText("Running: nee")

    def _on_state_rebuild_started(self, payload: dict) -> None:
        engine = payload.get("engine_class") or ",".join(payload.get("asset_classes") or []) or "-"
        from_date = payload.get("from_date") or "-"
        assets = len(payload.get("affected_assets") or [])
        self._append_log(f"START {engine} | assets={assets} | from={from_date}", "info")
        self._refresh_runtime_status()

    def _on_state_rebuild_finished(self, payload: dict) -> None:
        engine = payload.get("engine_class") or ",".join(payload.get("asset_classes") or []) or "-"
        status = payload.get("status") or "ok"
        exit_code = payload.get("exit_code")
        suffix = f" | exit={exit_code}" if exit_code is not None else ""
        self._append_log(f"FINISH {engine} | status={status}{suffix}", "info")
        self._refresh_runtime_status()

    def _on_state_rebuild_failed(self, message: str) -> None:
        self._append_log(f"FAIL {message}", "stderr")
        self._refresh_runtime_status()

    def _on_state_rebuild_output(self, payload: dict) -> None:
        stream = payload.get("stream") or "stdout"
        text = str(payload.get("text") or "").strip()
        if not text:
            return
        self._append_log(text, stream)

    def _on_database_changed(self, _db_name: str) -> None:
        self._load_assets()
        self._refresh_runtime_status()

    def _append_log(self, message: str, level: str = "info") -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = {
            "stderr": "ERR",
            "warn": "WRN",
            "stdout": "OUT",
            "info": "INF",
        }.get(level, "LOG")
        self.logOutput.appendPlainText(f"[{timestamp}] {prefix} {message}")
        cursor = self.logOutput.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.logOutput.setTextCursor(cursor)

    @staticmethod
    def _normalize_date(value) -> date | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        try:
            return datetime.strptime(str(value), "%Y-%m-%d").date()
        except Exception:
            return None
