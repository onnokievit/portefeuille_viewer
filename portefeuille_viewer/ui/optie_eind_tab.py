from PySide6.QtWidgets import QWidget, QVBoxLayout, QTableView, QPushButton, QMessageBox, QHBoxLayout, QLabel, QDateEdit
from PySide6.QtCore import QDate
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.ui.models import PandasTableModel
from portefeuille_viewer.ui.filter_popup import ColumnFilterPopup

import polars as pl
import pandas as pd

class OptieEindTab(QWidget):

    def __init__(self, broker=None, asset=None):
        super().__init__()
        self.asset = asset
        self.setWindowTitle("Optie Eind")
        self.layout = QVBoxLayout(self)

        # Selectievelden voor datum en broker
        
        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel("Optie Eind Datum:"))
        self.eind_select_edit = QDateEdit()
        self.eind_select_edit.setDate(QDate(2025, 11, 7))
        self.eind_select_edit.setCalendarPopup(True)
        top_layout.addWidget(self.eind_select_edit)

        top_layout.addWidget(QLabel("Transactie Datum:"))
        self.transactie_datum_edit = QDateEdit()
        self.transactie_datum_edit.setDate(QDate(2025, 11, 8))
        self.transactie_datum_edit.setCalendarPopup(True)
        top_layout.addWidget(self.transactie_datum_edit)

        # Broker selectie knop
        self.broker_select_btn = QPushButton("Selecteer brokers")
        self.broker_select_btn.setFixedWidth(130)
        self.broker_select_btn.setStyleSheet("background-color: #e0f0ff; color: #1a3a5e; border-radius: 6px; padding: 3px 8px;")
        self.broker_select_btn.clicked.connect(self.open_broker_popup)
        top_layout.addWidget(self.broker_select_btn)
        self.selected_brokers = None  # None = alles tonen

        self.btn_fetch = QPushButton("Optie Eind ophalen")
        top_layout.addWidget(self.btn_fetch)

        self.btn_add = QPushButton("Records toevoegen aan transactiedatabase")
        top_layout.addWidget(self.btn_add)

        top_layout.addStretch()
        self.layout.addLayout(top_layout)

        self.table = QTableView()
        self.layout.addWidget(self.table)

        self.btn_fetch.clicked.connect(self.on_fetch_clicked)
        self.btn_add.clicked.connect(self.add_records_to_db)

        # Tabel pas vullen na klikken
        self.model = None

    def open_broker_popup(self):
        # Verzamel unieke brokers uit beide snapshots
        opties = SNAPSHOT_STORE.aggregator_snapshot_load_open_opties_from_tx_live
        sprinters = SNAPSHOT_STORE.aggregator_snapshot_open_sprinters_live
        brokers = set(opties["broker"].unique().to_list() + sprinters["broker"].unique().to_list())
        popup = ColumnFilterPopup("Selecteer brokers", sorted(brokers), pre_selected=self.selected_brokers or set(), parent=self)
        popup.acceptedSelection.connect(self.set_selected_brokers)
        popup.cleared.connect(self.clear_brokers)
        popup.exec()

    def set_selected_brokers(self, brokers):
        self.selected_brokers = set(brokers)
        self.reload_table()

    def clear_brokers(self):
        self.selected_brokers = None
        self.reload_table()

    def reload_table(self):
        self.load_data()

    def load_data(self):
        # Haal geselecteerde datums op
        eind_select = self.eind_select_edit.date().toPython()
        transactie_datum = self.transactie_datum_edit.date().toPython()
        # Opties
        opties = SNAPSHOT_STORE.aggregator_snapshot_load_open_opties_from_tx_live
        df_opties = opties.filter(
            (pl.col("optie_exp_date") <= eind_select)
        )
        if self.selected_brokers is not None:
            df_opties = df_opties.filter(pl.col("broker").is_in(list(self.selected_brokers)))
        if self.asset:
            df_opties = df_opties.filter(pl.col("asset_rollup") == self.asset)


        # Voeg asset_detail toe aan opties, altijd leeg
        if "asset_detail" not in df_opties.columns:
            df_opties = df_opties.with_columns([
                pl.lit("").alias("asset_detail")
            ])
        df_opties = df_opties.select([
            "broker",
            "asset_rollup",
            "asset_detail",
            "Koers",
            "optie_exp_date",
            "optie_strike",
            "optie_call_put",
            "SomVantransactie_aantal"
        ])

        # Sprinters: selecteer direct uit de originele bron zodat koers altijd klopt
        sprinters = SNAPSHOT_STORE.aggregator_snapshot_open_sprinters_live
        df_sprinters = sprinters.filter(
            (pl.col("optie_exp_date") <= eind_select)
        )
        if self.selected_brokers is not None:
            df_sprinters = df_sprinters.filter(pl.col("broker").is_in(list(self.selected_brokers)))
        if self.asset:
            df_sprinters = df_sprinters.filter(pl.col("asset_rollup") == self.asset)

        # kolommen selecteren
        df_sprinters = df_sprinters.select([
            "broker",
            "asset_rollup",
            "asset_detail",
            "Koers",
            "optie_exp_date",
            "optie_strike",
            "optie_call_put",
            "SomVantransactie_aantal"
        ])
        # Voeg transactie_datum en asset_type toe
        df_opties = df_opties.with_columns([
            pl.lit(transactie_datum).alias("transactie_datum"),
            pl.lit("optie").alias("asset_type")
        ])
        df_sprinters = df_sprinters.with_columns([
            pl.lit(transactie_datum).alias("transactie_datum"),
            pl.lit("sprinter").alias("asset_type")
        ])
        # Zorg dat beide DataFrames exact dezelfde kolommen hebben
        kolommen_union = set(df_opties.columns) | set(df_sprinters.columns)
        # Vul ontbrekende kolommen met het juiste type
        def get_dtype(df, col):
            return df.schema[col] if col in df.columns else None

        for col in kolommen_union:
            # Opties
            if col not in df_opties.columns:
                dtype = get_dtype(df_sprinters, col)
                if dtype is None:
                    dtype = pl.Utf8
                df_opties = df_opties.with_columns([pl.lit(None).cast(dtype).alias(col)])
            # Sprinters
            if col not in df_sprinters.columns:
                dtype = get_dtype(df_opties, col)
                if dtype is None:
                    dtype = pl.Utf8
                df_sprinters = df_sprinters.with_columns([pl.lit(None).cast(dtype).alias(col)])
        # Herordenen
        df_opties = df_opties.select(sorted(kolommen_union))
        df_sprinters = df_sprinters.select(sorted(kolommen_union))
        # Combineer
        df_total = pl.concat([df_opties, df_sprinters], how="vertical")
        pdf = df_total.to_pandas()
        # Voeg transactie_type toe
        def transactie_type(row):
            aantal = row.get("SomVantransactie_aantal", 0)
            try:
                aantal = float(aantal)
            except Exception:
                aantal = 0
            return "koop" if aantal < 0 else "verkoop"

        pdf["transactie_type"] = pdf.apply(transactie_type, axis=1)

        # Herbereken SomVantransactie_aantal: altijd positief
        def abs_aantal(row):
            aantal = row.get("SomVantransactie_aantal", 0)
            try:
                return abs(float(aantal))
            except Exception:
                return 0

        pdf["SomVantransactie_aantal"] = pdf.apply(abs_aantal, axis=1)

        # Voeg transactie_prijs toe (altijd 0)
        pdf["transactie_prijs"] = 0

        # Voeg itm_otm toe
        def itm_otm(row):
            if row.get("optie_call_put") == "call":
                return "ITM" if row.get("Koers", 0) > row.get("optie_strike", 0) else "OTM"
            elif row.get("optie_call_put") == "put":
                return "ITM" if row.get("Koers", 0) < row.get("optie_strike", 0) else "OTM"
            return "?"

        pdf["itm_otm"] = pdf.apply(itm_otm, axis=1)

        # Voeg transactie_oorsprong toe
        def transactie_oorsprong(row):
            val = row.get("itm_otm", "?")
            if val == "ITM":
                return "ASSIGN"
            elif val == "OTM":
                return "EXPIRE"
            return "?"

        pdf["transactie_oorsprong"] = pdf.apply(transactie_oorsprong, axis=1)



        # Zet kolomvolgorde
        output_cols = [
            "transactie_datum",
            "broker",
            "asset_rollup",
            "asset_detail",
            "asset_type",
            "transactie_type",
            "SomVantransactie_aantal",
            "transactie_prijs",
            "optie_exp_date",
            "optie_strike",
            "optie_call_put",
            "Koers",
            "itm_otm",
            "transactie_oorsprong"
        ]

        # Voeg order_id en order_id_number toe
        pdf = pdf.reindex(columns=output_cols)
        pdf = pdf.copy()
        pdf["order_id"] = range(1, len(pdf) + 1)
        pdf["order_id_number"] = 1
        # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken
        # from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
        SNAPSHOT_STORE.test_repository_load_input_test_data = pl.DataFrame(pdf)  # of df_sum als je de gesumde versie wilt zien
        # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken

        pdf_aandelen = self.maak_aandelen_records(pdf, transactie_datum)
        # # # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken
        # # from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
        SNAPSHOT_STORE.test_repository_load_output_test_data = pl.DataFrame(pdf_aandelen)  # of df_sum als je de gesumde versie wilt zien
        # # # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken

        # Zet naar alleen datum en dan naar datetime64[ms] zodat Polars kan samenvoegen
        for col in ["transactie_datum", "optie_exp_date"]:
            pdf[col] = pd.to_datetime(pdf[col]).dt.date
            pdf_aandelen[col] = pd.to_datetime(pdf_aandelen[col]).dt.date
            pdf[col] = pd.to_datetime(pdf[col]).astype("datetime64[ms]")
            pdf_aandelen[col] = pd.to_datetime(pdf_aandelen[col]).astype("datetime64[ms]")

        pl_pdf = pl.DataFrame(pdf)
        pl_pdf_aandelen = pl.DataFrame(pdf_aandelen)
        pl_merged = pl.concat([pl_pdf, pl_pdf_aandelen])


        self.model = PandasTableModel(pl_merged.to_pandas())
        self.table.setModel(self.model)

    def on_fetch_clicked(self):
        self.load_data()

    def add_records_to_db(self):
        # Placeholder: hier records toevoegen aan transactiedatabase
        QMessageBox.information(self, "Toevoegen", "Records zijn toegevoegd aan transactiedatabase (dummy)")

    def maak_aandelen_records(self, pdf, transactie_datum):
        

        nieuwe_records = []
        kolommen = list(pdf.columns)
        # Voeg order_id en order_id_number toe aan kolommen als ze nog niet bestaan
        if "order_id" not in kolommen:
            kolommen.append("order_id")
        if "order_id_number" not in kolommen:
            kolommen.append("order_id_number")
        for idx, row in pdf.iterrows():
            if row.get("transactie_oorsprong") == "ASSIGN":
                nieuw = {col: None for col in kolommen}
                nieuw["transactie_datum"] = transactie_datum
                nieuw["broker"] = row.get("broker")
                nieuw["asset_rollup"] = row.get("asset_rollup")
                nieuw["asset_detail"] = row.get("asset_detail")
                nieuw["asset_type"] = "aandeel"
                nieuw["optie_exp_date"] = row.get("optie_exp_date")
                nieuw["optie_strike"] = row.get("optie_strike")
                nieuw["optie_call_put"] = row.get("optie_call_put")
                nieuw["Koers"] = row.get("Koers")
                nieuw["SomVantransactie_aantal"] = row.get("SomVantransactie_aantal")
                # Bepaal transactie_type
                if row.get("optie_call_put") == "call":
                    if row.get("transactie_type") == "verkoop":
                        nieuw["transactie_type"] = "koop"
                    elif row.get("transactie_type") == "koop":
                        nieuw["transactie_type"] = "verkoop"
                elif row.get("optie_call_put") == "put":
                    nieuw["transactie_type"] = row.get("transactie_type")
                else:
                    nieuw["transactie_type"] = row.get("transactie_type")
                nieuw["transactie_prijs"] = 0
                nieuw["itm_otm"] = row.get("itm_otm")
                nieuw["transactie_oorsprong"] = "ASSIGN"
                nieuw["transactie_oorsprong_detail"] = None
                nieuw["order_id"] = row.get("order_id")
                nieuw["order_id_number"] = 2
                nieuwe_records.append(nieuw)

        if nieuwe_records:
            df_aandelen = pd.DataFrame(nieuwe_records, columns=kolommen)
            # Zorg dat dtypes overeenkomen met pdf
            for col in ["transactie_datum", "optie_exp_date"]:
                if col in df_aandelen.columns and col in pdf.columns:
                    # Gebruik dtype van pdf
                    dtype_pdf = pdf[col].dtype
                    if pd.api.types.is_datetime64_any_dtype(dtype_pdf):
                        df_aandelen[col] = pd.to_datetime(df_aandelen[col])
                    else:
                        df_aandelen[col] = df_aandelen[col].astype(dtype_pdf)
            print("Aandelenrecords gegenereerd:")
            print(df_aandelen)
            return df_aandelen
        else:
            print("Geen aandelenrecords gegenereerd.")
            return pd.DataFrame(columns=kolommen)
