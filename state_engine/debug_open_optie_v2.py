from __future__ import annotations

import argparse

import polars as pl

from common import DEFAULT_DB_PATH, get_connection


def main() -> None:
    parser = argparse.ArgumentParser(description="Toon een v2 reeks voor een uniek_id.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--uniek-id", required=True)
    args = parser.parse_args()

    sql = """
        SELECT datum, broker, asset_rollup, uniek_id, optie_exp_date, optie_strike, optie_call_put,
               transactie_aantal, optie_premie, optie_fee, asset_close_raw, asset_close_effective,
               price_factor_split, price_factor_override, price_factor_total, itm_otm,
               optie_waarde, open_optie_waarde_itm, winst_verlies, valuation_rule_type, valuation_method
        FROM per_dag_open_opties_opgerold_v2
        WHERE uniek_id = ?
        ORDER BY datum
    """
    with get_connection(args.db) as conn:
        df = pl.read_database(sql, conn, execute_options={"parameters": [args.uniek_id]})
    print(df)


if __name__ == "__main__":
    main()
