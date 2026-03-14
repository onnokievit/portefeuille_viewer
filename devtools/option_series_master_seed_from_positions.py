from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, date
from typing import Any

import pyodbc


DEFAULT_ONNO_DB = r"C:\Users\onno\OneDrive\Beleggen\2025 - portefeuille database 02.03 - ONNO.accdb"
DEFAULT_STOCK_DB = r"C:\Users\onno\OneDrive\Beleggen\2025 - portefeuille database 02.03 - STOCKDATA.accdb"


def connect_access(db_path: str) -> pyodbc.Connection:
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


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        txt = _clean(v).replace(",", ".")
        try:
            return float(txt)
        except Exception:
            return None


@dataclass
class SeedStats:
    loaded: int = 0
    inserted: int = 0
    updated: int = 0
    skipped_invalid: int = 0


def fetch_open_option_series(onno_conn: pyodbc.Connection) -> list[dict]:
    sql = """
        SELECT
            asset_rollup,
            ib_symbol,
            ib_currency,
            optie_call_put,
            optie_strike,
            optie_exp_date,
            opt_exchange,
            opt_tradingclass
        FROM Opties_open_live_prices_python_3
        WHERE asset_rollup IS NOT NULL
          AND ib_currency IS NOT NULL
          AND optie_call_put IS NOT NULL
          AND optie_strike IS NOT NULL
          AND optie_exp_date IS NOT NULL
    """
    cur = onno_conn.cursor()
    rows = cur.execute(sql).fetchall()
    cols = [c[0] for c in cur.description]
    out = [dict(zip(cols, r)) for r in rows]
    return out


def seed_into_master(stock_conn: pyodbc.Connection, raw_rows: list[dict], dry_run: bool = False) -> SeedStats:
    stats = SeedStats()
    stats.loaded = len(raw_rows)
    cur = stock_conn.cursor()
    now = datetime.now()

    for r in raw_rows:
        asset_rollup = _clean(r.get("asset_rollup"))
        underlying_symbol = _clean(r.get("ib_symbol"))
        ib_currency = _clean(r.get("ib_currency")).upper()
        optie_call_put = _clean(r.get("optie_call_put")).lower()
        strike = _to_float(r.get("optie_strike"))
        expiry = _to_date(r.get("optie_exp_date"))
        exchange_code = _clean(r.get("opt_exchange")).upper()
        trading_class = _clean(r.get("opt_tradingclass")).upper()

        if not (asset_rollup and ib_currency and optie_call_put and strike is not None and expiry is not None):
            stats.skipped_invalid += 1
            continue

        # find existing by unique pre-resolve key
        existing = cur.execute(
            """
            SELECT TOP 1 series_id, underlying_symbol, exchange_code, trading_class, source_tag, active
            FROM option_series_master
            WHERE asset_rollup=?
              AND optie_call_put=?
              AND strike=?
              AND expiry=?
              AND ib_currency=?
            """,
            (asset_rollup, optie_call_put, strike, expiry, ib_currency),
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
                        optie_call_put,
                        "position",
                        True,
                        now,
                        now,
                    ),
                )
            continue

        # update minimal fields for existing rows
        stats.updated += 1
        if not dry_run:
            cur.execute(
                """
                UPDATE option_series_master
                SET underlying_symbol=?,
                    exchange_code=?,
                    trading_class=?,
                    source_tag=?,
                    active=?,
                    updated_at=?
                WHERE series_id=?
                """,
                (
                    underlying_symbol or None,
                    exchange_code or None,
                    trading_class or None,
                    "position",
                    True,
                    now,
                    int(existing[0]),
                ),
            )

    if not dry_run:
        stock_conn.commit()
    return stats


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Seed option_series_master from ONNO open options view.")
    p.add_argument("--onno-db", default=DEFAULT_ONNO_DB, help="Path to ONNO DB")
    p.add_argument("--stock-db", default=DEFAULT_STOCK_DB, help="Path to STOCKDATA DB")
    p.add_argument("--dry-run", action="store_true", help="Do not write to DB")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    onno_conn = connect_access(args.onno_db)
    stock_conn = connect_access(args.stock_db)
    try:
        raw = fetch_open_option_series(onno_conn)
        stats = seed_into_master(stock_conn, raw, dry_run=args.dry_run)
        print("=== option_series_master seed summary ===")
        print(f"loaded={stats.loaded}")
        print(f"inserted={stats.inserted}")
        print(f"updated={stats.updated}")
        print(f"skipped_invalid={stats.skipped_invalid}")
        print(f"dry_run={args.dry_run}")
    finally:
        onno_conn.close()
        stock_conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

