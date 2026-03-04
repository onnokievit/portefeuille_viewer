from __future__ import annotations

import sys
from collections import deque
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QProcess

from portefeuille_viewer.data import repository
from portefeuille_viewer.signals import signals


class StateEngineRunner(QObject):
    """Run state-engine rebuilds asynchronously from central app signals."""

    def __init__(self, fallback_refresh: Callable[[], None] | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._fallback_refresh = fallback_refresh
        self._queue: deque[dict] = deque()
        self._current_payload: dict | None = None
        self._process: QProcess | None = None

    def handle_rebuild_requested(self, payload: dict) -> None:
        normalized = self._normalize_payload(payload)
        if not normalized:
            return
        self._queue.append(normalized)
        if self._process is None:
            self._start_next()

    def handle_orders_committed(self) -> None:
        payload = {
            "asset_classes": [],
            "affected_assets": [],
            "from_date": None,
            "reason": "legacy_orders_committed",
            "mode": "fallback_full_refresh",
        }
        signals.stateRebuildRequested.emit(payload)
        if self._fallback_refresh is not None:
            self._fallback_refresh()

    def _normalize_payload(self, payload: dict | None) -> dict | None:
        if not payload:
            return None
        normalized = dict(payload)
        normalized["asset_classes"] = sorted({str(x).strip().lower() for x in payload.get("asset_classes", []) if str(x).strip()})
        normalized["affected_assets"] = sorted({str(x).strip() for x in payload.get("affected_assets", []) if str(x).strip()})
        normalized["from_date"] = payload.get("from_date")
        normalized["reason"] = payload.get("reason") or "unknown"
        normalized["mode"] = payload.get("mode") or "asset_incremental"
        if not normalized["asset_classes"] and not normalized["affected_assets"]:
            return None
        return normalized

    def _start_next(self) -> None:
        if self._process is not None or not self._queue:
            return

        payload = self._queue.popleft()
        self._current_payload = payload
        signals.stateRebuildStarted.emit(payload)

        if "opties" not in payload.get("asset_classes", []):
            signals.stateRebuildFinished.emit({**payload, "status": "skipped", "message": "No options rebuild needed."})
            self._current_payload = None
            self._start_next()
            return

        command = self._build_options_command(payload)
        if command is None:
            signals.stateRebuildFailed.emit("Kon options state-engine commando niet opbouwen.")
            self._current_payload = None
            self._start_next()
            return

        program, arguments = command
        process = QProcess(self)
        process.setProgram(program)
        process.setArguments(arguments)
        process.finished.connect(self._on_process_finished)
        process.errorOccurred.connect(self._on_process_error)
        self._process = process
        process.start()

    def _build_options_command(self, payload: dict) -> tuple[str, list[str]] | None:
        root_dir = Path(__file__).resolve().parents[2]
        script_path = root_dir / "state_engine" / "open_opties_state_v2.py"
        if not script_path.exists():
            return None

        db_path = getattr(repository, "db_path", None)
        if not db_path:
            return None

        mode = payload.get("mode") or "asset_incremental"
        arguments = [
            str(script_path),
            "--db",
            str(db_path),
            "--mode",
            str(mode),
        ]
        affected_assets = payload.get("affected_assets") or []
        if affected_assets:
            arguments.extend(["--asset-rollups", ",".join(affected_assets)])
        from_date = payload.get("from_date")
        if mode == "asset_incremental" and from_date:
            arguments.extend(["--from-date", str(from_date)])
        return sys.executable, arguments

    def _on_process_finished(self, exit_code: int, exit_status) -> None:
        payload = dict(self._current_payload or {})
        process = self._process
        stdout = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace") if process else ""
        stderr = bytes(process.readAllStandardError()).decode("utf-8", errors="replace") if process else ""
        self._process = None
        self._current_payload = None

        if exit_code == 0:
            signals.stateRebuildFinished.emit(
                {
                    **payload,
                    "status": "ok",
                    "exit_code": exit_code,
                    "stdout": stdout,
                    "stderr": stderr,
                }
            )
        else:
            message = f"State-engine faalde met exit_code={exit_code}. {stderr.strip() or stdout.strip()}".strip()
            signals.stateRebuildFailed.emit(message)
        self._start_next()

    def _on_process_error(self, process_error) -> None:
        payload = dict(self._current_payload or {})
        self._process = None
        self._current_payload = None
        signals.stateRebuildFailed.emit(f"State-engine procesfout: {process_error}. payload={payload}")
        self._start_next()
