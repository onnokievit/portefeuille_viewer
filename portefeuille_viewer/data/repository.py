import contextlib
import pandas as pd
import pyodbc
import polars as pl

from datetime import date, datetime, timedelta
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.config import get_databases, get_default_database, get_settings
from portefeuille_viewer.signals import signals
from portefeuille_viewer.domain.engine import compact_float64


# from portefeuille_viewer.data import live_aggregator_asset_rollup_data

import warnings # importeer warnings module om waarschuwingen te beheren
warnings.filterwarnings("ignore", category=UserWarning, module="pandas") # onderdruk specifieke waarschuwingen van pandas
warnings.filterwarnings("ignore", category=UserWarning)

# ------------------------------------------------------------
# Database configuratie (dynamisch geladen uit settings.ini)
# ------------------------------------------------------------
def _load_db_config():
    """Laad database configuratie uit settings.ini."""
    databases = get_databases()
    db_map = {name: db["path"] for name, db in databases.items()}
    db_styles = {name: {"fg": db["fg_color"], "bg": db["bg_color"]} 
    for name, db in databases.items()}
    return db_map, db_styles

DB_MAP, DB_STYLES = _load_db_config()
DEFAULT_DB_NAME = get_default_database()
db_path = DB_MAP.get(DEFAULT_DB_NAME, "") if DEFAULT_DB_NAME else ""
conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path};" if db_path else ""
# Tabelnaam voor optienotities; verwacht kolommen: uniek_id (TEXT, PK), comment (MEMO/TEXT), updated_at (DATETIME)
OPEN_OPTIE_COMMENTS_TABLE = "open_optie_comments"
OPEN_OPTIE_COMMENTS_TEXTCOLOR_COLUMNS = ("tekstcolor", "textcolor")
OPEN_OPTIE_COMMENTS_TEXTCOLOR_COL = None

def reload_db_config():
    """Herlaad database configuratie na wijzigingen in settings."""
    global DB_MAP, DB_STYLES, DEFAULT_DB_NAME, db_path, conn_str
    DB_MAP, DB_STYLES = _load_db_config()
    DEFAULT_DB_NAME = get_default_database()
    db_path = DB_MAP.get(DEFAULT_DB_NAME, "") if DEFAULT_DB_NAME else ""
    conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path};" if db_path else ""
    print(f"🔄 Database config herladen: {len(DB_MAP)} databases, default: {DEFAULT_DB_NAME}")

def switch_database(name: str):
    """Schakel naar een andere database."""
    global db_path, conn_str
    if name not in DB_MAP:
        raise ValueError(f"Onbekende database: {name}")
    # flush eventuele dirty comments naar huidige DB voordat we overschakelen
    with contextlib.suppress(Exception):
        flush_dirty_open_optie_comments_to_db()
    # flush dirty test orders naar huidige DB
    with contextlib.suppress(Exception):
        from portefeuille_viewer.data.test_order_repository import flush_dirty_test_orders_to_db
        flush_dirty_test_orders_to_db()
    new_path = DB_MAP[name]
    test_conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={new_path};"
    with pyodbc.connect(test_conn_str):  # test connectie
        pass
    db_path = new_path
    conn_str = test_conn_str
    # reset comment-cache zodat nieuwe DB geladen wordt
    try:
        SNAPSHOT_STORE.repository_snapshot_open_optie_comments = None
        SNAPSHOT_STORE.repository_dirty_open_optie_comments = []
    except Exception:
        pass
    try:
        SNAPSHOT_STORE.repository_snapshot_test_orders_cache = {}
        SNAPSHOT_STORE.repository_dirty_test_orders_assets = set()
    except Exception:
        pass
    # Sla ook de actieve database-naam op in de snapshot store voor UI-consumptie
    try:
        SNAPSHOT_STORE.active_database_name = name
    except Exception:
        # Niet kritisch, maar nuttig om te weten tijdens debugging
        print(f"Waarschuwing: kon SNAPSHOT_STORE.active_database_name niet instellen op {name}")
    else:
        # Emit central databaseChanged signal so UI can react (queued to main thread)
        with contextlib.suppress(Exception):
            signals.queued_emit_databaseChanged(name)

# ------------------------------------------------------------
# ################ Snapshot store loaders ####################
# ------------------------------------------------------------

# ------------------------------------------------------------
# asset_rollup_data referentie tabel ophalen
# ------------------------------------------------------------
def load_asset_rollup_data() -> pl.DataFrame:
    """
    Laadt de asset_rollup_data-tabel uit de database.
    """
    sql = "SELECT * FROM asset_rollup_data"
    # sql = "SELECT Id,asset_rollup, value_grow, sector, type, regio, ib_symbol, ib_currency, exchange, prim_exchange, INCL_EXCL FROM asset_rollup_data"
    with get_connection() as conn:
        df = pl.read_database(sql, conn)
    SNAPSHOT_STORE.safe_write("repository_snapshot_asset_rollup_data", df)
    return compact_float64(df)

# ------------------------------------------------------------
# asset_rollup_data referentie tabel ophalen
# ------------------------------------------------------------
def load_per_dag_asset_result() -> pl.DataFrame:
    """
    Laadt per-dag result voor UI op v2-basis met v1-compatibele kolomnamen.
    """
    df_v2 = getattr(SNAPSHOT_STORE, "repository_snapshot_per_dag_asset_result_v2", None)
    df_close = getattr(SNAPSHOT_STORE, "repository_snapshot_historical_close", None)

    if df_v2 is not None and df_close is not None and df_v2.height > 0:
        left = df_v2.select(
            [
                pl.col("datum").cast(pl.Date, strict=False).alias("datum"),
                pl.col("asset_rollup"),
                pl.col("totaal_v2").cast(pl.Float64, strict=False).alias("totaal"),
                pl.col("totaal_aantal_bezit_v2").cast(pl.Float64, strict=False).alias("totaal_aantal_bezit"),
            ]
        )
        right = df_close.select(
            [
                pl.col("datum").cast(pl.Date, strict=False).alias("datum"),
                pl.col("asset_rollup"),
                pl.col("close_price").cast(pl.Float64, strict=False).alias("close_price"),
            ]
        )
        df = left.join(right, on=["datum", "asset_rollup"], how="left").select(
            ["datum", "asset_rollup", "close_price", "totaal_aantal_bezit", "totaal"]
        )
    else:
        sql = """
            SELECT
                r.datum,
                r.asset_rollup,
                hp.close_price AS close_price,
                r.totaal_aantal_bezit_v2 AS totaal_aantal_bezit,
                r.totaal_v2 AS totaal
            FROM
                per_dag_asset_result_v2 AS r
                LEFT JOIN (
                    SELECT
                        datum,
                        asset_rollup,
                        MAX([close]) AS close_price
                    FROM
                        historical_data_correct
                    GROUP BY
                        datum,
                        asset_rollup
                ) AS hp
                    ON r.datum = hp.datum
                    AND r.asset_rollup = hp.asset_rollup
            ORDER BY
                r.asset_rollup,
                r.datum
        """
        with get_connection() as conn:
            df = pl.read_database(sql, conn)
    SNAPSHOT_STORE.safe_write("repository_per_dag_asset_result", df)
    return compact_float64(df)


def load_historical_close_snapshot() -> pl.DataFrame:
    """
    Laad minimale historical close-data in memory voor snelle chart-opbouw.
    """
    sql = """
        SELECT
            datum,
            asset_rollup,
            [close] AS close_price
        FROM historical_data_correct
        WHERE asset_rollup IS NOT NULL
    """
    with get_connection() as conn:
        df = pl.read_database(sql, conn)
    SNAPSHOT_STORE.safe_write("repository_snapshot_historical_close", df)
    return compact_float64(df)


def load_per_dag_asset_result_v2_snapshot() -> pl.DataFrame:
    """
    Laad minimale v2 dagresultaten in memory voor snelle chart-opbouw.
    """
    sql = """
        SELECT
            datum,
            asset_rollup,
            totaal_v2,
            totaal_aantal_bezit_v2
        FROM per_dag_asset_result_v2
        WHERE asset_rollup IS NOT NULL
    """
    with get_connection() as conn:
        df = pl.read_database(sql, conn)
    SNAPSHOT_STORE.safe_write("repository_snapshot_per_dag_asset_result_v2", df)
    return compact_float64(df)

# ------------------------------------------------------------
# sprinter_refenctie_data referentie tabel ophalen
# # ------------------------------------------------------------
def load_sprinter_referentie_data() -> pl.DataFrame:
    """
    Laadt de sprinter referentie tabel  uit de database.
    """
    sql = "SELECT * FROM sprinters_referentie_data"
    with get_connection() as conn:
        df = pl.read_database(sql, conn)
    SNAPSHOT_STORE.safe_write("repository_snapshot_sprinter_referentie_data", df)
    # return compact_float64(df)

# ------------------------------------------------------------
# OPTIE_refenctie_data referentie tabel ophalen
# # ------------------------------------------------------------
def load_optie_referentie_data() -> pl.DataFrame:
    """
    Laadt de sprinter referentie tabel  uit de database.
    """
    sql = "SELECT * FROM optie_referentie_data"
    with get_connection() as conn:
        df = pl.read_database(sql, conn)
    SNAPSHOT_STORE.safe_write("repository_snapshot_optie_referentie_data", df)
    # return compact_float64(df)


