from __future__ import annotations

import pandas as pd
import polars as pl

from PySide6.QtCore import Qt, QDate, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from portefeuille_viewer.config import get_settings
from portefeuille_viewer.data.repository import load_reference_lists
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE


DISPLAY_COLS = [
    ("Id",                      "Id"),
    ("datum",                   "Datum"),
    ("broker",                  "Broker"),
    ("asset_rollup",            "Asset"),
    ("asset_detail",            "Detail"),
    ("asset_type",              "Type"),
    ("transactie_type",         "Trans.type"),
    ("transactie_aantal",       "Aantal"),
    ("transactie_prijs",        "Prijs"),
    ("transactie_fee",          "Fee"),
    ("optie_exp_date",          "Exp.date"),
    ("optie_strike",            "Strike"),
    ("optie_call_put",          "C/P"),
    ("transactie_euro_totaal",  "Totaal"),
]

CHECK_COL = len(DISPLAY_COLS)

# Kolommen met numerieke waarden die rechts uitgelijnd worden
_RIGHT_ALIGN_COLS = {7, 8, 9, 11, 13}


def _fmt(val, col: str) -> str:
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return ""
    except Exception:
        pass
    try:
        if pd.isna(val):
            return ""
    except Exception:
        pass

    if col in ("datum", "optie_exp_date"):
        try:
            d = pd.to_datetime(val, errors="coerce")
            return d.strftime("%d/%m/%Y") if pd.notna(d) else ""
        except Exception:
            return str(val)

    if col in ("transactie_prijs", "transactie_fee", "transactie_euro_totaal", "optie_strike"):
        try:
            f = float(val)
            return f"{f:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except Exception:
            return str(val)

    if col == "transactie_aantal":
        try:
            f = float(val)
            if f == int(f):
                return f"{int(f):,}".replace(",", ".")
            return str(f)
        except Exception:
            return str(val)

    return str(val) if val is not None else ""


class _TransactiesTable(QTableWidget):
    """QTableWidget — Space togglet vinkje op huidige rij, sortering via header."""

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space:
            row = self.currentRow()
            if row >= 0:
                item = self.item(row, CHECK_COL)
                if item is not None:
                    new = Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked
                    item.setCheckState(new)
            return
        super().keyPressEvent(event)


class LaatstTransactiesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Laatste Transacties")
        self.setModal(False)
        self.setWindowFlags(
            Qt.Window |
            Qt.WindowMinimizeButtonHint |
            Qt.WindowMaximizeButtonHint |
            Qt.WindowCloseButtonHint
        )
        self.resize(1400, 680)
        self._checked_ids: set[int] = set()

        # Timer om snel achtereenvolgende resize-events samen te voegen
        self._save_widths_timer = QTimer(self)
        self._save_widths_timer.setSingleShot(True)
        self._save_widths_timer.setInterval(400)
        self._save_widths_timer.timeout.connect(self._save_col_widths)

        self._build_ui()
        self._populate_combos()
        self._restore_geometry()
        self._load_col_widths()
        self._fetch_and_show()

    # ------------------------------------------------------------------
    # UI opbouw
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(4)

        # ── Filterbalk (boven de tabel) ──────────────────────────────
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(6)

        # Linker blok: 2 rijen met velden
        fields_grid = QGridLayout()
        fields_grid.setSpacing(4)
        fields_grid.setHorizontalSpacing(6)

        ys = "background-color: #FFFF99;"

        # Rij 0: van / tot / broker / asset
        fields_grid.addWidget(QLabel("van"), 0, 0)
        self._date_van = QDateEdit()
        self._date_van.setCalendarPopup(True)
        self._date_van.setDisplayFormat("dd-MM-yy")
        self._date_van.setDate(QDate.currentDate())
        self._date_van.setStyleSheet(ys)
        self._date_van.setFixedWidth(90)
        fields_grid.addWidget(self._date_van, 0, 1)

        fields_grid.addWidget(QLabel("tot"), 0, 2)
        self._date_tot = QDateEdit()
        self._date_tot.setCalendarPopup(True)
        self._date_tot.setDisplayFormat("dd-MM-yy")
        self._date_tot.setDate(QDate.currentDate())
        self._date_tot.setStyleSheet(ys)
        self._date_tot.setFixedWidth(90)
        fields_grid.addWidget(self._date_tot, 0, 3)

        fields_grid.addWidget(QLabel("Broker"), 0, 4)
        self._combo_broker = QComboBox()
        self._combo_broker.setEditable(True)
        self._combo_broker.setStyleSheet(ys)
        self._combo_broker.setFixedWidth(110)
        fields_grid.addWidget(self._combo_broker, 0, 5)

        fields_grid.addWidget(QLabel("Asset"), 0, 6)
        self._combo_asset = QComboBox()
        self._combo_asset.setEditable(True)
        self._combo_asset.setStyleSheet(ys)
        self._combo_asset.setFixedWidth(110)
        fields_grid.addWidget(self._combo_asset, 0, 7)

        # Rij 1: asset type / call_put / strike / expire / hint
        fields_grid.addWidget(QLabel("Type"), 1, 0)
        self._combo_asset_type = QComboBox()
        self._combo_asset_type.addItems(["", "aandeel", "optie", "sprinter"])
        self._combo_asset_type.setStyleSheet(ys)
        self._combo_asset_type.setFixedWidth(90)
        fields_grid.addWidget(self._combo_asset_type, 1, 1)

        fields_grid.addWidget(QLabel("Call/Put"), 1, 2)
        self._combo_call_put = QComboBox()
        self._combo_call_put.addItems(["", "call", "put"])
        self._combo_call_put.setStyleSheet(ys)
        self._combo_call_put.setFixedWidth(70)
        fields_grid.addWidget(self._combo_call_put, 1, 3)

        fields_grid.addWidget(QLabel("Strike"), 1, 4)
        self._edit_strike = QLineEdit()
        self._edit_strike.setStyleSheet(ys)
        self._edit_strike.setFixedWidth(70)
        fields_grid.addWidget(self._edit_strike, 1, 5)

        fields_grid.addWidget(QLabel("Exp.date"), 1, 6)
        self._edit_expire = QLineEdit()
        self._edit_expire.setPlaceholderText("d-m-jj")
        self._edit_expire.setStyleSheet(ys)
        self._edit_expire.setFixedWidth(70)
        fields_grid.addWidget(self._edit_expire, 1, 7)

        lbl_hint = QLabel("leeg = allemaal")
        lbl_hint.setStyleSheet("color: gray; font-style: italic; font-size: 10px;")
        fields_grid.addWidget(lbl_hint, 1, 8)

        filter_bar.addLayout(fields_grid)
        filter_bar.addStretch()

        # Rechter blok: knop + teller, uitgelijnd naast de 2 rijen
        right_vbox = QVBoxLayout()
        right_vbox.setSpacing(4)
        self._btn_fetch = QPushButton("Transacties ophalen")
        self._btn_fetch.setStyleSheet(
            "background-color: #FF6B6B; color: white; font-weight: bold; padding: 4px 10px;"
        )
        self._btn_fetch.clicked.connect(self._fetch_and_show)
        right_vbox.addWidget(self._btn_fetch)

        self._lbl_count = QLabel("Aantal Records: 0")
        self._lbl_count.setStyleSheet("font-weight: bold;")
        right_vbox.addWidget(self._lbl_count)

        filter_bar.addLayout(right_vbox)
        root.addLayout(filter_bar)

        # ── Tabel (onder de filterbalk) ──────────────────────────────
        self._table = _TransactiesTable()
        self._table.setColumnCount(CHECK_COL + 1)
        headers = [h for _, h in DISPLAY_COLS] + ["✓"]
        self._table.setHorizontalHeaderLabels(headers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setStyleSheet(
            "QTableWidget::item:selected { background-color: #FFF2CC; color: #000000; }"
        )

        hdr = self._table.horizontalHeader()
        hdr.setSectionsClickable(True)
        hdr.setSortIndicatorShown(True)
        hdr.setSectionResizeMode(QHeaderView.Interactive)
        hdr.setStretchLastSection(False)
        hdr.sectionResized.connect(lambda *_: self._save_widths_timer.start())
        self._table.setSortingEnabled(True)

        root.addWidget(self._table)

    # ------------------------------------------------------------------
    # Window geometry persistentie
    # ------------------------------------------------------------------

    def _restore_geometry(self):
        geo = get_settings().get_laatste_transacties_window_geometry()
        if geo:
            screens = QGuiApplication.screens()
            on_screen = any(
                s.geometry().contains(geo['x'] + 50, geo['y'] + 50)
                for s in screens
            )
            if on_screen:
                self.setGeometry(geo['x'], geo['y'], geo['w'], geo['h'])
                return
        self.resize(1400, 680)

    def _save_geometry(self):
        g = self.geometry()
        get_settings().set_laatste_transacties_window_geometry(g.x(), g.y(), g.width(), g.height())

    def closeEvent(self, event):
        self._save_geometry()
        if getattr(self, '_force_close', False):
            event.accept()
        else:
            event.accept()  # deze dialog sluit normaal bij X

    # ------------------------------------------------------------------
    # Kolombreedte persistentie
    # ------------------------------------------------------------------

    def _load_col_widths(self):
        saved = get_settings().get_laatste_transacties_col_widths()
        hdr = self._table.horizontalHeader()
        for col_idx, (col_key, _) in enumerate(DISPLAY_COLS):
            if col_key in saved:
                hdr.resizeSection(col_idx, saved[col_key])
        hdr.resizeSection(CHECK_COL, saved.get("__check__", 30))
        hdr.setSectionResizeMode(CHECK_COL, QHeaderView.Fixed)

    def _save_col_widths(self):
        hdr = self._table.horizontalHeader()
        widths = {col_key: hdr.sectionSize(i) for i, (col_key, _) in enumerate(DISPLAY_COLS)}
        widths["__check__"] = hdr.sectionSize(CHECK_COL)
        get_settings().set_laatste_transacties_col_widths(widths)

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def _populate_combos(self):
        brokers, asset_rollups, _ = load_reference_lists()
        self._combo_broker.addItem("")
        self._combo_broker.addItems(brokers)
        self._combo_asset.addItem("")
        self._combo_asset.addItems(sorted(asset_rollups))

    def _fetch_and_show(self):
        df_pl: pl.DataFrame | None = getattr(
            SNAPSHOT_STORE, "repository_snapshot_alle_transacties", None
        )
        if df_pl is None or df_pl.is_empty():
            self._table.setRowCount(0)
            self._lbl_count.setText("Aantal Records: 0")
            return

        van = self._date_van.date().toPython()
        tot = self._date_tot.date().toPython()

        if "datum" in df_pl.columns:
            df_pl = df_pl.filter(
                (pl.col("datum").dt.date() >= van) &
                (pl.col("datum").dt.date() <= tot)
            )

        broker = self._combo_broker.currentText().strip()
        if broker and "broker" in df_pl.columns:
            df_pl = df_pl.filter(pl.col("broker") == broker)

        asset = self._combo_asset.currentText().strip()
        if asset and "asset_rollup" in df_pl.columns:
            df_pl = df_pl.filter(pl.col("asset_rollup") == asset)

        asset_type = self._combo_asset_type.currentText().strip()
        if asset_type and "asset_type" in df_pl.columns:
            df_pl = df_pl.filter(pl.col("asset_type") == asset_type)

        call_put = self._combo_call_put.currentText().strip()
        if call_put and "optie_call_put" in df_pl.columns:
            df_pl = df_pl.filter(pl.col("optie_call_put") == call_put)

        strike_txt = self._edit_strike.text().strip()
        if strike_txt and "optie_strike" in df_pl.columns:
            try:
                strike_val = float(strike_txt.replace(",", "."))
                df_pl = df_pl.filter(
                    pl.col("optie_strike").cast(pl.Float64, strict=False) == strike_val
                )
            except ValueError:
                pass

        expire_txt = self._edit_expire.text().strip()
        if expire_txt and "optie_exp_date" in df_pl.columns:
            df_pl = df_pl.filter(
                pl.col("optie_exp_date")
                .dt.strftime("%d-%m-%y")
                .str.contains(expire_txt)
            )

        df_pl = df_pl.sort("Id", descending=True)
        df = df_pl.to_pandas()

        self._lbl_count.setText(f"Aantal Records: {len(df)}")
        self._fill_table(df)

    def _fill_table(self, df: pd.DataFrame):
        # Sortering tijdelijk uitzetten tijdens vullen (anders enorme overhead)
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)
        self._table.setRowCount(len(df))

        for row_idx, row in enumerate(df.itertuples(index=False)):
            row_dict = row._asdict()
            for col_idx, (col_key, _) in enumerate(DISPLAY_COLS):
                val = row_dict.get(col_key)
                text = _fmt(val, col_key)
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                if col_idx in _RIGHT_ALIGN_COLS:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                # Sla numerieke sorteerwaarde op zodat sortering correct werkt
                if col_idx == 0:  # Id
                    try:
                        item.setData(Qt.UserRole, int(val))
                    except Exception:
                        pass
                self._table.setItem(row_idx, col_idx, item)

            # Checkbox kolom
            try:
                rec_id = int(row_dict.get("Id", -1))
            except (TypeError, ValueError):
                rec_id = -1
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk.setCheckState(Qt.Checked if rec_id in self._checked_ids else Qt.Unchecked)
            chk.setData(Qt.UserRole, rec_id)
            self._table.setItem(row_idx, CHECK_COL, chk)

        # Sortering weer aanzetten — behoudt huidige sorteerindicator
        self._table.setSortingEnabled(True)

        # Pas opgeslagen breedtes toe als er nog geen zijn (eerste keer)
        hdr = self._table.horizontalHeader()
        if not get_settings().get_laatste_transacties_col_widths():
            self._table.resizeColumnsToContents()
            hdr.resizeSection(CHECK_COL, 30)
        hdr.setSectionResizeMode(CHECK_COL, QHeaderView.Fixed)

        if len(df) > 0:
            self._table.selectRow(0)
            self._table.setFocus()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get_checked_ids(self) -> list[int]:
        """Geeft de Id's terug van alle aangevinkte rijen."""
        checked = []
        for row in range(self._table.rowCount()):
            item = self._table.item(row, CHECK_COL)
            if item and item.checkState() == Qt.Checked:
                rec_id = item.data(Qt.UserRole)
                if rec_id and rec_id > 0:
                    checked.append(rec_id)
        return checked
