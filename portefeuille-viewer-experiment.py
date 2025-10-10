import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont

from portefeuille_viewer.ui.main_window import MainWindow
from portefeuille_viewer.config import IB_HOST, IB_PORT, IB_CLIENT_ID
from portefeuille_viewer.data import repository
import time 
import sys
import pandas as pd
from PySide6.QtWidgets import QApplication, QTableView
from portefeuille_viewer.ui.models import PandasTableModel
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE 
import sys, os

start_time = time.time()


# # --- Forceer Python om deze map als eerste te gebruiken ---
# # Hierdoor wordt altijd de versie in portefeuille_viewer_experiment geladen
# sys.path.insert(0, os.path.dirname(__file__))

# from portefeuille_viewer.data import repository

# # Controleer welke repository daadwerkelijk geladen wordt:
# print("✅ Repository geladen uit:", repository.__file__)




def test_load_datasets():
    start_time = time.time()
    
    df = repository.load_alle_transacties()
    SNAPSHOT_STORE.alle_transacties = df 
    alle_transaties_time = time.time()
    # print(" alle transacties:")
    # print(df.shape)
    # print(df.columns)
    # print(df.head())

    df = repository.load_aandelen_from_tx()
    SNAPSHOT_STORE.aandelen = df 
    aandelen_time = time.time()

    df = repository.load_open_opties_from_tx()
    SNAPSHOT_STORE.load_open_opties_from_tx = df
    opties_open_time = time.time()

    df = repository.load_gesloten_opties_from_tx()
    SNAPSHOT_STORE.gesloten_opties = df
    optie_gesloten_time = time.time()

    df = repository.load_asset_rollup_data()
    # print(" asset_rollup_data:")
    # print(df.shape)
    # print(df.columns)
    # print(df.head())

    end_time = time.time()
    # print("Samenvatting van geladen datasets:")
    print(SNAPSHOT_STORE.summary())

    elapsed_time = end_time - start_time
    print(f"Time taken to load open transacties: {alle_transaties_time - start_time}) seconds")
    print(f"Time taken to load open aandelen: {aandelen_time - alle_transaties_time}) seconds")
    print(f"Time taken to load open opties: {opties_open_time - aandelen_time}) seconds")
    print(f"Time taken to load gesloten opties: {optie_gesloten_time - opties_open_time}) seconds")
    # print(f"Time taken to load open sprinters: {sprinters_time - optie_gesloten_time}) seconds")
    # print(f"Time taken to load gesloten sprinters: {gesloten_sprinters_time - sprinters_time}) seconds")    
    # print(f"Time taken to load alle transacties: {alle_transaties - gesloten_sprinters_time}) seconds")     
    print(f"Time taken to load all data: {elapsed_time:.2f} seconds")


def main():
    app = QApplication(sys.argv)
    # Globale app-font
    font = QFont()
    font.setPointSize(9)
    # PySide6 compat: nieuwe enum (Weight) óf oudere attribuut (DemiBold)
    try:
        font.setWeight(QFont.Weight.DemiBold)
    except AttributeError:
        font.setWeight(QFont.DemiBold)
    app.setFont(font)

    w = MainWindow()
    w.show()
    test_load_datasets()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
    