# ------------------------------------------------------------
# OPTIE_refenctie_data referentie tabel ophalen
# ------------------------------------------------------------
def load_dividend_data() -> pl.DataFrame:
    """
    Laadt de dividend tabel  uit de database.
    """
    sql = "SELECT * FROM fees_dividend"
    with get_connection() as conn:
        df = pl.read_database(sql, conn)

    # return compact_float64(df)

    df = (
        df.filter(pl.col("fee_type").is_in(["dividend", "div_belasting"]))
        .rename({"asset": "asset_rollup"})
        .group_by(["broker", "asset_rollup"])
        .agg([
            pl.sum("amount").alias("div_en_bel"),
        ])
    )
    SNAPSHOT_STORE.safe_write("repository_portfolio_dividend", df)


# ------------------------------------------------------------
# transacties laden
# ------------------------------------------------------------

def load_alle_transacties() -> pl.DataFrame:
    """
    Laadt alle transacties uit de database.
    """
    sql = "SELECT * FROM transacties_bron_data"  # vervang door jouw Access-query
    schema_overrides = {
        "aantal": pl.Decimal(18, 3),
        "transactie_aantal": pl.Decimal(18, 3),
        "transactie_prijs": pl.Decimal(18, 4),
        "transactie_fee": pl.Decimal(18, 4),
        "transactie_euro_totaal": pl.Decimal(18, 4),
        "optie_strike": pl.Decimal(18, 4),
        "multiplier_close_price": pl.Decimal(18, 6),
        "order_id": pl.Decimal(18, 0),
        "order_id_number": pl.Decimal(18, 0),
    }
    with get_connection() as conn:
        df = pl.read_database(sql, conn, schema_overrides=schema_overrides)
    compact_float64(df)
    SNAPSHOT_STORE.safe_write("repository_snapshot_alle_transacties", df)
    
    

# ------------------------------------------------------------
# Aandelen, zowel open als gesloten
# ------------------------------------------------------------
def load_aandelen_from_tx(df_tx: pl.DataFrame | None = None) -> pl.DataFrame:
    if df_tx is None:
        if SNAPSHOT_STORE.repository_snapshot_alle_transacties is None:
            raise ValueError("Transactiedata is niet geladen in SnapshotStore.")
        df_tx = SNAPSHOT_STORE.repository_snapshot_alle_transacties

    # Koop-aggregatie
    df_koop = (
        df_tx.filter((pl.col("asset_type") == "aandeel") & (pl.col("transactie_type") == "koop"))
        .group_by(["broker", "asset_rollup", "asset_type"])
        .agg([
            pl.sum("transactie_aantal").alias("aantal_koop"),
            pl.sum("transactie_euro_totaal").alias("euro_koop"),
            pl.sum("transactie_fee").alias("fee_koop"),
        ])
    )

    # Verkoop-aggregatie
    df_verkoop = (
        df_tx.filter((pl.col("asset_type") == "aandeel") & (pl.col("transactie_type") == "verkoop"))
        .group_by(["broker", "asset_rollup", "asset_type"])
        .agg([
            pl.sum("transactie_aantal").alias("aantal_verkoop"),
            pl.sum("transactie_euro_totaal").alias("euro_verkoop"),
            pl.sum("transactie_fee").alias("fee_verkoop"),
        ])
    )

    # Verzamel alle unieke asset keys uit beide kanten (koop en verkoop)
    koop_keys = df_koop.select(["broker", "asset_rollup", "asset_type"])
    verkoop_keys = df_verkoop.select(["broker", "asset_rollup", "asset_type"])
    all_keys = pl.concat([koop_keys, verkoop_keys]).unique()

    # Outer join koop en verkoop op alle unieke asset keys
    df = all_keys
    df = df.join(df_koop, on=["broker", "asset_rollup", "asset_type"], how="left")
    df = df.join(df_verkoop, on=["broker", "asset_rollup", "asset_type"], how="left")
    df = df.fill_null(0)

    df = df.with_columns([
        (pl.col("aantal_koop") + pl.col("aantal_verkoop")).alias("aantal_bezit"),
        (pl.col("fee_koop") + pl.col("fee_verkoop")).alias("eq_total_fee"),
    ])
    SNAPSHOT_STORE.safe_write("repository_snapshot_aandelen", df)


# ------------------------------------------------------------
# Open opties
# ------------------------------------------------------------
def load_open_opties_from_tx(df_tx: pl.DataFrame | None = None) -> pl.DataFrame:
    """
    Bouwt de dataset 'open opties' na volgens de Access-query:
    SELECT ... FROM transacties_bron_data
    GROUP BY ...
    HAVING asset_type='optie' AND exp_date>=Date() AND SUM(aantal)<>0
    """

    if df_tx is None:
        if SNAPSHOT_STORE.repository_snapshot_alle_transacties is None:
            raise ValueError("Transactiedata is niet geladen in SnapshotStore.")
        df_tx = SNAPSHOT_STORE.repository_snapshot_alle_transacties

    # df_tx = df_tx.filter(pl.col("transactie_oorsprong") != "HEDGE")

    vandaag = date.today()

    # --- Eerste aggregatie (overeenkomend met Access GROUP BY) ---
    per_uniek = (
        df_tx
        .group_by([
            
            "uniek_id",
            "broker",
            "asset_rollup",
            "asset_type",
            "optie_exp_date",
            "optie_strike",
            "optie_call_put"
        ])
        .agg([
            pl.sum("transactie_fee").alias("SomVantransactie_fee"),
            pl.sum("transactie_euro_totaal").alias("SomVantransactie_euro_totaal"),
            pl.sum("transactie_aantal").alias("SomVantransactie_aantal"),
            (pl.col("optie_strike") * pl.col("transactie_aantal")).sum().alias("optie_waarde")
        ])
    )

    # HAVING filter: alleen openstaande opties (exp_date >= vandaag, som(aantal) ≠ 0) ---
    per_uniek_filtered = per_uniek.filter(
        (pl.col("asset_type") == "optie")
        & (pl.col("optie_exp_date") >= vandaag)
        & (pl.col("SomVantransactie_aantal") != 0)
        
    )
    
    SNAPSHOT_STORE.safe_write("repository_snapshot_load_open_opties", per_uniek_filtered)
    #return per_uniek_filtered





# ------------------------------------------------------------
# Gesloten opties
# ------------------------------------------------------------
def load_gesloten_opties_from_tx(df_tx: pl.DataFrame | None = None) -> pl.DataFrame:
    """
    Bouwt de dataset 'gesloten opties' na volgens de Access-querylogica:
    1. Groepeer transacties per uniek_id, broker, asset_rollup, exp_date, strike, call_put.
    2. Bereken sommen van aantal, fee, euro_totaal.
    3. Filter alleen 'optie' waarvan:
       - exp_date < vandaag,  of
       - som(transactie_aantal) == 0.
    4. Groepeer opnieuw per broker + asset_rollup om series op te rollen.
    """

    if df_tx is None:
        if SNAPSHOT_STORE.repository_snapshot_alle_transacties is None:
            raise ValueError("Transactiedata is niet geladen in SnapshotStore.")
        df_tx = SNAPSHOT_STORE.repository_snapshot_alle_transacties

    vandaag = date.today()

    # --- Eerste aggregatie (komt overeen met Opties_closed_series_opgerold_op_uniek_id) ---
    per_uniek = (
        df_tx
        .group_by([
            "uniek_id",
            "broker",
            "asset_rollup",
            "asset_type",
            "optie_exp_date",
            "optie_strike",
            "optie_call_put"
        ])
        .agg([
            pl.sum("transactie_fee").alias("SomVantransactie_fee"),
            pl.sum("transactie_euro_totaal").alias("SomVantransactie_euro_totaal"),
            pl.sum("transactie_aantal").alias("SomVantransactie_aantal")
        ])
    )

    # --- Filter volgens HAVING-voorwaarden ---
    per_uniek_filtered = per_uniek.filter(
        (pl.col("asset_type") == "optie")
        & (
            (pl.col("optie_exp_date") < vandaag)
            | (pl.col("SomVantransactie_aantal") == 0)
        )
    )

    # --- Tweede aggregatie (komt overeen met 2e Access-query) ---
    df_final = (
        per_uniek_filtered
        .group_by(["broker", "asset_rollup"])
        .agg([
            pl.sum("SomVantransactie_fee").alias("clos_opt_transactie_fee"),
            pl.sum("SomVantransactie_euro_totaal").alias("clos_opt_transactie_euro_totaal"),
            pl.sum("SomVantransactie_aantal").alias("SomVanSomVantransactie_aantal")
        ])
        .sort(["broker", "asset_rollup"])
    )
    SNAPSHOT_STORE.safe_write("repository_snapshot_gesloten_opties", df_final)
    # return df_final

# ------------------------------------------------------------
# Gesloten opties zonder broker
# ------------------------------------------------------------

