from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pyodbc


OVERLAP_DAYS = 5
STOCKDATA_DB_PATH = r"C:\Users\onno\OneDrive\Beleggen\2025 - portefeuille database 02.03 - STOCKDATA.accdb"


def get_oldest_last_price_date() -> date | None:
    conn_str = (
        r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        rf"DBQ={STOCKDATA_DB_PATH}"
    )
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
    with pyodbc.connect(conn_str) as conn:
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


def build_payload() -> dict | None:
    target_date = date.today() - timedelta(days=1)
    oldest_last_date = get_oldest_last_price_date()
    if oldest_last_date and oldest_last_date >= target_date:
        return None

    if oldest_last_date is None:
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
    if payload is None:
        print(json.dumps({"status": "skipped", "reason": "startup_price_update"}))
        return 0

    script_dir = Path(__file__).resolve().parent
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []

    for script_name, extra_args in [
        ("1 A - stockprice ibkr fetch 1.1 - optimized.py", [str(payload["days_range"])]),
        ("1A_fetch_historical_index.py", [str(payload["days_range"])]),
        ("1 B - stockprice merge into historical data correct.py", []),
        ("1 C - delete temp stock price table.py", []),
    ]:
        exit_code, stdout, stderr = run_script(script_dir, script_name, extra_args)
        stdout_parts.append(stdout)
        stderr_parts.append(stderr)
        if exit_code != 0:
            print(
                json.dumps(
                    {
                        **payload,
                        "status": "failed",
                        "exit_code": exit_code,
                        "stdout": "".join(stdout_parts),
                        "stderr": "".join(stderr_parts),
                    }
                )
            )
            return exit_code

    print(
        json.dumps(
            {
                **payload,
                "status": "ok",
                "stdout": "".join(stdout_parts),
                "stderr": "".join(stderr_parts),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
