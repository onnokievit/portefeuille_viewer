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
            asset_rollup TEXT(20),
            uniek_id TEXT(255),
            optie_exp_date DATETIME,
            optie_strike CURRENCY,
            optie_call_put TEXT(10),
            transactie_aantal DOUBLE,
            optie_premie CURRENCY,
            optie_fee CURRENCY,
            asset_close_effective DOUBLE,
            itm_otm BYTE,
            optie_waarde DOUBLE,
            open_optie_waarde_itm CURRENCY,
            winst_verlies CURRENCY
        )
    """,
    "stock_splits": """
        CREATE TABLE stock_splits (
            Id AUTOINCREMENT PRIMARY KEY,
            asset_rollup TEXT(20),
            effective_date DATETIME,
            action_type TEXT(30),
            share_factor DOUBLE,
            price_factor DOUBLE,
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
    "state_engine_status": """
        CREATE TABLE state_engine_status (
            Id AUTOINCREMENT PRIMARY KEY,
            engine_name TEXT(50),
            asset_class TEXT(20),
            asset_rollup TEXT(20),
            last_rebuilt_through_date DATETIME,
            last_price_date_used DATETIME,
            last_run_at DATETIME,
            status TEXT(20)
        )
    """,
    "state_rebuild_queue": """
        CREATE TABLE state_rebuild_queue (
            Id AUTOINCREMENT PRIMARY KEY,
            created_at DATETIME,
            asset_rollup TEXT(64),
            asset_class TEXT(20),
            from_date DATETIME,
            reason TEXT(64),
            status TEXT(20),
            run_id TEXT(64),
            updated_at DATETIME
        )
    """,
    "state_runs": """
        CREATE TABLE state_runs (
            Id AUTOINCREMENT PRIMARY KEY,
            run_id TEXT(64),
            created_at DATETIME,
            started_at DATETIME,
            finished_at DATETIME,
            status TEXT(24),
            engine_class TEXT(24),
            reason TEXT(64),
            mode TEXT(32),
            from_date DATETIME,
            affected_assets LONGTEXT,
            payload_json LONGTEXT,
            exit_code LONG,
            error_text LONGTEXT
        )
    """,
    "per_dag_aandelen_state_v2": """
        CREATE TABLE per_dag_aandelen_state_v2 (
            Id AUTOINCREMENT PRIMARY KEY,
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
    """,
    "per_dag_open_sprinters_opgerold_v2": """
        CREATE TABLE per_dag_open_sprinters_opgerold_v2 (
            Id AUTOINCREMENT PRIMARY KEY,
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
    """,
    "per_dag_asset_result_v2": """
        CREATE TABLE per_dag_asset_result_v2 (
            Id AUTOINCREMENT PRIMARY KEY,
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
    """,
}

# stock_splits central semantics:
# - share_factor: factor applied to share/contract quantities after the action.
#   Examples:
#   - 2:1 split -> 2.0
#   - 1-for-5 reverse split -> 0.2
# - price_factor: factor applied to per-share open basis / average price.
#   Usually the inverse of share_factor.
# Options engine uses share_factor to correct back-adjusted historical prices to the
# old contract scale. Equities engine uses share_factor and price_factor together to
# transform open position buckets on the action date.


INDEX_STATEMENTS = [
    "CREATE INDEX idx_open_opties_v2_datum ON per_dag_open_opties_opgerold_v2 (datum)",
    "CREATE INDEX idx_open_opties_v2_uniek_id ON per_dag_open_opties_opgerold_v2 (uniek_id)",
    "CREATE INDEX idx_open_opties_v2_asset ON per_dag_open_opties_opgerold_v2 (asset_rollup)",
    "CREATE INDEX idx_open_opties_v2_datum_uniek ON per_dag_open_opties_opgerold_v2 (datum, uniek_id)",
    "CREATE INDEX idx_stock_splits_asset_date ON stock_splits (asset_rollup, effective_date)",
    "CREATE INDEX idx_option_factor_override_uid_date ON option_price_factor_overrides (uniek_id, effective_from_date)",
    "CREATE INDEX idx_state_engine_status_engine_asset ON state_engine_status (engine_name, asset_rollup)",
    "CREATE INDEX idx_state_rebuild_queue_status ON state_rebuild_queue (status)",
    "CREATE INDEX idx_state_rebuild_queue_asset_class ON state_rebuild_queue (asset_rollup, asset_class)",
    "CREATE INDEX idx_state_rebuild_queue_run_id ON state_rebuild_queue (run_id)",
    "CREATE INDEX idx_state_runs_run_id ON state_runs (run_id)",
    "CREATE INDEX idx_state_runs_status ON state_runs (status)",
    "CREATE INDEX idx_aandelen_state_v2_datum_asset_broker ON per_dag_aandelen_state_v2 (datum, asset_rollup, broker)",
    "CREATE INDEX idx_aandelen_state_v2_asset ON per_dag_aandelen_state_v2 (asset_rollup)",
    "CREATE INDEX idx_sprinters_v2_datum_asset_broker ON per_dag_open_sprinters_opgerold_v2 (datum, asset_rollup, broker)",
    "CREATE INDEX idx_sprinters_v2_uniek_id ON per_dag_open_sprinters_opgerold_v2 (uniek_id)",
    "CREATE INDEX idx_asset_result_v2_datum_asset ON per_dag_asset_result_v2 (datum, asset_rollup)",
]


