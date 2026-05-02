import unicodedata
from functools import lru_cache

from . import resource_monitor as _res
from . import i18n as _i18n

BORDER_TL = "\u256d"
BORDER_TR = "\u256e"
BORDER_BL = "\u2570"
BORDER_BR = "\u256f"
BORDER_H = "\u2500"
BORDER_V = "\u2502"

C_RED = "\033[38;2;243;139;168m"
C_GREEN = "\033[38;2;166;227;161m"
C_YELLOW = "\033[38;2;249;226;175m"
C_GRAY = "\033[90m"
C_RESET = "\033[0m"
C_BORDER = "\033[38;2;88;91;112m"
C_HIGHLIGHT = "\033[48;2;88;91;112m"

_selected_task_index = 0


def get_selected_index() -> int:
    return _selected_task_index


def set_selected_index(idx: int) -> None:
    global _selected_task_index
    _selected_task_index = idx


@lru_cache(maxsize=512)
def _visible_len(s: str) -> int:
    result = 0
    in_escape = False
    for ch in s:
        if ch == "\033":
            in_escape = True
            continue
        if in_escape:
            if ch.isalpha():
                in_escape = False
            continue
        char_width = unicodedata.east_asian_width(ch)
        if char_width in ("W", "F"):
            result += 2
        else:
            result += 1
    return result


def _pad_to_width(s: str, width: int) -> str:
    visible_len = _visible_len(s)
    if visible_len >= width:
        return s
    return s + " " * (width - visible_len)


def _rpad_to_width(s: str, width: int) -> str:
    visible_len = _visible_len(s)
    if visible_len >= width:
        return s
    return " " * (width - visible_len) + s


def _truncate_visible(s: str, max_width: int) -> str:
    visible = 0
    i = 0
    while i < len(s):
        if s[i] == '\033':
            j = s.find('m', i)
            if j >= 0:
                i = j + 1
            else:
                i = len(s)
        else:
            w = 2 if unicodedata.east_asian_width(s[i]) in ('W', 'F') else 1
            if visible + w > max_width:
                return s[:i] + C_RESET
            visible += w
            i += 1
    return s


