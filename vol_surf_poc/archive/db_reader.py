"""Read-only access to asset_rollup_data and optie_referentie_data from the stock DB."""
import pyodbc


def _connect(stock_db_path: str) -> pyodbc.Connection:
    conn_str = (
        r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        rf"DBQ={stock_db_path};"
    )
    return pyodbc.connect(conn_str)


def load_assets(stock_db_path: str) -> list[dict]:
    """Return all rows from asset_rollup_data, ordered by asset_rollup."""
    conn = _connect(stock_db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT asset_rollup, ib_symbol, ib_currency, exchange, prim_exchange, [type]
            FROM asset_rollup_data
            ORDER BY asset_rollup
        """)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def load_optie_referentie(stock_db_path: str, asset_rollup: str) -> dict | None:
    """Return the default (week=0) option reference row for an asset, or None."""
    conn = _connect(stock_db_path)
    try:
        cur = conn.cursor()
        # Prefer week=0 (generic fallback); fall back to any row for this asset
        cur.execute("""
            SELECT opt_exchange, opt_tradingclass, opt_multiplier, opt_week
            FROM optie_referentie_data
            WHERE asset_rollup = ?
            ORDER BY opt_week
        """, (asset_rollup,))
        rows = cur.fetchall()
        if not rows:
            return None
        # Prefer week == 0, else take first
        chosen = next((r for r in rows if r[3] == 0), rows[0])
        return {
            "opt_exchange":    str(chosen[0] or "SMART").strip(),
            "opt_tradingclass": str(chosen[1] or "").strip(),
            "opt_multiplier":  float(chosen[2]) if chosen[2] else 100.0,
        }
    finally:
        conn.close()
