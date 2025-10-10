from PySide6.QtCore import Slot
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTableView, QLabel, QHeaderView, QPushButton
from portefeuille_viewer.data import repository
from portefeuille_viewer.ui.models import PolarsTableModel
import polars as pl


class AandelenPolarsTab(QWidget):
    """
    Toont alle open aandelen (Polars) met live koersen uit PriceFeedService.
    """
    def __init__(self, pricefeed, parent=None):
        super().__init__(parent)
        self.feed_service = pricefeed

        layout = QVBoxLayout(self)
        self.label = QLabel("Nog geen data geladen.")
        layout.addWidget(self.label)

        self.table = QTableView()
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)

        btn_reload = QPushButton("🔄 Vernieuw gegevens")
        btn_reload.clicked.connect(self._reload_data)
        layout.addWidget(btn_reload)

        # Live updates koppelen
        self.feed_service.priceUpdated.connect(self._on_price_update)

        # Initieel laden
        self._reload_data()

    # ------------------------------------------------------------------
    @Slot()
    def _reload_data(self):
        """Laad aandelen-data en voeg live koersen toe."""
        try:
            df = repository.load_aandelen_from_tx()
            if df.is_empty():
                df = pl.DataFrame()

            # Laad asset_rollup_data en voeg ib_symbol, ib_currency, prim_exchange toe
            asset_map = repository.load_asset_rollup_data()
            if not asset_map.is_empty():
                df = df.join(
                    asset_map.select(["asset_rollup", "ib_symbol", "ib_currency", "prim_exchange"]),
                    on="asset_rollup",
                    how="left"
                )

            # Subscripties instellen voor de feed_service
            if not asset_map.is_empty():
                subs = (
                    asset_map.select(["ib_symbol", "ib_currency", "prim_exchange"])
                            .unique()
                            .to_numpy()
                            .tolist()
                )
                self.feed_service.ensure_subscriptions(subs)

            # Voeg koers toe per asset_rollup en ib_currency
            def get_koers(asset_rollup: str, ib_currency: str) -> float:
                prijs = self.feed_service.get(asset_rollup, cur=ib_currency)
                return prijs if prijs is not None else 0.0

            df = df.with_columns([
                pl.struct(["asset_rollup", "ib_currency"]).map_elements(
                    lambda row: get_koers(row["asset_rollup"], row["ib_currency"]),
                    return_dtype=pl.Float32
                ).alias("Koers")
            ])

            self.model = PolarsTableModel(df, self)
            self.table.setModel(self.model)
            self.label.setText(f"{len(df)} regels geladen, inclusief koersen.")
        except Exception as e:
            self.label.setText(f"Fout bij laden: {e}")

        # ------------------------------------------------------------------
    @Slot(str, str, float)

    def _on_price_update(self, sym: str, cur: str, px: float):
        """Realtime update van koerskolom in de tabel."""
        if not hasattr(self, "model") or self.model._df.is_empty():
            return
        if "ib_symbol" not in self.model._df.columns or "ib_currency" not in self.model._df.columns or "Koers" not in self.model._df.columns:
            return

        df = self.model._df

        # Controleer of sym en cur overeenkomen met een rij in de tabel
        if not ((df["ib_symbol"] == sym) & (df["ib_currency"] == cur)).any():
            return  # geen match in deze tabel

        # Update de kolom "Koers" voor de juiste rijen
        df = df.with_columns(
            pl.when((pl.col("ib_symbol") == sym) & (pl.col("ib_currency") == cur))
            .then(pl.lit(px))
            .otherwise(pl.col("Koers"))
            .alias("Koers")
        )

        self.model.set_df(df)
        # Optioneel: Toon een melding in de UI
        self.label.setText(f"Koersupdate ontvangen voor {sym} ({cur}): {px:.2f}")

    # def _on_price_update(self, sym: str, cur: str, px: float):
    #     if not hasattr(self, "model") or self.model._df.is_empty():
    #         return
    #     if "ib_symbol" not in self.model._df.columns or "Koers" not in self.model._df.columns:
    #         return

    #     df = self.model._df
    #     if sym not in df["ib_symbol"].to_list():
    #         return  # geen match in deze tabel

    #     df = df.with_columns(
    #         pl.when(pl.col("ib_symbol") == sym)
    #         .then(pl.lit(px))
    #         .otherwise(pl.col("Koers"))
    #         .alias("Koers")
    #     )
    #     self.model.set_df(df)
    #     # evt. self.label.setText(f"Koersupdate ontvangen voor {sym}: {px:.2f}")
