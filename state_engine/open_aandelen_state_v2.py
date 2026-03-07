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
    "transactie_aantal_dag": 4,
    "transactie_waarde_dag": 2,
    "transactie_fee_dag": 2,
    "open_long_qty": 4,
    "open_long_cost_basis": 2,
    "avg_long_price": 6,
    "open_short_qty": 4,
    "open_short_basis": 2,
    "avg_short_price": 6,
    "cum_qty_bought": 4,
    "cum_qty_sold": 4,
    "cum_value_bought": 2,
    "cum_value_sold": 2,
    "cum_fee": 2,
    "realized_pnl_long": 2,
    "realized_pnl_short": 2,
    "realized_pnl_total": 2,
    "unrealized_pnl_long": 2,
    "unrealized_pnl_short": 2,
    "unrealized_pnl_total": 2,
    "close_price_effective": 6,
    "market_value_long": 2,
    "market_value_short": 2,
    "net_position_qty": 4,
}

TEMP_STAGE_TABLE_PREFIX = "TempAandelenStateV2Stage"


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
    parser = argparse.ArgumentParser(description="Bouw per_dag_aandelen_state_v2")
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


def fetch_min_transaction_date(conn, asset_rollup: str | None = None) -> date:
    cursor = conn.cursor()
    if asset_rollup:
        cursor.execute(
            "SELECT MIN(datum) FROM transacties_bron_data WHERE asset_type='aandeel' AND asset_rollup=?",
            asset_rollup,
        )
    else:
        cursor.execute("SELECT MIN(datum) FROM transacties_bron_data WHERE asset_type='aandeel'")
    result = cursor.fetchone()[0]
    if result is None:
        raise RuntimeError("Geen aandelentransacties gevonden.")
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


def load_equity_transactions(conn, scope: RebuildScope) -> pl.DataFrame:
    sql = """
        SELECT
            Id,
            datum,
            broker,
            asset_rollup,
            transactie_type,
            transactie_aantal,
            transactie_prijs,
            transactie_euro_totaal,
            transactie_fee
        FROM transacties_bron_data
        WHERE asset_type='aandeel'
          AND datum <= ?
    """
    params: list = [scope.to_date]
    if scope.assets:
        placeholders = ",".join("?" for _ in scope.assets)
        sql += f" AND asset_rollup IN ({placeholders})"
        params.extend(scope.assets)
    sql += " ORDER BY asset_rollup, broker, datum, Id"
    return (
        pl.read_database(sql, conn, execute_options={"parameters": params})
        .with_columns(
            [
                pl.col("datum").cast(pl.Date),
                pl.col("asset_rollup").cast(pl.Utf8).str.strip_chars(),
                pl.col("broker").cast(pl.Utf8).str.strip_chars(),
                pl.col("transactie_type").cast(pl.Utf8).str.strip_chars().str.to_lowercase(),
            ]
        )
    )


def load_stock_splits(conn, scope: RebuildScope) -> pl.DataFrame:
    cursor = conn.cursor()
    available_cols = {row.column_name for row in cursor.columns(table="stock_splits")}
    effective_col = "effective_date" if "effective_date" in available_cols else "split_date"
    action_col = "action_type" if "action_type" in available_cols else "split_type"
    share_col = "share_factor" if "share_factor" in available_cols else "split_factor"
    price_col = "price_factor" if "price_factor" in available_cols else None
    effective_expr = effective_col if effective_col == "effective_date" else f"{effective_col} AS effective_date"
    action_expr = action_col if action_col == "action_type" else f"{action_col} AS action_type"
    share_expr = share_col if share_col == "share_factor" else f"{share_col} AS share_factor"
    price_expr = (
        price_col if price_col == "price_factor"
        else (f"{price_col} AS price_factor" if price_col else f"IIF({share_col} IS NULL OR {share_col}=0, Null, 1 / {share_col}) AS price_factor")
    )
    sql = f"""
        SELECT Id, asset_rollup, {effective_expr}, {action_expr},
               {share_expr}, {price_expr}
        FROM stock_splits
        WHERE active = True
          AND {effective_col} <= ?
    """
    params: list = [scope.to_date]
    if scope.assets:
        placeholders = ",".join("?" for _ in scope.assets)
        sql += f" AND asset_rollup IN ({placeholders})"
        params.extend(scope.assets)
    sql += " ORDER BY asset_rollup, effective_date, Id"
    return (
        pl.read_database(sql, conn, execute_options={"parameters": params})
        .with_columns(pl.col("effective_date").cast(pl.Date))
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
        .rename({"close": "close_price_effective"})
    )


