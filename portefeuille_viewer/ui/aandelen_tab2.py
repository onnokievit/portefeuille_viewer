from PySide6.QtWidgets import QWidget, QVBoxLayout, QTableView, QLabel, QPushButton, QHeaderView
from PySide6.QtCore import Slot, QSortFilterProxyModel, Qt
from portefeuille_viewer.domain.portfolio_engine import PortfolioEngine
from portefeuille_viewer.ui.models import PolarsTableModel
import polars as pl
from PySide6.QtWidgets import QComboBox
from portefeuille_viewer.ui.filter_popup import ColumnFilterPopup
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

        # --------------- drowdown voor broker selectie
        self.broker_select_btn = QPushButton("Selecteer brokers")
        self.broker_select_btn.clicked.connect(self.open_broker_popup)
        layout.addWidget(self.broker_select_btn)
        self.selected_brokers = None  # None = alles tonen
        # einde --------------- drowdown voor broker selectie

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

        # self.table.horizontalHeader().setSectionsMovable(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)


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
        from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE

        df = SNAPSHOT_STORE.aggregator_snapshot_aandelen_live
        # Filter op broker
        if self.selected_brokers is not None and "broker" in df.columns:
            df = df.filter(pl.col("broker").is_in(list(self.selected_brokers)))
        # Sum na filtering (groepeer op asset_rollup)
        if not df.is_empty():
            df_aandelen_sum = df.group_by("asset_rollup","koers").agg([
                pl.col("aantal_bezit").sum().alias("eq_aantal_bezit"),
                pl.col("aantal_koop").sum().alias("eq_aantal_koop"),
                pl.col("euro_koop").sum().alias("eq_euro_koop"),
                pl.col("aantal_verkoop").sum().alias("eq_aantal_verkoop"),
                pl.col("euro_verkoop").sum().alias("eq_euro_verkoop"),
                pl.col("total_result").sum().alias("eq_total_result"),
                pl.col("eq_total_fee").sum().alias("eq_total_fee"),
            ])
        else:
            df_aandelen_sum = df

        df_gesloten_opties = SNAPSHOT_STORE.repository_snapshot_gesloten_opties
        if self.selected_brokers is not None and "broker" in df.columns:
            df_gesloten_opties = df_gesloten_opties.filter(pl.col("broker").is_in(list(self.selected_brokers)))
                # Sum na filtering (groepeer op asset_rollup)
        if not df_gesloten_opties.is_empty():
            df_clos_opt_sum = df_gesloten_opties.group_by("asset_rollup").agg([
                pl.col("clos_opt_transactie_euro_totaal").sum(),
                pl.col("clos_opt_transactie_fee").sum(),
            ])
        else:
            df_clos_opt_sum = df_gesloten_opties


        df_gesloten_sprinters = SNAPSHOT_STORE.repository_snapshot_gesloten_sprinters_no_asset_detail
        if self.selected_brokers is not None and "broker" in df.columns:
            df_gesloten_sprinters = df_gesloten_sprinters.filter(pl.col("broker").is_in(list(self.selected_brokers)))
                # Sum na filtering (groepeer op asset_rollup)
        if not df_gesloten_sprinters.is_empty():
            df_clos_sp_sum = df_gesloten_sprinters.group_by("asset_rollup").agg([
                pl.col("clos_sp_transactie_euro_totaal").sum(),
                pl.col("clos_sp_transactie_fee").sum(),
            ])
        else:
            df_clos_sp_sum = df_gesloten_opties


        df_open_opties = SNAPSHOT_STORE.aggregator_snapshot_load_open_opties_from_tx_live
        if self.selected_brokers is not None and "broker" in df.columns:
            df_open_opties = df_open_opties.filter(pl.col("broker").is_in(list(self.selected_brokers)))
                # Sum na filtering (groepeer op asset_rollup)
        if not df_open_opties.is_empty():
            df_open_opt_sum = df_open_opties.group_by("asset_rollup").agg([
                pl.col("opt_total_result").sum().alias("open_opt_total_result"),
                pl.col("SomVantransactie_fee").sum().alias("open_opt_transactie_fee"),
             ])
        else:
            df_open_opt_sum = df_open_opties


        df_open_sprinters = SNAPSHOT_STORE.aggregator_snapshot_open_sprinters_live
        if self.selected_brokers is not None and "broker" in df.columns:
            df_open_sprinters = df_open_sprinters.filter(pl.col("broker").is_in(list(self.selected_brokers)))
                # Sum na filtering (groepeer op asset_rollup)
        if not df_open_sprinters.is_empty():
            df_open_sp_sum = df_open_sprinters.group_by("asset_rollup").agg([
                pl.col("sp_result").sum().alias("open_sp_result"),
                pl.col("SomVantransactie_fee").sum().alias("open_sp_transactie_fee"),
                pl.col("SomVantransactie_aantal").sum().alias("open_sp_aantal"),
             ])
        else:
            df_open_sp_sum = df_open_sprinters




        df_aand_opt = df_aandelen_sum.join(df_clos_opt_sum, on=["asset_rollup"], how="full", suffix="_opt_gesloten")
        if "asset_rollup_opt_gesloten" in df_aand_opt.columns:
            df_aand_opt = df_aand_opt.with_columns([
                pl.coalesce([pl.col("asset_rollup"), pl.col("asset_rollup_opt_gesloten")]).alias("asset_rollup")
        ])

        df_aand_opt_sp = df_aand_opt.join(df_clos_sp_sum, on=["asset_rollup"], how="full", suffix="_sp_gesloten")
        if "asset_rollup_sp_gesloten" in df_aand_opt_sp.columns:
            df_aand_opt_sp = df_aand_opt_sp.with_columns([
                pl.coalesce([pl.col("asset_rollup"), pl.col("asset_rollup_sp_gesloten")]).alias("asset_rollup")
        ])

        df_aand_opt_sp_open_opt = df_aand_opt_sp.join(df_open_opt_sum, on=["asset_rollup"], how="full", suffix="_opt_o_open")
        if "asset_rollup_opt_o_open" in df_aand_opt_sp_open_opt.columns:
            df_aand_opt_sp_open_opt = df_aand_opt_sp_open_opt.with_columns([
                pl.coalesce([pl.col("asset_rollup"), pl.col("asset_rollup_opt_o_open")]).alias("asset_rollup")
        ])
            

        df_open_sp_sum = df_aand_opt_sp_open_opt.join(df_open_sp_sum, on=["asset_rollup"], how="full", suffix="_sp_open")
        if "asset_rollup_opt_o_open" in df_aand_opt_sp_open_opt.columns:
            df_open_sp_sum = df_open_sp_sum.with_columns([
                pl.coalesce([pl.col("asset_rollup"), pl.col("asset_rollup_sp_open")]).alias("asset_rollup")
        ])




        # Sum na filtering (groepeer op asset_rollup)
        if not df_open_sp_sum.is_empty():
            df_sum = df_open_sp_sum.group_by("asset_rollup", "koers").agg([
                pl.col("eq_aantal_bezit").sum().alias("eq_aantal_bezit"),
                pl.col("open_sp_aantal").sum().alias("open_sp_aantal"),
                pl.col("eq_total_result").sum().alias("eq_total_result"),
                pl.col("clos_opt_transactie_euro_totaal").sum().alias("clos_opt_transactie_euro_totaal"),
                pl.col("clos_sp_transactie_euro_totaal").sum().alias("clos_sp_transactie_euro_totaal"),
                pl.col("open_opt_total_result").sum().alias("open_opt_total_result"),
                pl.col("open_sp_result").sum().alias("open_sp_result"),
                pl.col("eq_total_fee").sum().alias("eq_total_fee"),
                pl.col("clos_opt_transactie_fee").sum().alias("clos_opt_transactie_fee"),
                pl.col("clos_sp_transactie_fee").sum().alias("clos_sp_transactie_fee"),
                pl.col("open_opt_transactie_fee").sum().alias("open_opt_transactie_fee"),
                pl.col("open_sp_transactie_fee").sum().alias("open_sp_transactie_fee"),
            ]).with_columns([
                (
                    pl.col("eq_total_result")
                    + pl.col("clos_opt_transactie_euro_totaal")
                    + pl.col("clos_sp_transactie_euro_totaal")
                    + pl.col("open_opt_total_result")
                    + pl.col("open_sp_result")
                ).alias("totaal_resultaat"),
                (
                    pl.col("eq_total_fee")
                    + pl.col("clos_opt_transactie_fee")
                    + pl.col("clos_sp_transactie_fee")
                    + pl.col("open_opt_transactie_fee")
                    + pl.col("open_sp_transactie_fee")
                ).alias("totaal_fee")
            ])
        else:
            df_sum = df

        df_sum = df_sum.select([
            "asset_rollup",
            "koers",
            "eq_aantal_bezit",
            "open_sp_aantal",
            "eq_total_result",
            "clos_opt_transactie_euro_totaal",
            "clos_sp_transactie_euro_totaal",
            "open_opt_total_result",
            "open_sp_result",
            "totaal_resultaat",  # <-- zet deze waar je wilt
            "eq_total_fee",
            "clos_opt_transactie_fee",
            "clos_sp_transactie_fee",
            "open_opt_transactie_fee",
            "open_sp_transactie_fee",
            "totaal_fee",  # <-- zet deze waar je wilt
])

        ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken
        from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
        SNAPSHOT_STORE.test_repository_load_output_test_dataframe = df_sum  # of df_sum als je de gesumde versie wilt zien
        ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken

            
        self.model = PolarsTableModel(df_sum, self)
        self.proxy_model = QSortFilterProxyModel(self)
        self.proxy_model.setSourceModel(self.model)
        self.proxy_model.setSortRole(Qt.UserRole)
        self.table.setModel(self.proxy_model)
        
        # Restore user's sort preferences after model refresh
        if self.current_sort_column >= 0:
            self.table.sortByColumn(self.current_sort_column, self.current_sort_order)
        # Label wordt niet meer overschreven - ticker boodschap blijft staan

    def open_broker_popup(self):
        # Unieke brokers ophalen uit de huidige dataframe
        from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
        df = SNAPSHOT_STORE.aggregator_snapshot_aandelen_live
        if df is None or df.is_empty() or "broker" not in df.columns:
            return
        brokers = sorted(b for b in set(df["broker"].to_list()) if b is not None)
        pre_selected = set(self.selected_brokers) if self.selected_brokers else set(brokers)
        popup = ColumnFilterPopup("Selecteer brokers", brokers, pre_selected, self)
        popup.acceptedSelection.connect(self.set_broker_selection)
        popup.exec()

    def on_broker_selection_changed(self, idx):
        self.reload_data()

    def set_broker_selection(self, selected: set):
        self.selected_brokers = selected
        self.reload_data()

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