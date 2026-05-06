from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from iv_surface_window import IvSurfaceWindow


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = IvSurfaceWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
