# services/test_orders_repository.py (of onderaan repository.py)
import datetime as dt
import uuid
import pandas as pd
import polars as pl
from portefeuille_viewer.data.repository import get_connection
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE


TEST_ORDER_SCENARIOS_TABLE = "transacties_test_order_scenarios"
TEST_ORDER_SCENARIO_CONTENT_TABLE = "transacties_test_order_scenario_content"
DEFAULT_TEST_ORDER_SCENARIO_NAME = "Default"
SCENARIO_ORDER_UID_COL = "scenario_order_uid"
SOURCE_BUCKET_COL = "source_bucket"
SOURCE_TYPE_COL = "source_type"
BASE_POSITION_UNIEK_ID_COL = "base_position_uniek_id"
PARENT_CHANGE_UID_COL = "parent_change_uid"
CHANGE_KIND_COL = "change_kind"

BUCKET_1 = "bucket_1"

TEST_ORDER_COLS = [
    "broker",
    "asset_rollup",
    "asset_type",          # bv. "equity"/"option"
    "transactie_type",     # "buy"/"sell" of "koop"/"verkoop"
    "transactie_aantal",   # let op spelling conform tabel!
    "transactie_prijs",
    "optie_call_put",
    "optie_strike",
    "optie_exp_date",
    "create_date",
    "include",
    SCENARIO_ORDER_UID_COL,
    SOURCE_BUCKET_COL,
    SOURCE_TYPE_COL,
    BASE_POSITION_UNIEK_ID_COL,
    PARENT_CHANGE_UID_COL,
    CHANGE_KIND_COL,
]

def _empty_orders_df() -> pl.DataFrame:
    return pl.DataFrame({c: [] for c in ["Id"] + TEST_ORDER_COLS})


def _empty_scenarios_df() -> pl.DataFrame:
    return pl.DataFrame(
        {"scenario_id": [], "scenario_name": [], "description": [], "created_at": [], "updated_at": []}
    )


def _table_exists(cur, table_name: str) -> bool:
    try:
        rows = list(cur.tables(table=table_name))
        return bool(rows)
    except Exception:
        return False


def _column_names(cur, table_name: str) -> set[str]:
    try:
        return {str(row.column_name) for row in cur.columns(table=table_name)}
    except Exception:
        return set()


