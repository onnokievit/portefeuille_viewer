import polars as pl

class SnapshotStore:
    """
    Houdt de actuele datasets in geheugen.
    Wordt gevuld door repository-functies of engines,
    maar bevat zelf geen laadlogica meer.
    """

    def __init__(self):
        # Polars DataFrames (standaard leeg)
        self.open_aandelen: pl.DataFrame | None = None
        self.open_opties: pl.DataFrame | None = None
        self.open_sprinters: pl.DataFrame | None = None
        self.gesloten_aandelen: pl.DataFrame | None = None
        self.gesloten_opties: pl.DataFrame | None = None
        self.gesloten_sprinters: pl.DataFrame | None = None


    def clear(self):
        """Reset alle snapshots naar leeg."""
        self.open_aandelen = None
        self.open_opties = None
        self.open_sprinters = None
        self.gesloten_aandelen = None
        self.gesloten_opties = None
        self.gesloten_sprinters = None


    def is_loaded(self) -> bool:
        """Controleer of er al data is geladen."""
        return any([
            self.open_aandelen is not None,
            self.open_opties is not None,
            self.open_sprinters is not None,
            self.gesloten_aandelen is not None,
            self.gesloten_opties is not None,
            self.gesloten_sprinters is not None,

        ])

    def summary(self) -> str:
        """Korte tekstuele samenvatting voor debug/log."""
        parts = []
        if self.open_aandelen is not None:
            parts.append(f"Open Aandelen: {len(self.open_aandelen)} rijen")
        if self.open_opties is not None:
            parts.append(f"Open Opties: {len(self.open_opties)} rijen")
        if self.open_sprinters is not None:
            parts.append(f"Open Sprinters: {len(self.open_sprinters)} rijen")
        if self.gesloten_aandelen is not None:
            parts.append(f"Gesloten Aandelen: {len(self.open_sprinters)} rijen")
        if self.gesloten_opties is not None:
            parts.append(f"Gesloten Opties: {len(self.open_sprinters)} rijen")
        if self.gesloten_sprinters is not None:
            parts.append(f"Gesloten Sprinters: {len(self.open_sprinters)} rijen")

        return " | ".join(parts) if parts else "(geen data geladen)"


# Globale instantie — kan hergebruikt worden in UI of engines
SNAPSHOT_STORE = SnapshotStore()
