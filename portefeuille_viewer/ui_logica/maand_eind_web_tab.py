from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import polars as pl
from PySide6.QtCore import QObject, QTimer, Slot
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from portefeuille_viewer.config import get_settings
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.signals import signals
from portefeuille_viewer.ui_logica.maand_eind_chart_dialog import open_month_end_chart_dialog
from portefeuille_viewer.ui_logica.maand_eind_compare_dialog import MonthEndCompareDialog
from portefeuille_viewer.ui_logica.maand_eind_diff_chart_dialog import open_month_end_diff_chart_dialog

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


def _date_label(dt: date) -> str:
    return f"{dt.day:02d}-{dt.month:02d}-{dt.year % 100:02d}"


class MaandEindWebTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._js_ready = False
        self._is_active = False
        self._loaded_once = False
        self._pending_js_calls: list[tuple[str, object]] = []
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(150)
        self._render_timer.timeout.connect(self._publish_snapshot)
        self._start_date = date.today() - timedelta(days=365)
        self._end_date = date.today()
        self._frequency = "third_friday"
        self._filter_regio = ""
        self._filter_value_grow = ""
        self._filter_sector = ""
        self._year_perf_period = "month"
        self._compare_dialog: MonthEndCompareDialog | None = None

        layout = QVBoxLayout(self)
        if QWebEngineView is None:
            layout.addWidget(QLabel("QtWebEngine niet beschikbaar in deze runtime."))
            return
        self.web = QWebEngineView(self)
        layout.addWidget(self.web)
        if QWebChannel is not None:
            self.channel = QWebChannel(self.web.page())
            self.bridge = _MaandEindWebBridge(self)
            self.channel.registerObject("maandEindBridge", self.bridge)
            self.web.page().setWebChannel(self.channel)
        self.web.loadFinished.connect(self._on_web_loaded)
        self.web.setHtml(self._html_template())
        signals.snapshotUpdated.connect(self._on_snapshot_updated)
        signals.stateRebuildFinished.connect(self._on_state_rebuild_finished)
        signals.databaseChanged.connect(self._on_database_changed)

    def set_active(self, active: bool):
        self._is_active = bool(active)
        if not self._is_active:
            self._render_timer.stop()
            return
        if not self._js_ready:
            return
        self._publish_controls()
        self._publish_snapshot()

    def _on_web_loaded(self, ok: bool):
        self._js_ready = bool(ok)
        if not self._js_ready:
            return
        for func_name, payload in self._pending_js_calls:
            self._run_js(func_name, payload)
        self._pending_js_calls.clear()
        self._publish_controls()
        if self._is_active:
            self._publish_snapshot()

    def _on_snapshot_updated(self, snapshot_key: str):
        if self._is_active and snapshot_key in {
            "repository_snapshot_per_dag_asset_result_v2",
            "repository_snapshot_asset_rollup_data",
        }:
            self._publish_controls()
            self._schedule_publish()

    def _on_state_rebuild_finished(self, payload: dict | None):
        if self._is_active and (payload or {}).get("status") == "ok":
            self._schedule_publish()

    def _on_database_changed(self, _db_name: str):
        self._loaded_once = False
        if self._is_active:
            self._publish_controls()
            self._schedule_publish()

    def _schedule_publish(self):
        if not self._is_active or not self._js_ready:
            return
        if not self._render_timer.isActive():
            self._render_timer.start()

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
        exprs = [
            pl.col("asset_rollup").cast(pl.Utf8).str.strip_chars().str.to_uppercase().alias("asset_rollup"),
            (pl.col("regio").cast(pl.Utf8, strict=False).fill_null("").alias("regio") if "regio" in df_meta.columns else pl.lit("").alias("regio")),
            (
                pl.col("value_grow").cast(pl.Utf8, strict=False).fill_null("").alias("value_grow")
                if "value_grow" in df_meta.columns
                else pl.lit("").alias("value_grow")
            ),
            (pl.col("sector").cast(pl.Utf8, strict=False).fill_null("").alias("sector") if "sector" in df_meta.columns else pl.lit("").alias("sector")),
        ]
        return (
            df_meta.with_columns(exprs)
            .select(["asset_rollup", "regio", "value_grow", "sector"])
            .unique(subset=["asset_rollup"], keep="first")
            .sort("asset_rollup")
        )

    def _publish_controls(self):
        meta_df = self._metadata_df()

        def _options(col: str) -> list[str]:
            if meta_df.is_empty() or col not in meta_df.columns:
                return []
            return sorted({str(v) for v in meta_df[col].to_list() if v is not None and str(v).strip()})

        self._call_js(
            "syncControls",
            {
                "start_date": self._start_date.isoformat(),
                "end_date": self._end_date.isoformat(),
                "frequency": self._frequency,
                "filter_regio": self._filter_regio,
                "filter_value_grow": self._filter_value_grow,
                "filter_sector": self._filter_sector,
                "regio_options": _options("regio"),
                "value_grow_options": _options("value_grow"),
                "sector_options": _options("sector"),
            },
        )

    def _build_matrix(
        self,
        df_source: pl.DataFrame,
        schedule: list[date],
        group_keys: list[str],
        apply_sector_filter: bool,
    ) -> pl.DataFrame:
        if not schedule or df_source is None or df_source.is_empty():
            return pl.DataFrame({group_keys[0]: []})
        if "datum" not in df_source.columns or "asset_rollup" not in df_source.columns or "totaal_v2" not in df_source.columns:
            return pl.DataFrame({group_keys[0]: []})

        meta_df = self._metadata_df()
        eurusd = float(get_settings().get_eurusd() or 1.0)
        work = (
            df_source.with_columns(
                [
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
        )
        if self._filter_regio:
            work = work.filter(pl.col("regio") == self._filter_regio)
        if self._filter_value_grow:
            work = work.filter(pl.col("value_grow") == self._filter_value_grow)
        if apply_sector_filter and self._filter_sector:
            work = work.filter(pl.col("sector") == self._filter_sector)
        work = work.select(["datum", "asset_rollup", "value_grow", "sector", "regio", "waarde"]).sort(["asset_rollup", "datum"])
        if work.is_empty():
            return pl.DataFrame({group_keys[0]: []})

        if group_keys == ["sector"]:
            work = (
                work.group_by(["datum", "sector"])
                .agg(pl.col("waarde").sum().alias("waarde"))
                .sort(["sector", "datum"])
            )

        assets = (
            work.select(group_keys)
            .unique()
            .sort(group_keys[0])
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
            pl.concat([work.with_columns(pl.lit(0).alias("_is_schedule")), schedule_df], how="diagonal_relaxed")
            .sort([group_keys[0], "datum", "_is_schedule"])
            .with_columns(pl.col("waarde").fill_null(strategy="forward").over(group_keys[0]))
            .filter(pl.col("_is_schedule") == 1)
            .sort([group_keys[0], "datum"])
        )
        if combined.is_empty():
            return pl.DataFrame({group_keys[0]: []})

        pivot = combined.pivot(index=group_keys, on="datum", values="waarde")
        rename_map = {}
        for col in pivot.columns:
            if col in set(group_keys):
                continue
            dt = _coerce_to_date(col)
            if dt is not None:
                rename_map[col] = _date_label(dt)
        if rename_map:
            pivot = pivot.rename(rename_map)
        date_cols = [c for c in pivot.columns if c not in group_keys]
        if group_keys == ["sector"]:
            return (
                pivot.with_columns(
                    [
                        pl.col("sector").alias("asset_rollup"),
                        pl.lit("").alias("value_grow"),
                        pl.lit("").alias("regio"),
                    ]
                )
                .select(["asset_rollup", "value_grow", "sector", "regio"] + date_cols)
                .sort("asset_rollup")
            )
        return pivot.select(group_keys + date_cols).sort(group_keys[0])

    def _build_year_performance_matrix(
        self,
        df_source: pl.DataFrame,
        anchor_date: date,
        group_keys: list[str],
        apply_sector_filter: bool,
        period: str = "month",
    ) -> pl.DataFrame:
        schedule = sorted(
            {
                anchor_date - timedelta(days=365),
                anchor_date - timedelta(days=365 * 2),
                anchor_date - timedelta(days=365 * 3),
                anchor_date - timedelta(days=365 * 4),
                anchor_date - timedelta(days=365 * 5),
                anchor_date,
            }
        )
        base = self._build_matrix(
            df_source,
            schedule,
            group_keys=group_keys,
            apply_sector_filter=apply_sector_filter,
        )
        if base is None or base.is_empty():
            return pl.DataFrame({group_keys[0]: []})

        anchor_col = _date_label(anchor_date)
        compare_cols = {
            "perf_1y": _date_label(anchor_date - timedelta(days=365)),
            "perf_2y": _date_label(anchor_date - timedelta(days=365 * 2)),
            "perf_3y": _date_label(anchor_date - timedelta(days=365 * 3)),
            "perf_4y": _date_label(anchor_date - timedelta(days=365 * 4)),
            "perf_5y": _date_label(anchor_date - timedelta(days=365 * 5)),
        }
        meta_cols = ["asset_rollup", "value_grow", "sector", "regio"]
        available_meta = [c for c in meta_cols if c in base.columns]
        if anchor_col not in base.columns:
            return base.select(available_meta).with_columns(
                [
                    pl.lit(None).cast(pl.Float64).alias("perf_1y"),
                    pl.lit(None).cast(pl.Float64).alias("perf_2y"),
                    pl.lit(None).cast(pl.Float64).alias("perf_3y"),
                    pl.lit(None).cast(pl.Float64).alias("perf_4y"),
                    pl.lit(None).cast(pl.Float64).alias("perf_5y"),
                ]
            )

        exprs = []
        for out_col, compare_col in compare_cols.items():
            divisor_map = (
                {"perf_1y": 52.0, "perf_2y": 104.0, "perf_3y": 156.0, "perf_4y": 208.0, "perf_5y": 260.0}
                if period == "week"
                else {"perf_1y": 12.0, "perf_2y": 24.0, "perf_3y": 36.0, "perf_4y": 48.0, "perf_5y": 60.0}
            )
            divisor = divisor_map[out_col]
            if compare_col in base.columns:
                exprs.append(
                    pl.when(pl.col(anchor_col).is_not_null())
                    .then(
                        (
                            pl.col(anchor_col).cast(pl.Float64, strict=False)
                            - pl.col(compare_col).cast(pl.Float64, strict=False).fill_null(0.0)
                        )
                        / divisor
                    )
                    .otherwise(None)
                    .alias(out_col)
                )
            else:
                exprs.append(
                    pl.when(pl.col(anchor_col).is_not_null())
                    .then(pl.col(anchor_col).cast(pl.Float64, strict=False) / divisor)
                    .otherwise(None)
                    .alias(out_col)
                )
        return base.select(available_meta + [anchor_col] + [c for c in compare_cols.values() if c in base.columns]).with_columns(exprs).select(
            available_meta + ["perf_1y", "perf_2y", "perf_3y", "perf_4y", "perf_5y"]
        )

    def _publish_snapshot(self):
        if not self._is_active or not self._js_ready:
            return
        today = date.today()
        anchor_date = min(self._end_date, today)
        schedule = _append_today_if_needed(
            _schedule_dates(self._start_date, self._end_date, self._frequency),
            self._end_date,
        )
        df_source = getattr(SNAPSHOT_STORE, "repository_snapshot_per_dag_asset_result_v2", None)
        asset_matrix = self._build_matrix(
            df_source,
            schedule,
            group_keys=["asset_rollup", "value_grow", "sector", "regio"],
            apply_sector_filter=True,
        )
        sector_matrix = self._build_matrix(
            df_source,
            schedule,
            group_keys=["sector"],
            apply_sector_filter=False,
        )
        asset_year_perf = self._build_year_performance_matrix(
            df_source,
            anchor_date,
            group_keys=["asset_rollup", "value_grow", "sector", "regio"],
            apply_sector_filter=True,
            period=self._year_perf_period,
        )
        sector_year_perf = self._build_year_performance_matrix(
            df_source,
            anchor_date,
            group_keys=["sector"],
            apply_sector_filter=False,
            period=self._year_perf_period,
        )
        self._loaded_once = True
        self._call_js(
            "renderSnapshot",
            {
                "asset_rows": asset_matrix.to_dicts() if hasattr(asset_matrix, "to_dicts") else [],
                "asset_cols": list(asset_matrix.columns),
                "asset_year_rows": asset_year_perf.to_dicts() if hasattr(asset_year_perf, "to_dicts") else [],
                "asset_year_cols": list(asset_year_perf.columns),
                "sector_rows": sector_matrix.to_dicts() if hasattr(sector_matrix, "to_dicts") else [],
                "sector_cols": list(sector_matrix.columns),
                "sector_year_rows": sector_year_perf.to_dicts() if hasattr(sector_year_perf, "to_dicts") else [],
                "sector_year_cols": list(sector_year_perf.columns),
                "meta": {
                    "asset_count": int(asset_matrix.height),
                    "sector_count": int(sector_matrix.height),
                    "moment_count": max(int(asset_matrix.width) - 4, 0),
                    "frequency": self._frequency,
                    "year_perf_anchor": anchor_date.isoformat(),
                    "year_perf_period": self._year_perf_period,
                    "loaded_once": self._loaded_once,
                },
            },
        )

    def _set_start_date(self, value: str):
        parsed = _coerce_to_date(value)
        if parsed is None:
            return
        self._start_date = parsed
        self._schedule_publish()

    def _set_end_date(self, value: str):
        parsed = _coerce_to_date(value)
        if parsed is None:
            return
        self._end_date = parsed
        self._schedule_publish()

    def _set_frequency(self, value: str):
        mode = str(value or "").strip()
        if mode not in {"daily", "weekly_friday", "third_friday", "month_end", "quarter_end", "year_end"}:
            return
        self._frequency = mode
        self._schedule_publish()

    def _set_filter_regio(self, value: str):
        self._filter_regio = str(value or "").strip()
        self._schedule_publish()

    def _set_filter_value_grow(self, value: str):
        self._filter_value_grow = str(value or "").strip()
        self._schedule_publish()

    def _set_filter_sector(self, value: str):
        self._filter_sector = str(value or "").strip()
        self._schedule_publish()

    def _toggle_year_perf_period(self):
        self._year_perf_period = "week" if self._year_perf_period == "month" else "month"
        self._schedule_publish()

    def _open_end_value_chart_dialog(self) -> None:
        open_month_end_chart_dialog(
            self._start_date,
            self._end_date,
            self._frequency,
            self._filter_sector,
            self._filter_regio,
            self._filter_value_grow,
        )

    def _open_diff_value_chart_dialog(self) -> None:
        open_month_end_diff_chart_dialog(
            self._start_date,
            self._end_date,
            self._frequency,
            self._filter_sector,
            self._filter_regio,
            self._filter_value_grow,
        )

    def _open_compare_dialog(self) -> None:
        if self._compare_dialog is None:
            self._compare_dialog = MonthEndCompareDialog(self, self)
        self._compare_dialog.show()
        self._compare_dialog.raise_()
        self._compare_dialog.activateWindow()

    def _html_template(self) -> str:
        return """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8"/>
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <style>
      :root{
        --bg:#f4f1e8;
        --panel:#fbfaf6;
        --line:#d4c8af;
        --line-strong:#a38f67;
        --head:#d9ccb1;
        --head-2:#eee4d1;
        --text:#2b261d;
        --muted:#6c6557;
        --pos-bg:#d8efcf;
        --pos-fg:#14611f;
        --neg-bg:#f5cfcf;
        --neg-fg:#9d1717;
      }
      *{ box-sizing:border-box; }
      body{ margin:0; padding:14px; background:linear-gradient(180deg,#efe8d8 0%,#f7f4ec 100%); color:var(--text); font-family:Segoe UI, Arial, sans-serif; }
      .shell{ display:flex; flex-direction:column; gap:10px; }
      .toolbar{ display:flex; gap:10px; align-items:end; flex-wrap:wrap; padding:12px; border:1px solid var(--line); border-radius:12px; background:rgba(251,250,246,.92); box-shadow:0 10px 24px rgba(73,57,22,.08); }
      .field{ display:flex; flex-direction:column; gap:4px; min-width:150px; }
      .field label{ font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); font-weight:700; }
      .field input,.field select{ height:34px; padding:0 10px; border:1px solid var(--line); border-radius:8px; background:#fffdf8; color:var(--text); }
      .field input.filter{ min-width:220px; }
      .toolbar button{ height:34px; padding:0 14px; border:1px solid var(--line-strong); border-radius:8px; background:#8d7651; color:#fffdf8; cursor:pointer; font-weight:700; }
      .meta{ padding:0 2px; font-size:12px; color:var(--muted); }
      .tables-row{ display:grid; grid-template-columns:minmax(0,4fr) minmax(0,4fr) minmax(0,2fr); gap:12px; align-items:start; }
      .panel{ display:flex; flex-direction:column; gap:6px; min-width:0; }
      .section-title{ font-size:12px; font-weight:800; color:var(--muted); letter-spacing:.04em; text-transform:uppercase; margin:2px 2px -2px 2px; }
      .table-wrap{ border:1px solid var(--line); border-radius:14px; overflow-x:scroll; overflow-y:auto; scrollbar-gutter:stable both-edges; background:var(--panel); max-height:62vh; box-shadow:0 12px 30px rgba(73,57,22,.08); }
      .table-pad{ display:inline-block; min-width:100%; padding-right:56px; }
      table{ border-collapse:separate; border-spacing:0; min-width:max-content; width:max-content; font-size:12px; }
      thead th{ position:sticky; top:0; z-index:3; padding:7px 10px; background:var(--head); border-bottom:1px solid var(--line-strong); border-right:1px solid var(--line); white-space:nowrap; text-align:right; font-weight:700; font-variant-numeric:tabular-nums; cursor:pointer; user-select:none; }
      thead th.asset{ left:0; z-index:4; text-align:left; background:var(--head-2); min-width:110px; max-width:110px; }
      thead th.meta-col{ text-align:left; min-width:72px; max-width:72px; }
      thead th[data-sort="asc"]::after{ content:" ↑"; }
      thead th[data-sort="desc"]::after{ content:" ↓"; }
      tbody td{ padding:5px 10px; border-right:1px solid #e5dcc9; border-bottom:1px solid #ece4d4; white-space:nowrap; text-align:right; font-variant-numeric:tabular-nums; background:#fbfaf6; }
      tbody td.asset{ position:sticky; left:0; z-index:2; text-align:left; font-weight:700; background:#f3ecdd; min-width:110px; max-width:110px; overflow:hidden; text-overflow:ellipsis; }
      tbody td.meta-col{ text-align:left; min-width:72px; max-width:72px; overflow:hidden; text-overflow:ellipsis; }
      tbody tr:nth-child(even) td{ background:#f8f4eb; }
      tbody tr:nth-child(even) td.asset{ background:#eee5d3; }
      tbody tr.total-row td{ position:sticky; bottom:0; z-index:3; background:#e4d6b8 !important; font-weight:800; border-top:2px solid var(--line-strong); }
      tbody tr.total-row td.asset{ background:#d9c8a3 !important; }
      td.pos{ background:var(--pos-bg) !important; color:var(--pos-fg); font-weight:700; }
      td.neg{ background:var(--neg-bg) !important; color:var(--neg-fg); font-weight:700; }
      td.empty{ color:#b3a995; }
    </style>
  </head>
  <body>
    <div class="shell">
      <div class="toolbar">
        <div class="field">
          <label>Start date</label>
          <input id="start_date" type="date" />
        </div>
        <div class="field">
          <label>Eind date</label>
          <input id="end_date" type="date" />
        </div>
        <div class="field">
          <label>Frequentie</label>
          <select id="frequency">
            <option value="third_friday">3e vrijdag maand</option>
            <option value="weekly_friday">Elke vrijdag</option>
            <option value="month_end">Laatste dag maand</option>
            <option value="quarter_end">Laatste dag kwartaal</option>
            <option value="year_end">Laatste dag jaar</option>
            <option value="daily">Elke dag</option>
          </select>
        </div>
        <div class="field">
          <label>Regio</label>
          <select id="filter_regio"><option value="">Alle regio's</option></select>
        </div>
        <div class="field">
          <label>Value/Grow</label>
          <select id="filter_value_grow"><option value="">Alles</option></select>
        </div>
        <div class="field">
          <label>Sector</label>
          <select id="filter_sector"><option value="">Alle sectoren</option></select>
        </div>
        <div class="field">
          <label>Asset filter</label>
          <input id="asset_filter" class="filter" placeholder="Zoek asset_rollup" />
        </div>
        <button id="btn_refresh">Refresh</button>
        <button id="btn_endvalue_chart">Eindwaarde Chart</button>
        <button id="btn_diff_chart">Verschil Chart</button>
        <button id="btn_compare_dates">Vergelijk Datums</button>
        <button id="btn_year_perf_period">Performance: maand</button>
      </div>
      <div class="meta" id="meta">Nog niet geladen.</div>
      <div class="tables-row">
        <div class="panel">
          <div class="section-title">Eindwaarden</div>
          <div class="table-wrap" id="wrap-values">
            <div class="table-pad">
              <table id="tbl_values">
                <thead><tr id="thead-row-values"></tr></thead>
                <tbody id="tbody-values"></tbody>
              </table>
            </div>
          </div>
        </div>
        <div class="panel">
          <div class="section-title">Verschil Met Vorige Meetdatum</div>
          <div class="table-wrap" id="wrap-diff">
            <div class="table-pad">
              <table id="tbl_diff">
                <thead><tr id="thead-row-diff"></tr></thead>
                <tbody id="tbody-diff"></tbody>
              </table>
            </div>
          </div>
        </div>
        <div class="panel">
          <div class="section-title">Performance Per Jaar</div>
          <div class="table-wrap" id="wrap-year-perf">
            <div class="table-pad">
              <table id="tbl_year_perf">
                <thead><tr id="thead-row-year-perf"></tr></thead>
                <tbody id="tbody-year-perf"></tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
      <div class="tables-row">
        <div class="panel">
          <div class="section-title">Sector Totaal</div>
          <div class="table-wrap" id="wrap-sector-values">
            <div class="table-pad">
              <table id="tbl_sector_values">
                <thead><tr id="thead-row-sector-values"></tr></thead>
                <tbody id="tbody-sector-values"></tbody>
              </table>
            </div>
          </div>
        </div>
        <div class="panel">
          <div class="section-title">Sector Diff</div>
          <div class="table-wrap" id="wrap-sector-diff">
            <div class="table-pad">
              <table id="tbl_sector_diff">
                <thead><tr id="thead-row-sector-diff"></tr></thead>
                <tbody id="tbody-sector-diff"></tbody>
              </table>
            </div>
          </div>
        </div>
        <div class="panel">
          <div class="section-title">Sector Performance Per Jaar</div>
          <div class="table-wrap" id="wrap-sector-year-perf">
            <div class="table-pad">
              <table id="tbl_sector_year_perf">
                <thead><tr id="thead-row-sector-year-perf"></tr></thead>
                <tbody id="tbody-sector-year-perf"></tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
    <script>
      const ASSET_META_COLS = new Set(["asset_rollup","value_grow","sector","regio"]);
      const SECTOR_META_COLS = new Set(["asset_rollup","value_grow","sector","regio"]);
      const DIFF_VISIBLE_ASSET_COLS = ["asset_rollup"];
      const DIFF_VISIBLE_SECTOR_COLS = ["asset_rollup"];
      const YEAR_PERF_VISIBLE_COLS = ["asset_rollup","perf_1y","perf_2y","perf_3y","perf_4y","perf_5y"];
      const assetState = { cols: [], rows: [], filters: { asset: "" }, sort: { source: "values", col: "asset_rollup", dir: "asc" }, syncing:false };
      const sectorState = { cols: [], rows: [], filters: {}, sort: { source: "values", col: "asset_rollup", dir: "asc" }, syncing:false };
      const assetYearState = { cols: [], rows: [], filters: { asset: "" }, sort: { source: "year", col: "asset_rollup", dir: "asc" }, syncing:false };
      const sectorYearState = { cols: [], rows: [], filters: {}, sort: { source: "year", col: "asset_rollup", dir: "asc" }, syncing:false };
      const bridgeState = { bridge: null };
      let yearPerfPeriod = "month";
      function refillSelect(id, options, current, emptyLabel){
        const el=document.getElementById(id);
        if(!el) return;
        el.innerHTML = "";
        const base=document.createElement("option");
        base.value="";
        base.textContent=emptyLabel;
        el.appendChild(base);
        (options||[]).forEach(v=>{
          const opt=document.createElement("option");
          opt.value=String(v);
          opt.textContent=String(v);
          el.appendChild(opt);
        });
        el.value = current || "";
      }
      function fmt(v){
        if(v===null||v===undefined||v==="") return "";
        if(typeof v==="number" && Number.isFinite(v)) return Math.round(v).toString().replace(/\\B(?=(\\d{3})+(?!\\d))/g,".");
        return String(v);
      }
      function num(v){ return (typeof v==="number" && Number.isFinite(v)) ? v : null; }
      function cssFor(v){
        if(typeof v!=="number" || !Number.isFinite(v)) return "empty";
        if(v>0) return "pos";
        if(v<0) return "neg";
        return "";
      }
      function compareRows(a,b,col,dir, metaCols){
        if(metaCols.has(col)){
          const cmp = String(a[col]||"").localeCompare(String(b[col]||""));
          return dir==="asc" ? cmp : -cmp;
        }
        const av = num(a[col]);
        const bv = num(b[col]);
        if(av===null && bv===null) return 0;
        if(av===null) return 1;
        if(bv===null) return -1;
        const cmp = av-bv;
        return dir==="asc" ? cmp : -cmp;
      }
      function visibleRows(tableState, key){
        const needle=(tableState.filters[key]||"").trim().toLowerCase();
        if(!needle) return tableState.rows;
        return tableState.rows.filter(r => String(r[key]||"").toLowerCase().includes(needle));
      }
      function buildTotalRow(rows, cols, labelKey, metaCols){
        const out = {};
        cols.forEach(c => out[c] = "");
        out[labelKey] = "Totaal";
        for(const col of cols){
          if(metaCols.has(col)) continue;
          let total = 0;
          let hasAny = false;
          for(const row of rows){
            const v = num(row[col]);
            if(v!==null){ total += v; hasAny = true; }
          }
          out[col] = hasAny ? total : null;
        }
        return out;
      }
      function headerLabel(col, firstColLabel){
        if(col==="asset_rollup" && firstColLabel) return firstColLabel;
        if(col==="asset_rollup") return "Asset";
        if(col==="value_grow") return "Value/Grow";
        if(col==="sector") return "Sector";
        if(col==="regio") return "Regio";
        const suffix = yearPerfPeriod === "week" ? "wk" : "mnd";
        if(col==="perf_1y") return `1Y / ${suffix}`;
        if(col==="perf_2y") return `2Y / ${suffix}`;
        if(col==="perf_3y") return `3Y / ${suffix}`;
        if(col==="perf_4y") return `4Y / ${suffix}`;
        if(col==="perf_5y") return `5Y / ${suffix}`;
        return col;
      }
      function visibleColsFor(tableState, source, metaCols, diffVisibleCols){
        if(source==="diff"){
          const dateCols = tableState.cols.filter(c => !metaCols.has(c));
          return diffVisibleCols.concat(dateCols);
        }
        if(source==="year"){
          return YEAR_PERF_VISIBLE_COLS.filter(c => tableState.cols.includes(c));
        }
        return tableState.cols;
      }
      function diffRows(sortedRows, cols, metaCols){
        const dateCols = cols.filter(c => !metaCols.has(c));
        return sortedRows.map(row => {
          const out = {...row};
          let prev = null;
          for(const col of dateCols){
            const cur = num(row[col]);
            out[col] = (cur===null || prev===null) ? null : (cur - prev);
            if(cur!==null) prev = cur;
          }
          return out;
        });
      }
      function renderHeader(targetId, source, tableState, metaCols, diffVisibleCols, firstColLabel){
        const tr=document.getElementById(targetId);
        tr.innerHTML="";
        const cols = visibleColsFor(tableState, source, metaCols, diffVisibleCols);
        cols.forEach((col,idx)=>{
          const th=document.createElement("th");
          th.textContent=headerLabel(col, idx===0 ? firstColLabel : "");
          if(idx===0) th.className="asset";
          if(col!=="asset_rollup" && col!=="sector" && metaCols.has(col)) th.classList.add("meta-col");
          if(col===tableState.sort.col && tableState.sort.source===source) th.dataset.sort = tableState.sort.dir;
          th.onclick = ()=>{
            const isSectorHeader = targetId.includes("sector");
            if(source !== "year"){
              if(isSectorHeader){
                sectorYearState.sort = { source: "", col: "", dir: "asc" };
              } else {
                assetYearState.sort = { source: "", col: "", dir: "asc" };
              }
            }
            if(tableState.sort.col===col && tableState.sort.source===source){
              tableState.sort.dir = tableState.sort.dir==="asc" ? "desc" : "asc";
            } else {
              tableState.sort.source = source;
              tableState.sort.col = col;
              tableState.sort.dir = metaCols.has(col) ? "asc" : "desc";
            }
            rerenderAll();
          };
          tr.appendChild(th);
        });
      }
      function syncVerticalPair(leftId, rightId, tableState){
        const left=document.getElementById(leftId);
        const right=document.getElementById(rightId);
        if(!left || !right) return;
        left.addEventListener("scroll", ()=>{
          if(tableState.syncing) return;
          tableState.syncing = true;
          right.scrollTop = left.scrollTop;
          tableState.syncing = false;
        });
        right.addEventListener("scroll", ()=>{
          if(tableState.syncing) return;
          tableState.syncing = true;
          left.scrollTop = right.scrollTop;
          tableState.syncing = false;
        });
      }
      function syncVerticalGroup(ids, tableState){
        const nodes = ids.map(id => document.getElementById(id)).filter(Boolean);
        if(nodes.length < 2) return;
        nodes.forEach(node => {
          node.addEventListener("scroll", ()=>{
            if(tableState.syncing) return;
            tableState.syncing = true;
            const top = node.scrollTop;
            nodes.forEach(other => {
              if(other !== node) other.scrollTop = top;
            });
            tableState.syncing = false;
          });
        });
      }
      function syncHorizontalGroup(ids){
        const nodes = ids.map(id => document.getElementById(id)).filter(Boolean);
        if(nodes.length < 2) return;
        const state = { syncing: false };
        nodes.forEach(node => {
          node.addEventListener("scroll", ()=>{
            if(state.syncing) return;
            state.syncing = true;
            const left = node.scrollLeft;
            nodes.forEach(other => {
              if(other !== node) other.scrollLeft = left;
            });
            state.syncing = false;
          });
        });
      }
      function renderTableBody(bodyId, rows, source, tableState, metaCols, diffVisibleCols, labelKey){
        const body=document.getElementById(bodyId);
        if(!body) return;
        const cols = visibleColsFor(tableState, source, metaCols, diffVisibleCols);
        body.innerHTML="";
        for(const row of rows){
          const tr=document.createElement("tr");
          cols.forEach((col,idx)=>{
            const td=document.createElement("td");
            const v=row[col];
            td.textContent=fmt(v);
            if(idx===0){
              td.className="asset";
            }else if(metaCols.has(col)){
              td.classList.add("meta-col");
            }else{
              const cls=cssFor(v);
              if(cls) td.classList.add(cls);
            }
            if(v===null||v===undefined||v==="") td.classList.add("empty");
            tr.appendChild(td);
          });
          body.appendChild(tr);
        }
        if(rows.length){
          const totalRow = buildTotalRow(rows, cols, labelKey, metaCols);
          const tr=document.createElement("tr");
          tr.className="total-row";
          cols.forEach((col,idx)=>{
            const td=document.createElement("td");
            const v=totalRow[col];
            td.textContent=fmt(v);
            if(idx===0){
              td.className="asset";
            }else if(metaCols.has(col)){
              td.classList.add("meta-col");
            }else{
              const cls=cssFor(v);
              if(cls) td.classList.add(cls);
            }
            if(v===null||v===undefined||v==="") td.classList.add("empty");
            tr.appendChild(td);
          });
          body.appendChild(tr);
        }
      }
      function renderYearTableBody(bodyId, orderedRows, yearRows, source, tableState, metaCols, diffVisibleCols, labelKey){
        const body=document.getElementById(bodyId);
        if(!body) return;
        const cols = visibleColsFor(tableState, source, metaCols, diffVisibleCols);
        const byKey = new Map((yearRows||[]).map(r => [String(r[labelKey]||""), r]));
        const rows = orderedRows.map(r => byKey.get(String(r[labelKey]||"")) || {[labelKey]: r[labelKey]}).filter(Boolean);
        body.innerHTML="";
        for(const row of rows){
          const tr=document.createElement("tr");
          cols.forEach((col,idx)=>{
            const td=document.createElement("td");
            const v=row[col];
            td.textContent=fmt(v);
            if(idx===0){
              td.className="asset";
            }else{
              const cls=cssFor(v);
              if(cls) td.classList.add(cls);
            }
            if(v===null||v===undefined||v==="") td.classList.add("empty");
            tr.appendChild(td);
          });
          body.appendChild(tr);
        }
        if(rows.length){
          const totalRow = buildTotalRow(rows, cols, labelKey, new Set([labelKey]));
          const tr=document.createElement("tr");
          tr.className="total-row";
          cols.forEach((col,idx)=>{
            const td=document.createElement("td");
            const v=totalRow[col];
            td.textContent=fmt(v);
            if(idx===0){
              td.className="asset";
            }else{
              const cls=cssFor(v);
              if(cls) td.classList.add(cls);
            }
            if(v===null||v===undefined||v==="") td.classList.add("empty");
            tr.appendChild(td);
          });
          body.appendChild(tr);
        }
      }
      function orderByYearTable(baseRows, yearState, labelKey){
        const byKey = new Map((yearState.rows||[]).map(r => [String(r[labelKey]||""), r]));
        if(yearState.sort.source !== "year" || !yearState.sort.col){
          return baseRows;
        }
        return baseRows.slice().sort((a,b)=>{
          const ar = byKey.get(String(a[labelKey]||"")) || {};
          const br = byKey.get(String(b[labelKey]||"")) || {};
          return compareRows(ar, br, yearState.sort.col, yearState.sort.dir, new Set([labelKey]));
        });
      }
      function renderBody(tableState, metaCols, diffVisibleCols, valuesBodyId, diffBodyId, labelKey){
        const baseRows=visibleRows(tableState, labelKey).slice();
        const rowsForValues = baseRows.slice();
        const rowsForDiff = diffRows(baseRows, tableState.cols, metaCols);
        let order = baseRows.slice();
        if(tableState.sort.source==="values"){
          order = rowsForValues.slice().sort((a,b)=>compareRows(a,b,tableState.sort.col,tableState.sort.dir, metaCols));
        } else {
          const sortedDiff = rowsForDiff.slice().sort((a,b)=>compareRows(a,b,tableState.sort.col,tableState.sort.dir, metaCols));
          const keyCols = Array.from(metaCols);
          const keyOrder = sortedDiff.map(r => keyCols.map(k => String(r[k]||"")).join("__"));
          const valueMap = new Map(rowsForValues.map(r => [keyCols.map(k => String(r[k]||"")).join("__"), r]));
          order = keyOrder.map(k => valueMap.get(k)).filter(Boolean);
        }
        renderTableBody(valuesBodyId, order, "values", tableState, metaCols, diffVisibleCols, labelKey);
        renderTableBody(diffBodyId, diffRows(order, tableState.cols, metaCols), "diff", tableState, metaCols, diffVisibleCols, labelKey);
        return order;
      }
      function rerenderAll(){
        renderHeader("thead-row-values","values", assetState, ASSET_META_COLS, DIFF_VISIBLE_ASSET_COLS, "Asset");
        renderHeader("thead-row-diff","diff", assetState, ASSET_META_COLS, DIFF_VISIBLE_ASSET_COLS, "Asset");
        renderHeader("thead-row-year-perf","year", assetYearState, new Set(["asset_rollup"]), [], "Asset");
        let orderedAssets = renderBody(assetState, ASSET_META_COLS, DIFF_VISIBLE_ASSET_COLS, "tbody-values", "tbody-diff", "asset_rollup");
        if(assetYearState.sort.source === "year"){
          orderedAssets = orderByYearTable(visibleRows(assetState, "asset_rollup").slice(), assetYearState, "asset_rollup");
          renderTableBody("tbody-values", orderedAssets, "values", assetState, ASSET_META_COLS, DIFF_VISIBLE_ASSET_COLS, "asset_rollup");
          renderTableBody("tbody-diff", diffRows(orderedAssets, assetState.cols, ASSET_META_COLS), "diff", assetState, ASSET_META_COLS, DIFF_VISIBLE_ASSET_COLS, "asset_rollup");
        }
        renderYearTableBody("tbody-year-perf", orderedAssets, assetYearState.rows, "year", assetYearState, new Set(["asset_rollup"]), [], "asset_rollup");
        renderHeader("thead-row-sector-values","values", sectorState, SECTOR_META_COLS, DIFF_VISIBLE_SECTOR_COLS, "Sector");
        renderHeader("thead-row-sector-diff","diff", sectorState, SECTOR_META_COLS, DIFF_VISIBLE_SECTOR_COLS, "Sector");
        renderHeader("thead-row-sector-year-perf","year", sectorYearState, new Set(["asset_rollup"]), [], "Sector");
        let orderedSectors = renderBody(sectorState, SECTOR_META_COLS, DIFF_VISIBLE_SECTOR_COLS, "tbody-sector-values", "tbody-sector-diff", "asset_rollup");
        if(sectorYearState.sort.source === "year"){
          orderedSectors = orderByYearTable(visibleRows(sectorState, "asset_rollup").slice(), sectorYearState, "asset_rollup");
          renderTableBody("tbody-sector-values", orderedSectors, "values", sectorState, SECTOR_META_COLS, DIFF_VISIBLE_SECTOR_COLS, "asset_rollup");
          renderTableBody("tbody-sector-diff", diffRows(orderedSectors, sectorState.cols, SECTOR_META_COLS), "diff", sectorState, SECTOR_META_COLS, DIFF_VISIBLE_SECTOR_COLS, "asset_rollup");
        }
        renderYearTableBody("tbody-sector-year-perf", orderedSectors, sectorYearState.rows, "year", sectorYearState, new Set(["asset_rollup"]), [], "asset_rollup");
      }
      function bindUi(){
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
        document.getElementById("asset_filter")?.addEventListener("input", (e)=>{
          assetState.filters.asset=e.target.value||"";
          assetYearState.filters.asset=e.target.value||"";
          rerenderAll();
        });
        document.getElementById("btn_refresh")?.addEventListener("click", ()=> bridgeState.bridge?.refresh?.());
        document.getElementById("btn_endvalue_chart")?.addEventListener("click", ()=> bridgeState.bridge?.openEndValueChart?.());
        document.getElementById("btn_diff_chart")?.addEventListener("click", ()=> bridgeState.bridge?.openDiffValueChart?.());
        document.getElementById("btn_compare_dates")?.addEventListener("click", ()=> bridgeState.bridge?.openCompareDates?.());
        document.getElementById("btn_year_perf_period")?.addEventListener("click", ()=> bridgeState.bridge?.toggleYearPerfPeriod?.());
        bindDateCommit("start_date", (value)=> bridgeState.bridge?.setStartDate?.(value));
        bindDateCommit("end_date", (value)=> bridgeState.bridge?.setEndDate?.(value));
        document.getElementById("frequency")?.addEventListener("change", (e)=> bridgeState.bridge?.setFrequency?.(e.target.value||""));
        document.getElementById("filter_regio")?.addEventListener("change", (e)=> bridgeState.bridge?.setFilterRegio?.(e.target.value||""));
        document.getElementById("filter_value_grow")?.addEventListener("change", (e)=> bridgeState.bridge?.setFilterValueGrow?.(e.target.value||""));
        document.getElementById("filter_sector")?.addEventListener("change", (e)=> bridgeState.bridge?.setFilterSector?.(e.target.value||""));
      }
      window.syncControls = function(payload){
        if(!payload) return;
        refillSelect("filter_regio", payload.regio_options || [], payload.filter_regio || "", "Alle regio's");
        refillSelect("filter_value_grow", payload.value_grow_options || [], payload.filter_value_grow || "", "Alles");
        refillSelect("filter_sector", payload.sector_options || [], payload.filter_sector || "", "Alle sectoren");
        const s=document.getElementById("start_date");
        const e=document.getElementById("end_date");
        const f=document.getElementById("frequency");
        if(s) s.value = payload.start_date || "";
        if(e) e.value = payload.end_date || "";
        if(f) f.value = payload.frequency || "third_friday";
      };
      window.renderSnapshot = function(payload){
        assetState.rows = (payload&&payload.asset_rows)?payload.asset_rows:[];
        assetState.cols = (payload&&payload.asset_cols)?payload.asset_cols:[];
        assetYearState.rows = (payload&&payload.asset_year_rows)?payload.asset_year_rows:[];
        assetYearState.cols = (payload&&payload.asset_year_cols)?payload.asset_year_cols:[];
        sectorState.rows = (payload&&payload.sector_rows)?payload.sector_rows:[];
        sectorState.cols = (payload&&payload.sector_cols)?payload.sector_cols:[];
        sectorYearState.rows = (payload&&payload.sector_year_rows)?payload.sector_year_rows:[];
        sectorYearState.cols = (payload&&payload.sector_year_cols)?payload.sector_year_cols:[];
        const meta=(payload&&payload.meta)?payload.meta:{};
        yearPerfPeriod = meta.year_perf_period || "month";
        const btnPerf=document.getElementById("btn_year_perf_period");
        if(btnPerf) btnPerf.textContent = yearPerfPeriod === "week" ? "Performance: week" : "Performance: maand";
        if(!assetState.cols.includes(assetState.sort.col)) assetState.sort = { source:"values", col: "asset_rollup", dir: "asc" };
        if(!sectorState.cols.includes(sectorState.sort.col)) sectorState.sort = { source:"values", col: "asset_rollup", dir: "asc" };
        rerenderAll();
        const labels = {
          daily: "elke dag",
          weekly_friday: "elke vrijdag",
          third_friday: "3e vrijdag maand",
          month_end: "laatste dag maand",
          quarter_end: "laatste dag kwartaal",
          year_end: "laatste dag jaar"
        };
        const label = labels[meta.frequency] || "3e vrijdag maand";
        const perfLabel = yearPerfPeriod === "week" ? "jaarperformance per week" : "jaarperformance per maand";
        document.getElementById("meta").textContent = `${meta.asset_count||0} assets | ${meta.sector_count||0} sectoren | ${meta.moment_count||0} meetmomenten | ${perfLabel} t/m ${meta.year_perf_anchor||""} | bron: per_dag_asset_result_v2.totaal_v2 | US omgerekend via EURUSD | ${label}`;
      };
      if(window.qt && window.QWebChannel){
        new QWebChannel(qt.webChannelTransport, function(channel){
          bridgeState.bridge = channel.objects.maandEindBridge || null;
          bindUi();
          syncVerticalGroup(["wrap-values","wrap-diff","wrap-year-perf"], assetState);
          syncVerticalGroup(["wrap-sector-values","wrap-sector-diff","wrap-sector-year-perf"], sectorState);
          syncHorizontalGroup(["wrap-values", "wrap-sector-values"]);
          syncHorizontalGroup(["wrap-diff", "wrap-sector-diff"]);
        });
      } else {
        bindUi();
        syncVerticalGroup(["wrap-values","wrap-diff","wrap-year-perf"], assetState);
        syncVerticalGroup(["wrap-sector-values","wrap-sector-diff","wrap-sector-year-perf"], sectorState);
        syncHorizontalGroup(["wrap-values", "wrap-sector-values"]);
        syncHorizontalGroup(["wrap-diff", "wrap-sector-diff"]);
      }
    </script>
  </body>
</html>
"""


class _MaandEindWebBridge(QObject):
    def __init__(self, tab: MaandEindWebTab):
        super().__init__(tab)
        self._tab = tab

    @Slot(str)
    def setStartDate(self, value: str) -> None:
        self._tab._set_start_date(value)

    @Slot(str)
    def setEndDate(self, value: str) -> None:
        self._tab._set_end_date(value)

    @Slot(str)
    def setFrequency(self, value: str) -> None:
        self._tab._set_frequency(value)

    @Slot(str)
    def setFilterRegio(self, value: str) -> None:
        self._tab._set_filter_regio(value)

    @Slot(str)
    def setFilterValueGrow(self, value: str) -> None:
        self._tab._set_filter_value_grow(value)

    @Slot(str)
    def setFilterSector(self, value: str) -> None:
        self._tab._set_filter_sector(value)

    @Slot()
    def refresh(self) -> None:
        self._tab._publish_snapshot()

    @Slot()
    def openEndValueChart(self) -> None:
        self._tab._open_end_value_chart_dialog()

    @Slot()
    def openDiffValueChart(self) -> None:
        self._tab._open_diff_value_chart_dialog()

    @Slot()
    def openCompareDates(self) -> None:
        self._tab._open_compare_dialog()

    @Slot()
    def toggleYearPerfPeriod(self) -> None:
        self._tab._toggle_year_perf_period()
