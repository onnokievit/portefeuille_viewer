# services/test_orders_repository.py (of onderaan repository.py)
import datetime as dt
import pandas as pd
import polars as pl
from portefeuille_viewer.data.repository import get_connection
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE


TEST_ORDER_COLS = [
    "broker",
    "asset_rollup",
    "asset_type",          # bv. "equity"/"option"
    "transactie_type",     # "buy"/"sell" of "koop"/"verkoop"
    "transactie_aantal",   # let op spelling conform tabel!
    "transactie_prijs",
    "optie_call_put",
    "optie_strike",
    "optie_exp_date",
    "create_date",
    "include"
]

def _empty_orders_df() -> pl.DataFrame:
    return pl.DataFrame({c: [] for c in ["Id"] + TEST_ORDER_COLS})


def get_test_orders(asset_rollup: str | None = None) -> pl.DataFrame:
    where = " WHERE asset_rollup = ?" if asset_rollup else ""
    params = [asset_rollup] if asset_rollup else None
    sql = (
        "SELECT Id, broker, asset_rollup, asset_type, transactie_type, "
        "transactie_aantal, transactie_prijs, optie_call_put, "
        "optie_strike, optie_exp_date, create_date , include "
        "FROM transacties_test_orders" + where +
        " ORDER BY create_date DESC, Id DESC"
    )
    with get_connection() as conn:
        pdf = pd.read_sql(sql, conn, params=params)
    df = pl.from_pandas(pdf)
    # zorg voor consistente date/str weergave (UI verwacht strings)
    if "optie_exp_date" in df.columns:
        try:
            df = df.with_columns(
                pl.col("optie_exp_date")
                .cast(pl.Date)
                .dt.strftime("%d-%m-%Y")
                .fill_null("")
                .alias("optie_exp_date")
            )
        except Exception:
            df = df.with_columns(pl.col("optie_exp_date").cast(pl.Utf8).fill_null("").alias("optie_exp_date"))
    if "create_date" in df.columns:
        try:
            df = df.with_columns(
                pl.col("create_date")
                .cast(pl.Datetime)
                .dt.strftime("%d-%m-%Y %H:%M:%S")
                .fill_null("")
                .alias("create_date")
            )
        except Exception:
            df = df.with_columns(pl.col("create_date").cast(pl.Utf8).fill_null("").alias("create_date"))
    return df

def load_test_orders_cache_from_db():
    """Laad alle test orders in de snapshot cache (per asset_rollup)."""
    df_all = get_test_orders(asset_rollup=None)
    cache = {}
    if df_all.height > 0:
        unique_assets = df_all["asset_rollup"].unique().to_list()
        for asset in unique_assets:
            cache[asset] = df_all.filter(pl.col("asset_rollup") == asset)
    SNAPSHOT_STORE.repository_snapshot_test_orders_cache = cache
    SNAPSHOT_STORE.repository_dirty_test_orders_assets = set()

def get_cached_orders(asset_rollup: str) -> pl.DataFrame:
    cache = getattr(SNAPSHOT_STORE, "repository_snapshot_test_orders_cache", {}) or {}
    df = cache.get(asset_rollup)
    return df if df is not None else _empty_orders_df()

def set_cached_orders_for_asset(asset_rollup: str, df: pl.DataFrame):
    cache = getattr(SNAPSHOT_STORE, "repository_snapshot_test_orders_cache", {}) or {}
    cache[asset_rollup] = df
    SNAPSHOT_STORE.repository_snapshot_test_orders_cache = cache
    dirty = getattr(SNAPSHOT_STORE, "repository_dirty_test_orders_assets", set()) or set()
    dirty.add(asset_rollup)
    SNAPSHOT_STORE.repository_dirty_test_orders_assets = dirty

def flush_dirty_test_orders_to_db():
    """Schrijf alle dirty assets in cache terug naar DB: delete + bulk insert."""
    dirty = getattr(SNAPSHOT_STORE, "repository_dirty_test_orders_assets", set()) or set()
    if not dirty:
        return
    cache = getattr(SNAPSHOT_STORE, "repository_snapshot_test_orders_cache", {}) or {}
    with get_connection() as conn:
        cur = conn.cursor()
        for asset in list(dirty):
            df = cache.get(asset)
            if df is None or df.is_empty():
                # niets te schrijven, maar wel oude records verwijderen
                cur.execute("DELETE FROM transacties_test_orders WHERE asset_rollup = ?", (asset,))
                continue
            # delete oude rijen voor dit asset
            cur.execute("DELETE FROM transacties_test_orders WHERE asset_rollup = ?", (asset,))
            # insert alle rijen uit df
            cols = [c for c in TEST_ORDER_COLS]  # Id wordt autonummering
            placeholders = ", ".join(["?"] * len(cols))
            sql = f"INSERT INTO transacties_test_orders ({', '.join(cols)}) VALUES ({placeholders})"
            for row in df.iter_rows(named=True):
                norm_row = _normalize_order_row(row)
                values = [norm_row.get(c) for c in cols]
                cur.execute(sql, values)
        conn.commit()
    SNAPSHOT_STORE.repository_dirty_test_orders_assets = set()


def _normalize_order_row(row: dict) -> dict:
    data = dict(row)
    # lege strings naar None
    data = {k: (None if v == "" else v) for k, v in data.items()}

    def num(val):
        if val is None:
            return None
        try:
            return float(val)
        except Exception:
            return None

    def dt_val(val):
        if val is None:
            return None
        if isinstance(val, dt.datetime):
            return val
        if isinstance(val, dt.date):
            return dt.datetime.combine(val, dt.time.min)
        s = str(val).strip()
        # probeer dd-mm-yy of dd-mm-yyyy
        for fmt in ("%d-%m-%y", "%d-%m-%Y", "%d/%m/%y", "%d/%m/%Y"):
            try:
                return dt.datetime.strptime(s, fmt)
            except Exception:
                continue
        # laatste poging: ISO
        try:
            return dt.datetime.fromisoformat(s)
        except Exception:
            return None




    data["transactie_aantal"] = num(data.get("transactie_aantal"))
    data["transactie_prijs"] = num(data.get("transactie_prijs"))
    data["optie_strike"] = num(data.get("optie_strike"))
    data["optie_exp_date"] = dt_val(data.get("optie_exp_date"))
    data["create_date"] = dt_val(data.get("create_date")) or dt.datetime.now()
    inc = data.get("include", 1)
    try:
        data["include"] = int(inc)
    except Exception:
        data["include"] = 1
    return data



def insert_test_order(row: dict) -> int:
    data = _normalize_order_row(row)
    data.setdefault("create_date", dt.datetime.now())
    cols = [c for c in TEST_ORDER_COLS if c in data]
    placeholders = ", ".join(["?"] * len(cols))
    sql = f"INSERT INTO transacties_test_orders ({', '.join(cols)}) VALUES ({placeholders})"
    values = [data.get(c) for c in cols]
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, values)
        cur.execute("SELECT @@IDENTITY")
        new_id = cur.fetchone()[0]
        conn.commit()
    return int(new_id)

def update_test_order(order_id: int, row: dict) -> None:
    data = _normalize_order_row(row)
    data = {k: v for k, v in data.items() if k in TEST_ORDER_COLS}
    if not data:
        return
    set_clause = ", ".join([f"{k}=?" for k in data.keys()])
    sql = f"UPDATE transacties_test_orders SET {set_clause} WHERE Id=?"
    params = list(data.values()) + [order_id]
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()

def delete_test_order(order_id: int) -> None:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM transacties_test_orders WHERE Id=?", (order_id,))
        conn.commit()
