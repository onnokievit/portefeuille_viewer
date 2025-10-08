import pandas as pd
import pyodbc
from datetime import date, datetime, timedelta
import warnings
import numpy as np

warnings.filterwarnings(
    "ignore",
    message="pandas only supports SQLAlchemy connectable",
    category=UserWarning,
)

# ------------------------------------------------------------
# Database configuratie
# ------------------------------------------------------------
DB_MAP = {
    "ONNO-PRODUCTIE": r"C:\Users\onno\OneDrive\Beleggen\2025 - portefeuille database 02.03 - ONNO.accdb",
    "ONNO-TEST":      r"C:\Users\onno\OneDrive\Beleggen\2025 - portefeuille database 02.03 - ONNO - test.accdb",
    "MURIEL":         r"C:\Users\onno\OneDrive\Beleggen\2025 - portefeuille database 02.03 - MURIEL.accdb",
    "MURIEL-TEST":    r"C:\Users\onno\OneDrive\Beleggen\2025 - portefeuille database 02.03 - MURIEL - test.accdb",
}
DB_STYLES = {
    "ONNO-PRODUCTIE": {"fg": "white",  "bg": "#09890f"},
    "ONNO-TEST":      {"fg": "black",  "bg": "orange"},
    "MURIEL":         {"fg": "black",  "bg": "pink"},
}
DEFAULT_DB_NAME = next(iter(DB_MAP.keys()))
db_path = DB_MAP[DEFAULT_DB_NAME]
conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path};"

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

def _connect():
    return pyodbc.connect(conn_str, autocommit=True)


# ------------------------------------------------------------
# Orders tab helpers
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



# repository.py
# --- Vervanging begint hier ---
ALLOWED_SORT_COLS = {c: c for c in TABLE_COLS}

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

def _order_by_for_seek(col: str, direction: str) -> str:
    col_db = ALLOWED_SORT_COLS.get(col, "Id")
    dirn = "DESC" if str(direction).upper() == "DESC" else "ASC"
    return f" ORDER BY {col_db} {dirn}, Id {dirn}"

def _seek_predicate(col: str, direction: str) -> str:
    col_db = ALLOWED_SORT_COLS.get(col, "Id")
    dirn = str(direction).upper()
    if dirn == "ASC":
        return f"(({col_db} > ?) OR ({col_db} = ? AND Id > ?))"
    else:
        return f"(({col_db} < ?) OR ({col_db} = ? AND Id < ?))"