def load_gesloten_opties_no_broker() -> pl.DataFrame:
    """
    Voer een verdere aggregatie uit op snapshot_gesloten_opties, gegroepeerd op asset_rollup.
    Sla het resultaat op in snapshot_gesloten_opties_no_broker.
    """
    if SNAPSHOT_STORE.repository_snapshot_gesloten_opties is None:
        raise ValueError("snapshot_gesloten_opties is niet geladen in SnapshotStore.")

    # Voer aggregatie uit op asset_rollup
    df_final = (
        SNAPSHOT_STORE.repository_snapshot_gesloten_opties
        .group_by("asset_rollup")
        .agg([
            pl.sum("clos_opt_transactie_fee").alias("clos_opt_transactie_fee"),
            pl.sum("clos_opt_transactie_euro_totaal").alias("clos_opt_transactie_euro_totaal"),
        ])
        .sort("asset_rollup")
    )

    # Sla het resultaat op in snapshot_gesloten_opties_no_broker
    SNAPSHOT_STORE.safe_write("repository_snapshot_gesloten_opties_no_broker", df_final)
    return df_final


# ------------------------------------------------------------
# open sprinters
# ------------------------------------------------------------

def load_open_sprinters_from_tx(df_tx: pl.DataFrame | None = None) -> pl.DataFrame:
    """
    Bouwt de dataset 'open sprinters' na volgens de Access-query:
    SELECT ... FROM transacties_bron_data
    GROUP BY ...
    HAVING asset_type='sprinter' AND  SUM(aantal)<>0
    """

    if df_tx is None:
        if SNAPSHOT_STORE.repository_snapshot_alle_transacties is None:
            raise ValueError("Transactiedata is niet geladen in SnapshotStore.")
        df_tx = SNAPSHOT_STORE.repository_snapshot_alle_transacties

    

    

    # --- Eerste aggregatie (overeenkomend met Access GROUP BY) ---
    per_uniek = (
        df_tx
        .group_by([
            "uniek_id",
            "broker",
            "asset_rollup",
            "asset_detail",
            "asset_type",
            "optie_exp_date",
            "optie_strike",
            "optie_call_put"
        ])
        .agg([
            pl.sum("transactie_fee").alias("SomVantransactie_fee"),
            pl.sum("transactie_euro_totaal").alias("SomVantransactie_euro_totaal"),
            pl.sum("transactie_aantal").alias("SomVantransactie_aantal"),
            (pl.col("optie_strike") * pl.col("transactie_aantal")).sum().alias("optie_waarde")
        ])
    )

    # HAVING filter: alleen openstaande opties (exp_date >= vandaag, som(aantal) ≠ 0) ---
    per_uniek_filtered = per_uniek.filter(
        (pl.col("asset_type") == "sprinter")
        & (pl.col("SomVantransactie_aantal") != 0)
    )
    # SNAPSHOT_STORE.repository_snapshot_open_sprinters = per_uniek_filtered
    SNAPSHOT_STORE.safe_write("repository_snapshot_open_sprinters", per_uniek_filtered)
    #return per_uniek_filtered

    ######################### DEBUG CODE om het totaal te checken van open sprinters#
    #     # Functie: totaal euro gesloten sprinters
    # def print_sprinter_gesloten_euro_totaal(df): ######################### DEBUG CODE om het totaal te checken van open sprinters#
    #     if df is not None and "SomVantransactie_euro_totaal" in df.columns:
    #         totaal = df["SomVantransactie_euro_totaal"].sum()
    #         print(f"euro totaal open sprinters = {totaal}")
    #     else:
    #         print("Geen euro totaal open sprinters beschikbaar.")

    # print_sprinter_gesloten_euro_totaal(per_uniek_filtered)



# ------------------------------------------------------------
# Gesloten sprinters
# ------------------------------------------------------------

def load_gesloten_sprinters_from_tx(df_tx: pl.DataFrame | None = None) -> pl.DataFrame:
    """
    Bouwt de dataset 'gesloten sprinters' na volgens de Access-querylogica:
    1. Groepeer transacties per uniek_id, broker, asset_rollup, exp_date, strike, call_put.
    2. Bereken sommen van aantal, fee, euro_totaal.
    3. Filter alleen 'optie' waarvan:
       - exp_date < vandaag,  of
       - som(transactie_aantal) == 0.
    4. Groepeer opnieuw per broker + asset_rollup om series op te rollen.
    """

    if df_tx is None:
        if SNAPSHOT_STORE.repository_snapshot_alle_transacties is None:
            raise ValueError("Transactiedata is niet geladen in SnapshotStore.")
        df_tx = SNAPSHOT_STORE.repository_snapshot_alle_transacties

    

    # --- Eerste aggregatie (komt overeen met Opties_closed_series_opgerold_op_uniek_id) ---
    per_uniek = (
        df_tx
        .group_by([
            "uniek_id",
            "broker",
            "asset_rollup",
            "asset_detail",
            "optie_exp_date",
            "optie_strike",
            "asset_type",
        ])
        .agg([
            pl.sum("transactie_fee").alias("clos_sp_transactie_fee"),
            pl.sum("transactie_euro_totaal").alias("clos_opt_transactie_euro_totaal"),
            pl.sum("transactie_aantal").alias("SomVantransactie_aantal")
        ])
    )

    # --- Filter volgens HAVING-voorwaarden ---
    per_uniek_filtered = per_uniek.filter(
        (pl.col("asset_type") == "sprinter")
        & (
            (pl.col("SomVantransactie_aantal") == 0)
        )
    )

    # --- Tweede aggregatie (komt overeen met 2e Access-query) ---
    df_final = (
        per_uniek_filtered
        .group_by(["broker", "asset_rollup", "asset_detail"])
        .agg([
            pl.sum("clos_sp_transactie_fee").alias("clos_sp_transactie_fee"),
            pl.sum("clos_opt_transactie_euro_totaal").alias("clos_sp_transactie_euro_totaal"),
            
        ])
        .sort(["broker", "asset_rollup"])
    )
    SNAPSHOT_STORE.safe_write("repository_snapshot_gesloten_sprinters", df_final)

    df_no_asset_detail = (
        df_final
        .group_by(["broker", "asset_rollup"])
        .agg([
            pl.sum("clos_sp_transactie_fee").alias("clos_sp_transactie_fee"),
            pl.sum("clos_sp_transactie_euro_totaal").alias("clos_sp_transactie_euro_totaal"),
        ])
        .sort(["broker", "asset_rollup"])
    )
    SNAPSHOT_STORE.safe_write("repository_snapshot_gesloten_sprinters_no_asset_detail", df_no_asset_detail)

    # return df_final


    ######################### DEBUG CODE om het totaal te checken van gesloten sprinters#
    # # Functie: totaal euro gesloten sprinters
    # def print_sprinter_gesloten_euro_totaal(df):
    #     if df is not None and "SomVanSomVantransactie_euro_totaal" in df.columns:
    #         totaal = df["SomVanSomVantransactie_euro_totaal"].sum()
    #         print(f"euro totaal gesloten sprinters = {totaal}")
    #     else:
    #         print("Geen euro totaal gesloten sprinters beschikbaar.")

    # print_sprinter_gesloten_euro_totaal(df_final)



# ------------------------------------------------------------
# ############## EINDE Snapshot store loaders
# ------------------------------------------------------------




asset_types = ["aandeel", "optie", "sprinter"]
transactie_types = ["koop", "verkoop"]
transactie_oorsprong = ["OPEN", "CLOSE", "ASSIGN", "EXPIRE", "DOORROL", "STOCKSPLIT", "EXERCISE"]

TABLE_COLS = [
    "Id","datum","transactie_oorsprong","broker","asset_rollup","asset_type",
    "transactie_type","asset_detail","optie_exp_date","optie_strike","optie_call_put",
    "aantal","transactie_prijs","transactie_fee","uniek_id","transactie_oorsprong_detail"
]

def get_connection():
    return pyodbc.connect(conn_str)

def insert_transaction(data: dict) -> int:
    """Nieuwe transactie invoegen en Id teruggeven."""
    data = dict(data)
    data.pop("uniek_id", None)
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    values = list(data.values())
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"INSERT INTO transacties_bron_data_org ({cols}) VALUES ({placeholders})",
            values
        )
        cursor.execute("SELECT @@IDENTITY")
        new_id = cursor.fetchone()[0]
        conn.commit()
    # Emit centraal signaal na insert
    with contextlib.suppress(Exception):
        signals.ordersCommitted.emit()
    return new_id


