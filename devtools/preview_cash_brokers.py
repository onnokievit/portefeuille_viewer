"""Render the real Qt dashboard with synthetic data; never writes to a database."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtCore import QTimer, QSizeF
from PySide6.QtGui import QPageLayout, QPageSize
from devtools.test_cash_broker_selection import BrokerSelectionTests
from portefeuille_viewer.ui_logica import cash_management_web_tab as d
from portefeuille_viewer.services import year_result_vs_indices_service as indices

fixture = BrokerSelectionTests()
fixture.setUp()
settings = d.get_settings()
brokers = ['degiro', 'interactive', 'lynx', 'new']
rows = [{'id': i+1, 'datum': '2026-01-02', 'broker': b, 'ending_balance': v}
        for i, (b, v) in enumerate(zip(brokers, [110, 220, 330, 480]))]
with patch.object(d.broker_repository, 'load_brokers', return_value=brokers+['missing']), \
     patch.object(settings, 'get_cash_selected_brokers', return_value=brokers), \
     patch.object(d, 'list_account_daily_balances', return_value=rows), \
     patch.object(d, 'list_index_asset_rollups', return_value=[]), \
     patch.object(settings, 'get_cash_dashboard_start_date', return_value='2025-12-31'), \
     patch.object(d, 'build_year_result_vs_indices_payload', side_effect=lambda **kw: {
         'series': indices._build_portfolio_series(kw['portfolio_payload'], kw['selected_portfolio'])}):
    fake = SimpleNamespace(_chart_payload=d.CashManagementWebTab._chart_payload,
                           _visible_series_for_chart=d.CashManagementWebTab._visible_series_for_chart)
    payload = d.CashManagementWebTab._build_payload(fake)
for chart in payload['charts']:
    chart['visible_series'] = [s['id'] for s in chart['series']]
payload['panel_state'] = {'left_collapsed': True, 'right_collapsed': False}
assert payload['pivot']['rows'][0]['total'] == 1140
app = QApplication([])
errors = []

class Page(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            errors.append(message)

view = QWebEngineView()
view.setPage(Page(view))
view.resize(1500, 1000)
view.show()
output = Path('C:/python_coding/cash_broker_qa')
output.mkdir(exist_ok=True)

def verify():
    def done(result):
        print('UI:', result, 'JavaScript errors:', errors, flush=True)
        view.grab().save(str(output / 'cash_brokers.png'))
        result = json.loads(result)
        passed = not errors and result['brokers'] == 5 and 'new' in result['headers'] and result['charts'] == 5
        view.page().pdfPrintingFinished.connect(lambda path, ok: app.exit(0 if passed and ok else 1))
        layout = QPageLayout(QPageSize(QSizeF(400, 270), QPageSize.Unit.Millimeter), QPageLayout.Orientation.Portrait, __import__('PySide6.QtCore', fromlist=['QMarginsF']).QMarginsF(0,0,0,0))
        view.page().printToPdf(str(output / 'cash_brokers.pdf'), layout)
    view.page().runJavaScript("JSON.stringify({brokers:document.querySelectorAll('#brokerSelection input').length,headers:document.getElementById('pivotHead').innerText,charts:document.querySelectorAll('.plot').length})", done)

def loaded(ok):
    if not ok:
        app.exit(1)
        return
    view.page().runJavaScript('renderCashDashboard(' + json.dumps(payload, default=d._json_default) + ');document.querySelector("details").open=true;')
    QTimer.singleShot(1200, verify)

view.loadFinished.connect(loaded)
view.setHtml(d.CashManagementWebTab._html())
QTimer.singleShot(20000, lambda: app.exit(2))
code = app.exec()
fixture.doCleanups()
raise SystemExit(code)
