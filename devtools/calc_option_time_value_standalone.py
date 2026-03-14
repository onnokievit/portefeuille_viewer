from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pyodbc


DEFAULT_ONNO_DB = r"C:\Users\onno\OneDrive\Beleggen\2025 - portefeuille database 02.03 - ONNO.accdb"
DEFAULT_STOCK_DB = r"C:\Users\onno\OneDrive\Beleggen\2025 - portefeuille database 02.03 - STOCKDATA.accdb"


def connect_access(db_path: str) -> pyodbc.Connection:
    return pyodbc.connect(rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path}")


def load_open_option_positions(onno_conn: pyodbc.Connection) -> pd.DataFrame:
    max_datum = onno_conn.cursor().execute("SELECT MAX(datum) FROM per_dag_open_opties_opgerold_v2").fetchone()[0]
    if max_datum is None:
        return pd.DataFrame()
    sql = """
        SELECT
            datum,
            broker,
            asset_rollup,
            optie_exp_date,
            optie_strike,
            optie_call_put,
            Sum(transactie_aantal) AS qty_open
        FROM per_dag_open_opties_opgerold_v2
        WHERE datum=?
          AND transactie_aantal<>0
          AND optie_exp_date>=Date()
        GROUP BY datum, broker, asset_rollup, optie_exp_date, optie_strike, optie_call_put
        HAVING Sum(transactie_aantal)<>0
    """
    df = pd.read_sql(sql, onno_conn, params=[max_datum])
    if df.empty:
        return df
    df["broker"] = df["broker"].astype(str).str.strip().str.lower()
    df["asset_rollup"] = df["asset_rollup"].astype(str).str.strip()
    df["optie_call_put"] = df["optie_call_put"].astype(str).str.strip().str.lower()
    df["optie_strike"] = pd.to_numeric(df["optie_strike"], errors="coerce")
    df["optie_exp_date"] = pd.to_datetime(df["optie_exp_date"], errors="coerce").dt.date
    df["qty_open"] = pd.to_numeric(df["qty_open"], errors="coerce")
    return df


def load_universe_map(stock_conn: pyodbc.Connection, user_name: str) -> pd.DataFrame:
    sql = """
        SELECT
            broker,
            series_id,
            asset_rollup,
            expiry,
            strike,
            optie_call_put,
            ib_currency
        FROM option_subscription_universe_onno
        WHERE user_name=?
    """
    df = pd.read_sql(sql, stock_conn, params=[user_name])
    if df.empty:
        return df
    df["broker"] = df["broker"].astype(str).str.strip().str.lower()
    df["asset_rollup"] = df["asset_rollup"].astype(str).str.strip()
    df["optie_call_put"] = df["optie_call_put"].astype(str).str.strip().str.lower()
    df["strike"] = pd.to_numeric(df["strike"], errors="coerce")
    df["expiry"] = pd.to_datetime(df["expiry"], errors="coerce").dt.date
    return df


def load_latest_option_snapshot(stock_conn: pyodbc.Connection) -> pd.DataFrame:
    sql = """
        SELECT s.*
        FROM option_live_snapshot AS s
        INNER JOIN (
            SELECT series_id, MAX(snapshot_ts) AS max_ts
            FROM option_live_snapshot
            GROUP BY series_id
        ) AS x
          ON s.series_id=x.series_id AND s.snapshot_ts=x.max_ts
    """
    df = pd.read_sql(sql, stock_conn)
    if df.empty:
        return df
    num_cols = ["last", "delayed_last", "close", "delayed_close", "bid", "ask", "delayed_bid", "delayed_ask"]
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    # Prefer true trade last, then delayed last, then close variants, then mid.
    def pick_price(r: pd.Series) -> float | None:
        for c in ["last", "delayed_last", "close", "delayed_close"]:
            v = r.get(c)
            if pd.notna(v) and float(v) > 0:
                return float(v)
        b = r.get("bid")
        a = r.get("ask")
        if pd.notna(b) and pd.notna(a) and float(b) > 0 and float(a) > 0:
            return (float(b) + float(a)) / 2.0
        return None

    df["option_price"] = df.apply(pick_price, axis=1)
    keep = ["series_id", "snapshot_ts", "option_price"]
    return df[keep].copy()


def load_latest_underlying_close(stock_conn: pyodbc.Connection) -> pd.DataFrame:
    sql = """
        SELECT h.asset_rollup, h.datum, h.[close] AS underlying_close
        FROM historical_data_correct AS h
        INNER JOIN (
            SELECT asset_rollup, MAX(datum) AS max_datum
            FROM historical_data_correct
            GROUP BY asset_rollup
        ) AS x
          ON h.asset_rollup=x.asset_rollup AND h.datum=x.max_datum
    """
    df = pd.read_sql(sql, stock_conn)
    if df.empty:
        return df
    df["asset_rollup"] = df["asset_rollup"].astype(str).str.strip()
    df["underlying_close"] = pd.to_numeric(df["underlying_close"], errors="coerce")
    return df


