import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from app_window import VolSurfWindow


def main() -> None:
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = VolSurfWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
