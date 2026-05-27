import contextlib
import pandas as pd
import pyodbc
import polars as pl

from datetime import date, datetime, timedelta
from decimal import Decimal
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.config import get_databases, get_default_database, get_settings, get_stockdata_db_path
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
    global DEFAULT_DB_NAME, db_path, conn_str
    if name not in DB_MAP:
        raise ValueError(f"Onbekende database: {name}")
    # flush dirty live asset-prijzen naar huidige DB voordat we overschakelen
    with contextlib.suppress(Exception):
        from portefeuille_viewer.data.asset_last_price_store import ASSET_LAST_PRICE_STORE
        ASSET_LAST_PRICE_STORE.flush()
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
    DEFAULT_DB_NAME = name
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
    with contextlib.suppress(Exception):
        from portefeuille_viewer.services.year_result_vs_indices_service import clear_year_result_vs_indices_cache

        clear_year_result_vs_indices_cache()
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

def load_historical_ohlcv_snapshot() -> pl.DataFrame:
    """
    Laad historical OHLCV-data in memory en publiceer de latest-close afleiding.
    """
    with get_connection() as conn:
        table_cols = {str(row.column_name).lower() for row in conn.cursor().columns(table="historical_data_correct")}
        optional_selects = []
        if "historical_volatility" in table_cols:
            optional_selects.append("historical_volatility")
        if "implied_volatility" in table_cols:
            optional_selects.append("implied_volatility")
        optional_sql = "".join(f",\n                [{col}]" for col in optional_selects)
        sql = f"""
            SELECT
                datum,
                asset_rollup,
                [open] AS open_price,
                [high] AS high_price,
                [low] AS low_price,
                [close] AS close_price,
                [volume] AS volume_value
                {optional_sql}
            FROM historical_data_correct
            WHERE asset_rollup IS NOT NULL
        """
        df = pl.read_database(sql, conn)
    df_ohlcv = _prepare_historical_ohlcv_snapshot(df)
    SNAPSHOT_STORE.safe_write("repository_snapshot_historical_ohlcv", df_ohlcv)
    SNAPSHOT_STORE.safe_write(
        "repository_snapshot_historical_ohlcv_latest",
        _build_historical_ohlcv_latest_snapshot(df_ohlcv),
    )
    return compact_float64(df_ohlcv)


def load_asset_driver_beta_snapshot() -> pl.DataFrame:
    sql = """
        SELECT
            asset_rollup,
            home_index,
            beta_mode,
            driver_index,
            beta_value,
            lookback_code,
            return_interval,
            n_obs,
            r2,
            updated_at
        FROM asset_driver_beta_snapshot
    """
    legacy_sql = """
        SELECT
            asset_rollup,
            home_index,
            driver_index,
            beta_value,
            lookback_code,
            return_interval,
            n_obs,
            r2,
            updated_at
        FROM asset_driver_beta_snapshot
    """
    with get_stockdata_connection() as conn:
        try:
            df = pl.read_database(sql, conn)
        except Exception:
            df = pl.read_database(legacy_sql, conn)
            if df is not None and "beta_mode" not in df.columns:
                df = df.with_columns(pl.lit("").cast(pl.Utf8).alias("beta_mode"))
    if df is None or df.is_empty():
        out = pl.DataFrame(
            schema={
                "asset_rollup": pl.Utf8,
                "home_index": pl.Utf8,
                "beta_mode": pl.Utf8,
                "driver_index": pl.Utf8,
                "beta_value": pl.Float64,
                "lookback_code": pl.Utf8,
                "return_interval": pl.Utf8,
                "n_obs": pl.Int64,
                "r2": pl.Float64,
                "updated_at": pl.Datetime,
            }
        )
    else:
        out = df.with_columns([
            pl.col("asset_rollup").cast(pl.Utf8, strict=False).str.strip_chars().str.to_uppercase().alias("asset_rollup"),
            pl.col("home_index").cast(pl.Utf8, strict=False).str.strip_chars().str.to_uppercase().alias("home_index"),
            pl.col("beta_mode").cast(pl.Utf8, strict=False).str.strip_chars().str.to_lowercase().alias("beta_mode"),
            pl.col("driver_index").cast(pl.Utf8, strict=False).str.strip_chars().str.to_uppercase().alias("driver_index"),
            pl.col("lookback_code").cast(pl.Utf8, strict=False).str.strip_chars().str.to_lowercase().alias("lookback_code"),
            pl.col("return_interval").cast(pl.Utf8, strict=False).str.strip_chars().str.to_lowercase().alias("return_interval"),
            pl.col("beta_value").cast(pl.Float64, strict=False).alias("beta_value"),
            pl.col("n_obs").cast(pl.Int64, strict=False).alias("n_obs"),
            pl.col("r2").cast(pl.Float64, strict=False).alias("r2"),
        ])
    SNAPSHOT_STORE.safe_write("repository_snapshot_asset_driver_beta", out)
    if getattr(SNAPSHOT_STORE, "runtime_price_shift_driver", None) in (None, "") and out is not None and not out.is_empty():
        try:
            drivers = sorted(
                {
                    str(v).strip().upper()
                    for v in out["driver_index"].drop_nulls().to_list()
                    if str(v).strip()
                }
            )
        except Exception:
            drivers = []
        if drivers:
            SNAPSHOT_STORE.runtime_price_shift_driver = "AEX" if "AEX" in drivers else drivers[0]
    return compact_float64(out)


