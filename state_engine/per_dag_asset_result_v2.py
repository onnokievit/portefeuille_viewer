from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from time import perf_counter
from uuid import uuid4

import polars as pl
import pyodbc

from common import DEFAULT_DB_PATH, get_connection, normalize_numeric_columns, parse_iso_date


TEMP_STAGE_TABLE_PREFIX = "TempAssetResultV2Stage"
DIVIDEND_FEE_TYPES = ("dividend", "div_belasting", "871_fee", "transactiebelasting")

PRECISION_MAP = {
    "aandelen_resultaat_v2": 2,
    "asset_fee_v2": 2,
    "optie_resultaat_v2": 2,
    "gesloten_opties": 2,
    "optie_fee_v2": 2,
    "sprinter_resultaat_v2": 2,
    "gesloten_sprinters": 2,
    "sprinter_fee_v2": 2,
    "dividend_v2": 2,
    "dividend_belasting_v2": 2,
    "fees_dividend_belasting_v2": 2,
    "totaal_v2": 2,
}


@dataclass
class RebuildScope:
    assets: list[str] | None
    from_date: date
    to_date: date
    mode: str


@dataclass
class RunOptions:
    insert_mode: str
    temp_table_name: str


class PhaseTimer:
    def __init__(self) -> None:
        self._last = perf_counter()

    def mark(self, label: str) -> None:
        now = perf_counter()
        elapsed = now - self._last
        self._last = now
        print(f"[timing] {label}: {elapsed:.3f}s")


def parse_args():
    parser = argparse.ArgumentParser(description="Bouw per_dag_asset_result_v2 vanuit v2 state tabellen")
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--mode", choices=["full", "asset_incremental", "asset_split_rebuild"], default="full")
    parser.add_argument("--asset-rollups", help="Comma separated asset_rollup(s) for asset scoped rebuilds")
    parser.add_argument("--from-date", help="YYYY-MM-DD for incremental rebuild")
    parser.add_argument("--to-date", help="YYYY-MM-DD, default vandaag")
    parser.add_argument("--insert-mode", choices=["temp_table", "executemany"], default="temp_table")
    return parser.parse_args()


