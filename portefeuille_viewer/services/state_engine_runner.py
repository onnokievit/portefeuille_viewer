from __future__ import annotations

import json
import sys
import uuid
from collections import deque
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

import pyodbc
from PySide6.QtCore import QObject, QProcess

from portefeuille_viewer.data import repository
from portefeuille_viewer.signals import signals
from portefeuille_viewer.services.historical_price_update_runner import STOCKDATA_DB_PATH


STARTUP_DAILY_CATCHUP_REASON = "startup_daily_catchup_fullscope_v1"


class StateEngineRunner(QObject):
    """Run state-engine rebuilds asynchronously from central app signals."""

    def __init__(self, fallback_refresh: Callable[[], None] | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._fallback_refresh = fallback_refresh
        self._queue: deque[dict] = deque()
        self._current_payload: dict | None = None
        self._process: QProcess | None = None
        self._auto_order_rebuild_enabled = False
        self._queue_schema_checked_db: str | None = None
        self._runs_schema_checked_db: str | None = None
        self._recover_state_from_db()

    def handle_rebuild_requested(self, payload: dict) -> None:
        normalized = self._normalize_payload(payload)
        if not normalized:
            print(f"[state-engine-runner] ignored payload (empty/invalid): {payload}")
            return
        if self._should_defer_order_rebuild(normalized):
            self._enqueue_order_rebuild_payload(normalized)
            print(f"[state-engine-runner] auto order rebuild disabled -> deferred payload: {normalized}")
            return
        self._queue.append(normalized)
        print(f"[state-engine-runner] queued payload: {normalized}")
        if self._process is None:
            self._start_next()

    def set_auto_order_rebuild(self, enabled: bool) -> None:
        self._auto_order_rebuild_enabled = bool(enabled)
        print(f"[state-engine-runner] auto order rebuild set to: {self._auto_order_rebuild_enabled}")

    def is_auto_order_rebuild_enabled(self) -> bool:
        return self._auto_order_rebuild_enabled

    def run_pending_order_rebuild_now(self) -> bool:
        summary = self.get_pending_order_rebuild_summary()
        if summary["pending_assets"] <= 0:
            print("[state-engine-runner] no pending order-driven rebuild payloads")
            return False

        bundle = self._claim_pending_order_rebuild_bundle()
        if not bundle:
            print("[state-engine-runner] no pending order-driven rebuild payloads after drain")
            return False

        from_date_value = bundle["from_date"].isoformat() if bundle["from_date"] else None
        payload = {
            "asset_classes": sorted(bundle["asset_classes"]),
            "affected_assets": sorted(bundle["affected_assets"]),
            "from_date": from_date_value,
            "reason": "manual_pending_orders_rebuild",
            "mode": "asset_incremental",
            "_queue_run_id": bundle.get("queue_run_id"),
        }

        self.handle_rebuild_requested(payload)
        return True

    def queue_pending_rebuild(self, payload: dict) -> bool:
        normalized = self._normalize_payload(payload)
        if not normalized:
            print(f"[state-engine-runner] ignored manual pending payload (empty/invalid): {payload}")
            return False
        self._enqueue_order_rebuild_payload(normalized)
        return True

    def get_runtime_status(self) -> dict:
        payload = dict(self._current_payload or {})
        return {
            "running": self._process is not None,
            "payload": payload,
            "engine_class": payload.get("engine_class"),
            "from_date": payload.get("from_date"),
            "affected_assets": list(payload.get("affected_assets") or []),
            "reason": payload.get("reason"),
        }

    def get_pending_order_rebuild_summary(self) -> dict:
        db_path = getattr(repository, "db_path", None)
        if not db_path:
            return {"pending_assets": 0, "pending_classes": [], "from_date": None, "reasons": []}
        try:
            self._ensure_state_rebuild_queue_table(db_path)
            conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path}"
            with pyodbc.connect(conn_str) as conn:
                cur = conn.cursor()
                rows = cur.execute(
                    """
                    SELECT asset_rollup, asset_class, from_date, reason
                    FROM state_rebuild_queue
                    WHERE status='pending'
                    """
                ).fetchall()
        except Exception as exc:
            print(f"[state-engine-runner] pending summary failed: {exc}")
            return {"pending_assets": 0, "pending_classes": [], "from_date": None, "reasons": []}

        assets = set()
        classes = set()
        reasons = set()
        min_date: date | None = None
        for asset_rollup, asset_class, from_date_value, reason in rows:
            if asset_rollup:
                assets.add(str(asset_rollup).strip())
            if asset_class:
                classes.add(str(asset_class).strip().lower())
            if reason:
                reasons.add(str(reason).strip())
            parsed = self._parse_iso_date(from_date_value)
            if parsed is not None and (min_date is None or parsed < min_date):
                min_date = parsed

        return {
            "pending_assets": len(assets),
            "pending_classes": sorted(classes),
            "from_date": min_date.isoformat() if min_date else None,
            "reasons": sorted(reasons),
        }

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
        if status not in {"ok", "skipped"}:
            return
        self.request_daily_full_catchup_for_active_db(
            fetch_start_date=payload.get("fetch_start_date"),
            reason=STARTUP_DAILY_CATCHUP_REASON,
        )

    def handle_database_changed(self, db_name: str) -> None:
        _ = db_name
        self.request_daily_full_catchup_for_active_db(reason=STARTUP_DAILY_CATCHUP_REASON)

    def request_daily_full_catchup_for_active_db(
        self,
        fetch_start_date: str | None = None,
        reason: str = STARTUP_DAILY_CATCHUP_REASON,
    ) -> None:
        if self._has_successful_startup_daily_catchup_today():
            print("[state-engine-runner] daily full catchup already ran today -> skip")
            return
        effective_fetch_start = self._resolve_daily_fetch_start(fetch_start_date)
        payloads = self._build_daily_full_catchup_payloads(
            fetch_start_date=effective_fetch_start,
            reason=reason,
        )
        for payload in payloads:
            self.handle_rebuild_requested(payload)

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

    def _is_order_driven_reason(self, reason: str) -> bool:
        value = (reason or "").strip().lower()
        if value.startswith("order_"):
            return True
        if value.startswith("optie_eind_"):
            return True
        return value in {"legacy_orders_committed"}

    def _should_defer_order_rebuild(self, payload: dict) -> bool:
        if self._auto_order_rebuild_enabled:
            return False
        reason = str(payload.get("reason") or "").strip().lower()
        if reason == "price_catchup":
            return False
        if reason == "manual_pending_orders_rebuild":
            return False
        return self._is_order_driven_reason(reason)

    def _parse_iso_date(self, value) -> date | None:
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

    def _ensure_state_rebuild_queue_table(self, db_path: str) -> None:
        if self._queue_schema_checked_db == db_path:
            return
        conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path}"
        with pyodbc.connect(conn_str) as conn:
            cur = conn.cursor()
            exists = any(row.table_name == "state_rebuild_queue" for row in cur.tables(table="state_rebuild_queue"))
            if not exists:
                cur.execute(
                    """
                    CREATE TABLE state_rebuild_queue (
                        Id AUTOINCREMENT PRIMARY KEY,
                        created_at DATETIME,
                        asset_rollup TEXT(64),
                        asset_class TEXT(20),
                        from_date DATETIME,
                        reason TEXT(64),
                        status TEXT(20),
                        run_id TEXT(64),
                        updated_at DATETIME
                    )
                    """
                )
                conn.commit()
            try:
                cols = {row.column_name.lower() for row in cur.columns(table="state_rebuild_queue")}
            except Exception:
                cols = set()
            for col_name, ddl in [
                ("run_id", "ALTER TABLE state_rebuild_queue ADD COLUMN run_id TEXT(64)"),
                ("updated_at", "ALTER TABLE state_rebuild_queue ADD COLUMN updated_at DATETIME"),
                ("status", "ALTER TABLE state_rebuild_queue ADD COLUMN status TEXT(20)"),
            ]:
                if col_name not in cols:
                    try:
                        cur.execute(ddl)
                        conn.commit()
                    except pyodbc.Error:
                        conn.rollback()
            # Best effort index-creation.
            for stmt in [
                "CREATE INDEX idx_state_rebuild_queue_status ON state_rebuild_queue (status)",
                "CREATE INDEX idx_state_rebuild_queue_asset_class ON state_rebuild_queue (asset_rollup, asset_class)",
                "CREATE INDEX idx_state_rebuild_queue_run_id ON state_rebuild_queue (run_id)",
            ]:
                try:
                    cur.execute(stmt)
                    conn.commit()
                except pyodbc.Error:
                    conn.rollback()
        self._queue_schema_checked_db = db_path

    def _ensure_state_runs_table(self, db_path: str) -> None:
        if self._runs_schema_checked_db == db_path:
            return
        conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path}"
        with pyodbc.connect(conn_str) as conn:
            cur = conn.cursor()
            exists = any(row.table_name == "state_runs" for row in cur.tables(table="state_runs"))
            if not exists:
                cur.execute(
                    """
                    CREATE TABLE state_runs (
                        Id AUTOINCREMENT PRIMARY KEY,
                        run_id TEXT(64),
                        created_at DATETIME,
                        started_at DATETIME,
                        finished_at DATETIME,
                        status TEXT(24),
                        engine_class TEXT(24),
                        reason TEXT(64),
                        mode TEXT(32),
                        from_date DATETIME,
                        affected_assets LONGTEXT,
                        payload_json LONGTEXT,
                        exit_code LONG,
                        error_text LONGTEXT
                    )
                    """
                )
                conn.commit()
            for stmt in [
                "CREATE INDEX idx_state_runs_run_id ON state_runs (run_id)",
                "CREATE INDEX idx_state_runs_status ON state_runs (status)",
            ]:
                try:
                    cur.execute(stmt)
                    conn.commit()
                except pyodbc.Error:
                    conn.rollback()
        self._runs_schema_checked_db = db_path

    def _enqueue_order_rebuild_payload(self, payload: dict) -> None:
        db_path = getattr(repository, "db_path", None)
        if not db_path:
            return
        self._ensure_state_rebuild_queue_table(db_path)
        assets = payload.get("affected_assets") or []
        classes = payload.get("asset_classes") or []
        from_date_value = self._parse_iso_date(payload.get("from_date")) or date.today()
        reason = str(payload.get("reason") or "unknown")
        now = datetime.now()
        conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path}"
        with pyodbc.connect(conn_str) as conn:
            cur = conn.cursor()
            inserted = 0
            updated = 0
            now = datetime.now()
            for asset in assets:
                for asset_class in classes:
                    asset_value = str(asset).strip()
                    class_value = str(asset_class).strip().lower()
                    existing = cur.execute(
                        """
                        SELECT TOP 1 Id
                        FROM state_rebuild_queue
                        WHERE asset_rollup=?
                          AND asset_class=?
                          AND from_date=?
                          AND reason=?
                          AND status IN ('pending', 'running')
                        ORDER BY Id DESC
                        """,
                        asset_value,
                        class_value,
                        from_date_value,
                        reason,
                    ).fetchone()
                    if existing:
                        cur.execute(
                            """
                            UPDATE state_rebuild_queue
                            SET updated_at=?
                            WHERE Id=?
                            """,
                            now,
                            int(existing[0]),
                        )
                        updated += 1
                        continue
                    cur.execute(
                        """
                        INSERT INTO state_rebuild_queue
                            (created_at, asset_rollup, asset_class, from_date, reason, status, run_id, updated_at)
                        VALUES (?, ?, ?, ?, ?, 'pending', Null, ?)
                        """,
                        now,
                        asset_value,
                        class_value,
                        from_date_value,
                        reason,
                        now,
                    )
                    inserted += 1
            conn.commit()
        print(f"[state-engine-runner] queued pending order rebuild rows: {inserted} (dedup-updated={updated})")

    def _claim_pending_order_rebuild_bundle(self) -> dict | None:
        db_path = getattr(repository, "db_path", None)
        if not db_path:
            return None
        self._ensure_state_rebuild_queue_table(db_path)
        conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path}"
        queue_run_id = str(uuid.uuid4())
        with pyodbc.connect(conn_str) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE state_rebuild_queue
                SET status='running', run_id=?, updated_at=?
                WHERE status='pending'
                """,
                queue_run_id,
                datetime.now(),
            )
            conn.commit()
            rows = cur.execute(
                """
                SELECT Id, asset_rollup, asset_class, from_date, reason
                FROM state_rebuild_queue
                WHERE run_id=?
                """
                ,
                queue_run_id,
            ).fetchall()
            if not rows:
                return None

        assets: set[str] = set()
        classes: set[str] = set()
        reasons: set[str] = set()
        min_date: date | None = None
        for _, asset_rollup, asset_class, from_date_value, reason in rows:
            if asset_rollup:
                assets.add(str(asset_rollup).strip())
            if asset_class:
                classes.add(str(asset_class).strip().lower())
            if reason:
                reasons.add(str(reason).strip())
            parsed = self._parse_iso_date(from_date_value)
            if parsed is not None and (min_date is None or parsed < min_date):
                min_date = parsed

        return {
            "affected_assets": sorted(assets),
            "asset_classes": sorted(classes),
            "from_date": min_date,
            "reasons": sorted(reasons),
            "queue_run_id": queue_run_id,
        }

    def _recover_state_from_db(self) -> None:
        db_path = getattr(repository, "db_path", None)
        if not db_path:
            return
        try:
            self._ensure_state_rebuild_queue_table(db_path)
            self._ensure_state_runs_table(db_path)
            conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path}"
            with pyodbc.connect(conn_str) as conn:
                cur = conn.cursor()
                # Queue recovery: put dangling running rows back to pending.
                cur.execute(
                    """
                    UPDATE state_rebuild_queue
                    SET status='pending', run_id=Null, updated_at=?
                    WHERE status='running'
                    """,
                    datetime.now(),
                )
                # Journal recovery: mark hanging runs as recovered-aborted.
                cur.execute(
                    """
                    UPDATE state_runs
                    SET status='aborted_recovered', finished_at=?
                    WHERE status='running'
                    """,
                    datetime.now(),
                )
                conn.commit()
        except Exception as exc:
            print(f"[state-engine-runner] recovery skipped: {exc}")

    def request_catchup_for_active_db(self, fetch_start_date: str | None = None, reason: str = "price_catchup") -> None:
        payloads = self._build_price_catchup_payloads(fetch_start_date=fetch_start_date, reason=reason)
        for payload in payloads:
            self.handle_rebuild_requested(payload)

    def _build_daily_full_catchup_payloads(
        self,
        fetch_start_date: str | None = None,
        reason: str = STARTUP_DAILY_CATCHUP_REASON,
    ) -> list[dict]:
        db_path = getattr(repository, "db_path", None)
        if not db_path:
            return []

        from_date = self._parse_iso_date(fetch_start_date)
        if from_date is None:
            from_date = date.today() - timedelta(days=5)

        option_assets = self._get_assets_by_type(db_path, "optie")
        equity_assets_aandeel = self._get_assets_by_type(db_path, "aandeel")
        equity_assets_future = self._get_assets_by_type(db_path, "future")
        equity_assets = sorted(set(equity_assets_aandeel) | set(equity_assets_future))
        sprinter_assets = self._get_assets_by_type(db_path, "sprinter")

        out: list[dict] = []
        aggregate_assets: set[str] = set()
        for cls, assets in (
            ("aandelen", equity_assets),
            ("opties", option_assets),
            ("sprinters", sprinter_assets),
        ):
            if not assets:
                continue
            aggregate_assets.update(assets)
            out.append(
                {
                    "asset_classes": [cls],
                    "affected_assets": assets,
                    "from_date": from_date.isoformat(),
                    "reason": reason,
                    "mode": "asset_incremental",
                    "_aggregate_scheduled": True,
                }
            )

        if aggregate_assets:
            out.append(
                {
                    "asset_classes": ["asset_result_v2"],
                    "affected_assets": sorted(aggregate_assets),
                    "from_date": from_date.isoformat(),
                    "reason": reason,
                    "mode": "asset_incremental",
                    "_aggregate_scheduled": True,
                }
            )
        return out

    def _resolve_daily_fetch_start(self, fetch_start_date: str | None) -> str | None:
        parsed = self._parse_iso_date(fetch_start_date)
        if parsed is not None:
            return parsed.isoformat()
        fallback = self._get_today_startup_price_fetch_start_date()
        if fallback is not None:
            return fallback.isoformat()
        return None

    def _get_today_startup_price_fetch_start_date(self) -> date | None:
        try:
            conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={STOCKDATA_DB_PATH}"
            with pyodbc.connect(conn_str) as conn:
                cur = conn.cursor()
                row = cur.execute(
                    """
                    SELECT TOP 1 fetch_start_date
                    FROM price_update_runs
                    WHERE run_reason='startup_price_update'
                      AND status='ok'
                      AND DateValue(run_day)=?
                    ORDER BY started_at DESC
                    """,
                    date.today(),
                ).fetchone()
            if not row or row[0] is None:
                return None
            value = row[0]
            if isinstance(value, datetime):
                return value.date()
            if isinstance(value, date):
                return value
            return self._parse_iso_date(value)
        except Exception as exc:
            print(f"[state-engine-runner] cannot resolve startup fetch_start_date: {exc}")
            return None

    def _build_price_catchup_payloads(self, fetch_start_date: str | None = None, reason: str = "price_catchup") -> list[dict]:
        today = date.today()
        lookback_floor = today - timedelta(days=5)
        fetch_start = datetime.strptime(fetch_start_date, "%Y-%m-%d").date() if fetch_start_date else None
        db_path = getattr(repository, "db_path", None)
        if not db_path:
            return []

        option_assets = self._get_assets_by_type(db_path, "optie")
        if reason != STARTUP_DAILY_CATCHUP_REASON:
            open_option_assets = self._get_open_assets_by_type(db_path, "optie")
            option_assets = sorted(set(option_assets) & open_option_assets)
        else:
            option_assets = sorted(set(option_assets))

        equity_assets_aandeel = self._get_assets_by_type(db_path, "aandeel")
        equity_assets_future = self._get_assets_by_type(db_path, "future")
        equity_assets = sorted(set(equity_assets_aandeel) | set(equity_assets_future))
        if reason != STARTUP_DAILY_CATCHUP_REASON:
            open_equity_assets = self._get_open_assets_by_type(db_path, "aandeel") | self._get_open_assets_by_type(db_path, "future")
            equity_assets = sorted(set(equity_assets) & open_equity_assets)
        else:
            equity_assets = sorted(set(equity_assets))
        future_assets_set = set(equity_assets_future)
        sprinter_assets = self._get_assets_by_type(db_path, "sprinter")
        if reason != STARTUP_DAILY_CATCHUP_REASON:
            open_sprinter_assets = self._get_open_assets_by_type(db_path, "sprinter")
            sprinter_assets = sorted(set(sprinter_assets) & open_sprinter_assets)
        else:
            sprinter_assets = sorted(set(sprinter_assets))
        all_assets = sorted(set(option_assets) | set(equity_assets) | set(sprinter_assets))
        if not all_assets:
            return []

        shared_last_dates = self._get_shared_last_price_dates(all_assets)
        if not shared_last_dates:
            return []

        class_assets: dict[str, set[str]] = {"opties": set(), "aandelen": set(), "sprinters": set()}
        class_from_dates: dict[str, list[date]] = {"opties": [], "aandelen": [], "sprinters": []}

        def add_class_scope(asset_class: str, asset: str, candidate_date: date | None) -> None:
            class_assets[asset_class].add(asset)
            if candidate_date is not None:
                class_from_dates[asset_class].append(candidate_date)

        def finalize_from_date(dates: list[date]) -> date | None:
            if not dates:
                return None
            # Gebruik oudste benodigde datum, met minstens 5 dagen overlap.
            # Voorbeeld: min(oudste_nodig, today-5).
            return min(min(dates), lookback_floor)

        # Opties catchup (batch)
        if option_assets:
            local_status_opt = self._get_local_state_status(db_path, option_assets, engine_name="open_opties_v2")
            for asset in option_assets:
                shared_last = shared_last_dates.get(asset)
                if shared_last is None:
                    continue
                local_last = local_status_opt.get(asset)
                # Opties: local_v2 kan oud zijn zodra series gesloten zijn; gebruik status als primaire waarheid.
                needs_price_catchup = (local_last is None or shared_last > local_last)
                if needs_price_catchup:
                    if fetch_start is not None:
                        candidate = fetch_start
                    elif local_last is not None:
                        candidate = local_last
                    else:
                        first_tx_date = self._get_first_tx_date(db_path, asset, asset_type="optie")
                        candidate = first_tx_date
                    add_class_scope("opties", asset, candidate)

        # Aandelen catchup (batch)
        if equity_assets:
            local_status_eq = self._get_local_state_status(db_path, equity_assets, engine_name="open_aandelen_v2")
            for asset in equity_assets:
                shared_last = shared_last_dates.get(asset)
                if shared_last is None:
                    continue
                local_last = local_status_eq.get(asset)
                needs_price_catchup = (local_last is None or shared_last > local_last)
                if needs_price_catchup:
                    if fetch_start is not None:
                        candidate = fetch_start
                    elif local_last is not None:
                        candidate = local_last
                    else:
                        tx_type = "future" if asset in future_assets_set else "aandeel"
                        first_tx_date = self._get_first_tx_date(db_path, asset, asset_type=tx_type)
                        candidate = first_tx_date
                    add_class_scope("aandelen", asset, candidate)

        # Sprinters catchup (batch)
        if sprinter_assets:
            local_status_sp = self._get_local_state_status(db_path, sprinter_assets, engine_name="open_sprinters_v2")
            for asset in sprinter_assets:
                shared_last = shared_last_dates.get(asset)
                if shared_last is None:
                    continue
                local_last = local_status_sp.get(asset)
                needs_price_catchup = (local_last is None or shared_last > local_last)
                if needs_price_catchup:
                    if fetch_start is not None:
                        candidate = fetch_start
                    elif local_last is not None:
                        candidate = local_last
                    else:
                        first_tx_date = self._get_first_tx_date(db_path, asset, asset_type="sprinter")
                        candidate = first_tx_date
                    add_class_scope("sprinters", asset, candidate)

        out: list[dict] = []
        aggregate_assets: set[str] = set()
        aggregate_from_dates: list[date] = []

        for cls in ("aandelen", "opties", "sprinters"):
            assets_cls = sorted(class_assets.get(cls) or [])
            if not assets_cls:
                continue
            from_date_cls = finalize_from_date(class_from_dates.get(cls) or [])
            if from_date_cls is None:
                continue
            aggregate_assets.update(assets_cls)
            aggregate_from_dates.append(from_date_cls)
            out.append(
                {
                    "asset_classes": [cls],
                    "affected_assets": assets_cls,
                    "from_date": from_date_cls.isoformat(),
                    "reason": reason,
                    "mode": "asset_incremental",
                    # Eén gecombineerde aggregate-run volgt aan het einde.
                    "_aggregate_scheduled": True,
                }
            )

        if aggregate_assets and aggregate_from_dates:
            out.append(
                {
                    "asset_classes": ["asset_result_v2"],
                    "affected_assets": sorted(aggregate_assets),
                    "from_date": min(aggregate_from_dates).isoformat(),
                    "reason": reason,
                    "mode": "asset_incremental",
                    "_aggregate_scheduled": True,
                }
            )
        return out

    def _has_successful_startup_daily_catchup_today(self) -> bool:
        db_path = getattr(repository, "db_path", None)
        if not db_path:
            return False
        try:
            required_classes = self._expected_daily_engine_classes(db_path)
            if not required_classes:
                # Geen relevante assets in deze DB: niets te catchuppen.
                return True
            self._ensure_state_runs_table(db_path)
            conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path}"
            with pyodbc.connect(conn_str) as conn:
                cur = conn.cursor()
                rows = cur.execute(
                    """
                    SELECT DISTINCT engine_class
                    FROM state_runs
                    WHERE reason=?
                      AND status='ok'
                      AND DateValue(started_at)=?
                    """,
                    STARTUP_DAILY_CATCHUP_REASON,
                    date.today(),
                ).fetchall()
            present_classes = {
                str(r[0]).strip().lower()
                for r in rows
                if r and r[0] is not None and str(r[0]).strip()
            }
            return required_classes.issubset(present_classes)
        except Exception as exc:
            print(f"[state-engine-runner] startup daily catchup check failed: {exc}")
            return False

    def _expected_daily_engine_classes(self, db_path: str) -> set[str]:
        option_assets = self._get_assets_by_type(db_path, "optie")
        equity_assets = set(self._get_assets_by_type(db_path, "aandeel")) | set(
            self._get_assets_by_type(db_path, "future")
        )
        sprinter_assets = self._get_assets_by_type(db_path, "sprinter")

        classes: set[str] = set()
        if equity_assets:
            classes.add("aandelen")
        if option_assets:
            classes.add("opties")
        if sprinter_assets:
            classes.add("sprinters")
        if classes:
            classes.add("asset_result_v2")
        return classes

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

    def _get_open_assets_by_type(self, db_path: str, asset_type: str) -> set[str]:
        conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path}"
        if asset_type == "optie":
            query = """
                SELECT asset_rollup
                FROM transacties_bron_data
                WHERE asset_type='optie'
                  AND optie_exp_date >= Date()
                  AND asset_rollup IS NOT NULL
                GROUP BY asset_rollup
                HAVING Sum(transactie_aantal) <> 0
            """
        else:
            query = """
                SELECT asset_rollup
                FROM transacties_bron_data
                WHERE asset_type=?
                  AND asset_rollup IS NOT NULL
                GROUP BY asset_rollup
                HAVING Sum(transactie_aantal) <> 0
            """
        with pyodbc.connect(conn_str) as conn:
            cur = conn.cursor()
            if asset_type == "optie":
                rows = cur.execute(query).fetchall()
            else:
                rows = cur.execute(query, asset_type).fetchall()
        return {str(row[0]).strip() for row in rows if row[0] is not None and str(row[0]).strip()}

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
        self._start_run_journal(active_payload)
        signals.stateRebuildStarted.emit(active_payload)

        command = self._build_command(active_payload)
        if command is None:
            signals.stateRebuildFailed.emit(f"Kon {active_class} state-engine commando niet opbouwen.")
            self._finish_run_journal(active_payload, status="failed_build_command", exit_code=-1, error_text="build_command_failed")
            self._finalize_queue_after_run(active_payload, success=False)
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
        process.readyReadStandardOutput.connect(self._on_process_stdout)
        process.readyReadStandardError.connect(self._on_process_stderr)
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
            self._finish_run_journal(payload, status="ok", exit_code=exit_code, error_text=(stderr.strip() or None))
            self._finalize_queue_after_run(payload, success=True)
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
            self._finish_run_journal(
                payload,
                status="failed",
                exit_code=exit_code,
                error_text=(stderr.strip() or stdout.strip() or "unknown state-engine failure"),
            )
            self._finalize_queue_after_run(payload, success=False)
            message = f"State-engine faalde met exit_code={exit_code}. {stderr.strip() or stdout.strip()}".strip()
            signals.stateRebuildFailed.emit(message)
        self._start_next()

    def _on_process_error(self, process_error) -> None:
        payload = dict(self._current_payload or {})
        self._finish_run_journal(payload, status="process_error", exit_code=-1, error_text=str(process_error))
        self._finalize_queue_after_run(payload, success=False)
        self._process = None
        self._current_payload = None
        signals.stateRebuildFailed.emit(f"State-engine procesfout: {process_error}. payload={payload}")
        self._start_next()

    def _emit_process_output(self, stream: str, text: str) -> None:
        payload = dict(self._current_payload or {})
        cleaned = (text or "").replace("\r\n", "\n").replace("\r", "\n")
        for line in cleaned.split("\n"):
            message = line.strip()
            if not message:
                continue
            signals.queued_emit_stateRebuildOutput(
                {
                    "stream": stream,
                    "text": message,
                    "engine_class": payload.get("engine_class"),
                    "reason": payload.get("reason"),
                    "from_date": payload.get("from_date"),
                    "affected_assets": list(payload.get("affected_assets") or []),
                }
            )

    def _on_process_stdout(self) -> None:
        process = self._process
        if process is None:
            return
        text = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")
        self._emit_process_output("stdout", text)

    def _on_process_stderr(self) -> None:
        process = self._process
        if process is None:
            return
        text = bytes(process.readAllStandardError()).decode("utf-8", errors="replace")
        self._emit_process_output("stderr", text)

    def _start_run_journal(self, payload: dict) -> None:
        db_path = getattr(repository, "db_path", None)
        if not db_path:
            return
        self._ensure_state_runs_table(db_path)
        run_id = str(payload.get("_queue_run_id") or uuid.uuid4())
        payload["_state_run_id"] = run_id
        safe_payload = {k: v for k, v in payload.items() if not str(k).startswith("_")}
        conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path}"
        with pyodbc.connect(conn_str) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO state_runs
                    (run_id, created_at, started_at, status, engine_class, reason, mode, from_date, affected_assets, payload_json)
                VALUES (?, ?, ?, 'running', ?, ?, ?, ?, ?, ?)
                """,
                run_id,
                datetime.now(),
                datetime.now(),
                str(payload.get("engine_class") or ""),
                str(payload.get("reason") or ""),
                str(payload.get("mode") or ""),
                self._parse_iso_date(payload.get("from_date")),
                ",".join(payload.get("affected_assets") or []),
                json.dumps(safe_payload, default=str),
            )
            conn.commit()

    def _finish_run_journal(self, payload: dict, status: str, exit_code: int, error_text: str | None = None) -> None:
        db_path = getattr(repository, "db_path", None)
        run_id = payload.get("_state_run_id")
        if not db_path or not run_id:
            return
        conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path}"
        with pyodbc.connect(conn_str) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE state_runs
                SET status=?, finished_at=?, exit_code=?, error_text=?
                WHERE run_id=? AND status='running'
                """,
                str(status),
                datetime.now(),
                int(exit_code),
                (str(error_text) if error_text else None),
                str(run_id),
            )
            conn.commit()

    def _finalize_queue_after_run(self, payload: dict, success: bool) -> None:
        queue_run_id = payload.get("_queue_run_id")
        db_path = getattr(repository, "db_path", None)
        if not queue_run_id or not db_path:
            return
        conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path}"
        with pyodbc.connect(conn_str) as conn:
            cur = conn.cursor()
            if success:
                cur.execute(
                    """
                    UPDATE state_rebuild_queue
                    SET status='done', updated_at=?
                    WHERE run_id=? AND status='running'
                    """,
                    datetime.now(),
                    str(queue_run_id),
                )
            else:
                cur.execute(
                    """
                    UPDATE state_rebuild_queue
                    SET status='pending', run_id=Null, updated_at=?
                    WHERE run_id=? AND status='running'
                    """,
                    datetime.now(),
                    str(queue_run_id),
                )
            conn.commit()
