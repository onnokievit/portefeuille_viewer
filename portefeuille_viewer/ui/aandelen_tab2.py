from PySide6.QtWidgets import QWidget, QVBoxLayout, QTableView, QLabel, QPushButton, QHeaderView
from portefeuille_viewer.domain.portfolio_engine import PortfolioEngine
from portefeuille_viewer.ui.models import PolarsTableModel


class AandelenTab2(QWidget):
    """
    Tab voor het tonen van de geaggregeerde aandelen-posities uit PortfolioEngine.
    Kolommen: asset_rollup, koers, aantal_bezit, result_realised, result_non_realised
    """

    def __init__(self, portfolio_engine=None, pricefeed=None, parent=None):
        super().__init__(parent)
        
        # Use provided portfolio_engine or create our own for backward compatibility
        if portfolio_engine is not None:
            self.engine = portfolio_engine
            # Get the pricefeed from the engine for signal connection
            if hasattr(self.engine, 'pricefeed'):
                pricefeed = self.engine.pricefeed
        else:
            # Fallback: create own engine (backward compatibility)
            if pricefeed is None:
                raise ValueError("Either portfolio_engine or pricefeed must be provided")
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

        # Koppel live update: 
        # Als we een gecentraliseerde engine hebben, luister naar zijn dataUpdated signaal
        if hasattr(self.engine, 'dataUpdated'):
            self.engine.dataUpdated.connect(self.on_engine_data_update)
        
        # Fallback: luister naar pricefeed signalen (backward compatibility)
        elif pricefeed and hasattr(pricefeed, 'priceUpdated'):
            pricefeed.priceUpdated.connect(self.on_price_update)

    def reload_data(self):
        """Laad en toon de geaggregeerde dataset."""
        df = self.engine.get_aggregated()
        df = df.sort("asset_rollup")  # Sorteer hier!
        self.model = PolarsTableModel(df, self)
        self.table.setModel(self.model)
        self.label.setText(f"{len(df)} regels geladen.")

    def on_engine_data_update(self):
        """Bij data update van PortfolioEngine: refresh aggregatie."""
        self.reload_data()
    
    def on_price_update(self, *args):
        """Bij koersupdate via pricefeed: refresh aggregatie (fallback)."""
        print(f"📊 AandelenTab2: Received price update signal - refreshing... (args: {args})")
        self.reload_data()