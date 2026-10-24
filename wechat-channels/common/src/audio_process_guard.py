"""Bounded cleanup for owned recorder processes/files, never crawler processes."""
import json
import os
import subprocess
import time
from pathlib import Path


def _log(event):
    print(json.dumps(event, ensure_ascii=False), flush=True)


def stop_owned_recorder(process, *, log=_log):
    """Kill only the Popen recorder's tree, then reap it before WAV cleanup."""
    if process is None or process.poll() is not None:
        return True
    try:
        if os.name == 'nt':
            # Killing only the Python wrapper leaves its native WAV writer alive.
            result = subprocess.run(
                ['taskkill.exe', '/PID', str(int(process.pid)), '/T', '/F'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
            if result.returncode and process.poll() is None:
                raise RuntimeError('recorder_tree_termination_failed')
        else:
            process.terminate()
        process.wait(timeout=5)
        return True
    except Exception as error:
        log({'event': 'recorder_cleanup_deferred', 'pid': getattr(process, 'pid', None),
             'errorType': type(error).__name__, 'cleanupConfirmed': False})
        return False


def cleanup_audio_file(path, *, delays=(0.1, 0.2, 0.4, 0.8), pause=time.sleep, log=_log):
    """A cleanup failure must not replace an identity/stop/recording exception."""
    for attempt in range(len(delays) + 1):
        try:
            Path(path).unlink(missing_ok=True)
            return True
        except OSError as error:
            if attempt == len(delays):
                log({'event': 'audio_temp_cleanup_deferred', 'path': str(path),
                     'errorType': type(error).__name__,
                     'winerror': getattr(error, 'winerror', None), 'fileRetained': True})
                return False
            pause(delays[attempt])


class NativeRecorderJob:
    """Windows closes this job on wrapper termination, killing native writers.

    The collector also terminates the entire live recorder tree. The job covers
    abnormal wrapper exits after child assignment; no unrelated PID is targeted.
    """
    def __enter__(self):
        self.handle = None
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            class Basic(ctypes.Structure):
                _fields_ = [('processTime', ctypes.c_int64), ('jobTime', ctypes.c_int64),
                            ('flags', wintypes.DWORD), ('minSet', ctypes.c_size_t),
                            ('maxSet', ctypes.c_size_t), ('active', wintypes.DWORD),
                            ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD),
                            ('scheduling', wintypes.DWORD)]
            class IO(ctypes.Structure):
                _fields_ = [(name, ctypes.c_uint64) for name in
                            ('readOps', 'writeOps', 'otherOps', 'readBytes', 'writeBytes', 'otherBytes')]
            class Extended(ctypes.Structure):
                _fields_ = [('basic', Basic), ('io', IO), ('processMemory', ctypes.c_size_t),
                            ('jobMemory', ctypes.c_size_t), ('peakProcess', ctypes.c_size_t),
                            ('peakJob', ctypes.c_size_t)]
            self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
            self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
            self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
            self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            self.handle = self.kernel.CreateJobObjectW(None, None)
            if not self.handle:
                raise ctypes.WinError(ctypes.get_last_error())
            limits = Extended()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                error = ctypes.WinError(ctypes.get_last_error())
                self.__exit__(None, None, None)
                raise error
        return self

    def spawn(self, command, **kwargs):
        process = subprocess.Popen(command, **kwargs)
        if self.handle:
            if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
                import ctypes
                error = ctypes.WinError(ctypes.get_last_error())
                stop_owned_recorder(process)
                raise error
        return process

    def __exit__(self, *_):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
