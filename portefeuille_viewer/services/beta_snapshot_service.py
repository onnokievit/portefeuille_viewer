from __future__ import annotations

from datetime import datetime
from typing import Any, cast

import numpy as np
import pandas as pd
import pyodbc
from portefeuille_viewer.config import get_settings
from portefeuille_viewer.data import repository


BETA_SNAPSHOT_TABLE = "asset_driver_beta_snapshot"
RETURN_INTERVAL_DAILY = "daily"
LOOKBACK_MONTHS: dict[str, int] = {"3m": 3, "6m": 6, "12m": 12}
MIN_OBS = 10

_HOME_INDEX_BY_REGION = {
    "NL": "AEX",
    "DE": "DAX",
    "FR": "CAC",
    "HK": "HANGSENG",
    "IN": "INDIANIFTY50",
    "JPN": "NIKKEI225",
}
_US_NDX_SECTORS = {
    "INF TECH",
    "BUSS TECH SERVICES",
    "COMMUNICATION SERV",
}


def rebuild_asset_driver_beta_snapshot(stock_db_path: str) -> dict[str, Any]:
    _ = stock_db_path
    with repository.get_stockdata_connection() as conn:
        _ensure_beta_snapshot_table(conn)
        meta = _load_asset_metadata(conn)
        prices = _load_historical_ohlcv_close_series(conn)

        if meta.empty or prices.empty:
            _replace_snapshot_rows(conn, [])
            return {
                "status": "ok",
                "table": BETA_SNAPSHOT_TABLE,
                "rows_written": 0,
                "drivers": [],
                "assets": 0,
                "lookbacks": list(LOOKBACK_MONTHS.keys()),
                "message": "No metadata or historical prices available.",
            }

        prices = _prepare_prices(prices)
        meta = _prepare_meta(meta)
        returns_wide = _build_returns_wide(prices)
        if returns_wide.empty:
            _replace_snapshot_rows(conn, [])
            return {
                "status": "ok",
                "table": BETA_SNAPSHOT_TABLE,
                "rows_written": 0,
                "drivers": [],
                "assets": 0,
                "lookbacks": list(LOOKBACK_MONTHS.keys()),
                "message": "No overlapping returns available.",
            }

        drivers = _resolve_drivers(meta, returns_wide.columns)
        rows = _build_snapshot_rows(meta, returns_wide, drivers)
        _replace_snapshot_rows(conn, rows)
        return {
            "status": "ok",
            "table": BETA_SNAPSHOT_TABLE,
            "rows_written": len(rows),
            "drivers": drivers,
            "assets": int(len(_resolve_assets(meta, returns_wide.columns))),
            "lookbacks": list(LOOKBACK_MONTHS.keys()),
        }


def _load_asset_metadata(conn: pyodbc.Connection) -> pd.DataFrame:
    sql = """
        SELECT asset_rollup, [type] AS asset_type, regio, sector, INCL_EXCL, home_index, beta_mode
        FROM asset_rollup_data
        WHERE asset_rollup IS NOT NULL
    """
    return _read_sql_dataframe(conn, sql)


def _load_historical_ohlcv_close_series(conn: pyodbc.Connection) -> pd.DataFrame:
    sql = """
        SELECT datum, asset_rollup, [close] AS close_price
        FROM historical_data_correct
        WHERE asset_rollup IS NOT NULL
          AND [close] IS NOT NULL
    """
    return _read_sql_dataframe(conn, sql)


def _read_sql_dataframe(conn: pyodbc.Connection, sql: str) -> pd.DataFrame:
    cur = conn.cursor()
    rows = cur.execute(sql).fetchall()
    columns = [col[0] for col in cur.description] if cur.description else []
    # pyodbc.Row is runtime-compatible with pandas, but Pylance does not
    # recognize it as a supported record shape for from_records.
    normalized_rows = [tuple(row) for row in rows]
    return pd.DataFrame.from_records(normalized_rows, columns=columns)


