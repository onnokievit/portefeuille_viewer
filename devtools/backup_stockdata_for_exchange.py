"""Consistent explicit backup before first Wyse import; requires exclusive file access."""
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime
import msvcrt
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from portefeuille_viewer.config.process_lock import ProcessLock, canonical_path


def backup(path):
    path=Path(path).resolve()
    if not path.is_file() or path.suffix.lower()!='.accdb':
        raise ValueError('Bestaande STOCKDATA .accdb vereist')
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,
                                 wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    kernel.CreateFileW.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    target=path.with_name(path.stem+'.before-wyse-stockdata-'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.accdb')
    with ProcessLock('stock-writer:'+canonical_path(path)):
        handle=kernel.CreateFileW(str(path),0x80000000,0,None,3,0x80,None)
        if handle==ctypes.c_void_p(-1).value:
            raise RuntimeError('STOCKDATA is in gebruik; sluit viewers en Access voordat de backup wordt gemaakt')
        try:
            descriptor=msvcrt.open_osfhandle(handle,os.O_RDONLY|os.O_BINARY)
        except BaseException:
            kernel.CloseHandle(handle)
            raise
        with os.fdopen(descriptor,'rb') as source, target.open('xb') as dest:
            shutil.copyfileobj(source,dest,8*1024*1024)
            dest.flush();os.fsync(dest.fileno())
    if target.stat().st_size!=path.stat().st_size:
        raise RuntimeError('Backupgrootte verschilt; import niet starten')
    return target


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',required=True,type=Path)
    args=parser.parse_args()
    print(backup(args.db))
