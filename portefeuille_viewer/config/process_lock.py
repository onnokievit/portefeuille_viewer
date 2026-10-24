"""Windows locks shared by processes and app versions, without stale lock files."""
import ctypes
from ctypes import wintypes
import hashlib
import os


def canonical_path(path):
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


class ProcessLock:
    def __init__(self, resource):
        digest = hashlib.sha256(resource.encode('utf-8')).hexdigest()
        self.name = 'Global\\PortefeuilleViewer.' + digest
        self.handle = None
        self.owned = False

    def acquire(self, timeout_ms=0):
        if os.name != 'nt':
            raise RuntimeError('Deze procesbescherming vereist Windows')
        if self.owned:
            return True
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateMutexW.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
        kernel.ReleaseMutex.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        self.kernel = kernel
        handle = kernel.CreateMutexW(None, False, self.name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        status = kernel.WaitForSingleObject(handle, timeout_ms)
        if status in (0, 0x80):  # acquired, or abandoned after a crash
            self.handle, self.owned = handle, True
            return True
        error = ctypes.get_last_error()
        kernel.CloseHandle(handle)
        if status == 0x102:
            return False
        raise ctypes.WinError(error)

    def release(self):
        if self.handle:
            handle = self.handle
            if self.owned and not self.kernel.ReleaseMutex(handle):
                raise ctypes.WinError(ctypes.get_last_error())
            self.handle, self.owned = None, False
            self.kernel.CloseHandle(handle)

    def __enter__(self):
        if not self.acquire(10000):
            raise TimeoutError('Instellingen worden door een andere instantie bijgewerkt; probeer opnieuw')
        return self

    def __exit__(self, *exc):
        self.release()
