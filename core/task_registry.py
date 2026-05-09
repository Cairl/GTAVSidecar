import os
import json
from dataclasses import dataclass, field


@dataclass
class TaskInfo:
    name: str
    display_name_key: str
    group: str | None
    order: int
    default_config: dict
    locale_overrides: dict[str, dict] = field(default_factory=dict)
    has_manifest: bool = False


class TaskRegistry:
    _DEFAULT_ORDER = 999

    def __init__(self, base_dir: str):
        self._base_dir = base_dir
        self._tasks: dict[str, TaskInfo] = {}
        self._scan()

    def _scan(self) -> None:
        tasks_dir = os.path.join(self._base_dir, "tasks")
        if not os.path.isdir(tasks_dir):
            return

        for name in sorted(os.listdir(tasks_dir)):
            task_path = os.path.join(tasks_dir, name, "task.py")
            if not os.path.isfile(task_path):
                continue
            info = self._load_task_info(name)
            if info is not None:
                self._tasks[name] = info

    def _load_task_info(self, name: str) -> TaskInfo | None:
        manifest_path = os.path.join(self._base_dir, "tasks", name, "manifest.json")
        if os.path.exists(manifest_path):
            return self._load_from_manifest(name, manifest_path)
        return self._load_from_task_py(name)

    def _load_from_manifest(self, name: str, path: str) -> TaskInfo | None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return self._load_from_task_py(name)

        return TaskInfo(
            name=name,
            display_name_key=data.get("display_name_key", f"task.{name}"),
            group=data.get("group"),
            order=data.get("order", self._DEFAULT_ORDER),
            default_config=data.get("default_config", {}),
            locale_overrides=data.get("locales", {}),
            has_manifest=True,
        )

    def _load_from_task_py(self, name: str) -> TaskInfo | None:
        from . import config as _cfg

        mod = _cfg._load_task_module(name)
        if mod is None:
            return None

        task_cls = getattr(mod, "Task", None)
        if task_cls is None:
            return None

        group = getattr(task_cls, "group", None)
        defaults = getattr(task_cls, "default_config", {})

        return TaskInfo(
            name=name,
            display_name_key=f"task.{name}",
            group=group,
            order=self._DEFAULT_ORDER,
            default_config=defaults,
            locale_overrides={},
            has_manifest=False,
        )

    def get_task_names(self) -> list[str]:
        return sorted(self._tasks.keys(), key=lambda n: self._tasks[n].order)

    def get_task_info(self, name: str) -> TaskInfo | None:
        return self._tasks.get(name)

    def get_grouped_tasks(self) -> dict[str | None, list[str]]:
        groups: dict[str | None, list[str]] = {}
        for name in self.get_task_names():
            info = self._tasks[name]
            group = info.group
            if group not in groups:
                groups[group] = []
            groups[group].append(name)
        return groups

    def get_display_name(self, name: str, lang: str) -> str:
        info = self._tasks.get(name)
        if info is None:
            return name

        if lang in info.locale_overrides:
            override = info.locale_overrides[lang].get(info.display_name_key)
            if override:
                return override

        from . import i18n as _i18n
        translated = _i18n.translate(info.display_name_key)
        if translated != info.display_name_key:
            return translated

        return name

    def build_config(self, existing: dict | None = None) -> dict:
        if existing is None:
            existing = {}

        config = {
            "lang": existing.get("lang", "auto"),
            "scan_ms": existing.get("scan_ms", 2000),
        }

        for name in self.get_task_names():
            info = self._tasks[name]

            default_cfg = {"enabled": False, "scan_ms": 500}
            default_cfg.update(info.default_config)

            existing_task_cfg = self._get_existing_task_config(existing, name, info.group)
            if existing_task_cfg is not None:
                merged = default_cfg.copy()
                merged.update(existing_task_cfg)
                task_cfg = merged
            else:
                task_cfg = default_cfg.copy()

            if info.group:
                if info.group not in config:
                    config[info.group] = {}
                sub_name = self.extract_sub_name(name, info.group)
                config[info.group][sub_name] = task_cfg
            else:
                config[name] = task_cfg

        return config

    def _get_existing_task_config(self, config: dict, task_name: str, group: str | None) -> dict | None:
        if group:
            group_cfg = config.get(group)
            if isinstance(group_cfg, dict):
                sub_name = self.extract_sub_name(task_name, group)
                sub_value = group_cfg.get(sub_name)
                if isinstance(sub_value, dict):
                    return sub_value
        else:
            value = config.get(task_name)
            if isinstance(value, dict) and not self.is_task_group(value):
                return value
        return None

    @staticmethod
    def is_task_group(value):
        if not isinstance(value, dict) or not value:
            return False
        return all(isinstance(v, dict) for v in value.values())

    @staticmethod
    def extract_sub_name(task_name: str, group: str) -> str:
        return task_name[len(group) + 1:] if task_name.startswith(f"{group}_") else task_name

    def apply_locale_overrides(self, lang: str, translations: dict) -> dict:
        result = translations.copy()
        for info in self._tasks.values():
            if lang in info.locale_overrides:
                result.update(info.locale_overrides[lang])
        return result
