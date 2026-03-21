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
DIVIDEND_FEE_TYPE_ALIASES = {
    "dividend": "dividend",
    "div_belasting": "div_belasting",
    "div belasting": "div_belasting",
    "dividend_belasting": "div_belasting",
    "871_fee": "871_fee",
    "871 fee": "871_fee",
    "871-fee": "871_fee",
    "transactiebelasting": "transactiebelasting",
    "transactie_belasting": "transactiebelasting",
    "transaction_tax": "transactiebelasting",
}
DIVIDEND_FEE_SQL_FILTER_VALUES = tuple(sorted(set(DIVIDEND_FEE_TYPE_ALIASES.keys())))
ASSET_RESULT_INSERT_COLS = [
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
    "aantal_aandelen_v2",
    "aantal_put_short_v2",
    "aantal_put_long_v2",
    "aantal_sprinters_v2",
    "totaal_aantal_bezit_v2",
    "totaal_v2",
    "updated_at",
]

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
    "aantal_aandelen_v2": 4,
    "aantal_put_short_v2": 4,
    "aantal_put_long_v2": 4,
    "aantal_sprinters_v2": 4,
    "totaal_aantal_bezit_v2": 4,
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


def fetch_min_state_date_for_assets(conn, table_name: str, assets: list[str] | None) -> date | None:
    if not assets:
        return fetch_min_state_date(conn, table_name)
    placeholders = ",".join("?" for _ in assets)
    sql = f"SELECT MIN(datum) FROM {table_name} WHERE asset_rollup IN ({placeholders})"
    cur = conn.cursor()
    try:
        row = cur.execute(sql, assets).fetchone()
    except Exception:
        return None
    if not row or row[0] is None:
        return None
    value = row[0]
    return value.date() if isinstance(value, datetime) else value


def fetch_max_price_date(conn, assets: list[str] | None = None) -> date | None:
    cur = conn.cursor()
    if assets:
        placeholders = ",".join("?" for _ in assets)
        sql = f"SELECT MAX(datum) FROM historical_data_correct WHERE asset_rollup IN ({placeholders})"
        row = cur.execute(sql, assets).fetchone()
    else:
        row = cur.execute("SELECT MAX(datum) FROM historical_data_correct").fetchone()
    if not row or row[0] is None:
        return None
    value = row[0]
    return value.date() if isinstance(value, datetime) else value


def clamp_to_available_price_date(conn, requested_to_date: date, assets: list[str] | None) -> date:
    max_price_date = fetch_max_price_date(conn, assets)
    if max_price_date is None:
        return requested_to_date
    clamped = min(requested_to_date, max_price_date)
    if clamped < requested_to_date:
        print(
            f"[scope] to_date clamped van {requested_to_date} naar {clamped} "
            f"(laatste prijsdatum historical_data_correct)"
        )
    return clamped


def resolve_scope(args, conn) -> RebuildScope:
    requested_to_date = parse_iso_date(args.to_date) or date.today()
    assets = _normalize_assets(args.asset_rollups)
    # Voor asset_incremental willen we ook dagen zonder nieuwe price-bars kunnen materialiseren
    # (bijv. delisted assets met carry-forward resultaat).
    safe_to_date = requested_to_date if args.mode == "asset_incremental" else clamp_to_available_price_date(conn, requested_to_date, assets)
    if args.mode == "asset_incremental":
        from_date = parse_iso_date(args.from_date)
        if not from_date:
            raise ValueError("--from-date is verplicht voor asset_incremental")
        return RebuildScope(assets=assets, from_date=from_date, to_date=safe_to_date, mode=args.mode)

    if args.mode == "asset_split_rebuild" and assets:
        min_dates_assets = [
            fetch_min_state_date_for_assets(conn, "per_dag_aandelen_state_v2", assets),
            fetch_min_state_date_for_assets(conn, "per_dag_open_opties_opgerold_v2", assets),
            fetch_min_state_date_for_assets(conn, "per_dag_open_sprinters_opgerold_v2", assets),
        ]
        min_dates_assets = [d for d in min_dates_assets if d is not None]
        start_assets = min(min_dates_assets) if min_dates_assets else safe_to_date
        return RebuildScope(assets=assets, from_date=start_assets, to_date=safe_to_date, mode=args.mode)

    min_dates = [
        fetch_min_state_date(conn, "per_dag_aandelen_state_v2"),
        fetch_min_state_date(conn, "per_dag_open_opties_opgerold_v2"),
        fetch_min_state_date(conn, "per_dag_open_sprinters_opgerold_v2"),
    ]
    min_dates = [d for d in min_dates if d is not None]
    start = min(min_dates) if min_dates else safe_to_date
    return RebuildScope(assets=assets, from_date=start, to_date=safe_to_date, mode=args.mode)


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


