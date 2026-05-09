import sys
import os
import time
import shutil
import msvcrt
import signal

sys.dont_write_bytecode = True

from core import setup
from core import i18n
from core import config
from core import log_buffer
from core import renderer
from core import resource_monitor
from core import task_runner
from core import windows_api
from core import game_lifecycle
from core import task_registry

setup()

BASE_DIR = config.BASE_DIR


def main() -> None:
    cfg = config.load_config()
    config_lang = cfg.get("lang", "auto")
    game_lang = config.resolve_game_language(config_lang)
    i18n.i18n_init(game_lang, BASE_DIR)
    log_buffer.set_log_dir(os.path.join(BASE_DIR, "logs"))

    registry = task_registry.TaskRegistry(BASE_DIR)
    overrides = registry.apply_locale_overrides(game_lang, {})
    if overrides:
        i18n.apply_overrides(overrides)

    signal.signal(signal.SIGINT, signal.SIG_IGN)

    if os.name == "nt":
        os.system("")
    sys.stdout.write("\033[2J\033[?25l")
    sys.stdout.flush()

    lifecycle = game_lifecycle.GameLifecycleManager(windows_api.GAME_PROCESS_NAME)
    lifecycle.start()

    def _on_lifecycle_state_change(state: str, hwnd: int | None) -> None:
        if state == game_lifecycle.GameLifecycleManager.STATE_RUNNING:
            log_buffer.add(
                f"{renderer.C_GREEN}{i18n.translate('lifecycle_game_started')}{renderer.C_RESET}"
            )
        elif state == game_lifecycle.GameLifecycleManager.STATE_NOT_RUNNING:
            log_buffer.add(
                f"{renderer.C_GRAY}{i18n.translate('lifecycle_game_exited')}{renderer.C_RESET}"
            )

    lifecycle.add_listener(_on_lifecycle_state_change)

    runners: dict[str, task_runner.TaskRunner] = {}
    last_render_lines: list[str] = []
    last_lang = game_lang
    game_status = "not_running"
    game_status_check_time = 0.0

    _last_task_keys: list[str] = []
    _last_task_lines: list[str] = []
    _last_term_w = 0
    _last_entries: list[str] = []
    _frame_counter = 0

    try:
        while True:
            cfg = config.load_config()
            current_lang = config.resolve_game_language(cfg.get("lang", "auto"))
            if current_lang != last_lang:
                i18n.i18n_init(current_lang, BASE_DIR)
                overrides = registry.apply_locale_overrides(current_lang, {})
                if overrides:
                    i18n.apply_overrides(overrides)
                last_lang = current_lang

            task_cfgs = config._flatten_task_configs(cfg)

            for key in list(runners.keys()):
                if key not in task_cfgs:
                    runners[key].stop()
                    del runners[key]

            for key, task_cfg in task_cfgs.items():
                if key not in runners:
                    runner = task_runner.TaskRunner(key, task_cfg, cfg, lifecycle=lifecycle)
                    runners[key] = runner
                    if task_cfg.get("enabled", False):
                        runner.start()
                else:
                    runner = runners[key]
                    enabled = task_cfg.get("enabled", False)
                    if enabled and not runner.is_running:
                        runner.start()
                    elif not enabled and runner.is_running:
                        runner.stop()
                    if runner._task_cfg != task_cfg:
                        runner.reload(task_cfg, cfg)
                    else:
                        runner._task_cfg = task_cfg

            registry_names = registry.get_task_names()
            task_keys = [k for k in registry_names if k in task_cfgs]

            show_perf_running = False
            show_perf_runner = runners.get("show_performance")
            if show_perf_runner and show_perf_runner.is_running:
                show_perf_running = True

            now = time.time()
            if show_perf_running:
                resource_monitor.sample_process_resources()
            if now - game_status_check_time > 3.0:
                game_status = resource_monitor.get_game_status(lifecycle)
                game_status_check_time = now

            term_size = shutil.get_terminal_size()
            term_h = term_size.lines
            term_w = term_size.columns

            has_input = msvcrt.kbhit()
            needs_render = (
                has_input
                or term_w != _last_term_w
                or task_keys != _last_task_keys
                or _frame_counter % 5 == 0
            )

            if needs_render:
                task_lines = renderer.build_task_panel(
                    task_keys, runners, False, show_perf_running, game_status
                )
                task_panel_h = len(task_lines)

                log_avail = term_h - task_panel_h - 1
                entries = log_buffer.recent(log_avail) if log_avail > 0 else []

                lines = task_lines[:]
                if entries:
                    lines.append("")
                for entry in entries:
                    lines.append(renderer._truncate_visible(entry, term_w))

                out_buf: list[str] = []
                for i, line in enumerate(lines[:term_h]):
                    if i < len(last_render_lines) and last_render_lines[i] == line:
                        continue
                    out_buf.append(f"\033[{i + 1};1H\033[2K{line}")

                for i in range(len(lines), len(last_render_lines)):
                    if i < term_h:
                        out_buf.append(f"\033[{i + 1};1H\033[2K")

                if out_buf:
                    sys.stdout.write("".join(out_buf))
                sys.stdout.flush()
                last_render_lines = lines[:]

                _last_task_lines = task_lines
                _last_term_w = term_w
                _last_entries = entries

            _last_task_keys = task_keys
            _frame_counter += 1

            if has_input:
                key = msvcrt.getwch()
                if key == "\x00" or key == "\xe0":
                    arrow = msvcrt.getwch()
                    if arrow == "H":
                        if renderer.get_selected_index() == 0:
                            renderer.set_selected_index(len(task_keys) - 1)
                        else:
                            renderer.set_selected_index(renderer.get_selected_index() - 1)
                    elif arrow == "P":
                        if renderer.get_selected_index() >= len(task_keys) - 1:
                            renderer.set_selected_index(0)
                        else:
                            renderer.set_selected_index(renderer.get_selected_index() + 1)
                elif key == "\x1b":
                    pass
                elif key == "\r":
                    if task_keys and 0 <= renderer.get_selected_index() < len(task_keys):
                        task_key = task_keys[renderer.get_selected_index()]
                        runner = runners.get(task_key)
                        if runner:
                            if runner.is_running:
                                runner.stop()
                            else:
                                runner.start()
                            config._set_task_enabled(cfg, task_key, runner.is_running)
                            config.save_config(cfg)

            time.sleep(0.02)

    finally:
        lifecycle.stop()
        for runner in runners.values():
            runner.stop()
        sys.stdout.write("\033[r\033[m\033[?25h")
        sys.stdout.flush()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        sys.stdout.write("\033[r\033[m\033[?25h")
        sys.stdout.flush()
        print(f"\n{i18n.translate('fatal_error', error=e)}")
        import traceback
        traceback.print_exc()
        input(i18n.translate("press_enter_to_exit"))
