from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import polars as pl

from common import (
    DEFAULT_DB_PATH,
    chunked,
    get_connection,
    normalize_numeric_columns,
    parse_iso_date,
    sql_date_literal,
)


PRECISION_MAP = {
    "transactie_aantal": 4,
    "optie_strike": 2,
    "optie_premie": 2,
    "optie_fee": 2,
    "asset_close_raw": 6,
    "asset_close_effective": 6,
    "price_factor_split": 6,
    "price_factor_override": 6,
    "price_factor_total": 6,
    "optie_waarde": 6,
    "open_optie_waarde_itm": 2,
    "winst_verlies": 2,
}


@dataclass
class RebuildScope:
    assets: list[str] | None
    from_date: date
    to_date: date
    mode: str


def parse_args():
    parser = argparse.ArgumentParser(description="Bouw per_dag_open_opties_opgerold_v2")
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--mode", choices=["full", "asset_incremental", "asset_split_rebuild"], default="full")
    parser.add_argument("--asset-rollups", help="Comma separated asset_rollup(s) for asset scoped rebuilds")
    parser.add_argument("--from-date", help="YYYY-MM-DD for incremental rebuild")
    parser.add_argument("--to-date", help="YYYY-MM-DD, default vandaag")
    parser.add_argument("--debug-uniek-id")
    parser.add_argument("--validate-v1", action="store_true")
    return parser.parse_args()


def fetch_min_transaction_date(conn, asset_rollup: str | None = None) -> date:
    cursor = conn.cursor()
    if asset_rollup:
        cursor.execute(
            "SELECT MIN(datum) FROM transacties_bron_data WHERE asset_type='optie' AND asset_rollup=?",
            asset_rollup,
        )
    else:
        cursor.execute("SELECT MIN(datum) FROM transacties_bron_data WHERE asset_type='optie'")
    result = cursor.fetchone()[0]
    if result is None:
        raise RuntimeError("Geen optie transacties gevonden.")
    return result.date() if isinstance(result, datetime) else result


def resolve_scope(args, conn) -> RebuildScope:
    today = parse_iso_date(args.to_date) or date.today()
    if args.mode == "full":
        return RebuildScope(
            assets=None,
            from_date=fetch_min_transaction_date(conn),
            to_date=today,
            mode=args.mode,
        )

    if not args.asset_rollups:
        raise ValueError("--asset-rollups is verplicht voor asset scoped rebuilds")
    assets = [x.strip() for x in args.asset_rollups.split(",") if x.strip()]
    if not assets:
        raise ValueError("Geen geldige asset_rollups opgegeven")

    if args.mode == "asset_incremental":
        from_date = parse_iso_date(args.from_date)
        if not from_date:
            raise ValueError("--from-date is verplicht voor asset_incremental")
        return RebuildScope(assets=assets, from_date=from_date, to_date=today, mode=args.mode)

    first_dates = [fetch_min_transaction_date(conn, asset) for asset in assets]
    return RebuildScope(assets=assets, from_date=min(first_dates), to_date=today, mode=args.mode)


def load_option_transactions(conn, scope: RebuildScope) -> pl.DataFrame:
    sql = """
        SELECT
            Id,
            datum,
            broker,
            asset_rollup,
            uniek_id,
            optie_exp_date,
            optie_strike,
            optie_call_put,
            transactie_aantal,
            transactie_euro_totaal,
            transactie_fee
        FROM transacties_bron_data
        WHERE asset_type='optie'
          AND datum <= ?
    """
    params: list = [scope.to_date]
    if scope.assets:
        placeholders = ",".join("?" for _ in scope.assets)
        sql += f" AND asset_rollup IN ({placeholders})"
        params.extend(scope.assets)
    sql += " ORDER BY uniek_id, datum, Id"
    return pl.read_database(sql, conn, execute_options={"parameters": params})


def load_price_history(conn, scope: RebuildScope) -> pl.DataFrame:
    sql = """
        SELECT asset_rollup, datum, close
        FROM hist_data_per_asset_symbol
        WHERE datum >= ? AND datum <= ?
    """
    params: list = [scope.from_date - timedelta(days=10), scope.to_date]
    if scope.assets:
        placeholders = ",".join("?" for _ in scope.assets)
        sql += f" AND asset_rollup IN ({placeholders})"
        params.extend(scope.assets)
    sql += " ORDER BY asset_rollup, datum"
    return (
        pl.read_database(sql, conn, execute_options={"parameters": params})
        .with_columns(pl.col("datum").cast(pl.Date))
        .rename({"close": "asset_close_raw"})
    )


