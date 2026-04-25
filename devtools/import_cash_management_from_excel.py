from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import pyodbc


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from portefeuille_viewer.config import get_databases  # noqa: E402
from portefeuille_viewer.data.cash_management_repository import ensure_cash_management_schema  # noqa: E402


BROKER_COLUMNS = ("degiro", "interactive", "lynx")
DEFAULT_CURRENCY_CODE = "EUR"
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Importeer stortingen.xlsx naar cash_management_entries in de ONNO user-db."
    )
    parser.add_argument(
        "--excel",
        help="Pad naar Excel-bestand. Default: stortingen.xlsx in dezelfde map als de ONNO database.",
    )
    parser.add_argument(
        "--sheet",
        default=0,
        help="Worksheet naam of index. Default: eerste sheet.",
    )
    parser.add_argument(
        "--currency",
        default=DEFAULT_CURRENCY_CODE,
        help="Valuta code voor de geïmporteerde regels. Default: EUR.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Schrijf daadwerkelijk weg naar Access. Zonder deze vlag alleen preview.",
    )
    parser.add_argument(
        "--replace-range",
        action="store_true",
        help="Verwijder eerst bestaande records voor dezelfde brokers en datumrange uit de import.",
    )
    return parser.parse_args()


def load_excel_frame(excel_path: Path, sheet: str | int) -> pd.DataFrame:
    df = pd.read_excel(excel_path, sheet_name=sheet)
    df.columns = [str(col).strip().lower() for col in df.columns]
    required = {"datum", *BROKER_COLUMNS}
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Excel mist verplichte kolommen: {missing}")
    return df


def normalize_date(value) -> dt.date | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    parsed = pd.to_datetime(value, dayfirst=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def normalize_amount(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().replace(".", "").replace(",", ".")
        if not text:
            return None
        try:
            return float(text)
        except Exception:
            return None
    if pd.isna(value):
        return None
    try:
        return float(value)
    except Exception:
        return None


def build_records(df: pd.DataFrame, currency_code: str) -> list[dict]:
    rows: list[dict] = []
    for _, row in df.iterrows():
        row_date = normalize_date(row.get("datum"))
        if row_date is None:
            continue
        for broker in BROKER_COLUMNS:
            amount = normalize_amount(row.get(broker))
            if amount is None or abs(amount) < 1e-12:
                continue
            rows.append(
                {
                    "datum": row_date,
                    "broker": broker,
                    "account_name": broker,
                    "entry_type": "deposit" if amount > 0 else "withdrawal",
                    "amount": amount,
                    "currency_code": currency_code,
                    "fx_rate": None,
                    "transfer_group": None,
                    "comment_text": f"Imported from {Path(df.attrs.get('source_file', 'stortingen.xlsx')).name}",
                }
            )
    rows.sort(key=lambda item: (item["datum"], item["broker"], item["amount"]))
    return rows


def load_existing_keys(conn: pyodbc.Connection) -> set[tuple]:
    cur = conn.cursor()
    keys: set[tuple] = set()
    try:
        rows = cur.execute(
            """
            SELECT datum, broker, account_name, entry_type, amount, currency_code
            FROM cash_management_entries
            """
        ).fetchall()
    except Exception:
        return keys
    for row in rows:
        row_date = row[0].date() if hasattr(row[0], "date") else row[0]
        keys.add(
            (
                row_date,
                str(row[1] or "").strip().lower(),
                str(row[2] or "").strip().lower(),
                str(row[3] or "").strip().lower(),
                round(float(row[4] or 0.0), 8),
                str(row[5] or "").strip().upper(),
            )
        )
    return keys


def record_key(record: dict) -> tuple:
    return (
        record["datum"],
        str(record["broker"]).strip().lower(),
        str(record["account_name"]).strip().lower(),
        str(record["entry_type"]).strip().lower(),
        round(float(record["amount"]), 8),
        str(record["currency_code"]).strip().upper(),
    )


def replace_existing_range(conn: pyodbc.Connection, records: list[dict]) -> int:
    if not records:
        return 0
    min_date = min(record["datum"] for record in records)
    max_date = max(record["datum"] for record in records)
    brokers = sorted({str(record["broker"]).strip().lower() for record in records})
    placeholders = ", ".join("?" for _ in brokers)
    sql = (
        "DELETE FROM cash_management_entries "
        f"WHERE LCase(broker) IN ({placeholders}) AND datum >= ? AND datum <= ?"
    )
    params = [*brokers, min_date, max_date]
    cur = conn.cursor()
    cur.execute(sql, params)
    deleted = cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0
    conn.commit()
    return int(deleted)


def insert_records(conn: pyodbc.Connection, records: list[dict]) -> int:
    now = dt.datetime.now()
    cur = conn.cursor()
    inserted = 0
    for record in records:
        cur.execute(
            """
            INSERT INTO cash_management_entries
            (
                datum,
                broker,
                account_name,
                entry_type,
                amount,
                currency_code,
                fx_rate,
                transfer_group,
                comment_text,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["datum"],
                record["broker"],
                record["account_name"],
                record["entry_type"],
                record["amount"],
                record["currency_code"],
                record["fx_rate"],
                record["transfer_group"],
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
    db_path = resolve_onno_db_path()
    excel_path = Path(args.excel) if args.excel else db_path.parent / "stortingen.xlsx"
    sheet = int(args.sheet) if str(args.sheet).isdigit() else str(args.sheet)

    log(f"ONNO db: {db_path}")
    log(f"Excel bron: {excel_path}")
    if not excel_path.exists():
        log("FOUT: Excel-bestand niet gevonden.")
        return 1

    ensure_cash_management_schema()
    df = load_excel_frame(excel_path, sheet)
    df.attrs["source_file"] = str(excel_path)
    records = build_records(df, str(args.currency).strip().upper() or DEFAULT_CURRENCY_CODE)

    if not records:
        log("Geen importeerbare records gevonden.")
        return 0

    deposits = sum(1 for r in records if r["entry_type"] == "deposit")
    withdrawals = sum(1 for r in records if r["entry_type"] == "withdrawal")
    total_amount = sum(float(r["amount"]) for r in records)
    min_date = min(record["datum"] for record in records)
    max_date = max(record["datum"] for record in records)

    log(
        f"Preview: records={len(records)} deposits={deposits} withdrawals={withdrawals} "
        f"date_range={min_date}..{max_date} totaal={total_amount:.2f}"
    )
    for preview in records[:12]:
        print(
            f"  {preview['datum']} | {preview['broker']:<11} | "
            f"{preview['entry_type']:<10} | {preview['amount']:>12.2f} | {preview['currency_code']}"
        )
    if len(records) > 12:
        print(f"  ... {len(records) - 12} extra records")

    if not args.apply:
        log("Geen writes uitgevoerd. Gebruik --apply om weg te schrijven.")
        return 0

    with get_connection(db_path) as conn:
        deleted = 0
        if args.replace_range:
            deleted = replace_existing_range(conn, records)
            log(f"Bestaande records verwijderd in import-range: {deleted}")

        existing = load_existing_keys(conn)
        new_records = [record for record in records if record_key(record) not in existing]
        skipped = len(records) - len(new_records)
        inserted = insert_records(conn, new_records) if new_records else 0

    log(f"KLAAR: inserted={inserted} skipped_existing={skipped} deleted_range={deleted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
