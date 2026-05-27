from __future__ import annotations

import polars as pl

from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.services.portfolio_broker_filter_state import normalize_broker


NUMERIC_PORTFOLIO_COLS = (
    "aand_aantal_bezit",
    "aand_waarde_bezit",
    "opt_waarde_bezit",
    "opt_waarde_ITM",
    "opt_waarde_bezit_delta",
    "opt_aantal_ITM_put",
    "opt_aantal_OTM_put",
    "opt_aantal_ITM_call",
    "opt_aantal_OTM_call",
    "aantal_sprinters",
    "spr_waarde_bezit",
)


def filter_brokers(df: pl.DataFrame | None, selected_brokers: set[str] | None) -> pl.DataFrame:
    if df is None:
        return pl.DataFrame()
    if df.is_empty() or not selected_brokers or "broker" not in df.columns:
        return df
    selected = {normalize_broker(v) for v in selected_brokers if normalize_broker(v)}
    if not selected:
        return df
    return df.filter(
        pl.col("broker")
        .cast(pl.Utf8, strict=False)
        .str.strip_chars()
        .str.to_lowercase()
        .is_in(sorted(selected))
    )


def _empty_combined_schema() -> dict[str, pl.DataType]:
    return {
        "asset_rollup": pl.Utf8,
        "regio": pl.Utf8,
        "sector": pl.Utf8,
        "value_grow": pl.Utf8,
        "koers": pl.Float64,
        "aand_aantal_bezit": pl.Float64,
        "aand_waarde_bezit": pl.Float64,
        "opt_waarde_bezit": pl.Float64,
        "opt_waarde_ITM": pl.Float64,
        "opt_waarde_bezit_delta": pl.Float64,
        "opt_aantal_ITM_put": pl.Float64,
        "opt_aantal_OTM_put": pl.Float64,
        "opt_aantal_ITM_call": pl.Float64,
        "opt_aantal_OTM_call": pl.Float64,
        "aantal_sprinters": pl.Float64,
        "spr_waarde_bezit": pl.Float64,
        "total_aantal_lineair": pl.Float64,
        "total_waarde_lineair": pl.Float64,
        "total_waarde_delta": pl.Float64,
        "portfolio_total_waarde_lineair_pct": pl.Float64,
        "portfolio_total_waarde_delta_pct": pl.Float64,
        "portfolio_total_waarde_lineair_pct_all_brokers": pl.Float64,
        "portfolio_total_waarde_delta_pct_all_brokers": pl.Float64,
    }


def _safe_div_expr(numerator: str, denominator: float, alias: str) -> pl.Expr:
    if denominator:
        return (pl.col(numerator) / pl.lit(float(denominator))).alias(alias)
    return pl.lit(0.0).cast(pl.Float64).alias(alias)


def _coalesce_join_key_and_meta(df: pl.DataFrame) -> pl.DataFrame:
    exprs: list[pl.Expr] = []
    drop_cols: list[str] = []
    for col in ("asset_rollup", "regio", "sector", "value_grow"):
        right_col = f"{col}_right"
        if right_col not in df.columns:
            continue
        if col in df.columns:
            exprs.append(pl.coalesce([pl.col(col), pl.col(right_col)]).alias(col))
        else:
            exprs.append(pl.col(right_col).alias(col))
        drop_cols.append(right_col)
    if exprs:
        df = df.with_columns(exprs)
    return df.drop(drop_cols) if drop_cols else df


def _group_aandelen(df: pl.DataFrame) -> pl.DataFrame:
    if df is None or df.is_empty():
        return pl.DataFrame(schema={
            "asset_rollup": pl.Utf8,
            "regio": pl.Utf8,
            "sector": pl.Utf8,
            "value_grow": pl.Utf8,
            "koers": pl.Float64,
            "aand_aantal_bezit": pl.Float64,
            "aand_waarde_bezit": pl.Float64,
        })
    return (
        df.with_columns(pl.col("asset_rollup").cast(pl.Utf8, strict=False))
        .group_by(["asset_rollup", "regio", "sector", "value_grow", "koers"])
        .agg(
            [
                pl.col("aantal_bezit").cast(pl.Float64, strict=False).sum().alias("aand_aantal_bezit"),
                pl.col("waarde_bezit").cast(pl.Float64, strict=False).sum().alias("aand_waarde_bezit"),
            ]
        )
    )


