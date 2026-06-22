from __future__ import annotations

import logging
import queue
import re
import sys
import threading
import tkinter as tk

logger = logging.getLogger(__name__)
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Callable, Optional

from .. import config as appconfig
from .. import i18n
from ..i18n import t as _T
from ..credentials import load_credentials, needs_master_password, save_credentials
from ..discovery import (
    discover_devices, probe_device, probe_device_manual,
    detect_local_syncthing, resolve_live_ip,
    _query_hub_devices, _query_hub_devices_via_remote,
)
from ..generate import agent_template_available, generate_multi_agent_file
from ..models import DeviceInfo, FolderConfig, RenameResult
from ..renamer import is_absolute_path, rename_all_devices, resolve_remote_folder_path
from ..syncthing import SyncthingClient

_IS_WIN = sys.platform == "win32"
WIN_W   = 760 if _IS_WIN else 900
WIN_H   = 560 if _IS_WIN else 650
PAD     = 14
BLUE    = "#1565C0"
STEPS   = ["Conexión", "Carpeta", "Dispositivos", "Nombres", "Topología", "Ejecutar"]

# Segoe UI is Windows-only; use DejaVu Sans on Linux/Mac (virtually always installed)
_FONT      = "Segoe UI"  if _IS_WIN else "DejaVu Sans"
_MONO      = "Consolas"  if _IS_WIN else "DejaVu Sans Mono"
_STEPS_SZ  = 8  # header auto-sizes; same point size works on all platforms


# Pure topology-graph model lives in topology.py (no tkinter) so the headless CLI can
# reuse it. The GUI imports the helpers it draws with from there.
from ..topology import (  # noqa: E402
    _device_kind, _ROLE_LABELS,
    _copy_topology, _arrow_from_senders, _derive_roles,
    _build_topology, _reconcile_topology, _edge_arrow,
    _topology_delta, _detect_topology_issues, _topology_issues_detailed, orphaned_node_ids,
    _topology_to_json, _topology_from_json, _merge_remembered,
    _resolve_name_map, _name_is_placeholder,
)


# ── i18n shim ───────────────────────────────────────────────────────────────
# The GUI is written in Spanish (the source language). Rather than wrap every one of the
# hundreds of widget strings by hand, we route the text that flows through tkinter's common
# sinks — widget `text=`, window titles, menu labels and message boxes — through the
# translation catalog. COMPLETE strings present in the catalog get translated; interpolated
# or unknown strings pass through unchanged (degrading to Spanish). This is a NO-OP when the
# active language is the source (Spanish), so it costs nothing in the default case.
_I18N_INSTALLED = False


def _install_tk_i18n() -> None:
    global _I18N_INSTALLED
    if _I18N_INSTALLED or i18n.get_language() == "es":
        return
    _I18N_INSTALLED = True
    T = i18n.t

    def _tr(v):
        return T(v) if isinstance(v, str) else v

    def _patch_text(cls):
        _init = cls.__init__

        def __init__(self, *a, **kw):
            if isinstance(kw.get("text"), str):
                kw["text"] = T(kw["text"])
            _init(self, *a, **kw)
        cls.__init__ = __init__

        _cfg = cls.configure

        def configure(self, cnf=None, **kw):
            if isinstance(cnf, dict) and isinstance(cnf.get("text"), str):
                cnf = dict(cnf)
                cnf["text"] = T(cnf["text"])
            if isinstance(kw.get("text"), str):
                kw["text"] = T(kw["text"])
            return _cfg(self, cnf, **kw)
        cls.configure = configure
        cls.config = configure

    for _cls in (tk.Label, tk.Button, tk.Checkbutton, tk.Radiobutton, tk.Menubutton,
                 tk.LabelFrame, ttk.Label, ttk.Button, ttk.Checkbutton, ttk.Radiobutton,
                 ttk.Menubutton, ttk.LabelFrame):
        _patch_text(_cls)

    # Canvas item text (topology badges/legends drawn with create_text). Device labels and
    # other interpolated strings aren't in the catalog, so they pass through unchanged.
    _create_text = tk.Canvas.create_text

    def _canvas_text(self, *a, **kw):
        if isinstance(kw.get("text"), str):
            kw["text"] = T(kw["text"])
        return _create_text(self, *a, **kw)
    tk.Canvas.create_text = _canvas_text

    # Treeview column headers (table titles): tree.heading(col, text="…").
    _heading = ttk.Treeview.heading

    def _tree_heading(self, column, option=None, **kw):
        if isinstance(kw.get("text"), str):
            kw["text"] = T(kw["text"])
        return _heading(self, column, option, **kw)
    ttk.Treeview.heading = _tree_heading

    # Menu entry labels (add_command / add_cascade / add_radiobutton / …, all go via add).
    _add = tk.Menu.add

    def _menu_add(self, itemType, cnf={}, **kw):
        if isinstance(cnf, dict) and isinstance(cnf.get("label"), str):
            cnf = dict(cnf)
            cnf["label"] = T(cnf["label"])
        if isinstance(kw.get("label"), str):
            kw["label"] = T(kw["label"])
        return _add(self, itemType, cnf, **kw)
    tk.Menu.add = _menu_add

    # Window titles (Tk + Toplevel both route through Wm.wm_title).
    _wm_title = tk.Wm.wm_title

    def _title(self, string=None):
        return _wm_title(self, T(string) if isinstance(string, str) else string)
    tk.Wm.wm_title = _title
    tk.Wm.title = _title

    # Message boxes: translate title + message (both passed positionally in this codebase).
    import functools
    for _name in ("showinfo", "showwarning", "showerror", "askquestion",
                  "askyesno", "askokcancel", "askretrycancel"):
        _orig = getattr(messagebox, _name, None)
        if _orig is None:
            continue

        def _make(orig):
            @functools.wraps(orig)
            def _wrapped(title=None, message=None, **kw):
                return orig(_tr(title), _tr(message), **kw)
            return _wrapped
        setattr(messagebox, _name, _make(_orig))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _default_url() -> str:
    # Always default to loopback; detect_local_syncthing() refines this at connect
    # time (incl. the WSL→Windows-host fallback and the exact scheme/port from config).
    return "https://127.0.0.1:8384"


