"""Voer de bestaande migratie handmatig uit voor één expliciet gekozen database.

Gebruik vanuit de repository: python devtools/migrate_user_database.py --db "pad.accdb"
Dit is onderhoudscode, geen onderdeel van de normale appstart.
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portefeuille_viewer.services.db_migration_service import DbMigrationService


def main() -> int:
    parser = argparse.ArgumentParser(description="Bestaande migratie uitvoeren op één userdatabase.")
    parser.add_argument("--db", required=True, type=Path, help="Pad naar de te migreren Access-database")
    args = parser.parse_args()
    path = args.db.resolve()
    if not path.is_file():
        parser.error(f"Database bestaat niet: {path}")
    result = DbMigrationService().migrate_db(path.stem, str(path))
    if not result.success:
        print(f"[db-migrate] {path}: FAILED ({result.error})", file=sys.stderr)
        return 1
    print(f"[db-migrate] {path}: v{result.old_version} -> v{result.new_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
