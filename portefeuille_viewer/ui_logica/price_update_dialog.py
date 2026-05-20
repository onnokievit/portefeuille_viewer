from __future__ import annotations

from contextlib import suppress
from datetime import datetime

from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from portefeuille_viewer.signals import signals


class PriceUpdateDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Price Update")
        self.setModal(False)
        self.resize(980, 560)
        self._running = False
        self._build_ui()
        self._connect_signals()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        row = QHBoxLayout()
        self.labelStatus = QLabel("Idle")
        row.addWidget(self.labelStatus)
        row.addStretch(1)
        self.buttonStart = QPushButton("Start Price Update")
        self.buttonStart.clicked.connect(self.start_update)
        row.addWidget(self.buttonStart)
        self.buttonClear = QPushButton("Clear log")
        row.addWidget(self.buttonClear)
        root.addLayout(row)

        self.logOutput = QPlainTextEdit(self)
        self.logOutput.setReadOnly(True)
        self.logOutput.setFont(QFont("Consolas", 9))
        root.addWidget(self.logOutput, 1)
        self.buttonClear.clicked.connect(self.logOutput.clear)

    def _connect_signals(self) -> None:
        signals.priceUpdateStarted.connect(self._on_price_update_started)
        signals.priceUpdateFinished.connect(self._on_price_update_finished)
        signals.priceUpdateFailed.connect(self._on_price_update_failed)
        signals.priceUpdateOutput.connect(self._on_price_update_output)

    def closeEvent(self, event) -> None:
        with suppress(Exception):
            signals.priceUpdateStarted.disconnect(self._on_price_update_started)
        with suppress(Exception):
            signals.priceUpdateFinished.disconnect(self._on_price_update_finished)
        with suppress(Exception):
            signals.priceUpdateFailed.disconnect(self._on_price_update_failed)
        with suppress(Exception):
            signals.priceUpdateOutput.disconnect(self._on_price_update_output)
        super().closeEvent(event)

    def start_update(self) -> None:
        if self._running:
            self._append_log("Price update loopt al.", "warn")
            return
        self._running = True
        self.buttonStart.setEnabled(False)
        self.labelStatus.setText("Aangevraagd...")
        self._append_log("Handmatige price update aangevraagd.", "info")
        signals.priceUpdateRequested.emit({"reason": "manual_settings_price_update", "force": True})

    def _on_price_update_started(self, payload: dict) -> None:
        self._running = True
        self.buttonStart.setEnabled(False)
        reason = (payload or {}).get("reason", "-")
        force = bool((payload or {}).get("force"))
        self.labelStatus.setText("Loopt...")
        self._append_log(f"START reason={reason} force={force}", "info")

    def _on_price_update_finished(self, payload: dict) -> None:
        self._running = False
        self.buttonStart.setEnabled(True)
        status = (payload or {}).get("status", "ok")
        start = (payload or {}).get("fetch_start_date", "n/a")
        target = (payload or {}).get("target_date", "today")
        exit_code = (payload or {}).get("exit_code")
        suffix = f" exit={exit_code}" if exit_code is not None else ""
        self.labelStatus.setText(f"Klaar: {status}")
        self._append_log(f"FINISH status={status} range={start}->{target}{suffix}", "info")

    def _on_price_update_failed(self, message: str) -> None:
        self._running = False
        self.buttonStart.setEnabled(True)
        self.labelStatus.setText("Fout")
        self._append_log(str(message or ""), "stderr")

    def _on_price_update_output(self, payload: dict) -> None:
        stream = (payload or {}).get("stream", "stdout")
        text = str((payload or {}).get("text") or "")
        if not text:
            return
        for line in text.rstrip().splitlines():
            if line.strip().startswith("{") and '"status"' in line and '"stdout"' in line:
                self._append_log("Final JSON payload ontvangen; status wordt apart verwerkt.", "stdout")
                continue
            self._append_log(line, stream)

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
