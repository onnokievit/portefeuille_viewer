import polars as pl


class SnapshotStore:
    """
    Houdt de actuele datasets in geheugen.
    Wordt gevuld door repository-functies of engines,
    maar bevat zelf geen laadlogica meer.
    """

    def __init__(self):
        # Polars DataFrames (standaard leeg)
        self.snapshot_alle_transacties: pl.DataFrame | None = None
        self.snapshot_aandelen: pl.DataFrame | None = None
        self.snapshot_load_open_opties_from_tx: pl.DataFrame | None = None
        self.open_sprinters: pl.DataFrame | None = None
        self.snapshot_gesloten_opties: pl.DataFrame | None = None
        self.gesloten_sprinters: pl.DataFrame | None = None
        self.snapshot_asset_rollup_data: pl.DataFrame | None = None

    def clear(self):
        """Reset alle snapshots naar leeg."""
        self.snapshot_alle_transacties = None
        self.snapshot_aandelen = None
        self.snapshot_load_open_opties_from_tx = None
        self.open_sprinters = None
        self.snapshot_gesloten_opties = None
        self.gesloten_sprinters = None
        self.snapshot_asset_rollup_data = None

    def is_loaded(self) -> bool:
        """Controleer of er al data is geladen."""
        return any([
            self.snapshot_alle_transacties is not None,
            self.snapshot_aandelen is not None,
            self.snapshot_load_open_opties_from_tx is not None,
            self.open_sprinters is not None,
            self.snapshot_gesloten_opties is not None,
            self.gesloten_sprinters is not None,
            self.snapshot_asset_rollup_data is not None
        ])

    def snapshot_store_summary(self) -> str:
        """Korte tekstuele samenvatting voor debug/log."""
        parts = []
        if self.snapshot_alle_transacties is not None:
            parts.append(f"Alle Transacties: {len(self.snapshot_alle_transacties)} rijen")
        if self.snapshot_aandelen is not None:
            parts.append(f"Open Aandelen: {len(self.snapshot_aandelen)} rijen")
        if self.snapshot_load_open_opties_from_tx is not None:
            parts.append(f"Open Opties: {len(self.snapshot_load_open_opties_from_tx)} rijen")
        if self.open_sprinters is not None:
            parts.append(f"Open Sprinters: {len(self.open_sprinters)} rijen")
        if self.snapshot_gesloten_opties is not None:
            parts.append(f"Gesloten Opties: {len(self.snapshot_gesloten_opties)} rijen")
        if self.gesloten_sprinters is not None:
            parts.append(f"Gesloten Sprinters: {len(self.gesloten_sprinters)} rijen")
        if self.snapshot_asset_rollup_data is not None:
            parts.append(f"Asset Rollup data: {len(self.snapshot_asset_rollup_data)} rijen")

        return " | ".join(parts) if parts else "(geen data geladen)"



# Globale instantie — kan hergebruikt worden in UI of engines
SNAPSHOT_STORE = SnapshotStore()