import os
import re
import time
import threading


_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


class _LogBuffer:
    def __init__(self, max_lines: int = 200):
        self._lines: list[str] = []
        self._max_lines = max_lines
        self._lock = threading.Lock()
        self._trimmed = 0
        self._log_dir: str | None = None
        self._log_path: str | None = None
        self._max_log_files = 5

    def set_log_dir(self, log_dir: str) -> None:
        self._log_dir = log_dir

    def _ensure_log_file(self) -> None:
        if self._log_path is not None:
            return
        if self._log_dir is None:
            return
        os.makedirs(self._log_dir, exist_ok=True)
        ts = time.strftime("%Y-%m-%d_%H-%M-%S")
        self._log_path = os.path.join(self._log_dir, f"session_{ts}.log")
        self._rotate_logs()

    def _rotate_logs(self) -> None:
        if self._log_dir is None:
            return
        try:
            files = sorted(
                [f for f in os.listdir(self._log_dir) if f.endswith(".log")],
                reverse=True,
            )
            for old in files[self._max_log_files - 1:]:
                os.remove(os.path.join(self._log_dir, old))
        except OSError:
            pass

    def add(self, msg: str) -> int:
        ts = time.strftime("%H:%M:%S")
        line = f"\033[90m[{ts}]\033[0m {msg}"
        with self._lock:
            self._lines.append(line)
            if len(self._lines) > self._max_lines:
                self._lines.pop(0)
                self._trimmed += 1
            idx = self._trimmed + len(self._lines) - 1

        self._ensure_log_file()
        if self._log_path is not None:
            try:
                plain = _strip_ansi(f"[{ts}] {msg}")
                with open(self._log_path, "a", encoding="utf-8") as f:
                    f.write(plain + "\n")
            except OSError:
                pass

        return idx

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
