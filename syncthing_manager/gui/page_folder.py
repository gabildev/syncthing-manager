from __future__ import annotations
from .common import *  # noqa: F401,F403


class FolderPageMixin:
    def _page_folder(self, f: tk.Frame):
        tk.Label(f, text="Seleccionar carpeta", bg="white",
                 font=(_FONT, 11, "bold")).pack(anchor="w")
        ttk.Separator(f, orient="horizontal").pack(fill=tk.X, pady=(6, 6))
        tk.Label(f, text="Haz doble clic en una fila o selecciónala y pulsa Siguiente →",
                 bg="white", fg="#888", font=(_FONT, 8)).pack(anchor="w", pady=(0, 8))
        _nf_bar = tk.Frame(f, bg="white")
        _nf_bar.pack(anchor="w", pady=(0, 6))
        ttk.Button(_nf_bar, text="➕ Nueva carpeta",
                   command=lambda: _new_folder()).pack(side=tk.LEFT)

        # Container frame — tree and scrollbar as direct children (avoids in_= issues on Windows)
        frm = tk.Frame(f, bd=2, relief="groove")
        frm.pack(fill=tk.BOTH, expand=True)

        cols = ("#", "ID", "Label", "Ruta local", "Dispositivos")
        tree = ttk.Treeview(frm, columns=cols, show="headings", height=11, selectmode="browse")
        for col, w, stretch, minw, anchor in zip(
            cols,
            [self._cw("99", 24), self._cw("ID", 60), self._cw("Label", 60),
             self._cw("Ruta local", 120), self._cw("Dispositivos", 32)],
            [False, False, False, True, False],
            [self._cw("99", 24), self._cw("ID", 20), self._cw("Label", 20),
             self._cw("Ruta local", 60), self._cw("Dispositivos", 20)],
            ["center", "w", "w", "w", "center"],
        ):
            tree.heading(col, text=col)
            tree.column(col, width=w, stretch=stretch, anchor=anchor, minwidth=minw)

        vsb = ttk.Scrollbar(frm, orient="vertical",   command=tree.yview)
        hsb = ttk.Scrollbar(frm, orient="horizontal", command=tree.xview)
        frm.grid_rowconfigure(0, weight=1)
        frm.grid_rowconfigure(1, weight=0)
        frm.grid_columnconfigure(0, weight=1)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        vsb.grid_remove()
        hsb.grid_remove()

        def _folder_vsb_set(first, last):
            vsb.set(first, last)
            if float(first) <= 0.0 and float(last) >= 1.0:
                vsb.grid_remove()
            else:
                vsb.grid()

        def _folder_hsb_set(first, last):
            hsb.set(first, last)
            if float(first) <= 0.0 and float(last) >= 1.0:
                hsb.grid_remove()
            else:
                hsb.grid()

        tree.configure(yscrollcommand=_folder_vsb_set, xscrollcommand=_folder_hsb_set)

        _ruta_local_minw = self._cw("Ruta local", 60)
        _folder_fixed_cols = [c for c in cols if c != "Ruta local"]

        def _enforce_folder_col_minw(e=None):
            avail = tree.winfo_width()
            if avail <= 1:
                return
            fixed_total = sum(tree.column(c, "width") for c in _folder_fixed_cols)
            remaining = avail - fixed_total
            if remaining < _ruta_local_minw:
                excess = _ruta_local_minw - remaining
                for c in reversed(_folder_fixed_cols):
                    cw = tree.column(c, "width")
                    cm = tree.column(c, "minwidth")
                    if cw > cm:
                        trim = min(cw - cm, excess)
                        tree.column(c, width=cw - trim)
                        excess -= trim
                        if excess <= 0:
                            break
                fixed_total = sum(tree.column(c, "width") for c in _folder_fixed_cols)
            tree.column("Ruta local", width=max(_ruta_local_minw, avail - fixed_total))

        tree.bind("<ButtonRelease-1>", _enforce_folder_col_minw)
        tree.bind("<Configure>", _enforce_folder_col_minw)

        _folder_init_widths = {
            "#": self._cw("99", 24), "ID": self._cw("ID", 60),
            "Label": self._cw("Label", 60), "Ruta local": self._cw("Ruta local", 120),
            "Dispositivos": self._cw("Dispositivos", 32),
        }

        def _reset_folder_cols():
            for c, w in _folder_init_widths.items():
                tree.column(c, width=w)
            _enforce_folder_col_minw()

        def _folder_rclick(event):
            menu = tk.Menu(tree, tearoff=0)
            menu.add_command(label="Restablecer columnas", command=_reset_folder_cols)
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        tree.bind("<Button-3>", _folder_rclick)

        self._btn_next.config(state="disabled")
        self._status("Cargando carpetas...", "#555")
        my_gen = self._show_gen

        # Double-click advances exactly like the Next button — both MUST go through do_select
        # (defined below) so the per-folder state reset (topology, overrides, passive/agent
        # queues, and the new-folder `devices` wipe) runs. Earlier the double-click used a
        # separate handler that skipped all of it, leaking the previous folder's state.
        # do_select is resolved at click time (after this method finishes building the page).
        tree.bind("<Double-1>", lambda _: do_select())

        # Signature of the last-rendered folder set, so the background poll only rebuilds the
        # tree when Syncthing's folders actually changed (added/removed/relabelled/moved) —
        # avoids flicker and needless selection churn on every tick.
        _folder_sig = {"v": None}

        def _sig_of(folders):
            # Rebuild only when the FOLDER SET itself changes (added/removed/relabelled/moved).
            # Deliberately excludes device-count: cluster churn (a peer joining/leaving a
            # folder) would otherwise trigger a full tree rebuild + selection/scroll
            # re-assertion every few seconds even though the folder list is unchanged. The
            # count cell just refreshes on the next real folder change or on navigation.
            return tuple((fl.id, fl.label, fl.path) for fl in folders)

        def _populate(folders, *, preserve):
            # Preserve the user's selection across a refresh (by folder ID); fall back to the
            # first row on the initial load or when the selected folder is gone (e.g. it was
            # just deleted in the Syncthing web UI — that now disappears here live).
            sel_id = None
            if preserve and tree.selection():
                try:
                    sel_id = tree.set(tree.selection()[0], "ID")
                except Exception:
                    sel_id = None
            _yview = tree.yview()   # remember scroll so a live refresh doesn't jump to the top
            tree.delete(*tree.get_children())
            rows = [(i, fl.id, fl.label or fl.id, fl.path, len(fl.devices))
                    for i, fl in enumerate(folders, 1)]
            for row in rows:
                tree.insert("", "end", iid=str(row[0]), values=row)
            # Fit fixed columns to content; Ruta local (stretch) fills the rest
            for col_idx, col in enumerate(cols):
                if col == "Ruta local":
                    continue
                w = max(max((self._cw(str(r[col_idx]), 16) for r in rows), default=0),
                        self._cw(col, 28))
                tree.column(col, width=w, minwidth=w)
            self.s["folders"] = folders
            self._status(_T('{} carpeta(s) — selecciona una y pulsa Siguiente →').format(len(folders)), "#2E7D32")
            self._btn_next.config(state="normal" if folders else "disabled")
            target = next((str(r[0]) for r in rows if r[1] == sel_id), None) if sel_id else None
            _preserved_sel = target is not None   # the user's own selection survived the refresh
            if target is None and rows:
                target = "1"
            if target:
                tree.selection_set(target)
                tree.focus(target)
            if preserve:
                # Restore the prior scroll position so a live refresh doesn't snap the view,
                # THEN make sure the row the user actually selected stays visible. tree.see()
                # only scrolls when that row would be off-screen, so the user keeps their
                # position when it's already visible. We DON'T see() the row-1 fallback (used
                # when the selected folder was just deleted elsewhere): jerking the view to the
                # top to show an auto-selected row the user didn't choose is more disruptive
                # than leaving them where they were reading.
                try:
                    tree.yview_moveto(_yview[0])
                    if target and _preserved_sel:
                        tree.see(target)
                except Exception:
                    pass

        def load(initial):
            try:
                folders = self.s["client"].get_folders()
            except Exception as e:
                msg = str(e)  # capture now: 'e' is deleted when the except block exits
                if initial and self._show_gen == my_gen:
                    self._post(lambda: self._status(_T('Error cargando carpetas: {}').format(msg), "#C62828"))
                return
            if self._show_gen != my_gen:
                return
            sig = _sig_of(folders)
            if sig == _folder_sig["v"]:
                return   # unchanged → leave the tree (and the user's selection) untouched
            def update():
                if self._show_gen != my_gen:
                    return
                _folder_sig["v"] = sig
                _populate(folders, preserve=not initial)
            self._post(update)

        # In-flight guard: never stack poll threads if a get_folders() runs slow — otherwise
        # multiple threads would hit the shared requests.Session concurrently (not thread-safe).
        _poll_busy = {"v": False}

        def _spawn_load(initial):
            if _poll_busy["v"]:
                return
            _poll_busy["v"] = True

            def _run():
                try:
                    load(initial)
                finally:
                    _poll_busy["v"] = False
            threading.Thread(target=_run, daemon=True).start()

        def _poll_folders():
            # Live refresh: reflect folders added/removed in the Syncthing web UI without
            # leaving this page. Stops automatically when the wizard navigates elsewhere.
            if self._show_gen != my_gen:
                return
            _spawn_load(False)
            self.after(4000, _poll_folders)

        _spawn_load(True)
        self.after(4000, _poll_folders)

        def do_select():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("Selección", "Selecciona una carpeta de la lista.")
                return
            idx = int(sel[0]) - 1
            if not (0 <= idx < len(self.s["folders"])):
                return
            chosen = self.s["folders"][idx]
            # Leaving a NEW folder created this session that was never executed → offer ONCE to
            # delete it (unconfigured local folder / testing leftover). Only when actually moving
            # to a DIFFERENT folder; default keep.
            _pend = self.s.get("_pending_new_folder")
            if _pend and _pend.get("id") and _pend["id"] != chosen.id:
                self._maybe_prompt_orphan_cleanup()
            # Switching to a DIFFERENT folder resets the per-folder state (topology, links,
            # overrides, passive/agent queues) — those are folder-scoped. We do NOT wipe the
            # discovered devices: a device's CREDENTIALS are the same regardless of which
            # folder you manage, so keeping them lets you hop between folders without
            # re-entering SSH/API creds. A forced re-discovery then re-probes those devices
            # against the NEW folder (carrying their creds over), refreshing their folder
            # membership/path/role; the topology rebuild + reconcile prune then drop anyone
            # who doesn't share the new folder. (Per-folder SSH-user tweaks still possible
            # by editing the device afterwards.)
            prev = self.s.get("folder")
            # Before any reset/clear below, remember the outgoing folder's device credentials
            # so the same devices come pre-filled in the next folder (session-only, never disk).
            self._remember_session_creds(self.s.get("devices", []))
            # Reset the per-folder state on a folder SWITCH — and ALSO when re-selecting a
            # freshly-CREATED folder even if its id matches a just-deleted one. Otherwise
            # `prev.id == chosen.id` skips the reset and the deleted folder's residual state
            # (topology_orig, manual nodes, stale devices…) resurrects as ghost nodes / a blank
            # preview / GET-404. The rename-step inputs etc. are reset inside the shared helper.
            _fresh = self.s.get("_new_folder_fresh") == chosen.id
            if prev is None or prev.id != chosen.id or _fresh:
                self._reset_folder_scoped_state()
                self.s["_force_rediscover"] = True
                # A brand-new folder is local-only: drop the previous folder's discovered
                # devices so they don't show in the Devices list (the forced re-discovery
                # repopulates it — just the local node for a new folder). For existing→existing
                # hops we keep `devices` so credentials carry over (re-discovery prunes them).
                # Only consume the marker when the just-created folder is the one actually
                # selected — otherwise picking a different folder first would eat the marker and
                # the new folder would later inherit that folder's device list.
                if _fresh:
                    self.s.pop("_new_folder_fresh", None)
                    self.s["devices"] = []
            self.s["folder"] = chosen
            self.s["local_folder_gone"] = False   # fresh folder → local is the hub again
            # Remember (for THIS folder session) that it's a brand-new folder, so the final
            # "Deshacer" on the Execute screen can offer to also DELETE it — not just revert
            # the topology. Set explicitly every selection so it's True only for the fresh one.
            self.s["folder_is_new"] = bool(_fresh)
            # Track this brand-new folder so, if the user abandons it without ever executing,
            # _maybe_prompt_orphan_cleanup can offer to delete it (cleared on a real execute).
            if _fresh:
                self.s["_pending_new_folder"] = {"id": chosen.id, "label": chosen.label,
                                                 "path": chosen.path}
            self._show(2)

        def _new_folder():
            """Create a brand-new folder on THIS (local) node — immediate and local (it's
            your folder on your node; no device pairing happens here). Sharing it with other
            devices is done afterwards via Topología, following the normal reachable / passive
            / agent / manual-accept model."""
            client = self.s.get("client")
            if not client:
                messagebox.showinfo("Nueva carpeta", "Sin conexión con Syncthing.", parent=self)
                return
            dlg = tk.Toplevel(self)
            dlg.title("Nueva carpeta")
            dlg.configure(bg="white")
            dlg.transient(self)
            dlg.grab_set()
            self._center_dialog(dlg)
            tk.Label(dlg, text="Crear una carpeta nueva en este equipo", bg="white",
                     font=(_FONT, 10, "bold")).pack(anchor="w", padx=16, pady=(12, 2))
            tk.Label(dlg, text="Se crea aquí, en el nodo local. Para compartirla con otros "
                               "equipos, hazlo luego en Topología.", bg="white", fg="#888",
                     font=(_FONT, 8), wraplength=420, justify="left").pack(anchor="w", padx=16)
            grid = tk.Frame(dlg, bg="white")
            grid.pack(fill=tk.X, padx=16, pady=(6, 0))
            label_v = tk.StringVar()
            id_v = tk.StringVar()
            path_v = tk.StringVar()
            _id_edited = {"v": False}
            _label_edited = {"v": False}

            def _add_row(r, lbl, var, width=32):
                tk.Label(grid, text=lbl, bg="white", anchor="e", width=8).grid(
                    row=r, column=0, sticky="e", pady=3)
                e = ttk.Entry(grid, textvariable=var, width=width)
                e.grid(row=r, column=1, sticky="w", padx=(8, 0))
                return e
            label_entry = _add_row(0, "Label:", label_v)
            # A manual label edit stops the path→label autofill (below): once you type your own
            # label, editing the path afterwards never clobbers it.
            label_entry.bind("<KeyRelease>", lambda _e: _label_edited.__setitem__("v", True))
            id_entry = _add_row(1, "ID:", id_v)
            id_entry.bind("<KeyRelease>", lambda _e: _id_edited.__setitem__("v", True))
            # Live ID-collision check, inline right under the ID field (no popup): empty while
            # the ID is free, a red note the moment it clashes with an existing folder so you can
            # pick another before clicking Crear. _create() repeats it as the final gate. (A
            # folder ID must be unique on the device — Syncthing can't hold two with the same id.)
            id_msg = tk.Label(grid, text="", bg="white", fg="#C62828", font=(_FONT, 8),
                              anchor="w", justify="left", wraplength=300)
            id_msg.grid(row=2, column=1, columnspan=2, sticky="w")

            def _check_id(*_):
                fid = id_v.get().strip()
                clash = fid and any(fl.id == fid for fl in self.s.get("folders", []))
                id_msg.config(text="⚠ Ya existe una carpeta con ese ID — elige otro." if clash else "")
            id_v.trace_add("write", _check_id)

            def _on_label(*_):
                # Derive the ID from the label PRESERVING its case (Syncthing IDs are
                # case-sensitive and may be mixed-case): "Testeo" → "Testeo", not "testeo".
                # Only spaces / illegal chars collapse to '-'.
                if not _id_edited["v"]:
                    id_v.set(re.sub(r"[^A-Za-z0-9-]+", "-", label_v.get().strip()).strip("-"))
            label_v.trace_add("write", _on_label)
            _add_row(3, "Ruta:", path_v, width=24)

            def _on_path(*_):
                # Keep the label (and, through _on_label, the ID) in step with the LAST path
                # segment as you build the path — pick "…/Desktop" then append "/Testeo" and the
                # label/ID follow to "Testeo". Stops the moment you edit the label by hand
                # (_label_edited): it's a convenience default, never a lock.
                if not _label_edited["v"]:
                    base = Path(path_v.get().strip().rstrip("/\\")).name
                    if base:
                        label_v.set(base)
            path_v.trace_add("write", _on_path)

            def _browse_path():
                # Pick a directory in the explorer; the path trace above autofills label/ID from
                # its name (unless you've already typed your own label).
                chosen = filedialog.askdirectory(mustexist=False, parent=dlg)
                if chosen:
                    path_v.set(chosen)
            ttk.Button(grid, text="Examinar…", command=_browse_path).grid(
                row=3, column=2, padx=(4, 0))
            tk.Label(grid, text="(se crea si no existe; el explorador permite crear carpetas)",
                     bg="white", fg="#888", font=(_FONT, 8)).grid(
                row=4, column=1, columnspan=2, sticky="w")
            st = tk.Label(dlg, text="", bg="white", font=(_FONT, 8))
            st.pack(anchor="w", padx=16, pady=(4, 0))
            btnf = tk.Frame(dlg, bg="white")
            btnf.pack(fill=tk.X, padx=16, pady=12)

            def _create():
                lbl = label_v.get().strip()
                fid = id_v.get().strip()
                path = path_v.get().strip()
                if not lbl:
                    st.config(text="El label no puede estar vacío.", fg="#C62828"); return
                if not fid:
                    st.config(text="El ID no puede estar vacío.", fg="#C62828"); return
                # Keep the id URL-safe: it's interpolated into REST path segments
                # (/rest/config/folders/{id}) all over the app, so a space/special char
                # would break those calls. The auto-derived id is already safe; this guards
                # a manually-typed one.
                if not re.fullmatch(r"[A-Za-z0-9._-]+", fid):
                    st.config(text="El ID solo puede tener letras, números y . _ - "
                                   "(sin espacios).", fg="#C62828"); return
                if not path:
                    st.config(text="Indica una ruta.", fg="#C62828"); return
                if any(fl.id == fid for fl in self.s.get("folders", [])):
                    st.config(text="Ya existe una carpeta con ese ID.", fg="#C62828"); return
                st.config(text="Creando…", fg="#555")

                def work():
                    try:
                        # POST /rest/config/folders is an UPSERT, not a create: a duplicate id
                        # silently OVERWRITES the existing folder's config (path/devices/type).
                        # The in-memory list can be stale (4s poll / external change), so re-check
                        # on the SERVER right before creating and abort instead of clobbering.
                        try:
                            exists = client.get_folder(fid) is not None
                            check_failed = False
                        except Exception:
                            # get_folder returns None ONLY on 404; it RE-RAISES timeouts/5xx/auth.
                            # Don't create on an UNVERIFIED check — the UPSERT could clobber an
                            # existing folder. Fail safe: abort and ask the user to retry.
                            exists, check_failed = False, True
                        if check_failed:
                            err = "__checkfail__"
                        elif exists:
                            err = "__clash__"
                        else:
                            try:
                                Path(path).expanduser().mkdir(parents=True, exist_ok=True)
                            except OSError:
                                pass   # Syncthing also creates the path; ignore mkdir issues here
                            my_id = self.s.get("my_id") or client.get_my_device_id()
                            client.create_folder({
                                "id": fid, "label": lbl, "path": path, "type": "sendreceive",
                                "fsWatcherEnabled": True, "rescanIntervalS": 3600,
                                "devices": [{"deviceID": my_id}]})
                            # Scan immediately so the .stfolder marker is written now (consistent
                            # with the remote topology-create path); the dir already exists.
                            try:
                                client.rescan_folder(fid)
                            except Exception:
                                pass
                            err = None
                    except Exception as e:
                        err = str(e)

                    def ui():
                        if err == "__checkfail__":
                            st.config(text="No se pudo verificar si el ID ya existe (error de "
                                           "conexión). Reintenta.", fg="#C62828")
                            return
                        if err == "__clash__":
                            st.config(text="Ya existe una carpeta con ese ID (en el servidor) — "
                                           "elige otro.", fg="#C62828")
                            return
                        if err:
                            st.config(text=_T('Error: {}').format(err), fg="#C62828")
                            return
                        if dlg.winfo_exists():
                            dlg.destroy()
                        self._status(_T('Carpeta «{}» creada en este equipo.').format(lbl), "#2E7D32")
                        # Mark it so selecting it starts with a fresh (local-only) device list
                        # instead of inheriting the previously managed folder's devices.
                        self.s["_new_folder_fresh"] = fid
                        self._show(1)   # reload the folder list (now includes the new one)
                    self._post(ui)
                threading.Thread(target=work, daemon=True).start()
            ttk.Button(btnf, text="Crear", command=_create).pack(side=tk.RIGHT)
            ttk.Button(btnf, text="Cancelar", command=dlg.destroy).pack(side=tk.RIGHT, padx=(0, 6))

        self._next_handlers[1] = do_select
