from __future__ import annotations

import json
from collections import OrderedDict
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from PySide6.QtCore import QObject, Slot
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from portefeuille_viewer.config import get_settings
from portefeuille_viewer.data.account_daily_balance_repository import (
    list_account_daily_balances,
    upsert_account_daily_balance,
)
from portefeuille_viewer.services.cash_management_chart_service import (
    PREFERRED_BROKER_ORDER,
    build_cash_management_chart_payload,
)
from portefeuille_viewer.services.cash_management_result_chart_service import (
    build_cash_management_result_chart_payload,
)
from portefeuille_viewer.services.year_result_vs_indices_service import (
    build_year_result_vs_indices_payload,
    clear_year_result_vs_indices_cache,
    list_index_asset_rollups,
)
from portefeuille_viewer.signals import signals
from portefeuille_viewer.ui_logica.chart_dialog_settings import (
    cash_series_definitions,
    inject_line_settings,
)
from portefeuille_viewer.ui_logica.cash_management_entries_dialog import (
    open_cash_management_entries_dialog,
)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:  # pragma: no cover
    QWebEngineView = None

try:
    from PySide6.QtWebChannel import QWebChannel
except Exception:  # pragma: no cover
    QWebChannel = None


CHART_VALUE = "cash_management_value"
CHART_RESULT = "cash_management_result"
CHART_YEAR_RESULT = "cash_management_year_result"
CHART_YEAR_PERCENT = "cash_management_year_result_percent"
CHART_VS_INDICES = "year_result_vs_indices"

PIVOT_BROKERS = ["degiro", "interactive", "lynx"]
PORTFOLIO_OPTIONS = [
    {"id": "total", "label": "Totaal"},
    {"id": "degiro", "label": "Degiro"},
    {"id": "interactive", "label": "Interactive"},
    {"id": "lynx", "label": "Lynx"},
]


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _iso_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    if len(text) >= 10:
        return text[:10]
    return text


def _date_to_nl(value: str) -> str:
    text = str(value or "").strip()
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return f"{text[8:10]}-{text[5:7]}-{text[0:4]}"
    return text


def _filter_points(points: list[dict], start_date: str) -> list[dict]:
    start = str(start_date or "").strip()
    if not start:
        return list(points or [])
    return [point for point in points or [] if str(point.get("date") or "") >= start]


def _sorted_brokers(brokers: list[str]) -> list[str]:
    preferred = {name: idx for idx, name in enumerate(PREFERRED_BROKER_ORDER)}
    return sorted(
        [str(value or "").strip().lower() for value in brokers or [] if str(value or "").strip()],
        key=lambda broker: (0 if broker in preferred else 1, preferred.get(broker, 999), broker),
    )


def _points_by_date(points: list[dict]) -> OrderedDict[str, list[dict]]:
    by_date: OrderedDict[str, list[dict]] = OrderedDict()
    for point in sorted(points or [], key=lambda item: (str(item.get("date") or ""), str(item.get("broker") or ""))):
        date_value = str(point.get("date") or "")
        if not date_value:
            continue
        by_date.setdefault(date_value, []).append(point)
    return by_date


def _series_from_cash_points(
    points: list[dict],
    brokers: list[str],
    total_key: str,
    broker_key: str,
    total_id: str,
    total_label: str,
    broker_label_prefix: str,
    default_style: str,
) -> list[dict]:
    by_date = _points_by_date(points)
    total_points = []
    for date_value, rows in by_date.items():
        value = next((row.get(total_key) for row in rows if row.get(total_key) is not None), None)
        if value is not None:
            total_points.append({"date": date_value, "y": float(value)})
    series = [
        {"id": total_id, "label": total_label, "default_style": default_style, "points": total_points},
    ]

    for broker in brokers:
        broker_points = []
        for date_value, rows in by_date.items():
            row = next((item for item in rows if str(item.get("broker") or "").lower() == broker), None)
            if row is None or row.get(broker_key) is None:
                continue
            broker_points.append({"date": date_value, "y": float(row[broker_key])})
        series.append(
            {
                "id": f"broker:{broker}",
                "label": f"{broker_label_prefix} {broker}".strip(),
                "default_style": default_style,
                "points": broker_points,
            }
        )
    return series


def _year_result(points: list[dict]) -> list[dict]:
    bases: dict[str, float] = {}
    out = []
    for point in points:
        date_value = str(point.get("date") or "")
        if len(date_value) < 4 or point.get("y") is None:
            continue
        year = date_value[:4]
        value = float(point["y"])
        bases.setdefault(year, value)
        out.append({"date": date_value, "y": value - bases[year]})
    return out


def _year_percent(raw: list[dict], profit_key: str, capital_key: str, mode: str) -> list[dict]:
    states: dict[str, dict[str, float]] = {}
    out = []
    for point in raw:
        date_value = str(point.get("date") or "")
        if len(date_value) < 4:
            continue
        profit = point.get(profit_key)
        capital = point.get(capital_key)
        if profit is None or capital is None:
            continue
        profit = float(profit)
        capital = float(capital)
        if abs(capital) < 1e-12:
            continue
        year = date_value[:4]
        states.setdefault(year, {"base_profit": profit, "base_capital": capital, "capital_sum": 0.0, "capital_count": 0.0})
        state = states[year]
        state["capital_sum"] += capital
        state["capital_count"] += 1.0
        denominator = state["base_capital"] if mode == "start" else state["capital_sum"] / state["capital_count"]
        if abs(denominator) < 1e-12:
            continue
        out.append({"date": date_value, "y": ((profit - state["base_profit"]) / denominator) * 100.0})
    return out


def _year_percent_series(points: list[dict], brokers: list[str], mode: str) -> list[dict]:
    by_date = _points_by_date(points)
    total_raw = []
    for date_value, rows in by_date.items():
        total_raw.append(
            {
                "date": date_value,
                "profit": next((row.get("total_profit") for row in rows if row.get("total_profit") is not None), None),
                "capital": next((row.get("total_value") for row in rows if row.get("total_value") is not None), None),
            }
        )
    series = [
        {
            "id": "total_year_percent",
            "label": "% pj totaal",
            "default_style": "dashed",
            "points": _year_percent(total_raw, "profit", "capital", mode),
        }
    ]
    for broker in brokers:
        raw = []
        for date_value, rows in by_date.items():
            row = next((item for item in rows if str(item.get("broker") or "").lower() == broker), None)
            if not row:
                continue
            raw.append({"date": date_value, "profit": row.get("profit"), "capital": row.get("ending_balance")})
        series.append(
            {
                "id": f"broker:{broker}",
                "label": f"% pj {broker}",
                "default_style": "dashed",
                "points": _year_percent(raw, "profit", "capital", mode),
            }
        )
    return series


def _build_pivot_rows() -> list[dict]:
    rows = list_account_daily_balances(limit=None)
    cells: dict[tuple[str, str], dict] = {}
    dates = set()
    for row in rows:
        broker = str(row.get("broker") or "").strip().lower()
        if broker not in PIVOT_BROKERS:
            continue
        date_value = _iso_date(row.get("datum"))
        if not date_value:
            continue
        dates.add(date_value)
        key = (date_value, broker)
        if key not in cells:
            cells[key] = {
                "id": row.get("id"),
                "value": None if row.get("ending_balance") is None else float(row["ending_balance"]),
                "comment": row.get("comment_text") or "",
            }
    out = []
    for date_value in sorted(dates, reverse=True):
        item = {"date": date_value, "date_nl": _date_to_nl(date_value), "brokers": {}, "total": 0.0}
        total = 0.0
        for broker in PIVOT_BROKERS:
            cell = cells.get((date_value, broker))
            item["brokers"][broker] = cell
            if cell and cell.get("value") is not None:
                total += float(cell["value"])
        item["total"] = total
        out.append(item)
    return out


