from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyodbc


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from portefeuille_viewer.config import get_stockdata_db_path
from portefeuille_viewer.data.repository import get_stockdata_connection


DEFAULT_ONNO_DB = r"C:\Users\onno\OneDrive\Beleggen\2025 - portefeuille database 02.03 - ONNO.accdb"


def connect_access(db_path: str) -> pyodbc.Connection:
    if db_path == get_stockdata_db_path():
        return get_stockdata_connection()
    return pyodbc.connect(rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path}")


def _clean(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _to_date(v: Any) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    txt = _clean(v)
    if not txt:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(txt, fmt).date()
        except ValueError:
            continue
    return None


def _friday_number(expiry: Any) -> int | None:
    d = _to_date(expiry)
    if d is None:
        return None
    return int((d.day - 1) // 7 + 1)


def load_latest_open_options_v2(conn: pyodbc.Connection) -> pd.DataFrame:
    q_max = "SELECT MAX(datum) AS max_datum FROM per_dag_open_opties_opgerold_v2"
    max_row = conn.cursor().execute(q_max).fetchone()
    if not max_row or max_row[0] is None:
        return pd.DataFrame()
    max_datum = max_row[0]

    sql = """
        SELECT
            datum,
            broker,
            asset_rollup,
            optie_exp_date,
            optie_strike,
            optie_call_put,
            transactie_aantal,
            winst_verlies
        FROM per_dag_open_opties_opgerold_v2
        WHERE datum = ?
          AND transactie_aantal <> 0
    """
    df = pd.read_sql(sql, conn, params=[max_datum])
    if not df.empty:
        df["optie_exp_date"] = pd.to_datetime(df["optie_exp_date"], errors="coerce").dt.date
        today = date.today()
        df = df[df["optie_exp_date"].notna() & (df["optie_exp_date"] >= today)].copy()
    return df


def load_asset_rollup_data(conn: pyodbc.Connection) -> pd.DataFrame:
    sql = """
        SELECT asset_rollup, ib_symbol, ib_currency
        FROM asset_rollup_data
    """
    return pd.read_sql(sql, conn)


def load_optie_referentie_data(conn: pyodbc.Connection) -> pd.DataFrame:
    sql = """
        SELECT asset_rollup, opt_week, opt_exchange, opt_tradingclass
        FROM optie_referentie_data
    """
    return pd.read_sql(sql, conn)


def load_transactie_euro_sums(conn: pyodbc.Connection) -> pd.DataFrame:
    # Access _3 semantics for SomVantransactie_euro_totaal come from transaction aggregation.
    sql = """
        SELECT
            broker,
            asset_rollup,
            optie_exp_date,
            optie_strike,
            optie_call_put,
            Sum(transactie_euro_totaal) AS SomVantransactie_euro_totaal_tx
        FROM transacties_bron_data
        WHERE asset_type='optie'
          AND optie_exp_date >= Date()
        GROUP BY broker, asset_rollup, optie_exp_date, optie_strike, optie_call_put
        HAVING Sum(transactie_aantal) <> 0
    """
    return pd.read_sql(sql, conn)


def build_universe(
    df_v2: pd.DataFrame,
    df_asset: pd.DataFrame,
    df_ref: pd.DataFrame,
    df_tx_sum: pd.DataFrame,
) -> pd.DataFrame:
    if df_v2.empty:
        return pd.DataFrame()

    # Normalize basics
    df = df_v2.copy()
    df["asset_rollup"] = df["asset_rollup"].map(_clean)
    df["broker"] = df["broker"].map(_clean)
    df["asset_type"] = "optie"
    df["optie_call_put"] = df["optie_call_put"].map(lambda x: _clean(x).lower())
    df["VrijdagNummer"] = df["optie_exp_date"].map(_friday_number)

    # Aggregate to same level as old _3 output (broker + series)
    grp_cols = ["broker", "asset_rollup", "asset_type", "optie_exp_date", "optie_strike", "optie_call_put"]
    agg_df = (
        df.groupby(grp_cols, dropna=False, as_index=False)
        .agg(
            SomVantransactie_aantal=("transactie_aantal", "sum"),
            VrijdagNummer=("VrijdagNummer", "max"),
        )
    )

    # Use tx-based euro totals to match Access _3 semantics.
    tx = df_tx_sum.copy()
    tx["broker"] = tx["broker"].map(_clean)
    tx["asset_rollup"] = tx["asset_rollup"].map(_clean)
    tx["optie_call_put"] = tx["optie_call_put"].map(lambda x: _clean(x).lower())
    tx["optie_strike"] = pd.to_numeric(tx["optie_strike"], errors="coerce")
    tx["optie_exp_date"] = pd.to_datetime(tx["optie_exp_date"], errors="coerce").dt.date
    agg_df = agg_df.merge(
        tx[
            [
                "broker",
                "asset_rollup",
                "optie_exp_date",
                "optie_strike",
                "optie_call_put",
                "SomVantransactie_euro_totaal_tx",
            ]
        ],
        on=["broker", "asset_rollup", "optie_exp_date", "optie_strike", "optie_call_put"],
        how="left",
    )
    agg_df["SomVantransactie_euro_totaal"] = agg_df["SomVantransactie_euro_totaal_tx"]
    agg_df = agg_df.drop(columns=["SomVantransactie_euro_totaal_tx"])

    # Join asset map (equivalent old _1)
    asset_map = df_asset.copy()
    asset_map["asset_rollup"] = asset_map["asset_rollup"].map(_clean)
    asset_map["ib_symbol"] = asset_map["ib_symbol"].map(_clean)
    asset_map["ib_currency"] = asset_map["ib_currency"].map(_clean)
    out = agg_df.merge(asset_map, on="asset_rollup", how="inner")

    # Build MaxWeek per asset from referentie
    ref = df_ref.copy()
    ref["asset_rollup"] = ref["asset_rollup"].map(_clean)
    ref["opt_week"] = pd.to_numeric(ref["opt_week"], errors="coerce")
    max_week = ref.groupby("asset_rollup", as_index=False)["opt_week"].max().rename(columns={"opt_week": "MaxWeek"})
    out = out.merge(max_week, on="asset_rollup", how="left")
    out["MaxWeek"] = pd.to_numeric(out["MaxWeek"], errors="coerce")

    # WeeknummerVoorJoin exactly as Access:
    # IIf(MaxWeek>1, VrijdagNummer, MaxWeek)
    out["WeeknummerVoorJoin"] = out.apply(
        lambda r: (r["VrijdagNummer"] if pd.notna(r["MaxWeek"]) and float(r["MaxWeek"]) > 1 else r["MaxWeek"]),
        axis=1,
    )
    out["WeeknummerVoorJoin"] = pd.to_numeric(out["WeeknummerVoorJoin"], errors="coerce")

    # Final join with referentie (equivalent _3)
    ref_small = ref[["asset_rollup", "opt_week", "opt_exchange", "opt_tradingclass"]].copy()
    final_df = out.merge(
        ref_small,
        left_on=["asset_rollup", "WeeknummerVoorJoin"],
        right_on=["asset_rollup", "opt_week"],
        how="inner",
    )

    cols = [
        "broker",
        "asset_rollup",
        "asset_type",
        "optie_exp_date",
        "optie_strike",
        "optie_call_put",
        "SomVantransactie_aantal",
        "SomVantransactie_euro_totaal",
        "ib_symbol",
        "ib_currency",
        "VrijdagNummer",
        "MaxWeek",
        "WeeknummerVoorJoin",
        "opt_exchange",
        "opt_tradingclass",
        "opt_week",
    ]
    final_df = final_df[cols].copy()
    final_df = final_df.sort_values(["asset_rollup", "optie_exp_date", "optie_call_put", "optie_strike"]).reset_index(drop=True)
    return final_df


def save_to_access_table(conn: pyodbc.Connection, table_name: str, df: pd.DataFrame) -> None:
    cur = conn.cursor()
    try:
        cur.execute(f"DROP TABLE {table_name}")
        conn.commit()
    except Exception:
        pass

    cur.execute(
        f"""
        CREATE TABLE {table_name} (
            broker TEXT(32),
            asset_rollup TEXT(64),
            asset_type TEXT(16),
            optie_exp_date DATETIME,
            optie_strike DOUBLE,
            optie_call_put TEXT(8),
            SomVantransactie_aantal DOUBLE,
            SomVantransactie_euro_totaal DOUBLE,
            ib_symbol TEXT(32),
            ib_currency TEXT(16),
            VrijdagNummer INTEGER,
            MaxWeek DOUBLE,
            WeeknummerVoorJoin DOUBLE,
            opt_exchange TEXT(32),
            opt_tradingclass TEXT(32),
            opt_week DOUBLE
        )
        """
    )
    conn.commit()

    ins_sql = f"""
        INSERT INTO {table_name} (
            broker, asset_rollup, asset_type, optie_exp_date, optie_strike, optie_call_put,
            SomVantransactie_aantal, SomVantransactie_euro_totaal, ib_symbol, ib_currency,
            VrijdagNummer, MaxWeek, WeeknummerVoorJoin, opt_exchange, opt_tradingclass, opt_week
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    rows = []
    for _, r in df.iterrows():
        rows.append(
            (
                r["broker"],
                r["asset_rollup"],
                r["asset_type"],
                r["optie_exp_date"],
                float(r["optie_strike"]) if pd.notna(r["optie_strike"]) else None,
                r["optie_call_put"],
                float(r["SomVantransactie_aantal"]) if pd.notna(r["SomVantransactie_aantal"]) else None,
                float(r["SomVantransactie_euro_totaal"]) if pd.notna(r["SomVantransactie_euro_totaal"]) else None,
                r["ib_symbol"],
                r["ib_currency"],
                int(r["VrijdagNummer"]) if pd.notna(r["VrijdagNummer"]) else None,
                float(r["MaxWeek"]) if pd.notna(r["MaxWeek"]) else None,
                float(r["WeeknummerVoorJoin"]) if pd.notna(r["WeeknummerVoorJoin"]) else None,
                r["opt_exchange"],
                r["opt_tradingclass"],
                float(r["opt_week"]) if pd.notna(r["opt_week"]) else None,
            )
        )
    if rows:
        cur.executemany(ins_sql, rows)
        conn.commit()


def compare_with_access_q3(conn: pyodbc.Connection, py_df: pd.DataFrame) -> tuple[int, int]:
    q3_df = pd.read_sql("SELECT * FROM Opties_open_live_prices_python_3", conn)
    return len(py_df), len(q3_df)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build Python equivalent of Opties_open_live_prices_python_3 from v2 state.")
    p.add_argument("--db", default=DEFAULT_ONNO_DB, help="ONNO DB path")
    p.add_argument("--output-csv", default="", help="Output CSV path")
    p.add_argument("--output-table", default="Opties_open_live_prices_python_3_py", help="Output Access table name")
    p.add_argument("--no-table", action="store_true", help="Do not write output table")
    p.add_argument("--compare-q3", action="store_true", help="Compare rowcount with existing Access _3 query")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    conn = connect_access(args.db)
    try:
        df_v2 = load_latest_open_options_v2(conn)
        df_asset = load_asset_rollup_data(conn)
        df_ref = load_optie_referentie_data(conn)
        df_tx_sum = load_transactie_euro_sums(conn)
        out = build_universe(df_v2, df_asset, df_ref, df_tx_sum)

        out_csv = Path(args.output_csv) if args.output_csv else Path(__file__).resolve().parent / "options_live_universe_py.csv"
        out.to_csv(out_csv, index=False)

        if not args.no_table:
            save_to_access_table(conn, args.output_table, out)

        print("=== build_options_live_universe_py summary ===")
        print(f"input_v2_rows={len(df_v2)}")
        print(f"output_rows={len(out)}")
        print(f"output_csv={out_csv}")
        if not args.no_table:
            print(f"output_table={args.output_table}")
        if args.compare_q3:
            py_n, q3_n = compare_with_access_q3(conn, out)
            print(f"compare_rowcount_py={py_n} access_q3={q3_n}")
        if len(out) > 0:
            print("\npreview:")
            print(out.head(10).to_string(index=False))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