def load_stock_splits(conn, scope: RebuildScope) -> pl.DataFrame:
    # split_factor is the valuation correction factor for asset_close_raw.
    # It is not the legal split ratio text. Examples:
    # - normal split 1 -> 10  => factor 10.0
    # - reverse split 1-for-5 => factor 0.2
    sql = """
        SELECT Id, asset_rollup, split_date, split_factor, split_type
        FROM stock_splits
        WHERE active = True
          AND split_date <= ?
    """
    params: list = [scope.to_date]
    if scope.assets:
        placeholders = ",".join("?" for _ in scope.assets)
        sql += f" AND asset_rollup IN ({placeholders})"
        params.extend(scope.assets)
    sql += " ORDER BY asset_rollup, split_date"
    return pl.read_database(sql, conn, execute_options={"parameters": params})


def load_option_price_factor_overrides(conn) -> pl.DataFrame:
    sql = """
        SELECT Id, uniek_id, effective_from_date, effective_to_date, override_factor, override_type, reason
        FROM option_price_factor_overrides
        WHERE active = True
        ORDER BY uniek_id, effective_from_date
    """
    return pl.read_database(sql, conn)


def build_open_series(df_tx: pl.DataFrame, scope: RebuildScope) -> pl.DataFrame:
    if df_tx.is_empty():
        return pl.DataFrame()

    grouped = (
        df_tx.with_columns(
            pl.col("datum").cast(pl.Date),
            pl.col("optie_exp_date").cast(pl.Date),
        )
        .group_by(["uniek_id", "datum"])
        .agg(
            [
                pl.col("Id").max().alias("last_tx_id"),
                pl.col("broker").last().alias("broker"),
                pl.col("asset_rollup").last().alias("asset_rollup"),
                pl.col("optie_exp_date").last().alias("optie_exp_date"),
                pl.col("optie_strike").last().alias("optie_strike"),
                pl.col("optie_call_put").last().alias("optie_call_put"),
                pl.col("transactie_aantal").sum().alias("delta_aantal"),
                pl.col("transactie_euro_totaal").sum().alias("delta_premie"),
                pl.col("transactie_fee").sum().alias("delta_fee"),
            ]
        )
        .sort(["uniek_id", "datum", "last_tx_id"])
    )

    intervals: list[dict] = []
    for unique_df in grouped.partition_by("uniek_id", maintain_order=True):
        rows = unique_df.to_dicts()
        running_qty = 0.0
        running_premie = 0.0
        running_fee = 0.0
        for idx, row in enumerate(rows):
            running_qty += float(row["delta_aantal"] or 0.0)
            running_premie += float(row["delta_premie"] or 0.0)
            running_fee += float(row["delta_fee"] or 0.0)
            if abs(running_qty) < 1e-12:
                running_qty = 0.0
                running_premie = 0.0
                running_fee = 0.0
                continue

            start_date = row["datum"]
            next_event_date = rows[idx + 1]["datum"] if idx + 1 < len(rows) else None
            end_date = scope.to_date if next_event_date is None else min(scope.to_date, next_event_date - timedelta(days=1))
            expiry = row["optie_exp_date"]
            if expiry:
                end_date = min(end_date, expiry)
            if end_date < start_date:
                continue
            if end_date < scope.from_date:
                continue
            intervals.append(
                {
                    "uniek_id": row["uniek_id"],
                    "broker": row["broker"],
                    "asset_rollup": row["asset_rollup"],
                    "optie_exp_date": expiry,
                    "optie_strike": row["optie_strike"],
                    "optie_call_put": row["optie_call_put"],
                    "series_open_date": start_date,
                    "interval_start": start_date,
                    "interval_end": end_date,
                    "transactie_aantal": running_qty,
                    "optie_premie": running_premie,
                    "optie_fee": running_fee,
                }
            )
    return pl.DataFrame(intervals) if intervals else pl.DataFrame()


def materialize_daily_open_rows(df_series: pl.DataFrame, scope: RebuildScope) -> pl.DataFrame:
    if df_series.is_empty():
        return pl.DataFrame()

    rows: list[dict] = []
    for item in df_series.to_dicts():
        start = max(item["interval_start"], scope.from_date)
        end = min(item["interval_end"], scope.to_date)
        current = start
        while current <= end:
            out = dict(item)
            out["datum"] = current
            rows.append(out)
            current += timedelta(days=1)
    if not rows:
        return pl.DataFrame()
    return pl.DataFrame(rows).drop(["interval_start", "interval_end"])


