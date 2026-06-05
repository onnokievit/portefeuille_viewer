from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


FILTER_COLUMNS = ("broker", "ib_currency", "asset_type", "sector", "regio", "value_grow")
PIVOT_FIELDS = (
    "Periode",
    "broker",
    "ib_currency",
    "asset_rollup",
    "asset_type",
    "transactie_type",
    "transactie_oorsprong",
    "sector",
    "regio",
    "value_grow",
)
GRANULARITIES = {
    "Jaar": "Y",
    "Maand": "M",
    "Week": "W-MON",
    "Dag": "D",
}


@dataclass
class PivotRequest:
    granularity: str = "Maand"
    enabled_filters: dict[str, set[str]] = field(default_factory=dict)
    row_fields: list[str] = field(default_factory=lambda: ["Periode"])
    column_fields: list[str] = field(default_factory=lambda: ["broker", "ib_currency"])
    date_from: pd.Timestamp | None = None
    date_to: pd.Timestamp | None = None
    include_count: bool = True
    include_fee: bool = True


def apply_filters(df: pd.DataFrame, request: PivotRequest) -> pd.DataFrame:
    result = df.copy()
    if request.date_from is not None:
        result = result[result["datum"] >= request.date_from]
    if request.date_to is not None:
        result = result[result["datum"] <= request.date_to]

    for col, selected in request.enabled_filters.items():
        if selected and col in result.columns:
            result = result[result[col].isin(selected)]
    return result


def _period_label(values: pd.Series, granularity: str) -> pd.Series:
    if granularity == "Jaar":
        return values.dt.strftime("%Y")
    if granularity == "Maand":
        return values.dt.strftime("%Y-%m")
    if granularity == "Week":
        iso = values.dt.isocalendar()
        return iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)
    return values.dt.strftime("%Y-%m-%d")


def build_pivot(df: pd.DataFrame, request: PivotRequest) -> pd.DataFrame:
    filtered = apply_filters(df, request)
    filtered = filtered.dropna(subset=["datum"]).copy()
    if filtered.empty:
        return pd.DataFrame()

    filtered["Periode"] = _period_label(filtered["datum"], request.granularity)
    row_fields = _clean_fields(request.row_fields, fallback=["Periode"])
    column_fields = _clean_fields(request.column_fields, fallback=["broker", "ib_currency"])
    row_fields = [field for field in row_fields if field in filtered.columns]
    column_fields = [field for field in column_fields if field in filtered.columns and field not in row_fields]
    if not row_fields:
        row_fields = ["Periode"]

    grouped = (
        filtered.groupby(row_fields + column_fields, dropna=False)
        .agg(
            Aantal=("Id", "count"),
            Fee=("transactie_fee", "sum"),
        )
        .reset_index()
    )

    value_columns = []
    if request.include_count:
        value_columns.append("Aantal")
    if request.include_fee:
        value_columns.append("Fee")
    if not value_columns:
        value_columns = ["Aantal", "Fee"]

    if column_fields:
        pivot = grouped.pivot_table(
            index=row_fields,
            columns=column_fields,
            values=value_columns,
            aggfunc="sum",
            fill_value=0,
            margins=True,
            margins_name="Totaal",
        )
        pivot = pivot.sort_index(axis=1, level=list(range(pivot.columns.nlevels)))
        pivot = pivot.reset_index()
    else:
        pivot = grouped.groupby(row_fields, dropna=False)[value_columns].sum().reset_index()
        total = {field: "Totaal" if idx == 0 else "" for idx, field in enumerate(row_fields)}
        for col in value_columns:
            total[col] = pivot[col].sum()
        pivot = pd.concat([pivot, pd.DataFrame([total])], ignore_index=True)

    pivot.columns = _flatten_columns(pivot.columns)
    leading = [field for field in row_fields if field in pivot.columns]
    value_cols = [col for col in pivot.columns if col not in leading and "| Totaal" not in col]
    total_cols = [col for col in pivot.columns if "| Totaal" in col]
    return pivot[leading + value_cols + total_cols]


def _flatten_columns(columns) -> list[str]:
    flattened: list[str] = []
    for col in columns:
        if isinstance(col, tuple):
            parts = [str(part) for part in col if str(part) and str(part) != "nan"]
            if parts == ["Periode"]:
                flattened.append("Periode")
            else:
                flattened.append(" | ".join(parts))
        else:
            flattened.append(str(col))
    return flattened


def _clean_fields(fields: list[str] | tuple[str, ...], fallback: list[str]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for field in fields or fallback:
        text = str(field or "").strip()
        if text and text not in seen:
            cleaned.append(text)
            seen.add(text)
    return cleaned or list(fallback)