def _group_opties(df: pl.DataFrame) -> pl.DataFrame:
    if df is None or df.is_empty():
        return pl.DataFrame(schema={
            "asset_rollup": pl.Utf8,
            "regio": pl.Utf8,
            "sector": pl.Utf8,
            "value_grow": pl.Utf8,
            "opt_waarde_bezit": pl.Float64,
            "opt_waarde_ITM": pl.Float64,
            "opt_waarde_bezit_delta": pl.Float64,
            "opt_aantal_ITM_put": pl.Float64,
            "opt_aantal_OTM_put": pl.Float64,
            "opt_aantal_ITM_call": pl.Float64,
            "opt_aantal_OTM_call": pl.Float64,
        })
    df = df.with_columns(pl.col("asset_rollup").cast(pl.Utf8, strict=False))
    if "waarde_ITM" not in df.columns:
        df = df.with_columns(pl.lit(0.0).cast(pl.Float64).alias("waarde_ITM"))
    if "waarde_bezit_delta" not in df.columns:
        df = df.with_columns(pl.lit(0.0).cast(pl.Float64).alias("waarde_bezit_delta"))
    if "optie_call_put" in df.columns and "aantal_ITM" in df.columns and "aantal_OTM" in df.columns:
        df = df.with_columns(
            [
                pl.when(pl.col("optie_call_put").cast(pl.Utf8, strict=False).str.to_lowercase() == "put")
                .then(pl.col("aantal_ITM").cast(pl.Float64, strict=False))
                .otherwise(0.0)
                .alias("_aantal_ITM_put"),
                pl.when(pl.col("optie_call_put").cast(pl.Utf8, strict=False).str.to_lowercase() == "put")
                .then(pl.col("aantal_OTM").cast(pl.Float64, strict=False))
                .otherwise(0.0)
                .alias("_aantal_OTM_put"),
                pl.when(pl.col("optie_call_put").cast(pl.Utf8, strict=False).str.to_lowercase() == "call")
                .then(pl.col("aantal_ITM").cast(pl.Float64, strict=False))
                .otherwise(0.0)
                .alias("_aantal_ITM_call"),
                pl.when(pl.col("optie_call_put").cast(pl.Utf8, strict=False).str.to_lowercase() == "call")
                .then(pl.col("aantal_OTM").cast(pl.Float64, strict=False))
                .otherwise(0.0)
                .alias("_aantal_OTM_call"),
            ]
        )
    else:
        for col in ("_aantal_ITM_put", "_aantal_OTM_put", "_aantal_ITM_call", "_aantal_OTM_call"):
            df = df.with_columns(pl.lit(0.0).cast(pl.Float64).alias(col))
    for source_col, temp_col in (
        ("aantal_ITM_put", "_aantal_ITM_put"),
        ("aantal_OTM_put", "_aantal_OTM_put"),
        ("aantal_ITM_call", "_aantal_ITM_call"),
        ("aantal_OTM_call", "_aantal_OTM_call"),
    ):
        if source_col in df.columns:
            df = df.with_columns(
                pl.coalesce([pl.col(source_col).cast(pl.Float64, strict=False), pl.col(temp_col)]).alias(temp_col)
            )
    for col in ("regio", "sector", "value_grow"):
        if col not in df.columns:
            df = df.with_columns(pl.lit(None).cast(pl.Utf8).alias(col))
    cp_expr = (
        pl.col("optie_call_put").cast(pl.Utf8, strict=False).str.to_lowercase()
        if "optie_call_put" in df.columns
        else pl.lit("put")
    )
    df = df.with_columns(
        [
            pl.when(cp_expr == "put")
            .then(pl.col("waarde_bezit").cast(pl.Float64, strict=False))
            .otherwise(0.0)
            .alias("_put_waarde_bezit"),
            pl.when(cp_expr == "put")
            .then(pl.col("waarde_ITM").cast(pl.Float64, strict=False))
            .otherwise(0.0)
            .alias("_put_waarde_ITM"),
            pl.when(cp_expr == "put")
            .then(pl.col("waarde_bezit_delta").cast(pl.Float64, strict=False))
            .otherwise(0.0)
            .alias("_put_waarde_bezit_delta"),
        ]
    )
    return df.group_by(["asset_rollup", "regio", "sector", "value_grow"]).agg(
        [
            pl.col("_put_waarde_bezit").sum().alias("opt_waarde_bezit"),
            pl.col("_put_waarde_ITM").sum().alias("opt_waarde_ITM"),
            pl.col("_put_waarde_bezit_delta").sum().alias("opt_waarde_bezit_delta"),
            pl.col("_aantal_ITM_put").sum().alias("opt_aantal_ITM_put"),
            pl.col("_aantal_OTM_put").sum().alias("opt_aantal_OTM_put"),
            pl.col("_aantal_ITM_call").sum().alias("opt_aantal_ITM_call"),
            pl.col("_aantal_OTM_call").sum().alias("opt_aantal_OTM_call"),
        ]
    )


