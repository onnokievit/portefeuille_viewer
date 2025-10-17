import pandas as pd
import pyodbc
from datetime import date, datetime, timedelta
from portefeuille_viewer.domain.engine import compact_float64
import warnings
import polars as pl
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE 
from portefeuille_viewer.config import get_databases, get_default_database
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
    new_path = DB_MAP[name]
    test_conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={new_path};"
    with pyodbc.connect(test_conn_str):  # test connectie
        pass
    db_path = new_path
    conn_str = test_conn_str
    # Sla ook de actieve database-naam op in de snapshot store voor UI-consumptie
    try:
        SNAPSHOT_STORE.active_database_name = name
    except Exception:
        # Niet kritisch, maar nuttig om te weten tijdens debugging
        print(f"Waarschuwing: kon SNAPSHOT_STORE.active_database_name niet instellen op {name}")
    else:
        # Emit central databaseChanged signal so UI can react (queued to main thread)
        try:
            from portefeuille_viewer.signals import signals
            signals.queued_emit_databaseChanged(name)
        except Exception:
            # If signals are not available, ignore silently (no hard dependency)
            pass


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
    sql = "SELECT Id,asset_rollup, value_grow, sector, type, regio, ib_symbol, ib_currency, exchange, prim_exchange FROM asset_rollup_data"
    with get_connection() as conn:
        df = pl.read_database(sql, conn)
    SNAPSHOT_STORE.snapshot_asset_rollup_data = df
    # return compact_float64(df)

# ------------------------------------------------------------
# sprinter_refenctie_data referentie tabel ophalen
# ------------------------------------------------------------
def load_sprinter_referentie_data() -> pl.DataFrame:
    """
    Laadt de sprinter referentie tabel  uit de database.
    """
    sql = "SELECT * FROM sprinters_referentie_data"
    with get_connection() as conn:
        df = pl.read_database(sql, conn)
    SNAPSHOT_STORE.repository_snapshot_sprinter_referentie_data = df
    # return compact_float64(df)



# ------------------------------------------------------------
# transacties laden
# ------------------------------------------------------------

def load_alle_transacties() -> pl.DataFrame:
    """
    Laadt alle transacties uit de database.
    """
    sql = "SELECT * FROM transacties_bron_data_org"  # vervang door jouw Access-query
    with get_connection() as conn:
        df = pl.read_database(sql, conn)
    compact_float64(df)
    SNAPSHOT_STORE.repository_snapshot_alle_transacties = df
    
    

# ------------------------------------------------------------
# Aandelen, zowel open als gesloten
# ------------------------------------------------------------
def load_aandelen_from_tx(df_tx: pl.DataFrame | None = None) -> pl.DataFrame:
    if df_tx is None:
        if SNAPSHOT_STORE.repository_snapshot_alle_transacties is None:
            raise ValueError("Transactiedata is niet geladen in SnapshotStore.")
        df_tx = SNAPSHOT_STORE.repository_snapshot_alle_transacties

    df_koop = (
        df_tx.filter((pl.col("asset_type") == "aandeel") & (pl.col("transactie_type") == "koop"))
        .group_by(["broker", "asset_rollup", "asset_type"])
        .agg([
            pl.sum("transactie_aantal").alias("aantal_koop"),
            pl.sum("transactie_euro_totaal").alias("euro_koop"),
            pl.sum("transactie_fee").alias("fee_koop"),
        ])
    )

    df_verkoop = (
        df_tx.filter((pl.col("asset_type") == "aandeel") & (pl.col("transactie_type") == "verkoop"))
        .group_by(["broker", "asset_rollup", "asset_type"])
        .agg([
            pl.sum("transactie_aantal").alias("aantal_verkoop"),
            pl.sum("transactie_euro_totaal").alias("euro_verkoop"),
            pl.sum("transactie_fee").alias("fee_verkoop"),
        ])
    )

    df = df_koop.join(df_verkoop, on=["broker", "asset_rollup", "asset_type"], how="outer").fill_null(0)
    
    df = df.with_columns([
        (pl.col("aantal_koop") + pl.col("aantal_verkoop")).alias("aantal_bezit"),
        (pl.col("fee_koop") + pl.col("fee_verkoop")).alias("eq_total_fee"),
    ]
    )
    SNAPSHOT_STORE.repository_snapshot_aandelen = df
    
    


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
    # SNAPSHOT_STORE.snapshot_load_open_opties_from_tx = per_uniek_filtered
    SNAPSHOT_STORE.repository_snapshot_load_open_opties = per_uniek_filtered
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
            pl.sum("SomVantransactie_fee").alias("SomVanSomVantransactie_fee"),
            pl.sum("SomVantransactie_euro_totaal").alias("SomVanSomVantransactie_euro_totaal"),
            pl.sum("SomVantransactie_aantal").alias("SomVanSomVantransactie_aantal")
        ])
        .sort(["broker", "asset_rollup"])
    )
    SNAPSHOT_STORE.repository_snapshot_gesloten_opties = df_final
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
            pl.sum("SomVanSomVantransactie_fee").alias("clos_opt_transactie_fee"),
            pl.sum("SomVanSomVantransactie_euro_totaal").alias("clos_opt_transactie_euro_totaal"),
        ])
        .sort("asset_rollup")
    )

    # Sla het resultaat op in snapshot_gesloten_opties_no_broker
    SNAPSHOT_STORE.repository_snapshot_gesloten_opties_no_broker = df_final
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

    

    vandaag = date.today()

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
    SNAPSHOT_STORE.repository_snapshot_open_sprinters = per_uniek_filtered
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

    vandaag = date.today()

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
            pl.sum("transactie_fee").alias("SomVantransactie_fee"),
            pl.sum("transactie_euro_totaal").alias("SomVantransactie_euro_totaal"),
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
            pl.sum("SomVantransactie_fee").alias("SomVanSomVantransactie_fee"),
            pl.sum("SomVantransactie_euro_totaal").alias("SomVanSomVantransactie_euro_totaal"),
            pl.sum("SomVantransactie_aantal").alias("SomVanSomVantransactie_aantal")
        ])
        .sort(["broker", "asset_rollup"])
    )
    SNAPSHOT_STORE.repository_snapshot_gesloten_sprinters = df_final
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
    data = dict(data); data.pop("uniek_id", None)
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
        cursor = conn.cursor()
        # Maak placeholders voor IN clause
        placeholders = ",".join("?" * len(ids_to_delete))
        sql = f"DELETE FROM transacties_bron_data_org WHERE Id IN ({placeholders})"
        cursor.execute(sql, ids_to_delete)
        deleted_count = cursor.rowcount
        conn.commit()
    return deleted_count


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
        if pd.isna(x) or str(x).strip() == "":
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
        conds.append("asset_rollup = ?"); params.append(ar)
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
            conds.append(f"[{col}] = ?"); params.append(v)

        elif op == "contains":
            conds.append(f"[{col}] LIKE ?"); params.append(f"%{v}%")

        elif op == "startswith":
            conds.append(f"[{col}] LIKE ?"); params.append(f"{v}%")

        elif op == "endswith":
            conds.append(f"[{col}] LIKE ?"); params.append(f"%{v}")

        elif op == "date_on":
            d = _parse_date(v)
            if d:
                conds.append(f"([{col}] >= ? AND [{col}] < ?)"); params.extend([d, d + timedelta(days=1)])

        elif op == "date_between":
            if isinstance(v, (list, tuple)) and len(v) >= 2:
                d1 = _parse_date(v[0]); d2 = _parse_date(v[1])
                if d1 and d2:
                    conds.append(f"[{col}] BETWEEN ? AND ?"); params.extend([d1, d2])

        elif op == "gte":
            conds.append(f"[{col}] >= ?"); params.append(v)

        elif op == "lte":
            conds.append(f"[{col}] <= ?"); params.append(v)
    
    where_sql = (" WHERE " + " AND ".join(conds)) if conds else ""
    return where_sql, params