def ensure_test_order_scenario_schema() -> None:
    with get_connection() as conn:
        cur = conn.cursor()

        # Base tabel uitbreiden met scenario metadata voor bucket 1/2/3.
        cols = _column_names(cur, "transacties_test_orders")
        if SCENARIO_ORDER_UID_COL not in cols:
            try:
                cur.execute(
                    f"ALTER TABLE transacties_test_orders ADD COLUMN {SCENARIO_ORDER_UID_COL} TEXT(64)"
                )
            except Exception:
                pass
        for col_name in (
            SOURCE_BUCKET_COL,
            SOURCE_TYPE_COL,
            BASE_POSITION_UNIEK_ID_COL,
            PARENT_CHANGE_UID_COL,
            CHANGE_KIND_COL,
        ):
            if col_name not in cols:
                try:
                    cur.execute(
                        f"ALTER TABLE transacties_test_orders ADD COLUMN {col_name} TEXT(255)"
                    )
                except Exception:
                    pass

        # Missende uid's backfillen zodat scenario-content niet op vluchtige autonummers hoeft te leunen.
        try:
            rows = cur.execute(
                f"SELECT Id FROM transacties_test_orders WHERE {SCENARIO_ORDER_UID_COL} IS NULL OR {SCENARIO_ORDER_UID_COL}=''"
            ).fetchall()
            for row in rows:
                cur.execute(
                    f"UPDATE transacties_test_orders SET {SCENARIO_ORDER_UID_COL}=? WHERE Id=?",
                    (str(uuid.uuid4()), int(row[0])),
                )
        except Exception:
            pass
        try:
            cur.execute(
                f"UPDATE transacties_test_orders SET {SOURCE_BUCKET_COL}=? "
                f"WHERE {SOURCE_BUCKET_COL} IS NULL OR {SOURCE_BUCKET_COL}=''",
                (BUCKET_1,),
            )
        except Exception:
            pass

        if not _table_exists(cur, TEST_ORDER_SCENARIOS_TABLE):
            try:
                cur.execute(
                    f"""
                    CREATE TABLE {TEST_ORDER_SCENARIOS_TABLE} (
                        scenario_id COUNTER PRIMARY KEY,
                        scenario_name TEXT(255),
                        description TEXT(255),
                        created_at DATETIME,
                        updated_at DATETIME
                    )
                    """
                )
            except Exception:
                pass

        if not _table_exists(cur, TEST_ORDER_SCENARIO_CONTENT_TABLE):
            try:
                cur.execute(
                    f"""
                    CREATE TABLE {TEST_ORDER_SCENARIO_CONTENT_TABLE} (
                        id COUNTER PRIMARY KEY,
                        scenario_id LONG,
                        {SCENARIO_ORDER_UID_COL} TEXT(64),
                        enabled BIT,
                        execution_family TEXT(64),
                        expected_outcome TEXT(64),
                        override_price DOUBLE,
                        override_amount DOUBLE,
                        updated_at DATETIME
                    )
                    """
                )
            except Exception:
                pass

        try:
            cur.execute(
                f"CREATE INDEX idx_{TEST_ORDER_SCENARIOS_TABLE}_name ON {TEST_ORDER_SCENARIOS_TABLE} (scenario_name)"
            )
        except Exception:
            pass
        try:
            cur.execute(
                f"CREATE INDEX idx_{TEST_ORDER_SCENARIO_CONTENT_TABLE}_scenario ON {TEST_ORDER_SCENARIO_CONTENT_TABLE} (scenario_id)"
            )
        except Exception:
            pass
        try:
            cur.execute(
                f"CREATE INDEX idx_{TEST_ORDER_SCENARIO_CONTENT_TABLE}_uid ON {TEST_ORDER_SCENARIO_CONTENT_TABLE} ({SCENARIO_ORDER_UID_COL})"
            )
        except Exception:
            pass

        conn.commit()


def list_test_order_scenarios() -> pl.DataFrame:
    ensure_test_order_scenario_schema()
    with get_connection() as conn:
        pdf = pd.read_sql(
            f"""
            SELECT scenario_id, scenario_name, description, created_at, updated_at
            FROM {TEST_ORDER_SCENARIOS_TABLE}
            ORDER BY updated_at DESC, created_at DESC, scenario_id DESC
            """,
            conn,
        )
    return pl.from_pandas(pdf) if not pdf.empty else pl.DataFrame(
        {"scenario_id": [], "scenario_name": [], "description": [], "created_at": [], "updated_at": []}
    )


def load_test_order_scenarios_cache_from_db() -> None:
    ensure_test_order_scenario_schema()
    scenarios_df = list_test_order_scenarios()
    with get_connection() as conn:
        pdf = pd.read_sql(
            f"""
            SELECT scenario_id, {SCENARIO_ORDER_UID_COL}, enabled, execution_family, expected_outcome, override_price, override_amount, updated_at
            FROM {TEST_ORDER_SCENARIO_CONTENT_TABLE}
            """,
            conn,
        )
    content_cache: dict[int, dict[str, dict]] = {}
    if not pdf.empty:
        for row in pdf.to_dict(orient="records"):
            sid = int(row.get("scenario_id"))
            uid = str(row.get(SCENARIO_ORDER_UID_COL) or "").strip()
            if not uid:
                continue
            content_cache.setdefault(sid, {})[uid] = row
    SNAPSHOT_STORE.repository_snapshot_test_order_scenarios = scenarios_df
    SNAPSHOT_STORE.repository_snapshot_test_order_scenario_content = content_cache
    SNAPSHOT_STORE.repository_dirty_test_order_scenarios = False
    SNAPSHOT_STORE.repository_deleted_test_order_scenario_ids = set()


def get_cached_test_order_scenarios() -> pl.DataFrame:
    df = getattr(SNAPSHOT_STORE, "repository_snapshot_test_order_scenarios", None)
    return df if df is not None else _empty_scenarios_df()


