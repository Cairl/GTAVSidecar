import os
import json
import time
import threading
import itertools

import cv2
import numpy as np


class Task(BaseTask):
    group = "hack_solver"
    start_trigger = {"overlay": "trigger", "lang": "global", "click": False}
    steps = [{"overlay": "hack", "lang": "auto", "action": "hack"}]
    step_timeout_ms = 60000

    def __init__(self, task_name, task_cfg, global_cfg):
        super().__init__(task_name, task_cfg, global_cfg)
        self._breach_solver = None

    def load(self):
        if not super().load():
            return False
        solver = BreachSolver(self._task_name, self._global_cfg)
        solver.set_trigger_matcher(self._start_trigger_matcher)
        if not solver.load():
            return False
        self._breach_solver = solver
        return True

    def execute_step(self, step_index, hwnd, confidence, scan_center):
        action = self._step_actions[step_index]
        if action == "hack":
            return self._breach_solver.run(hwnd)
        return super().execute_step(step_index, hwnd, confidence, scan_center)


class BreachSolver:
    NUM_COUNT = 3
    MULTIPLIER_VALUES = {"x1": 1, "x2": 2, "x10": 10}
    RED_THRESHOLD = 80
    RED_CLOSE_SIZE = 10
    SYMBOL_MATCH_THRESHOLD = 0.6
    DIGIT_MATCH_THRESHOLD = 0.5
    TARGET_DIGIT_MATCH_THRESHOLD = 0.5

    def __init__(self, task_name, global_cfg):
        self._task_name = task_name
        self._global_cfg = global_cfg
        self._digit_templates = []
        self._digit_grays = []
        self._symbol_templates = {}
        self._symbol_grays = {}
        self._grid_cfg = {}
        self._trigger_matcher = None
        self._red_close_kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT, (self.RED_CLOSE_SIZE, self.RED_CLOSE_SIZE)
        )

    def set_trigger_matcher(self, matcher):
        self._trigger_matcher = matcher

    def _resolve_path(self, filename):
        base = os.path.join(BASE_DIR, "tasks", self._task_name)
        game_lang = resolve_game_language(self._global_cfg.get("lang", "auto"))
        for lang in (game_lang, "global", "en_US"):
            path = os.path.join(base, lang, filename)
            if os.path.exists(path):
                return path
        return os.path.join(base, "global", filename)

    def _load_template_image(self, path):
        raw = np.fromfile(path, dtype=np.uint8)
        img = cv2.imdecode(raw, cv2.IMREAD_UNCHANGED)
        if img is None or img.ndim != 3 or img.shape[2] < 3:
            raise ValueError("invalid image")
        bgr = img[:, :, :3]
        bright = np.max(bgr, axis=2)
        _, mask = cv2.threshold(bright, 30, 255, cv2.THRESH_BINARY)
        coords = cv2.findNonZero(mask)
        if coords is None:
            raise ValueError("no bright pixels")
        bx, by, bw, bh = cv2.boundingRect(coords)
        tmpl = bgr[by:by + bh, bx:bx + bw]
        msk = mask[by:by + bh, bx:bx + bw]
        t_bright = np.max(tmpl, axis=2)
        _, t_bin = cv2.threshold(t_bright, 30, 255, cv2.THRESH_BINARY)
        return tmpl, msk, bw, bh, t_bin

    def load(self):
        lang_dir = os.path.join(BASE_DIR, "tasks", self._task_name, "global")

        grid_json = os.path.join(lang_dir, "grid.json")
        if not os.path.exists(grid_json):
            game_lang = resolve_game_language(self._global_cfg.get("lang", "auto"))
            lang_dir = os.path.join(BASE_DIR, "tasks", self._task_name, game_lang)
            grid_json = os.path.join(lang_dir, "grid.json")
        if not os.path.exists(grid_json):
            _log_buffer.add(
                f"[{translate('task.' + self._task_name)}] {C_RED}"
                f"{translate('overlay_load_failed', overlay='grid.json', error='not found')}{C_RESET}"
            )
            return False

        with open(grid_json, "r", encoding="utf-8") as f:
            self._grid_cfg = json.load(f)

        self._digit_templates = []
        self._digit_grays = []
        for d in range(10):
            path = self._resolve_path(f"{d}.png")
            if not os.path.exists(path):
                _log_buffer.add(
                    f"[{translate('task.' + self._task_name)}] {C_RED}"
                    f"{translate('overlay_load_failed', overlay=f'{d}.png', error='not found')}{C_RESET}"
                )
                return False
            try:
                tmpl, msk, bw, bh, t_bin = self._load_template_image(path)
                gray = np.max(tmpl, axis=2)
                self._digit_templates.append({
                    "digit": d,
                    "template": tmpl,
                    "mask": msk,
                    "w": bw, "h": bh,
                    "t_bin": t_bin,
                })
                self._digit_grays.append(gray)
            except (FileNotFoundError, ValueError) as e:
                _log_buffer.add(
                    f"[{translate('task.' + self._task_name)}] {C_RED}"
                    f"{translate('overlay_load_failed', overlay=f'{d}.png', error=e)}{C_RESET}"
                )
                return False

        self._symbol_templates = {}
        self._symbol_grays = {}
        for name in ("x1", "x2", "x10"):
            path = self._resolve_path(f"{name}.png")
            if not os.path.exists(path):
                _log_buffer.add(
                    f"[{translate('task.' + self._task_name)}] {C_RED}"
                    f"{translate('overlay_load_failed', overlay=f'{name}.png', error='not found')}{C_RESET}"
                )
                return False
            try:
                tmpl, msk, bw, bh, t_bin = self._load_template_image(path)
                gray = np.max(tmpl, axis=2)
                self._symbol_templates[name] = {
                    "template": tmpl,
                    "mask": msk,
                    "w": bw, "h": bh,
                }
                self._symbol_grays[name] = gray
            except (FileNotFoundError, ValueError) as e:
                _log_buffer.add(
                    f"[{translate('task.' + self._task_name)}] {C_RED}"
                    f"{translate('overlay_load_failed', overlay=f'{name}.png', error=e)}{C_RESET}"
                )
                return False

        return True

    def _find_red_components(self, region, min_h=30):
        red_ch = region[:, :, 2].astype(np.float32)
        green_ch = region[:, :, 1].astype(np.float32)
        red_mask = ((red_ch > self.RED_THRESHOLD) & (red_ch > green_ch * 2)).astype(np.uint8) * 255
        closed = cv2.morphologyEx(red_mask, cv2.MORPH_CLOSE, self._red_close_kernel)
        num_labels, _, stats, centroids = cv2.connectedComponentsWithStats(closed, connectivity=8)
        components = []
        for i in range(1, num_labels):
            x, y, w, h, area = stats[i]
            if h >= min_h:
                components.append({
                    "cx": int(centroids[i][0]), "cy": int(centroids[i][1]),
                    "x": x, "y": y, "w": w, "h": h,
                })
        components.sort(key=lambda c: c["cx"])
        return components

    def _match_digit_region(self, region_gray):
        best_digit = -1
        best_corr = 0.0
        for idx, d_info in enumerate(self._digit_templates):
            t_gray = self._digit_grays[idx]
            tw, th = d_info["w"], d_info["h"]
            if th > region_gray.shape[0] or tw > region_gray.shape[1]:
                continue
            result = cv2.matchTemplate(region_gray, t_gray, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)
            if max_val > best_corr:
                best_corr = max_val
                best_digit = d_info["digit"]
        return best_digit, best_corr

    def _match_symbol_region(self, region):
        best_name = None
        best_corr = 0.0
        scores = {}
        for name, s_info in self._symbol_templates.items():
            t_gray = self._symbol_grays[name]
            tw, th = s_info["w"], s_info["h"]
            if th > region.shape[0] or tw > region.shape[1]:
                scores[name] = -1.0
                continue
            result = cv2.matchTemplate(region, t_gray, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)
            scores[name] = max_val
            if max_val > best_corr:
                best_corr = max_val
                best_name = name
        return best_name, best_corr, scores

    SHAPE_MATCH_THRESHOLD = 0.6

    def _scan_digits(self, region, max_digits=0):
        region_gray = np.max(region, axis=2)
        region_bright = np.max(region, axis=2)
        _, region_bin = cv2.threshold(region_bright, 30, 255, cv2.THRESH_BINARY)

        all_detections = []
        n_peaks = max(max_digits, 2) if max_digits > 0 else 2

        for idx, d_info in enumerate(self._digit_templates):
            t_gray = self._digit_grays[idx]
            t_bin = d_info["t_bin"]
            tw, th = d_info["w"], d_info["h"]
            if th > region_gray.shape[0] or tw > region_gray.shape[1]:
                continue
            result = cv2.matchTemplate(region_gray, t_gray, cv2.TM_CCOEFF_NORMED)

            for _ in range(n_peaks):
                _, max_val, _, max_loc = cv2.minMaxLoc(result)
                if max_val < self.DIGIT_MATCH_THRESHOLD:
                    break

                px, py = max_loc
                patch_bin = region_bin[py:py + th, px:px + tw]
                union_mask = (patch_bin > 0) | (t_bin > 0)
                agree = ((patch_bin > 0) == (t_bin > 0)) & union_mask
                shape_score = float(np.sum(agree)) / max(float(np.sum(union_mask)), 1.0)

                if shape_score >= self.SHAPE_MATCH_THRESHOLD:
                    all_detections.append({
                        "digit": d_info["digit"],
                        "confidence": shape_score,
                        "cx": max_loc[0] + tw // 2,
                        "w": tw,
                    })
                sx1 = max(0, max_loc[0])
                sx2 = min(result.shape[1], max_loc[0] + tw)
                sy1 = max(0, max_loc[1])
                sy2 = min(result.shape[0], max_loc[1] + th)
                result[sy1:sy2, sx1:sx2] = 0

        if not all_detections:
            return -1

        all_detections.sort(key=lambda d: d["confidence"], reverse=True)
        kept = []
        for det in all_detections:
            overlap = False
            for k in kept:
                if abs(det["cx"] - k["cx"]) < min(det["w"], k["w"]) * 0.5:
                    overlap = True
                    break
            if not overlap:
                kept.append(det)

        if max_digits > 0 and len(kept) > max_digits:
            if max_digits == 1:
                kept = [max(kept, key=lambda d: d["confidence"])]
            else:
                kept.sort(key=lambda d: d["cx"])
                kept = kept[-max_digits:]
        else:
            kept.sort(key=lambda d: d["cx"])

        digits = [d["digit"] for d in kept]
        value = 0
        for d in digits:
            value = value * 10 + d
        return value if digits else -1

    def _read_target(self, image, offset):
        ox, oy = offset
        cfg = self._grid_cfg["target"]
        y = cfg["y"] + oy
        h = cfg["h"]
        x_start = cfg["x_start"] + ox

        target_region = image[y:y + h, x_start:x_start + 500]
        if target_region.size == 0:
            return -1

        components = self._find_red_components(target_region, min_h=50)
        if not components:
            return -1

        if len(components) > 3:
            components = components[-3:]

        target_red = target_region[:, :, 2]

        digits = []
        for comp in components:
            margin = 30
            x1 = max(0, comp["x"] - margin)
            y1 = max(0, comp["y"] - margin)
            x2 = min(target_red.shape[1], comp["x"] + comp["w"] + margin)
            y2 = min(target_red.shape[0], comp["y"] + comp["h"] + margin)
            crop_red = target_red[y1:y2, x1:x2]

            d, c = self._match_digit_region(crop_red)
            if d >= 0 and c >= self.TARGET_DIGIT_MATCH_THRESHOLD:
                digits.append(d)
            else:
                digits.append(0)

        if not digits:
            return -1
        value = 0
        for d in digits:
            value = value * 10 + d
        return value

    def _read_number_at(self, image, region_cfg, offset):
        ox, oy = offset
        rx = region_cfg["x"] + ox
        ry = region_cfg["y"] + oy
        rw = region_cfg["w"]
        rh = region_cfg["h"]

        region = image[ry:ry + rh, rx:rx + rw]
        if region.size == 0:
            return -1

        return self._scan_digits(region, max_digits=1)

    def _read_symbol_at(self, image, region_cfg, offset):
        ox, oy = offset
        rx = region_cfg["x"] + ox
        ry = region_cfg["y"] + oy
        rw = region_cfg["w"]
        rh = region_cfg["h"]

        region = image[ry:ry + rh, rx:rx + rw]
        if region.size == 0:
            return None

        region_gray = np.max(region, axis=2)
        name, conf, _ = self._match_symbol_region(region_gray)
        if name is not None and conf >= self.SYMBOL_MATCH_THRESHOLD:
            return name
        return None

    def _solve_assignment(self, target, numbers, multipliers):
        multiplier_values = [self.MULTIPLIER_VALUES.get(m, 1) for m in multipliers]
        for perm in itertools.permutations(range(self.NUM_COUNT)):
            total = sum(numbers[i] * multiplier_values[perm[i]] for i in range(self.NUM_COUNT))
            if total == target:
                return perm
        return None

    def run(self, hwnd):
        display_name = translate("task." + self._task_name)

        focus_game_window(hwnd)
        clip_cursor_to_window(hwnd)

        try:
            image = capture_window(hwnd)
            if image is None:
                _log_buffer.add(f"[{display_name}] {C_RED}{translate('hack_capture_failed')}{C_RESET}")
                return False

            offset = get_client_offset(hwnd)

            target = self._read_target(image, offset)
            if target <= 0:
                _log_buffer.add(f"[{display_name}] {C_RED}{translate('hack_target_read_failed')}{C_RESET}")
                return False

            numbers = []
            for i, num_cfg in enumerate(self._grid_cfg["numbers"]):
                val = self._read_number_at(image, num_cfg, offset)
                if val < 0:
                    _log_buffer.add(f"[{display_name}] {C_RED}{translate('breach_number_read_failed', index=i+1)}{C_RESET}")
                    return False
                numbers.append(val)

            multipliers = []
            for i, sym_cfg in enumerate(self._grid_cfg["symbols"]):
                sym = self._read_symbol_at(image, sym_cfg, offset)
                if sym is None:
                    _log_buffer.add(f"[{display_name}] {C_RED}{translate('breach_symbol_read_failed', index=i+1)}{C_RESET}")
                    return False
                multipliers.append(sym)

            assignment = self._solve_assignment(target, numbers, multipliers)
            if assignment is None:
                _log_buffer.add(f"[{display_name}] {C_RED}{translate('breach_no_solution')}{C_RESET}")
                return False

            mult_values = {"x1": 1, "x2": 2, "x10": 10}
            paired_syms = [multipliers[assignment[i]] for i in range(self.NUM_COUNT)]
            products = [numbers[i] * mult_values.get(paired_syms[i], 1) for i in range(self.NUM_COUNT)]

            num_strs = [str(n) for n in numbers]
            num_w = max(len(s) for s in num_strs)
            mult_val_strs = [str(mult_values.get(paired_syms[i], 1)) for i in range(self.NUM_COUNT)]
            mult_w = max(len(s) for s in mult_val_strs)
            prod_strs = [str(p) for p in products]
            prod_w = max(len(s) for s in prod_strs)

            content_w = num_w + 3 + mult_w + 3 + prod_w
            target_str = f"{target:03d}"
            sum_visible = 3 + 1 + len(target_str)
            inner_w = max(content_w, sum_visible) + 2
            pad = " " * (inner_w - content_w - 2)

            bc = C_BORDER
            rs = C_RESET
            gn = C_GREEN
            yl = C_YELLOW

            top_idx = _log_buffer.add(
                f"[{display_name}] {bc}╭{'─' * inner_w}╮{rs}"
            )

            line_indices = []
            for i in range(self.NUM_COUNT):
                num = num_strs[i].rjust(num_w)
                mult_blank = " " * mult_w
                prod_blank = " " * prod_w
                content = f" {num} × {mult_blank} = {prod_blank}{pad} "
                idx = _log_buffer.add(
                    f"[{display_name}] {bc}│{rs}{content}{bc}│{rs}"
                )
                line_indices.append(idx)

            sep_idx = _log_buffer.add(
                f"[{display_name}] {bc}│{'─' * inner_w}│{rs}"
            )

            sum_pad_left = " " * (inner_w - sum_visible - 2)
            sum_idx = _log_buffer.add(
                f"[{display_name}] {bc}│{rs} {sum_pad_left}000/{target_str} {bc}│{rs}"
            )

            btm_idx = _log_buffer.add(
                f"[{display_name}] {bc}╰{'─' * inner_w}╯{rs}"
            )

            animation_delay = self._grid_cfg.get("animation_delay_ms", 1500) / 1000.0
            multiplier_values = [self.MULTIPLIER_VALUES.get(m, 1) for m in multipliers]

            current_sum = 0
            prev_sum = 0
            _anim_thread = None
            selected_symbols = set()

            for i in range(self.NUM_COUNT):
                target_sym_idx = assignment[i]

                send_key("enter")
                time.sleep(0.5)

                cursor_pos = i
                while cursor_pos in selected_symbols:
                    cursor_pos = (cursor_pos + 1) % self.NUM_COUNT

                available = [idx for idx in range(self.NUM_COUNT) if idx not in selected_symbols]

                if target_sym_idx in available:
                    target_in_available = available.index(target_sym_idx)
                else:
                    target_in_available = 0

                cursor_in_available = available.index(cursor_pos) if cursor_pos in available else 0

                current_idx = cursor_in_available
                while current_idx < target_in_available:
                    send_key("down")
                    time.sleep(0.15)
                    current_idx += 1
                while current_idx > target_in_available:
                    send_key("up")
                    time.sleep(0.15)
                    current_idx -= 1

                send_key("enter")

                selected_symbols.add(target_sym_idx)

                num = num_strs[i].rjust(num_w)
                mult_val = mult_val_strs[i].rjust(mult_w)
                prod = prod_strs[i].rjust(prod_w)
                content_hi = f" {num} × {yl}{mult_val}{rs} = {prod}{pad} "
                content_lo = f" {num} × {mult_val} = {prod}{pad} "

                expected_sum = prev_sum + numbers[i] * multiplier_values[assignment[i]]
                sum_pad_left = " " * (inner_w - 3 - 1 - len(target_str) - 2)

                def _animate_sum(start, end, idx, pad_left):
                    for step_s in range(start + 1, end + 1):
                        step_color = gn if step_s == target else yl
                        step_str = f"{step_s:03d}"
                        _log_buffer.replace_at(
                            idx,
                            f"[{display_name}] {bc}│{rs} {pad_left}{step_color}{step_str}{rs}/{target_str} {bc}│{rs}"
                        )
                        if step_s < end:
                            time.sleep(0.03)

                _anim_thread = threading.Thread(target=_animate_sum, args=(prev_sum, expected_sum, sum_idx, sum_pad_left), daemon=True)
                _anim_thread.start()
                prev_sum = expected_sum

                delay = animation_delay if i < self.NUM_COUNT - 1 else 1.0
                blink_interval = 0.15
                blink_count = 3
                elapsed = 0.0

                for _ in range(blink_count):
                    _log_buffer.replace_at(
                        line_indices[i],
                        f"[{display_name}] {bc}│{rs}{content_lo}{bc}│{rs}"
                    )
                    time.sleep(blink_interval)
                    elapsed += blink_interval
                    _log_buffer.replace_at(
                        line_indices[i],
                        f"[{display_name}] {bc}│{rs}{content_hi}{bc}│{rs}"
                    )
                    time.sleep(blink_interval)
                    elapsed += blink_interval

                remaining = delay - elapsed
                if remaining > 0:
                    time.sleep(remaining)

                verify_image = capture_window(hwnd)
                if verify_image is not None:
                    verify_offset = get_client_offset(hwnd)
                    actual_target = self._read_target(verify_image, verify_offset)
                    if 0 < actual_target < target:
                        current_sum = target - actual_target
                    else:
                        current_sum = expected_sum
                else:
                    current_sum = expected_sum

            _log_buffer.add(f"[{display_name}] {gn}{translate('hack_game_over')}{rs}")

            if _anim_thread is not None:
                _anim_thread.join()

            if self._trigger_matcher is not None:
                while True:
                    time.sleep(0.5)
                    image = capture_window(hwnd)
                    if image is None:
                        break
                    offset = get_client_offset(hwnd)
                    found, _ = self._trigger_matcher.match_from_image(image, 0.95, offset)
                    if not found:
                        break

            time.sleep(3.0)
            return True

        finally:
            unclip_cursor()
