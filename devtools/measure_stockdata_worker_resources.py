"""Compare resource growth on a NEW synthetic Access DB, never a user database.

python -m devtools.measure_stockdata_worker_resources --mode worker --iterations 100 --duration 60 --output result.json
Run direct and worker in separate processes. No process-wide inventory polling.
"""
import argparse
import base64
import ctypes
from datetime import datetime
import json
from pathlib import Path
import subprocess
import tempfile
import time

import psutil

from portefeuille_viewer.data.shared_database import connect_stockdata
from portefeuille_viewer.data.stockdata_worker import (enable_stockdata_workers,
    shutdown_stockdata_workers, stockdata_job, worker_for)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['direct', 'worker'], required=True)
    parser.add_argument('--iterations', type=int, default=100)
    parser.add_argument('--duration', type=float, default=60)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.iterations < 2 or args.duration < 0:
        parser.error('iterations >= 2 en duration >= 0 vereist')
    user = ctypes.WinDLL('user32')
    kernel = ctypes.WinDLL('kernel32')
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    user.GetGuiResources.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    user.GetGuiResources.restype = ctypes.c_uint
    handle = kernel.GetCurrentProcess()
    process = psutil.Process()
    def sample(iteration):
        return dict(iteration=iteration, seconds=round(time.monotonic()-started, 3),
            gdi=user.GetGuiResources(handle, 0), handles=process.num_handles(),
            rss_mb=round(process.memory_info().rss/1048576, 2), threads=process.num_threads())
    with tempfile.TemporaryDirectory(prefix='pv-worker-resource-') as tmp:
        path = Path(tmp)/'synthetic.accdb'
        script = "$ErrorActionPreference='Stop';$e=New-Object -ComObject DAO.DBEngine.120;" \
            + "$d=$e.CreateDatabase('"+str(path).replace("'","''")+"',';LANGID=0x0409;CP=1252;COUNTRY=0',128);" \
            + "$d.Execute('CREATE TABLE probe (id LONG PRIMARY KEY)');$d.Execute('INSERT INTO probe VALUES (1)');$d.Close()"
        subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-EncodedCommand',
            base64.b64encode(script.encode('utf-16-le')).decode()], check=True, capture_output=True, timeout=30)
        @stockdata_job
        def probe(path):
            with connect_stockdata(path) as conn:
                return conn.execute('SELECT id FROM probe').fetchone()[0]
        if args.mode == 'worker':
            enable_stockdata_workers()
        started = time.monotonic()
        samples = [sample(0)]
        try:
            # Warm-up separately: driver initialisation must not count as a leak.
            assert probe(path) == 1
            samples.append(sample(1))
            for i in range(2, args.iterations+1):
                assert probe(path) == 1
                if i % 10 == 0 or i == args.iterations:
                    samples.append(sample(i))
                target = args.duration*(i-1)/(args.iterations-1)
                time.sleep(max(0, started+target-time.monotonic()))
            samples.append(sample(args.iterations))
            stats = worker_for(path).stats() if args.mode == 'worker' else None
        finally:
            shutdown_stockdata_workers()
        report = dict(mode=args.mode, finished_at=datetime.now().astimezone().isoformat(),
            samples=samples, worker=stats, after_shutdown=sample(args.iterations))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(dict(mode=args.mode, after_warmup=samples[1], final=samples[-1], worker=stats)))


if __name__ == '__main__':
    main()
