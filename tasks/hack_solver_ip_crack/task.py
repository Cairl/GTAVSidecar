import os
import json
import time
from collections import deque

import cv2
import numpy as np


class Task(BaseTask):
    group = "hack_solver"
    start_trigger = {"overlay": "trigger", "lang": "global", "click": False}
    steps = [{"overlay": "hack", "lang": "auto", "action": "hack"}]
    step_timeout_ms = 60000

    def __init__(self, task_name, task_cfg, global_cfg):
        super().__init__(task_name, task_cfg, global_cfg)
        self._hacking_solver = None

    def load(self):
        if not super().load():
            return False
        auto_enter = self._task_cfg.get("auto_enter", True)
        scan_ms = self._task_cfg.get("scan_ms", 500)
        solver = HackingSolver(self._task_name, self._global_cfg, auto_enter, scan_ms)
        solver.set_trigger_matcher(self._start_trigger_matcher)
        if not solver.load():
            return False
        self._hacking_solver = solver
        return True

    def execute_step(self, step_index, hwnd, confidence, scan_center):
        action = self._step_actions[step_index]
        if action == "hack":
            return self._hacking_solver.run(hwnd)
        return super().execute_step(step_index, hwnd, confidence, scan_center)


class HackingSolver:
    GRID_ROWS = 8
    GRID_COLS = 10
    CURSOR_LEN = 4
    MAX_STEPS = 25
    TOTAL_CELLS = GRID_ROWS * GRID_COLS
    MAX_ATTEMPTS = 5

    def __init__(self, task_name, global_cfg, auto_enter=True, scan_ms=500):
        self._task_name = task_name
        self._global_cfg = global_cfg
        self._auto_enter = auto_enter
        self._scan_interval = scan_ms / 1000.0
        self._digit_templates = []
        self._grid_cfg = {}
        self._ip_cfg = {}
        self._trigger_matcher = None
        self._fail_matcher = None

    def set_trigger_matcher(self, matcher):
        self._trigger_matcher = matcher

    def _move(self, pos, key):
        row, col = divmod(pos, self.GRID_COLS)
        if key == "w":
            row = (row - 1) % self.GRID_ROWS
        elif key == "s":
            row = (row + 1) % self.GRID_ROWS
        elif key == "d":
            if col == self.GRID_COLS - 1:
                col = 0
                row = (row + 1) % self.GRID_ROWS
            else:
                col += 1
        elif key == "a":
            if col == 0:
                col = self.GRID_COLS - 1
                row = (row - 1) % self.GRID_ROWS
            else:
                col -= 1
        return row * self.GRID_COLS + col

    def _resolve_path(self, lang, filename):
        base = os.path.join(BASE_DIR, "tasks", self._task_name)
        game_lang = resolve_game_language(self._global_cfg.get("lang", "auto"))
        if lang == "auto":
            lang = game_lang
        return os.path.join(base, lang, filename)

    def load(self):
        game_lang = resolve_game_language(self._global_cfg.get("lang", "auto"))
        lang_dir = os.path.join(BASE_DIR, "tasks", self._task_name, game_lang)
        if not os.path.isdir(lang_dir):
            for fallback in ("global", "en_US"):
                fb = os.path.join(BASE_DIR, "tasks", self._task_name, fallback)
                if os.path.isdir(fb):
                    lang_dir = fb
                    break

        grid_json = os.path.join(lang_dir, "grid.json")
        if not os.path.exists(grid_json):
            _log_buffer.add(
                f"[{translate('task.' + self._task_name)}] {C_RED}"
                f"{translate('overlay_load_failed', overlay='grid.json', error='not found')}{C_RESET}"
            )
            return False

        with open(grid_json, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        self._grid_cfg = cfg["grid"]
        self._ip_cfg = cfg["target_ip"]

        alpha_threshold = 128
        self._digit_templates = []
        for d in range(10):
            path = os.path.join(lang_dir, f"{d}.png")
            if not os.path.exists(path):
                _log_buffer.add(
                    f"[{translate('task.' + self._task_name)}] {C_RED}"
                    f"{translate('overlay_load_failed', overlay=f'{d}.png', error='not found')}{C_RESET}"
                )
                return False
            try:
                raw = np.fromfile(path, dtype=np.uint8)
                digit_image = cv2.imdecode(raw, cv2.IMREAD_UNCHANGED)
                if digit_image is None or digit_image.ndim != 3 or digit_image.shape[2] != 4:
                    raise ValueError("invalid image")
                alpha = digit_image[:, :, 3]
                mask = (alpha > alpha_threshold).astype(np.uint8) * 255
                coords = cv2.findNonZero(mask)
                if coords is None:
                    raise ValueError("no opaque pixels")
                bx, by, bw, bh = cv2.boundingRect(coords)
                self._digit_templates.append({
                    "digit": d,
                    "template": digit_image[by:by + bh, bx:bx + bw, :3],
                    "mask": mask[by:by + bh, bx:bx + bw],
                    "w": bw,
                    "h": bh,
                })
            except (FileNotFoundError, ValueError) as e:
                _log_buffer.add(
                    f"[{translate('task.' + self._task_name)}] {C_RED}"
                    f"{translate('overlay_load_failed', overlay=f'{d}.png', error=e)}{C_RESET}"
                )
                return False

        fail_path = os.path.join(lang_dir, "fail.png")
        if os.path.exists(fail_path):
            try:
                self._fail_matcher = OverlayMatcher(
                    fail_path,
                    128,
                )
            except Exception:
                self._fail_matcher = None

        return True

    def _match_digit_color(self, image, cx, cy):
        best_digit = 0
        best_conf = 0.0
        for d_info in self._digit_templates:
            t = d_info["template"]
            m = d_info["mask"]
            tw, th = d_info["w"], d_info["h"]
            rx = cx - tw // 2
            ry = cy - th // 2
            if ry < 0 or rx < 0 or ry + th > image.shape[0] or rx + tw > image.shape[1]:
                continue
            region = image[ry:ry + th, rx:rx + tw]
            if region.shape[:2] != t.shape[:2]:
                continue
            diff = cv2.absdiff(region, t)
            diff_gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
            mask_float = m.astype(np.float32) / 255.0
            total_weight = mask_float.sum()
            if total_weight < 1.0:
                continue
            conf = 1.0 - (diff_gray * mask_float).sum() / total_weight
            if conf > best_conf:
                best_conf = conf
                best_digit = d_info["digit"]
        return best_digit, best_conf

    def _match_digit_shape(self, image, cx, cy):
        best_digit = 0
        best_conf = 0.0
        for d_info in self._digit_templates:
            t = d_info["template"]
            m = d_info["mask"]
            tw, th = d_info["w"], d_info["h"]
            rx = cx - tw // 2
            ry = cy - th // 2
            if ry < 0 or rx < 0 or ry + th > image.shape[0] or rx + tw > image.shape[1]:
                continue
            region = image[ry:ry + th, rx:rx + tw]
            if region.shape[:2] != t.shape[:2]:
                continue
            region_bright = np.max(region, axis=2)
            _, region_bin = cv2.threshold(region_bright, 60, 255, cv2.THRESH_BINARY)
            t_bright = np.max(t, axis=2)
            _, t_bin = cv2.threshold(t_bright, 60, 255, cv2.THRESH_BINARY)
            mask_bool = m > 0
            region_fg = region_bin[mask_bool].astype(np.float32) / 255.0
            template_fg = t_bin[mask_bool].astype(np.float32) / 255.0
            total = float(mask_bool.sum())
            if total < 1.0:
                continue
            agreement = np.minimum(region_fg, template_fg).sum() + np.minimum(1.0 - region_fg, 1.0 - template_fg).sum()
            conf = agreement / total
            if conf > best_conf:
                best_conf = conf
                best_digit = d_info["digit"]
        return best_digit, best_conf

    def _is_component_red(self, image, comp):
        x, y, w, h = comp["x"], comp["y"], comp["w"], comp["h"]
        sample_x = x + w // 4
        sample_y = y + h // 4
        sample_w = min(w // 2, 30)
        sample_h = min(h // 2, 30)
        if sample_y + sample_h > image.shape[0] or sample_x + sample_w > image.shape[1]:
            return False
        region = image[sample_y:sample_y + sample_h, sample_x:sample_x + sample_w]
        if region.size == 0:
            return False
        r_ch = region[:, :, 2].astype(np.float32)
        g_ch = region[:, :, 1].astype(np.float32)
        bright_mask = r_ch > 80
        if not bright_mask.any():
            return False
        red_pixels = (bright_mask & (r_ch > g_ch * 2)).sum()
        total_bright = bright_mask.sum()
        return total_bright > 10 and red_pixels / total_bright > 0.3

    def _read_grid(self, image, offset):
        ox, oy = offset
        origin_x = self._grid_cfg["origin_x"] + ox
        origin_y = self._grid_cfg["origin_y"] + oy
        col_spacing = self._grid_cfg["col_spacing"]
        row_spacing = self._grid_cfg["row_spacing"]

        grid_h = row_spacing * self.GRID_ROWS
        grid_w = col_spacing * self.GRID_COLS
        grid_area = image[origin_y:origin_y + grid_h, origin_x:origin_x + grid_w]
        gray = cv2.cvtColor(grid_area, cv2.COLOR_BGR2GRAY)
        red_ch = grid_area[:, :, 2]
        bright = np.maximum(gray, red_ch)
        _, binary = cv2.threshold(bright, 80, 255, cv2.THRESH_BINARY)

        num_labels, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)

        components = []
        for i in range(1, num_labels):
            x, y, w, h, area = stats[i]
            if 10 < w < 80 and 50 < h < 110 and area > 200:
                comp = {
                    "x": x + origin_x,
                    "y": y + origin_y,
                    "w": w,
                    "h": h,
                    "cx": x + origin_x + w // 2,
                    "cy": y + origin_y + h // 2,
                }
                comp["is_red"] = self._is_component_red(image, comp)
                components.append(comp)

        rows_dict = {}
        for comp in components:
            placed = False
            for key in list(rows_dict.keys()):
                if abs(comp["cy"] - key) < row_spacing * 0.4:
                    rows_dict[key].append(comp)
                    placed = True
                    break
            if not placed:
                rows_dict[comp["cy"]] = [comp]

        sorted_rows = sorted(rows_dict.items(), key=lambda x: x[0])[:self.GRID_ROWS]

        grid = [0] * (self.GRID_ROWS * self.GRID_COLS)
        cursor_pos = 0
        low_conf_cells = []
        red_positions = set()

        for row_idx, (row_y, row_digits) in enumerate(sorted_rows):
            row_digits.sort(key=lambda d: d["cx"])

            cells = []
            i = 0
            while i < len(row_digits) - 1:
                d1 = row_digits[i]
                d2 = row_digits[i + 1]
                gap = d2["cx"] - d1["cx"]
                if gap < col_spacing * 0.5:
                    cells.append((d1, d2))
                    i += 2
                else:
                    cells.append((d1, None))
                    i += 1
            if i < len(row_digits):
                cells.append((row_digits[i], None))

            for col_idx, (d1, d2) in enumerate(cells[:self.GRID_COLS]):
                if d1["is_red"]:
                    v1, c1 = self._match_digit_shape(image, d1["cx"], d1["cy"])
                else:
                    v1, c1 = self._match_digit_color(image, d1["cx"], d1["cy"])
                    if c1 < 0.7:
                        v1, c1 = self._match_digit_shape(image, d1["cx"], d1["cy"])
                if d2 is not None:
                    if d2["is_red"]:
                        v2, c2 = self._match_digit_shape(image, d2["cx"], d2["cy"])
                    else:
                        v2, c2 = self._match_digit_color(image, d2["cx"], d2["cy"])
                        if c2 < 0.7:
                            v2, c2 = self._match_digit_shape(image, d2["cx"], d2["cy"])
                else:
                    v2, c2 = 0, 1.0
                grid[row_idx * self.GRID_COLS + col_idx] = v1 * 10 + v2
                if c1 < 0.5 or c2 < 0.5:
                    low_conf_cells.append(
                        f"R{row_idx + 1}C{col_idx + 1}={v1}{v2}({c1:.0%}/{c2:.0%})"
                    )

            for ci, (d1, _) in enumerate(cells[:self.GRID_COLS]):
                if d1["is_red"]:
                    red_positions.add((row_idx, ci))

        for row_idx, col_idx in sorted(red_positions):
            if col_idx > 0:
                left = (row_idx, col_idx - 1)
            else:
                left = ((row_idx - 1) % self.GRID_ROWS, self.GRID_COLS - 1)
            if left not in red_positions:
                cursor_pos = row_idx * self.GRID_COLS + col_idx
                break

        return grid, cursor_pos, low_conf_cells

    def _read_target_ip(self, image, offset):
        ox, oy = offset
        ip_y = self._ip_cfg["y"] + oy
        ip_h = self._ip_cfg["h"]
        x_start = self._ip_cfg["x_start"] + ox

        ip_region = image[ip_y:ip_y + ip_h, x_start:x_start + 900]
        if ip_region.size == 0:
            return [], []

        ref_h = self._digit_templates[0]["h"]

        ip_bright = np.max(ip_region, axis=2)
        _, ip_bin = cv2.threshold(ip_bright, 60, 255, cv2.THRESH_BINARY)

        num_labels, _, stats, _ = cv2.connectedComponentsWithStats(ip_bin, connectivity=8)

        digit_components = []
        for i in range(1, num_labels):
            x, y, w, h, area = stats[i]
            if area > 50 and h > ip_h * 0.3:
                digit_components.append({"x": x, "y": y, "w": w, "h": h})

        rows_dict = {}
        for comp in digit_components:
            cy = comp["y"] + comp["h"] // 2
            placed = False
            for key in list(rows_dict.keys()):
                if abs(cy - key) < ip_h * 0.4:
                    rows_dict[key].append(comp)
                    placed = True
                    break
            if not placed:
                rows_dict[cy] = [comp]

        sorted_rows = sorted(rows_dict.items(), key=lambda x: x[0])

        ip_values = []
        ip_confs = []
        for _, row_comps in sorted_rows:
            row_comps.sort(key=lambda c: c["x"])
            for comp in row_comps:
                dx_start = comp["x"]
                dx_end = comp["x"] + comp["w"]
                dy_start = comp["y"]
                dy_end = comp["y"] + comp["h"]
                digit_region = ip_region[dy_start:dy_end, dx_start:dx_end]
                if digit_region.size == 0:
                    continue

                component_width = dx_end - dx_start
                component_height = dy_end - dy_start
                new_h = ref_h
                new_w = max(1, int(component_width * new_h / component_height))
                resized = cv2.resize(digit_region, (new_w, new_h))

                best_digit = -1
                best_conf = 0.0
                for d_info in self._digit_templates:
                    t = d_info["template"]
                    tw, th = d_info["w"], d_info["h"]

                    t_resized = cv2.resize(t, (new_w, new_h))
                    m_resized = cv2.resize(d_info["mask"], (new_w, new_h))

                    r_bright = np.max(resized, axis=2)
                    _, r_bin = cv2.threshold(r_bright, 60, 255, cv2.THRESH_BINARY)
                    t_bright = np.max(t_resized, axis=2)
                    _, t_bin = cv2.threshold(t_bright, 60, 255, cv2.THRESH_BINARY)

                    mask_bool = m_resized > 128
                    if not mask_bool.any():
                        continue
                    r_fg = r_bin[mask_bool].astype(np.float32) / 255.0
                    t_fg = t_bin[mask_bool].astype(np.float32) / 255.0
                    total = float(mask_bool.sum())
                    agreement = np.minimum(r_fg, t_fg).sum() + np.minimum(1.0 - r_fg, 1.0 - t_fg).sum()
                    conf = agreement / total

                    if conf > best_conf:
                        best_conf = conf
                        best_digit = d_info["digit"]

                if best_digit >= 0:
                    ip_values.append(best_digit)
                    ip_confs.append(best_conf)

        result = []
        for i in range(0, len(ip_values) - 1, 2):
            result.append(ip_values[i] * 10 + ip_values[i + 1])
        return result, ip_confs

    def _find_target_in_grid(self, target, grid):
        for pos in range(self.TOTAL_CELLS):
            match = True
            current = pos
            for k in range(self.CURSOR_LEN):
                if grid[current] != target[k]:
                    match = False
                    break
                if k < self.CURSOR_LEN - 1:
                    current = self._move(current, "right")
            if match:
                return pos
        return None

    def _plan_path(self, start, goal):
        if start == goal:
            return []
        visited = {start}
        queue = deque([(start, [])])
        while queue:
            pos, path = queue.popleft()
            for key in ("w", "s", "a", "d"):
                next_pos = self._move(pos, key)
                if next_pos in visited:
                    continue
                new_path = path + [key]
                if next_pos == goal:
                    return new_path
                visited.add(next_pos)
                queue.append((next_pos, new_path))
        return []

    def _update_display(self, grid, cursor_pos, target_pos, target_values,
                        path, path_step, status):
        _hack_display_update(
            grid=grid[:],
            cursor_pos=cursor_pos,
            target_pos=target_pos,
            target_values=target_values[:],
            path=path[:],
            path_step=path_step,
            status=status,
            task_name=self._task_name,
        )

    def _verify_hack_complete(self, hwnd, offset):
        if self._trigger_matcher is None:
            return True
        for _ in range(5):
            time.sleep(0.3)
            image = capture_window(hwnd)
            if image is None:
                continue
            found, confidence = self._trigger_matcher.match_from_image(image, 0.95, offset)
            if not found:
                return True
        return False

    def _check_fail(self, hwnd, offset):
        if self._fail_matcher is None:
            return False
        image = capture_window(hwnd)
        if image is None:
            return False
        found, _ = self._fail_matcher.match_from_image(image, 0.95, offset)
        return found

    def _attempt_hack(self, hwnd, display_name):
        _hack_display_clear()
        image = capture_window(hwnd)
        if image is None:
            if self._check_fail(hwnd, get_client_offset(hwnd)):
                return "reset"
            _hack_display_clear()
            _log_buffer.add(f"[{display_name}] {C_RED}{translate('hack_capture_failed')}{C_RESET}")
            return None

        offset = get_client_offset(hwnd)

        target, ip_confs = self._read_target_ip(image, offset)
        if len(target) < self.CURSOR_LEN:
            if self._check_fail(hwnd, offset):
                return "reset"
            _hack_display_clear()
            _log_buffer.add(
                f"[{display_name}] {C_RED}{translate('hack_target_read_failed')}{C_RESET}"
            )
            return None

        target_str = ".".join(f"{v:02d}" for v in target[:self.CURSOR_LEN])
        _log_buffer.add(
            f"[{display_name}] {translate('hack_target_detected', target=f'{C_RED}{target_str}{C_RESET}')}"
        )

        grid, cursor_pos, low_conf = self._read_grid(image, offset)

        target_pos = self._find_target_in_grid(target[:self.CURSOR_LEN], grid)
        if target_pos is None:
            return "reset"

        self._update_display(
            grid, cursor_pos, target_pos, target[:self.CURSOR_LEN],
            [], 0, f"{C_GRAY}{translate('hack_planning_path')}{C_RESET}"
        )

        current_pos = cursor_pos
        current_target_pos = target_pos
        path = []
        path_idx = 0
        last_read_time = time.time()
        retrack_count = 0

        while True:
            if current_pos == current_target_pos:
                retrack_count += 1
                self._update_display(
                    grid, current_pos, current_target_pos, target[:self.CURSOR_LEN],
                    [], 0,
                    f"{C_GREEN}{translate('hack_target_aligned', count=retrack_count)}{C_RESET}"
                )
                time.sleep(0.3)

                re_image = capture_window(hwnd)
                if re_image is None:
                    if self._check_fail(hwnd, offset):
                        return "reset"
                    _hack_display_clear()
                    _log_buffer.add(f"[{display_name}] {C_RED}{translate('hack_capture_failed')}{C_RESET}")
                    return None

                if self._trigger_matcher is not None:
                    found, _ = self._trigger_matcher.match_from_image(re_image, 0.95, offset)
                    if not found:
                        if self._check_fail(hwnd, offset):
                            return "reset"
                        return True

                grid, cursor_pos, _ = self._read_grid(re_image, offset)
                current_pos = cursor_pos

                new_target_pos = self._find_target_in_grid(target[:self.CURSOR_LEN], grid)
                if new_target_pos is None:
                    return "reset"

                current_target_pos = new_target_pos

                if current_pos == current_target_pos and self._auto_enter:
                    send_key("enter")
                    time.sleep(0.5)
                    re_image = capture_window(hwnd)
                    if re_image is not None:
                        if self._trigger_matcher is not None:
                            found, _ = self._trigger_matcher.match_from_image(re_image, 0.95, offset)
                            if not found:
                                if self._check_fail(hwnd, offset):
                                    return "reset"
                                return True

                path = []
                path_idx = 0
                last_read_time = time.time()

                cr = current_pos // self.GRID_COLS + 1
                cc = current_pos % self.GRID_COLS + 1
                tr = current_target_pos // self.GRID_COLS + 1
                tc = current_target_pos % self.GRID_COLS + 1
                self._update_display(
                    grid, current_pos, current_target_pos, target[:self.CURSOR_LEN],
                    [], 0,
                    f"{C_GRAY}{translate('hack_reread_status', cr=cr, cc=cc, tr=tr, tc=tc)}{C_RESET}"
                )
                continue

            if time.time() - last_read_time >= self._scan_interval:
                re_image = capture_window(hwnd)
                if re_image is not None:
                    if self._trigger_matcher is not None:
                        found, _ = self._trigger_matcher.match_from_image(re_image, 0.95, offset)
                        if not found:
                            if self._check_fail(hwnd, offset):
                                return "reset"
                            return True

                    grid, cursor_pos, _ = self._read_grid(re_image, offset)
                    current_pos = cursor_pos

                    new_target_pos = self._find_target_in_grid(target[:self.CURSOR_LEN], grid)
                    if new_target_pos is not None:
                        if new_target_pos != current_target_pos:
                            current_target_pos = new_target_pos

                    path = []
                    path_idx = 0

                    cr = current_pos // self.GRID_COLS + 1
                    cc = current_pos % self.GRID_COLS + 1
                    tr = current_target_pos // self.GRID_COLS + 1
                    tc = current_target_pos % self.GRID_COLS + 1
                    self._update_display(
                        grid, current_pos, current_target_pos, target[:self.CURSOR_LEN],
                        [], 0,
                        f"{C_GRAY}{translate('hack_reread_status', cr=cr, cc=cc, tr=tr, tc=tc)}{C_RESET}"
                    )

                last_read_time = time.time()

            if path_idx == 0 or path_idx >= len(path):
                path = self._plan_path(current_pos, current_target_pos)
                path_idx = 0
                if not path:
                    break

            key = path[path_idx]
            send_key(key)
            current_pos = self._move(current_pos, key)
            path_idx += 1

            self._update_display(
                grid, current_pos, current_target_pos, target[:self.CURSOR_LEN],
                path, path_idx,
                f"{C_GRAY}{key} -> R{current_pos // 10 + 1}C{current_pos % 10 + 1}{C_RESET}"
            )

            time.sleep(0.08)

    def run(self, hwnd):
        display_name = translate("task." + self._task_name)

        bring_to_foreground(hwnd)
        time.sleep(0.5)
        clip_cursor_to_window(hwnd)

        try:
            while True:
                result = self._attempt_hack(hwnd, display_name)
                if result == "reset":
                    _hack_display_clear()
                    _log_buffer.add(f"[{display_name}] {C_YELLOW}{translate('hack_resetting')}{C_RESET}")
                    send_key("enter")
                    time.sleep(1.0)
                    continue
                if result is not True:
                    _hack_display_clear()
                else:
                    _hack_display_update(game_over=True)
                    _log_buffer.add(f"[{display_name}] {C_GREEN}{translate('hack_completed')}{C_RESET}")
                return result is True
        finally:
            unclip_cursor()
