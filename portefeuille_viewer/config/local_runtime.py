"""Local runtime common to app versions using the same STOCKDATA file."""
import hashlib
import os
from pathlib import Path
import time

from .process_lock import canonical_path
from .profile_storage import computer_id


def runtime_root():
    override = os.environ.get('PV_RUNTIME_ROOT')
    base = Path(override) if override else Path(__file__).resolve().parents[3] / '.portefeuille_runtime'
    root = base / computer_id()
    root.mkdir(parents=True, exist_ok=True)
    return root


def resource_id(resource):
    return hashlib.sha256(str(resource).encode('utf-8')).hexdigest()


class FileLease:
    """OS-held byte-range lock, releasable from a different worker thread."""
    def __init__(self, resource):
        self.path = runtime_root() / 'leases' / (resource_id(resource) + '.lock')
        self.file = None

    def acquire(self, timeout=0):
        import msvcrt
        if self.file is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        f = open(self.path, 'a+b')
        if f.seek(0, 2) == 0:
            f.write(b'0'); f.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                self.file = f
                return True
            except OSError as exc:
                if exc.errno not in (13, 11, 36):
                    f.close(); raise
                if time.monotonic() >= deadline:
                    f.close(); return False
                time.sleep(.025)

    def release(self):
        if self.file is not None:
            f, self.file = self.file, None
            f.close()

    def __enter__(self):
        if not self.acquire(15):
            raise TimeoutError('Gedeelde taak is nog actief in een andere instantie')
        return self

    def __exit__(self, *args):
        self.release()


def maintenance_lease(stock_path):
    return FileLease('stock-maintenance:' + canonical_path(stock_path))


def canonical_host(host):
    value = str(host).strip().lower()
    return '127.0.0.1' if value in {'localhost', '::1', '[::1]', '127.0.0.1'} else value
