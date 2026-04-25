from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import pyodbc


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from portefeuille_viewer.config import get_databases  # noqa: E402
from portefeuille_viewer.data.account_daily_balance_repository import (  # noqa: E402
    ensure_account_daily_balances_schema,
)
from portefeuille_viewer.data.cash_management_repository import ensure_cash_management_schema  # noqa: E402


BROKER = "degiro"
DEFAULT_START_DATE = dt.date(2021, 1, 11)
DEFAULT_END_DATE = dt.date(2021, 5, 21)
DEFAULT_CURRENCY_CODE = "EUR"
DEFAULT_SOURCE_NAME = "backfill"
ONNO_DB_KEYS = ("onno-productie", "onno")


def log(message: str) -> None:
    stamp = dt.datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] {message}", flush=True)


def resolve_onno_db_path() -> Path:
    databases = get_databases()
    for key in ONNO_DB_KEYS:
        if key in databases:
            return Path(databases[key]["path"])
    for name, cfg in databases.items():
        if "onno" in str(name).lower():
            return Path(cfg["path"])
    raise RuntimeError("Kon ONNO database-pad niet vinden in settings_shared.ini")


def get_connection(db_path: Path) -> pyodbc.Connection:
    conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path};"
    return pyodbc.connect(conn_str)


def parse_date(value: str) -> dt.date:
    return dt.datetime.strptime(value, "%Y-%m-%d").date()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Vul account_daily_balances voor degiro aan met cumulatieve cashflows "
            "op weekdagen in de historische startperiode."
        )
    )
    parser.add_argument("--start", default=DEFAULT_START_DATE.isoformat(), help="Startdatum YYYY-MM-DD.")
    parser.add_argument("--end", default=DEFAULT_END_DATE.isoformat(), help="Einddatum YYYY-MM-DD.")
    parser.add_argument("--currency", default=DEFAULT_CURRENCY_CODE, help="Valuta code. Default: EUR.")
    parser.add_argument("--source", default=DEFAULT_SOURCE_NAME, help="Source naam. Default: backfill.")
    parser.add_argument(
        "--weekdays-only",
        action="store_true",
        help=(
            "Vul strikt alleen weekdagen. Default vult weekdagen plus weekenddagen "
            "waarop degiro cashflows staan."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Schrijf daadwerkelijk weg naar Access. Zonder deze vlag alleen preview.",
    )
    return parser.parse_args()


def iter_weekdays(start_date: dt.date, end_date: dt.date):
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            yield current
        current += dt.timedelta(days=1)


def build_target_dates(
    start_date: dt.date,
    end_date: dt.date,
    cashflows: list[tuple[dt.date, float]],
    weekdays_only: bool,
) -> list[dt.date]:
    dates = set(iter_weekdays(start_date, end_date))
    if not weekdays_only:
        dates.update(day for day, _amount in cashflows if start_date <= day <= end_date)
    return sorted(dates)


def load_cashflows_until(conn: pyodbc.Connection, end_date: dt.date) -> list[tuple[dt.date, float]]:
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT datum, amount
        FROM cash_management_entries
        WHERE LCase(broker)=?
          AND entry_type IN ('deposit', 'withdrawal')
          AND datum <= ?
        ORDER BY datum ASC, id ASC
        """,
        (BROKER, end_date),
    ).fetchall()
    out: list[tuple[dt.date, float]] = []
    for row in rows:
        row_date = row[0].date() if hasattr(row[0], "date") else row[0]
        if row_date is None:
            continue
        out.append((row_date, float(row[1] or 0.0)))
    return out


def load_existing_balance_dates(conn: pyodbc.Connection, start_date: dt.date, end_date: dt.date) -> set[dt.date]:
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT datum
        FROM account_daily_balances
        WHERE LCase(broker)=?
          AND datum >= ?
          AND datum <= ?
        """,
        (BROKER, start_date, end_date),
    ).fetchall()
    out: set[dt.date] = set()
    for row in rows:
        row_date = row[0].date() if hasattr(row[0], "date") else row[0]
        if row_date is not None:
            out.add(row_date)
    return out


