from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import pyodbc


@dataclass(frozen=True)
class AssetRow:
    asset_rollup: str
    ib_symbol: str
    ib_currency: str
    asset_type: str

    @property
    def label(self) -> str:
        suffix = f" / {self.ib_symbol}" if self.ib_symbol and self.ib_symbol != self.asset_rollup else ""
        return f"{self.asset_rollup}{suffix}"


def connect_access(db_path: str) -> pyodbc.Connection:
    conn_str = (
        r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        rf"DBQ={db_path};"
        r"READONLY=TRUE;"
    )
    return pyodbc.connect(conn_str)


def load_assets(db_path: str) -> list[AssetRow]:
    sql = """
        SELECT asset_rollup, ib_symbol, ib_currency, [type]
        FROM asset_rollup_data
        WHERE asset_rollup IS NOT NULL
        ORDER BY asset_rollup
    """
    rows: list[AssetRow] = []
    with connect_access(db_path) as conn:
        cur = conn.cursor()
        for row in cur.execute(sql).fetchall():
            asset_rollup = clean(getattr(row, "asset_rollup", ""))
            if not asset_rollup:
                continue
            rows.append(
                AssetRow(
                    asset_rollup=asset_rollup.upper(),
                    ib_symbol=clean(getattr(row, "ib_symbol", "")),
                    ib_currency=clean(getattr(row, "ib_currency", "")) or "USD",
                    asset_type=clean(getattr(row, "type", "")),
                )
            )
    return rows


def load_volatility_history(db_path: str, asset_rollup: str) -> pd.DataFrame:
    sql = """
        SELECT [datum], [close], [historical_volatility], [implied_volatility]
        FROM historical_data_correct
        WHERE UCASE([asset_rollup]) = UCASE(?)
          AND [implied_volatility] IS NOT NULL
        ORDER BY [datum]
    """
    with connect_access(db_path) as conn:
        cur = conn.cursor()
        rows = cur.execute(sql, asset_rollup).fetchall()
        cols = [col[0] for col in cur.description]
        df = pd.DataFrame.from_records(rows, columns=cols)

    if df.empty:
        return pd.DataFrame(columns=["close", "historical_volatility", "implied_vol"])

    df["datum"] = pd.to_datetime(df["datum"], errors="coerce")
    df = df.dropna(subset=["datum"]).sort_values("datum").set_index("datum")
    df = df.rename(columns={"implied_volatility": "implied_vol"})
    for column in ("close", "historical_volatility", "implied_vol"):
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=["implied_vol"])
    return df


def filter_duration(df: pd.DataFrame, duration: str) -> pd.DataFrame:
    if df.empty:
        return df
    days = duration_to_days(duration)
    if days is None:
        return df
    cutoff = df.index.max() - pd.Timedelta(days=days)
    return df.loc[df.index >= cutoff].copy()


def duration_to_days(duration: str) -> int | None:
    text = clean(duration).upper()
    if not text:
        return None
    parts = text.split()
    if len(parts) != 2:
        return None
    try:
        amount = int(float(parts[0]))
    except ValueError:
        return None
    unit = parts[1]
    if unit.startswith("D"):
        return amount
    if unit.startswith("W"):
        return amount * 7
    if unit.startswith("M"):
        return amount * 30
    if unit.startswith("Y"):
        return amount * 365
    return None


def clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