def _group_sprinters(df: pl.DataFrame) -> pl.DataFrame:
    if df is None or df.is_empty():
        return pl.DataFrame(schema={
            "asset_rollup": pl.Utf8,
            "regio": pl.Utf8,
            "sector": pl.Utf8,
            "value_grow": pl.Utf8,
            "aantal_sprinters": pl.Float64,
            "spr_waarde_bezit": pl.Float64,
        })
    for col in ("regio", "sector", "value_grow"):
        if col not in df.columns:
            df = df.with_columns(pl.lit(None).cast(pl.Utf8).alias(col))
    return (
        df.with_columns(pl.col("asset_rollup").cast(pl.Utf8, strict=False))
        .group_by(["asset_rollup", "regio", "sector", "value_grow"])
        .agg(
            [
                pl.col("aantal_sprinters").cast(pl.Float64, strict=False).sum().alias("aantal_sprinters"),
                pl.col("spr_waarde_bezit").cast(pl.Float64, strict=False).sum().alias("spr_waarde_bezit"),
            ]
        )
    )


def build_combined_portfolio_value_df(
    df_aandelen: pl.DataFrame | None,
    df_opties_put: pl.DataFrame | None,
    df_sprinters: pl.DataFrame | None,
    *,
    all_brokers_df: pl.DataFrame | None = None,
) -> pl.DataFrame:
    df_a = _group_aandelen(df_aandelen)
    df_o = _group_opties(df_opties_put)
    df_s = _group_sprinters(df_sprinters)
    if df_a.is_empty() and df_o.is_empty() and df_s.is_empty():
        return pl.DataFrame(schema=_empty_combined_schema())

    df = df_a.join(df_o, on=["asset_rollup"], how="outer")
    df = _coalesce_join_key_and_meta(df)
    df = df.join(df_s, on=["asset_rollup"], how="outer")
    df = _coalesce_join_key_and_meta(df)

    for col in ("regio", "sector", "value_grow"):
        if col not in df.columns:
            df = df.with_columns(pl.lit(None).cast(pl.Utf8).alias(col))
    if "koers" not in df.columns:
        df = df.with_columns(pl.lit(None).cast(pl.Float64).alias("koers"))

    fill_exprs = []
    for col in NUMERIC_PORTFOLIO_COLS:
        if col not in df.columns:
            df = df.with_columns(pl.lit(0.0).cast(pl.Float64).alias(col))
        fill_exprs.append(pl.col(col).cast(pl.Float64, strict=False).fill_null(0.0).alias(col))
    df = df.with_columns(fill_exprs)

    df = df.with_columns(
        [
            (pl.col("aand_aantal_bezit") + (-1 * pl.col("opt_aantal_ITM_put"))).alias("total_aantal_lineair"),
            (pl.col("aand_waarde_bezit") + pl.col("opt_waarde_bezit") + pl.col("spr_waarde_bezit")).alias("total_waarde_lineair"),
            (pl.col("aand_waarde_bezit") + pl.col("opt_waarde_bezit_delta") + pl.col("spr_waarde_bezit")).alias("total_waarde_delta"),
        ]
    )
    total_lineair = float(df["total_waarde_lineair"].sum()) if "total_waarde_lineair" in df.columns else 0.0
    total_delta = float(df["total_waarde_delta"].sum()) if "total_waarde_delta" in df.columns else 0.0

    if all_brokers_df is not None and not all_brokers_df.is_empty():
        all_total_lineair = float(all_brokers_df["total_waarde_lineair"].sum()) if "total_waarde_lineair" in all_brokers_df.columns else 0.0
        all_total_delta = float(all_brokers_df["total_waarde_delta"].sum()) if "total_waarde_delta" in all_brokers_df.columns else 0.0
    else:
        all_total_lineair = total_lineair
        all_total_delta = total_delta

    df = df.with_columns(
        [
            _safe_div_expr("total_waarde_lineair", total_lineair, "portfolio_total_waarde_lineair_pct"),
            _safe_div_expr("total_waarde_delta", total_delta, "portfolio_total_waarde_delta_pct"),
            _safe_div_expr("total_waarde_lineair", all_total_lineair, "portfolio_total_waarde_lineair_pct_all_brokers"),
            _safe_div_expr("total_waarde_delta", all_total_delta, "portfolio_total_waarde_delta_pct_all_brokers"),
        ]
    )
    return df.sort("asset_rollup")


