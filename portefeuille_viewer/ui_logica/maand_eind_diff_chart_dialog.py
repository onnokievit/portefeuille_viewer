from __future__ import annotations

import contextlib
import json
from datetime import date

from PySide6.QtCore import QObject, Qt, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout

from portefeuille_viewer.config import get_settings
from portefeuille_viewer.signals import signals
from portefeuille_viewer.ui_logica.maand_eind_chart_dialog import (
    _append_today_if_needed,
    _coerce_to_date,
    _schedule_dates,
    MaandEindChartDialog,
)

try:
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:  # pragma: no cover
    QWebChannel = None
    QWebEngineView = None


class MaandEindDiffChartDialog(MaandEindChartDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Maandeind Verschilwaarden Chart")

    def _restore_saved_state(self) -> None:
        with contextlib.suppress(Exception):
            state = get_settings().get_month_end_diff_chart_state()
            if not state:
                return
            start_date = _coerce_to_date(state.get("start_date"))
            if start_date is not None:
                self._start_date = start_date
            self._end_date = date.today()
            frequency = str(state.get("frequency") or "").strip()
            if frequency in {"daily", "weekly_friday", "third_friday", "month_end", "quarter_end", "year_end"}:
                self._frequency = frequency
            sectors = state.get("selected_sectors")
            regios = state.get("selected_regios")
            value_grows = state.get("selected_value_grows")
            self._selected_sectors = {str(v).strip() for v in (sectors or []) if str(v).strip()} or None
            self._selected_regios = {str(v).strip() for v in (regios or []) if str(v).strip()} or None
            self._selected_value_grows = {str(v).strip() for v in (value_grows or []) if str(v).strip()} or None
            self._split_sector = bool(state.get("split_sector", False))
            self._split_regio = bool(state.get("split_regio", False))
            self._split_value_grow = bool(state.get("split_value_grow", False))
            self._restored_state = True

    def _save_state(self) -> None:
        with contextlib.suppress(Exception):
            get_settings().set_month_end_diff_chart_state(
                {
                    "start_date": self._start_date.isoformat(),
                    "frequency": self._frequency,
                    "selected_sectors": sorted(self._selected_sectors) if self._selected_sectors else [],
                    "selected_regios": sorted(self._selected_regios) if self._selected_regios else [],
                    "selected_value_grows": sorted(self._selected_value_grows) if self._selected_value_grows else [],
                    "split_sector": bool(self._split_sector),
                    "split_regio": bool(self._split_regio),
                    "split_value_grow": bool(self._split_value_grow),
                }
            )

    def _restore_geometry(self) -> None:
        geo = get_settings().get_month_end_diff_chart_window_geometry()
        if geo:
            screens = QGuiApplication.screens()
            on_screen = any(
                s.geometry().contains(geo["x"] + 50, geo["y"] + 50)
                for s in screens
            )
            if on_screen:
                self.setGeometry(geo["x"], geo["y"], geo["w"], geo["h"])
                return
        self.resize(1380, 860)

    def _save_geometry(self) -> None:
        g = self.geometry()
        with contextlib.suppress(Exception):
            get_settings().set_month_end_diff_chart_window_geometry(g.x(), g.y(), g.width(), g.height())

    def _build_series_payload(self) -> dict[str, object]:
        schedule_probe = _append_today_if_needed([self._end_date], self._end_date)
        work = self._filtered_work_df(schedule_probe)
        min_visible_date = self._start_date
        full_series_start = self._start_date
        if not work.is_empty() and "datum" in work.columns:
            with contextlib.suppress(Exception):
                earliest_values = [value for value in work.get_column("datum").drop_nulls().to_list() if value is not None]
                if earliest_values:
                    full_series_start = min(earliest_values)

        original_start_date = self._start_date
        try:
            self._start_date = full_series_start
            base = super()._build_series_payload()
        finally:
            self._start_date = original_start_date

        def _to_diff_points(points: list[dict]) -> tuple[list[dict[str, object]], float | None]:
            diff_points: list[dict[str, object]] = []
            prev_val = None
            latest_value = None
            for point in points:
                cur = point.get("value")
                if cur is None:
                    diff_val = None
                elif prev_val is None:
                    diff_val = float(cur)
                else:
                    diff_val = float(cur) - float(prev_val)
                if diff_val is not None:
                    latest_value = diff_val
                diff_points.append(
                    {
                        "date": point.get("date"),
                        "label": point.get("label"),
                        "value": diff_val,
                    }
                )
                if cur is not None:
                    prev_val = cur
            return diff_points, latest_value

        def _is_visible(point: dict[str, object]) -> bool:
            point_date = _coerce_to_date(point.get("date"))
            return point_date is not None and point_date >= min_visible_date

        points = base.get("points") or []
        all_diff_points, _ = _to_diff_points(points)
        diff_points = [point for point in all_diff_points if _is_visible(point)]
        latest_value = next((point.get("value") for point in reversed(diff_points) if point.get("value") is not None), None)
        split_series = base.get("split_series") or []
        diff_split_series: list[dict[str, object]] = []
        for series in split_series:
            all_series_points, _ = _to_diff_points(series.get("points") or [])
            series_points = [point for point in all_series_points if _is_visible(point)]
            diff_split_series.append(
                {
                    "name": series.get("name"),
                    "label": series.get("label"),
                    "dash": series.get("dash"),
                    "points": series_points,
                }
            )

        base["points"] = diff_points
        base["split_series"] = diff_split_series
        meta = dict(base.get("meta") or {})
        meta["latest_value"] = latest_value
        meta["moment_count"] = len(diff_points)
        base["meta"] = meta
        return base

    def _html_template(self) -> str:
        html = super()._html_template()
        html = html.replace("Eindwaarde", "Verschilwaarde")
        html = html.replace("window.renderSeries = function(payload){", "window.renderSeries = function(payload){\n        window.__chartMode = 'bar';")
        html = html.replace("function drawChart(points, splitSeries){", "function drawChart(points, splitSeries){\n        const chartMode = window.__chartMode || 'line';")
        html = html.replace(
            """        const path = document.createElementNS(ns, "path");
        const d = valid.map((p, idx) => `${idx === 0 ? "M" : "L"} ${xAt(idx)} ${yAt(p.value)}`).join(" ");
        path.setAttribute("d", d);
        path.setAttribute("fill", "none");
        path.setAttribute("stroke", "#8c7552");
        path.setAttribute("stroke-width", "2");
        path.setAttribute("stroke-linejoin", "round");
        path.setAttribute("stroke-linecap", "round");
        svg.appendChild(path);""",
            """        if(chartMode === 'bar'){
          const zeroY = yAt(0);
          const barSlot = valid.length > 1 ? innerW / valid.length : innerW * 0.45;
          const barWidth = Math.max(Math.min(barSlot * 0.72, 28), 6);
          valid.forEach((p, idx) => {
            const x = xAt(idx) - (barWidth / 2);
            const y = yAt(p.value);
            const rect = document.createElementNS(ns, "rect");
            rect.setAttribute("x", String(x));
            rect.setAttribute("y", String(Math.min(y, zeroY)));
            rect.setAttribute("width", String(barWidth));
            rect.setAttribute("height", String(Math.max(Math.abs(zeroY - y), 1)));
            rect.setAttribute("rx", "2");
            rect.setAttribute("fill", p.value >= 0 ? "#8c7552" : "#c07b63");
            rect.setAttribute("opacity", "0.9");
            svg.appendChild(rect);
          });
        } else {
          const path = document.createElementNS(ns, "path");
          const d = valid.map((p, idx) => `${idx === 0 ? "M" : "L"} ${xAt(idx)} ${yAt(p.value)}`).join(" ");
          path.setAttribute("d", d);
          path.setAttribute("fill", "none");
          path.setAttribute("stroke", "#8c7552");
          path.setAttribute("stroke-width", "2");
          path.setAttribute("stroke-linejoin", "round");
          path.setAttribute("stroke-linecap", "round");
          svg.appendChild(path);
        }""",
        )
        return html


_MONTH_END_DIFF_CHART_DIALOG_INSTANCE: "MaandEindDiffChartDialog | None" = None


def open_month_end_diff_chart_dialog(
    start_date: date,
    end_date: date,
    frequency: str,
    filter_sector: str = "",
    filter_regio: str = "",
    filter_value_grow: str = "",
) -> None:
    global _MONTH_END_DIFF_CHART_DIALOG_INSTANCE
    if _MONTH_END_DIFF_CHART_DIALOG_INSTANCE is not None:
        try:
            _MONTH_END_DIFF_CHART_DIALOG_INSTANCE.isVisible()
        except RuntimeError:
            _MONTH_END_DIFF_CHART_DIALOG_INSTANCE = None
    if _MONTH_END_DIFF_CHART_DIALOG_INSTANCE is None:
        _MONTH_END_DIFF_CHART_DIALOG_INSTANCE = MaandEindDiffChartDialog(None)
        _MONTH_END_DIFF_CHART_DIALOG_INSTANCE.sync_from_maand_eind(
            start_date,
            end_date,
            frequency,
            filter_sector,
            filter_regio,
            filter_value_grow,
        )
    dlg = _MONTH_END_DIFF_CHART_DIALOG_INSTANCE
    if dlg.windowState() & Qt.WindowMinimized:
        dlg.setWindowState(dlg.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
        dlg.showNormal()
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()


def close_month_end_diff_chart_dialog() -> None:
    global _MONTH_END_DIFF_CHART_DIALOG_INSTANCE
    if _MONTH_END_DIFF_CHART_DIALOG_INSTANCE is not None:
        try:
            _MONTH_END_DIFF_CHART_DIALOG_INSTANCE._force_close = True
            _MONTH_END_DIFF_CHART_DIALOG_INSTANCE.close()
        except RuntimeError:
            pass
        _MONTH_END_DIFF_CHART_DIALOG_INSTANCE = None
