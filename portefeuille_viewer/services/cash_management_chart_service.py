from __future__ import annotations

from datetime import date

import pandas as pd
import polars as pl

from portefeuille_viewer.data.repository import get_connection


PREFERRED_BROKER_ORDER = ["degiro", "lynx", "interactive"]


def _empty_payload() -> dict:
    return {
        "points": [],
        "brokers": [],
        "stats": {
            "start_date": None,
            "end_date": None,
            "brokers": 0,
            "points": 0,
        },
    }


def _sort_brokers(values: list[str]) -> list[str]:
    preferred_map = {name: idx for idx, name in enumerate(PREFERRED_BROKER_ORDER)}
    return sorted(
        values,
        key=lambda broker: (
            0 if broker in preferred_map else 1,
            preferred_map.get(broker, 9999),
            broker,
        ),
    )


def _load_cash_entries_df() -> pl.DataFrame:
    with get_connection() as conn:
        try:
            pdf = pd.read_sql(
                """
                SELECT datum, broker, entry_type, amount
                FROM cash_management_entries
                WHERE entry_type IN ('deposit', 'withdrawal')
                """,
                conn,
            )
        except Exception:
            pdf = pd.DataFrame()
    if pdf.empty:
        return pl.DataFrame(
            schema={
                "datum": pl.Date,
                "broker": pl.Utf8,
                "entry_type": pl.Utf8,
                "amount": pl.Float64,
            }
        )
    df = pl.from_pandas(pdf)
    return df.with_columns(
        [
            pl.col("datum").cast(pl.Date),
            pl.col("broker").cast(pl.Utf8).str.strip_chars().str.to_lowercase(),
            pl.col("entry_type").cast(pl.Utf8).str.strip_chars().str.to_lowercase(),
            pl.col("amount").cast(pl.Float64),
        ]
    )


def _load_daily_balances_df() -> pl.DataFrame:
    with get_connection() as conn:
        try:
            pdf = pd.read_sql(
                """
                SELECT datum, broker, ending_balance
                FROM account_daily_balances
                """,
                conn,
            )
        except Exception:
            pdf = pd.DataFrame()
    if pdf.empty:
        return pl.DataFrame(
            schema={
                "datum": pl.Date,
                "broker": pl.Utf8,
                "ending_balance": pl.Float64,
            }
        )
    df = pl.from_pandas(pdf)
    return df.with_columns(
        [
            pl.col("datum").cast(pl.Date),
            pl.col("broker").cast(pl.Utf8).str.strip_chars().str.to_lowercase(),
            pl.col("ending_balance").cast(pl.Float64),
        ]
    )


def build_cash_management_chart_payload() -> dict:
    cash_df = _load_cash_entries_df()
    balance_df = _load_daily_balances_df()

    broker_frames = []
    if not cash_df.is_empty():
        broker_frames.append(cash_df.select("broker"))
    if not balance_df.is_empty():
        broker_frames.append(balance_df.select("broker"))
    if not broker_frames:
        return _empty_payload()

    brokers = _sort_brokers(
        pl.concat(broker_frames).unique().sort("broker").get_column("broker").to_list()
    )
    if not brokers:
        return _empty_payload()
    broker_sort_df = pl.DataFrame({"broker": brokers, "broker_sort": list(range(len(brokers)))})
    brokers_df = broker_sort_df.select("broker")

    dates = []
    if not cash_df.is_empty():
        dates.extend(cash_df.get_column("datum").drop_nulls().to_list())
    if not balance_df.is_empty():
        dates.extend(balance_df.get_column("datum").drop_nulls().to_list())
    if not dates:
        return _empty_payload()

    start_date = min(dates)
    end_date = max(dates)
    if not isinstance(start_date, date) or not isinstance(end_date, date):
        return _empty_payload()

    calendar_df = pl.DataFrame(
        {
            "datum": pl.date_range(start=start_date, end=end_date, interval="1d", eager=True),
        }
    )
    grid_df = calendar_df.join(brokers_df, how="cross")

    if cash_df.is_empty():
        cash_daily = pl.DataFrame(schema={"datum": pl.Date, "broker": pl.Utf8, "daily_cash_flow": pl.Float64})
    else:
        cash_daily = (
            cash_df.group_by(["datum", "broker"])
            .agg(pl.col("amount").sum().alias("daily_cash_flow"))
            .sort(["broker", "datum"])
        )

    if balance_df.is_empty():
        balance_daily = pl.DataFrame(
            schema={"datum": pl.Date, "broker": pl.Utf8, "ending_balance": pl.Float64}
        )
    else:
        balance_daily = (
            balance_df.group_by(["datum", "broker"])
            .agg(pl.col("ending_balance").last().alias("ending_balance"))
            .sort(["broker", "datum"])
        )

    joined = (
        grid_df.join(cash_daily, on=["datum", "broker"], how="left")
        .join(balance_daily, on=["datum", "broker"], how="left")
        .join(broker_sort_df, on="broker", how="left")
        .with_columns(pl.col("daily_cash_flow").fill_null(0.0))
        .sort(["broker_sort", "datum"])
        .with_columns(
            [
                pl.col("daily_cash_flow").cum_sum().over("broker").alias("invested_cumulative"),
                pl.col("ending_balance").forward_fill().over("broker").alias("ending_balance_ffill"),
            ]
        )
        .sort(["datum", "broker_sort"])
        .with_columns(
            pl.col("invested_cumulative").cum_sum().over("datum").alias("invested_stacked")
        )
        .with_columns(
            (
                pl.col("ending_balance_ffill") - pl.col("invested_cumulative")
            ).alias("profit")
        )
        .sort(["broker_sort", "datum"])
    )

    totals = (
        joined.group_by("datum")
        .agg(
            [
                pl.col("ending_balance_ffill").sum().alias("total_value"),
                pl.col("invested_cumulative").sum().alias("total_invested"),
                pl.col("profit").sum().alias("total_profit"),
            ]
        )
        .sort("datum")
    )

    totals_map = {
        row["datum"]: {
            "total_value": None if row["total_value"] is None else float(row["total_value"]),
            "total_invested": None if row["total_invested"] is None else float(row["total_invested"]),
            "total_profit": None if row["total_profit"] is None else float(row["total_profit"]),
        }
        for row in totals.to_dicts()
    }

    points: list[dict] = []
    for row in joined.to_dicts():
        day_totals = totals_map.get(row["datum"], {})
        points.append(
            {
                "date": row["datum"].isoformat() if row["datum"] else "",
                "broker": str(row["broker"] or ""),
                "invested_cumulative": None
                if row["invested_cumulative"] is None
                else float(row["invested_cumulative"]),
                "invested_stacked": None
                if row["invested_stacked"] is None
                else float(row["invested_stacked"]),
                "ending_balance": None
                if row["ending_balance_ffill"] is None
                else float(row["ending_balance_ffill"]),
                "profit": None if row["profit"] is None else float(row["profit"]),
                "total_value": day_totals.get("total_value"),
                "total_invested": day_totals.get("total_invested"),
                "total_profit": day_totals.get("total_profit"),
            }
        )

    return {
        "points": points,
        "brokers": brokers,
        "stats": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "brokers": len(brokers),
            "points": len(points),
        },
    }
