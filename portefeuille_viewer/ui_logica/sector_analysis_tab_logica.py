from PySide6.QtWidgets import QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHBoxLayout, QSizePolicy, QScrollArea, QHeaderView
from PySide6.QtCore import QSortFilterProxyModel, QTimer
from PySide6.QtCharts import QChart, QChartView, QPieSeries, QPieSlice
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QColor, QPen
import polars as pl

from portefeuille_viewer.ui.sector_tab import Ui_Form
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.signals import signals
from portefeuille_viewer.ui.models import PolarsTableModel


class SectorAnalysisTab(QWidget, Ui_Form):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self._wrap_in_scroll_area()
        self._chart_views = {}
        self._init_pie_chart("pieChartValueLineair", "pieChartValue1")
        self._init_pie_chart("pieChartValueLineairNaOpties", "frame_2")
        self._init_pie_chart("pieChartValueDelta")
        self._init_pie_chart("pieChartValueDeltaPutITM")
        self._init_pie_chart("pieChartValueGrowLineair")
        self._init_pie_chart("pieChartValueGrowLineairNaOpties")
        self._init_pie_chart("pieChartValueGrowDelta")
        self._init_pie_chart("pieChartValueGrowDeltaPutITM")
        self._init_sector_table()
        self._init_sector_totals_footer()
        self._init_sector_table_delta()
        self._init_sector_totals_footer_delta()
        self._init_value_grow_table()
        self._init_value_grow_totals_footer()
        self._init_value_grow_table_delta()
        self._init_value_grow_totals_footer_delta()
        self._sector_color_map = {}
        self._chart_data = {}
        self._put_otm_ratio = 1.0
        self._value_grow_color_map = {}
        self._value_grow_chart_data = {}
        self._put_otm_ratio_value_grow = 1.0
        self._snapshot_reload_timer = QTimer(self)
        self._snapshot_reload_timer.setSingleShot(True)
        self._snapshot_reload_timer.setInterval(150)
        self._snapshot_reload_timer.timeout.connect(self.reload_data)
        self._watched_snapshot_keys = {
            "repository_snapshot_portfolio_value_optie_call_put_detailed",
            "repository_snapshot_portfolio_value_aandelen",
            "repository_snapshot_portfolio_value_sprinters",
            "repository_snapshot_portfolio_value_total_combined_put",
        }
        self.reload_data()
        signals.databaseChanged.connect(self._on_db_changed)
        signals.snapshotUpdated.connect(self._on_snapshot_updated)
        signals.stateRebuildFinished.connect(self._on_state_rebuild_finished)
        if hasattr(self, "putOTMRatio"):
            try:
                self.putOTMRatio.setValue(100)
                self.putOTMRatio.valueChanged.connect(self._on_put_otm_ratio_changed)
                self._on_put_otm_ratio_changed(self.putOTMRatio.value())
            except Exception:
                pass
        if hasattr(self, "putOTMRatioValueGrow"):
            try:
                self.putOTMRatioValueGrow.setValue(100)
                self.putOTMRatioValueGrow.valueChanged.connect(self._on_put_otm_ratio_value_grow_changed)
                self._on_put_otm_ratio_value_grow_changed(self.putOTMRatioValueGrow.value())
            except Exception:
                pass

    def _get_pie_frame(self, primary_name: str, fallback_name: str | None = None):
        if hasattr(self, primary_name):
            return getattr(self, primary_name)
        if fallback_name and hasattr(self, fallback_name):
            return getattr(self, fallback_name)
        return None

    def _init_pie_chart(self, primary_name: str, fallback_name: str | None = None):
        frame = self._get_pie_frame(primary_name, fallback_name)
        if frame is None:
            return
        if frame.layout() is None:
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
        else:
            layout = frame.layout()
        chart = QChart()
        chart.legend().hide()
        chart.setBackgroundVisible(False)
        series = QPieSeries()
        chart.addSeries(series)
        chart_view = QChartView(chart, frame)
        chart_view.setRenderHint(QPainter.Antialiasing)
        layout.addWidget(chart_view)
        self._chart_views[primary_name] = chart_view

    def _init_sector_table(self):
        if not hasattr(self, "tableSectorValuesLineair"):
            self._sector_table_model = None
            self._sector_table_proxy = None
            return
        self._sector_table_model = SectorTableModel(pl.DataFrame(), self)
        self._sector_table_proxy = QSortFilterProxyModel(self)
        self._sector_table_proxy.setSourceModel(self._sector_table_model)
        self._sector_table_proxy.setSortRole(Qt.UserRole)
        self.tableSectorValuesLineair.setModel(self._sector_table_proxy)
        self.tableSectorValuesLineair.setSortingEnabled(True)
        header = self.tableSectorValuesLineair.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        self.tableSectorValuesLineair.verticalHeader().setVisible(False)
        self._apply_sector_table_widths()
        self.tableSectorValuesLineair.horizontalHeader().sortIndicatorChanged.connect(
            lambda _idx, _order: self._update_charts_from_table_order()
        )
        header_map = {
            "sector": "Sector",
            "value_lineair": "Lineair",
            "value_lineair_pct": "Lineair %",
            "value_na_opties": "Na opties",
            "value_na_opties_pct": "Na opties %",
        }
        self._sector_table_model.set_display_headers(header_map)

    def _init_sector_table_delta(self):
        if not hasattr(self, "tableSectorValuesDelta"):
            self._sector_table_delta_model = None
            self._sector_table_delta_proxy = None
            return
        self._sector_table_delta_model = SectorTableModel(pl.DataFrame(), self)
        self._sector_table_delta_proxy = QSortFilterProxyModel(self)
        self._sector_table_delta_proxy.setSourceModel(self._sector_table_delta_model)
        self._sector_table_delta_proxy.setSortRole(Qt.UserRole)
        self.tableSectorValuesDelta.setModel(self._sector_table_delta_proxy)
        self.tableSectorValuesDelta.setSortingEnabled(True)
        header = self.tableSectorValuesDelta.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        header.sortIndicatorChanged.connect(
            lambda _idx, _order: self._update_delta_charts_from_table_order()
        )
        self.tableSectorValuesDelta.verticalHeader().setVisible(False)
        self._apply_sector_table_delta_widths()
        header_map = {
            "sector": "Sector",
            "value_aandelen_put_delta": "Aandelen + Put Delta",
            "value_aandelen_delta_all": "Aandelen + Delta (all)",
            "value_aandelen_put_delta_pct": "Aandelen + Put Delta %",
            "value_aandelen_delta_all_pct": "Aandelen + Delta (all) %",
        }
        self._sector_table_delta_model.set_display_headers(header_map)

    def _init_value_grow_table(self):
        if not hasattr(self, "tableValueGrowValuesLineair"):
            self._value_grow_table_model = None
            self._value_grow_table_proxy = None
            return
        self._value_grow_table_model = SectorTableModel(pl.DataFrame(), self)
        self._value_grow_table_proxy = QSortFilterProxyModel(self)
        self._value_grow_table_proxy.setSourceModel(self._value_grow_table_model)
        self._value_grow_table_proxy.setSortRole(Qt.UserRole)
        self.tableValueGrowValuesLineair.setModel(self._value_grow_table_proxy)
        self.tableValueGrowValuesLineair.setSortingEnabled(True)
        header = self.tableValueGrowValuesLineair.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        self.tableValueGrowValuesLineair.verticalHeader().setVisible(False)
        self._apply_value_grow_table_widths()
        self.tableValueGrowValuesLineair.horizontalHeader().sortIndicatorChanged.connect(
            lambda _idx, _order: self._update_value_grow_charts_from_table_order()
        )
        header_map = {
            "value_grow": "Value/Grow",
            "value_lineair": "Lineair",
            "value_lineair_pct": "Lineair %",
            "value_na_opties": "Na opties",
            "value_na_opties_pct": "Na opties %",
        }
        self._value_grow_table_model.set_display_headers(header_map)

    def _init_value_grow_table_delta(self):
        if not hasattr(self, "tableValueGrowValuesDelta"):
            self._value_grow_table_delta_model = None
            self._value_grow_table_delta_proxy = None
            return
        self._value_grow_table_delta_model = SectorTableModel(pl.DataFrame(), self)
        self._value_grow_table_delta_proxy = QSortFilterProxyModel(self)
        self._value_grow_table_delta_proxy.setSourceModel(self._value_grow_table_delta_model)
        self._value_grow_table_delta_proxy.setSortRole(Qt.UserRole)
        self.tableValueGrowValuesDelta.setModel(self._value_grow_table_delta_proxy)
        self.tableValueGrowValuesDelta.setSortingEnabled(True)
        header = self.tableValueGrowValuesDelta.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        header.sortIndicatorChanged.connect(
            lambda _idx, _order: self._update_value_grow_delta_charts_from_table_order()
        )
        self.tableValueGrowValuesDelta.verticalHeader().setVisible(False)
        self._apply_value_grow_table_delta_widths()
        header_map = {
            "value_grow": "Value/Grow",
            "value_aandelen_put_delta": "Aandelen + Put Delta",
            "value_aandelen_delta_all": "Aandelen + Delta (all)",
            "value_aandelen_put_delta_pct": "Aandelen + Put Delta %",
            "value_aandelen_delta_all_pct": "Aandelen + Delta (all) %",
        }
        self._value_grow_table_delta_model.set_display_headers(header_map)

    def _on_db_changed(self, _db_name: str):
        self.reload_data()

    def _on_snapshot_updated(self, snapshot_key: str):
        if snapshot_key in self._watched_snapshot_keys:
            self._snapshot_reload_timer.start()

    def _on_state_rebuild_finished(self, payload: dict | None):
        if (payload or {}).get("status") == "ok":
            self.reload_data()

    def _on_put_otm_ratio_changed(self, value):
        try:
            self._put_otm_ratio = max(0.0, min(1.0, float(value) / 100.0))
        except Exception:
            self._put_otm_ratio = 1.0
        self.reload_data()

    def _on_put_otm_ratio_value_grow_changed(self, value):
        try:
            self._put_otm_ratio_value_grow = max(0.0, min(1.0, float(value) / 100.0))
        except Exception:
            self._put_otm_ratio_value_grow = 1.0
        self.reload_data()

    def reload_data(self):
        df_opties = getattr(SNAPSHOT_STORE, "repository_snapshot_portfolio_value_optie_call_put_detailed", None)
        df_aandelen = getattr(SNAPSHOT_STORE, "repository_snapshot_portfolio_value_aandelen", None)
        df_sprinters = getattr(SNAPSHOT_STORE, "repository_snapshot_portfolio_value_sprinters", None)

        df_opties = df_opties if df_opties is not None else pl.DataFrame()
        df_aandelen = df_aandelen if df_aandelen is not None else pl.DataFrame()
        df_sprinters = df_sprinters if df_sprinters is not None else pl.DataFrame()

        frames_lineair = []
        if not df_opties.is_empty() and "sector" in df_opties.columns:
            if "optie_call_put" in df_opties.columns:
                df_put = df_opties.filter(pl.col("optie_call_put") == "put")
            else:
                df_put = df_opties
            if "waarde_ITM" in df_put.columns and "waarde_OTM" in df_put.columns:
                df_put = df_put.filter(pl.col("sector").is_not_null())
                df_put = df_put.with_columns([
                    pl.col("waarde_ITM").cast(pl.Float64).fill_null(0.0).alias("_waarde_itm"),
                    pl.col("waarde_OTM").cast(pl.Float64).fill_null(0.0).alias("_waarde_otm"),
                ])
                df_put = df_put.with_columns(
                    (pl.col("_waarde_itm") + (pl.col("_waarde_otm") * self._put_otm_ratio)).alias("waarde_bezit_adj")
                )
                frames_lineair.append(df_put.select(["sector", "waarde_bezit_adj"]).rename({"waarde_bezit_adj": "waarde_bezit"}))
            elif "waarde_bezit" in df_put.columns:
                df_put = df_put.filter(pl.col("sector").is_not_null())
                frames_lineair.append(df_put.select(["sector", "waarde_bezit"]))
        if not df_aandelen.is_empty() and "sector" in df_aandelen.columns and "waarde_bezit" in df_aandelen.columns:
            df_aandelen = df_aandelen.filter(pl.col("sector").is_not_null())
            frames_lineair.append(df_aandelen.select(["sector", "waarde_bezit"]))
        if not df_sprinters.is_empty() and "sector" in df_sprinters.columns and "spr_waarde_bezit" in df_sprinters.columns:
            df_sprinters = df_sprinters.filter(pl.col("sector").is_not_null())
            frames_lineair.append(df_sprinters.select(["sector", "spr_waarde_bezit"]).rename({"spr_waarde_bezit": "waarde_bezit"}))

        data_lineair = self._build_sector_sum(frames_lineair)

        frames_na_opties = []
        if not df_opties.is_empty() and "sector" in df_opties.columns:
            if "optie_call_put" in df_opties.columns and "waarde_ITM" in df_opties.columns:
                df_put_itm = df_opties.filter(pl.col("optie_call_put") == "put")
                df_put_itm = df_put_itm.filter(pl.col("sector").is_not_null())
                frames_na_opties.append(df_put_itm.select(["sector", "waarde_ITM"]).rename({"waarde_ITM": "waarde_bezit"}))
            if "optie_call_put" in df_opties.columns and "waarde_ITM" in df_opties.columns:
                df_call_itm = df_opties.filter(pl.col("optie_call_put") == "call")
                df_call_itm = df_call_itm.filter(pl.col("sector").is_not_null())
                frames_na_opties.append(df_call_itm.select(["sector", "waarde_ITM"]).rename({"waarde_ITM": "waarde_bezit"}))
        if not df_aandelen.is_empty() and "sector" in df_aandelen.columns and "waarde_bezit" in df_aandelen.columns:
            df_aandelen = df_aandelen.filter(pl.col("sector").is_not_null())
            frames_na_opties.append(df_aandelen.select(["sector", "waarde_bezit"]))
        if not df_sprinters.is_empty() and "sector" in df_sprinters.columns and "spr_waarde_bezit" in df_sprinters.columns:
            df_sprinters = df_sprinters.filter(pl.col("sector").is_not_null())
            frames_na_opties.append(df_sprinters.select(["sector", "spr_waarde_bezit"]).rename({"spr_waarde_bezit": "waarde_bezit"}))

        data_na_opties = self._build_sector_sum(frames_na_opties)

        self._set_sector_table_data(data_lineair, data_na_opties)
        data_delta = self._build_sector_delta_chart_data(df_opties, df_aandelen, df_sprinters)
        self._set_sector_table_delta_data(df_opties, df_aandelen, df_sprinters)
        self._chart_data = {
            "pieChartValueLineair": data_lineair,
            "pieChartValueLineairNaOpties": data_na_opties,
            "pieChartValueDelta": data_delta.get("value_aandelen_put_delta", {}),
            "pieChartValueDeltaPutITM": data_delta.get("value_aandelen_delta_all", {}),
        }
        df_opties_vg = getattr(SNAPSHOT_STORE, "repository_snapshot_portfolio_value_optie_call_put_detailed", None)
        df_aandelen_vg = getattr(SNAPSHOT_STORE, "repository_snapshot_portfolio_value_aandelen", None)
        df_sprinters_vg = getattr(SNAPSHOT_STORE, "repository_snapshot_portfolio_value_sprinters", None)
        df_opties_vg = df_opties_vg if df_opties_vg is not None else pl.DataFrame()
        df_aandelen_vg = df_aandelen_vg if df_aandelen_vg is not None else pl.DataFrame()
        df_sprinters_vg = df_sprinters_vg if df_sprinters_vg is not None else pl.DataFrame()
        frames_lineair_value_grow = []
        if not df_opties_vg.is_empty() and "value_grow" in df_opties_vg.columns:
            if "optie_call_put" in df_opties_vg.columns:
                df_put = df_opties_vg.filter(pl.col("optie_call_put") == "put")
            else:
                df_put = df_opties_vg
            if "waarde_ITM" in df_put.columns and "waarde_OTM" in df_put.columns:
                df_put = df_put.filter(pl.col("value_grow").is_not_null())
                df_put = df_put.with_columns([
                    pl.col("waarde_ITM").cast(pl.Float64).fill_null(0.0).alias("_waarde_itm"),
                    pl.col("waarde_OTM").cast(pl.Float64).fill_null(0.0).alias("_waarde_otm"),
                ])
                df_put = df_put.with_columns(
                    (pl.col("_waarde_itm") + (pl.col("_waarde_otm") * self._put_otm_ratio_value_grow)).alias("waarde_bezit_adj")
                )
                frames_lineair_value_grow.append(
                    df_put.select(["value_grow", "waarde_bezit_adj"]).rename({"waarde_bezit_adj": "waarde_bezit"})
                )
            elif "waarde_bezit" in df_put.columns:
                df_put = df_put.filter(pl.col("value_grow").is_not_null())
                frames_lineair_value_grow.append(df_put.select(["value_grow", "waarde_bezit"]))
        if not df_aandelen_vg.is_empty() and "value_grow" in df_aandelen_vg.columns and "waarde_bezit" in df_aandelen_vg.columns:
            df_aandelen_vg = df_aandelen_vg.filter(pl.col("value_grow").is_not_null())
            frames_lineair_value_grow.append(df_aandelen_vg.select(["value_grow", "waarde_bezit"]))
        if not df_sprinters_vg.is_empty() and "value_grow" in df_sprinters_vg.columns and "spr_waarde_bezit" in df_sprinters_vg.columns:
            df_sprinters_vg = df_sprinters_vg.filter(pl.col("value_grow").is_not_null())
            frames_lineair_value_grow.append(
                df_sprinters_vg.select(["value_grow", "spr_waarde_bezit"]).rename({"spr_waarde_bezit": "waarde_bezit"})
            )

        data_lineair_value_grow = self._build_value_grow_sum(frames_lineair_value_grow)

        frames_na_opties_value_grow = []
        if not df_opties_vg.is_empty() and "value_grow" in df_opties_vg.columns:
            if "optie_call_put" in df_opties_vg.columns and "waarde_ITM" in df_opties_vg.columns:
                df_put_itm = df_opties_vg.filter(pl.col("optie_call_put") == "put")
                df_put_itm = df_put_itm.filter(pl.col("value_grow").is_not_null())
                frames_na_opties_value_grow.append(
                    df_put_itm.select(["value_grow", "waarde_ITM"]).rename({"waarde_ITM": "waarde_bezit"})
                )
            if "optie_call_put" in df_opties_vg.columns and "waarde_ITM" in df_opties_vg.columns:
                df_call_itm = df_opties_vg.filter(pl.col("optie_call_put") == "call")
                df_call_itm = df_call_itm.filter(pl.col("value_grow").is_not_null())
                frames_na_opties_value_grow.append(
                    df_call_itm.select(["value_grow", "waarde_ITM"]).rename({"waarde_ITM": "waarde_bezit"})
                )
        if not df_aandelen_vg.is_empty() and "value_grow" in df_aandelen_vg.columns and "waarde_bezit" in df_aandelen_vg.columns:
            df_aandelen_vg = df_aandelen_vg.filter(pl.col("value_grow").is_not_null())
            frames_na_opties_value_grow.append(df_aandelen_vg.select(["value_grow", "waarde_bezit"]))
        if not df_sprinters_vg.is_empty() and "value_grow" in df_sprinters_vg.columns and "spr_waarde_bezit" in df_sprinters_vg.columns:
            df_sprinters_vg = df_sprinters_vg.filter(pl.col("value_grow").is_not_null())
            frames_na_opties_value_grow.append(
                df_sprinters_vg.select(["value_grow", "spr_waarde_bezit"]).rename({"spr_waarde_bezit": "waarde_bezit"})
            )

        data_na_opties_value_grow = self._build_value_grow_sum(frames_na_opties_value_grow)

        self._set_value_grow_table_data(data_lineair_value_grow, data_na_opties_value_grow)
        data_delta_value_grow = self._build_value_grow_delta_chart_data(df_opties_vg, df_aandelen_vg, df_sprinters_vg)
        self._set_value_grow_table_delta_data(df_opties_vg, df_aandelen_vg, df_sprinters_vg)
        self._value_grow_chart_data = {
            "pieChartValueGrowLineair": data_lineair_value_grow,
            "pieChartValueGrowLineairNaOpties": data_na_opties_value_grow,
            "pieChartValueGrowDelta": data_delta_value_grow.get("value_aandelen_put_delta", {}),
            "pieChartValueGrowDeltaPutITM": data_delta_value_grow.get("value_aandelen_delta_all", {}),
        }
        self._ensure_sector_colors()
        self._ensure_value_grow_colors()
        self._update_charts_from_table_order()
        self._update_delta_charts_from_table_order()
        self._update_value_grow_charts_from_table_order()
        self._update_value_grow_delta_charts_from_table_order()

    def _build_sector_sum(self, frames: list[pl.DataFrame]) -> dict:
        if not frames:
            return {}
        df_all = pl.concat(frames, how="diagonal_relaxed")
        if df_all.is_empty():
            return {}
        df_sum = (
            df_all.group_by("sector")
            .agg(pl.col("waarde_bezit").sum().alias("waarde_bezit"))
            .sort("waarde_bezit", descending=True)
        )
        return {row[0]: row[1] for row in df_sum.rows()}

    def _build_value_grow_sum(self, frames: list[pl.DataFrame]) -> dict:
        if not frames:
            return {}
        df_all = pl.concat(frames, how="diagonal_relaxed")
        if df_all.is_empty():
            return {}
        df_sum = (
            df_all.group_by("value_grow")
            .agg(pl.col("waarde_bezit").sum().alias("waarde_bezit"))
            .sort("waarde_bezit", descending=True)
        )
        return {row[0]: row[1] for row in df_sum.rows()}

    def _set_sector_table_data(self, data_lineair: dict, data_na_opties: dict):
        if self._sector_table_model is None:
            return
        sectors = set(data_lineair.keys()) | set(data_na_opties.keys())
        total_lineair = sum(float(v) for v in data_lineair.values() if v is not None) if data_lineair else 0.0
        total_na_opties = sum(float(v) for v in data_na_opties.values() if v is not None) if data_na_opties else 0.0
        rows = []
        for sector in sorted(sectors):
            val_lineair = float(data_lineair.get(sector, 0.0) or 0.0)
            val_na_opties = float(data_na_opties.get(sector, 0.0) or 0.0)
            rows.append({
                "sector": sector,
                "value_lineair": val_lineair,
                "value_lineair_pct": (val_lineair / total_lineair * 100.0) if total_lineair else 0.0,
                "value_na_opties": val_na_opties,
                "value_na_opties_pct": (val_na_opties / total_na_opties * 100.0) if total_na_opties else 0.0,
            })
        df = pl.DataFrame(rows) if rows else pl.DataFrame()
        if not df.is_empty():
            df = df.select([
                "sector",
                "value_lineair",
                "value_lineair_pct",
                "value_na_opties",
                "value_na_opties_pct",
            ])
        self._sector_table_model.set_df(df)
        self._apply_sector_table_widths()
        self._update_sector_totals(df)

    def _set_value_grow_table_data(self, data_lineair: dict, data_na_opties: dict):
        if self._value_grow_table_model is None:
            return
        values = set(data_lineair.keys()) | set(data_na_opties.keys())
        total_lineair = sum(float(v) for v in data_lineair.values() if v is not None) if data_lineair else 0.0
        total_na_opties = sum(float(v) for v in data_na_opties.values() if v is not None) if data_na_opties else 0.0
        rows = []
        for value_grow in sorted(values):
            val_lineair = float(data_lineair.get(value_grow, 0.0) or 0.0)
            val_na_opties = float(data_na_opties.get(value_grow, 0.0) or 0.0)
            rows.append({
                "value_grow": value_grow,
                "value_lineair": val_lineair,
                "value_lineair_pct": (val_lineair / total_lineair * 100.0) if total_lineair else 0.0,
                "value_na_opties": val_na_opties,
                "value_na_opties_pct": (val_na_opties / total_na_opties * 100.0) if total_na_opties else 0.0,
            })
        df = pl.DataFrame(rows) if rows else pl.DataFrame()
        if not df.is_empty():
            df = df.select([
                "value_grow",
                "value_lineair",
                "value_lineair_pct",
                "value_na_opties",
                "value_na_opties_pct",
            ])
        self._value_grow_table_model.set_df(df)
        self._apply_value_grow_table_widths()
        self._update_value_grow_totals(df)

    def _set_sector_table_delta_data(self, df_opties: pl.DataFrame, df_aandelen: pl.DataFrame, df_sprinters: pl.DataFrame | None = None):
        if self._sector_table_delta_model is None:
            return
        df = pl.DataFrame()
        if df_aandelen is not None and not df_aandelen.is_empty():
            if "sector" in df_aandelen.columns and "waarde_bezit" in df_aandelen.columns:
                df_aandelen = df_aandelen.filter(pl.col("sector").is_not_null())
                df = (
                    df_aandelen.group_by("sector")
                    .agg(pl.col("waarde_bezit").sum().alias("value_aandelen"))
                    .sort("value_aandelen", descending=True)
                )
                total = float(df["value_aandelen"].sum()) if df.height > 0 else 0.0
                df = df.with_columns(
                    (pl.col("value_aandelen") / total * 100.0).alias("value_aandelen_pct")
                    if total
                    else pl.lit(0.0).alias("value_aandelen_pct")
                )
                df = df.select(["sector", "value_aandelen", "value_aandelen_pct"])
        if df_sprinters is not None and not df_sprinters.is_empty():
            if "sector" in df_sprinters.columns and "spr_waarde_bezit" in df_sprinters.columns:
                df_sprinters = df_sprinters.filter(pl.col("sector").is_not_null())
                df_spr = (
                    df_sprinters.group_by("sector")
                    .agg(pl.col("spr_waarde_bezit").sum().alias("value_sprinters"))
                )
                if df.is_empty():
                    df = df_spr.rename({"value_sprinters": "value_aandelen"})
                else:
                    df = df.join(df_spr, on="sector", how="left")
                    df = df.with_columns(
                        (pl.col("value_aandelen").fill_null(0.0) + pl.col("value_sprinters").fill_null(0.0)).alias("value_aandelen")
                    ).drop(["value_sprinters"])
        df_all_delta = pl.DataFrame()
        if df_opties is not None and not df_opties.is_empty():
            if "optie_call_put" in df_opties.columns and "waarde_bezit_delta" in df_opties.columns and "sector" in df_opties.columns:
                df_put_delta = (
                    df_opties.filter(pl.col("optie_call_put") == "put")
                    .filter(pl.col("sector").is_not_null())
                    .group_by("sector")
                    .agg(pl.col("waarde_bezit_delta").sum().alias("value_put_delta"))
                )
                df_all_delta = (
                    df_opties.filter(pl.col("sector").is_not_null())
                    .group_by("sector")
                    .agg(pl.col("waarde_bezit_delta").sum().alias("value_delta_all"))
                )
                if df.is_empty():
                    df = df_put_delta
                else:
                    df = df.join(df_put_delta, on="sector", how="left")
                if not df_all_delta.is_empty():
                    if df.is_empty():
                        df = df_all_delta
                    else:
                        df = df.join(df_all_delta, on="sector", how="left")
        if not df.is_empty():
            if "value_put_delta" in df.columns:
                df = df.with_columns(pl.col("value_put_delta").fill_null(0.0))
            if "value_delta_all" in df.columns:
                df = df.with_columns(pl.col("value_delta_all").fill_null(0.0))
            if "value_aandelen" in df.columns and "value_put_delta" in df.columns:
                df = df.with_columns(
                    (pl.col("value_aandelen") + pl.col("value_put_delta")).alias("value_aandelen_put_delta")
                )
            elif "value_aandelen" in df.columns and "value_aandelen_put_delta" not in df.columns:
                df = df.with_columns(pl.col("value_aandelen").alias("value_aandelen_put_delta"))
            if "value_aandelen" in df.columns and "value_delta_all" in df.columns:
                df = df.with_columns(
                    (pl.col("value_aandelen") + pl.col("value_delta_all")).alias("value_aandelen_delta_all")
                )
            elif "value_aandelen" in df.columns and "value_aandelen_delta_all" not in df.columns:
                df = df.with_columns(pl.col("value_aandelen").alias("value_aandelen_delta_all"))
            total_put = float(df["value_aandelen_put_delta"].sum()) if "value_aandelen_put_delta" in df.columns and df.height > 0 else 0.0
            total_all = float(df["value_aandelen_delta_all"].sum()) if "value_aandelen_delta_all" in df.columns and df.height > 0 else 0.0
            if "value_aandelen_put_delta" in df.columns:
                df = df.with_columns(
                    (pl.col("value_aandelen_put_delta") / total_put * 100.0).alias("value_aandelen_put_delta_pct")
                    if total_put
                    else pl.lit(0.0).alias("value_aandelen_put_delta_pct")
                )
            if "value_aandelen_delta_all" in df.columns:
                df = df.with_columns(
                    (pl.col("value_aandelen_delta_all") / total_all * 100.0).alias("value_aandelen_delta_all_pct")
                    if total_all
                    else pl.lit(0.0).alias("value_aandelen_delta_all_pct")
                )
            cols = [
                "sector",
                "value_aandelen_put_delta",
                "value_aandelen_put_delta_pct",
                "value_aandelen_delta_all",
                "value_aandelen_delta_all_pct",
            ]
            df = df.select([c for c in cols if c in df.columns])
            fill_cols = [c for c in df.columns if c != "sector"]
            if fill_cols:
                df = df.with_columns([pl.col(c).fill_null(0.0) for c in fill_cols])
        self._sector_table_delta_model.set_df(df)
        self._apply_sector_table_delta_widths()
        self._update_sector_totals_delta(df)

    def _set_value_grow_table_delta_data(self, df_opties: pl.DataFrame, df_aandelen: pl.DataFrame, df_sprinters: pl.DataFrame | None = None):
        if self._value_grow_table_delta_model is None:
            return
        df = pl.DataFrame()
        if df_aandelen is not None and not df_aandelen.is_empty():
            if "value_grow" in df_aandelen.columns and "waarde_bezit" in df_aandelen.columns:
                df_aandelen = df_aandelen.filter(pl.col("value_grow").is_not_null())
                df = (
                    df_aandelen.group_by("value_grow")
                    .agg(pl.col("waarde_bezit").sum().alias("value_aandelen"))
                    .sort("value_aandelen", descending=True)
                )
                total = float(df["value_aandelen"].sum()) if df.height > 0 else 0.0
                df = df.with_columns(
                    (pl.col("value_aandelen") / total * 100.0).alias("value_aandelen_pct")
                    if total
                    else pl.lit(0.0).alias("value_aandelen_pct")
                )
                df = df.select(["value_grow", "value_aandelen", "value_aandelen_pct"])
        if df_sprinters is not None and not df_sprinters.is_empty():
            if "value_grow" in df_sprinters.columns and "spr_waarde_bezit" in df_sprinters.columns:
                df_sprinters = df_sprinters.filter(pl.col("value_grow").is_not_null())
                df_spr = (
                    df_sprinters.group_by("value_grow")
                    .agg(pl.col("spr_waarde_bezit").sum().alias("value_sprinters"))
                )
                if df.is_empty():
                    df = df_spr.rename({"value_sprinters": "value_aandelen"})
                else:
                    df = df.join(df_spr, on="value_grow", how="left")
                    df = df.with_columns(
                        (pl.col("value_aandelen").fill_null(0.0) + pl.col("value_sprinters").fill_null(0.0)).alias("value_aandelen")
                    ).drop(["value_sprinters"])
        df_all_delta = pl.DataFrame()
        if df_opties is not None and not df_opties.is_empty():
            if "optie_call_put" in df_opties.columns and "waarde_bezit_delta" in df_opties.columns and "value_grow" in df_opties.columns:
                df_put_delta = (
                    df_opties.filter(pl.col("optie_call_put") == "put")
                    .filter(pl.col("value_grow").is_not_null())
                    .group_by("value_grow")
                    .agg(pl.col("waarde_bezit_delta").sum().alias("value_put_delta"))
                )
                df_all_delta = (
                    df_opties.filter(pl.col("value_grow").is_not_null())
                    .group_by("value_grow")
                    .agg(pl.col("waarde_bezit_delta").sum().alias("value_delta_all"))
                )
                if df.is_empty():
                    df = df_put_delta
                else:
                    df = df.join(df_put_delta, on="value_grow", how="left")
                if not df_all_delta.is_empty():
                    if df.is_empty():
                        df = df_all_delta
                    else:
                        df = df.join(df_all_delta, on="value_grow", how="left")
        if not df.is_empty():
            if "value_put_delta" in df.columns:
                df = df.with_columns(pl.col("value_put_delta").fill_null(0.0))
            if "value_delta_all" in df.columns:
                df = df.with_columns(pl.col("value_delta_all").fill_null(0.0))
            if "value_aandelen" in df.columns and "value_put_delta" in df.columns:
                df = df.with_columns(
                    (pl.col("value_aandelen") + pl.col("value_put_delta")).alias("value_aandelen_put_delta")
                )
            elif "value_aandelen" in df.columns and "value_aandelen_put_delta" not in df.columns:
                df = df.with_columns(pl.col("value_aandelen").alias("value_aandelen_put_delta"))
            if "value_aandelen" in df.columns and "value_delta_all" in df.columns:
                df = df.with_columns(
                    (pl.col("value_aandelen") + pl.col("value_delta_all")).alias("value_aandelen_delta_all")
                )
            elif "value_aandelen" in df.columns and "value_aandelen_delta_all" not in df.columns:
                df = df.with_columns(pl.col("value_aandelen").alias("value_aandelen_delta_all"))
            total_put = float(df["value_aandelen_put_delta"].sum()) if "value_aandelen_put_delta" in df.columns and df.height > 0 else 0.0
            total_all = float(df["value_aandelen_delta_all"].sum()) if "value_aandelen_delta_all" in df.columns and df.height > 0 else 0.0
            if "value_aandelen_put_delta" in df.columns:
                df = df.with_columns(
                    (pl.col("value_aandelen_put_delta") / total_put * 100.0).alias("value_aandelen_put_delta_pct")
                    if total_put
                    else pl.lit(0.0).alias("value_aandelen_put_delta_pct")
                )
            if "value_aandelen_delta_all" in df.columns:
                df = df.with_columns(
                    (pl.col("value_aandelen_delta_all") / total_all * 100.0).alias("value_aandelen_delta_all_pct")
                    if total_all
                    else pl.lit(0.0).alias("value_aandelen_delta_all_pct")
                )
            cols = [
                "value_grow",
                "value_aandelen_put_delta",
                "value_aandelen_put_delta_pct",
                "value_aandelen_delta_all",
                "value_aandelen_delta_all_pct",
            ]
            df = df.select([c for c in cols if c in df.columns])
            fill_cols = [c for c in df.columns if c != "value_grow"]
            if fill_cols:
                df = df.with_columns([pl.col(c).fill_null(0.0) for c in fill_cols])
        self._value_grow_table_delta_model.set_df(df)
        self._apply_value_grow_table_delta_widths()
        self._update_value_grow_totals_delta(df)

    def _build_sector_delta_chart_data(self, df_opties: pl.DataFrame, df_aandelen: pl.DataFrame, df_sprinters: pl.DataFrame | None = None) -> dict:
        data = {"value_aandelen_put_delta": {}, "value_aandelen_delta_all": {}}
        df = pl.DataFrame()
        if df_aandelen is not None and not df_aandelen.is_empty():
            if "sector" in df_aandelen.columns and "waarde_bezit" in df_aandelen.columns:
                df_aandelen = df_aandelen.filter(pl.col("sector").is_not_null())
                df = (
                    df_aandelen.group_by("sector")
                    .agg(pl.col("waarde_bezit").sum().alias("value_aandelen"))
                )
        if df_sprinters is not None and not df_sprinters.is_empty():
            if "sector" in df_sprinters.columns and "spr_waarde_bezit" in df_sprinters.columns:
                df_sprinters = df_sprinters.filter(pl.col("sector").is_not_null())
                df_spr = (
                    df_sprinters.group_by("sector")
                    .agg(pl.col("spr_waarde_bezit").sum().alias("value_sprinters"))
                )
                if df.is_empty():
                    df = df_spr.rename({"value_sprinters": "value_aandelen"})
                else:
                    df = df.join(df_spr, on="sector", how="left")
                    df = df.with_columns(
                        (pl.col("value_aandelen").fill_null(0.0) + pl.col("value_sprinters").fill_null(0.0)).alias("value_aandelen")
                    ).drop(["value_sprinters"])
        if df_opties is not None and not df_opties.is_empty():
            if "optie_call_put" in df_opties.columns and "waarde_bezit_delta" in df_opties.columns and "sector" in df_opties.columns:
                df_put_delta = (
                    df_opties.filter(pl.col("optie_call_put") == "put")
                    .filter(pl.col("sector").is_not_null())
                    .group_by("sector")
                    .agg(pl.col("waarde_bezit_delta").sum().alias("value_put_delta"))
                )
                df_all_delta = (
                    df_opties.filter(pl.col("sector").is_not_null())
                    .group_by("sector")
                    .agg(pl.col("waarde_bezit_delta").sum().alias("value_delta_all"))
                )
                if df.is_empty():
                    df = df_put_delta
                else:
                    df = df.join(df_put_delta, on="sector", how="left")
                if not df_all_delta.is_empty():
                    if df.is_empty():
                        df = df_all_delta
                    else:
                        df = df.join(df_all_delta, on="sector", how="left")
        if not df.is_empty():
            if "value_put_delta" in df.columns:
                df = df.with_columns(pl.col("value_put_delta").fill_null(0.0))
            if "value_delta_all" in df.columns:
                df = df.with_columns(pl.col("value_delta_all").fill_null(0.0))
            if "value_aandelen" in df.columns and "value_put_delta" in df.columns:
                df = df.with_columns(
                    (pl.col("value_aandelen") + pl.col("value_put_delta")).alias("value_aandelen_put_delta")
                )
            elif "value_aandelen" in df.columns and "value_aandelen_put_delta" not in df.columns:
                df = df.with_columns(pl.col("value_aandelen").alias("value_aandelen_put_delta"))
            if "value_aandelen" in df.columns and "value_delta_all" in df.columns:
                df = df.with_columns(
                    (pl.col("value_aandelen") + pl.col("value_delta_all")).alias("value_aandelen_delta_all")
                )
            elif "value_aandelen" in df.columns and "value_aandelen_delta_all" not in df.columns:
                df = df.with_columns(pl.col("value_aandelen").alias("value_aandelen_delta_all"))
            if "value_aandelen_put_delta" in df.columns:
                data["value_aandelen_put_delta"] = {
                    row[0]: row[1] for row in df.select(["sector", "value_aandelen_put_delta"]).rows()
                }
            if "value_aandelen_delta_all" in df.columns:
                data["value_aandelen_delta_all"] = {
                    row[0]: row[1] for row in df.select(["sector", "value_aandelen_delta_all"]).rows()
                }
        return data

    def _build_value_grow_delta_chart_data(self, df_opties: pl.DataFrame, df_aandelen: pl.DataFrame, df_sprinters: pl.DataFrame | None = None) -> dict:
        data = {"value_aandelen_put_delta": {}, "value_aandelen_delta_all": {}}
        df = pl.DataFrame()
        if df_aandelen is not None and not df_aandelen.is_empty():
            if "value_grow" in df_aandelen.columns and "waarde_bezit" in df_aandelen.columns:
                df_aandelen = df_aandelen.filter(pl.col("value_grow").is_not_null())
                df = (
                    df_aandelen.group_by("value_grow")
                    .agg(pl.col("waarde_bezit").sum().alias("value_aandelen"))
                )
        if df_sprinters is not None and not df_sprinters.is_empty():
            if "value_grow" in df_sprinters.columns and "spr_waarde_bezit" in df_sprinters.columns:
                df_sprinters = df_sprinters.filter(pl.col("value_grow").is_not_null())
                df_spr = (
                    df_sprinters.group_by("value_grow")
                    .agg(pl.col("spr_waarde_bezit").sum().alias("value_sprinters"))
                )
                if df.is_empty():
                    df = df_spr.rename({"value_sprinters": "value_aandelen"})
                else:
                    df = df.join(df_spr, on="value_grow", how="left")
                    df = df.with_columns(
                        (pl.col("value_aandelen").fill_null(0.0) + pl.col("value_sprinters").fill_null(0.0)).alias("value_aandelen")
                    ).drop(["value_sprinters"])
        if df_opties is not None and not df_opties.is_empty():
            if "optie_call_put" in df_opties.columns and "waarde_bezit_delta" in df_opties.columns and "value_grow" in df_opties.columns:
                df_put_delta = (
                    df_opties.filter(pl.col("optie_call_put") == "put")
                    .filter(pl.col("value_grow").is_not_null())
                    .group_by("value_grow")
                    .agg(pl.col("waarde_bezit_delta").sum().alias("value_put_delta"))
                )
                df_all_delta = (
                    df_opties.filter(pl.col("value_grow").is_not_null())
                    .group_by("value_grow")
                    .agg(pl.col("waarde_bezit_delta").sum().alias("value_delta_all"))
                )
                if df.is_empty():
                    df = df_put_delta
                else:
                    df = df.join(df_put_delta, on="value_grow", how="left")
                if not df_all_delta.is_empty():
                    if df.is_empty():
                        df = df_all_delta
                    else:
                        df = df.join(df_all_delta, on="value_grow", how="left")
        if not df.is_empty():
            if "value_put_delta" in df.columns:
                df = df.with_columns(pl.col("value_put_delta").fill_null(0.0))
            if "value_delta_all" in df.columns:
                df = df.with_columns(pl.col("value_delta_all").fill_null(0.0))
            if "value_aandelen" in df.columns and "value_put_delta" in df.columns:
                df = df.with_columns(
                    (pl.col("value_aandelen") + pl.col("value_put_delta")).alias("value_aandelen_put_delta")
                )
            elif "value_aandelen" in df.columns and "value_aandelen_put_delta" not in df.columns:
                df = df.with_columns(pl.col("value_aandelen").alias("value_aandelen_put_delta"))
            if "value_aandelen" in df.columns and "value_delta_all" in df.columns:
                df = df.with_columns(
                    (pl.col("value_aandelen") + pl.col("value_delta_all")).alias("value_aandelen_delta_all")
                )
            elif "value_aandelen" in df.columns and "value_aandelen_delta_all" not in df.columns:
                df = df.with_columns(pl.col("value_aandelen").alias("value_aandelen_delta_all"))
            if "value_aandelen_put_delta" in df.columns:
                data["value_aandelen_put_delta"] = {
                    row[0]: row[1] for row in df.select(["value_grow", "value_aandelen_put_delta"]).rows()
                }
            if "value_aandelen_delta_all" in df.columns:
                data["value_aandelen_delta_all"] = {
                    row[0]: row[1] for row in df.select(["value_grow", "value_aandelen_delta_all"]).rows()
                }
        return data

    def _get_sector_order_from_table(self):
        if self._sector_table_proxy is None or self._sector_table_model is None:
            return []
        order = []
        try:
            sector_col = self._sector_table_model._cols.index("sector")
        except Exception:
            return order
        for row in range(self._sector_table_proxy.rowCount()):
            proxy_idx = self._sector_table_proxy.index(row, sector_col)
            src_idx = self._sector_table_proxy.mapToSource(proxy_idx)
            if not src_idx.isValid():
                continue
            val = self._sector_table_model._df[src_idx.row(), sector_col]
            if val is not None:
                order.append(str(val))
        return order

    def _get_value_grow_order_from_table(self):
        if self._value_grow_table_proxy is None or self._value_grow_table_model is None:
            return []
        order = []
        try:
            col_idx = self._value_grow_table_model._cols.index("value_grow")
        except Exception:
            return order
        for row in range(self._value_grow_table_proxy.rowCount()):
            proxy_idx = self._value_grow_table_proxy.index(row, col_idx)
            src_idx = self._value_grow_table_proxy.mapToSource(proxy_idx)
            if not src_idx.isValid():
                continue
            val = self._value_grow_table_model._df[src_idx.row(), col_idx]
            if val is not None:
                order.append(str(val))
        return order

    def _get_sector_order_from_delta_table(self):
        if self._sector_table_delta_proxy is None or self._sector_table_delta_model is None:
            return []
        order = []
        try:
            sector_col = self._sector_table_delta_model._cols.index("sector")
        except Exception:
            return order
        for row in range(self._sector_table_delta_proxy.rowCount()):
            proxy_idx = self._sector_table_delta_proxy.index(row, sector_col)
            src_idx = self._sector_table_delta_proxy.mapToSource(proxy_idx)
            if not src_idx.isValid():
                continue
            val = self._sector_table_delta_model._df[src_idx.row(), sector_col]
            if val is not None:
                order.append(str(val))
        return order

    def _get_value_grow_order_from_delta_table(self):
        if self._value_grow_table_delta_proxy is None or self._value_grow_table_delta_model is None:
            return []
        order = []
        try:
            col_idx = self._value_grow_table_delta_model._cols.index("value_grow")
        except Exception:
            return order
        for row in range(self._value_grow_table_delta_proxy.rowCount()):
            proxy_idx = self._value_grow_table_delta_proxy.index(row, col_idx)
            src_idx = self._value_grow_table_delta_proxy.mapToSource(proxy_idx)
            if not src_idx.isValid():
                continue
            val = self._value_grow_table_delta_model._df[src_idx.row(), col_idx]
            if val is not None:
                order.append(str(val))
        return order

    def _ensure_sector_colors(self):
        all_sectors = sorted({k for data in self._chart_data.values() for k in data.keys()})
        if not all_sectors:
            return
        palette = [
            QColor("#5B9BD5"),
            QColor("#ED7D31"),
            QColor("#A5A5A5"),
            QColor("#FFC000"),
            QColor("#4472C4"),
            QColor("#70AD47"),
            QColor("#264478"),
            QColor("#9E480E"),
            QColor("#636363"),
            QColor("#997300"),
            QColor("#255E91"),
            QColor("#548235"),
            QColor("#7F7F7F"),
            QColor("#C55A11"),
            QColor("#8FAADC"),
            QColor("#F4B183"),
        ]
        for idx, sector in enumerate(all_sectors):
            if sector not in self._sector_color_map:
                self._sector_color_map[sector] = palette[idx % len(palette)]

    def _ensure_value_grow_colors(self):
        all_values = sorted({k for data in self._value_grow_chart_data.values() for k in data.keys()})
        if not all_values:
            return
        palette = [
            QColor("#5B9BD5"),
            QColor("#ED7D31"),
            QColor("#A5A5A5"),
            QColor("#FFC000"),
            QColor("#4472C4"),
            QColor("#70AD47"),
            QColor("#264478"),
            QColor("#9E480E"),
            QColor("#636363"),
            QColor("#997300"),
            QColor("#255E91"),
            QColor("#548235"),
            QColor("#7F7F7F"),
            QColor("#C55A11"),
            QColor("#8FAADC"),
            QColor("#F4B183"),
        ]
        for idx, value_grow in enumerate(all_values):
            if value_grow not in self._value_grow_color_map:
                self._value_grow_color_map[value_grow] = palette[idx % len(palette)]

    def _update_charts_from_table_order(self):
        order = self._get_sector_order_from_table()
        if not order and self._chart_data:
            order = sorted({k for data in self._chart_data.values() for k in data.keys()})
        for chart_name, data in self._chart_data.items():
            if chart_name.startswith("pieChartValueDelta"):
                continue
            self._set_pie_data(chart_name, data, order)

    def _update_delta_charts_from_table_order(self):
        order = self._get_sector_order_from_delta_table()
        if not order and self._chart_data:
            order = sorted({k for data in self._chart_data.values() for k in data.keys()})
        for chart_name in ("pieChartValueDelta", "pieChartValueDeltaPutITM"):
            data = self._chart_data.get(chart_name, {})
            self._set_pie_data(chart_name, data, order)

    def _update_value_grow_charts_from_table_order(self):
        order = self._get_value_grow_order_from_table()
        if not order and self._value_grow_chart_data:
            order = sorted({k for data in self._value_grow_chart_data.values() for k in data.keys()})
        for chart_name, data in self._value_grow_chart_data.items():
            if chart_name.startswith("pieChartValueGrowDelta"):
                continue
            self._set_pie_data(chart_name, data, order)

    def _update_value_grow_delta_charts_from_table_order(self):
        order = self._get_value_grow_order_from_delta_table()
        if not order and self._value_grow_chart_data:
            order = sorted({k for data in self._value_grow_chart_data.values() for k in data.keys()})
        for chart_name in ("pieChartValueGrowDelta", "pieChartValueGrowDeltaPutITM"):
            data = self._value_grow_chart_data.get(chart_name, {})
            self._set_pie_data(chart_name, data, order)

    def _set_pie_data(self, chart_name: str, data: dict, order: list[str] | None = None):
        chart_view = self._chart_views.get(chart_name)
        if chart_view is None:
            return
        chart = chart_view.chart()
        series = chart.series()[0] if chart.series() else None
        if series is None:
            series = QPieSeries()
            chart.addSeries(series)
        series.clear()
        total = 0.0
        for _sector, value in data.items():
            try:
                total += float(value)
            except Exception:
                continue
        if total == 0:
            return
        total = 0.0
        for v in data.values():
            try:
                total += float(v)
            except Exception:
                continue
        ordered_sectors = order if order else list(data.keys())
        for sector in ordered_sectors:
            if sector not in data:
                continue
            value = data.get(sector)
            try:
                val = float(value)
            except Exception:
                continue
            if val == 0:
                continue
            pct = (val / total * 100.0) if total else 0.0
            label = f"{sector}<br/>{val:,.0f} ({pct:.0f}%)"
            slice_item = series.append(label, val)
            color = self._sector_color_map.get(sector)
            if color is None:
                color = self._value_grow_color_map.get(sector)
            if color is not None:
                slice_item.setBrush(color)
            slice_item.setPen(QPen(QColor("#FFFFFF"), 1))
            slice_item.setLabelVisible(True)
            slice_item.setLabelPosition(QPieSlice.LabelOutside)
            slice_item.setLabelArmLengthFactor(0.15)

    def _init_sector_totals_footer(self):
        if not hasattr(self, "tableSectorValuesLineair"):
            self._tbl_sector_totals = None
            return
        self._tbl_sector_totals = QTableWidget(self)
        self._tbl_sector_totals.setRowCount(1)
        self._tbl_sector_totals.setColumnCount(0)
        self._tbl_sector_totals.setFixedHeight(32)
        self._tbl_sector_totals.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._tbl_sector_totals.verticalHeader().setVisible(False)
        self._tbl_sector_totals.horizontalHeader().setVisible(False)
        self._tbl_sector_totals.horizontalHeader().setStretchLastSection(False)
        self._tbl_sector_totals.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._tbl_sector_totals.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._tbl_sector_totals.setEditTriggers(QTableWidget.NoEditTriggers)
        self._tbl_sector_totals.setFocusPolicy(Qt.NoFocus)
        self._tbl_sector_totals.setSelectionMode(QTableWidget.NoSelection)

        parent = self.tableSectorValuesLineair.parentWidget()
        if parent is None:
            return
        self._footer_container = QWidget(parent)
        self._footer_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        footer_layout = QHBoxLayout(self._footer_container)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(0)
        self._footer_spacer = QWidget(self._footer_container)
        self._footer_spacer.setFixedWidth(0)
        footer_layout.addWidget(self._tbl_sector_totals)
        footer_layout.addWidget(self._footer_spacer)

        table_rect = self.tableSectorValuesLineair.geometry()
        self._footer_container.setGeometry(
            table_rect.x(),
            table_rect.y() + table_rect.height(),
            table_rect.width(),
            32,
        )

        self._init_footer_sync()
        self._update_scroll_content_size()

    def _init_value_grow_totals_footer(self):
        if not hasattr(self, "tableValueGrowValuesLineair"):
            self._tbl_value_grow_totals = None
            return
        self._tbl_value_grow_totals = QTableWidget(self)
        self._tbl_value_grow_totals.setRowCount(1)
        self._tbl_value_grow_totals.setColumnCount(0)
        self._tbl_value_grow_totals.setFixedHeight(32)
        self._tbl_value_grow_totals.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._tbl_value_grow_totals.verticalHeader().setVisible(False)
        self._tbl_value_grow_totals.horizontalHeader().setVisible(False)
        self._tbl_value_grow_totals.horizontalHeader().setStretchLastSection(False)
        self._tbl_value_grow_totals.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._tbl_value_grow_totals.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._tbl_value_grow_totals.setEditTriggers(QTableWidget.NoEditTriggers)
        self._tbl_value_grow_totals.setFocusPolicy(Qt.NoFocus)
        self._tbl_value_grow_totals.setSelectionMode(QTableWidget.NoSelection)

        parent = self.tableValueGrowValuesLineair.parentWidget()
        if parent is None:
            return
        self._footer_container_value_grow = QWidget(parent)
        self._footer_container_value_grow.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        footer_layout = QHBoxLayout(self._footer_container_value_grow)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(0)
        self._footer_spacer_value_grow = QWidget(self._footer_container_value_grow)
        self._footer_spacer_value_grow.setFixedWidth(0)
        footer_layout.addWidget(self._tbl_value_grow_totals)
        footer_layout.addWidget(self._footer_spacer_value_grow)

        table_rect = self.tableValueGrowValuesLineair.geometry()
        self._footer_container_value_grow.setGeometry(
            table_rect.x(),
            table_rect.y() + table_rect.height(),
            table_rect.width(),
            32,
        )

        self._init_footer_sync_value_grow()
        self._update_scroll_content_size()

    def _init_footer_sync(self):
        header = self.tableSectorValuesLineair.horizontalHeader()
        header.sectionResized.connect(
            lambda idx, _old, new: self._tbl_sector_totals.setColumnWidth(idx, new)
        )
        header.sectionMoved.connect(
            lambda logical, _old, new: self._tbl_sector_totals.horizontalHeader().moveSection(
                self._tbl_sector_totals.horizontalHeader().visualIndex(logical), new
            )
        )
        main_scroll = self.tableSectorValuesLineair.horizontalScrollBar()
        footer_scroll = self._tbl_sector_totals.horizontalScrollBar()
        main_scroll.valueChanged.connect(footer_scroll.setValue)
        main_scroll.rangeChanged.connect(lambda _min, _max: self._sync_footer_scrollbar_gap())
        self.tableSectorValuesLineair.verticalScrollBar().rangeChanged.connect(
            lambda _min, _max: self._sync_footer_scrollbar_gap()
        )

    def _init_footer_sync_value_grow(self):
        header = self.tableValueGrowValuesLineair.horizontalHeader()
        header.sectionResized.connect(
            lambda idx, _old, new: self._tbl_value_grow_totals.setColumnWidth(idx, new)
        )
        header.sectionMoved.connect(
            lambda logical, _old, new: self._tbl_value_grow_totals.horizontalHeader().moveSection(
                self._tbl_value_grow_totals.horizontalHeader().visualIndex(logical), new
            )
        )
        main_scroll = self.tableValueGrowValuesLineair.horizontalScrollBar()
        footer_scroll = self._tbl_value_grow_totals.horizontalScrollBar()
        main_scroll.valueChanged.connect(footer_scroll.setValue)
        main_scroll.rangeChanged.connect(lambda _min, _max: self._sync_footer_scrollbar_gap_value_grow())
        self.tableValueGrowValuesLineair.verticalScrollBar().rangeChanged.connect(
            lambda _min, _max: self._sync_footer_scrollbar_gap_value_grow()
        )

    def _sync_footer_scrollbar_gap(self):
        v_scroll = self.tableSectorValuesLineair.verticalScrollBar()
        scroll_width = v_scroll.sizeHint().width() if v_scroll.maximum() > 0 else 0
        if hasattr(self, "_footer_spacer") and self._footer_spacer is not None:
            self._footer_spacer.setFixedWidth(scroll_width)

    def _sync_footer_scrollbar_gap_value_grow(self):
        v_scroll = self.tableValueGrowValuesLineair.verticalScrollBar()
        scroll_width = v_scroll.sizeHint().width() if v_scroll.maximum() > 0 else 0
        if hasattr(self, "_footer_spacer_value_grow") and self._footer_spacer_value_grow is not None:
            self._footer_spacer_value_grow.setFixedWidth(scroll_width)

    def _update_sector_totals(self, df: pl.DataFrame):
        if self._tbl_sector_totals is None or df is None or df.is_empty():
            if self._tbl_sector_totals is not None:
                self._tbl_sector_totals.setColumnCount(0)
            return
        cols = list(df.columns)
        self._tbl_sector_totals.setColumnCount(len(cols))
        totals = {}
        for col in cols:
            if col == "sector":
                totals[col] = "TOTAAL"
            elif col.endswith("_pct"):
                totals[col] = 100.0
            else:
                try:
                    totals[col] = float(df[col].sum())
                except Exception:
                    totals[col] = ""
        for i, col in enumerate(cols):
            val = totals.get(col, "")
            if isinstance(val, float) and col.endswith("_pct"):
                text = f"{val:.1f}%"
            elif isinstance(val, float):
                text = f"{val:,.0f}"
            else:
                text = str(val)
            item = QTableWidgetItem(text)
            if col == "sector":
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            else:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            item.setBackground(QColor(242, 242, 242))
            self._tbl_sector_totals.setItem(0, i, item)
        self._sync_footer_section_sizes()

    def _update_value_grow_totals(self, df: pl.DataFrame):
        if self._tbl_value_grow_totals is None or df is None or df.is_empty():
            if self._tbl_value_grow_totals is not None:
                self._tbl_value_grow_totals.setColumnCount(0)
            return
        cols = list(df.columns)
        self._tbl_value_grow_totals.setColumnCount(len(cols))
        totals = {}
        for col in cols:
            if col == "value_grow":
                totals[col] = "TOTAAL"
            elif col.endswith("_pct"):
                totals[col] = 100.0
            else:
                try:
                    totals[col] = float(df[col].sum())
                except Exception:
                    totals[col] = ""
        for i, col in enumerate(cols):
            val = totals.get(col, "")
            if isinstance(val, float) and col.endswith("_pct"):
                text = f"{val:.1f}%"
            elif isinstance(val, float):
                text = f"{val:,.0f}"
            else:
                text = str(val)
            item = QTableWidgetItem(text)
            if col == "value_grow":
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            else:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            item.setBackground(QColor(242, 242, 242))
            self._tbl_value_grow_totals.setItem(0, i, item)
        self._sync_footer_section_sizes_value_grow()

    def _apply_sector_table_widths(self):
        if not hasattr(self, "tableSectorValuesLineair"):
            return
        widths = {
            "sector": 130,
            "value_lineair":80,
            "value_lineair_pct": 80,
            "value_na_opties": 80   ,
            "value_na_opties_pct": 80,
        }
        header = self.tableSectorValuesLineair.horizontalHeader()
        model = getattr(self, "_sector_table_model", None)
        if model is None or model._df is None:
            return
        for i, col in enumerate(model._df.columns):
            if col in widths:
                header.resizeSection(i, widths[col])
        self._sync_footer_section_sizes()

    def _apply_value_grow_table_widths(self):
        if not hasattr(self, "tableValueGrowValuesLineair"):
            return
        widths = {
            "value_grow": 130,
            "value_lineair": 80,
            "value_lineair_pct": 80,
            "value_na_opties": 80,
            "value_na_opties_pct": 80,
        }
        header = self.tableValueGrowValuesLineair.horizontalHeader()
        model = getattr(self, "_value_grow_table_model", None)
        if model is None or model._df is None:
            return
        for i, col in enumerate(model._df.columns):
            if col in widths:
                header.resizeSection(i, widths[col])
        self._sync_footer_section_sizes_value_grow()

    def _apply_sector_table_delta_widths(self):
        if not hasattr(self, "tableSectorValuesDelta"):
            return
        widths = {
            "sector": 130,
            "value_aandelen_put_delta": 80,
            "value_aandelen_put_delta_pct": 80,
            "value_aandelen_delta_all": 80,
            "value_aandelen_delta_all_pct": 80,
        }
        header = self.tableSectorValuesDelta.horizontalHeader()
        model = getattr(self, "_sector_table_delta_model", None)
        if model is None or model._df is None:
            return
        for i, col in enumerate(model._df.columns):
            if col in widths:
                header.resizeSection(i, widths[col])
        self._sync_footer_section_sizes_delta()

    def _apply_value_grow_table_delta_widths(self):
        if not hasattr(self, "tableValueGrowValuesDelta"):
            return
        widths = {
            "value_grow": 130,
            "value_aandelen_put_delta": 80,
            "value_aandelen_put_delta_pct": 80,
            "value_aandelen_delta_all": 80,
            "value_aandelen_delta_all_pct": 80,
        }
        header = self.tableValueGrowValuesDelta.horizontalHeader()
        model = getattr(self, "_value_grow_table_delta_model", None)
        if model is None or model._df is None:
            return
        for i, col in enumerate(model._df.columns):
            if col in widths:
                header.resizeSection(i, widths[col])
        self._sync_footer_section_sizes_value_grow_delta()

    def _init_sector_totals_footer_delta(self):
        if not hasattr(self, "tableSectorValuesDelta"):
            self._tbl_sector_totals_delta = None
            return
        self._tbl_sector_totals_delta = QTableWidget(self)
        self._tbl_sector_totals_delta.setRowCount(1)
        self._tbl_sector_totals_delta.setColumnCount(0)
        self._tbl_sector_totals_delta.setFixedHeight(32)
        self._tbl_sector_totals_delta.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._tbl_sector_totals_delta.verticalHeader().setVisible(False)
        self._tbl_sector_totals_delta.horizontalHeader().setVisible(False)
        self._tbl_sector_totals_delta.horizontalHeader().setStretchLastSection(False)
        self._tbl_sector_totals_delta.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._tbl_sector_totals_delta.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._tbl_sector_totals_delta.setEditTriggers(QTableWidget.NoEditTriggers)
        self._tbl_sector_totals_delta.setFocusPolicy(Qt.NoFocus)
        self._tbl_sector_totals_delta.setSelectionMode(QTableWidget.NoSelection)

        parent = self.tableSectorValuesDelta.parentWidget()
        if parent is None:
            return
        self._footer_container_delta = QWidget(parent)
        self._footer_container_delta.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        footer_layout = QHBoxLayout(self._footer_container_delta)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(0)
        self._footer_spacer_delta = QWidget(self._footer_container_delta)
        self._footer_spacer_delta.setFixedWidth(0)
        footer_layout.addWidget(self._tbl_sector_totals_delta)
        footer_layout.addWidget(self._footer_spacer_delta)

        table_rect = self.tableSectorValuesDelta.geometry()
        self._footer_container_delta.setGeometry(
            table_rect.x(),
            table_rect.y() + table_rect.height(),
            table_rect.width(),
            32,
        )

        self._init_footer_sync_delta()
        self._update_scroll_content_size()

    def _init_value_grow_totals_footer_delta(self):
        if not hasattr(self, "tableValueGrowValuesDelta"):
            self._tbl_value_grow_totals_delta = None
            return
        self._tbl_value_grow_totals_delta = QTableWidget(self)
        self._tbl_value_grow_totals_delta.setRowCount(1)
        self._tbl_value_grow_totals_delta.setColumnCount(0)
        self._tbl_value_grow_totals_delta.setFixedHeight(32)
        self._tbl_value_grow_totals_delta.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._tbl_value_grow_totals_delta.verticalHeader().setVisible(False)
        self._tbl_value_grow_totals_delta.horizontalHeader().setVisible(False)
        self._tbl_value_grow_totals_delta.horizontalHeader().setStretchLastSection(False)
        self._tbl_value_grow_totals_delta.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._tbl_value_grow_totals_delta.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._tbl_value_grow_totals_delta.setEditTriggers(QTableWidget.NoEditTriggers)
        self._tbl_value_grow_totals_delta.setFocusPolicy(Qt.NoFocus)
        self._tbl_value_grow_totals_delta.setSelectionMode(QTableWidget.NoSelection)

        parent = self.tableValueGrowValuesDelta.parentWidget()
        if parent is None:
            return
        self._footer_container_value_grow_delta = QWidget(parent)
        self._footer_container_value_grow_delta.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        footer_layout = QHBoxLayout(self._footer_container_value_grow_delta)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(0)
        self._footer_spacer_value_grow_delta = QWidget(self._footer_container_value_grow_delta)
        self._footer_spacer_value_grow_delta.setFixedWidth(0)
        footer_layout.addWidget(self._tbl_value_grow_totals_delta)
        footer_layout.addWidget(self._footer_spacer_value_grow_delta)

        table_rect = self.tableValueGrowValuesDelta.geometry()
        self._footer_container_value_grow_delta.setGeometry(
            table_rect.x(),
            table_rect.y() + table_rect.height(),
            table_rect.width(),
            32,
        )

        self._init_footer_sync_value_grow_delta()
        self._update_scroll_content_size()

    def _init_footer_sync_delta(self):
        header = self.tableSectorValuesDelta.horizontalHeader()
        header.sectionResized.connect(
            lambda idx, _old, new: self._tbl_sector_totals_delta.setColumnWidth(idx, new)
        )
        header.sectionMoved.connect(
            lambda logical, _old, new: self._tbl_sector_totals_delta.horizontalHeader().moveSection(
                self._tbl_sector_totals_delta.horizontalHeader().visualIndex(logical), new
            )
        )
        main_scroll = self.tableSectorValuesDelta.horizontalScrollBar()
        footer_scroll = self._tbl_sector_totals_delta.horizontalScrollBar()
        main_scroll.valueChanged.connect(footer_scroll.setValue)
        main_scroll.rangeChanged.connect(lambda _min, _max: self._sync_footer_scrollbar_gap_delta())
        self.tableSectorValuesDelta.verticalScrollBar().rangeChanged.connect(
            lambda _min, _max: self._sync_footer_scrollbar_gap_delta()
        )

    def _init_footer_sync_value_grow_delta(self):
        header = self.tableValueGrowValuesDelta.horizontalHeader()
        header.sectionResized.connect(
            lambda idx, _old, new: self._tbl_value_grow_totals_delta.setColumnWidth(idx, new)
        )
        header.sectionMoved.connect(
            lambda logical, _old, new: self._tbl_value_grow_totals_delta.horizontalHeader().moveSection(
                self._tbl_value_grow_totals_delta.horizontalHeader().visualIndex(logical), new
            )
        )
        main_scroll = self.tableValueGrowValuesDelta.horizontalScrollBar()
        footer_scroll = self._tbl_value_grow_totals_delta.horizontalScrollBar()
        main_scroll.valueChanged.connect(footer_scroll.setValue)
        main_scroll.rangeChanged.connect(lambda _min, _max: self._sync_footer_scrollbar_gap_value_grow_delta())
        self.tableValueGrowValuesDelta.verticalScrollBar().rangeChanged.connect(
            lambda _min, _max: self._sync_footer_scrollbar_gap_value_grow_delta()
        )

    def _sync_footer_scrollbar_gap_delta(self):
        v_scroll = self.tableSectorValuesDelta.verticalScrollBar()
        scroll_width = v_scroll.sizeHint().width() if v_scroll.maximum() > 0 else 0
        if hasattr(self, "_footer_spacer_delta") and self._footer_spacer_delta is not None:
            self._footer_spacer_delta.setFixedWidth(scroll_width)

    def _sync_footer_scrollbar_gap_value_grow_delta(self):
        v_scroll = self.tableValueGrowValuesDelta.verticalScrollBar()
        scroll_width = v_scroll.sizeHint().width() if v_scroll.maximum() > 0 else 0
        if hasattr(self, "_footer_spacer_value_grow_delta") and self._footer_spacer_value_grow_delta is not None:
            self._footer_spacer_value_grow_delta.setFixedWidth(scroll_width)

    def _update_sector_totals_delta(self, df: pl.DataFrame):
        if self._tbl_sector_totals_delta is None or df is None or df.is_empty():
            if self._tbl_sector_totals_delta is not None:
                self._tbl_sector_totals_delta.setColumnCount(0)
            return
        cols = list(df.columns)
        self._tbl_sector_totals_delta.setColumnCount(len(cols))
        totals = {}
        for col in cols:
            if col == "sector":
                totals[col] = "TOTAAL"
            elif col.endswith("_pct"):
                totals[col] = 100.0
            else:
                try:
                    totals[col] = float(df[col].sum())
                except Exception:
                    totals[col] = ""
        for i, col in enumerate(cols):
            val = totals.get(col, "")
            if isinstance(val, float) and col.endswith("_pct"):
                text = f"{val:.1f}%"
            elif isinstance(val, float):
                text = f"{val:,.0f}"
            else:
                text = str(val)
            item = QTableWidgetItem(text)
            if col == "sector":
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            else:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            item.setBackground(QColor(242, 242, 242))
            self._tbl_sector_totals_delta.setItem(0, i, item)
        self._sync_footer_section_sizes_delta()

    def _update_value_grow_totals_delta(self, df: pl.DataFrame):
        if self._tbl_value_grow_totals_delta is None or df is None or df.is_empty():
            if self._tbl_value_grow_totals_delta is not None:
                self._tbl_value_grow_totals_delta.setColumnCount(0)
            return
        cols = list(df.columns)
        self._tbl_value_grow_totals_delta.setColumnCount(len(cols))
        totals = {}
        for col in cols:
            if col == "value_grow":
                totals[col] = "TOTAAL"
            elif col.endswith("_pct"):
                totals[col] = 100.0
            else:
                try:
                    totals[col] = float(df[col].sum())
                except Exception:
                    totals[col] = ""
        for i, col in enumerate(cols):
            val = totals.get(col, "")
            if isinstance(val, float) and col.endswith("_pct"):
                text = f"{val:.1f}%"
            elif isinstance(val, float):
                text = f"{val:,.0f}"
            else:
                text = str(val)
            item = QTableWidgetItem(text)
            if col == "value_grow":
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            else:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            item.setBackground(QColor(242, 242, 242))
            self._tbl_value_grow_totals_delta.setItem(0, i, item)
        self._sync_footer_section_sizes_value_grow_delta()

    def _sync_footer_section_sizes(self):
        if getattr(self, "_tbl_sector_totals", None) is None:
            return
        header = self.tableSectorValuesLineair.horizontalHeader()
        for i in range(header.count()):
            self._tbl_sector_totals.setColumnWidth(i, header.sectionSize(i))
        self._tbl_sector_totals.horizontalScrollBar().setValue(
            self.tableSectorValuesLineair.horizontalScrollBar().value()
        )

    def _sync_footer_section_sizes_value_grow(self):
        if getattr(self, "_tbl_value_grow_totals", None) is None:
            return
        header = self.tableValueGrowValuesLineair.horizontalHeader()
        for i in range(header.count()):
            self._tbl_value_grow_totals.setColumnWidth(i, header.sectionSize(i))
        self._tbl_value_grow_totals.horizontalScrollBar().setValue(
            self.tableValueGrowValuesLineair.horizontalScrollBar().value()
        )

    def _sync_footer_section_sizes_delta(self):
        if getattr(self, "_tbl_sector_totals_delta", None) is None:
            return
        header = self.tableSectorValuesDelta.horizontalHeader()
        for i in range(header.count()):
            self._tbl_sector_totals_delta.setColumnWidth(i, header.sectionSize(i))
        self._tbl_sector_totals_delta.horizontalScrollBar().setValue(
            self.tableSectorValuesDelta.horizontalScrollBar().value()
        )

    def _sync_footer_section_sizes_value_grow_delta(self):
        if getattr(self, "_tbl_value_grow_totals_delta", None) is None:
            return
        header = self.tableValueGrowValuesDelta.horizontalHeader()
        for i in range(header.count()):
            self._tbl_value_grow_totals_delta.setColumnWidth(i, header.sectionSize(i))
        self._tbl_value_grow_totals_delta.horizontalScrollBar().setValue(
            self.tableValueGrowValuesDelta.horizontalScrollBar().value()
        )

    def _wrap_in_scroll_area(self) -> None:
        try:
            if getattr(self, "_sector_scroll_area", None) is not None:
                return

            content = QWidget()
            for child in self.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
                if child is content:
                    continue
                child.setParent(content)

            max_w = 0
            max_h = 0
            for child in content.findChildren(QWidget):
                g = child.geometry()
                max_w = max(max_w, g.x() + g.width())
                max_h = max(max_h, g.y() + g.height())
            if max_w > 0 and max_h > 0:
                content.setMinimumSize(max_w + 10, max_h + 10)

            scroll = QScrollArea(self)
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            scroll.setWidget(content)
            scroll.setGeometry(self.rect())

            self._sector_scroll_area = scroll
        except Exception as exc:
            print(f"[ui] kon SectorAnalysisTab niet scrollbaar maken: {exc}")

    def _update_scroll_content_size(self) -> None:
        scroll = getattr(self, "_sector_scroll_area", None)
        if scroll is None:
            return
        content = scroll.widget()
        if content is None:
            return
        max_w = 0
        max_h = 0
        for child in content.findChildren(QWidget):
            g = child.geometry()
            max_w = max(max_w, g.x() + g.width())
            max_h = max(max_h, g.y() + g.height())
        if max_w > 0 and max_h > 0:
            content.setMinimumSize(max_w + 10, max_h + 10)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "_sector_scroll_area", None) is not None:
            self._sector_scroll_area.setGeometry(self.rect())


class SectorTableModel(PolarsTableModel):
    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or self._df.is_empty():
            return None
        col_name = self._cols[index.column()]
        val = self._df[index.row(), index.column()]
        if role == Qt.DisplayRole and col_name.endswith("_pct"):
            if val is None:
                return ""
            try:
                return f"{float(val):.1f}%"
            except Exception:
                return str(val)
        if role == Qt.DisplayRole and col_name in (
            "value_lineair",
            "value_na_opties",
            "value_delta_1",
            "value_delta_2",
            "value_delta_3",
            "value_aandelen",
            "value_put_delta",
            "value_aandelen_put_delta",
            "value_aandelen_delta_all",
        ):
            if val is None:
                return ""
            try:
                return f"{float(val):,.0f}"
            except Exception:
                return str(val)
        return super().data(index, role)
