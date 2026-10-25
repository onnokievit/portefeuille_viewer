"""Standalone Qt 6.9.3/Windows COM reproducer: no app, DB or WebEngine imports.

Run from repo root: python -m devtools.reproduce_qt_window_only
Shows one empty, non-activating window for four seconds, then exits normally.
"""
import faulthandler
import sys

from PySide6.QtCore import Qt, QTimer, qVersion
from PySide6.QtWidgets import QApplication, QWidget


def main():
    faulthandler.enable()
    app = QApplication([])
    window = QWidget()
    window.setWindowTitle('Leeg Qt-testvenster: sluit automatisch')
    window.setAttribute(Qt.WA_ShowWithoutActivating)
    window.setWindowFlag(Qt.WindowDoesNotAcceptFocus)
    window.resize(360, 120)
    window.show()
    QTimer.singleShot(4000, app.quit)
    print('Qt', qVersion(), 'eventloop start', flush=True)
    code = app.exec()
    print('Qt eventloop klaar; exitcode', code, flush=True)
    return code


if __name__ == '__main__':
    sys.exit(main())
