from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Slot

from portefeuille_viewer.config import get_stockdata_db_path
from portefeuille_viewer.signals import signals


OVERLAP_DAYS = 5
STOCKDATA_DB_PATH = get_stockdata_db_path()


class HistoricalPriceUpdateRunner(QObject):
    """Run startup historical price update entirely in a separate process."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process: QProcess | None = None
        self._stdout_chunks: list[bytes] = []
        self._stderr_chunks: list[bytes] = []

    @Slot()
    def request_startup_update(self) -> None:
        self.request_update(reason="startup_price_update", force=False)

    def request_manual_update(self) -> None:
        self.request_update(reason="manual_settings_price_update", force=True)

    def request_update(self, *, reason: str = "startup_price_update", force: bool = False) -> None:
        if self._process is not None:
            return

        script_path = Path(__file__).resolve().parents[2] / "price_update_scripts" / "startup_price_update.py"
        process = QProcess(self)
        process.setProgram(sys.executable)
        args = [str(script_path), "--reason", str(reason or "startup_price_update")]
        if force:
            args.append("--force")
        process.setArguments(args)
        process.readyReadStandardOutput.connect(self._on_ready_stdout)
        process.readyReadStandardError.connect(self._on_ready_stderr)
        process.finished.connect(self._on_process_finished)
        process.errorOccurred.connect(self._on_process_error)
        self._process = process
        self._stdout_chunks = []
        self._stderr_chunks = []
        signals.priceUpdateStarted.emit({"reason": reason, "force": bool(force)})
        process.start()

    def _on_ready_stdout(self) -> None:
        if self._process is None:
            return
        chunk = bytes(self._process.readAllStandardOutput())
        self._stdout_chunks.append(chunk)
        text = chunk.decode("utf-8", errors="replace")
        if text:
            signals.priceUpdateOutput.emit({"stream": "stdout", "text": text})

    def _on_ready_stderr(self) -> None:
        if self._process is None:
            return
        chunk = bytes(self._process.readAllStandardError())
        self._stderr_chunks.append(chunk)
        text = chunk.decode("utf-8", errors="replace")
        if text:
            signals.priceUpdateOutput.emit({"stream": "stderr", "text": text})

    def _on_process_finished(self, exit_code: int, exit_status) -> None:
        process = self._process
        if process is not None:
            # Flush eventuele laatste bytes die nog in de buffers staan.
            self._stdout_chunks.append(bytes(process.readAllStandardOutput()))
            self._stderr_chunks.append(bytes(process.readAllStandardError()))
        stdout = b"".join(self._stdout_chunks).decode("utf-8", errors="replace")
        stderr = b"".join(self._stderr_chunks).decode("utf-8", errors="replace")
        self._stdout_chunks = []
        self._stderr_chunks = []
        self._process = None

        payload = self._parse_last_json_line(stdout)
        if payload is None:
            message = f"Kon startup price update output niet parsen. exit_code={exit_code}. {stderr.strip() or stdout.strip()}".strip()
            signals.priceUpdateFailed.emit(message)
            return

        payload["stdout"] = stdout
        payload["stderr"] = stderr
        status = payload.get("status")
        if exit_code == 0 and status in {"ok", "skipped"}:
            signals.priceUpdateFinished.emit(payload)
            return

        message = f"Historical price update faalde met exit_code={exit_code}. {stderr.strip() or stdout.strip()}".strip()
        signals.priceUpdateFailed.emit(message)

    def _on_process_error(self, process_error) -> None:
        self._process = None
        signals.priceUpdateFailed.emit(f"Historical price update procesfout: {process_error}")

    @staticmethod
    def _parse_last_json_line(stdout: str) -> dict | None:
        for line in reversed([line.strip() for line in stdout.splitlines() if line.strip()]):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        return None
