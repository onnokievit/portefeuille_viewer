import datetime as dt

import pandas as pd
import polars as pl

from portefeuille_viewer.data.repository import get_connection
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE


BETA_SHIFT_SCENARIOS_TABLE = "beta_shift_scenarios"
BETA_SHIFT_SCENARIO_CONTENT_TABLE = "beta_shift_scenario_content"
DEFAULT_BETA_SHIFT_SCENARIO_NAME = "Default"
GLOBAL_SHIFT_KEY = "__GLOBAL__"


def _empty_scenarios_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "scenario_id": [],
            "scenario_name": [],
            "lookback_code": [],
            "created_at": [],
            "updated_at": [],
        }
    )


def _table_exists(cur, table_name: str) -> bool:
    try:
        return bool(list(cur.tables(table=table_name)))
    except Exception:
        return False


def _column_names(cur, table_name: str) -> set[str]:
    try:
        return {str(row.column_name).lower() for row in cur.columns(table=table_name)}
    except Exception:
        return set()


def ensure_beta_shift_scenario_schema() -> None:
    with get_connection() as conn:
        cur = conn.cursor()
        if not _table_exists(cur, BETA_SHIFT_SCENARIOS_TABLE):
            cur.execute(
                f"""
                CREATE TABLE {BETA_SHIFT_SCENARIOS_TABLE} (
                    scenario_id COUNTER PRIMARY KEY,
                    scenario_name TEXT(255),
                    lookback_code TEXT(16),
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        else:
            cols = _column_names(cur, BETA_SHIFT_SCENARIOS_TABLE)
            if "lookback_code" not in cols:
                try:
                    cur.execute(
                        f"ALTER TABLE {BETA_SHIFT_SCENARIOS_TABLE} ADD COLUMN lookback_code TEXT(16)"
                    )
                except Exception:
                    pass

        if not _table_exists(cur, BETA_SHIFT_SCENARIO_CONTENT_TABLE):
            cur.execute(
                f"""
                CREATE TABLE {BETA_SHIFT_SCENARIO_CONTENT_TABLE} (
                    id COUNTER PRIMARY KEY,
                    scenario_id LONG,
                    index_name TEXT(64),
                    shift_pct DOUBLE,
                    updated_at DATETIME
                )
                """
            )
        try:
            cur.execute(
                f"CREATE INDEX idx_{BETA_SHIFT_SCENARIOS_TABLE}_name ON {BETA_SHIFT_SCENARIOS_TABLE} (scenario_name)"
            )
        except Exception:
            pass
        try:
            cur.execute(
                f"CREATE INDEX idx_{BETA_SHIFT_SCENARIO_CONTENT_TABLE}_scenario ON {BETA_SHIFT_SCENARIO_CONTENT_TABLE} (scenario_id)"
            )
        except Exception:
            pass
        conn.commit()


def list_beta_shift_scenarios() -> pl.DataFrame:
    ensure_beta_shift_scenario_schema()
    with get_connection() as conn:
        pdf = pd.read_sql(
            f"""
            SELECT scenario_id, scenario_name, lookback_code, created_at, updated_at
            FROM {BETA_SHIFT_SCENARIOS_TABLE}
            ORDER BY updated_at DESC, created_at DESC, scenario_id DESC
            """,
            conn,
        )
    if pdf.empty:
        return _empty_scenarios_df()
    return pl.from_pandas(pdf)


def load_beta_shift_scenarios_cache_from_db() -> None:
    ensure_beta_shift_scenario_schema()
    scenarios_df = list_beta_shift_scenarios()
    content_cache: dict[int, dict[str, float]] = {}
    with get_connection() as conn:
        pdf = pd.read_sql(
            f"""
            SELECT scenario_id, index_name, shift_pct
            FROM {BETA_SHIFT_SCENARIO_CONTENT_TABLE}
            """,
            conn,
        )
    if not pdf.empty:
        for row in pdf.to_dict(orient="records"):
            try:
                sid = int(row.get("scenario_id"))
            except Exception:
                continue
            idx = str(row.get("index_name") or "").strip().upper()
            if not idx:
                continue
            try:
                pct = float(row.get("shift_pct") or 0.0)
            except Exception:
                pct = 0.0
            content_cache.setdefault(sid, {})[idx] = pct
    SNAPSHOT_STORE.repository_snapshot_beta_shift_scenarios = scenarios_df
    SNAPSHOT_STORE.repository_snapshot_beta_shift_scenario_content = content_cache


def get_cached_beta_shift_scenarios() -> pl.DataFrame:
    df = getattr(SNAPSHOT_STORE, "repository_snapshot_beta_shift_scenarios", None)
    return df if df is not None else _empty_scenarios_df()


def get_cached_beta_shift_scenario_content_map(scenario_id: int | None) -> dict[str, float]:
    if scenario_id is None:
        return {}
    cache = getattr(SNAPSHOT_STORE, "repository_snapshot_beta_shift_scenario_content", {}) or {}
    return dict(cache.get(int(scenario_id), {}) or {})


def create_beta_shift_scenario(name: str, *, lookback_code: str = "12m") -> int:
    ensure_beta_shift_scenario_schema()
    scenario_name = str(name or "").strip()
    if not scenario_name:
        raise ValueError("scenario_name is verplicht")
    now = dt.datetime.now()
    with get_connection() as conn:
        cur = conn.cursor()
        row = cur.execute(
            f"SELECT TOP 1 scenario_id FROM {BETA_SHIFT_SCENARIOS_TABLE} WHERE scenario_name=?",
            (scenario_name,),
        ).fetchone()
        if row is not None and row[0] is not None:
            scenario_id = int(row[0])
            cur.execute(
                f"UPDATE {BETA_SHIFT_SCENARIOS_TABLE} SET lookback_code=?, updated_at=? WHERE scenario_id=?",
                (str(lookback_code or "12m"), now, scenario_id),
            )
        else:
            cur.execute(
                f"""
                INSERT INTO {BETA_SHIFT_SCENARIOS_TABLE} (scenario_name, lookback_code, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (scenario_name, str(lookback_code or "12m"), now, now),
            )
            cur.execute("SELECT @@IDENTITY")
            scenario_id = int(cur.fetchone()[0])
        conn.commit()
    load_beta_shift_scenarios_cache_from_db()
    return scenario_id


def rename_beta_shift_scenario(scenario_id: int, new_name: str) -> None:
    ensure_beta_shift_scenario_schema()
    scenario_name = str(new_name or "").strip()
    if not scenario_name:
        raise ValueError("scenario_name is verplicht")
    now = dt.datetime.now()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""
            UPDATE {BETA_SHIFT_SCENARIOS_TABLE}
            SET scenario_name=?, updated_at=?
            WHERE scenario_id=?
            """,
            (scenario_name, now, int(scenario_id)),
        )
        conn.commit()
    load_beta_shift_scenarios_cache_from_db()


def delete_beta_shift_scenario(scenario_id: int) -> None:
    ensure_beta_shift_scenario_schema()
    sid = int(scenario_id)
    with get_connection() as conn:
        cur = conn.cursor()
        row = cur.execute(
            f"SELECT TOP 1 scenario_name FROM {BETA_SHIFT_SCENARIOS_TABLE} WHERE scenario_id=?",
            (sid,),
        ).fetchone()
        if row is not None and str(row[0] or "").strip() == DEFAULT_BETA_SHIFT_SCENARIO_NAME:
            raise ValueError("Default scenario kan niet verwijderd worden")
        cur.execute(
            f"DELETE FROM {BETA_SHIFT_SCENARIO_CONTENT_TABLE} WHERE scenario_id=?",
            (sid,),
        )
        cur.execute(
            f"DELETE FROM {BETA_SHIFT_SCENARIOS_TABLE} WHERE scenario_id=?",
            (sid,),
        )
        conn.commit()
    load_beta_shift_scenarios_cache_from_db()


def ensure_default_beta_shift_scenario() -> int:
    load_beta_shift_scenarios_cache_from_db()
    df = get_cached_beta_shift_scenarios()
    if not df.is_empty():
        existing = df.filter(pl.col("scenario_name") == DEFAULT_BETA_SHIFT_SCENARIO_NAME)
        if existing.height > 0:
            return int(existing["scenario_id"][0])
    return create_beta_shift_scenario(DEFAULT_BETA_SHIFT_SCENARIO_NAME, lookback_code="12m")


def save_beta_shift_scenario_content(
    scenario_id: int,
    *,
    lookback_code: str,
    shift_map: dict[str, float] | None,
) -> None:
    ensure_beta_shift_scenario_schema()
    now = dt.datetime.now()
    normalized: dict[str, float] = {}
    for key, value in dict(shift_map or {}).items():
        idx = str(key or "").strip().upper()
        if not idx:
            continue
        try:
            pct = float(value)
        except Exception:
            continue
        if abs(pct) >= 1e-12:
            normalized[idx] = pct

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE {BETA_SHIFT_SCENARIOS_TABLE} SET lookback_code=?, updated_at=? WHERE scenario_id=?",
            (str(lookback_code or "12m"), now, int(scenario_id)),
        )
        cur.execute(
            f"DELETE FROM {BETA_SHIFT_SCENARIO_CONTENT_TABLE} WHERE scenario_id=?",
            (int(scenario_id),),
        )
        for idx, pct in normalized.items():
            cur.execute(
                f"""
                INSERT INTO {BETA_SHIFT_SCENARIO_CONTENT_TABLE} (scenario_id, index_name, shift_pct, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (int(scenario_id), idx, float(pct), now),
            )
        conn.commit()
    load_beta_shift_scenarios_cache_from_db()
