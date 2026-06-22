from __future__ import annotations
from .common import *  # noqa: F401,F403
from .settings import SettingsMixin
from .page_connect import ConnectPageMixin
from .page_folder import FolderPageMixin
from .page_devices import DiscoverPageMixin
from .page_names import NamesPageMixin
from .page_topology import TopologyPageMixin
from .page_execute import ExecutePageMixin


class App(tk.Tk, SettingsMixin, ConnectPageMixin, FolderPageMixin, DiscoverPageMixin, NamesPageMixin, TopologyPageMixin, ExecutePageMixin):
    def __init__(self):
        super().__init__()
        self.title("Syncthing Folder Rename")
        self.configure(bg="white")
        self._apply_window_icon()

        # Apply theme and derive all sizes from actual font metrics so the UI
        # looks correct at any DPI / system font size / GTK theme.
        self._win_w, self._win_h = WIN_W, WIN_H
        self._col_font = None   # set below; used for column-width measurement
        try:
            import tkinter.font as tkfont
            style = ttk.Style(self)
            if _IS_WIN:
                style.theme_use("vista")
            else:
                style.theme_use("clam")
                style.configure("TEntry", cursor="xterm")
                # Measure the font that will actually be rendered
                _fnt  = tkfont.Font(family=_FONT, size=9)
                _line = _fnt.metrics("linespace")   # pixels, e.g. 14 @ 96dpi, 22 @ 144dpi
                _hpad = max(4, _line // 4)
                style.configure("Treeview", rowheight=_line + 10, borderwidth=0)
                style.configure("Treeview.Heading", padding=(4, _hpad, 4, _hpad))
                # --- Make clam look closer to the Windows vista theme ---
                _btn_bg = "#f0f0f0"
                style.configure("TButton",
                    background=_btn_bg, relief="raised", padding=(8, 4),
                    bordercolor="#adadad",
                )
                style.map("TButton",
                    background=[("pressed", "#d0d0d0"), ("active", "#e5e5e5")],
                    relief=[("pressed", "sunken")],
                )
                style.configure("TEntry",
                    fieldbackground="white", bordercolor="#b0b0b0",
                )
                style.configure("Vertical.TScrollbar",
                    troughcolor="#e8e8e8", background="#c0c0c0",
                    arrowcolor="#505050",
                )
                style.map("Vertical.TScrollbar",
                    background=[("active", "#a0a0a0")],
                )
                style.map("Treeview",
                    background=[("selected", "#0078d7")],
                    foreground=[("selected", "white")],
                )
                style.configure("TCheckbutton", indicatormargin=(2, 2, 6, 2))
                style.map("TCheckbutton",
                    indicatorcolor=[("selected", "#1565C0"), ("!selected", "white")],
                    indicatorrelief=[("selected", "flat"), ("!selected", "groove")],
                )
                self._col_font = _fnt   # reuse for column-width measurement
                # Scale window proportionally if font is larger than 96dpi baseline (~14 px)
                _scale = _line / 14.0
                if _scale > 1.05:
                    sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
                    self._win_w = min(int(WIN_W * _scale), sw - 100)
                    self._win_h = min(int(WIN_H * _scale), sh - 100)
        except Exception:
            pass

        self.minsize(self._win_w, self._win_h)
        self.geometry(f"{self._win_w}x{self._win_h}")

        # Shared wizard state
        self.s: dict = {
            "advanced": bool(appconfig.get_setting("advanced", False)),
            "url": _default_url(),
            "api_key": "",
            "ssh_user": "",
            "ssh_key": "",
            "ssh_password": "",
            "ssh_port": 22,
            "client": None,
            "folders": [],
            "folder": None,
            "devices": [],
            "agent_devices": [],   # problem devices selected for agent generation
            "fcfg_pending": {},     # device_id -> advanced folder-config overrides to apply
            "path_overrides": {},   # device_id -> per-device new path/name (B4)
            "new_label": "",
            "new_path_input": "",
            "skip_path": False,
            "dry_run": False,
            "rename_id": False,
            "new_folder_id": "",
            "topology": None,       # current edited topology graph (built on entering the page)
            "topology_orig": None,  # snapshot of the original graph, for diffing
        }

        self._q: queue.Queue = queue.Queue()
        self._step = 0
        self._show_gen = 0   # incremented on every _show(); lets background threads detect stale pages
        self._devices_lock = threading.Lock()  # guards self.s["devices"] for cross-thread access
        self._probes_in_flight = 0   # >0 while a remote-access probe runs; gates the Devices "Siguiente"
        self._page_frame: Optional[tk.Frame] = None
        # Callable for "Next" per step (set by each page builder)
        self._next_handlers: list[Optional[Callable]] = [None] * len(STEPS)
        # Optional guard the Execute page registers when it has offline devices pending without
        # an agent: it's consulted before leaving the page (Back) or closing the app, shows the
        # stay/leave dialog, and reverts the un-applied offline-only edits on leave. None on every
        # other page (cleared in _show). Fail-open — see _leave_execute_ok.
        self._exec_leave_guard: Optional[Callable] = None
        # Intercept the window close so the leave-guard can run; without a guard it just closes.
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)

        self._build_header()
        ttk.Separator(self, orient="horizontal").pack(fill=tk.X)
        # Pin the footer (Back/Next) to the BOTTOM *before* the expanding body, so a tall
        # page can never push the nav buttons off-screen — the body fills what's left.
        self._build_footer()
        ttk.Separator(self, orient="horizontal").pack(side=tk.BOTTOM, fill=tk.X)
        self._body = tk.Frame(self, bg="white")
        self._body.pack(fill=tk.BOTH, expand=True)

        self._show(0)
        self.after(50, self._drain)

    def _center_dialog(self, win):
        """Place a Toplevel centred over the MAIN window, so it opens on the same monitor
        as the program (not wherever the WM decides / where it was last)."""
        def _do():
            if not win.winfo_exists():
                return
            win.update_idletasks()
            rx, ry = self.winfo_rootx(), self.winfo_rooty()
            rw, rh = self.winfo_width(), self.winfo_height()
            ww = win.winfo_width() or win.winfo_reqwidth()
            wh = win.winfo_height() or win.winfo_reqheight()
            x = rx + max((rw - ww) // 2, 0)
            y = ry + max((rh - wh) // 3, 0)
            win.geometry(f"+{x}+{y}")
        win.after(10, _do)

    def _build_header(self):
        hdr = tk.Frame(self, bg=BLUE)
        hdr.pack(fill=tk.X)
        inner = tk.Frame(hdr, bg=BLUE)
        inner.pack(fill=tk.X, padx=PAD, pady=(8, 8))
        # Settings gear, fixed top-right.
        tk.Button(inner, text="⚙", bg=BLUE, fg="white", bd=0, font=(_FONT, 15),
                  activebackground=BLUE, activeforeground="#BBDEFB", cursor="hand2",
                  command=self._open_settings).pack(side=tk.RIGHT, anchor="n")
        box = tk.Frame(inner, bg=BLUE)
        box.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(box, text="Syncthing Folder Rename", bg=BLUE, fg="white",
                 font=(_FONT, 13, "bold")).pack(anchor="w", pady=(0, 2))
        self._steps_var = tk.StringVar()
        tk.Label(box, textvariable=self._steps_var, bg=BLUE, fg="#BBDEFB",
                 font=(_FONT, _STEPS_SZ), wraplength=self._win_w - 2 * PAD).pack(anchor="w")

    def _build_footer(self):
        ftr = tk.Frame(self, bg="#F5F5F5")
        ftr.pack(side=tk.BOTTOM, fill=tk.X)
        self._status_var = tk.StringVar()
        self._status_lbl = tk.Label(ftr, textvariable=self._status_var,
                                     bg="#F5F5F5", fg="#555",
                                     font=(_FONT, 9), anchor="w")
        self._status_lbl.pack(side=tk.LEFT, padx=PAD, fill=tk.X, expand=True)
        self._btn_next = ttk.Button(ftr, text="Siguiente →", command=self._on_next)
        self._btn_next.pack(side=tk.RIGHT, padx=(4, PAD), pady=8)
        self._btn_back = ttk.Button(ftr, text="← Atrás", command=self._on_back, state="disabled")
        self._btn_back.pack(side=tk.RIGHT, padx=4, pady=8)

    def _cw(self, text: str, extra: int = 24) -> int:
        """Pixel width for a treeview column: measured text + padding. Font-metric-aware."""
        if self._col_font:
            return self._col_font.measure(text) + extra
        return len(text) * 9 + extra   # rough fallback if font not available

    def _update_steps(self, step: int):
        parts = []
        for i, name in enumerate(STEPS):
            name = _T(name)   # step labels are translated at render time
            if i < step:
                parts.append(f"✓ {name}")
            elif i == step:
                parts.append(f"● {name}")
            else:
                parts.append(f"○ {name}")
        self._steps_var.set("  ".join(parts))

    def _show(self, step: int):
        self._exec_leave_guard = None   # only the Execute page re-registers it (per build)
        self._show_gen += 1          # invalidate all in-flight background threads
        self._step = step
        self._update_steps(step)
        self._btn_back.config(state="normal" if step > 0 else "disabled")
        self._btn_next.config(state="normal", text="Siguiente →")
        self._status_var.set("")
        self._status_lbl.config(fg="#555")

        if self._page_frame:
            self._page_frame.destroy()

        frame = tk.Frame(self._body, bg="white", padx=PAD, pady=PAD)
        frame.pack(fill=tk.BOTH, expand=True)
        self._page_frame = frame

        builders = [
            self._page_connect,
            self._page_folder,
            self._page_discover,
            self._page_rename,
            self._page_topology,
            self._page_execute,
        ]
        builders[step](frame)

    def _on_next(self):
        # On Execute, "Next" is "Cerrar" → also a way to leave the page; honor the leave-guard.
        # On every other page the guard is None, so this is a no-op there.
        if not self._leave_execute_ok():
            return
        h = self._next_handlers[self._step]
        if h:
            h()

    def _on_back(self):
        if self._step > 0:
            if not self._leave_execute_ok():
                return   # user chose to stay (or the guard handled it); don't navigate
            self._show(self._step - 1)

    def _leave_execute_ok(self) -> bool:
        """True if it's OK to leave the Execute page now. When the Execute page registered a
        leave-guard (offline devices pending without an agent), delegate to it: it shows the
        stay/leave dialog and, on leave, reverts the un-applied offline-only edits. Returns
        False only when the user chooses to STAY. Fail-open: no guard, or any error → allow
        leaving (never trap the user)."""
        g = self._exec_leave_guard
        if not g:
            return True
        try:
            return bool(g())
        except Exception:
            logger.debug("execute leave-guard error", exc_info=True)
            return True

    def _on_window_close(self):
        """WM_DELETE_WINDOW handler: let the Execute leave-guard run first; if the user doesn't
        choose to stay (or there's no guard), close normally."""
        if self._leave_execute_ok():
            self._maybe_prompt_orphan_cleanup(blocking=True)
            self.destroy()

    def _maybe_prompt_orphan_cleanup(self, blocking: bool = False) -> None:
        """If a folder was created NEW this session but never executed (an unconfigured local
        folder — a likely leftover from testing), offer to delete it. Default KEEP (a local-only
        folder is a valid outcome). Asked once PER FOLDER (whichever fires first: a folder SWITCH
        or app CLOSE) — a SECOND abandoned folder is asked about again. `blocking` (close) runs
        the delete synchronously, since daemon threads die at exit.

        Once-per-folder falls out of tracking a single `_pending_new_folder` and clearing it
        right after asking — no global 'already asked' flag, so the next abandoned folder prompts."""
        pend = self.s.get("_pending_new_folder")
        if not pend or not pend.get("id"):
            return
        self.s.pop("_pending_new_folder", None)      # handled → don't re-ask for THIS folder
        # Only a TRULY unconfigured folder is "basurilla". If the user added devices or edited the
        # topology — even without a real execute (e.g. only a dry-run preview) — it's intentional
        # work, so don't offer to delete it. (Runs before _reset_folder_scoped_state on a switch,
        # and on the current folder at close, so this state still belongs to the pending folder.)
        if self.s.get("manual_topo_nodes") or _topology_delta(
                self.s.get("topology_orig"), self.s.get("topology")).get("any"):
            return
        fid, lbl, path = pend["id"], pend.get("label") or pend["id"], pend.get("path")
        try:
            wants_delete = messagebox.askyesno(
                "Carpeta sin configurar",
                _T('Creaste «{}» pero no llegaste a configurarla (sin dispositivos ni '
                   'sincronización). ¿Borrarla?\n\nSi la conservas, queda como una carpeta '
                   'local en este equipo.').format(lbl),
                default="no", icon="question", parent=self)
        except Exception:
            return
        if not wants_delete:
            return
        client = self.s.get("client")
        if not client:
            return

        def _do():
            try:
                from ..renamer import delete_folder_on_device
                my_id = self.s.get("my_id") or client.get_my_device_id()
                dev = DeviceInfo(device_id=my_id or "local", name="local", ip="127.0.0.1",
                                 api_url=client.base_url, api_key=client.api_key,
                                 folder_path=path, ssh_reachable=False, api_reachable=True,
                                 is_local=True)
                delete_folder_on_device(dev, fid, delete_data=True)
            except Exception as _e:
                logger.debug("orphan-folder cleanup delete failed: %s", _e)
        if blocking:
            # App is exiting → run in a thread but JOIN with a short timeout so a hung/slow local
            # Syncthing (up to the 60s socket timeout) can't freeze the window close. If it doesn't
            # finish in time the daemon thread is abandoned at exit — acceptable for a cleanup.
            _t = threading.Thread(target=_do, daemon=True)
            _t.start()
            _t.join(timeout=5)
        else:
            threading.Thread(target=_do, daemon=True).start()

    # ── Remote-access probe gating ───────────────────────────────────────────
    # While a probe is in flight a device's reachability isn't known yet, so advancing from the
    # Devices page would mis-route it to the agent/passive dialog. Background probe threads bracket
    # themselves with these; the Devices "Siguiente" is disabled until the last one finishes.
    def _probe_started(self) -> None:
        with self._devices_lock:
            self._probes_in_flight += 1
        self._post(self._sync_next_for_probes)

    def _probe_finished(self) -> None:
        with self._devices_lock:
            self._probes_in_flight = max(0, self._probes_in_flight - 1)
        self._post(self._sync_next_for_probes)

    def _sync_next_for_probes(self) -> None:
        """Disable 'Siguiente' on the Devices page (step 2) while a remote-access probe runs;
        re-enable when the last finishes. Only gates step 2 — other pages own the button via _show."""
        if getattr(self, "_step", None) != 2:
            return
        try:
            if self._probes_in_flight > 0:
                self._btn_next.config(state="disabled", text=_T('Comprobando acceso…'))
            else:
                self._btn_next.config(state="normal", text="Siguiente →")
        except Exception:
            pass

    def _run_probe(self, fn: Callable) -> None:
        """Launch a background remote-access probe `fn`, bracketed so the Devices 'Siguiente'
        is gated for its whole lifetime (decremented even if `fn` raises)."""
        self._probe_started()

        def _wrapped():
            try:
                fn()
            finally:
                self._probe_finished()
        threading.Thread(target=_wrapped, daemon=True).start()

    def _post(self, fn: Callable):
        self._q.put(fn)

    def _drain(self):
        try:
            while True:
                fn = self._q.get_nowait()
                try:
                    fn()
                except Exception as _e:
                    # Never let a stale callback (TclError on destroyed widget,
                    # etc.) kill the drain loop — but do log for debugging.
                    logger.debug("_drain callback error: %s", _e, exc_info=True)
        except queue.Empty:
            pass
        self.after(50, self._drain)

    def _status(self, msg: str, color: str = "#555"):
        self._status_var.set(_T(msg))   # complete status strings are translated; others pass through
        self._status_lbl.config(fg=color)

    def _reset_folder_scoped_state(self) -> None:
        """Forget everything scoped to the CURRENT folder: the topology graph + baseline +
        snapshot, the removed/locked sets, the undo/redo stacks, the passive/agent queues, the
        per-folder path/config overrides, the manual topology nodes, and the rename-step inputs.
        SINGLE source of truth shared by do_select (folder switch) and every full-folder-removal
        path, so the key-set can't drift — a missed key means residual state bleeding into a
        re-created same-id folder (ghost nodes, blank preview, GET-404). Does NOT touch
        `devices` (credentials are folder-agnostic) nor `folder` (the caller owns that)."""
        for _k in ("topology", "topology_orig", "topology_snapshot"):
            self.s.pop(_k, None)
        self.s["topology_removed"] = set()
        self.s["topology_locked"] = set()
        self.s["topo_undo"] = []
        self.s["topo_redo"] = []
        self.s.pop("_undo", None)   # rename-undo snapshot is folder-scoped (id/label/path/ID)
        self.s.pop("_pending_new_folder", None)   # orphan-cleanup pointer must not survive a
        # folder switch / full-folder-removal as a stale pointer to a gone folder (do_select
        # re-sets it for a fresh folder AFTER this reset)
        self.s["folder_is_new"] = False   # do_select re-sets it; reset here so it can't bleed
        self.s["agent_devices"] = []
        self.s["passive_devices"] = set()
        self.s["path_overrides"] = {}
        self.s["fcfg_pending"] = {}
        self.s["manual_topo_nodes"] = {}
        self.s["_disc_auto_retry_done"] = False
        self.s["new_label"] = ""
        self.s["new_path_input"] = ""
        self.s["new_folder_id"] = ""
        self.s["skip_path"] = False
        self.s["rename_id"] = False

    # ── In-session credential reuse ──────────────────────────────────────────
    # Devices are re-discovered per folder, so creds the user types for folder A would be
    # lost when switching to folder B. We keep a SESSION-ONLY store (never written to disk —
    # that's what the encrypted credentials file is for) keyed by Syncthing device-id, with
    # IP/host as a fallback key, and merge it back in so the same devices in another folder
    # come pre-filled. Cleared only when the process exits. NOT folder-scoped → never reset
    # in _reset_folder_scoped_state.
    _SESSION_CRED_PORTS = ("ssh_port", "winrm_port")
    # Host-level creds: a remote SHELL login is the same for any Syncthing instance on that host,
    # so these are safe to reuse via the IP/host fallback (different device-id, same machine).
    _SESSION_CRED_HOST_SECRETS = ("ssh_user", "ssh_key_path", "ssh_password",
                                  "winrm_user", "winrm_password")
    # api_key/api_url identify a SPECIFIC instance (port + key) → only reuse on an exact device-id
    # match, never via the IP fallback (a 2nd Syncthing on the same host has a different API).
    _SESSION_CRED_SECRETS = ("api_key", "api_url") + _SESSION_CRED_HOST_SECRETS
    _SESSION_CRED_KEYS = _SESSION_CRED_SECRETS + _SESSION_CRED_PORTS

    @staticmethod
    def _device_has_creds(d) -> bool:
        # Ports/URLs alone aren't credentials — require an actual secret/identity.
        return bool(d.api_key or d.ssh_user or d.ssh_key_path or d.ssh_password
                    or d.winrm_user or d.winrm_password)

    def _apply_window_icon(self) -> None:
        """Set the window/taskbar icon from the bundled PNG. Cosmetic → never fail startup.
        Resolves both dev (repo assets/) and the PyInstaller bundle (sys._MEIPASS/assets/)."""
        try:
            cands = []
            base = getattr(sys, "_MEIPASS", None)
            if base:
                cands.append(Path(base) / "assets" / "icon.png")
            cands.append(Path(__file__).resolve().parents[2] / "assets" / "icon.png")
            for p in cands:
                if p.exists():
                    self._icon_img = tk.PhotoImage(file=str(p))   # keep a ref (avoid GC)
                    self.iconphoto(True, self._icon_img)
                    return
        except Exception:
            pass   # icon is purely cosmetic — a missing/unreadable file must not break the GUI

    def _remember_session_creds(self, devices) -> None:
        """MERGE any credentials present on these devices into the session store. Never wipes:
        a device shown later WITHOUT a given field (offline, or re-probed over SSH-only so its
        api_key isn't re-read) must not erase what the user typed earlier — so we update only
        non-empty fields per id and keep the rest. Non-default ports are remembered; a default
        port never stomps a saved non-default one."""
        store = self.s.setdefault("_session_creds", {})
        # Iterate an atomic snapshot: some callers pass the LIVE self.s["devices"], which worker
        # threads mutate under _devices_lock — a live `for d in devices` would race. We can't take
        # the lock here (some callers already hold it → re-entrant deadlock); list() is GIL-atomic.
        for d in list(devices or []):
            if getattr(d, "is_local", False) or not self._device_has_creds(d):
                continue
            entry = store.setdefault(d.device_id, {"device_id": d.device_id, "ip": None})
            if d.ip:
                entry["ip"] = d.ip
            for k in self._SESSION_CRED_SECRETS:
                v = getattr(d, k, None)
                if v:                       # non-empty → update; empty → keep prior value
                    entry[k] = v
                else:
                    entry.setdefault(k, None)
            for k in self._SESSION_CRED_PORTS:
                v = getattr(d, k, None)
                if v and v not in (22, 5985):   # only a real (non-default) port overrides
                    entry[k] = v
                else:
                    entry.setdefault(k, v)

    def _session_cred_entries(self, exclude_ids) -> list:
        """cfg-style entries (for discover_devices) for remembered devices not already covered.
        Omits folder_path — that's per-folder, not a credential."""
        store = self.s.get("_session_creds") or {}
        return [dict(e) for did, e in store.items() if did not in (exclude_ids or set())]

    def _apply_session_creds(self, devices) -> None:
        """Fill MISSING creds on freshly-discovered devices from the session store, matching by
        device-id first, then IP/host. Only fills empties — never overrides discovered/typed
        values. Lets the rename/topology steps reach a device even if its probe didn't use creds."""
        store = self.s.get("_session_creds") or {}
        if not store:
            return
        # IP fallback only for UNAMBIGUOUS hosts: if two device-ids share an IP (two Syncthing
        # nodes on one host), we can't tell which creds belong to a new id at that IP — skip it
        # rather than risk applying the wrong device's SSH key/password.
        from collections import Counter
        _ipc = Counter(e["ip"] for e in store.values() if e.get("ip"))
        by_ip = {e["ip"]: e for e in store.values() if e.get("ip") and _ipc[e["ip"]] == 1}
        for d in list(devices or []):   # atomic snapshot — see _remember_session_creds
            if getattr(d, "is_local", False):
                continue
            by_id = store.get(d.device_id)
            e = by_id or (by_ip.get(d.ip) if d.ip else None)
            if not e:
                continue
            # Exact device-id match → reuse all creds. IP-fallback match (same host, different id)
            # → only HOST-level shell creds; api_key/api_url could belong to another instance.
            secrets = self._SESSION_CRED_SECRETS if by_id else self._SESSION_CRED_HOST_SECRETS
            for k in secrets:
                if not getattr(d, k, None) and e.get(k):
                    setattr(d, k, e[k])
            # Carry the matching port only when we actually adopted that channel's creds and
            # the device is still on the default port (don't stomp an explicit per-device port).
            if e.get("ssh_port") and d.ssh_port == 22 and (e.get("ssh_user") or e.get("ssh_key_path")):
                d.ssh_port = e["ssh_port"]
            if e.get("winrm_port") and d.winrm_port == 5985 and e.get("winrm_user"):
                d.winrm_port = e["winrm_port"]

    def _unlock_modal(self) -> None:
        """Block the whole app behind the password prompt until it's entered correctly.
        Used at STARTUP (gate), by «Bloquear ahora», and by the inactivity auto-lock. No-op
        if the lock is disabled. «Salir»/✗ quits the app. A convenience deterrent
        (recoverable), not strong security."""
        from .. import applock
        if not applock.is_enabled() or getattr(self, "_locked_open", False):
            return
        self._locked_open = True
        # Hide EVERY visible window — the main one AND any open child Toplevels (e.g. Ajustes)
        # — so none lingers beside the lock (which looked like a second lock window); remember
        # which ones were up so we can restore them on unlock.
        self._locked_hidden = []
        for w in self.winfo_children():
            try:
                if isinstance(w, tk.Toplevel) and w.winfo_viewable():
                    w.withdraw()
                    self._locked_hidden.append(w)
            except Exception:
                pass
        self.withdraw()
        dlg = tk.Toplevel(self)
        dlg.title("Bloqueado")
        dlg.configure(bg="white")
        dlg.protocol("WM_DELETE_WINDOW", self.destroy)
        try:
            self._center_dialog(dlg)
        except Exception:
            pass
        dlg.grab_set()
        tk.Label(dlg, text="🔒 Aplicación bloqueada", bg="white",
                 font=(_FONT, 12, "bold")).pack(anchor="w", padx=20, pady=(16, 2))
        _hint = ("Introduce tu contraseña de Syncthing." if applock.method() == "syncthing"
                 else "Introduce la contraseña para desbloquear.")
        tk.Label(dlg, text=_hint, bg="white", fg="#555",
                 font=(_FONT, 9)).pack(anchor="w", padx=20)
        pw_v = tk.StringVar()
        ent = ttk.Entry(dlg, textvariable=pw_v, width=30, show="●")
        ent.pack(anchor="w", padx=20, pady=(8, 2))
        msg = tk.Label(dlg, text="", bg="white", fg="#C62828", font=(_FONT, 8))
        msg.pack(anchor="w", padx=20)

        def _try(_e=None):
            if applock.verify(pw_v.get()):
                self._locked_open = False
                self._idle_reset()
                dlg.destroy()
                self.deiconify()
                for w in getattr(self, "_locked_hidden", []):
                    try:
                        w.deiconify()
                    except Exception:
                        pass
                self._locked_hidden = []
                self.lift()
            else:
                pw_v.set("")
                msg.config(text="Contraseña incorrecta.")
                ent.focus_set()
            return "break"
        bf = tk.Frame(dlg, bg="white")
        bf.pack(fill=tk.X, padx=20, pady=14)
        tk.Button(bf, text="🔓 Desbloquear", fg="white", bg="#2E7D32",
                  activebackground="#1B5E20", activeforeground="white", relief="raised",
                  command=_try).pack(side=tk.RIGHT)
        ttk.Button(bf, text="Salir", command=self.destroy).pack(side=tk.RIGHT, padx=(0, 6))
        dlg.bind("<Return>", _try)
        ent.focus_set()

    def _idle_reset(self) -> None:
        import time
        self._last_activity = time.time()

    def _setup_idle_lock(self) -> None:
        """Bind activity events + poll: lock after N minutes idle (when enabled). Cheap."""
        import time
        self._last_activity = time.time()
        for _ev in ("<Key>", "<Button>", "<Motion>", "<MouseWheel>"):
            try:
                self.bind_all(_ev, lambda _e: setattr(self, "_last_activity", time.time()),
                              add="+")
            except Exception:
                pass

        def _check():
            from .. import applock
            try:
                mins = applock.inactivity_minutes()
                if (applock.is_enabled() and mins > 0
                        and not getattr(self, "_locked_open", False)
                        and (time.time() - getattr(self, "_last_activity", time.time())) >= mins * 60):
                    self._unlock_modal()
            except Exception:
                pass
            self.after(20000, _check)
        self.after(20000, _check)

    def _lock_now(self) -> None:
        """Manual «Bloquear ahora» — with a confirmation, since you'll need the password."""
        from .. import applock
        if not applock.is_enabled():
            messagebox.showinfo("Bloquear ahora",
                                "El candado no está activado. Actívalo en Ajustes.", parent=self)
            return
        if messagebox.askyesno("Bloquear ahora",
                               "¿Bloquear la aplicación? Tendrás que introducir la contraseña "
                               "para volver.", parent=self):
            self._unlock_modal()


def main(lang=None):
    import socket
    # Language: an explicit `lang` (passed by the `gui` CLI subcommand, which already resolved
    # --lang → stored → OS) wins; on a bare double-click (lang=None) read the stored preference.
    # Resolve + install the translation shim BEFORE any widget is built.
    i18n.set_language(lang if lang is not None else appconfig.get_setting("language", "auto"))
    _install_tk_i18n()
    # Global safety net only — must stay above the longest explicit per-operation
    # timeout (SSH find/exec is 30s) so it never prematurely interrupts a live SSH
    # channel. All HTTP/SSH/WinRM calls already pass their own tighter timeouts.
    socket.setdefaulttimeout(60)
    app = App()
    app._setup_idle_lock()        # optional inactivity auto-lock (no-op unless enabled)
    # Startup gate: if the lock is on, prompt for the password before the app is usable
    # (scheduled so it runs once the event loop is up). No-op when the lock is disabled.
    app.after(0, app._unlock_modal)
    app.mainloop()
