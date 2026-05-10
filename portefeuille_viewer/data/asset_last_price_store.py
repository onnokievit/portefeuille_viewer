import threading
import time
from datetime import datetime
from typing import Optional

from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE


class AssetLastPriceStore:
    """
    Centrale coordinator voor asset_last_prices.

    De Access tabel wordt gebruikt als persistence/fallback cache:
    - lezen: een keer per actieve database, bij start of database-wissel
    - schrijven: alleen dirty live-prijzen, minimaal eens per 5 minuten en bij shutdown
    """

    def __init__(self, min_save_interval_sec: float = 300.0):
        self._lock = threading.RLock()
        self._prices: dict[tuple[str, str], float] = {}
        self._dirty_keys: set[tuple[str, str]] = set()
        self._loaded_db_key: Optional[str] = None
        self._last_save_monotonic = 0.0
        self._min_save_interval_sec = float(min_save_interval_sec)

    @staticmethod
    def _normalize_key(sym: str, cur: str) -> tuple[str, str]:
        return (str(sym or "").strip().upper(), str(cur or "").strip().upper())

    @staticmethod
    def _current_db_key() -> str:
        from portefeuille_viewer.data import repository

        return str(getattr(repository, "db_path", "") or "")

    @staticmethod
    def _read_from_db() -> dict[tuple[str, str], float]:
        from portefeuille_viewer.data import repository

        out: dict[tuple[str, str], float] = {}
        with repository.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT ib_symbol, ib_currency, price FROM asset_last_prices")
            for row in cursor.fetchall():
                symbol, currency, price = row
                key = AssetLastPriceStore._normalize_key(symbol, currency)
                if key[0] and key[1] and price is not None:
                    out[key] = float(price)
        return out

    @staticmethod
    def _write_to_db(rows: dict[tuple[str, str], float]) -> None:
        if not rows:
            return
        from portefeuille_viewer.data import repository

        now = datetime.now()
        with repository.get_connection() as conn:
            cursor = conn.cursor()
            for (sym, cur), price in rows.items():
                cursor.execute(
                    "UPDATE asset_last_prices SET price=?, last_update=? WHERE ib_symbol=? AND ib_currency=?",
                    (price, now, sym, cur),
                )
                if cursor.rowcount == 0:
                    cursor.execute(
                        "INSERT INTO asset_last_prices (ib_symbol, ib_currency, price, last_update) VALUES (?, ?, ?, ?)",
                        (sym, cur, price, now),
                    )
            conn.commit()

    def load_from_db(self, *, force: bool = False, publish_snapshot: bool = True) -> dict[tuple[str, str], float]:
        db_key = self._current_db_key()
        with self._lock:
            if not force and self._loaded_db_key == db_key:
                return dict(self._prices)
            prices = self._read_from_db()
            self._prices = dict(prices)
            self._dirty_keys.clear()
            self._loaded_db_key = db_key
            self._last_save_monotonic = time.monotonic()
            snapshot = dict(self._prices)
        if publish_snapshot:
            SNAPSHOT_STORE.set_live_prices(snapshot)
        return snapshot

    def ensure_loaded(self) -> dict[tuple[str, str], float]:
        return self.load_from_db(force=False, publish_snapshot=True)

    def get_snapshot(self) -> dict[tuple[str, str], float]:
        with self._lock:
            return dict(self._prices)

    def update_price(self, sym: str, cur: str, price: float | None) -> None:
        if price in (None, 0.0):
            return
        try:
            px = float(price)
        except Exception:
            return
        if px <= 0:
            return
        key = self._normalize_key(sym, cur)
        if not key[0] or not key[1]:
            return
        with self._lock:
            current = self._prices.get(key)
            self._prices[key] = px
            if current != px:
                self._dirty_keys.add(key)
        SNAPSHOT_STORE.update_live_prices({key: px})

    def update_many(self, prices: dict) -> None:
        for key, price in dict(prices or {}).items():
            if isinstance(key, tuple) and len(key) == 2:
                self.update_price(key[0], key[1], price)

    def save_to_db(self, *, force: bool = False) -> int:
        with self._lock:
            if not self._dirty_keys:
                return 0
            now_mono = time.monotonic()
            if not force and (now_mono - self._last_save_monotonic) < self._min_save_interval_sec:
                return 0
            rows = {
                key: self._prices[key]
                for key in self._dirty_keys
                if key in self._prices and self._prices[key] not in (None, 0.0)
            }
            self._write_to_db(rows)
            for key in rows:
                self._dirty_keys.discard(key)
            self._last_save_monotonic = time.monotonic()
        return len(rows)

    def flush(self) -> int:
        return self.save_to_db(force=True)

    def reset_for_database_change(self) -> dict[tuple[str, str], float]:
        return self.load_from_db(force=True, publish_snapshot=True)


ASSET_LAST_PRICE_STORE = AssetLastPriceStore()
