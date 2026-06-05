from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pyodbc


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from portefeuille_viewer.config import get_databases, get_default_database  # noqa: E402


def active_database() -> tuple[str, str]:
    databases = get_databases()
    default_name = get_default_database()
    if not default_name or default_name not in databases:
        raise RuntimeError("Geen actieve database gevonden in settings.")
    db_path = databases[default_name].get("path") or ""
    if not db_path:
        raise RuntimeError(f"Database '{default_name}' heeft geen pad in settings.")
    return default_name, db_path


def connect_read_only() -> pyodbc.Connection:
    _, db_path = active_database()
    conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path};"
    return pyodbc.connect(conn_str, readonly=True)


def load_transactions() -> pd.DataFrame:
    sql = """
        SELECT
            t.Id,
            t.datum,
            t.broker,
            t.asset_rollup,
            t.asset_detail,
            t.asset_type,
            t.transactie_type,
            t.transactie_oorsprong,
            t.transactie_oorsprong_detail,
            t.aantal,
            t.transactie_prijs,
            t.transactie_fee,
            t.transactie_euro_totaal,
            t.transactie_aantal,
            a.ib_currency,
            a.sector,
            a.regio,
            a.value_grow,
            a.type AS asset_rollup_type
        FROM transacties_bron_data_org AS t
        LEFT JOIN asset_rollup_data AS a
            ON t.asset_rollup = a.asset_rollup
    """
    with connect_read_only() as conn:
        cursor = conn.cursor()
        rows = cursor.execute(sql).fetchall()
        columns = [column[0] for column in cursor.description]
        df = pd.DataFrame.from_records(rows, columns=columns)

    df["datum"] = pd.to_datetime(df["datum"], errors="coerce")
    df["transactie_fee"] = pd.to_numeric(df["transactie_fee"], errors="coerce").fillna(0.0)
    for col in (
        "broker",
        "asset_rollup",
        "asset_type",
        "transactie_type",
        "transactie_oorsprong",
        "ib_currency",
        "sector",
        "regio",
        "value_grow",
    ):
        df[col] = df[col].fillna("Onbekend").astype(str).str.strip()
        df.loc[df[col] == "", col] = "Onbekend"
    return df
