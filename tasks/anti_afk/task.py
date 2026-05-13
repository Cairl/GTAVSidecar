import time
import ctypes


class Task(BaseTask):
    group = None
    start_trigger = {}
    steps = []
    run_once = False
    default_config = {"enabled": False, "interval_min": 10, "key": "enter"}
    always_active = True

    def __init__(self, task_name, task_cfg, global_cfg):
        super().__init__(task_name, task_cfg, global_cfg)
        self._bg_start = None
        self._last_hwnd = None

    def load(self):
        return True

    def execute_step(self, step_index, hwnd, confidence, scan_center):
        if hwnd != self._last_hwnd:
            self._bg_start = None
            self._last_hwnd = hwnd

        if hwnd is None:
            self._bg_start = None
            return True

        config = load_config()
        afk_cfg = config.get("anti_afk", {})
        interval = afk_cfg.get("interval_min", 10) * 60.0
        key = afk_cfg.get("key", "enter")

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

        return True

    def read_timing(self):
        idle_interval = 1.0
        active_interval = 1.0
        threshold = 0.95
        click_delay = 0.0
        step_timeout = 30.0
        return idle_interval, active_interval, threshold, click_delay, step_timeout
