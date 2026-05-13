import os
import time

import cv2
import numpy as np


class Task(BaseTask):
    group = "hack_solver"
    start_trigger = {"overlay": "trigger", "lang": "global", "click": False}
    steps = [{"overlay": "hack", "lang": "auto", "action": "hack"}]
    step_timeout_ms = 60000
    run_once = False
    default_config = {"scan_ms": 50}

    def __init__(self, task_name, task_cfg, global_cfg):
        super().__init__(task_name, task_cfg, global_cfg)
        self._solver = None

    def load(self):
        if not super().load():
            return False
        scan_ms = self._task_cfg.get("scan_ms", 50)
        solver = BruteForceSolver(self._task_name, self._global_cfg, scan_ms)
        solver.set_trigger_matcher(self._start_trigger_matcher)
        if not solver.load():
            return False
        self._solver = solver
        return True

    def execute_start_trigger(self, hwnd, confidence, scan_center):
        pass

    def execute_step(self, step_index, hwnd, confidence, scan_center):
        action = self._step_actions[step_index]
        if action == "hack":
            return self._solver.run(hwnd)
        return super().execute_step(step_index, hwnd, confidence, scan_center)


class BruteForceSolver:
    NUM_CELLS = 8
    MAX_ATTEMPTS = 10
    RED_THRESHOLD = 80
    RED_RATIO_THRESHOLD = 0.02
    CELL_MARGIN = 5
    VLINE_BRIGHT_THRESHOLD = 100
    VLINE_RATIO_THRESHOLD = 0.05

    def __init__(self, task_name, global_cfg, scan_ms=50):
        self._task_name = task_name
        self._global_cfg = global_cfg
        self._scan_interval = scan_ms / 1000.0
        self._trigger_matcher = None
        self._cell_rects = []
        self._completed = 0
        self._progress_line_idx = None

    def set_trigger_matcher(self, matcher):
        self._trigger_matcher = matcher

    def load(self):
        self._cell_rects = []
        for i in range(1, self.NUM_CELLS + 1):
            path = os.path.join(BASE_DIR, "tasks", self._task_name, "global", f"{i}.png")
            if not os.path.exists(path):
                _log_buffer.add(
                    f"[{translate('task.' + self._task_name)}] {C_RED}"
                    f"{translate('overlay_load_failed', overlay=f'{i}.png', error='not found')}{C_RESET}"
                )
                return False
            try:
                matcher = OverlayMatcher(path, 128)
                x, y, w, h = matcher.bbox
                self._cell_rects.append((x, y, w, h))
            except (FileNotFoundError, ValueError) as e:
                _log_buffer.add(
                    f"[{translate('task.' + self._task_name)}] {C_RED}"
                    f"{translate('overlay_load_failed', overlay=f'{i}.png', error=e)}{C_RESET}"
                )
                return False
        return True

    def _has_red_in_cell(self, image, cell_index, offset):
        x, y, w, h = self._cell_rects[cell_index]
        x += offset[0]
        y += offset[1]
        margin = self.CELL_MARGIN
        ry = y + margin
        rx = x + margin
        rh = h - margin * 2
        rw = w - margin * 2
        if ry < 0 or rx < 0 or ry + rh > image.shape[0] or rx + rw > image.shape[1]:
            return False
        interior = image[ry:ry + rh, rx:rx + rw]
        if interior.size == 0:
            return False
        r_ch = interior[:, :, 2].astype(np.float32)
        g_ch = interior[:, :, 1].astype(np.float32)
        red_mask = (r_ch > self.RED_THRESHOLD) & (r_ch > g_ch * 2)
        red_ratio = red_mask.sum() / red_mask.size
        return red_ratio > self.RED_RATIO_THRESHOLD

    def _is_cell_active(self, image, cell_index, offset):
        x, y, w, h = self._cell_rects[cell_index]
        x += offset[0]
        y += offset[1]
        left_x = x + 2
        right_x = x + w - 3
        if left_x < 0 or right_x + 1 > image.shape[1] or y < 0 or y + h > image.shape[0]:
            return False
        left_strip = image[y:y + h, left_x:left_x + 1]
        right_strip = image[y:y + h, right_x:right_x + 1]
        if left_strip.size == 0 or right_strip.size == 0:
            return False
        left_bright = np.max(left_strip, axis=2).astype(np.float32)
        right_bright = np.max(right_strip, axis=2).astype(np.float32)
        left_active = (left_bright > self.VLINE_BRIGHT_THRESHOLD).sum() / left_bright.size
        right_active = (right_bright > self.VLINE_BRIGHT_THRESHOLD).sum() / right_bright.size
        return left_active > self.VLINE_RATIO_THRESHOLD and right_active > self.VLINE_RATIO_THRESHOLD

    def _find_active_cell(self, image, offset):
        for i in range(self.NUM_CELLS):
            if self._is_cell_active(image, i, offset):
                return i
        return None

    def _update_progress(self, display_name):
        msg = translate('hack.' + self._task_name + '.progress', current=self._completed, total=self.NUM_CELLS)
        if self._progress_line_idx is not None:
            _log_buffer.replace_at(self._progress_line_idx, f"[{display_name}] {msg}")
        else:
            self._progress_line_idx = _log_buffer.add(f"[{display_name}] {msg}")

    def _attempt_hack(self, hwnd, display_name):
        image = capture_window(hwnd)
        if image is None:
            _log_buffer.add(f"[{display_name}] {C_RED}{translate('hack.' + self._task_name + '.capture_failed')}{C_RESET}")
            return "capture_failed"

        offset = get_client_offset(hwnd)

        active_cell = self._find_active_cell(image, offset)

        if active_cell is None:
            if self._trigger_matcher is not None:
                found, _ = self._trigger_matcher.match_from_image(image, 0.95, offset)
                if not found:
                    return True
            return None

        if self._has_red_in_cell(image, active_cell, offset):
            send_key("enter")
            self._completed += 1
            self._update_progress(display_name)
            time.sleep(0.2)
            return None

        return None

    def run(self, hwnd):
        display_name = translate("task." + self._task_name)

        self._completed = 0
        self._progress_line_idx = None

        focus_game_window(hwnd)
        clip_cursor_to_window(hwnd)

        try:
            _log_buffer.add(f"[{display_name}] {C_YELLOW}{translate('hack.' + self._task_name + '.game_start')}{C_RESET}")

            capture_fails = 0
            while True:
                result = self._attempt_hack(hwnd, display_name)
                if result == "capture_failed":
                    capture_fails += 1
                    if capture_fails >= self.MAX_ATTEMPTS:
                        return False
                    time.sleep(self._scan_interval)
                    continue
                capture_fails = 0
                if result is True:
                    _log_buffer.add(f"[{display_name}] {C_GREEN}{translate('hack.' + self._task_name + '.game_over')}{C_RESET}")
                    return True
                time.sleep(self._scan_interval)
        finally:
            unclip_cursor()
