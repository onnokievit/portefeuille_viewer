from __future__ import annotations

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSize, Qt


class DataFrameTableModel(QAbstractTableModel):
    def __init__(self, df: pd.DataFrame | None = None):
        super().__init__()
        self._df = df if df is not None else pd.DataFrame()

    def set_dataframe(self, df: pd.DataFrame) -> None:
        self.beginResetModel()
        self._df = df.copy()
        self.endResetModel()

    def dataframe(self) -> pd.DataFrame:
        return self._df.copy()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._df)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._df.columns)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or role not in (Qt.DisplayRole, Qt.TextAlignmentRole):
            return None
        value = self._df.iat[index.row(), index.column()]
        if role == Qt.TextAlignmentRole:
            if isinstance(value, (int, float)):
                return Qt.AlignRight | Qt.AlignVCenter
            return Qt.AlignLeft | Qt.AlignVCenter
        if pd.isna(value):
            return ""
        if isinstance(value, float):
            return f"{value:,.2f}"
        return str(value)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if orientation == Qt.Horizontal:
            text = str(self._df.columns[section])
            if role == Qt.DisplayRole:
                return text.replace(" | ", "\n")
            if role == Qt.TextAlignmentRole:
                return Qt.AlignCenter
            if role == Qt.SizeHintRole:
                line_count = text.count(" | ") + 1
                return QSize(90, max(30, 18 * line_count + 10))
            return None
        if role != Qt.DisplayRole:
            return None
        return str(section + 1)

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsSelectable | Qt.ItemIsEnabled
