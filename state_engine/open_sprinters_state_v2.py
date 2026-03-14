from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from time import perf_counter
from uuid import uuid4

import polars as pl
import pyodbc

from common import DEFAULT_DB_PATH, get_connection, normalize_numeric_columns, parse_iso_date


PRECISION_MAP = {
    "transactie_aantal": 4,
    "transactie_euro_totaal": 2,
    "transactie_fee": 2,
    "multiplier_close_price": 6,
    "sprinter_ratio": 6,
    "sprinter_funding": 6,
    "asset_close_effective": 6,
    "sprinter_resultaat": 2,
    "sprinter_aantal_bezit": 4,
}

TEMP_STAGE_TABLE_PREFIX = "TempSprintersStateV2Stage"


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
    parser = argparse.ArgumentParser(description="Bouw per_dag_open_sprinters_opgerold_v2")
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--mode", choices=["full", "asset_incremental", "asset_split_rebuild"], default="full")
    parser.add_argument("--asset-rollups", help="Comma separated asset_rollup(s) for asset scoped rebuilds")
    parser.add_argument("--from-date", help="YYYY-MM-DD for incremental rebuild")
    parser.add_argument("--to-date", help="YYYY-MM-DD, default vandaag")
    parser.add_argument(
        "--insert-mode",
        choices=["temp_table", "executemany"],
        default="temp_table",
    )
    return parser.parse_args()


def fetch_min_transaction_date(conn, asset_rollup: str | None = None) -> date | None:
    cursor = conn.cursor()
    if asset_rollup:
        cursor.execute(
            "SELECT MIN(datum) FROM transacties_bron_data WHERE asset_type='sprinter' AND asset_rollup=?",
            asset_rollup,
        )
    else:
        cursor.execute("SELECT MIN(datum) FROM transacties_bron_data WHERE asset_type='sprinter'")
    result = cursor.fetchone()[0]
    if result is None:
        return None
    return result.date() if isinstance(result, datetime) else result