def _normalize_assets(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    assets = [x.strip() for x in raw.split(",") if x.strip()]
    return assets or None


def fetch_min_state_date(conn, table_name: str) -> date | None:
    cur = conn.cursor()
    try:
        row = cur.execute(f"SELECT MIN(datum) FROM {table_name}").fetchone()
    except Exception:
        return None
    if not row or row[0] is None:
        return None
    value = row[0]
    return value.date() if isinstance(value, datetime) else value


def resolve_scope(args, conn) -> RebuildScope:
    today = parse_iso_date(args.to_date) or date.today()
    assets = _normalize_assets(args.asset_rollups)
    if args.mode == "asset_incremental":
        from_date = parse_iso_date(args.from_date)
        if not from_date:
            raise ValueError("--from-date is verplicht voor asset_incremental")
        return RebuildScope(assets=assets, from_date=from_date, to_date=today, mode=args.mode)

    if args.mode == "asset_split_rebuild" and assets:
        return RebuildScope(assets=assets, from_date=date(1900, 1, 1), to_date=today, mode=args.mode)

    min_dates = [
        fetch_min_state_date(conn, "per_dag_aandelen_state_v2"),
        fetch_min_state_date(conn, "per_dag_open_opties_opgerold_v2"),
        fetch_min_state_date(conn, "per_dag_open_sprinters_opgerold_v2"),
    ]
    min_dates = [d for d in min_dates if d is not None]
    start = min(min_dates) if min_dates else today
    return RebuildScope(assets=assets, from_date=start, to_date=today, mode=args.mode)


def _asset_filter_sql(scope: RebuildScope, alias: str = "") -> tuple[str, list]:
    if not scope.assets:
        return "", []
    prefix = f"{alias}." if alias else ""
    placeholders = ",".join("?" for _ in scope.assets)
    return f" AND {prefix}asset_rollup IN ({placeholders})", list(scope.assets)


def _ensure_columns(df: pl.DataFrame, cols: list[str]) -> pl.DataFrame:
    missing = [c for c in cols if c not in df.columns]
    if not missing:
        return df
    return df.with_columns([pl.lit(0.0).alias(c) for c in missing])


def load_aandelen_component(conn, scope: RebuildScope) -> pl.DataFrame:
    asset_filter, asset_params = _asset_filter_sql(scope)
    sql = f"""
        SELECT
            datum,
            asset_rollup,
            SUM(realized_pnl_total + unrealized_pnl_total) AS aandelen_resultaat_v2,
            SUM(cum_fee) AS asset_fee_v2
        FROM per_dag_aandelen_state_v2
        WHERE datum >= ? AND datum <= ?
        {asset_filter}
        GROUP BY datum, asset_rollup
    """
    params = [scope.from_date, scope.to_date, *asset_params]
    return pl.read_database(sql, conn, execute_options={"parameters": params}).with_columns(
        pl.col("datum").cast(pl.Date),
        pl.col("asset_rollup").cast(pl.Utf8).str.strip_chars(),
        pl.col("aandelen_resultaat_v2").fill_null(0.0),
        pl.col("asset_fee_v2").fill_null(0.0),
    )


def load_opties_component(conn, scope: RebuildScope) -> pl.DataFrame:
    asset_filter, asset_params = _asset_filter_sql(scope)
    sql_tx = f"""
        SELECT
            datum,
            asset_rollup,
            uniek_id,
            optie_exp_date,
            transactie_aantal,
            transactie_euro_totaal,
            transactie_fee
        FROM transacties_bron_data
        WHERE asset_type='optie'
          AND datum <= ?
          {asset_filter}
        ORDER BY asset_rollup, uniek_id, datum, Id
    """
    params_tx = [scope.to_date, *asset_params]
    df_tx = (
        pl.read_database(sql_tx, conn, execute_options={"parameters": params_tx})
        .with_columns(
            pl.col("datum").cast(pl.Date),
            pl.col("asset_rollup").cast(pl.Utf8).str.strip_chars(),
            pl.col("uniek_id").cast(pl.Utf8).str.strip_chars(),
            pl.col("optie_exp_date").cast(pl.Date),
            pl.col("transactie_aantal").fill_null(0.0),
            pl.col("transactie_euro_totaal").fill_null(0.0),
            pl.col("transactie_fee").fill_null(0.0),
        )
    )
    if df_tx.is_empty():
        return pl.DataFrame(
            schema={
                "datum": pl.Date,
                "asset_rollup": pl.Utf8,
                "optie_resultaat_v2": pl.Float64,
                "gesloten_opties": pl.Float64,
                "optie_fee_v2": pl.Float64,
            }
        )

    # Open ITM component uit opties-v2 state (alleen open series)
    sql_itm = f"""
        SELECT datum, asset_rollup, SUM(open_optie_waarde_itm) AS open_itm
        FROM per_dag_open_opties_opgerold_v2
        WHERE datum >= ? AND datum <= ?
        {asset_filter}
        GROUP BY datum, asset_rollup
    """
    params_itm = [scope.from_date, scope.to_date, *asset_params]
    df_itm = (
        pl.read_database(sql_itm, conn, execute_options={"parameters": params_itm})
        .with_columns(
            pl.col("datum").cast(pl.Date),
            pl.col("asset_rollup").cast(pl.Utf8).str.strip_chars(),
            pl.col("open_itm").fill_null(0.0),
        )
    )

    # Dagelijkse tx per serie
    df_day = (
        df_tx.group_by(["asset_rollup", "uniek_id", "datum"])
        .agg(
            pl.col("optie_exp_date").drop_nulls().max().alias("optie_exp_date"),
            pl.col("transactie_aantal").sum().alias("qty_dag"),
            pl.col("transactie_euro_totaal").sum().alias("eur_dag"),
            pl.col("transactie_fee").sum().alias("fee_dag"),
        )
        .sort(["asset_rollup", "uniek_id", "datum"])
    )

    # Intervallen met cumulatieve stand per serie
    intervals: list[dict] = []
    for part in df_day.partition_by(["asset_rollup", "uniek_id"], maintain_order=True):
        rows = part.to_dicts()
        asset = str(rows[0]["asset_rollup"]).strip()
        uid = str(rows[0]["uniek_id"]).strip()
        cum_qty = 0.0
        cum_eur = 0.0
        cum_fee = 0.0
        event_dates = [r["datum"] if not isinstance(r["datum"], datetime) else r["datum"].date() for r in rows]
        exp_date = rows[0].get("optie_exp_date")
        if isinstance(exp_date, datetime):
            exp_date = exp_date.date()
        for idx, row in enumerate(rows):
            event_date = row["datum"] if not isinstance(row["datum"], datetime) else row["datum"].date()
            cum_qty += float(row.get("qty_dag") or 0.0)
            cum_eur += float(row.get("eur_dag") or 0.0)
            cum_fee += float(row.get("fee_dag") or 0.0)
            next_event = event_dates[idx + 1] if idx + 1 < len(event_dates) else None
            end_date = scope.to_date if next_event is None else min(scope.to_date, next_event - timedelta(days=1))
            if end_date < event_date:
                continue
            intervals.append(
                {
                    "asset_rollup": asset,
                    "uniek_id": uid,
                    "datum_start": event_date,
                    "datum_end": end_date,
                    "optie_exp_date": exp_date,
                    "cum_qty": cum_qty,
                    "cum_eur": cum_eur,
                    "cum_fee": cum_fee,
                }
            )

    if not intervals:
        return pl.DataFrame(
            schema={
                "datum": pl.Date,
                "asset_rollup": pl.Utf8,
                "optie_resultaat_v2": pl.Float64,
                "gesloten_opties": pl.Float64,
                "optie_fee_v2": pl.Float64,
            }
        )

    df_int = pl.DataFrame(intervals)
    df_daily = (
        df_int.with_columns(
            pl.max_horizontal("datum_start", pl.lit(scope.from_date, dtype=pl.Date)).alias("effective_start"),
            pl.min_horizontal("datum_end", pl.lit(scope.to_date, dtype=pl.Date)).alias("effective_end"),
        )
        .filter(pl.col("effective_end") >= pl.col("effective_start"))
        .with_columns(
            pl.date_ranges("effective_start", "effective_end", interval="1d", closed="both").alias("datum")
        )
        .explode("datum")
        .drop(["datum_start", "datum_end", "effective_start", "effective_end"])
    )

    df_opt = (
        df_daily.group_by(["datum", "asset_rollup"])
        .agg(
            pl.when(pl.col("cum_qty") == 0).then(pl.col("cum_eur")).otherwise(0.0).sum().alias("hist_premie_v2"),
            pl.when(pl.col("cum_qty") != 0).then(pl.col("cum_eur")).otherwise(0.0).sum().alias("open_premie_v2"),
            pl.when(
                (pl.col("cum_qty") == 0)
                | (
                    pl.col("optie_exp_date").is_not_null()
                    & (pl.col("optie_exp_date") < pl.col("datum"))
                )
            )
            .then(pl.col("cum_eur"))
            .otherwise(0.0)
            .sum()
            .alias("gesloten_opties"),
            pl.when(pl.col("cum_qty") == 0).then(pl.col("cum_fee")).otherwise(0.0).sum().alias("optie_fee_closed_v2"),
            pl.when(pl.col("cum_qty") != 0).then(pl.col("cum_fee")).otherwise(0.0).sum().alias("optie_fee_open_v2"),
        )
        .join(df_itm, on=["datum", "asset_rollup"], how="left")
        .with_columns(pl.col("open_itm").fill_null(0.0))
        .with_columns(
            (
                pl.col("hist_premie_v2") + pl.col("open_premie_v2") + pl.col("open_itm")
            ).alias("optie_resultaat_v2"),
            (
                pl.col("optie_fee_closed_v2") + pl.col("optie_fee_open_v2")
            ).alias("optie_fee_v2"),
        )
        .select(["datum", "asset_rollup", "optie_resultaat_v2", "gesloten_opties", "optie_fee_v2"])
    )
    return df_opt


def load_sprinters_component(conn, scope: RebuildScope) -> pl.DataFrame:
    asset_filter, asset_params = _asset_filter_sql(scope)
    sql = f"""
        SELECT
            datum,
            asset_rollup,
            SUM(sprinter_resultaat) AS sprinter_resultaat_v2,
            SUM(IIF(transactie_aantal = 0, transactie_euro_totaal, 0)) AS gesloten_sprinters,
            SUM(transactie_fee) AS sprinter_fee_v2
        FROM per_dag_open_sprinters_opgerold_v2
        WHERE datum >= ? AND datum <= ?
        {asset_filter}
        GROUP BY datum, asset_rollup
    """
    params = [scope.from_date, scope.to_date, *asset_params]
    return pl.read_database(sql, conn, execute_options={"parameters": params}).with_columns(
        pl.col("datum").cast(pl.Date),
        pl.col("asset_rollup").cast(pl.Utf8).str.strip_chars(),
        pl.col("sprinter_resultaat_v2").fill_null(0.0),
        pl.col("gesloten_sprinters").fill_null(0.0),
        pl.col("sprinter_fee_v2").fill_null(0.0),
    )


def load_dividend_component(conn, scope: RebuildScope) -> pl.DataFrame:
    if scope.assets:
        placeholders_assets = ",".join("?" for _ in scope.assets)
        asset_filter = f" AND f.asset IN ({placeholders_assets})"
        asset_params = list(scope.assets)
    else:
        asset_filter = ""
        asset_params = []
    fee_types_placeholders = ",".join("?" for _ in DIVIDEND_FEE_TYPES)
    sql = f"""
        SELECT f.datum, f.asset AS asset_rollup, f.fee_type, SUM(f.amount) AS amount
        FROM fees_dividend AS f
        WHERE f.fee_type IN ({fee_types_placeholders})
          AND f.datum <= ?
          {asset_filter}
        GROUP BY f.datum, f.asset, f.fee_type
        ORDER BY f.asset, f.fee_type, f.datum
    """
    params = [*DIVIDEND_FEE_TYPES, scope.to_date, *asset_params]
    df = pl.read_database(sql, conn, execute_options={"parameters": params})
    if df.is_empty():
        return pl.DataFrame(
            schema={
                "datum": pl.Date,
                "asset_rollup": pl.Utf8,
                "dividend_v2": pl.Float64,
                "dividend_belasting_v2": pl.Float64,
                "fees_dividend_belasting_v2": pl.Float64,
            }
        )

    df = (
        df.with_columns(
            pl.col("datum").cast(pl.Date),
            pl.col("asset_rollup").cast(pl.Utf8).str.strip_chars(),
            pl.col("fee_type").cast(pl.Utf8).str.strip_chars(),
            pl.col("amount").fill_null(0.0),
        )
        .sort(["asset_rollup", "fee_type", "datum"])
        .with_columns(
            pl.col("amount").cum_sum().over(["asset_rollup", "fee_type"]).alias("cum_amount")
        )
        .pivot(
            values="cum_amount",
            index=["datum", "asset_rollup"],
            columns="fee_type",
            aggregate_function="max",
        )
        .pipe(_ensure_columns, ["dividend", "div_belasting", "871_fee", "transactiebelasting"])
        .with_columns(
            pl.col("dividend").fill_null(0.0).alias("dividend_v2"),
            pl.col("div_belasting").fill_null(0.0).alias("dividend_belasting_v2"),
            (
                pl.col("dividend").fill_null(0.0)
                + pl.col("div_belasting").fill_null(0.0)
                + pl.col("871_fee").fill_null(0.0)
                + pl.col("transactiebelasting").fill_null(0.0)
            ).alias("fees_dividend_belasting_v2"),
        )
        .select(["datum", "asset_rollup", "dividend_v2", "dividend_belasting_v2", "fees_dividend_belasting_v2"])
    )

    if scope.from_date > date(1900, 1, 1):
        # Incremental: add baseline cumulative value from day before from_date.
        baseline_cutoff = scope.from_date - timedelta(days=1)
        sql_base = f"""
            SELECT f.asset AS asset_rollup, f.fee_type, SUM(f.amount) AS base_amount
            FROM fees_dividend AS f
            WHERE f.fee_type IN ({fee_types_placeholders})
              AND f.datum <= ?
              {asset_filter}
            GROUP BY f.asset, f.fee_type
        """
        params_base = [*DIVIDEND_FEE_TYPES, baseline_cutoff, *asset_params]
        base = pl.read_database(sql_base, conn, execute_options={"parameters": params_base})
        if not base.is_empty():
            base = base.with_columns(
                pl.col("asset_rollup").cast(pl.Utf8).str.strip_chars(),
                pl.col("fee_type").cast(pl.Utf8).str.strip_chars(),
                pl.col("base_amount").fill_null(0.0),
            )
            base = (
                base.pivot(
                    values="base_amount",
                    index=["asset_rollup"],
                    columns="fee_type",
                    aggregate_function="sum",
                )
                .pipe(_ensure_columns, ["dividend", "div_belasting", "871_fee", "transactiebelasting"])
                .with_columns(
                    pl.col("dividend").fill_null(0.0).alias("base_dividend_v2"),
                    pl.col("div_belasting").fill_null(0.0).alias("base_dividend_belasting_v2"),
                    (
                        pl.col("dividend").fill_null(0.0)
                        + pl.col("div_belasting").fill_null(0.0)
                        + pl.col("871_fee").fill_null(0.0)
                        + pl.col("transactiebelasting").fill_null(0.0)
                    ).alias("base_fees_dividend_belasting_v2"),
                )
                .select(["asset_rollup", "base_dividend_v2", "base_dividend_belasting_v2", "base_fees_dividend_belasting_v2"])
            )
            df = (
                df.join(base, on="asset_rollup", how="left")
                .with_columns(
                    pl.col("base_dividend_v2").fill_null(0.0),
                    pl.col("base_dividend_belasting_v2").fill_null(0.0),
                    pl.col("base_fees_dividend_belasting_v2").fill_null(0.0),
                )
                .with_columns(
                    (pl.col("dividend_v2") + pl.col("base_dividend_v2")).alias("dividend_v2"),
                    (pl.col("dividend_belasting_v2") + pl.col("base_dividend_belasting_v2")).alias("dividend_belasting_v2"),
                    (pl.col("fees_dividend_belasting_v2") + pl.col("base_fees_dividend_belasting_v2")).alias("fees_dividend_belasting_v2"),
                )
                .drop(["base_dividend_v2", "base_dividend_belasting_v2", "base_fees_dividend_belasting_v2"])
            )

    df = df.filter(pl.col("datum") >= pl.lit(scope.from_date, dtype=pl.Date))

    # Carry-forward cumulatieve dividend-standen naar alle dagen in de scope.
    # Zonder dit staan alleen event-dagen gevuld en worden tussenliggende dagen 0.
    if df.is_empty():
        return df

    assets_df = df.select("asset_rollup").unique()
    calendar_df = pl.DataFrame(
        {
            "datum": pl.date_range(
                scope.from_date,
                scope.to_date,
                interval="1d",
                eager=True,
            )
        }
    )
    grid = assets_df.join(calendar_df, how="cross").sort(["asset_rollup", "datum"])
    events = df.sort(["asset_rollup", "datum"])
    dense = (
        grid.join_asof(events, on="datum", by="asset_rollup", strategy="backward")
        .with_columns(
            pl.col("dividend_v2").fill_null(0.0),
            pl.col("dividend_belasting_v2").fill_null(0.0),
            pl.col("fees_dividend_belasting_v2").fill_null(0.0),
        )
        .select(["datum", "asset_rollup", "dividend_v2", "dividend_belasting_v2", "fees_dividend_belasting_v2"])
    )
    return dense


def build_final(df_a: pl.DataFrame, df_o: pl.DataFrame, df_s: pl.DataFrame, df_d: pl.DataFrame) -> pl.DataFrame:
    frames = [x for x in [df_a, df_o, df_s, df_d] if not x.is_empty()]
    if not frames:
        return pl.DataFrame()
    keys = pl.concat([f.select(["datum", "asset_rollup"]) for f in frames], how="vertical").unique()

    df = (
        keys.join(df_a, on=["datum", "asset_rollup"], how="left")
        .join(df_o, on=["datum", "asset_rollup"], how="left")
        .join(df_s, on=["datum", "asset_rollup"], how="left")
        .join(df_d, on=["datum", "asset_rollup"], how="left")
        .with_columns(
            pl.col("aandelen_resultaat_v2").fill_null(0.0),
            pl.col("asset_fee_v2").fill_null(0.0),
            pl.col("optie_resultaat_v2").fill_null(0.0),
            pl.col("gesloten_opties").fill_null(0.0),
            pl.col("optie_fee_v2").fill_null(0.0),
            pl.col("sprinter_resultaat_v2").fill_null(0.0),
            pl.col("gesloten_sprinters").fill_null(0.0),
            pl.col("sprinter_fee_v2").fill_null(0.0),
            pl.col("dividend_v2").fill_null(0.0),
            pl.col("dividend_belasting_v2").fill_null(0.0),
            pl.col("fees_dividend_belasting_v2").fill_null(0.0),
        )
        .with_columns(
            (
                pl.col("aandelen_resultaat_v2")
                + pl.col("asset_fee_v2")
                + pl.col("optie_resultaat_v2")
                + pl.col("optie_fee_v2")
                + pl.col("sprinter_resultaat_v2")
                + pl.col("sprinter_fee_v2")
                + pl.col("fees_dividend_belasting_v2")
            ).alias("totaal_v2"),
            pl.lit(datetime.now()).alias("updated_at"),
        )
        .sort(["datum", "asset_rollup"])
    )
    return normalize_numeric_columns(df, PRECISION_MAP)


def delete_target_range(conn, scope: RebuildScope) -> None:
    def _to_access_date_literal(d: date) -> str:
        return f"#{d.month}/{d.day}/{d.year}#"

    cursor = conn.cursor()
    if scope.assets is None:
        cursor.execute("DELETE FROM per_dag_asset_result_v2")
        conn.commit()
        return

    batch_days = 30
    for asset in scope.assets:
        batch_start = scope.from_date
        while batch_start <= scope.to_date:
            batch_end = min(batch_start + timedelta(days=batch_days - 1), scope.to_date)
            sql = (
                "DELETE FROM per_dag_asset_result_v2 "
                "WHERE asset_rollup = ? "
                f"AND datum >= {_to_access_date_literal(batch_start)} "
                f"AND datum <= {_to_access_date_literal(batch_end)}"
            )
            cursor.execute(sql, asset)
            conn.commit()
            batch_start = batch_end + timedelta(days=1)


def drop_temp_stage_table(conn, table_name: str) -> None:
    cursor = conn.cursor()
    try:
        cursor.execute(f"DROP TABLE [{table_name}]")
        conn.commit()
    except Exception:
        conn.rollback()


def drop_stale_temp_stage_tables(conn) -> None:
    cursor = conn.cursor()
    stale_names: list[str] = []
    for row in cursor.tables(tableType="TABLE"):
        table_name = row.table_name
        if table_name and str(table_name).startswith(TEMP_STAGE_TABLE_PREFIX):
            stale_names.append(str(table_name))
    for table_name in stale_names:
        try:
            cursor.execute(f"DROP TABLE [{table_name}]")
            conn.commit()
        except Exception:
            conn.rollback()


def create_temp_stage_table(conn, table_name: str) -> None:
    drop_temp_stage_table(conn, table_name)
    cur = conn.cursor()
    cur.execute(
        f"""
        CREATE TABLE [{table_name}] (
            datum DATETIME,
            asset_rollup TEXT(20),
            aandelen_resultaat_v2 CURRENCY,
            asset_fee_v2 CURRENCY,
            optie_resultaat_v2 CURRENCY,
            gesloten_opties CURRENCY,
            optie_fee_v2 CURRENCY,
            sprinter_resultaat_v2 CURRENCY,
            gesloten_sprinters CURRENCY,
            sprinter_fee_v2 CURRENCY,
            dividend_v2 CURRENCY,
            dividend_belasting_v2 CURRENCY,
            fees_dividend_belasting_v2 CURRENCY,
            totaal_v2 CURRENCY,
            updated_at DATETIME
        )
        """
    )
    conn.commit()


def insert_rows(conn, df_final: pl.DataFrame, run_options: RunOptions) -> None:
    if df_final.is_empty():
        print("Geen rijen om te inserten.")
        return

    insert_cols = [
        "datum",
        "asset_rollup",
        "aandelen_resultaat_v2",
        "asset_fee_v2",
        "optie_resultaat_v2",
        "gesloten_opties",
        "optie_fee_v2",
        "sprinter_resultaat_v2",
        "gesloten_sprinters",
        "sprinter_fee_v2",
        "dividend_v2",
        "dividend_belasting_v2",
        "fees_dividend_belasting_v2",
        "totaal_v2",
        "updated_at",
    ]
    rows = df_final.select(insert_cols).rows()
    placeholders = ",".join(["?"] * len(insert_cols))
    query = f"INSERT INTO per_dag_asset_result_v2 ({','.join(insert_cols)}) VALUES ({placeholders})"
    cur = conn.cursor()
    if run_options.insert_mode == "temp_table":
        stage_table = run_options.temp_table_name
        try:
            create_temp_stage_table(conn, stage_table)
            stage_query = f"INSERT INTO [{stage_table}] ({','.join(insert_cols)}) VALUES ({placeholders})"
            cur.executemany(stage_query, rows)
            conn.commit()
            cur.execute(
                f"""
                INSERT INTO per_dag_asset_result_v2 ({','.join(insert_cols)})
                SELECT {','.join(insert_cols)}
                FROM [{stage_table}]
                """
            )
            conn.commit()
        except pyodbc.Error as exc:
            print(f"[warn] temp_table insert fallback naar executemany door Access lock/DDL error: {exc}")
            conn.rollback()
            cur.executemany(query, rows)
            conn.commit()
        finally:
            drop_temp_stage_table(conn, stage_table)
        return

    cur.executemany(query, rows)
    conn.commit()


def update_state_engine_status(conn, scope: RebuildScope, df_final: pl.DataFrame) -> None:
    if df_final.is_empty():
        return
    assets = sorted({str(x).strip() for x in df_final.select("asset_rollup").unique().to_series().to_list() if x is not None and str(x).strip()})
    if not assets:
        return
    run_at = datetime.now()
    cur = conn.cursor()
    for asset in assets:
        cur.execute("DELETE FROM state_engine_status WHERE engine_name=? AND asset_rollup=?", "asset_result_v2", asset)
        cur.execute(
            """
            INSERT INTO state_engine_status
                (engine_name, asset_class, asset_rollup, last_rebuilt_through_date, last_price_date_used, last_run_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            "asset_result_v2",
            "portfolio",
            asset,
            scope.to_date,
            scope.to_date,
            run_at,
            "ok",
        )
    conn.commit()


def main() -> None:
    args = parse_args()
    run_options = RunOptions(
        insert_mode=args.insert_mode,
        temp_table_name=f"{TEMP_STAGE_TABLE_PREFIX}_{uuid4().hex[:8]}",
    )
    overall_start = perf_counter()
    timer = PhaseTimer()
    with get_connection(args.db) as conn:
        drop_stale_temp_stage_tables(conn)
        scope = resolve_scope(args, conn)
        print(f"Scope mode={scope.mode} assets={scope.assets or 'ALL'} from={scope.from_date} to={scope.to_date}")
        timer.mark("resolve_scope")

        df_a = load_aandelen_component(conn, scope)
        timer.mark(f"load_aandelen_component ({df_a.height} rows)")
        df_o = load_opties_component(conn, scope)
        timer.mark(f"load_opties_component ({df_o.height} rows)")
        df_s = load_sprinters_component(conn, scope)
        timer.mark(f"load_sprinters_component ({df_s.height} rows)")
        df_d = load_dividend_component(conn, scope)
        timer.mark(f"load_dividend_component ({df_d.height} rows)")

        df_final = build_final(df_a, df_o, df_s, df_d)
        timer.mark(f"build_final ({df_final.height} rows)")
        if df_final.is_empty():
            delete_target_range(conn, scope)
            timer.mark("delete_target_range")
            print("Geen rows voor per_dag_asset_result_v2 in deze scope.")
            print(f"[timing] total: {perf_counter() - overall_start:.3f}s")
            return

        delete_target_range(conn, scope)
        timer.mark("delete_target_range")
        insert_rows(conn, df_final, run_options)
        timer.mark(f"insert_rows ({run_options.insert_mode})")
        update_state_engine_status(conn, scope, df_final)
        timer.mark("update_state_engine_status")
        print(f"Ingevoegd: {df_final.height} rijen")

    print(f"[timing] total: {perf_counter() - overall_start:.3f}s")


if __name__ == "__main__":
    main()