def ensure_asset_result_v2_schema(conn) -> None:
    required = {
        "aantal_aandelen_v2": "DOUBLE",
        "aantal_put_short_v2": "DOUBLE",
        "aantal_put_long_v2": "DOUBLE",
        "aantal_sprinters_v2": "DOUBLE",
        "totaal_aantal_bezit_v2": "DOUBLE",
    }
    existing = {row.column_name.lower() for row in conn.cursor().columns(table="per_dag_asset_result_v2")}
    cur = conn.cursor()
    for col, typ in required.items():
        if col.lower() in existing:
            continue
        cur.execute(f"ALTER TABLE per_dag_asset_result_v2 ADD COLUMN {col} {typ}")
        conn.commit()


def load_stock_splits(conn, scope: RebuildScope) -> pl.DataFrame:
    asset_filter, asset_params = _asset_filter_sql(scope)
    cursor = conn.cursor()
    available_cols = {row.column_name for row in cursor.columns(table="stock_splits")}
    effective_col = "effective_date" if "effective_date" in available_cols else "split_date"
    share_col = "share_factor" if "share_factor" in available_cols else "split_factor"
    active_col = "active" if "active" in available_cols else None
    active_filter = " AND active <> 0" if active_col else ""
    sql = f"""
        SELECT asset_rollup, {effective_col}, {share_col}
        FROM stock_splits
        WHERE {effective_col} IS NOT NULL
          AND {share_col} IS NOT NULL
          {active_filter}
          {asset_filter}
        ORDER BY asset_rollup, {effective_col}
    """
    params = [*asset_params]
    try:
        df = pl.read_database(sql, conn, execute_options={"parameters": params})
    except Exception:
        return pl.DataFrame(schema={"asset_rollup": pl.Utf8, "effective_date": pl.Date, "share_factor": pl.Float64})
    if df.is_empty():
        return pl.DataFrame(schema={"asset_rollup": pl.Utf8, "effective_date": pl.Date, "share_factor": pl.Float64})
    return (
        df.with_columns(
            pl.col("asset_rollup").cast(pl.Utf8).str.strip_chars(),
            pl.col(effective_col).cast(pl.Date).alias("effective_date"),
            pl.col(share_col).cast(pl.Float64).alias("share_factor"),
        )
        .filter(pl.col("share_factor").is_not_null() & (pl.col("share_factor") != 0.0))
        .select(["asset_rollup", "effective_date", "share_factor"])
        .sort(["asset_rollup", "effective_date"])
    )


def _build_series_split_rules(
    series_events: dict[tuple[str, str], list[tuple[date, float]]],
    split_map: dict[str, list[dict]],
) -> dict[tuple[str, str], list[tuple[date, float, date | None]]]:
    rules: dict[tuple[str, str], list[tuple[date, float, date | None]]] = {}
    tol_abs = 1e-6
    for key, events in series_events.items():
        asset, _uid = key
        if asset not in split_map:
            continue
        events_sorted = sorted(events, key=lambda x: x[0])
        if not events_sorted:
            continue
        open_date = events_sorted[0][0]
        asset_splits = split_map.get(asset, [])
        if not asset_splits:
            continue
        series_rules: list[tuple[date, float, date | None]] = []
        for split in asset_splits:
            split_date = split["effective_date"]
            factor = float(split["share_factor"] or 1.0)
            if factor == 0.0 or open_date >= split_date:
                continue
            # Cumulatieve qty voor splitdatum.
            cum_before = 0.0
            for event_date, qty_delta in events_sorted:
                if event_date >= split_date:
                    break
                cum_before += qty_delta
            expected_delta = cum_before * (factor - 1.0)
            tol = max(tol_abs, abs(expected_delta) * 1e-6)
            corrected_at: date | None = None
            cum = cum_before
            # Als transacties de corporate-action omzetting expliciet tonen, stoppen we factor vanaf die dag.
            # Ook als cum_before op transactieniveau 0 lijkt (door doorrol-netting), blijft factor voor
            # pre-split open series van kracht tenzij een duidelijke omzetting wordt gedetecteerd.
            if abs(cum_before) > tol_abs:
                for event_date, qty_delta in events_sorted:
                    if event_date < split_date:
                        continue
                    cum_after = cum + qty_delta
                    if abs(qty_delta - expected_delta) <= tol or abs(cum_after - (cum_before * factor)) <= tol:
                        corrected_at = event_date
                        break
                    cum = cum_after
            series_rules.append((split_date, factor, corrected_at))
        if series_rules:
            rules[key] = series_rules
    return rules