def resolve_scope(args, conn) -> RebuildScope:
    today = parse_iso_date(args.to_date) or date.today()
    if args.mode == "full":
        min_date = fetch_min_transaction_date(conn)
        return RebuildScope(
            assets=None,
            from_date=min_date or today,
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

    first_dates = [d for d in (fetch_min_transaction_date(conn, asset) for asset in assets) if d is not None]
    if not first_dates:
        return RebuildScope(assets=assets, from_date=today, to_date=today, mode=args.mode)
    return RebuildScope(assets=assets, from_date=min(first_dates), to_date=today, mode=args.mode)


def load_sprinter_transactions(conn, scope: RebuildScope) -> pl.DataFrame:
    sql = """
        SELECT
            Id,
            datum,
            broker,
            asset_rollup,
            uniek_id,
            asset_detail,
            transactie_aantal,
            transactie_euro_totaal,
            transactie_fee,
            multiplier_close_price
        FROM transacties_bron_data
        WHERE asset_type='sprinter'
          AND datum <= ?
    """
    params: list = [scope.to_date]
    if scope.assets:
        placeholders = ",".join("?" for _ in scope.assets)
        sql += f" AND asset_rollup IN ({placeholders})"
        params.extend(scope.assets)
    sql += " ORDER BY asset_rollup, broker, uniek_id, datum, Id"
    return (
        pl.read_database(sql, conn, execute_options={"parameters": params})
        .with_columns(
            [
                pl.col("datum").cast(pl.Date),
                pl.col("asset_rollup").cast(pl.Utf8).str.strip_chars(),
                pl.col("broker").cast(pl.Utf8).str.strip_chars(),
                pl.col("uniek_id").cast(pl.Utf8).str.strip_chars(),
                pl.col("asset_detail").cast(pl.Utf8).str.strip_chars(),
                pl.col("multiplier_close_price").fill_null(1.0),
            ]
        )
    )


def load_sprinter_reference(conn) -> pl.DataFrame:
    sql = """
        SELECT
            asset_detail,
            sprinter_funding,
            sprinter_ratio
        FROM sprinters_referentie_data
    """
    return (
        pl.read_database(sql, conn)
        .with_columns(
            pl.col("asset_detail").cast(pl.Utf8).str.strip_chars(),
            pl.col("sprinter_funding").fill_null(0.0),
            pl.col("sprinter_ratio").fill_null(1.0),
        )
        .select(["asset_detail", "sprinter_funding", "sprinter_ratio"])
        .unique(subset=["asset_detail"])
    )


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


def build_state_intervals(df_tx: pl.DataFrame, scope: RebuildScope) -> pl.DataFrame:
    if df_tx.is_empty():
        return pl.DataFrame()

    intervals: list[dict] = []
    for bucket_df in df_tx.partition_by(["asset_rollup", "broker", "uniek_id"], maintain_order=True):
        rows = bucket_df.to_dicts()
        asset = str(rows[0]["asset_rollup"]).strip()
        broker = str(rows[0]["broker"]).strip()
        uniek_id = str(rows[0]["uniek_id"]).strip()

        by_date: dict[date, list[dict]] = {}
        for row in rows:
            datum = row["datum"]
            if isinstance(datum, datetime):
                datum = datum.date()
            row["datum"] = datum
            by_date.setdefault(datum, []).append(row)

        event_dates = sorted(by_date.keys())

        tx_qty_cum = 0.0
        tx_eur_cum = 0.0
        tx_fee_cum = 0.0
        multiplier = 1.0
        asset_detail = str(rows[0].get("asset_detail") or "").strip()

        for idx, event_date in enumerate(event_dates):
            day_rows = by_date.get(event_date, [])
            day_qty = 0.0
            day_eur = 0.0
            day_fee = 0.0
            for row in sorted(day_rows, key=lambda r: r["Id"]):
                day_qty += float(row.get("transactie_aantal") or 0.0)
                day_eur += float(row.get("transactie_euro_totaal") or 0.0)
                day_fee += float(row.get("transactie_fee") or 0.0)
                multiplier = float(row.get("multiplier_close_price") or multiplier or 1.0)
                if str(row.get("asset_detail") or "").strip():
                    asset_detail = str(row.get("asset_detail") or "").strip()

            tx_qty_cum += day_qty
            tx_eur_cum += day_eur
            tx_fee_cum += day_fee

            # Open-sprinters tabel moet alleen echt open posities bevatten.
            # Zodra de serie sluit (qty ~ 0), resetten we cumulatieven en
            # schrijven we geen dagelijkse open-intervalregels meer weg.
            if abs(tx_qty_cum) < 1e-12:
                tx_qty_cum = 0.0
                tx_eur_cum = 0.0
                tx_fee_cum = 0.0
                continue

            next_event_date = event_dates[idx + 1] if idx + 1 < len(event_dates) else None
            interval_end = scope.to_date if next_event_date is None else min(scope.to_date, next_event_date - timedelta(days=1))
            if interval_end < event_date:
                continue
            intervals.append(
                {
                    "datum_start": event_date,
                    "datum_end": interval_end,
                    "asset_rollup": asset,
                    "broker": broker,
                    "uniek_id": uniek_id,
                    "asset_detail": asset_detail,
                    "transactie_aantal": tx_qty_cum,
                    "transactie_euro_totaal": tx_eur_cum,
                    "transactie_fee": tx_fee_cum,
                    "multiplier_close_price": multiplier,
                }
            )

    return pl.DataFrame(intervals) if intervals else pl.DataFrame()


def materialize_daily_rows(df_state_intervals: pl.DataFrame, scope: RebuildScope) -> pl.DataFrame:
    if df_state_intervals.is_empty():
        return pl.DataFrame()
    scope_start = pl.lit(scope.from_date, dtype=pl.Date)
    scope_end = pl.lit(scope.to_date, dtype=pl.Date)
    return (
        df_state_intervals.with_columns(
            pl.max_horizontal("datum_start", scope_start).alias("effective_start"),
            pl.min_horizontal("datum_end", scope_end).alias("effective_end"),
        )
        .filter(pl.col("effective_end") >= pl.col("effective_start"))
        .with_columns(
            pl.date_ranges(
                "effective_start",
                "effective_end",
                interval="1d",
                closed="both",
            ).alias("datum")
        )
        .explode("datum")
        .drop(["datum_start", "datum_end", "effective_start", "effective_end"])
    )


def attach_effective_close(df_daily: pl.DataFrame, df_prices: pl.DataFrame) -> pl.DataFrame:
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


def compute_sprinter_values(df_daily: pl.DataFrame, df_ref: pl.DataFrame) -> pl.DataFrame:
    if df_daily.is_empty():
        return df_daily
    df = (
        df_daily.join(df_ref, on="asset_detail", how="left")
        .with_columns(
            pl.col("sprinter_funding").fill_null(0.0),
            pl.col("sprinter_ratio").fill_null(1.0),
            pl.col("asset_close_raw").fill_null(0.0),
            pl.col("multiplier_close_price").fill_null(1.0),
        )
        .with_columns(
            (pl.col("asset_close_raw") * pl.col("multiplier_close_price")).alias("asset_close_effective")
        )
        .with_columns(
            pl.when(pl.col("sprinter_ratio") == 0.0).then(1.0).otherwise(pl.col("sprinter_ratio")).alias("sprinter_ratio")
        )
        .with_columns(
            (
                (pl.col("transactie_aantal") * pl.col("asset_close_effective")) / pl.col("sprinter_ratio")
                - (pl.col("transactie_aantal") * pl.col("sprinter_funding")) / pl.col("sprinter_ratio")
                + pl.col("transactie_euro_totaal")
            ).alias("sprinter_resultaat"),
            (pl.col("transactie_aantal") / pl.col("sprinter_ratio")).alias("sprinter_aantal_bezit"),
        )
    )
    return df


def normalize_for_access(df: pl.DataFrame) -> pl.DataFrame:
    if df.is_empty():
        return df
    return normalize_numeric_columns(df, PRECISION_MAP)


def delete_target_range(conn, scope: RebuildScope) -> None:
    def _to_access_date_literal(d: date) -> str:
        return f"#{d.month}/{d.day}/{d.year}#"

    cursor = conn.cursor()
    if scope.assets is None:
        # Vermijd Access MaxLocksPerFile door full-delete in dagbatches uit te voeren.
        batch_days = 30
        batch_start = scope.from_date
        while batch_start <= scope.to_date:
            batch_end = min(batch_start + timedelta(days=batch_days - 1), scope.to_date)
            sql = (
                "DELETE FROM per_dag_open_sprinters_opgerold_v2 "
                f"WHERE datum >= {_to_access_date_literal(batch_start)} "
                f"AND datum <= {_to_access_date_literal(batch_end)}"
            )
            cursor.execute(sql)
            conn.commit()
            batch_start = batch_end + timedelta(days=1)
        return

    batch_days = 30
    for asset in scope.assets:
        batch_start = scope.from_date
        while batch_start <= scope.to_date:
            batch_end = min(batch_start + timedelta(days=batch_days - 1), scope.to_date)
            sql = (
                "DELETE FROM per_dag_open_sprinters_opgerold_v2 "
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
    cursor = conn.cursor()
    cursor.execute(
        f"""
        CREATE TABLE [{table_name}] (
            datum DATETIME,
            broker TEXT(20),
            asset_rollup TEXT(20),
            uniek_id TEXT(255),
            asset_detail TEXT(50),
            transactie_aantal DOUBLE,
            transactie_euro_totaal CURRENCY,
            transactie_fee CURRENCY,
            multiplier_close_price DOUBLE,
            sprinter_ratio DOUBLE,
            sprinter_funding DOUBLE,
            asset_close_effective DOUBLE,
            sprinter_resultaat CURRENCY,
            sprinter_aantal_bezit DOUBLE
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
        "broker",
        "asset_rollup",
        "uniek_id",
        "asset_detail",
        "transactie_aantal",
        "transactie_euro_totaal",
        "transactie_fee",
        "multiplier_close_price",
        "sprinter_ratio",
        "sprinter_funding",
        "asset_close_effective",
        "sprinter_resultaat",
        "sprinter_aantal_bezit",
    ]
    rows = df_final.select(insert_cols).rows()
    placeholders = ",".join(["?"] * len(insert_cols))
    query = f"INSERT INTO per_dag_open_sprinters_opgerold_v2 ({','.join(insert_cols)}) VALUES ({placeholders})"
    cursor = conn.cursor()
    if run_options.insert_mode == "temp_table":
        stage_table = run_options.temp_table_name
        try:
            create_temp_stage_table(conn, stage_table)
            stage_query = f"INSERT INTO [{stage_table}] ({','.join(insert_cols)}) VALUES ({placeholders})"
            cursor.executemany(stage_query, rows)
            conn.commit()
            cursor.execute(
                f"""
                INSERT INTO per_dag_open_sprinters_opgerold_v2 ({','.join(insert_cols)})
                SELECT {','.join(insert_cols)}
                FROM [{stage_table}]
                """
            )
            conn.commit()
        except pyodbc.Error as exc:
            print(f"[warn] temp_table insert fallback naar executemany door Access lock/DDL error: {exc}")
            conn.rollback()
            cursor.executemany(query, rows)
            conn.commit()
        finally:
            drop_temp_stage_table(conn, stage_table)
        return
    cursor.executemany(query, rows)
    conn.commit()


def update_state_engine_status(conn, scope: RebuildScope, df_tx: pl.DataFrame, df_prices: pl.DataFrame) -> None:
    affected_assets = scope.assets or (
        sorted({str(x).strip() for x in df_tx.select("asset_rollup").unique().to_series().to_list() if x is not None and str(x).strip()})
        if not df_tx.is_empty()
        else []
    )
    if not affected_assets:
        return

    price_dates: dict[str, date | None] = {}
    if not df_prices.is_empty():
        grouped = df_prices.group_by("asset_rollup").agg(pl.col("datum").max().alias("last_price_date"))
        for row in grouped.to_dicts():
            last_price_date = row["last_price_date"]
            if isinstance(last_price_date, datetime):
                last_price_date = last_price_date.date()
            price_dates[str(row["asset_rollup"]).strip()] = last_price_date

    cursor = conn.cursor()
    run_at = datetime.now()
    for asset in affected_assets:
        cursor.execute(
            "DELETE FROM state_engine_status WHERE engine_name=? AND asset_rollup=?",
            "open_sprinters_v2",
            asset,
        )
        cursor.execute(
            """
            INSERT INTO state_engine_status
                (engine_name, asset_class, asset_rollup, last_rebuilt_through_date, last_price_date_used, last_run_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            "open_sprinters_v2",
            "sprinters",
            asset,
            scope.to_date,
            price_dates.get(asset),
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

        df_tx = load_sprinter_transactions(conn, scope)
        timer.mark(f"load_sprinter_transactions ({df_tx.height} rows)")
        if df_tx.is_empty():
            delete_target_range(conn, scope)
            timer.mark("delete_target_range")
            print("Geen sprintertransacties gevonden voor deze scope.")
            print(f"[timing] total: {perf_counter() - overall_start:.3f}s")
            return

        df_ref = load_sprinter_reference(conn)
        timer.mark(f"load_sprinter_reference ({df_ref.height} rows)")
        df_prices = load_price_history(conn, scope)
        timer.mark(f"load_price_history ({df_prices.height} rows)")
        df_state_intervals = build_state_intervals(df_tx, scope)
        timer.mark(f"build_state_intervals ({df_state_intervals.height} rows)")
        df_daily = materialize_daily_rows(df_state_intervals, scope)
        timer.mark(f"materialize_daily_rows ({df_daily.height} rows)")
        if df_daily.is_empty():
            delete_target_range(conn, scope)
            timer.mark("delete_target_range")
            update_state_engine_status(conn, scope, df_tx, df_prices)
            timer.mark("update_state_engine_status")
            print("Geen sprinter-state gevonden voor deze scope. Bestaande scope in v2 is opgeschoond.")
            print(f"[timing] total: {perf_counter() - overall_start:.3f}s")
            return

        df_final = attach_effective_close(df_daily, df_prices)
        timer.mark("attach_effective_close")
        df_final = compute_sprinter_values(df_final, df_ref)
        timer.mark("compute_sprinter_values")
        df_final = normalize_for_access(df_final)
        timer.mark("normalize_for_access")

        delete_target_range(conn, scope)
        timer.mark("delete_target_range")
        insert_rows(conn, df_final, run_options)
        timer.mark(f"insert_rows ({run_options.insert_mode})")
        update_state_engine_status(conn, scope, df_tx, df_prices)
        timer.mark("update_state_engine_status")
        print(f"Ingevoegd: {df_final.height} rijen")

    print(f"[timing] total: {perf_counter() - overall_start:.3f}s")


if __name__ == "__main__":
    main()
