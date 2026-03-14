from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import pyodbc


DEFAULT_STOCK_DB = r"C:\Users\onno\OneDrive\Beleggen\2025 - portefeuille database 02.03 - STOCKDATA.accdb"


def connect_access(db_path: str) -> pyodbc.Connection:
    return pyodbc.connect(rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path}")


def load_universe(conn: pyodbc.Connection, user_name: str) -> pd.DataFrame:
    sql = """
        SELECT
            u.user_name,
            u.broker,
            u.series_id,
            u.qty_open,
            u.position_eur,
            m.asset_rollup,
            m.underlying_symbol,
            m.optie_call_put,
            m.strike,
            m.expiry,
            m.ib_currency,
            m.exchange_code,
            m.trading_class,
            m.multiplier,
            m.conid,
            m.local_symbol,
            m.last_verified_ts
        FROM option_series_usage AS u
        INNER JOIN option_series_master AS m
            ON u.series_id = m.series_id
        WHERE u.user_name=?
          AND u.active=True
          AND m.active=True
        ORDER BY m.asset_rollup, m.expiry, m.optie_call_put, m.strike, u.broker
    """
    return pd.read_sql(sql, conn, params=[user_name])


def write_table(conn: pyodbc.Connection, table_name: str, df: pd.DataFrame) -> None:
    cur = conn.cursor()
    try:
        cur.execute(f"DROP TABLE {table_name}")
        conn.commit()
    except Exception:
        pass

    cur.execute(
        f"""
        CREATE TABLE {table_name} (
            user_name TEXT(32),
            broker TEXT(32),
            series_id LONG,
            qty_open DOUBLE,
            position_eur DOUBLE,
            asset_rollup TEXT(64),
            underlying_symbol TEXT(32),
            optie_call_put TEXT(8),
            strike DOUBLE,
            expiry DATETIME,
            ib_currency TEXT(16),
            exchange_code TEXT(32),
            trading_class TEXT(32),
            multiplier DOUBLE,
            conid LONG,
            local_symbol TEXT(64),
            last_verified_ts DATETIME
        )
        """
    )
    conn.commit()

    ins = f"""
        INSERT INTO {table_name} (
            user_name, broker, series_id, qty_open, position_eur,
            asset_rollup, underlying_symbol, optie_call_put, strike, expiry,
            ib_currency, exchange_code, trading_class, multiplier, conid, local_symbol, last_verified_ts
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    rows = []
    for _, r in df.iterrows():
        expiry = r.get("expiry")
        if pd.isna(expiry):
            expiry = None
        last_verified_ts = r.get("last_verified_ts")
        if pd.isna(last_verified_ts):
            last_verified_ts = None
        rows.append(
            (
                r.get("user_name"),
                r.get("broker"),
                int(r.get("series_id")) if pd.notna(r.get("series_id")) else None,
                float(r.get("qty_open")) if pd.notna(r.get("qty_open")) else None,
                float(r.get("position_eur")) if pd.notna(r.get("position_eur")) else None,
                r.get("asset_rollup"),
                r.get("underlying_symbol"),
                r.get("optie_call_put"),
                float(r.get("strike")) if pd.notna(r.get("strike")) else None,
                expiry,
                r.get("ib_currency"),
                r.get("exchange_code"),
                r.get("trading_class"),
                float(r.get("multiplier")) if pd.notna(r.get("multiplier")) else None,
                int(r.get("conid")) if pd.notna(r.get("conid")) else None,
                r.get("local_symbol"),
                last_verified_ts,
            )
        )
    if rows:
        cur.executemany(ins, rows)
        conn.commit()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export active option subscription universe for one user.")
    p.add_argument("--user", default="onno")
    p.add_argument("--stock-db", default=DEFAULT_STOCK_DB)
    p.add_argument("--table", default="option_subscription_universe_onno")
    p.add_argument("--csv", default="")
    p.add_argument("--no-table", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    conn = connect_access(args.stock_db)
    try:
        df = load_universe(conn, args.user)
        out_csv = Path(args.csv) if args.csv else Path(__file__).resolve().parent / f"option_subscription_universe_{args.user}.csv"
        df.to_csv(out_csv, index=False)
        if not args.no_table:
            write_table(conn, args.table, df)

        resolved = int((df["conid"].fillna(0) > 0).sum()) if not df.empty else 0
        unresolved = int(len(df) - resolved)
        print("=== export_option_subscription_universe summary ===")
        print(f"user={args.user}")
        print(f"rows={len(df)}")
        print(f"resolved_conid={resolved}")
        print(f"unresolved_conid={unresolved}")
        print(f"csv={out_csv}")
        if not args.no_table:
            print(f"table={args.table}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
