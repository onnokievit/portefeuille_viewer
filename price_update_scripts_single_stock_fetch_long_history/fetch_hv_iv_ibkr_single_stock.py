from __future__ import annotations

import sys
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from price_update_scripts.fetch_asset_volatility_history_to_db import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
