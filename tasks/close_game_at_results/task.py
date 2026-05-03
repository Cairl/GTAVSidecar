import time


class Task(BaseTask):
    group = None
    start_trigger = {"overlay": "trigger", "lang": "global", "scan": "horizontal", "click": False}
    steps = []
    default_config = {"wait_ms": 2000}

    def execute_start_trigger(self, hwnd, confidence, scan_center):
        kill_delay_ms = self._task_cfg.get("wait_ms", 2000)
        kill_delay_s = kill_delay_ms / 1000.0
        display_name = translate(f"task.{self._task_name}")
        step_key = f"step.{self._start_trigger_name}.{self._task_name}"
        step_display = translate(step_key)
        if step_display == step_key:
            step_display = self._start_trigger_name
        _log_buffer.add(
            f"[{display_name}] {translate('detected', name=f'{C_YELLOW}{step_display}{C_RESET}', confidence=f'{confidence:.1%}')}"
        )
        time.sleep(kill_delay_s)
        success = kill_game_process(GAME_PROCESS_NAME)
        if success:
            _log_buffer.add(
                f"[{display_name}] {translate('process_killed', confidence=f'{confidence:.1%}')}"
            )
        else:
            _log_buffer.add(
                f"[{display_name}] {C_RED}{translate('process_kill_failed')}{C_RESET}"
            )
