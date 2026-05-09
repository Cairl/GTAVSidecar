import threading
import time
from typing import Callable

from . import windows_api as _win
from . import log_buffer as _log_mod
from . import i18n as _i18n

_POLL_INTERVAL_NOT_RUNNING = 5.0
_POLL_INTERVAL_DETECTING = 1.0
_POLL_INTERVAL_RUNNING = 3.0


class GameLifecycleManager:
    STATE_NOT_RUNNING = "not_running"
    STATE_DETECTING = "detecting"
    STATE_RUNNING = "running"

    def __init__(self, process_name: str):
        self._process_name = process_name
        self._state = self.STATE_NOT_RUNNING
        self._hwnd: int | None = None
        self._pid: int | None = None
        self._listeners: list[Callable[[str, int | None], None]] = []
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running = False
        self._state_event = threading.Event()
        self._target_state: str | None = None

    def add_listener(self, callback: Callable[[str, int | None], None]) -> None:
        with self._lock:
            self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[str, int | None], None]) -> None:
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def _notify_listeners(self, state: str, hwnd: int | None) -> None:
        with self._lock:
            listeners = self._listeners.copy()
        for cb in listeners:
            try:
                cb(state, hwnd)
            except Exception:
                pass

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._state_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._thread = None

    def wait_for_state(self, state: str, timeout: float | None = None) -> bool:
        if self._state == state:
            return True
        self._target_state = state
        self._state_event.clear()
        return self._state_event.wait(timeout=timeout)

    def _set_state(self, state: str, hwnd: int | None = None, pid: int | None = None) -> None:
        changed = False
        with self._lock:
            if self._state != state:
                self._state = state
                changed = True
            self._hwnd = hwnd
            if pid is not None:
                self._pid = pid

        if changed:
            self._notify_listeners(state, hwnd)
            if self._target_state == state:
                self._state_event.set()

    def _loop(self) -> None:
        while self._running:
            pid = _win._find_pid_by_name(self._process_name)

            if pid is None:
                if self._state != self.STATE_NOT_RUNNING:
                    self._set_state(self.STATE_NOT_RUNNING, None, None)
                time.sleep(_POLL_INTERVAL_NOT_RUNNING)
                continue

            if self._state == self.STATE_NOT_RUNNING:
                self._set_state(self.STATE_DETECTING, None, pid)
                time.sleep(_POLL_INTERVAL_DETECTING)
                continue

            hwnd = _win.find_game_window(self._process_name)

            if hwnd is None:
                if self._state == self.STATE_RUNNING:
                    self._set_state(self.STATE_DETECTING, None, pid)
                time.sleep(_POLL_INTERVAL_DETECTING)
                continue

            if self._state != self.STATE_RUNNING:
                self._set_state(self.STATE_RUNNING, hwnd, pid)
            else:
                with self._lock:
                    self._hwnd = hwnd

            time.sleep(_POLL_INTERVAL_RUNNING)

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def hwnd(self) -> int | None:
        with self._lock:
            return self._hwnd

    @property
    def pid(self) -> int | None:
        with self._lock:
            return self._pid
