from __future__ import annotations

import os
import sys
from datetime import date, datetime
from pathlib import Path

import pyodbc
from PySide6.QtWidgets import (
    QApplication,
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

        self.label_db = QLabel(f"DB: {self.db_path}")
        self.label_db.setStyleSheet("color: #555;")

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Asset:"))
        top_row.addWidget(self.combo_assets)
        top_row.addStretch()
        top_row.addWidget(self.label_db)

        date_axis = pg.DateAxisItem(orientation="bottom")
        self.chart = pg.PlotWidget(axisItems={"bottom": date_axis})
        self.chart.showGrid(x=True, y=True, alpha=0.25)
        self.chart.addLegend()
        self.chart.setLabel("bottom", "Datum")
        self.chart.setLabel("left", "Resultaat")

        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.addLayout(top_row)
        layout.addWidget(self.chart)
        self.setCentralWidget(wrapper)

        self._load_assets()

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

    def _load_series(self, asset_rollup: str) -> tuple[list[float], list[float], list[float], list[float]]:
        sql_v1 = """
            SELECT datum, totaal
            FROM per_dag_asset_result
            WHERE asset_rollup = ?
            ORDER BY datum
        """
        sql_v2 = """
            SELECT datum, totaal_v2
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
        for row in rows_v1:
            ts = to_timestamp(row[0])
            if ts is None:
                continue
            x_v1.append(ts)
            y_v1.append(float(row[1] or 0.0))

        x_v2: list[float] = []
        y_v2: list[float] = []
        for row in rows_v2:
            ts = to_timestamp(row[0])
            if ts is None:
                continue
            x_v2.append(ts)
            y_v2.append(float(row[1] or 0.0))

        return x_v1, y_v1, x_v2, y_v2

    def on_asset_changed(self, asset_rollup: str) -> None:
        if not asset_rollup:
            return

        try:
            x_v1, y_v1, x_v2, y_v2 = self._load_series(asset_rollup)
        except Exception as exc:
            QMessageBox.critical(self, "Database fout", f"Data laden mislukt voor {asset_rollup}:\n{exc}")
            return

        self.chart.clear()
        self.chart.addLegend()
        self.chart.plot(
            x_v1,
            y_v1,
            pen=pg.mkPen("#1f77b4", width=2),
            name="v1 totaal",
            symbol=None,
        )
        self.chart.plot(
            x_v2,
            y_v2,
            pen=pg.mkPen("#ff7f0e", width=2),
            name="v2 totaal",
            symbol=None,
        )

        if not x_v1 and not x_v2:
            self.statusBar().showMessage(f"Geen data voor asset: {asset_rollup}")
        else:
            self.statusBar().showMessage(f"Asset: {asset_rollup} | v1 punten: {len(x_v1)} | v2 punten: {len(x_v2)}")


def main() -> None:
    app = QApplication(sys.argv)
    db_path = resolve_db_path()
    window = AssetResultViewer(db_path)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