def fetch_records_page(
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
# --- Einde vervanging ---






# ------------------------------------------------------------
# Live View tab helpers
# ------------------------------------------------------------
def coalesce_cols(df: pd.DataFrame, out_col: str, *cands: str):
    vals = None
    for c in cands:
        if c in df.columns:
            vals = df[c] if vals is None else vals.where(vals.notna(), df[c])
    df[out_col] = vals if vals is not None else pd.NA


def load_assetrollup_to_ib():
    """
    Leest asset_rollup_data en koppelt aan IB symbolen.
    Gefilterd en opgeschoond zoals in de 1-bestand versie.
    """
    try:
        with get_connection() as conn:
            df = pd.read_sql(
                """SELECT asset_rollup, ib_symbol, ib_currency, prim_exchange
                   FROM asset_rollup_data
                   WHERE ib_symbol IS NOT NULL AND ib_currency IS NOT NULL""",
                conn,
            )
    except Exception as e:
        print(f"[MAP] error: {e}")
        return pd.DataFrame()

    if df.empty:
        return df

    for c in ["asset_rollup", "ib_symbol", "ib_currency", "prim_exchange"]:
        df[c] = df[c].astype(str).str.strip()

    df = df[
        (df["asset_rollup"] != "")
        & (df["ib_symbol"] != "")
        & (df["ib_currency"] != "")
    ]
    df["_ar_key"] = df["asset_rollup"].str.casefold()
    df = df.drop_duplicates(subset=["_ar_key"]).reset_index(drop=True)

    return df[
        ["_ar_key", "asset_rollup", "ib_symbol", "ib_currency", "prim_exchange"]
    ]




def load_equity_flows() -> pd.DataFrame:
    """
    Bouwt samenvatting van aandelen-transacties (aandeel-type).
    Logica identiek aan 1-bestand-versie: correcte tekens, qty_eq, hist_eq, avg_entry_eq.
    """
    try:
        with get_connection() as conn:
            raw = pd.read_sql(
                """SELECT asset_rollup, asset_type, transactie_type,
                          aantal, transactie_euro_totaal, transactie_fee
                   FROM transacties_bron_data_org
                   WHERE asset_rollup IS NOT NULL""",
                conn,
            )
    except Exception as e:
        print(f"[EQ FLOWS] read error: {e}")
        return pd.DataFrame()

    if raw.empty:
        return pd.DataFrame()

    raw["asset_rollup"] = raw["asset_rollup"].astype(str).str.strip()
    raw["asset_type"] = raw["asset_type"].astype(str).str.strip().str.casefold()
    raw["transactie_type"] = raw["transactie_type"].astype(str).str.strip().str.casefold()
    for c in ["aantal", "transactie_euro_totaal", "transactie_fee"]:
        raw[c] = pd.to_numeric(raw[c], errors="coerce").fillna(0.0)

    df = raw[raw["asset_type"] == "aandeel"].copy()
    if df.empty:
        return pd.DataFrame()

    is_buy = df["transactie_type"].eq("koop")
    is_sell = df["transactie_type"].eq("verkoop")

    buy = df[is_buy].groupby("asset_rollup", as_index=False).agg(
        buy_qty=("aantal", "sum"),
        buy_eur=("transactie_euro_totaal", lambda s: -s.sum()),
        fee_buy=("transactie_fee", "sum"),
    )
    sell = df[is_sell].groupby("asset_rollup", as_index=False).agg(
        sell_qty=("aantal", "sum"),
        sell_eur=("transactie_euro_totaal", "sum"),
        fee_sell=("transactie_fee", "sum"),
    )

    flows = pd.merge(buy, sell, on="asset_rollup", how="outer").fillna(0.0)
    flows["qty_eq"] = flows["buy_qty"] - flows["sell_qty"]
    flows["fee_eq"] = flows["fee_buy"] + flows["fee_sell"]
    flows = flows.drop(columns=["fee_buy", "fee_sell"])

    def _avg_long(r):
        return (r.buy_eur / r.buy_qty) if r.buy_qty > 0 else 0.0

    def _avg_short(r):
        return (r.sell_eur / r.sell_qty) if r.sell_qty > 0 else 0.0

    def _hist_init(r):
        if r.qty_eq >= 0:
            av = _avg_long(r)
            return r.sell_eur - r.sell_qty * av
        else:
            avs = _avg_short(r)
            open_short_qty = -r.qty_eq
            return r.sell_eur - open_short_qty * avs - r.buy_eur

    flows["avg_entry_eq"] = flows.apply(
        lambda r: _avg_long(r) if r.qty_eq >= 0 else _avg_short(r), axis=1
    )
    flows["hist_eq"] = flows.apply(_hist_init, axis=1)
    flows["_ar_key"] = flows["asset_rollup"].str.casefold()
    


    return flows.reset_index(drop=True)



def load_sprinter_reference() -> pd.DataFrame:
    try:
        with _connect() as conn:
            ref = pd.read_sql("SELECT * FROM sprinters_referentie_data", conn)
    except Exception as e:
        print(f"[SPR REF] error: {e}")
        return pd.DataFrame()
    return ref

############################### start sprinter flows ###############################

def load_sprinter_flows() -> pd.DataFrame:
    """
    Retourneert alle sprinterposities op detailniveau (asset_detail).
    - Berekeningen per sprinter (geen aggregatie)
    - Funding (sprinter_funding) correct meegenomen
    - Fees niet inbegrepen (apart query)
    """

    import numpy as np
    import pandas as pd

    try:
        with get_connection() as conn:
            tx = pd.read_sql("""
                SELECT asset_rollup, asset_detail, asset_type, transactie_type,
                       aantal, transactie_prijs, transactie_euro_totaal
                FROM transacties_bron_data_org
                WHERE asset_type='sprinter'
            """, conn)

            ref = pd.read_sql("""
                SELECT asset_detail, sprinter_funding
                FROM sprinters_referentie_data
                WHERE sprinter_funding IS NOT NULL
            """, conn)
    except Exception as e:
        print(f"[SPRINTER FLOWS] read error: {e}")
        return pd.DataFrame()

    if tx.empty:
        return pd.DataFrame()

    # Normalisatie
    for c in ["asset_rollup", "asset_detail", "asset_type", "transactie_type"]:
        tx[c] = tx[c].astype(str).str.strip().str.lower()
    tx["aantal"] = pd.to_numeric(tx["aantal"], errors="coerce").fillna(0.0)
    tx["transactie_prijs"] = pd.to_numeric(tx["transactie_prijs"], errors="coerce").fillna(0.0)
    tx["transactie_euro_totaal"] = pd.to_numeric(tx["transactie_euro_totaal"], errors="coerce").fillna(0.0)

    # Koop / verkoop samenvatten per sprinter
    is_buy  = tx["transactie_type"].eq("koop")
    is_sell = tx["transactie_type"].eq("verkoop")
    grp = ["asset_detail", "asset_rollup"]

    buy = tx[is_buy].groupby(grp, as_index=False).agg(
        buy_qty=("aantal", "sum"),
        buy_eur=("transactie_euro_totaal", lambda s: -s.sum())
    )
    sell = tx[is_sell].groupby(grp, as_index=False).agg(
        sell_qty=("aantal", "sum"),
        sell_eur=("transactie_euro_totaal", "sum")
    )

    df = pd.merge(buy, sell, on=grp, how="outer").fillna(0.0)
    df["qty_spr"] = df["buy_qty"] - df["sell_qty"]

    # Gemiddelde aankoopprijs & historisch resultaat
    df["avg_entry_spr"] = np.where(df["buy_qty"] > 0, df["buy_eur"] / df["buy_qty"], 0.0)
    df["hist_spr"] = np.where(
        df["qty_spr"] >= 0,
        df["sell_eur"] - df["sell_qty"] * df["avg_entry_spr"],
        df["sell_eur"] - (-df["qty_spr"]) * (df["sell_eur"] / df["sell_qty"]) - df["buy_eur"]
    )

    # Funding koppelen per sprinter
    ref["asset_detail"] = ref["asset_detail"].astype(str).str.strip().str.lower()
    ref = ref.rename(columns={"sprinter_funding": "fund_w"})
    df = df.merge(ref, on="asset_detail", how="left")
    df["fund_w"] = pd.to_numeric(df["fund_w"], errors="coerce").fillna(0.0)

    # Extra kolom voor key-merge
    df["_ar_key"] = df["asset_rollup"].str.casefold()
    df["_spr_key"] = df["asset_detail"].str.casefold()

    return df.reset_index(drop=True)





################################ einde sprinter flows ###############################



def load_closed_options_summary(brokers: list[str] | None = None) -> pd.DataFrame:
    """
    Gesloten/verlopen opties per asset_rollup uit transacties_bron_data_org:
      - aantal = 0  (gesloten/opgerold)
      - OF (optie_exp_date IS NOT NULL AND optie_exp_date < Date())  (verlopen)
    Geeft per asset_rollup: som(premie) en som(fees).
    """
    import pandas as pd
    with get_connection() as conn:
        base_sql = """
        SELECT asset_rollup,
               SUM(transactie_euro_totaal) AS premie_opties,
               SUM(transactie_fee)         AS fees_opties
        FROM (
            SELECT asset_rollup, transactie_euro_totaal, transactie_fee
            FROM transacties_bron_data_org
            WHERE asset_type='optie' AND asset_rollup IS NOT NULL AND aantal=0
            {broker1}

            UNION ALL

            SELECT asset_rollup, transactie_euro_totaal, transactie_fee
            FROM transacties_bron_data_org
            WHERE asset_type='optie' AND asset_rollup IS NOT NULL
              AND (optie_exp_date IS NOT NULL AND optie_exp_date < Date())
            {broker2}
        ) q
        GROUP BY asset_rollup
        """
        params: list = []
        if brokers:
            ph = ",".join(["?"] * len(brokers))
            sql = base_sql.format(broker1=f"AND broker IN ({ph})",
                                  broker2=f"AND broker IN ({ph})")
            params = brokers + brokers  # voor beide SELECTs
        else:
            sql = base_sql.format(broker1="", broker2="")

        df = pd.read_sql(sql, conn, params=params)

    # normaliseren
    df.columns = [str(c).strip().lower() for c in df.columns]
    if df.empty:
        return pd.DataFrame(columns=["_ar_key","asset_rollup","premie_opties","fees_opties"])

    df["asset_rollup"]  = df["asset_rollup"].astype(str).str.strip()
    df["_ar_key"]       = df["asset_rollup"].str.casefold()
    df["premie_opties"] = pd.to_numeric(df["premie_opties"], errors="coerce").fillna(0.0)
    df["fees_opties"]   = pd.to_numeric(df["fees_opties"],   errors="coerce").fillna(0.0)
    return df[["_ar_key","asset_rollup","premie_opties","fees_opties"]]




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

def load_sprinter_fees() -> pd.DataFrame:
    """
    Haalt de som van alle sprintertransactie-fees op per asset_rollup.
    Equivalent aan de Access-query:
        SELECT asset_rollup, asset_type, SUM(transactie_fee)
        FROM transacties_bron_data_org
        WHERE asset_type='sprinter'
        GROUP BY asset_rollup, asset_type;
    """
    import pandas as pd
    try:
        with get_connection() as conn:
            df = pd.read_sql("""
                SELECT asset_rollup, SUM(transactie_fee) AS fee_spr
                FROM transacties_bron_data_org
                WHERE asset_type='sprinter'
                GROUP BY asset_rollup
            """, conn)
    except Exception as e:
        print(f"[SPRINTER FEES] read error: {e}")
        return pd.DataFrame(columns=["asset_rollup", "fee_spr"])

    df["_ar_key"] = df["asset_rollup"].str.casefold()
    # print("=== DEBUG SPRINTER FEES ===")
    # print(df.head(50))
    # print("Aantal regels:", len(df))
    return df




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

def _clean(x): 
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



def _date_for_id(x):
    d = _parse_date(x)
    return "" if not d else f"{d.day}-{d.month}-{d.year}"

def _norm_dec_for_id(x):
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


def build_portfolio_snapshot():
    """
    Bouwt een volledige portefeuille-snapshot:
    - Alle assets uit asset_rollup_data
    - Met equity en sprinter berekeningen
    """

    conn = get_connection()
    ar = pd.read_sql("SELECT * FROM asset_rollup_data", conn)
    eq = load_equity_flows()
    sp = load_sprinter_flows()

    # --- merge alles op asset_rollup
    df = ar.merge(eq, on="asset_rollup", how="left", suffixes=("", "_eq"))
    df = df.merge(sp, on="asset_rollup", how="left", suffixes=("", "_spr"))

    # --- bereken waarden
    df["Waarde_eq"] = df["current_price"] * df["qty_eq"].fillna(0)
    df["Waarde_spr"] = df["current_price"] * df["qty_spr"].fillna(0)

    df["Total_eq"] = df["Waarde_eq"].fillna(0) + df["total_eq"].fillna(0)
    df["Total_spr"] = df["Waarde_spr"].fillna(0) + df["total_spr"].fillna(0)
    df["Total_portefeuille"] = df["Total_eq"].fillna(0) + df["Total_spr"].fillna(0)

    # --- afronden en sorteren
    df = df.fillna(0)
    cols_order = [
        "asset_rollup", "ib_currency", "current_price",
        "qty_eq", "avg_entry_eq", "Waarde_eq", "total_eq",
        "qty_spr", "avg_entry_spr", "Waarde_spr", "total_spr",
        "Total_portefeuille"
    ]
    df = df[[c for c in cols_order if c in df.columns]].sort_values("asset_rollup")
    return df



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
    


    