def get_cached_test_order_scenario_content_map(scenario_id: int | None) -> dict[str, dict]:
    if scenario_id is None:
        return {}
    cache = getattr(SNAPSHOT_STORE, "repository_snapshot_test_order_scenario_content", {}) or {}
    return dict(cache.get(int(scenario_id), {}) or {})


def get_effective_test_orders_for_asset(
    asset_rollup: str,
    scenario_id: int | None = None,
) -> pl.DataFrame:
    df_orders = get_cached_orders(asset_rollup)
    if df_orders is None or getattr(df_orders, "is_empty", lambda: True)():
        return df_orders
    effective_scenario_id = (
        scenario_id
        if scenario_id is not None
        else getattr(SNAPSHOT_STORE, "runtime_active_test_order_scenario_id", None)
    )
    if effective_scenario_id is None or SCENARIO_ORDER_UID_COL not in df_orders.columns:
        return df_orders
    content_map = get_cached_test_order_scenario_content_map(effective_scenario_id)
    enabled_uids = {
        uid for uid, row in content_map.items()
        if int(row.get("enabled") or 0) == 1
    }
    return df_orders.with_columns(
        pl.col(SCENARIO_ORDER_UID_COL)
        .cast(pl.Utf8, strict=False)
        .map_elements(
            lambda uid: 1 if str(uid or "").strip() in enabled_uids else 0,
            return_dtype=pl.Int64,
        )
        .alias("include")
    )


def create_test_order_scenario_in_cache(name: str, *, description: str | None = None) -> int:
    ensure_test_order_scenario_schema()
    scenario_name = str(name or "").strip()
    if not scenario_name:
        raise ValueError("scenario_name is verplicht")
    df = get_cached_test_order_scenarios()
    if not df.is_empty():
        existing = df.filter(pl.col("scenario_name") == scenario_name)
        if existing.height > 0:
            return int(existing["scenario_id"][0])
    ids = df["scenario_id"].to_list() if not df.is_empty() else []
    negative_ids = [int(v) for v in ids if int(v) < 0]
    temp_id = (min(negative_ids) - 1) if negative_ids else -1
    now = dt.datetime.now()
    new_row = pl.DataFrame(
        {
            "scenario_id": [temp_id],
            "scenario_name": [scenario_name],
            "description": [description],
            "created_at": [now],
            "updated_at": [now],
        }
    )
    SNAPSHOT_STORE.repository_snapshot_test_order_scenarios = (
        pl.concat([df, new_row], how="diagonal_relaxed") if not df.is_empty() else new_row
    )
    cache = getattr(SNAPSHOT_STORE, "repository_snapshot_test_order_scenario_content", {}) or {}
    cache.setdefault(temp_id, {})
    SNAPSHOT_STORE.repository_snapshot_test_order_scenario_content = cache
    SNAPSHOT_STORE.repository_dirty_test_order_scenarios = True
    return temp_id


def rename_test_order_scenario_in_cache(scenario_id: int, new_name: str) -> int:
    ensure_test_order_scenario_schema()
    scenario_id = int(scenario_id)
    scenario_name = str(new_name or "").strip()
    if not scenario_name:
        raise ValueError("scenario_name is verplicht")
    df = get_cached_test_order_scenarios()
    if df.is_empty():
        raise ValueError("Scenario bestaat niet")
    duplicate = df.filter(
        (pl.col("scenario_name") == scenario_name) & (pl.col("scenario_id") != scenario_id)
    )
    if duplicate.height > 0:
        raise ValueError("Scenario naam bestaat al")
    if scenario_name == DEFAULT_TEST_ORDER_SCENARIO_NAME:
        duplicate_default = df.filter(pl.col("scenario_name") == DEFAULT_TEST_ORDER_SCENARIO_NAME)
        if duplicate_default.height > 0 and int(duplicate_default["scenario_id"][0]) != scenario_id:
            raise ValueError("Scenario naam bestaat al")
    now = dt.datetime.now()
    updated = df.with_columns([
        pl.when(pl.col("scenario_id") == scenario_id)
        .then(pl.lit(scenario_name))
        .otherwise(pl.col("scenario_name"))
        .alias("scenario_name"),
        pl.when(pl.col("scenario_id") == scenario_id)
        .then(pl.lit(now))
        .otherwise(pl.col("updated_at"))
        .alias("updated_at"),
    ])
    SNAPSHOT_STORE.repository_snapshot_test_order_scenarios = updated
    SNAPSHOT_STORE.repository_dirty_test_order_scenarios = True
    return scenario_id


