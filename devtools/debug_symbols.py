import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.data import repository
import time

# Load datasets functie uit het hoofdbestand
def load_datasets():
    start_time = time.time()
    
    repository.load_alle_transacties()
    repository.load_aandelen_from_tx()
    repository.load_open_opties_from_tx()
    repository.load_gesloten_opties_from_tx()
    repository.load_gesloten_opties_no_broker()
    repository.load_asset_rollup_data()
    
    end_time = time.time()
    print(f"Datasets geladen in {end_time - start_time:.2f} seconden.")

load_datasets()
from portefeuille_viewer.domain.portfolio_engine import PortfolioEngine
from portefeuille_viewer.services.price_feed import PriceFeedService
from portefeuille_viewer.config import IB_HOST, IB_PORT, IB_CLIENT_ID

feed = PriceFeedService(IB_HOST, IB_PORT, IB_CLIENT_ID)
engine = PortfolioEngine(feed)
df = engine.get_full_df()

print("=== DEBUG INFO ===")
print(f"DataFrame shape: {df.shape}")
print(f"Kolommen: {df.columns}")

if "ib_symbol" in df.columns:
    symbols = df["ib_symbol"].unique().to_list()
    print(f"Symbolen in engine ({len(symbols)}): {symbols}")
    
    # Check specifically for CL
    if "CL" in symbols:
        print("✅ CL symbol gevonden in engine")
    else:
        print("❌ CL symbol NIET gevonden in engine")
else:
    print("❌ Geen ib_symbol kolom gevonden")

print("==================")