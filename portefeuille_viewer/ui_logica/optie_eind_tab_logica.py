from PySide6.QtWidgets import QWidget, QMessageBox
from PySide6.QtCore import QDate, Qt, QSortFilterProxyModel
from PySide6.QtGui import QColor

from portefeuille_viewer.ui.optie_eind_ui import Ui_OptieEindTab
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.ui.models import PandasTableModel
from portefeuille_viewer.ui.filter_popup import ColumnFilterPopup
from portefeuille_viewer.signals import signals
from portefeuille_viewer.data.repository import load_last_prices_dict
from portefeuille_viewer.data.repository import build_uniek_id
from portefeuille_viewer.data.repository import fetch_open_optie_comments
import polars as pl
import pandas as pd
import numpy as np
import datetime


class OptieEindTableModel(PandasTableModel):
    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or self._df is None:
            return None
        col_name = self._df.columns[index.column()]
        val = self._df.iat[index.row(), index.column()]

        if role == Qt.UserRole:
            if col_name == "include":
                return 1 if bool(val) else 0
            if col_name in ("optie_exp_date", "datum"):
                try:
                    ts = pd.to_datetime(val, errors="coerce")
                    return None if pd.isna(ts) else ts.to_pydatetime()
                except Exception:
                    return None
            if pd.isna(val):
                return None
            return val

        if col_name == "include":
            if role == Qt.CheckStateRole:
                return Qt.Checked if bool(val) else Qt.Unchecked
            if role == Qt.DisplayRole:
                return ""

        if col_name == "optie_comment":
            if role == Qt.BackgroundRole and "optie_comment_color" in self._df.columns:
                try:
                    color_val = self._df.at[index.row(), "optie_comment_color"]
                    if isinstance(color_val, str) and color_val:
                        return QColor(color_val)
                except Exception:
                    pass
            if role == Qt.ForegroundRole and "optie_comment_textcolor" in self._df.columns:
                try:
                    text_color_val = self._df.at[index.row(), "optie_comment_textcolor"]
                    if isinstance(text_color_val, str) and text_color_val:
                        return QColor(text_color_val)
                except Exception:
                    pass
        return super().data(index, role)

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemIsEnabled
        col_name = self._df.columns[index.column()]
        if col_name == "include":
            return Qt.ItemIsEnabled | Qt.ItemIsSelectable
        return super().flags(index)

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid() or self._df is None:
            return False
        col_name = self._df.columns[index.column()]
        if col_name == "include" and role in (Qt.EditRole, Qt.CheckStateRole):
            if role == Qt.CheckStateRole:
                new_value = (value == Qt.Checked)
            else:
                new_value = bool(value)
            self._df.iat[index.row(), index.column()] = new_value
            self.dataChanged.emit(index, index, [Qt.CheckStateRole, Qt.DisplayRole])
            return True
        return super().setData(index, value, role)


class OptieEindSortProxy(QSortFilterProxyModel):
    def lessThan(self, left, right):
        try:
            col = left.column()
            col_name = self.sourceModel()._df.columns[col]
            if col_name in ("optie_exp_date", "datum"):
                lv = self.sourceModel().data(left, Qt.UserRole)
                rv = self.sourceModel().data(right, Qt.UserRole)
                if lv is None and rv is None:
                    return False
                if lv is None:
                    return True
                if rv is None:
                    return False
                return lv < rv
        except Exception:
            pass
        return super().lessThan(left, right)

