import json
import os
import re
import winreg
import importlib.util

from . import log_buffer as _log_mod
from . import i18n as _i18n_mod

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
_config_cache: dict = {"data": None, "mtime": 0.0}

_STEAM_LANG_MAP = {
    "schinese": "zh_CN",
    "tchinese": "zh_TW",
    "english": "en_US",
}
_GTA5_APPID = "3240220"
_detected_lang_cache: str | None = None

_SKIP_CONFIG_KEYS = frozenset({"lang", "scan_ms", "anti_afk"})

_TASK_ORDER = [
    "create_invite_only",
    "close_game_at_results",
    "hack_solver_voltlab",
    "hack_solver_connect_host",
    "show_performance",
    "anti_afk",
    "bunker_fast_track_research",
]

_INJECT_SYMBOLS = {}


def set_inject_symbols(symbols: dict) -> None:
    _INJECT_SYMBOLS.clear()
    _INJECT_SYMBOLS.update(symbols)


def _is_task_group(value):
    if not isinstance(value, dict) or not value:
        return False
    return all(isinstance(v, dict) for v in value.values())


def _flatten_task_configs(config):
    result = {}
    for key, value in config.items():
        if key in _SKIP_CONFIG_KEYS:
            continue
        if not isinstance(value, dict):
            continue
        if _is_task_group(value):
            for sub_key, sub_value in value.items():
                result[f"{key}_{sub_key}"] = sub_value if isinstance(sub_value, dict) else {}
        else:
            result[key] = value

    tasks_dir = os.path.join(BASE_DIR, "tasks")
    if os.path.isdir(tasks_dir):
        for name in os.listdir(tasks_dir):
            if name == "anti_afk":
                continue
            if name not in result and os.path.isfile(os.path.join(tasks_dir, name, "task.py")):
                mod = _load_task_module(name)
                task_cfg = {"enabled": False, "scan_ms": 500}
                if mod:
                    task_cls = getattr(mod, "Task", None)
                    if task_cls:
                        defaults = getattr(task_cls, "default_config", {})
                        task_cfg.update(defaults)
                result[name] = task_cfg

    return result


def _get_task_config(config, task_name):
    for key, value in config.items():
        if key in _SKIP_CONFIG_KEYS:
            continue
        if not isinstance(value, dict):
            continue
        if key == task_name:
            if _is_task_group(value):
                continue
            return value
        if _is_task_group(value):
            prefix = f"{key}_"
            if task_name.startswith(prefix):
                sub_key = task_name[len(prefix):]
                if sub_key in value:
                    sub_value = value[sub_key]
                    return sub_value if isinstance(sub_value, dict) else {}
    return None


def _set_task_enabled(config, task_name, enabled):
    task_cfg = _get_task_config(config, task_name)
    if task_cfg is not None:
        task_cfg["enabled"] = enabled


def _load_task_module(task_name: str):
    task_py = os.path.join(BASE_DIR, "tasks", task_name, "task.py")
    if not os.path.exists(task_py):
        return None
    spec = importlib.util.spec_from_file_location(f"tasks.{task_name}", task_py)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    mod.__dict__.update(_INJECT_SYMBOLS)
    spec.loader.exec_module(mod)
    return mod


def _migrate_config(config: dict) -> dict:
    if "hack_solver" in config and isinstance(config["hack_solver"], dict):
        hs = config["hack_solver"]
        if "ip_crack" in hs:
            hs["connect_host"] = hs.pop("ip_crack")
    return config


def load_config() -> dict:
    try:
        if not os.path.exists(CONFIG_FILE):
            default_cfg = _build_default_config()
            save_config(default_cfg)
            return default_cfg
        mtime = os.path.getmtime(CONFIG_FILE)
        if mtime > _config_cache["mtime"]:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                _config_cache["data"] = _migrate_config(json.load(f))
            _config_cache["mtime"] = mtime
    except Exception:
        pass
    return _config_cache["data"] or {}


def save_config(config: dict) -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        _config_cache["data"] = config
        _config_cache["mtime"] = os.path.getmtime(CONFIG_FILE)
    except Exception:
        pass


def _build_default_config() -> dict:
    config: dict = {"lang": "auto", "scan_ms": 2000}
    tasks_dir = os.path.join(BASE_DIR, "tasks")
    if not os.path.isdir(tasks_dir):
        return config

    all_names = set(os.listdir(tasks_dir))
    ordered_names = [n for n in _TASK_ORDER if n in all_names]
    for extra in sorted(all_names - set(_TASK_ORDER)):
        ordered_names.append(extra)

    for name in ordered_names:
        task_path = os.path.join(tasks_dir, name, "task.py")
        if not os.path.isfile(task_path):
            continue
        if name == "anti_afk":
            config["anti_afk"] = {"enabled": False, "interval_min": 10, "key": "enter"}
            continue
        mod = _load_task_module(name)
        if mod is None:
            continue
        task_cls = getattr(mod, "Task", None)
        if task_cls is None:
            continue
        group = getattr(task_cls, "group", None)
        defaults = getattr(task_cls, "default_config", {})
        task_cfg = {"enabled": False, "scan_ms": 500}
        task_cfg.update(defaults)
        if group:
            if group not in config:
                config[group] = {}
            sub_name = name[len(group) + 1:] if name.startswith(f"{group}_") else name
            config[group][sub_name] = task_cfg
        else:
            config[name] = task_cfg

    return config


def detect_game_language() -> str:
    global _detected_lang_cache
    if _detected_lang_cache is not None:
        return _detected_lang_cache

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            steam_path, _ = winreg.QueryValueEx(key, "SteamPath")

        vdf_path = os.path.join(steam_path, "steamapps", "libraryfolders.vdf")
        if not os.path.exists(vdf_path):
            manifest_path = os.path.join(
                steam_path, "steamapps", f"appmanifest_{_GTA5_APPID}.acf"
            )
            if os.path.exists(manifest_path):
                lang = _read_acf_language(manifest_path)
                if lang:
                    _detected_lang_cache = lang
                    return _detected_lang_cache
            _detected_lang_cache = "en_US"
            return _detected_lang_cache

        library_paths = _parse_library_folders(vdf_path)
        search_paths = [os.path.join(steam_path, "steamapps")] + [
            os.path.join(p, "steamapps") for p in library_paths
        ]

        for sp in search_paths:
            manifest_path = os.path.join(sp, f"appmanifest_{_GTA5_APPID}.acf")
            if os.path.exists(manifest_path):
                lang = _read_acf_language(manifest_path)
                if lang:
                    _detected_lang_cache = lang
                    return _detected_lang_cache

        _detected_lang_cache = "en_US"
        return _detected_lang_cache
    except Exception:
        _detected_lang_cache = "en_US"
        return _detected_lang_cache


def _parse_library_folders(vdf_path: str) -> list[str]:
    with open(vdf_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    paths = []
    for m in re.finditer(r'"path"\s+"(.+?)"', content):
        p = m.group(1).replace("\\\\", "\\")
        if os.path.isdir(p):
            paths.append(p)
    return paths


def _read_acf_language(acf_path: str) -> str | None:
    with open(acf_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    m = re.search(r'"language"\s+"(\w+)"', content)
    if not m:
        return None
    steam_lang = m.group(1)
    return _STEAM_LANG_MAP.get(steam_lang, "en_US")


def resolve_game_language(config_lang: str) -> str:
    if config_lang != "auto":
        return config_lang
    return detect_game_language()
