from __future__ import annotations

from datetime import date

import polars as pl
from PySide6.QtCore import QAbstractTableModel, QDate, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QDateEdit,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableView,
    QVBoxLayout,
)

from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE


POS_BG = QColor("#d8efcf")
POS_FG = QColor("#14611f")
NEG_BG = QColor("#f5cfcf")
NEG_FG = QColor("#9d1717")


class MonthEndCompareModel(QAbstractTableModel):
    COLUMNS = ["Asset", "Startwaarde", "Eindwaarde", "Verschil"]

    def __init__(self, rows: list[dict] | None = None, parent=None):
        super().__init__(parent)
        self._rows = list(rows or [])

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()
        keys = ["asset", "start", "end", "diff"]
        value = row.get(keys[col])

        if role == Qt.UserRole:
            return value
        if role == Qt.TextAlignmentRole:
            return (Qt.AlignLeft if col == 0 else Qt.AlignRight) | Qt.AlignVCenter
        if col == 3 and isinstance(value, (int, float)):
            if role == Qt.BackgroundRole and value != 0:
                return QBrush(POS_BG if value > 0 else NEG_BG)
            if role == Qt.ForegroundRole and value != 0:
                return QBrush(POS_FG if value > 0 else NEG_FG)
        if role != Qt.DisplayRole:
            return None
        if col == 0:
            return str(value or "")
        if value is None:
            return ""
        return f"{float(value):,.2f}"

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.COLUMNS[section]
        return str(section + 1)


class MonthEndCompareSortProxy(QSortFilterProxyModel):
    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        left_value = self.sourceModel().data(left, Qt.UserRole)
        right_value = self.sourceModel().data(right, Qt.UserRole)
        if left.column() > 0 and right.column() > 0:
            try:
                return float(left_value or 0.0) < float(right_value or 0.0)
            except Exception:
                pass
        return str(left_value or "").lower() < str(right_value or "").lower()


class MonthEndCompareDialog(QDialog):
    def __init__(self, month_end_tab, parent=None):
        super().__init__(parent)
        self._tab = month_end_tab
        self.setWindowTitle("Eindwaarden Vergelijken")
        self.resize(920, 680)

        self._model = MonthEndCompareModel(parent=self)
        self._proxy = MonthEndCompareSortProxy(self)
        self._proxy.setSourceModel(self._model)

        root = QVBoxLayout(self)
        controls = QHBoxLayout()

        self.start_date = QDateEdit(self)
        self.start_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat("dd-MM-yyyy")
        self.start_date.setDate(QDate(self._tab._start_date.year, self._tab._start_date.month, self._tab._start_date.day))

        self.end_date = QDateEdit(self)
        self.end_date.setCalendarPopup(True)
        self.end_date.setDisplayFormat("dd-MM-yyyy")
        self.end_date.setDate(QDate(self._tab._end_date.year, self._tab._end_date.month, self._tab._end_date.day))

        refresh = QPushButton("Vergelijk", self)
        refresh.clicked.connect(self.refresh)

        controls.addWidget(QLabel("Startdatum"))
        controls.addWidget(self.start_date)
        controls.addWidget(QLabel("Einddatum"))
        controls.addWidget(self.end_date)
        controls.addWidget(refresh)
        controls.addStretch(1)
        root.addLayout(controls)

        self.status = QLabel("", self)
        root.addWidget(self.status)

        self.table = QTableView(self)
        self.table.setModel(self._proxy)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)

        self.refresh()

    def refresh(self) -> None:
        start = self.start_date.date().toPython()
        end = self.end_date.date().toPython()
        if end < start:
            start, end = end, start
        rows = self._build_rows(start, end)
        self._model.set_rows(rows)
        self.table.resizeColumnsToContents()
        total_diff = sum(float(row.get("diff") or 0.0) for row in rows)
        self.status.setText(
            f"{len(rows)} assets | start {start.isoformat()} | eind {end.isoformat()} | totaal verschil {total_diff:,.2f}"
        )

    def _build_rows(self, start: date, end: date) -> list[dict]:
        df_source = getattr(SNAPSHOT_STORE, "repository_snapshot_per_dag_asset_result_v2", None)
        matrix = self._tab._build_matrix(
            df_source,
            [start, end],
            group_keys=["asset_rollup", "value_grow", "sector", "regio"],
            apply_sector_filter=True,
        )
        if matrix is None or matrix.is_empty():
            return []

        start_col = _date_label(start)
        end_col = _date_label(end)
        if start_col not in matrix.columns:
            matrix = matrix.with_columns(pl.lit(None).cast(pl.Float64).alias(start_col))
        if end_col not in matrix.columns:
            matrix = matrix.with_columns(pl.lit(None).cast(pl.Float64).alias(end_col))

        rows: list[dict] = []
        for row in matrix.select(["asset_rollup", start_col, end_col]).to_dicts():
            start_value = _to_float(row.get(start_col))
            end_value = _to_float(row.get(end_col))
            calc_start = 0.0 if start_value is None else start_value
            calc_end = 0.0 if end_value is None else end_value
            rows.append(
                {
                    "asset": row.get("asset_rollup") or "",
                    "start": calc_start,
                    "end": calc_end,
                    "diff": calc_end - calc_start,
                }
            )
        return sorted(rows, key=lambda r: str(r.get("asset") or ""))


def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _date_label(dt: date) -> str:
    return f"{dt.day:02d}-{dt.month:02d}-{dt.year % 100:02d}"