def load_aantal_component(conn, scope: RebuildScope) -> pl.DataFrame:
    empty = pl.DataFrame(
        schema={
            "datum": pl.Date,
            "asset_rollup": pl.Utf8,
            "aantal_aandelen_v2": pl.Float64,
            "aantal_put_short_v2": pl.Float64,
            "aantal_put_long_v2": pl.Float64,
            "aantal_sprinters_v2": pl.Float64,
            "totaal_aantal_bezit_v2": pl.Float64,
        }
    )
    splits = load_stock_splits(conn, scope)
    split_map: dict[str, list[dict]] = {}
    if not splits.is_empty():
        for row in splits.to_dicts():
            split_map.setdefault(row["asset_rollup"], []).append(row)

    asset_filter, asset_params = _asset_filter_sql(scope)
    # Aandelen (net position qty)
    sql_eq = f"""
        SELECT datum, asset_rollup, SUM(net_position_qty) AS qty_eq
        FROM per_dag_aandelen_state_v2
        WHERE datum >= ? AND datum <= ?
          {asset_filter}
        GROUP BY datum, asset_rollup
    """
    params_eq = [scope.from_date, scope.to_date, *asset_params]
    df_eq = pl.read_database(sql_eq, conn, execute_options={"parameters": params_eq})
    if df_eq.is_empty():
        df_eq = pl.DataFrame(schema={"datum": pl.Date, "asset_rollup": pl.Utf8, "qty_eq": pl.Float64})
    else:
        df_eq = df_eq.with_columns(
            pl.col("datum").cast(pl.Date),
            pl.col("asset_rollup").cast(pl.Utf8).str.strip_chars(),
            pl.col("qty_eq").fill_null(0.0).cast(pl.Float64),
        )
        if split_map:
            rows = []
            for r in df_eq.to_dicts():
                asset = r["asset_rollup"]
                d = r["datum"]
                factor = 1.0
                for split in split_map.get(asset, []):
                    if split["effective_date"] > d:
                        factor *= float(split["share_factor"] or 1.0)
                rows.append({"datum": d, "asset_rollup": asset, "qty_eq": float(r["qty_eq"] or 0.0) * factor})
            df_eq = pl.DataFrame(rows)

    # Opties per serie met split-correctieregels.
    sql_opt = f"""
        SELECT datum, asset_rollup, uniek_id, optie_call_put, transactie_aantal
        FROM per_dag_open_opties_opgerold_v2
        WHERE datum >= ? AND datum <= ?
          {asset_filter}
    """
    params_opt = [scope.from_date, scope.to_date, *asset_params]
    df_opt = pl.read_database(sql_opt, conn, execute_options={"parameters": params_opt})
    if df_opt.is_empty():
        df_opt_agg = pl.DataFrame(schema={"datum": pl.Date, "asset_rollup": pl.Utf8, "qty_put_short": pl.Float64, "qty_put_long": pl.Float64})
    else:
        df_opt = df_opt.with_columns(
            pl.col("datum").cast(pl.Date),
            pl.col("asset_rollup").cast(pl.Utf8).str.strip_chars(),
            pl.col("uniek_id").cast(pl.Utf8).str.strip_chars(),
            pl.col("optie_call_put").cast(pl.Utf8).str.to_lowercase().str.strip_chars(),
            pl.col("transactie_aantal").fill_null(0.0).cast(pl.Float64),
        )
        tx_sql_opt = f"""
            SELECT datum, asset_rollup, uniek_id, SUM(transactie_aantal) AS qty_delta
            FROM transacties_bron_data
            WHERE asset_type='optie'
              AND datum <= ?
              {asset_filter}
            GROUP BY datum, asset_rollup, uniek_id
            ORDER BY asset_rollup, uniek_id, datum
        """
        tx_opt = pl.read_database(tx_sql_opt, conn, execute_options={"parameters": [scope.to_date, *asset_params]})
        series_events_opt: dict[tuple[str, str], list[tuple[date, float]]] = {}
        if not tx_opt.is_empty():
            tx_opt = tx_opt.with_columns(
                pl.col("datum").cast(pl.Date),
                pl.col("asset_rollup").cast(pl.Utf8).str.strip_chars(),
                pl.col("uniek_id").cast(pl.Utf8).str.strip_chars(),
                pl.col("qty_delta").fill_null(0.0).cast(pl.Float64),
            )
            for row in tx_opt.to_dicts():
                key = (row["asset_rollup"], row["uniek_id"])
                series_events_opt.setdefault(key, []).append((row["datum"], float(row["qty_delta"] or 0.0)))
        rules_opt = _build_series_split_rules(series_events_opt, split_map)

        rows = []
        for row in df_opt.to_dicts():
            factor = 1.0
            key = (row["asset_rollup"], row["uniek_id"])
            for _split_date, f, corrected_at in rules_opt.get(key, []):
                if corrected_at is None or row["datum"] < corrected_at:
                    factor *= f
            qty_adj = float(row["transactie_aantal"] or 0.0) * factor
            if row["optie_call_put"] != "put":
                continue
            rows.append(
                {
                    "datum": row["datum"],
                    "asset_rollup": row["asset_rollup"],
                    "qty_put_short": max(0.0, -qty_adj),
                    "qty_put_long": max(0.0, qty_adj),
                }
            )
        if rows:
            df_opt_agg = (
                pl.DataFrame(rows)
                .group_by(["datum", "asset_rollup"])
                .agg(
                    pl.col("qty_put_short").sum(),
                    pl.col("qty_put_long").sum(),
                )
            )
        else:
            df_opt_agg = pl.DataFrame(schema={"datum": pl.Date, "asset_rollup": pl.Utf8, "qty_put_short": pl.Float64, "qty_put_long": pl.Float64})

    # Sprinters per serie met dezelfde split-correctieregels.
    sql_sp = f"""
        SELECT datum, asset_rollup, uniek_id, sprinter_aantal_bezit
        FROM per_dag_open_sprinters_opgerold_v2
        WHERE datum >= ? AND datum <= ?
          {asset_filter}
    """
    params_sp = [scope.from_date, scope.to_date, *asset_params]
    df_sp = pl.read_database(sql_sp, conn, execute_options={"parameters": params_sp})
    if df_sp.is_empty():
        df_sp_agg = pl.DataFrame(schema={"datum": pl.Date, "asset_rollup": pl.Utf8, "qty_sp": pl.Float64})
    else:
        df_sp = df_sp.with_columns(
            pl.col("datum").cast(pl.Date),
            pl.col("asset_rollup").cast(pl.Utf8).str.strip_chars(),
            pl.col("uniek_id").cast(pl.Utf8).str.strip_chars(),
            pl.col("sprinter_aantal_bezit").fill_null(0.0).cast(pl.Float64),
        )
        tx_sql_sp = f"""
            SELECT datum, asset_rollup, uniek_id, SUM(transactie_aantal) AS qty_delta
            FROM transacties_bron_data
            WHERE asset_type='sprinter'
              AND datum <= ?
              {asset_filter}
            GROUP BY datum, asset_rollup, uniek_id
            ORDER BY asset_rollup, uniek_id, datum
        """
        tx_sp = pl.read_database(tx_sql_sp, conn, execute_options={"parameters": [scope.to_date, *asset_params]})
        series_events_sp: dict[tuple[str, str], list[tuple[date, float]]] = {}
        if not tx_sp.is_empty():
            tx_sp = tx_sp.with_columns(
                pl.col("datum").cast(pl.Date),
                pl.col("asset_rollup").cast(pl.Utf8).str.strip_chars(),
                pl.col("uniek_id").cast(pl.Utf8).str.strip_chars(),
                pl.col("qty_delta").fill_null(0.0).cast(pl.Float64),
            )
            for row in tx_sp.to_dicts():
                key = (row["asset_rollup"], row["uniek_id"])
                series_events_sp.setdefault(key, []).append((row["datum"], float(row["qty_delta"] or 0.0)))
        rules_sp = _build_series_split_rules(series_events_sp, split_map)

        rows = []
        for row in df_sp.to_dicts():
            factor = 1.0
            key = (row["asset_rollup"], row["uniek_id"])
            for _split_date, f, corrected_at in rules_sp.get(key, []):
                if corrected_at is None or row["datum"] < corrected_at:
                    factor *= f
            rows.append(
                {
                    "datum": row["datum"],
                    "asset_rollup": row["asset_rollup"],
                    "qty_sp": float(row["sprinter_aantal_bezit"] or 0.0) * factor,
                }
            )
        df_sp_agg = (
            pl.DataFrame(rows)
            .group_by(["datum", "asset_rollup"])
            .agg(pl.col("qty_sp").sum())
        ) if rows else pl.DataFrame(schema={"datum": pl.Date, "asset_rollup": pl.Utf8, "qty_sp": pl.Float64})

    frames = [f for f in [df_eq.select(["datum", "asset_rollup", "qty_eq"]) if "qty_eq" in df_eq.columns else None, df_opt_agg, df_sp_agg] if f is not None and not f.is_empty()]
    if not frames:
        return empty
    keys = pl.concat([f.select(["datum", "asset_rollup"]) for f in frames], how="vertical").unique()
    out = (
        keys
        .join(df_eq.select(["datum", "asset_rollup", "qty_eq"]) if "qty_eq" in df_eq.columns else pl.DataFrame(schema={"datum": pl.Date, "asset_rollup": pl.Utf8, "qty_eq": pl.Float64}), on=["datum", "asset_rollup"], how="left")
        .join(df_opt_agg, on=["datum", "asset_rollup"], how="left")
        .join(df_sp_agg, on=["datum", "asset_rollup"], how="left")
        .with_columns(
            pl.col("qty_eq").fill_null(0.0).alias("aantal_aandelen_v2"),
            pl.col("qty_put_short").fill_null(0.0).alias("aantal_put_short_v2"),
            pl.col("qty_put_long").fill_null(0.0).alias("aantal_put_long_v2"),
            pl.col("qty_sp").fill_null(0.0).alias("aantal_sprinters_v2"),
        )
        .with_columns(
            (
                pl.col("aantal_aandelen_v2")
                + pl.col("aantal_put_short_v2")
                + pl.col("aantal_sprinters_v2")
            ).alias("totaal_aantal_bezit_v2")
        )
        .select(
            [
                "datum",
                "asset_rollup",
                "aantal_aandelen_v2",
                "aantal_put_short_v2",
                "aantal_put_long_v2",
                "aantal_sprinters_v2",
                "totaal_aantal_bezit_v2",
            ]
        )
    )
    return out