def build_records(
    cashflows: list[tuple[dt.date, float]],
    existing_dates: set[dt.date],
    start_date: dt.date,
    end_date: dt.date,
    currency_code: str,
    source_name: str,
    weekdays_only: bool,
) -> list[dict]:
    records: list[dict] = []
    cumulative = 0.0
    cash_idx = 0
    cashflows = sorted(cashflows, key=lambda item: item[0])

    for day in build_target_dates(start_date, end_date, cashflows, weekdays_only):
        while cash_idx < len(cashflows) and cashflows[cash_idx][0] <= day:
            cumulative += cashflows[cash_idx][1]
            cash_idx += 1
        if day in existing_dates:
            continue
        records.append(
            {
                "datum": day,
                "broker": BROKER,
                "account_name": BROKER,
                "ending_balance": cumulative,
                "currency_code": currency_code,
                "source_name": source_name,
                "comment_text": "Backfilled from cumulative degiro cashflows",
            }
        )
    return records


def insert_records(conn: pyodbc.Connection, records: list[dict]) -> int:
    now = dt.datetime.now()
    cur = conn.cursor()
    inserted = 0
    for record in records:
        cur.execute(
            """
            INSERT INTO account_daily_balances
            (
                datum,
                broker,
                account_name,
                ending_balance,
                currency_code,
                source_name,
                comment_text,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["datum"],
                record["broker"],
                record["account_name"],
                record["ending_balance"],
                record["currency_code"],
                record["source_name"],
                record["comment_text"],
                now,
                now,
            ),
        )
        inserted += 1
    conn.commit()
    return inserted


def main() -> int:
    args = parse_args()
    start_date = parse_date(args.start)
    end_date = parse_date(args.end)
    if end_date < start_date:
        raise ValueError("Einddatum ligt voor startdatum")

    currency_code = str(args.currency).strip().upper() or DEFAULT_CURRENCY_CODE
    source_name = str(args.source).strip().lower() or DEFAULT_SOURCE_NAME
    db_path = resolve_onno_db_path()

    log(f"ONNO db: {db_path}")
    log(f"Broker: {BROKER}")
    mode = "alleen weekdagen" if args.weekdays_only else "weekdagen plus cashflow-weekenddagen"
    log(f"Periode: {start_date}..{end_date} {mode}")

    ensure_cash_management_schema()
    ensure_account_daily_balances_schema()

    with get_connection(db_path) as conn:
        cashflows = load_cashflows_until(conn, end_date)
        existing_dates = load_existing_balance_dates(conn, start_date, end_date)
        records = build_records(
            cashflows,
            existing_dates,
            start_date,
            end_date,
            currency_code,
            source_name,
            bool(args.weekdays_only),
        )

        target_dates = build_target_dates(start_date, end_date, cashflows, bool(args.weekdays_only))
        log(
            f"Preview: target_dagen={len(target_dates)} cashflow_records_t_m_einddatum={len(cashflows)} "
            f"bestaande_balance_dagen={len(existing_dates)} toe_te_voegen={len(records)}"
        )
        for preview in records[:12]:
            print(
                f"  {preview['datum']} | {preview['broker']:<6} | "
                f"{preview['ending_balance']:>12.2f} | {preview['currency_code']} | {preview['source_name']}"
            )
        if len(records) > 12:
            print(f"  ... {len(records) - 12} extra records")
        if records:
            log(
                f"Eerste record={records[0]['datum']} waarde={records[0]['ending_balance']:.2f}; "
                f"laatste record={records[-1]['datum']} waarde={records[-1]['ending_balance']:.2f}"
            )

        if not args.apply:
            log("Geen writes uitgevoerd. Gebruik --apply om weg te schrijven.")
            return 0

        inserted = insert_records(conn, records) if records else 0
        log(f"KLAAR: inserted={inserted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
