"""
Option Chain Table Model
Polars-based table model voor option chain display
"""

import datetime
import polars as pl
from PySide6.QtCore import QAbstractTableModel, Qt, QModelIndex


class OptionChainTableModel(QAbstractTableModel):
    """
    Table model voor option chain data (Polars DataFrame)
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._df: pl.DataFrame | None = None
        self._columns = []
    
    def set_dataframe(self, df: pl.DataFrame):
        """Update table met nieuwe DataFrame"""
        self.beginResetModel()
        self._df = df
        self._columns = df.columns if df is not None else []
        self.endResetModel()
    
    def clear(self):
        """Clear table"""
        self.beginResetModel()
        self._df = None
        self._columns = []
        self.endResetModel()
    
    def rowCount(self, parent=QModelIndex()):
        if self._df is None:
            return 0
        return len(self._df)
    
    def columnCount(self, parent=QModelIndex()):
        if self._df is None:
            return 0
        return len(self._columns)
    
    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or self._df is None:
            return None
        
        row = index.row()
        col = index.column()
        
        if row >= len(self._df) or col >= len(self._columns):
            return None
        
        val = self._df[row, col]
        
        # Display role
        if role == Qt.DisplayRole:
            if val is None:
                return ""
            
            # Format floats (2 decimals, European style)
            if isinstance(val, float):
                return f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            
            # Format dates
            if isinstance(val, datetime.date):
                return val.strftime("%d/%m/%Y")
            
            return str(val)
        
        # Text alignment
        if role == Qt.TextAlignmentRole:
            # Numbers right-aligned
            if isinstance(val, (int, float)):
                return Qt.AlignRight | Qt.AlignVCenter
            # Dates center-aligned
            if isinstance(val, datetime.date):
                return Qt.AlignCenter | Qt.AlignVCenter
            # Text left-aligned
            return Qt.AlignLeft | Qt.AlignVCenter
        
        # Background color for Call/Put
        if role == Qt.BackgroundRole:
            # Get Type column index
            if "Type" in self._columns:
                type_col_idx = self._columns.index("Type")
                option_type = self._df[row, type_col_idx]
                
                # Light green for Calls
                if option_type == "C":
                    from PySide6.QtGui import QColor
                    return QColor(200, 255, 200)  # Light green
                # Light red for Puts
                elif option_type == "P":
                    from PySide6.QtGui import QColor
                    return QColor(255, 200, 200)  # Light red
        
        return None
    
    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        
        if orientation == Qt.Horizontal:
            if self._df is None or section >= len(self._columns):
                return None
            return self._columns[section]
        
        if orientation == Qt.Vertical:
            return str(section + 1)
        
        return None
    
    def get_row_data(self, row: int) -> dict:
        """Get all data for a specific row"""
        if self._df is None or row >= len(self._df):
            return {}
        
        row_dict = {}
        for col_idx, col_name in enumerate(self._columns):
            row_dict[col_name] = self._df[row, col_idx]
        
        return row_dict