def delete_test_order_scenario_in_cache(scenario_id: int) -> None:
    ensure_test_order_scenario_schema()
    scenario_id = int(scenario_id)
    df = get_cached_test_order_scenarios()
    if df.is_empty():
        return
    target = df.filter(pl.col("scenario_id") == scenario_id)
    if target.is_empty():
        return
    scenario_name = str(target["scenario_name"][0] or "").strip()
    if scenario_name == DEFAULT_TEST_ORDER_SCENARIO_NAME:
        raise ValueError("Default scenario kan niet verwijderd worden")
    SNAPSHOT_STORE.repository_snapshot_test_order_scenarios = df.filter(pl.col("scenario_id") != scenario_id)
    cache = getattr(SNAPSHOT_STORE, "repository_snapshot_test_order_scenario_content", {}) or {}
    if scenario_id in cache:
        del cache[scenario_id]
    SNAPSHOT_STORE.repository_snapshot_test_order_scenario_content = cache
    deleted = getattr(SNAPSHOT_STORE, "repository_deleted_test_order_scenario_ids", set()) or set()
    if scenario_id > 0:
        deleted.add(scenario_id)
    SNAPSHOT_STORE.repository_deleted_test_order_scenario_ids = deleted
    SNAPSHOT_STORE.repository_dirty_test_order_scenarios = True


