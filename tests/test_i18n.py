"""i18n: language detection, resolution and translation."""
import pytest

from syncthing_manager import i18n
from syncthing_manager.translations_en import EN


@pytest.fixture(autouse=True)
def _restore_language():
    prev = i18n.get_language()
    yield
    i18n.set_language(prev)


def test_t_identity_in_source_language():
    i18n.set_language("es")
    assert i18n.t("Guardar") == "Guardar"
    assert i18n.t("cualquier cosa no traducida") == "cualquier cosa no traducida"


def test_t_translates_in_english():
    i18n.set_language("en")
    assert i18n.t("Guardar") == "Save"
    assert i18n.t("Topología") == "Topology"


def test_t_falls_back_to_source_when_missing():
    i18n.set_language("en")
    assert i18n.t("una cadena sin traducción en el catálogo") == \
        "una cadena sin traducción en el catálogo"


def test_resolve_language():
    assert i18n.resolve_language("en") == "en"
    assert i18n.resolve_language("es") == "es"
    # "auto"/None/garbage fall back to OS detection (a supported language).
    assert i18n.resolve_language("auto") in i18n.available_languages()
    assert i18n.resolve_language(None) in i18n.available_languages()
    assert i18n.resolve_language("zz") in i18n.available_languages()


def test_detect_os_language_from_env(monkeypatch):
    for v in ("LC_ALL", "LC_MESSAGES", "LANGUAGE"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    assert i18n.detect_os_language() == "en"
    monkeypatch.setenv("LANG", "es_ES.UTF-8")
    assert i18n.detect_os_language() == "es"
    monkeypatch.setenv("LANG", "fr_FR.UTF-8")   # any non-Spanish → English
    assert i18n.detect_os_language() == "en"


def test_set_language_auto_resolves_to_supported():
    i18n.set_language("auto")
    assert i18n.get_language() in i18n.available_languages()


def test_language_precedence(monkeypatch):
    """Order: explicit program setting → OS language (first run / 'auto') → English."""
    # 1) An explicit program setting wins, regardless of the OS language.
    monkeypatch.setenv("LANG", "es_ES.UTF-8")
    assert i18n.resolve_language("en") == "en"
    assert i18n.resolve_language("es") == "es"
    # 2) First run / 'auto' follows the OS language.
    assert i18n.resolve_language("auto") == "es"
    monkeypatch.setenv("LANG", "de_DE.UTF-8")     # non-Spanish OS
    assert i18n.resolve_language(None) == "en"
    # 3) When the OS language can't be detected, fall back to English.
    for v in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr("locale.getlocale", lambda *a: (None, None))
    monkeypatch.setattr("locale.getdefaultlocale", lambda *a: (None, None))
    assert i18n.resolve_language("auto") == "en"


def test_catalog_entries_are_nonempty_strings():
    assert EN, "English catalog should not be empty"
    for k, v in EN.items():
        assert isinstance(k, str) and isinstance(v, str)
        assert k and v


def _placeholder_count(s: str) -> int:
    """Number of auto-numbered {} fields (the only form this catalog uses)."""
    import string
    return sum(1 for _lit, field, _spec, _conv in string.Formatter().parse(s)
               if field is not None)


def _extract_display_literals():
    """Every Spanish string that reaches the UI: _T() args, widget text=/label=, window
    titles, and messagebox positional args (the exact positions the i18n shim translates)."""
    import ast
    import re as _re
    from pathlib import Path
    pkg = Path(i18n.__file__).parent
    MB = {"showinfo", "showwarning", "showerror", "askquestion",
          "askyesno", "askokcancel", "askretrycancel", "title", "wm_title"}
    TR = {"_T", "t", "_"}
    out: dict[str, str] = {}

    def cs(node):
        return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None

    # CLI user-facing call sites (Typer + Rich + getpass). The string FIRST arg of these is
    # shown to the user, so it must be wrapped in _T() (→ captured via TR above) and present in
    # the EN catalog. Listing the raw calls here means an UNWRAPPED Spanish literal is flagged.
    def _cli_target(f) -> bool:
        if not isinstance(f, ast.Attribute):
            return False
        owner = f.value.id if isinstance(f.value, ast.Name) else None
        return (
            (owner == "typer" and f.attr in ("prompt", "confirm"))
            or (owner in ("console", "err_console") and f.attr in ("print", "status"))
            or (owner == "getpass" and f.attr == "getpass")
            # Rich table headers: <table>.add_column("Header", …) — any owner var.
            or f.attr == "add_column"
        )

    for path in pkg.rglob("*.py"):
        if path.name == "translations_en.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
            if name in TR or name in MB or _cli_target(f):
                for a in node.args:
                    s = cs(a)
                    if s:
                        out.setdefault(s, f"{path.name}:{node.lineno}")
            for kw in node.keywords:
                # text=/label= (tkinter) and help= (Typer options/commands) reach the user.
                if kw.arg in ("text", "label", "help"):
                    s = cs(kw.value)
                    if s:
                        out.setdefault(s, f"{path.name}:{node.lineno}")
    # Keep only strings with actual letters (skip pure symbol/emoji/format-only fragments).
    return {s: loc for s, loc in out.items()
            if _re.search(r"[A-Za-zÁÉÍÓÚáéíóúñÑ¿¡üÜ]", s)}


# Language-neutral display strings: identical in ES and EN, so the graceful source fallback
# already shows correct English — they intentionally have no catalog entry.
_LANG_NEUTRAL = {
    "Device ID:", "Rescan (s):", "Syncthing Folder Rename", "Syncthing Rename Agent", "✓ cred.",
    # CLI table headers that are identical in Spanish and English (technical terms).
    "API", "Config", "ID", "IP", "Label", "#",
}


def test_english_catalog_covers_every_ui_string():
    """Full ES→EN coverage: no user-facing Spanish string may be missing from the catalog
    (it would render in Spanish in English mode). Guards against future drift."""
    missing = {s: loc for s, loc in _extract_display_literals().items()
               if s not in EN and s not in _LANG_NEUTRAL}
    assert not missing, (
        f"{len(missing)} UI string(s) missing an English translation:\n"
        + "\n".join(f"  [{loc}] {s!r}" for s, loc in sorted(missing.items())))


def test_no_untranslated_spanish_literals_in_gui():
    """Exhaustive guard: NO Spanish display literal in the GUI package may be absent from the
    catalog. Scans every string constant (skipping docstrings) for Spanish markers and asserts
    none is missing from EN — except a small allowlist of NON-display tokens:
      • 'Mi dispositivo'   — a width-measuring sample, never rendered.
      • 'agente'           — a _device_kind logic token compared with ==, not shown.
      • 'sin enlaces' / 'disco NO borrado' — substrings compared with `in`/`not in`; translating
        them would break the comparison (their DISPLAY is deferred — see notes)."""
    import ast
    import re as _re
    from pathlib import Path
    pkg = Path(i18n.__file__).parent / "gui"
    ALLOW = {"Mi dispositivo", "agente", "sin enlaces", "disco NO borrado"}
    ES = _re.compile(
        r"[áéíóúñ¿¡]|\b(de|la|el|los|las|un|una|sin|con|por|para|que|al|del|no|su|este|esta|"
        r"carpeta|dispositivo|disco|clave|usuario|puerto|contraseña|nombre|ruta|reanud|conectad|"
        r"desconocid|opcional|acceso|cambio|guardar|añad|borrar|quitar|vincul|configurad|necesari|"
        r"aplica|seleccion|mover|enlace|equipo|exploración|pasiv|agente|crear|nuev|paso|pausad|"
        r"ningún|aún|dejar|revert|deshac|todas|todos|previsualiz|inválid|válid|conect|propia|"
        r"directamente|primero|ocurra|máquina)\b", _re.I)

    def looks_es(s):
        return bool(s and len(s) >= 3 and ES.search(s))

    def is_internal(s):
        return "://" in s or s.startswith("--") or "%s" in s or bool(_re.fullmatch(r"[\W\d_]+", s or ""))

    missing = {}
    for path in pkg.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        doc = set()
        for n in ast.walk(tree):
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                b = n.body
                if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant) \
                        and isinstance(b[0].value.value, str):
                    doc.add(id(b[0].value))
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc:
                s = n.value
                if looks_es(s) and not is_internal(s) and s not in EN and s not in EN.values() \
                        and s not in ALLOW:
                    missing.setdefault(s, f"{path.name}:{n.lineno}")
    assert not missing, (
        f"{len(missing)} untranslated Spanish literal(s) in the GUI:\n"
        + "\n".join(f"  [{loc}] {s!r}" for s, loc in sorted(missing.items())))


