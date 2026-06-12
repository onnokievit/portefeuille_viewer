from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from transactie_analyse.data_loader import active_database, load_transactions
from transactie_analyse.pivot_engine import (
    FILTER_COLUMNS,
    GRANULARITIES,
    PIVOT_FIELDS,
    PivotRequest,
    apply_filters,
    build_pivot,
)
from transactie_analyse.table_model import DataFrameTableModel


FILTER_TITLES = {
    "Periode": "Periode",
    "broker": "Broker",
    "ib_currency": "Currency",
    "asset_rollup": "Asset",
    "asset_type": "Asset type",
    "transactie_type": "Transactie type",
    "transactie_oorsprong": "Oorsprong",
    "sector": "Sector",
    "regio": "Regio",
    "value_grow": "Waarde/groei",
}


class FieldListWidget(QListWidget):
    def __init__(self, changed_callback, parent=None):
        super().__init__(parent)
        self._changed_callback = changed_callback
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragDropMode(QListWidget.DragDrop)
        self.setSelectionMode(QListWidget.ExtendedSelection)

    def dropEvent(self, event):
        super().dropEvent(event)
        self._changed_callback()


class TransactionAnalysisWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Transactie Analyse - read only")
        self.resize(1500, 850)

        self.source_df = pd.DataFrame()
        self.full_pivot_df = pd.DataFrame()
        self.pivot_left_model = DataFrameTableModel()
        self.pivot_right_model = DataFrameTableModel()
        self.detail_model = DataFrameTableModel()
        self.filter_lists: dict[str, QListWidget] = {}
        self.field_lists: dict[str, FieldListWidget] = {}

        self._build_ui()
        self._resize_to_available_screen()
        self.reload_data()

    def _build_ui(self) -> None:
        self.status = QLabel("Read-only")

        reload_action = QAction("Vernieuwen", self)
        reload_action.triggered.connect(self.reload_data)
        export_action = QAction("Exporteer CSV", self)
        export_action.triggered.connect(self.export_current_csv)
        self.menuBar().addAction(reload_action)
        self.menuBar().addAction(export_action)

        central = QWidget()
        root = QVBoxLayout(central)

        self.db_label = QLabel("")
        self.db_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.db_label)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)
        splitter.addWidget(self._build_filter_panel())
        splitter.addWidget(self._build_result_panel())
        splitter.setSizes([320, 1180])

        root.addWidget(self.status)
        self.setCentralWidget(central)

    def _build_filter_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(300)
        scroll.setMaximumWidth(430)

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        controls = QGroupBox("Rapport")
        grid = QGridLayout(controls)

        self.granularity_combo = QComboBox()
        self.granularity_combo.addItems(GRANULARITIES.keys())
        self.granularity_combo.setCurrentText("Maand")
        self.granularity_combo.currentTextChanged.connect(self.refresh_views)

        self.count_check = QCheckBox("Aantal")
        self.count_check.setChecked(True)
        self.count_check.toggled.connect(self.refresh_views)

        self.fee_check = QCheckBox("Fee")
        self.fee_check.setChecked(True)
        self.fee_check.toggled.connect(self.refresh_views)

        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("yyyy-MM-dd")
        self.date_from.dateChanged.connect(self.refresh_views)

        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("yyyy-MM-dd")
        self.date_to.dateChanged.connect(self.refresh_views)

        grid.addWidget(QLabel("Periode"), 0, 0)
        grid.addWidget(self.granularity_combo, 0, 1)
        grid.addWidget(self.count_check, 1, 0, 1, 2)
        grid.addWidget(self.fee_check, 2, 0, 1, 2)
        grid.addWidget(QLabel("Van"), 3, 0)
        grid.addWidget(self.date_from, 3, 1)
        grid.addWidget(QLabel("Tot"), 4, 0)
        grid.addWidget(self.date_to, 4, 1)
        layout.addWidget(controls)
        layout.addWidget(self._build_pivot_fields_panel())

        for col in FILTER_COLUMNS:
            box = QGroupBox(FILTER_TITLES.get(col, col))
            box_layout = QVBoxLayout(box)
            list_widget = QListWidget()
            list_widget.setMinimumHeight(70)
            list_widget.setMaximumHeight(110)
            list_widget.itemChanged.connect(self.refresh_views)
            box_layout.addWidget(list_widget)
            buttons = QHBoxLayout()
            select_all = QPushButton("Alles")
            select_all.clicked.connect(lambda _=False, c=col: self._set_filter_checked(c, True))
            clear = QPushButton("Geen")
            clear.clicked.connect(lambda _=False, c=col: self._set_filter_checked(c, False))
            buttons.addWidget(select_all)
            buttons.addWidget(clear)
            box_layout.addLayout(buttons)
            self.filter_lists[col] = list_widget
            layout.addWidget(box)

        layout.addStretch(1)
        scroll.setWidget(panel)
        return scroll

    def _build_pivot_fields_panel(self) -> QWidget:
        box = QGroupBox("Pivot velden")
        layout = QVBoxLayout(box)

        for key, title in (
            ("available", "Beschikbaar"),
            ("rows", "Rijen"),
            ("columns", "Kolommen"),
        ):
            layout.addWidget(QLabel(title))
            list_widget = FieldListWidget(self._on_field_layout_changed)
            list_widget.setMinimumHeight(54)
            list_widget.setMaximumHeight(82)
            self.field_lists[key] = list_widget
            layout.addWidget(list_widget)

        reset = QPushButton("Standaard")
        reset.clicked.connect(self._reset_pivot_fields)
        layout.addWidget(reset)
        self._reset_pivot_fields(refresh=False)
        return box

    def _build_result_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        self.summary_label = QLabel("")
        layout.addWidget(self.summary_label)

        tabs = QTabWidget()
        pivot_widget = QWidget()
        pivot_layout = QHBoxLayout(pivot_widget)
        pivot_layout.setContentsMargins(0, 0, 0, 0)
        pivot_layout.setSpacing(0)

        self.pivot_left_view = QTableView()
        self.pivot_left_view.setModel(self.pivot_left_model)
        self.pivot_left_view.setEditTriggers(QTableView.NoEditTriggers)
        self.pivot_left_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.pivot_left_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.pivot_left_view.setSortingEnabled(False)

        self.pivot_right_view = QTableView()
        self.pivot_right_view.setModel(self.pivot_right_model)
        self.pivot_right_view.setEditTriggers(QTableView.NoEditTriggers)
        self.pivot_right_view.setSortingEnabled(False)
        self.pivot_right_view.verticalScrollBar().valueChanged.connect(
            self.pivot_left_view.verticalScrollBar().setValue
        )
        self.pivot_left_view.verticalHeader().setDefaultSectionSize(
            self.pivot_right_view.verticalHeader().defaultSectionSize()
        )

        pivot_layout.addWidget(self.pivot_left_view)
        pivot_layout.addWidget(self.pivot_right_view, 1)
        tabs.addTab(pivot_widget, "Pivot")

        self.detail_view = QTableView()
        self.detail_view.setModel(self.detail_model)
        self.detail_view.setSortingEnabled(True)
        self.detail_view.setEditTriggers(QTableView.NoEditTriggers)
        tabs.addTab(self.detail_view, "Transacties")
        layout.addWidget(tabs, 1)
        return panel

    def _reset_pivot_fields(self, refresh: bool = True) -> None:
        defaults = {
            "rows": ["Periode"],
            "columns": ["broker", "ib_currency"],
        }
        used = set(defaults["rows"] + defaults["columns"])
        available = [field for field in PIVOT_FIELDS if field not in used]
        for key, values in (
            ("available", available),
            ("rows", defaults["rows"]),
            ("columns", defaults["columns"]),
        ):
            widget = self.field_lists.get(key)
            if widget is None:
                continue
            widget.clear()
            for field in values:
                widget.addItem(FILTER_TITLES.get(field, field))
                widget.item(widget.count() - 1).setData(Qt.UserRole, field)
        if refresh:
            self.refresh_views()

    def _resize_to_available_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            self.resize(1400, 800)
            return
        available = screen.availableGeometry()
        width = min(1500, max(1100, int(available.width() * 0.92)))
        height = min(850, max(650, int(available.height() * 0.88)))
        width = min(width, available.width())
        height = min(height, available.height())
        self.resize(width, height)
        self.move(
            available.x() + max(0, (available.width() - width) // 2),
            available.y() + max(0, (available.height() - height) // 2),
        )

    def _on_field_layout_changed(self) -> None:
        self._deduplicate_field_lists()
        self.refresh_views()

    def _deduplicate_field_lists(self) -> None:
        seen: set[str] = set()
        for key in ("rows", "columns", "available"):
            widget = self.field_lists[key]
            row = 0
            while row < widget.count():
                item = widget.item(row)
                field = item.data(Qt.UserRole) or item.text()
                if field in seen:
                    widget.takeItem(row)
                    continue
                seen.add(field)
                row += 1

    def _fields(self, key: str) -> list[str]:
        widget = self.field_lists[key]
        return [widget.item(row).data(Qt.UserRole) or widget.item(row).text() for row in range(widget.count())]

    def reload_data(self) -> None:
        try:
            db_name, db_path = active_database()
            self.db_label.setText(f"Database: {db_name} - {db_path}")
            self.source_df = load_transactions()
            self._populate_dates()
            self._populate_filters()
            self.refresh_views()
        except Exception as exc:
            QMessageBox.critical(self, "Laden mislukt", str(exc))

    def _populate_dates(self) -> None:
        valid_dates = self.source_df["datum"].dropna()
        if valid_dates.empty:
            today = QDate.currentDate()
            self.date_from.setDate(today)
            self.date_to.setDate(today)
            return
        min_date = valid_dates.min().date()
        max_date = valid_dates.max().date()
        self.date_from.blockSignals(True)
        self.date_to.blockSignals(True)
        self.date_from.setDate(QDate(min_date.year, min_date.month, min_date.day))
        self.date_to.setDate(QDate(max_date.year, max_date.month, max_date.day))
        self.date_from.blockSignals(False)
        self.date_to.blockSignals(False)

    def _populate_filters(self) -> None:
        for col, list_widget in self.filter_lists.items():
            list_widget.blockSignals(True)
            list_widget.clear()
            values = sorted(v for v in self.source_df[col].dropna().astype(str).unique() if v)
            for value in values:
                item = QListWidgetItem(value)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked)
                list_widget.addItem(item)
            list_widget.blockSignals(False)

    def _set_filter_checked(self, col: str, checked: bool) -> None:
        list_widget = self.filter_lists[col]
        list_widget.blockSignals(True)
        state = Qt.Checked if checked else Qt.Unchecked
        for row in range(list_widget.count()):
            list_widget.item(row).setCheckState(state)
        list_widget.blockSignals(False)
        self.refresh_views()

    def _request(self) -> PivotRequest:
        filters = {}
        for col, list_widget in self.filter_lists.items():
            selected = {
                list_widget.item(row).text()
                for row in range(list_widget.count())
                if list_widget.item(row).checkState() == Qt.Checked
            }
            all_values = {list_widget.item(row).text() for row in range(list_widget.count())}
            if selected != all_values:
                filters[col] = selected

        date_from = pd.Timestamp(self.date_from.date().toPython())
        date_to = pd.Timestamp(self.date_to.date().toPython()) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
        return PivotRequest(
            granularity=self.granularity_combo.currentText(),
            enabled_filters=filters,
            row_fields=self._fields("rows"),
            column_fields=self._fields("columns"),
            date_from=date_from,
            date_to=date_to,
            include_count=self.count_check.isChecked(),
            include_fee=self.fee_check.isChecked(),
        )

    def refresh_views(self) -> None:
        if self.source_df.empty:
            return
        request = self._request()
        filtered = apply_filters(self.source_df, request)
        pivot = build_pivot(self.source_df, request)
        self.full_pivot_df = pivot

        detail_cols = [
            "datum",
            "broker",
            "ib_currency",
            "asset_rollup",
            "asset_type",
            "transactie_type",
            "transactie_oorsprong",
            "transactie_fee",
            "sector",
            "regio",
            "value_grow",
            "Id",
        ]
        detail = filtered[detail_cols].sort_values("datum", ascending=False)
        frozen_count = max(1, len(request.row_fields))
        left = pivot.iloc[:, :frozen_count] if not pivot.empty else pd.DataFrame()
        right = pivot.iloc[:, frozen_count:] if not pivot.empty else pd.DataFrame()
        self.pivot_left_model.set_dataframe(left)
        self.pivot_right_model.set_dataframe(right)
        self.detail_model.set_dataframe(detail)
        self.pivot_left_view.resizeColumnsToContents()
        self.pivot_right_view.resizeColumnsToContents()
        self._apply_pivot_header_layout(pivot)
        self._resize_frozen_pivot_width(left)

        total_fee = filtered["transactie_fee"].sum()
        self.summary_label.setText(
            f"Rijen: {len(filtered):,} | Brokers: {filtered['broker'].nunique():,} | "
            f"Currencies: {filtered['ib_currency'].nunique():,} | Fee: {total_fee:,.2f}"
        )
        self.status.setText("Read-only: database wordt alleen met SELECT gelezen.")

    def _resize_frozen_pivot_width(self, left: pd.DataFrame) -> None:
        if left.empty:
            self.pivot_left_view.setFixedWidth(120)
            return
        width = self.pivot_left_view.verticalHeader().width() + 4
        for column in range(len(left.columns)):
            width += self.pivot_left_view.columnWidth(column)
        self.pivot_left_view.setFixedWidth(min(max(width, 140), 520))

    def _apply_pivot_header_layout(self, pivot: pd.DataFrame) -> None:
        if pivot.empty:
            return
        max_lines = max(str(col).count(" | ") + 1 for col in pivot.columns)
        height = max(30, 18 * max_lines + 12)
        for view in (self.pivot_left_view, self.pivot_right_view):
            header = view.horizontalHeader()
            header.setDefaultAlignment(Qt.AlignCenter)
            header.setMinimumHeight(height)
            header.setFixedHeight(height)

    def export_current_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Exporteer pivot", "transactie_pivot.csv", "CSV (*.csv)")
        if not path:
            return
        self.full_pivot_df.to_csv(path, index=False, sep=";")
        self.status.setText(f"Pivot geexporteerd naar {path}")


def main() -> int:
    app = QApplication(sys.argv)
    window = TransactionAnalysisWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
