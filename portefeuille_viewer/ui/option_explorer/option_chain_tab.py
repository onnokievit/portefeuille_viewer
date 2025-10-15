"""
Option Chain Explorer Tab
Main UI voor option chain exploration (MVP - geen live prices)
"""

from datetime import date, timedelta
import polars as pl
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QTableView, QGroupBox, QRadioButton, QButtonGroup,
    QLineEdit, QDateEdit, QHeaderView, QMessageBox
)
from PySide6.QtCore import Qt, QDate

from ...data.snapshot_store import SNAPSHOT_STORE
from .option_chain_service import OptionChainService
from .option_chain_model import OptionChainTableModel


class OptionChainTab(QWidget):
    """
    Option Chain Explorer Tab
    
    Functionaliteit:
    - Select symbol uit asset_rollup_data
    - Select expiry date range
    - Filter op strike range
    - Filter op Call/Put/Both
    - Toon option chain in tabel (MVP: geen live prices)
    """
    
    def __init__(self, feed_service, parent=None):
        super().__init__(parent)
        self.feed_service = feed_service
        
        # Service voor IBKR calls
        self.option_chain_service = OptionChainService(feed_service)
        
        # Connect signals
        self.option_chain_service.contracts_received.connect(self._on_contracts_received)
        self.option_chain_service.error_occurred.connect(self._on_error)
        self.option_chain_service.request_completed.connect(self._on_request_completed)
        
        # Build UI
        self._init_ui()
        
        # Load symbols
        self._load_symbols()
    
    def _init_ui(self):
        """Initialize UI components"""
        layout = QVBoxLayout(self)
        
        # Title
        title = QLabel("Option Chain Explorer")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title)
        
        # Filters section
        filters_group = self._create_filters_section()
        layout.addWidget(filters_group)
        
        # Table section
        table_group = self._create_table_section()
        layout.addLayout(table_group)
        
        # Status label
        self.status_label = QLabel("Ready. Select symbol and click Refresh to load option chain.")
        self.status_label.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(self.status_label)
    
    def _create_filters_section(self) -> QGroupBox:
        """Create filters section"""
        group = QGroupBox("Filters")
        layout = QVBoxLayout()
        
        # Row 1: Symbol
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Symbol:"))
        self.symbol_combo = QComboBox()
        self.symbol_combo.setMinimumWidth(150)
        self.symbol_combo.setEditable(True)  # Allow manual input
        row1.addWidget(self.symbol_combo)
        row1.addStretch()
        layout.addLayout(row1)
        
        # Row 2: Expiry Range
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Expiry Range:"))
        
        row2.addWidget(QLabel("From:"))
        self.expiry_from = QDateEdit()
        self.expiry_from.setCalendarPopup(True)
        self.expiry_from.setDisplayFormat("dd/MM/yyyy")
        self.expiry_from.setDate(QDate.currentDate())
        row2.addWidget(self.expiry_from)
        
        row2.addWidget(QLabel("To:"))
        self.expiry_to = QDateEdit()
        self.expiry_to.setCalendarPopup(True)
        self.expiry_to.setDisplayFormat("dd/MM/yyyy")
        self.expiry_to.setDate(QDate.currentDate().addMonths(3))
        row2.addWidget(self.expiry_to)
        
        row2.addStretch()
        layout.addLayout(row2)
        
        # Row 3: Strike Range
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Strike Range:"))
        
        row3.addWidget(QLabel("Min:"))
        self.strike_min = QLineEdit()
        self.strike_min.setPlaceholderText("Optional")
        self.strike_min.setMaximumWidth(100)
        row3.addWidget(self.strike_min)
        
        row3.addWidget(QLabel("Max:"))
        self.strike_max = QLineEdit()
        self.strike_max.setPlaceholderText("Optional")
        self.strike_max.setMaximumWidth(100)
        row3.addWidget(self.strike_max)
        
        row3.addWidget(QLabel("(leave empty for all strikes)"))
        row3.addStretch()
        layout.addLayout(row3)
        
        # Row 4: Option Type (Radio buttons)
        row4 = QHBoxLayout()
        row4.addWidget(QLabel("Option Type:"))
        
        self.type_both = QRadioButton("Both")
        self.type_calls = QRadioButton("Calls Only")
        self.type_puts = QRadioButton("Puts Only")
        
        self.type_both.setChecked(True)  # Default
        
        # Button group
        self.type_button_group = QButtonGroup()
        self.type_button_group.addButton(self.type_both, 0)
        self.type_button_group.addButton(self.type_calls, 1)
        self.type_button_group.addButton(self.type_puts, 2)
        
        row4.addWidget(self.type_both)
        row4.addWidget(self.type_calls)
        row4.addWidget(self.type_puts)
        row4.addStretch()
        layout.addLayout(row4)
        
        # Row 5: Refresh & Stop Buttons
        row5 = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh Option Chain")
        self.refresh_button.clicked.connect(self._on_refresh_clicked)
        self.refresh_button.setStyleSheet("font-weight: bold; padding: 5px;")
        row5.addWidget(self.refresh_button)
        
        self.stop_button = QPushButton("Stop Receiving")
        self.stop_button.clicked.connect(self._on_stop_clicked)
        self.stop_button.setEnabled(False)  # Disabled by default
        self.stop_button.setStyleSheet("padding: 5px;")
        row5.addWidget(self.stop_button)
        
        row5.addStretch()
        layout.addLayout(row5)
        
        group.setLayout(layout)
        return group
    
    def _create_table_section(self) -> QVBoxLayout:
        """Create table section"""
        layout = QVBoxLayout()
        
        # Table
        self.table_view = QTableView()
        self.table_model = OptionChainTableModel()
        self.table_view.setModel(self.table_model)
        
        # Table properties
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSelectionBehavior(QTableView.SelectRows)
        self.table_view.setSelectionMode(QTableView.SingleSelection)
        self.table_view.setSortingEnabled(True)
        
        # Column resize mode
        header = self.table_view.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.Interactive)
        
        layout.addWidget(self.table_view)
        
        return layout
    
    def _load_symbols(self):
        """Load symbols from snapshot_asset_rollup_data"""
        if SNAPSHOT_STORE.snapshot_asset_rollup_data is None:
            self.status_label.setText("⚠️ No asset data loaded. Please load portfolio first.")
            return
        
        try:
            # Get unique IB symbols (not asset_rollup!)
            df = SNAPSHOT_STORE.snapshot_asset_rollup_data
            symbols = df['ib_symbol'].unique().sort()
            
            # Populate combo box
            self.symbol_combo.clear()
            self.symbol_combo.addItems(symbols.to_list())
            
            print(f"[OptionChain] Loaded {len(symbols)} IB symbols")
            
        except Exception as e:
            print(f"[OptionChain] Error loading symbols: {e}")
            self.status_label.setText(f"⚠️ Error loading symbols: {e}")
    
    def _on_refresh_clicked(self):
        """Handle refresh button click"""
        # Validate inputs
        symbol = self.symbol_combo.currentText().strip()
        if not symbol:
            QMessageBox.warning(self, "Input Error", "Please select or enter a symbol.")
            return
        
        # Get filter values
        expiry_from = self.expiry_from.date().toPython()
        expiry_to = self.expiry_to.date().toPython()
        
        # Validate date range
        if expiry_from > expiry_to:
            QMessageBox.warning(self, "Input Error", "Start date must be before end date.")
            return
        
        # Get strike range (optional)
        strike_min = None
        strike_max = None
        
        strike_min_text = self.strike_min.text().strip()
        strike_max_text = self.strike_max.text().strip()
        
        try:
            if strike_min_text:
                strike_min = float(strike_min_text)
            if strike_max_text:
                strike_max = float(strike_max_text)
                
            if strike_min and strike_max and strike_min > strike_max:
                QMessageBox.warning(self, "Input Error", "Min strike must be less than max strike.")
                return
        except ValueError:
            QMessageBox.warning(self, "Input Error", "Strike prices must be valid numbers.")
            return
        
        # Get option type
        if self.type_both.isChecked():
            option_type = "both"
        elif self.type_calls.isChecked():
            option_type = "call"
        else:
            option_type = "put"
        
        # Get currency from asset_rollup_data
        currency = self._get_currency_for_symbol(symbol)
        
        # Update UI
        self.refresh_button.setEnabled(False)
        self.refresh_button.setText("Loading...")
        self.stop_button.setEnabled(True)  # Enable stop button
        self.status_label.setText(f"🔄 Requesting option chain for {symbol}...")
        self.table_model.clear()
        
        # Request option chain
        self.option_chain_service.request_option_chain(
            symbol=symbol,
            currency=currency,
            expiry_from=expiry_from,
            expiry_to=expiry_to,
            strike_min=strike_min,
            strike_max=strike_max,
            option_type=option_type
        )
    
    def _get_currency_for_symbol(self, symbol: str) -> str:
        """Get currency for symbol from asset_rollup_data"""
        try:
            df = SNAPSHOT_STORE.snapshot_asset_rollup_data
            # Filter on ib_symbol (not asset_rollup!)
            filtered = df.filter(pl.col('ib_symbol') == symbol)
            
            if len(filtered) > 0 and 'ib_currency' in filtered.columns:
                currency = filtered['ib_currency'][0]
                return currency if currency else "USD"
        except Exception as e:
            print(f"[OptionChain] Error getting currency: {e}")
        
        return "USD"  # Default
    
    def _on_contracts_received(self, contracts: list):
        """Handle contracts received from IBKR"""
        if not contracts:
            self.status_label.setText("⚠️ No options found matching criteria.")
            return
        
        # Convert to Polars DataFrame
        df = self._contracts_to_dataframe(contracts)
        
        # Update table
        self.table_model.set_dataframe(df)
        
        # Update status
        symbol = self.symbol_combo.currentText()
        self.status_label.setText(f"✅ Loaded {len(contracts)} option contracts for {symbol}")
        
        # Auto-resize columns
        self.table_view.resizeColumnsToContents()
    
    def _on_error(self, error_msg: str):
        """Handle error"""
        self.status_label.setText(f"❌ Error: {error_msg}")
        QMessageBox.critical(self, "Error", error_msg)
    
    def _on_request_completed(self):
        """Handle request completion"""
        self.refresh_button.setEnabled(True)
        self.refresh_button.setText("Refresh Option Chain")
        self.stop_button.setEnabled(False)  # Disable stop button
    
    def _on_stop_clicked(self):
        """Handle stop button click"""
        if self.option_chain_service.is_loading():
            # Stop the service
            self.option_chain_service.stop_request()
            # Update UI
            self.refresh_button.setEnabled(True)
            self.refresh_button.setText("Refresh Option Chain")
            self.stop_button.setEnabled(False)
            self.status_label.setText("⚠️ Request stopped by user.")
    
    def _contracts_to_dataframe(self, contracts: list) -> pl.DataFrame:
        """
        Convert contract list to Polars DataFrame
        
        Columns: ConId, Strike, Type, Expiry, Trading Class, Multiplier
        """
        data = {
            'ConId': [],
            'Strike': [],
            'Type': [],
            'Expiry': [],
            'Trading Class': [],
            'Multiplier': [],
        }
        
        for c in contracts:
            data['ConId'].append(c['conId'])
            data['Strike'].append(c['strike'])
            data['Type'].append(c['right'])
            
            # Parse expiry to date
            try:
                from datetime import datetime
                expiry_date = datetime.strptime(c['expiry'], "%Y%m%d").date()
                data['Expiry'].append(expiry_date)
            except:
                data['Expiry'].append(None)
            
            data['Trading Class'].append(c['trading_class'])
            
            # Parse multiplier to int
            try:
                data['Multiplier'].append(int(c['multiplier']))
            except:
                data['Multiplier'].append(100)
        
        # Create DataFrame
        df = pl.DataFrame(data)
        
        # Sort by Expiry, Strike, Type
        df = df.sort(['Expiry', 'Strike', 'Type'])
        
        return df
