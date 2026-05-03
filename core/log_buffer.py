import time
import threading


class _LogBuffer:
    def __init__(self, max_lines: int = 200):
        self._lines: list[str] = []
        self._max_lines = max_lines
        self._lock = threading.Lock()
        self._trimmed = 0

    def add(self, msg: str) -> int:
        ts = time.strftime("%H:%M:%S")
        line = f"\033[90m[{ts}]\033[0m {msg}"
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
                sep = "]\033[0m "
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
