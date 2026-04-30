import sys
import os
import re
import json
import time
import winreg
import shutil
import msvcrt
import ctypes
import ctypes.wintypes
import threading
import importlib.util
import unicodedata

import cv2
import numpy as np

sys.dont_write_bytecode = True

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
_config_cache: dict = {"data": None, "mtime": 0.0}
GAME_PROCESS_NAME = "GTA5_Enhanced.exe"

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

C_RED = "\033[38;2;243;139;168m"
C_GREEN = "\033[38;2;166;227;161m"
C_YELLOW = "\033[38;2;249;226;175m"
C_GRAY = "\033[90m"
C_RESET = "\033[0m"
C_BORDER = "\033[38;2;88;91;112m"
C_HIGHLIGHT = "\033[48;2;88;91;112m"
C_UNDERLINE = "\033[4m"
C_BLUE = "\033[38;2;137;180;250m"


def _truncate_visible(s: str, max_width: int) -> str:
    visible = 0
    i = 0
    while i < len(s):
        if s[i] == '\033':
            j = s.find('m', i)
            if j >= 0:
                i = j + 1
            else:
                i = len(s)
        else:
            w = 2 if unicodedata.east_asian_width(s[i]) in ('W', 'F') else 1
            if visible + w > max_width:
                return s[:i] + C_RESET
            visible += w
            i += 1
    return s

BORDER_TL = "╭"
BORDER_TR = "╮"
BORDER_BL = "╰"
BORDER_BR = "╯"
BORDER_H = "─"
BORDER_V = "│"

_translations: dict[str, str] = {}
_fallback: dict[str, str] = {}


def i18n_init(lang: str, base_dir: str) -> None:
    global _translations, _fallback

    en_path = os.path.join(base_dir, "locales", "en_US.json")
    if os.path.exists(en_path):
        with open(en_path, "r", encoding="utf-8") as f:
            _fallback = json.load(f)

    lang_path = os.path.join(base_dir, "locales", f"{lang}.json")
    if os.path.exists(lang_path):
        with open(lang_path, "r", encoding="utf-8") as f:
            _translations = json.load(f)
    else:
        _translations = _fallback.copy()


def translate(key: str, **kwargs) -> str:
    text = _translations.get(key) or _fallback.get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text


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


PROCESS_TERMINATE = 0x0001


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


_anti_afk_task = None


def _start_anti_afk() -> None:
    global _anti_afk_task
    if _anti_afk_task and _anti_afk_task.is_running:
        return
    if _anti_afk_task is None:
        mod = _load_task_module("anti_afk")
        if mod is None:
            return
        task_cls = getattr(mod, "Task", None)
        if task_cls is None:
            return
        config = load_config()
        afk_cfg = config.get("anti_afk", {})
        task = task_cls("anti_afk", afk_cfg, config)
        if not task.load():
            return
        _anti_afk_task = task
    _anti_afk_task.start()


def _stop_anti_afk() -> None:
    global _anti_afk_task
    if _anti_afk_task:
        _anti_afk_task.stop()