def _prepare_meta(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    asset_type_series = cast(pd.Series, out["asset_type"] if "asset_type" in out.columns else pd.Series(dtype="object"))
    regio_series = cast(pd.Series, out["regio"] if "regio" in out.columns else pd.Series(dtype="object"))
    sector_series = cast(pd.Series, out["sector"] if "sector" in out.columns else pd.Series(dtype="object"))
    incl_excl_series = cast(pd.Series, out["INCL_EXCL"] if "INCL_EXCL" in out.columns else pd.Series(dtype="object"))
    home_index_series = cast(pd.Series, out["home_index"] if "home_index" in out.columns else pd.Series(dtype="object"))
    beta_mode_series = cast(pd.Series, out["beta_mode"] if "beta_mode" in out.columns else pd.Series(dtype="object"))
    out["asset_rollup"] = out["asset_rollup"].astype(str).str.strip().str.upper()
    out["asset_type"] = asset_type_series.fillna("").astype(str).str.strip().str.lower()
    out["regio"] = regio_series.fillna("").astype(str).str.strip().str.upper()
    out["sector"] = sector_series.fillna("").astype(str).str.strip()
    out["INCL_EXCL"] = pd.to_numeric(incl_excl_series, errors="coerce").fillna(0).astype(int)
    out["home_index"] = home_index_series.fillna("").astype(str).str.strip().str.upper()
    out["beta_mode"] = beta_mode_series.fillna("").astype(str).str.strip().str.lower()
    out = out.drop_duplicates(subset=["asset_rollup"], keep="last")
    return out


def _prepare_prices(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["asset_rollup"] = out["asset_rollup"].astype(str).str.strip().str.upper()
    out["datum"] = pd.to_datetime(out["datum"], errors="coerce")
    out["close_price"] = pd.to_numeric(out["close_price"], errors="coerce")
    out = out.dropna(subset=["asset_rollup", "datum", "close_price"])
    out = out.sort_values(["asset_rollup", "datum"]).drop_duplicates(["asset_rollup", "datum"], keep="last")
    return out


def _build_returns_wide(prices: pd.DataFrame) -> pd.DataFrame:
    wide = prices.pivot(index="datum", columns="asset_rollup", values="close_price").sort_index()
    returns = wide.pct_change(fill_method=None)
    returns = returns.replace([np.inf, -np.inf], np.nan)
    returns = returns.dropna(axis=0, how="all")
    return returns


def _resolve_drivers(meta: pd.DataFrame, available_symbols: Any) -> list[str]:
    available = {str(v).strip().upper() for v in available_symbols}
    enabled_from_settings = set(get_settings().get_enabled_beta_drivers())
    mask = (meta["asset_type"] == "index") & (meta["INCL_EXCL"] == 1)
    drivers = [
        str(v).strip().upper()
        for v in meta.loc[mask, "asset_rollup"].tolist()
        if str(v).strip().upper() in available
        and (not enabled_from_settings or str(v).strip().upper() in enabled_from_settings)
    ]
    return sorted(set(drivers))


def _resolve_assets(meta: pd.DataFrame, available_symbols: Any) -> list[str]:
    available = {str(v).strip().upper() for v in available_symbols}
    mask = meta["INCL_EXCL"] == 1
    assets = [
        str(v).strip().upper()
        for v in meta.loc[mask, "asset_rollup"].tolist()
        if str(v).strip().upper() in available
    ]
    return sorted(set(assets))


def _build_snapshot_rows(meta: pd.DataFrame, returns_wide: pd.DataFrame, drivers: list[str]) -> list[tuple]:
    if not drivers:
        return []
    meta_by_asset = meta.set_index("asset_rollup", drop=False)
    available_assets = _resolve_assets(meta, returns_wide.columns)
    latest_date = returns_wide.index.max()
    updated_at = datetime.now()
    rows: list[tuple] = []
    driver_set = set(drivers)

    for lookback_code, months in LOOKBACK_MONTHS.items():
        start_date = latest_date - pd.DateOffset(months=months)
        window = returns_wide.loc[returns_wide.index >= start_date]
        if window.empty:
            continue
        for driver in drivers:
            if driver not in window.columns:
                continue
            driver_series = window[driver]
            for asset_rollup in available_assets:
                if asset_rollup not in window.columns:
                    continue
                pair = pd.concat(
                    [window[asset_rollup].rename("asset"), driver_series.rename("driver")],
                    axis=1,
                ).dropna()
                if len(pair) < MIN_OBS:
                    continue
                driver_var = float(np.var(pair["driver"].to_numpy(dtype=float), ddof=1))
                if not np.isfinite(driver_var) or driver_var <= 0.0:
                    continue
                cov = float(np.cov(pair["asset"].to_numpy(dtype=float), pair["driver"].to_numpy(dtype=float), ddof=1)[0, 1])
                beta_value = cov / driver_var
                if not np.isfinite(beta_value):
                    continue
                corr = float(np.corrcoef(pair["asset"].to_numpy(dtype=float), pair["driver"].to_numpy(dtype=float))[0, 1])
                r2 = (corr * corr) if np.isfinite(corr) else None
                meta_row = meta_by_asset.loc[asset_rollup] if asset_rollup in meta_by_asset.index else None
                home_index = _infer_home_index(meta_row, driver_set)
                beta_mode = str(meta_row.get("beta_mode") or "").strip().lower() if meta_row is not None else ""
                rows.append(
                    (
                        asset_rollup,
                        home_index,
                        beta_mode,
                        driver,
                        float(beta_value),
                        lookback_code,
                        RETURN_INTERVAL_DAILY,
                        int(len(pair)),
                        float(r2) if r2 is not None and np.isfinite(r2) else None,
                        updated_at,
                    )
                )
    return rows


def _infer_home_index(meta_row: pd.Series | None, driver_set: set[str]) -> str | None:
    if meta_row is None or getattr(meta_row, "empty", False):
        return None
    asset_rollup = str(meta_row.get("asset_rollup") or "").strip().upper()
    if asset_rollup in driver_set:
        return asset_rollup
    manual = str(meta_row.get("home_index") or "").strip().upper()
    if manual:
        return manual
    region = str(meta_row.get("regio") or "").strip().upper()
    sector = str(meta_row.get("sector") or "").strip().upper()
    if region == "US":
        candidate = "NDX" if sector in _US_NDX_SECTORS else "SPX"
        return candidate if candidate in driver_set else None
    candidate = _HOME_INDEX_BY_REGION.get(region)
    return candidate if candidate in driver_set else None


def _ensure_beta_snapshot_table(conn: pyodbc.Connection) -> None:
    cur = conn.cursor()
    exists = any(row.table_name == BETA_SNAPSHOT_TABLE for row in cur.tables(table=BETA_SNAPSHOT_TABLE))
    if not exists:
        cur.execute(
            f"""
            CREATE TABLE {BETA_SNAPSHOT_TABLE} (
                Id AUTOINCREMENT PRIMARY KEY,
                asset_rollup TEXT(64),
                home_index TEXT(64),
                beta_mode TEXT(32),
                driver_index TEXT(64),
                beta_value DOUBLE,
                lookback_code TEXT(16),
                return_interval TEXT(16),
                n_obs LONG,
                r2 DOUBLE,
                updated_at DATETIME
            )
            """
        )
        conn.commit()
    try:
        cols = {row.column_name.lower() for row in cur.columns(table=BETA_SNAPSHOT_TABLE)}
    except Exception:
        cols = set()
    for col_name, ddl in [
        ("home_index", f"ALTER TABLE {BETA_SNAPSHOT_TABLE} ADD COLUMN home_index TEXT(64)"),
        ("beta_mode", f"ALTER TABLE {BETA_SNAPSHOT_TABLE} ADD COLUMN beta_mode TEXT(32)"),
        ("driver_index", f"ALTER TABLE {BETA_SNAPSHOT_TABLE} ADD COLUMN driver_index TEXT(64)"),
        ("beta_value", f"ALTER TABLE {BETA_SNAPSHOT_TABLE} ADD COLUMN beta_value DOUBLE"),
        ("lookback_code", f"ALTER TABLE {BETA_SNAPSHOT_TABLE} ADD COLUMN lookback_code TEXT(16)"),
        ("return_interval", f"ALTER TABLE {BETA_SNAPSHOT_TABLE} ADD COLUMN return_interval TEXT(16)"),
        ("n_obs", f"ALTER TABLE {BETA_SNAPSHOT_TABLE} ADD COLUMN n_obs LONG"),
        ("r2", f"ALTER TABLE {BETA_SNAPSHOT_TABLE} ADD COLUMN r2 DOUBLE"),
        ("updated_at", f"ALTER TABLE {BETA_SNAPSHOT_TABLE} ADD COLUMN updated_at DATETIME"),
    ]:
        if col_name not in cols:
            try:
                cur.execute(ddl)
                conn.commit()
            except pyodbc.Error:
                conn.rollback()
    for stmt in [
        f"CREATE INDEX idx_{BETA_SNAPSHOT_TABLE}_key ON {BETA_SNAPSHOT_TABLE} (asset_rollup, driver_index, lookback_code)",
        f"CREATE INDEX idx_{BETA_SNAPSHOT_TABLE}_driver ON {BETA_SNAPSHOT_TABLE} (driver_index)",
    ]:
        try:
            cur.execute(stmt)
            conn.commit()
        except pyodbc.Error:
            conn.rollback()


def _replace_snapshot_rows(conn: pyodbc.Connection, rows: list[tuple]) -> None:
    cur = conn.cursor()
    cur.execute(f"DELETE FROM {BETA_SNAPSHOT_TABLE}")
    conn.commit()
    if not rows:
        return
    cur.executemany(
        f"""
        INSERT INTO {BETA_SNAPSHOT_TABLE}
            (asset_rollup, home_index, beta_mode, driver_index, beta_value, lookback_code, return_interval, n_obs, r2, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
