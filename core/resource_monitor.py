import ctypes
import ctypes.wintypes
import time

from . import windows_api as _win


class _FILETIME(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", ctypes.wintypes.DWORD),
        ("dwHighDateTime", ctypes.wintypes.DWORD),
    ]


class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.wintypes.DWORD),
        ("PageFaultCount", ctypes.wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


ctypes.windll.kernel32.GetCurrentProcess.restype = ctypes.wintypes.HANDLE
ctypes.windll.kernel32.GetProcessTimes.restype = ctypes.wintypes.BOOL
ctypes.windll.kernel32.GetProcessTimes.argtypes = [
    ctypes.wintypes.HANDLE,
    ctypes.POINTER(_FILETIME),
    ctypes.POINTER(_FILETIME),
    ctypes.POINTER(_FILETIME),
    ctypes.POINTER(_FILETIME),
]
ctypes.windll.psapi.GetProcessMemoryInfo.restype = ctypes.wintypes.BOOL
ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [
    ctypes.wintypes.HANDLE,
    ctypes.POINTER(_PROCESS_MEMORY_COUNTERS),
    ctypes.wintypes.DWORD,
]

_process_cpu_state: dict = {
    "last_time": 0.0,
    "last_process_time": 0,
    "cpu_percent": 0.0,
    "last_sample_time": 0.0,
    "mem_mb": 0.0,
}


def sample_process_resources() -> None:
    now = time.time()
    state = _process_cpu_state
    if now - state["last_sample_time"] < 1.0:
        return
    state["last_sample_time"] = now

    process = ctypes.windll.kernel32.GetCurrentProcess()

    creation_time = _FILETIME()
    exit_time = _FILETIME()
    kernel_time = _FILETIME()
    user_time = _FILETIME()
    result = ctypes.windll.kernel32.GetProcessTimes(
        process,
        ctypes.byref(creation_time),
        ctypes.byref(exit_time),
        ctypes.byref(kernel_time),
        ctypes.byref(user_time),
    )
    if result:
        process_time = (kernel_time.dwHighDateTime << 32 | kernel_time.dwLowDateTime) + \
                       (user_time.dwHighDateTime << 32 | user_time.dwLowDateTime)
        if state["last_time"] == 0.0:
            state["last_time"] = now
            state["last_process_time"] = process_time
        else:
            wall_delta = now - state["last_time"]
            if wall_delta >= 0.001:
                process_delta = process_time - state["last_process_time"]
                state["cpu_percent"] = min(process_delta / (wall_delta * 10_000_000) * 100, 100.0)
            state["last_time"] = now
            state["last_process_time"] = process_time

    counters = _PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS)
    result = ctypes.windll.psapi.GetProcessMemoryInfo(
        process,
        ctypes.byref(counters),
        counters.cb,
    )
    if result:
        state["mem_mb"] = counters.WorkingSetSize / (1024 * 1024)


def get_cpu_percent() -> float:
    return _process_cpu_state["cpu_percent"]


def get_mem_mb() -> float:
    return _process_cpu_state["mem_mb"]


def get_game_status() -> str:
    pid = _win._find_pid_by_name(_win.GAME_PROCESS_NAME)
    if pid is None:
        return "not_running"
    hwnd = _win.find_game_window(_win.GAME_PROCESS_NAME)
    if hwnd is None:
        return "no_window"
    return "connected"
