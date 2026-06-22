"""Lightweight internationalization (i18n).

Design: Spanish is the SOURCE language — the literal Spanish string in the code IS the
translation key. `t("Guardar")` returns "Save" in English mode and "Guardar" otherwise.
This keeps the code readable and means a missing translation degrades gracefully to Spanish
instead of showing a bare key.

Strings with runtime values use `{}` placeholders and `.format()` at the call site, e.g.
    t("«{n}» ya no comparte la carpeta").format(n=name)
so the template (the key) is what gets translated, not the interpolated result.

Language resolution: an explicit preference ("es"/"en") wins; "auto"/None falls back to the
OS language; any non-Spanish OS defaults to English.
"""
from __future__ import annotations

import locale
import os
from typing import Optional

from .translations_en import EN as _EN

_SUPPORTED = ("es", "en")
_SOURCE = "es"               # the language the code is written in
_lang = _SOURCE              # current active language
_TRANSLATIONS = {"en": _EN}  # source ("es") needs no table


def detect_os_language() -> str:
    """Best-effort OS language → 'es' or 'en' (anything non-Spanish → 'en')."""
    def _norm(code: str) -> Optional[str]:
        code = (code or "").strip().lower().replace("-", "_").split(".")[0].split("_")[0]
        if code == "es":
            return "es"
        if code:
            return "en"
        return None

    # 1) POSIX-style environment variables (also honoured on WSL/macOS/Linux).
    for env in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        v = os.environ.get(env)
        if v:
            r = _norm(v.split(":")[0])
            if r:
                return r
    # 2) Python's locale (reads the OS/registry on Windows).
    try:
        for loc in (locale.getlocale()[0], locale.getdefaultlocale()[0]):  # noqa: locale dep ok
            r = _norm(loc or "")
            if r:
                return r
    except Exception:
        pass
    # 3) Windows UI language as a last resort.
    try:
        import ctypes  # noqa: imported lazily; only on Windows
        lid = ctypes.windll.kernel32.GetUserDefaultUILanguage()  # type: ignore[attr-defined]
        # Spanish primary language id is 0x0A.
        return "es" if (lid & 0x3FF) == 0x0A else "en"
    except Exception:
        return "en"


def resolve_language(pref: Optional[str]) -> str:
    """Map a stored/CLI preference to a concrete supported language, in this precedence:
      1. the language explicitly set in the program ('es'/'en') wins;
      2. otherwise ('auto'/None → e.g. first run) use the OS language;
      3. if the OS language can't be detected, fall back to English.
    Steps 2–3 are handled by detect_os_language()."""
    if pref in _SUPPORTED:
        return pref  # type: ignore[return-value]
    return detect_os_language()


def set_language(lang: Optional[str]) -> None:
    """Activate a language. Accepts 'es'/'en'/'auto'/None (auto → OS detection)."""
    global _lang
    _lang = resolve_language(lang)


def get_language() -> str:
    return _lang


def available_languages() -> tuple[str, ...]:
    return _SUPPORTED


def t(s: str) -> str:
    """Translate a source (Spanish) string to the active language; identity for the source."""
    if _lang == _SOURCE:
        return s
    return _TRANSLATIONS.get(_lang, {}).get(s, s)


# Common shorthand.
_ = t
