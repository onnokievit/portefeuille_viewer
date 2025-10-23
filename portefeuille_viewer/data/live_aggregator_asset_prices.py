import threading
import time
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE

def update_live_prices(new_prices: dict):
    """
    Update de centrale live_prices store.
    new_prices: dict met als key asset_id (bijv. ib_symbol, optie_id, etc.), value = prijs of dict met meer info.
    """
    if SNAPSHOT_STORE.live_prices is None:
        SNAPSHOT_STORE.live_prices = {}
    SNAPSHOT_STORE.live_prices.update(new_prices)
    # Eventueel kun je hier extra logica toevoegen, zoals timestamp, logging, etc.

def clear_live_prices():
    """
    Reset de centrale live_prices store.
    """
    SNAPSHOT_STORE.live_prices = {}

def start_live_price_updater(price_feed, interval_sec=2):
    """
    Start een background thread die periodiek de live prijzen uit de price_feed service haalt
    en deze in SNAPSHOT_STORE.live_prices bijwerkt.
    - price_feed: een instantie van PriceFeedService
    - interval_sec: update-interval in seconden
    """
    def updater():
        while True:
            # Haal alle actuele prijzen op uit de price_feed service
            # Dit voorbeeld verwacht dat price_feed.get_all_prices() een dict teruggeeft
            try:
                prices = price_feed.get_all_prices()  # {asset_id: prijs, ...}
                if prices:
                    update_live_prices(prices)
            except Exception as e:
                print(f"[LivePriceUpdater] Fout bij ophalen prijzen: {e}")
            time.sleep(interval_sec)

    thread = threading.Thread(target=updater, daemon=True)
    thread.start()