def _order_by_for_seek(col: str, direction: str) -> str: ########################## niet genoemd door chatgpt om te blijven?
    col_db = ALLOWED_SORT_COLS.get(col, "Id")
    dirn = "DESC" if str(direction).upper() == "DESC" else "ASC"
    return f" ORDER BY {col_db} {dirn}, Id {dirn}"

def _seek_predicate(col: str, direction: str) -> str: ########################## niet genoemd door chatgpt om te blijven?
    col_db = ALLOWED_SORT_COLS.get(col, "Id")
    dirn = str(direction).upper()
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
                SELECT TOP {int(limit)} *
                FROM [{table}]
                {where_sql}
                {_order_by_for_seek(sort_col, sort_dir)}
            """
            return pd.read_sql(sql, conn, params=params)
        else:
            pred = _seek_predicate(sort_col, sort_dir)
            where2 = where_sql + (" AND " if where_sql else " WHERE ") + pred
            sql = f"""
                SELECT TOP {int(limit)} *
                FROM [{table}]
                {where2}
                {_order_by_for_seek(sort_col, sort_dir)}
            """
            return pd.read_sql(sql, conn, params=[*params, seek_value, seek_value, int(seek_id)])


def load_reference_lists():
    """Haal lijsten voor comboboxen op."""
    try:
        with get_connection() as conn:
            brokers = pd.read_sql("SELECT DISTINCT broker FROM transacties_bron_data_org", conn)["broker"].dropna().astype(str).tolist()
            rollups = pd.read_sql("SELECT DISTINCT asset_rollup FROM asset_rollup_data", conn)["asset_rollup"].dropna().astype(str).tolist()
            sprinters = pd.read_sql("SELECT DISTINCT asset_detail FROM sprinters_referentie_data", conn)["asset_detail"].dropna().astype(str).tolist()
    except Exception:
        brokers, rollups, sprinters = [], [], []
    return brokers, rollups, sprinters


import pyodbc

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

def update_transactions_atomic(record_id1: int, data1: dict,
                               record_id2: int | None = None, data2: dict | None = None):
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

def _clean(x): ########################## niet genoemd door chatgpt om te blijven?????? 
    return "" if x is None else str(x).strip()

def _parse_date(x):
    from datetime import date, datetime
    if x in (None, ""): return None
    if isinstance(x, datetime): return x.date()
    if isinstance(x, date): return x
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
    if s == "":
        return None
    try:
        return int(float(s))
    except Exception:
        return None



def _date_for_id(x): ########################## niet genoemd door chatgpt om te blijven?
    d = _parse_date(x)
    return "" if not d else f"{d.day}-{d.month}-{d.year}"

def _norm_dec_for_id(x): ########################## niet genoemd door chatgpt om te blijven?
    if x in (None, ""): return ""
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

def is_pairable(order: dict) -> bool:
    """
    Bepaal of een order koppelbaar is (d.w.z. dat er een tweede transactie bij hoort).
    Gebruikt het transactie_oorsprong veld.
    """
    oorspr = (order.get("transactie_oorsprong") or "").upper()
    return oorspr in {"DOORROL", "ASSIGN", "EXPIRE", "EXERCISE"}


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

