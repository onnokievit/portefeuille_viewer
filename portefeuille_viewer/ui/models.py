import pandas as pd
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel
from PySide6.QtGui import QColor, QBrush
import polars as pl
import datetime



# ------------------------------------------------------------
# PandasTableModel — generiek voor Orders-tab
# ------------------------------------------------------------
class PandasTableModel(QAbstractTableModel):
    def __init__(self, df: pd.DataFrame, parent=None):
        super().__init__(parent)
        self._df = df.copy() if df is not None else pd.DataFrame()

    def rowCount(self, parent=QModelIndex()):
        return 0 if self._df is None else len(self._df)

    def columnCount(self, parent=QModelIndex()):
        return 0 if self._df is None else len(self._df.columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or self._df is None:
            return None
        val = self._df.iat[index.row(), index.column()]

        if role == Qt.DisplayRole:
            # Belangrijk: None/NaN/NaT moeten leeg tonen
            return "" if pd.isna(val) else str(val)

        if role == Qt.TextAlignmentRole:
            return (Qt.AlignRight | Qt.AlignVCenter) if isinstance(val, (float, int)) else (Qt.AlignLeft | Qt.AlignVCenter)

        return None



    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole or self._df is None:
            return None
        if orientation == Qt.Horizontal:
            return str(self._df.columns[section])
        return str(section + 1)

    def set_df(self, df: pd.DataFrame):
        self.beginResetModel()
        self._df = df.copy() if df is not None else pd.DataFrame()
        self.endResetModel()

    def get_row(self, row_idx: int) -> dict:
        """Geef de geselecteerde rij als dict terug, of {} als out-of-range."""
        if self._df is None or row_idx < 0 or row_idx >= len(self._df):
            return {}
        return self._df.iloc[row_idx].to_dict()
    def append_df(self, df_more: pd.DataFrame):
        if df_more is None or df_more.empty:
            return
        start = len(self._df)
        self.beginInsertRows(QModelIndex(), start, start + len(df_more) - 1)
        self._df = pd.concat([self._df, df_more], ignore_index=True)
        self.endInsertRows()


class HighlightingPandasTableModel(PandasTableModel):
    """Pandas model that can highlight specific rows by Id via BackgroundRole."""
    def __init__(self, df: pd.DataFrame, parent=None, highlight_ids=None):
        super().__init__(df, parent)
        self._highlight_ids = set(int(i) for i in (highlight_ids or []) if i is not None)

    def set_highlight_ids(self, ids):
        self._highlight_ids = set(int(i) for i in (ids or []) if i is not None)
        if self.rowCount() and self.columnCount():
            tl = self.index(0, 0)
            br = self.index(self.rowCount() - 1, self.columnCount() - 1)
            self.dataChanged.emit(tl, br, [Qt.BackgroundRole])

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.BackgroundRole and self._highlight_ids and self._df is not None:
            try:
                # PandasTableModel ensures column order; find Id column index
                id_col = self._df.columns.get_loc("Id")
                row_id = self._df.iat[index.row(), id_col]
                if pd.notna(row_id):
                    try:
                        rid = int(row_id)
                    except Exception:
                        rid = None
                    if rid is not None and rid in self._highlight_ids:
                        return QBrush(QColor("#FFF2CC"))
            except Exception:
                pass
        return super().data(index, role)

    def set_df(self, df: pd.DataFrame):
        super().set_df(df)
        # repaint after dataset change
        if self.rowCount() and self.columnCount():
            tl = self.index(0, 0)
            br = self.index(self.rowCount() - 1, self.columnCount() - 1)
            self.dataChanged.emit(tl, br, [Qt.BackgroundRole])



# ------------------------------------------------------------
# Polars model voor portefeuille (
# ------------------------------------------------------------
class PolarsTableModel(QAbstractTableModel):
    """
    Qt-model dat data rechtstreeks uit een Polars DataFrame toont.
    Te gebruiken voor de Live-tab.
    """

    def __init__(self, df: pl.DataFrame | None = None, parent=None):
        super().__init__(parent)
        self._df = df if df is not None else pl.DataFrame()
        self._cols = list(self._df.columns)

    def set_df(self, df: pl.DataFrame):
        self.layoutAboutToBeChanged.emit()
        #self.beginResetModel()
        self._df = df if df is not None else pl.DataFrame()
        self._cols = list(self._df.columns)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if self._df.is_empty() else self._df.height

    def columnCount(self, parent=QModelIndex()):
        return 0 if self._df.is_empty() else self._df.width

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self._cols[section]
        return str(section + 1)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or self._df.is_empty():
            return None

        val = self._df[index.row(), index.column()]
        col_name = self._cols[index.column()]

        # --- Tekstopmaak ---
        if role == Qt.DisplayRole:
            if val is None:
                return ""
            if isinstance(val, float):
                return f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            # Format date columns without timestamp
            return val.strftime("%d/%m/%Y") if isinstance(val, datetime.date) else str(val)
        # --- Sorteer data (echte waarden voor QSortFilterProxyModel) ---
        if role == Qt.UserRole:
            # Geef de echte waarde terug voor sorting
            if val is None:
                return None
            # Converteer Polars types naar Python types
            return float(val) if isinstance(val, (int, float)) else str(val)
        if role == Qt.TextAlignmentRole:
            if isinstance(val, (int, float)):
                return Qt.AlignRight | Qt.AlignVCenter
            # Center align date columns
            if isinstance(val, datetime.date):
                return Qt.AlignCenter | Qt.AlignVCenter
            return Qt.AlignLeft | Qt.AlignVCenter

        # if role == Qt.ForegroundRole and col_name.lower().startswith("totaal"):
        #     if isinstance(val, (int, float)):
        #         return QBrush(QColor("darkgreen") if val >= 0 else QColor("red"))
        if role == Qt.BackgroundRole and col_name.lower().startswith("totaal") and isinstance(val, (int, float)):
            return QBrush(QColor("#c6f7c6") if val >= 0 else QColor("#f7c6c6"))
        if role == Qt.BackgroundRole and col_name.lower().startswith("net_change") and isinstance(val, (int, float)):
            return QBrush(QColor("#c6f7c6") if val >= 0 else QColor("#f7c6c6"))
        return None

class ColoredPolarsTableModel(PolarsTableModel):
    def __init__(self, df, kleur_kolommen=None, kleur_func=None, *args, **kwargs):
        super().__init__(df, *args, **kwargs)
        self.kleur_kolommen = kleur_kolommen or []
        self.kleur_func = kleur_func

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            return super().data(index, role)
        if role == Qt.BackgroundRole and self.kleur_func:
            row = self._df.row(index.row())
            colname = self._df.columns[index.column()]
            kleur = self.kleur_func(row, colname, self.kleur_kolommen)
            if kleur:
                return kleur
        return super().data(index, role)
    
    def sort(self, column, order):
        self.layoutAboutToBeChanged.emit()
        colname = self._df.columns[column]
        ascending = order == Qt.AscendingOrder
        self._df = self._df.sort(colname, reverse=not ascending)
        self.layoutChanged.emit()


class MultiColFilterProxy(QSortFilterProxyModel):
    """
    Houdt per kolom een set 'in'-waardes, 'eq' of 'contains' filter bij.
    Werkt bovenop WidePerAssetModel (client-side filtering).
    """
    def __init__(self, col_names: list[str], parent=None):
        super().__init__(parent)
        self._cols = list(col_names)
        self._in = {}         # {colname: set([...])}
        self._eq = {}         # {colname: value}
        self._contains = {}   # {colname: "substr"}

        self.setDynamicSortFilter(True)

    def clearAll(self):
        self._in.clear()
        self._eq.clear()
        self._contains.clear()
        self.invalidateFilter()

    def clearFor(self, col: str):
        self._in.pop(col, None)
        self._eq.pop(col, None)
        self._contains.pop(col, None)
        self.invalidateFilter()

    def setIn(self, col: str, values: set):
        self._in[col] = set(values or [])
        self.invalidateFilter()

    def setEq(self, col: str, value):
        self._eq[col] = value
        self.invalidateFilter()

    def setContains(self, col: str, substr: str):
        self._contains[col] = (substr or "").strip()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:
        sm = self.sourceModel()
        if sm is None:
            return True
        # lees rechtstreeks uit model._df voor performance en betrouwbaarheid
        try:
            df = sm._df
        except Exception:
            return True

        for col, want in self._in.items():
            if want:
                val = df.iloc[source_row][col]
                # None/"" worden in set gerepresenteerd als None
                v = None if pd.isna(val) or not str(val).strip() else str(val)
                if v not in want:
                    return False

        for col, v in self._eq.items():
            val = df.iloc[source_row][col]
            if pd.isna(val) or str(val) != str(v):
                return False

        for col, substr in self._contains.items():
            if substr:
                val = str(df.iloc[source_row][col])
                if substr.lower() not in val.lower():
                    return False

        return True