def build_task_panel(task_keys: list[str], runners: dict,
                     anti_afk_running: bool = False,
                     show_perf_running: bool = False,
                     game_status: str = "not_running") -> list[str]:
    border_color = f"{C_BORDER}"
    reset_color = C_RESET
    title = _i18n.translate("app_title")
    PAD = 2

    group_last_child: dict[str, str] = {}
    for key in task_keys:
        if key in ("anti_afk", "show_performance"):
            continue
        runner = runners.get(key)
        group = runner.group if runner else None
        if group:
            group_last_child[group] = key

    seen_groups: set[str] = set()
    rows: list[tuple[str, bool, bool]] = []

    for idx, key in enumerate(task_keys):
        if key == "anti_afk":
            display_name = _i18n.translate(f"task.{key}")
            is_running = anti_afk_running
            is_selected = idx == _selected_task_index
            checkbox = "\U0001F5F9" if is_running else "\u2610"
            prefix = f"{' ' * PAD}{checkbox}  "
            rows.append((f"{prefix}{display_name}", is_selected, is_running))
            continue

        if key == "show_performance":
            display_name = _i18n.translate(f"task.{key}")
            is_running = show_perf_running
            is_selected = idx == _selected_task_index
            checkbox = "\U0001F5F9" if is_running else "\u2610"
            prefix = f"{' ' * PAD}{checkbox}  "
            rows.append((f"{prefix}{display_name}", is_selected, is_running))
            continue

        runner = runners.get(key)
        display_name = _i18n.translate(f"task.{key}")
        is_running = runner is not None and runner.is_running
        is_selected = idx == _selected_task_index
        group = runner.group if runner else None

        if group and group not in seen_groups:
            seen_groups.add(group)
            group_name = _i18n.translate(f"group.{group}")
            group_prefix = f"{' ' * PAD}☒  "
            rows.append((f"{group_prefix}{group_name}", False, False))

        if group:
            checkbox = "\U0001F5F9" if is_running else "\u2610"
            child_prefix = f"{' ' * PAD}  {checkbox}  "
            rows.append((f"{child_prefix}{display_name}", is_selected, is_running))
        else:
            checkbox = "\U0001F5F9" if is_running else "\u2610"
            prefix = f"{' ' * PAD}{checkbox}  "
            rows.append((f"{prefix}{display_name}", is_selected, is_running))

    max_content_w = max(_visible_len(r[0]) for r in rows) if rows else 0
    inner_w = max_content_w + PAD * 2 + 1
    title_min_width = len(title) + PAD * 2 + 2
    inner_w = max(inner_w, title_min_width)

    status_colors = {
        "connected": C_GREEN,
        "not_running": C_RED,
        "no_window": C_YELLOW,
    }
    sc = status_colors.get(game_status, C_RED)

    if show_perf_running:
        cpu_pct = _res.get_cpu_percent()
        mem_mb = _res.get_mem_mb()
        if mem_mb >= 1024:
            mem_str = f"{mem_mb / 1024:.2f}GB"
        else:
            mem_str = f"{mem_mb:.1f}MB"
        status_text = (
            f"{_i18n.translate('status_cpu')} {cpu_pct:.1f}%"
            f"  {_i18n.translate('status_memory')} {mem_str}"
        )

    lines: list[str] = []
    title_pad = inner_w - len(title) - 2
    left_dashes = min(3, title_pad // 2)
    right_dashes = title_pad - left_dashes
    lines.append(
        f"{border_color}{BORDER_TL}{BORDER_H * left_dashes} "
        f"{sc}{title}{C_RESET}{border_color} "
        f"{BORDER_H * right_dashes}{BORDER_TR}{reset_color}"
    )

    for content, is_selected, is_running in rows:
        padded = _pad_to_width(content, inner_w)
        if is_selected:
            highlighted = padded.replace(C_RESET, C_RESET + C_HIGHLIGHT)
            lines.append(
                f"{border_color}{BORDER_V}{reset_color}{C_HIGHLIGHT}"
                f"{highlighted}{reset_color}{border_color}{BORDER_V}{reset_color}"
            )
        else:
            lines.append(
                f"{border_color}{BORDER_V}{reset_color}"
                f"{padded}{border_color}{BORDER_V}{reset_color}"
            )

    if show_perf_running:
        lines.append(f"{border_color}{BORDER_V}{BORDER_H * inner_w}{BORDER_V}{reset_color}")
        status_padded = " " + _pad_to_width(status_text, inner_w - 2) + " "
        lines.append(
            f"{border_color}{BORDER_V}{reset_color}{status_padded}"
            f"{border_color}{BORDER_V}{reset_color}"
        )

    lines.append(f"{border_color}{BORDER_BL}{BORDER_H * inner_w}{BORDER_BR}{reset_color}")
    return lines


def build_grid_panel() -> list[str]:
    from . import log_buffer as _log_mod

    with _log_mod._hack_display_lock:
        state = dict(_log_mod._hack_display)

    if not state:
        return []

    if "grid" not in state:
        return []

    grid = state["grid"]
    cursor_pos = state.get("cursor_pos", -1)
    target_pos = state.get("target_pos", -1)

    cursor_positions = set()
    if cursor_pos is not None and cursor_pos >= 0:
        for k in range(4):
            cursor_positions.add((cursor_pos + k) % 80)

    target_positions = set()
    if target_pos is not None and target_pos >= 0:
        for k in range(4):
            target_positions.add((target_pos + k) % 80)

    lines: list[str] = []
    for r in range(8):
        cells = []
        for c in range(10):
            idx = r * 10 + c
            val = f"{grid[idx]:02d}"
            if idx in target_positions and idx in cursor_positions:
                val = f"{C_GREEN}\033[4m{val}\033[0m"
            elif idx in target_positions:
                val = f"{C_GREEN}{val}\033[0m"
            elif idx in cursor_positions:
                val = f"\033[4m{val}\033[0m"
            cells.append(val)
        lines.append(" ".join(cells))

    if state.get("game_over"):
        display_name = _i18n.translate(f"task.{state.get('task_name', '')}")
        footer = f"[{display_name}] {_i18n.translate('hack_game_over')}"
        lines.append(footer)

    return lines