# ── Cross-platform checkbox widget ───────────────────────────────────────────

class _CheckBox(tk.Frame):
    """Canvas-drawn checkbox sized to the actual rendered font — Linux only."""

    def __init__(self, master, *, variable: tk.BooleanVar,
                 text: str = "", command=None, state: str = "normal", **kw):
        try:
            bg = kw.pop("bg", master.cget("bg"))
        except Exception:
            bg = "white"
        super().__init__(master, bg=bg, **kw)
        self._var = variable
        self._cmd = command
        self._enabled = state != "disabled"

        try:
            import tkinter.font as tkfont
            self._s = max(13, tkfont.Font(family=_FONT, size=9).metrics("linespace"))
        except Exception:
            self._s = 14

        self._cv = tk.Canvas(self, width=self._s, height=self._s, bg=bg,
                             highlightthickness=0, cursor="hand2")
        self._cv.pack(side=tk.LEFT, padx=(0, 5))
        self._cv.bind("<Button-1>", self._on_click)

        if text:
            lbl = tk.Label(self, text=text, bg=bg, font=(_FONT, 9), cursor="hand2")
            lbl.pack(side=tk.LEFT)
            lbl.bind("<Button-1>", self._on_click)

        self._var.trace_add("write", lambda *_: self._draw())
        self._draw()

    def _on_click(self, _e=None):
        if not self._enabled:
            return
        self._var.set(not self._var.get())
        if self._cmd:
            self._cmd()

    def _draw(self):
        cv, s = self._cv, self._s
        cv.delete("all")
        checked = self._var.get()
        if not self._enabled:
            fill, border = "#e8e8e8", "#c0c0c0"
        elif checked:
            fill, border = BLUE, "#0d47a1"
        else:
            fill, border = "white", "#767676"
        cv.create_rectangle(1, 1, s - 1, s - 1, outline=border, fill=fill, width=1)
        if checked:
            # Proportional checkmark relative to box size
            x0 = int(s * 0.15); y0 = int(s * 0.50)
            xm = int(s * 0.42); ym = int(s * 0.78)
            x1 = int(s * 0.85); y1 = int(s * 0.18)
            lw = max(1, s // 6)
            cv.create_line(x0, y0, xm, ym, fill="white", width=lw)
            cv.create_line(xm, ym, x1, y1, fill="white", width=lw)

    def config(self, **kw):
        if "state" in kw:
            self._enabled = kw.pop("state") != "disabled"
            self._draw()
        super().config(**kw)

    configure = config


def _CheckButton(master, **kw):
    """On Windows uses native ttk.Checkbutton; on Linux uses the Canvas-drawn _CheckBox."""
    if _IS_WIN:
        kw.pop("bg", None)
        return ttk.Checkbutton(master, **kw)
    return _CheckBox(master, **kw)


# ── Master password dialog ────────────────────────────────────────────────────

def _ask_master_password(parent: tk.Tk, title: str = "Contraseña maestra",
                         confirm: bool = False) -> Optional[str]:
    """Modal dialog that returns the entered password, or None if cancelled."""
    result: list[Optional[str]] = [None]

    dlg = tk.Toplevel(parent)
    dlg.title(title)
    dlg.geometry(("420x230" if confirm else "420x190") if not _IS_WIN else ("380x200" if confirm else "380x160"))
    dlg.resizable(False, False)
    dlg.grab_set()
    dlg.configure(bg="white")

    tk.Label(dlg, text="🔑  Contraseña maestra", bg="white",
             font=(_FONT, 10, "bold")).pack(anchor="w", padx=16, pady=(14, 4))
    tk.Label(dlg, text="Se usa para cifrar/descifrar las credenciales guardadas.\n"
                        "No se almacena en ningún sitio.",
             bg="white", fg="#666", font=(_FONT, 8),
             justify="left").pack(anchor="w", padx=16)

    ttk.Separator(dlg, orient="horizontal").pack(fill=tk.X, padx=16, pady=8)

    grid = tk.Frame(dlg, bg="white")
    grid.pack(fill=tk.X, padx=16)

    tk.Label(grid, text="Contraseña:", bg="white", width=14, anchor="e").grid(
        row=0, column=0, sticky="e", pady=3)
    pw_v = tk.StringVar()
    ttk.Entry(grid, textvariable=pw_v, show="●", width=28).grid(
        row=0, column=1, sticky="w", padx=(8, 0), pady=3)

    pw2_v = tk.StringVar()
    if confirm:
        tk.Label(grid, text="Confirmar:", bg="white", width=14, anchor="e").grid(
            row=1, column=0, sticky="e", pady=3)
        ttk.Entry(grid, textvariable=pw2_v, show="●", width=28).grid(
            row=1, column=1, sticky="w", padx=(8, 0), pady=3)

    err_lbl = tk.Label(dlg, text="", bg="white", fg="#C62828", font=(_FONT, 8))
    err_lbl.pack(anchor="w", padx=16)

    btn_frm = tk.Frame(dlg, bg="white")
    btn_frm.pack(side=tk.BOTTOM, fill=tk.X, padx=16, pady=10)

    def on_ok():
        pw = pw_v.get()
        if not pw:
            err_lbl.config(text="La contraseña no puede estar vacía.")
            return
        if confirm and pw != pw2_v.get():
            err_lbl.config(text="Las contraseñas no coinciden.")
            return
        result[0] = pw
        dlg.destroy()

    ttk.Button(btn_frm, text="Aceptar", command=on_ok).pack(side=tk.RIGHT)
    ttk.Button(btn_frm, text="Cancelar", command=dlg.destroy).pack(side=tk.RIGHT, padx=(0, 6))
    dlg.bind("<Return>", lambda _: on_ok())

    parent.wait_window(dlg)
    return result[0]


# ── Main application ──────────────────────────────────────────────────────────

__all__ = ['BLUE', 'Callable', 'DeviceInfo', 'FolderConfig', 'Optional', 'PAD', 'Path', 'RenameResult', 'STEPS', 'SyncthingClient', 'WIN_H', 'WIN_W', '_CheckBox', '_CheckButton', '_FONT', '_I18N_INSTALLED', '_IS_WIN', '_MONO', '_ROLE_LABELS', '_STEPS_SZ', '_T', '_arrow_from_senders', '_ask_master_password', '_build_topology', '_copy_topology', '_default_url', '_derive_roles', '_detect_topology_issues', '_device_kind', '_edge_arrow', '_install_tk_i18n', '_merge_remembered', '_name_is_placeholder', 'orphaned_node_ids', '_query_hub_devices', '_query_hub_devices_via_remote', '_reconcile_topology', '_resolve_name_map', '_topology_delta', '_topology_issues_detailed', '_topology_from_json', '_topology_to_json', 'agent_template_available', 'appconfig', 'detect_local_syncthing', 'discover_devices', 'filedialog', 'generate_multi_agent_file', 'i18n', 'is_absolute_path', 'load_credentials', 'logger', 'logging', 'messagebox', 'needs_master_password', 'probe_device', 'probe_device_manual', 'queue', 're', 'rename_all_devices', 'resolve_live_ip', 'resolve_remote_folder_path', 'save_credentials', 'scrolledtext', 'sys', 'threading', 'tk', 'ttk']
