import pyodbc

from datetime import datetime
from time import sleep

from portefeuille_viewer.data.repository import get_connection


ACCOUNT_DAILY_BALANCES_TABLE = "account_daily_balances"
_SCHEMA_READY = False


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


def ensure_account_daily_balances_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with _get_connection_with_retry() as conn:
        cur = conn.cursor()
        if not _table_exists(cur, ACCOUNT_DAILY_BALANCES_TABLE):
            cur.execute(
                f"""
                CREATE TABLE {ACCOUNT_DAILY_BALANCES_TABLE} (
                    id COUNTER PRIMARY KEY,
                    datum DATETIME,
                    broker TEXT(64),
                    account_name TEXT(128),
                    ending_balance DOUBLE,
                    currency_code TEXT(16),
                    source_name TEXT(32),
                    comment_text TEXT(255),
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )

        for index_name, index_sql in (
            (
                f"idx_{ACCOUNT_DAILY_BALANCES_TABLE}_datum",
                f"CREATE INDEX idx_{ACCOUNT_DAILY_BALANCES_TABLE}_datum ON {ACCOUNT_DAILY_BALANCES_TABLE} (datum)",
            ),
            (
                f"idx_{ACCOUNT_DAILY_BALANCES_TABLE}_broker",
                f"CREATE INDEX idx_{ACCOUNT_DAILY_BALANCES_TABLE}_broker ON {ACCOUNT_DAILY_BALANCES_TABLE} (broker)",
            ),
            (
                f"idx_{ACCOUNT_DAILY_BALANCES_TABLE}_account",
                f"CREATE INDEX idx_{ACCOUNT_DAILY_BALANCES_TABLE}_account ON {ACCOUNT_DAILY_BALANCES_TABLE} (account_name)",
            ),
            (
                f"idx_{ACCOUNT_DAILY_BALANCES_TABLE}_source",
                f"CREATE INDEX idx_{ACCOUNT_DAILY_BALANCES_TABLE}_source ON {ACCOUNT_DAILY_BALANCES_TABLE} (source_name)",
            ),
            (
                f"idx_{ACCOUNT_DAILY_BALANCES_TABLE}_broker_date",
                f"CREATE INDEX idx_{ACCOUNT_DAILY_BALANCES_TABLE}_broker_date ON {ACCOUNT_DAILY_BALANCES_TABLE} (broker, datum)",
            ),
        ):
            if _index_exists(cur, ACCOUNT_DAILY_BALANCES_TABLE, index_name):
                continue
            try:
                cur.execute(index_sql)
            except Exception:
                pass
        conn.commit()
    _SCHEMA_READY = True


def list_account_daily_balances(limit: int | None = 3000) -> list[dict]:
    ensure_account_daily_balances_schema()
    with _get_connection_with_retry() as conn:
        cur = conn.cursor()
        top_clause = ""
        if limit is not None:
            try:
                top_clause = f"TOP {max(1, int(limit))} "
            except Exception:
                top_clause = ""
        rows = cur.execute(
            f"""
            SELECT
                {top_clause}id,
                datum,
                broker,
                account_name,
                ending_balance,
                currency_code,
                source_name,
                comment_text
            FROM {ACCOUNT_DAILY_BALANCES_TABLE}
            ORDER BY datum DESC, broker ASC, id DESC
            """
        ).fetchall()

    out: list[dict] = []
    for row in rows:
        out.append(
            {
                "id": row[0],
                "datum": row[1],
                "broker": row[2],
                "account_name": row[3],
                "ending_balance": row[4],
                "currency_code": row[5],
                "source_name": row[6],
                "comment_text": row[7],
            }
        )
    return out


def upsert_account_daily_balance(payload: dict) -> int:
    ensure_account_daily_balances_schema()
    now = datetime.now()
    balance_id = payload.get("id")
    datum = payload.get("datum")
    broker = str(payload.get("broker") or "").strip().lower()
    ending_balance = payload.get("ending_balance")
    currency_code = str(payload.get("currency_code") or "EUR").strip().upper()
    source_name = str(payload.get("source_name") or "manual").strip().lower()
    comment_text = str(payload.get("comment_text") or "").strip() or None

    if not datum:
        raise ValueError("datum is verplicht")
    if not broker:
        raise ValueError("broker is verplicht")
    try:
        ending_balance = float(ending_balance)
    except Exception as exc:
        raise ValueError("ending_balance is ongeldig") from exc
    if not source_name:
        source_name = "manual"

    with _get_connection_with_retry() as conn:
        cur = conn.cursor()
        if balance_id in ("", None):
            cur.execute(
                f"""
                INSERT INTO {ACCOUNT_DAILY_BALANCES_TABLE}
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
                    datum,
                    broker,
                    broker,
                    ending_balance,
                    currency_code,
                    source_name,
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
            UPDATE {ACCOUNT_DAILY_BALANCES_TABLE}
            SET
                datum=?,
                broker=?,
                account_name=?,
                ending_balance=?,
                currency_code=?,
                source_name=?,
                comment_text=?,
                updated_at=?
            WHERE id=?
            """,
            (
                datum,
                broker,
                broker,
                ending_balance,
                currency_code,
                source_name,
                comment_text,
                now,
                int(balance_id),
            ),
        )
        conn.commit()
        return int(balance_id)


def delete_account_daily_balance(balance_id: int) -> None:
    ensure_account_daily_balances_schema()
    with _get_connection_with_retry() as conn:
        cur = conn.cursor()
        cur.execute(f"DELETE FROM {ACCOUNT_DAILY_BALANCES_TABLE} WHERE id=?", (int(balance_id),))
        conn.commit()
