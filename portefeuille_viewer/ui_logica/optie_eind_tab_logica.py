from PySide6.QtWidgets import QWidget, QMessageBox
from PySide6.QtCore import QDate

from portefeuille_viewer.ui.optie_eind_ui import Ui_OptieEindTab
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.ui.models import PandasTableModel
from portefeuille_viewer.ui.filter_popup import ColumnFilterPopup
from portefeuille_viewer.signals import signals
from portefeuille_viewer.data.repository import load_last_prices_dict
from portefeuille_viewer.data.repository import build_uniek_id
import polars as pl
import pandas as pd
import numpy as np
import datetime

class OptieEindTab(QWidget, Ui_OptieEindTab):
    def __init__(self, broker=None, asset=None, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.live_prices = SNAPSHOT_STORE.live_prices or {}
        self.last_prices = load_last_prices_dict()
        self.asset = asset
        self.active_db_name = "transacties_bron_data_test_accounts"
        self.selected_brokers = None
        self.model = None
        # Koppel knoppen en widgets (objectNames uit optie_eind_ui.py)
        self.btnOptieEindOphalen.clicked.connect(self.on_fetch_clicked)
        self.btnRecordsToevoegen.clicked.connect(self.add_records_to_db)
        self.btnTestAccountLeegmaken.clicked.connect(self.clear_test_account)
        self.btnMoveToProductie.clicked.connect(self.move_records_to_productie)
        self.btnSelecteerBrokers.clicked.connect(self.open_broker_popup)
        # Zet standaarddatums

        def next_friday(date=None):
            if date is None:
                date = datetime.date.today()
            days_ahead = (4 - date.weekday() + 7) % 7  # 4 = vrijdag
            days_ahead = days_ahead if days_ahead != 0 else 7
            return date + datetime.timedelta(days=days_ahead)

        volgende_vrijdag = next_friday()
        self.dateOptieStart.setDate(QDate(volgende_vrijdag.year, volgende_vrijdag.month, volgende_vrijdag.day))
        self.dateOptieEind.setDate(QDate(volgende_vrijdag.year, volgende_vrijdag.month, volgende_vrijdag.day))

        def next_saturday(date=None):
            if date is None:
                date = datetime.date.today()
            days_ahead = (5 - date.weekday() + 7) % 7  # 5 = zaterdag
            days_ahead = days_ahead if days_ahead != 0 else 7
            return date + datetime.timedelta(days=days_ahead)

        volgende_zaterdag = next_saturday()
        self.dateTransactie.setDate(QDate(volgende_zaterdag.year, volgende_zaterdag.month, volgende_zaterdag.day))
        
    def move_records_to_productie(self):
        QMessageBox.information(self, "Move to productie", "Deze functionaliteit is nog niet geïmplementeerd.")

    def clear_test_account(self):
        from portefeuille_viewer.data.repository import conn_str
        import pyodbc
        with pyodbc.connect(conn_str) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM transacties_bron_data_test_accounts")
            conn.commit()
        QMessageBox.information(self, "Test account", "Alle records zijn verwijderd uit transacties_bron_data_test_accounts.")
        signals.databaseChanged.emit(self.active_db_name)
        self.model = None

    def open_broker_popup(self):
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
        start_select = self.dateOptieStart.date().toPython()
        print("Start selectie datum:", start_select)
        eind_select = self.dateOptieEind.date().toPython()
        print("Eind selectie datum:", eind_select)
        transactie_datum = self.dateTransactie.date().toPython()
        transactie_optie_input = SNAPSHOT_STORE.repository_snapshot_alle_transacties

        df_transacties = transactie_optie_input.filter(
            (pl.col("optie_exp_date") >= start_select) & (pl.col("optie_exp_date") <= eind_select)
        )
        if self.selected_brokers is not None:
            df_transacties = df_transacties.filter(pl.col("broker").is_in(list(self.selected_brokers)))
        if self.asset:
            df_transacties = df_transacties.filter(pl.col("asset_rollup") == self.asset)

        df_grouped_optie = (
            df_transacties
            .filter(pl.col("asset_type").is_in(["optie"]))
            .group_by([
                "broker",
                "asset_rollup",
                "asset_type",
                "optie_exp_date",
                "optie_strike",
                "optie_call_put"
            ])
            .agg([
                pl.col("transactie_aantal").sum().alias("sum_transactie_aantal"),
                pl.col("transactie_euro_totaal").sum().alias("sum_transactie_euro_totaal"),
                pl.col("transactie_fee").sum().alias("sum_transactie_fee"),
            ])
            .filter(pl.col("sum_transactie_aantal") != 0))

        if "asset_detail" not in df_grouped_optie.columns:
            df_grouped_optie = df_grouped_optie.with_columns([pl.lit("").alias("asset_detail")])

        df_grouped_sprinter = (
            df_transacties
            .filter(pl.col("asset_type").is_in(["sprinter"]))
            .group_by([
                "broker",
                "asset_rollup",
                "asset_detail",
                "asset_type",
                "optie_exp_date",
                "optie_strike",
                "optie_call_put"
            ])
            .agg([
                pl.col("transactie_aantal").sum().alias("sum_transactie_aantal"),
                pl.col("transactie_euro_totaal").sum().alias("sum_transactie_euro_totaal"),
                pl.col("transactie_fee").sum().alias("sum_transactie_fee"),
            ])
            .filter(pl.col("sum_transactie_aantal") != 0))

        kolommen = ["broker", "asset_rollup", "asset_detail", "asset_type", "optie_exp_date", "optie_strike", "optie_call_put", "sum_transactie_aantal", "sum_transactie_euro_totaal", "sum_transactie_fee"]
        df_grouped_optie = df_grouped_optie.select(kolommen)
        df_grouped_sprinter = df_grouped_sprinter.select(kolommen)
        df_total = pl.concat([df_grouped_optie, df_grouped_sprinter], how="vertical")


        asset_map = SNAPSHOT_STORE.snapshot_asset_rollup_data
        if asset_map.is_empty():
            return pl.DataFrame()
        # Selecteer relevante velden uit asset_map
        asset_map = asset_map.select([
            "asset_rollup", "ib_symbol", "ib_currency"
        ])

        df = df_total.join(asset_map, on="asset_rollup", how="left")

        df = df.with_columns([
            pl.struct(["ib_symbol", "ib_currency"]).map_elements(
                lambda row: (
                    self.live_prices.get((row["ib_symbol"], row["ib_currency"])) if row["ib_symbol"] and row["ib_currency"] and self.live_prices and self.live_prices.get((row["ib_symbol"], row["ib_currency"])) not in (None, 0.0)
                    else self.last_prices.get((row["ib_symbol"], row["ib_currency"]), 0.0) if row["ib_symbol"] and row["ib_currency"] and self.last_prices else 0.0
                ),
                return_dtype=pl.Float64
            ).alias("Koers")
        ])


        df = df.with_columns([
            pl.lit("").alias("itm_otm"),
            pl.lit("").alias("transactie_oorsprong")
        ])

        df_output = df.with_columns(
            pl.when(
                (pl.col("optie_call_put") == "call")
                & (pl.col("Koers") < pl.col("optie_strike"))
            )
            .then(pl.lit("OTM"))
            .when(
                (pl.col("optie_call_put") == "call")
                & (pl.col("Koers") >= pl.col("optie_strike"))
            )
            .then(pl.lit("ITM"))
            .when(
                (pl.col("optie_call_put") == "put")
                & (pl.col("Koers") > pl.col("optie_strike"))
            )
            .then(pl.lit("OTM"))
            .when(
                (pl.col("optie_call_put") == "put")
                & (pl.col("Koers") <= pl.col("optie_strike"))
            )
            .then(pl.lit("ITM"))
            .otherwise(pl.lit("?"))
            .alias("itm_otm")
        )

        # 2. Voeg transactie_oorsprong toe
        df_output = df_output.with_columns([
            pl.when(pl.col("itm_otm") == "ITM").then(pl.lit("ASSIGN")).otherwise(pl.lit("EXPIRE")).alias("transactie_oorsprong")
        ])
        df_output = df_output.with_columns([
            pl.when(pl.col("sum_transactie_aantal") < 0).then(pl.lit("koop")).otherwise(pl.lit("verkoop")).alias("transactie_type")
        ])
        df_output = df_output.with_columns([
            pl.when(pl.col("sum_transactie_aantal") < 0) .then(-pl.col("sum_transactie_aantal")) .otherwise(pl.col("sum_transactie_aantal")) .alias("aantal")
        ])
        df_output = df_output.with_columns([pl.lit(0).alias("transactie_prijs")])
        df_output = df_output.with_columns([pl.lit(transactie_datum).alias("datum")])

        # Haal hoogste order_id op uit transacties
        repo_tx = SNAPSHOT_STORE.repository_snapshot_alle_transacties
        if repo_tx is not None and "order_id" in repo_tx.columns:
            try:
                max_order_id = repo_tx["order_id"].max()
                start_order_id = int(max_order_id) + 1 if pd.notnull(max_order_id) else 1
            except Exception:
                start_order_id = 1
        else:
            start_order_id = 1

        # Voeg order_id kolom toe aan df_output, oplopend vanaf start_order_id
        df_output = df_output.with_columns([
            pl.Series("order_id", list(range(start_order_id, start_order_id + df_output.height)))
        ])
        df_output = df_output.with_columns([pl.lit(1).alias("order_id_number")])        

        # aandelen recorden aanmaken voor toegewezen opties
        assign_df = df_output.filter(pl.col("transactie_oorsprong") == "ASSIGN")
        
        # # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken
        # from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE # sourcery skip
        SNAPSHOT_STORE.test_repository_load_output_test_dataframe = assign_df  # sourcery skip # of df_sum als je de gesumde versie wilt zien
        # # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken
        if assign_df.is_empty():
            print("DataFrame is leeg")
        else:
            
            print("DataFrame bevat rijen")


        # Functie om transactie_type te bepalen
        def bepaal_transactie_type(row):
            call_put = row["optie_call_put"]
            aantal = row["sum_transactie_aantal"]
            # Long = aantal > 0, Short = aantal < 0
            if call_put == "call":
                return "koop" if aantal > 0 else "verkoop"
            elif call_put == "put":
                return "verkoop" if aantal > 0 else "koop"
            return "?"

        # Maak aandelenrecords aan
        aandelen_records = []
        if not assign_df.is_empty():
            for row in assign_df.to_dicts():
                aandelen_records.append({
                    "datum": row["datum"],
                    "broker": row["broker"],
                    "asset_rollup": row["asset_rollup"],
                    "asset_type": "aandeel",
                    "aantal": abs(row["sum_transactie_aantal"]),
                    "transactie_prijs": row["optie_strike"],
                    "transactie_oorsprong": "ASSIGN",
                    "transactie_type": bepaal_transactie_type(row),
                    "order_id": row["order_id"],
                    # "order_id_number": 2,
                })

        # Zet om naar Polars DataFrame
        aandelen_df = pl.DataFrame(aandelen_records)
        aandelen_df = aandelen_df.with_columns([pl.lit(2).alias("order_id_number")])

        kolommen = [
            "datum","broker", "asset_rollup", "asset_detail", "asset_type", "transactie_type",  "aantal", "transactie_prijs",
            "optie_exp_date", "optie_strike", "optie_call_put",
            "transactie_oorsprong", "order_id", "order_id_number"
        ]
        # Voeg ontbrekende kolommen toe aan aandelen_df
        for col in kolommen:
            if col not in aandelen_df.columns:
                aandelen_df = aandelen_df.with_columns([pl.lit(None).alias(col)])

        # Voeg ontbrekende kolommen toe aan df_output
        for col in kolommen:
            if col not in df_output.columns:
                df_output = df_output.with_columns([pl.lit(None).alias(col)])
        # Selecteer en sorteer kolommen in beide DataFrames
        aandelen_df = aandelen_df.select(kolommen)
        df_output = df_output.select(kolommen)
        # Stel: 'aantal' en 'transactie_prijs' moeten Float64 zijn
        for col in ["aantal", "transactie_prijs"]:
            if col in aandelen_df.columns:
                aandelen_df = aandelen_df.with_columns([pl.col(col).cast(pl.Float64).alias(col)])
            if col in df_output.columns:
                df_output = df_output.with_columns([pl.col(col).cast(pl.Float64).alias(col)])

        # Nu kun je samenvoegen
        if not assign_df.is_empty():
            df_concat = pl.concat([df_output, aandelen_df], how="vertical")

            # Bouw uniek_id mapping     
            df_concat = df_concat.with_columns([
                pl.struct(df_concat.columns).map_elements(lambda row: build_uniek_id(row), return_dtype=pl.Utf8).alias("uniek_id")
            ])

            mapping = { (row["order_id"], row["order_id_number"]): row["uniek_id"] for row in df_concat.to_dicts() }

            def get_oorsprong_detail(row):
                oid = row["order_id"]
                oid_num = row["order_id_number"]
                other_num = 2 if oid_num == 1 else 1
                return mapping.get((oid, other_num))

            df_concat = df_concat.with_columns([
                pl.struct(df_concat.columns).map_elements(get_oorsprong_detail, return_dtype=pl.Utf8).alias("transactie_oorsprong_detail")
            ])
        else:
            df_concat = df_output.with_columns([pl.lit(None).alias("transactie_oorsprong_detail")])


        self.model = PandasTableModel(df_concat.to_pandas())
        self.tblOptieEind.setModel(self.model)
        # self.add_records_to_db()        
        


    def on_fetch_clicked(self):
        # self.load_data()
        self.load_data()

    def add_records_to_db(self):
        upload_cols = [
            "datum", "broker", "asset_rollup", "asset_detail", "asset_type", "transactie_type", "aantal", "transactie_prijs",
            "optie_exp_date", "optie_strike", "optie_call_put", "transactie_oorsprong", "order_id", "order_id_number",
            "transactie_oorsprong_detail"
        ]
        
        col_map = {
            "datum": "datum",
            "broker": "broker",
            "asset_rollup": "asset_rollup",
            "asset_detail": "asset_detail",
            "asset_type": "asset_type",
            "transactie_type": "transactie_type",
            "aantal": "aantal",
            "transactie_prijs": "transactie_prijs",
            "optie_exp_date": "optie_exp_date",
            "optie_strike": "optie_strike",
            "optie_call_put": "optie_call_put",
            "transactie_oorsprong": "transactie_oorsprong",
            "order_id": "order_id",
            "order_id_number": "order_id_number",
            "transactie_oorsprong_detail": "transactie_oorsprong_detail"
        }
        

        df = self.model._df if hasattr(self.model, '_df') else self.model._data
        df_db = df[list(col_map.keys())].rename(columns=col_map)
        df_db = self._convert_df_for_access(df_db)
        df_db = df_db[upload_cols]
        if "optie_call_put" in df_db.columns:
            df_db["optie_call_put"] = df_db["optie_call_put"].replace("", None)
        if "optie_exp_date" in df_db.columns:
            df_db["optie_exp_date"] = pd.to_datetime(df_db["optie_exp_date"], errors="coerce")
            df_db["optie_exp_date"] = df_db["optie_exp_date"].apply(lambda x: x.date() if pd.notnull(x) else None)
        
        df_db = df_db.dropna(how="all")  # verwijder volledig lege rijen
        df_db = df_db[~(df_db == '').all(axis=1)]  # verwijder rijen die alleen lege strings bevatten
        
        from portefeuille_viewer.data.repository import conn_str
        import pyodbc
        with pyodbc.connect(conn_str) as conn:
            cursor = conn.cursor()
            for _, row in df_db.iterrows():
                placeholders = ','.join(['?'] * len(df_db.columns))
                sql = f"INSERT INTO transacties_bron_data_test_accounts ({','.join(df_db.columns)}) VALUES ({placeholders})"
                cursor.execute(sql, tuple(row))
            conn.commit()
        QMessageBox.information(self, "Toevoegen", f"{len(df_db)} records toegevoegd aan transacties_bron_data_test_accounts.")
        signals.databaseChanged.emit(self.active_db_name)

    def _convert_df_for_access(self, df):
        date_cols = ["datum", "optie_exp_date"]
        num_cols = ["aantal", "transactie_prijs", "optie_strike", "order_id", "order_id_number"]
        text_cols = ["broker", "asset_rollup", "asset_type", "transactie_type", "optie_call_put", "transactie_oorsprong"]
        for col in date_cols:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
        for col in num_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(float)
        for col in text_cols:
            if col in df.columns:
                df[col] = df[col].fillna('').astype(str)
        return df

    def maak_aandelen_records(self, pdf, transactie_datum):
        nieuwe_records = []
        kolommen = list(pdf.columns)
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
                nieuw["optie_exp_date"] = pd.NaT
                nieuw["optie_strike"] = np.nan
                nieuw["optie_call_put"] = ""
                nieuw["Koers"] = row.get("Koers")
                nieuw["SomVantransactie_aantal"] = row.get("SomVantransactie_aantal")
                if row.get("optie_call_put") == "call":
                    if row.get("transactie_type") == "verkoop":
                        nieuw["transactie_type"] = "koop"
                    elif row.get("transactie_type") == "koop":
                        nieuw["transactie_type"] = "verkoop"
                elif row.get("optie_call_put") == "put":
                    nieuw["transactie_type"] = row.get("transactie_type")
                else:
                    nieuw["transactie_type"] = row.get("transactie_type")
                nieuw["transactie_prijs"] = row.get("optie_strike")
                nieuw["itm_otm"] = row.get("itm_otm")
                nieuw["transactie_oorsprong"] = "ASSIGN"
                nieuw["transactie_oorsprong_detail"] = None
                nieuw["order_id"] = row.get("order_id")
                nieuw["order_id_number"] = 2
                nieuwe_records.append(nieuw)
        if nieuwe_records:
            df_aandelen = pd.DataFrame(nieuwe_records, columns=kolommen)
            for col in ["transactie_datum", "optie_exp_date"]:
                if col in df_aandelen.columns and col in pdf.columns:
                    dtype_pdf = pdf[col].dtype
                    if pd.api.types.is_datetime64_any_dtype(dtype_pdf):
                        df_aandelen[col] = pd.to_datetime(df_aandelen[col])
                    else:
                        df_aandelen[col] = df_aandelen[col].astype(dtype_pdf)
            return df_aandelen
        else:
            print("Geen aandelenrecords gegenereerd.")
            return pd.DataFrame(columns=kolommen)