def intrinsic_value(cp: str, strike: float, underlying_close: float) -> float:
    if cp == "call":
        return max(0.0, underlying_close - strike)
    return max(0.0, strike - underlying_close)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Standalone option time-value calculator from ONNO positions + STOCK snapshots.")
    p.add_argument("--onno-db", default=DEFAULT_ONNO_DB)
    p.add_argument("--stock-db", default=DEFAULT_STOCK_DB)
    p.add_argument("--user", default="onno")
    p.add_argument("--fx-usd-eur", type=float, default=0.0, help="Optional USD->EUR factor (e.g. 0.92). 0 disables EUR conversion.")
    p.add_argument("--save-csv", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    onno_conn = connect_access(args.onno_db)
    stock_conn = connect_access(args.stock_db)
    try:
        pos = load_open_option_positions(onno_conn)
        uni = load_universe_map(stock_conn, args.user)
        snap = load_latest_option_snapshot(stock_conn)
        und = load_latest_underlying_close(stock_conn)
    finally:
        onno_conn.close()
        stock_conn.close()

    if pos.empty:
        print("Geen open optieposities gevonden.")
        return 1
    if uni.empty:
        print("Geen option universe rows gevonden.")
        return 1
    if snap.empty:
        print("Geen option snapshots gevonden. Run eerst subscribe_live_options_from_universe.py")
        return 1

    merged = pos.merge(
        uni,
        left_on=["broker", "asset_rollup", "optie_exp_date", "optie_strike", "optie_call_put"],
        right_on=["broker", "asset_rollup", "expiry", "strike", "optie_call_put"],
        how="left",
        validate="1:1",
    )
    missing_series = int(merged["series_id"].isna().sum())
    merged = merged.merge(snap, on="series_id", how="left")
    merged = merged.merge(und[["asset_rollup", "underlying_close"]], on="asset_rollup", how="left")

    merged["intrinsic_per_unit"] = merged.apply(
        lambda r: intrinsic_value(
            str(r.get("optie_call_put", "")).lower(),
            float(r.get("optie_strike")) if pd.notna(r.get("optie_strike")) else 0.0,
            float(r.get("underlying_close")) if pd.notna(r.get("underlying_close")) else 0.0,
        )
        if pd.notna(r.get("underlying_close")) and pd.notna(r.get("optie_strike"))
        else None,
        axis=1,
    )
    merged["time_value_per_unit"] = (merged["option_price"] - merged["intrinsic_per_unit"]).clip(lower=0)
    merged["time_value_signed_ccy"] = merged["time_value_per_unit"] * merged["qty_open"]
    merged["time_value_abs_ccy"] = merged["time_value_per_unit"] * merged["qty_open"].abs()

    calc = merged[
        merged["series_id"].notna()
        & merged["option_price"].notna()
        & merged["underlying_close"].notna()
        & merged["time_value_per_unit"].notna()
    ].copy()

    by_ccy = calc.groupby("ib_currency", dropna=False).agg(
        rows=("series_id", "count"),
        time_value_signed=("time_value_signed_ccy", "sum"),
        time_value_abs=("time_value_abs_ccy", "sum"),
    )

    print("=== Option Time Value Summary ===")
    print(f"positions_rows={len(pos)}")
    print(f"series_match_missing={missing_series}")
    print(f"rows_with_prices={int(merged['option_price'].notna().sum())}")
    print(f"rows_with_underlying_close={int(merged['underlying_close'].notna().sum())}")
    print(f"rows_calculated={len(calc)}")
    print("\nPer currency:")
    print(by_ccy.to_string(float_format=lambda x: f"{x:,.2f}"))

    if args.fx_usd_eur > 0:
        usd_signed = float(by_ccy.loc["USD", "time_value_signed"]) if "USD" in by_ccy.index else 0.0
        usd_abs = float(by_ccy.loc["USD", "time_value_abs"]) if "USD" in by_ccy.index else 0.0
        eur_signed = float(by_ccy.loc["EUR", "time_value_signed"]) if "EUR" in by_ccy.index else 0.0
        eur_abs = float(by_ccy.loc["EUR", "time_value_abs"]) if "EUR" in by_ccy.index else 0.0
        eur_total_signed = eur_signed + usd_signed * float(args.fx_usd_eur)
        eur_total_abs = eur_abs + usd_abs * float(args.fx_usd_eur)
        print("\nEUR-estimate:")
        print(f"fx_usd_eur={args.fx_usd_eur}")
        print(f"time_value_signed_eur_est={eur_total_signed:,.2f}")
        print(f"time_value_abs_eur_est={eur_total_abs:,.2f}")

    if args.save_csv:
        out = Path(__file__).resolve().parent / "option_time_value_detail.csv"
        cols = [
            "broker",
            "asset_rollup",
            "optie_exp_date",
            "optie_strike",
            "optie_call_put",
            "qty_open",
            "ib_currency",
            "option_price",
            "underlying_close",
            "intrinsic_per_unit",
            "time_value_per_unit",
            "time_value_signed_ccy",
            "time_value_abs_ccy",
            "series_id",
            "snapshot_ts",
        ]
        to_save = merged[cols].sort_values(["asset_rollup", "optie_exp_date", "optie_call_put", "optie_strike"]).copy()
        round_cols = [
            "optie_strike",
            "qty_open",
            "option_price",
            "underlying_close",
            "intrinsic_per_unit",
            "time_value_per_unit",
            "time_value_signed_ccy",
            "time_value_abs_ccy",
        ]
        for c in round_cols:
            if c in to_save.columns:
                to_save[c] = pd.to_numeric(to_save[c], errors="coerce").round(2)
        try:
            to_save.to_csv(
                out,
                index=False,
                sep=";",
                decimal=",",
                encoding="utf-8-sig",
            )
            print(f"\nSaved detail CSV: {out}")
        except PermissionError:
            alt = Path(__file__).resolve().parent / "option_time_value_detail_nl.csv"
            to_save.to_csv(
                alt,
                index=False,
                sep=";",
                decimal=",",
                encoding="utf-8-sig",
            )
            print(f"\nSaved detail CSV (fallback, original locked): {alt}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
