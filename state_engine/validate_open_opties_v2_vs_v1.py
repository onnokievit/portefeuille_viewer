from __future__ import annotations

import argparse

import polars as pl

from common import DEFAULT_DB_PATH, get_connection, normalize_numeric_columns, normalize_uniek_id_for_compare, parse_iso_date


COMPARE_PRECISION = {
    "transactie_aantal": 4,
    "optie_premie": 2,
    "open_optie_waarde_itm": 2,
    "winst_verlies": 2,
}


def load_table(conn, table: str, from_date, to_date, asset_rollup: str | None) -> pl.DataFrame:
    clauses = ["datum >= ?"]
    params = [from_date]
    if to_date:
        clauses.append("datum <= ?")
        params.append(to_date)
    if asset_rollup:
        clauses.append("asset_rollup = ?")
        params.append(asset_rollup)
    where_sql = " AND ".join(clauses)
    amount_select = "optie_aantal AS transactie_aantal" if table == "per_dag_open_opties_opgerold" else "transactie_aantal"
    sql = f"""
        SELECT datum, asset_rollup, uniek_id, {amount_select},
               optie_premie, itm_otm, open_optie_waarde_itm, winst_verlies
        FROM {table}
        WHERE {where_sql}
    """
    return pl.read_database(sql, conn, execute_options={"parameters": params})


def main() -> None:
    parser = argparse.ArgumentParser(description="Vergelijk open opties v1 en v2 met normalisatie van legacy uniek_id.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--asset-rollup")
    parser.add_argument("--from-date", required=True)
    parser.add_argument("--to-date")
    args = parser.parse_args()

    from_date = parse_iso_date(args.from_date)
    to_date = parse_iso_date(args.to_date) if args.to_date else None
    with get_connection(args.db) as conn:
        v1 = load_table(conn, "per_dag_open_opties_opgerold", from_date, to_date, args.asset_rollup)
        v2 = load_table(conn, "per_dag_open_opties_opgerold_v2", from_date, to_date, args.asset_rollup)

    def prep(df: pl.DataFrame) -> pl.DataFrame:
        if df.is_empty():
            return df
        df = (
            df.with_columns(
                pl.col("datum").cast(pl.Date),
                pl.col("transactie_aantal").cast(pl.Float64),
                pl.col("optie_premie").cast(pl.Float64),
                pl.col("itm_otm").cast(pl.Int64),
                pl.col("open_optie_waarde_itm").cast(pl.Float64),
                pl.col("winst_verlies").cast(pl.Float64),
                pl.col("uniek_id")
                .map_elements(normalize_uniek_id_for_compare, return_dtype=pl.Utf8)
                .alias("uniek_id_norm"),
            )
            .drop("uniek_id")
            .rename({"uniek_id_norm": "uniek_id"})
            .sort(["datum", "asset_rollup", "uniek_id"])
        )
        return normalize_numeric_columns(df, COMPARE_PRECISION)

    v1 = prep(v1)
    v2 = prep(v2)

    print(f"per_dag_open_opties_opgerold: {v1.height}")
    print(f"per_dag_open_opties_opgerold_v2: {v2.height}")

    key_cols = ["datum", "asset_rollup", "uniek_id"]
    value_cols = ["transactie_aantal", "optie_premie", "itm_otm", "open_optie_waarde_itm", "winst_verlies"]

    v1_keys = v1.select(key_cols).unique().sort(key_cols)
    v2_keys = v2.select(key_cols).unique().sort(key_cols)
    only_v1_keys = v1_keys.join(v2_keys, on=key_cols, how="anti")
    only_v2_keys = v2_keys.join(v1_keys, on=key_cols, how="anti")

    print(f"Keys alleen in v1: {only_v1_keys.height}")
    print(f"Keys alleen in v2: {only_v2_keys.height}")

    if only_v1_keys.height:
        print("Voorbeeld keys alleen in v1:")
        for row in only_v1_keys.head(10).to_dicts():
            print(repr(row))
    if only_v2_keys.height:
        print("Voorbeeld keys alleen in v2:")
        for row in only_v2_keys.head(10).to_dicts():
            print(repr(row))

    shared_v1 = v1.join(only_v1_keys, on=key_cols, how="anti")
    shared_v2 = v2.join(only_v2_keys, on=key_cols, how="anti")
    joined = (
        shared_v1.rename({col: f"{col}_v1" for col in value_cols})
        .join(
            shared_v2.rename({col: f"{col}_v2" for col in value_cols}),
            on=key_cols,
            how="inner",
        )
        .sort(key_cols)
    )

    mismatch_mask = None
    for col in value_cols:
        expr = pl.col(f"{col}_v1") != pl.col(f"{col}_v2")
        mismatch_mask = expr if mismatch_mask is None else (mismatch_mask | expr)
    value_mismatches = joined.filter(mismatch_mask) if mismatch_mask is not None else pl.DataFrame()

    print(f"Inhoudelijke verschillen op gedeelde keys: {value_mismatches.height}")
    if value_mismatches.height:
        print("Voorbeeld inhoudelijke verschillen:")
        show_cols = key_cols + [item for col in value_cols for item in (f"{col}_v1", f"{col}_v2")]
        for row in value_mismatches.select(show_cols).head(10).to_dicts():
            print(repr(row))


if __name__ == "__main__":
    main()