def delete_transactions_by_order_id(order_id: str) -> int:
    """
    Verwijder alle transacties met een specifieke order_id.
    Retourneert het aantal verwijderde records.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM transacties_bron_data_org WHERE order_id = ?",
            (order_id,)
        )
        deleted_count = cursor.rowcount
        conn.commit()
    return deleted_count


def delete_transactions_by_ids(ids_to_delete: list) -> int:
    """
    Verwijder transacties met specifieke Id's.
    Retourneert het aantal verwijderde records.
    """
    if not ids_to_delete:
        return 0

    with get_connection() as conn:
        deleted_count = _extracted_from_delete_transactions_by_ids_10(
            conn, ids_to_delete
        )
    # Emit centraal signaal na delete
    with contextlib.suppress(Exception):
        signals.ordersCommitted.emit()
    return deleted_count


# TODO Rename this here and in `delete_transactions_by_ids`
def _extracted_from_delete_transactions_by_ids_10(conn, ids_to_delete):
    cursor = conn.cursor()
    # Maak placeholders voor IN clause
    placeholders = ",".join("?" * len(ids_to_delete))
    sql = f"DELETE FROM transacties_bron_data_org WHERE Id IN ({placeholders})"
    cursor.execute(sql, ids_to_delete)
    result = cursor.rowcount
    conn.commit()
    return result


##############################versie met build_where_and_params, niet meer nodig omdat client side filtering goed genoeg is
def get_distinct_values(column: str, table: str = "transacties_bron_data_org", base_filters: dict | None = None) -> list:
    """
    Haal unieke waarden voor één kolom op.
    - base_filters: andere actieve filters meenemen (zodat de lijst contextgevoelig is).
    - None in de return staat voor '(Lege regels)'.
    """
    where_sql, params = _build_where_and_params(base_filters or {})
    # DISTINCT op de kolom, met andere filters toegepast
    with get_connection() as conn:
        sql = f"SELECT DISTINCT [{column}] AS v FROM [{table}] {where_sql} ORDER BY [{column}]"
        df = pd.read_sql(sql, conn, params=params)
    vals = []
    for x in df["v"].tolist():
        if pd.isna(x) or not str(x).strip():
            vals.append(None)
        else:
            vals.append(x)
    return vals




ALLOWED_SORT_COLS = {c: c for c in TABLE_COLS} # kan dit weg? aan chatgpt vragen

############### deze functie wordt gebruikt voor serverside side filtering. niet nodig omdat client side goed genoeg werkt, laten staan omdat het in de toekomst misschien nodig is
def _build_where_and_params(filters: dict | None) -> tuple[str, list]: 
    filters = filters or {}
    conds, params = [], []
    ar = (filters.get("asset_rollup") or "").strip()
    if ar:
        conds.append("asset_rollup = ?")
        params.append(ar)
    q = (filters.get("q") or "").strip()
    if q:
        like = f"%{q}%"
        conds.append("(broker LIKE ? OR asset_rollup LIKE ? OR asset_detail LIKE ? OR uniek_id LIKE ?)")
        params.extend([like, like, like, like])
        # --- GENERIEKE filters via key-prefixen ---
    #  - "__in__kolom": lijst → IN (...)  (+ optioneel lege regels via None)
    #  - "__eq__kolom": exact gelijk
    #  - "__contains__kolom": LIKE %...%
    #  - "__startswith__kolom": LIKE ...%
    #  - "__endswith__kolom": LIKE %...
    #  - "__date_on__kolom": dag = [d, d+1)
    #  - "__date_between__kolom": (d1, d2) inclusief
    #  - "__gte__/__lte__kolom": grenswaarden
    for k, v in (filters or {}).items():
        if not (isinstance(k, str) and k.startswith("__")):
            continue
        try:
            op, col = k.strip("_").split("__", 1)
        except ValueError:
            continue
        col = col.strip()

        if op == "in" and isinstance(v, (list, tuple, set)) and v:
            vs = list(v)
            def _is_blank(val):
                # lege string óf een ontbrekende waarde (None/NaN/pd.NA/NaT)
                return (isinstance(val, str) and val.strip() == "") or pd.isna(val)

            vs = list(v)
            blanks = any(_is_blank(x) for x in vs)
            vs_clean = [x for x in vs if not _is_blank(x)]
            parts = []
            if vs_clean:
                placeholders = ",".join(["?"] * len(vs_clean))
                parts.append(f"[{col}] IN ({placeholders})")
                params.extend(vs_clean)
            if blanks:
                parts.append(f"([{col}] IS NULL OR [{col}] = '')")
            if parts:
                conds.append("(" + " OR ".join(parts) + ")")

        elif op == "eq":
            conds.append(f"[{col}] = ?")
            params.append(v)

        elif op == "contains":
            conds.append(f"[{col}] LIKE ?")
            params.append(f"%{v}%")

        elif op == "startswith":
            conds.append(f"[{col}] LIKE ?")
            params.append(f"{v}%")

        elif op == "endswith":
            conds.append(f"[{col}] LIKE ?")
            params.append(f"%{v}")

        elif op == "date_on":
            d = _parse_date(v)
            if d:
                conds.append(f"([{col}] >= ? AND [{col}] < ?)")
                params.extend([d, d + timedelta(days=1)])

        elif op == "date_between":
            if isinstance(v, (list, tuple)) and len(v) >= 2:
                d1 = _parse_date(v[0])
                d2 = _parse_date(v[1])
                if d1 and d2:
                    conds.append(f"[{col}] BETWEEN ? AND ?")
                    params.extend([d1, d2])

        elif op == "gte":
            conds.append(f"[{col}] >= ?")
            params.append(v)

        elif op == "lte":
            conds.append(f"[{col}] <= ?")
            params.append(v)
    
    where_sql = (" WHERE " + " AND ".join(conds)) if conds else ""
    return where_sql, params

def _order_by_for_seek(col: str, direction: str) -> str: ########################## niet genoemd door chatgpt om te blijven?
    col_db = ALLOWED_SORT_COLS.get(col, "Id")
    dirn = "DESC" if direction.upper() == "DESC" else "ASC"
    return f" ORDER BY {col_db} {dirn}, Id {dirn}"

def _seek_predicate(col: str, direction: str) -> str: ########################## niet genoemd door chatgpt om te blijven?
    col_db = ALLOWED_SORT_COLS.get(col, "Id")
    dirn = direction.upper()
    if dirn == "ASC":
        return f"(({col_db} > ?) OR ({col_db} = ? AND Id > ?))"
    else:
        return f"(({col_db} < ?) OR ({col_db} = ? AND Id < ?))"

def fetch_records_page( ################## dit is de oude versie van fetch_records_page, met build_where_and_params. 
    table: str = "transacties_bron_data_org",
    sort_col: str = "Id",
    sort_dir: str = "DESC",
    limit: int = 200,
    filters: dict | None = None,
    seek_value=None,
    seek_id: int | None = None,
) -> pd.DataFrame:
    where_sql, params = _build_where_and_params(filters)
    with get_connection() as conn:
        if seek_value is None or seek_id is None:
            sql = f"""
                SELECT TOP {limit} *
                FROM [{table}]
                {where_sql}
                {_order_by_for_seek(sort_col, sort_dir)}
            """
            return pd.read_sql(sql, conn, params=params)
        else:
            pred = _seek_predicate(sort_col, sort_dir)
            where2 = where_sql + (" AND " if where_sql else " WHERE ") + pred
            sql = f"""
                SELECT TOP {limit} *
                FROM [{table}]
                {where2}
                {_order_by_for_seek(sort_col, sort_dir)}
            """
            return pd.read_sql(sql, conn, params=[*params, seek_value, seek_value, int(seek_id)])


def load_reference_lists():
    """Haal lijsten voor comboboxen op."""
    try:
        brokers = get_settings().get_brokers()
        with get_connection() as conn:
            if not brokers:
                brokers = pd.read_sql(
                    "SELECT DISTINCT broker FROM transacties_bron_data_org",
                    conn,
                )["broker"].dropna().astype(str).tolist()
            rollups = pd.read_sql("SELECT DISTINCT asset_rollup FROM asset_rollup_data", conn)["asset_rollup"].dropna().astype(str).tolist()
            sprinters = pd.read_sql("SELECT DISTINCT asset_detail FROM sprinters_referentie_data", conn)["asset_detail"].dropna().astype(str).tolist()
    except Exception:
        brokers, rollups, sprinters = [], [], []
    return brokers, rollups, sprinters

def _sanitize_update_dict(d: dict) -> dict:
    d = dict(d or {})
    d.pop("uniek_id", None)
    d.pop("order_id", None)
    d.pop("order_id_number", None)
    return d

def _build_set_clause_and_params(d: dict):
    cols = list(d.keys())
    if not cols:
        return "", []
    sets = ", ".join(f"{c} = ?" for c in cols)
    params = [d[c] for c in cols]
    return sets, params

def update_transactions_atomic(record_id1: int, data1: dict, record_id2: int | None = None, data2: dict | None = None):
    """
    Voer een update uit op één of twee records (binnen dezelfde transactie).
    Als beide updates mislukken wordt een rollback gedaan.
    """
    d1 = _sanitize_update_dict(data1)
    d2 = _sanitize_update_dict(data2) if (record_id2 is not None and data2 is not None) else None
    if not d1 and not d2:
        return
    with get_connection() as conn:
        cur = conn.cursor()
        try:
            if d1:
                sets1, params1 = _build_set_clause_and_params(d1)
                cur.execute(f"UPDATE transacties_bron_data_org SET {sets1} WHERE Id = ?", params1 + [record_id1])

            if record_id2 is not None and d2:
                sets2, params2 = _build_set_clause_and_params(d2)
                cur.execute(f"UPDATE transacties_bron_data_org SET {sets2} WHERE Id = ?", params2 + [record_id2])

            conn.commit()
        except pyodbc.Error:
            conn.rollback()
            raise
    # Emit centraal signaal na update
    with contextlib.suppress(Exception):
        signals.ordersCommitted.emit()

def _clean(x): ########################## niet genoemd door chatgpt om te blijven?????? 
    return "" if x is None else str(x).strip()

def _parse_date(x):
    from datetime import date, datetime
    if x in (None, ""): 
        return None
    if isinstance(x, datetime): 
        return x.date()
    if isinstance(x, date): 
        return x
    s = str(x).strip().replace("\\", "/").replace("-", "/")
    p = s.split("/")
    try:
        if len(p) == 3:
            if len(p[0]) <= 2 and len(p[1]) <= 2:
                d, m, y = int(p[0]), int(p[1]), int(p[2])
                y = (2000+y) if y < 100 else y
                return date(y, m, d)
            if len(p[0]) == 4:
                y, m, d = int(p[0]), int(p[1]), int(p[2])
                return date(y, m, d)
    except Exception:
        return None
    return None

def parse_int_field(s):
    """Parseer een UI-veld naar int of None. Accepteert '10', '10.0', '10,0'."""
    if s is None:
        return None
    s = str(s).strip().replace(",", ".")
    if not s:
        return None
    try:
        return int(float(s))
    except Exception:
        return None


def parse_float_field(s):
    """Parseer een UI-veld naar float of None. Accepteert '0.1', '0,1'."""
    if s is None:
        return None
    s = str(s).strip().replace(",", ".")
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None

def _date_for_id(x): ########################## niet genoemd door chatgpt om te blijven?
    d = _parse_date(x)
    return f"{d.day}-{d.month}-{d.year}" if d else ""

def _norm_dec_for_id(x): ########################## niet genoemd door chatgpt om te blijven?
    if x in (None, ""): 
        return ""
    s = str(x).strip().replace(",", ".")
    try:
        f = float(s)
        return str(int(f)) if f.is_integer() else f"{f}".rstrip("0").rstrip(".")
    except ValueError:
        return s

def build_uniek_id(values: dict) -> str:
    """Genereer uniek_id string op basis van transactievelden (zoals broker, rollup, type, enz.)."""
    broker = _clean(values.get("broker"))
    at = _clean(values.get("asset_type")).lower()
    if at == "optie":
        rollup = _clean(values.get("asset_rollup"))
        exp    = _date_for_id(values.get("optie_exp_date"))
        cp     = _clean(values.get("optie_call_put")).lower()
        strike = _norm_dec_for_id(values.get("optie_strike"))
        return f"{broker}-{rollup}-{at}-{exp}-{cp}-{strike}"
    if at == "sprinter":
        detail = _clean(values.get("asset_detail"))
        return f"{broker}-{detail}-{at}"
    if at == "aandeel":
        rollup = _clean(values.get("asset_rollup"))
        return f"{broker}-{rollup}-{at}"
    rollup = _clean(values.get("asset_rollup"))
    return f"{broker}-{rollup}-{at}"


def fetch_open_optie_comments(uniek_ids: list[str]) -> pl.DataFrame:
    """
    Haal commentaar per uniek_id uit cache; laadt cache uit DB indien nodig.
    Retourneert per uniek_id alleen de laatste entry (dagboekprincipe).
    Kolommen: uniek_id, optie_comment, optie_comment_color, optie_comment_textcolor, optie_comment_updated_at.
    """
    empty_df = pl.DataFrame({
        "uniek_id": pl.Series([], dtype=pl.Utf8),
        "optie_comment": pl.Series([], dtype=pl.Utf8),
        "optie_comment_color": pl.Series([], dtype=pl.Utf8),
        "optie_comment_textcolor": pl.Series([], dtype=pl.Utf8),
        "optie_comment_updated_at": pl.Series([], dtype=pl.Datetime),
    })
    if not uniek_ids:
        return empty_df

    if getattr(SNAPSHOT_STORE, "repository_snapshot_open_optie_comments", None) is None:
        load_open_optie_comments_cache()

    cached = getattr(SNAPSHOT_STORE, "repository_snapshot_open_optie_comments", None)
    if cached is None or cached.is_empty():
        print("[comments] cache leeg, geen comments beschikbaar")
        return empty_df
    try:
        df_filtered = cached.filter(pl.col("uniek_id").is_in(uniek_ids))
        if df_filtered.is_empty():
            return empty_df
        pl_df = (
            df_filtered
            .sort(["uniek_id", "optie_comment_updated_at"], descending=True, nulls_last=True)
            .group_by("uniek_id", maintain_order=True)
            .agg([
                pl.col("optie_comment").first().alias("optie_comment"),
                pl.col("optie_comment_color").first().alias("optie_comment_color"),
                pl.col("optie_comment_textcolor").first().alias("optie_comment_textcolor"),
                pl.col("optie_comment_updated_at").first().alias("optie_comment_updated_at"),
            ])
        )
        # print(f"[comments] fetched {pl_df.height} latest comments from cache for {len(uniek_ids)} ids")
        return pl_df
    except Exception as exc:
        print(f"[comments] fetch from cache failed: {exc}")
        return empty_df


def load_open_optie_comments_cache():
    """
    Laad volledige open_optie_comments tabel in cache (SNAPSHOT_STORE.repository_snapshot_open_optie_comments).
    """
    global OPEN_OPTIE_COMMENTS_TEXTCOLOR_COL
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            rows = None
            for col in OPEN_OPTIE_COMMENTS_TEXTCOLOR_COLUMNS:
                try:
                    cur.execute(
                        f"SELECT uniek_id, comment, color, {col}, updated_at FROM {OPEN_OPTIE_COMMENTS_TABLE}"
                    )
                    rows = cur.fetchall()
                    OPEN_OPTIE_COMMENTS_TEXTCOLOR_COL = col
                    break
                except Exception:
                    continue
            if rows is None:
                cur.execute(f"SELECT uniek_id, comment, color, updated_at FROM {OPEN_OPTIE_COMMENTS_TABLE}")
                rows = cur.fetchall()
                OPEN_OPTIE_COMMENTS_TEXTCOLOR_COL = None
    except Exception as exc:
        print(f"[comments] load cache failed: {exc}")
        SNAPSHOT_STORE.repository_snapshot_open_optie_comments = pl.DataFrame({
            "uniek_id": pl.Series([], dtype=pl.Utf8),
            "optie_comment": pl.Series([], dtype=pl.Utf8),
            "optie_comment_color": pl.Series([], dtype=pl.Utf8),
            "optie_comment_textcolor": pl.Series([], dtype=pl.Utf8),
            "optie_comment_updated_at": pl.Series([], dtype=pl.Datetime),
        })
        return

    normalized_rows = []
    for r in rows:
        try:
            if OPEN_OPTIE_COMMENTS_TEXTCOLOR_COL:
                if len(r) >= 5:
                    normalized_rows.append((r[0], r[1], r[2], r[3], r[4]))
                elif len(r) == 4:
                    normalized_rows.append((r[0], r[1], r[2], None, r[3]))
            else:
                if len(r) >= 4:
                    normalized_rows.append((r[0], r[1], r[2], "", r[3]))
                elif len(r) == 3:
                    normalized_rows.append((r[0], r[1], None, "", r[2]))
        except Exception as exc:
            print(f"[comments] skip row err={exc} value={r}")

    df = pd.DataFrame(
        normalized_rows,
        columns=[
            "uniek_id",
            "optie_comment",
            "optie_comment_color",
            "optie_comment_textcolor",
            "optie_comment_updated_at",
        ],
    )
    try:
        df["optie_comment_updated_at"] = pd.to_datetime(df["optie_comment_updated_at"], errors="coerce", dayfirst=True)
    except Exception:
        pass
    pl_df = pl.from_pandas(df).with_columns([
        pl.col("uniek_id").cast(pl.Utf8),
        pl.col("optie_comment").cast(pl.Utf8),
        pl.col("optie_comment_color").cast(pl.Utf8),
        pl.col("optie_comment_textcolor").cast(pl.Utf8),
    ])
    SNAPSHOT_STORE.repository_snapshot_open_optie_comments = pl_df
    # print(f"[comments] cache loaded: {pl_df.height} rows")


def upsert_open_optie_comment(
    uniek_id: str,
    comment: str,
    color: str | None = None,
    textcolor: str | None = None,
    updated_at=None,
) -> None:
    """
    Voeg een comment toe (append) voor een uniek_id in cache en markeer dirty voor DB flush.
    """
    if not uniek_id:
        return
    updated_at = updated_at or datetime.now()
    # zorg dat cache geladen is
    if getattr(SNAPSHOT_STORE, "repository_snapshot_open_optie_comments", None) is None:
        load_open_optie_comments_cache()

    new_row = {
        "uniek_id": uniek_id,
        "optie_comment": comment,
        "optie_comment_color": color or "",
        "optie_comment_textcolor": textcolor or "",
        "optie_comment_updated_at": updated_at,
    }
    # append aan cache
    try:
        df_cache = getattr(SNAPSHOT_STORE, "repository_snapshot_open_optie_comments", None)
        if df_cache is None or df_cache.is_empty():
            SNAPSHOT_STORE.repository_snapshot_open_optie_comments = pl.DataFrame(new_row)
        else:
            SNAPSHOT_STORE.repository_snapshot_open_optie_comments = pl.concat([df_cache, pl.DataFrame(new_row)], how="diagonal_relaxed")
    except Exception as exc:
        print(f"[comments] kon cache niet bijwerken: {exc}")

    # markeer dirty
    try:
        dirty_list = getattr(SNAPSHOT_STORE, "repository_dirty_open_optie_comments", None)
        if dirty_list is None:
            SNAPSHOT_STORE.repository_dirty_open_optie_comments = []
            dirty_list = SNAPSHOT_STORE.repository_dirty_open_optie_comments
        dirty_list.append(new_row)
    except Exception as exc:
        print(f"[comments] kon dirty list niet bijwerken: {exc}")

    with contextlib.suppress(Exception):
        signals.databaseChanged.emit()


def update_open_optie_comment_color(uniek_id: str, color: str | None, textcolor: str | None = None) -> None:
    """
    Werk alleen de kleur bij voor de laatste comment van een uniek_id.
    """
    if not uniek_id:
        return
    # zorg dat cache geladen is
    if getattr(SNAPSHOT_STORE, "repository_snapshot_open_optie_comments", None) is None:
        load_open_optie_comments_cache()

    # Update cache: laatste entry voor uniek_id aanpassen
    try:
        df_cache = getattr(SNAPSHOT_STORE, "repository_snapshot_open_optie_comments", None)
        if df_cache is not None and not df_cache.is_empty():
            df_sub = df_cache.filter(pl.col("uniek_id") == uniek_id)
            if not df_sub.is_empty():
                df_sub = df_sub.sort("optie_comment_updated_at", descending=True, nulls_last=True)
                latest_ts = df_sub["optie_comment_updated_at"][0] if "optie_comment_updated_at" in df_sub.columns else None
                df_cache = df_cache.with_columns([
                    pl.when(
                        (pl.col("uniek_id") == uniek_id)
                        & (pl.col("optie_comment_updated_at") == latest_ts)
                    )
                    .then(pl.lit(color or ""))
                    .otherwise(pl.col("optie_comment_color"))
                    .alias("optie_comment_color")
                ])
                if "optie_comment_textcolor" in df_cache.columns:
                    df_cache = df_cache.with_columns([
                        pl.when(
                            (pl.col("uniek_id") == uniek_id)
                            & (pl.col("optie_comment_updated_at") == latest_ts)
                        )
                        .then(pl.lit(textcolor or ""))
                        .otherwise(pl.col("optie_comment_textcolor"))
                        .alias("optie_comment_textcolor")
                    ])
                SNAPSHOT_STORE.repository_snapshot_open_optie_comments = df_cache
    except Exception as exc:
        print(f"[comments] kon kleur in cache niet bijwerken: {exc}")

    # markeer dirty met speciale mode zodat flush een UPDATE doet
    try:
        dirty_list = getattr(SNAPSHOT_STORE, "repository_dirty_open_optie_comments", None)
        if dirty_list is None:
            SNAPSHOT_STORE.repository_dirty_open_optie_comments = []
            dirty_list = SNAPSHOT_STORE.repository_dirty_open_optie_comments
        dirty_list.append({
            "mode": "color_only",
            "uniek_id": uniek_id,
            "color": color or "",
            "textcolor": textcolor or "",
        })
    except Exception as exc:
        print(f"[comments] kon dirty list niet bijwerken: {exc}")

    with contextlib.suppress(Exception):
        signals.databaseChanged.emit()


def flush_dirty_open_optie_comments_to_db():
    dirty = getattr(SNAPSHOT_STORE, "repository_dirty_open_optie_comments", None) or []
    if not dirty:
        return
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            for row in dirty:
                if row.get("mode") == "color_only":
                    if OPEN_OPTIE_COMMENTS_TEXTCOLOR_COL:
                        cur.execute(
                            f"UPDATE {OPEN_OPTIE_COMMENTS_TABLE} "
                            f"SET color = ?, {OPEN_OPTIE_COMMENTS_TEXTCOLOR_COL} = ? "
                            f"WHERE uniek_id = ? AND updated_at = (SELECT MAX(updated_at) FROM {OPEN_OPTIE_COMMENTS_TABLE} WHERE uniek_id = ?)",
                            (
                                row.get("color") or "",
                                row.get("textcolor") or "",
                                row.get("uniek_id"),
                                row.get("uniek_id"),
                            ),
                        )
                    else:
                        cur.execute(
                            f"UPDATE {OPEN_OPTIE_COMMENTS_TABLE} "
                            f"SET color = ? "
                            f"WHERE uniek_id = ? AND updated_at = (SELECT MAX(updated_at) FROM {OPEN_OPTIE_COMMENTS_TABLE} WHERE uniek_id = ?)",
                            (row.get("color") or "", row.get("uniek_id"), row.get("uniek_id")),
                        )
                else:
                    if OPEN_OPTIE_COMMENTS_TEXTCOLOR_COL:
                        cur.execute(
                            f"INSERT INTO {OPEN_OPTIE_COMMENTS_TABLE} (uniek_id, comment, color, {OPEN_OPTIE_COMMENTS_TEXTCOLOR_COL}, updated_at) VALUES (?, ?, ?, ?, ?)",
                            (
                                row.get("uniek_id"),
                                row.get("optie_comment"),
                                row.get("optie_comment_color"),
                                row.get("optie_comment_textcolor") or "",
                                row.get("optie_comment_updated_at"),
                            ),
                        )
                    else:
                        cur.execute(
                            f"INSERT INTO {OPEN_OPTIE_COMMENTS_TABLE} (uniek_id, comment, color, updated_at) VALUES (?, ?, ?, ?)",
                            (row.get("uniek_id"), row.get("optie_comment"), row.get("optie_comment_color"), row.get("optie_comment_updated_at")),
                        )
            conn.commit()
        SNAPSHOT_STORE.repository_dirty_open_optie_comments = []
        # print(f"[comments] flushed {len(dirty)} comments to DB")
    except Exception as exc:
        print(f"[comments] flush failed: {exc}")

def is_pairable(order: dict) -> bool:
    """
    Bepaal of een order koppelbaar is (d.w.z. dat er een tweede transactie bij hoort).
    Gebruikt het transactie_oorsprong veld.
    """
    oorspr = (order.get("transactie_oorsprong") or "").upper()
    return oorspr in {"DOORROL", "ASSIGN", "EXERCISE"}

def get_next_order_id() -> int:
    """
    Bepaalt het volgende beschikbare order_id in transacties_bron_data_org.
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT MAX(order_id) FROM transacties_bron_data_org")
        row = cur.fetchone()
        return (row[0] or 0) + 1