def test_no_bare_spanish_in_non_translating_sinks():
    """Guard the blind spot of the catalog-coverage test: a Spanish string that IS in the
    catalog but is passed UNWRAPPED to a sink the shim does NOT auto-translate (the Text-widget
    writers `w`/`log_line`/`insert`, and `Combobox.set`) renders in Spanish under English. Such
    a literal must be wrapped in `_T(...)` (then its arg is a Call, not a bare Constant)."""
    import ast
    import re as _re
    from pathlib import Path
    pkg = Path(i18n.__file__).parent
    NON_TR = {"w", "log_line", "insert", "set"}
    ES = _re.compile(
        r"[áéíóúñ¿¡]|\b\w+(ando|iendo|ándo|iéndo)\b|\b(de|la|el|los|las|un|una|sin|con|para|que|"
        r"del|carpeta|dispositivo|disco|clave|usuario|puerto|contraseña|nombre|ruta|enlace|equipo|"
        r"agente|crear|gener|ejecut|reanud|pausad|aceptar|omitir|inconsistenc|accesibl|gestionar|"
        r"elige|autocompletar|directamente|migrad|desconocid|configurad)\b", _re.I)
    found = {}
    for path in pkg.glob("gui/*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            fn = n.func
            name = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else "")
            if name not in NON_TR:
                continue
            for a in n.args:
                if isinstance(a, ast.Constant) and isinstance(a.value, str) \
                        and len(a.value) >= 3 and ES.search(a.value):
                    found.setdefault(a.value, f"{path.name}:{a.lineno}")
    assert not found, (
        f"{len(found)} bare Spanish literal(s) in non-translating sinks (wrap in _T):\n"
        + "\n".join(f"  [{loc}] {s!r}" for s, loc in sorted(found.items())))


def test_gui_table_headers_are_translated():
    """GUI Treeview column headers are passed as `tree.heading(col, text=col)` — a variable,
    so the AST literal scanner can't see them. List them explicitly: every non-neutral header
    must have an English translation (the shim now routes Treeview.heading text= through it)."""
    headers = {
        "Nombre", "IP", "Remoto", "API", "SO", "Ruta en disco",   # page_devices
        "#", "ID", "Label", "Ruta local", "Dispositivos",         # page_folder
    }
    missing = {h for h in headers if h not in EN and h not in _LANG_NEUTRAL}
    assert not missing, f"GUI table headers missing an English translation: {sorted(missing)}"


def test_translation_placeholders_match_source():
    """Every English value must have the SAME number of positional {} placeholders as its
    Spanish key. A mismatch means a call site does .format(...) against the Spanish source
    (a lookup miss) or — worse — IndexErrors at runtime. Guards against catalog drift."""
    mismatches = [(k, _placeholder_count(k), _placeholder_count(v))
                  for k, v in EN.items()
                  if _placeholder_count(k) != _placeholder_count(v)]
    assert not mismatches, f"placeholder count drift (key vs value): {mismatches}"
