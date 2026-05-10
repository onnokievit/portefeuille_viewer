
import threading
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.data.asset_last_price_store import ASSET_LAST_PRICE_STORE

def initialize_live_prices():
    """
    Vul SNAPSHOT_STORE.live_prices altijd eerst met de laatste bekende prijzen uit de database.
    Daarna kan deze dict live worden bijgewerkt met prijzen uit de price_feed.
    """
    ASSET_LAST_PRICE_STORE.ensure_loaded()

def update_live_prices(new_prices: dict):
    """
    Update de centrale live_prices store.
    new_prices: dict met als key asset_id (bijv. ib_symbol, optie_id, etc.), value = prijs of dict met meer info.
    """
    SNAPSHOT_STORE.update_live_prices(new_prices)

def clear_live_prices():
    """
    Reset de centrale live_prices store.
    """
    SNAPSHOT_STORE.clear_live_prices()

def start_live_price_updater(price_feed, interval_sec=2):
    stop_event = threading.Event()
    def updater():
        while not stop_event.is_set():
            try:
                prices = price_feed.get_all_prices()
                if prices:
                    update_live_prices(prices)
            except Exception as e:
                print(f"[LivePriceUpdater] Fout bij ophalen prijzen: {e}")
            stop_event.wait(interval_sec)
    thread = threading.Thread(target=updater, daemon=True)
    thread.start()
    return stop_event, thread

