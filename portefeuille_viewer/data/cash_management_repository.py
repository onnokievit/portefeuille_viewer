import pyodbc

from datetime import datetime
from time import sleep

from portefeuille_viewer.data import repository as data_repository
from portefeuille_viewer.data.repository import get_connection


CASH_MANAGEMENT_TABLE = "cash_management_entries"
_SCHEMA_READY_PATHS: set[str] = set()


def _table_exists(cur: pyodbc.Cursor, table_name: str) -> bool:
    try:
        return bool(list(cur.tables(table=table_name)))
    except Exception:
        return False


def _index_exists(cur: pyodbc.Cursor, table_name: str, index_name: str) -> bool:
    try:
        for row in cur.statistics(table=table_name):
            if str(getattr(row, "index_name", "") or "").lower() == index_name.lower():
                return True
    except Exception:
        return False
    return False


def _get_connection_with_retry(retries: int = 4, delay_s: float = 0.25):
    last_exc = None
    for attempt in range(max(1, retries)):
        try:
            return get_connection()
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                sleep(delay_s)
    raise last_exc


def ensure_cash_management_schema() -> None:
    db_key = str(data_repository.db_path or "")
    if db_key and db_key in _SCHEMA_READY_PATHS:
        return
    with _get_connection_with_retry() as conn:
        cur = conn.cursor()
        if not _table_exists(cur, CASH_MANAGEMENT_TABLE):
            cur.execute(
                f"""
                CREATE TABLE {CASH_MANAGEMENT_TABLE} (
                    id COUNTER PRIMARY KEY,
                    datum DATETIME,
                    broker TEXT(64),
                    account_name TEXT(128),
                    entry_type TEXT(32),
                    amount DOUBLE,
                    currency_code TEXT(16),
                    fx_rate DOUBLE,
                    transfer_group TEXT(64),
                    comment_text TEXT(255),
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )

        for index_name, index_sql in (
            (
                f"idx_{CASH_MANAGEMENT_TABLE}_datum",
                f"CREATE INDEX idx_{CASH_MANAGEMENT_TABLE}_datum ON {CASH_MANAGEMENT_TABLE} (datum)",
            ),
            (
                f"idx_{CASH_MANAGEMENT_TABLE}_broker",
                f"CREATE INDEX idx_{CASH_MANAGEMENT_TABLE}_broker ON {CASH_MANAGEMENT_TABLE} (broker)",
            ),
            (
                f"idx_{CASH_MANAGEMENT_TABLE}_account",
                f"CREATE INDEX idx_{CASH_MANAGEMENT_TABLE}_account ON {CASH_MANAGEMENT_TABLE} (account_name)",
            ),
            (
                f"idx_{CASH_MANAGEMENT_TABLE}_type",
                f"CREATE INDEX idx_{CASH_MANAGEMENT_TABLE}_type ON {CASH_MANAGEMENT_TABLE} (entry_type)",
            ),
            (
                f"idx_{CASH_MANAGEMENT_TABLE}_transfer",
                f"CREATE INDEX idx_{CASH_MANAGEMENT_TABLE}_transfer ON {CASH_MANAGEMENT_TABLE} (transfer_group)",
            ),
            (
                f"idx_{CASH_MANAGEMENT_TABLE}_broker_date",
                f"CREATE INDEX idx_{CASH_MANAGEMENT_TABLE}_broker_date ON {CASH_MANAGEMENT_TABLE} (broker, datum)",
            ),
        ):
            if _index_exists(cur, CASH_MANAGEMENT_TABLE, index_name):
                continue
            try:
                cur.execute(index_sql)
            except Exception:
                pass
        conn.commit()
    if db_key:
        _SCHEMA_READY_PATHS.add(db_key)


def list_cash_management_entries(limit: int | None = 3000) -> list[dict]:
    ensure_cash_management_schema()
    with _get_connection_with_retry() as conn:
        cur = conn.cursor()
        top_clause = ""
        if limit is not None:
            try:
                n = max(1, int(limit))
                top_clause = f"TOP {n} "
            except Exception:
                top_clause = ""
        rows = cur.execute(
            f"""
        SELECT
            {top_clause}id,
            datum,
            broker,
            account_name,
            entry_type,
            amount,
            currency_code,
            fx_rate,
            transfer_group,
            comment_text
        FROM {CASH_MANAGEMENT_TABLE}
        ORDER BY datum DESC, id DESC
        """,
        ).fetchall()

    out: list[dict] = []
    for row in rows:
        out.append(
            {
                "id": row[0],
                "datum": row[1],
                "broker": row[2],
                "account_name": row[3],
                "entry_type": row[4],
                "amount": row[5],
                "currency_code": row[6],
                "fx_rate": row[7],
                "transfer_group": row[8],
                "comment_text": row[9],
            }
        )
    return out


def upsert_cash_management_entry(payload: dict) -> int:
    ensure_cash_management_schema()
    now = datetime.now()
    entry_id = payload.get("id")
    datum = payload.get("datum")
    broker = str(payload.get("broker") or "").strip().lower()
    account_name = str(payload.get("account_name") or "").strip()
    entry_type = str(payload.get("entry_type") or "").strip().lower()
    amount = payload.get("amount")
    currency_code = str(payload.get("currency_code") or "EUR").strip().upper()
    fx_rate = payload.get("fx_rate")
    transfer_group = str(payload.get("transfer_group") or "").strip() or None
    comment_text = str(payload.get("comment_text") or "").strip() or None

    if not datum:
        raise ValueError("datum is verplicht")
    if not broker:
        raise ValueError("broker is verplicht")
    if not account_name:
        raise ValueError("account_name is verplicht")
    if entry_type not in {"deposit", "withdrawal", "fx_conversion_in", "fx_conversion_out"}:
        raise ValueError("entry_type ongeldig")
    try:
        amount = float(amount)
    except Exception as exc:
        raise ValueError("amount is ongeldig") from exc
    if fx_rate in ("", None):
        fx_rate = None
    else:
        try:
            fx_rate = float(fx_rate)
        except Exception as exc:
            raise ValueError("fx_rate is ongeldig") from exc

    with _get_connection_with_retry() as conn:
        cur = conn.cursor()
        if entry_id in ("", None):
            cur.execute(
                f"""
                INSERT INTO {CASH_MANAGEMENT_TABLE}
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
                    datum,
                    broker,
                    account_name,
                    entry_type,
                    amount,
                    currency_code,
                    fx_rate,
                    transfer_group,
                    comment_text,
                    now,
                    now,
                ),
            )
            cur.execute("SELECT @@IDENTITY")
            new_id = int(cur.fetchone()[0])
            conn.commit()
            return new_id
        cur.execute(
            f"""
            UPDATE {CASH_MANAGEMENT_TABLE}
            SET
                datum=?,
                broker=?,
                account_name=?,
                entry_type=?,
                amount=?,
                currency_code=?,
                fx_rate=?,
                transfer_group=?,
                comment_text=?,
                updated_at=?
            WHERE id=?
            """,
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
                now,
                int(entry_id),
            ),
        )
        conn.commit()
        return int(entry_id)


def delete_cash_management_entry(entry_id: int) -> None:
    ensure_cash_management_schema()
    with _get_connection_with_retry() as conn:
        cur = conn.cursor()
        cur.execute(f"DELETE FROM {CASH_MANAGEMENT_TABLE} WHERE id=?", (int(entry_id),))
        conn.commit()
