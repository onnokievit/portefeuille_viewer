"""Terminate a QProcess and its descendants if its owning app crashes."""
import ctypes
from ctypes import wintypes
import logging


class WorkerJob:
    def __init__(self, process):
        self.process = process
        self.handle = None
        process.started.connect(self.attach)
        process.finished.connect(self.close)
        process.errorOccurred.connect(self.abort)

    def attach(self):
        # Layout from JOBOBJECT_EXTENDED_LIMIT_INFORMATION (Windows SDK).
        class Basic(ctypes.Structure):
            _fields_=[('process_time',ctypes.c_int64),('job_time',ctypes.c_int64),
                      ('flags',wintypes.DWORD),('min_ws',ctypes.c_size_t),('max_ws',ctypes.c_size_t),
                      ('active',wintypes.DWORD),('affinity',ctypes.c_size_t),
                      ('priority',wintypes.DWORD),('scheduling',wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_=[(n,ctypes.c_uint64) for n in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
        class Limits(ctypes.Structure):
            _fields_=[('basic',Basic),('io',IO),('process_memory',ctypes.c_size_t),
                      ('job_memory',ctypes.c_size_t),('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR];kernel.CreateJobObjectW.restype=wintypes.HANDLE
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
        kernel.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE]
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        job=kernel.CreateJobObjectW(None,None)
        child=kernel.OpenProcess(0x0100|0x0001,False,int(self.process.processId()))
        limits=Limits();limits.basic.flags=0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok=job and child and kernel.SetInformationJobObject(job,9,ctypes.byref(limits),ctypes.sizeof(limits)) and kernel.AssignProcessToJobObject(job,child)
        if child:kernel.CloseHandle(child)
        if not ok:
            error=ctypes.get_last_error()
            if job:kernel.CloseHandle(job)
            self.process.kill()
            logging.getLogger(__name__).error('Worker containment failed (%s); worker stopped',error)
            return
        self.kernel,self.handle=kernel,job

    def abort(self, *args):
        self.close()  # closing the job stops all descendants before task lease release
        if self.process.state() != self.process.ProcessState.NotRunning:
            self.process.kill()
            self.process.waitForFinished(3000)

    def close(self,*args):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle=None


def protect_worker(process):
    process._pv_worker_job=WorkerJob(process)
    return process
