from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal

from portefeuille_viewer.data import repository


class SingleAssetLongHistoryRunner(QObject):
    started = Signal(dict)
    stepStarted = Signal(dict)
    output = Signal(str)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process: QProcess | None = None
        self._asset_rollup = ""
        self._steps: list[tuple[str, Path, list[str]]] = []
        self._step_index = -1
        self._stdout_chunks: list[bytes] = []
        self._stderr_chunks: list[bytes] = []
        self._all_output: list[str] = []

    @property
    def is_running(self) -> bool:
        return self._process is not None

    def start(self, asset_rollup: str) -> None:
        if self._process is not None:
            return
        asset = str(asset_rollup or "").strip()
        if not asset:
            self.failed.emit("Geen asset_rollup opgegeven.")
            return

        script_dir = Path(__file__).resolve().parents[2] / "price_update_scripts_single_stock_fetch_long_history"
        self._asset_rollup = asset
        self._steps = [
            (
                "21 - historische data ophalen via IBKR",
                script_dir / "21 - stockprice ibkr fetch 1.1 - single stock 10Y.py",
                [asset],
            ),
            (
                "22 - temp data mergen naar historical_data_correct",
                script_dir / "22 - stockprice merge into historical data correct.py",
                [],
            ),
            (
                "23 - tijdelijke tabel leegmaken",
                script_dir / "23 - delete temp stock price table.py",
                [],
            ),
        ]
        missing = [str(path) for _label, path, _args in self._steps if not path.exists()]
        if missing:
            self.failed.emit("Script niet gevonden: " + ", ".join(missing))
            return

        self._step_index = -1
        self._all_output = []
        self.started.emit({"asset_rollup": asset, "steps": len(self._steps)})
        self.output.emit(f"Start lange historie voor {asset}\n")
        self._start_next_step()

    def _start_next_step(self) -> None:
        self._step_index += 1
        if self._step_index >= len(self._steps):
            try:
                repository.load_historical_close_snapshot()
            except Exception as exc:
                message = f"Historie staat in DB, maar herladen van app-snapshots faalde: {type(exc).__name__}: {exc}"
                self.output.emit(f"\n{message}\n")
                self.failed.emit(message)
                return
            payload = {
                "status": "ok",
                "asset_rollup": self._asset_rollup,
                "steps": len(self._steps),
                "output": "\n".join(self._all_output),
            }
            self.output.emit("\nAlle stappen succesvol afgerond.\n")
            self.finished.emit(payload)
            return

        label, script_path, args = self._steps[self._step_index]
        self._stdout_chunks = []
        self._stderr_chunks = []
        self.stepStarted.emit(
            {
                "asset_rollup": self._asset_rollup,
                "step_index": self._step_index + 1,
                "steps": len(self._steps),
                "label": label,
            }
        )
        self.output.emit(f"\n=== Stap {self._step_index + 1}/{len(self._steps)}: {label} ===\n")

        process = QProcess(self)
        process.setProgram(sys.executable)
        process.setArguments(["-u", str(script_path), *args])
        process.setWorkingDirectory(str(script_path.parent))
        process.readyReadStandardOutput.connect(self._on_ready_stdout)
        process.readyReadStandardError.connect(self._on_ready_stderr)
        process.finished.connect(self._on_process_finished)
        process.errorOccurred.connect(self._on_process_error)
        self._process = process
        process.start()

    def _on_ready_stdout(self) -> None:
        if self._process is None:
            return
        data = bytes(self._process.readAllStandardOutput())
        self._stdout_chunks.append(data)
        self._emit_output(data)

    def _on_ready_stderr(self) -> None:
        if self._process is None:
            return
        data = bytes(self._process.readAllStandardError())
        self._stderr_chunks.append(data)
        self._emit_output(data)

    def _emit_output(self, data: bytes) -> None:
        if not data:
            return
        text = data.decode("utf-8", errors="replace")
        self._all_output.append(text)
        self.output.emit(text)

    def _on_process_finished(self, exit_code: int, _exit_status) -> None:
        process = self._process
        if process is not None:
            stdout_tail = bytes(process.readAllStandardOutput())
            stderr_tail = bytes(process.readAllStandardError())
            self._stdout_chunks.append(stdout_tail)
            self._stderr_chunks.append(stderr_tail)
            self._emit_output(stdout_tail)
            self._emit_output(stderr_tail)
        label = self._steps[self._step_index][0]
        self._process = None
        if exit_code != 0:
            message = f"Stap {self._step_index + 1} faalde met exit_code={exit_code}: {label}"
            self.output.emit(f"\n{message}\n")
            self.failed.emit(message)
            return
        self.output.emit(f"\nStap {self._step_index + 1} klaar: {label}\n")
        self._start_next_step()

    def _on_process_error(self, process_error) -> None:
        self._process = None
        message = f"Procesfout tijdens lange historie update: {process_error}"
        self.output.emit(f"\n{message}\n")
        self.failed.emit(message)
