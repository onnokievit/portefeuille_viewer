import polars as pl


class SnapshotStore:
    """
    Houdt de actuele datasets in geheugen.
    Wordt gevuld door repository-functies of engines,
    maar bevat zelf geen laadlogica meer.
    """

    def __init__(self):
        # Polars DataFrames (standaard leeg)
        self.snapshot_alle_transacties = None
        self.snapshot_aandelen = None
        self.snapshot_aandelen_live = None  # NIEUW: live geaggregeerde aandelen data
        self.snapshot_load_open_opties = None
        self.snapshot_load_open_opties_live = None  # NIEUW: live opties data met koersen
        self.snapshot_load_open_sprinters = None
        self.snapshot_load_open_sprinters_live = None
        self.snapshot_gesloten_opties = None
        self.snapshot_gesloten_opties_no_broker = None
        self.snapshot_gesloten_sprinters = None
        self.snapshot_asset_rollup_data = None
        # PortfolioEngine aggregated results
        self.snapshot_aggregated_portfolio = None

    def clear(self):
        """Reset alle snapshots naar leeg."""
        self.snapshot_alle_transacties = None
        self.snapshot_aandelen = None
        self.snapshot_aandelen_live = None
        self.snapshot_load_open_opties = None
        self.snapshot_load_open_opties_live = None
        self.snapshot_load_open_sprinters = None
        self.snapshot_load_open_sprinters_live = None
        self.snapshot_gesloten_opties = None
        self.snapshot_gesloten_opties_no_broker = None
        self.snapshot_gesloten_sprinters = None
        self.snapshot_aggregated_portfolio = None
        self.snapshot_asset_rollup_data = None

    def is_loaded(self) -> bool:
        """Controleer of er al data is geladen."""
        return any([
            self.snapshot_alle_transacties is not None,
            self.snapshot_aandelen is not None,
            self.snapshot_aandelen_live is not None,
            self.snapshot_load_open_opties is not None,
            self.snapshot_load_open_opties_live is not None,
            self.snapshot_load_open_sprinters is not None,
            self.snapshot_load_open_sprinters_live is not None,
            self.snapshot_gesloten_opties is not None,
            self.snapshot_gesloten_opties_no_broker is not None,
            self.snapshot_gesloten_sprinters is not None,
            self.snapshot_asset_rollup_data is not None
        ])

    def snapshot_store_summary(self) -> str:
        """Korte tekstuele samenvatting voor debug/log."""
        parts = []
        if self.snapshot_alle_transacties is not None:
            parts.append(f"Alle Transacties: {len(self.snapshot_alle_transacties)} rijen")
        if self.snapshot_aandelen is not None:
            parts.append(f"Open Aandelen: {len(self.snapshot_aandelen)} rijen")
        if self.snapshot_aandelen_live is not None:
            parts.append(f"Live Aandelen: {len(self.snapshot_aandelen_live)} rijen")
        if self.snapshot_load_open_opties is not None:
            parts.append(f"Open Opties: {len(self.snapshot_load_open_opties)} rijen")
        if self.snapshot_load_open_opties_live is not None:
            parts.append(f"Live Opties: {len(self.snapshot_load_open_opties_live)} rijen")
        if self.snapshot_load_open_sprinters is not None:
            parts.append(f"Open Sprinters (load): {len(self.snapshot_load_open_sprinters)} rijen")
        if self.snapshot_load_open_sprinters_live is not None:
            parts.append(f"Open Sprinters (live): {len(self.snapshot_load_open_sprinters_live)} rijen")
        if self.snapshot_gesloten_opties is not None:
            parts.append(f"Gesloten Opties: {len(self.snapshot_gesloten_opties)} rijen")
        if self.snapshot_gesloten_opties_no_broker is not None:
            parts.append(f"Gesloten Opties (zonder broker): {len(self.snapshot_gesloten_opties_no_broker)} rijen")
        if self.snapshot_gesloten_sprinters is not None:
            parts.append(f"Gesloten Sprinters: {len(self.snapshot_gesloten_sprinters)} rijen")
        if self.snapshot_asset_rollup_data is not None:
            parts.append(f"Asset Rollup data: {len(self.snapshot_asset_rollup_data)} rijen")
        if self.snapshot_aggregated_portfolio is not None:
            parts.append(f"Aggregated Portfolio: {len(self.snapshot_aggregated_portfolio)} assets")

        return " \n ".join(parts) if parts else "(geen data geladen)"



# Globale instantie — kan hergebruikt worden in UI of engines
SNAPSHOT_STORE = SnapshotStore()