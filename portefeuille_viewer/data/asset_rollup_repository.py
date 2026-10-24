from __future__ import annotations

from dataclasses import dataclass
from time import sleep
from typing import Any

from portefeuille_viewer.data import repository as data_repository


_original_rows = {}

ASSET_ROLLUP_TABLE = "asset_rollup_data"


@dataclass(frozen=True)
class AssetRollupColumn:
    name: str
    type_name: str
    nullable: bool
    is_primary_key: bool = False

    @property
    def is_counter(self) -> bool:
        return self.type_name.upper() == "COUNTER"

    @property
    def is_numeric(self) -> bool:
        return self.type_name.upper() in {
            "BYTE",
            "COUNTER",
            "CURRENCY",
            "DECIMAL",
            "DOUBLE",
            "INTEGER",
            "LONG",
            "REAL",
            "SHORT",
            "SINGLE",
        }


def _get_connection_with_retry(retries: int = 4, delay_s: float = 0.25):
    last_exc = None
    for attempt in range(max(1, retries)):
        try:
            return data_repository.get_stockdata_connection()
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                sleep(delay_s)
    raise last_exc


def _bracket(name: str) -> str:
    return f"[{str(name).replace(']', ']]')}]"


def list_asset_rollup_columns() -> list[AssetRollupColumn]:
    with _get_connection_with_retry() as conn:
        cur = conn.cursor()
        pk_columns: set[str] = set()
        try:
            for row in cur.statistics(table=ASSET_ROLLUP_TABLE, unique=True):
                index_name = str(getattr(row, "index_name", "") or "")
                column_name = str(getattr(row, "column_name", "") or "")
                if index_name.lower() == "primarykey" and column_name:
                    pk_columns.add(column_name.lower())
        except Exception:
            pass

        columns = []
        col_cur = conn.cursor()
        for row in col_cur.columns(table=ASSET_ROLLUP_TABLE):
            name = str(row.column_name)
            columns.append(
                AssetRollupColumn(
                    name=name,
                    type_name=str(row.type_name or ""),
                    nullable=bool(row.nullable),
                    is_primary_key=name.lower() in pk_columns,
                )
            )
        if not columns:
            cur.execute(f"SELECT TOP 1 * FROM {ASSET_ROLLUP_TABLE}")
            numeric_names = {
                "id",
                "previous_price",
                "current_price",
                "daily_change",
                "contractid",
                "incl_excl",
            }
            for desc in cur.description or []:
                name = str(desc[0])
                lower_name = name.lower()
                if lower_name == "id":
                    type_name = "COUNTER"
                elif lower_name in numeric_names:
                    type_name = "DOUBLE"
                else:
                    type_name = "VARCHAR"
                columns.append(
                    AssetRollupColumn(
                        name=name,
                        type_name=type_name,
                        nullable=lower_name != "id",
                        is_primary_key=lower_name == "id",
                    )
                )
    if not columns:
        raise RuntimeError(f"Tabel {ASSET_ROLLUP_TABLE} niet gevonden of heeft geen kolommen")
    return columns


def list_asset_rollup_rows() -> list[dict[str, Any]]:
    columns = list_asset_rollup_columns()
    select_cols = ", ".join(_bracket(col.name) for col in columns)
    order_col = "asset_rollup" if any(col.name.lower() == "asset_rollup" for col in columns) else columns[0].name
    sql = f"SELECT {select_cols} FROM {ASSET_ROLLUP_TABLE} ORDER BY {_bracket(order_col)}"
    with _get_connection_with_retry() as conn:
        rows = conn.cursor().execute(sql).fetchall()
    result = [
        {col.name: row[idx] for idx, col in enumerate(columns)}
        for row in rows
    ]
    pk = next((c for c in columns if c.is_primary_key), columns[0])
    _original_rows.clear()
    _original_rows.update({int(row[pk.name]): dict(row) for row in result})
    return result


def _check_original(conn, pk, row_id):
    conn.begin_write()
    expected = _original_rows.get(int(row_id))
    if expected is None:
        raise RuntimeError("Herlaad de tabel voordat u een bestaande rij wijzigt")
    cur = conn.cursor().execute(f"SELECT * FROM {ASSET_ROLLUP_TABLE} WHERE {_bracket(pk.name)}=?", int(row_id))
    row = cur.fetchone()
    actual = {d[0]: row[i] for i, d in enumerate(cur.description)} if row is not None else None
    if actual != expected:
        raise RuntimeError("Deze rij is inmiddels gewijzigd of verwijderd door een andere instantie. Herlaad de tabel en beoordeel uw wijziging opnieuw.")


def _coerce_value(value: Any, column: AssetRollupColumn) -> Any:
    if column.is_counter:
        return None
    if isinstance(value, str):
        value = value.strip()
    if value in ("", None):
        return None
    type_name = column.type_name.upper()
    if type_name in {"BYTE", "INTEGER", "LONG", "SHORT"}:
        return int(float(value))
    if type_name in {"CURRENCY", "DECIMAL", "DOUBLE", "REAL", "SINGLE"}:
        return float(str(value).replace(",", "."))
    return value


def upsert_asset_rollup_row(payload: dict[str, Any]) -> int:
    columns = list_asset_rollup_columns()
    pk = next((col for col in columns if col.is_primary_key), columns[0])
    row_id = payload.get(pk.name)
    writable = [col for col in columns if not col.is_counter and not col.is_primary_key]

    asset_rollup = str(payload.get("asset_rollup") or "").strip()
    if not asset_rollup:
        raise ValueError("asset_rollup is verplicht")

    values = {col.name: _coerce_value(payload.get(col.name), col) for col in writable}
    with _get_connection_with_retry() as conn:
        cur = conn.cursor()
        if row_id in ("", None):
            insert_cols = ", ".join(_bracket(col.name) for col in writable)
            placeholders = ", ".join("?" for _ in writable)
            cur.execute(
                f"INSERT INTO {ASSET_ROLLUP_TABLE} ({insert_cols}) VALUES ({placeholders})",
                tuple(values[col.name] for col in writable),
            )
            cur.execute("SELECT @@IDENTITY")
            new_id = int(cur.fetchone()[0])
            conn.commit()
            _refresh_asset_rollup_snapshots()
            return new_id

        _check_original(conn, pk, row_id)
        assignments = ", ".join(f"{_bracket(col.name)}=?" for col in writable)
        cur.execute(
            f"UPDATE {ASSET_ROLLUP_TABLE} SET {assignments} WHERE {_bracket(pk.name)}=?",
            tuple(values[col.name] for col in writable) + (int(row_id),),
        )
        conn.commit()
        _refresh_asset_rollup_snapshots()
        return int(row_id)


def delete_asset_rollup_row(row_id: int) -> None:
    columns = list_asset_rollup_columns()
    pk = next((col for col in columns if col.is_primary_key), columns[0])
    with _get_connection_with_retry() as conn:
        _check_original(conn, pk, row_id)
        conn.cursor().execute(
            f"DELETE FROM {ASSET_ROLLUP_TABLE} WHERE {_bracket(pk.name)}=?",
            int(row_id),
        )
        conn.commit()
    _refresh_asset_rollup_snapshots()


def _refresh_asset_rollup_snapshots() -> None:
    data_repository.load_asset_rollup_data()
    data_repository.build_repository_active_asset_rollup_data()
