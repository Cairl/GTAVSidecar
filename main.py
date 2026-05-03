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

setup()

BASE_DIR = config.BASE_DIR

_anti_afk_task = None


def _load_anti_afk_module():
    mod = config._load_task_module("anti_afk")
    if mod is None:
        return None
    task_cls = getattr(mod, "Task", None)
    if task_cls is None:
        return None
    cfg = config.load_config()
    afk_cfg = cfg.get("anti_afk", {})
    task = task_cls("anti_afk", afk_cfg, cfg)
    if not task.load():
        return None
    return task


def _start_anti_afk():
    global _anti_afk_task
    if _anti_afk_task and _anti_afk_task.is_running:
        return
    if _anti_afk_task is None:
        _anti_afk_task = _load_anti_afk_module()
        if _anti_afk_task is None:
            return
    _anti_afk_task.start()


def _stop_anti_afk():
    global _anti_afk_task
    if _anti_afk_task:
        _anti_afk_task.stop()


def main() -> None:
    cfg = config.load_config()
    config_lang = cfg.get("lang", "auto")
    game_lang = config.resolve_game_language(config_lang)
    i18n.i18n_init(game_lang, BASE_DIR)
    log_buffer._log_buffer.set_log_dir(os.path.join(BASE_DIR, "logs"))

    signal.signal(signal.SIGINT, signal.SIG_IGN)

    if os.name == "nt":
        os.system("")
    sys.stdout.write("\033[2J\033[?25l")
    sys.stdout.flush()

    runners: dict[str, task_runner.TaskRunner] = {}
    last_render_lines: list[str] = []
    last_lang = game_lang
    game_status = "not_running"
    game_status_check_time = 0.0

    try:
        while True:
            cfg = config.load_config()
            current_lang = config.resolve_game_language(cfg.get("lang", "auto"))
            if current_lang != last_lang:
                i18n.i18n_init(current_lang, BASE_DIR)
                last_lang = current_lang

            task_cfgs = config._flatten_task_configs(cfg)

            afk_cfg = cfg.get("anti_afk", {})
            afk_enabled = afk_cfg.get("enabled", False)
            afk_running = _anti_afk_task is not None and _anti_afk_task.is_running
            if afk_enabled and not afk_running:
                _start_anti_afk()
            elif not afk_enabled and afk_running:
                _stop_anti_afk()

            for key in list(runners.keys()):
                if key not in task_cfgs:
                    runners[key].stop()
                    del runners[key]

            for key, task_cfg in task_cfgs.items():
                if key not in runners:
                    runner = task_runner.TaskRunner(key, task_cfg, cfg)
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

            task_keys = list(task_cfgs.keys()) + ["anti_afk"]
            task_keys = [k for k in config._TASK_ORDER if k in task_keys]

            show_perf_running = False
            show_perf_runner = runners.get("show_performance")
            if show_perf_runner and show_perf_runner.is_running:
                show_perf_running = True

            now = time.time()
            if show_perf_running:
                resource_monitor.sample_process_resources()
            if now - game_status_check_time > 3.0:
                game_status = resource_monitor.get_game_status()
                game_status_check_time = now

            term_size = shutil.get_terminal_size()
            term_h = term_size.lines
            term_w = term_size.columns

            task_lines = renderer.build_task_panel(
                task_keys, runners, afk_running, show_perf_running, game_status
            )
            task_panel_h = len(task_lines)

            log_avail = term_h - task_panel_h - 1
            entries = log_buffer._log_buffer.recent(log_avail) if log_avail > 0 else []

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

            if msvcrt.kbhit():
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
                        if task_key == "anti_afk":
                            if _anti_afk_task and _anti_afk_task.is_running:
                                _stop_anti_afk()
                            else:
                                _start_anti_afk()
                            if "anti_afk" not in cfg:
                                cfg["anti_afk"] = {}
                            cfg["anti_afk"]["enabled"] = _anti_afk_task is not None and _anti_afk_task.is_running
                            config.save_config(cfg)
                        else:
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
        _stop_anti_afk()
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
