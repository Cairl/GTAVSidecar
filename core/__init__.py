import os

from . import windows_api
from . import task_base
from . import config
from . import i18n
from . import log_buffer
from . import resource_monitor
from . import renderer
from . import task_runner

_INJECT_SYMBOLS = {
    "BaseTask": task_base.BaseTask,
    "OverlayMatcher": task_base.OverlayMatcher,
    "capture_window": windows_api.capture_window,
    "click_at": windows_api.click_at,
    "send_key": windows_api.send_key,
    "send_key_background": windows_api.send_key_background,
    "focus_game_window": windows_api.focus_game_window,
    "get_client_offset": windows_api.get_client_offset,
    "get_client_screen_origin": windows_api.get_client_screen_origin,
    "clip_cursor_to_window": windows_api.clip_cursor_to_window,
    "unclip_cursor": windows_api.unclip_cursor,
    "kill_game_process": windows_api.kill_game_process,
    "find_game_window": windows_api.find_game_window,
    "translate": i18n.translate,
    "load_config": config.load_config,
    "_log_buffer": log_buffer._log_buffer,
    "resolve_game_language": config.resolve_game_language,
    "GAME_PROCESS_NAME": windows_api.GAME_PROCESS_NAME,
    "BASE_DIR": config.BASE_DIR,
    "C_RED": renderer.C_RED,
    "C_GREEN": renderer.C_GREEN,
    "C_YELLOW": renderer.C_YELLOW,
    "C_RESET": renderer.C_RESET,
    "C_GRAY": renderer.C_GRAY,
    "C_BORDER": renderer.C_BORDER,
    "C_HIGHLIGHT": renderer.C_HIGHLIGHT,
    "C_BLUE": "\033[38;2;137;180;250m",
}


def setup():
    config.set_inject_symbols(_INJECT_SYMBOLS)
