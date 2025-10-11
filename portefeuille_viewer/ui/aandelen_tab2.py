from PySide6.QtWidgets import QWidget, QVBoxLayout, QTableView, QLabel, QPushButton, QHeaderView
from portefeuille_viewer.domain.portfolio_engine import PortfolioEngine
from portefeuille_viewer.ui.models import PolarsTableModel

class AandelenTab2(QWidget):
    """
    Tab voor het tonen van de geaggregeerde aandelen-posities uit PortfolioEngine.
    Kolommen: asset_rollup, koers, aantal_bezit, result_realised, result_non_realised
    """

    def __init__(self, pricefeed, parent=None):
        super().__init__(parent)
        self.engine = PortfolioEngine(pricefeed)

        layout = QVBoxLayout(self)
        self.setLayout(layout)

        self.label = QLabel("Aandelen-overzicht (geaggregeerd)")
        layout.addWidget(self.label)

        self.table = QTableView()
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)

        btn_reload = QPushButton("🔄 Vernieuw gegevens")
        btn_reload.clicked.connect(self.reload_data)
        layout.addWidget(btn_reload)

        # Initieel laden
        self.reload_data()

        # Koppel live update van koers via pricefeed signaal
        pricefeed.priceUpdated.connect(self.on_price_update)

    def reload_data(self):
        """Laad en toon de geaggregeerde dataset."""
        df = self.engine.get_aggregated()
        df = df.sort("asset_rollup")  # Sorteer hier!
        self.model = PolarsTableModel(df, self)
        self.table.setModel(self.model)
        self.label.setText(f"{len(df)} regels geladen.")

    def on_price_update(self, *args):
        """Bij koersupdate: refresh aggregatie."""
        self.reload_data()