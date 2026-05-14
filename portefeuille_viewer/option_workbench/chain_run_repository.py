from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .asset_source import connect_access
from .models import AssetScanResult, ScannerSettings


class ChainRunRepository:
    def __init__(self, stock_db_path: str | Path) -> None:
        self.stock_db_path = str(stock_db_path)

    def ensure_schema(self) -> None:
        with connect_access(self.stock_db_path) as conn:
            cur = conn.cursor()
            self._ensure_table(cur, "option_chain_scan_runs", RUNS_TABLE_SQL)
            self._ensure_table(cur, "option_chain_scan_asset_log", ASSET_LOG_TABLE_SQL)
            conn.commit()

    def start_run(self, run_id: str, settings: ScannerSettings, asset_count: int) -> None:
        self.ensure_schema()
        now = datetime.now()
        with connect_access(self.stock_db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO option_chain_scan_runs
                    (run_id, started_at, status, tws_host, tws_port, client_id, parquet_dir, asset_count,
                     contracts_seen, contracts_inserted, contracts_updated, contracts_rejected)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    now,
                    "running",
                    settings.tws_host,
                    int(settings.tws_port),
                    int(settings.client_id_min),
                    str(settings.parquet_dir),
                    int(asset_count),
                    0,
                    0,
                    0,
                    0,
                ),
            )
            conn.commit()

    def log_asset(self, run_id: str, result: AssetScanResult, started_at: datetime, finished_at: datetime) -> None:
        self.ensure_schema()
        with connect_access(self.stock_db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO option_chain_scan_asset_log
                    (run_id, asset_rollup, ib_symbol, ib_currency, option_exchange, status, started_at,
                     finished_at, months_requested, requests_sent, contracts_returned, contracts_inserted,
                     contracts_updated, contracts_rejected, parquet_path, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    result.asset_rollup,
                    result.ib_symbol,
                    result.ib_currency,
                    result.option_exchange,
                    result.status,
                    started_at,
                    finished_at,
                    int(result.months_requested),
                    int(result.requests_sent),
                    int(result.contracts_returned),
                    int(result.contracts_inserted),
                    int(result.contracts_updated),
                    int(result.contracts_rejected),
                    result.parquet_path,
                    result.error_message,
                ),
            )
            conn.commit()

    def finish_run(self, run_id: str, status: str, results: list[AssetScanResult], error_message: str = "") -> None:
        now = datetime.now()
        with connect_access(self.stock_db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE option_chain_scan_runs
                SET finished_at=?, status=?, contracts_seen=?, contracts_inserted=?,
                    contracts_updated=?, contracts_rejected=?, error_message=?
                WHERE run_id=?
                """,
                (
                    now,
                    status,
                    sum(int(r.contracts_returned) for r in results),
                    sum(int(r.contracts_inserted) for r in results),
                    sum(int(r.contracts_updated) for r in results),
                    sum(int(r.contracts_rejected) for r in results),
                    error_message,
                    run_id,
                ),
            )
            conn.commit()

    @staticmethod
    def _ensure_table(cur, table_name: str, create_sql: str) -> None:
        try:
            cur.execute(f"SELECT TOP 1 * FROM {table_name}")
            return
        except Exception:
            pass
        cur.execute(create_sql)


RUNS_TABLE_SQL = """
CREATE TABLE option_chain_scan_runs (
    run_id TEXT(64) PRIMARY KEY,
    started_at DATETIME,
    finished_at DATETIME,
    status TEXT(32),
    tws_host TEXT(64),
    tws_port LONG,
    client_id LONG,
    parquet_dir LONGTEXT,
    asset_count LONG,
    contracts_seen LONG,
    contracts_inserted LONG,
    contracts_updated LONG,
    contracts_rejected LONG,
    error_message LONGTEXT
)
"""


ASSET_LOG_TABLE_SQL = """
CREATE TABLE option_chain_scan_asset_log (
    id AUTOINCREMENT PRIMARY KEY,
    run_id TEXT(64),
    asset_rollup TEXT(64),
    ib_symbol TEXT(64),
    ib_currency TEXT(16),
    option_exchange TEXT(32),
    status TEXT(32),
    started_at DATETIME,
    finished_at DATETIME,
    months_requested LONG,
    requests_sent LONG,
    contracts_returned LONG,
    contracts_inserted LONG,
    contracts_updated LONG,
    contracts_rejected LONG,
    parquet_path LONGTEXT,
    error_message LONGTEXT
)
"""
