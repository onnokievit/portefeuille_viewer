from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pyodbc

from portefeuille_viewer.config import get_databases


@dataclass(slots=True)
class MigrationResult:
    database_name: str
    database_path: str
    old_version: int
    new_version: int
    success: bool
    error: str | None = None


class DbMigrationService:
    """
    Minimal multi-user DB migration bootstrap.

    Rules:
    - Additive only.
    - Never drop/rename legacy tables.
    - Migrations are idempotent.
    """

    TARGET_VERSION = 1

    def discover_user_databases(self) -> list[tuple[str, str]]:
        dbs = get_databases() or {}
        out: list[tuple[str, str]] = []
        for name, cfg in dbs.items():
            path = str((cfg or {}).get("path") or "").strip()
            if path:
                out.append((str(name), path))
        return out

    def migrate_all_user_dbs(self) -> list[MigrationResult]:
        results: list[MigrationResult] = []
        for name, path in self.discover_user_databases():
            results.append(self.migrate_db(name, path))
        return results

    def migrate_db(self, name: str, path: str) -> MigrationResult:
        try:
            with self._connect(path) as conn:
                cur = conn.cursor()
                self._ensure_meta_tables(cur)
                old_version = self._read_version(cur)
                if old_version < self.TARGET_VERSION:
                    self._apply_migrations(cur, old_version, self.TARGET_VERSION)
                    self._write_version(cur, self.TARGET_VERSION)
                conn.commit()
                new_version = self._read_version(cur)
            return MigrationResult(name, path, old_version, new_version, True, None)
        except Exception as exc:
            return MigrationResult(name, path, 0, 0, False, str(exc))

    def get_db_version(self, db_path: str) -> int:
        with self._connect(db_path) as conn:
            cur = conn.cursor()
            self._ensure_meta_tables(cur)
            return self._read_version(cur)

    def _connect(self, db_path: str):
        conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path};"
        return pyodbc.connect(conn_str)

    def _ensure_meta_tables(self, cur) -> None:
        # Access has no CREATE TABLE IF NOT EXISTS; create and ignore "already exists" errors.
        try:
            cur.execute(
                """
                CREATE TABLE engine_meta_version (
                    id LONG,
                    schema_version LONG,
                    updated_at DATETIME
                )
                """
            )
        except Exception:
            pass
        try:
            cur.execute(
                """
                CREATE TABLE engine_migration_log (
                    id COUNTER PRIMARY KEY,
                    migration_name TEXT(120),
                    started_at DATETIME,
                    ended_at DATETIME,
                    status TEXT(32),
                    message TEXT(255)
                )
                """
            )
        except Exception:
            pass

    def _read_version(self, cur) -> int:
        try:
            row = cur.execute("SELECT TOP 1 schema_version FROM engine_meta_version ORDER BY id").fetchone()
            if row and row[0] is not None:
                return int(row[0])
        except Exception:
            return 0
        return 0

    def _write_version(self, cur, version: int) -> None:
        now = datetime.now()
        cur.execute("DELETE FROM engine_meta_version")
        cur.execute(
            "INSERT INTO engine_meta_version (id, schema_version, updated_at) VALUES (1, ?, ?)",
            (int(version), now),
        )

    def _apply_migrations(self, cur, old_version: int, target_version: int) -> None:
        started = datetime.now()
        try:
            # Placeholder for v1 additive migrations.
            # Keep empty now to avoid accidental legacy impact.
            _ = (old_version, target_version)
            cur.execute(
                "INSERT INTO engine_migration_log (migration_name, started_at, ended_at, status, message) VALUES (?, ?, ?, ?, ?)",
                ("bootstrap_v1", started, datetime.now(), "ok", "No-op bootstrap applied"),
            )
        except Exception as exc:
            cur.execute(
                "INSERT INTO engine_migration_log (migration_name, started_at, ended_at, status, message) VALUES (?, ?, ?, ?, ?)",
                ("bootstrap_v1", started, datetime.now(), "failed", str(exc)[:255]),
            )
            raise

