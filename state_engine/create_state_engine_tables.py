from __future__ import annotations

import argparse
from datetime import datetime

from common import DEFAULT_DB_PATH, get_connection


TABLE_DEFINITIONS = {
    "per_dag_open_opties_opgerold_v2": """
        CREATE TABLE per_dag_open_opties_opgerold_v2 (
            Id AUTOINCREMENT PRIMARY KEY,
            datum DATETIME,
            broker TEXT(50),
            asset_rollup TEXT(100),
            uniek_id TEXT(255),
            optie_exp_date DATETIME,
            optie_strike CURRENCY,
            optie_call_put TEXT(10),
            transactie_aantal DOUBLE,
            optie_premie CURRENCY,
            optie_fee CURRENCY,
            asset_close_raw DOUBLE,
            asset_close_effective DOUBLE,
            itm_otm BYTE,
            optie_waarde DOUBLE,
            open_optie_waarde_itm CURRENCY,
            winst_verlies CURRENCY,
            price_factor_split DOUBLE,
            price_factor_override DOUBLE,
            price_factor_total DOUBLE,
            valuation_rule_type TEXT(50),
            valuation_rule_id LONG,
            valuation_method TEXT(50),
            updated_at DATETIME
        )
    """,
    "stock_splits": """
        CREATE TABLE stock_splits (
            Id AUTOINCREMENT PRIMARY KEY,
            asset_rollup TEXT(100),
            split_date DATETIME,
            split_factor DOUBLE,
            split_type TEXT(30),
            active YESNO,
            description TEXT(255),
            notes LONGTEXT,
            updated_at DATETIME
        )
    """,
    "option_price_factor_overrides": """
        CREATE TABLE option_price_factor_overrides (
            Id AUTOINCREMENT PRIMARY KEY,
            uniek_id TEXT(255),
            effective_from_date DATETIME,
            effective_to_date DATETIME,
            override_factor DOUBLE,
            override_type TEXT(50),
            active YESNO,
            reason TEXT(255),
            notes LONGTEXT,
            updated_at DATETIME
        )
    """,
}

# stock_splits.split_factor semantics:
# It is the valuation correction factor applied to asset_close_raw to get back to
# the contract scale used by the option series.
# It is NOT the raw legal split ratio text.
# Examples used in this engine:
# - PROSUS 1 -> 2.1796 split: split_factor = 2.1796
# - UVXY 1-for-5 reverse split: split_factor = 0.2


INDEX_STATEMENTS = [
    "CREATE INDEX idx_open_opties_v2_datum ON per_dag_open_opties_opgerold_v2 (datum)",
    "CREATE INDEX idx_open_opties_v2_uniek_id ON per_dag_open_opties_opgerold_v2 (uniek_id)",
    "CREATE INDEX idx_open_opties_v2_asset ON per_dag_open_opties_opgerold_v2 (asset_rollup)",
    "CREATE INDEX idx_open_opties_v2_datum_uniek ON per_dag_open_opties_opgerold_v2 (datum, uniek_id)",
    "CREATE INDEX idx_stock_splits_asset_date ON stock_splits (asset_rollup, split_date)",
    "CREATE INDEX idx_option_factor_override_uid_date ON option_price_factor_overrides (uniek_id, effective_from_date)",
]


def table_exists(cursor, table_name: str) -> bool:
    return any(row.table_name == table_name for row in cursor.tables(table=table_name))


def create_tables(db_path: str) -> None:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        for table_name, ddl in TABLE_DEFINITIONS.items():
            if table_exists(cursor, table_name):
                print(f"Bestaat al: {table_name}")
                continue
            cursor.execute(ddl)
            conn.commit()
            print(f"Aangemaakt: {table_name}")

        for stmt in INDEX_STATEMENTS:
            try:
                cursor.execute(stmt)
                conn.commit()
                print(f"Index aangemaakt: {stmt}")
            except Exception:
                # Access geeft fout als index al bestaat; dat is prima.
                conn.rollback()

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"Klaar op {timestamp}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Maak state engine tabellen aan in Access.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Pad naar Access database")
    args = parser.parse_args()
    create_tables(args.db)


if __name__ == "__main__":
    main()
