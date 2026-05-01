import time
import ctypes
import threading


class Task(BaseTask):
    group = None
    start_trigger = {}
    steps = []

    def __init__(self, task_name, task_cfg, global_cfg):
        super().__init__(task_name, task_cfg, global_cfg)
        self._running = False
        self._thread = None
        self._bg_start = None

    def load(self):
        return True

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None

    @property
    def is_running(self):
        return self._running

    def _loop(self):
        while self._running:
            config = load_config()
            afk_cfg = config.get("anti_afk", {})
            interval = afk_cfg.get("interval_min", 10) * 60.0
            key = afk_cfg.get("key", "enter")

            hwnd = find_game_window()
            if hwnd:
                fg = ctypes.windll.user32.GetForegroundWindow()
                if fg != hwnd:
                    if self._bg_start is None:
                        self._bg_start = time.time()
                    elif time.time() - self._bg_start >= interval:
                        focus_game_window(hwnd)
                        send_key(key)
                        display_name = translate(f"task.{self._task_name}")
                        colored_key = f"{C_YELLOW}[{key.upper()}]{C_RESET}"
                        _log_buffer.add(
                            f"[{display_name}] {translate('anti_afk_sent', key_name=colored_key)}"
                        )
                        self._bg_start = None
                else:
                    self._bg_start = None

            time.sleep(1.0)