def load_asset_dividend_calendar_snapshot() -> pl.DataFrame:
    from portefeuille_viewer.data.dividend_calendar_repository import ensure_dividend_calendar_schema

    ensure_dividend_calendar_schema()
    sql = """
        SELECT
            asset_rollup,
            ib_symbol,
            ib_currency,
            next_dividend_date,
            next_dividend_amount,
            trailing_12m_dividend,
            forward_12m_dividend,
            next_earnings_date,
            source_dividend,
            source_earnings,
            status,
            message,
            raw_dividend_value,
            fetched_at,
            updated_at
        FROM asset_dividend_calendar_current
    """
    with get_stockdata_connection() as conn:
        df = pl.read_database(sql, conn)
    if df is None or df.is_empty():
        out = pl.DataFrame(
            schema={
                "asset_rollup": pl.Utf8,
                "ib_symbol": pl.Utf8,
                "ib_currency": pl.Utf8,
                "next_dividend_date": pl.Date,
                "next_dividend_amount": pl.Float64,
                "trailing_12m_dividend": pl.Float64,
                "forward_12m_dividend": pl.Float64,
                "next_earnings_date": pl.Date,
                "source_dividend": pl.Utf8,
                "source_earnings": pl.Utf8,
                "status": pl.Utf8,
                "message": pl.Utf8,
                "raw_dividend_value": pl.Utf8,
                "fetched_at": pl.Datetime,
                "updated_at": pl.Datetime,
            }
        )
    else:
        out = df.with_columns(
            [
                pl.col("asset_rollup").cast(pl.Utf8, strict=False).str.strip_chars().str.to_uppercase(),
                pl.col("ib_symbol").cast(pl.Utf8, strict=False).str.strip_chars(),
                pl.col("ib_currency").cast(pl.Utf8, strict=False).str.strip_chars(),
                pl.col("next_dividend_date").cast(pl.Date, strict=False),
                pl.col("next_dividend_amount").cast(pl.Float64, strict=False),
                pl.col("trailing_12m_dividend").cast(pl.Float64, strict=False),
                pl.col("forward_12m_dividend").cast(pl.Float64, strict=False),
                pl.col("next_earnings_date").cast(pl.Date, strict=False),
                pl.col("source_dividend").cast(pl.Utf8, strict=False),
                pl.col("source_earnings").cast(pl.Utf8, strict=False),
                pl.col("status").cast(pl.Utf8, strict=False),
                pl.col("message").cast(pl.Utf8, strict=False),
                pl.col("raw_dividend_value").cast(pl.Utf8, strict=False),
            ]
        )
    SNAPSHOT_STORE.safe_write("repository_snapshot_asset_dividend_calendar", out)
    return compact_float64(out)


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
    df = _prepare_per_dag_asset_result_v2_snapshot(df)
    SNAPSHOT_STORE.safe_write("repository_snapshot_per_dag_asset_result_v2", df)
    SNAPSHOT_STORE.safe_write(
        "repository_snapshot_per_dag_asset_result_v2_latest",
        _build_per_dag_asset_result_v2_latest_snapshot(df),
    )
    return compact_float64(df)