def attach_raw_prices(df_daily: pl.DataFrame, df_prices: pl.DataFrame) -> pl.DataFrame:
    if df_daily.is_empty():
        return df_daily
    return (
        df_daily.sort(["asset_rollup", "datum"])
        .join_asof(
            df_prices.sort(["asset_rollup", "datum"]),
            on="datum",
            by="asset_rollup",
            strategy="backward",
        )
    )


def compute_split_factor(df_daily: pl.DataFrame, df_splits: pl.DataFrame) -> pl.DataFrame:
    if df_daily.is_empty():
        return df_daily

    split_map: dict[str, list[dict]] = {}
    for row in df_splits.to_dicts():
        split_map.setdefault(row["asset_rollup"], []).append(row)

    factors = []
    for row in df_daily.to_dicts():
        factor = 1.0
        for split in split_map.get(row["asset_rollup"], []):
            split_date = split["split_date"]
            if isinstance(split_date, datetime):
                split_date = split_date.date()
            # IBKR historical prices are back-adjusted after a split.
            # For series opened before a later split, the factor must correct
            # the whole life of that old series, not only dates after split_date.
            if split_date > row["series_open_date"]:
                factor *= float(split["split_factor"] or 1.0)
        factors.append(factor)
    return df_daily.with_columns(pl.Series("price_factor_split", factors))


def attach_override_factor(df_daily: pl.DataFrame, df_overrides: pl.DataFrame) -> pl.DataFrame:
    if df_daily.is_empty():
        return df_daily

    override_map: dict[str, list[dict]] = {}
    for row in df_overrides.to_dicts():
        override_map.setdefault(row["uniek_id"], []).append(row)

    override_factors = []
    rule_types = []
    rule_ids = []
    for row in df_daily.to_dicts():
        factor = 1.0
        rule_type = "split_only"
        rule_id = None
        for override in override_map.get(row["uniek_id"], []):
            start = override["effective_from_date"]
            end = override["effective_to_date"]
            if isinstance(start, datetime):
                start = start.date()
            if isinstance(end, datetime):
                end = end.date()
            if start <= row["datum"] and (end is None or end >= row["datum"]):
                factor = float(override["override_factor"] or 1.0)
                rule_type = override.get("override_type") or "override_only"
                rule_id = override.get("Id")
                break
        override_factors.append(factor)
        rule_types.append(rule_type)
        rule_ids.append(rule_id)

    return df_daily.with_columns(
        pl.Series("price_factor_override", override_factors),
        pl.Series("valuation_rule_type", rule_types),
        pl.Series("valuation_rule_id", rule_ids),
    )


def compute_effective_prices_and_valuation(df_daily: pl.DataFrame) -> pl.DataFrame:
    if df_daily.is_empty():
        return df_daily

    return (
        df_daily.with_columns(
            (pl.col("price_factor_split") * pl.col("price_factor_override")).alias("price_factor_total"),
        )
        .with_columns(
            (pl.col("asset_close_raw") * pl.col("price_factor_total")).alias("asset_close_effective"),
        )
        .with_columns(
            pl.when(
                (pl.col("optie_call_put") == "call") & (pl.col("asset_close_effective") > pl.col("optie_strike"))
            )
            .then(1)
            .when(
                (pl.col("optie_call_put") == "put") & (pl.col("asset_close_effective") < pl.col("optie_strike"))
            )
            .then(1)
            .otherwise(0)
            .alias("itm_otm"),
            pl.when(pl.col("optie_call_put") == "call")
            .then((pl.col("asset_close_effective") - pl.col("optie_strike")).clip(lower_bound=0))
            .otherwise((pl.col("optie_strike") - pl.col("asset_close_effective")).clip(lower_bound=0))
            .alias("optie_waarde"),
        )
        .with_columns(
            (pl.col("optie_waarde") * pl.col("transactie_aantal")).alias("open_optie_waarde_itm"),
            (pl.col("optie_premie") + pl.col("optie_waarde") * pl.col("transactie_aantal")).alias("winst_verlies"),
            pl.lit("intrinsic_only").alias("valuation_method"),
            pl.lit(datetime.now()).alias("updated_at"),
        )
    )


def normalize_for_access(df: pl.DataFrame) -> pl.DataFrame:
    if df.is_empty():
        return df
    return normalize_numeric_columns(df, PRECISION_MAP)


def delete_target_range(conn, scope: RebuildScope) -> None:
    cursor = conn.cursor()
    if scope.assets is None:
        cursor.execute("DELETE FROM per_dag_open_opties_opgerold_v2")
        conn.commit()
        return
    for asset in scope.assets:
        cursor.execute(
            "DELETE FROM per_dag_open_opties_opgerold_v2 WHERE asset_rollup = ? AND datum >= ?",
            asset,
            scope.from_date,
        )
    conn.commit()


