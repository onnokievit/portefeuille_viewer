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
start_time = time.time()

import sys, os

# # --- Forceer Python om deze map als eerste te gebruiken ---
# # Hierdoor wordt altijd de versie in portefeuille_viewer_experiment geladen
# sys.path.insert(0, os.path.dirname(__file__))

# from portefeuille_viewer.data import repository

# # Controleer welke repository daadwerkelijk geladen wordt:
# print("✅ Repository geladen uit:", repository.__file__)




def test_load_datasets():
    start_time = time.time()
    
    df = repository.load_alle_transacties()
    print(" alle transacties:")
    print(df.shape)
    print(df.columns)
    print(df.head())
    
    df = repository.load_aandelen_from_tx()
    print(" open aandelen:")
    print(df.shape)
    print(df.columns)
    print(df.head())
    aandelen_time = time.time()

    df = repository.load_open_opties_from_tx()
    print(" open opties:")
    print(df.shape)
    print(df.columns)
    print(df.head())
    opties_time = time.time()

    df = repository.load_gesloten_opties_from_tx()
    print(" gesloten opties:")
    print(df.shape)
    print(df.columns)
    print(df.head())
    optie_gesloten_time = time.time()
      
    
    
    # # print(df.shape)
    # # print(df.columns)
    # # print(df.head())

    
    # df = repository.load_open_sprinters()
    # # print(df.shape)
    # # print(df.columns)
    # # print(df.head())
    # sprinters_time = time.time()

    # df = repository.load_gesloten_sprinters()
    # # print(df.shape)
    # # print(df.columns)
    # # print(df.head())
    # gesloten_sprinters_time = time.time()
    
    
    
    alle_transaties = time.time()
    # print(df.shape)
    # print(df.columns)
    #print(df.head())


    end_time = time.time()
    elapsed_time = end_time - start_time

    # print(f"Time taken to load open aandelen: {aandelen_time - start_time}) seconds")
    # print(f"Time taken to load open opties: {opties_time - aandelen_time}) seconds")
    # print(f"Time taken to load gesloten opties: {optie_gesloten_time - opties_time}) seconds")
    # print(f"Time taken to load open sprinters: {sprinters_time - optie_gesloten_time}) seconds")
    # print(f"Time taken to load gesloten sprinters: {gesloten_sprinters_time - sprinters_time}) seconds")    
    # print(f"Time taken to load alle transacties: {alle_transaties - gesloten_sprinters_time}) seconds")     
    print(f"Time taken to load alle transacties: {alle_transaties - start_time}) seconds")
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
    








