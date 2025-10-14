from PySide6.QtWidgets import QWidget, QVBoxLayout, QTableView, QLabel, QPushButton, QHeaderView
from PySide6.QtCore import Slot, QSortFilterProxyModel, Qt
from portefeuille_viewer.domain.portfolio_engine import PortfolioEngine
from portefeuille_viewer.ui.models import PolarsTableModel
import polars as pl


class AandelenTab2(QWidget):
    """
    Tab voor het tonen van de geaggregeerde aandelen-posities uit PortfolioEngine.
    Kolommen: asset_rollup, koers, aantal_bezit, result_realised, result_non_realised
    """

    def __init__(self, portfolio_engine=None, pricefeed=None, parent=None):
        super().__init__(parent)
        
        # Track sort state to preserve user's sorting after data updates
        self.current_sort_column = -1  # -1 means no sorting
        self.current_sort_order = 0     # 0 = ascending, 1 = descending
        
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
        
        # Compact row height for more rows on screen
        self.table.verticalHeader().setDefaultSectionSize(20)  # 22 pixels row height
        
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)

        btn_reload = QPushButton("🔄 Vernieuw gegevens")
        btn_reload.clicked.connect(self.reload_data)
        layout.addWidget(btn_reload)

        # Initieel laden
        self.reload_data()

        # Store pricefeed reference voor ticker display
        self.pricefeed = pricefeed or (self.engine.pricefeed if hasattr(self.engine, 'pricefeed') else None)
        
        # Koppel live update: 
        # Als we een gecentraliseerde engine hebben, luister naar zijn dataUpdated signaal
        if hasattr(self.engine, 'dataUpdated'):
            self.engine.dataUpdated.connect(self.on_engine_data_update)
        
        # Koppel ook aan pricefeed voor ticker display (NIET voor table updates)
        if self.pricefeed and hasattr(self.pricefeed, 'priceUpdated'):
            self.pricefeed.priceUpdated.connect(self.on_ticker_display)
        
        # Fallback: luister naar pricefeed signalen (backward compatibility)
        elif pricefeed and hasattr(pricefeed, 'priceUpdated'):
            pricefeed.priceUpdated.connect(self.on_price_update)

    def on_sort_changed(self, column, order):
        """Track user's sort preferences."""
        self.current_sort_column = column
        self.current_sort_order = order
    
    def reload_data(self):
        """Laad en toon de geaggregeerde dataset."""
        # Load directly from SnapshotStore instead of via engine
        from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
        
        df = SNAPSHOT_STORE.snapshot_aandelen_live
        if df is None or df.is_empty():
            # Fallback: empty dataframe
            import polars as pl
            df = pl.DataFrame({
                "asset_rollup": [],
                "koers": [],
                "aantal_bezit": [],
                "result_realised": [],
                "result_non_realised": [],
                "eq_total_fee": [],
                "total_result": []
            })
            
        self.model = PolarsTableModel(df, self)
        self.proxy_model = QSortFilterProxyModel(self)
        self.proxy_model.setSourceModel(self.model)
        # Use Qt.UserRole for sorting (raw numeric values instead of formatted strings)
        self.proxy_model.setSortRole(Qt.UserRole)
        self.table.setModel(self.proxy_model)
        
        # Restore user's sort preferences after model refresh
        if self.current_sort_column >= 0:
            self.table.sortByColumn(self.current_sort_column, self.current_sort_order)
        # Label wordt niet meer overschreven - ticker boodschap blijft staan

    def on_engine_data_update(self):
        """Bij data update van PortfolioEngine: refresh aggregatie."""
        # Before reload, save current sort state from the table
        if hasattr(self, 'table') and self.table.model() is not None:
            header = self.table.horizontalHeader()
            self.current_sort_column = header.sortIndicatorSection()
            self.current_sort_order = header.sortIndicatorOrder()
        self.reload_data()
    
    @Slot(str, str, float)
    def on_ticker_display(self, sym: str, cur: str, px: float):
        """Toon ticker melding zoals in AandelenTab (GEEN table update)."""
        # Check of dit symbool relevant is voor onze tabel
        if hasattr(self, "model") and not self.model._df.is_empty():
            df = self.model._df
            # Alleen tonen als het symbool in onze tabel voorkomt
            if "ib_symbol" in df.columns:
                if sym in df["ib_symbol"].to_list():
                    self.label.setText(f"📈 Koersupdate ontvangen voor {sym} ({cur}): {px:.2f}")
            elif "asset_rollup" in df.columns:
                if sym in df["asset_rollup"].to_list():
                    self.label.setText(f"📈 Koersupdate ontvangen voor {sym} ({cur}): {px:.2f}")
    
    def on_price_update(self, *args):
        """Bij koersupdate via pricefeed: refresh aggregatie (fallback)."""
        self.reload_data()