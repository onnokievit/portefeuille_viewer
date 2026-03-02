from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

import polars as pl
import pyodbc


DEFAULT_DB_PATH = r"C:\Users\onno\OneDrive\Beleggen\2025 - portefeuille database 02.03 - ONNO.accdb"


def get_connection(db_path: str = DEFAULT_DB_PATH) -> pyodbc.Connection:
    conn_str = r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=" + db_path
    return pyodbc.connect(conn_str)


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def sql_date_literal(value: date | datetime) -> str:
    if isinstance(value, datetime):
        value = value.date()
    return f"#{value:%Y-%m-%d}#"


def quantize_decimal(value, scale: int):
    if value is None:
        return None
    q = Decimal("1").scaleb(-scale)
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))


def normalize_numeric_columns(df: pl.DataFrame, precision_map: dict[str, int]) -> pl.DataFrame:
    for col, scale in precision_map.items():
        if col in df.columns:
            df = df.with_columns(
                pl.col(col)
                .map_elements(lambda v, s=scale: quantize_decimal(v, s), return_dtype=pl.Float64)
                .alias(col)
            )
    return df


def chunked(items: Iterable, size: int):
    chunk = []
    for item in items:
        chunk.append(item)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def normalize_uniek_id_for_compare(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    # Legacy v1 ids can contain an Access-style leading space before numeric strikes: "...-put- 19"
    return re.sub(r"-(\s+)(?=\d)", "-", value)