def _build_pivot_summary(pivot_rows: list[dict], result_points: list[dict]) -> dict:
    columns = list(PIVOT_BROKERS) + ["total"]
    max_balance = {
        column: {"value": None, "date": "", "date_nl": ""}
        for column in columns
    }
    max_profit = {
        column: {"value": None, "date": "", "date_nl": ""}
        for column in columns
    }
    current_profit = {
        column: {"value": None, "date": "", "date_nl": ""}
        for column in columns
    }
    current_balance = {
        column: {"value": None, "date": "", "date_nl": ""}
        for column in columns
    }
    invested_by_column_date: dict[str, dict[str, float]] = {column: {} for column in columns}

    for row in pivot_rows or []:
        date_value = str(row.get("date") or "")
        date_nl = str(row.get("date_nl") or _date_to_nl(date_value))
        for broker in PIVOT_BROKERS:
            cell = (row.get("brokers") or {}).get(broker)
            value = None if not cell else cell.get("value")
            if value is None:
                continue
            current = max_balance[broker].get("value")
            if current is None or float(value) > float(current):
                max_balance[broker] = {"value": float(value), "date": date_value, "date_nl": date_nl}
            if not current_balance[broker].get("date") or date_value >= str(current_balance[broker].get("date") or ""):
                current_balance[broker] = {"value": float(value), "date": date_value, "date_nl": date_nl}
        total = row.get("total")
        if total is not None:
            current = max_balance["total"].get("value")
            if current is None or float(total) > float(current):
                max_balance["total"] = {"value": float(total), "date": date_value, "date_nl": date_nl}
            if not current_balance["total"].get("date") or date_value >= str(current_balance["total"].get("date") or ""):
                current_balance["total"] = {"value": float(total), "date": date_value, "date_nl": date_nl}

    seen_total_dates = set()
    for point in result_points or []:
        date_value = str(point.get("date") or "")
        if not date_value:
            continue
        date_nl = _date_to_nl(date_value)
        broker = str(point.get("broker") or "").strip().lower()
        if broker in PIVOT_BROKERS and point.get("invested_cumulative") is not None:
            invested_by_column_date[broker][date_value] = float(point["invested_cumulative"])
        if broker in PIVOT_BROKERS and point.get("profit") is not None:
            value = float(point["profit"])
            current = max_profit[broker].get("value")
            if current is None or value > float(current):
                max_profit[broker] = {"value": value, "date": date_value, "date_nl": date_nl}
            if not current_profit[broker].get("date") or date_value >= str(current_profit[broker].get("date") or ""):
                current_profit[broker] = {"value": value, "date": date_value, "date_nl": date_nl}
        if date_value not in seen_total_dates and point.get("total_profit") is not None:
            seen_total_dates.add(date_value)
            if point.get("total_invested") is not None:
                invested_by_column_date["total"][date_value] = float(point["total_invested"])
            value = float(point["total_profit"])
            current = max_profit["total"].get("value")
            if current is None or value > float(current):
                max_profit["total"] = {"value": value, "date": date_value, "date_nl": date_nl}
            if not current_profit["total"].get("date") or date_value >= str(current_profit["total"].get("date") or ""):
                current_profit["total"] = {"value": value, "date": date_value, "date_nl": date_nl}

    adjusted_current_balance = {}
    balance_drawdown = {}
    for column in columns:
        current_value = current_balance[column].get("value")
        current_date = str(current_balance[column].get("date") or "")
        peak_value = max_balance[column].get("value")
        peak_date = str(max_balance[column].get("date") or "")
        current_invested = invested_by_column_date[column].get(current_date)
        peak_invested = invested_by_column_date[column].get(peak_date)
        if current_value is None or current_invested is None or peak_invested is None:
            adjusted_current_balance[column] = {"value": None, "date": "", "date_nl": ""}
            balance_drawdown[column] = {"value": None, "date": "", "date_nl": ""}
            continue
        adjusted_value = float(current_value) - (float(current_invested) - float(peak_invested))
        adjusted_current_balance[column] = {
            "value": adjusted_value,
            "date": current_date,
            "date_nl": current_balance[column].get("date_nl") or "",
        }
        if peak_value in (None, 0):
            balance_drawdown[column] = {"value": None, "date": "", "date_nl": ""}
            continue
        balance_drawdown[column] = {
            "value": -1.0 * (1.0 - (adjusted_value / float(peak_value))) * 100.0,
            "date": current_date,
            "date_nl": current_balance[column].get("date_nl") or "",
        }

    profit_drawdown = {}
    for column in columns:
        current = current_profit[column].get("value")
        peak = max_profit[column].get("value")
        if current is None or peak in (None, 0):
            profit_drawdown[column] = {"value": None, "date": "", "date_nl": ""}
            continue
        profit_drawdown[column] = {
            "value": -1.0 * (1.0 - (float(current) / float(peak))) * 100.0,
            "date": current_profit[column].get("date") or "",
            "date_nl": current_profit[column].get("date_nl") or "",
        }

    return {
        "columns": columns,
        "adjusted_current_balance": adjusted_current_balance,
        "balance_drawdown": balance_drawdown,
        "max_balance": max_balance,
        "current_profit": current_profit,
        "max_profit": max_profit,
        "profit_drawdown": profit_drawdown,
    }


class _CashDashboardBridge(QObject):
    def __init__(self, tab: "CashManagementWebTab"):
        super().__init__(tab)
        self._tab = tab

    @Slot()
    def ready(self):
        self._tab.publish_payload()

    @Slot()
    def refresh(self):
        self._tab.publish_payload(force_reload=True)

    @Slot()
    def openCashMutaties(self):
        open_cash_management_entries_dialog(self._tab)

    @Slot(str)
    def saveDailyBalance(self, payload: str):
        try:
            data = json.loads(payload or "{}")
            upsert_account_daily_balance(
                {
                    "id": data.get("id") or None,
                    "datum": data.get("datum"),
                    "broker": data.get("broker"),
                    "ending_balance": data.get("ending_balance"),
                    "currency_code": "EUR",
                    "source_name": "manual",
                    "comment_text": data.get("comment_text") or "",
                }
            )
            self._tab.publish_payload(force_reload=True, status="Opgeslagen.")
        except Exception as exc:
            self._tab.publish_status(f"Fout bij opslaan: {exc}")

    @Slot(str, str, float, str)
    def setLineSetting(self, chart_id: str, series_id: str, width: float, style: str):
        settings = get_settings()
        settings.set_chart_line_width_for_series(chart_id, series_id, width)
        settings.set_chart_line_style_for_series(chart_id, series_id, style)
        self._tab.publish_payload(reuse_cache=True)

    @Slot(str, str)
    def setVisibleSeries(self, chart_id: str, payload: str):
        try:
            series_ids = json.loads(payload or "[]")
        except Exception:
            series_ids = []
        if not isinstance(series_ids, list):
            series_ids = []
        get_settings().set_chart_visible_series_for_chart(chart_id, [str(item) for item in series_ids])
        self._tab.publish_payload(reuse_cache=True)

    @Slot(str)
    def setStartDate(self, value: str):
        get_settings().set_cash_dashboard_start_date(value)
        self._tab.publish_payload(force_reload=True)

    @Slot(str)
    def setPanelState(self, payload: str):
        try:
            state = json.loads(payload or "{}")
        except Exception:
            state = {}
        if isinstance(state, dict):
            get_settings().set_cash_dashboard_panel_state(state)

    @Slot(str)
    def setYearPercentMode(self, mode: str):
        get_settings().set_cash_dashboard_year_percent_mode(mode)
        self._tab.publish_payload(force_reload=True)

    @Slot(int)
    def setChartHeight(self, value: int):
        get_settings().set_cash_dashboard_chart_height_px(value)
        self._tab.publish_payload(reuse_cache=True)

    @Slot(str)
    def setVsIndicesSelection(self, payload: str):
        try:
            data = json.loads(payload or "{}")
        except Exception:
            return
        settings = get_settings()
        settings.set_year_result_vs_indices_selected_portfolio(data.get("portfolio") or [])
        settings.set_year_result_vs_indices_selected_indices(data.get("indices") or [])
        self._tab.publish_payload(reuse_cache=True)


class CashManagementWebTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._js_ready = False
        self._is_active = False
        self._payload_cache: dict | None = None
        self._needs_force_reload = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if QWebEngineView is None:
            layout.addWidget(QLabel("QtWebEngine niet beschikbaar in deze runtime.", self))
            return

        self.web = QWebEngineView(self)
        layout.addWidget(self.web, 1)
        self.bridge = _CashDashboardBridge(self)
        self.channel = None
        if QWebChannel is not None:
            self.channel = QWebChannel(self.web.page())
            self.channel.registerObject("cashBridge", self.bridge)
            self.web.page().setWebChannel(self.channel)
        self.web.loadFinished.connect(self._on_load_finished)
        self.web.setHtml(self._html())
        signals.databaseChanged.connect(self._on_database_changed)

    def set_active(self, active: bool):
        self._is_active = bool(active)
        if self._is_active and self._js_ready:
            self.publish_payload(force_reload=self._needs_force_reload)

    def _on_load_finished(self, ok: bool):
        self._js_ready = bool(ok)
        if ok and self._is_active:
            self.publish_payload(force_reload=self._needs_force_reload)

    def _on_database_changed(self, _db_name: str):
        self._payload_cache = None
        self._needs_force_reload = True
        clear_year_result_vs_indices_cache()
        if self._is_active and self._js_ready:
            self.publish_payload(force_reload=True, status="Database gewisseld; data herladen.")

    def publish_status(self, status: str):
        if not self._js_ready:
            return
        self.web.page().runJavaScript(f"window.setStatus({json.dumps(str(status))});")

    def publish_payload(self, force_reload: bool = False, status: str = "", reuse_cache: bool = False):
        if not self._is_active:
            return
        force_reload = bool(force_reload or self._needs_force_reload)
        if reuse_cache and self._payload_cache is not None:
            payload = self._refresh_display_settings(dict(self._payload_cache))
        elif force_reload or self._payload_cache is None:
            payload = self._build_payload(force_reload=force_reload)
        else:
            payload = self._refresh_display_settings(dict(self._payload_cache))
        if status:
            payload["status"] = status
        self._payload_cache = payload
        if not self._js_ready:
            return
        self._needs_force_reload = False
        raw = json.dumps(payload, ensure_ascii=False, default=_json_default)
        self.web.page().runJavaScript(f"window.renderCashDashboard({raw});")

    def _refresh_display_settings(self, payload: dict) -> dict:
        settings = get_settings()
        payload["start_date"] = settings.get_cash_dashboard_start_date()
        payload["panel_state"] = settings.get_cash_dashboard_panel_state()
        payload["year_percent_mode"] = settings.get_cash_dashboard_year_percent_mode()
        payload["chart_height"] = settings.get_cash_dashboard_chart_height_px()
        payload.setdefault("vs_indices", {})["selected_portfolio"] = settings.get_year_result_vs_indices_selected_portfolio()
        payload.setdefault("vs_indices", {})["selected_indices"] = settings.get_year_result_vs_indices_selected_indices()
        for chart in payload.get("charts") or []:
            chart_id = str(chart.get("id") or "")
            chart["line_width"] = settings.get_chart_line_width_px()
            chart["line_widths"] = settings.get_chart_line_widths_for_chart(chart_id)
            chart["line_styles"] = settings.get_chart_line_styles_for_chart(chart_id)
            chart["visible_series"] = self._visible_series_for_chart(chart)
        return payload

    def _build_payload(self, force_reload: bool = False) -> dict:
        settings = get_settings()
        start_date = settings.get_cash_dashboard_start_date()
        year_percent_mode = settings.get_cash_dashboard_year_percent_mode()
        status_messages: list[str] = []

        raw_payload = build_cash_management_chart_payload()
        result_payload = build_cash_management_result_chart_payload()
        points = _filter_points(raw_payload.get("points") or [], start_date)
        result_points = _filter_points(result_payload.get("points") or [], start_date)
        brokers = _sorted_brokers(raw_payload.get("brokers") or [])

        value_series = _series_from_cash_points(
            points,
            brokers,
            "total_value",
            "invested_stacked",
            "total_value",
            "Total value",
            "",
            "solid",
        )
        result_series = _series_from_cash_points(
            result_points,
            brokers,
            "total_profit",
            "profit",
            "total_result",
            "Totaal resultaat",
            "Resultaat",
            "solid",
        )
        year_series = [
            {**item, "points": _year_result(item.get("points") or [])}
            for item in _series_from_cash_points(
                result_points,
                brokers,
                "total_profit",
                "profit",
                "total_year_result",
                "Totaal jaarresultaat",
                "Jaarresultaat",
                "dashed",
            )
        ]
        percent_series = _year_percent_series(result_points, brokers, year_percent_mode)
        index_options = list_index_asset_rollups()
        try:
            vs_payload = build_year_result_vs_indices_payload(
                selected_indices=index_options,
                selected_portfolio=["total", "degiro", "lynx", "interactive"],
                start_date=start_date,
                force_reload=force_reload,
            )
        except Exception as exc:
            status_messages.append(f"% vs indices niet geladen: {exc}")
            vs_payload = {
                "series": [],
                "index_options": index_options,
                "selected_indices": index_options,
                "selected_portfolio": ["total", "degiro", "lynx", "interactive"],
                "stats": {},
            }
        vs_payload = inject_line_settings(vs_payload, settings, CHART_VS_INDICES)

        charts = [
            self._chart_payload(CHART_VALUE, "Cash", "EUR", value_series),
            self._chart_payload(CHART_RESULT, "Resultaat", "EUR", result_series),
            self._chart_payload(CHART_YEAR_RESULT, "Jaarresultaat", "EUR", year_series),
            self._chart_payload(CHART_YEAR_PERCENT, "% jaarresultaat", "%", percent_series),
            {
                "id": CHART_VS_INDICES,
                "title": "% vs indices",
                "unit": "%",
                "series": vs_payload.get("series") or [],
                "config_series": [
                    {
                        "id": item.get("id"),
                        "label": item.get("label") or item.get("id"),
                        "default_style": "solid",
                    }
                    for item in vs_payload.get("series") or []
                ],
                "line_width": settings.get_chart_line_width_px(),
                "line_widths": settings.get_chart_line_widths_for_chart(CHART_VS_INDICES),
                "line_styles": settings.get_chart_line_styles_for_chart(CHART_VS_INDICES),
                "stats": vs_payload.get("stats") or {},
            },
        ]
        for chart in charts:
            chart["visible_series"] = self._visible_series_for_chart(chart)

        pivot_rows = _build_pivot_rows()
        return {
            "start_date": start_date,
            "panel_state": settings.get_cash_dashboard_panel_state(),
            "year_percent_mode": year_percent_mode,
            "chart_height": settings.get_cash_dashboard_chart_height_px(),
            "charts": charts,
            "pivot": {
                "brokers": PIVOT_BROKERS,
                "rows": pivot_rows,
                "summary": _build_pivot_summary(pivot_rows, result_points),
            },
            "entry": {"today": date.today().isoformat(), "brokers": PIVOT_BROKERS},
            "vs_indices": {
                "portfolio_options": PORTFOLIO_OPTIONS,
                "index_options": index_options,
                "selected_portfolio": settings.get_year_result_vs_indices_selected_portfolio(),
                "selected_indices": settings.get_year_result_vs_indices_selected_indices(),
            },
            "status": " | ".join(status_messages),
        }

    @staticmethod
    def _chart_payload(chart_id: str, title: str, unit: str, series: list[dict]) -> dict:
        settings = get_settings()
        payload = {
            "id": chart_id,
            "title": title,
            "unit": unit,
            "series": series,
            "config_series": cash_series_definitions([], "", "", "", "solid"),
            "line_width": settings.get_chart_line_width_px(),
            "line_widths": settings.get_chart_line_widths_for_chart(chart_id),
            "line_styles": settings.get_chart_line_styles_for_chart(chart_id),
        }
        payload["config_series"] = [
            {
                "id": item.get("id"),
                "label": item.get("label") or item.get("id"),
                "default_style": item.get("default_style") or "solid",
            }
            for item in series or []
        ]
        return payload

    @staticmethod
    def _visible_series_for_chart(chart: dict) -> list[str]:
        settings = get_settings()
        chart_id = str(chart.get("id") or "")
        available = [
            str(item.get("id") or "").strip()
            for item in chart.get("config_series") or chart.get("series") or []
            if str(item.get("id") or "").strip()
        ]
        if chart_id == CHART_VS_INDICES:
            selected = []
            for value in settings.get_year_result_vs_indices_selected_portfolio():
                selected.append(f"portfolio:{str(value).strip().lower()}")
            for value in settings.get_year_result_vs_indices_selected_indices():
                selected.append(f"index:{str(value).strip().upper()}")
            allowed = set(available)
            return [series_id for series_id in selected if series_id in allowed]

        saved_map = settings.get_chart_visible_series_by_chart()
        if chart_id not in saved_map:
            visible = available
        else:
            saved = saved_map.get(chart_id) or []
            allowed = set(available)
            visible = [series_id for series_id in saved if series_id in allowed]
        return visible

    @staticmethod
    def _html() -> str:
        return r"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
  <style>
    :root { --line:#d8d8d8; --bg:#f4f4f4; --panel:#fff; --text:#151515; --muted:#666; --accent:#0b65c2; }
    * { box-sizing: border-box; }
    body { margin:0; font-family: Segoe UI, Arial, sans-serif; color:var(--text); background:var(--bg); font-size:13px; }
    button, input, select, textarea { font:inherit; }
    .topbar { height:42px; display:flex; align-items:center; gap:8px; padding:6px 10px; border-bottom:1px solid var(--line); background:#fafafa; position:sticky; top:0; z-index:5; }
    .topbar input { height:26px; padding:2px 7px; border:1px solid #bbb; border-radius:4px; }
    .topbar button, .drawer-toggle, .form button { height:26px; padding:2px 10px; border:1px solid #aaa; border-radius:4px; background:#fff; cursor:pointer; }
    .status { margin-left:auto; color:var(--muted); }
    .shell { display:grid; grid-template-columns: minmax(760px, 1fr) 430px; gap:10px; height:calc(100vh - 42px); padding:8px; overflow:hidden; }
    .shell.right-collapsed { grid-template-columns: minmax(760px, 1fr) 34px; }
    .right-panel { min-width:0; overflow:hidden; border:1px solid var(--line); background:var(--panel); }
    .panel-head { height:32px; display:flex; align-items:center; gap:6px; padding:4px 6px; border-bottom:1px solid var(--line); background:#f8f8f8; font-weight:600; }
    .panel-body { height:calc(100% - 32px); overflow:hidden; display:grid; grid-template-rows:auto auto minmax(0, 1fr) auto; }
    .shell.right-collapsed .right-panel .panel-body, .shell.right-collapsed .right-title { display:none; }
    .chart-scroll { overflow:auto; min-width:0; background:var(--panel); border:1px solid var(--line); }
    .chart-stack { padding:10px; display:flex; flex-direction:column; gap:18px; min-width:760px; }
    .chart-row { display:grid; grid-template-columns: 285px minmax(560px, 1fr); gap:10px; border-bottom:1px solid #ededed; padding-bottom:14px; align-items:start; }
    .shell.left-collapsed .chart-row { grid-template-columns: minmax(560px, 1fr); }
    .shell.left-collapsed .cfg-cell { display:none; }
    .chart-title { font-size:16px; font-weight:600; margin:0 0 4px 0; color:#123456; }
    .chart-sub { color:var(--muted); font-size:12px; }
    .plot { width:100%; height:var(--chart-height, 320px); border:1px solid #e5e5e5; background:#fff; }
    .cfg-block { padding:9px; border:1px solid #e4d3aa; border-radius:8px; background:#fffaf0; }
    .cfg-block h3 { margin:0 0 8px 0; font-size:13px; }
    .line-row { display:grid; grid-template-columns: minmax(90px, 1fr) 58px 82px; gap:5px; align-items:center; margin-bottom:5px; }
    .line-row input, .line-row select { width:100%; height:24px; border:1px solid #bbb; border-radius:4px; padding:1px 4px; }
    .checks { display:flex; flex-wrap:wrap; gap:6px 10px; margin:5px 0 8px 0; }
    .checks label { white-space:nowrap; }
    fieldset { border:2px solid #9d9d9d; padding:10px 12px 12px; margin:8px 0 12px; background:#fffdf8; }
    legend { padding:0 5px; color:#666; font-size:14px; }
    .pickbox { border:1px solid #eee; background:#fff; height:160px; overflow:auto; padding:4px; margin:5px 0 8px; outline:none; }
    .pickbox:focus { border-color:#7aa7d9; box-shadow:0 0 0 1px #7aa7d9 inset; }
    .pick-row { display:block; padding:4px 7px; cursor:pointer; user-select:none; font-weight:600; }
    .pick-row.selected { background:#c9c9c9; }
    .pick-row:hover { background:#e5eef8; }
    .small-actions { display:grid; grid-template-columns: 1fr 1fr; gap:6px; margin:4px 0 8px; }
    .small-actions button { height:28px; border:1px solid #d7c49a; border-radius:7px; background:#eadfc8; font-weight:600; }
    .form { display:grid; grid-template-columns: 74px 1fr; gap:5px 7px; padding:8px; border-bottom:1px solid var(--line); }
    .form input, .form select, .form textarea { width:100%; border:1px solid #bbb; border-radius:4px; padding:3px 5px; }
    .form textarea { grid-column:2; min-height:46px; resize:vertical; }
    .form .actions { grid-column:2; display:flex; gap:6px; }
    .pivot-wrap { min-height:0; overflow:auto; position:relative; }
    .pivot-spacer { width:1px; opacity:0; }
    .pivot-head table, .pivot-wrap table { table-layout:fixed; }
    .pivot-head { overflow:hidden; border-bottom:1px solid #ddd; }
    .pivot-head th { position:static; }
    .pivot-wrap table { position:absolute; left:0; top:0; }
    .pivot-summary { border-top:1px solid #d0d0d0; background:#fafafa; padding:0 17px 0 0; }
    .pivot-summary table { table-layout:fixed; font-size:12px; }
    .pivot-summary th { position:static; background:#f1f1f1; }
    .pivot-summary td { height:auto; vertical-align:top; white-space:normal; line-height:1.25; }
    .pivot-summary tr.summary-section-start td { border-top:2px solid #9f9f9f; }
    .summary-value { font-weight:600; }
    .summary-date { color:#666; font-size:11px; margin-top:2px; }
    table { border-collapse:collapse; width:100%; }
    th, td { border:1px solid #ddd; padding:4px 6px; text-align:right; white-space:nowrap; height:28px; }
    th { position:sticky; top:0; background:#f6f6f6; z-index:2; }
    td:first-child, th:first-child { text-align:left; }
    td.broker-cell { cursor:pointer; }
    td.broker-cell:hover { background:#eaf3ff; }
    .empty { color:#aaa; }
    .muted { color:var(--muted); }
  </style>
</head>
<body>
  <div class="topbar">
    <button onclick="togglePanel('left')">☰ Instellingen</button>
    <label>Startdatum</label>
    <input id="startDate" type="date">
    <label>Chart hoogte</label>
    <input id="chartHeight" type="number" min="160" max="900" step="20" style="width:78px">
    <button onclick="bridgeCall('setStartDate', document.getElementById('startDate').value)">Refresh</button>
    <button onclick="bridgeCall('openCashMutaties')">Cash Mutaties</button>
    <span id="status" class="status"></span>
  </div>
  <div id="shell" class="shell">
    <main class="chart-scroll"><div id="charts" class="chart-stack"></div></main>
    <aside class="right-panel">
      <div class="panel-head"><button class="drawer-toggle" onclick="togglePanel('right')">☰</button><span class="right-title">Cash pivot</span></div>
      <div class="panel-body">
        <div class="form">
          <label>Datum</label><input id="entryDate" type="date">
          <label>Broker</label><select id="entryBroker"></select>
          <label>Eindstand</label><input id="entryValue" type="number" step="0.01">
          <label>Comment</label><textarea id="entryComment"></textarea>
          <div class="actions"><button onclick="saveEntry()">Opslaan</button><button onclick="resetEntry()">Reset</button></div>
          <input id="entryId" type="hidden">
        </div>
        <div id="pivotHead" class="pivot-head"></div>
        <div id="pivotWrap" class="pivot-wrap" onscroll="renderPivotVisible()">
          <div id="pivotSpacer" class="pivot-spacer"></div>
          <table id="pivotTable"></table>
        </div>
        <div id="pivotSummary" class="pivot-summary"></div>
      </div>
    </aside>
  </div>
<script>
let bridge=null, DATA=null, pivotTop=0;
const rowH=28, buffer=18;
const palette=["#111","#1f77b4","#d62728","#2ca02c","#9467bd","#ff7f0e","#17becf","#8c564b"];
function setStatus(text){ document.getElementById("status").textContent=text||""; }
function bridgeCall(name, ...args){ if(bridge && bridge[name]) bridge[name](...args); }
function fmt(n, dec=2){ if(n===null || n===undefined || Number.isNaN(Number(n))) return ""; return Number(n).toLocaleString("nl-NL",{minimumFractionDigits:dec,maximumFractionDigits:dec}); }
function escapeHtml(s){ return String(s??"").replace(/[&<>"']/g, m=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[m])); }
function togglePanel(side){
  const shell=document.getElementById("shell");
  shell.classList.toggle(side==="left"?"left-collapsed":"right-collapsed");
  savePanelState();
}
function savePanelState(){
  const shell=document.getElementById("shell");
  bridgeCall("setPanelState", JSON.stringify({left_collapsed:shell.classList.contains("left-collapsed"), right_collapsed:shell.classList.contains("right-collapsed")}));
}
function saveChartHeight(){
  const value=Number(document.getElementById("chartHeight").value||320);
  document.documentElement.style.setProperty("--chart-height", `${Math.max(160, Math.min(900, value))}px`);
  bridgeCall("setChartHeight", Math.round(value));
}
function lineWidth(chart, sid){ return Number(chart.line_widths?.[sid] ?? chart.line_width ?? 1.6); }
function lineStyle(chart, item){ return chart.line_styles?.[item.id] ?? item.default_style ?? "solid"; }
function visibleSet(chart){ return new Set(chart.visible_series || (chart.config_series||[]).map(item=>item.id)); }
function renderCashDashboard(payload){
  DATA=payload||{};
  document.getElementById("startDate").value=DATA.start_date||"2021-01-01";
  document.getElementById("chartHeight").value=DATA.chart_height||320;
  document.getElementById("chartHeight").onchange=saveChartHeight;
  document.documentElement.style.setProperty("--chart-height", `${DATA.chart_height||320}px`);
  const shell=document.getElementById("shell");
  shell.classList.toggle("left-collapsed", !!DATA.panel_state?.left_collapsed);
  shell.classList.toggle("right-collapsed", !!DATA.panel_state?.right_collapsed);
  renderCharts();
  renderEntryForm();
  renderPivotSetup();
  setStatus(DATA.status||"");
}
function renderConfig(){
  const pane=document.getElementById("configPane");
  pane.innerHTML=(DATA.charts||[]).map(chart=>{
    const vs=chart.id==="year_result_vs_indices" ? renderVsConfig() : "";
    const mode=chart.id==="cash_management_year_result_percent" ? `<div class="checks"><label><input type="radio" name="ypm" value="average" ${DATA.year_percent_mode==="average"?"checked":""} onchange="bridgeCall('setYearPercentMode',this.value)"> Gemiddelde noemer</label><label><input type="radio" name="ypm" value="start" ${DATA.year_percent_mode==="start"?"checked":""} onchange="bridgeCall('setYearPercentMode',this.value)"> Start noemer</label></div>` : "";
    const rows=(chart.config_series||[]).map(item=>`<div class="line-row">
      <span title="${escapeHtml(item.id)}">${escapeHtml(item.label)}</span>
      <input type="number" min="0.5" max="8" step="0.1" value="${lineWidth(chart,item.id)}" onchange="saveLine('${chart.id}','${escapeHtml(item.id)}',this.value,this.parentElement.querySelector('select').value)">
      <select onchange="saveLine('${chart.id}','${escapeHtml(item.id)}',this.parentElement.querySelector('input').value,this.value)">
        <option value="solid" ${lineStyle(chart,item)==="solid"?"selected":""}>Doorlopend</option>
        <option value="dashed" ${lineStyle(chart,item)==="dashed"?"selected":""}>Gestreept</option>
      </select>
    </div>`).join("");
    return `<section class="cfg-block"><h3>${escapeHtml(chart.title)}</h3>${mode}${vs}${rows}</section>`;
  }).join("");
}
function renderVsConfig(){
  const selectedP=new Set(DATA.vs_indices?.selected_portfolio||[]);
  const selectedI=new Set(DATA.vs_indices?.selected_indices||[]);
  const portfolio=(DATA.vs_indices?.portfolio_options||[]).map(o=>`<div class="pick-row ${selectedP.has(o.id)?"selected":""}" data-vsp="${escapeHtml(o.id)}" onmousedown="pickMouseDown(event,this)" onmouseenter="pickMouseEnter(event,this)">${escapeHtml(o.label)}</div>`).join("");
  const indices=(DATA.vs_indices?.index_options||[]).map(i=>`<div class="pick-row ${selectedI.has(i)?"selected":""}" data-vsi="${escapeHtml(i)}" onmousedown="pickMouseDown(event,this)" onmouseenter="pickMouseEnter(event,this)">${escapeHtml(i)}</div>`).join("");
  return `<fieldset><legend>PORTFOLIO</legend><div class="small-actions"><button onclick="selectGroup('vsp',true)">Alles</button><button onclick="selectGroup('vsp',false)">Niets</button></div><div class="pickbox" tabindex="0" data-pick-kind="vsp" data-pick-key="vsp" onkeydown="pickKeyDown(event,this)">${portfolio}</div></fieldset>
  <fieldset><legend>INDICES</legend><div class="small-actions"><button onclick="selectGroup('vsi',true)">Alles</button><button onclick="selectGroup('vsi',false)">Niets</button></div><div class="pickbox" tabindex="0" data-pick-kind="vsi" data-pick-key="vsi" onkeydown="pickKeyDown(event,this)">${indices||"<span class='muted'>Geen index assets gevonden</span>"}</div></fieldset>`;
}
let dragPickBox=null;
let dragPickDirty=false;
let activePickKey="";
let pickScrollTopByKey={};
document.addEventListener("mouseup", ()=>{
  if(dragPickBox && dragPickDirty) commitPick(dragPickBox);
  dragPickBox=null;
  dragPickDirty=false;
});
document.addEventListener("keydown", ev=>{
  if(ev.defaultPrevented || (ev.key!=="ArrowDown" && ev.key!=="ArrowUp")) return;
  const active=document.activeElement?.classList?.contains("pickbox") ? document.activeElement : findActivePickBox();
  if(active) pickKeyDown(ev, active);
});
function commitPick(box){
  rememberPickScroll(box);
  const kind=box?.dataset?.pickKind||"";
  if(kind==="vsp" || kind==="vsi") saveVsSelection();
  else if(kind==="series") saveSeriesSelection(box.dataset.chartId||"");
}
function pickRows(box){ return [...(box?.querySelectorAll(".pick-row")||[])]; }
function setRowSelected(row, selected){ row.classList.toggle("selected", selected); }
function pickBoxKey(box){ return box?.dataset?.pickKey || `${box?.dataset?.pickKind||""}:${box?.dataset?.chartId||""}`; }
function rememberPickScroll(box){
  if(!box) return;
  pickScrollTopByKey[pickBoxKey(box)]=box.scrollTop || 0;
}
function setActivePickBox(box){
  if(!box) return;
  activePickKey=pickBoxKey(box);
  document.querySelectorAll(".pickbox.active").forEach(el=>el.classList.remove("active"));
  box.classList.add("active");
  box.focus({preventScroll:true});
}
function findActivePickBox(){
  if(!activePickKey) return null;
  return document.querySelector(`.pickbox[data-pick-key="${cssEscape(activePickKey)}"]`);
}
function restoreActivePickBox(){
  const box=findActivePickBox();
  if(!box) return;
  box.classList.add("active");
  const selected=pickRows(box).filter(row=>row.classList.contains("selected"));
  box._lastPick=selected.length ? selected[selected.length-1] : null;
  if(Object.prototype.hasOwnProperty.call(pickScrollTopByKey, activePickKey)){
    box.scrollTop=pickScrollTopByKey[activePickKey];
  } else if(box._lastPick){
    box._lastPick.scrollIntoView({block:"nearest"});
  }
  box.focus({preventScroll:true});
}
function cssEscape(value){
  if(window.CSS && CSS.escape) return CSS.escape(String(value));
  return String(value).replace(/["\\]/g, "\\$&");
}
function pickMouseDown(ev, el){
  if(ev.button!==0) return;
  ev.preventDefault();
  const box=el.closest(".pickbox");
  if(!box) return;
  setActivePickBox(box);
  const rows=pickRows(box);
  if(ev.shiftKey && box._lastPick){
    const a=rows.indexOf(box._lastPick), b=rows.indexOf(el);
    if(a>=0 && b>=0){
      if(!ev.ctrlKey && !ev.metaKey) rows.forEach(row=>setRowSelected(row, false));
      const lo=Math.min(a,b), hi=Math.max(a,b);
      for(let i=lo;i<=hi;i++) setRowSelected(rows[i], true);
    }
  } else if(ev.ctrlKey || ev.metaKey){
    setRowSelected(el, !el.classList.contains("selected"));
  } else {
    rows.forEach(row=>setRowSelected(row, false));
    setRowSelected(el, true);
  }
  box._lastPick=el;
  dragPickBox=box;
  dragPickDirty=true;
}
function pickMouseEnter(ev, el){
  const box=el.closest(".pickbox");
  if(!dragPickBox || box!==dragPickBox || ev.buttons!==1) return;
  setRowSelected(el, true);
  box._lastPick=el;
  dragPickDirty=true;
}
function pickKeyDown(ev, box){
  if(ev.key!=="ArrowDown" && ev.key!=="ArrowUp") return;
  ev.preventDefault();
  const rows=pickRows(box);
  if(!rows.length) return;
  let idx=box._lastPick ? rows.indexOf(box._lastPick) : -1;
  if(idx<0){
    const selected=rows.filter(row=>row.classList.contains("selected"));
    idx=selected.length ? rows.indexOf(selected[selected.length-1]) : 0;
  }
  idx += ev.key==="ArrowDown" ? 1 : -1;
  idx=Math.max(0, Math.min(rows.length-1, idx));
  if(ev.shiftKey && box._lastPick){
    setRowSelected(rows[idx], true);
  } else if(ev.ctrlKey || ev.metaKey){
    setRowSelected(rows[idx], true);
  } else {
    rows.forEach(row=>setRowSelected(row, false));
    setRowSelected(rows[idx], true);
  }
  rows[idx].scrollIntoView({block:"nearest"});
  box._lastPick=rows[idx];
  rememberPickScroll(box);
  commitPick(box);
}
function selectGroup(group, checked){
  const first=document.querySelector(`[data-${group}]`);
  const box=first?.closest(".pickbox");
  if(box) setActivePickBox(box);
  document.querySelectorAll(`[data-${group}]`).forEach(el=>{ el.classList.toggle("selected", checked); });
  if(box) rememberPickScroll(box);
  saveVsSelection();
}
function saveVsSelection(){
  const portfolio=[...document.querySelectorAll("[data-vsp].selected")].map(el=>el.dataset.vsp);
  const indices=[...document.querySelectorAll("[data-vsi].selected")].map(el=>el.dataset.vsi);
  bridgeCall("setVsIndicesSelection", JSON.stringify({portfolio,indices}));
}
function saveLine(chartId, seriesId, width, style){ bridgeCall("setLineSetting", chartId, seriesId, Number(width), style); }
function renderCharts(){
  document.getElementById("charts").innerHTML=(DATA.charts||[]).map((chart,idx)=>`<section class="chart-row" data-chart-series="${chart.id}"><aside class="cfg-cell">${renderConfigForChart(chart)}</aside><div><h2 class="chart-title">${escapeHtml(chart.title)}</h2><div class="chart-sub">${chart.stats?.start_date||""} ${chart.stats?.end_date? "t/m "+chart.stats.end_date:""}</div><svg class="plot" id="chart_${idx}"></svg></div></section>`).join("");
  (DATA.charts||[]).forEach((chart,idx)=>drawChart(document.getElementById(`chart_${idx}`), chart));
  restoreActivePickBox();
}
function renderConfigForChart(chart){
  const vs=chart.id==="year_result_vs_indices" ? renderVsConfig() : "";
  const mode=chart.id==="cash_management_year_result_percent" ? `<div class="checks"><label><input type="radio" name="ypm" value="average" ${DATA.year_percent_mode==="average"?"checked":""} onchange="bridgeCall('setYearPercentMode',this.value)"> Gemiddelde noemer</label><label><input type="radio" name="ypm" value="start" ${DATA.year_percent_mode==="start"?"checked":""} onchange="bridgeCall('setYearPercentMode',this.value)"> Start noemer</label></div>` : "";
  const selected=visibleSet(chart);
  const selector=(chart.config_series||[]).map(item=>`<div class="pick-row ${selected.has(item.id)?"selected":""}" data-series-pick="${escapeHtml(item.id)}" onmousedown="pickMouseDown(event,this)" onmouseenter="pickMouseEnter(event,this)">${escapeHtml(item.label)}</div>`).join("");
  const lineItems=chart.id==="year_result_vs_indices"
    ? (chart.config_series||[]).filter(item=>selected.has(item.id))
    : (chart.config_series||[]);
  const rows=lineItems.map(item=>`<div class="line-row">
      <span title="${escapeHtml(item.id)}">${escapeHtml(item.label)}</span>
      <input type="number" min="0.5" max="8" step="0.1" value="${lineWidth(chart,item.id)}" onchange="saveLine('${chart.id}','${escapeHtml(item.id)}',this.value,this.parentElement.querySelector('select').value)">
      <select onchange="saveLine('${chart.id}','${escapeHtml(item.id)}',this.parentElement.querySelector('input').value,this.value)">
        <option value="solid" ${lineStyle(chart,item)==="solid"?"selected":""}>Doorlopend</option>
        <option value="dashed" ${lineStyle(chart,item)==="dashed"?"selected":""}>Gestreept</option>
      </select>
    </div>`).join("");
  if(chart.id==="year_result_vs_indices"){
    const lineRows=rows || `<div class="muted">Geen geselecteerde lijnen</div>`;
    return `<section class="cfg-block"><h3>${escapeHtml(chart.title)}</h3>${vs}<div class="muted">Lijndikte en type</div>${lineRows}</section>`;
  }
  return `<section class="cfg-block"><h3>${escapeHtml(chart.title)}</h3>${mode}<fieldset><legend>LIJNEN</legend><div class="small-actions"><button onclick="selectSeriesGroup('${chart.id}',true)">Alles</button><button onclick="selectSeriesGroup('${chart.id}',false)">Niets</button></div><div class="pickbox" tabindex="0" data-pick-kind="series" data-chart-id="${chart.id}" data-pick-key="series:${chart.id}" onkeydown="pickKeyDown(event,this)">${selector}</div></fieldset>${rows}</section>`;
}
function selectSeriesGroup(chartId, checked){ document.querySelectorAll(`[data-chart-series="${chartId}"] [data-series-pick]`).forEach(el=>el.classList.toggle("selected", checked)); saveSeriesSelection(chartId); }
function saveSeriesSelection(chartId){
  const ids=[...document.querySelectorAll(`[data-chart-series="${chartId}"] [data-series-pick].selected`)].map(el=>el.dataset.seriesPick);
  bridgeCall("setVisibleSeries", chartId, JSON.stringify(ids));
}
function drawChart(svg, chart){
  if(!svg) return;
  const w=svg.clientWidth||900, h=svg.clientHeight||320, m={l:20,r:76,t:18,b:34};
  svg.setAttribute("viewBox",`0 0 ${w} ${h}`);
  const selected=visibleSet(chart);
  const visibleSeries=(chart.series||[]).filter(s=>selected.has(s.id));
  const all=visibleSeries.flatMap(s=>(s.points||[]).map(p=>({d:p.date,y:Number(p.y)}))).filter(p=>p.d && Number.isFinite(p.y));
  if(!all.length){ svg.innerHTML=`<text x="${w/2}" y="${h/2}" text-anchor="middle" fill="#777">Geen data</text>`; return; }
  const dates=[...new Set(all.map(p=>p.d))].sort();
  const minY=Math.min(...all.map(p=>p.y)), maxY=Math.max(...all.map(p=>p.y));
  const axis=niceAxis(minY,maxY,chart.unit,h-m.t-m.b);
  const y0=axis.min, y1=axis.max;
  const x=d=>m.l + (dates.indexOf(d)/Math.max(1,dates.length-1))*(w-m.l-m.r);
  const y=v=>h-m.b - ((v-y0)/(y1-y0))*(h-m.t-m.b);
  let html="";
  axis.minor.forEach(val=>{ if(val<=y0 || val>=y1) return; const yy=y(val); html+=`<line x1="${m.l}" x2="${w-m.r}" y1="${yy}" y2="${yy}" stroke="#f1f1f1"/>`; if(axis.labelMinor){ html+=`<text x="${w-m.r+8}" y="${yy+4}" text-anchor="start" fill="#7a8da2" font-size="11">${fmtAxis(val, chart.unit)}</text>`; } });
  axis.major.forEach(val=>{ const yy=y(val); const zero=Math.abs(val)<1e-9; html+=`<line x1="${m.l}" x2="${w-m.r}" y1="${yy}" y2="${yy}" stroke="${zero?"#8d8d8d":"#dcdcdc"}" stroke-width="${zero?1.8:1}"/><text x="${w-m.r+8}" y="${yy+4}" text-anchor="start" fill="#5c738e" font-size="11">${fmtAxis(val, chart.unit)}</text>`; });
  html+=`<line x1="${m.l}" x2="${w-m.r}" y1="${h-m.b}" y2="${h-m.b}" stroke="#bbb"/><line x1="${m.l}" x2="${m.l}" y1="${m.t}" y2="${h-m.b}" stroke="#bbb"/>`;
  const tickDates=niceDateTicks(dates, w-m.l-m.r);
  tickDates.forEach(d=>{ const xx=x(d); html+=`<line x1="${xx}" x2="${xx}" y1="${m.t}" y2="${h-m.b}" stroke="#f5f5f5"/><text x="${xx}" y="${h-10}" text-anchor="middle" fill="#666" font-size="11" transform="rotate(-45 ${xx} ${h-10})">${formatDateTick(d)}</text>`; });
  visibleSeries.forEach((s,si)=>{
    const color=s.color||palette[si%palette.length], width=lineWidth(chart,s.id), dash=lineStyle(chart,s)==="dashed" ? "6 4" : "";
    const clean=(s.points||[]).filter(p=>p.date && Number.isFinite(Number(p.y)));
    const segments=[];
    let current=[], lastYear="";
    clean.forEach(p=>{
      const year=String(p.date).slice(0,4);
      const mustBreak=["cash_management_year_result","cash_management_year_result_percent","year_result_vs_indices"].includes(chart.id) && lastYear && year!==lastYear;
      if(mustBreak && current.length){ segments.push(current); current=[]; }
      current.push(p); lastYear=year;
    });
    if(current.length) segments.push(current);
    segments.forEach(seg=>{
      const pts=seg.map(p=>`${x(p.date).toFixed(1)},${y(Number(p.y)).toFixed(1)}`).join(" ");
      if(pts) html+=`<polyline points="${pts}" fill="none" stroke="${color}" stroke-width="${width}" stroke-dasharray="${dash}"><title>${escapeHtml(s.label)}</title></polyline>`;
    });
  });
  let lx=m.l+8, ly=m.t+12;
  visibleSeries.slice(0,8).forEach((s,si)=>{ const color=s.color||palette[si%palette.length]; html+=`<line x1="${lx}" x2="${lx+18}" y1="${ly}" y2="${ly}" stroke="${color}" stroke-width="2"/><text x="${lx+24}" y="${ly+4}" font-size="11" fill="#333">${escapeHtml(s.label)}</text>`; lx+=130; if(lx>w-160){ lx=m.l+8; ly+=16; } });
  svg.innerHTML=html;
}
function niceAxis(minVal,maxVal,unit,plotHeight){
  if(!Number.isFinite(minVal) || !Number.isFinite(maxVal)) return {min:0,max:1,major:[0,1],minor:[0.5]};
  if(unit !== "%") return moneyAxis(minVal,maxVal);
  return percentAxis(minVal,maxVal,plotHeight);
}
function percentAxis(minVal,maxVal,plotHeight){
  if(minVal===maxVal){ const pad=Math.max(1,Math.abs(minVal)*0.1); minVal-=pad; maxVal+=pad; }
  if(minVal>0 && minVal/(maxVal-minVal)<0.18) minVal=0;
  if(maxVal<0 && Math.abs(maxVal)/(maxVal-minVal)<0.18) maxVal=0;
  const range=Math.max(1, maxVal-minVal);
  const minPx=34;
  let step=10;
  const ticksFor = s => Math.ceil(maxVal/s)-Math.floor(minVal/s)+1;
  if((plotHeight || 320) / ticksFor(step) < minPx) step=5;
  if((plotHeight || 320) / ticksFor(step) < minPx) step=2;
  if((plotHeight || 320) / ticksFor(step) < minPx) step=niceStep(range/5);
  const axisMin=Math.floor(minVal/step)*step;
  const axisMax=Math.ceil(maxVal/step)*step;
  const major=[];
  for(let v=axisMin; v<=axisMax+step*0.5; v+=step){ major.push(cleanTick(v)); }
  const minorStep=step/2, minor=[];
  for(let v=axisMin; v<=axisMax+minorStep*0.5; v+=minorStep){ if(!major.some(m=>Math.abs(m-v)<step*1e-6)) minor.push(cleanTick(v)); }
  return {min:axisMin,max:axisMax,major,minor,labelMinor:false};
}
function moneyAxis(minVal,maxVal){
  if(minVal===maxVal){ const pad=Math.max(25000,Math.abs(minVal)*0.08); minVal-=pad; maxVal+=pad; }
  minVal=Math.min(minVal,0);
  maxVal=Math.max(maxVal,0);
  const minorStep=25000;
  const range=maxVal-minVal;
  const majorStep=range<=150000 ? 25000 : range<=350000 ? 50000 : 100000;
  const axisMin=Math.floor(minVal/minorStep)*minorStep;
  const axisMax=Math.max(minorStep, Math.ceil(maxVal/minorStep)*minorStep);
  const minor=[], major=[];
  for(let v=axisMin; v<=axisMax+minorStep*0.5; v+=minorStep){
    const clean=cleanTick(v);
    if(Math.abs(clean % majorStep)<1e-6 || Math.abs(clean)<1e-9) major.push(clean);
    else minor.push(clean);
  }
  return {min:axisMin,max:axisMax,major,minor,labelMinor:true};
}
function niceStep(raw){
  const exp=Math.floor(Math.log10(Math.max(raw,1e-12)));
  const base=Math.pow(10,exp);
  const f=raw/base;
  const nice=f<=1?1:f<=2?2:f<=2.5?2.5:f<=5?5:10;
  return nice*base;
}
function cleanTick(v){ return Math.abs(v)<1e-10?0:Number(v.toPrecision(12)); }
function fmtAxis(value, unit){
  const abs=Math.abs(value);
  const dec=unit==="%" ? (abs<10?1:0) : (abs<10?2:abs<100?1:0);
  return fmt(value,dec) + (unit==="%" ? "%" : "");
}
function niceDateTicks(dates, width){
  if(!dates.length) return [];
  const maxTicks=Math.max(3, Math.floor(width/115));
  const first=new Date(dates[0]+"T00:00:00"), last=new Date(dates[dates.length-1]+"T00:00:00");
  const days=Math.max(1, Math.round((last-first)/86400000));
  const dateSet=new Set(dates);
  const out=[];
  function pushNear(dt){
    const target=dt.toISOString().slice(0,10);
    if(dateSet.has(target)){ out.push(target); return; }
    for(let offset=1; offset<=4; offset++){
      const plus=new Date(dt); plus.setDate(plus.getDate()+offset);
      const minus=new Date(dt); minus.setDate(minus.getDate()-offset);
      const p=plus.toISOString().slice(0,10), m=minus.toISOString().slice(0,10);
      if(dateSet.has(p)){ out.push(p); return; }
      if(dateSet.has(m)){ out.push(m); return; }
    }
  }
  if(days<=80){
    const step=days<=35?7:14;
    const d=new Date(first);
    while(d<=last){ pushNear(d); d.setDate(d.getDate()+step); }
  } else if(days<=420){
    const monthStep=maxTicks<7?2:1;
    const d=new Date(first.getFullYear(), first.getMonth(), 1);
    while(d<=last){ pushNear(d); d.setMonth(d.getMonth()+monthStep); }
  } else {
    const monthStep=days<=900?3:6;
    const d=new Date(first.getFullYear(), Math.floor(first.getMonth()/monthStep)*monthStep, 1);
    while(d<=last){ pushNear(d); d.setMonth(d.getMonth()+monthStep); }
  }
  out.push(dates[0], dates[dates.length-1]);
  return [...new Set(out)].filter(d=>dateSet.has(d)).sort().filter((d,i,arr)=>arr.length<=maxTicks || i===0 || i===arr.length-1 || i % Math.ceil(arr.length/maxTicks)===0);
}
function formatDateTick(iso){
  const [y,m,d]=String(iso).split("-");
  return `${d}-${m}-${String(y).slice(2)}`;
}
function renderEntryForm(){ const sel=document.getElementById("entryBroker"); sel.innerHTML=(DATA.entry?.brokers||[]).map(b=>`<option value="${b}">${b}</option>`).join(""); resetEntry(); }
function resetEntry(){ document.getElementById("entryId").value=""; document.getElementById("entryDate").value=DATA.entry?.today||""; document.getElementById("entryBroker").value=(DATA.entry?.brokers||["degiro"])[0]; document.getElementById("entryValue").value=""; document.getElementById("entryComment").value=""; }
function saveEntry(){ bridgeCall("saveDailyBalance", JSON.stringify({ id:document.getElementById("entryId").value, datum:document.getElementById("entryDate").value, broker:document.getElementById("entryBroker").value, ending_balance:document.getElementById("entryValue").value, comment_text:document.getElementById("entryComment").value })); }
function loadEntry(date, broker, cell){ if(!cell) return; document.getElementById("entryId").value=cell.id||""; document.getElementById("entryDate").value=date; document.getElementById("entryBroker").value=broker; document.getElementById("entryValue").value=cell.value??""; document.getElementById("entryComment").value=cell.comment||""; }
function renderPivotSetup(){ const rows=DATA.pivot?.rows||[]; document.getElementById("pivotSpacer").style.height=`${rows.length*rowH}px`; renderPivotVisible(); renderPivotSummary(); }
function renderPivotVisible(){
  const wrap=document.getElementById("pivotWrap"), table=document.getElementById("pivotTable"), rows=DATA?.pivot?.rows||[], brokers=DATA?.pivot?.brokers||[];
  document.getElementById("pivotHead").innerHTML="<table><thead><tr><th>datum</th>"+brokers.map(b=>`<th>${escapeHtml(b)}</th>`).join("")+"<th>totaal</th></tr></thead></table>";
  const start=Math.max(0, Math.floor(wrap.scrollTop/rowH)-buffer), count=Math.ceil(wrap.clientHeight/rowH)+buffer*2, end=Math.min(rows.length,start+count);
  table.style.transform=`translateY(${start*rowH}px)`;
  let html="<tbody>";
  for(let i=start;i<end;i++){ const r=rows[i]; html+=`<tr><td>${escapeHtml(r.date_nl)}</td>`; brokers.forEach(b=>{ const c=r.brokers?.[b]; html+=`<td class="broker-cell ${c?"":"empty"}" onclick="loadPivotCell(${i},'${b}')">${c?fmt(c.value,2):""}</td>`; }); html+=`<td>${fmt(r.total,2)}</td></tr>`; }
  table.innerHTML=html+"</tbody>";
}
function loadPivotCell(rowIndex, broker){ const r=DATA?.pivot?.rows?.[rowIndex]; if(!r) return; loadEntry(r.date, broker, r.brokers?.[broker]); }
function renderPivotSummary(){
  const target=document.getElementById("pivotSummary");
  if(!target) return;
  const brokers=DATA?.pivot?.brokers||[];
  const columns=[...brokers,"total"];
  const summary=DATA?.pivot?.summary||{};
  const label={degiro:"degiro",interactive:"interactive",lynx:"lynx",total:"totaal"};
  function cell(rowKey, column, unit){
    const item=summary?.[rowKey]?.[column]||{};
    if(item.value===null || item.value===undefined) return "<td class='empty'></td>";
    const valueText=unit==="%" ? `${fmt(item.value,1)}%` : fmt(item.value,2);
    return `<td><div class="summary-value">${valueText}</div><div class="summary-date">${escapeHtml(item.date_nl||"")}</div></td>`;
  }
  const currentBalanceTitle="Huidige eindstand, gecorrigeerd voor cash mutaties (stortingen / opnames) sinds laatste max. eindstand";
  target.innerHTML=`<table><thead><tr><th></th>${columns.map(c=>`<th>${escapeHtml(label[c]||c)}</th>`).join("")}</tr></thead>
    <tbody>
      <tr title="${escapeHtml(currentBalanceTitle)}"><td>Current eindstand</td>${columns.map(c=>cell("adjusted_current_balance",c,"EUR")).join("")}</tr>
      <tr><td>Max eindstand</td>${columns.map(c=>cell("max_balance",c,"EUR")).join("")}</tr>
      <tr><td>Eindstand drawdown</td>${columns.map(c=>cell("balance_drawdown",c,"%")).join("")}</tr>
      <tr class="summary-section-start"><td>Current profit</td>${columns.map(c=>cell("current_profit",c,"EUR")).join("")}</tr>
      <tr><td>Max profit</td>${columns.map(c=>cell("max_profit",c,"EUR")).join("")}</tr>
      <tr><td>Profit / max</td>${columns.map(c=>cell("profit_drawdown",c,"%")).join("")}</tr>
    </tbody></table>`;
}
if(window.qt && window.QWebChannel){ new QWebChannel(qt.webChannelTransport, ch=>{ bridge=ch.objects.cashBridge; bridge.ready(); }); }
</script>
</body>
</html>
"""