def save_test_order_scenario(name: str, *, description: str | None = None) -> int:
    ensure_test_order_scenario_schema()
    scenario_name = str(name or "").strip()
    if not scenario_name:
        raise ValueError("scenario_name is verplicht")
    with get_connection() as conn:
        cur = conn.cursor()
        row = cur.execute(
            f"SELECT TOP 1 scenario_id FROM {TEST_ORDER_SCENARIOS_TABLE} WHERE scenario_name=?",
            (scenario_name,),
        ).fetchone()
        now = dt.datetime.now()
        if row:
            scenario_id = int(row[0])
            cur.execute(
                f"UPDATE {TEST_ORDER_SCENARIOS_TABLE} SET description=?, updated_at=? WHERE scenario_id=?",
                (description, now, scenario_id),
            )
        else:
            cur.execute(
                f"""
                INSERT INTO {TEST_ORDER_SCENARIOS_TABLE} (scenario_name, description, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (scenario_name, description, now, now),
            )
            cur.execute("SELECT @@IDENTITY")
            scenario_id = int(cur.fetchone()[0])
        conn.commit()
    return scenario_id


def ensure_default_test_order_scenario() -> int:
    ensure_test_order_scenario_schema()
    load_test_order_scenarios_cache_from_db()
    df = get_cached_test_order_scenarios()
    if not df.is_empty():
        existing = df.filter(pl.col("scenario_name") == DEFAULT_TEST_ORDER_SCENARIO_NAME)
        if existing.height > 0:
            scenario_id = int(existing["scenario_id"][0])
        else:
            scenario_id = create_test_order_scenario_in_cache(DEFAULT_TEST_ORDER_SCENARIO_NAME)
    else:
        scenario_id = create_test_order_scenario_in_cache(DEFAULT_TEST_ORDER_SCENARIO_NAME)
    content_map = get_cached_test_order_scenario_content_map(scenario_id)
    if not content_map:
        base_df = get_test_orders(asset_rollup=None, scenario_id=None)
        save_scenario_content_for_visible_rows(scenario_id, base_df)
    return scenario_id


def get_test_order_scenario_content_map(scenario_id: int) -> dict[str, dict]:
    ensure_test_order_scenario_schema()
    with get_connection() as conn:
        pdf = pd.read_sql(
            f"""
            SELECT {SCENARIO_ORDER_UID_COL}, enabled, execution_family, expected_outcome, override_price, override_amount
            FROM {TEST_ORDER_SCENARIO_CONTENT_TABLE}
            WHERE scenario_id=?
            """,
            conn,
            params=[int(scenario_id)],
        )
    if pdf.empty:
        return {}
    out = {}
    for row in pdf.to_dict(orient="records"):
        uid = str(row.get(SCENARIO_ORDER_UID_COL) or "").strip()
        if not uid:
            continue
        out[uid] = row
    return out


def save_scenario_content_for_visible_rows(scenario_id: int, df: pl.DataFrame | None) -> None:
    ensure_test_order_scenario_schema()
    if df is None or getattr(df, "is_empty", lambda: True)():
        return
    if SCENARIO_ORDER_UID_COL not in df.columns:
        return
    rows = df.to_dicts()
    visible_uids = [
        str(row.get(SCENARIO_ORDER_UID_COL) or "").strip()
        for row in rows
        if str(row.get(SCENARIO_ORDER_UID_COL) or "").strip()
    ]
    cache = getattr(SNAPSHOT_STORE, "repository_snapshot_test_order_scenario_content", {}) or {}
    scenario_map = dict(cache.get(int(scenario_id), {}) or {})
    for uid in visible_uids:
        scenario_map.pop(uid, None)
    now = dt.datetime.now()
    for row in rows:
        uid = str(row.get(SCENARIO_ORDER_UID_COL) or "").strip()
        if not uid:
            continue
        enabled = 1 if (str(row.get("include", 0)).strip() in {"1", "True", "true"} or row.get("include") == 1) else 0
        scenario_map[uid] = {
            "scenario_id": int(scenario_id),
            SCENARIO_ORDER_UID_COL: uid,
            "enabled": enabled,
            "execution_family": None,
            "expected_outcome": None,
            "override_price": None,
            "override_amount": None,
            "updated_at": now,
        }
    cache[int(scenario_id)] = scenario_map
    SNAPSHOT_STORE.repository_snapshot_test_order_scenario_content = cache
    scenarios_df = get_cached_test_order_scenarios()
    if not scenarios_df.is_empty() and int(scenario_id) in [int(v) for v in scenarios_df["scenario_id"].to_list()]:
        SNAPSHOT_STORE.repository_snapshot_test_order_scenarios = scenarios_df.with_columns(
            pl.when(pl.col("scenario_id") == int(scenario_id))
            .then(pl.lit(now))
            .otherwise(pl.col("updated_at"))
            .alias("updated_at")
        )
    SNAPSHOT_STORE.repository_dirty_test_order_scenarios = True


def flush_dirty_test_order_scenarios_to_db() -> None:
    dirty = bool(getattr(SNAPSHOT_STORE, "repository_dirty_test_order_scenarios", False))
    if not dirty:
        return
    ensure_test_order_scenario_schema()
    scenarios_df = get_cached_test_order_scenarios()
    content_cache = getattr(SNAPSHOT_STORE, "repository_snapshot_test_order_scenario_content", {}) or {}
    deleted_ids = getattr(SNAPSHOT_STORE, "repository_deleted_test_order_scenario_ids", set()) or set()
    if scenarios_df is None:
        return
    id_map: dict[int, int] = {}
    with get_connection() as conn:
        cur = conn.cursor()
        for deleted_id in sorted(int(v) for v in deleted_ids if int(v) > 0):
            cur.execute(f"DELETE FROM {TEST_ORDER_SCENARIO_CONTENT_TABLE} WHERE scenario_id = ?", (deleted_id,))
            cur.execute(f"DELETE FROM {TEST_ORDER_SCENARIOS_TABLE} WHERE scenario_id = ?", (deleted_id,))
        # Upsert scenario meta and remap temporary ids.
        for row in scenarios_df.to_dicts():
            sid = int(row.get("scenario_id"))
            name = str(row.get("scenario_name") or "").strip()
            if not name:
                continue
            description = row.get("description")
            created_at = row.get("created_at") or dt.datetime.now()
            updated_at = row.get("updated_at") or dt.datetime.now()
            if sid > 0:
                cur.execute(
                    f"UPDATE {TEST_ORDER_SCENARIOS_TABLE} SET scenario_name=?, description=?, created_at=?, updated_at=? WHERE scenario_id=?",
                    (name, description, created_at, updated_at, sid),
                )
                id_map[sid] = sid
            else:
                cur.execute(
                    f"""
                    INSERT INTO {TEST_ORDER_SCENARIOS_TABLE} (scenario_name, description, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (name, description, created_at, updated_at),
                )
                cur.execute("SELECT @@IDENTITY")
                new_id = int(cur.fetchone()[0])
                id_map[sid] = new_id
        # Rewrite full scenario content table from cache. Small enough for now.
        cur.execute(f"DELETE FROM {TEST_ORDER_SCENARIO_CONTENT_TABLE}")
        for old_sid, uid_map in content_cache.items():
            real_sid = id_map.get(int(old_sid), int(old_sid))
            for row in (uid_map or {}).values():
                uid = str(row.get(SCENARIO_ORDER_UID_COL) or "").strip()
                if not uid:
                    continue
                cur.execute(
                    f"""
                    INSERT INTO {TEST_ORDER_SCENARIO_CONTENT_TABLE}
                    (scenario_id, {SCENARIO_ORDER_UID_COL}, enabled, execution_family, expected_outcome, override_price, override_amount, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        real_sid,
                        uid,
                        int(row.get("enabled") or 0),
                        row.get("execution_family"),
                        row.get("expected_outcome"),
                        row.get("override_price"),
                        row.get("override_amount"),
                        row.get("updated_at") or dt.datetime.now(),
                    ),
                )
        conn.commit()
    # Remap in-memory ids after inserts of temporary scenarios.
    if id_map:
        rows = []
        for row in scenarios_df.to_dicts():
            old_sid = int(row.get("scenario_id"))
            row["scenario_id"] = id_map.get(old_sid, old_sid)
            rows.append(row)
        SNAPSHOT_STORE.repository_snapshot_test_order_scenarios = (
            pl.DataFrame(rows) if rows else _empty_scenarios_df()
        )
        remapped_content = {}
        for old_sid, uid_map in content_cache.items():
            real_sid = id_map.get(int(old_sid), int(old_sid))
            remapped_content[real_sid] = uid_map
        SNAPSHOT_STORE.repository_snapshot_test_order_scenario_content = remapped_content
    SNAPSHOT_STORE.repository_dirty_test_order_scenarios = False
    SNAPSHOT_STORE.repository_deleted_test_order_scenario_ids = set()


def get_test_orders(asset_rollup: str | None = None, scenario_id: int | None = None) -> pl.DataFrame:
    ensure_test_order_scenario_schema()
    where = " WHERE asset_rollup = ?" if asset_rollup else ""
    params = [asset_rollup] if asset_rollup else None
    sql = (
        f"SELECT Id, {SCENARIO_ORDER_UID_COL}, {SOURCE_BUCKET_COL}, {SOURCE_TYPE_COL}, "
        f"{BASE_POSITION_UNIEK_ID_COL}, {PARENT_CHANGE_UID_COL}, {CHANGE_KIND_COL}, "
        "broker, asset_rollup, asset_type, transactie_type, "
        "transactie_aantal, transactie_prijs, optie_call_put, "
        "optie_strike, optie_exp_date, create_date , include "
        "FROM transacties_test_orders" + where +
        " ORDER BY create_date DESC, Id DESC"
    )
    with get_connection() as conn:
        pdf = pd.read_sql(sql, conn, params=params)
    df = pl.from_pandas(pdf)
    # zorg voor consistente date/str weergave (UI verwacht strings)
    if "optie_exp_date" in df.columns:
        try:
            df = df.with_columns(
                pl.col("optie_exp_date")
                .cast(pl.Date)
                .dt.strftime("%d-%m-%Y")
                .fill_null("")
                .alias("optie_exp_date")
            )
        except Exception:
            df = df.with_columns(pl.col("optie_exp_date").cast(pl.Utf8).fill_null("").alias("optie_exp_date"))
    if "create_date" in df.columns:
        try:
            df = df.with_columns(
                pl.col("create_date")
                .cast(pl.Datetime)
                .dt.strftime("%d-%m-%Y %H:%M:%S")
                .fill_null("")
                .alias("create_date")
            )
        except Exception:
            df = df.with_columns(pl.col("create_date").cast(pl.Utf8).fill_null("").alias("create_date"))
    if SCENARIO_ORDER_UID_COL in df.columns:
        df = df.with_columns(pl.col(SCENARIO_ORDER_UID_COL).cast(pl.Utf8).fill_null("").alias(SCENARIO_ORDER_UID_COL))
    for col_name in (
        SOURCE_BUCKET_COL,
        SOURCE_TYPE_COL,
        BASE_POSITION_UNIEK_ID_COL,
        PARENT_CHANGE_UID_COL,
        CHANGE_KIND_COL,
    ):
        if col_name in df.columns:
            default_value = BUCKET_1 if col_name == SOURCE_BUCKET_COL else ""
            df = df.with_columns(pl.col(col_name).cast(pl.Utf8).fill_null(default_value).alias(col_name))
    if scenario_id is not None and df.height > 0 and SCENARIO_ORDER_UID_COL in df.columns:
        content_map = get_test_order_scenario_content_map(int(scenario_id))
        enabled_uids = {
            uid for uid, row in content_map.items()
            if int(row.get("enabled") or 0) == 1
        }
        df = df.with_columns(
            pl.col(SCENARIO_ORDER_UID_COL)
            .map_elements(lambda uid: 1 if str(uid or "").strip() in enabled_uids else 0, return_dtype=pl.Int64)
            .alias("include")
        )
    return df

def load_test_orders_cache_from_db(scenario_id: int | None = None):
    """Laad alle test orders in de snapshot cache (per asset_rollup)."""
    df_all = get_test_orders(asset_rollup=None, scenario_id=scenario_id)
    cache = {}
    if df_all.height > 0:
        unique_assets = df_all["asset_rollup"].unique().to_list()
        for asset in unique_assets:
            cache[asset] = df_all.filter(pl.col("asset_rollup") == asset)
    SNAPSHOT_STORE.repository_snapshot_test_orders_cache = cache
    SNAPSHOT_STORE.repository_dirty_test_orders_assets = set()

def get_cached_orders(asset_rollup: str) -> pl.DataFrame:
    cache = getattr(SNAPSHOT_STORE, "repository_snapshot_test_orders_cache", {}) or {}
    df = cache.get(asset_rollup)
    return df if df is not None else _empty_orders_df()

def set_cached_orders_for_asset(asset_rollup: str, df: pl.DataFrame):
    cache = getattr(SNAPSHOT_STORE, "repository_snapshot_test_orders_cache", {}) or {}
    cache[asset_rollup] = df
    SNAPSHOT_STORE.repository_snapshot_test_orders_cache = cache
    dirty = getattr(SNAPSHOT_STORE, "repository_dirty_test_orders_assets", set()) or set()
    dirty.add(asset_rollup)
    SNAPSHOT_STORE.repository_dirty_test_orders_assets = dirty

def flush_dirty_test_orders_to_db():
    """Schrijf alle dirty assets in cache terug naar DB: delete + bulk insert."""
    dirty = getattr(SNAPSHOT_STORE, "repository_dirty_test_orders_assets", set()) or set()
    if not dirty:
        return
    cache = getattr(SNAPSHOT_STORE, "repository_snapshot_test_orders_cache", {}) or {}
    with get_connection() as conn:
        cur = conn.cursor()
        for asset in list(dirty):
            df = cache.get(asset)
            if df is None or df.is_empty():
                # niets te schrijven, maar wel oude records verwijderen
                cur.execute("DELETE FROM transacties_test_orders WHERE asset_rollup = ?", (asset,))
                continue
            # delete oude rijen voor dit asset
            cur.execute("DELETE FROM transacties_test_orders WHERE asset_rollup = ?", (asset,))
            # insert alle rijen uit df
            cols = [c for c in TEST_ORDER_COLS]  # Id wordt autonummering
            placeholders = ", ".join(["?"] * len(cols))
            sql = f"INSERT INTO transacties_test_orders ({', '.join(cols)}) VALUES ({placeholders})"
            for row in df.iter_rows(named=True):
                norm_row = _normalize_order_row(row)
                values = [norm_row.get(c) for c in cols]
                cur.execute(sql, values)
        conn.commit()
    SNAPSHOT_STORE.repository_dirty_test_orders_assets = set()


def _normalize_order_row(row: dict) -> dict:
    data = dict(row)
    # lege strings naar None
    data = {k: (None if v == "" else v) for k, v in data.items()}

    def num(val):
        if val is None:
            return None
        try:
            return float(val)
        except Exception:
            return None

    def dt_val(val):
        if val is None:
            return None
        if isinstance(val, dt.datetime):
            return val
        if isinstance(val, dt.date):
            return dt.datetime.combine(val, dt.time.min)
        s = str(val).strip()
        # probeer dd-mm-yy of dd-mm-yyyy
        for fmt in ("%d-%m-%y", "%d-%m-%Y", "%d/%m/%y", "%d/%m/%Y"):
            try:
                return dt.datetime.strptime(s, fmt)
            except Exception:
                continue
        # laatste poging: ISO
        try:
            return dt.datetime.fromisoformat(s)
        except Exception:
            return None




    data["transactie_aantal"] = num(data.get("transactie_aantal"))
    data["transactie_prijs"] = num(data.get("transactie_prijs"))
    data["optie_strike"] = num(data.get("optie_strike"))
    data["optie_exp_date"] = dt_val(data.get("optie_exp_date"))
    data["create_date"] = dt_val(data.get("create_date")) or dt.datetime.now()
    uid = str(data.get(SCENARIO_ORDER_UID_COL) or "").strip()
    data[SCENARIO_ORDER_UID_COL] = uid or str(uuid.uuid4())
    data[SOURCE_BUCKET_COL] = str(data.get(SOURCE_BUCKET_COL) or "").strip() or BUCKET_1
    data[SOURCE_TYPE_COL] = str(data.get(SOURCE_TYPE_COL) or "").strip() or None
    data[BASE_POSITION_UNIEK_ID_COL] = str(data.get(BASE_POSITION_UNIEK_ID_COL) or "").strip() or None
    data[PARENT_CHANGE_UID_COL] = str(data.get(PARENT_CHANGE_UID_COL) or "").strip() or None
    data[CHANGE_KIND_COL] = str(data.get(CHANGE_KIND_COL) or "").strip() or None
    inc = data.get("include", 1)
    try:
        data["include"] = int(inc)
    except Exception:
        data["include"] = 1
    return data



def insert_test_order(row: dict) -> int:
    data = _normalize_order_row(row)
    data.setdefault("create_date", dt.datetime.now())
    cols = [c for c in TEST_ORDER_COLS if c in data]
    placeholders = ", ".join(["?"] * len(cols))
    sql = f"INSERT INTO transacties_test_orders ({', '.join(cols)}) VALUES ({placeholders})"
    values = [data.get(c) for c in cols]
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, values)
        cur.execute("SELECT @@IDENTITY")
        new_id = cur.fetchone()[0]
        conn.commit()
    return int(new_id)

def update_test_order(order_id: int, row: dict) -> None:
    data = _normalize_order_row(row)
    data = {k: v for k, v in data.items() if k in TEST_ORDER_COLS}
    if not data:
        return
    set_clause = ", ".join([f"{k}=?" for k in data.keys()])
    sql = f"UPDATE transacties_test_orders SET {set_clause} WHERE Id=?"
    params = list(data.values()) + [order_id]
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()

def delete_test_order(order_id: int) -> None:
    with get_connection() as conn:
        cur = conn.cursor()
        uid_row = None
        try:
            uid_row = cur.execute(
                f"SELECT {SCENARIO_ORDER_UID_COL} FROM transacties_test_orders WHERE Id=?",
                (order_id,),
            ).fetchone()
        except Exception:
            uid_row = None
        if uid_row and uid_row[0]:
            try:
                cur.execute(
                    f"DELETE FROM {TEST_ORDER_SCENARIO_CONTENT_TABLE} WHERE {SCENARIO_ORDER_UID_COL}=?",
                    (str(uid_row[0]),),
                )
            except Exception:
                pass
        cur.execute("DELETE FROM transacties_test_orders WHERE Id=?", (order_id,))
        conn.commit()
