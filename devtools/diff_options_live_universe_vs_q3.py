from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd
import pyodbc


DEFAULT_ONNO_DB = r"C:\Users\onno\OneDrive\Beleggen\2025 - portefeuille database 02.03 - ONNO.accdb"


def connect_access(db_path: str) -> pyodbc.Connection:
    return pyodbc.connect(rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path}")


def _clean(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _norm_cp(v: Any) -> str:
    return _clean(v).lower()


def _norm_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        s = _clean(v).replace(",", ".")
        try:
            return float(s)
        except Exception:
            return None


def load_table(conn: pyodbc.Connection, name: str) -> pd.DataFrame:
    return pd.read_sql(f"SELECT * FROM {name}", conn)


def prep(df: pd.DataFrame, src_name: str) -> pd.DataFrame:
    out = df.copy()
    out["broker"] = out["broker"].map(_clean)
    out["asset_rollup"] = out["asset_rollup"].map(_clean)
    out["optie_call_put"] = out["optie_call_put"].map(_norm_cp)
    out["optie_strike"] = out["optie_strike"].map(_norm_float)
    out["SomVantransactie_aantal"] = out["SomVantransactie_aantal"].map(_norm_float)
    out["SomVantransactie_euro_totaal"] = out["SomVantransactie_euro_totaal"].map(_norm_float)
    if "optie_exp_date" in out.columns:
        out["optie_exp_date"] = pd.to_datetime(out["optie_exp_date"], errors="coerce").dt.date
    out["src"] = src_name
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Diff Access _3 vs Python-built options live universe")
    p.add_argument("--db", default=DEFAULT_ONNO_DB)
    p.add_argument("--left", default="Opties_open_live_prices_python_3")
    p.add_argument("--right", default="Opties_open_live_prices_python_3_py")
    p.add_argument("--out-dir", default=str(Path(__file__).resolve().parent))
    return p.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = connect_access(args.db)
    try:
        left_raw = load_table(conn, args.left)
        right_raw = load_table(conn, args.right)
    finally:
        conn.close()

    left = prep(left_raw, "access_q3")
    right = prep(right_raw, "python")

    key_cols = ["broker", "asset_rollup", "optie_exp_date", "optie_strike", "optie_call_put"]
    cmp_cols = [
        "SomVantransactie_aantal",
        "SomVantransactie_euro_totaal",
        "ib_symbol",
        "ib_currency",
        "opt_exchange",
        "opt_tradingclass",
        "opt_week",
        "WeeknummerVoorJoin",
    ]

    left_keys = left[key_cols].drop_duplicates()
    right_keys = right[key_cols].drop_duplicates()

    left_only = left_keys.merge(right_keys, on=key_cols, how="left", indicator=True)
    left_only = left_only[left_only["_merge"] == "left_only"].drop(columns=["_merge"])

    right_only = right_keys.merge(left_keys, on=key_cols, how="left", indicator=True)
    right_only = right_only[right_only["_merge"] == "left_only"].drop(columns=["_merge"])

    both_keys = left_keys.merge(right_keys, on=key_cols, how="inner")
    left_both = left.merge(both_keys, on=key_cols, how="inner")
    right_both = right.merge(both_keys, on=key_cols, how="inner")

    merged = left_both.merge(
        right_both,
        on=key_cols,
        how="inner",
        suffixes=("_access", "_python"),
    )

    diff_rows = []
    for _, r in merged.iterrows():
        diffs = []
        for c in cmp_cols:
            la = r.get(f"{c}_access")
            rb = r.get(f"{c}_python")
            if pd.isna(la) and pd.isna(rb):
                continue
            if isinstance(la, float) or isinstance(rb, float):
                la_f = _norm_float(la)
                rb_f = _norm_float(rb)
                if la_f is None and rb_f is None:
                    continue
                if la_f is None or rb_f is None or abs(la_f - rb_f) > 1e-9:
                    diffs.append(c)
            else:
                if _clean(la) != _clean(rb):
                    diffs.append(c)
        if diffs:
            row = {k: r[k] for k in key_cols}
            row["diff_cols"] = ",".join(diffs)
            for c in cmp_cols:
                row[f"{c}_access"] = r.get(f"{c}_access")
                row[f"{c}_python"] = r.get(f"{c}_python")
            diff_rows.append(row)

    diff_df = pd.DataFrame(diff_rows)

    left_only_path = out_dir / "options_live_diff_left_only.csv"
    right_only_path = out_dir / "options_live_diff_right_only.csv"
    value_diff_path = out_dir / "options_live_diff_value_mismatch.csv"

    left_only.to_csv(left_only_path, index=False)
    right_only.to_csv(right_only_path, index=False)
    diff_df.to_csv(value_diff_path, index=False)

    print("=== options universe diff summary ===")
    print(f"left_table={args.left} rows={len(left)} unique_keys={len(left_keys)}")
    print(f"right_table={args.right} rows={len(right)} unique_keys={len(right_keys)}")
    print(f"left_only_keys={len(left_only)} -> {left_only_path}")
    print(f"right_only_keys={len(right_only)} -> {right_only_path}")
    print(f"value_mismatch_keys={len(diff_df)} -> {value_diff_path}")

    if len(left_only) > 0:
        print("\nleft_only sample:")
        print(left_only.head(10).to_string(index=False))
    if len(right_only) > 0:
        print("\nright_only sample:")
        print(right_only.head(10).to_string(index=False))
    if len(diff_df) > 0:
        print("\nvalue_mismatch sample:")
        show_cols = key_cols + ["diff_cols"]
        print(diff_df[show_cols].head(10).to_string(index=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

