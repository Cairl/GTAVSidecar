import ctypes
import ctypes.wintypes
import time

import numpy as np

GAME_PROCESS_NAME = "GTA5_Enhanced.exe"

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_EXTENDEDKEY = 0x0001
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
PW_RENDERFULLCONTENT = 2
TH32CS_SNAPPROCESS = 0x00000002
PROCESS_TERMINATE = 0x0001


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.wintypes.LONG),
        ("top", ctypes.wintypes.LONG),
        ("right", ctypes.wintypes.LONG),
        ("bottom", ctypes.wintypes.LONG),
    ]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.wintypes.DWORD),
        ("biWidth", ctypes.wintypes.LONG),
        ("biHeight", ctypes.wintypes.LONG),
        ("biPlanes", ctypes.wintypes.WORD),
        ("biBitCount", ctypes.wintypes.WORD),
        ("biCompression", ctypes.wintypes.DWORD),
        ("biSizeImage", ctypes.wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.wintypes.LONG),
        ("biYPelsPerMeter", ctypes.wintypes.LONG),
        ("biClrUsed", ctypes.wintypes.DWORD),
        ("biClrImportant", ctypes.wintypes.DWORD),
    ]


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.wintypes.DWORD),
        ("cntUsage", ctypes.wintypes.DWORD),
        ("th32ProcessID", ctypes.wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", ctypes.wintypes.DWORD),
        ("cntThreads", ctypes.wintypes.DWORD),
        ("th32ParentProcessID", ctypes.wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.wintypes.WORD),
        ("wScan", ctypes.wintypes.WORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.wintypes.ULONG)),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.wintypes.LONG),
        ("dy", ctypes.wintypes.LONG),
        ("mouseData", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.wintypes.ULONG)),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("_input",)
    _fields_ = [
        ("type", ctypes.wintypes.DWORD),
        ("_input", _INPUT_UNION),
    ]


_KEY_MAP = {
    "w": 0x11, "a": 0x1E, "s": 0x1F, "d": 0x20,
    "esc": 0x01,
    "enter": 0x1C,
    "up": 0x48, "down": 0x50, "left": 0x4B, "right": 0x4D,
}
_EXTENDED_KEYS = {"up", "down", "left", "right"}
_ARROW_KEY_MAP = {
    "w": "up", "a": "left", "s": "down", "d": "right",
}

_BG_VK_MAP = {
    "enter": 0x0D, "return": 0x0D,
    "space": 0x20,
    "esc": 0x1B, "escape": 0x1B,
    "tab": 0x09,
    "backspace": 0x08,
    "delete": 0x2E, "del": 0x2E,
    "insert": 0x2D, "ins": 0x2D,
    "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
    "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77,
    "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    "shift": 0x10, "ctrl": 0x11, "alt": 0x12,
    "lshift": 0xA0, "rshift": 0xA1,
    "lctrl": 0xA2, "rctrl": 0xA3,
    "lalt": 0xA4, "ralt": 0xA5,
}
_EXTENDED_VKS = frozenset({
    0x21, 0x22, 0x23, 0x24,
    0x25, 0x26, 0x27, 0x28,
    0x2D, 0x2E,
    0x5B, 0x5C,
})


def _find_pid_by_name(process_name: str) -> int | None:
    snapshot = ctypes.windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == -1:
        return None

    entry = _PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
    result = None

    if ctypes.windll.kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
        while True:
            if entry.szExeFile.lower() == process_name.lower():
                result = entry.th32ProcessID
                break
            entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
            if not ctypes.windll.kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break

    ctypes.windll.kernel32.CloseHandle(snapshot)
    return result


def _find_window_by_pid(pid: int) -> int | None:
    result = []

    @ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def callback(hwnd, _):
        if ctypes.windll.user32.IsWindowVisible(hwnd):
            wpid = ctypes.wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
            if wpid.value == pid:
                result.append(hwnd)
        return True

    ctypes.windll.user32.EnumWindows(callback, 0)
    return result[0] if result else None


def find_game_window(process_name: str = GAME_PROCESS_NAME) -> int | None:
    pid = _find_pid_by_name(process_name)
    if pid is None:
        return None
    return _find_window_by_pid(pid)


def capture_window(hwnd: int) -> np.ndarray | None:
    rect = _RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w = rect.right - rect.left
    h = rect.bottom - rect.top

    if w <= 0 or h <= 0:
        return None

    hwnd_dc = ctypes.windll.user32.GetWindowDC(hwnd)
    if not hwnd_dc:
        return None

    mem_dc = ctypes.windll.gdi32.CreateCompatibleDC(hwnd_dc)
    bitmap = ctypes.windll.gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
    old_bitmap = ctypes.windll.gdi32.SelectObject(mem_dc, bitmap)

    ctypes.windll.user32.PrintWindow(hwnd, mem_dc, PW_RENDERFULLCONTENT)

    bmi = _BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0

    buf_size = w * h * 4
    buf = ctypes.create_string_buffer(buf_size)

    scan_lines = ctypes.windll.gdi32.GetDIBits(
        mem_dc, bitmap, 0, h,
        ctypes.byref(buf), ctypes.byref(bmi), 0,
    )

    ctypes.windll.gdi32.SelectObject(mem_dc, old_bitmap)
    ctypes.windll.gdi32.DeleteObject(bitmap)
    ctypes.windll.gdi32.DeleteDC(mem_dc)
    ctypes.windll.user32.ReleaseDC(hwnd, hwnd_dc)

    if scan_lines == 0:
        return None

    arr = np.frombuffer(buf.raw, dtype=np.uint8).reshape((h, w, 4))
    return arr[:, :, :3].copy()


