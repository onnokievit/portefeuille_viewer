from __future__ import annotations

import contextlib
import json
from datetime import date, datetime, timedelta

import polars as pl
from PySide6.QtCore import QObject, Qt, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout

from portefeuille_viewer.config import get_settings
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.signals import signals

try:
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:  # pragma: no cover
    QWebChannel = None
    QWebEngineView = None


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


def _last_day_of_month(year: int, month: int) -> date:
    if month == 12:
        return date(year + 1, 1, 1) - timedelta(days=1)
    return date(year, month + 1, 1) - timedelta(days=1)


def _iter_month_end_dates(start_date: date, end_date: date) -> list[date]:
    out: list[date] = []
    year = start_date.year
    month = start_date.month
    while (year, month) <= (end_date.year, end_date.month):
        candidate = _last_day_of_month(year, month)
        if start_date <= candidate <= end_date:
            out.append(candidate)
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
    return out


def _iter_quarter_end_dates(start_date: date, end_date: date) -> list[date]:
    quarter_end_months = (3, 6, 9, 12)
    out: list[date] = []
    year = start_date.year
    while year <= end_date.year:
        for month in quarter_end_months:
            candidate = _last_day_of_month(year, month)
            if start_date <= candidate <= end_date:
                out.append(candidate)
        year += 1
    return out


def _iter_year_end_dates(start_date: date, end_date: date) -> list[date]:
    out: list[date] = []
    for year in range(start_date.year, end_date.year + 1):
        candidate = date(year, 12, 31)
        if start_date <= candidate <= end_date:
            out.append(candidate)
    return out


def _schedule_dates(start_date: date, end_date: date, mode: str) -> list[date]:
    if end_date < start_date:
        start_date, end_date = end_date, start_date
    if mode == "daily":
        return _iter_daily_dates(start_date, end_date)
    if mode == "weekly_friday":
        return _iter_friday_dates(start_date, end_date)
    if mode == "month_end":
        return _iter_month_end_dates(start_date, end_date)
    if mode == "quarter_end":
        return _iter_quarter_end_dates(start_date, end_date)
    if mode == "year_end":
        return _iter_year_end_dates(start_date, end_date)
    return _iter_third_friday_dates(start_date, end_date)


def _append_today_if_needed(schedule: list[date], end_date: date) -> list[date]:
    today = date.today()
    if end_date < today:
        return schedule
    if today not in schedule:
        schedule = list(schedule) + [today]
    return sorted(set(schedule))


class MaandEindChartDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Maandeind Eindwaarden Chart")
        self.setModal(False)
        self.setWindowFlag(Qt.Window, True)
        self.setWindowFlag(Qt.WindowMinimizeButtonHint, True)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.setWindowFlag(Qt.WindowCloseButtonHint, True)
        self._force_close = False
        self._js_ready = False
        self._pending_js_calls: list[tuple[str, object]] = []
        self._start_date = date.today() - timedelta(days=365)
        self._end_date = date.today()
        self._frequency = "third_friday"
        self._selected_sectors: set[str] | None = None
        self._selected_regios: set[str] | None = None
        self._selected_value_grows: set[str] | None = None
        self._split_sector = False
        self._split_regio = False
        self._split_value_grow = False
        self._restored_state = False
        self._restore_saved_state()
        self._restore_geometry()

        layout = QVBoxLayout(self)
        if QWebEngineView is None:
            layout.addWidget(QLabel("QtWebEngine niet beschikbaar in deze runtime."))
            return
        self.web = QWebEngineView(self)
        layout.addWidget(self.web)
        if QWebChannel is not None:
            self.channel = QWebChannel(self.web.page())
            self.bridge = _MaandEindChartBridge(self)
            self.channel.registerObject("maandEindChartBridge", self.bridge)
            self.web.page().setWebChannel(self.channel)
        self.web.loadFinished.connect(self._on_web_loaded)
        self.web.setHtml(self._html_template())
        signals.snapshotUpdated.connect(self._on_snapshot_updated)
        signals.stateRebuildFinished.connect(self._on_state_rebuild_finished)
        signals.databaseChanged.connect(self._on_database_changed)

    def closeEvent(self, event):
        self._save_geometry()
        self._save_state()
        if getattr(self, "_force_close", False):
            global _MONTH_END_CHART_DIALOG_INSTANCE
            _MONTH_END_CHART_DIALOG_INSTANCE = None
            event.accept()
            return
        event.ignore()
        self.hide()

    def sync_from_maand_eind(
        self,
        start_date: date,
        end_date: date,
        frequency: str,
        filter_sector: str = "",
        filter_regio: str = "",
        filter_value_grow: str = "",
    ) -> None:
        if self._restored_state:
            return
        self._start_date = start_date
        self._end_date = end_date
        if frequency in {"daily", "weekly_friday", "third_friday", "month_end", "quarter_end", "year_end"}:
            self._frequency = frequency
        self._selected_sectors = {filter_sector} if str(filter_sector or "").strip() else None
        self._selected_regios = {filter_regio} if str(filter_regio or "").strip() else None
        self._selected_value_grows = {filter_value_grow} if str(filter_value_grow or "").strip() else None
        self._save_state()
        self._publish_all()

    def _on_web_loaded(self, ok: bool):
        self._js_ready = bool(ok)
        if not self._js_ready:
            return
        for func_name, payload in self._pending_js_calls:
            self._run_js(func_name, payload)
        self._pending_js_calls.clear()
        self._publish_all()

    def _on_snapshot_updated(self, snapshot_key: str):
        if snapshot_key in {"repository_snapshot_per_dag_asset_result_v2", "repository_snapshot_asset_rollup_data"}:
            self._publish_all()

    def _on_state_rebuild_finished(self, payload: dict | None):
        if (payload or {}).get("status") == "ok":
            self._publish_all()

    def _on_database_changed(self, _db_name: str):
        self._publish_all()

    def _call_js(self, func_name: str, payload: object):
        if not hasattr(self, "web"):
            return
        if not self._js_ready:
            self._pending_js_calls.append((func_name, payload))
            return
        self._run_js(func_name, payload)

    def _run_js(self, func_name: str, payload: object):
        js_payload = json.dumps(payload, ensure_ascii=False, default=self._json_default)
        self.web.page().runJavaScript(f"window.{func_name}({js_payload});")

    @staticmethod
    def _json_default(value):
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return str(value)

    def _metadata_df(self) -> pl.DataFrame:
        df_meta = getattr(SNAPSHOT_STORE, "repository_snapshot_asset_rollup_data", None)
        if df_meta is None or df_meta.is_empty() or "asset_rollup" not in df_meta.columns:
            return pl.DataFrame(
                schema={
                    "asset_rollup": pl.Utf8,
                    "regio": pl.Utf8,
                    "value_grow": pl.Utf8,
                    "sector": pl.Utf8,
                }
            )
        return (
            df_meta.with_columns(
                [
                    pl.col("asset_rollup").cast(pl.Utf8).str.strip_chars().str.to_uppercase().alias("asset_rollup"),
                    (
                        pl.col("regio").cast(pl.Utf8, strict=False).fill_null("").alias("regio")
                        if "regio" in df_meta.columns
                        else pl.lit("").alias("regio")
                    ),
                    (
                        pl.col("value_grow").cast(pl.Utf8, strict=False).fill_null("").alias("value_grow")
                        if "value_grow" in df_meta.columns
                        else pl.lit("").alias("value_grow")
                    ),
                    (
                        pl.col("sector").cast(pl.Utf8, strict=False).fill_null("").alias("sector")
                        if "sector" in df_meta.columns
                        else pl.lit("").alias("sector")
                    ),
                ]
            )
            .select(["asset_rollup", "regio", "value_grow", "sector"])
            .unique(subset=["asset_rollup"], keep="first")
            .sort("asset_rollup")
        )

    def _options(self, meta_df: pl.DataFrame, col: str) -> list[str]:
        if meta_df.is_empty() or col not in meta_df.columns:
            return []
        return sorted({str(v) for v in meta_df[col].to_list() if v is not None and str(v).strip()})

    @staticmethod
    def _selection_payload(selected: set[str] | None, options: list[str]) -> dict[str, object]:
        if selected is None:
            return {"mode": "all", "selected": []}
        keep = [opt for opt in options if opt in selected]
        return {"mode": "custom", "selected": keep}

    def _apply_selection_filter(self, df: pl.DataFrame, col: str, selected: set[str] | None) -> pl.DataFrame:
        if selected is None:
            return df
        values = [v for v in selected if str(v).strip()]
        if not values:
            return df.filter(pl.lit(False))
        return df.filter(pl.col(col).is_in(values))

    def _filtered_work_df(self, schedule: list[date]) -> pl.DataFrame:
        df_source = getattr(SNAPSHOT_STORE, "repository_snapshot_per_dag_asset_result_v2", None)
        if not schedule or df_source is None or df_source.is_empty():
            return pl.DataFrame(schema={"datum": pl.Date, "asset_rollup": pl.Utf8, "waarde": pl.Float64})
        if "datum" not in df_source.columns or "asset_rollup" not in df_source.columns or "totaal_v2" not in df_source.columns:
            return pl.DataFrame(schema={"datum": pl.Date, "asset_rollup": pl.Utf8, "waarde": pl.Float64})
        meta_df = self._metadata_df()
        eurusd = float(get_settings().get_eurusd() or 1.0)
        work = (
            df_source.with_columns(
                [
                    pl.col("datum").cast(pl.Date, strict=False).alias("datum"),
                    pl.col("asset_rollup").cast(pl.Utf8).str.strip_chars().str.to_uppercase().alias("asset_rollup"),
                    pl.col("totaal_v2").cast(pl.Float64, strict=False).alias("waarde"),
                ]
            )
            .join(meta_df, on="asset_rollup", how="left")
            .with_columns(
                [
                    pl.col("regio").fill_null(""),
                    pl.col("value_grow").fill_null(""),
                    pl.col("sector").fill_null(""),
                    pl.when(pl.col("regio") == "US").then(pl.col("waarde") / eurusd).otherwise(pl.col("waarde")).alias("waarde"),
                ]
            )
            .filter(pl.col("datum").is_not_null() & (pl.col("datum") <= schedule[-1]))
            .select(["datum", "asset_rollup", "sector", "regio", "value_grow", "waarde"])
            .sort(["asset_rollup", "datum"])
        )
        work = self._apply_selection_filter(work, "sector", self._selected_sectors)
        work = self._apply_selection_filter(work, "regio", self._selected_regios)
        work = self._apply_selection_filter(work, "value_grow", self._selected_value_grows)
        return work

    def _build_series_payload(self) -> dict[str, object]:
        schedule = _append_today_if_needed(
            _schedule_dates(self._start_date, self._end_date, self._frequency),
            self._end_date,
        )
        meta_df = self._metadata_df()
        work = self._filtered_work_df(schedule)
        if not schedule:
            return {
                "points": [],
                "split_series": [],
                "meta": {"asset_count": 0, "moment_count": 0, "frequency": self._frequency, "latest_value": None},
            }
        if work.is_empty():
            return {
                "points": [{"date": dt.isoformat(), "label": dt.strftime("%d-%m-%Y"), "value": None} for dt in schedule],
                "split_series": [],
                "meta": {"asset_count": 0, "moment_count": len(schedule), "frequency": self._frequency, "latest_value": None},
            }

        assets = (
            work.select(["asset_rollup"])
            .unique()
            .sort("asset_rollup")
            .with_columns(pl.lit(1).alias("_k"))
        )
        schedule_df = (
            pl.DataFrame({"datum": schedule})
            .with_columns(pl.lit(1).alias("_k"))
            .join(assets, on="_k", how="inner")
            .drop("_k")
            .with_columns([pl.lit(None).cast(pl.Float64).alias("waarde"), pl.lit(1).alias("_is_schedule")])
        )
        combined = (
            pl.concat([work.select(["datum", "asset_rollup", "waarde"]).with_columns(pl.lit(0).alias("_is_schedule")), schedule_df], how="diagonal_relaxed")
            .sort(["asset_rollup", "datum", "_is_schedule"])
            .with_columns(pl.col("waarde").fill_null(strategy="forward").over("asset_rollup"))
            .filter(pl.col("_is_schedule") == 1)
            .sort("datum")
        )
        series_df = (
            combined.group_by("datum")
            .agg(pl.col("waarde").sum().alias("value"))
            .sort("datum")
        )
        latest_value = None
        points: list[dict[str, object]] = []
        value_map = {row["datum"]: row.get("value") for row in series_df.to_dicts()}
        for dt in schedule:
            raw_val = value_map.get(dt)
            val = float(raw_val) if raw_val is not None else None
            if val is not None:
                latest_value = val
            points.append({"date": dt.isoformat(), "label": dt.strftime("%d-%m-%Y"), "value": val})
        split_series: list[dict[str, object]] = []

        def _build_group_split_series(group_col: str, prefix: str, dash: str) -> list[dict[str, object]]:
            labels = (
                work.select([group_col])
                .filter(pl.col(group_col).cast(pl.Utf8).str.len_chars() > 0)
                .unique()
                .sort(group_col)
                .to_dicts()
            )
            cumulative_by_date: dict[date, float] = {dt: 0.0 for dt in schedule}
            out: list[dict[str, object]] = []
            for row in labels:
                group_name = str(row.get(group_col) or "").strip()
                if not group_name:
                    continue
                group_work = work.filter(pl.col(group_col) == group_name)
                group_assets = (
                    group_work.select(["asset_rollup"])
                    .unique()
                    .sort("asset_rollup")
                    .with_columns(pl.lit(1).alias("_k"))
                )
                group_schedule_df = (
                    pl.DataFrame({"datum": schedule})
                    .with_columns(pl.lit(1).alias("_k"))
                    .join(group_assets, on="_k", how="inner")
                    .drop("_k")
                    .with_columns([pl.lit(None).cast(pl.Float64).alias("waarde"), pl.lit(1).alias("_is_schedule")])
                )
                group_combined = (
                    pl.concat(
                        [group_work.select(["datum", "asset_rollup", "waarde"]).with_columns(pl.lit(0).alias("_is_schedule")), group_schedule_df],
                        how="diagonal_relaxed",
                    )
                    .sort(["asset_rollup", "datum", "_is_schedule"])
                    .with_columns(pl.col("waarde").fill_null(strategy="forward").over("asset_rollup"))
                    .filter(pl.col("_is_schedule") == 1)
                    .sort("datum")
                )
                group_series_df = (
                    group_combined.group_by("datum")
                    .agg(pl.col("waarde").sum().alias("value"))
                    .sort("datum")
                )
                group_value_map = {r["datum"]: r.get("value") for r in group_series_df.to_dicts()}
                group_points: list[dict[str, object]] = []
                for dt in schedule:
                    raw_val = group_value_map.get(dt)
                    base_val = float(raw_val) if raw_val is not None else 0.0
                    cumulative_by_date[dt] = cumulative_by_date.get(dt, 0.0) + base_val
                    group_points.append(
                        {
                            "date": dt.isoformat(),
                            "label": dt.strftime("%d-%m-%Y"),
                            "value": cumulative_by_date[dt],
                        }
                    )
                out.append({"name": group_name, "label": f"{prefix}: {group_name}", "dash": dash, "points": group_points})
            return out

        if self._split_sector:
            split_series.extend(_build_group_split_series("sector", "Sector", "4 4"))
        if self._split_value_grow:
            split_series.extend(_build_group_split_series("value_grow", "Value/Grow", "2 4"))
        if self._split_regio:
            split_series.extend(_build_group_split_series("regio", "Regio", "8 4"))
        return {
            "points": points,
            "split_series": split_series,
            "meta": {
                "asset_count": int(work.select("asset_rollup").unique().height),
                "asset_list": [
                    {
                        "asset_rollup": str(row.get("asset_rollup") or "").strip(),
                        "end_value": float(row.get("end_value")) if row.get("end_value") is not None else None,
                    }
                    for row in (
                        combined.group_by("asset_rollup")
                        .agg(pl.col("waarde").last().alias("end_value"))
                        .sort("asset_rollup")
                        .to_dicts()
                    )
                    if str(row.get("asset_rollup") or "").strip()
                ],
                "moment_count": len(schedule),
                "frequency": self._frequency,
                "latest_value": latest_value,
                "sector_count": len(self._options(meta_df, "sector")),
            },
        }

    def _publish_controls(self) -> None:
        meta_df = self._metadata_df()
        sector_options = self._options(meta_df, "sector")
        regio_options = self._options(meta_df, "regio")
        value_grow_options = self._options(meta_df, "value_grow")
        self._call_js(
            "syncControls",
            {
                "start_date": self._start_date.isoformat(),
                "end_date": self._end_date.isoformat(),
                "frequency": self._frequency,
                "sector_options": sector_options,
                "regio_options": regio_options,
                "value_grow_options": value_grow_options,
                "split_sector": bool(self._split_sector),
                "split_regio": bool(self._split_regio),
                "split_value_grow": bool(self._split_value_grow),
                "sector_selection": self._selection_payload(self._selected_sectors, sector_options),
                "regio_selection": self._selection_payload(self._selected_regios, regio_options),
                "value_grow_selection": self._selection_payload(self._selected_value_grows, value_grow_options),
            },
        )

    def _publish_series(self) -> None:
        self._call_js("renderSeries", self._build_series_payload())

    def _publish_all(self) -> None:
        self._publish_controls()
        self._publish_series()

    def _restore_saved_state(self) -> None:
        with contextlib.suppress(Exception):
            state = get_settings().get_month_end_chart_state()
            if not state:
                return
            start_date = _coerce_to_date(state.get("start_date"))
            end_date = _coerce_to_date(state.get("end_date"))
            if start_date is not None:
                self._start_date = start_date
            if end_date is not None:
                self._end_date = end_date
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
            get_settings().set_month_end_chart_state(
                {
                    "start_date": self._start_date.isoformat(),
                    "end_date": self._end_date.isoformat(),
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
        geo = get_settings().get_month_end_chart_window_geometry()
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
            get_settings().set_month_end_chart_window_geometry(g.x(), g.y(), g.width(), g.height())

    def _set_start_date(self, value: str) -> None:
        parsed = _coerce_to_date(value)
        if parsed is None:
            return
        self._start_date = parsed
        self._save_state()
        self._publish_series()

    def _set_end_date(self, value: str) -> None:
        parsed = _coerce_to_date(value)
        if parsed is None:
            return
        self._end_date = parsed
        self._save_state()
        self._publish_series()

    def _set_frequency(self, value: str) -> None:
        mode = str(value or "").strip()
        if mode not in {"daily", "weekly_friday", "third_friday", "month_end", "quarter_end", "year_end"}:
            return
        self._frequency = mode
        self._save_state()
        self._publish_series()

    @staticmethod
    def _parse_selection_payload(payload: str) -> set[str] | None:
        try:
            raw = json.loads(payload or "{}")
        except Exception:
            raw = {}
        mode = str(raw.get("mode") or "").strip().lower()
        selected = raw.get("selected") or []
        values = {str(v).strip() for v in selected if str(v).strip()}
        if mode == "all":
            return None
        return values

    def _set_sector_selection(self, payload: str) -> None:
        self._selected_sectors = self._parse_selection_payload(payload)
        self._save_state()
        self._publish_series()

    def _set_regio_selection(self, payload: str) -> None:
        self._selected_regios = self._parse_selection_payload(payload)
        self._save_state()
        self._publish_series()

    def _set_value_grow_selection(self, payload: str) -> None:
        self._selected_value_grows = self._parse_selection_payload(payload)
        self._save_state()
        self._publish_series()

    def _set_split_sector(self, value: bool) -> None:
        self._split_sector = bool(value)
        self._save_state()
        self._publish_series()

    def _set_split_regio(self, value: bool) -> None:
        self._split_regio = bool(value)
        self._save_state()
        self._publish_series()

    def _set_split_value_grow(self, value: bool) -> None:
        self._split_value_grow = bool(value)
        self._save_state()
        self._publish_series()

    def _html_template(self) -> str:
        return """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8"/>
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <style>
      :root{
        --bg:#f2ede3;
        --panel:#fbfaf7;
        --line:#d7cbb3;
        --line-strong:#8c7552;
        --text:#2f271b;
        --muted:#766c5e;
        --accent:#8c7552;
        --accent-soft:#e9ddc8;
      }
      *{ box-sizing:border-box; }
      body{
        margin:0;
        background:radial-gradient(circle at top left, #f7f1e3 0%, #efe7d7 52%, #ebe1cf 100%);
        color:var(--text);
        font-family:Segoe UI, Arial, sans-serif;
      }
      .shell{
        display:grid;
        grid-template-columns:300px minmax(0,1fr);
        height:100vh;
        min-height:0;
      }
      .sidebar{
        border-right:1px solid var(--line);
        background:rgba(251,250,247,.94);
        padding:14px;
        overflow:auto;
        min-height:0;
      }
      .main{
        display:flex;
        flex-direction:column;
        min-width:0;
        min-height:0;
        padding:14px;
        gap:12px;
      }
      .toolbar{
        display:flex;
        gap:10px;
        align-items:flex-start;
        justify-content:space-between;
        flex-wrap:wrap;
        padding:0;
        border:none;
        border-radius:0;
        background:transparent;
        box-shadow:none;
      }
      .toolbar-panel{
        display:flex;
        gap:10px;
        align-items:end;
        flex-wrap:wrap;
        padding:12px;
        border:1px solid var(--line);
        border-radius:14px;
        background:rgba(236,230,219,.92);
        box-shadow:0 10px 28px rgba(79,59,22,.08);
      }
      .toolbar-left{
        flex:0 0 auto;
        max-width:fit-content;
      }
      .toolbar-right{
        display:flex;
        flex:0 0 auto;
        max-width:fit-content;
      }
      .field{
        display:flex;
        flex-direction:column;
        gap:4px;
        min-width:150px;
      }
      .field label{
        font-size:11px;
        text-transform:uppercase;
        letter-spacing:.07em;
        color:var(--muted);
        font-weight:700;
      }
      .field input,.field select{
        height:36px;
        padding:0 10px;
        border:1px solid var(--line);
        border-radius:9px;
        background:#fffdf9;
        color:var(--text);
      }
      button.action{
        height:36px;
        padding:0 14px;
        border:1px solid var(--line-strong);
        border-radius:9px;
        background:var(--accent);
        color:#fffdf9;
        cursor:pointer;
        font-weight:700;
      }
      .summary{
        display:flex;
        gap:18px;
        align-items:flex-end;
        flex-wrap:nowrap;
      }
      .summary-inline{
        display:flex;
        align-items:baseline;
        gap:10px;
        white-space:nowrap;
      }
      .summary-item{
        display:inline-flex;
        align-items:baseline;
        gap:6px;
      }
      .summary-sep{
        color:var(--muted);
        font-weight:700;
      }
      .summary-key{
        font-size:10px;
        text-transform:uppercase;
        letter-spacing:.06em;
        color:var(--muted);
        font-weight:700;
      }
      .summary-value{
        font-size:18px;
        font-weight:800;
      }
      .summary-toggle{
        cursor:pointer;
        text-decoration:underline;
        text-underline-offset:2px;
      }
      .panel-title{
        font-size:12px;
        font-weight:800;
        color:var(--muted);
        letter-spacing:.06em;
        text-transform:uppercase;
      }
      .filter-group{
        margin-bottom:14px;
        padding:12px;
        border:1px solid var(--line);
        border-radius:12px;
        background:#fffdf9;
      }
      .filter-group h3{
        margin:0 0 8px 0;
        font-size:12px;
        text-transform:uppercase;
        letter-spacing:.06em;
        color:var(--muted);
      }
      .tog{
        display:flex;
        gap:6px;
        margin-bottom:8px;
      }
      .tog button{
        flex:1;
        height:30px;
        border:1px solid var(--line);
        border-radius:8px;
        background:var(--accent-soft);
        color:var(--text);
        cursor:pointer;
        font-weight:700;
      }
      .multi-select{
        width:100%;
        min-height:220px;
        border:1px solid var(--line);
        border-radius:10px;
        background:#fffdfa;
        color:var(--text);
        padding:4px;
        font-size:13px;
      }
      .chart-wrap{
        position:relative;
        flex:1 1 auto;
        min-height:0;
        border:1px solid var(--line);
        border-radius:18px;
        background:rgba(251,250,247,.94);
        overflow:hidden;
        box-shadow:0 14px 34px rgba(79,59,22,.08);
      }
      .chart-shell{
        display:flex;
        height:100%;
        min-height:0;
      }
      .chart-stage{
        position:relative;
        flex:1 1 auto;
        min-width:0;
        min-height:0;
      }
      .asset-panel{
        display:none;
        width:250px;
        flex:0 0 250px;
        border-left:1px solid var(--line);
        background:#f7f2e6;
        padding:12px;
        overflow:auto;
      }
      .asset-panel.visible{
        display:block;
      }
      .asset-panel h4{
        margin:0 0 10px 0;
        font-size:11px;
        text-transform:uppercase;
        letter-spacing:.06em;
        color:var(--muted);
      }
      .asset-list{
        display:flex;
        flex-direction:column;
        gap:6px;
      }
      .asset-item{
        padding:6px 8px;
        border:1px solid var(--line);
        border-radius:8px;
        background:#fffdfa;
        font-size:13px;
        color:var(--text);
      }
      #chart{
        width:100%;
        height:100%;
        min-height:0;
        display:block;
      }
      #no-data{
        position:absolute;
        inset:0;
        display:flex;
        align-items:center;
        justify-content:center;
        color:#a0927d;
        font-size:16px;
        pointer-events:none;
      }
    </style>
  </head>
  <body>
    <div class="shell">
      <div class="sidebar">
        <div class="panel-title">Filters</div>
        <div class="filter-group">
          <h3 style="display:flex;align-items:center;justify-content:space-between;gap:8px;">
            <span>Sector</span>
            <label style="display:flex;align-items:center;gap:6px;font-size:12px;text-transform:none;letter-spacing:0;color:var(--muted);">
              <input id="split_sector" type="checkbox" />
              <span>Split</span>
            </label>
          </h3>
          <div class="tog">
            <button onclick="setAll('sector', true)">Alles</button>
            <button onclick="setAll('sector', false)">Niets</button>
          </div>
          <select id="items-sector" class="multi-select" multiple></select>
        </div>
        <div class="filter-group">
          <h3 style="display:flex;align-items:center;justify-content:space-between;gap:8px;">
            <span>Value/Grow</span>
            <label style="display:flex;align-items:center;gap:6px;font-size:12px;text-transform:none;letter-spacing:0;color:var(--muted);">
              <input id="split_value_grow" type="checkbox" />
              <span>Split</span>
            </label>
          </h3>
          <div class="tog">
            <button onclick="setAll('value_grow', true)">Alles</button>
            <button onclick="setAll('value_grow', false)">Niets</button>
          </div>
          <select id="items-value-grow" class="multi-select" multiple></select>
        </div>
        <div class="filter-group">
          <h3 style="display:flex;align-items:center;justify-content:space-between;gap:8px;">
            <span>Regio</span>
            <label style="display:flex;align-items:center;gap:6px;font-size:12px;text-transform:none;letter-spacing:0;color:var(--muted);">
              <input id="split_regio" type="checkbox" />
              <span>Split</span>
            </label>
          </h3>
          <div class="tog">
            <button onclick="setAll('regio', true)">Alles</button>
            <button onclick="setAll('regio', false)">Niets</button>
          </div>
          <select id="items-regio" class="multi-select" multiple></select>
        </div>
      </div>
      <div class="main">
        <div class="toolbar">
          <div class="toolbar-panel toolbar-left">
            <div class="field">
              <label>Start</label>
              <input id="start_date" type="date" />
            </div>
            <div class="field">
              <label>Eind</label>
              <input id="end_date" type="date" />
            </div>
            <div class="field">
              <label>Timeframe</label>
              <select id="frequency">
                <option value="daily">Dagelijks</option>
                <option value="weekly_friday">Wekelijks vrijdag</option>
                <option value="third_friday">3e vrijdag</option>
                <option value="month_end">Maand eind</option>
                <option value="quarter_end">Q eind</option>
                <option value="year_end">Jaar eind</option>
              </select>
            </div>
            <button id="btn_refresh" class="action">Refresh</button>
          </div>
          <div class="toolbar-panel toolbar-right">
            <div class="summary">
              <div class="summary-inline">
                <span class="summary-item"><span class="summary-key">Eindwaarde</span><span class="summary-value" id="latest_value">-</span></span>
                <span class="summary-sep">/</span>
                <span class="summary-item"><span class="summary-key">Meetmomenten</span><span class="summary-value" id="moment_count">0</span></span>
                <span class="summary-sep">/</span>
                <span class="summary-item"><span class="summary-key summary-toggle" id="assets_toggle">Assets</span><span class="summary-value summary-toggle" id="asset_count">0</span></span>
              </div>
            </div>
          </div>
        </div>
        <div class="chart-wrap">
          <div class="chart-shell">
            <div class="chart-stage">
              <svg id="chart" preserveAspectRatio="none"></svg>
              <div id="no-data">Geen data voor deze selectie.</div>
            </div>
            <aside id="asset_panel" class="asset-panel">
              <h4>Assets In Scope</h4>
              <div id="asset_list" class="asset-list"></div>
            </aside>
          </div>
        </div>
      </div>
    </div>
    <script>
      const bridgeState = { bridge: null };
      const PALETTE = ["#B23A48","#437F97","#4D9078","#8F5DB7","#C17C00","#2D6A4F","#6B705C","#6D597A","#BC6C25","#3D5A80","#C44536","#6A994E"];
      const state = {
        points: [],
        sectorSeries: [],
        assetList: [],
        showAssets: false,
        selections: {
          sector: { mode: "all", selected: [] },
          value_grow: { mode: "all", selected: [] },
          regio: { mode: "all", selected: [] }
        }
      };
      const groupMeta = {
        sector: { container: "items-sector", bridge: "setSectorSelection" },
        value_grow: { container: "items-value-grow", bridge: "setValueGrowSelection" },
        regio: { container: "items-regio", bridge: "setRegioSelection" }
      };
      function fmtNumber(v){
        if(v===null || v===undefined || !Number.isFinite(v)) return "-";
        return Math.round(v).toString().replace(/\\B(?=(\\d{3})+(?!\\d))/g,".");
      }
      function sendSelection(key){
        const meta = groupMeta[key];
        const select = document.getElementById(meta.container);
        if(!select) return;
        const options = Array.from(select.options);
        const checked = options.filter(n => n.selected).map(n => n.value);
        const allChecked = options.length > 0 && checked.length === options.length;
        const payload = allChecked ? { mode: "all", selected: [] } : { mode: "custom", selected: checked };
        state.selections[key] = payload;
        const fn = bridgeState.bridge?.[meta.bridge];
        if(typeof fn === "function"){
          fn(JSON.stringify(payload));
        }
      }
      function buildGroup(key, options, selection){
        const meta = groupMeta[key];
        const root = document.getElementById(meta.container);
        if(!root) return;
        const mode = (selection && selection.mode) || "all";
        const selected = new Set((selection && selection.selected) || []);
        root.innerHTML = "";
        (options || []).forEach(value => {
          const opt = document.createElement("option");
          opt.value = String(value);
          opt.textContent = String(value);
          opt.selected = mode === "all" ? true : selected.has(String(value));
          root.appendChild(opt);
        });
        root.onchange = () => sendSelection(key);
      }
      function setAll(key, checked){
        const meta = groupMeta[key];
        const select = document.getElementById(meta.container);
        if(!select) return;
        Array.from(select.options).forEach(node => {
          node.selected = checked;
        });
        sendSelection(key);
      }
      function bindDateCommit(id, setter){
        const el = document.getElementById(id);
        if(!el) return;
        const commit = () => setter?.(el.value || "");
        el.addEventListener("blur", commit);
        el.addEventListener("keydown", (e) => {
          if(e.key === "Enter"){
            commit();
            el.blur();
          }
        });
      }
      function bindUi(){
        document.getElementById("btn_refresh")?.addEventListener("click", ()=> bridgeState.bridge?.refresh?.());
        bindDateCommit("start_date", (value) => bridgeState.bridge?.setStartDate?.(value));
        bindDateCommit("end_date", (value) => bridgeState.bridge?.setEndDate?.(value));
        document.getElementById("frequency")?.addEventListener("change", (e)=> bridgeState.bridge?.setFrequency?.(e.target.value || ""));
        document.getElementById("assets_toggle")?.addEventListener("click", toggleAssetsPanel);
        document.getElementById("asset_count")?.addEventListener("click", toggleAssetsPanel);
        document.getElementById("split_sector")?.addEventListener("change", (e)=> bridgeState.bridge?.setSplitSector?.(!!e.target.checked));
        document.getElementById("split_value_grow")?.addEventListener("change", (e)=> bridgeState.bridge?.setSplitValueGrow?.(!!e.target.checked));
        document.getElementById("split_regio")?.addEventListener("change", (e)=> bridgeState.bridge?.setSplitRegio?.(!!e.target.checked));
        if(window.ResizeObserver){
          const wrap = document.querySelector(".chart-stage");
          if(wrap){
            const obs = new ResizeObserver(() => {
              if(state.points && state.points.length){
                drawChart(state.points, state.sectorSeries);
              }
            });
            obs.observe(wrap);
          }
        } else {
          window.addEventListener("resize", () => {
            if(state.points && state.points.length){
              drawChart(state.points, state.sectorSeries);
            }
          });
        }
      }
      function renderAssetPanel(){
        const panel = document.getElementById("asset_panel");
        const list = document.getElementById("asset_list");
        if(!panel || !list) return;
        panel.classList.toggle("visible", !!state.showAssets);
        list.innerHTML = "";
        (state.assetList || []).forEach(asset => {
          const item = document.createElement("div");
          item.className = "asset-item";
          const name = String(asset.asset_rollup || "");
          const endValue = fmtNumber(asset.end_value);
          item.textContent = endValue === "-" ? name : `${name}  |  ${endValue}`;
          list.appendChild(item);
        });
      }
      function toggleAssetsPanel(){
        state.showAssets = !state.showAssets;
        renderAssetPanel();
        if(state.points && state.points.length){
          drawChart(state.points, state.sectorSeries);
        }
      }
      function yTicks(minV, maxV){
        const steps = 4;
        const out = [];
        for(let i = 0; i <= steps; i++){
          const ratio = i / steps;
          out.push(maxV - (maxV - minV) * ratio);
        }
        return out;
      }
      function subsampleIndexes(indexes, maxCount){
        const unique = Array.from(new Set(indexes)).sort((a,b) => a - b);
        if(unique.length <= maxCount) return unique;
        const out = [];
        for(let i = 0; i < maxCount; i++){
          const pos = Math.round((i * (unique.length - 1)) / (maxCount - 1));
          out.push(unique[pos]);
        }
        return Array.from(new Set(out)).sort((a,b) => a - b);
      }
      function buildLabelIndexes(valid){
        if(valid.length <= 1) return [0];
        const freq = document.getElementById("frequency")?.value || "third_friday";
        const candidates = [0, valid.length - 1];
        valid.forEach((point, idx) => {
          const dt = new Date(point.date);
          if(Number.isNaN(dt.getTime())) return;
          if(freq === "daily"){
            const isWeekEnd = dt.getDay() === 5;
            const prev = idx > 0 ? new Date(valid[idx - 1].date) : null;
            const next = idx + 1 < valid.length ? new Date(valid[idx + 1].date) : null;
            const monthStarts = prev && dt.getMonth() !== prev.getMonth();
            const monthEnds = next && dt.getMonth() !== next.getMonth();
            if(isWeekEnd || monthStarts || monthEnds){
              candidates.push(idx);
            }
          } else if(freq === "weekly_friday"){
            if(idx % 2 === 0) candidates.push(idx);
          } else {
            candidates.push(idx);
          }
        });
        return subsampleIndexes(candidates, 25);
      }
      function drawChart(points, splitSeries){
        const svg = document.getElementById("chart");
        const noData = document.getElementById("no-data");
        if(!svg) return;
        svg.innerHTML = "";
        const valid = (points || []).filter(p => typeof p.value === "number" && Number.isFinite(p.value));
        const extraSeries = Array.isArray(splitSeries) ? splitSeries : [];
        noData.style.display = valid.length ? "none" : "flex";
        if(!valid.length){
          return;
        }
        const bounds = svg.getBoundingClientRect();
        const width = Math.max(Math.round(bounds.width || 1000), 720);
        const height = Math.max(Math.round(bounds.height || 520), 480);
        svg.setAttribute("width", String(width));
        svg.setAttribute("height", String(height));
        const margin = { top: 24, right: 28, bottom: 72, left: 94 };
        const innerW = width - margin.left - margin.right;
        const innerH = height - margin.top - margin.bottom;
        const allValues = valid.map(p => p.value);
        extraSeries.forEach(series => {
          (series.points || []).forEach(p => {
            if(typeof p.value === "number" && Number.isFinite(p.value)){
              allValues.push(p.value);
            }
          });
        });
        let minV = Math.min(...allValues);
        let maxV = Math.max(...allValues);
        if(minV === maxV){
          const delta = Math.abs(minV || 1) * 0.08;
          minV -= delta;
          maxV += delta;
        }
        const xAt = idx => margin.left + (valid.length === 1 ? innerW / 2 : (idx / (valid.length - 1)) * innerW);
        const yAt = value => margin.top + (1 - ((value - minV) / (maxV - minV))) * innerH;
        const ns = "http://www.w3.org/2000/svg";
        const bg = document.createElementNS(ns, "rect");
        bg.setAttribute("x", "0");
        bg.setAttribute("y", "0");
        bg.setAttribute("width", String(width));
        bg.setAttribute("height", String(height));
        bg.setAttribute("fill", "#fbfaf7");
        svg.appendChild(bg);
        yTicks(minV, maxV).forEach(tick => {
          const y = yAt(tick);
          const line = document.createElementNS(ns, "line");
          line.setAttribute("x1", String(margin.left));
          line.setAttribute("x2", String(width - margin.right));
          line.setAttribute("y1", String(y));
          line.setAttribute("y2", String(y));
          line.setAttribute("stroke", "#ddd1bc");
          line.setAttribute("stroke-width", "1");
          svg.appendChild(line);
          const txt = document.createElementNS(ns, "text");
          txt.setAttribute("x", String(margin.left - 12));
          txt.setAttribute("y", String(y + 4));
          txt.setAttribute("text-anchor", "end");
          txt.setAttribute("font-size", "12");
          txt.setAttribute("fill", "#7a6e5d");
          txt.textContent = fmtNumber(tick);
          svg.appendChild(txt);
        });
        const axisY = document.createElementNS(ns, "line");
        axisY.setAttribute("x1", String(margin.left));
        axisY.setAttribute("x2", String(margin.left));
        axisY.setAttribute("y1", String(margin.top));
        axisY.setAttribute("y2", String(height - margin.bottom));
        axisY.setAttribute("stroke", "#8c7552");
        axisY.setAttribute("stroke-width", "1.4");
        svg.appendChild(axisY);
        const axisX = document.createElementNS(ns, "line");
        axisX.setAttribute("x1", String(margin.left));
        axisX.setAttribute("x2", String(width - margin.right));
        axisX.setAttribute("y1", String(height - margin.bottom));
        axisX.setAttribute("y2", String(height - margin.bottom));
        axisX.setAttribute("stroke", "#8c7552");
        axisX.setAttribute("stroke-width", "1.4");
        svg.appendChild(axisX);
        if(minV <= 0 && maxV >= 0){
          const zeroY = yAt(0);
          const zeroLine = document.createElementNS(ns, "line");
          zeroLine.setAttribute("x1", String(margin.left));
          zeroLine.setAttribute("x2", String(width - margin.right));
          zeroLine.setAttribute("y1", String(zeroY));
          zeroLine.setAttribute("y2", String(zeroY));
          zeroLine.setAttribute("stroke", "#8c7552");
          zeroLine.setAttribute("stroke-width", "2");
          zeroLine.setAttribute("opacity", "0.9");
          svg.appendChild(zeroLine);
          const zeroLabel = document.createElementNS(ns, "text");
          zeroLabel.setAttribute("x", String(margin.left - 12));
          zeroLabel.setAttribute("y", String(zeroY + 4));
          zeroLabel.setAttribute("text-anchor", "end");
          zeroLabel.setAttribute("font-size", "12");
          zeroLabel.setAttribute("font-weight", "700");
          zeroLabel.setAttribute("fill", "#8c7552");
          zeroLabel.textContent = "0";
          svg.appendChild(zeroLabel);
        }
        extraSeries.forEach((series, seriesIdx) => {
          const splitValid = (series.points || []).filter(p => typeof p.value === "number" && Number.isFinite(p.value));
          if(!splitValid.length) return;
          const splitPath = document.createElementNS(ns, "path");
          const splitD = splitValid.map((p, idx) => {
            const originalIdx = (series.points || []).findIndex(sp => sp.date === p.date);
            const x = xAt(Math.max(originalIdx, 0));
            const y = yAt(p.value);
            return `${idx === 0 ? "M" : "L"} ${x} ${y}`;
          }).join(" ");
          splitPath.setAttribute("d", splitD);
          splitPath.setAttribute("fill", "none");
          splitPath.setAttribute("stroke", PALETTE[seriesIdx % PALETTE.length]);
          splitPath.setAttribute("stroke-width", "1");
          splitPath.setAttribute("stroke-dasharray", series.dash || "4 4");
          splitPath.setAttribute("stroke-linejoin", "round");
          splitPath.setAttribute("stroke-linecap", "round");
          splitPath.setAttribute("opacity", "0.95");
          svg.appendChild(splitPath);
        });
        const labelIndexes = new Set(buildLabelIndexes(valid));
        const path = document.createElementNS(ns, "path");
        const d = valid.map((p, idx) => `${idx === 0 ? "M" : "L"} ${xAt(idx)} ${yAt(p.value)}`).join(" ");
        path.setAttribute("d", d);
        path.setAttribute("fill", "none");
        path.setAttribute("stroke", "#8c7552");
        path.setAttribute("stroke-width", "2");
        path.setAttribute("stroke-linejoin", "round");
        path.setAttribute("stroke-linecap", "round");
        svg.appendChild(path);
        valid.forEach((point, idx) => {
          if(!labelIndexes.has(idx)) return;
          const x = xAt(idx);
          const label = document.createElementNS(ns, "text");
          label.setAttribute("x", String(x));
          label.setAttribute("y", String(height - margin.bottom + 18));
          label.setAttribute("text-anchor", "end");
          label.setAttribute("transform", `rotate(-35 ${x} ${height - margin.bottom + 18})`);
          label.setAttribute("font-size", "13");
          label.setAttribute("fill", "#7a6e5d");
          label.textContent = point.label;
          svg.appendChild(label);
        });
      }
      window.syncControls = function(payload){
        if(!payload) return;
        const s = document.getElementById("start_date");
        const e = document.getElementById("end_date");
        const f = document.getElementById("frequency");
        const split = document.getElementById("split_sector");
        const splitRegio = document.getElementById("split_regio");
        const splitValueGrow = document.getElementById("split_value_grow");
        if(s) s.value = payload.start_date || "";
        if(e) e.value = payload.end_date || "";
        if(f) f.value = payload.frequency || "third_friday";
        if(split) split.checked = !!payload.split_sector;
        if(splitRegio) splitRegio.checked = !!payload.split_regio;
        if(splitValueGrow) splitValueGrow.checked = !!payload.split_value_grow;
        buildGroup("sector", payload.sector_options || [], payload.sector_selection || { mode: "all", selected: [] });
        buildGroup("value_grow", payload.value_grow_options || [], payload.value_grow_selection || { mode: "all", selected: [] });
        buildGroup("regio", payload.regio_options || [], payload.regio_selection || { mode: "all", selected: [] });
      };
      window.renderSeries = function(payload){
        const points = (payload && payload.points) ? payload.points : [];
        const splitSeries = (payload && payload.split_series) ? payload.split_series : [];
        const meta = (payload && payload.meta) ? payload.meta : {};
        state.points = points;
        state.sectorSeries = splitSeries;
        state.assetList = (meta.asset_list || []);
        document.getElementById("latest_value").textContent = fmtNumber(meta.latest_value);
        document.getElementById("moment_count").textContent = String(meta.moment_count || 0);
        document.getElementById("asset_count").textContent = String(meta.asset_count || 0);
        renderAssetPanel();
        drawChart(points, splitSeries);
      };
      if(window.qt && window.QWebChannel){
        new QWebChannel(qt.webChannelTransport, function(channel){
          bridgeState.bridge = channel.objects.maandEindChartBridge || null;
          bindUi();
        });
      } else {
        bindUi();
      }
    </script>
  </body>
</html>
"""


class _MaandEindChartBridge(QObject):
    def __init__(self, dialog: MaandEindChartDialog):
        super().__init__(dialog)
        self._dialog = dialog

    @Slot(str)
    def setStartDate(self, value: str) -> None:
        self._dialog._set_start_date(value)

    @Slot(str)
    def setEndDate(self, value: str) -> None:
        self._dialog._set_end_date(value)

    @Slot(str)
    def setFrequency(self, value: str) -> None:
        self._dialog._set_frequency(value)

    @Slot(str)
    def setSectorSelection(self, payload: str) -> None:
        self._dialog._set_sector_selection(payload)

    @Slot(str)
    def setRegioSelection(self, payload: str) -> None:
        self._dialog._set_regio_selection(payload)

    @Slot(str)
    def setValueGrowSelection(self, payload: str) -> None:
        self._dialog._set_value_grow_selection(payload)

    @Slot(bool)
    def setSplitSector(self, value: bool) -> None:
        self._dialog._set_split_sector(value)

    @Slot(bool)
    def setSplitRegio(self, value: bool) -> None:
        self._dialog._set_split_regio(value)

    @Slot(bool)
    def setSplitValueGrow(self, value: bool) -> None:
        self._dialog._set_split_value_grow(value)

    @Slot()
    def refresh(self) -> None:
        self._dialog._publish_all()


_MONTH_END_CHART_DIALOG_INSTANCE: "MaandEindChartDialog | None" = None


def open_month_end_chart_dialog(
    start_date: date,
    end_date: date,
    frequency: str,
    filter_sector: str = "",
    filter_regio: str = "",
    filter_value_grow: str = "",
) -> None:
    global _MONTH_END_CHART_DIALOG_INSTANCE
    if _MONTH_END_CHART_DIALOG_INSTANCE is not None:
        try:
            _MONTH_END_CHART_DIALOG_INSTANCE.isVisible()
        except RuntimeError:
            _MONTH_END_CHART_DIALOG_INSTANCE = None
    if _MONTH_END_CHART_DIALOG_INSTANCE is None:
        _MONTH_END_CHART_DIALOG_INSTANCE = MaandEindChartDialog(None)
        _MONTH_END_CHART_DIALOG_INSTANCE.sync_from_maand_eind(
            start_date,
            end_date,
            frequency,
            filter_sector,
            filter_regio,
            filter_value_grow,
        )
    dlg = _MONTH_END_CHART_DIALOG_INSTANCE
    if dlg.windowState() & Qt.WindowMinimized:
        dlg.setWindowState(dlg.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
        dlg.showNormal()
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()


def close_month_end_chart_dialog() -> None:
    global _MONTH_END_CHART_DIALOG_INSTANCE
    if _MONTH_END_CHART_DIALOG_INSTANCE is not None:
        try:
            _MONTH_END_CHART_DIALOG_INSTANCE._force_close = True
            _MONTH_END_CHART_DIALOG_INSTANCE.close()
        except RuntimeError:
            pass
        _MONTH_END_CHART_DIALOG_INSTANCE = None
