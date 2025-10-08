import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont

from portefeuille_viewer.ui.main_window import MainWindow
from portefeuille_viewer.config import IB_HOST, IB_PORT, IB_CLIENT_ID


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
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