def load_aandelen_component(conn, scope: RebuildScope) -> pl.DataFrame:
    asset_filter, asset_params = _asset_filter_sql(scope)
    sql = f"""
        SELECT
            datum,
            asset_rollup,
            SUM(
                IIF(realized_pnl_total IS NULL, 0, realized_pnl_total)
                + IIF(unrealized_pnl_total IS NULL, 0, unrealized_pnl_total)
            ) AS aandelen_resultaat_v2,
            SUM(IIF(cum_fee IS NULL, 0, cum_fee)) AS asset_fee_v2
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
    sql_tx = f"""
        SELECT
            datum,
            asset_rollup,
            uniek_id,
            transactie_aantal,
            transactie_euro_totaal,
            transactie_fee
        FROM transacties_bron_data
        WHERE asset_type='sprinter'
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
                "sprinter_resultaat_v2": pl.Float64,
                "gesloten_sprinters": pl.Float64,
                "sprinter_fee_v2": pl.Float64,
            }
        )

    # Open mark-to-market component uit open-sprinters v2 state (na open-only fix).
    sql_open = f"""
        SELECT
            datum,
            asset_rollup,
            SUM(sprinter_resultaat) AS open_sprinter_result
        FROM per_dag_open_sprinters_opgerold_v2
        WHERE datum >= ? AND datum <= ?
        {asset_filter}
        GROUP BY datum, asset_rollup
    """
    params_open = [scope.from_date, scope.to_date, *asset_params]
    df_open = (
        pl.read_database(sql_open, conn, execute_options={"parameters": params_open})
        .with_columns(
            pl.col("datum").cast(pl.Date),
            pl.col("asset_rollup").cast(pl.Utf8).str.strip_chars(),
            pl.col("open_sprinter_result").fill_null(0.0),
        )
    )

    # Dagelijkse transactiedelta per serie.
    df_day = (
        df_tx.group_by(["asset_rollup", "uniek_id", "datum"])
        .agg(
            pl.col("transactie_aantal").sum().alias("qty_dag"),
            pl.col("transactie_euro_totaal").sum().alias("eur_dag"),
            pl.col("transactie_fee").sum().alias("fee_dag"),
        )
        .sort(["asset_rollup", "uniek_id", "datum"])
    )

    intervals: list[dict] = []
    for part in df_day.partition_by(["asset_rollup", "uniek_id"], maintain_order=True):
        rows = part.to_dicts()
        asset = str(rows[0]["asset_rollup"]).strip()
        uid = str(rows[0]["uniek_id"]).strip()
        cum_qty = 0.0
        cum_eur = 0.0
        cum_fee = 0.0
        event_dates = [r["datum"] if not isinstance(r["datum"], datetime) else r["datum"].date() for r in rows]
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
                "sprinter_resultaat_v2": pl.Float64,
                "gesloten_sprinters": pl.Float64,
                "sprinter_fee_v2": pl.Float64,
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

    df_closed = (
        df_daily.group_by(["datum", "asset_rollup"])
        .agg(
            pl.when(pl.col("cum_qty") == 0).then(pl.col("cum_eur")).otherwise(0.0).sum().alias("gesloten_sprinters"),
            pl.when(pl.col("cum_qty") == 0).then(pl.col("cum_fee")).otherwise(0.0).sum().alias("sprinter_fee_closed_v2"),
            pl.when(pl.col("cum_qty") != 0).then(pl.col("cum_fee")).otherwise(0.0).sum().alias("sprinter_fee_open_v2"),
        )
        .join(df_open, on=["datum", "asset_rollup"], how="left")
        .with_columns(
            pl.col("open_sprinter_result").fill_null(0.0),
            pl.col("gesloten_sprinters").fill_null(0.0),
            pl.col("sprinter_fee_closed_v2").fill_null(0.0),
            pl.col("sprinter_fee_open_v2").fill_null(0.0),
        )
        .with_columns(
            (pl.col("open_sprinter_result") + pl.col("gesloten_sprinters")).alias("sprinter_resultaat_v2"),
            (pl.col("sprinter_fee_closed_v2") + pl.col("sprinter_fee_open_v2")).alias("sprinter_fee_v2"),
        )
        .select(["datum", "asset_rollup", "sprinter_resultaat_v2", "gesloten_sprinters", "sprinter_fee_v2"])
    )
    return df_closed


