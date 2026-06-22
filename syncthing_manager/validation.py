"""
Pre-flight validation of rename inputs, aware of each target device's OS.

A name that is perfectly valid on Linux can be rejected by Windows (reserved
names, forbidden characters, trailing dot/space). Validating per-device — using
the OS we detected during discovery — lets us warn the user *before* a rename
fails halfway on one machine. When the OS is unknown we assume Windows (the
strictest) so we never wave through a name that would later fail there.
"""
from __future__ import annotations

import re
from typing import Optional

from .i18n import t as _T

# Characters Windows forbids in a path component.
_WIN_INVALID_CHARS = set('<>:"/\\|?*')

# Names Windows reserves regardless of extension or case (CON, COM1.txt, …).
_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL"} \
    | {f"COM{i}" for i in range(1, 10)} \
    | {f"LPT{i}" for i in range(1, 10)}

_WINDOWS_ABS_RE = re.compile(r'^[A-Za-z]:[/\\]|^\\\\')


def is_windows_os(os_type: Optional[str]) -> bool:
    """Treat an unknown OS as Windows so validation stays on the strict side. macOS is POSIX
    (like Linux), so it is NOT treated as Windows."""
    return os_type not in ("linux", "macos")


def differs_only_in_case(old: str, new: str) -> bool:
    """True if old and new are the same text except for letter case."""
    return bool(old) and bool(new) and old != new and old.lower() == new.lower()


def validate_dir_name(name: str, os_type: Optional[str]) -> list[str]:
    """
    Validate a *bare* directory name (a single path component, not a full path)
    for the given device OS. Returns a list of human-readable problems; empty = OK.
    """
    problems: list[str] = []
    if not name or not name.strip():
        return [_T("el nombre está vacío")]
    # '.' and '..' are path-traversal segments, not folder names: as a bare dir-name they'd make
    # _resolve_new_path move the folder INTO its parent/grandparent. Windows already rejects them
    # via the trailing-dot rule, but POSIX would let them through — refuse explicitly on every OS.
    if name.strip() in (".", ".."):
        return [_T("«.» y «..» no son nombres de carpeta válidos")]
    if "\x00" in name:
        problems.append(_T("contiene un carácter NUL"))

    if is_windows_os(os_type):
        bad = sorted(set(name) & _WIN_INVALID_CHARS)
        if bad:
            problems.append(_T("caracteres no válidos en Windows: ") + " ".join(bad))
        stem = name.split(".", 1)[0].strip().upper()
        if stem in _WIN_RESERVED:
            problems.append(_T("«{}» es un nombre reservado en Windows").format(name))
        if name != name.rstrip(" ."):
            problems.append(_T("no puede terminar en espacio ni punto (Windows lo recorta)"))
        if len(name) > 255:
            problems.append(_T("el nombre es demasiado largo (>255 caracteres)"))
    else:
        if "/" in name:
            problems.append(_T("no puede contener «/»"))
        if len(name.encode("utf-8")) > 255:
            problems.append(_T("el nombre es demasiado largo (>255 bytes)"))

    return problems


def validate_new_path_input(path_input: str, os_type: Optional[str]) -> list[str]:
    """
    Validate the user's new-path field, which may be a bare name OR an absolute path.
    For an absolute path we check it matches the device's OS path style and validate
    its last component; for a bare name we validate the name directly.
    """
    problems: list[str] = []
    if not path_input or not path_input.strip():
        return [_T("la ruta/el nombre está vacío")]

    is_abs = bool(re.match(r'^/', path_input) or _WINDOWS_ABS_RE.search(path_input))
    if is_abs:
        looks_windows = bool(_WINDOWS_ABS_RE.search(path_input))
        if looks_windows and not is_windows_os(os_type):
            problems.append(_T("es una ruta de Windows (C:\\…) pero este dispositivo no es Windows"))
        elif not looks_windows and is_windows_os(os_type):
            problems.append(_T("es una ruta POSIX (/…) pero este dispositivo es Windows"))
        leaf = re.split(r'[/\\]', path_input.rstrip("/\\"))[-1]
    else:
        leaf = path_input

    problems += validate_dir_name(leaf, os_type)
    # MAX_PATH on Windows (~260) for the whole absolute path
    if is_abs and is_windows_os(os_type) and len(path_input) > 259:
        problems.append(_T("la ruta supera el límite de longitud de Windows (~260)"))
    return problems
