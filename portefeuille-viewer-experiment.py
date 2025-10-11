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


# # --- Forceer Python om deze map als eerste te gebruiken ---
# # Hierdoor wordt altijd de versie in portefeuille_viewer_experiment geladen
# sys.path.insert(0, os.path.dirname(__file__))

# # Controleer welke repository daadwerkelijk geladen wordt:
# print("✅ Repository geladen uit:", repository.__file__)



def load_datasets():
    start_time = time.time()            
    repository.load_alle_transacties()
    repository.load_aandelen_from_tx()
    repository.load_open_opties_from_tx()
    repository.load_gesloten_opties_from_tx()
    repository.load_asset_rollup_data()
    end_time = time.time()
    elapsed_time = end_time - start_time
    print(f"Datasets geladen in {elapsed_time:.2f} seconden.")
    print(SNAPSHOT_STORE.snapshot_store_summary())


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
    load_datasets()
    w = MainWindow()
    w.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
    