def aggregate_daily_transactions(df_tx: pl.DataFrame) -> pl.DataFrame:
    if df_tx.is_empty():
        return pl.DataFrame()
    return (
        df_tx.with_columns(
            pl.when(pl.col("transactie_aantal") > 0).then(pl.col("transactie_aantal")).otherwise(0.0).alias("qty_bought_dag"),
            pl.when(pl.col("transactie_aantal") < 0).then(-pl.col("transactie_aantal")).otherwise(0.0).alias("qty_sold_dag"),
            pl.when(pl.col("transactie_euro_totaal") < 0).then(-pl.col("transactie_euro_totaal")).otherwise(0.0).alias("value_bought_dag"),
            pl.when(pl.col("transactie_euro_totaal") > 0).then(pl.col("transactie_euro_totaal")).otherwise(0.0).alias("value_sold_dag"),
            pl.col("transactie_fee").fill_null(0.0).alias("fee_dag"),
        )
        .group_by(["asset_rollup", "broker", "datum"])
        .agg(
            [
                pl.col("transactie_aantal").sum().alias("transactie_aantal_dag"),
                pl.col("transactie_euro_totaal").sum().alias("transactie_waarde_dag"),
                pl.col("fee_dag").sum().alias("transactie_fee_dag"),
                pl.col("qty_bought_dag").sum().alias("qty_bought_dag"),
                pl.col("qty_sold_dag").sum().alias("qty_sold_dag"),
                pl.col("value_bought_dag").sum().alias("value_bought_dag"),
                pl.col("value_sold_dag").sum().alias("value_sold_dag"),
            ]
        )
        .sort(["asset_rollup", "broker", "datum"])
    )


def _position_side(long_qty: float, short_qty: float) -> str:
    if long_qty > 0:
        return "long"
    if short_qty > 0:
        return "short"
    return "flat"


def _normalized_tx_qty(row: dict) -> float:
    qty = float(row.get("transactie_aantal") or 0.0)
    tx_type = str(row.get("transactie_type") or "").strip().lower()
    if tx_type == "koop" and qty < 0:
        qty = -qty
    elif tx_type == "verkoop" and qty > 0:
        qty = -qty
    return qty