def load_dividend_component(conn, scope: RebuildScope) -> pl.DataFrame:
    empty_result = pl.DataFrame(
        schema={
            "datum": pl.Date,
            "asset_rollup": pl.Utf8,
            "dividend_v2": pl.Float64,
            "dividend_belasting_v2": pl.Float64,
            "fees_dividend_belasting_v2": pl.Float64,
        }
    )

    if scope.assets:
        placeholders_assets = ",".join("?" for _ in scope.assets)
        asset_filter = f" AND f.asset IN ({placeholders_assets})"
        asset_params = list(scope.assets)
    else:
        asset_filter = ""
        asset_params = []
    fee_types_placeholders = ",".join("?" for _ in DIVIDEND_FEE_SQL_FILTER_VALUES)
    sql = f"""
        SELECT f.datum, f.asset AS asset_rollup, f.fee_type, SUM(f.amount) AS amount
        FROM fees_dividend AS f
        WHERE LCase(f.fee_type) IN ({fee_types_placeholders})
          AND f.datum >= ?
          AND f.datum <= ?
          {asset_filter}
        GROUP BY f.datum, f.asset, f.fee_type
        ORDER BY f.asset, f.fee_type, f.datum
    """
    params = [*DIVIDEND_FEE_SQL_FILTER_VALUES, scope.from_date, scope.to_date, *asset_params]
    df = pl.read_database(sql, conn, execute_options={"parameters": params})
    if not df.is_empty():
        df = (
            df.with_columns(
                pl.col("datum").cast(pl.Date),
                pl.col("asset_rollup").cast(pl.Utf8).str.strip_chars(),
                pl.col("fee_type")
                .cast(pl.Utf8)
                .str.strip_chars()
                .str.to_lowercase()
                .map_elements(lambda v: DIVIDEND_FEE_TYPE_ALIASES.get(v), return_dtype=pl.Utf8)
                .alias("fee_type"),
                pl.col("amount").fill_null(0.0),
            )
            .filter(pl.col("fee_type").is_not_null())
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
            .sort(["asset_rollup", "datum"])
            .with_columns(
                pl.col("dividend").fill_null(strategy="forward").over("asset_rollup"),
                pl.col("div_belasting").fill_null(strategy="forward").over("asset_rollup"),
                pl.col("871_fee").fill_null(strategy="forward").over("asset_rollup"),
                pl.col("transactiebelasting").fill_null(strategy="forward").over("asset_rollup"),
            )
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
    else:
        df = empty_result

    base = pl.DataFrame(
        schema={
            "asset_rollup": pl.Utf8,
            "base_dividend_v2": pl.Float64,
            "base_dividend_belasting_v2": pl.Float64,
            "base_fees_dividend_belasting_v2": pl.Float64,
        }
    )

    if scope.from_date > date(1900, 1, 1):
        # Incremental: baseline cumulative value from day before from_date.
        baseline_cutoff = scope.from_date - timedelta(days=1)
        sql_base = f"""
            SELECT f.asset AS asset_rollup, f.fee_type, SUM(f.amount) AS base_amount
            FROM fees_dividend AS f
            WHERE LCase(f.fee_type) IN ({fee_types_placeholders})
              AND f.datum <= ?
              {asset_filter}
            GROUP BY f.asset, f.fee_type
        """
        params_base = [*DIVIDEND_FEE_SQL_FILTER_VALUES, baseline_cutoff, *asset_params]
        base = pl.read_database(sql_base, conn, execute_options={"parameters": params_base})
        if not base.is_empty():
            base = base.with_columns(
                pl.col("asset_rollup").cast(pl.Utf8).str.strip_chars(),
                pl.col("fee_type")
                .cast(pl.Utf8)
                .str.strip_chars()
                .str.to_lowercase()
                .map_elements(lambda v: DIVIDEND_FEE_TYPE_ALIASES.get(v), return_dtype=pl.Utf8)
                .alias("fee_type"),
                pl.col("base_amount").fill_null(0.0),
            ).filter(pl.col("fee_type").is_not_null())
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

    df = df.filter(pl.col("datum") >= pl.lit(scope.from_date, dtype=pl.Date))

    # Carry-forward cumulatieve dividend-standen naar alle dagen in de scope.
    # Zonder dit staan alleen event-dagen gevuld en worden tussenliggende dagen 0.
    if scope.assets:
        assets_df = pl.DataFrame(
            {
                "asset_rollup": [
                    str(a).strip()
                    for a in scope.assets
                    if a is not None and str(a).strip()
                ]
            }
        ).unique()
    else:
        asset_frames = []
        if not df.is_empty():
            asset_frames.append(df.select("asset_rollup").unique())
        if not base.is_empty():
            asset_frames.append(base.select("asset_rollup").unique())
        if not asset_frames:
            return empty_result
        assets_df = pl.concat(asset_frames, how="vertical").unique()

    if assets_df.is_empty():
        return empty_result

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
    dense = grid.join_asof(events, on="datum", by="asset_rollup", strategy="backward")

    if not base.is_empty():
        dense = (
            dense.join(base, on="asset_rollup", how="left")
            .with_columns(
                pl.col("base_dividend_v2").fill_null(0.0),
                pl.col("base_dividend_belasting_v2").fill_null(0.0),
                pl.col("base_fees_dividend_belasting_v2").fill_null(0.0),
            )
            .with_columns(
                (pl.col("dividend_v2").fill_null(0.0) + pl.col("base_dividend_v2")).alias("dividend_v2"),
                (pl.col("dividend_belasting_v2").fill_null(0.0) + pl.col("base_dividend_belasting_v2")).alias("dividend_belasting_v2"),
                (
                    pl.col("fees_dividend_belasting_v2").fill_null(0.0)
                    + pl.col("base_fees_dividend_belasting_v2")
                ).alias("fees_dividend_belasting_v2"),
            )
            .drop(["base_dividend_v2", "base_dividend_belasting_v2", "base_fees_dividend_belasting_v2"])
        )
    else:
        dense = dense.with_columns(
            pl.col("dividend_v2").fill_null(0.0),
            pl.col("dividend_belasting_v2").fill_null(0.0),
            pl.col("fees_dividend_belasting_v2").fill_null(0.0),
        )

    return dense.select(["datum", "asset_rollup", "dividend_v2", "dividend_belasting_v2", "fees_dividend_belasting_v2"])


def build_final(df_a: pl.DataFrame, df_o: pl.DataFrame, df_s: pl.DataFrame, df_d: pl.DataFrame, df_q: pl.DataFrame) -> pl.DataFrame:
    frames = [x for x in [df_a, df_o, df_s, df_d, df_q] if not x.is_empty()]
    if not frames:
        return pl.DataFrame()
    keys = pl.concat([f.select(["datum", "asset_rollup"]) for f in frames], how="vertical").unique()

    df = (
        keys.join(df_a, on=["datum", "asset_rollup"], how="left")
        .join(df_o, on=["datum", "asset_rollup"], how="left")
        .join(df_s, on=["datum", "asset_rollup"], how="left")
        .join(df_d, on=["datum", "asset_rollup"], how="left")
        .join(df_q, on=["datum", "asset_rollup"], how="left")
        .sort(["asset_rollup", "datum"])
        .with_columns(
            pl.col("aandelen_resultaat_v2").fill_null(strategy="forward").over("asset_rollup"),
            pl.col("asset_fee_v2").fill_null(strategy="forward").over("asset_rollup"),
            pl.col("optie_resultaat_v2").fill_null(strategy="forward").over("asset_rollup"),
            pl.col("gesloten_opties").fill_null(strategy="forward").over("asset_rollup"),
            pl.col("optie_fee_v2").fill_null(strategy="forward").over("asset_rollup"),
            pl.col("sprinter_resultaat_v2").fill_null(strategy="forward").over("asset_rollup"),
            pl.col("gesloten_sprinters").fill_null(strategy="forward").over("asset_rollup"),
            pl.col("sprinter_fee_v2").fill_null(strategy="forward").over("asset_rollup"),
            pl.col("dividend_v2").fill_null(strategy="forward").over("asset_rollup"),
            pl.col("dividend_belasting_v2").fill_null(strategy="forward").over("asset_rollup"),
            pl.col("fees_dividend_belasting_v2").fill_null(strategy="forward").over("asset_rollup"),
            pl.col("aantal_aandelen_v2").fill_null(strategy="forward").over("asset_rollup"),
            pl.col("aantal_put_short_v2").fill_null(strategy="forward").over("asset_rollup"),
            pl.col("aantal_put_long_v2").fill_null(strategy="forward").over("asset_rollup"),
            pl.col("aantal_sprinters_v2").fill_null(strategy="forward").over("asset_rollup"),
            pl.col("totaal_aantal_bezit_v2").fill_null(strategy="forward").over("asset_rollup"),
        )
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
            pl.col("aantal_aandelen_v2").fill_null(0.0),
            pl.col("aantal_put_short_v2").fill_null(0.0),
            pl.col("aantal_put_long_v2").fill_null(0.0),
            pl.col("aantal_sprinters_v2").fill_null(0.0),
            pl.col("totaal_aantal_bezit_v2").fill_null(0.0),
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
    delete_target_range_for_table(conn, scope, "per_dag_asset_result_v2")


def delete_target_range_for_table(conn, scope: RebuildScope, table_name: str) -> None:
    def _to_access_date_literal(d: date) -> str:
        return f"#{d.month}/{d.day}/{d.year}#"

    cursor = conn.cursor()
    if scope.assets is None:
        cursor.execute(f"DELETE FROM {table_name}")
        conn.commit()
        return

    if scope.mode == "asset_split_rebuild":
        for asset in scope.assets:
            cursor.execute(f"DELETE FROM {table_name} WHERE asset_rollup = ?", asset)
        conn.commit()
        return

    batch_days = 30
    for asset in scope.assets:
        batch_start = scope.from_date
        while batch_start <= scope.to_date:
            batch_end = min(batch_start + timedelta(days=batch_days - 1), scope.to_date)
            sql = (
                f"DELETE FROM {table_name} "
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
            aantal_aandelen_v2 DOUBLE,
            aantal_put_short_v2 DOUBLE,
            aantal_put_long_v2 DOUBLE,
            aantal_sprinters_v2 DOUBLE,
            totaal_aantal_bezit_v2 DOUBLE,
            totaal_v2 CURRENCY,
            updated_at DATETIME
        )
        """
    )
    conn.commit()


def table_exists(conn, table_name: str) -> bool:
    cur = conn.cursor()
    return any(row.table_name == table_name for row in cur.tables(table=table_name))


def insert_rows(conn, df_final: pl.DataFrame, run_options: RunOptions) -> None:
    if df_final.is_empty():
        print("Geen rijen om te inserten.")
        return

    rows = df_final.select(ASSET_RESULT_INSERT_COLS).rows()
    placeholders = ",".join(["?"] * len(ASSET_RESULT_INSERT_COLS))
    query = f"INSERT INTO per_dag_asset_result_v2 ({','.join(ASSET_RESULT_INSERT_COLS)}) VALUES ({placeholders})"
    cur = conn.cursor()
    if run_options.insert_mode == "temp_table":
        stage_table = run_options.temp_table_name
        try:
            create_temp_stage_table(conn, stage_table)
            stage_query = f"INSERT INTO [{stage_table}] ({','.join(ASSET_RESULT_INSERT_COLS)}) VALUES ({placeholders})"
            cur.executemany(stage_query, rows)
            conn.commit()
            cur.execute(
                f"""
                INSERT INTO per_dag_asset_result_v2 ({','.join(ASSET_RESULT_INSERT_COLS)})
                SELECT {','.join(ASSET_RESULT_INSERT_COLS)}
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
    requested_to_date = parse_iso_date(args.to_date) or date.today()
    requested_to_date = min(requested_to_date, date.today())
    run_options = RunOptions(
        insert_mode=args.insert_mode,
        temp_table_name=f"{TEMP_STAGE_TABLE_PREFIX}_{uuid4().hex[:8]}",
    )
    overall_start = perf_counter()
    timer = PhaseTimer()
    with get_connection(args.db) as conn:
        drop_stale_temp_stage_tables(conn)
        ensure_asset_result_v2_schema(conn)
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
        df_q = load_aantal_component(conn, scope)
        timer.mark(f"load_aantal_component ({df_q.height} rows)")

        df_final = build_final(df_a, df_o, df_s, df_d, df_q)
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