def table_exists(cursor, table_name: str) -> bool:
    return any(row.table_name == table_name for row in cursor.tables(table=table_name))


def column_names(cursor, table_name: str) -> set[str]:
    return {row.column_name for row in cursor.columns(table=table_name)}


def ensure_stock_splits_schema(cursor, conn) -> None:
    if not table_exists(cursor, "stock_splits"):
        return

    try:
        cols = column_names(cursor, "stock_splits")
    except Exception:
        return
    add_map = {
        "effective_date": "ALTER TABLE stock_splits ADD COLUMN effective_date DATETIME",
        "action_type": "ALTER TABLE stock_splits ADD COLUMN action_type TEXT(30)",
        "share_factor": "ALTER TABLE stock_splits ADD COLUMN share_factor DOUBLE",
        "price_factor": "ALTER TABLE stock_splits ADD COLUMN price_factor DOUBLE",
    }
    for col, stmt in add_map.items():
        if col not in cols:
            try:
                cursor.execute(stmt)
                conn.commit()
            except Exception:
                conn.rollback()
                print("stock_splits schema-migratie overgeslagen; waarschijnlijk gelinkte tabel in deze db.")
                return

    cols = column_names(cursor, "stock_splits")

    if "split_date" in cols and "effective_date" in cols:
        try:
            cursor.execute("UPDATE stock_splits SET effective_date = split_date WHERE effective_date IS NULL")
            conn.commit()
        except Exception:
            conn.rollback()
            print("stock_splits update effective_date overgeslagen (gelinkte/gelockte tabel).")
    if "split_type" in cols and "action_type" in cols:
        try:
            cursor.execute("UPDATE stock_splits SET action_type = split_type WHERE action_type IS NULL")
            conn.commit()
        except Exception:
            conn.rollback()
            print("stock_splits update action_type overgeslagen (gelinkte/gelockte tabel).")
    if "split_factor" in cols and "share_factor" in cols:
        try:
            cursor.execute("UPDATE stock_splits SET share_factor = split_factor WHERE share_factor IS NULL")
            conn.commit()
        except Exception:
            conn.rollback()
            print("stock_splits update share_factor overgeslagen (gelinkte/gelockte tabel).")
    if "share_factor" in cols and "price_factor" in cols:
        try:
            cursor.execute(
                """
                UPDATE stock_splits
                SET price_factor = IIF(share_factor IS NULL OR share_factor = 0, Null, 1 / share_factor)
                WHERE price_factor IS NULL
                """
            )
            conn.commit()
        except Exception:
            conn.rollback()
            print("stock_splits update price_factor overgeslagen (gelinkte/gelockte tabel).")


def ensure_per_dag_asset_result_v2_schema(cursor, conn) -> None:
    if not table_exists(cursor, "per_dag_asset_result_v2"):
        return
    try:
        cols = column_names(cursor, "per_dag_asset_result_v2")
    except Exception:
        return
    add_map = {
        "gesloten_opties": "ALTER TABLE per_dag_asset_result_v2 ADD COLUMN gesloten_opties CURRENCY",
        "gesloten_sprinters": "ALTER TABLE per_dag_asset_result_v2 ADD COLUMN gesloten_sprinters CURRENCY",
        "dividend_v2": "ALTER TABLE per_dag_asset_result_v2 ADD COLUMN dividend_v2 CURRENCY",
        "dividend_belasting_v2": "ALTER TABLE per_dag_asset_result_v2 ADD COLUMN dividend_belasting_v2 CURRENCY",
    }
    for col, stmt in add_map.items():
        if col not in cols:
            try:
                cursor.execute(stmt)
                conn.commit()
            except Exception:
                conn.rollback()
                print(f"per_dag_asset_result_v2 schema-migratie overgeslagen voor {col}.")


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

        ensure_stock_splits_schema(cursor, conn)
        ensure_per_dag_asset_result_v2_schema(cursor, conn)

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