def build_state_intervals(df_tx: pl.DataFrame, df_actions: pl.DataFrame, scope: RebuildScope) -> pl.DataFrame:
    if df_tx.is_empty():
        return pl.DataFrame()

    action_map: dict[str, list[dict]] = {}
    if not df_actions.is_empty():
        for row in df_actions.to_dicts():
            action_map.setdefault(str(row["asset_rollup"]).strip(), []).append(row)

    intervals: list[dict] = []
    for bucket_df in df_tx.partition_by(["asset_rollup", "broker"], maintain_order=True):
        rows = bucket_df.to_dicts()
        asset = str(rows[0]["asset_rollup"]).strip()
        broker = str(rows[0]["broker"]).strip()

        by_date: dict[date, list[dict]] = {}
        for row in rows:
            datum = row["datum"]
            if isinstance(datum, datetime):
                datum = datum.date()
            row["datum"] = datum
            by_date.setdefault(datum, []).append(row)

        first_tx_date = min(by_date)
        action_dates = {r["effective_date"] for r in action_map.get(asset, []) if r["effective_date"] >= first_tx_date}
        event_dates = sorted(set(by_date.keys()) | set(action_dates))

        open_long_qty = 0.0
        open_long_cost_basis = 0.0
        open_short_qty = 0.0
        open_short_basis = 0.0
        cum_qty_bought = 0.0
        cum_qty_sold = 0.0
        cum_value_bought = 0.0
        cum_value_sold = 0.0
        cum_fee = 0.0
        realized_pnl_long = 0.0
        realized_pnl_short = 0.0

        actions_for_asset = action_map.get(asset, [])
        actions_by_date: dict[date, list[dict]] = {}
        for action in actions_for_asset:
            actions_by_date.setdefault(action["effective_date"], []).append(action)

        pending_share_factor = 1.0

        for idx, event_date in enumerate(event_dates):
            day_rows = by_date.get(event_date, [])
            day_signed_qty = sum(_normalized_tx_qty(r) for r in day_rows)
            price_scale_factor = 1.0

            for action in actions_by_date.get(event_date, []):
                share_factor = float(action["share_factor"] or 1.0)
                if share_factor <= 0:
                    continue
                pending_share_factor *= share_factor

            # Pas pending splitfactor toe zodra dat nodig is:
            # - direct bij normale transactiedag
            # - of op laatste eventdag
            # Maar sla toepassing over als transacties de conversie al expliciet bevatten.
            if pending_share_factor != 1.0:
                net_pos_before_split = open_long_qty - open_short_qty
                expected_split_delta = net_pos_before_split * (pending_share_factor - 1.0)
                tol = max(1e-6, abs(expected_split_delta) * 1e-6)
                split_is_already_encoded = abs(expected_split_delta) > tol and abs(day_signed_qty - expected_split_delta) <= tol
                is_last_event = idx == (len(event_dates) - 1)
                should_apply_now = bool(day_rows) or is_last_event

                if split_is_already_encoded:
                    pending_share_factor = 1.0
                elif should_apply_now:
                    open_long_qty *= pending_share_factor
                    open_short_qty *= pending_share_factor
                    pending_share_factor = 1.0
                    # Cost basis (in currency) remains economically the same through a pure split.
                    # Only quantity scales; avg price is derived later via basis / qty.
                else:
                    # Split is uitgesteld (bijv. broker-conversie de volgende dag):
                    # waardeer tussenliggend nog op oude contractschaal.
                    price_scale_factor = pending_share_factor

            day_tx_qty = 0.0
            day_tx_value = 0.0
            day_tx_fee = 0.0
            for row in sorted(day_rows, key=lambda r: r["Id"]):
                qty = _normalized_tx_qty(row)
                price = float(row["transactie_prijs"] or 0.0)
                fee = float(row["transactie_fee"] or 0.0)
                cash_total = float(row["transactie_euro_totaal"] or 0.0)
                day_tx_qty += qty
                day_tx_value += cash_total
                day_tx_fee += fee
                cum_fee += fee

                if qty > 0:
                    buy_qty = qty
                    cum_qty_bought += buy_qty
                    cum_value_bought += abs(cash_total)

                    close_short_qty = min(buy_qty, open_short_qty)
                    if close_short_qty > 0:
                        avg_short_price = open_short_basis / open_short_qty if open_short_qty else 0.0
                        realized_pnl_short += (avg_short_price - price) * close_short_qty
                        open_short_qty -= close_short_qty
                        open_short_basis -= avg_short_price * close_short_qty
                        buy_qty -= close_short_qty
                        if open_short_qty <= 1e-12:
                            open_short_qty = 0.0
                            open_short_basis = 0.0

                    if buy_qty > 0:
                        open_long_qty += buy_qty
                        open_long_cost_basis += buy_qty * price

                elif qty < 0:
                    sell_qty = -qty
                    cum_qty_sold += sell_qty
                    cum_value_sold += abs(cash_total)

                    close_long_qty = min(sell_qty, open_long_qty)
                    if close_long_qty > 0:
                        avg_long_price = open_long_cost_basis / open_long_qty if open_long_qty else 0.0
                        realized_pnl_long += (price - avg_long_price) * close_long_qty
                        open_long_qty -= close_long_qty
                        open_long_cost_basis -= avg_long_price * close_long_qty
                        sell_qty -= close_long_qty
                        if open_long_qty <= 1e-12:
                            open_long_qty = 0.0
                            open_long_cost_basis = 0.0

                    if sell_qty > 0:
                        open_short_qty += sell_qty
                        open_short_basis += sell_qty * price

            avg_long_price = open_long_cost_basis / open_long_qty if open_long_qty else 0.0
            avg_short_price = open_short_basis / open_short_qty if open_short_qty else 0.0
            next_event_date = event_dates[idx + 1] if idx + 1 < len(event_dates) else None
            interval_end = scope.to_date if next_event_date is None else min(scope.to_date, next_event_date - timedelta(days=1))
            if interval_end < event_date:
                continue
            intervals.append(
                {
                    "datum_start": event_date,
                    "datum_end": interval_end,
                    "datum": event_date,
                    "asset_rollup": asset,
                    "broker": broker,
                    "transactie_aantal_dag": day_tx_qty,
                    "transactie_waarde_dag": day_tx_value,
                    "transactie_fee_dag": day_tx_fee,
                    "open_long_qty": open_long_qty,
                    "open_long_cost_basis": open_long_cost_basis,
                    "avg_long_price": avg_long_price,
                    "open_short_qty": open_short_qty,
                    "open_short_basis": open_short_basis,
                    "avg_short_price": avg_short_price,
                    "cum_qty_bought": cum_qty_bought,
                    "cum_qty_sold": cum_qty_sold,
                    "cum_value_bought": cum_value_bought,
                    "cum_value_sold": cum_value_sold,
                    "cum_fee": cum_fee,
                    "realized_pnl_long": realized_pnl_long,
                    "realized_pnl_short": realized_pnl_short,
                    "realized_pnl_total": realized_pnl_long + realized_pnl_short,
                    "position_side": _position_side(open_long_qty, open_short_qty),
                    "price_scale_factor": price_scale_factor,
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


def apply_split_price_correction(df_prices: pl.DataFrame, df_actions: pl.DataFrame) -> pl.DataFrame:
    """
    historical close is split-adjusted in many feeds. For state valuation against raw transaction prices,
    reconstruct an effective close by multiplying pre-split dates with cumulative share_factor of future splits.
    """
    if df_prices.is_empty():
        return df_prices
    if df_actions.is_empty():
        return df_prices.with_columns(pl.lit(1.0).alias("price_correction_factor"))

    price_rows = df_prices.sort(["asset_rollup", "datum"]).to_dicts()
    actions_by_asset: dict[str, list[tuple[date, float]]] = {}
    for row in df_actions.select(["asset_rollup", "effective_date", "share_factor"]).to_dicts():
        asset = str(row["asset_rollup"]).strip()
        eff = row["effective_date"]
        if isinstance(eff, datetime):
            eff = eff.date()
        share_factor = float(row["share_factor"] or 1.0)
        if share_factor <= 0:
            continue
        actions_by_asset.setdefault(asset, []).append((eff, share_factor))
    for asset in actions_by_asset:
        actions_by_asset[asset].sort(key=lambda x: x[0])

    corr_rows: list[dict] = []
    # Walk per asset by ascending date; remove factor once split effective date is reached.
    for price_part in df_prices.sort(["asset_rollup", "datum"]).partition_by("asset_rollup", maintain_order=True):
        asset_key = str(price_part["asset_rollup"][0]).strip()
        actions = actions_by_asset.get(asset_key, [])
        if not actions:
            for r in price_part.select(["datum"]).to_dicts():
                d = r["datum"]
                if isinstance(d, datetime):
                    d = d.date()
                corr_rows.append(
                    {
                        "asset_rollup": asset_key,
                        "datum": d,
                        "price_correction_factor": 1.0,
                    }
                )
            continue
        active_factor = 1.0
        for _, sf in actions:
            active_factor *= sf
        idx = 0
        for r in price_part.select(["datum"]).to_dicts():
            d = r["datum"]
            if isinstance(d, datetime):
                d = d.date()
            while idx < len(actions) and d >= actions[idx][0]:
                sf = actions[idx][1]
                active_factor = active_factor / sf if sf != 0 else active_factor
                idx += 1
            corr_rows.append(
                {
                    "asset_rollup": asset_key,
                    "datum": d,
                    "price_correction_factor": float(active_factor),
                }
            )

    df_corr = pl.DataFrame(corr_rows)
    return (
        df_prices.join(df_corr, on=["asset_rollup", "datum"], how="left")
        .with_columns(pl.col("price_correction_factor").fill_null(1.0))
        .with_columns((pl.col("close_price_effective") * pl.col("price_correction_factor")).alias("close_price_effective"))
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


def compute_valuation(df_daily: pl.DataFrame) -> pl.DataFrame:
    if df_daily.is_empty():
        return df_daily
    return (
        df_daily.with_columns(
            (
                pl.col("close_price_effective") * pl.col("price_scale_factor").fill_null(1.0)
            ).alias("close_price_effective")
        )
        .with_columns(
            (pl.col("open_long_qty") * pl.col("close_price_effective")).alias("market_value_long"),
            (pl.col("open_short_qty") * pl.col("close_price_effective")).alias("market_value_short"),
        )
        .with_columns(
            (pl.col("market_value_long") - pl.col("open_long_cost_basis")).alias("unrealized_pnl_long"),
            (pl.col("open_short_basis") - pl.col("market_value_short")).alias("unrealized_pnl_short"),
            (pl.col("open_long_qty") - pl.col("open_short_qty")).alias("net_position_qty"),
        )
        .with_columns(
            (pl.col("unrealized_pnl_long") + pl.col("unrealized_pnl_short")).alias("unrealized_pnl_total"),
            (pl.col("realized_pnl_long") + pl.col("realized_pnl_short")).alias("realized_pnl_total"),
        )
    )


def normalize_for_access(df: pl.DataFrame) -> pl.DataFrame:
    if df.is_empty():
        return df
    return normalize_numeric_columns(df, PRECISION_MAP)


def delete_target_range(conn, scope: RebuildScope) -> None:
    def _to_access_date_literal(d: date) -> str:
        return f"#{d.month}/{d.day}/{d.year}#"

    cursor = conn.cursor()
    if scope.assets is None:
        cursor.execute("DELETE FROM per_dag_aandelen_state_v2")
        conn.commit()
        return

    batch_days = 30
    for asset in scope.assets:
        batch_start = scope.from_date
        while batch_start <= scope.to_date:
            batch_end = min(batch_start + timedelta(days=batch_days - 1), scope.to_date)
            # Access kan onbetrouwbaar zijn met geparametriseerde Date compares op DATETIME-kolommen.
            # Gebruik expliciete Access date-literals voor robuuste range-deletes.
            sql = (
                "DELETE FROM per_dag_aandelen_state_v2 "
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
        cursor.execute(f"DROP TABLE {table_name}")
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
        CREATE TABLE {table_name} (
            datum DATETIME,
            broker TEXT(20),
            asset_rollup TEXT(20),
            transactie_aantal_dag DOUBLE,
            transactie_waarde_dag CURRENCY,
            transactie_fee_dag CURRENCY,
            open_long_qty DOUBLE,
            open_long_cost_basis CURRENCY,
            avg_long_price DOUBLE,
            open_short_qty DOUBLE,
            open_short_basis CURRENCY,
            avg_short_price DOUBLE,
            cum_qty_bought DOUBLE,
            cum_qty_sold DOUBLE,
            cum_value_bought CURRENCY,
            cum_value_sold CURRENCY,
            cum_fee CURRENCY,
            realized_pnl_long CURRENCY,
            realized_pnl_short CURRENCY,
            realized_pnl_total CURRENCY,
            unrealized_pnl_long CURRENCY,
            unrealized_pnl_short CURRENCY,
            unrealized_pnl_total CURRENCY,
            close_price_effective DOUBLE,
            market_value_long CURRENCY,
            market_value_short CURRENCY,
            net_position_qty DOUBLE,
            position_side TEXT(10)
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
        "transactie_aantal_dag",
        "transactie_waarde_dag",
        "transactie_fee_dag",
        "open_long_qty",
        "open_long_cost_basis",
        "avg_long_price",
        "open_short_qty",
        "open_short_basis",
        "avg_short_price",
        "cum_qty_bought",
        "cum_qty_sold",
        "cum_value_bought",
        "cum_value_sold",
        "cum_fee",
        "realized_pnl_long",
        "realized_pnl_short",
        "realized_pnl_total",
        "unrealized_pnl_long",
        "unrealized_pnl_short",
        "unrealized_pnl_total",
        "close_price_effective",
        "market_value_long",
        "market_value_short",
        "net_position_qty",
        "position_side",
    ]
    rows = df_final.select(insert_cols).rows()
    placeholders = ",".join(["?"] * len(insert_cols))
    query = f"INSERT INTO per_dag_aandelen_state_v2 ({','.join(insert_cols)}) VALUES ({placeholders})"
    cursor = conn.cursor()
    if run_options.insert_mode == "temp_table":
        stage_table = run_options.temp_table_name
        try:
            create_temp_stage_table(conn, stage_table)
            stage_query = f"INSERT INTO {stage_table} ({','.join(insert_cols)}) VALUES ({placeholders})"
            cursor.executemany(stage_query, rows)
            conn.commit()
            cursor.execute(
                f"""
                INSERT INTO per_dag_aandelen_state_v2 ({','.join(insert_cols)})
                SELECT {','.join(insert_cols)}
                FROM {stage_table}
                """
            )
            conn.commit()
        except pyodbc.Error as exc:
            # Access kan DDL-locks geven wanneer de app/andere processen de DB gebruiken.
            # Fallback naar directe executemany insert zodat de run niet faalt.
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
            "open_aandelen_v2",
            asset,
        )
        cursor.execute(
            """
            INSERT INTO state_engine_status
                (engine_name, asset_class, asset_rollup, last_rebuilt_through_date, last_price_date_used, last_run_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            "open_aandelen_v2",
            "aandelen",
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
        # Defensief: ruim achtergebleven temp stage tables van eerdere fails/locks op.
        drop_stale_temp_stage_tables(conn)
        scope = resolve_scope(args, conn)
        print(f"Scope mode={scope.mode} assets={scope.assets or 'ALL'} from={scope.from_date} to={scope.to_date}")
        timer.mark("resolve_scope")

        df_tx = load_equity_transactions(conn, scope)
        timer.mark(f"load_equity_transactions ({df_tx.height} rows)")
        if df_tx.is_empty():
            delete_target_range(conn, scope)
            timer.mark("delete_target_range")
            print("Geen aandelentransacties gevonden voor deze scope.")
            print(f"[timing] total: {perf_counter() - overall_start:.3f}s")
            return

        df_actions = load_stock_splits(conn, scope)
        timer.mark(f"load_stock_splits ({df_actions.height} rows)")
        df_prices = load_price_history(conn, scope)
        timer.mark(f"load_price_history ({df_prices.height} rows)")
        df_prices = apply_split_price_correction(df_prices, df_actions)
        timer.mark("apply_split_price_correction")
        df_state_intervals = build_state_intervals(df_tx, df_actions, scope)
        timer.mark(f"build_state_intervals ({df_state_intervals.height} rows)")
        df_daily = materialize_daily_rows(df_state_intervals, scope)
        timer.mark(f"materialize_daily_rows ({df_daily.height} rows)")
        if df_daily.is_empty():
            delete_target_range(conn, scope)
            timer.mark("delete_target_range")
            update_state_engine_status(conn, scope, df_tx, df_prices)
            timer.mark("update_state_engine_status")
            print("Geen aandelen-state gevonden voor deze scope. Bestaande scope in v2 is opgeschoond.")
            print(f"[timing] total: {perf_counter() - overall_start:.3f}s")
            return

        daily_tx = aggregate_daily_transactions(df_tx)
        timer.mark(f"aggregate_daily_transactions ({daily_tx.height} rows)")
        df_final = (
            df_daily.drop(["transactie_aantal_dag", "transactie_waarde_dag", "transactie_fee_dag"])
            .join(daily_tx.select(["asset_rollup", "broker", "datum", "transactie_aantal_dag", "transactie_waarde_dag", "transactie_fee_dag"]), on=["asset_rollup", "broker", "datum"], how="left")
            .with_columns(
                pl.col("transactie_aantal_dag").fill_null(0.0),
                pl.col("transactie_waarde_dag").fill_null(0.0),
                pl.col("transactie_fee_dag").fill_null(0.0),
            )
        )
        df_final = attach_effective_close(df_final, df_prices)
        timer.mark("attach_effective_close")
        df_final = compute_valuation(df_final)
        timer.mark("compute_valuation")
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
