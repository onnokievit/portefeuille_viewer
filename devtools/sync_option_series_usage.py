from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pandas as pd
import pyodbc

from seed_option_series_master_from_all_users import (
    USER_DB_MAP,
    _load_universe_from_user_db,
    connect_access,
)


DEFAULT_STOCK_DB = r"C:\Users\onno\OneDrive\Beleggen\2025 - portefeuille database 02.03 - STOCKDATA.accdb"


@dataclass
class SyncStats:
    user: str
    loaded: int = 0
    resolved: int = 0
    upserted: int = 0
    unresolved: int = 0
    deactivated: int = 0


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


def ensure_usage_table(stock_conn: pyodbc.Connection) -> None:
    cur = stock_conn.cursor()
    try:
        cur.execute("SELECT TOP 1 usage_id FROM option_series_usage")
        return
    except Exception:
        pass

    cur.execute(
        """
        CREATE TABLE option_series_usage (
            usage_id COUNTER PRIMARY KEY,
            user_name TEXT(32) NOT NULL,
            broker TEXT(32) NOT NULL,
            series_id LONG NOT NULL,
            qty_open DOUBLE,
            position_eur DOUBLE,
            source_tag TEXT(16),
            active YESNO,
            last_seen_date DATETIME,
            created_at DATETIME,
            updated_at DATETIME
        )
        """
    )
    stock_conn.commit()
    try:
        cur.execute(
            """
            CREATE UNIQUE INDEX ux_option_series_usage
            ON option_series_usage (user_name, broker, series_id)
            """
        )
        stock_conn.commit()
    except Exception:
        # Index may already exist if partially created previously.
        pass


def _resolve_series_id(stock_cur: pyodbc.Cursor, row: pd.Series) -> int | None:
    asset_rollup = _clean(row.get("asset_rollup"))
    cp = _clean(row.get("optie_call_put")).lower()
    strike = _to_float(row.get("optie_strike"))
    expiry = row.get("optie_exp_date")
    ib_currency = _clean(row.get("ib_currency")).upper()
    if not (asset_rollup and cp and strike is not None and pd.notna(expiry) and ib_currency):
        return None

    found = stock_cur.execute(
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
    if found is None:
        return None
    return int(found[0])


def sync_user_usage(
    stock_conn: pyodbc.Connection,
    user: str,
    universe_df: pd.DataFrame,
    dry_run: bool,
) -> SyncStats:
    stats = SyncStats(user=user, loaded=len(universe_df))
    if universe_df.empty:
        return stats

    run_ts = datetime.now()
    run_day = date.today()
    cur = stock_conn.cursor()

    # Robust sync semantics:
    # 1) Mark all existing position-usage rows for this user inactive.
    # 2) Re-activate only rows present in current universe through upsert.
    if not dry_run:
        cur.execute(
            """
            UPDATE option_series_usage
            SET active=False, updated_at=?
            WHERE user_name=?
              AND source_tag='position'
              AND active=True
            """,
            (run_ts, user),
        )
        stats.deactivated = int(cur.rowcount if cur.rowcount != -1 else 0)
        stock_conn.commit()

    for _, r in universe_df.iterrows():
        series_id = _resolve_series_id(cur, r)
        if series_id is None:
            stats.unresolved += 1
            continue
        stats.resolved += 1

        broker = _clean(r.get("broker")).lower()
        qty_open = _to_float(r.get("SomVantransactie_aantal"))
        position_eur = _to_float(r.get("SomVantransactie_euro_totaal"))

        existing = cur.execute(
            """
            SELECT TOP 1 usage_id
            FROM option_series_usage
            WHERE user_name=? AND broker=? AND series_id=?
            """,
            (user, broker, series_id),
        ).fetchone()

        if existing is None:
            stats.upserted += 1
            if not dry_run:
                cur.execute(
                    """
                    INSERT INTO option_series_usage (
                        user_name, broker, series_id, qty_open, position_eur,
                        source_tag, active, last_seen_date, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, 'position', True, ?, ?, ?)
                    """,
                    (user, broker, series_id, qty_open, position_eur, run_day, run_ts, run_ts),
                )
        else:
            stats.upserted += 1
            if not dry_run:
                cur.execute(
                    """
                    UPDATE option_series_usage
                    SET qty_open=?,
                        position_eur=?,
                        source_tag='position',
                        active=True,
                        last_seen_date=?,
                        updated_at=?
                    WHERE usage_id=?
                    """,
                    (qty_open, position_eur, run_day, run_ts, int(existing[0])),
                )

    if not dry_run:
        stock_conn.commit()

    return stats


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Sync per-user option series usage into STOCKDATA.option_series_usage.")
    p.add_argument("--users", default="onno,muriel,quinten", help="Comma-separated users to sync")
    p.add_argument("--stock-db", default=DEFAULT_STOCK_DB, help="Path to STOCKDATA DB")
    p.add_argument("--dry-run", action="store_true", help="Do not write to DB")
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
    try:
        ensure_usage_table(stock_conn)
        all_stats: list[SyncStats] = []
        for user in selected:
            df = _load_universe_from_user_db(USER_DB_MAP[user])
            stats = sync_user_usage(stock_conn, user=user, universe_df=df, dry_run=args.dry_run)
            all_stats.append(stats)
            print(
                f"[{user}] loaded={stats.loaded} resolved={stats.resolved} "
                f"upserted={stats.upserted} unresolved={stats.unresolved} deactivated={stats.deactivated}"
            )

        cur = stock_conn.cursor()
        total_usage = cur.execute("SELECT COUNT(*) FROM option_series_usage").fetchone()[0]
        active_usage = cur.execute("SELECT COUNT(*) FROM option_series_usage WHERE active=True").fetchone()[0]

        print("\n=== sync_option_series_usage summary ===")
        print(f"users_processed={selected}")
        print(f"dry_run={args.dry_run}")
        print(f"usage_rows_total={total_usage}")
        print(f"usage_rows_active={active_usage}")
        print(f"sum_loaded={sum(s.loaded for s in all_stats)}")
        print(f"sum_resolved={sum(s.resolved for s in all_stats)}")
        print(f"sum_upserted={sum(s.upserted for s in all_stats)}")
        print(f"sum_unresolved={sum(s.unresolved for s in all_stats)}")
        print(f"sum_deactivated={sum(s.deactivated for s in all_stats)}")
    finally:
        stock_conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