# This class defines a widget in a Python application that includes functionality for fetching data,
# adding records to a database, clearing test accounts, and moving records to production, with default
# date settings for upcoming Fridays and Saturdays.
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
        self.tblOptieEind.pressed.connect(self._on_table_clicked)
        if hasattr(self, "pushButtonInclude"):
            self.pushButtonInclude.clicked.connect(self.toggle_include_all_none)
        # Zet standaarddatums

        def next_friday(date=None):
            if date is None:
                date = datetime.date.today()
            days_ahead = (4 - date.weekday() + 7) % 7  # 4 = vrijdag
            #days_ahead = days_ahead if days_ahead != 0 else 7
            return date + datetime.timedelta(days=days_ahead)
        # def next_friday(date=None):
        #     if date is None:
        #         date = datetime.date.today()
        #     days_ahead = (4 - date.weekday() + 7) % 7  # 4 = vrijdag
        #     return date if days_ahead == 0 else date + datetime.timedelta(days=days_ahead)
        
        volgende_vrijdag = next_friday()
        self.dateOptieStart.setDate(QDate(volgende_vrijdag.year, volgende_vrijdag.month, volgende_vrijdag.day))
        self.dateOptieEind.setDate(QDate(volgende_vrijdag.year, volgende_vrijdag.month, volgende_vrijdag.day))

        def next_saturday(date=None):
            if date is None:
                date = datetime.date.today()
            days_ahead = (5 - date.weekday() + 7) % 7  # 5 = zaterdag
            #days_ahead = days_ahead if days_ahead != 0 else 7
            return date + datetime.timedelta(days=days_ahead)

        volgende_zaterdag = next_saturday()
        self.dateTransactie.setDate(QDate(volgende_zaterdag.year, volgende_zaterdag.month, volgende_zaterdag.day))

    @staticmethod
    def _state_classes_from_asset_types(asset_types) -> list[str]:
        mapping = {
            "aandeel": "aandelen",
            "optie": "opties",
            "sprinter": "sprinters",
            "future": "aandelen",
        }
        out = sorted(
            {
                mapping.get(str(t).strip().lower())
                for t in (asset_types or [])
                if t is not None and mapping.get(str(t).strip().lower())
            }
        )
        return out

    def _emit_state_rebuild(self, asset_rollups, from_date, asset_types, reason: str) -> None:
        assets = sorted({str(a).strip() for a in (asset_rollups or []) if a is not None and str(a).strip()})
        if not assets:
            return
        classes = self._state_classes_from_asset_types(asset_types)
        if not classes:
            classes = ["aandelen", "opties", "sprinters"]
        dt_val = pd.to_datetime(from_date, errors="coerce")
        if pd.isna(dt_val):
            return
        payload = {
            "asset_classes": classes,
            "affected_assets": assets,
            "from_date": dt_val.date().isoformat(),
            "reason": reason,
            "mode": "asset_incremental",
        }
        print(f"[optie-eind] stateRebuildRequested payload: {payload}")
        signals.queued_emit_stateRebuildRequested(payload)

    def _collect_test_account_scope(self):
        from portefeuille_viewer.data.repository import conn_str
        import pyodbc
        with pyodbc.connect(conn_str) as conn:
            cur = conn.cursor()
            rows = cur.execute(
                """
                SELECT asset_rollup, asset_type, MIN(datum) AS min_datum
                FROM transacties_bron_data_test_accounts
                GROUP BY asset_rollup, asset_type
                """
            ).fetchall()
        if not rows:
            return [], None, []
        assets = sorted({str(r[0]).strip() for r in rows if r[0] is not None and str(r[0]).strip()})
        types = sorted({str(r[1]).strip().lower() for r in rows if r[1] is not None and str(r[1]).strip()})
        min_dates = []
        for r in rows:
            d = r[2]
            if d is None:
                continue
            d = pd.to_datetime(d, errors="coerce")
            if pd.notna(d):
                min_dates.append(d.date())
        min_date = min(min_dates) if min_dates else None
        return assets, min_date, types
        
    def move_records_to_productie(self):
        QMessageBox.information(self, "Move to productie", "Deze functionaliteit is nog niet geïmplementeerd.")

    def clear_test_account(self):
        from portefeuille_viewer.data.repository import conn_str
        import pyodbc
        assets, min_date, types = self._collect_test_account_scope()
        with pyodbc.connect(conn_str) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM transacties_bron_data_test_accounts")
            conn.commit()
        QMessageBox.information(self, "Test account", "Alle records zijn verwijderd uit transacties_bron_data_test_accounts.")
        signals.databaseChanged.emit(self.active_db_name)
        if assets and min_date is not None:
            self._emit_state_rebuild(
                asset_rollups=assets,
                from_date=min_date,
                asset_types=types,
                reason="optie_eind_clear_test_account",
            )
        self.reload_table()

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

        # comments worden later gekoppeld op dezelfde berekende uniek_id als in opties_open

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


        asset_map = SNAPSHOT_STORE.repository_snapshot_asset_rollup_data
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

        # Koppel comments via dezelfde uniek_id-opbouw als in opties_open_tab
        df_output = df_output.with_columns([
            pl.when(pl.col("asset_type") == "optie")
            .then(
                pl.struct([
                    "broker",
                    "asset_rollup",
                    "optie_exp_date",
                    "optie_call_put",
                    "optie_strike",
                ]).map_elements(lambda s: build_uniek_id({**s, "asset_type": "optie"}), return_dtype=pl.Utf8)
            )
            .otherwise(pl.lit(None))
            .alias("_comment_uniek_id"),
            pl.lit("").alias("optie_comment"),
            pl.lit("").alias("optie_comment_color"),
            pl.lit("").alias("optie_comment_textcolor"),
        ])

        try:
            comment_ids = (
                df_output
                .filter(pl.col("_comment_uniek_id").is_not_null())
                .select(pl.col("_comment_uniek_id").cast(pl.Utf8))
                .unique()
                .to_series()
                .to_list()
            )
            comment_ids = [x for x in comment_ids if x]
        except Exception:
            comment_ids = []

        if comment_ids:
            try:
                df_comments = fetch_open_optie_comments(comment_ids)
                if df_comments is not None and not df_comments.is_empty():
                    df_output = df_output.join(
                        df_comments.select([
                            pl.col("uniek_id").alias("_comment_uniek_id"),
                            "optie_comment",
                            "optie_comment_color",
                            "optie_comment_textcolor",
                        ]),
                        on="_comment_uniek_id",
                        how="left",
                        suffix="_comment_db",
                    )
                    if "optie_comment_comment_db" in df_output.columns:
                        exprs = [
                            pl.coalesce([pl.col("optie_comment_comment_db"), pl.col("optie_comment")])
                            .fill_null("")
                            .alias("optie_comment"),
                        ]
                        if "optie_comment_color_comment_db" in df_output.columns:
                            exprs.append(
                                pl.coalesce([pl.col("optie_comment_color_comment_db"), pl.col("optie_comment_color")])
                                .fill_null("")
                                .alias("optie_comment_color")
                            )
                        if "optie_comment_textcolor_comment_db" in df_output.columns:
                            exprs.append(
                                pl.coalesce([pl.col("optie_comment_textcolor_comment_db"), pl.col("optie_comment_textcolor")])
                                .fill_null("")
                                .alias("optie_comment_textcolor")
                            )
                        df_output = df_output.with_columns(exprs)
                        for c in ("optie_comment_comment_db", "optie_comment_color_comment_db", "optie_comment_textcolor_comment_db"):
                            if c in df_output.columns:
                                df_output = df_output.drop(c)
            except Exception:
                pass

        if "_comment_uniek_id" in df_output.columns:
            df_output = df_output.drop("_comment_uniek_id")

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
            "transactie_oorsprong", "order_id", "order_id_number", "optie_comment", "optie_comment_color", "optie_comment_textcolor"
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

        if "optie_exp_date" in df_concat.columns:
            df_concat = df_concat.with_columns(pl.col("optie_exp_date").cast(pl.Date))
        if "datum" in df_concat.columns:
            df_concat = df_concat.with_columns(pl.col("datum").cast(pl.Date))

        df_concat = df_concat.with_columns([pl.lit(True).alias("include")])
        cols = [c for c in df_concat.columns if c != "include"] + ["include"]
        df_concat = df_concat.select(cols)
        self.model = OptieEindTableModel(df_concat.to_pandas())
        self._table_proxy = OptieEindSortProxy(self)
        self._table_proxy.setSourceModel(self.model)
        self._table_proxy.setSortRole(Qt.UserRole)
        self.tblOptieEind.setModel(self._table_proxy)
        self.tblOptieEind.setSortingEnabled(True)
        try:
            include_idx = self.model._df.columns.get_loc("include")
            self.tblOptieEind.setColumnWidth(include_idx, 60)
        except Exception:
            pass
        for hide_col in ("optie_comment_color", "optie_comment_textcolor"):
            try:
                idx = self.model._df.columns.get_loc(hide_col)
                self.tblOptieEind.setColumnHidden(idx, True)
            except Exception:
                pass
        self._update_include_button_label()
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
        if "include" in df.columns:
            df = df[df["include"].fillna(True)]
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
        try:
            assets = sorted({str(x).strip() for x in df_db["asset_rollup"].dropna().tolist() if str(x).strip()})
            min_date = pd.to_datetime(df_db["datum"], errors="coerce").min()
            types = sorted({str(x).strip().lower() for x in df_db["asset_type"].dropna().tolist() if str(x).strip()})
            if assets and pd.notna(min_date):
                self._emit_state_rebuild(
                    asset_rollups=assets,
                    from_date=min_date,
                    asset_types=types,
                    reason="optie_eind_add_records",
                )
        except Exception as exc:
            print(f"[optie-eind] state rebuild payload opbouwen mislukt: {exc}")

    def _on_table_clicked(self, index):
        if not index.isValid() or not self.model or not hasattr(self.model, "_df"):
            return
        src_index = self._table_proxy.mapToSource(index) if hasattr(self, "_table_proxy") else index
        if not src_index.isValid():
            return
        df = self.model._df
        if df is None or df.empty or "include" not in df.columns:
            return
        try:
            col_name = df.columns[src_index.column()]
        except Exception:
            return
        if col_name != "include":
            return
        current = bool(df.iat[src_index.row(), src_index.column()])
        df.iat[src_index.row(), src_index.column()] = (not current)
        self.model.dataChanged.emit(src_index, src_index, [Qt.CheckStateRole, Qt.DisplayRole])
        self._update_include_button_label()

    def _get_include_state(self):
        if not self.model or not hasattr(self.model, "_df"):
            return None, None
        df = self.model._df
        if df is None or df.empty or "include" not in df.columns:
            return None, None
        series = df["include"].fillna(True)
        all_selected = bool(series.all())
        any_selected = bool(series.any())
        return all_selected, any_selected

    def _update_include_button_label(self):
        if not hasattr(self, "pushButtonInclude"):
            return
        all_selected, any_selected = self._get_include_state()
        if all_selected:
            self.pushButtonInclude.setText("Select none")
        elif any_selected:
            self.pushButtonInclude.setText("Select all")
        else:
            self.pushButtonInclude.setText("Select all")

    def toggle_include_all_none(self):
        if not self.model or not hasattr(self.model, "_df"):
            return
        df = self.model._df
        if df is None or df.empty or "include" not in df.columns:
            return
        all_selected, _any_selected = self._get_include_state()
        new_value = False if all_selected else True
        df["include"] = new_value
        if self.model.rowCount() and self.model.columnCount():
            col = df.columns.get_loc("include")
            tl = self.model.index(0, col)
            br = self.model.index(self.model.rowCount() - 1, col)
            self.model.dataChanged.emit(tl, br, [Qt.CheckStateRole, Qt.DisplayRole])
        self._update_include_button_label()

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