def get_client_offset(hwnd: int) -> tuple[int, int]:
    window_rect = _RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(window_rect))

    point = ctypes.wintypes.POINT(0, 0)
    ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(point))

    return (point.x - window_rect.left, point.y - window_rect.top)


def get_client_screen_origin(hwnd: int) -> tuple[int, int]:
    point = ctypes.wintypes.POINT(0, 0)
    ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(point))
    return (point.x, point.y)


def bring_to_foreground(hwnd: int) -> bool:
    if ctypes.windll.user32.IsIconic(hwnd):
        ctypes.windll.user32.ShowWindow(hwnd, 9)

    for _ in range(10):
        fg = ctypes.windll.user32.GetForegroundWindow()
        if fg == hwnd:
            return True
        fg_tid = ctypes.windll.user32.GetWindowThreadProcessId(fg, None)
        cur_tid = ctypes.windll.kernel32.GetCurrentThreadId()
        ctypes.windll.user32.AttachThreadInput(cur_tid, fg_tid, True)
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        ctypes.windll.user32.AttachThreadInput(cur_tid, fg_tid, False)
        time.sleep(0.05)

    return ctypes.windll.user32.GetForegroundWindow() == hwnd


def focus_game_window(hwnd: int) -> bool:
    bring_to_foreground(hwnd)
    time.sleep(0.3)
    rect = _RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    center_x = (rect.left + rect.right) // 2
    center_y = (rect.top + rect.bottom) // 2
    click_at(center_x, center_y)
    time.sleep(0.5)
    return True


def _make_mouse_input(flags: int) -> _INPUT:
    inp = _INPUT()
    inp.type = INPUT_MOUSE
    inp.mi.dx = 0
    inp.mi.dy = 0
    inp.mi.mouseData = 0
    inp.mi.dwFlags = flags
    inp.mi.time = 0
    inp.mi.dwExtraInfo = ctypes.pointer(ctypes.wintypes.ULONG(0))
    return inp


def click_at(screen_x: int, screen_y: int) -> None:
    ctypes.windll.user32.SetCursorPos(screen_x, screen_y)
    time.sleep(0.1)

    ctypes.windll.user32.SendInput(
        1, ctypes.byref(_make_mouse_input(MOUSEEVENTF_LEFTDOWN)), ctypes.sizeof(_INPUT)
    )
    time.sleep(0.08)
    ctypes.windll.user32.SendInput(
        1, ctypes.byref(_make_mouse_input(MOUSEEVENTF_LEFTUP)), ctypes.sizeof(_INPUT)
    )


def _make_key_input(scan_code: int, flags: int) -> _INPUT:
    inp = _INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki.wVk = 0
    inp.ki.wScan = scan_code
    inp.ki.dwFlags = flags | KEYEVENTF_SCANCODE
    inp.ki.time = 0
    inp.ki.dwExtraInfo = ctypes.pointer(ctypes.wintypes.ULONG(0))
    return inp


def send_key(key: str) -> None:
    key_lower = key.lower()
    if key_lower in _ARROW_KEY_MAP:
        key_lower = _ARROW_KEY_MAP[key_lower]
    scan = _KEY_MAP.get(key_lower)
    if scan is None:
        return
    ext = KEYEVENTF_EXTENDEDKEY if key_lower in _EXTENDED_KEYS else 0
    ctypes.windll.user32.SendInput(
        1, ctypes.byref(_make_key_input(scan, ext)), ctypes.sizeof(_INPUT)
    )
    time.sleep(0.08)
    ctypes.windll.user32.SendInput(
        1, ctypes.byref(_make_key_input(scan, ext | KEYEVENTF_KEYUP)), ctypes.sizeof(_INPUT)
    )
    time.sleep(0.08)


def clip_cursor_to_window(hwnd: int) -> None:
    rect = _RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    ctypes.windll.user32.ClipCursor(ctypes.byref(rect))


def unclip_cursor() -> None:
    ctypes.windll.user32.ClipCursor(None)


def _resolve_vk(key: str) -> int | None:
    lower = key.lower()
    vk = _BG_VK_MAP.get(lower)
    if vk is not None:
        return vk
    if len(key) == 1 and key.isalpha():
        return ord(key.upper())
    if len(key) == 1 and key.isdigit():
        return ord(key)
    return None


def send_key_background(hwnd: int, key: str) -> None:
    vk = _resolve_vk(key)
    if vk is None:
        return
    scan_code = ctypes.windll.user32.MapVirtualKeyW(vk, 0)
    ext_flag = (1 << 24) if vk in _EXTENDED_VKS else 0
    lParam_down = ext_flag | (scan_code << 16) | 1
    lParam_up = ext_flag | (scan_code << 16) | (1 << 30) | (1 << 31) | 1
    ctypes.windll.user32.PostMessageW(hwnd, WM_KEYDOWN, vk, lParam_down)
    time.sleep(0.05)
    ctypes.windll.user32.PostMessageW(hwnd, WM_KEYUP, vk, lParam_up)


def kill_game_process(process_name: str) -> bool:
    pid = _find_pid_by_name(process_name)
    if pid is None:
        return False
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not handle:
        return False
    result = ctypes.windll.kernel32.TerminateProcess(handle, 0)
    ctypes.windll.kernel32.CloseHandle(handle)
    return result != 0
