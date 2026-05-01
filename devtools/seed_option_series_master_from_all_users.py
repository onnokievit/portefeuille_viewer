from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyodbc

# Reuse the proven _3-equivalent Python builder logic.
from build_options_live_universe_py import (
    build_universe,
    connect_access,
    load_asset_rollup_data,
    load_latest_open_options_v2,
    load_optie_referentie_data,
    load_transactie_euro_sums,
)


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from portefeuille_viewer.config import get_stockdata_db_path


DEFAULT_STOCK_DB = get_stockdata_db_path()
USER_DB_MAP = {
    "onno": r"C:\Users\onno\OneDrive\Beleggen\2025 - portefeuille database 02.03 - ONNO.accdb",
    "muriel": r"C:\Users\onno\OneDrive\Beleggen\2025 - portefeuille database 02.03 - MURIEL.accdb",
    "quinten": r"C:\Users\onno\OneDrive\Beleggen\2025 - portefeuille database 02.03 - QUINTEN.accdb",
}


@dataclass
class SeedStats:
    user: str
    loaded: int = 0
    inserted: int = 0
    updated: int = 0
    skipped_invalid: int = 0


def _clean(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _to_float(v: Any) -> float | None:
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


def _to_ts() -> datetime:
    return datetime.now()


def _load_universe_from_user_db(user_db_path: str) -> pd.DataFrame:
    conn = connect_access(user_db_path)
    try:
        df_v2 = load_latest_open_options_v2(conn)
        df_asset = load_asset_rollup_data(conn)
        df_ref = load_optie_referentie_data(conn)
        df_tx_sum = load_transactie_euro_sums(conn)
        out = build_universe(df_v2, df_asset, df_ref, df_tx_sum)
        return out
    finally:
        conn.close()


def _upsert_master(stock_conn: pyodbc.Connection, user: str, df: pd.DataFrame, dry_run: bool) -> SeedStats:
    stats = SeedStats(user=user, loaded=len(df))
    if df.empty:
        return stats

    now = _to_ts()
    cur = stock_conn.cursor()
    for _, r in df.iterrows():
        asset_rollup = _clean(r.get("asset_rollup"))
        cp = _clean(r.get("optie_call_put")).lower()
        strike = _to_float(r.get("optie_strike"))
        expiry = r.get("optie_exp_date")
        ib_currency = _clean(r.get("ib_currency")).upper()
        underlying_symbol = _clean(r.get("ib_symbol")).upper()
        exchange_code = _clean(r.get("opt_exchange")).upper()
        trading_class = _clean(r.get("opt_tradingclass")).upper()

        if not (asset_rollup and cp and strike is not None and pd.notna(expiry) and ib_currency):
            stats.skipped_invalid += 1
            continue

        existing = cur.execute(
            """
            SELECT TOP 1 series_id
            FROM option_series_master
            WHERE asset_rollup=?
              AND optie_call_put=?
              AND strike=?
              AND expiry=?
              AND ib_currency=?
            """,
            (asset_rollup, cp, strike, expiry, ib_currency),
        ).fetchone()

        if existing is None:
            stats.inserted += 1
            if not dry_run:
                cur.execute(
                    """
                    INSERT INTO option_series_master (
                        asset_rollup,
                        underlying_symbol,
                        strike,
                        expiry,
                        exchange_code,
                        trading_class,
                        ib_currency,
                        optie_call_put,
                        source_tag,
                        active,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        asset_rollup,
                        underlying_symbol or None,
                        strike,
                        expiry,
                        exchange_code or None,
                        trading_class or None,
                        ib_currency,
                        cp,
                        "position",
                        True,
                        now,
                        now,
                    ),
                )
        else:
            stats.updated += 1
            if not dry_run:
                cur.execute(
                    """
                    UPDATE option_series_master
                    SET underlying_symbol=?,
                        exchange_code=?,
                        trading_class=?,
                        source_tag='position',
                        active=True,
                        updated_at=?
                    WHERE series_id=?
                    """,
                    (
                        underlying_symbol or None,
                        exchange_code or None,
                        trading_class or None,
                        now,
                        int(existing[0]),
                    ),
                )

    if not dry_run:
        stock_conn.commit()
    return stats


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Seed STOCKDATA.option_series_master from user DB option universes.")
    p.add_argument("--users", default="onno,muriel,quinten", help="Comma-separated users to process")
    p.add_argument("--stock-db", default=DEFAULT_STOCK_DB, help="Path to STOCKDATA DB")
    p.add_argument("--dry-run", action="store_true", help="Do not write to master table")
    p.add_argument("--save-csv", action="store_true", help="Save per-user universe CSV in devtools")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    users = [u.strip().lower() for u in args.users.split(",") if u.strip()]
    selected = [u for u in users if u in USER_DB_MAP]
    unknown = [u for u in users if u not in USER_DB_MAP]
    if unknown:
        print(f"Unknown users ignored: {unknown}")
    if not selected:
        print("No valid users selected.")
        return 1

    stock_conn = connect_access(args.stock_db)
    all_stats: list[SeedStats] = []
    try:
        for user in selected:
            user_db = USER_DB_MAP[user]
            df = _load_universe_from_user_db(user_db)
            if args.save_csv:
                out_csv = Path(__file__).resolve().parent / f"options_live_universe_{user}.csv"
                df.to_csv(out_csv, index=False)
                print(f"[{user}] csv={out_csv} rows={len(df)}")
            stats = _upsert_master(stock_conn, user, df, dry_run=args.dry_run)
            all_stats.append(stats)
            print(
                f"[{user}] loaded={stats.loaded} inserted={stats.inserted} updated={stats.updated} skipped_invalid={stats.skipped_invalid}"
            )

        cur = stock_conn.cursor()
        total_master = cur.execute("SELECT COUNT(*) FROM option_series_master").fetchone()[0]
        active_master = cur.execute("SELECT COUNT(*) FROM option_series_master WHERE active=True").fetchone()[0]
        print("\n=== seed_option_series_master_from_all_users summary ===")
        print(f"users_processed={selected}")
        print(f"dry_run={args.dry_run}")
        print(f"master_rows_total={total_master}")
        print(f"master_rows_active={active_master}")
        print(f"sum_loaded={sum(s.loaded for s in all_stats)}")
        print(f"sum_inserted={sum(s.inserted for s in all_stats)}")
        print(f"sum_updated={sum(s.updated for s in all_stats)}")
        print(f"sum_skipped_invalid={sum(s.skipped_invalid for s in all_stats)}")
    finally:
        stock_conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
