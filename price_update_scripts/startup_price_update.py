from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path


OVERLAP_DAYS = 5
APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from portefeuille_viewer.data.repository import get_stockdata_connection  # noqa: E402
from portefeuille_viewer.data.update_run_repository import (  # noqa: E402
    has_successful_run_today as has_successful_update_run_today,
    log_update_run_once,
)


def get_oldest_last_price_date() -> date | None:
    query = """
        SELECT MIN(last_datum) AS oldest_last_date
        FROM (
            SELECT h.asset_rollup, MAX(h.datum) AS last_datum
            FROM historical_data_correct AS h
            INNER JOIN asset_rollup_data AS a
                ON h.asset_rollup = a.asset_rollup
            WHERE a.ib_currency IS NOT NULL
              AND a.INCL_EXCL = 1
            GROUP BY h.asset_rollup
        ) AS q
    """
    with _connect() as conn:
        cur = conn.cursor()
        row = cur.execute(query).fetchone()
    if not row or row[0] is None:
        return None
    value = row[0]
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return value.date()


def _connect():
    return get_stockdata_connection()


def has_successful_run_today(run_reason: str) -> bool:
    try:
        if has_successful_update_run_today(run_reason):
            return True
    except Exception as exc:
        print(f"[startup-price-update] update_runs check failed: {exc}", file=sys.stderr)

    today = date.today()
    with _connect() as conn:
        cur = conn.cursor()
        row = cur.execute(
            """
            SELECT COUNT(*) 
            FROM price_update_runs
            WHERE run_reason = ?
              AND status = 'ok'
              AND DateValue(run_day) = ?
            """,
            run_reason,
            today,
        ).fetchone()
    return bool(row and row[0] and int(row[0]) > 0)


def log_price_update_run(payload: dict, status: str, message: str = "") -> None:
    now = datetime.now()
    target_date_value = payload.get("target_date")
    fetch_start_value = payload.get("fetch_start_date")
    target_date = datetime.strptime(target_date_value, "%Y-%m-%d").date() if target_date_value else None
    fetch_start = datetime.strptime(fetch_start_value, "%Y-%m-%d").date() if fetch_start_value else None
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO price_update_runs
                (run_reason, run_day, started_at, finished_at, status, target_date, fetch_start_date, days_range, message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            payload.get("reason", "startup_price_update"),
            date.today(),
            now,
            now,
            status,
            target_date,
            fetch_start,
            int(payload.get("days_range", OVERLAP_DAYS)),
            message[:32000] if message else "",
        )
        conn.commit()
    try:
        log_update_run_once(
            task_name=str(payload.get("reason") or "startup_price_update"),
            run_reason=str(payload.get("reason") or "startup_price_update"),
            status=status,
            target_date=target_date,
            fetch_start_date=fetch_start,
            days_range=int(payload.get("days_range", OVERLAP_DAYS)),
            rows_processed=None,
            rows_ok=None,
            rows_error=None,
            source="startup_price_update",
            message=message[:32000] if message else "",
            payload=payload,
        )
    except Exception as exc:
        print(f"[startup-price-update] update_runs log failed: {exc}", file=sys.stderr)


def build_payload() -> dict:
    target_date = date.today() - timedelta(days=1)
    oldest_last_date = get_oldest_last_price_date()

    if oldest_last_date is None:
        fetch_start = target_date - timedelta(days=OVERLAP_DAYS)
    elif oldest_last_date >= target_date:
        # Als gisteren al aanwezig is, toch overlap draaien om intraday-data van gisteren
        # te overschrijven met definitieve close bars.
        fetch_start = target_date - timedelta(days=OVERLAP_DAYS)
    else:
        fetch_start = oldest_last_date - timedelta(days=OVERLAP_DAYS)

    if fetch_start > date.today():
        fetch_start = date.today()

    days_range = max((date.today() - fetch_start).days, OVERLAP_DAYS)
    return {
        "reason": "startup_price_update",
        "target_date": target_date.isoformat(),
        "fetch_start_date": fetch_start.isoformat(),
        "days_range": days_range,
    }


def run_script(script_dir: Path, script_name: str, extra_args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, script_name, *extra_args],
        cwd=str(script_dir),
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def main() -> int:
    payload = build_payload()
    if has_successful_run_today("startup_price_update"):
        print(json.dumps({"status": "skipped", "reason": "startup_price_update_already_ran_today"}))
        return 0

    script_dir = Path(__file__).resolve().parent
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []

    for script_name, extra_args in [
        ("1 A - stockprice ibkr fetch 1.1 - optimized.py", [str(payload["days_range"])]),
        ("1A_fetch_historical_index.py", [str(payload["days_range"])]),
        ("1A_fetch_historical_futures.py", [str(payload["days_range"])]),
        ("1 B - stockprice merge into historical data correct.py", []),
        ("1 C - delete temp stock price table.py", []),
        ("rebuild_asset_driver_beta_snapshot.py", []),
    ]:
        exit_code, stdout, stderr = run_script(script_dir, script_name, extra_args)
        stdout_parts.append(stdout)
        stderr_parts.append(stderr)
        if exit_code != 0:
            merged_stdout = "".join(stdout_parts)
            merged_stderr = "".join(stderr_parts)
            log_price_update_run(
                payload=payload,
                status="failed",
                message=(merged_stderr or merged_stdout or f"exit_code={exit_code}"),
            )
            print(
                json.dumps(
                    {
                        **payload,
                        "status": "failed",
                        "exit_code": exit_code,
                        "stdout": merged_stdout,
                        "stderr": merged_stderr,
                    }
                )
            )
            return exit_code

    merged_stdout = "".join(stdout_parts)
    merged_stderr = "".join(stderr_parts)
    log_price_update_run(
        payload=payload,
        status="ok",
        message=(merged_stderr or "ok"),
    )
    print(
        json.dumps(
            {
                **payload,
                "status": "ok",
                "stdout": merged_stdout,
                "stderr": merged_stderr,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
