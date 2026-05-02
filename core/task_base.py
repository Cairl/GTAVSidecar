import os
import time

import cv2
import numpy as np

from . import windows_api as _win
from . import config as _cfg
from . import i18n as _i18n
from . import log_buffer as _log_mod


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
            raise FileNotFoundError(_i18n.translate("overlay_load_error", path=self._overlay_path))
        if overlay.ndim != 3 or overlay.shape[2] != 4:
            raise ValueError(_i18n.translate("overlay_format_error"))

        alpha = overlay[:, :, 3]
        binary = (alpha > self._alpha_threshold).astype(np.uint8) * 255

        coords = cv2.findNonZero(binary)
        if coords is None:
            raise ValueError(_i18n.translate("overlay_empty_error"))

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
    run_once: bool = False

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
        base = os.path.join(_cfg.BASE_DIR, "tasks", self._task_name)
        game_lang = _cfg.resolve_game_language(self._global_cfg.get("lang", "auto"))

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
            _log_mod._log_buffer.add(
                f"[{_i18n.translate(f'task.{self._task_name}')}] "
                f"\033[38;2;243;139;168m{_i18n.translate('overlay_load_failed', overlay=overlay, error=e)}\033[0m"
            )
            return None

    def load(self) -> bool:
        alpha_threshold = 128

        start_trigger_cfg = self.start_trigger
        steps = self.steps

        if not start_trigger_cfg and not steps:
            self._is_key_sequence = False
            self._key_steps = []
            self._matchers = []
            self._step_names = []
            self._step_scans = []
            self._step_actions = []
            return True

        if not start_trigger_cfg and steps and all("delay" in s for s in steps):
            self._is_key_sequence = True
            self._key_steps = steps
            self._matchers = []
            self._step_names = []
            self._step_scans = []
            self._step_actions = []
            return True

        if not start_trigger_cfg or steps is None:
            _log_mod._log_buffer.add(
                f"[{_i18n.translate(f'task.{self._task_name}')}] "
                f"\033[38;2;243;139;168m"
                f"{_i18n.translate('overlay_load_failed', overlay='task.py', error='missing start_trigger or steps')}\033[0m"
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
        display_name = _i18n.translate(f"task.{self._task_name}")
        step_key = f"step.{self._start_trigger_name}.{self._task_name}"
        step_display = _i18n.translate(step_key)
        if step_display == step_key:
            step_display = self._start_trigger_name
        if self._start_trigger_click:
            self._click_matcher(hwnd, self._start_trigger_matcher, scan_center)
            _log_mod._log_buffer.add(
                f"[{display_name}] {_i18n.translate('start_trigger_detected', name=f'\033[38;2;249;226;175m{step_display}\033[0m', confidence=f'{confidence:.1%}')}"
            )
        else:
            _log_mod._log_buffer.add(
                f"[{display_name}] {_i18n.translate('detected', name=f'\033[38;2;249;226;175m{step_display}\033[0m')}"
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
        display_name = _i18n.translate(f"task.{self._task_name}")
        step_name = self._step_names[step_index]
        action = self._step_actions[step_index]

        step_key = f"step.{step_name}.{self._task_name}"
        step_display = _i18n.translate(step_key)
        if step_display == step_key:
            step_display = step_name

        if action == "kill_process":
            killed = _win.kill_game_process(_win.GAME_PROCESS_NAME)
            if killed:
                msg = _i18n.translate('process_killed')
                _log_mod._log_buffer.add(f"[{display_name}] {_color_step(msg)} ({confidence:.1%})")
            else:
                _log_mod._log_buffer.add(
                    f"[{display_name}] \033[38;2;243;139;168m{_i18n.translate('process_kill_failed')}\033[0m"
                )
            return True

        matcher = self._matchers[step_index]
        self._click_matcher(hwnd, matcher, scan_center)
        colored_step = _color_step(step_display)
        _log_mod._log_buffer.add(
            f"[{display_name}] {_i18n.translate('click_success', name=colored_step, confidence=f'{confidence:.1%}')}"
        )
        return True

    def _click_matcher(self, hwnd, matcher, center=None):
        _win.focus_game_window(hwnd)
        origin = _win.get_client_screen_origin(hwnd)
        c = center if center is not None else matcher.center
        _win.click_at(origin[0] + c[0], origin[1] + c[1])

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
        display_name = _i18n.translate(f"task.{self._task_name}")

        start_key = f"sequence_starting.{self._task_name}"
        start_msg = _i18n.translate(start_key)
        if start_msg == start_key:
            start_msg = _i18n.translate("sequence_starting")

        done_key = f"sequence_done.{self._task_name}"
        done_msg = _i18n.translate(done_key)
        if done_msg == done_key:
            done_msg = _i18n.translate("sequence_done")

        _log_mod._log_buffer.add(
            f"[{display_name}] \033[38;2;249;226;175m{start_msg}\033[0m"
        )
        _win.focus_game_window(hwnd)
        for step in self._key_steps:
            time.sleep(step["delay"] / 1000.0)
            repeat = step.get("repeat", 1)
            key = step["key"]
            for _ in range(repeat):
                _win.send_key(key)
        _log_mod._log_buffer.add(
            f"[{display_name}] \033[38;2;166;227;161m{done_msg}\033[0m"
        )


def _color_step(text: str) -> str:
    if "|" in text:
        action, detail = text.split("|", 1)
        return f"{action}\033[38;2;249;226;175m{detail}\033[0m"
    return f"\033[38;2;249;226;175m{text}\033[0m"