def get_next_order_item_no(order_id: int) -> int:
    """
    Bepaalt het volgende order_id_number (volgnummer binnen een order_id).
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT MAX(order_id_number) FROM transacties_bron_data_org WHERE order_id = ?", (order_id,)
        )
        row = cur.fetchone()
        return (row[0] or 0) + 1



def load_last_prices_dict():
    from portefeuille_viewer.data.repository import get_connection
    last_prices = {}
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT ib_symbol, ib_currency, price FROM asset_last_prices")
        for row in cursor.fetchall():
            symbol, currency, price = row
            last_prices[(symbol,currency)] = price
    # print(f"[DEBUG load last prices werkt] Loaded last_prices: {len(last_prices)} items, sample: {list(last_prices.items())[:5]}")
    return last_prices

def load_live_prices():
    """
    Laad de initiële live prijzen in SNAPSHOT_STORE.live_prices.
    Eerst vullen met laatste bekende prijzen uit de database.
    """
    from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
    last_prices = load_last_prices_dict()
    SNAPSHOT_STORE.live_prices = last_prices

def build_repository_active_asset_rollup_data():
    """
    bouwt de tabel op, die aangeeft of een asset actief is / niet actief is 
    waarde beschikbaar in veld "status": 'active' of 'inactive'
    """
    # Haal basis asset info op
    df_assets = SNAPSHOT_STORE.repository_snapshot_asset_rollup_data
    if df_assets is None or df_assets.height == 0:
        return pl.DataFrame({})

    # Haal posities op
    df_aandelen = SNAPSHOT_STORE.repository_snapshot_aandelen
    df_aandelen = df_aandelen.group_by("asset_rollup").agg(pl.col("aantal_bezit").sum())
    
    df_sprinters = SNAPSHOT_STORE.repository_snapshot_open_sprinters
    df_opties = SNAPSHOT_STORE.repository_snapshot_load_open_opties

    # Bepaal per asset of deze actief is
    def is_active(asset):
        # Aandelen > 100 of < -100
        if df_aandelen is not None and df_aandelen.height > 0:
            pos = df_aandelen.filter(pl.col('asset_rollup') == asset)
            if pos.height > 0 and (pos['aantal_bezit'].max() > 99 or pos['aantal_bezit'].min() < -99):
                return 'active'
        # Sprinters in bezit
        if df_sprinters is not None and df_sprinters.height > 0:
            pos = df_sprinters.filter(pl.col('asset_rollup') == asset)
            if pos.height > 0:
                return 'active'
        # Opties in bezit/short
        if df_opties is not None and df_opties.height > 0:
            pos = df_opties.filter(pl.col('asset_rollup') == asset)
            if pos.height > 0:
                return 'active'
        return 'inactive'

    # Voeg status toe
    df_assets = df_assets.with_columns([
        pl.col('asset_rollup').map_elements(is_active).alias('status')
    ])

    # Je kunt hier ook regio, sector, waarde/groei etc. selecteren
    # Bijvoorbeeld: df_assets.select(['asset_rollup', 'regio', 'sector', 'waarde_groei', 'status'])
    SNAPSHOT_STORE.repository_snapshot_active_asset_rollup_data = df_assets
    return df_assets

def portfolio_value_asset_rollup_opties_put():
    # Haal basis asset info op
    df_assets = SNAPSHOT_STORE.repository_snapshot_asset_rollup_data
    if df_assets is None or df_assets.height == 0:
        return pl.DataFrame({})

    # Haal posities op
    
    
    df_opties = SNAPSHOT_STORE.aggregator_snapshot_load_open_opties_from_tx_live
        
    if df_opties is None:
        raise ValueError("aggregator_snapshot_aandelen_live is niet gevuld!")
    else:
        df_opties_waarde = df_opties.with_columns([
            (
                pl.col("SomVantransactie_aantal")
                * pl.col("optie_strike")
                * pl.when(pl.col("optie_call_put") == "call").then(1).otherwise(-1)
            ).alias("waarde_bezit"),
        ])
    df_opties_waarde_2 = df_opties_waarde.with_columns([
        pl.when(pl.col("ITM_OTM") != 0).then(pl.col("waarde_bezit") ).otherwise(None).alias("waarde_ITM"),
        pl.when(pl.col("ITM_OTM") != 0).then(pl.col("SomVantransactie_aantal") ).otherwise(None).alias("aantal_ITM"),
        pl.when(pl.col("ITM_OTM") == 0).then(pl.col("waarde_bezit") ).otherwise(None).alias("waarde_OTM"),
        pl.when(pl.col("ITM_OTM") == 0).then(pl.col("SomVantransactie_aantal") ).otherwise(None).alias("aantal_OTM"),
        
    ])



    df_opties_waarde_2 = df_opties_waarde_2.with_columns(
        pl.struct(["optie_call_put", "Koers", "optie_strike"])
        .map_elements(
            lambda row: estimate_delta(
                row["optie_call_put"],
                row["Koers"],
                row["optie_strike"]
            ),
            return_dtype=pl.Float64  # <-- specify the return type here
        )
        .alias("delta")
    )
    if df_opties_waarde_2 is None:
        raise ValueError("aggregator_snapshot_aandelen_live is niet gevuld!")
    else:
        df_opties_waarde_2 = df_opties_waarde_2.with_columns([
            
            (pl.col("SomVantransactie_aantal") * pl.col("Koers") * pl.col("delta")).alias("waarde_bezit_delta"),
            
        ])
    df_opties_waarde_2 = df_opties_waarde_2.drop(["ib_symbol", "SomVantransactie_euro_totaal", "opt_total_result", "SomVantransactie_fee"])

    # JOIN df_assets op df_opties_waarde_3 op asset_rollup, voeg regio, sector, value_grow toe
    df_opties_waarde_2 = df_opties_waarde_2.join(
        df_assets.select(["asset_rollup", "regio", "sector", "value_grow"]),
        on="asset_rollup",
        how="left"
    )
    # # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken
    # from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE # sourcery skip
    SNAPSHOT_STORE.test_repository_load_input_test_dataframe = df_opties_waarde_2  # sourcery skip # of df_sum als je de gesumde versie wilt zien
    # # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken
    
    df_opties_waarde_3 = df_opties_waarde_2.clone()
    
    
    group_keys = ["asset_rollup", "broker", "regio", "sector", "value_grow"]

    df_opties_waarde_2 = df_opties_waarde_2.filter(pl.col("optie_call_put") == "put")

    df_opties_waarde_2 = df_opties_waarde_2.group_by(group_keys).agg([
        pl.sum("waarde_bezit").alias("waarde_bezit"),
        pl.sum("waarde_ITM").alias("waarde_ITM"),
        pl.sum("waarde_bezit_delta").alias("waarde_bezit_delta"),
        pl.sum("aantal_ITM").alias("aantal_ITM_put"),
        pl.sum("aantal_OTM").alias("aantal_OTM_put"),

        ])
    df_opties_calls = df_opties_waarde_3.filter(pl.col("optie_call_put") == "call")
    df_opties_calls = df_opties_calls.group_by(group_keys).agg([
        pl.sum("aantal_ITM").alias("aantal_ITM_call"),
        pl.sum("aantal_OTM").alias("aantal_OTM_call"),
    ])
    df_opties_waarde_2 = df_opties_waarde_2.join(
        df_opties_calls,
        on=group_keys,
        how="left",
    ).with_columns([
        pl.col("aantal_ITM_call").fill_null(0).alias("aantal_ITM_call"),
        pl.col("aantal_OTM_call").fill_null(0).alias("aantal_OTM_call"),
    ])
    SNAPSHOT_STORE.repository_snapshot_portfolio_value_optie = df_opties_waarde_2
    #return df_opties_waarde_2
    
    df_opties_waarde_4 = df_opties_waarde_3.with_columns([
        pl.when(pl.col("ITM_OTM") != 0).then(pl.col("waarde_bezit_delta") ).otherwise(None).alias("waarde_delta_ITM"),
        pl.when(pl.col("ITM_OTM") != 0).then(pl.col("SomVantransactie_aantal") ).otherwise(None).alias("aantal_delta_ITM"),
        pl.when(pl.col("ITM_OTM") == 0).then(pl.col("waarde_bezit_delta") ).otherwise(None).alias("waarde_delta_OTM"),
        pl.when(pl.col("ITM_OTM") == 0).then(pl.col("SomVantransactie_aantal") ).otherwise(None).alias("aantal_delta_OTM"),
        
    ])    
    # # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken
    # from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE # sourcery skip
    SNAPSHOT_STORE.test_repository_load_output_test_dataframe = df_opties_waarde_4  # sourcery skip # of df_sum als je de gesumde versie wilt zien
    # # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken
    SNAPSHOT_STORE.repository_snapshot_portfolio_value_optie_call_put_detailed = df_opties_waarde_4


def estimate_delta(option_type: str, spot: float, strike: float) -> float:
    """
    Schat delta op basis van moneyness.

    - Ondersteunt option_type in varianten: "call", "put", "C", "P", hoofd-/kleine letters.
    - Retourneert None (null) bij ongeldige of ontbrekende invoer i.p.v. exceptie te gooien,
    - zodat UDF-evaluatie in Polars niet faalt.
    """

    # Normaliseer option_type en sta C/P toe
    t = (option_type or "").strip().lower()
    if t in ("c", "call"):
        t = "call"
    elif t in ("p", "put"):
        t = "put"
    else:
        return None  # onbekende type -> null

    # Valideer en converteer inputs
    try:
        spot_f = float(spot) if spot is not None else None
        strike_f = float(strike) if strike is not None else None
    except (TypeError, ValueError):
        return None

    if spot_f is None or strike_f is None or spot_f == 0.0:
        return None

    # Moneyness als % verschil
    m = (strike_f - spot_f) / spot_f

    # ----------- PUT DELTA -----------
    if t == "put":
        if m > 0.10:
            return -1.00      # deep ITM
        elif m > 0.05:
            return -0.75      # ITM
        elif abs(m) <= 0.025:
            return -0.50      # ATM
        elif m > -0.15:
            return -0.25      # OTM
        else:
            return -0.10      # deep OTM

    # ----------- CALL DELTA -----------
    if t == "call":
        if m < -0.10:
            return 1.00       # deep ITM
        elif m < -0.05:
            return 0.75       # ITM
        elif abs(m) <= 0.025:
            return 0.50       # ATM
        elif m < 0.15:
            return 0.25       # OTM
        else:
            return 0.10       # deep OTM

    # Fallback (zou niet bereikt moeten worden)
    return None




def portfolio_value_asset_rollup_aandelen():

    # Haal posities op
    df_aandelen = SNAPSHOT_STORE.aggregator_snapshot_aandelen_live

    if df_aandelen is None:
        raise ValueError("aggregator_snapshot_aandelen_live is niet gevuld!")
    else:
        df_aandelen_waarde = df_aandelen.with_columns([
            pl.col("broker").fill_null("onbekend").alias("broker"),
            (pl.col("asset_rollup") ).alias("asset_rollup"),
            (pl.col("regio") ).alias("regio"),
            (pl.col("sector") ).alias("sector"),
            (pl.col("value_grow") ).alias("value_grow"),
            
            (pl.col("aantal_bezit") ).alias("aantal_bezit"),
            (pl.col("aantal_bezit") * pl.col("koers")).alias("waarde_bezit"),
            
        ])
    df_aandelen_waarde = df_aandelen_waarde.drop(["aantal_koop", "aantal_verkoop", "euro_koop", "euro_verkoop", "eq_total_fee", "total_result"])
    
    SNAPSHOT_STORE.repository_snapshot_portfolio_value_aandelen = df_aandelen_waarde
    #return df_aandelen_waarde

def portfolio_value_asset_rollup_sprinters():
    df_assets = SNAPSHOT_STORE.repository_snapshot_asset_rollup_data
    if df_assets is None or df_assets.height == 0:
        SNAPSHOT_STORE.repository_snapshot_portfolio_value_sprinters = pl.DataFrame({})
        return

    # Prefer repository snapshot (tx-derived, always available after load_open_sprinters_from_tx).
    # Fallback to live aggregator snapshot when needed.
    df_sprinters = SNAPSHOT_STORE.repository_snapshot_open_sprinters
    if df_sprinters is None or df_sprinters.height == 0:
        df_sprinters = SNAPSHOT_STORE.aggregator_snapshot_open_sprinters_live
    if df_sprinters is None or df_sprinters.height == 0:
        SNAPSHOT_STORE.repository_snapshot_portfolio_value_sprinters = pl.DataFrame({})
        return

    df_sprinters_waarde = df_sprinters.with_columns(
        [
            pl.col("SomVantransactie_aantal").cast(pl.Float64).alias("SomVantransactie_aantal"),
            pl.col("optie_strike").cast(pl.Float64).alias("optie_strike"),
            (
                pl.col("SomVantransactie_aantal").cast(pl.Float64)
                * pl.col("optie_strike").cast(pl.Float64)
            ).alias("spr_waarde_bezit"),
        ]
    )

    df_sprinters_waarde = df_sprinters_waarde.join(
        df_assets.select(["asset_rollup", "regio", "sector", "value_grow"]),
        on="asset_rollup",
        how="left",
    )

    df_sprinters_waarde = df_sprinters_waarde.group_by(
        ["asset_rollup", "regio", "sector", "value_grow"]
    ).agg(
        [
            pl.sum("SomVantransactie_aantal").alias("aantal_sprinters"),
            pl.sum("spr_waarde_bezit").alias("spr_waarde_bezit"),
        ]
    )

    SNAPSHOT_STORE.repository_snapshot_portfolio_value_sprinters = df_sprinters_waarde

def portfolio_value_asset_rollup_combined():
    from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
    df_aandelen = SNAPSHOT_STORE.repository_snapshot_portfolio_value_aandelen
    df_opties_put = SNAPSHOT_STORE.repository_snapshot_portfolio_value_optie
    df_sprinters = SNAPSHOT_STORE.repository_snapshot_portfolio_value_sprinters

    if df_aandelen is None or df_opties_put is None:
        raise ValueError("Een van de benodigde dataframes is niet gevuld!")
    if df_sprinters is None:
        df_sprinters = pl.DataFrame({})

    df_opties_put = df_opties_put.group_by("asset_rollup",  "regio", "sector", "value_grow").agg([
        pl.sum("waarde_bezit").alias("opt_waarde_bezit"),
        pl.sum("waarde_ITM").alias("opt_waarde_ITM"),
        pl.sum("waarde_bezit_delta").alias("opt_waarde_bezit_delta"),
        pl.sum("aantal_ITM_put").alias("opt_aantal_ITM_put"),
        pl.sum("aantal_OTM_put").alias("opt_aantal_OTM_put"),
        pl.sum("aantal_ITM_call").alias("opt_aantal_ITM_call"),
        pl.sum("aantal_OTM_call").alias("opt_aantal_OTM_call"),
        ])
    df_opties_put = df_opties_put.drop(["regio", "sector", "value_grow"])
    if not df_sprinters.is_empty():
        df_sprinters = df_sprinters.group_by("asset_rollup", "regio", "sector", "value_grow").agg([
            pl.sum("aantal_sprinters").alias("aantal_sprinters"),
            pl.sum("spr_waarde_bezit").alias("spr_waarde_bezit"),
        ])
        df_sprinters = df_sprinters.drop(["regio", "sector", "value_grow"])
    else:
        df_sprinters = pl.DataFrame(
            schema={
                "asset_rollup": pl.Utf8,
                "aantal_sprinters": pl.Float64,
                "spr_waarde_bezit": pl.Float64,
            }
        )


    df_aandelen = df_aandelen.group_by("asset_rollup", "regio", "sector", "value_grow","koers").agg([
        pl.sum("aantal_bezit").alias("aand_aantal_bezit"),
        pl.sum("waarde_bezit").alias("aand_waarde_bezit"),
        ])

    # Ensure join key uses a stable dtype across sources.
    if "asset_rollup" in df_aandelen.columns:
        df_aandelen = df_aandelen.with_columns(pl.col("asset_rollup").cast(pl.Utf8))
    if "asset_rollup" in df_opties_put.columns:
        df_opties_put = df_opties_put.with_columns(pl.col("asset_rollup").cast(pl.Utf8))
    if "asset_rollup" in df_sprinters.columns:
        df_sprinters = df_sprinters.with_columns(pl.col("asset_rollup").cast(pl.Utf8))


    
    # Join op asset_rollup en broker
    df_combined = df_aandelen.join(
        df_opties_put,
        on=["asset_rollup"],
        how="outer",
        # suffix="opt_"
    )

    if "asset_rollup_right" in df_combined.columns:
        df_combined = df_combined.drop(["asset_rollup_right"])

    df_combined = df_combined.join(
        df_sprinters,
        on=["asset_rollup"],
        how="outer",
    )
    if "asset_rollup_right" in df_combined.columns:
        df_combined = df_combined.drop(["asset_rollup_right"])

    # Vervang nullen door 0 voor sommaties
    df_combined = df_combined.with_columns([
        pl.col("aand_aantal_bezit").fill_null(0).alias("aand_aantal_bezit"),
        pl.col("aand_waarde_bezit").fill_null(0).alias("aand_waarde_bezit"),
        pl.col("opt_waarde_bezit").fill_null(0).alias("opt_waarde_bezit"),
        pl.col("opt_waarde_ITM").fill_null(0).alias("opt_waarde_ITM"),
        pl.col("opt_waarde_bezit_delta").fill_null(0).alias("opt_waarde_bezit_delta"),
        pl.col("opt_aantal_ITM_put").fill_null(0).alias("opt_aantal_ITM_put"),
        pl.col("opt_aantal_OTM_put").fill_null(0).alias("opt_aantal_OTM_put"),
        pl.col("opt_aantal_ITM_call").fill_null(0).alias("opt_aantal_ITM_call"),
        pl.col("opt_aantal_OTM_call").fill_null(0).alias("opt_aantal_OTM_call"),
        pl.col("aantal_sprinters").fill_null(0).alias("aantal_sprinters"),
        pl.col("spr_waarde_bezit").fill_null(0).alias("spr_waarde_bezit"),
    ])



    # Bereken totale waarde per asset_rollup en broker
    df_combined = df_combined.with_columns([
        (pl.col("aand_aantal_bezit") + (-1* pl.col("opt_aantal_ITM_put"))).alias("total_aantal_lineair"),

        (pl.col("aand_waarde_bezit") + pl.col("opt_waarde_bezit") + pl.col("spr_waarde_bezit")).alias("total_waarde_lineair"),
        (pl.col("aand_waarde_bezit") + pl.col("opt_waarde_bezit_delta") + pl.col("spr_waarde_bezit")).alias("total_waarde_delta"),
    ])

    total_portfolio_value_lineair = df_combined['total_waarde_lineair'].sum()
    total_portfolio_value_delta = df_combined['total_waarde_delta'].sum()

    df_combined = df_combined.with_columns([
        (pl.col("total_waarde_lineair")/total_portfolio_value_lineair).alias("portfolio_total_waarde_lineair_pct"),
        (pl.col("total_waarde_delta")/total_portfolio_value_delta).alias("portfolio_total_waarde_delta_pct"),
    ])

    SNAPSHOT_STORE.repository_snapshot_portfolio_value_total_combined_put = df_combined
    #return df_combined

def refresh_all_snapshots():
    load_alle_transacties()
    load_aandelen_from_tx()
    load_open_opties_from_tx()
    load_gesloten_opties_from_tx()
    load_gesloten_opties_no_broker()
    load_open_sprinters_from_tx()
    load_gesloten_sprinters_from_tx()
    load_asset_rollup_data()
    load_sprinter_referentie_data()
    load_dividend_data()
    load_historical_close_snapshot()
    load_per_dag_asset_result_v2_snapshot()
    load_per_dag_asset_result()
    load_optie_referentie_data()
        
    build_repository_active_asset_rollup_data()
    portfolio_value_asset_rollup_opties_put()
    portfolio_value_asset_rollup_aandelen()
    portfolio_value_asset_rollup_sprinters()
    portfolio_value_asset_rollup_combined()


    
