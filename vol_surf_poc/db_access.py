from __future__ import annotations

from pathlib import Path

import pyodbc


TRUE_TEXT = {"1", "-1", "true", "yes", "ja", "j", "y", "on", "waar"}


def connect_access(db_path: str | Path):
    return pyodbc.connect(rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path}")


def truthy(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in TRUE_TEXT


def table_columns(cursor, table_name: str) -> set[str]:
    out: set[str] = set()
    try:
        for row in cursor.columns(table=table_name):
            out.add(str(row.column_name).lower())
    except Exception:
        return set()
    return out


def load_assets(stock_db_path: str | Path, include_disabled: bool = True) -> list[dict]:
    with connect_access(stock_db_path) as conn:
        cur = conn.cursor()
        cols = table_columns(cur, "asset_rollup_data")
        required = {"asset_rollup", "ib_symbol", "ib_currency"}
        missing = required - cols
        if missing:
            raise RuntimeError(f"asset_rollup_data mist kolommen: {sorted(missing)}")
        wanted = ["asset_rollup", "ib_symbol", "ib_currency"]
        for col in ("optie_scanner_incl", "ib_asset_type", "exchange"):
            if col in cols:
                wanted.append(col)
        rows = cur.execute(f"SELECT {', '.join('[' + c + ']' for c in wanted)} FROM asset_rollup_data").fetchall()
        idx = {name: pos for pos, name in enumerate(wanted)}

    assets: list[dict] = []
    for row in rows:
        enabled = truthy(row[idx["optie_scanner_incl"]]) if "optie_scanner_incl" in idx else True
        if not enabled and not include_disabled:
            continue
        asset = _clean(row[idx["asset_rollup"]]).upper()
        if not asset:
            continue
        assets.append(
            {
                "asset_rollup": asset,
                "ib_symbol": _clean(row[idx["ib_symbol"]]).upper() or asset,
                "ib_currency": _clean(row[idx["ib_currency"]]).upper(),
                "ib_asset_type": _clean(row[idx["ib_asset_type"]]).upper() if "ib_asset_type" in idx else "STK",
                "exchange": _clean(row[idx["exchange"]]).upper() if "exchange" in idx else "",
                "enabled": enabled,
            }
        )
    return sorted(assets, key=lambda item: item["asset_rollup"])


def load_latest_spot(stock_db_path: str | Path, asset_rollup: str) -> tuple[float | None, str]:
    with connect_access(stock_db_path) as conn:
        cur = conn.cursor()
        cols = table_columns(cur, "historical_data_correct")
        if not cols:
            return None, "historical_data_correct niet gevonden"
        asset_col = "asset_rollup" if "asset_rollup" in cols else None
        date_col = "datum" if "datum" in cols else ("date" if "date" in cols else None)
        close_col = "close" if "close" in cols else ("slot" if "slot" in cols else None)
        if not asset_col or not date_col or not close_col:
            return None, "historical_data_correct mist asset/date/close kolommen"
        row = cur.execute(
            f"""
            SELECT TOP 1 [{date_col}], [{close_col}]
            FROM historical_data_correct
            WHERE [{asset_col}] = ? AND [{close_col}] IS NOT NULL
            ORDER BY [{date_col}] DESC
            """,
            (asset_rollup,),
        ).fetchone()
        if not row:
            return None, f"geen spot gevonden voor {asset_rollup}"
        try:
            return float(row[1]), f"{row[0]}"
        except Exception:
            return None, f"ongeldige close voor {asset_rollup}: {row[1]}"


def _clean(value: object) -> str:
    return str(value or "").strip()
