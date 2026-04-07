from __future__ import annotations

from typing import Iterable

import pyodbc

from portefeuille_viewer.services.historical_price_update_runner import STOCKDATA_DB_PATH


DEFAULT_PRICE_DECIMALS = 2


def _connect_stockdb():
    conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={STOCKDATA_DB_PATH};"
    return pyodbc.connect(conn_str)


def load_price_decimals_map(
    asset_rollups: Iterable[str] | None = None,
    default: int = DEFAULT_PRICE_DECIMALS,
) -> dict[str, int]:
    assets = [str(a).strip() for a in (asset_rollups or []) if str(a).strip()]
    result: dict[str, int] = {asset: int(default) for asset in assets}

    try:
        with _connect_stockdb() as conn:
            cur = conn.cursor()
            try:
                cur.execute("SELECT TOP 1 asset_rollup, price_decimals FROM single_asset_stepsize_settings")
            except Exception:
                return result

            if assets:
                placeholders = ",".join("?" for _ in assets)
                query = (
                    "SELECT asset_rollup, price_decimals "
                    "FROM single_asset_stepsize_settings "
                    f"WHERE asset_rollup IN ({placeholders})"
                )
                rows = cur.execute(query, assets).fetchall()
            else:
                rows = cur.execute(
                    "SELECT asset_rollup, price_decimals FROM single_asset_stepsize_settings"
                ).fetchall()
    except Exception:
        return result

    for row in rows:
        asset = str(row[0] or "").strip()
        if not asset:
            continue
        try:
            decimals = int(row[1])
        except Exception:
            decimals = int(default)
        result[asset] = max(0, min(6, decimals))

    return result
