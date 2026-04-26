from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal, Slot


class AssetVolatilityHistoryUpdateRunner(QObject):
    """Run the daily HV/IV DB update script in a separate process."""

    started = Signal(dict)
    finished = Signal(dict)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 7496,
        client_id: int = 140,
        duration: str = "5 D",
        max_in_flight: int = 3,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.host = host
        self.port = int(port)
        self.client_id = int(client_id)
        self.duration = str(duration)
        self.max_in_flight = int(max_in_flight)
        self._process: QProcess | None = None
        self._stdout_chunks: list[bytes] = []
        self._stderr_chunks: list[bytes] = []
        self._stdout_line_buffer = ""

    @Slot()
    def request_startup_update(self) -> None:
        self.request_update(reason="startup_asset_volatility_history_update")

    def request_update(self, *, reason: str = "asset_volatility_history_update") -> bool:
        if self._process is not None:
            return False

        script_path = Path(__file__).resolve().parents[2] / "price_update_scripts" / "fetch_asset_volatility_history_to_db.py"
        process = QProcess(self)
        process.setProgram(sys.executable)
        process.setArguments(
            [
                str(script_path),
                "--host",
                str(self.host),
                "--port",
                str(self.port),
                "--client-id",
                str(self.client_id),
                "--duration",
                str(self.duration),
                "--max-in-flight",
                str(self.max_in_flight),
            ]
        )
        process.readyReadStandardOutput.connect(self._on_ready_stdout)
        process.readyReadStandardError.connect(self._on_ready_stderr)
        process.finished.connect(self._on_process_finished)
        process.errorOccurred.connect(self._on_process_error)
        self._process = process
        self._stdout_chunks = []
        self._stderr_chunks = []
        self._stdout_line_buffer = ""
        payload = {
            "reason": reason,
            "duration": self.duration,
            "max_in_flight": self.max_in_flight,
            "host": self.host,
            "port": self.port,
            "client_id": self.client_id,
        }
        self.started.emit(payload)
        process.start()
        return True

    def _on_ready_stdout(self) -> None:
        if self._process is None:
            return
        chunk = bytes(self._process.readAllStandardOutput())
        self._stdout_chunks.append(chunk)
        text = chunk.decode("utf-8", errors="replace")
        self._emit_progress_lines(text)

    def _on_ready_stderr(self) -> None:
        if self._process is None:
            return
        chunk = bytes(self._process.readAllStandardError())
        self._stderr_chunks.append(chunk)
        text = chunk.decode("utf-8", errors="replace").strip()
        if text:
            self.progress.emit(text)

    def _on_process_finished(self, exit_code: int, exit_status) -> None:
        process = self._process
        if process is not None:
            self._stdout_chunks.append(bytes(process.readAllStandardOutput()))
            self._stderr_chunks.append(bytes(process.readAllStandardError()))
        stdout = b"".join(self._stdout_chunks).decode("utf-8", errors="replace")
        stderr = b"".join(self._stderr_chunks).decode("utf-8", errors="replace")
        self._stdout_chunks = []
        self._stderr_chunks = []
        self._process = None

        payload = self._parse_last_json_line(stdout)
        if payload is None:
            message = f"Kon asset volatility update output niet parsen. exit_code={exit_code}. {stderr.strip() or stdout.strip()}".strip()
            self.failed.emit(message)
            return

        payload["stdout"] = stdout
        payload["stderr"] = stderr
        payload["exit_code"] = exit_code
        status = payload.get("status")
        if exit_code == 0 and status in {"ok", "partial", "skipped"}:
            self.finished.emit(payload)
            return

        message = f"Asset volatility update faalde met exit_code={exit_code}. {stderr.strip() or stdout.strip()}".strip()
        self.failed.emit(message)

    def _on_process_error(self, process_error) -> None:
        self._process = None
        self.failed.emit(f"Asset volatility update procesfout: {process_error}")

    def _emit_progress_lines(self, text: str) -> None:
        if not text:
            return
        combined = self._stdout_line_buffer + text
        lines = combined.splitlines(keepends=True)
        self._stdout_line_buffer = ""
        for line in lines:
            if line.endswith(("\n", "\r")):
                stripped = line.strip()
                if stripped and not stripped.startswith("{"):
                    self.progress.emit(stripped)
            else:
                self._stdout_line_buffer = line

    @staticmethod
    def from_environment(*, host: str, port: int, parent: QObject | None = None) -> "AssetVolatilityHistoryUpdateRunner":
        return AssetVolatilityHistoryUpdateRunner(
            host=os.getenv("ASSET_VOL_HISTORY_UPDATE_HOST", host),
            port=int(os.getenv("ASSET_VOL_HISTORY_UPDATE_PORT", str(port))),
            client_id=int(os.getenv("ASSET_VOL_HISTORY_UPDATE_CLIENT_ID", "140")),
            duration=os.getenv("ASSET_VOL_HISTORY_UPDATE_DURATION", "5 D"),
            max_in_flight=int(os.getenv("ASSET_VOL_HISTORY_UPDATE_MAX_IN_FLIGHT", "3")),
            parent=parent,
        )

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
