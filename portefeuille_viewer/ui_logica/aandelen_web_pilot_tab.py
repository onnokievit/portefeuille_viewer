from __future__ import annotations

import json

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

try:
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:  # pragma: no cover - optional runtime dependency
    QWebChannel = None
    QWebEngineView = None


class AandelenWebPilotTab(QWidget):
    """
    Minimal WebEngine pilot tab.

    - Uses a lightweight HTML frame/card layout.
    - Exposes a JS endpoint to apply tiny value updates.
    - Keeps existing PySide tabs untouched (feature-flag style integration).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        if QWebEngineView is None:
            layout.addWidget(QLabel("QtWebEngine niet beschikbaar in deze runtime."))
            return
        self.web = QWebEngineView(self)
        layout.addWidget(self.web)
        if QWebChannel is not None:
            self.channel = QWebChannel(self.web.page())
            self.web.page().setWebChannel(self.channel)
        self.web.setHtml(self._html_template())

    def push_value(self, frame_id: str, value_text: str) -> None:
        if not hasattr(self, "web"):
            return
        payload = json.dumps({"id": frame_id, "value": value_text})
        self.web.page().runJavaScript(f"window.applyDelta({payload});")

    def _html_template(self) -> str:
        return """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8"/>
    <style>
      body { font-family: Segoe UI, Arial, sans-serif; margin: 12px; background:#f5f6f8; }
      .grid { display:grid; grid-template-columns: repeat(4, minmax(140px, 1fr)); gap:10px; }
      .card { background:white; border:1px solid #d8dde6; border-radius:8px; padding:10px; }
      .label { color:#5b677a; font-size:12px; }
      .value { font-weight:700; font-size:22px; margin-top:4px; }
    </style>
  </head>
  <body>
    <div class="grid">
      <div class="card"><div class="label">Net Change</div><div class="value" id="net_change">-</div></div>
      <div class="card"><div class="label">Koers</div><div class="value" id="koers">-</div></div>
      <div class="card"><div class="label">Koers Prev</div><div class="value" id="koers_prev">-</div></div>
      <div class="card"><div class="label">Totaal Inc Fee</div><div class="value" id="totaal_inc_fee">-</div></div>
    </div>
    <script>
      window.applyDelta = function(delta) {
        if (!delta || !delta.id) return;
        const el = document.getElementById(delta.id);
        if (el) el.textContent = String(delta.value ?? "");
      };
    </script>
  </body>
</html>
"""

