from __future__ import annotations
from .common import *  # noqa: F401,F403


class DiscoverPageMixin:
    def _page_discover(self, f: tk.Frame):
        folder: FolderConfig = self.s["folder"]
        tk.Label(f, text=_T('Dispositivos — {}').format(folder.label or folder.id), bg="white",
                 font=(_FONT, 11, "bold")).pack(anchor="w")
        ttk.Separator(f, orient="horizontal").pack(fill=tk.X, pady=(6, 6))
        tk.Label(f, text="Selecciona un dispositivo con problemas y pulsa 'Editar credenciales' para configurarlo.",
                 bg="white", fg="#888", font=(_FONT, 8)).pack(anchor="w", pady=(0, 2))
        tk.Label(f, text="⚠: la API Key se obtendrá automáticamente via SSH al ejecutar el rename.",
                 bg="white", fg="#888", font=(_FONT, 8)).pack(anchor="w", pady=(0, 1))
        tk.Label(f, text="Dispositivos sin acceso remoto → se gestionarán por exploración pasiva "
                          "(al reconectar) o con un agente local.",
                 bg="white", fg="#888", font=(_FONT, 8)).pack(anchor="w", pady=(0, 6))

        cols = ("Nombre", "IP", "Remoto", "API", "SO", "Ruta en disco")
        tree_frm = tk.Frame(f, bd=2, relief="groove")
        tree_frm.pack(fill=tk.BOTH, expand=True)
        tree = ttk.Treeview(tree_frm, columns=cols, show="headings", height=8, selectmode="browse")
        for col, w, stretch, minw, anchor in zip(
            cols,
            # Initial widths sized for typical real content
            [self._cw("Mi dispositivo", 16),           # typical device name (kept compact so the
                                                       # fixed columns don't crowd out SO/Ruta)
             self._cw("192.168.100.200", 20),          # typical IPv4
             self._cw("WinRM ✓", 28),                  # longest status message
             self._cw("API", 24),                      # small — only ✓ ⚠ —
             self._cw("🐧 Linux", 18),                  # OS chip
             self._cw("Ruta en disco", 100)],           # stretch col, generous start
            [False, False, False, False, False, True],
            # Minwidths = header width (small) so the fit logic can shrink fixed columns enough
            # to keep the whole row inside the window — instead of overflowing into a horizontal
            # scrollbar. Content that doesn't fit a narrowed column just clips. SO floors at the
            # OS-chip width so "🐧 Linux"/"🪟 Windows" is never clipped when columns are trimmed.
            [self._cw("Nombre", 10), self._cw("IP", 10),
             self._cw("Remoto", 10), self._cw("API", 10), self._cw("🐧 Linux", 12),
             self._cw("Ruta", 12)],
            ["w", "center", "center", "center", "center", "w"],
        ):
            tree.heading(col, text=col)
            tree.column(col, width=w, stretch=stretch, anchor=anchor, minwidth=minw)

        vsb = ttk.Scrollbar(tree_frm, orient="vertical",   command=tree.yview)
        hsb = ttk.Scrollbar(tree_frm, orient="horizontal", command=tree.xview)
        tree_frm.grid_rowconfigure(0, weight=1)
        tree_frm.grid_rowconfigure(1, weight=0)
        tree_frm.grid_columnconfigure(0, weight=1)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        vsb.grid_remove()
        hsb.grid_remove()

        def _devices_vsb_set(first, last):
            vsb.set(first, last)
            if float(first) <= 0.0 and float(last) >= 1.0:
                vsb.grid_remove()
            else:
                vsb.grid()

        def _devices_hsb_set(first, last):
            hsb.set(first, last)
            if float(first) <= 0.0 and float(last) >= 1.0:
                hsb.grid_remove()
            else:
                hsb.grid()

        tree.configure(yscrollcommand=_devices_vsb_set, xscrollcommand=_devices_hsb_set)

        _ruta_minw = self._cw("Ruta en disco", 60)   # preferred width for the path column
        _ruta_floor = self._cw("Ruta", 12)            # hard floor when the window is narrow
        _fixed_cols = [c for c in cols if c != "Ruta en disco"]
        def _enforce_col_minw(e=None):
            avail = tree.winfo_width()
            if avail <= 1:
                return
            fixed_total = sum(tree.column(c, "width") for c in _fixed_cols)
            remaining = avail - fixed_total
            if remaining < _ruta_minw:
                excess = _ruta_minw - remaining
                for c in reversed(_fixed_cols):
                    cw = tree.column(c, "width")
                    cm = tree.column(c, "minwidth")
                    if cw > cm:
                        trim = min(cw - cm, excess)
                        tree.column(c, width=cw - trim)
                        excess -= trim
                        if excess <= 0:
                            break
                fixed_total = sum(tree.column(c, "width") for c in _fixed_cols)
            # Give the path column whatever's left. Floor is tiny (not _ruta_minw) so the row
            # always fits the window width — no horizontal scrollbar; long paths just clip.
            tree.column("Ruta en disco", width=max(_ruta_floor, avail - fixed_total))
        tree.bind("<ButtonRelease-1>", _enforce_col_minw)
        tree.bind("<Configure>", _enforce_col_minw)

        _dev_init_widths = {
            "Nombre":       self._cw("Nombre del dispositivo", 20),
            "IP":           self._cw("192.168.100.200", 20),
            "Remoto":       self._cw("WinRM ✓", 28),
            "API":          self._cw("API", 24),
            "Ruta en disco": self._cw("Ruta en disco", 100),
        }

        def _reset_dev_cols():
            for c, w in _dev_init_widths.items():
                tree.column(c, width=w)
            _enforce_col_minw()

        def _dev_rclick(event):
            menu = tk.Menu(tree, tearoff=0)
            menu.add_command(label="Restablecer columnas", command=_reset_dev_cols)
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        tree.bind("<Button-3>", _dev_rclick)

        # Button bar below tree — two rows so all six buttons fit in narrow/windowed mode
        # (one row overflowed the window width and clipped "➕ Añadir dispositivo").
        btn_bar = tk.Frame(f, bg="white")
        btn_bar.pack(fill=tk.X, pady=(6, 0))
        btn_bar2 = tk.Frame(f, bg="white")
        btn_bar2.pack(fill=tk.X, pady=(4, 0))
        edit_btn = ttk.Button(btn_bar, text="✏  Editar credenciales", state="disabled",
                              command=lambda: _open_edit_dialog())
        edit_btn.pack(side=tk.LEFT)
        retry_btn = ttk.Button(btn_bar, text="↺  Reintentar SSH", state="disabled",
                               command=lambda: _retry_selected())
        retry_btn.pack(side=tk.LEFT, padx=(6, 0))
        refresh_btn = ttk.Button(btn_bar, text="🔄  Redescubrir",
                                 command=lambda: (self.s.__setitem__("_force_rediscover", True),
                                                  self._show(2)))
        refresh_btn.pack(side=tk.LEFT, padx=(6, 0))
        names_btn = ttk.Button(btn_bar2, text="🏷  Sincronizar nombres", state="disabled",
                               command=lambda: _open_name_sync_dialog())
        names_btn.pack(side=tk.LEFT)
        save_btn = ttk.Button(btn_bar2, text="💾  Guardar credenciales", state="disabled",
                              command=lambda: _save_credentials())
        save_btn.pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(btn_bar2, text="➕  Añadir dispositivo",
                   command=lambda: _add_device_manual()).pack(side=tk.LEFT, padx=(6, 0))
        remove_btn = ttk.Button(btn_bar2, text="🗑  Quitar dispositivo", state="disabled",
                                command=lambda: _remove_device())
        remove_btn.pack(side=tk.LEFT, padx=(6, 0))

        def _update_status():
            devs = self.s.get("devices", [])
            ok       = sum(1 for d in devs if _device_kind(d) == "ok")
            offline  = sum(1 for d in devs if _device_kind(d) == "offline")
            problems = sum(1 for d in devs if _device_kind(d) == "problem")
            color = "#2E7D32" if problems == 0 else "#C66000"
            parts = [_T('{} dispositivo(s): {} OK').format(len(devs), ok)]
            if offline:
                parts.append(f"{offline} offline")
            if problems:
                parts.append(_T('{} con problemas — selecciónalos para editar credenciales').format(problems))
            msg = ", ".join(parts)
            n_creds = self.s.get("_creds_loaded", 0)
            if n_creds:
                msg += f"  ·  🔑 {n_creds} cred. cargadas"
            self._status(msg, color)

        def _selected_device() -> Optional[DeviceInfo]:
            sel = tree.selection()
            if not sel:
                return None
            did = sel[0]
            return next((d for d in self.s.get("devices", []) if d.device_id == did), None)

        def _on_select(_event=None):
            dev = _selected_device()
            if dev and not dev.is_local:
                edit_btn.config(state="normal")
                retry_btn.config(state="normal")
                remove_btn.config(state="normal")
            else:
                edit_btn.config(state="disabled")
                retry_btn.config(state="disabled")
                remove_btn.config(state="disabled")

        tree.bind("<<TreeviewSelect>>", _on_select)

        def _remove_device():
            """Quitar dispositivo (F-a): remove the selected device from this session — the
            devices list, the manually-added topology nodes, and the in-memory topology graph
            — and remember it in topology_removed so reconcile/snapshot don't resurrect it.
            Does NOT touch Syncthing config (no unshare/delete): that's a separate action in
            Topología. Mirrors topology's _remove_node so you don't have to switch pages."""
            dev = _selected_device()
            if not dev or dev.is_local:
                return
            if not messagebox.askyesno(
                "Quitar dispositivo",
                _T('¿Quitar «{}» de la lista y de la topología?\n\nNo cambia la configuración '
                   'de Syncthing (no deja de compartir ni borra nada en los equipos) — solo se '
                   'quita de esta sesión. Para dejar de compartir una carpeta, hazlo en '
                   'Topología.').format(dev.name),
                parent=self):
                return
            did = dev.device_id
            with self._devices_lock:
                self.s["devices"] = [d for d in self.s.get("devices", []) if d.device_id != did]
            self.s.get("manual_topo_nodes", {}).pop(did, None)
            self.s.setdefault("topology_removed", set()).add(did)
            self.s.get("passive_devices", set()).discard(did)
            self.s["agent_devices"] = [a for a in self.s.get("agent_devices", [])
                                       if a.device_id != did]
            # Drop from BOTH the live graph and the baseline (topology_orig). If we dropped it
            # only from the live graph, a device that's a REAL folder member would show up as a
            # pending "link removed" diff and a later Ejecutar would actually UNSHARE it —
            # contradicting this dialog's promise that it doesn't change Syncthing.
            for _g in (self.s.get("topology"), self.s.get("topology_orig")):
                if _g and did in _g.get("nodes", {}):
                    _g["nodes"].pop(did, None)
                    _g["edges"] = {e for e in _g.get("edges", set()) if did not in e}
                    _g["edge_dir"] = {e: s for e, s in _g.get("edge_dir", {}).items()
                                      if did not in e}
            if tree.exists(did):
                tree.delete(did)
            _update_status()
            _on_select()   # selection is gone now → disable the per-device buttons
            self._status(_T('«{}» quitado de la lista.').format(dev.name), "#2E7D32")

        def _on_double(_e=None):
            # Double-click a device row → open its "Editar credenciales" dialog.
            dev = _selected_device()
            if dev and not dev.is_local:
                _open_edit_dialog()
            return "break"
        tree.bind("<Double-1>", _on_double)

        self._btn_next.config(state="disabled")
        self._status("Descubriendo dispositivos...", "#555")
        my_gen = self._show_gen

        def _os_chip(d: DeviceInfo) -> str:
            return {"windows": "🪟 Win", "linux": "🐧 Linux", "macos": "🍎 Mac"}.get(d.os_type, "❔")

        def _row_values(dev: DeviceInfo):
            if dev.is_local:
                return (dev.name, dev.ip or "local", "local", "✓", _os_chip(dev),
                        dev.folder_path or "—")
            if dev.ssh_reachable:
                remote = "SSH ✓"
            elif dev.winrm_reachable:
                remote = "WinRM ✓"
            elif not dev.ip:
                remote = "offline"
            elif not (dev.ssh_user or dev.ssh_key_path or dev.ssh_password
                      or dev.winrm_user or dev.winrm_password):
                remote = "sin SSH"
            else:
                remote = "✗ error"
            api = "✓" if dev.api_reachable else ("⚠" if dev.api_key else "—")
            return (dev.name, dev.ip or _T("(sin IP)"), _T(remote), api, _os_chip(dev),
                    dev.folder_path or "—")

        def _refresh_row(dev: DeviceInfo):
            vals = _row_values(dev)
            if tree.exists(dev.device_id):
                tree.item(dev.device_id, values=vals)
            else:
                tree.insert("", "end", iid=dev.device_id, values=vals)

        def on_found(dev: DeviceInfo):
            if self._show_gen == my_gen:
                self._post(lambda d=dev: _refresh_row(d))

        def _save_credentials():
            # Snapshot under the lock: discovery/probe workers append/replace this list, so
            # iterating the live list here (UI thread) could raise "list changed size during
            # iteration" or persist a half-updated set. Other readers already snapshot it.
            with self._devices_lock:
                devs = list(self.s.get("devices", []))
            has_secrets = any(
                (d.ssh_password or d.winrm_password or d.api_key)
                for d in devs if not d.is_local
            )
            # The on-disk file is encrypted but no secrets are loaded in memory (the user
            # never unlocked it this session). Overwriting now would drop the encrypted
            # credentials and silently downgrade the file to plaintext — refuse instead of
            # losing data. The user must unlock first (or there is genuinely nothing to save).
            if needs_master_password() and not has_secrets:
                self._status(_T('El archivo de credenciales está cifrado y no se ha '
                                'desbloqueado en esta sesión; guardar ahora borraría las '
                                'credenciales cifradas. Desbloquéalas primero.'), "#C62828")
                return
            master_pw = None
            if has_secrets:
                master_pw = _ask_master_password(self, confirm=True,
                    title="Contraseña maestra para cifrado")
                if master_pw is None:
                    return  # cancelled
            try:
                path = save_credentials(devs, master_password=master_pw)
                note = " (cifradas)" if master_pw else " (sin cifrar)"
                self._status(_T('✓ Guardado en {}{}').format(path, note), "#2E7D32")
            except Exception as e:
                self._status(_T('Error al guardar: {}').format(e), "#C62828")

        def _add_device_manual():
            """Pair a NEW device with this node and surface it as an unconnected node in
            Topología (to share the folder there). Only the LOCAL side is configured here —
            the remote must accept (reachable → directo en Topología; si no, pasiva/agente/
            manual). Works for a brand-new folder (start local-only, add devices here)."""
            client = self.s.get("client")
            dlg = tk.Toplevel(self)
            dlg.title("Añadir dispositivo")
            dlg.configure(bg="white")
            dlg.transient(self)
            dlg.grab_set()
            self._center_dialog(dlg)
            tk.Label(dlg, text="Añadir dispositivo al clúster", bg="white",
                     font=(_FONT, 10, "bold")).pack(anchor="w", padx=16, pady=(12, 2))
            tk.Label(dlg, text="Lo empareja en ESTE equipo y aparece en Topología para "
                               "compartirle la carpeta. El otro equipo debe aceptar, o "
                               "configúralo con credenciales (acceso opcional).",
                     bg="white", fg="#888", font=(_FONT, 8), wraplength=440,
                     justify="left").pack(anchor="w", padx=16)

            # Vincular conocido: pick a device the local Syncthing already knows (e.g. shared
            # in OTHER folders / auto-detected) so you don't have to type its ID — same as the
            # Topología dialog. Manual entry below still works. Loaded in the background.
            link = tk.Frame(dlg, bg="white")
            link.pack(fill=tk.X, padx=16, pady=(6, 0))
            tk.Label(link, text="Vincular conocido:", bg="white", anchor="e",
                     width=15).pack(side=tk.LEFT)
            known_var = tk.StringVar()
            known_cb = ttk.Combobox(link, textvariable=known_var, state="readonly", width=30)
            known_cb.pack(side=tk.LEFT, padx=(6, 0))
            known_cb.set(_T("(cargando dispositivos conocidos…)"))
            _known_map: dict = {}

            def _on_known(_e=None):
                sel = known_var.get()
                if sel in _known_map:
                    did, nm = _known_map[sel]
                    id_v.set(did)
                    if not name_v.get().strip():
                        name_v.set(nm)
            known_cb.bind("<<ComboboxSelected>>", _on_known)

            def _load_known():
                items = []
                if client:
                    try:
                        my_id = self.s.get("my_id", "")
                        with self._devices_lock:
                            present = {d.device_id for d in self.s.get("devices", [])}
                        for dc in client.get_config_devices():
                            if dc.device_id == my_id or dc.device_id in present:
                                continue
                            disp = f"{dc.name or dc.device_id[:7]} — {dc.device_id[:7]}…"
                            _known_map[disp] = (dc.device_id, dc.name or "")
                            items.append(disp)
                    except Exception:
                        pass

                def ui():
                    if not known_cb.winfo_exists():
                        return
                    if items:
                        known_cb["values"] = sorted(items)
                        known_cb.set(_T("(elige para autocompletar…)"))
                    else:
                        known_cb.set(_T("(no hay otros dispositivos conocidos)"))
                        known_cb.config(state="disabled")
                self._post(ui)
            threading.Thread(target=_load_known, daemon=True).start()

            grid = tk.Frame(dlg, bg="white")
            grid.pack(fill=tk.X, padx=16, pady=(6, 0))
            id_v = tk.StringVar(); name_v = tk.StringVar(); ip_v = tk.StringVar()
            su_v = tk.StringVar(); sk_v = tk.StringVar(); sp_v = tk.StringVar()
            au_v = tk.StringVar(); ak_v = tk.StringVar()
            # Full access config in the ADD dialog (so you don't have to add-then-edit just
            # to set a port). Ports prefill from the configured defaults (B7).
            _def_ssh = int(appconfig.get_setting("default_ssh_port", 22) or 22)
            _def_winrm = int(appconfig.get_setting("default_winrm_port", 5985) or 5985)
            sport_v = tk.StringVar(value=str(_def_ssh))
            wu_v = tk.StringVar(); wpw_v = tk.StringVar(); wport_v = tk.StringVar(value=str(_def_winrm))
            # Folder path ON THIS DEVICE (where the shared folder will be created/used).
            # Prefilled with ~/<folder label> so the user sees and can adjust it here.
            _cur_folder = self.s.get("folder")
            _flabel = (_cur_folder.label or _cur_folder.id) if _cur_folder else ""
            path_v = tk.StringVar(value=(f"~/{_flabel}" if _flabel else ""))

            def _r(r, lbl, var, show="", browse=False):
                tk.Label(grid, text=lbl, bg="white", anchor="e", width=15).grid(
                    row=r, column=0, sticky="e", pady=2)
                ttk.Entry(grid, textvariable=var, width=30, show=show).grid(
                    row=r, column=1, sticky="w", padx=(6, 0))
                if browse:
                    ttk.Button(grid, text="…", width=3,
                               command=lambda: sk_v.set(
                                   filedialog.askopenfilename(title=_T("Clave SSH privada"))
                                   or sk_v.get())).grid(row=r, column=2, padx=(2, 0))

            def _hdr(r, txt):
                tk.Label(grid, text=txt, bg="white", fg="#888", font=(_FONT, 8, "bold")).grid(
                    row=r, column=0, columnspan=3, sticky="w", pady=(6, 2))

            _r(0, "Device ID:", id_v)
            _r(1, "Nombre:", name_v)
            _r(2, "Ruta de carpeta:", path_v)
            tk.Label(grid, text="(ruta en ESTE dispositivo donde se creará/compartirá la carpeta; "
                                "por defecto ~/<carpeta>)", bg="white", fg="#888",
                     font=(_FONT, 8), wraplength=380, justify="left").grid(
                row=3, column=1, columnspan=2, sticky="w")
            _hdr(4, "Acceso (opcional)")
            _r(5, "IP / Host:", ip_v)
            _hdr(6, "── SSH ──")
            _r(7, "Usuario SSH:", su_v)
            _r(8, "Clave SSH:", sk_v, browse=True)
            _r(9, "Contraseña SSH:", sp_v, show="●")
            _r(10, "Puerto SSH:", sport_v)
            _hdr(11, "── WinRM (Windows) ──")
            _r(12, "Usuario WinRM:", wu_v)
            _r(13, "Contraseña WinRM:", wpw_v, show="●")
            _r(14, "Puerto WinRM:", wport_v)
            _hdr(15, "── Syncthing API ──")
            _r(16, "URL API:", au_v)
            _r(17, "API Key:", ak_v, show="●")
            st = tk.Label(dlg, text="", bg="white", font=(_FONT, 8))
            st.pack(anchor="w", padx=16, pady=(4, 0))

            # Pre-fill credentials for a device configured earlier this session OR in another
            # folder (session store, then the saved/disk store) — same as the Topología dialog,
            # so you don't re-type them when re-adding the same device in a new folder. Fires
            # when a full Device ID is entered (typed or chosen from "Vincular conocido", which
            # sets id_v). ONLY fills the dialog fields — never links the device to the folder.
            _prefilled = {"for": None}

            def _prefill_creds(*_):
                did = id_v.get().strip().upper()
                if len(did) < 50 or _prefilled["for"] == did:
                    return
                with self._devices_lock:
                    ex = next((d for d in self.s.get("devices", []) if d.device_id == did), None)
                store = (self.s.get("_session_creds") or {}).get(did) or {}
                saved = next((c for c in (self.s.get("_saved_creds") or [])
                              if c.get("device_id") == did), {})
                if ex is None and not store and not saved:
                    return
                _prefilled["for"] = did

                def _val(attr, *keys):
                    if ex is not None:
                        v = getattr(ex, attr, None)
                        if v:
                            return v
                    for src in (store, saved):
                        for k in keys:
                            if src.get(k):
                                return src[k]
                    return None

                _name = _val("name", "name")
                if _name and not name_v.get().strip():
                    name_v.set(_name)
                _ip = _val("ip", "ip", "ssh_host")
                if _ip and not ip_v.get().strip():
                    ip_v.set(_ip)
                for _var, _attr, _key in ((su_v, "ssh_user", "ssh_user"),
                                          (sk_v, "ssh_key_path", "ssh_key_path"),
                                          (sp_v, "ssh_password", "ssh_password"),
                                          (wu_v, "winrm_user", "winrm_user"),
                                          (wpw_v, "winrm_password", "winrm_password"),
                                          (ak_v, "api_key", "api_key")):
                    _v = _val(_attr, _key)
                    if _v and not _var.get().strip():
                        _var.set(_v)
                _spt = _val("ssh_port", "ssh_port")
                if _spt and _spt != 22 and sport_v.get().strip() in ("", "22"):
                    sport_v.set(str(_spt))
                _wpt = _val("winrm_port", "winrm_port")
                if _wpt and _wpt != 5985 and wport_v.get().strip() in ("", "5985"):
                    wport_v.set(str(_wpt))
                _au = _val("api_url", "api_url")
                if _au and not au_v.get().strip():
                    au_v.set(_au)
                st.config(text="↩ Credenciales previas restauradas para este dispositivo.",
                          fg="#1565C0")
            id_v.trace_add("write", _prefill_creds)

            # Auto-detect the device's IP from the LOCAL Syncthing once a full Device ID is
            # entered (typed or chosen from "Vincular conocido", which sets id_v) and the IP
            # field is still empty — same behaviour as the Topología «Nuevo dispositivo»
            # dialog. Without this the IP stayed blank here (probe_device with ip=None can't
            # connect, so nothing was discovered until a later Redescubrir/Estado).
            _ip_auto = {"for": None}

            def _autodetect_ip(*_):
                did = id_v.get().strip().upper()
                if len(did) < 50 or ip_v.get().strip() or _ip_auto["for"] == did:
                    return
                _ip_auto["for"] = did

                def work():
                    found = resolve_live_ip(self.s.get("client"), did)

                    def ui():
                        if dlg.winfo_exists() and found and not ip_v.get().strip():
                            ip_v.set(found)
                            # Don't stomp a validation error the user just triggered (e.g.
                            # clicked Añadir mid-detect): `st` is shared, so only show the
                            # autodetect note when no red error is currently displayed.
                            if str(st.cget("fg")).lower() != "#c62828":
                                st.config(text=_T('IP autodetectada: {}').format(found), fg="#2E7D32")
                    self._post(ui)
                threading.Thread(target=work, daemon=True).start()
            id_v.trace_add("write", _autodetect_ip)

            def _add():
                did = id_v.get().strip()
                name = name_v.get().strip() or (did[:7] if did else "")
                if not did:
                    st.config(text="El Device ID no puede estar vacío.", fg="#C62828")
                    return
                if client:
                    try:
                        chk = client.check_device_id(did)
                        if isinstance(chk, dict) and chk.get("id"):
                            did = chk["id"]
                        elif isinstance(chk, dict) and chk.get("error"):
                            st.config(text="Device ID no válido.", fg="#C62828")
                            return
                    except Exception:
                        pass
                _fpath = path_v.get().strip() or None
                with self._devices_lock:
                    _existing = next((d for d in self.s.get("devices", [])
                                      if d.device_id == did), None)
                if _existing is not None:
                    # Already configured (e.g. in ANOTHER folder). Devices are folder-agnostic and
                    # persist across folders, so don't reject it — surface it in THIS folder's
                    # topology as an unconnected NEW node (keeping its existing credentials) so you
                    # can share the current folder with it here. Without this, re-adding a known
                    # device in a new folder did nothing and it never appeared in Topología.
                    self.s.setdefault("manual_topo_nodes", {})[did] = {
                        "label": _existing.name or name, "path": _fpath}
                    self.s.get("topology_removed", set()).discard(did)
                    dlg.destroy()
                    self._status(_T('«{}» ya estaba configurado — añadido a la topología de esta carpeta para compartírsela.').format(_existing.name or name), "#2E7D32")
                    return
                def _port(var, default):
                    try:
                        return int(var.get().strip() or default)
                    except ValueError:
                        return default
                # NOTE: folder_path stays None on the DeviceInfo — the device does NOT share this
                # folder yet. The chosen path lives ONLY in manual_topo_nodes (below), which is
                # what the topology apply uses to create the folder. Putting it on folder_path
                # made _shares_folder() report the device as a real member, so _build_topology
                # treated it as an existing (non-new) node and the manual_topo_nodes injection
                # skipped it → it showed up WITHOUT the "Nuevo dispositivo" mark. Once it actually
                # shares the folder (after apply + re-discovery), folder_path is set for real and
                # it correctly becomes a normal node.
                nd = DeviceInfo(
                    device_id=did, name=name, ip=ip_v.get().strip() or None,
                    api_url=au_v.get().strip() or None, api_key=ak_v.get().strip() or None,
                    folder_path=None, ssh_reachable=False, api_reachable=False, is_local=False,
                    ssh_user=su_v.get().strip() or None, ssh_key_path=sk_v.get().strip() or None,
                    ssh_password=sp_v.get().strip() or None, ssh_port=_port(sport_v, 22),
                    winrm_user=wu_v.get().strip() or None,
                    winrm_password=wpw_v.get().strip() or None, winrm_port=_port(wport_v, 5985))
                with self._devices_lock:
                    self.s.setdefault("devices", []).append(nd)
                if client:
                    try:
                        client.add_device(did, name)   # local side only (best-effort)
                    except Exception:
                        pass
                # Surface it as an unconnected node in Topología (merged into the graph there).
                # Carry the chosen path so the topology apply creates the folder there.
                self.s.setdefault("manual_topo_nodes", {})[did] = {"label": name, "path": _fpath}
                self.s.get("topology_removed", set()).discard(did)
                _refresh_row(nd)
                dlg.destroy()
                self._status(_T('«{}» añadido — compártele la carpeta en Topología.').format(name), "#2E7D32")
                _has_ssh = bool(nd.ssh_user or nd.ssh_key_path or nd.ssh_password)
                _has_winrm = bool(nd.winrm_user and nd.winrm_password)
                if _has_ssh or _has_winrm or (nd.api_key and nd.api_url):
                    def work():
                        import dataclasses as _d
                        folder = self.s["folder"]
                        # Resolve the live IP from the local Syncthing if none was entered/
                        # autodetected yet (e.g. Añadir clicked before the background detect
                        # finished) — probe_device with ip=None can't connect.
                        _ip = nd.ip or resolve_live_ip(client, did)
                        try:
                            if _has_ssh or _has_winrm:
                                pd = probe_device(device_id=did, name=name, ip=_ip,
                                    folder_id=folder.id, override={
                                        "ssh_user": nd.ssh_user, "ssh_key_path": nd.ssh_key_path,
                                        "ssh_password": nd.ssh_password, "ssh_port": nd.ssh_port,
                                        "winrm_user": nd.winrm_user, "winrm_password": nd.winrm_password,
                                        "winrm_port": nd.winrm_port})
                                pd = _d.replace(pd, api_key=pd.api_key or nd.api_key or None,
                                                folder_path=pd.folder_path or nd.folder_path)
                            else:
                                pd = probe_device_manual(device_id=did, name=name, ip=_ip,
                                    folder_id=folder.id, api_key=nd.api_key, api_url=nd.api_url,
                                    folder_path=nd.folder_path or "")
                        except Exception:
                            return
                        with self._devices_lock:
                            for i, x in enumerate(self.s["devices"]):
                                if x.device_id == did:
                                    self.s["devices"][i] = pd
                                    break
                        # Keep the topology node's path in sync with what the probe actually
                        # discovered on the device (it may differ from what was typed), so
                        # Topología doesn't use/show a stale path.
                        if pd.folder_path:
                            _mtn = self.s.get("manual_topo_nodes")
                            if isinstance(_mtn, dict) and did in _mtn:
                                _mtn[did]["path"] = pd.folder_path
                        self._post(lambda: _refresh_row(pd))
                    self._run_probe(work)   # gates Devices "Siguiente" while this probe runs
            btnf = tk.Frame(dlg, bg="white")
            btnf.pack(fill=tk.X, padx=16, pady=12)
            ttk.Button(btnf, text="Añadir", command=_add).pack(side=tk.RIGHT)
            ttk.Button(btnf, text="Cancelar", command=dlg.destroy).pack(side=tk.RIGHT, padx=(0, 6))
            dlg.bind("<Return>", lambda e: _add())

        def run(_is_auto=False):
            # Load saved credentials, decrypting if needed
            # _ask_master_password must run on the main thread (tkinter requirement)
            # An automatic second pass reuses the creds decrypted on the first pass,
            # so it never re-prompts for the master password.
            _reuse = _is_auto and self.s.get("_saved_creds") is not None
            master_pw = None
            if needs_master_password() and not _reuse:
                if self._show_gen != my_gen:
                    return
                pw_result: list = [None]
                done_event = threading.Event()
                def _ask_pw():
                    try:
                        pw_result[0] = _ask_master_password(
                            self, title="Contraseña maestra — cargar credenciales")
                    finally:
                        done_event.set()
                self._post(_ask_pw)
                if not done_event.wait(timeout=120):
                    # Timed out — window likely closed or drain loop stopped
                    logger.debug("Password prompt timed out — aborting discovery")
                    return
                if self._show_gen != my_gen:
                    return
                master_pw = pw_result[0]
            try:
                saved = (list(self.s["_saved_creds"]) if _reuse
                         else load_credentials(master_password=master_pw))
            except ValueError as e:
                msg = str(e)  # capture now: 'e' is deleted when the except block exits
                if self._show_gen == my_gen:
                    self._post(lambda: (
                        self._status(msg, "#C62828"),
                        self._btn_next.config(state="normal"),
                    ))
                return
            # Cache the DECRYPTED credentials so later hub expansion (edit/retry)
            # can reuse them without re-prompting for the master password — a
            # plain load_credentials() would return them still encrypted.
            self.s["_saved_creds"] = list(saved)
            self.s["_creds_loaded"] = len(saved)

            cfg = list(saved)
            if self.s["ssh_user"] or self.s["ssh_key"] or self.s.get("ssh_password"):
                cfg.append({"ssh_user": self.s["ssh_user"] or None,
                             "ssh_key_path": self.s["ssh_key"] or None,
                             "ssh_password": self.s.get("ssh_password") or None,
                             "ssh_port": self.s.get("ssh_port", 22)})

            # Redescubrir: carry over any in-memory credentials the user set via the
            # UI but hasn't saved to disk yet, so SSH/WinRM probes still work.
            saved_ids = {c.get("device_id") for c in saved if c.get("device_id")}
            with self._devices_lock:
                _current_devices = list(self.s.get("devices", []))
            # Remember creds the user typed on the current devices, for reuse in other folders.
            self._remember_session_creds(_current_devices)
            for _dev in _current_devices:
                if _dev.is_local or _dev.device_id in saved_ids:
                    continue
                # Same "has creds" test as the session store (includes SSH/WinRM PASSWORDS, which
                # this guard previously omitted → a password-only device wasn't carried over).
                if self._device_has_creds(_dev):
                    entry = {
                        "device_id":      _dev.device_id,
                        "api_key":        _dev.api_key or None,
                        "ssh_user":       _dev.ssh_user or None,
                        "ssh_key_path":   _dev.ssh_key_path or None,
                        "ssh_password":   _dev.ssh_password or None,
                        "ssh_port":       _dev.ssh_port,
                        "winrm_user":     _dev.winrm_user or None,
                        "winrm_password": _dev.winrm_password or None,
                        "winrm_port":     _dev.winrm_port,
                        "folder_path":    _dev.folder_path or None,
                    }
                    # Advertise a direct API URL when the device relies on direct API:
                    # either it was reachable, OR it has no SSH/WinRM creds (so API is
                    # its only path — keep the user-entered api_key+api_url so they
                    # survive a re-discovery instead of being silently dropped).
                    # SSH/WinRM-capable devices omit api_url so they re-probe over SSH
                    # (fast) rather than pinging a localhost-only API (slow timeout).
                    _has_shell = bool(_dev.ssh_user or _dev.ssh_key_path or _dev.ssh_password
                                      or (_dev.winrm_user and _dev.winrm_password))
                    if _dev.api_url and (_dev.api_reachable or not _has_shell):
                        entry["api_url"] = _dev.api_url
                    cfg.append(entry)

            # Pull in creds remembered from OTHER folders THIS SESSION (device-id keyed,
            # in-memory only) so the same devices probe & configure without re-typing.
            _cfg_ids = {c.get("device_id") for c in cfg if c.get("device_id")}
            cfg.extend(self._session_cred_entries(exclude_ids=_cfg_ids))

            try:
                # On the automatic 2nd pass, reuse already-reachable devices (don't
                # re-probe them) — only offline/new ones and hub expansion are retried.
                _keep = None
                if _is_auto:
                    with self._devices_lock:
                        _keep = {d.device_id: d for d in self.s.get("devices", [])}
                devs = discover_devices(self.s["client"], folder, cfg,
                                        on_device_found=on_found, keep=_keep)
                if self._show_gen != my_gen:
                    return  # user navigated away; discard results
                with self._devices_lock:
                    self.s["devices"] = devs
                    # Fill any still-missing creds (id, then IP fallback) and remember the
                    # resulting set — so a device unreachable at probe time can still be
                    # configured, and its creds carry to the next folder.
                    self._apply_session_creds(devs)
                    self._remember_session_creds(devs)

                def _fit_device_cols():
                    for col in cols:
                        if col == "Ruta en disco":
                            continue
                        w = max(
                            max((self._cw(str(tree.set(iid, col)), 16)
                                 for iid in tree.get_children()), default=0),
                            self._cw(col, 28),
                        )
                        tree.column(col, minwidth=w)

                self._post(lambda: (
                    _update_status(),
                    _fit_device_cols(),
                    self._btn_next.config(state="normal"),
                    save_btn.config(state="normal"),
                    names_btn.config(state="normal"),
                ))

                # Auto second pass: offline members revealed only through a hub can be
                # missed on the first sweep if the hub's connection wasn't up yet. When
                # there's a reachable device (a potential hub), re-run ONCE a few seconds
                # later so the user doesn't have to press «Redescubrir» by hand.
                if not _is_auto and not self.s.get("_disc_auto_retry_done"):
                    _hubs = [d.name for d in devs
                             if _device_kind(d) == "ok" and not d.is_local and d.api_key]
                    if _hubs:
                        self.s["_disc_auto_retry_done"] = True
                        if len(_hubs) == 1:
                            _hmsg = _T("🔄  Redescubriendo desde «{}»…").format(_hubs[0])
                        else:
                            _hmsg = _T('🔄  Redescubriendo desde {} dispositivos…').format(len(_hubs))

                        def _auto(hmsg=_hmsg):
                            if self._show_gen == my_gen:
                                self._status(hmsg, "#555")
                                self._run_probe(lambda: run(_is_auto=True))
                        self._post(lambda: self.after(4000, _auto))
            except Exception as e:
                msg = str(e)  # capture now: 'e' is deleted when the except block exits
                if self._show_gen == my_gen:
                    self._post(lambda: (
                        self._status(_T('Error: {}').format(msg), "#C62828"),
                        self._btn_next.config(state="normal"),
                    ))

        def _show_cached(cached: list):
            """Re-entry (Atrás→Adelante): show already-discovered devices instantly,
            no re-probe. A fresh probe only happens on first entry or 'Redescubrir'."""
            for dev in cached:
                _refresh_row(dev)
            for col in cols:
                if col == "Ruta en disco":
                    continue
                w = max(
                    max((self._cw(str(tree.set(iid, col)), 16)
                         for iid in tree.get_children()), default=0),
                    self._cw(col, 28),
                )
                tree.column(col, minwidth=w)
            _update_status()
            self._btn_next.config(state="normal")
            save_btn.config(state="normal")
            names_btn.config(state="normal")

        _force = self.s.pop("_force_rediscover", False)
        # A manual Redescubrir re-arms the one-shot automatic second pass.
        if _force:
            self.s["_disc_auto_retry_done"] = False
        with self._devices_lock:
            _cached = list(self.s.get("devices", []))
        if _cached and not _force:
            _show_cached(_cached)
            # Drop devices that no longer share THIS folder (left over e.g. after the folder
            # was deleted+recreated, the "raspberry pi huérfana" case): reconcile the cached
            # list against the folder's CURRENT membership in Syncthing — one cheap local API
            # call, no re-probe. Devices still pending in topology (manually added / is_new)
            # are kept. Runs in the background and removes only genuine orphans, so it never
            # delays the instant cached render.
            def _reconcile_orphans():
                folder = self.s.get("folder")
                client = self.s.get("client")
                if not folder or not client:
                    return
                try:
                    cur = client.get_folder(folder.id)
                except Exception:
                    return            # transient error → leave the list as-is
                if cur is None:
                    return            # folder gone → folder page handles that
                member_ids = {d.get("deviceID") for d in (cur.devices or [])}

                def _ui():
                    if self._show_gen != my_gen or not tree.winfo_exists():
                        return
                    # Re-read manual_topo_nodes / is_new nodes HERE, on the main thread, not on the
                    # worker before _post: the add-device dialog writes both, and a device added in
                    # the gap between the worker's snapshot and this callback would otherwise be
                    # absent from the stale sets → wrongly reaped as an orphan. Reading them now (and
                    # under the lock) keeps the reconcile in step with the live state.
                    manual = set(self.s.get("manual_topo_nodes") or {})
                    new_ids = {nid for nid, n in list(
                        (self.s.get("topology") or {}).get("nodes", {}).items())
                        if n.get("is_new")}
                    with self._devices_lock:
                        cur_devs = list(self.s.get("devices", []))
                        orphan_ids = {d.device_id for d in cur_devs if not (
                            d.is_local or d.device_id in member_ids
                            or d.device_id in manual or d.device_id in new_ids)}
                        if not orphan_ids:
                            return
                        self.s["devices"] = [d for d in cur_devs
                                             if d.device_id not in orphan_ids]
                    for _oid in orphan_ids:
                        if tree.exists(_oid):
                            tree.delete(_oid)
                    _update_status()
                self._post(_ui)
            threading.Thread(target=_reconcile_orphans, daemon=True).start()
        else:
            self._run_probe(run)

        # Live connectivity watch (#86): while on this page, poll the LOCAL Syncthing's
        # connected peers every ~20 s. If a device drops or reconnects, surface it in the
        # status bar (we don't auto re-probe — heavy — but the change is made visible).
        _conn_watch = {"seen": None}

        def _watch_conn():
            if self._show_gen != my_gen or not tree.winfo_exists():
                return
            client = self.s.get("client")

            def work():
                try:
                    conn = client.get_connected_devices() if client else {}
                    now = {d for d, ci in conn.items() if ci.connected}
                except Exception:
                    now = None

                def ui():
                    if self._show_gen != my_gen or not tree.winfo_exists():
                        return
                    if now is not None:
                        prev = _conn_watch["seen"]
                        if prev is not None and now != prev:
                            with self._devices_lock:
                                names = {d.device_id: d.name for d in self.s.get("devices", [])}
                            dropped = [names.get(x, x[:7]) for x in (prev - now)]
                            joined = [names.get(x, x[:7]) for x in (now - prev)]
                            parts = []
                            if dropped:
                                parts.append("se desconectó " + ", ".join(f"«{n}»" for n in dropped))
                            if joined:
                                parts.append("reconectó " + ", ".join(f"«{n}»" for n in joined))
                            if parts:
                                self._status("🔄  Cambios de conectividad: " + "; ".join(parts)
                                             + " — pulsa «Redescubrir» para actualizar.", "#C66000")
                        _conn_watch["seen"] = now
                    self.after(20000, _watch_conn)
                self._post(ui)
            threading.Thread(target=work, daemon=True).start()
        self.after(20000, _watch_conn)

        # ── Device name sync dialog ───────────────────────────────────────────

        def _open_name_sync_dialog():
            devs = self.s.get("devices", [])
            if not devs:
                return

            dlg = tk.Toplevel(self)
            dlg.title("Sincronizar nombres de dispositivos")
            if _IS_WIN:
                dlg.geometry(f"{min(560, self._win_w - 60)}x{min(500, self._win_h - 60)}")
            dlg.resizable(True, True)
            dlg.grab_set()
            self._center_dialog(dlg)
            dlg.configure(bg="white")

            tk.Label(dlg, text="Sincronizar nombres de dispositivos", bg="white",
                     font=(_FONT, 10, "bold")).pack(anchor="w", padx=14, pady=(12, 2))
            tk.Label(
                dlg,
                text="Define un nombre canónico para cada dispositivo. "
                     "Se aplicará en todos los equipos alcanzables (API, SSH, WinRM).\n"
                     "Solo se actualizan los pares ya configurados — no se crean nuevas entradas.",
                bg="white", fg="#666", font=(_FONT, 8), justify="left", wraplength=480,
            ).pack(anchor="w", padx=14, pady=(0, 6))
            ttk.Separator(dlg, orient="horizontal").pack(fill=tk.X, padx=14)

            # Opt-in to edit offline devices' names too (per-node config → applied later
            # via passive exploration / agent, since we can't reach them now).
            _offline_entries: list = []
            edit_offline_v = tk.BooleanVar(value=False)

            def _toggle_offline_edit():
                st = "normal" if edit_offline_v.get() else "disabled"
                for e in _offline_entries:
                    if e.winfo_exists():
                        e.config(state=st)
            tk.Checkbutton(dlg, text="Editar también equipos offline (se aplicarán al reconectar: "
                                     "exploración pasiva o agente)", variable=edit_offline_v,
                           command=_toggle_offline_edit, bg="white", font=(_FONT, 8),
                           anchor="w", justify="left", wraplength=480).pack(fill=tk.X, anchor="w",
                                                                            padx=14, pady=(4, 0))

            # ── Column headers ────────────────────────────────────────────────
            hdr = tk.Frame(dlg, bg="#F0F0F0")
            hdr.pack(fill=tk.X, padx=14, pady=(4, 0))
            tk.Label(hdr, text="", bg="#F0F0F0", width=2).pack(side=tk.LEFT)
            tk.Label(hdr, text="Dispositivo", bg="#F0F0F0",
                     font=(_FONT, 8, "bold"), width=20, anchor="w").pack(side=tk.LEFT, padx=(4, 0))
            tk.Label(hdr, text="Nombre actual", bg="#F0F0F0",
                     font=(_FONT, 8, "bold"), width=18, anchor="w").pack(side=tk.LEFT)
            tk.Label(hdr, text="Nombre nuevo", bg="#F0F0F0",
                     font=(_FONT, 8, "bold"), width=18, anchor="w").pack(side=tk.LEFT)

            # ── Scrollable rows ───────────────────────────────────────────────
            scroll_frm = tk.Frame(dlg, bg="white")
            scroll_frm.pack(fill=tk.BOTH, expand=True, padx=14)
            scroll_frm.grid_columnconfigure(0, weight=1)
            scroll_frm.grid_rowconfigure(0, weight=1)

            canvas = tk.Canvas(scroll_frm, bg="white", highlightthickness=0)
            vsb = ttk.Scrollbar(scroll_frm, orient="vertical", command=canvas.yview)
            canvas.configure(yscrollcommand=vsb.set)
            canvas.grid(row=0, column=0, sticky="nsew")
            vsb.grid(row=0, column=1, sticky="ns")
            vsb.grid_remove()  # hidden until content overflows

            inner = tk.Frame(canvas, bg="white")
            cwin = canvas.create_window((0, 0), window=inner, anchor="nw")

            _sync_pending = [False]

            def _sync_scroll_update(*_):
                if not canvas.winfo_exists():
                    return
                req_h = inner.winfo_reqheight()
                ch = canvas.winfo_height()
                if ch <= 1:
                    if not _sync_pending[0]:
                        _sync_pending[0] = True
                        def _retry():
                            _sync_pending[0] = False
                            _sync_scroll_update()
                        canvas.after(10, _retry)
                    return
                if req_h <= ch:
                    vsb.grid_remove()
                else:
                    vsb.grid()
                canvas.configure(scrollregion=(0, 0, canvas.winfo_width(), req_h))

            def _sync_canvas_cfg(e):
                canvas.itemconfig(cwin, width=e.width)
                _sync_scroll_update()

            inner.bind("<Configure>", _sync_scroll_update)
            canvas.bind("<Configure>", _sync_canvas_cfg)

            def _sync_mwheel(event):
                if inner.winfo_reqheight() > canvas.winfo_height():
                    canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

            canvas.bind("<MouseWheel>", _sync_mwheel)
            canvas.bind("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
            canvas.bind("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))

            name_vars: dict[str, tk.StringVar] = {}

            for dev in devs:
                row = tk.Frame(inner, bg="white")
                row.pack(fill=tk.X, pady=1)

                kind = _device_kind(dev)
                dot_fg = "#4CAF50" if kind == "ok" else ("#9E9E9E" if kind == "offline" else "#E65100")
                tk.Label(row, text="●", fg=dot_fg, bg="white", width=2,
                         font=(_FONT, 9)).pack(side=tk.LEFT)

                lbl = ("[local]  " if dev.is_local else "  ") + (dev.name[:18] or dev.device_id[:7])
                tk.Label(row, text=lbl, bg="white", width=22, anchor="w",
                         font=(_FONT, 9)).pack(side=tk.LEFT, padx=(4, 0))
                tk.Label(row, text=dev.name[:16], bg="white", fg="#888",
                         width=18, anchor="w", font=(_FONT, 9)).pack(side=tk.LEFT)

                v = tk.StringVar(value=dev.name)
                name_vars[dev.device_id] = v
                ent = ttk.Entry(row, textvariable=v, width=20)
                ent.pack(side=tk.LEFT, padx=(4, 0))
                if kind != "ok" and not dev.is_local:
                    ent.config(state="disabled")   # enabled by the "edit offline" checkbox
                    _offline_entries.append(ent)

            # ── Status + buttons ──────────────────────────────────────────────
            # Pack the button bar at the BOTTOM *first* so it always reserves its full
            # height; the status label and scroll area shrink instead of squashing the
            # buttons into thin clickable slivers when the result text is long (#88).
            btn_frm = tk.Frame(dlg, bg="white")
            btn_frm.pack(side=tk.BOTTOM, fill=tk.X, padx=14, pady=8)
            ttk.Separator(dlg, orient="horizontal").pack(side=tk.BOTTOM, fill=tk.X, padx=14)
            status_lbl = tk.Label(dlg, text="", bg="white", font=(_FONT, 8),
                                  wraplength=480, justify="left", anchor="w")
            status_lbl.pack(side=tk.BOTTOM, anchor="w", fill=tk.X, padx=14, pady=(4, 2))

            preview_v = tk.BooleanVar(value=True)
            _CheckButton(
                btn_frm, text="Solo previsualizar (no aplicar)", variable=preview_v,
            ).pack(side=tk.LEFT)

            def _cap_lines(lines, limit=8):
                """Bound the status text so a long per-device list can't grow the dialog
                past its fixed height and squash the buttons (#88)."""
                if len(lines) <= limit:
                    return "\n".join(lines)
                return "\n".join(lines[:limit] + [_T('  … y {} más').format(len(lines) - limit)])

            def do_apply():
                name_map = {
                    dev_id: v.get().strip()
                    for dev_id, v in name_vars.items()
                    if v.get().strip()
                }
                if not name_map:
                    return

                dry = preview_v.get()

                if dry:
                    lines = []
                    for dev in devs:
                        new_name = name_map.get(dev.device_id)
                        if not new_name or new_name == dev.name:
                            continue
                        kind = _device_kind(dev)
                        tag = "✓" if kind == "ok" else ("~ offline" if kind == "offline" else "✗ error")
                        lines.append(f"  {tag}  {dev.name}  →  {new_name}")
                    if lines:
                        status_lbl.config(
                            text=_T("[PREVISUALIZACIÓN — no se aplica nada]\n") + _cap_lines(lines),
                            fg="#1565C0",
                        )
                    else:
                        status_lbl.config(text="Sin cambios pendientes.", fg="#555")
                    return

                apply_btn.config(state="disabled", text="Aplicando…")
                status_lbl.config(text="Conectando con cada dispositivo…", fg="#555")

                def _work_impl():
                    from ..device_names import sync_device_names
                    results = sync_device_names(self.s["client"], devs, name_map)

                    # Update in-memory DeviceInfo names so the treeview stays consistent
                    with self._devices_lock:
                        for i, dev in enumerate(self.s["devices"]):
                            new_name = name_map.get(dev.device_id)
                            if new_name:
                                self.s["devices"][i].name = new_name

                    # If editing offline devices was opted in, queue the canonical names so
                    # they're applied to those equipos when they reconnect (passive) or via
                    # an agent. (sync_device_names skips unreachable ones now.)
                    pend_offline = 0
                    if edit_offline_v.get():
                        nc = self.s.setdefault("names_canonical", {})
                        nc.update(name_map)
                        pend_offline = sum(1 for d in devs if not d.is_local
                                           and _device_kind(d) != "ok"
                                           and name_map.get(d.device_id))

                    ok = sum(1 for r in results if r.success)
                    total_updated = sum(r.updated for r in results)

                    lines = []
                    for r in results:
                        if r.error:
                            lines.append(f"  ✗  {r.device.name}: {r.error}")
                        elif r.updated:
                            lines.append(
                                _T('  ✓  {}: {} nombre(s) propagado(s)').format(r.device.name, r.updated)
                            )
                        else:
                            lines.append(_T('  —  {}: sin cambios').format(r.device.name))

                    summary = (
                        _T('✓  {} nombre(s) actualizado(s) en {}/{} equipo(s)').format(total_updated, ok, len(results))
                    )
                    if pend_offline:
                        summary += (_T('  ·  {} offline pendiente(s) (se aplicarán al reconectar / por agente)').format(pend_offline))
                    color = "#2E7D32" if ok == len(results) else "#C66000"

                    def ui_done():
                        if not apply_btn.winfo_exists():
                            return
                        apply_btn.config(state="normal", text="Aplicar →")
                        status_lbl.config(text=summary + "\n" + _cap_lines(lines), fg=color)
                        # Changes are applied → "Cancelar" no longer fits; it's now "Salir".
                        # (Not persisted: reopening the dialog starts as "Cancelar" again.)
                        cancel_btn.config(text="Salir")
                        # Refresh device treeview rows with new names
                        with self._devices_lock:
                            _devs_snapshot = list(self.s["devices"])
                        for dev in _devs_snapshot:
                            _refresh_row(dev)
                        self._status(summary, color)

                    self._post(ui_done)

                def work():
                    # Never leave the button stuck on "Aplicando…": surface any failure and
                    # re-enable it (sync_device_names / the in-memory update could raise).
                    try:
                        _work_impl()
                    except Exception as e:
                        def _err(_e=e):
                            if not apply_btn.winfo_exists():
                                return
                            apply_btn.config(state="normal", text="Aplicar →")
                            status_lbl.config(text=_T('Error al sincronizar: {}').format(_e),
                                              fg="#C62828")
                        self._post(_err)

                threading.Thread(target=work, daemon=True).start()

            apply_btn = ttk.Button(btn_frm, text="Aplicar →", command=do_apply)
            apply_btn.pack(side=tk.RIGHT)
            cancel_btn = ttk.Button(btn_frm, text="Cancelar", command=dlg.destroy)
            cancel_btn.pack(side=tk.RIGHT, padx=(0, 6))

        # ── Hub expansion helper (called from background threads) ─────────────

        def _expand_hub_background(hub_dev: DeviceInfo) -> int:
            """
            Query hub_dev's Syncthing API (via direct API or SSH/WinRM proxy) for
            new devices sharing this folder.  Adds them to self.s["devices"] and
            inserts their rows into the treeview.
            Returns the number of newly discovered devices.
            Must be called from a background thread.
            """
            if not hub_dev.api_key:
                return 0
            if not (hub_dev.api_reachable or hub_dev.ssh_reachable or hub_dev.winrm_reachable):
                return 0

            # Build active credentials config (same as discovery flow). Reuse the
            # already-decrypted credentials cached during discovery; calling
            # load_credentials() here would return encrypted blobs (no master pw).
            saved = self.s.get("_saved_creds")
            if saved is None:
                saved = load_credentials()
            active_cfg = list(saved)
            if self.s.get("ssh_user") or self.s.get("ssh_key") or self.s.get("ssh_password"):
                active_cfg.append({
                    "ssh_user": self.s.get("ssh_user") or None,
                    "ssh_key_path": self.s.get("ssh_key") or None,
                    "ssh_password": self.s.get("ssh_password") or None,
                    "ssh_port": self.s.get("ssh_port", 22),
                })
            with self._devices_lock:
                for _dev in self.s["devices"]:
                    if not _dev.is_local and (_dev.api_key or _dev.ssh_user or _dev.winrm_user):
                        active_cfg.append({
                            "device_id":    _dev.device_id,
                            "api_key":      _dev.api_key or None,
                            "api_url":      _dev.api_url or None,
                            "ssh_user":     _dev.ssh_user or None,
                            "ssh_key_path": _dev.ssh_key_path or None,
                            "ssh_password": _dev.ssh_password or None,
                            "ssh_port":     _dev.ssh_port,
                            "winrm_user":   _dev.winrm_user or None,
                            "winrm_password": _dev.winrm_password or None,
                            "winrm_port":   _dev.winrm_port,
                        })
                known_ids = {d.device_id for d in self.s["devices"]}

            if hub_dev.api_reachable and hub_dev.api_url:
                new_entries = _query_hub_devices(hub_dev, folder.id, known_ids, active_cfg)
            else:
                new_entries = _query_hub_devices_via_remote(hub_dev, folder.id, known_ids, active_cfg)

            # Prefer the LOCAL node's own name for a revealed peer ONLY when WE have named it
            # (conflict resolution: if our config disagrees with the hub, our name wins; if we
            # never named it, the hub's name is used as-is — local doesn't "always" prevail).
            # Same rule as discover_devices._worker and the topology resolver, so all three
            # hub-expansion paths agree.
            local_cfg = {}
            try:
                _lc = self.s.get("client")
                if _lc:
                    local_cfg = {d.device_id: d for d in _lc.get_config_devices()}
            except Exception:
                local_cfg = {}

            # Probe outside lock (expensive I/O), then append under lock
            probed = []
            for hdev_id, hdev_name, hdev_ip, hdev_override in new_entries:
                _lc_dev = local_cfg.get(hdev_id)
                if _lc_dev and not _name_is_placeholder(_lc_dev.name, hdev_id):
                    hdev_name = _lc_dev.name   # local named it → authoritative on a conflict
                hdev_info = probe_device(
                    device_id=hdev_id, name=hdev_name,
                    ip=hdev_ip, folder_id=folder.id, override=hdev_override,
                )
                probed.append(hdev_info)

            added = 0
            for hdev_info in probed:
                if self._show_gen != my_gen:
                    break  # user navigated away — discard remaining results
                with self._devices_lock:
                    if any(d.device_id == hdev_info.device_id for d in self.s["devices"]):
                        continue
                    self.s["devices"].append(hdev_info)
                added += 1
                if self._show_gen == my_gen:
                    self._post(lambda d=hdev_info: _refresh_row(d))

            return added

        # ── Credential editor dialog ──────────────────────────────────────────

        def _open_edit_dialog():
            dev = _selected_device()
            if not dev:
                return

            dlg = tk.Toplevel(self)
            dlg.title(_T('Credenciales — {}').format(dev.name))
            if _IS_WIN:
                dlg.geometry(f"{min(580, self._win_w - 40)}x{min(660, self._win_h - 40)}")
            dlg.resizable(True, True)
            dlg.grab_set()
            self._center_dialog(dlg)
            dlg.configure(bg="white")

            tk.Label(dlg, text=_T('Editar credenciales: {}').format(dev.name), bg="white",
                     font=(_FONT, 10, "bold")).pack(anchor="w", padx=14, pady=(12, 4))
            ttk.Separator(dlg, orient="horizontal").pack(fill=tk.X, padx=14)

            grid = tk.Frame(dlg, bg="white")
            grid.pack(fill=tk.X, padx=14, pady=10)

            # Configured default ports (B7) used when the device still has the built-in
            # defaults, so a custom default port prefills instead of 22/5985/8384.
            _def_ssh = int(appconfig.get_setting("default_ssh_port", 22) or 22)
            _def_winrm = int(appconfig.get_setting("default_winrm_port", 5985) or 5985)
            _def_api = int(appconfig.get_setting("default_api_port", 8384) or 8384)
            _ssh_port0 = dev.ssh_port if dev.ssh_port != 22 else _def_ssh
            _winrm_port0 = dev.winrm_port if dev.winrm_port != 5985 else _def_winrm
            _api_url0 = dev.api_url or f"http://127.0.0.1:{_def_api}"
            fields = {}
            rows = [
                ("IP / Host:",        "ip",             dev.ip or "",              False, False),
                # ── SSH ──
                ("── SSH ──",         "_sep_ssh",        "",                        False, False),
                ("Puerto SSH:",       "ssh_port",       str(_ssh_port0),           False, False),
                ("Usuario SSH:",      "ssh_user",       dev.ssh_user or "",        False, False),
                ("Clave privada:",    "ssh_key",        dev.ssh_key_path or "",    True,  False),
                ("Contraseña SSH:",   "ssh_password",   dev.ssh_password or "",    False, True),
                # ── WinRM ──
                ("── WinRM (Win) ──", "_sep_winrm",     "",                        False, False),
                ("Usuario WinRM:",    "winrm_user",     dev.winrm_user or "",      False, False),
                ("Contraseña WinRM:", "winrm_password", dev.winrm_password or "",  False, True),
                ("Puerto WinRM:",     "winrm_port",     str(_winrm_port0),         False, False),
                # ── Syncthing ──
                ("── Syncthing ──",   "_sep_api",       "",                        False, False),
                ("URL de la API:",    "api_url",        _api_url0,                 False, False),
                ("API Key:",          "api_key",        dev.api_key or "",         False, True),
                ("Ruta de carpeta:",  "folder_path",    dev.folder_path or "",     False, False),
            ]
            for row_i, (lbl, key, val, has_browse, is_secret) in enumerate(rows):
                if key.startswith("_sep"):
                    tk.Label(grid, text=lbl, bg="white", fg="#888",
                             font=(_FONT, 8, "bold")).grid(
                        row=row_i, column=0, columnspan=3, sticky="w", pady=(8, 2))
                    continue
                tk.Label(grid, text=lbl, bg="white", anchor="e",
                         width=20).grid(row=row_i, column=0, sticky="e", pady=2)
                v = tk.StringVar(value=val)
                entry_width = 8 if key in ("ssh_port", "winrm_port") else 32
                e = ttk.Entry(grid, textvariable=v, width=entry_width,
                              show="●" if is_secret else "")
                e.grid(row=row_i, column=1, sticky="w", padx=(8, 0), pady=2)
                if has_browse:
                    ttk.Button(grid, text="…", width=3,
                               command=lambda ev=v: ev.set(
                                   filedialog.askopenfilename(title=_T("Clave SSH privada")) or ev.get()
                               )).grid(row=row_i, column=2, padx=(4, 0))
                hints = {
                    "ssh_port": "(22)", "winrm_port": "(5985)",
                    "ssh_password": "(alternativa a clave)",
                    "winrm_password": "(usuario Windows)",
                }
                if not dev.ip:  # offline / sin IP — la IP es opcional, se autodescubre
                    hints["ip"] = "(opcional — se autodescubre al reconectar)"
                if key in hints:
                    tk.Label(grid, text=hints[key], bg="white", fg="#888",
                             font=(_FONT, 8)).grid(row=row_i, column=2, sticky="w", padx=(4, 0))
                fields[key] = v

            # Operating system (E2/N6): LOCKED only when we truly DETECTED it (os_detected) —
            # detection is authoritative and runs in the background. Otherwise the user picks
            # Windows or Linux (no "Auto" radio — auto-detection isn't a manual choice); the
            # pick drives the agent template and POSIX-vs-Windows path validation.
            os_dlg_v = None
            osf = tk.Frame(dlg, bg="white")
            osf.pack(anchor="w", padx=14, pady=(2, 4))
            tk.Label(osf, text="Sistema:", bg="white", anchor="e", width=20).pack(side=tk.LEFT)
            if dev.os_detected and dev.os_type:
                _t = {"windows": "🪟 Windows", "macos": "🍎 macOS"}.get(dev.os_type, "🐧 Linux")
                tk.Label(osf, text=f"{_t}  · detectado", bg="white", fg="#2E7D32",
                         font=(_FONT, 9)).pack(side=tk.LEFT, padx=(8, 0))
            else:
                os_dlg_v = tk.StringVar(value=dev.os_type if dev.os_type in ("windows", "linux", "macos") else "")
                for _val, _txt in (("windows", "🪟 Windows"), ("linux", "🐧 Linux"), ("macos", "🍎 macOS")):
                    ttk.Radiobutton(osf, text=_txt, value=_val,
                                    variable=os_dlg_v).pack(side=tk.LEFT, padx=(4, 0))
                tk.Label(osf, text="(se autodetecta al conectar)", bg="white", fg="#888",
                         font=(_FONT, 8)).pack(side=tk.LEFT, padx=(8, 0))

            result_lbl = tk.Label(dlg, text="", bg="white", font=(_FONT, 8))
            result_lbl.pack(anchor="w", padx=14)

            # Parity with the add dialogs: a device added offline/passive may have no IP yet.
            # If it's connected RIGHT NOW, autodetect the IP from the local Syncthing on open
            # so the user can add SSH/API creds without hunting for the address.
            if not dev.ip:
                _edit_did = dev.device_id

                def _edit_detect_ip():
                    found = resolve_live_ip(self.s.get("client"), _edit_did)

                    def _ui():
                        if dlg.winfo_exists() and found and not fields["ip"].get().strip():
                            fields["ip"].set(found)
                            result_lbl.config(text=_T('IP autodetectada: {}').format(found),
                                              fg="#2E7D32")
                    self._post(_ui)
                threading.Thread(target=_edit_detect_ip, daemon=True).start()

            # F-c: if this device already shares the folder but its path is unknown here,
            # autodetect it from the device's OWN config (over API/SSH/WinRM) by the folder
            # ID — so editing credentials shows where the folder actually lives there.
            if not dev.folder_path and _device_kind(dev) == "ok":
                _cur_folder = self.s.get("folder")
                if _cur_folder:
                    _fid = _cur_folder.id

                    def _edit_detect_path():
                        found = resolve_remote_folder_path(dev, _fid)

                        def _ui():
                            if dlg.winfo_exists() and found and not fields["folder_path"].get().strip():
                                fields["folder_path"].set(found)
                        self._post(_ui)
                    threading.Thread(target=_edit_detect_path, daemon=True).start()

            btn_frm = tk.Frame(dlg, bg="white")
            btn_frm.pack(side=tk.BOTTOM, fill=tk.X, padx=14, pady=10)

            def _save_fields():
                """Read + validate + persist the typed credentials synchronously in the main
                thread (StringVars aren't thread-safe). Returns the parsed values dict, or
                None on a validation error. Persisting up-front — before the possibly-slow
                (~15 s on an offline device) probe — is what lets the user hit Guardar/
                Siguiente without losing creds, and what keeps offline devices' credentials
                for later passive exploration."""
                ip             = fields["ip"].get().strip()
                ssh_user       = fields["ssh_user"].get().strip() or None
                ssh_key        = fields["ssh_key"].get().strip() or None
                ssh_pw         = fields["ssh_password"].get().strip() or None
                winrm_user_val = fields["winrm_user"].get().strip() or None
                winrm_pw_val   = fields["winrm_password"].get().strip() or None
                try:
                    ssh_port_val   = int(fields["ssh_port"].get().strip() or 22)
                    winrm_port_val = int(fields["winrm_port"].get().strip() or 5985)
                except ValueError:
                    result_lbl.config(text="✗  Puerto inválido — debe ser un número.", fg="#C62828")
                    return None
                api_url        = fields["api_url"].get().strip()
                api_key        = fields["api_key"].get().strip()
                folder_path    = fields["folder_path"].get().strip()
                # Manually chosen OS (only when the selector is shown — i.e. not detected).
                # Never overrides a detected OS; os_detected stays False so detection can win.
                _sel_os = (os_dlg_v.get() if (os_dlg_v is not None
                           and os_dlg_v.get() in ("windows", "linux", "macos")) else None)

                import dataclasses as _dc_sync
                with self._devices_lock:
                    for _i, _d in enumerate(self.s["devices"]):
                        if _d.device_id == dev.device_id:
                            self.s["devices"][_i] = _dc_sync.replace(
                                _d,
                                ip=ip or _d.ip,
                                ssh_user=ssh_user or _d.ssh_user,
                                ssh_key_path=ssh_key or _d.ssh_key_path,
                                ssh_password=ssh_pw or _d.ssh_password,
                                ssh_port=ssh_port_val,
                                winrm_user=winrm_user_val or _d.winrm_user,
                                winrm_password=winrm_pw_val or _d.winrm_password,
                                winrm_port=winrm_port_val,
                                api_key=api_key or _d.api_key,
                                api_url=api_url or _d.api_url,
                                folder_path=folder_path or _d.folder_path,
                                os_type=_sel_os or _d.os_type,
                            )
                            break
                return {"ip": ip, "ssh_user": ssh_user, "ssh_key": ssh_key, "ssh_pw": ssh_pw,
                        "winrm_user_val": winrm_user_val, "winrm_pw_val": winrm_pw_val,
                        "ssh_port_val": ssh_port_val, "winrm_port_val": winrm_port_val,
                        "sel_os": _sel_os,
                        "api_url": api_url, "api_key": api_key, "folder_path": folder_path}

            def do_save() -> bool:
                """Guardar: persist the typed values, kick off the SAME connection probe as
                «Probar» but in the background, then close the dialog. The probe keeps running
                after close (its UI callbacks are guarded by winfo_exists) and updates the
                device row/status — so saving validates the credentials without making the
                user wait or press Probar separately."""
                if not do_test():   # persists + launches background probe; False on bad input
                    return False
                dlg.destroy()
                return True

            def do_test() -> bool:
                """Probar: persist the typed values, then probe the connection in the
                background (leaves the dialog open). False on validation error."""
                v = _save_fields()
                if v is None:
                    return False
                test_btn.config(state="disabled", text="Probando...")
                result_lbl.config(text="", fg="#555")
                ip             = v["ip"]
                ssh_user       = v["ssh_user"]
                ssh_key        = v["ssh_key"]
                ssh_pw         = v["ssh_pw"]
                winrm_user_val = v["winrm_user_val"]
                winrm_pw_val   = v["winrm_pw_val"]
                ssh_port_val   = v["ssh_port_val"]
                winrm_port_val = v["winrm_port_val"]
                api_url        = v["api_url"]
                api_key        = v["api_key"]
                folder_path    = v["folder_path"]
                sel_os         = v["sel_os"]

                def _work_impl():
                    from ..discovery import probe_device, probe_device_manual
                    import dataclasses

                    override = {
                        "ssh_user": ssh_user, "ssh_key_path": ssh_key,
                        "ssh_password": ssh_pw, "ssh_port": ssh_port_val,
                        "winrm_user": winrm_user_val, "winrm_password": winrm_pw_val,
                        "winrm_port": winrm_port_val,
                    }

                    has_ssh   = bool(ssh_user or ssh_key or ssh_pw)
                    has_winrm = bool(winrm_user_val and winrm_pw_val)

                    if has_ssh or has_winrm:
                        # SSH/WinRM credentials present → full probe.
                        # This SSHs in, reads config.xml, discovers api_key and
                        # folder_path, and sets ssh_reachable=True on success.
                        new_dev = probe_device(
                            device_id=dev.device_id, name=dev.name,
                            ip=ip, folder_id=folder.id, override=override,
                        )
                        # If user explicitly entered api_key or api_url, prefer
                        # those over the values discovered from config.xml.
                        final_key = api_key or new_dev.api_key
                        final_url = api_url or new_dev.api_url
                        final_path = folder_path or new_dev.folder_path
                        if (final_key != new_dev.api_key
                                or final_url != new_dev.api_url
                                or final_path != new_dev.folder_path):
                            new_dev = dataclasses.replace(
                                new_dev,
                                api_key=final_key,
                                api_url=final_url,
                                folder_path=final_path,
                            )
                    elif api_key and api_url:
                        # No SSH/WinRM — try direct API ping only
                        new_dev = probe_device_manual(
                            device_id=dev.device_id, name=dev.name,
                            ip=ip, folder_id=folder.id,
                            api_key=api_key, api_url=api_url,
                            folder_path=folder_path,
                            ssh_user=None, ssh_key_path=None,
                            ssh_password=None, ssh_port=ssh_port_val,
                        )
                    else:
                        # Nothing actionable — just update the stored fields
                        new_dev = dataclasses.replace(
                            dev,
                            ip=ip or dev.ip,
                            api_url=api_url or dev.api_url,
                            api_key=api_key or dev.api_key,
                            folder_path=folder_path or dev.folder_path,
                        )

                    # Always keep whatever the user typed, even if the probe failed or
                    # the device has no IP (probe_device returns early on no-IP without
                    # carrying the override creds). This is what makes offline devices'
                    # SSH/WinRM/API credentials persist for later passive exploration.
                    # Preserve the user's MANUAL OS pick unless the probe actually DETECTED one:
                    # the probe rebuilds new_dev with os_type=None when it can't reach the device
                    # (exactly the offline case where the manual pick matters), which would
                    # otherwise silently discard the Windows/Linux choice _save_fields stored and
                    # break agent-template selection / path validation for that device.
                    _os = new_dev.os_type if new_dev.os_detected else (sel_os or new_dev.os_type)
                    new_dev = dataclasses.replace(
                        new_dev,
                        ip=ip or new_dev.ip,
                        ssh_user=ssh_user or new_dev.ssh_user,
                        ssh_key_path=ssh_key or new_dev.ssh_key_path,
                        ssh_password=ssh_pw or new_dev.ssh_password,
                        ssh_port=ssh_port_val,
                        winrm_user=winrm_user_val or new_dev.winrm_user,
                        winrm_password=winrm_pw_val or new_dev.winrm_password,
                        winrm_port=winrm_port_val,
                        api_key=api_key or new_dev.api_key,
                        api_url=api_url or new_dev.api_url,
                        folder_path=folder_path or new_dev.folder_path,
                        os_type=_os,
                    )

                    # Persist updated device in wizard state
                    with self._devices_lock:
                        devs = self.s["devices"]
                        for i, d in enumerate(devs):
                            if d.device_id == new_dev.device_id:
                                devs[i] = new_dev
                                break
                    # Reachable now → it's configured directly; drop it from the passive/agent
                    # queues so it's no longer listed/handled as "al reconectar". Under the lock:
                    # the Execute passive loop / _refresh_status mutate these same set/list off-thread.
                    if new_dev.api_reachable or new_dev.ssh_reachable or new_dev.winrm_reachable:
                        with self._devices_lock:
                            self.s.get("passive_devices", set()).discard(new_dev.device_id)
                            self.s["agent_devices"] = [a for a in self.s.get("agent_devices", [])
                                                       if a.device_id != new_dev.device_id]

                    def _conn_msg() -> tuple:
                        if new_dev.api_reachable:
                            return "✓  Guardado — API accesible directamente", "#2E7D32"
                        if new_dev.ssh_reachable:
                            return "✓  Guardado — SSH OK (API accesible en localhost del dispositivo)", "#2E7D32"
                        if new_dev.winrm_reachable:
                            return "✓  Guardado — WinRM OK (API accesible en localhost del dispositivo)", "#2E7D32"
                        return (
                            _T('✗  Sin conexión: {}').format(new_dev.ssh_error or new_dev.api_error or 'desconocido'),
                            "#C62828",
                        )

                    _msg, _color = _conn_msg()
                    # Refresh row immediately; button stays disabled during hub expansion
                    _reachable = (new_dev.api_reachable or new_dev.ssh_reachable
                                  or new_dev.winrm_reachable)
                    self._post(lambda m=_msg, c=_color, r=_reachable, nm=new_dev.name: (
                        _refresh_row(new_dev),
                        result_lbl.config(text=m, fg=c),
                        self._status(_T('🔄  Re-descubriendo dispositivos desde {}…').format(nm), "#555")
                        if r else None,
                    ))

                    # Hub expansion: discover devices reachable via this hub
                    n_new = _expand_hub_background(new_dev)

                    def ui_finish(n=n_new, msg=_msg, color=_color,
                                  r=_reachable, nm=new_dev.name):
                        _update_status()  # refresh device counts (incl. any new ones)
                        try:
                            test_btn.config(state="normal", text="Probar")
                            # Make the re-discovery outcome explicit in the status bar
                            # (otherwise the device-count text overwrites it instantly).
                            if r:
                                extra = _T('{} dispositivo(s) nuevo(s)').format(n) if n > 0 else "sin dispositivos nuevos"
                                self._status(f"🔄  Redescubrimiento desde {nm}: {extra}",
                                             "#2E7D32" if n > 0 else "#555")
                            if n > 0 and dlg.winfo_exists():
                                result_lbl.config(
                                    text=msg + _T('\n↳ {} dispositivo(s) nuevo(s) descubierto(s)').format(n),
                                    fg=color,
                                )
                        except Exception:
                            pass

                    self._post(ui_finish)

                def work():
                    # Never leave 'Probar' stuck on "Probando…": surface any failure and
                    # restore the button (probe / hub expansion could raise).
                    try:
                        _work_impl()
                    except Exception as e:
                        def _err(_e=e):
                            if test_btn.winfo_exists():
                                test_btn.config(state="normal", text="Probar")
                            if result_lbl.winfo_exists():
                                result_lbl.config(
                                    text=_T('Error al probar: {}').format(_e), fg="#C62828")
                        self._post(_err)

                self._run_probe(work)   # gates Devices "Siguiente" while this probe runs
                return True

            # Guardar (primary, rightmost) = persist + close. Probar = persist + probe,
            # leaving the dialog open so the user can see the connection result.
            ttk.Button(btn_frm, text="Guardar", command=do_save).pack(side=tk.RIGHT)
            test_btn = ttk.Button(btn_frm, text="Probar", command=do_test)
            test_btn.pack(side=tk.RIGHT, padx=(0, 6))

            # Enter = Guardar (persist + close). Any in-flight hub expansion keeps running
            # in the background after close (guarded by winfo_exists). Only in this dialog.
            dlg.bind("<Return>", lambda _e=None: do_save())

        # ── SSH retry ─────────────────────────────────────────────────────────

        def _retry_selected():
            dev = _selected_device()
            if not dev:
                return
            self._status(_T("Reintentando {}...").format(dev.name), "#555")
            retry_btn.config(state="disabled")
            edit_btn.config(state="disabled")

            def _work_impl():
                from ..discovery import probe_device
                override = {
                    "ssh_user": dev.ssh_user, "ssh_key_path": dev.ssh_key_path,
                    "ssh_password": dev.ssh_password, "ssh_port": dev.ssh_port,
                    "winrm_user": dev.winrm_user, "winrm_password": dev.winrm_password,
                    "winrm_port": dev.winrm_port,
                }
                new_dev = probe_device(
                    device_id=dev.device_id, name=dev.name,
                    ip=dev.ip, folder_id=folder.id, override=override,
                )
                with self._devices_lock:
                    devs = self.s["devices"]
                    for i, d in enumerate(devs):
                        if d.device_id == new_dev.device_id:
                            devs[i] = new_dev
                            break

                # Quick row update — buttons stay disabled during expansion
                def ui_quick():
                    _refresh_row(new_dev)
                    if new_dev.api_reachable:
                        self._status(f"✓ {dev.name} OK", "#2E7D32")
                    elif new_dev.ssh_reachable or new_dev.winrm_reachable:
                        self._status(_T("✓ {} — SSH/WinRM OK, redescubriendo…").format(dev.name), "#555")
                    else:
                        self._status(
                            f"✗ {dev.name}: {new_dev.ssh_error or new_dev.api_error}", "#C62828")
                self._post(ui_quick)

                # Hub expansion via SSH/WinRM or direct API
                n_new = _expand_hub_background(new_dev)

                def ui_done(n=n_new):
                    _update_status()  # always runs first
                    try:
                        _on_select()
                    except Exception:
                        pass
                    if n > 0:
                        self._status(_T('↳ {}: {} dispositivo(s) nuevo(s) descubierto(s)').format(dev.name, n), "#2E7D32")
                self._post(ui_done)

            def work():
                # Never leave the buttons stuck disabled: surface any failure and re-enable
                # them (probe_device / hub expansion could raise an unexpected error).
                try:
                    _work_impl()
                except Exception as e:
                    def _err(_e=e):
                        if retry_btn.winfo_exists():
                            retry_btn.config(state="normal")
                        if edit_btn.winfo_exists():
                            edit_btn.config(state="normal")
                        self._status(_T('Error al reintentar {}: {}').format(dev.name, _e),
                                     "#C62828")
                    self._post(_err)

            threading.Thread(target=work, daemon=True).start()

        def do_next():
            # Don't advance while a remote-access probe is still running — the device's
            # reachability isn't known yet, so it would be mis-routed to the agent/passive dialog.
            # (Belt-and-suspenders: the "Siguiente" button is also disabled during probes.)
            if self._probes_in_flight > 0:
                self._status(_T('Comprobando el acceso remoto… espera a que termine.'), "#C66000")
                return
            with self._devices_lock:
                devs = list(self.s["devices"])
            actionable = [d for d in devs if _device_kind(d) == "ok"]
            if not actionable:
                messagebox.showerror("Sin dispositivos", "No hay dispositivos alcanzables.")
                return

            problem = [d for d in devs if _device_kind(d) == "problem"]
            offline = [d for d in devs if _device_kind(d) == "offline"]

            if not problem and not offline:
                self.s["agent_devices"] = []
                self.s["passive_devices"] = set()
                self._show(3)
                return

            # ── Agent selection dialog ────────────────────────────────────────
            dlg = tk.Toplevel(self)
            dlg.title("Dispositivos sin acceso remoto")
            dlg.geometry(f"{min(680, self._win_w - 30)}x{min(500, self._win_h - 40)}")
            dlg.resizable(True, True)
            dlg.grab_set()
            self._center_dialog(dlg)
            dlg.configure(bg="white")

            tk.Label(dlg, text="Dispositivos sin acceso remoto",
                     bg="white", font=(_FONT, 10, "bold")).pack(anchor="w", padx=14, pady=(12, 2))
            ttk.Separator(dlg, orient="horizontal").pack(fill=tk.X, padx=14)

            tk.Label(dlg,
                     text="Elige cómo configurar cada dispositivo (puedes marcar ambas):\n"
                          "  🤖 Agente — ejecutable que se copia y corre en la máquina (offline, sin credenciales).\n"
                          "  🔎 Pasiva — se auto-configura al reconectarse mientras la ventana final siga abierta "
                          "(requiere credenciales).",
                     bg="white", fg="#555", font=(_FONT, 8), justify="left",
                     ).pack(anchor="w", padx=14, pady=(6, 6))

            agent_frm = tk.Frame(dlg, bg="white")
            agent_frm.pack(fill=tk.BOTH, expand=True, padx=14)
            agent_frm.grid_columnconfigure(0, weight=1)
            agent_frm.grid_rowconfigure(0, weight=1)

            canvas = tk.Canvas(agent_frm, bg="white", highlightthickness=0)
            vsb    = ttk.Scrollbar(agent_frm, orient="vertical", command=canvas.yview)
            canvas.configure(yscrollcommand=vsb.set)
            canvas.grid(row=0, column=0, sticky="nsew")
            vsb.grid(row=0, column=1, sticky="ns")
            vsb.grid_remove()  # hidden until content overflows

            scroll_frame = tk.Frame(canvas, bg="white")
            agent_cwin = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")

            _agent_pending = [False]

            def _agent_scroll_update(*_):
                if not canvas.winfo_exists():
                    return
                req_h = scroll_frame.winfo_reqheight()
                ch = canvas.winfo_height()
                if ch <= 1:
                    if not _agent_pending[0]:
                        _agent_pending[0] = True
                        def _retry():
                            _agent_pending[0] = False
                            _agent_scroll_update()
                        canvas.after(10, _retry)
                    return
                if req_h <= ch:
                    vsb.grid_remove()
                else:
                    vsb.grid()
                canvas.configure(scrollregion=(0, 0, canvas.winfo_width(), req_h))

            def _agent_canvas_cfg(e):
                canvas.itemconfig(agent_cwin, width=e.width)
                _agent_scroll_update()

            scroll_frame.bind("<Configure>", _agent_scroll_update)
            canvas.bind("<Configure>", _agent_canvas_cfg)

            def _agent_mwheel(event):
                if scroll_frame.winfo_reqheight() > canvas.winfo_height():
                    canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

            canvas.bind("<MouseWheel>", _agent_mwheel)
            canvas.bind("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
            canvas.bind("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))

            agent_vars:   dict[str, tk.BooleanVar] = {}
            passive_vars: dict[str, tk.BooleanVar] = {}
            cred_lbls:    dict[str, tk.Label]      = {}
            # device_ids whose Passive checkbox the user toggled by hand → don't let a later
            # credential save silently re-enable a box the user deliberately unticked.
            passive_user_set: set[str] = set()

            def _has_creds(d: DeviceInfo) -> bool:
                return bool(d.api_key or d.ssh_user or d.ssh_key_path or d.ssh_password
                            or (d.winrm_user and d.winrm_password))

            def _refresh_cred(dev_id: str):
                with self._devices_lock:
                    d = next((x for x in self.s["devices"] if x.device_id == dev_id), None)
                cl = cred_lbls.get(dev_id)
                if not cl or d is None:
                    return
                if getattr(d, "ssh_creds_rejected", False):
                    # Creds present but VERIFIED-REJECTED (probe got "auth failed"). Don't show a
                    # green "✓ cred." and don't auto-enable passive — retrying with bad creds is
                    # futile; the user must fix them first. Keyed on ssh_creds_rejected, NOT on the
                    # mere presence of ssh_error: an offline/no-IP device (the canonical passive
                    # target) also carries an ssh_error and must NOT be condemned as "inválidas".
                    cl.config(text="✗ cred. inválidas", fg="#C62828")
                    if dev_id in passive_vars:
                        passive_vars[dev_id].set(False)
                elif _has_creds(d):
                    cl.config(text="✓ cred.", fg="#2E7D32")
                    # Adding creds enables passive BY DEFAULT — but never override a box the user
                    # explicitly toggled (re-saving creds must not silently re-tick an untick).
                    if dev_id in passive_vars and dev_id not in passive_user_set:
                        passive_vars[dev_id].set(True)
                else:
                    cl.config(text="⚠ faltan", fg="#C66000")

            def _edit_creds_inline(dev: DeviceInfo, on_saved):
                import dataclasses as _dc
                ed = tk.Toplevel(dlg)
                ed.title(_T('Credenciales — {}').format(dev.name))
                ed.configure(bg="white")
                ed.resizable(False, False)
                ed.grab_set()
                self._center_dialog(ed)
                grid = tk.Frame(ed, bg="white")
                grid.pack(fill=tk.X, padx=14, pady=12)
                rows = [
                    ("IP / Host:",       "ip",            dev.ip or "",            False),
                    ("── SSH ──",        "_s1",           "",                      False),
                    ("Usuario SSH:",     "ssh_user",      dev.ssh_user or "",      False),
                    ("Clave privada:",   "ssh_key",       dev.ssh_key_path or "",  False),
                    ("Contraseña SSH:",  "ssh_password",  dev.ssh_password or "",  True),
                    ("Puerto SSH:",      "ssh_port",      str(dev.ssh_port),       False),
                    ("── WinRM ──",      "_s2",           "",                      False),
                    ("Usuario WinRM:",   "winrm_user",    dev.winrm_user or "",    False),
                    ("Contraseña WinRM:","winrm_password",dev.winrm_password or "",True),
                    ("Puerto WinRM:",    "winrm_port",    str(dev.winrm_port),     False),
                    ("── API ──",        "_s3",           "",                      False),
                    ("URL API:",         "api_url",       dev.api_url or "http://127.0.0.1:8384", False),
                    ("API Key:",         "api_key",       dev.api_key or "",       True),
                ]
                vs: dict[str, tk.StringVar] = {}
                r = 0
                for lbl, key, val, secret in rows:
                    if key.startswith("_s"):
                        tk.Label(grid, text=lbl, bg="white", fg="#888",
                                 font=(_FONT, 8, "bold")).grid(row=r, column=0, columnspan=2,
                                                               sticky="w", pady=(6, 2))
                        r += 1
                        continue
                    tk.Label(grid, text=lbl, bg="white", anchor="e", width=16).grid(
                        row=r, column=0, sticky="e", pady=2)
                    v = tk.StringVar(value=val)
                    vs[key] = v
                    ttk.Entry(grid, textvariable=v, width=28,
                              show="●" if secret else "").grid(row=r, column=1, sticky="w",
                                                               padx=(8, 0), pady=2)
                    if key == "ip":
                        tk.Label(grid, text="(opcional — se autodescubre al reconectar)",
                                 bg="white", fg="#888", font=(_FONT, 7)).grid(
                            row=r, column=2, sticky="w", padx=(6, 0))
                    elif key == "ssh_key":   # «…» examinar la clave privada
                        ttk.Button(grid, text="…", width=3,
                                   command=lambda vv=v: vv.set(
                                       filedialog.askopenfilename(title=_T("Clave SSH privada"))
                                       or vv.get())
                                   ).grid(row=r, column=2, sticky="w", padx=(4, 0))
                    r += 1

                def _save():
                    try:
                        sp = int(vs["ssh_port"].get().strip() or 22)
                        wp = int(vs["winrm_port"].get().strip() or 5985)
                    except ValueError:
                        messagebox.showerror("Error", "Puerto inválido — debe ser un número.")
                        return
                    with self._devices_lock:
                        for i, d in enumerate(self.s["devices"]):
                            if d.device_id == dev.device_id:
                                self.s["devices"][i] = _dc.replace(
                                    d,
                                    ip=vs["ip"].get().strip() or d.ip,
                                    ssh_user=vs["ssh_user"].get().strip() or None,
                                    ssh_key_path=vs["ssh_key"].get().strip() or None,
                                    ssh_password=vs["ssh_password"].get().strip() or None,
                                    ssh_port=sp,
                                    winrm_user=vs["winrm_user"].get().strip() or None,
                                    winrm_password=vs["winrm_password"].get().strip() or None,
                                    winrm_port=wp,
                                    api_url=vs["api_url"].get().strip() or d.api_url,
                                    api_key=vs["api_key"].get().strip() or None,
                                    # Creds just changed → the previous "rejected" verdict no
                                    # longer applies; clear it so a corrected device isn't stuck
                                    # showing "inválidas" (it's re-verified on the next probe).
                                    ssh_error=None,
                                    ssh_creds_rejected=False,
                                )
                                break
                    ed.destroy()
                    on_saved()

                bf = tk.Frame(ed, bg="white")
                bf.pack(side=tk.BOTTOM, fill=tk.X, padx=14, pady=10)
                ttk.Button(bf, text="Guardar", command=_save).pack(side=tk.RIGHT)
                ttk.Button(bf, text="Cancelar", command=ed.destroy).pack(side=tk.RIGHT, padx=(0, 6))
                ed.bind("<Return>", lambda e: _save())

            def _add_device_row(dev: DeviceInfo, label_suffix: str):
                row = tk.Frame(scroll_frame, bg="white")
                row.pack(fill=tk.X, pady=3)
                tk.Label(row, text=dev.name, bg="white", font=(_FONT, 8, "bold"),
                         width=16, anchor="w").pack(side=tk.LEFT)
                tk.Label(row, text=label_suffix, bg="white", fg="#888",
                         font=(_FONT, 7), width=14, anchor="w").pack(side=tk.LEFT)
                av = tk.BooleanVar(value=False)          # Agente NO por defecto
                agent_vars[dev.device_id] = av
                _CheckButton(row, variable=av, text="🤖 Agente").pack(side=tk.LEFT, padx=(4, 0))
                pv = tk.BooleanVar(value=True)           # Pasiva por defecto para todos
                passive_vars[dev.device_id] = pv
                _CheckButton(row, variable=pv, text="🔎 Pasiva",
                             command=lambda did=dev.device_id: passive_user_set.add(did)
                             ).pack(side=tk.LEFT, padx=(8, 0))
                cl = tk.Label(row, text="", bg="white", font=(_FONT, 7))
                cl.pack(side=tk.RIGHT)
                cred_lbls[dev.device_id] = cl
                ttk.Button(row, text="✏ Credenciales",
                           command=lambda d=dev: _edit_creds_inline(
                               d, lambda i=d.device_id: _refresh_cred(i))
                           ).pack(side=tk.RIGHT, padx=(6, 0))
                _refresh_cred(dev.device_id)

            if problem:
                if offline:
                    tk.Label(scroll_frame, text="Con problemas de conexión:",
                             bg="white", fg="#888", font=(_FONT, 8, "bold"),
                             ).pack(anchor="w", pady=(4, 0))
                for dev in problem:
                    _add_device_row(dev, f"({dev.ip})")

            if offline:
                if problem:
                    ttk.Separator(scroll_frame, orient="horizontal").pack(fill=tk.X, pady=(6, 2))
                tk.Label(scroll_frame, text="Sin IP conocida (offline):",
                         bg="white", fg="#888", font=(_FONT, 8, "bold"),
                         ).pack(anchor="w", pady=(4, 0))
                for dev in offline:
                    _add_device_row(dev, "(sin IP)")

            ttk.Separator(dlg, orient="horizontal").pack(fill=tk.X, padx=14, pady=(6, 0))
            btn_frm = tk.Frame(dlg, bg="white")
            btn_frm.pack(fill=tk.X, padx=14, pady=8)

            def _continue():
                with self._devices_lock:
                    by_id = {d.device_id: d for d in self.s["devices"]}
                agent_sel = []
                passive_ids: set = set()
                missing = []
                bad_creds = []
                for dev in problem + offline:
                    cur = by_id.get(dev.device_id, dev)
                    if agent_vars[dev.device_id].get():
                        agent_sel.append(cur)
                    if passive_vars[dev.device_id].get():
                        passive_ids.add(dev.device_id)
                        if not _has_creds(cur):
                            missing.append(cur.name)
                        elif getattr(cur, "ssh_creds_rejected", False):
                            bad_creds.append(cur.name)
                if missing:
                    if not messagebox.askyesno(
                        "Faltan credenciales",
                        _T('Marcaste exploración pasiva para {}, pero no tienen credenciales, así que no se podrán auto-configurar al reconectarse.\n\n¿Continuar igualmente?').format(', '.join(missing)),
                        icon="warning",
                    ):
                        return
                if bad_creds:
                    if not messagebox.askyesno(
                        "Credenciales inválidas",
                        _T('Marcaste exploración pasiva para {}, pero sus credenciales SSH fueron rechazadas, así que la auto-configuración fallará hasta que las corrijas.\n\n¿Continuar igualmente?').format(', '.join(bad_creds)),
                        icon="warning",
                    ):
                        return
                self.s["agent_devices"] = agent_sel
                self.s["passive_devices"] = passive_ids
                dlg.destroy()
                self._show(3)

            ttk.Button(btn_frm, text="Continuar →", command=_continue).pack(side=tk.RIGHT)
            ttk.Button(btn_frm, text="Omitir todos",
                       command=lambda: (
                           self.s.__setitem__("agent_devices", []),
                           self.s.__setitem__("passive_devices", set()),
                           dlg.destroy(),
                           self._show(3),
                       )).pack(side=tk.RIGHT, padx=(0, 6))

        self._next_handlers[2] = do_next