def _normalize_asset_rollup_column(df: pl.DataFrame, col_name: str = "asset_rollup") -> pl.DataFrame:
    if col_name not in df.columns:
        return df
    return df.with_columns(
        pl.col(col_name)
        .cast(pl.Utf8, strict=False)
        .str.strip_chars()
        .str.to_uppercase()
        .alias(col_name)
    )


def _normalize_date_column(df: pl.DataFrame, col_name: str = "datum") -> pl.DataFrame:
    if col_name not in df.columns:
        return df
    return df.with_columns(
        pl.coalesce(
            [
                pl.col(col_name).cast(pl.Date, strict=False),
                pl.col(col_name).cast(pl.Utf8).str.strptime(pl.Date, "%Y-%m-%d", strict=False),
                pl.col(col_name).cast(pl.Utf8).str.strptime(pl.Date, "%d/%m/%Y", strict=False),
                pl.col(col_name).cast(pl.Utf8).str.strptime(pl.Date, "%d-%m-%Y", strict=False),
            ]
        ).alias(col_name)
    )


def _prepare_historical_ohlcv_snapshot(df: pl.DataFrame) -> pl.DataFrame:
    if df is None or df.is_empty():
        return pl.DataFrame(
            schema={
                "datum": pl.Date,
                "asset_rollup": pl.Utf8,
                "open_price": pl.Float64,
                "high_price": pl.Float64,
                "low_price": pl.Float64,
                "close_price": pl.Float64,
                "volume_value": pl.Float64,
            }
        )
    df = _normalize_date_column(df, "datum")
    df = _normalize_asset_rollup_column(df, "asset_rollup")
    casts: list[pl.Expr] = []
    for col in (
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume_value",
        "historical_volatility",
        "implied_volatility",
    ):
        if col in df.columns:
            casts.append(pl.col(col).cast(pl.Float64, strict=False).alias(col))
    if casts:
        df = df.with_columns(casts)
    return compact_float64(df)


def _prepare_per_dag_asset_result_v2_snapshot(df: pl.DataFrame) -> pl.DataFrame:
    if df is None or df.is_empty():
        return pl.DataFrame(
            schema={
                "datum": pl.Date,
                "asset_rollup": pl.Utf8,
                "totaal_v2": pl.Float64,
                "totaal_aantal_bezit_v2": pl.Float64,
            }
        )
    df = _normalize_date_column(df, "datum")
    df = _normalize_asset_rollup_column(df, "asset_rollup")
    casts: list[pl.Expr] = []
    if "totaal_v2" in df.columns:
        casts.append(pl.col("totaal_v2").cast(pl.Float64, strict=False).alias("totaal_v2"))
    if "totaal_aantal_bezit_v2" in df.columns:
        casts.append(
            pl.col("totaal_aantal_bezit_v2").cast(pl.Float64, strict=False).alias("totaal_aantal_bezit_v2")
        )
    if casts:
        df = df.with_columns(casts)
    return compact_float64(df)


def _build_historical_ohlcv_latest_snapshot(df: pl.DataFrame) -> pl.DataFrame:
    if df is None or df.is_empty():
        return pl.DataFrame(schema={"asset_rollup": pl.Utf8, "datum": pl.Date, "close_price": pl.Float64})
    today = date.today()
    latest_df = (
        df.filter(pl.col("datum").is_not_null() & (pl.col("datum") < today) & pl.col("close_price").is_not_null())
        .sort(["asset_rollup", "datum"])
        .group_by("asset_rollup")
        .agg(
            [
                pl.col("datum").last().alias("datum"),
                pl.col("close_price").last().alias("close_price"),
            ]
        )
    )
    return compact_float64(latest_df)


