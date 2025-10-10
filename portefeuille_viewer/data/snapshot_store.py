import polars as pl
from portefeuille_viewer.data.repository import load_asset_rollup_data

class SnapshotStore:
    """
    Houdt de actuele datasets in geheugen.
    Wordt gevuld door repository-functies of engines,
    maar bevat zelf geen laadlogica meer.
    """

    def __init__(self):
        # Polars DataFrames (standaard leeg)
        self.alle_transacties: pl.DataFrame | None = None
        self.aandelen: pl.DataFrame | None = None
        self.load_open_opties_from_tx: pl.DataFrame | None = None
        self.open_sprinters: pl.DataFrame | None = None
        self.gesloten_opties: pl.DataFrame | None = None
        self.gesloten_sprinters: pl.DataFrame | None = None
        self.asset_rollup_data: pl.DataFrame | None = None

    def clear(self):
        """Reset alle snapshots naar leeg."""
        self.alle_transacties = None
        self.aandelen = None
        self.load_open_opties_from_tx = None
        self.open_sprinters = None
        self.gesloten_opties = None
        self.gesloten_sprinters = None
        self.asset_rollup_data = None

    def is_loaded(self) -> bool:
        """Controleer of er al data is geladen."""
        return any([
            self.alle_transacties is not None,
            self.aandelen is not None,
            self.load_open_opties_from_tx is not None,
            self.open_sprinters is not None,
            self.gesloten_opties is not None,
            self.gesloten_sprinters is not None,
            self.asset_rollup_data is not None
        ])

    def summary(self) -> str:
        """Korte tekstuele samenvatting voor debug/log."""
        parts = []
        if self.alle_transacties is not None:
            parts.append(f"Alle Transacties: {len(self.alle_transacties)} rijen")
        if self.aandelen is not None:
            parts.append(f"Open Aandelen: {len(self.aandelen)} rijen")
        if self.load_open_opties_from_tx is not None:
            parts.append(f"Open Opties: {len(self.load_open_opties_from_tx)} rijen")
        if self.open_sprinters is not None:
            parts.append(f"Open Sprinters: {len(self.open_sprinters)} rijen")
        if self.gesloten_opties is not None:
            parts.append(f"Gesloten Opties: {len(self.gesloten_opties)} rijen")
        if self.gesloten_sprinters is not None:
            parts.append(f"Gesloten Sprinters: {len(self.gesloten_sprinters)} rijen")
        if self.asset_rollup_data is not None:
            parts.append(f"Asset Rollup data: {len(self.asset_rollup_data)} rijen")

        return " | ".join(parts) if parts else "(geen data geladen)"

    def load_asset_rollup(self):
        """Vul de asset_rollup snapshot."""
        self.asset_rollup_data = load_asset_rollup_data()

# Globale instantie — kan hergebruikt worden in UI of engines
SNAPSHOT_STORE = SnapshotStore()