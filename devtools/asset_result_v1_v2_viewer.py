from __future__ import annotations

import os
import sys
from datetime import date, datetime
from pathlib import Path

import pyodbc
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# Forceer pyqtgraph om dezelfde Qt-binding te gebruiken als deze app.
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")
import pyqtgraph as pg
from pyqtgraph import ViewBox


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from portefeuille_viewer.config import get_databases, get_default_database  # noqa: E402
from state_engine.common import DEFAULT_DB_PATH  # noqa: E402


def resolve_db_path() -> str:
    databases = get_databases()
    default_name = get_default_database()
    if default_name and default_name in databases:
        return databases[default_name]["path"]
    return DEFAULT_DB_PATH


def to_timestamp(value) -> float | None:
    if value is None:
        return None
    epoch = datetime(1970, 1, 1)
    if isinstance(value, datetime):
        return (value - epoch).total_seconds()
    if isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
        return (dt - epoch).total_seconds()
    return None


class AssetResultViewer(QMainWindow):
    def __init__(self, db_path: str):
        super().__init__()
        self.db_path = db_path
        self.setWindowTitle("Asset Resultaat Vergelijking (v1 vs v2)")
        self.resize(1100, 650)

        self.combo_assets = QComboBox()
        self.combo_assets.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.combo_assets.currentTextChanged.connect(self.on_asset_changed)
        self.chk_v1_result = QCheckBox("v1 resultaat")
        self.chk_v1_result.setChecked(True)
        self.chk_v1_result.toggled.connect(self._redraw_current_asset)
        self.chk_v2_result = QCheckBox("v2 resultaat")
        self.chk_v2_result.setChecked(True)
        self.chk_v2_result.toggled.connect(self._redraw_current_asset)
        self.chk_v1_qty = QCheckBox("v1 hoeveelheid")
        self.chk_v1_qty.setChecked(True)
        self.chk_v1_qty.toggled.connect(self._redraw_current_asset)
        self.chk_v2_qty = QCheckBox("v2 hoeveelheid")
        self.chk_v2_qty.setChecked(True)
        self.chk_v2_qty.toggled.connect(self._redraw_current_asset)

        self.label_db = QLabel(f"DB: {self.db_path}")
        self.label_db.setStyleSheet("color: #555;")

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Asset:"))
        top_row.addWidget(self.combo_assets)
        top_row.addSpacing(12)
        top_row.addWidget(self.chk_v1_result)
        top_row.addWidget(self.chk_v2_result)
        top_row.addWidget(self.chk_v1_qty)
        top_row.addWidget(self.chk_v2_qty)
        top_row.addStretch()
        top_row.addWidget(self.label_db)

        date_axis = pg.DateAxisItem(orientation="bottom")
        self.chart = pg.PlotWidget(axisItems={"bottom": date_axis})
        self.chart.showGrid(x=True, y=True, alpha=0.25)
        self.chart.addLegend()
        self.chart.setLabel("bottom", "Datum")
        self.chart.setLabel("left", "Resultaat")
        self._right_view = ViewBox()
        self._setup_right_axis()

        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.addLayout(top_row)
        layout.addWidget(self.chart)
        self.setCentralWidget(wrapper)

        self._load_assets()

    def _setup_right_axis(self) -> None:
        pi = self.chart.plotItem
        pi.showAxis("right")
        pi.scene().addItem(self._right_view)
        pi.getAxis("right").linkToView(self._right_view)
        self._right_view.setXLink(pi)
        pi.getAxis("right").setLabel("Aantal bezit (v2)", color="#2ca02c")
        self._update_right_axis_geometry()
        pi.vb.sigResized.connect(self._update_right_axis_geometry)

    def _update_right_axis_geometry(self) -> None:
        pi = self.chart.plotItem
        self._right_view.setGeometry(pi.vb.sceneBoundingRect())
        self._right_view.linkedViewChanged(pi.vb, self._right_view.XAxis)

    @staticmethod
    def _range_with_aligned_zero(left_min: float, left_max: float, data_min: float, data_max: float) -> tuple[float, float]:
        # Match the zero-height ratio of left axis on the right axis while keeping all right-axis data visible.
        if left_max <= left_min:
            left_min, left_max = -1.0, 1.0

        left_span = left_max - left_min
        f = (0.0 - left_min) / left_span  # 0 at bottom=0, top=1

        eps = 1e-9
        if f <= eps:
            rmin = min(0.0, data_min)
            rmax = max(eps, data_max)
            return rmin, rmax
        if f >= 1.0 - eps:
            rmin = min(data_min, -eps)
            rmax = max(0.0, data_max)
            return rmin, rmax

        k = (1.0 - f) / f  # b = k * a, where range is [-a, +b]
        need_a = max(0.0, -data_min, data_max / k if k > eps else 0.0)
        a = max(need_a, eps)
        b = max(k * a, eps)
        return -a, b

    def _get_connection(self) -> pyodbc.Connection:
        conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={self.db_path};"
        return pyodbc.connect(conn_str)

    def _load_assets(self) -> None:
        sql = """
            SELECT asset_rollup FROM per_dag_asset_result
            UNION
            SELECT asset_rollup FROM per_dag_asset_result_v2
            ORDER BY asset_rollup
        """
        try:
            with self._get_connection() as conn:
                rows = conn.cursor().execute(sql).fetchall()
        except Exception as exc:
            QMessageBox.critical(self, "Database fout", f"Assets laden mislukt:\n{exc}")
            return

        assets = [str(r[0]).strip() for r in rows if r and r[0] is not None and str(r[0]).strip()]
        self.combo_assets.blockSignals(True)
        self.combo_assets.clear()
        self.combo_assets.addItems(assets)
        self.combo_assets.blockSignals(False)
        if assets:
            self.combo_assets.setCurrentIndex(0)
            self.on_asset_changed(assets[0])

    def _load_series(
        self, asset_rollup: str
    ) -> tuple[list[float], list[float], list[float], list[float], list[float], list[float], list[float], list[float]]:
        sql_v1 = """
            SELECT datum, totaal, totaal_aantal_bezit
            FROM per_dag_asset_result
            WHERE asset_rollup = ?
            ORDER BY datum
        """
        sql_v2 = """
            SELECT datum, totaal_v2, totaal_aantal_bezit_v2
            FROM per_dag_asset_result_v2
            WHERE asset_rollup = ?
            ORDER BY datum
        """

        with self._get_connection() as conn:
            cur = conn.cursor()
            rows_v1 = cur.execute(sql_v1, (asset_rollup,)).fetchall()
            rows_v2 = cur.execute(sql_v2, (asset_rollup,)).fetchall()

        x_v1: list[float] = []
        y_v1: list[float] = []
        y_qty_v1: list[float] = []
        for row in rows_v1:
            ts = to_timestamp(row[0])
            if ts is None:
                continue
            x_v1.append(ts)
            y_v1.append(float(row[1] or 0.0))
            y_qty_v1.append(float(row[2] or 0.0))

        x_v2: list[float] = []
        y_v2: list[float] = []
        y_qty_v2: list[float] = []
        for row in rows_v2:
            ts = to_timestamp(row[0])
            if ts is None:
                continue
            x_v2.append(ts)
            y_v2.append(float(row[1] or 0.0))
            y_qty_v2.append(float(row[2] or 0.0))

        return x_v1, y_v1, x_v2, y_v2, x_v1, y_qty_v1, x_v2, y_qty_v2

    def on_asset_changed(self, asset_rollup: str) -> None:
        if not asset_rollup:
            return

        try:
            x_v1, y_v1, x_v2, y_v2, x_qty_v1, y_qty_v1, x_qty_v2, y_qty_v2 = self._load_series(asset_rollup)
        except Exception as exc:
            QMessageBox.critical(self, "Database fout", f"Data laden mislukt voor {asset_rollup}:\n{exc}")
            return

        self.chart.clear()
        self.chart.addLegend()
        self._right_view.clear()
        if self.chk_v1_result.isChecked():
            self.chart.plot(
                x_v1,
                y_v1,
                pen=pg.mkPen("#1f77b4", width=2),
                name="v1 totaal",
                symbol=None,
            )
        if self.chk_v2_result.isChecked():
            self.chart.plot(
                x_v2,
                y_v2,
                pen=pg.mkPen("#ff7f0e", width=2),
                name="v2 totaal",
                symbol=None,
            )
        if self.chk_v1_qty.isChecked():
            self._right_view.addItem(
                pg.PlotCurveItem(
                    x_qty_v1,
                    y_qty_v1,
                    pen=pg.mkPen("#98df8a", width=2),
                    name="v1 aantal bezit",
                )
            )
        if self.chk_v2_qty.isChecked():
            self._right_view.addItem(
                pg.PlotCurveItem(
                    x_qty_v2,
                    y_qty_v2,
                    pen=pg.mkPen("#d62728", width=2),
                    name="v2 aantal bezit",
                )
            )
        self.chart.plotItem.vb.autoRange()
        left_min, left_max = self.chart.plotItem.vb.viewRange()[1]
        qty_values: list[float] = []
        if self.chk_v1_qty.isChecked():
            qty_values.extend(y_qty_v1)
        if self.chk_v2_qty.isChecked():
            qty_values.extend(y_qty_v2)
        if qty_values:
            right_min, right_max = self._range_with_aligned_zero(
                float(left_min),
                float(left_max),
                float(min(qty_values)),
                float(max(qty_values)),
            )
            self._right_view.setYRange(right_min, right_max, padding=0.0)
        self._update_right_axis_geometry()

        if not x_v1 and not x_v2:
            self.statusBar().showMessage(f"Geen data voor asset: {asset_rollup}")
        else:
            self.statusBar().showMessage(
                f"Asset: {asset_rollup} | v1 punten: {len(x_v1)} | v2 punten: {len(x_v2)} | qty v1: {len(x_qty_v1)} | qty v2: {len(x_qty_v2)}"
            )

    def _redraw_current_asset(self) -> None:
        asset = self.combo_assets.currentText().strip()
        if asset:
            self.on_asset_changed(asset)


def main() -> None:
    app = QApplication(sys.argv)
    db_path = resolve_db_path()
    window = AssetResultViewer(db_path)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
