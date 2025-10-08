
import pandas as pd
from portefeuille_viewer.data import repository

class SnapshotStore:
    def __init__(self):
        self.open_sprinters = pd.DataFrame()
        self.open_opties = pd.DataFrame()
        self.open_aandelen = pd.DataFrame()

    def load_all(self):
        try:
            self.open_sprinters = repository.load_sprinter_flows()
        except Exception as e:
            print(f"[Snapshot] Sprinters laden mislukt: {e}")
            self.open_sprinters = pd.DataFrame()

        try:
            self.open_opties = repository.load_closed_options_summary()
        except Exception as e:
            print(f"[Snapshot] Opties laden mislukt: {e}")
            self.open_opties = pd.DataFrame()

        try:
            self.open_aandelen = repository.load_equity_flows()
        except Exception as e:
            print(f"[Snapshot] Aandelen laden mislukt: {e}")
            self.open_aandelen = pd.DataFrame()


# Globale instantie van SnapshotStore
SNAPSHOT_STORE = SnapshotStore()
