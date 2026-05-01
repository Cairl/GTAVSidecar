import json
import os


_translations: dict[str, str] = {}
_fallback: dict[str, str] = {}


def i18n_init(lang: str, base_dir: str) -> None:
    global _translations, _fallback

    en_path = os.path.join(base_dir, "locales", "en_US.json")
    if os.path.exists(en_path):
        with open(en_path, "r", encoding="utf-8") as f:
            _fallback = json.load(f)

    lang_path = os.path.join(base_dir, "locales", f"{lang}.json")
    if os.path.exists(lang_path):
        with open(lang_path, "r", encoding="utf-8") as f:
            _translations = json.load(f)
    else:
        _translations = _fallback.copy()


def translate(key: str, **kwargs) -> str:
    text = _translations.get(key) or _fallback.get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text
