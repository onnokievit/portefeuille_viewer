from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pyodbc

from portefeuille_viewer.data import repository


@dataclass
class DividendCalendarRow:
    asset_rollup: str
    ib_symbol: str
    ib_currency: str
    next_dividend_date: date | None
    next_dividend_amount: float | None
    trailing_12m_dividend: float | None
    forward_12m_dividend: float | None
    next_earnings_date: date | None
    source_dividend: str
    source_earnings: str
    status: str
    message: str
    raw_dividend_value: str
    fetched_at: datetime
    updated_at: datetime


def _connect() -> pyodbc.Connection:
    return repository.get_stockdata_connection()


def ensure_dividend_calendar_schema() -> None:
    with _connect() as conn:
        cur = conn.cursor()
        for table_name in ("asset_dividend_calendar_current", "asset_dividend_calendar_history"):
            exists = any(row.table_name == table_name for row in cur.tables(table=table_name))
            if not exists:
                cur.execute(
                    f"""
                    CREATE TABLE {table_name} (
                        Id AUTOINCREMENT PRIMARY KEY,
                        asset_rollup TEXT(64),
                        ib_symbol TEXT(64),
                        ib_currency TEXT(16),
                        next_dividend_date DATETIME,
                        next_dividend_amount DOUBLE,
                        trailing_12m_dividend DOUBLE,
                        forward_12m_dividend DOUBLE,
                        next_earnings_date DATETIME,
                        source_dividend TEXT(80),
                        source_earnings TEXT(80),
                        status TEXT(32),
                        message LONGTEXT,
                        raw_dividend_value LONGTEXT,
                        fetched_at DATETIME,
                        updated_at DATETIME
                    )
                    """
                )
                conn.commit()
        for stmt in [
            "CREATE INDEX idx_divcal_current_asset ON asset_dividend_calendar_current (asset_rollup)",
            "CREATE INDEX idx_divcal_current_next_div ON asset_dividend_calendar_current (next_dividend_date)",
            "CREATE INDEX idx_divcal_history_asset_fetch ON asset_dividend_calendar_history (asset_rollup, fetched_at)",
        ]:
            try:
                cur.execute(stmt)
                conn.commit()
            except pyodbc.Error:
                conn.rollback()


def _row_values(row: DividendCalendarRow) -> tuple[Any, ...]:
    return (
        row.asset_rollup,
        row.ib_symbol,
        row.ib_currency,
        row.next_dividend_date,
        row.next_dividend_amount,
        row.trailing_12m_dividend,
        row.forward_12m_dividend,
        row.next_earnings_date,
        row.source_dividend,
        row.source_earnings,
        row.status,
        row.message[:32000] if row.message else "",
        row.raw_dividend_value[:32000] if row.raw_dividend_value else "",
        row.fetched_at,
        row.updated_at,
    )


def replace_current_and_append_history(rows: list[DividendCalendarRow]) -> None:
    """Compatibility name: patch available values; never delete the current row."""
    ensure_dividend_calendar_schema()
    if not rows:
        return
    columns = """
        asset_rollup, ib_symbol, ib_currency, next_dividend_date, next_dividend_amount,
        trailing_12m_dividend, forward_12m_dividend, next_earnings_date,
        source_dividend, source_earnings, status, message, raw_dividend_value,
        fetched_at, updated_at
    """
    placeholders = ", ".join("?" for _ in range(15))
    with _connect() as conn:
        conn.begin_write()
        cur = conn.cursor()
        for row in rows:
            current = cur.execute('SELECT ' + columns + ' FROM asset_dividend_calendar_current WHERE asset_rollup=?',
                                  row.asset_rollup).fetchone()
            names = [name.strip() for name in columns.split(',')]
            before = dict(zip(names, current)) if current else {}
            merged = merge_dividend_row(before, row)
            values = tuple(merged[name] for name in names)
            if current:
                cur.execute('UPDATE asset_dividend_calendar_current SET '
                    + ','.join(f'[{name}]=?' for name in names[1:]) + ' WHERE asset_rollup=?',
                    *(values[1:] + (row.asset_rollup,)))
            else:
                cur.execute(f'INSERT INTO asset_dividend_calendar_current ({columns}) VALUES ({placeholders})', *values)
            substantive = set(names) - {'fetched_at', 'updated_at'}
            def comparable(value):
                return value.date() if isinstance(value, datetime) else value
            if not current or any(comparable(before.get(name)) != comparable(merged[name]) for name in substantive):
                cur.execute(f'INSERT INTO asset_dividend_calendar_history ({columns}) VALUES ({placeholders})', *values)
        conn.commit()


def merge_dividend_row(before, row):
    names = ('asset_rollup','ib_symbol','ib_currency','next_dividend_date','next_dividend_amount',
             'trailing_12m_dividend','forward_12m_dividend','next_earnings_date','source_dividend',
             'source_earnings','status','message','raw_dividend_value','fetched_at','updated_at')
    incoming = dict(zip(names, _row_values(row)))
    merged = dict(before)
    for name, value in incoming.items():
        if name in {'status','message','fetched_at','updated_at'} or value is not None and value != '':
            merged[name] = value
        else:
            merged.setdefault(name, value)
    old_date = before.get('next_dividend_date')
    old_date = old_date.date() if isinstance(old_date, datetime) else old_date
    # Do not attach a previous dividend amount to a newly announced date.
    if old_date and row.next_dividend_date and old_date != row.next_dividend_date and row.next_dividend_amount is None:
        merged['next_dividend_date'] = before['next_dividend_date']
        merged['next_dividend_amount'] = before.get('next_dividend_amount')
        merged['message'] = 'Nieuwe dividenddatum ontvangen; wacht op bijpassend bedrag'
        merged['status'] = 'partial'
    return merged


def load_asset_universe() -> list[dict[str, Any]]:
    query = """
        SELECT
            asset_rollup,
            [type] AS asset_type,
            ib_symbol,
            ib_currency,
            exchange,
            prim_exchange,
            contractid
        FROM asset_rollup_data
        WHERE IIF(ib_symbol IS NULL, '', ib_symbol) <> ''
        ORDER BY asset_rollup
    """
    with _connect() as conn:
        rows = conn.cursor().execute(query).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        contractid = None
        try:
            contractid = int(row.contractid) if row.contractid is not None else None
        except Exception:
            contractid = None
        out.append(
            {
                "asset_rollup": str(row.asset_rollup or "").strip(),
                "asset_type": str(row.asset_type or "").strip().lower(),
                "ib_symbol": str(row.ib_symbol or "").strip(),
                "ib_currency": str(row.ib_currency or "USD").strip() or "USD",
                "exchange": str(row.exchange or "SMART").strip() or "SMART",
                "prim_exchange": str(row.prim_exchange or "").strip(),
                "contractid": contractid,
            }
        )
    return out
