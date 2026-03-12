from __future__ import annotations

import sys
from collections import deque
from datetime import date, datetime
from pathlib import Path
from typing import Callable

import pyodbc
from PySide6.QtCore import QObject, QProcess

from portefeuille_viewer.data import repository
from portefeuille_viewer.signals import signals
from portefeuille_viewer.services.historical_price_update_runner import STOCKDATA_DB_PATH


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
            print(f"[state-engine-runner] ignored payload (empty/invalid): {payload}")
            return
        self._queue.append(normalized)
        print(f"[state-engine-runner] queued payload: {normalized}")
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

    def handle_price_update_finished(self, payload: dict) -> None:
        status = (payload or {}).get("status")
        if status != "ok":
            # Bij 'skipped' zijn er geen nieuwe close-prices; een price_catchup-run
            # is dan onnodig en kan bij grote scopes startup-freezes geven.
            return
        self.request_catchup_for_active_db(fetch_start_date=payload.get("fetch_start_date"))

    def handle_database_changed(self, db_name: str) -> None:
        self.request_catchup_for_active_db()

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

    def request_catchup_for_active_db(self, fetch_start_date: str | None = None) -> None:
        payload = self._build_price_catchup_payload(fetch_start_date=fetch_start_date)
        if payload:
            self.handle_rebuild_requested(payload)

    def _build_price_catchup_payload(self, fetch_start_date: str | None = None) -> dict | None:
        today = date.today()
        db_path = getattr(repository, "db_path", None)
        if not db_path:
            return None

        option_assets = self._get_assets_by_type(db_path, "optie")
        equity_assets_aandeel = self._get_assets_by_type(db_path, "aandeel")
        equity_assets_future = self._get_assets_by_type(db_path, "future")
        equity_assets = sorted(set(equity_assets_aandeel) | set(equity_assets_future))
        future_assets_set = set(equity_assets_future)
        sprinter_assets = self._get_assets_by_type(db_path, "sprinter")
        all_assets = sorted(set(option_assets) | set(equity_assets) | set(sprinter_assets))
        if not all_assets:
            return None

        shared_last_dates = self._get_shared_last_price_dates(all_assets)
        if not shared_last_dates:
            return None

        outdated_assets: set[str] = set()
        from_dates: list[date] = []
        classes: set[str] = set()

        # Opties catchup
        if option_assets:
            local_status_opt = self._get_local_state_status(db_path, option_assets, engine_name="open_opties_v2")
            local_v2_opt = self._get_local_v2_max_dates(db_path, option_assets, table_name="per_dag_open_opties_opgerold_v2")
            for asset in option_assets:
                shared_last = shared_last_dates.get(asset)
                if shared_last is None:
                    continue
                local_last = local_status_opt.get(asset)
                local_v2_last = local_v2_opt.get(asset)
                if (
                    local_last is None
                    or local_v2_last is None
                    or shared_last > local_last
                    or shared_last > local_v2_last
                ):
                    needs_price_catchup = True
                else:
                    needs_price_catchup = False
                needs_calendar_extend = (local_v2_last is not None and local_v2_last < today)
                if needs_price_catchup or needs_calendar_extend:
                    classes.add("opties")
                    outdated_assets.add(asset)
                    if fetch_start_date and needs_price_catchup:
                        from_dates.append(datetime.strptime(fetch_start_date, "%Y-%m-%d").date())
                    elif needs_price_catchup and local_v2_last is not None:
                        from_dates.append(local_v2_last)
                    elif needs_price_catchup and local_last is not None:
                        from_dates.append(local_last)
                    elif needs_price_catchup:
                        first_tx_date = self._get_first_tx_date(db_path, asset, asset_type="optie")
                        if first_tx_date:
                            from_dates.append(first_tx_date)
                    else:
                        from_dates.append(today)

        # Aandelen catchup
        if equity_assets:
            local_status_eq = self._get_local_state_status(db_path, equity_assets, engine_name="open_aandelen_v2")
            local_v2_eq = self._get_local_v2_max_dates(db_path, equity_assets, table_name="per_dag_aandelen_state_v2")
            for asset in equity_assets:
                shared_last = shared_last_dates.get(asset)
                if shared_last is None:
                    continue
                local_last = local_status_eq.get(asset)
                local_v2_last = local_v2_eq.get(asset)
                if (
                    local_last is None
                    or local_v2_last is None
                    or shared_last > local_last
                    or shared_last > local_v2_last
                ):
                    needs_price_catchup = True
                else:
                    needs_price_catchup = False
                needs_calendar_extend = (local_v2_last is not None and local_v2_last < today)
                if needs_price_catchup or needs_calendar_extend:
                    classes.add("aandelen")
                    outdated_assets.add(asset)
                    if fetch_start_date and needs_price_catchup:
                        from_dates.append(datetime.strptime(fetch_start_date, "%Y-%m-%d").date())
                    elif needs_price_catchup and local_v2_last is not None:
                        from_dates.append(local_v2_last)
                    elif needs_price_catchup and local_last is not None:
                        from_dates.append(local_last)
                    elif needs_price_catchup:
                        tx_type = "future" if asset in future_assets_set else "aandeel"
                        first_tx_date = self._get_first_tx_date(db_path, asset, asset_type=tx_type)
                        if first_tx_date:
                            from_dates.append(first_tx_date)
                    else:
                        from_dates.append(today)

        # Sprinters catchup
        if sprinter_assets:
            local_status_sp = self._get_local_state_status(db_path, sprinter_assets, engine_name="open_sprinters_v2")
            local_v2_sp = self._get_local_v2_max_dates(db_path, sprinter_assets, table_name="per_dag_open_sprinters_opgerold_v2")
            for asset in sprinter_assets:
                shared_last = shared_last_dates.get(asset)
                if shared_last is None:
                    continue
                local_last = local_status_sp.get(asset)
                local_v2_last = local_v2_sp.get(asset)
                if (
                    local_last is None
                    or local_v2_last is None
                    or shared_last > local_last
                    or shared_last > local_v2_last
                ):
                    needs_price_catchup = True
                else:
                    needs_price_catchup = False
                needs_calendar_extend = (local_v2_last is not None and local_v2_last < today)
                if needs_price_catchup or needs_calendar_extend:
                    classes.add("sprinters")
                    outdated_assets.add(asset)
                    if fetch_start_date and needs_price_catchup:
                        from_dates.append(datetime.strptime(fetch_start_date, "%Y-%m-%d").date())
                    elif needs_price_catchup and local_v2_last is not None:
                        from_dates.append(local_v2_last)
                    elif needs_price_catchup and local_last is not None:
                        from_dates.append(local_last)
                    elif needs_price_catchup:
                        first_tx_date = self._get_first_tx_date(db_path, asset, asset_type="sprinter")
                        if first_tx_date:
                            from_dates.append(first_tx_date)
                    else:
                        from_dates.append(today)

        if not classes or not outdated_assets or not from_dates:
            return None

        return {
            "asset_classes": sorted(classes),
            "affected_assets": sorted(outdated_assets),
            "from_date": min(from_dates).isoformat(),
            "reason": "price_catchup",
            "mode": "asset_incremental",
        }

    def _get_assets_by_type(self, db_path: str, asset_type: str) -> list[str]:
        conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path}"
        query = """
            SELECT DISTINCT asset_rollup
            FROM transacties_bron_data
            WHERE asset_type=?
              AND asset_rollup IS NOT NULL
        """
        with pyodbc.connect(conn_str) as conn:
            cur = conn.cursor()
            rows = cur.execute(query, asset_type).fetchall()
        return sorted({str(row[0]).strip() for row in rows if row[0] is not None and str(row[0]).strip()})

    def _get_shared_last_price_dates(self, assets: list[str]) -> dict[str, date]:
        if not assets:
            return {}
        conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={STOCKDATA_DB_PATH}"
        placeholders = ",".join("?" for _ in assets)
        query = f"""
            SELECT asset_rollup, MAX(datum) AS last_price_date
            FROM historical_data_correct
            WHERE asset_rollup IN ({placeholders})
            GROUP BY asset_rollup
        """
        with pyodbc.connect(conn_str) as conn:
            cur = conn.cursor()
            rows = cur.execute(query, assets).fetchall()
        result: dict[str, date] = {}
        for asset_rollup, last_price_date in rows:
            if isinstance(last_price_date, datetime):
                last_price_date = last_price_date.date()
            result[str(asset_rollup).strip()] = last_price_date
        return result

    def _get_local_state_status(self, db_path: str, assets: list[str], engine_name: str) -> dict[str, date]:
        if not assets:
            return {}
        conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path}"
        placeholders = ",".join("?" for _ in assets)
        query = f"""
            SELECT asset_rollup, last_price_date_used
            FROM state_engine_status
            WHERE engine_name=?
              AND asset_rollup IN ({placeholders})
        """
        try:
            with pyodbc.connect(conn_str) as conn:
                cur = conn.cursor()
                rows = cur.execute(query, [engine_name, *assets]).fetchall()
        except pyodbc.Error:
            return {}
        result: dict[str, date] = {}
        for asset_rollup, last_price_date_used in rows:
            if last_price_date_used is None:
                continue
            if isinstance(last_price_date_used, datetime):
                last_price_date_used = last_price_date_used.date()
            result[str(asset_rollup).strip()] = last_price_date_used
        return result

    def _get_local_v2_max_dates(self, db_path: str, assets: list[str], table_name: str) -> dict[str, date]:
        if not assets:
            return {}
        conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path}"
        placeholders = ",".join("?" for _ in assets)
        query = f"""
            SELECT asset_rollup, MAX(datum) AS max_v2_date
            FROM {table_name}
            WHERE asset_rollup IN ({placeholders})
            GROUP BY asset_rollup
        """
        try:
            with pyodbc.connect(conn_str) as conn:
                cur = conn.cursor()
                rows = cur.execute(query, assets).fetchall()
        except pyodbc.Error:
            return {}
        result: dict[str, date] = {}
        for asset_rollup, max_v2_date in rows:
            if max_v2_date is None:
                continue
            if isinstance(max_v2_date, datetime):
                max_v2_date = max_v2_date.date()
            result[str(asset_rollup).strip()] = max_v2_date
        return result

    def _get_first_tx_date(self, db_path: str, asset: str, asset_type: str) -> date | None:
        conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path}"
        query = """
            SELECT MIN(datum)
            FROM transacties_bron_data
            WHERE asset_type=? AND asset_rollup=?
        """
        with pyodbc.connect(conn_str) as conn:
            cur = conn.cursor()
            row = cur.execute(query, asset_type, asset).fetchone()
        if not row or row[0] is None:
            return None
        value = row[0]
        if isinstance(value, datetime):
            return value.date()
        return value

    def _start_next(self) -> None:
        if self._process is not None or not self._queue:
            return

        payload = self._queue.popleft()
        classes = [c for c in payload.get("asset_classes", []) if c in {"opties", "aandelen", "sprinters", "asset_result_v2"}]
        if not classes:
            signals.stateRebuildFinished.emit({**payload, "status": "skipped", "message": "No supported state-engine needed."})
            self._start_next()
            return

        base_classes = {"opties", "aandelen", "sprinters"}
        aggregate_scheduled = bool(payload.get("_aggregate_scheduled"))
        if (not aggregate_scheduled) and any(c in base_classes for c in classes):
            aggregate_payload = dict(payload)
            aggregate_payload["asset_classes"] = ["asset_result_v2"]
            aggregate_payload["_aggregate_scheduled"] = True
            self._queue.append(aggregate_payload)
            aggregate_scheduled = True

        # Bij gecombineerde payloads voeren we engines sequentieel uit.
        if len(classes) > 1:
            for cls in reversed(classes[1:]):
                follow_up = dict(payload)
                follow_up["asset_classes"] = [cls]
                if aggregate_scheduled:
                    follow_up["_aggregate_scheduled"] = True
                self._queue.appendleft(follow_up)
        active_class = classes[0]
        active_payload = dict(payload)
        active_payload["asset_classes"] = [active_class]
        active_payload["engine_class"] = active_class
        if aggregate_scheduled:
            active_payload["_aggregate_scheduled"] = True

        self._current_payload = active_payload
        signals.stateRebuildStarted.emit(active_payload)

        command = self._build_command(active_payload)
        if command is None:
            signals.stateRebuildFailed.emit(f"Kon {active_class} state-engine commando niet opbouwen.")
            self._current_payload = None
            self._start_next()
            return

        program, arguments = command
        print(f"[state-engine-runner] start class={active_class} mode={active_payload.get('mode')} assets={active_payload.get('affected_assets')} from={active_payload.get('from_date')}")
        process = QProcess(self)
        process.setProgram(program)
        process.setArguments(arguments)
        process.finished.connect(self._on_process_finished)
        process.errorOccurred.connect(self._on_process_error)
        self._process = process
        process.start()

    def _build_command(self, payload: dict) -> tuple[str, list[str]] | None:
        asset_class = (payload.get("asset_classes") or [None])[0]
        if asset_class == "opties":
            return self._build_options_command(payload)
        if asset_class == "aandelen":
            return self._build_aandelen_command(payload)
        if asset_class == "sprinters":
            return self._build_sprinters_command(payload)
        if asset_class == "asset_result_v2":
            return self._build_asset_result_v2_command(payload)
        return None

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

    def _build_aandelen_command(self, payload: dict) -> tuple[str, list[str]] | None:
        root_dir = Path(__file__).resolve().parents[2]
        script_path = root_dir / "state_engine" / "open_aandelen_state_v2.py"
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

    def _build_sprinters_command(self, payload: dict) -> tuple[str, list[str]] | None:
        root_dir = Path(__file__).resolve().parents[2]
        script_path = root_dir / "state_engine" / "open_sprinters_state_v2.py"
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

    def _build_asset_result_v2_command(self, payload: dict) -> tuple[str, list[str]] | None:
        root_dir = Path(__file__).resolve().parents[2]
        script_path = root_dir / "state_engine" / "per_dag_asset_result_v2.py"
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