def build_filtered_portfolio_value_df(
    selected_brokers: set[str] | None,
    *,
    use_scenario: bool = False,
) -> pl.DataFrame:
    all_df = getattr(SNAPSHOT_STORE, "repository_snapshot_portfolio_value_total_combined_put", None)
    source_aandelen = (
        getattr(SNAPSHOT_STORE, "repository_snapshot_portfolio_value_aandelen_scenario", None)
        if use_scenario else None
    )
    if source_aandelen is None:
        source_aandelen = getattr(SNAPSHOT_STORE, "repository_snapshot_portfolio_value_aandelen", None)
    source_opties = (
        getattr(SNAPSHOT_STORE, "repository_snapshot_portfolio_value_optie_call_put_detailed_scenario", None)
        if use_scenario else None
    )
    if source_opties is None:
        source_opties = getattr(SNAPSHOT_STORE, "repository_snapshot_portfolio_value_optie_call_put_detailed", None)
    source_sprinters = (
        getattr(SNAPSHOT_STORE, "repository_snapshot_portfolio_value_sprinters_scenario", None)
        if use_scenario else None
    )
    if source_sprinters is None:
        source_sprinters = getattr(SNAPSHOT_STORE, "repository_snapshot_portfolio_value_sprinters", None)

    all_scope_df = None
    if use_scenario:
        all_scope_df = build_combined_portfolio_value_df(source_aandelen, source_opties, source_sprinters)
    elif all_df is not None and not all_df.is_empty():
        all_scope_df = all_df

    if not selected_brokers and not use_scenario and all_df is not None and not all_df.is_empty():
        if "portfolio_total_waarde_lineair_pct_all_brokers" in all_df.columns and "portfolio_total_waarde_delta_pct_all_brokers" in all_df.columns:
            return all_df.clone()
        return build_combined_portfolio_value_df(source_aandelen, source_opties, source_sprinters, all_brokers_df=all_df)
    if not selected_brokers and use_scenario:
        return all_scope_df if all_scope_df is not None else pl.DataFrame(schema=_empty_combined_schema())

    return build_combined_portfolio_value_df(
        filter_brokers(source_aandelen, selected_brokers),
        filter_brokers(source_opties, selected_brokers),
        filter_brokers(source_sprinters, selected_brokers),
        all_brokers_df=all_scope_df,
    )
