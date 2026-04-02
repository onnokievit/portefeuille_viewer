from __future__ import annotations

from datetime import date, timedelta

import polars as pl
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QDate, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.signals import signals


def _coerce_to_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            from datetime import datetime

            return datetime.strptime(text[:10], fmt).date()
        except Exception:
            continue
    return None


def _iter_daily_dates(start_date: date, end_date: date) -> list[date]:
    out: list[date] = []
    current = start_date
    while current <= end_date:
        out.append(current)
        current += timedelta(days=1)
    return out


def _iter_friday_dates(start_date: date, end_date: date) -> list[date]:
    out: list[date] = []
    current = start_date
    while current.weekday() != 4:
        current += timedelta(days=1)
    while current <= end_date:
        out.append(current)
        current += timedelta(days=7)
    return out


def _third_friday(year: int, month: int) -> date:
    first = date(year, month, 1)
    offset = (4 - first.weekday()) % 7
    return first + timedelta(days=offset + 14)


def _iter_third_friday_dates(start_date: date, end_date: date) -> list[date]:
    out: list[date] = []
    year = start_date.year
    month = start_date.month
    while (year, month) <= (end_date.year, end_date.month):
        candidate = _third_friday(year, month)
        if start_date <= candidate <= end_date:
            out.append(candidate)
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
    return out


def _schedule_dates(start_date: date, end_date: date, mode: str) -> list[date]:
    if end_date < start_date:
        start_date, end_date = end_date, start_date
    if mode == "daily":
        return _iter_daily_dates(start_date, end_date)
    if mode == "weekly_friday":
        return _iter_friday_dates(start_date, end_date)
    return _iter_third_friday_dates(start_date, end_date)


class MaandEindTableModel(QAbstractTableModel):
    def __init__(self, df: pl.DataFrame | None = None, parent=None) -> None:
        super().__init__(parent)
        self._df = pl.DataFrame({}) if df is None else df
        self._cols = list(self._df.columns)

    def set_df(self, df: pl.DataFrame | None) -> None:
        self.beginResetModel()
        self._df = pl.DataFrame({}) if df is None else df
        self._cols = list(self._df.columns)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if self._df.is_empty() else self._df.height

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if self._df.is_empty() else self._df.width

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self._cols[section] if 0 <= section < len(self._cols) else ""
        return str(section + 1)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or self._df.is_empty():
            return None
        row = index.row()
        col = index.column()
        col_name = self._cols[col]
        value = self._df[row, col]

        if role == Qt.DisplayRole:
            if value is None:
                return ""
            if col_name == "asset_rollup":
                return str(value)
            try:
                return f"{float(value):,.0f}".replace(",", ".")
            except Exception:
                return str(value)

        if role == Qt.UserRole:
            if value is None:
                return float("-inf") if col_name != "asset_rollup" else ""
            if col_name == "asset_rollup":
                return str(value)
            try:
                return float(value)
            except Exception:
                return str(value)

        if role == Qt.TextAlignmentRole:
            if col_name == "asset_rollup":
                return Qt.AlignLeft | Qt.AlignVCenter
            return Qt.AlignRight | Qt.AlignVCenter

        return None


class MaandEindTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._is_active = False
        self._loaded_once = False
        self._build_ui()
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(150)
        self._reload_timer.timeout.connect(self.reload_snapshot)
        self._watched_snapshot_keys = {"repository_snapshot_per_dag_asset_result_v2"}

        signals.snapshotUpdated.connect(self._on_snapshot_updated)
        signals.stateRebuildFinished.connect(self._on_state_rebuild_finished)
        signals.databaseChanged.connect(self._on_database_changed)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Start date"))
        self.start_date_edit = QDateEdit(self)
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDisplayFormat("dd-MM-yyyy")
        self.start_date_edit.setDate(QDate.currentDate().addMonths(-12))
        controls.addWidget(self.start_date_edit)

        controls.addWidget(QLabel("Eind date"))
        self.end_date_edit = QDateEdit(self)
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.setDisplayFormat("dd-MM-yyyy")
        self.end_date_edit.setDate(QDate.currentDate())
        controls.addWidget(self.end_date_edit)

        controls.addWidget(QLabel("Frequentie"))
        self.frequency_combo = QComboBox(self)
        self.frequency_combo.addItem("Elke dag", "daily")
        self.frequency_combo.addItem("Elke vrijdag", "weekly_friday")
        self.frequency_combo.addItem("3e vrijdag maand", "third_friday")
        self.frequency_combo.setCurrentIndex(2)
        controls.addWidget(self.frequency_combo)

        self.refresh_button = QPushButton("Refresh", self)
        self.refresh_button.clicked.connect(self.reload_snapshot)
        controls.addWidget(self.refresh_button)
        controls.addStretch(1)

        layout.addLayout(controls)

        self.info_label = QLabel("", self)
        layout.addWidget(self.info_label)

        self.table_view = QTableView(self)
        self.model = MaandEindTableModel(parent=self)
        self.table_view.setModel(self.model)
        self.table_view.setSortingEnabled(False)
        self.table_view.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table_view.horizontalHeader().setStretchLastSection(False)
        self.table_view.verticalHeader().setVisible(False)
        self.table_view.verticalHeader().setDefaultSectionSize(18)
        layout.addWidget(self.table_view)
        self.info_label.setText("Laadt bij openen van deze tab.")

    def set_active(self, active: bool) -> None:
        self._is_active = bool(active)
        if self._is_active and not self._loaded_once:
            self.reload_snapshot()

    def _on_snapshot_updated(self, snapshot_key: str) -> None:
        if self._is_active and snapshot_key in self._watched_snapshot_keys:
            self._reload_timer.start()

    def _on_state_rebuild_finished(self, payload: dict | None) -> None:
        if self._is_active and (payload or {}).get("status") == "ok":
            self._reload_timer.start()

    def _on_database_changed(self, _db_name: str) -> None:
        self._loaded_once = False
        if self._is_active:
            self._reload_timer.start()

    def _current_start_date(self) -> date:
        return self.start_date_edit.date().toPython()

    def _current_end_date(self) -> date:
        return self.end_date_edit.date().toPython()

    def _current_mode(self) -> str:
        return str(self.frequency_combo.currentData() or "third_friday")

    def _build_matrix(self, df_source: pl.DataFrame, schedule: list[date]) -> pl.DataFrame:
        if not schedule:
            return pl.DataFrame({"asset_rollup": []})

        if df_source is None or df_source.is_empty():
            return pl.DataFrame({"asset_rollup": []})

        work = df_source
        if "datum" not in work.columns or "asset_rollup" not in work.columns or "totaal_v2" not in work.columns:
            return pl.DataFrame({"asset_rollup": []})

        work = (
            work.with_columns(
                [
                    pl.col("asset_rollup").cast(pl.Utf8).str.strip_chars().str.to_uppercase().alias("asset_rollup"),
                    pl.col("totaal_v2").cast(pl.Float64, strict=False).alias("waarde"),
                ]
            )
            .filter(pl.col("datum").is_not_null() & (pl.col("datum") <= schedule[-1]))
            .select(["datum", "asset_rollup", "waarde"])
            .sort(["asset_rollup", "datum"])
        )

        if work.is_empty():
            return pl.DataFrame({"asset_rollup": []})

        assets = (
            work.select("asset_rollup")
            .unique()
            .sort("asset_rollup")
            .with_columns(pl.lit(1).alias("_k"))
        )
        schedule_df = (
            pl.DataFrame({"datum": schedule})
            .with_columns(pl.lit(1).alias("_k"))
            .join(assets, on="_k", how="inner")
            .drop("_k")
            .with_columns(
                [
                    pl.lit(None).cast(pl.Float64).alias("waarde"),
                    pl.lit(1).alias("_is_schedule"),
                ]
            )
        )
        source_df = work.with_columns(pl.lit(0).alias("_is_schedule"))
        combined = (
            pl.concat([source_df, schedule_df], how="diagonal_relaxed")
            .sort(["asset_rollup", "datum", "_is_schedule"])
            .with_columns(pl.col("waarde").fill_null(strategy="forward").over("asset_rollup"))
            .filter(pl.col("_is_schedule") == 1)
            .filter(pl.col("datum").is_in(schedule))
            .sort(["asset_rollup", "datum"])
        )

        if combined.is_empty():
            return pl.DataFrame({"asset_rollup": []})

        pivot = combined.pivot(index="asset_rollup", on="datum", values="waarde")
        rename_map = {
            col: _coerce_to_date(col).strftime("%d-%m-%y")
            for col in pivot.columns
            if col != "asset_rollup" and _coerce_to_date(col) is not None
        }
        if rename_map:
            pivot = pivot.rename(rename_map)
        return pivot.sort("asset_rollup")

    def reload_snapshot(self) -> None:
        if not self._is_active:
            return
        start_date = self._current_start_date()
        end_date = self._current_end_date()
        mode = self._current_mode()
        schedule = _schedule_dates(start_date, end_date, mode)
        df_source = getattr(SNAPSHOT_STORE, "repository_snapshot_per_dag_asset_result_v2", None)
        matrix = self._build_matrix(df_source, schedule)
        self.model.set_df(matrix)
        self._loaded_once = True
        header = self.table_view.horizontalHeader()
        if matrix.width > 0:
            header.setSectionResizeMode(0, QHeaderView.Stretch)
        for idx in range(1, matrix.width):
            header.setSectionResizeMode(idx, QHeaderView.Interactive)
            self.table_view.setColumnWidth(idx, 82)
        period_text = {
            "daily": "elke dag",
            "weekly_friday": "elke vrijdag",
            "third_friday": "3e vrijdag van de maand",
        }.get(mode, mode)
        self.info_label.setText(
            f"{matrix.height} assets, {max(matrix.width - 1, 0)} meetmomenten, bron: per_dag_asset_result_v2.totaal_v2 ({period_text})"
        )
