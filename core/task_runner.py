import time
import threading

from . import windows_api as _win
from . import config as _cfg
from . import task_base as _task_base
from . import i18n as _i18n
from . import log_buffer as _log_mod


class TaskRunner:
    def __init__(self, task_name: str, task_cfg: dict, global_cfg: dict):
        self._task_name = task_name
        self._task_cfg = task_cfg
        self._global_cfg = global_cfg
        self._running = False
        self._thread: threading.Thread | None = None
        self._task: _task_base.BaseTask | None = None
        self._status = "stopped"
        self._last_confidence = 0.0
        self._current_step = 0
        self._sequence_started = False
        self._timeout_count = 0
        self._cycle_count = 0
        self._run_once_checked = False
        self._load_task()

    def _load_task(self) -> bool:
        mod = _cfg._load_task_module(self._task_name)
        if mod is None:
            _log_mod._log_buffer.add(
                f"[{_i18n.translate(f'task.{self._task_name}')}] "
                f"\033[38;2;243;139;168m"
                f"{_i18n.translate('overlay_load_failed', overlay='task.py', error='not found')}\033[0m"
            )
            return False

        task_cls = getattr(mod, "Task", None)
        if task_cls is None:
            _log_mod._log_buffer.add(
                f"[{_i18n.translate(f'task.{self._task_name}')}] "
                f"\033[38;2;243;139;168m"
                f"{_i18n.translate('overlay_load_failed', overlay='task.py', error='missing Task class')}\033[0m"
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
        self._run_once_checked = False
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

    def _disable_and_stop_in_config(self):
        cfg = _cfg.load_config()
        task_cfg = _cfg._get_task_config(cfg, self._task_name)
        if task_cfg:
            task_cfg["enabled"] = False
            _cfg.save_config(cfg)
        self._running = False
        self._status = "stopped"

    def reload(self, task_cfg: dict, global_cfg: dict) -> None:
        was_running = self._running
        self.stop()
        self._task_cfg = task_cfg
        self._global_cfg = global_cfg
        self._last_confidence = 0.0
        self._current_step = 0
        self._sequence_started = False
        self._timeout_count = 0
        self._run_once_checked = False
        if self._task:
            self._task.reload(task_cfg, global_cfg)
        if was_running:
            self.start()

    def _run(self) -> None:
        task_name = self._task_name
        display_name = _i18n.translate(f"task.{task_name}")
        process_name = _win.GAME_PROCESS_NAME
        step_index = 0
        step_start = time.time()
        last_config_mtime = _cfg._config_cache["mtime"]
        hwnd = None
        hwnd_check_time = 0.0
        idle_interval, active_interval, threshold, click_delay, step_timeout = self._task.read_timing()

        while self._running:
            if _cfg._config_cache["mtime"] > last_config_mtime:
                cfg = _cfg.load_config()
                new_task_cfg = _cfg._get_task_config(cfg, self._task_name)
                if new_task_cfg is not None:
                    if self._task._task_cfg != new_task_cfg:
                        self._task.reload(new_task_cfg, cfg)
                        self._task_cfg = new_task_cfg
                        self._global_cfg = cfg
                        step_index = 0
                        step_start = time.time()
                        self._sequence_started = False
                        idle_interval, active_interval, threshold, click_delay, step_timeout = self._task.read_timing()
                        _log_mod._log_buffer.add(
                            f"\033[38;2;249;226;175m[{display_name}] {_i18n.translate('config_reloaded')}\033[0m"
                        )
                    else:
                        self._task._task_cfg = new_task_cfg
                        self._task_cfg = new_task_cfg
                last_config_mtime = _cfg._config_cache["mtime"]

            now = time.time()
            if hwnd is None or now - hwnd_check_time > 3.0:
                hwnd = _win.find_game_window(process_name)
                hwnd_check_time = now

            if hwnd is None:
                if self._task._is_key_sequence and not self._sequence_started:
                    _log_mod._log_buffer.add(
                        f"[{display_name}] \033[38;2;243;139;168m{_i18n.translate('game_window_not_found')}\033[0m"
                    )
                    cfg = _cfg.load_config()
                    task_cfg = _cfg._get_task_config(cfg, self._task_name)
                    if task_cfg:
                        task_cfg["enabled"] = False
                        _cfg.save_config(cfg)
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
                cfg = _cfg.load_config()
                task_cfg = _cfg._get_task_config(cfg, self._task_name)
                if task_cfg:
                    task_cfg["enabled"] = False
                    _cfg.save_config(cfg)
                self._running = False
                self._status = "stopped"
                continue

            if not self._sequence_started and self._task.has_start_trigger:
                image = _win.capture_window(hwnd)
                if image is None:
                    time.sleep(idle_interval)
                    continue

                offset = _win.get_client_offset(hwnd)
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
                    if self._task.run_once and not self._run_once_checked:
                        self._run_once_checked = True
                        _log_mod._log_buffer.add(
                            f"[{display_name}] \033[38;2;243;139;168m{_i18n.translate('trigger_not_found')}\033[0m"
                        )
                        self._disable_and_stop_in_config()
                        continue
                    time.sleep(idle_interval)
                continue

            if step_index >= self._task.step_count:
                if self._task.run_once:
                    self._disable_and_stop_in_config()
                    continue
                self._sequence_started = False
                step_index = 0
                self._cycle_count += 1
                time.sleep(idle_interval)
                continue

            image = _win.capture_window(hwnd)
            if image is None:
                time.sleep(active_interval)
                continue

            offset = _win.get_client_offset(hwnd)
            found, confidence, scan_center = self._task.match_step(step_index, image, offset, threshold)
            self._last_confidence = confidence
            self._current_step = step_index

            if found:
                success = self._task.execute_step(step_index, hwnd, confidence, scan_center)
                if self._task.run_once:
                    self._disable_and_stop_in_config()
                    continue
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
                        _log_mod._log_buffer.add(
                            f"[{display_name}] \033[38;2;243;139;168m{_i18n.translate('step_timeout_reset')}\033[0m"
                        )
                        self._sequence_started = False
                        self._timeout_count = 0
                        step_index = 0
                    else:
                        _log_mod._log_buffer.add(
                            f"[{display_name}] \033[38;2;249;226;175m{_i18n.translate('step_timeout')}\033[0m"
                        )
                        step_index = 0
                    step_start = time.time()
            else:
                if step_index > 0 and time.time() - step_start > step_timeout:
                    self._timeout_count += 1

                    if self._timeout_count >= 3:
                        _log_mod._log_buffer.add(
                            f"[{display_name}] {_i18n.translate('step_timeout_reset')}"
                        )
                        self._sequence_started = False
                        self._timeout_count = 0
                        step_index = 0
                    else:
                        _log_mod._log_buffer.add(
                            f"[{display_name}] {_i18n.translate('step_timeout')}"
                        )
                        step_index = 0

                    step_start = time.time()

                time.sleep(active_interval)
