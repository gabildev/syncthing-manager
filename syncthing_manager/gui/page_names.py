from __future__ import annotations
from .common import *  # noqa: F401,F403


class NamesPageMixin:
    def _page_rename(self, f: tk.Frame):
        folder: FolderConfig = self.s["folder"]

        tk.Label(f, text="Nuevo nombre", bg="white",
                 font=(_FONT, 11, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Separator(f, orient="horizontal").grid(
            row=1, column=0, columnspan=3, sticky="ew", pady=(6, 14))

        # Current info
        for row, label, value in [
            (2, "Label actual:", folder.label or folder.id),
            (3, "Ruta actual:", folder.path),
        ]:
            tk.Label(f, text=label, bg="white", fg="#666",
                     font=(_FONT, 9)).grid(row=row, column=0, sticky="w", pady=1)
            tk.Label(f, text=value, bg="white",
                     font=(_FONT, 9, "bold")).grid(
                row=row, column=1, columnspan=2, sticky="w", padx=(10, 0), pady=1)

        ttk.Separator(f, orient="horizontal").grid(
            row=4, column=0, columnspan=3, sticky="ew", pady=(10, 12))

        # Each target (label / path / ID) has its OWN enable toggle so the user can change
        # any subset independently (B6/N2). The path toggle is the ONLY one ticked by
        # default — renaming the directory on disk is the program's original purpose.
        change_label_v = tk.BooleanVar(value=False)
        label_v = tk.StringVar(value=self.s["new_label"] or folder.label or "")
        label_entry = ttk.Entry(f, textvariable=label_v, width=40)
        label_entry.grid(row=5, column=1, columnspan=2, sticky="w", padx=(10, 0), pady=3)

        def _update_label_state():
            label_entry.config(state="normal" if change_label_v.get() else "disabled")
        _CheckButton(f, text="Cambiar label:", variable=change_label_v,
                     command=_update_label_state).grid(row=5, column=0, sticky="w")

        # New path / name — with its own toggle (N2). `skip_path` is just its inverse:
        # path unchecked == "solo cambiar el label" (the old standalone checkbox, removed).
        change_path_v = tk.BooleanVar(value=not self.s["skip_path"])
        path_v = tk.StringVar(value=self.s["new_path_input"] or folder.label or "")

        path_row = tk.Frame(f, bg="white")
        path_row.grid(row=6, column=1, columnspan=2, sticky="w", padx=(10, 0), pady=(10, 0))
        path_entry = ttk.Entry(path_row, textvariable=path_v, width=36)
        path_entry.pack(side=tk.LEFT)
        browse_btn = ttk.Button(path_row, text="…", width=3,
                                command=lambda: path_v.set(
                                    filedialog.askdirectory(title="Seleccionar nueva carpeta") or path_v.get()
                                ))
        browse_btn.pack(side=tk.LEFT, padx=(4, 0))

        tk.Label(f,
                 text="Escribe solo el nombre (ej: Documentos) o una ruta completa (ej: D:\\Docs\\Nuevo)",
                 bg="white", fg="#888", font=(_FONT, 8)).grid(
            row=7, column=1, columnspan=2, sticky="w", padx=(10, 0), pady=(2, 10))

        def update_path_state():
            st = "normal" if change_path_v.get() else "disabled"
            path_entry.config(state=st)
            browse_btn.config(state=st)

        _CheckButton(f, text="Cambiar ruta / nombre:", variable=change_path_v,
                     command=update_path_state).grid(row=6, column=0, sticky="w", pady=(10, 0))

        ttk.Separator(f, orient="horizontal").grid(
            row=8, column=0, columnspan=3, sticky="ew", pady=(8, 8))

        dry_v = tk.BooleanVar(value=self.s["dry_run"])
        _CheckButton(f,
                     text="Dry run — simular sin ejecutar nada (recomendado para la primera prueba)",
                     variable=dry_v).grid(row=10, column=0, columnspan=3, sticky="w", pady=(6, 0))

        rename_id_v = tk.BooleanVar(value=self.s["rename_id"])
        _CheckButton(f,
                     text="Renombrar ID de carpeta",
                     variable=rename_id_v).grid(row=11, column=0, columnspan=3, sticky="w", pady=(6, 0))

        # New ID field — only shown when rename_id is checked
        new_id_v = tk.StringVar(value=self.s.get("new_folder_id") or folder.label or "")
        rename_id_frame = tk.Frame(f, bg="white")
        rename_id_frame.grid(row=12, column=0, columnspan=3, sticky="w", padx=(20, 0), pady=(2, 0))
        tk.Label(rename_id_frame, text="Nuevo ID:", bg="white", font=(_FONT, 8)).pack(side=tk.LEFT)
        new_id_entry = ttk.Entry(rename_id_frame, textvariable=new_id_v, width=28)
        new_id_entry.pack(side=tk.LEFT, padx=(6, 0))
        tk.Label(rename_id_frame,
                 text=f"  (actual: «{folder.id}»)",
                 bg="white", fg="#888", font=(_FONT, 8)).pack(side=tk.LEFT)
        rename_id_warn = tk.Label(rename_id_frame,
                 text="  ⚠ todos los dispositivos deberán aceptar la nueva carpeta",
                 bg="white", fg="#C66000", font=(_FONT, 8))
        rename_id_warn.pack(side=tk.LEFT)

        def update_rename_id_ui(*_):
            if rename_id_v.get():
                rename_id_frame.grid()
            else:
                rename_id_frame.grid_remove()
        rename_id_v.trace_add("write", update_rename_id_ui)

        update_rename_id_ui()   # set initial visibility
        _update_label_state()   # label entry starts disabled (toggle off by default)
        update_path_state()     # path entry starts enabled (toggle on by default)

        # These choices apply to ALL devices. Per-device tweaks (distinct path/role/access
        # for one machine) live in the next window (Topología → editar dispositivo).
        tk.Label(f, text="💡 Esto se aplica a todos los dispositivos. Para una ruta/rol/acceso "
                         "distinto por equipo, edítalo en la siguiente ventana (Topología).",
                 bg="white", fg="#1565C0", font=(_FONT, 8), wraplength=560, justify="left").grid(
            row=13, column=0, columnspan=3, sticky="w", pady=(12, 0))

        # The path mirrors the label as you type — but only until you edit the path
        # yourself; after that, label and path can differ. `_last_autoset` records our
        # own writes so we can tell an auto-mirrored value from a user-typed one.
        # (Skipped entirely while "solo cambiar label" is active — path is unused then.)
        _last_autoset = [path_v.get()]

        def on_label_change(*_):
            if not change_path_v.get():
                return
            if path_v.get() == _last_autoset[0]:   # path not manually edited → keep mirroring
                new = label_v.get()
                path_v.set(new)
                _last_autoset[0] = new
        label_v.trace_add("write", on_label_change)

        # The new-ID field mirrors the label the same way the path does: it tracks the
        # label until the user edits the ID by hand, after which they're independent.
        _last_id_autoset = [new_id_v.get()]

        def on_label_change_id(*_):
            if not rename_id_v.get():
                return
            if new_id_v.get() == _last_id_autoset[0]:  # ID not hand-edited → keep mirroring
                new = label_v.get()
                new_id_v.set(new)
                _last_id_autoset[0] = new
        label_v.trace_add("write", on_label_change_id)

        f.columnconfigure(1, weight=1)

        def do_next():
            # If "Cambiar label" is off, keep the current label (a no-op PUT) so only the
            # path and/or ID change — lets the user do "solo ruta" / "solo ID".
            if not change_label_v.get():
                lbl = folder.label or folder.id
            else:
                lbl = label_v.get().strip()
            path_in = path_v.get().strip()
            skip_path = not change_path_v.get()
            invalid_chars = set('/\\:*?"<>|')
            # No change selected is allowed: you can go to Topología just to manage the
            # cluster (add/unshare/unlink devices, edit links) without renaming anything.
            if change_label_v.get() and not lbl:
                messagebox.showerror("Error", "El label no puede estar vacío.")
                return
            if change_label_v.get() and any(c in invalid_chars for c in lbl):
                messagebox.showerror("Error", _T("El label contiene caracteres no válidos: {}").format(repr(lbl)))
                return
            if not skip_path:
                if not path_in:
                    messagebox.showerror("Error",
                                         "Introduce el nuevo nombre o ruta, "
                                         "o desmarca 'Cambiar ruta / nombre'.")
                    return
                if not is_absolute_path(path_in) and any(c in set(':*?"<>|') for c in path_in):
                    messagebox.showerror("Error", _T("El nombre contiene caracteres no válidos: {}").format(repr(path_in)))
                    return
            new_fid = new_id_v.get().strip()
            if rename_id_v.get():
                if not new_fid:
                    messagebox.showerror("Error", "El nuevo ID no puede estar vacío.")
                    return
                if new_fid == folder.id:
                    messagebox.showerror("Error", "El nuevo ID es igual al actual.")
                    return
            # Save the rename choices and advance to the Topology page; the change
            # preview modal now fires from there (after topology edits).
            self.s.update({
                "new_label": lbl,
                "new_path_input": path_in,
                "skip_path": skip_path,
                "dry_run": dry_v.get(),
                "rename_id": rename_id_v.get(),
                "new_folder_id": new_fid if rename_id_v.get() else "",
            })
            self._show(4)

        self._next_handlers[3] = do_next

    def _open_change_preview(self):
        """Sentinel before the preview (the user asked for it): if a reachable device we
        edited changed its folder config since we read it, warn so the user can keep their
        edits (applied non-destructively on top) or go back to review. Then open the
        actual preview."""
        topo = self.s.get("topology")
        orig = self.s.get("topology_orig")
        if not (topo and orig and _topology_delta(orig, topo).get("any")):
            self._build_change_preview()
            return
        from ..renamer import compute_topology_diff
        diff = compute_topology_diff(orig, topo, locked=self.s.get("topology_locked"))
        changed = set(diff["role_changed"])
        for e in (diff["links_added"] | diff["links_removed"]):
            changed |= set(e)
        folder_id = self.s["folder"].id
        with self._devices_lock:
            targets = [d for d in self.s.get("devices", [])
                       if not d.is_local and d.device_id in changed
                       and _device_kind(d) == "ok" and d.api_reachable and d.api_url]
        if not targets:
            self._build_change_preview()
            return
        self._status("Comprobando la configuración actual de los equipos…", "#555")
        _my_gen = self._show_gen   # bind now; ui() must not open the preview on a page we left

        def work():
            diverged = []
            for d in targets:
                try:
                    f = SyncthingClient(d.api_url, d.api_key or "", verify_ssl=False).get_folder(folder_id)
                    cur_role = f.raw.get("type") if f else None
                except Exception:
                    cur_role = None
                exp = (orig["nodes"].get(d.device_id) or {}).get("role")
                if cur_role and exp and cur_role != exp:
                    diverged.append(d.name)

            def ui():
                if self._show_gen != _my_gen:
                    return   # user navigated away during the per-device probe; don't pop the modal
                self._status("", "#555")
                if diverged:
                    names = ", ".join(f"«{n}»" for n in diverged)
                    keep = messagebox.askyesno(
                        "La configuración del equipo cambió",
                        _T('{} cambió su configuración de la carpeta desde que la editaste.\n\nSi continúas, TUS cambios se aplicarán ENCIMA de la suya (fusionados, sin borrar lo que no tocaste).\n\n• Sí = continuar y conservar tus cambios.\n• No = volver para revisarlo (puedes redescubrir para cargar su configuración actual).').format(names),
                        parent=self)
                    if not keep:
                        return  # back to topology page (user reviews / redescubre)
                self._build_change_preview()
            self._post(ui)
        threading.Thread(target=work, daemon=True).start()

    def _build_change_preview(self):
        """Confirmation modal: show exactly what will change (rename + topology),
        per device, before executing. Reads all choices from self.s. Fires from the
        Topology page's Next button; on confirm advances to the Execute page."""
        folder: FolderConfig = self.s["folder"]
        lbl       = self.s["new_label"]
        path_in   = self.s["new_path_input"]
        skip_path = self.s["skip_path"]
        dry_run   = self.s["dry_run"]
        do_rename_id = self.s["rename_id"]
        new_fid   = self.s.get("new_folder_id", "")
        topo_delta = _topology_delta(self.s.get("topology_orig"), self.s.get("topology"),
                                     self.s.get("topology_locked"))
        if True:
            from ..renamer import _resolve_new_path
            with self._devices_lock:
                devs = list(self.s.get("devices", []))
            _topo = self.s.get("topology")
            _new_ids = {nid for nid, n in _topo["nodes"].items()
                        if n.get("is_new")} if _topo else set()
            # New topology devices have no folder to rename → not rename targets here.
            actionable = [d for d in devs if _device_kind(d) == "ok" and d.device_id not in _new_ids]
            agent_devs = self.s.get("agent_devices", [])

            dlg = tk.Toplevel(self)
            dlg.title("Vista previa de cambios")
            dlg.configure(bg="white")
            dlg.resizable(True, True)
            dlg.grab_set()
            self._center_dialog(dlg)
            if _IS_WIN:
                dlg.geometry(f"{min(640, self._win_w - 30)}x{min(540, self._win_h - 30)}")

            tk.Label(dlg, text="Vista previa de cambios" + ("  —  DRY RUN" if dry_run else ""),
                     bg="white", font=(_FONT, 10, "bold")).pack(anchor="w", padx=14, pady=(12, 4))

            _label_changed = bool(lbl and lbl != (folder.label or folder.id))
            _no_rename = (not _label_changed) and skip_path and not do_rename_id
            if _no_rename:
                head = ["Sin cambios de rename — solo gestión de topología."]
            else:
                head = [_T('Carpeta (label):   «{}»   →   «{}»').format(folder.label or folder.id, lbl)
                        if _label_changed else
                        _T('Carpeta (label):   «{}»   (sin cambios)').format(folder.label or folder.id)]
                if not skip_path:
                    head.append(_T('Ruta / nombre:     {}').format(path_in))
                else:
                    head.append("Ruta:              (sin cambios)")
                if do_rename_id:
                    head.append(_T('ID de carpeta:     «{}»   →   «{}»').format(folder.id, new_fid))
            tk.Label(dlg, text="\n".join(head), bg="white", font=(_FONT, 9),
                     justify="left").pack(anchor="w", padx=14)

            if do_rename_id and not dry_run:
                tk.Label(dlg,
                         text="⚠ Renombrar ID crea la carpeta nueva y borra la antigua en cada dispositivo "
                              "accesible; el resto necesita el agente o la exploración pasiva.",
                         bg="white", fg="#C66000", font=(_FONT, 8), wraplength=600,
                         justify="left").pack(anchor="w", padx=14, pady=(4, 0))

            ttk.Separator(dlg, orient="horizontal").pack(fill=tk.X, padx=14, pady=8)

            body = scrolledtext.ScrolledText(dlg, height=12, font=(_MONO, 9), wrap=tk.WORD,
                                             relief=tk.FLAT, bg="#F7F7F7")
            body.pack(fill=tk.BOTH, expand=True, padx=14)

            def w(line=""):
                body.insert(tk.END, line + "\n")

            _povr = self.s.get("path_overrides", {}) or {}
            if _no_rename:
                # No label/path/ID change was selected, so these reachable devices get NO
                # rename applied — only the topology changes below. Listing them as
                # "(solo label)" wrongly implied a name edit; state plainly that nothing
                # is renamed (the count refers to existing reachable devices; new topology
                # devices are handled in the "Cambios de topología" section).
                if actionable:
                    if topo_delta and topo_delta.get("any"):
                        w(_T('No se renombra nada en {} dispositivo(s) accesible(s) — solo se aplican los cambios de topología de abajo.').format(len(actionable)))
                    else:
                        w(_T('No se renombra nada en {} dispositivo(s) accesible(s), y no hay cambios de topología: no hay nada que aplicar.').format(len(actionable)))
            else:
                w(_T('Se aplicará a {} dispositivo(s) accesible(s):').format(len(actionable)))
                for d in actionable:
                    _din = _povr.get(d.device_id) or path_in   # per-device override (B4)
                    _tag = _T("  (ruta propia)") if d.device_id in _povr else ""
                    _what = _T("label + ruta") if not skip_path else _T("solo label")
                    if skip_path:
                        w(f"  • {d.name}: ({_what})")
                    elif not d.folder_path:
                        w(_T('  • {}: (ruta autodetectada al ejecutar){}').format(d.name, _tag))
                    else:
                        try:
                            newp = _resolve_new_path(d.folder_path, _din)
                        except Exception:
                            newp = _din
                        # Single line "old → new"; the ScrolledText (wrap=WORD) only wraps
                        # to extra lines when it doesn't fit the available width.
                        w(f"  • {d.name}:  {d.folder_path}  →  {newp}{_tag}")
            # Devices configured AT RECONNECT, split by their REAL method so the info is
            # coherent (passive and agent are independent choices; a device can have both).
            # (#89 — before, agent+passive were lumped and a passive device also showed up
            # under the topology "no accesibles" warning below, contradicting this list.)
            by_id       = {d.device_id: d for d in devs}
            actionable_ids = {d.device_id for d in actionable}
            # A device that's REACHABLE now is configured directly — it must NOT be listed as
            # "al reconectar (pasiva/agente)" just because it once lacked credentials. Passive
            # and agent only cover devices we can't reach right now. NOTE: we subtract every
            # reachable device (not just `actionable`), because a freshly-added topology device
            # (is_new) is excluded from `actionable` yet, once probed OK, is configured directly
            # too — so it must not fall back into the passive list (the "sigue saliendo pasiva"
            # bug after configuring a new device in Topología).
            reachable_now_ids = {d.device_id for d in devs if _device_kind(d) == "ok"}
            passive_ids = set(self.s.get("passive_devices", set())) - reachable_now_ids
            agent_ids   = {d.device_id for d in agent_devs} - reachable_now_ids
            managed_ids = (agent_ids | passive_ids)
            _nm = lambda i: (by_id[i].name if by_id.get(i) else i[:7])
            if managed_ids:
                w()
                w(_T('Al reconectar — {} dispositivo(s):').format(len(managed_ids)))
                for i in sorted(passive_ids - agent_ids, key=_nm):
                    w(_T('  🔎 exploración pasiva:  {}').format(_nm(i)))
                for i in sorted(agent_ids - passive_ids, key=_nm):
                    w(_T('  🧩 agente (ejecútalo en el equipo):  {}').format(_nm(i)))
                for i in sorted(agent_ids & passive_ids, key=_nm):
                    w(_T("  🔎+🧩 pasiva + agente:  {}  (lo que ocurra primero)").format(_nm(i)))
            # Folder members we can neither reach now nor have a method for → manual accept.
            unmanaged = sorted(
                (d.name for d in devs
                 if not d.is_local and d.device_id not in actionable_ids
                 and d.device_id not in managed_ids
                 and d.device_id not in _new_ids),
            )
            if unmanaged:
                w()
                w(_T('⚠ Sin gestionar ({}) — ni pasiva ni agente; habría que aceptarlos a mano:').format(len(unmanaged)))
                for nm in unmanaged:
                    w(f"  • {nm}")

            # ── Topology changes (if any) ──
            if topo_delta and topo_delta.get("any"):
                w()
                w(_T("Cambios de topología:"))
                _cur_edges = (self.s.get("topology") or {}).get("edges", set())
                for nd in topo_delta["new_devices"]:
                    w(_T('  + nuevo dispositivo «{}»  (ruta: {})').format(nd['label'], nd.get('path') or '~/'+nd['label']))
                    if not any(nd.get("id") in e for e in _cur_edges):
                        # A new device with no links: the folder IS created on it and loaded into
                        # Syncthing, but with no peers it stays ORPHANED (syncs with nobody) until
                        # you connect it. State that plainly so it's an informed choice.
                        w(_T('     ⚠ «{}» sin enlaces: se le creará la carpeta (cargada en Syncthing), pero quedará HUÉRFANA —no se comparte— hasta que la enlaces en la Topología.').format(nd['label']))
                for a, b in topo_delta["links_added"]:
                    w(f"  + vincular  {a} ↔ {b}")
                for a, b in topo_delta["links_removed"]:
                    w(f"  − desvincular  {a} ↔ {b}")
                for lbl in topo_delta.get("unshared", []):
                    w(_T('  ✖ dejar de compartir en «{}» (se queda sin enlaces)').format(lbl))
                for name, old_role, new_role in topo_delta["roles_changed"]:
                    w(_T('  ~ rol de {}:  {} → {}').format(name, _T(_ROLE_LABELS.get(old_role, old_role)), _T(_ROLE_LABELS.get(new_role, new_role))))

                # Asymmetry warning: a role/link change only takes effect on a device if
                # we can reach it now, or it's covered by an agent / passive exploration.
                # Flag changes touching devices that are none of those — until applied on
                # BOTH ends the topology stays lopsided (e.g. both 'sendonly' → no sync).
                orig_t = self.s.get("topology_orig") or {"nodes": {}, "edges": set()}
                kind_by_id = {d.device_id: _device_kind(d) for d in devs}
                changed_ids = set()
                for nid, n in _topo["nodes"].items():
                    on = orig_t["nodes"].get(nid)
                    if on and on.get("role") != n.get("role"):
                        changed_ids.add(nid)
                for e in (_topo["edges"] ^ orig_t["edges"]):
                    changed_ids |= set(e)
                # Only TRULY unmanaged devices are a risk: not reachable now, AND not covered
                # by an agent NOR passive exploration (those WILL be configured on reconnect,
                # so they must not be flagged here — that was the contradiction in #89).
                risky = sorted({
                    (_topo["nodes"].get(nid) or {}).get("label", nid[:7])
                    for nid in changed_ids
                    if not (_topo["nodes"].get(nid) or {}).get("is_new")
                    and not (_topo["nodes"].get(nid) or {}).get("is_local")
                    and kind_by_id.get(nid) != "ok"
                    and nid not in agent_ids and nid not in passive_ids
                })
                if risky:
                    w()
                    w(_T("⚠ No accesibles ahora y sin gestionar: ") + ", ".join(risky))
                    w(_T("  Sus cambios de rol/enlace no se aplicarán hasta aceptarlos a mano;"))
                    w(_T("  hasta entonces la topología puede quedar asimétrica."))
            body.config(state="disabled")

            # ── Pre-flight: validate before touching anything (runs in background) ──
            pf_frame = tk.Frame(dlg, bg="white")
            pf_frame.pack(fill=tk.X, padx=14, pady=(8, 0))
            pf_lbl = tk.Label(pf_frame, text="Comprobando (pre-vuelo)…", bg="white", fg="#555",
                              font=(_FONT, 9), justify="left", wraplength=600, anchor="w")
            pf_lbl.pack(fill=tk.X, anchor="w")
            override_var = tk.BooleanVar(value=False)

            btnf = tk.Frame(dlg, bg="white")
            btnf.pack(side=tk.BOTTOM, fill=tk.X, padx=14, pady=10)

            def _go():
                self.s.update({
                    "new_label": lbl,
                    "new_path_input": path_in,
                    "skip_path": skip_path,
                    "dry_run": dry_run,
                    "rename_id": do_rename_id,
                    "new_folder_id": new_fid if do_rename_id else "",
                })
                dlg.destroy()
                self._show(5)

            exec_btn = ttk.Button(btnf, text=("Simular →" if dry_run else "Ejecutar →"), command=_go)
            exec_btn.pack(side=tk.RIGHT)
            ttk.Button(btnf, text="Cancelar", command=dlg.destroy).pack(side=tk.RIGHT, padx=(0, 6))

            _pf = {"errors": False, "done": False}

            def _sync_exec_btn(*_):
                # Disabled until pre-flight finishes; blocked on errors unless overridden
                # (dry-run never blocks — it changes nothing).
                if not _pf["done"]:
                    exec_btn.config(state="disabled")
                elif _pf["errors"] and not dry_run and not override_var.get():
                    exec_btn.config(state="disabled")
                else:
                    exec_btn.config(state="normal")

            override_chk = tk.Checkbutton(
                pf_frame, text="Ejecutar de todas formas (ignorar errores del pre-vuelo)",
                variable=override_var, bg="white", font=(_FONT, 8), command=_sync_exec_btn)
            exec_btn.config(state="disabled")

            def _run_preflight():
                from ..renamer import preflight_check
                err = None
                issues = []
                try:
                    issues = preflight_check(actionable, folder.id, path_in, skip_path,
                                             new_fid if do_rename_id else "")
                except Exception as e:
                    err = str(e)

                def _apply():
                    if not dlg.winfo_exists():
                        return
                    errors = [i for i in issues if i.level == "error"]
                    warns  = [i for i in issues if i.level == "warning"]
                    _pf["errors"] = bool(errors)
                    _pf["done"] = True
                    lines = []
                    if not errors and not warns and not err:
                        lines.append("✓ Pre-vuelo OK — sin problemas detectados")
                    for i in errors:
                        lines.append(f"✗ {i.device_name}: {i.message}")
                    for i in warns:
                        lines.append(f"⚠ {i.device_name}: {i.message}")
                    if err:
                        lines.append(_T('⚠ No se pudo completar el pre-vuelo: {}').format(err))
                    color = "#C62828" if errors else ("#C66000" if (warns or err) else "#2E7D32")
                    pf_lbl.config(text="\n".join(lines), fg=color)
                    if errors and not dry_run:
                        override_chk.pack(anchor="w", pady=(4, 0))
                    _sync_exec_btn()
                self._post(_apply)

            threading.Thread(target=_run_preflight, daemon=True).start()
