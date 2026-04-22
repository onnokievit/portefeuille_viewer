from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

import pyodbc

from portefeuille_viewer.services.historical_price_update_runner import STOCKDATA_DB_PATH


def _connect() -> pyodbc.Connection:
    conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={STOCKDATA_DB_PATH};"
    return pyodbc.connect(conn_str)


def ensure_update_runs_schema() -> None:
    with _connect() as conn:
        cur = conn.cursor()
        exists = any(row.table_name == "update_runs" for row in cur.tables(table="update_runs"))
        if not exists:
            cur.execute(
                """
                CREATE TABLE update_runs (
                    Id AUTOINCREMENT PRIMARY KEY,
                    task_name TEXT(80),
                    run_reason TEXT(120),
                    run_day DATETIME,
                    started_at DATETIME,
                    finished_at DATETIME,
                    status TEXT(32),
                    target_date DATETIME,
                    fetch_start_date DATETIME,
                    days_range LONG,
                    rows_processed LONG,
                    rows_ok LONG,
                    rows_error LONG,
                    source TEXT(80),
                    message LONGTEXT,
                    payload_json LONGTEXT
                )
                """
            )
            conn.commit()
        for stmt in [
            "CREATE INDEX idx_update_runs_task_day ON update_runs (task_name, run_day)",
            "CREATE INDEX idx_update_runs_status ON update_runs (status)",
            "CREATE INDEX idx_update_runs_started ON update_runs (started_at)",
        ]:
            try:
                cur.execute(stmt)
                conn.commit()
            except pyodbc.Error:
                conn.rollback()


def has_successful_run_today(task_name: str) -> bool:
    ensure_update_runs_schema()
    with _connect() as conn:
        cur = conn.cursor()
        row = cur.execute(
            """
            SELECT COUNT(*)
            FROM update_runs
            WHERE task_name=?
              AND status='ok'
              AND DateValue(run_day)=?
            """,
            str(task_name),
            date.today(),
        ).fetchone()
    return bool(row and row[0] and int(row[0]) > 0)


def start_update_run(
    *,
    task_name: str,
    run_reason: str,
    source: str = "",
    payload: dict[str, Any] | None = None,
) -> int | None:
    ensure_update_runs_schema()
    now = datetime.now()
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO update_runs
                (task_name, run_reason, run_day, started_at, status, source, payload_json)
            VALUES (?, ?, ?, ?, 'running', ?, ?)
            """,
            str(task_name),
            str(run_reason),
            date.today(),
            now,
            str(source or ""),
            json.dumps(payload or {}, default=str),
        )
        conn.commit()
        row = cur.execute("SELECT @@IDENTITY").fetchone()
    try:
        return int(row[0]) if row and row[0] is not None else None
    except Exception:
        return None


def finish_update_run(
    run_id: int | None,
    *,
    status: str,
    message: str = "",
    rows_processed: int | None = None,
    rows_ok: int | None = None,
    rows_error: int | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    if run_id is None:
        return
    ensure_update_runs_schema()
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE update_runs
            SET finished_at=?,
                status=?,
                message=?,
                rows_processed=?,
                rows_ok=?,
                rows_error=?,
                payload_json=?
            WHERE Id=?
            """,
            datetime.now(),
            str(status),
            str(message or "")[:32000],
            rows_processed,
            rows_ok,
            rows_error,
            json.dumps(payload or {}, default=str),
            int(run_id),
        )
        conn.commit()


def log_update_run_once(
    *,
    task_name: str,
    run_reason: str,
    status: str,
    message: str = "",
    source: str = "",
    target_date: date | None = None,
    fetch_start_date: date | None = None,
    days_range: int | None = None,
    rows_processed: int | None = None,
    rows_ok: int | None = None,
    rows_error: int | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    ensure_update_runs_schema()
    now = datetime.now()
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO update_runs
                (task_name, run_reason, run_day, started_at, finished_at, status,
                 target_date, fetch_start_date, days_range, rows_processed, rows_ok,
                 rows_error, source, message, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            str(task_name),
            str(run_reason),
            date.today(),
            now,
            now,
            str(status),
            target_date,
            fetch_start_date,
            days_range,
            rows_processed,
            rows_ok,
            rows_error,
            str(source or ""),
            str(message or "")[:32000],
            json.dumps(payload or {}, default=str),
        )
        conn.commit()