def _build_per_dag_asset_result_v2_latest_snapshot(df: pl.DataFrame) -> pl.DataFrame:
    if df is None or df.is_empty():
        return pl.DataFrame(schema={"asset_rollup": pl.Utf8, "totaal": pl.Float64})
    today = date.today()
    latest_df = (
        df.filter(pl.col("datum").is_not_null() & (pl.col("datum") < today))
        .sort(["asset_rollup", "datum"])
        .group_by("asset_rollup")
        .agg(pl.col("totaal_v2").last().alias("totaal"))
    )
    return compact_float64(latest_df)

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
    Laadt de optie referentie tabel uit de stock database.
    """
    sql = "SELECT * FROM optie_referentie_data"
    with get_stockdata_connection() as conn:
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




asset_types = ["aandeel", "future", "optie", "sprinter"]
transactie_types = ["koop", "verkoop"]
transactie_oorsprong = ["OPEN", "CLOSE", "ASSIGN", "EXPIRE", "DOORROL", "STOCKSPLIT", "EXERCISE"]

TABLE_COLS = [
    "Id","datum","transactie_oorsprong","broker","asset_rollup","asset_type",
    "transactie_type","asset_detail","optie_exp_date","optie_strike","optie_call_put",
    "aantal","transactie_prijs","transactie_fee","uniek_id","transactie_oorsprong_detail"
]

def get_connection():
    return pyodbc.connect(conn_str)


def get_stockdata_connection():
    conn_str_stock = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={get_stockdata_db_path()};"
    return pyodbc.connect(conn_str_stock)


def _normalize_orders_committed_payload(
    rows: list[dict] | None = None,
    *,
    reason: str = "unknown",
    operation: str = "upsert",
    deleted_ids: list[int] | None = None,
) -> dict:
    rows = list(rows or [])
    asset_types: set[str] = set()
    asset_rollups: set[str] = set()
    ids: list[int] = []
    for row in rows:
        at = str(row.get("asset_type") or "").strip().lower()
        ar = str(row.get("asset_rollup") or "").strip()
        rid = row.get("Id")
        if at:
            asset_types.add(at)
        if ar:
            asset_rollups.add(ar)
        if rid is not None:
            with contextlib.suppress(Exception):
                ids.append(int(rid))
    if deleted_ids:
        for rid in deleted_ids:
            with contextlib.suppress(Exception):
                ids.append(int(rid))
    ids = sorted(set(ids))
    return {
        "reason": reason,
        "operation": operation,
        "changed_asset_types": sorted(asset_types),
        "changed_assets": sorted(asset_rollups),
        "changed_ids": ids,
        "row_count": len(rows),
        "committed_rows": rows,
        "deleted_ids": sorted(set(int(rid) for rid in (deleted_ids or []) if rid is not None)),
    }


def _fetch_rows_for_ids(conn, ids_to_fetch: list) -> list[dict]:
    if not ids_to_fetch:
        return []
    placeholders = ",".join("?" * len(ids_to_fetch))
    sql = (
        "SELECT Id, asset_type, asset_rollup "
        f"FROM transacties_bron_data_org WHERE Id IN ({placeholders})"
    )
    df = pl.read_database(sql, conn, execute_options={"parameters": ids_to_fetch})
    return df.to_dicts()


def _transaction_schema_overrides() -> dict:
    return {
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


def _fetch_full_transactions_by_ids(conn, ids_to_fetch: list) -> list[dict]:
    if not ids_to_fetch:
        return []
    placeholders = ",".join("?" * len(ids_to_fetch))
    sql = f"SELECT * FROM transacties_bron_data_org WHERE Id IN ({placeholders}) ORDER BY Id"
    df = pl.read_database(
        sql,
        conn,
        schema_overrides=_transaction_schema_overrides(),
        execute_options={"parameters": ids_to_fetch},
    )
    return df.to_dicts()


def _transactions_rows_to_df(rows: list[dict], current_df: pl.DataFrame) -> pl.DataFrame:
    row_df = pl.from_dicts(rows, schema_overrides=_transaction_schema_overrides())
    for col_name, dtype in current_df.schema.items():
        if col_name not in row_df.columns:
            row_df = row_df.with_columns(pl.lit(None, dtype=dtype).alias(col_name))
        else:
            row_df = row_df.with_columns(pl.col(col_name).cast(dtype, strict=False))
    return row_df.select(current_df.columns)


def patch_transactions_snapshot_from_orders_payload(payload: dict | None) -> pl.DataFrame | None:
    current_df = SNAPSHOT_STORE.repository_snapshot_alle_transacties
    if current_df is None:
        return None

    payload = dict(payload or {})
    operation = str(payload.get("operation") or "").strip().lower()
    committed_rows = list(payload.get("committed_rows") or [])
    deleted_ids = []
    for rid in (payload.get("deleted_ids") or payload.get("changed_ids") or []):
        with contextlib.suppress(Exception):
            deleted_ids.append(int(rid))
    deleted_ids = sorted(set(deleted_ids))

    if operation == "delete":
        if not deleted_ids or "Id" not in current_df.columns:
            return None
        patched_df = current_df.filter(~pl.col("Id").cast(pl.Int64, strict=False).is_in(deleted_ids))
    else:
        if not committed_rows or "Id" not in current_df.columns:
            return None
        row_df = _transactions_rows_to_df(committed_rows, current_df)
        upsert_ids = (
            row_df.select(pl.col("Id").cast(pl.Int64, strict=False).alias("Id"))
            .drop_nulls()
            .get_column("Id")
            .to_list()
        )
        if not upsert_ids:
            return None
        current_filtered = current_df.filter(
            ~pl.col("Id").cast(pl.Int64, strict=False).is_in(upsert_ids)
        )
        patched_df = pl.concat([current_filtered, row_df], how="vertical_relaxed")
        if "Id" in patched_df.columns:
            patched_df = patched_df.sort("Id")

    SNAPSHOT_STORE.safe_write("repository_snapshot_alle_transacties", patched_df)
    return patched_df


def insert_transactions_atomic(rows: list[dict], *, reason: str = "insert_transactions_atomic") -> list[dict]:
    """Voeg 1..n transacties atomisch in en geef de committed rows terug."""
    rows = [dict(row or {}) for row in (rows or [])]
    if not rows:
        return []
    inserted_ids: list[int] = []
    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            for row in rows:
                row.pop("uniek_id", None)
                cols = ", ".join(row.keys())
                placeholders = ", ".join(["?"] * len(row))
                values = list(row.values())
                cursor.execute(
                    f"INSERT INTO transacties_bron_data_org ({cols}) VALUES ({placeholders})",
                    values,
                )
                cursor.execute("SELECT @@IDENTITY")
                inserted_ids.append(int(cursor.fetchone()[0]))
            conn.commit()
            committed_rows = _fetch_full_transactions_by_ids(conn, inserted_ids)
        except pyodbc.Error:
            conn.rollback()
            raise
    with contextlib.suppress(Exception):
        signals.ordersCommitted.emit(
            _normalize_orders_committed_payload(
                committed_rows,
                reason=reason,
                operation="insert",
            )
        )
    return committed_rows

def insert_transaction(data: dict) -> int:
    """Nieuwe transactie invoegen en Id teruggeven."""
    committed_rows = insert_transactions_atomic([data], reason="insert_transaction")
    if not committed_rows:
        raise RuntimeError("insert_transaction returned no committed rows")
    return int(committed_rows[0]["Id"])


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
        deleted_rows = _fetch_rows_for_ids(conn, ids_to_delete)
        deleted_count = _extracted_from_delete_transactions_by_ids_10(
            conn, ids_to_delete
        )
    # Emit centraal signaal na delete
    with contextlib.suppress(Exception):
        signals.ordersCommitted.emit(
            _normalize_orders_committed_payload(
                deleted_rows,
                reason="delete_transactions_by_ids",
                operation="delete",
                deleted_ids=ids_to_delete,
            )
        )
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
    committed_rows: list[dict] = []
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
            ids_to_fetch = [record_id1]
            if record_id2 is not None:
                ids_to_fetch.append(record_id2)
            committed_rows = _fetch_full_transactions_by_ids(conn, ids_to_fetch)
        except pyodbc.Error:
            conn.rollback()
            raise
    # Emit centraal signaal na update
    with contextlib.suppress(Exception):
        signals.ordersCommitted.emit(
            _normalize_orders_committed_payload(
                committed_rows,
                reason="update_transactions_atomic",
                operation="update",
            )
        )

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
    from portefeuille_viewer.data.asset_last_price_store import ASSET_LAST_PRICE_STORE

    return ASSET_LAST_PRICE_STORE.ensure_loaded()

def load_live_prices():
    """
    Laad de initiële live prijzen in SNAPSHOT_STORE.live_prices.
    Eerst vullen met laatste bekende prijzen uit de database.
    """
    from portefeuille_viewer.data.asset_last_price_store import ASSET_LAST_PRICE_STORE

    ASSET_LAST_PRICE_STORE.ensure_loaded()

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



    delta_lookup = build_option_delta_lookup()
    df_opties_waarde_2 = df_opties_waarde_2.with_columns([
        pl.struct(["asset_rollup", "optie_call_put", "optie_exp_date", "optie_strike", "Koers"])
        .map_elements(
            lambda row: resolve_option_delta(
                row["asset_rollup"],
                row["optie_call_put"],
                row["optie_exp_date"],
                row["optie_strike"],
                row["Koers"],
                delta_lookup,
            ),
            return_dtype=pl.Float64  # <-- specify the return type here
        )
        .alias("delta"),
        pl.struct(["asset_rollup", "optie_call_put", "optie_exp_date", "optie_strike", "Koers"])
        .map_elements(
            lambda row: resolve_option_delta_source(
                row["asset_rollup"],
                row["optie_call_put"],
                row["optie_exp_date"],
                row["optie_strike"],
                row["Koers"],
                delta_lookup,
            ),
            return_dtype=pl.Utf8,
        )
        .alias("delta_source"),
    ])
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
        how="outer",
    )
    coalesce_exprs = []
    drop_cols = []
    for key in group_keys:
        right_key = f"{key}_right"
        if right_key in df_opties_waarde_2.columns:
            coalesce_exprs.append(pl.coalesce([pl.col(key), pl.col(right_key)]).alias(key))
            drop_cols.append(right_key)
    if coalesce_exprs:
        df_opties_waarde_2 = df_opties_waarde_2.with_columns(coalesce_exprs).drop(drop_cols)
    df_opties_waarde_2 = df_opties_waarde_2.with_columns([
        pl.col("waarde_bezit").fill_null(0).alias("waarde_bezit"),
        pl.col("waarde_ITM").fill_null(0).alias("waarde_ITM"),
        pl.col("waarde_bezit_delta").fill_null(0).alias("waarde_bezit_delta"),
        pl.col("aantal_ITM_put").fill_null(0).alias("aantal_ITM_put"),
        pl.col("aantal_OTM_put").fill_null(0).alias("aantal_OTM_put"),
        pl.col("aantal_ITM_call").fill_null(0).alias("aantal_ITM_call"),
        pl.col("aantal_OTM_call").fill_null(0).alias("aantal_OTM_call"),
    ])
    SNAPSHOT_STORE.safe_write("repository_snapshot_portfolio_value_optie", df_opties_waarde_2)
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
    SNAPSHOT_STORE.safe_write("repository_snapshot_portfolio_value_optie_call_put_detailed", df_opties_waarde_4)


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


def _option_key_asset(value) -> str | None:
    text = str(value or "").strip().upper()
    return text or None


def _option_key_type(value) -> str | None:
    text = str(value or "").strip().lower()
    if text in {"c", "call"}:
        return "call"
    if text in {"p", "put"}:
        return "put"
    return None


def _option_key_expiry(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10] if fmt == "%Y-%m-%d" else text, fmt).date().isoformat()
        except Exception:
            pass
    return text[:10]


def _option_key_strike(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, str):
        value = value.strip().replace(",", ".")
    try:
        return round(float(value), 6)
    except Exception:
        return None


def _option_delta_key(asset_rollup, option_type, expiry, strike) -> tuple[str, str, str, float] | None:
    asset = _option_key_asset(asset_rollup)
    cp = _option_key_type(option_type)
    exp = _option_key_expiry(expiry)
    strike_f = _option_key_strike(strike)
    if asset is None or cp is None or exp is None or strike_f is None:
        return None
    return (asset, cp, exp, strike_f)


def _valid_delta(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", ".")
    try:
        out = float(value)
    except Exception:
        return None
    if out != out:
        return None
    return out


def build_option_delta_lookup() -> dict[tuple[str, str, str, float], float]:
    """
    Brokerloze delta-map uit snapshot_optie_timevalue_live.

    snapshot_optie_timevalue_live is positie-gebaseerd en kan dezelfde optie
    meerdere keren bevatten. Voor pricing/greeks gebruiken we daarom alleen de
    instrument-key en nemen we de eerste niet-null delta.
    """
    df = getattr(SNAPSHOT_STORE, "snapshot_optie_timevalue_live", None)
    if df is None or df.is_empty():
        return {}
    required = {"asset", "c_p", "exp", "strike", "delta"}
    if not required.issubset(set(df.columns)):
        return {}

    lookup: dict[tuple[str, str, str, float], float] = {}
    for row in df.select(["asset", "c_p", "exp", "strike", "delta"]).to_dicts():
        key = _option_delta_key(row.get("asset"), row.get("c_p"), row.get("exp"), row.get("strike"))
        if key is None or key in lookup:
            continue
        delta = _valid_delta(row.get("delta"))
        if delta is not None:
            lookup[key] = delta
    return lookup


def resolve_option_delta(
    asset_rollup,
    option_type,
    expiry,
    strike,
    spot,
    delta_lookup: dict[tuple[str, str, str, float], float] | None = None,
) -> float | None:
    lookup = delta_lookup if delta_lookup is not None else build_option_delta_lookup()
    key = _option_delta_key(asset_rollup, option_type, expiry, strike)
    if key is not None:
        delta = _valid_delta(lookup.get(key))
        if delta is not None:
            return delta
    return estimate_delta(option_type, spot, strike)


def resolve_option_delta_source(
    asset_rollup,
    option_type,
    expiry,
    strike,
    spot,
    delta_lookup: dict[tuple[str, str, str, float], float] | None = None,
) -> str:
    lookup = delta_lookup if delta_lookup is not None else build_option_delta_lookup()
    key = _option_delta_key(asset_rollup, option_type, expiry, strike)
    if key is not None and _valid_delta(lookup.get(key)) is not None:
        return "pricefeed"
    if estimate_delta(option_type, spot, strike) is not None:
        return "estimate"
    return ""




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
    
    SNAPSHOT_STORE.safe_write("repository_snapshot_portfolio_value_aandelen", df_aandelen_waarde)
    #return df_aandelen_waarde

def portfolio_value_asset_rollup_sprinters():
    df_assets = SNAPSHOT_STORE.repository_snapshot_asset_rollup_data
    if df_assets is None or df_assets.height == 0:
        SNAPSHOT_STORE.safe_write("repository_snapshot_portfolio_value_sprinters", pl.DataFrame({}))
        return

    # Prefer repository snapshot (tx-derived, always available after load_open_sprinters_from_tx).
    # Fallback to live aggregator snapshot when needed.
    df_sprinters = SNAPSHOT_STORE.repository_snapshot_open_sprinters
    if df_sprinters is None or df_sprinters.height == 0:
        df_sprinters = SNAPSHOT_STORE.aggregator_snapshot_open_sprinters_live
    if df_sprinters is None or df_sprinters.height == 0:
        SNAPSHOT_STORE.safe_write("repository_snapshot_portfolio_value_sprinters", pl.DataFrame({}))
        return

    broker_expr = (
        pl.col("broker").fill_null("onbekend").alias("broker")
        if "broker" in df_sprinters.columns
        else pl.lit("onbekend").alias("broker")
    )
    df_sprinters_waarde = df_sprinters.with_columns(
        [
            broker_expr,
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
        ["broker", "asset_rollup", "regio", "sector", "value_grow"]
    ).agg(
        [
            pl.sum("SomVantransactie_aantal").alias("aantal_sprinters"),
            pl.sum("spr_waarde_bezit").alias("spr_waarde_bezit"),
        ]
    )

    SNAPSHOT_STORE.safe_write("repository_snapshot_portfolio_value_sprinters", df_sprinters_waarde)

def portfolio_value_asset_rollup_combined():
    from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
    from portefeuille_viewer.services.portfolio_value_broker_view import build_combined_portfolio_value_df
    df_aandelen = SNAPSHOT_STORE.repository_snapshot_portfolio_value_aandelen
    df_opties = SNAPSHOT_STORE.repository_snapshot_portfolio_value_optie_call_put_detailed
    if df_opties is None or df_opties.is_empty():
        df_opties = SNAPSHOT_STORE.repository_snapshot_portfolio_value_optie
    df_sprinters = SNAPSHOT_STORE.repository_snapshot_portfolio_value_sprinters

    if df_aandelen is None or df_opties is None:
        raise ValueError("Een van de benodigde dataframes is niet gevuld!")
    if df_sprinters is None:
        df_sprinters = pl.DataFrame({})
    df_combined = build_combined_portfolio_value_df(df_aandelen, df_opties, df_sprinters)

    SNAPSHOT_STORE.safe_write("repository_snapshot_portfolio_value_total_combined_put", df_combined)
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
    load_historical_ohlcv_snapshot()
    load_asset_driver_beta_snapshot()
    load_per_dag_asset_result_v2_snapshot()
    load_optie_referentie_data()
        
    build_repository_active_asset_rollup_data()
    portfolio_value_asset_rollup_opties_put()
    portfolio_value_asset_rollup_aandelen()
    portfolio_value_asset_rollup_sprinters()
    portfolio_value_asset_rollup_combined()


    
