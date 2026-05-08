import time


class Task(BaseTask):
    group = None
    start_trigger = {"overlay": "trigger", "lang": "auto"}
    steps = []
    _clicked_pid: int | None = None

    def execute_start_trigger(self, hwnd, confidence, scan_center):
        current_pid = _find_pid_by_name(GAME_PROCESS_NAME)
        if current_pid is not None and current_pid == Task._clicked_pid:
            return
        focus_game_window(hwnd)
        origin = get_client_screen_origin(hwnd)
        c = scan_center if scan_center is not None else self._start_trigger_matcher.center
        move_cursor_to(origin[0] + c[0], origin[1] + c[1])
        time.sleep(0.3)
        send_key("enter")
        Task._clicked_pid = current_pid
        display_name = translate(f"task.{self._task_name}")
        step_key = f"step.{self._start_trigger_name}.{self._task_name}"
        step_display = translate(step_key)
        if step_display == step_key:
            step_display = self._start_trigger_name
        _log_buffer.add(
            f"[{display_name}] {step_display}"
        )
