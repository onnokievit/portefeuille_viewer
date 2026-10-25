"""Isolate Qt/WebEngine/Access first-chance exceptions, without production data.

Run from repository root: python -m devtools.reproduce_qt_com --surface hidden
Use --surface visible for small, non-activating windows which close automatically.
Each case runs in a fresh process; no debugger is attached and faulthandler stays on.
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import ctypes
import faulthandler
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
CASES = ('python', 'access', 'qt', 'qt-empty', 'qt-web', 'qt-access-ui', 'qt-access-thread',
         'qt-web-access-ui', 'qt-web-access-thread', 'qt-web-appworker')


def emit(stage, **values):
    print(json.dumps(dict(stage=stage, pid=os.getpid(), thread=threading.get_ident(),
                          at=datetime.now().astimezone().isoformat(), **values)), flush=True)


def apartment():
    """Query only, never initialise or change the COM apartment."""
    if os.name != 'nt':
        return None
    ole = ctypes.WinDLL('ole32')
    kind, qualifier = ctypes.c_int(-1), ctypes.c_int(-1)
    hr = ole.CoGetApartmentType(ctypes.byref(kind), ctypes.byref(qualifier))
    return dict(hresult=f'{hr & 0xffffffff:08X}', kind=kind.value, qualifier=qualifier.value)


def child(args):
    faulthandler.enable()
    session = args.session.resolve()
    metadata = json.loads((session/'synthetic_database.json').read_text(encoding='utf-8'))
    db = session/'synthetic_qt_com.accdb'
    if metadata.get('database') != str(db) or not metadata.get('synthetic_only'):
        raise RuntimeError('Only a generated synthetic fixture is allowed')
    emit('start', case=args.case, surface=args.surface, python=sys.version, apartment=apartment())
    read_count = 0
    failures = []
    web_results = []
    executor = None
    app_worker = None

    def raw_read():
        nonlocal read_count
        import pyodbc
        before = apartment()
        conn = pyodbc.connect(rf'DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db};READONLY=TRUE;')
        try:
            cursor = conn.cursor()
            row = cursor.execute('SELECT marker FROM pv_com_repro_guard WHERE id=1').fetchone()
            assert row and row[0] == metadata['marker']
            cursor.close()
            conn.rollback()
            read_count += 1
        finally:
            conn.close()
        emit('access_read', count=read_count, apartment_before=before, apartment_after=apartment())

    if args.case == 'python':
        emit('finished', reads=0)
        return 0
    if args.case == 'access':
        for _ in range(8):
            raw_read()
        emit('finished', reads=read_count)
        return 0

    from PySide6.QtCore import QTimer, Qt, qVersion
    from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QLineEdit
    import PySide6
    app = QApplication([])
    app.setApplicationName('PV-COM-Repro-'+args.case)
    native_filter = None
    if args.native_messages and os.name == 'nt' and args.surface != 'offscreen':
        from PySide6.QtCore import QAbstractNativeEventFilter
        from ctypes import wintypes
        class NativeFilter(QAbstractNativeEventFilter):
            def nativeEventFilter(self, event_type, message):
                if bytes(event_type) in {b'windows_generic_MSG', b'windows_dispatcher_MSG'}:
                    msg = wintypes.MSG.from_address(int(message))
                    names = {0x3d:'WM_GETOBJECT', 0x7:'WM_SETFOCUS', 0x6:'WM_ACTIVATE',
                             0x18:'WM_SHOWWINDOW', 0x281:'WM_IME_SETCONTEXT', 0x51:'WM_INPUTLANGCHANGE'}
                    if msg.message in names:
                        emit('native_message', name=names[msg.message],
                             message=msg.message, lparam=msg.lParam)
                return False, 0  # Observe only: never consume or alter a Windows message.
        native_filter = NativeFilter()
        app.installNativeEventFilter(native_filter)
    emit('qt_ready', pyside=PySide6.__version__, qt=qVersion(), apartment=apartment())
    window = QWidget()
    window.setWindowTitle('Portefeuille Viewer: geïsoleerde COM-test — '+args.case)
    window.setAttribute(Qt.WA_ShowWithoutActivating)
    window.setWindowFlag(Qt.WindowDoesNotAcceptFocus)
    window.resize(480, 200)
    label = None
    if args.case != 'qt-empty':
        layout = QVBoxLayout(window)
        label = QLabel('Alleen synthetische testgegevens; sluit automatisch.')
        layout.addWidget(label)
        edit = QLineEdit('Geen portfolio of netwerkverbinding')
        layout.addWidget(edit)
    web = profile = None
    if 'web' in args.case:
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
        profile = QWebEngineProfile(window)  # Off-the-record, no persistent user cache.
        web = QWebEngineView(window)
        web.setPage(QWebEnginePage(profile, web))
        web.loadFinished.connect(lambda ok: (web_results.append(bool(ok)), emit('web_loaded', ok=bool(ok))))
        web.setHtml('<!doctype html><html><body><h3>Lokale test</h3>'
                    '<input aria-label="Testinvoer" value="synthetisch">'
                    '<p id="status">Geen externe bronnen.</p></body></html>')
        layout.addWidget(web)

    if args.case.endswith('appworker'):
        from portefeuille_viewer.data.stockdata_worker import enable_stockdata_workers, stockdata_job
        from portefeuille_viewer.data.shared_database import connect_stockdata
        from portefeuille_viewer.data import stockdata_worker as app_worker
        enable_stockdata_workers()
        @stockdata_job
        def pooled_read(path):
            nonlocal read_count
            with connect_stockdata(path) as conn:
                row = conn.execute('SELECT marker FROM pv_com_repro_guard WHERE id=1').fetchone()
                assert row[0] == metadata['marker']
                read_count += 1
            emit('appworker_read', count=read_count, apartment=apartment())
        def read():
            pooled_read(db)
    elif args.case.endswith('thread'):
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='repro-access')
        def read():
            executor.submit(raw_read).result()
    elif 'access' in args.case:
        read = raw_read
    else:
        read = lambda: None

    # Match startup: initial reads before event loop, then callbacks after show.
    read()
    def tick():
        try:
            read()
            if label is not None:
                label.setText('Synthetische callbacks: '+str(read_count))
        except Exception as exc:
            failures.append(type(exc).__name__+': '+str(exc))
            emit('callback_error', error=failures[-1])
            app.quit()
    timer = QTimer(window)
    timer.setInterval(500)
    timer.timeout.connect(tick)
    timer.start()
    if args.surface in {'visible', 'offscreen'}:
        window.show()
    else:
        window.winId()  # Windows platform/window initialisation, without showing it.
    emit('enter_event_loop', apartment=apartment())
    QTimer.singleShot(int(args.seconds*1000), app.quit)
    result = app.exec()
    timer.stop()
    if executor:
        executor.shutdown(wait=True)
    stats = app_worker.worker_telemetry() if app_worker else []
    if app_worker:
        app_worker.shutdown_stockdata_workers()
    # Destroy the WebEngine page before its off-the-record profile.
    if web:
        web.page().deleteLater()
        app.processEvents()
    window.close()
    emit('finished', reads=read_count, callback_errors=failures, web_results=web_results,
         workers=stats, qt_exit=result)
    return 1 if failures or (web and not any(web_results)) else int(result)


def fixture(session):
    from uuid import uuid4
    path = session/'synthetic_qt_com.accdb'
    marker = uuid4().hex
    script = "$ErrorActionPreference='Stop';$e=New-Object -ComObject DAO.DBEngine.120;" \
        + "$d=$e.CreateDatabase('"+str(path).replace("'","''")+"',';LANGID=0x0409;CP=1252;COUNTRY=0',128);" \
        + "$d.Execute('CREATE TABLE pv_com_repro_guard (id LONG PRIMARY KEY, marker TEXT(64))');" \
        + "$d.Execute(\"INSERT INTO pv_com_repro_guard VALUES (1,'"+marker+"')\");$d.Close()"
    subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-EncodedCommand',
        base64.b64encode(script.encode('utf-16-le')).decode()], check=True, capture_output=True, timeout=30)
    (session/'synthetic_database.json').write_text(json.dumps(dict(database=str(path),
        marker=marker, synthetic_only=True)), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--surface', choices=['hidden','offscreen','visible'], default='hidden')
    parser.add_argument('--seconds', type=float, default=6)
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--cases', nargs='+', choices=CASES, default=list(CASES))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--native-messages', action='store_true',
                        help='Observe selected Windows messages on test windows only')
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--case', choices=CASES, help=argparse.SUPPRESS)
    parser.add_argument('--session', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.seconds < 1 or args.repeat < 1:
        parser.error('seconds >= 1 en repeat >= 1 vereist')
    if args.child:
        return child(args)
    diagnostics = ROOT.parents[1]/'diagnostics'
    session = diagnostics/('qt_com_repro_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    session.mkdir(parents=True)
    fixture(session)
    env = dict(os.environ, PYTHONIOENCODING='utf-8:backslashreplace', PYTHONUTF8='1')
    # Baseline: clear prior accessibility/GPU experiments, only for our children.
    cleared = {k: env.pop(k) for k in ('QTWEBENGINE_CHROMIUM_FLAGS','QT_ACCESSIBILITY',
        'QT_QPA_PLATFORM','QTWEBENGINE_DISABLE_SANDBOX') if k in env}
    if args.surface == 'offscreen':
        env['QT_QPA_PLATFORM'] = 'offscreen'
    results = []
    emit('matrix_start', session=str(session), cleared_test_environment=cleared)
    for iteration in range(1,args.repeat+1):
        for case in args.cases:
            log = session/f'{iteration:02d}_{case}_{args.surface}.log'
            command = [sys.executable, '-u', '-m', 'devtools.reproduce_qt_com', '--child',
                '--case', case, '--session', str(session), '--surface', args.surface,
                '--seconds', str(args.seconds)]
            if args.native_messages:
                command.append('--native-messages')
            started = time.monotonic()
            timed_out = False
            with log.open('wb') as stream:
                process = subprocess.Popen(command, cwd=ROOT, env=env,
                    stdout=stream, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                try:
                    code = process.wait(timeout=max(45,args.seconds+30))
                except subprocess.TimeoutExpired:
                    timed_out = True
                    import psutil
                    try:
                        children = psutil.Process(process.pid).children(recursive=True)
                    except psutil.NoSuchProcess:
                        children = []
                    process.kill()
                    process.wait(timeout=10)
                    for sub in children:
                        try:
                            sub.terminate()
                        except psutil.NoSuchProcess:
                            pass
                    code = process.returncode
            text = log.read_text(encoding='utf-8', errors='replace')
            row = dict(case=case, surface=args.surface, iteration=iteration, exit_code=code,
                timed_out=timed_out, seconds=round(time.monotonic()-started,2),
                target_exception_count=text.lower().count('code 0x8001010d'),
                finished='"stage": "finished"' in text, log=str(log))
            results.append(row)
            emit('case_result', **row)
            summary = dict(session=str(session), results=results)
            (session/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(summary,indent=2),encoding='utf-8')
    return int(any(r['exit_code'] or not r['finished'] for r in results))


if __name__ == '__main__':
    raise SystemExit(main())
