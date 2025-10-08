
import pandas as pd
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTableView, QHeaderView, QHBoxLayout, QGroupBox
from PySide6.QtCore import QTimer, Qt, Slot
from portefeuille_viewer.data.repository import get_connection, load_assetrollup_to_ib
from portefeuille_viewer.ui.models import PandasTableModel

class OpenOptionsTab(QWidget):
    def __init__(self, pricefeed, parent=None):
        super().__init__(parent)
        self.feed_service = pricefeed

        self.model_call = PandasTableModel(pd.DataFrame(), self)
        self.model_put = PandasTableModel(pd.DataFrame(), self)

        self.table_call = QTableView()
        self.table_call.setModel(self.model_call)
        self._setup_table(self.table_call)

        self.table_put = QTableView()
        self.table_put.setModel(self.model_put)
        self._setup_table(self.table_put)

        self.label = QLabel("Open opties: 0 calls, 0 puts")

        layout = QVBoxLayout(self)

        box_layout = QHBoxLayout()
        group_call = QGroupBox("CALL opties")
        group_put = QGroupBox("PUT opties")
        group_call.setLayout(QVBoxLayout())
        group_put.setLayout(QVBoxLayout())
        group_call.layout().addWidget(self.table_call)
        group_put.layout().addWidget(self.table_put)

        box_layout.addWidget(group_call)
        box_layout.addWidget(group_put)

        layout.addLayout(box_layout)
        layout.addWidget(self.label)

        self._refresh_data()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_data)
        self._timer.start(5000)

    def _setup_table(self, table):
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableView.SelectRows)
        table.setSelectionMode(QTableView.SingleSelection)
        table.setSortingEnabled(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

    @Slot()
    def _refresh_data(self):
        try:
            df = self._load_options_data()
            df_call = df[df["optie_call_put"] == "call"].copy()
            df_put = df[df["optie_call_put"] == "put"].copy()
            self.model_call.set_df(df_call)
            self.model_put.set_df(df_put)
            self.label.setText(f"Open opties: {len(df_call)} calls, {len(df_put)} puts")
        except Exception as e:
            self.label.setText(f"Fout bij laden: {e}")

    def _load_options_data(self):
        with get_connection() as conn:
            df = pd.read_sql("""
                SELECT broker, asset_rollup, optie_call_put, optie_strike, optie_exp_date,
                       SomVantransactie_aantal AS aantal,
                       SomVantransactie_euro_totaal AS premie,
                       SomVantransactie_fee AS fee
                FROM Opties_open_series_opgerold_op_uniek_id
                ORDER BY broker, asset_rollup, optie_call_put, optie_strike
            """, conn)

        df["asset_rollup"] = df["asset_rollup"].astype(str).str.strip()
        mapping = load_assetrollup_to_ib()
        df = df.merge(mapping, on="asset_rollup", how="left")

        df["laatste_koers"] = df.apply(
            lambda r: self.feed_service.get(r["ib_symbol"], r["ib_currency"]), axis=1
        )

        def calc_result(row):
            try:
                ul = float(row["laatste_koers"])
                strike = float(row["optie_strike"])
                aantal = float(row["aantal"])
                if row["optie_call_put"] == "call":
                    return max(ul - strike, 0) * aantal
                elif row["optie_call_put"] == "put":
                    return max(strike - ul, 0) * aantal
                return 0.0
            except:
                return 0.0

        df["resultaat"] = df.apply(calc_result, axis=1)
        df["totaal"] = df["resultaat"] + df["premie"]
        df["premie_per_optie"] = df["premie"] / df["aantal"]
        return df
