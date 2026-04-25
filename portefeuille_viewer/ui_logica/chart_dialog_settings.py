from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
)


def make_start_date_controls(parent, settings, chart_id: str, on_changed):
    checkbox = QCheckBox("Startdatum", parent)
    checkbox.setChecked(bool(settings.get_chart_start_date(chart_id)))
    date_edit = QDateEdit(parent)
    date_edit.setCalendarPopup(True)
    date_edit.setDisplayFormat("dd-MM-yyyy")
    date_edit.setMinimumDate(QDate(2000, 1, 1))
    date_edit.setMaximumDate(QDate(2099, 12, 31))
    date_edit.setDate(_load_qdate(settings.get_chart_start_date(chart_id)))
    date_edit.setEnabled(checkbox.isChecked())
    clear_button = QPushButton("Geen start", parent)

    def current_text() -> str:
        if not checkbox.isChecked():
            return ""
        return date_edit.date().toString("yyyy-MM-dd")

    def apply_change() -> None:
        date_edit.setEnabled(checkbox.isChecked())
        settings.set_chart_start_date(chart_id, current_text())
        on_changed()

    checkbox.toggled.connect(lambda _checked: apply_change())
    date_edit.dateChanged.connect(lambda _date: apply_change())
    clear_button.clicked.connect(lambda: checkbox.setChecked(False))
    return checkbox, date_edit, clear_button


def _load_qdate(raw: str) -> QDate:
    if raw:
        try:
            year, month, day = [int(part) for part in raw.split("-")]
            return QDate(year, month, day)
        except Exception:
            pass
    return QDate(2021, 1, 1)


def create_line_settings_table(parent) -> QTableWidget:
    table = QTableWidget(parent)
    table.setColumnCount(3)
    table.setHorizontalHeaderLabels(["Lijn", "px", "Type"])
    table.setEditTriggers(QTableWidget.NoEditTriggers)
    table.setSelectionMode(QAbstractItemView.NoSelection)
    table.setMaximumHeight(125)
    return table


def populate_line_settings_table(
    table: QTableWidget,
    parent,
    settings,
    chart_id: str,
    series: list[dict],
    on_changed,
) -> None:
    table.setUpdatesEnabled(False)
    table.blockSignals(True)
    try:
        table.clearContents()
        table.setRowCount(len(series or []))
        line_widths = settings.get_chart_line_widths_for_chart(chart_id)
        line_styles = settings.get_chart_line_styles_for_chart(chart_id)
        default_width = settings.get_chart_line_width_px()
        for row_idx, item in enumerate(series or []):
            series_id = str(item.get("id") or "")
            label = str(item.get("label") or series_id)
            label_item = QTableWidgetItem(label)
            label_item.setData(Qt.UserRole, series_id)
            table.setItem(row_idx, 0, label_item)

            spin = QDoubleSpinBox(parent)
            spin.setRange(0.5, 8.0)
            spin.setDecimals(1)
            spin.setSingleStep(0.1)
            spin.setSuffix(" px")
            spin.setValue(float(line_widths.get(series_id, default_width)))
            spin.valueChanged.connect(
                lambda value, sid=series_id: _set_width(settings, chart_id, sid, value, on_changed)
            )
            table.setCellWidget(row_idx, 1, spin)

            combo = QComboBox(parent)
            combo.addItem("Gestreept", "dashed")
            combo.addItem("Doorlopend", "solid")
            style = line_styles.get(series_id, str(item.get("default_style") or "solid"))
            combo.setCurrentIndex(max(0, combo.findData(style)))
            combo.currentIndexChanged.connect(
                lambda _idx, sid=series_id, widget=combo: _set_style(
                    settings,
                    chart_id,
                    sid,
                    str(widget.currentData() or "solid"),
                    on_changed,
                )
            )
            table.setCellWidget(row_idx, 2, combo)
    finally:
        table.blockSignals(False)
        table.setUpdatesEnabled(True)
    table.resizeColumnsToContents()


def _set_width(settings, chart_id: str, series_id: str, value: float, on_changed) -> None:
    settings.set_chart_line_width_for_series(chart_id, series_id, value)
    on_changed()


def _set_style(settings, chart_id: str, series_id: str, style: str, on_changed) -> None:
    settings.set_chart_line_style_for_series(chart_id, series_id, style)
    on_changed()


def filter_payload_by_chart_start_date(payload: dict, settings, chart_id: str) -> dict:
    start_date = settings.get_chart_start_date(chart_id)
    if not start_date:
        return dict(payload or {})
    filtered = dict(payload or {})
    points = [
        point for point in filtered.get("points", [])
        if str(point.get("date") or "") >= start_date
    ]
    filtered["points"] = points
    stats = dict(filtered.get("stats") or {})
    stats["start_date"] = min((point.get("date") for point in points), default=None)
    stats["end_date"] = max((point.get("date") for point in points), default=None)
    stats["points"] = len(points)
    filtered["stats"] = stats
    return filtered


def inject_line_settings(payload: dict, settings, chart_id: str) -> dict:
    enriched = dict(payload or {})
    enriched["line_width"] = settings.get_chart_line_width_px()
    enriched["line_widths"] = settings.get_chart_line_widths_for_chart(chart_id)
    enriched["line_styles"] = settings.get_chart_line_styles_for_chart(chart_id)
    return enriched


def cash_series_definitions(brokers: list[str], total_id: str, total_label: str, broker_label_prefix: str, default_style: str) -> list[dict]:
    series = [
        {"id": total_id, "label": total_label, "default_style": default_style},
    ]
    for broker in brokers or []:
        series.append(
            {
                "id": f"broker:{broker}",
                "label": f"{broker_label_prefix} {broker}".strip(),
                "default_style": default_style,
            }
        )
    return series
