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

_INJECT_SYMBOLS = {}


def set_inject_symbols(symbols: dict) -> None:
    _INJECT_SYMBOLS.clear()
    _INJECT_SYMBOLS.update(symbols)


def _is_task_group(value):
    if not isinstance(value, dict) or not value:
        return False
    return all(isinstance(v, dict) for v in value.values())


def _flatten_task_configs(config):
    from . import task_registry
    registry = task_registry.TaskRegistry(BASE_DIR)
    result = {}

    for name in registry.get_task_names():
        info = registry.get_task_info(name)
        if info is None:
            continue

        if info.group:
            group_cfg = config.get(info.group, {})
            sub_name = name[len(info.group) + 1:] if name.startswith(f"{info.group}_") else name
            result[name] = group_cfg.get(sub_name, {})
        else:
            result[name] = config.get(name, {})

    return result


def _get_task_config(config, task_name):
    from . import task_registry
    registry = task_registry.TaskRegistry(BASE_DIR)
    info = registry.get_task_info(task_name)
    if info is None:
        return None

    if info.group:
        group_cfg = config.get(info.group, {})
        sub_name = task_name[len(info.group) + 1:] if task_name.startswith(f"{info.group}_") else task_name
        sub_value = group_cfg.get(sub_name)
        return sub_value if isinstance(sub_value, dict) else {}
    else:
        value = config.get(task_name)
        return value if isinstance(value, dict) and not _is_task_group(value) else {}


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
    from . import task_registry
    registry = task_registry.TaskRegistry(BASE_DIR)
    return registry.build_config()


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
