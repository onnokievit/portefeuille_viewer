from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from portefeuille_viewer.services.beta_snapshot_service import rebuild_asset_driver_beta_snapshot
from portefeuille_viewer.config import get_stockdata_db_path


def main() -> int:
    payload = rebuild_asset_driver_beta_snapshot(get_stockdata_db_path())
    print(json.dumps(payload, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