class OverlayMatcher:
    def __init__(self, overlay_path: str, alpha_threshold: int = 128):
        self._overlay_path = overlay_path
        self._alpha_threshold = alpha_threshold
        self._template: np.ndarray | None = None
        self._template_scan: np.ndarray | None = None
        self._mask: np.ndarray | None = None
        self._bbox: tuple[int, int, int, int] = (0, 0, 0, 0)
        self._center: tuple[int, int] = (0, 0)
        self._load_overlay()

    def _load_overlay(self) -> None:
        raw = np.fromfile(self._overlay_path, dtype=np.uint8)
        overlay = cv2.imdecode(raw, cv2.IMREAD_UNCHANGED)
        if overlay is None:
            raise FileNotFoundError(translate("overlay_load_error", path=self._overlay_path))
        if overlay.ndim != 3 or overlay.shape[2] != 4:
            raise ValueError(translate("overlay_format_error"))

        alpha = overlay[:, :, 3]
        binary = (alpha > self._alpha_threshold).astype(np.uint8) * 255

        coords = cv2.findNonZero(binary)
        if coords is None:
            raise ValueError(translate("overlay_empty_error"))

        x, y, w, h = cv2.boundingRect(coords)
        self._bbox = (x, y, w, h)
        self._center = (x + w // 2, y + h // 2)
        self._template = overlay[y:y + h, x:x + w, :3]
        self._mask = binary[y:y + h, x:x + w]

        mask_bool = self._mask > 0
        self._template_scan = self._template.copy()
        if mask_bool.any() and not mask_bool.all():
            mean_color = self._template[mask_bool].mean(axis=0).astype(np.uint8)
            self._template_scan[~mask_bool] = mean_color

    @property
    def center(self) -> tuple[int, int]:
        return self._center

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        return self._bbox

    def match_from_image(
        self, image: np.ndarray, threshold: float = 0.95, offset: tuple[int, int] = (0, 0),
    ) -> tuple[bool, float]:
        x, y, w, h = self._bbox
        x += offset[0]
        y += offset[1]

        if y < 0 or x < 0 or y + h > image.shape[0] or x + w > image.shape[1]:
            return False, 0.0

        region = image[y:y + h, x:x + w]
        if region.shape[:2] != self._template.shape[:2]:
            return False, 0.0

        diff = cv2.absdiff(region, self._template)
        diff_gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        mask_float = self._mask.astype(np.float32) / 255.0

        total_weight = mask_float.sum()
        if total_weight < 1.0:
            return False, 0.0

        weighted_diff = (diff_gray * mask_float).sum()
        confidence = 1.0 - weighted_diff / total_weight

        return confidence >= threshold, round(float(confidence), 4)

    def match_from_image_scan(
        self, image: np.ndarray, threshold: float = 0.95, offset: tuple[int, int] = (0, 0),
    ) -> tuple[bool, float, tuple[int, int] | None]:
        _, y, w, h = self._bbox
        y_adj = y + offset[1]

        pad = 20
        y_start = max(0, y_adj - pad)
        y_end = min(image.shape[0], y_adj + h + pad)

        strip = image[y_start:y_end, :]

        if strip.shape[0] < self._template_scan.shape[0] or strip.shape[1] < self._template_scan.shape[1]:
            return False, 0.0, None

        result = cv2.matchTemplate(strip, self._template_scan, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val < 0.5:
            return False, round(float(max_val), 4), None

        match_x, match_y = max_loc
        region = strip[match_y:match_y + h, match_x:match_x + w]
        if region.shape[:2] != self._template.shape[:2]:
            return False, round(float(max_val), 4), None

        diff = cv2.absdiff(region, self._template)
        diff_gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        mask_float = self._mask.astype(np.float32) / 255.0

        total_weight = mask_float.sum()
        if total_weight < 1.0:
            return False, 0.0, None

        weighted_diff = (diff_gray * mask_float).sum()
        confidence = 1.0 - weighted_diff / total_weight

        found = confidence >= threshold
        if found:
            center_x = match_x + w // 2 - offset[0]
            center_y = y_start + match_y + h // 2 - offset[1]
            return True, round(float(confidence), 4), (center_x, center_y)

        return False, round(float(confidence), 4), None


class BaseTask:
    start_trigger: dict = {}
    steps: list[dict] = []
    group: str | None = None
    step_timeout_ms: int = 30000

    def __init__(self, task_name: str, task_cfg: dict, global_cfg: dict):
        self._task_name = task_name
        self._task_cfg = task_cfg
        self._global_cfg = global_cfg
        self._matchers: list[OverlayMatcher | None] = []
        self._step_names: list[str] = []
        self._step_scans: list[bool] = []
        self._step_actions: list[str] = []
        self._start_trigger_matcher: OverlayMatcher | None = None
        self._start_trigger_name: str = ""
        self._start_trigger_scan: bool = False
        self._start_trigger_click: bool = True
        self._is_key_sequence = False
        self._key_steps: list[dict] = []

    def _resolve_overlay(self, overlay: str, lang: str) -> str:
        base = os.path.join(BASE_DIR, "tasks", self._task_name)
        game_lang = resolve_game_language(self._global_cfg.get("lang", "auto"))

        if lang == "auto":
            lang_path = os.path.join(base, game_lang, f"{overlay}.png")
            if os.path.exists(lang_path):
                return lang_path
            for fallback in ("global", "en_US"):
                fb_path = os.path.join(base, fallback, f"{overlay}.png")
                if os.path.exists(fb_path):
                    return fb_path
            return os.path.join(base, game_lang, f"{overlay}.png")

        return os.path.join(base, lang, f"{overlay}.png")

    def _load_single_matcher(self, overlay: str, lang: str, alpha_threshold: int) -> OverlayMatcher | None:
        path = self._resolve_overlay(overlay, lang)
        try:
            return OverlayMatcher(path, alpha_threshold=alpha_threshold)
        except (FileNotFoundError, ValueError) as e:
            _log_buffer.add(
                f"[{translate(f'task.{self._task_name}')}] {C_RED}{translate('overlay_load_failed', overlay=overlay, error=e)}{C_RESET}"
            )
            return None

    def load(self) -> bool:
        alpha_threshold = 128

        start_trigger_cfg = self.start_trigger
        steps = self.steps

        if not start_trigger_cfg and steps and all("delay" in s for s in steps):
            self._is_key_sequence = True
            self._key_steps = steps
            self._matchers = []
            self._step_names = []
            self._step_scans = []
            self._step_actions = []
            return True

        if not start_trigger_cfg or steps is None:
            _log_buffer.add(
                f"[{translate(f'task.{self._task_name}')}] {C_RED}"
                f"{translate('overlay_load_failed', overlay='task.py', error='missing start_trigger or steps')}{C_RESET}"
            )
            return False

        self._step_scans = []
        self._step_actions = []
        self._start_trigger_scan = False
        self._start_trigger_click = True

        self._start_trigger_scan = start_trigger_cfg.get("scan") == "horizontal"
        self._start_trigger_click = start_trigger_cfg.get("click", True)
        matcher = self._load_single_matcher(
            start_trigger_cfg["overlay"],
            start_trigger_cfg.get("lang", "auto"),
            alpha_threshold,
        )
        if matcher is None:
            return False
        self._start_trigger_matcher = matcher
        self._start_trigger_name = start_trigger_cfg["overlay"]

        matchers = []
        names = []
        for step in steps:
            action = step.get("action", "click")
            if action == "hack":
                matchers.append(None)
                names.append(step.get("overlay", "hack"))
                self._step_scans.append(False)
                self._step_actions.append("hack")
                continue
            matcher = self._load_single_matcher(
                step["overlay"], step.get("lang", "auto"), alpha_threshold,
            )
            if matcher is None:
                return False
            matchers.append(matcher)
            names.append(step["overlay"])
            self._step_scans.append(step.get("scan") == "horizontal")
            self._step_actions.append(action)

        self._matchers = matchers
        self._step_names = names
        return True

    def match_start_trigger(self, image, offset, threshold):
        if self._start_trigger_matcher is None:
            return False, 0.0, None
        if self._start_trigger_scan:
            found, confidence, scan_center = self._start_trigger_matcher.match_from_image_scan(image, threshold, offset)
            return found, confidence, scan_center
        found, confidence = self._start_trigger_matcher.match_from_image(image, threshold, offset)
        return found, confidence, None

    def execute_start_trigger(self, hwnd, confidence, scan_center):
        display_name = translate(f"task.{self._task_name}")
        step_key = f"step.{self._start_trigger_name}.{self._task_name}"
        step_display = translate(step_key)
        if step_display == step_key:
            step_display = self._start_trigger_name
        if self._start_trigger_click:
            self._click_matcher(hwnd, self._start_trigger_matcher, scan_center)
            _log_buffer.add(
                f"[{display_name}] {translate('start_trigger_detected', name=f'{C_YELLOW}{step_display}{C_RESET}', confidence=f'{confidence:.1%}')}"
            )
        else:
            _log_buffer.add(
                f"[{display_name}] {translate('detected', name=f'{C_YELLOW}{step_display}{C_RESET}')}"
            )

    def match_step(self, step_index, image, offset, threshold):
        if self._step_actions[step_index] == "hack":
            return True, 1.0, None
        matcher = self._matchers[step_index]
        if matcher is None:
            return False, 0.0, None
        if self._step_scans[step_index]:
            found, confidence, scan_center = matcher.match_from_image_scan(image, threshold, offset)
            return found, confidence, scan_center
        found, confidence = matcher.match_from_image(image, threshold, offset)
        return found, confidence, None

    def execute_step(self, step_index, hwnd, confidence, scan_center):
        display_name = translate(f"task.{self._task_name}")
        step_name = self._step_names[step_index]
        action = self._step_actions[step_index]

        step_key = f"step.{step_name}.{self._task_name}"
        step_display = translate(step_key)
        if step_display == step_key:
            step_display = step_name

        if action == "kill_process":
            killed = kill_game_process(GAME_PROCESS_NAME)
            if killed:
                msg = translate('process_killed')
                _log_buffer.add(f"[{display_name}] {_color_step(msg)} ({confidence:.1%})")
            else:
                _log_buffer.add(
                    f"[{display_name}] {C_RED}{translate('process_kill_failed')}{C_RESET}"
                )
            return True

        matcher = self._matchers[step_index]
        self._click_matcher(hwnd, matcher, scan_center)
        colored_step = _color_step(step_display)
        _log_buffer.add(
            f"[{display_name}] {translate('click_success', name=colored_step, confidence=f'{confidence:.1%}')}"
        )
        return True

    def _click_matcher(self, hwnd, matcher, center=None):
        was_foreground = ctypes.windll.user32.GetForegroundWindow() == hwnd
        bring_to_foreground(hwnd)
        if not was_foreground:
            time.sleep(3.0)
        origin = get_client_screen_origin(hwnd)
        c = center if center is not None else matcher.center
        click_at(origin[0] + c[0], origin[1] + c[1])

    def reload(self, task_cfg: dict, global_cfg: dict):
        self._task_cfg = task_cfg
        self._global_cfg = global_cfg
        self._matchers = []
        self._step_names = []
        self._step_scans = []
        self._step_actions = []
        self._start_trigger_matcher = None
        self._start_trigger_name = ""
        self._start_trigger_scan = False
        self._start_trigger_click = True
        self._is_key_sequence = False
        self._key_steps = []
        self.load()

    def read_timing(self):
        idle_interval = self._global_cfg.get("scan_ms", 2000) / 1000.0
        active_interval = self._task_cfg.get("scan_ms", 500) / 1000.0
        threshold = 0.95
        click_delay = 0.5
        step_timeout = self.step_timeout_ms / 1000.0
        return idle_interval, active_interval, threshold, click_delay, step_timeout

    @property
    def step_count(self):
        if self._is_key_sequence:
            return len(self._key_steps)
        return len(self._matchers)

    @property
    def has_start_trigger(self):
        return self._start_trigger_matcher is not None or self._is_key_sequence

    def execute_key_sequence(self, hwnd: int) -> None:
        display_name = translate(f"task.{self._task_name}")
        _log_buffer.add(f"[{display_name}] {C_BLUE}聚焦窗口...{C_RESET}")
        bring_to_foreground(hwnd)
        time.sleep(0.3)
        rect = _RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        center_x = (rect.left + rect.right) // 2
        center_y = (rect.top + rect.bottom) // 2
        click_at(center_x, center_y)
        time.sleep(0.5)
        for step in self._key_steps:
            time.sleep(step["delay"] / 1000.0)
            repeat = step.get("repeat", 1)
            key = step["key"]
            label = f"{key} x{repeat}" if repeat > 1 else key
            _log_buffer.add(f"[{display_name}] {C_YELLOW}按 {label}{C_RESET}")
            for _ in range(repeat):
                send_key(key)
        _log_buffer.add(f"[{display_name}] {C_GREEN}已完成{C_RESET}")


_STEAM_LANG_MAP = {
    "schinese": "zh_CN",
    "tchinese": "zh_TW",
    "english": "en_US",
}
_GTA5_APPID = "3240220"
_detected_lang_cache: str | None = None


def detect_game_language() -> str:
    global _detected_lang_cache
    if _detected_lang_cache is not None:
        return _detected_lang_cache

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            steam_path, _ = winreg.QueryValueEx(key, "SteamPath")

        vdf_path = os.path.join(steam_path, "steamapps", "libraryfolders.vdf")
        if not os.path.exists(vdf_path):
            manifest_path = os.path.join(
                steam_path, "steamapps", f"appmanifest_{_GTA5_APPID}.acf"
            )
            if os.path.exists(manifest_path):
                lang = _read_acf_language(manifest_path)
                if lang:
                    _detected_lang_cache = lang
                    return _detected_lang_cache
            _detected_lang_cache = "en_US"
            return _detected_lang_cache

        library_paths = _parse_library_folders(vdf_path)
        search_paths = [os.path.join(steam_path, "steamapps")] + [
            os.path.join(p, "steamapps") for p in library_paths
        ]

        for sp in search_paths:
            manifest_path = os.path.join(sp, f"appmanifest_{_GTA5_APPID}.acf")
            if os.path.exists(manifest_path):
                lang = _read_acf_language(manifest_path)
                if lang:
                    _detected_lang_cache = lang
                    return _detected_lang_cache

        _detected_lang_cache = "en_US"
        return _detected_lang_cache
    except Exception:
        _detected_lang_cache = "en_US"
        return _detected_lang_cache


def _parse_library_folders(vdf_path: str) -> list[str]:
    with open(vdf_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    paths = []
    for m in re.finditer(r'"path"\s+"(.+?)"', content):
        p = m.group(1).replace("\\\\", "\\")
        if os.path.isdir(p):
            paths.append(p)
    return paths


def _read_acf_language(acf_path: str) -> str | None:
    with open(acf_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    m = re.search(r'"language"\s+"(\w+)"', content)
    if not m:
        return None
    steam_lang = m.group(1)
    return _STEAM_LANG_MAP.get(steam_lang, "en_US")


def resolve_game_language(config_lang: str) -> str:
    if config_lang != "auto":
        return config_lang
    return detect_game_language()


def load_config() -> dict:
    try:
        if not os.path.exists(CONFIG_FILE):
            default_cfg = _build_default_config()
            save_config(default_cfg)
            return default_cfg
        mtime = os.path.getmtime(CONFIG_FILE)
        if mtime > _config_cache["mtime"]:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                _config_cache["data"] = json.load(f)
            _config_cache["mtime"] = mtime
    except Exception:
        pass
    return _config_cache["data"] or {}


def save_config(config: dict) -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        _config_cache["data"] = config
        _config_cache["mtime"] = os.path.getmtime(CONFIG_FILE)
    except Exception:
        pass


_SKIP_CONFIG_KEYS = frozenset({"lang", "scan_ms", "anti_afk"})


def _is_task_group(value):
    if not isinstance(value, dict) or not value:
        return False
    return all(isinstance(v, dict) for v in value.values())


def _flatten_task_configs(config):
    result = {}
    for key, value in config.items():
        if key in _SKIP_CONFIG_KEYS:
            continue
        if not isinstance(value, dict):
            continue
        if _is_task_group(value):
            for sub_key, sub_value in value.items():
                result[f"{key}_{sub_key}"] = sub_value if isinstance(sub_value, dict) else {}
        else:
            result[key] = value
    return result


def _get_task_config(config, task_name):
    for key, value in config.items():
        if key in _SKIP_CONFIG_KEYS:
            continue
        if not isinstance(value, dict):
            continue
        if key == task_name:
            if _is_task_group(value):
                continue
            return value
        if _is_task_group(value):
            prefix = f"{key}_"
            if task_name.startswith(prefix):
                sub_key = task_name[len(prefix):]
                if sub_key in value:
                    sub_value = value[sub_key]
                    return sub_value if isinstance(sub_value, dict) else {}
    return None


def _set_task_enabled(config, task_name, enabled):
    task_cfg = _get_task_config(config, task_name)
    if task_cfg is not None:
        task_cfg["enabled"] = enabled


def _load_task_module(task_name: str):
    task_py = os.path.join(BASE_DIR, "tasks", task_name, "task.py")
    if not os.path.exists(task_py):
        return None
    spec = importlib.util.spec_from_file_location(f"tasks.{task_name}", task_py)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    mod.__dict__.update(_INJECT_SYMBOLS)
    spec.loader.exec_module(mod)
    return mod


def _build_default_config() -> dict:
    config: dict = {"lang": "auto", "scan_ms": 2000}
    tasks_dir = os.path.join(BASE_DIR, "tasks")
    if not os.path.isdir(tasks_dir):
        return config

    for name in sorted(os.listdir(tasks_dir)):
        task_path = os.path.join(tasks_dir, name, "task.py")
        if not os.path.isfile(task_path):
            continue
        if name == "anti_afk":
            config["anti_afk"] = {"enabled": False, "interval_min": 10, "key": "enter"}
            continue
        mod = _load_task_module(name)
        if mod is None:
            continue
        task_cls = getattr(mod, "Task", None)
        if task_cls is None:
            continue
        group = getattr(task_cls, "group", None)
        if group:
            if group not in config:
                config[group] = {}
            sub_name = name[len(group) + 1:] if name.startswith(f"{group}_") else name
            config[group][sub_name] = {"enabled": False, "scan_ms": 500}
        else:
            config[name] = {"enabled": False, "scan_ms": 500}

    return config


class _LogBuffer:
    def __init__(self, max_lines: int = 200):
        self._lines: list[str] = []
        self._max_lines = max_lines
        self._lock = threading.Lock()
        self._trimmed = 0

    def add(self, msg: str) -> int:
        ts = time.strftime("%H:%M:%S")
        line = f"{C_GRAY}[{ts}]{C_RESET} {msg}"
        with self._lock:
            self._lines.append(line)
            if len(self._lines) > self._max_lines:
                self._lines.pop(0)
                self._trimmed += 1
            return self._trimmed + len(self._lines) - 1

    def replace_at(self, abs_index: int, msg: str) -> None:
        with self._lock:
            idx = abs_index - self._trimmed
            if 0 <= idx < len(self._lines):
                old = self._lines[idx]
                sep = f"]{C_RESET} "
                pos = old.find(sep)
                if pos >= 0:
                    self._lines[idx] = old[:pos + len(sep)] + msg

    def append_to_last(self, suffix: str) -> None:
        with self._lock:
            if self._lines:
                self._lines[-1] = self._lines[-1] + suffix

    def recent(self, n: int) -> list[str]:
        with self._lock:
            return self._lines[-n:] if n > 0 else []


_log_buffer = _LogBuffer()

_hack_display: dict = {}
_hack_display_lock = threading.Lock()

_process_cpu_state: dict = {
    "last_time": 0.0,
    "last_process_time": 0,
    "cpu_percent": 0.0,
    "last_sample_time": 0.0,
    "mem_mb": 0.0,
}

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


def _hack_display_update(**kwargs) -> None:
    with _hack_display_lock:
        _hack_display.update(kwargs)


def _hack_display_clear() -> None:
    with _hack_display_lock:
        _hack_display.clear()


def _sample_process_resources() -> None:
    now = time.time()
    state = _process_cpu_state
    if now - state["last_sample_time"] < 2.0:
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


def _get_game_status() -> str:
    pid = _find_pid_by_name(GAME_PROCESS_NAME)
    if pid is None:
        return "not_running"
    hwnd = find_game_window(GAME_PROCESS_NAME)
    if hwnd is None:
        return "no_window"
    return "connected"


_INJECT_SYMBOLS = {
    "BaseTask": BaseTask,
    "OverlayMatcher": OverlayMatcher,
    "capture_window": capture_window,
    "click_at": click_at,
    "send_key": send_key,
    "send_key_background": send_key_background,
    "bring_to_foreground": bring_to_foreground,
    "get_client_offset": get_client_offset,
    "get_client_screen_origin": get_client_screen_origin,
    "clip_cursor_to_window": clip_cursor_to_window,
    "unclip_cursor": unclip_cursor,
    "kill_game_process": kill_game_process,
    "find_game_window": find_game_window,
    "translate": translate,
    "load_config": load_config,
    "_log_buffer": _log_buffer,
    "_hack_display_update": _hack_display_update,
    "_hack_display_clear": _hack_display_clear,
    "resolve_game_language": resolve_game_language,
    "GAME_PROCESS_NAME": GAME_PROCESS_NAME,
    "BASE_DIR": BASE_DIR,
    "C_RED": C_RED, "C_GREEN": C_GREEN, "C_YELLOW": C_YELLOW,
    "C_RESET": C_RESET, "C_GRAY": C_GRAY, "C_BORDER": C_BORDER, "C_BLUE": C_BLUE,
}


class TaskRunner:
    def __init__(self, task_name: str, task_cfg: dict, global_cfg: dict):
        self._task_name = task_name
        self._task_cfg = task_cfg
        self._global_cfg = global_cfg
        self._running = False
        self._thread: threading.Thread | None = None
        self._task: BaseTask | None = None
        self._status = "stopped"
        self._last_confidence = 0.0
        self._current_step = 0
        self._sequence_started = False
        self._timeout_count = 0
        self._cycle_count = 0
        self._load_task()

    def _load_task(self) -> bool:
        mod = _load_task_module(self._task_name)
        if mod is None:
            _log_buffer.add(
                f"[{translate(f'task.{self._task_name}')}] {C_RED}"
                f"{translate('overlay_load_failed', overlay='task.py', error='not found')}{C_RESET}"
            )
            return False

        task_cls = getattr(mod, "Task", None)
        if task_cls is None:
            _log_buffer.add(
                f"[{translate(f'task.{self._task_name}')}] {C_RED}"
                f"{translate('overlay_load_failed', overlay='task.py', error='missing Task class')}{C_RESET}"
            )
            return False

        task = task_cls(self._task_name, self._task_cfg, self._global_cfg)
        if not task.load():
            return False

        self._task = task
        return True

    @property
    def status(self) -> str:
        return self._status

    @property
    def last_confidence(self) -> float:
        return self._last_confidence

    @property
    def current_step(self) -> int:
        return self._current_step

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def group(self) -> str | None:
        return self._task.group if self._task else None

    def start(self) -> None:
        if self._running:
            return
        if self._task is None:
            if not self._load_task():
                return
        self._running = True
        self._status = "running"
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._status = "stopped"
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._thread = None

    def reload(self, task_cfg: dict, global_cfg: dict) -> None:
        was_running = self._running
        self.stop()
        self._task_cfg = task_cfg
        self._global_cfg = global_cfg
        self._last_confidence = 0.0
        self._current_step = 0
        self._sequence_started = False
        self._timeout_count = 0
        if self._task:
            self._task.reload(task_cfg, global_cfg)
        if was_running:
            self.start()

    def _run(self) -> None:
        task_name = self._task_name
        display_name = translate(f"task.{task_name}")
        process_name = GAME_PROCESS_NAME
        step_index = 0
        step_start = time.time()
        last_config_mtime = _config_cache["mtime"]
        hwnd = None
        hwnd_check_time = 0.0
        idle_interval, active_interval, threshold, click_delay, step_timeout = self._task.read_timing()

        while self._running:
            if _config_cache["mtime"] > last_config_mtime:
                cfg = load_config()
                new_task_cfg = _get_task_config(cfg, self._task_name)
                if new_task_cfg is not None:
                    if self._task._task_cfg != new_task_cfg:
                        self._task.reload(new_task_cfg, cfg)
                        self._task_cfg = new_task_cfg
                        self._global_cfg = cfg
                        step_index = 0
                        step_start = time.time()
                        self._sequence_started = False
                        idle_interval, active_interval, threshold, click_delay, step_timeout = self._task.read_timing()
                        _log_buffer.add(f"{C_YELLOW}[{display_name}] {translate('config_reloaded')}{C_RESET}")
                    else:
                        self._task._task_cfg = new_task_cfg
                        self._task_cfg = new_task_cfg
                last_config_mtime = _config_cache["mtime"]

            now = time.time()
            if hwnd is None or now - hwnd_check_time > 3.0:
                hwnd = find_game_window(process_name)
                hwnd_check_time = now

            if hwnd is None:
                if self._task._is_key_sequence and not self._sequence_started:
                    _log_buffer.add(
                        f"[{display_name}] {C_RED}游戏窗口未找到，无法执行{C_RESET}"
                    )
                    cfg = load_config()
                    task_cfg = _get_task_config(cfg, self._task_name)
                    if task_cfg:
                        task_cfg["enabled"] = False
                        save_config(cfg)
                    self._running = False
                    self._status = "stopped"
                    continue
                if self._status != "paused":
                    self._status = "paused"
                time.sleep(2)
                continue

            if self._status != "running":
                self._status = "running"

            if not self._sequence_started and self._task._is_key_sequence:
                self._task.execute_key_sequence(hwnd)
                cfg = load_config()
                task_cfg = _get_task_config(cfg, self._task_name)
                if task_cfg:
                    task_cfg["enabled"] = False
                    save_config(cfg)
                self._running = False
                self._status = "stopped"
                continue

            if not self._sequence_started and self._task.has_start_trigger:
                image = capture_window(hwnd)
                if image is None:
                    time.sleep(idle_interval)
                    continue

                offset = get_client_offset(hwnd)
                found, confidence, scan_center = self._task.match_start_trigger(image, offset, threshold)
                self._last_confidence = confidence

                if found:
                    self._task.execute_start_trigger(hwnd, confidence, scan_center)
                    self._sequence_started = True
                    step_index = 0
                    step_start = time.time()
                    for _ in range(int(click_delay * 10)):
                        if not self._running:
                            break
                        time.sleep(0.1)
                else:
                    time.sleep(idle_interval)
                continue

            if step_index >= self._task.step_count:
                self._sequence_started = False
                step_index = 0
                self._cycle_count += 1
                time.sleep(idle_interval)
                continue

            image = capture_window(hwnd)
            if image is None:
                time.sleep(active_interval)
                continue

            offset = get_client_offset(hwnd)
            found, confidence, scan_center = self._task.match_step(step_index, image, offset, threshold)
            self._last_confidence = confidence
            self._current_step = step_index

            if found:
                success = self._task.execute_step(step_index, hwnd, confidence, scan_center)
                if success:
                    self._timeout_count = 0
                    step_index += 1
                    step_start = time.time()
                    for _ in range(int(click_delay * 10)):
                        if not self._running:
                            break
                        time.sleep(0.1)
                else:
                    self._timeout_count += 1
                    if self._timeout_count >= 3:
                        _log_buffer.add(
                            f"[{display_name}] {C_RED}{translate('step_timeout_reset')}{C_RESET}"
                        )
                        self._sequence_started = False
                        self._timeout_count = 0
                        step_index = 0
                    else:
                        _log_buffer.add(
                            f"[{display_name}] {C_YELLOW}{translate('step_timeout')}{C_RESET}"
                        )
                        step_index = 0
                    step_start = time.time()
            else:
                if step_index > 0 and time.time() - step_start > step_timeout:
                    self._timeout_count += 1

                    if self._timeout_count >= 3:
                        _log_buffer.add(
                            f"[{display_name}] {translate('step_timeout_reset')}"
                        )
                        self._sequence_started = False
                        self._timeout_count = 0
                        step_index = 0
                    else:
                        _log_buffer.add(
                            f"[{display_name}] {translate('step_timeout')}"
                        )
                        step_index = 0

                    step_start = time.time()

                time.sleep(active_interval)


def _visible_len(s: str) -> int:
    result = 0
    in_escape = False
    for ch in s:
        if ch == "\033":
            in_escape = True
            continue
        if in_escape:
            if ch.isalpha():
                in_escape = False
            continue
        char_width = unicodedata.east_asian_width(ch)
        if char_width in ("W", "F"):
            result += 2
        else:
            result += 1
    return result


def _pad_to_width(s: str, width: int) -> str:
    visible_len = _visible_len(s)
    if visible_len >= width:
        return s
    return s + " " * (width - visible_len)


def _rpad_to_width(s: str, width: int) -> str:
    visible_len = _visible_len(s)
    if visible_len >= width:
        return s
    return " " * (width - visible_len) + s


def _color_step(text: str) -> str:
    if "|" in text:
        action, detail = text.split("|", 1)
        return f"{action}{C_YELLOW}{detail}{C_RESET}"
    return f"{C_YELLOW}{text}{C_RESET}"


_selected_task_index = 0


def _build_task_panel(task_keys: list[str], runners: dict[str, TaskRunner], anti_afk_running: bool = False, game_status: str = "not_running") -> list[str]:
    border_color = f"{C_BORDER}"
    reset_color = C_RESET
    title = translate("app_title")
    PAD = 2

    group_last_child: dict[str, str] = {}
    for key in task_keys:
        if key == "anti_afk":
            continue
        runner = runners.get(key)
        group = runner.group if runner else None
        if group:
            group_last_child[group] = key

    seen_groups: set[str] = set()
    rows: list[tuple[str, bool, bool]] = []

    for idx, key in enumerate(task_keys):
        if key == "anti_afk":
            display_name = translate(f"task.{key}")
            is_running = anti_afk_running
            is_selected = idx == _selected_task_index
            checkbox = "🗹" if is_running else "☐"
            prefix = f"{' ' * PAD}{checkbox}  "
            rows.append((f"{prefix}{display_name}", is_selected, is_running))
            continue

        runner = runners.get(key)
        display_name = translate(f"task.{key}")
        is_running = runner is not None and runner.is_running
        is_selected = idx == _selected_task_index
        group = runner.group if runner else None

        if group and group not in seen_groups:
            seen_groups.add(group)
            group_name = translate(f"group.{group}")
            group_prefix = f"{' ' * PAD}   "
            rows.append((f"{group_prefix}{group_name}", False, False))

        if group:
            checkbox = "🗹" if is_running else "☐"
            child_prefix = f"{' ' * PAD}    {checkbox}  "
            rows.append((f"{child_prefix}{display_name}", is_selected, is_running))
        else:
            checkbox = "🗹" if is_running else "☐"
            prefix = f"{' ' * PAD}{checkbox}  "
            rows.append((f"{prefix}{display_name}", is_selected, is_running))

    max_content_w = max(_visible_len(r[0]) for r in rows) if rows else 0
    inner_w = max_content_w + PAD * 2 + 1
    title_min_width = len(title) + PAD * 2 + 2
    inner_w = max(inner_w, title_min_width)

    status_colors = {
        "connected": C_GREEN,
        "not_running": C_RED,
        "no_window": C_YELLOW,
    }
    sc = status_colors.get(game_status, C_RED)
    cpu_pct = _process_cpu_state["cpu_percent"]
    mem_mb = _process_cpu_state["mem_mb"]
    status_text = (
        f"{translate('status_cpu')} {cpu_pct:.1f}%"
        f"  {translate('status_memory')} {mem_mb:.1f}MB"
    )
    status_visible_w = _visible_len(status_text)
    inner_w = max(inner_w, status_visible_w + PAD * 2 + 2)

    lines: list[str] = []
    title_pad = inner_w - len(title) - 2
    left_dashes = min(3, title_pad // 2)
    right_dashes = title_pad - left_dashes
    lines.append(f"{border_color}{BORDER_TL}{BORDER_H * left_dashes} {sc}{title}{C_RESET}{border_color} {BORDER_H * right_dashes}{BORDER_TR}{reset_color}")

    lines.append(f"{border_color}{BORDER_V}{reset_color}{' ' * inner_w}{border_color}{BORDER_V}{reset_color}")

    for content, is_selected, is_running in rows:
        padded = _pad_to_width(content, inner_w)
        if is_selected:
            highlighted = padded.replace(C_RESET, C_RESET + C_HIGHLIGHT)
            lines.append(f"{border_color}{BORDER_V}{reset_color}{C_HIGHLIGHT}{highlighted}{reset_color}{border_color}{BORDER_V}{reset_color}")
        else:
            lines.append(f"{border_color}{BORDER_V}{reset_color}{padded}{border_color}{BORDER_V}{reset_color}")

    lines.append(f"{border_color}{BORDER_V}{reset_color}{' ' * inner_w}{border_color}{BORDER_V}{reset_color}")

    lines.append(f"{border_color}{BORDER_V}{BORDER_H * inner_w}{BORDER_V}{reset_color}")

    status_padded = " " + _rpad_to_width(status_text, inner_w - 2) + " "
    lines.append(f"{border_color}{BORDER_V}{reset_color}{status_padded}{border_color}{BORDER_V}{reset_color}")

    lines.append(f"{border_color}{BORDER_BL}{BORDER_H * inner_w}{BORDER_BR}{reset_color}")
    return lines


def _build_grid_panel() -> list[str]:
    with _hack_display_lock:
        state = dict(_hack_display)

    if not state:
        return []

    if "grid" not in state:
        return []

    grid = state["grid"]
    cursor_pos = state.get("cursor_pos", -1)
    target_pos = state.get("target_pos", -1)
    target_values = state.get("target_values", [])

    cursor_positions = set()
    if cursor_pos is not None and cursor_pos >= 0:
        for k in range(4):
            cursor_positions.add((cursor_pos + k) % 80)

    target_positions = set()
    if target_pos is not None and target_pos >= 0:
        for k in range(4):
            target_positions.add((target_pos + k) % 80)

    lines: list[str] = []
    for r in range(8):
        cells = []
        for c in range(10):
            idx = r * 10 + c
            val = f"{grid[idx]:02d}"
            if idx in target_positions and idx in cursor_positions:
                val = f"{C_GREEN}{C_UNDERLINE}{val}{C_RESET}"
            elif idx in target_positions:
                val = f"{C_GREEN}{val}{C_RESET}"
            elif idx in cursor_positions:
                val = f"{C_UNDERLINE}{val}{C_RESET}"
            cells.append(val)
        lines.append(" ".join(cells))

    if state.get("game_over"):
        display_name = translate(f"task.{state.get('task_name', '')}")
        footer = f"[{display_name}] {translate('hack_game_over')}"
        lines.append(footer)

    return lines


def main() -> None:
    global _selected_task_index
    config = load_config()
    config_lang = config.get("lang", "auto")
    game_lang = resolve_game_language(config_lang)
    i18n_init(game_lang, BASE_DIR)

    if os.name == "nt":
        os.system("")
    sys.stdout.write("\033[2J\033[?25l")
    sys.stdout.flush()

    runners: dict[str, TaskRunner] = {}
    last_render_lines: list[str] = []
    last_lang = game_lang
    game_status = "not_running"
    game_status_check_time = 0.0

    try:
        while True:
            config = load_config()
            current_lang = resolve_game_language(config.get("lang", "auto"))
            if current_lang != last_lang:
                i18n_init(current_lang, BASE_DIR)
                last_lang = current_lang

            task_cfgs = _flatten_task_configs(config)

            afk_cfg = config.get("anti_afk", {})
            afk_enabled = afk_cfg.get("enabled", False)
            afk_running = _anti_afk_task is not None and _anti_afk_task.is_running
            if afk_enabled and not afk_running:
                _start_anti_afk()
            elif not afk_enabled and afk_running:
                _stop_anti_afk()

            for key in list(runners.keys()):
                if key not in task_cfgs:
                    runners[key].stop()
                    del runners[key]

            for key, task_cfg in task_cfgs.items():
                if key not in runners:
                    runner = TaskRunner(key, task_cfg, config)
                    runners[key] = runner
                    if task_cfg.get("enabled", False):
                        runner.start()
                else:
                    runner = runners[key]
                    enabled = task_cfg.get("enabled", False)
                    if enabled and not runner.is_running:
                        runner.start()
                    elif not enabled and runner.is_running:
                        runner.stop()
                    if runner._task_cfg != task_cfg:
                        runner.reload(task_cfg, config)
                    else:
                        runner._task_cfg = task_cfg

            task_keys = list(task_cfgs.keys()) + ["anti_afk"]

            now = time.time()
            _sample_process_resources()
            if now - game_status_check_time > 3.0:
                game_status = _get_game_status()
                game_status_check_time = now

            term_h = shutil.get_terminal_size().lines
            term_w = shutil.get_terminal_size().columns

            task_lines = _build_task_panel(task_keys, runners, afk_running, game_status)
            task_panel_h = len(task_lines)

            grid_lines = _build_grid_panel()
            grid_panel_h = len(grid_lines)

            log_avail = term_h - task_panel_h - grid_panel_h
            entries = _log_buffer.recent(log_avail) if log_avail > 0 else []

            lines = task_lines[:]
            for entry in entries:
                lines.append(_truncate_visible(entry, term_w))
            lines.extend(grid_lines)

            for i, line in enumerate(lines[:term_h]):
                if i < len(last_render_lines) and last_render_lines[i] == line:
                    continue
                sys.stdout.write(f"\033[{i + 1};1H\033[2K{line}")

            for i in range(len(lines), len(last_render_lines)):
                if i < term_h:
                    sys.stdout.write(f"\033[{i + 1};1H\033[2K")

            sys.stdout.flush()
            last_render_lines = lines[:]

            if msvcrt.kbhit():
                key = msvcrt.getwch()
                if key == "\x00" or key == "\xe0":
                    arrow = msvcrt.getwch()
                    if arrow == "H":
                        _selected_task_index = max(0, _selected_task_index - 1)
                    elif arrow == "P":
                        _selected_task_index = max(0, min(len(task_keys) - 1, _selected_task_index + 1))
                elif key == "\r":
                    if task_keys and 0 <= _selected_task_index < len(task_keys):
                        task_key = task_keys[_selected_task_index]
                        if task_key == "anti_afk":
                            if _anti_afk_task and _anti_afk_task.is_running:
                                _stop_anti_afk()
                            else:
                                _start_anti_afk()
                            if "anti_afk" not in config:
                                config["anti_afk"] = {}
                            config["anti_afk"]["enabled"] = _anti_afk_task is not None and _anti_afk_task.is_running
                            save_config(config)
                        else:
                            runner = runners.get(task_key)
                            if runner:
                                if runner.is_running:
                                    runner.stop()
                                else:
                                    runner.start()
                                _set_task_enabled(config, task_key, runner.is_running)
                                save_config(config)

            time.sleep(0.15)

    finally:
        _stop_anti_afk()
        for runner in runners.values():
            runner.stop()
        sys.stdout.write("\033[r\033[m\033[?25h")
        sys.stdout.flush()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        sys.stdout.write("\033[r\033[m\033[?25h")
        sys.stdout.flush()
        print(f"\n{translate('fatal_error', error=e)}")
        import traceback
        traceback.print_exc()
        input(translate("press_enter_to_exit"))