def insert_v2_rows(conn, df_final: pl.DataFrame) -> None:
    if df_final.is_empty():
        print("Geen rijen om te inserten.")
        return

    insert_cols = [
        "datum",
        "broker",
        "asset_rollup",
        "uniek_id",
        "optie_exp_date",
        "optie_strike",
        "optie_call_put",
        "transactie_aantal",
        "optie_premie",
        "optie_fee",
        "asset_close_raw",
        "asset_close_effective",
        "itm_otm",
        "optie_waarde",
        "open_optie_waarde_itm",
        "winst_verlies",
        "price_factor_split",
        "price_factor_override",
        "price_factor_total",
        "valuation_rule_type",
        "valuation_rule_id",
        "valuation_method",
        "updated_at",
    ]
    df_final = df_final.select(insert_cols)
    rows = [tuple(row) for row in df_final.iter_rows()]
    placeholders = ",".join(["?"] * len(insert_cols))
    query = f"INSERT INTO per_dag_open_opties_opgerold_v2 ({','.join(insert_cols)}) VALUES ({placeholders})"
    cursor = conn.cursor()
    for group in chunked(rows, 1000):
        cursor.executemany(query, group)
    conn.commit()


def maybe_validate_v1(conn, scope: RebuildScope) -> None:
    cursor = conn.cursor()
    if scope.assets is None:
        cursor.execute(
            "SELECT COUNT(*) FROM per_dag_open_opties_opgerold WHERE datum >= ? AND datum <= ?",
            scope.from_date,
            scope.to_date,
        )
        old_count = cursor.fetchone()[0]
        cursor.execute(
            "SELECT COUNT(*) FROM per_dag_open_opties_opgerold_v2 WHERE datum >= ? AND datum <= ?",
            scope.from_date,
            scope.to_date,
        )
        new_count = cursor.fetchone()[0]
    else:
        old_count = 0
        new_count = 0
        for asset in scope.assets:
            cursor.execute(
                "SELECT COUNT(*) FROM per_dag_open_opties_opgerold WHERE asset_rollup=? AND datum >= ? AND datum <= ?",
                asset,
                scope.from_date,
                scope.to_date,
            )
            old_count += cursor.fetchone()[0]
            cursor.execute(
                "SELECT COUNT(*) FROM per_dag_open_opties_opgerold_v2 WHERE asset_rollup=? AND datum >= ? AND datum <= ?",
                asset,
                scope.from_date,
                scope.to_date,
            )
            new_count += cursor.fetchone()[0]
    print(f"Validatie count v1={old_count}, v2={new_count}")


def debug_uniek_id(df_final: pl.DataFrame, uniek_id: str) -> None:
    if df_final.is_empty():
        print("Geen data beschikbaar voor debug.")
        return
    debug_df = df_final.filter(pl.col("uniek_id") == uniek_id).sort("datum")
    if debug_df.is_empty():
        print(f"Geen rijen gevonden voor {uniek_id}")
        return
    print(debug_df)


def main() -> None:
    args = parse_args()
    with get_connection(args.db) as conn:
        scope = resolve_scope(args, conn)
        print(f"Scope mode={scope.mode} assets={scope.assets or 'ALL'} from={scope.from_date} to={scope.to_date}")
        df_tx = load_option_transactions(conn, scope)
        df_series = build_open_series(df_tx, scope)
        df_daily = materialize_daily_open_rows(df_series, scope)
        if df_daily.is_empty():
            print("Geen open opties gevonden voor deze scope.")
            return
        df_prices = load_price_history(conn, scope)
        df_splits = load_stock_splits(conn, scope)
        df_overrides = load_option_price_factor_overrides(conn)
        df_daily = attach_raw_prices(df_daily, df_prices)
        df_daily = compute_split_factor(df_daily, df_splits)
        df_daily = attach_override_factor(df_daily, df_overrides)
        df_final = compute_effective_prices_and_valuation(df_daily)
        df_final = normalize_for_access(df_final)
        if args.debug_uniek_id:
            debug_uniek_id(df_final, args.debug_uniek_id)
        delete_target_range(conn, scope)
        insert_v2_rows(conn, df_final)
        print(f"Ingevoegd: {df_final.height} rijen")
        if args.validate_v1:
            maybe_validate_v1(conn, scope)


if __name__ == "__main__":
    main()
