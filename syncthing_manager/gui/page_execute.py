from __future__ import annotations
from .common import *  # noqa: F401,F403


class ExecutePageMixin:
    def _purge_reverted_new_nodes(self, folder_id, node_ids, keep_devices: bool = False) -> None:
        """Drop nodes from ALL of the GUI's state: the live topology graph, the persisted
        per-folder snapshot, plus `topology_removed` so neither the reconcile pass nor the
        snapshot overlay resurrects them (in-session or on a later run). Must run on the Tk
        main thread (mutates self.s graph).

        Default (`keep_devices=False`) ALSO drops them from `self.s["devices"]` — for
        user-added (is_new) nodes reverted by an undo, which were never really wanted. Pass
        `keep_devices=True` for an UNSHARED EXISTING device: it stays a real, credentialed
        device (it may share OTHER folders), so it must NOT vanish from the folder-agnostic
        devices list — only from THIS folder's topology."""
        node_ids = {n for n in node_ids if n}
        if not node_ids:
            return
        self.s.setdefault("topology_removed", set()).update(node_ids)
        if not keep_devices:
            with self._devices_lock:
                self.s["devices"] = [d for d in self.s.get("devices", [])
                                     if d.device_id not in node_ids]
        _t = self.s.get("topology")
        if _t:
            # Copy-and-swap (atomic) so a concurrent reader never sees a half-mutated graph.
            _t2 = _copy_topology(_t)
            for _nid in node_ids:
                _t2["nodes"].pop(_nid, None)
                _t2["edges"] = {e for e in _t2.get("edges", set()) if _nid not in e}
                _t2["edge_dir"] = {e: v for e, v in _t2.get("edge_dir", {}).items()
                                   if _nid not in e}
            self.s["topology"] = _t2
        try:
            _snap = appconfig.load_topology_snapshot(folder_id)
            _snap = _topology_from_json(_snap) if _snap else None
            if _snap:
                for _nid in node_ids:
                    _snap["nodes"].pop(_nid, None)
                    _snap["edges"] = {e for e in _snap.get("edges", set()) if _nid not in e}
                    _snap["edge_dir"] = {e: v for e, v in _snap.get("edge_dir", {}).items()
                                         if _nid not in e}
                appconfig.save_topology_snapshot(folder_id, _topology_to_json(_snap))
        except Exception:
            pass

    def _exec_abandon_guard(self) -> bool:
        """Consulted (via App._leave_execute_ok) before leaving Execute — Back, Cerrar, or
        closing the app. Warns ONLY about devices relying on PASSIVE exploration (offline with
        credentials, configured on reconnect) that haven't been configured yet: the passive
        sweep only runs while you're on this page, so leaving silently loses them. Devices on
        the AGENT route (no credentials) are NOT counted — they always need their agent
        regardless of leaving (the agent panel already says so), so leaving doesn't lose them.
        On 'leave' it reverts the edits that landed NOWHERE and marks the rest as unconfirmed.
        Returns False ONLY when the user chooses to STAY."""
        orig, cur = self.s.get("topology_orig"), self.s.get("topology")
        if not orig or not cur:
            return True
        from ..renamer import compute_topology_diff
        diff = compute_topology_diff(orig, cur, locked=self.s.get("topology_locked"))
        if not diff.get("any"):
            return True
        targets = set(diff.get("role_changed", {}))
        for e in (diff.get("links_added", set()) | diff.get("links_removed", set())):
            targets |= set(e)
        # Only PASSIVE-route targets count: passive_devices = offline-with-creds queued for the
        # in-session sweep (configured ones are removed from it). Agent-only devices aren't here.
        # Also exclude any device ALREADY covered by a generated agent (per-device, not a global
        # flag — generating a one-OS agent must not suppress the warning for passive devices on
        # OTHER machines that the agent doesn't include).
        passive_ids = set(self.s.get("passive_devices", set()))
        agent_ids = set(self.s.get("_exec_agent_generated_ids", set()))
        pending = {nid for nid in targets if nid in passive_ids and nid not in agent_ids}
        if not pending:
            return True
        msg = _T('Hay {} dispositivo(s) que se configurarían por EXPLORACIÓN PASIVA al '
                 'reconectar, pero la pasiva solo sigue mientras estás en esta ventana. Si sales '
                 'ahora sin generar un agente, esos cambios NO se aplicarán en ellos: se '
                 'revertirá lo que no cuajó en ningún sitio y se marcarán como «sin confirmar» en '
                 'la topología.\n\n(Los dispositivos que van por agente no se ven afectados: se '
                 'configuran cuando ejecutes su agente.)\n\n¿Salir de todas formas?'
                 ).format(len(pending))
        if not messagebox.askyesno("Exploración pasiva sin terminar", msg, parent=self):
            return False   # stay
        self._exec_abandon_cleanup(diff, pending)
        return True

    def _exec_abandon_cleanup(self, diff: dict, pending: set) -> None:
        """Leave-with-pending cleanup. KEEPS edges a reachable end really applied
        (accessible↔offline prevails); drops only ADDED edges whose BOTH ends are pending
        offline (applied nowhere); marks pending nodes 'unconfirmed' (persisted). Touches only
        the GUI graph + snapshot — never reverts Syncthing config on the reachable side."""
        cur, orig = self.s.get("topology"), self.s.get("topology_orig")
        if not cur:
            return
        pending = set(pending)
        nowhere = {e for e in diff.get("links_added", set()) if e <= pending}  # applied nowhere

        def _strip(g):
            if not g:
                return
            g["edges"] = {e for e in g.get("edges", set()) if e not in nowhere}
            g["edge_dir"] = {e: v for e, v in g.get("edge_dir", {}).items() if e not in nowhere}
        _strip(cur)
        _strip(orig)
        for nid in pending:
            if nid in cur.get("nodes", {}):
                cur["nodes"][nid]["unconfirmed"] = True
        folder = self.s.get("folder")
        if folder:
            try:
                snap = appconfig.load_topology_snapshot(folder.id)
                snap = _topology_from_json(snap) if snap else None
                if snap:
                    snap["edges"] = {e for e in snap.get("edges", set()) if e not in nowhere}
                    snap["edge_dir"] = {e: v for e, v in snap.get("edge_dir", {}).items()
                                        if e not in nowhere}
                    for nid in pending:
                        if nid in snap.get("nodes", {}):
                            snap["nodes"][nid]["unconfirmed"] = True
                    appconfig.save_topology_snapshot(folder.id, _topology_to_json(snap))
            except Exception:
                pass

    def _page_execute(self, f: tk.Frame):
        dry = self.s["dry_run"]
        self.s["_exec_agent_generated_ids"] = set()   # device ids covered by a generated agent
        exec_gen = self._show_gen  # lets the passive poller detect a stale page
        # Shared control between the forward passive loop, the undo/revert loop and
        # the passive-status window:
        #   reverting   — once the user undoes, the forward loop stops re-applying
        #                 changes so the revert loop can put them back.
        #   configured  — device_ids the forward loop has already handled (for status).
        #   wake        — set() to make the passive sweep run immediately (force discover).
        passive_ctrl = {"reverting": False, "configured": set(), "wake": threading.Event(),
                        # Guards the "configured" set: the forward passive thread .add()s to it
                        # while the undo worker copies it — protect both so the copy can't race the
                        # add (defensive under the GIL; required under a free-threaded build).
                        "lock": threading.Lock()}
        title = "Dry Run — simulando cambios (nada se modificará)" if dry else "Ejecutando rename"
        title_lbl = tk.Label(f, text=title, bg="white", font=(_FONT, 11, "bold"))
        title_lbl.pack(anchor="w")
        ttk.Separator(f, orient="horizontal").pack(fill=tk.X, pady=(6, 8))

        progress = ttk.Progressbar(f, mode="indeterminate")
        progress.pack(fill=tk.X, pady=(0, 8))
        progress.start(12)

        log = scrolledtext.ScrolledText(
            f, height=14, font=(_MONO, 9),
            bg="#1E1E1E", fg="#D4D4D4",
            state="disabled", wrap=tk.WORD,
            relief=tk.FLAT,
        )
        log.pack(fill=tk.BOTH, expand=True)
        log.tag_config("ok",   foreground="#4EC9B0")
        log.tag_config("err",  foreground="#F48771")
        log.tag_config("warn", foreground="#DCDCAA")
        log.tag_config("dim",  foreground="#666")
        log.tag_config("info", foreground="#9CDCFE")

        self._btn_next.config(state="disabled", text="Ejecutando…")
        self._btn_back.config(state="disabled")

        def log_line(msg: str, tag: str = ""):
            def ui():
                log.config(state="normal")
                log.insert(tk.END, msg + "\n", tag)
                log.see(tk.END)
                log.config(state="disabled")
            self._post(ui)

        def run():
            try:
                with self._devices_lock:
                    devices = list(self.s["devices"])
                folder     = self.s["folder"]
                new_label  = self.s["new_label"]
                path_input = self.s["new_path_input"]
                skip_path  = self.s["skip_path"]
                dry_run    = self.s["dry_run"]
                rename_id     = self.s.get("rename_id", False)
                new_folder_id = self.s.get("new_folder_id", "").strip()
                _old_dir_name = Path(folder.path.rstrip("/\\")).name if folder.path else ""
                id_results: list = []

                if dry_run:
                    log_line(_T("[ DRY RUN — no se realizará ningún cambio real ]"), "warn")
                if rename_id and new_folder_id:
                    log_line(_T('Renombrar ID de carpeta: «{}» → «{}»').format(folder.id, new_folder_id), "info")
                log_line(_T('Carpeta: {}  →  {}').format(folder.label or folder.id, new_label), "info")
                if not skip_path:
                    log_line(_T('Ruta/nombre nuevo: {}').format(path_input), "info")
                log_line("", "dim")

                # B9: credentials entered in the topology editor RESET a device's
                # reachability (to force a re-verify), so if the user typed creds but didn't
                # press "Probar y conectar" the device would be wrongly treated as passive
                # here. Re-probe passive devices that HAVE credentials so they upgrade to
                # reachable and get configured directly (not just queued for reconnect).
                import dataclasses as _dc9
                _passive_ids = set(self.s.get("passive_devices", set()))
                _to_probe = [d for d in devices
                             if not d.is_local and d.device_id in _passive_ids
                             and _device_kind(d) != "ok"
                             and (d.ssh_user or d.ssh_key_path or d.ssh_password
                                  or (d.winrm_user and d.winrm_password)
                                  or (d.api_key and d.api_url))]
                if _to_probe and not dry_run:
                    log_line(_T('Verificando {} dispositivo(s) con credenciales…').format(len(_to_probe)), "dim")

                    def _probe_one(d):
                        try:
                            if (d.ssh_user or d.ssh_key_path or d.ssh_password
                                    or (d.winrm_user and d.winrm_password)):
                                nd = probe_device(
                                    device_id=d.device_id, name=d.name, ip=d.ip, folder_id=folder.id,
                                    override={"ssh_user": d.ssh_user, "ssh_key_path": d.ssh_key_path,
                                              "ssh_password": d.ssh_password, "ssh_port": d.ssh_port,
                                              "winrm_user": d.winrm_user, "winrm_password": d.winrm_password,
                                              "winrm_port": d.winrm_port})
                                nd = _dc9.replace(nd, api_key=nd.api_key or d.api_key,
                                                  api_url=nd.api_url or d.api_url,
                                                  folder_path=nd.folder_path or d.folder_path)
                            else:
                                nd = probe_device_manual(
                                    device_id=d.device_id, name=d.name, ip=d.ip, folder_id=folder.id,
                                    api_key=d.api_key, api_url=d.api_url, folder_path=d.folder_path or "")
                            return nd
                        except Exception:
                            return None

                    # Probe in parallel so several offline devices don't serialize their
                    # (~15 s) timeouts at the start of the run.
                    from concurrent.futures import ThreadPoolExecutor
                    with ThreadPoolExecutor(max_workers=4) as _ex:
                        for nd in _ex.map(_probe_one, _to_probe):
                            if nd is not None and _device_kind(nd) == "ok":
                                for i, x in enumerate(devices):
                                    if x.device_id == nd.device_id:
                                        devices[i] = nd
                                        break
                                with self._devices_lock:
                                    for i, x in enumerate(self.s["devices"]):
                                        if x.device_id == nd.device_id:
                                            self.s["devices"][i] = nd
                                            break
                                    # Now reachable → drop it from the passive/agent queues so it
                                    # isn't ALSO handled (or shown) as "al reconectar". UNDER the
                                    # same lock the passive loop uses, or an update is lost / a
                                    # set is mutated mid-iteration.
                                    self.s.get("passive_devices", set()).discard(nd.device_id)
                                    self.s["agent_devices"] = [a for a in self.s.get("agent_devices", [])
                                                               if a.device_id != nd.device_id]
                                log_line(_T('  ✓  {} accesible — se configurará directamente.').format(nd.name), "ok")

                reachable   = [d for d in devices if _device_kind(d) == "ok"]
                # New topology devices have no folder yet → exclude from the rename
                # (they get the folder created in the topology step); existing devices
                # are the rename targets.
                _topo0  = self.s.get("topology")
                _new_ids = {nid for nid, n in _topo0["nodes"].items()
                            if n.get("is_new")} if _topo0 else set()
                actionable  = [d for d in reachable if d.device_id not in _new_ids]
                agent_devs  = self.s.get("agent_devices", [])
                if agent_devs:
                    names = ", ".join(d.name for d in agent_devs)
                    log_line(_T('{} dispositivo(s) sin acceso → agente: {}').format(len(agent_devs), names), "warn")
                # Count only NON-local devices as "remoto(s)" — the local node is processed too
                # but it isn't remote (the old message counted it, e.g. "2 remotamente" when one
                # was this equipo). Count over the FOLDER'S topology nodes, not `actionable`:
                # `actionable` excludes is_new devices (they have no folder to rename yet), but a
                # new device IS configured this run in the topology step below — counting only
                # actionable showed "0 remoto(s)" for a brand-new folder whose remotes are all new.
                _topo_node_ids = set(_topo0["nodes"]) if _topo0 else set()
                _remote_reach = [d for d in reachable
                                 if not d.is_local and d.device_id in _topo_node_ids]
                _remote_n = len(_remote_reach)
                _local_in = any(d.is_local for d in actionable)
                log_line(_T('Procesando {} dispositivo(s) remoto(s){}…').format(
                    _remote_n, _T(' + este equipo') if _local_in else ""), "dim")

                results = rename_all_devices(
                    devices=actionable,
                    folder_id=folder.id,
                    new_label=new_label,
                    new_dir_name=(path_input if not skip_path
                                  else (Path(folder.path.rstrip("/\\")).name if folder.path else "")),
                    dry_run=dry_run,
                    skip_path_rename=skip_path,
                    path_overrides=self.s.get("path_overrides"),
                )

                # Refresh cached folder_path to the new location so a later undo
                # reverts the directory from where it ACTUALLY is now (the discovered
                # path is stale once the rename moved it).
                with self._devices_lock:
                    for r in results:
                        if r.success and r.new_path:
                            r.device.folder_path = r.new_path

                log_line("", "dim")
                for r in results:
                    steps = []
                    if r.paused:   steps.append(_T("pausado"))
                    if r.dir_renamed and not skip_path: steps.append(_T("disco OK"))
                    if r.config_updated: steps.append(_T("config OK"))
                    if r.resumed:  steps.append(_T("reanudado"))

                    if r.skipped_absent:
                        log_line(_T('  •  {} — aún sin la carpeta aquí; se creará al aplicar la topología').format(r.device.name), "dim")
                    elif r.success and not r.warning:
                        log_line(f"  ✓  {r.device.name} — {', '.join(steps)}", "ok")
                    elif r.success and r.warning:
                        log_line(_T('  ⚠  {} — {} (acción manual necesaria)').format(r.device.name, ', '.join(steps)), "warn")
                        for line in r.warning.splitlines():
                            log_line(f"       {line}", "warn")
                    elif r.left_paused:
                        log_line(_T("  ⚠  {} — SYNC PAUSADA: {}").format(r.device.name, r.error), "err")
                    else:
                        done = ", ".join(steps) if steps else _T("ningún paso")
                        log_line(_T('  ✗  {} — {} — Error: {}').format(r.device.name, done, r.error), "err")

                # ── Folder ID rename ─────────────────────────────────────────
                if rename_id and new_folder_id and new_folder_id != folder.id:
                    log_line("", "dim")
                    log_line(_T("── Renombrando ID: «{}» → «{}» ──").format(folder.id, new_folder_id), "warn")
                    from ..renamer import rename_folder_id
                    id_results[:] = rename_folder_id(
                        devices=actionable,
                        old_folder_id=folder.id,
                        new_folder_id=new_folder_id,
                        dry_run=dry_run,
                    )
                    for dev_name, ok, msg in id_results:
                        if ok:
                            log_line(f"  ✓  {dev_name} — ID actualizado", "ok")
                        else:
                            log_line(f"  ✗  {dev_name} — {msg}", "err")

                # ── Topology changes ─────────────────────────────────────────
                # Applied by editing each reachable device's config directly (both
                # endpoints), so no device has to "accept" anything in Syncthing.
                topo = self.s.get("topology")
                topo_delta = _topology_delta(self.s.get("topology_orig"), topo)
                if topo_delta.get("any"):
                    from ..renamer import apply_topology_on_device, compute_topology_diff
                    # Compute the SAFE diff: only what the user changed, never a full
                    # membership rewrite. Locked edges are skipped. Edited links to offline
                    # devices ARE included (reachable end now, offline end on reconnect).
                    topo_diff = compute_topology_diff(
                        self.s.get("topology_orig"), topo,
                        locked=self.s.get("topology_locked"))
                    # After an ID rename the reachable devices already hold the new id.
                    eff_fid = (new_folder_id if (rename_id and new_folder_id
                                                 and new_folder_id != folder.id) else folder.id)
                    log_line("", "dim")
                    log_line(_T("── Aplicando topología (solo cambios) ──"), "warn")
                    if topo_diff["skipped_locked"]:
                        log_line(_T('  🔒  {} enlace(s) bloqueado(s) — no se modifican.').format(len(topo_diff['skipped_locked'])), "dim")
                    configured_ids = set()
                    # Apply in parallel (independent per-device API calls) — much faster
                    # than sequential on larger fleets (Proposal 4). Only devices that are
                    # new here or have an edit of their own are touched.
                    from concurrent.futures import ThreadPoolExecutor

                    def _dev_changed(d):
                        n = topo["nodes"].get(d.device_id)
                        if not n:
                            return False
                        if n.get("is_new"):
                            return True
                        r, a, rm = (topo_diff["role_changed"].get(d.device_id),
                                    [e for e in topo_diff["links_added"] if d.device_id in e],
                                    [e for e in topo_diff["links_removed"] if d.device_id in e])
                        return bool(r is not None or a or rm)
                    targets = [d for d in reachable if _dev_changed(d)]
                    if targets:
                        with ThreadPoolExecutor(max_workers=4) as _ex:
                            trs = list(_ex.map(
                                lambda d: (d, apply_topology_on_device(
                                    d, eff_fid, topo, diff=topo_diff,
                                    folder_label=new_label, dry_run=dry_run)),
                                targets))
                        for d, tr in trs:
                            log_line(f"  {'✓' if tr.ok else '✗'}  {tr.device_name} — {tr.message}",
                                     "ok" if tr.ok else "err")
                            if tr.ok:
                                configured_ids.add(d.device_id)
                    # Topology nodes we couldn't reach this run (new devices added only by
                    # ID, or offline peers): their own config can't be edited without
                    # access — they'll be configured via passive/agent (no accept needed).
                    changed_ids = set(topo_diff["role_changed"])
                    for e in (topo_diff["links_added"] | topo_diff["links_removed"]):
                        changed_ids |= set(e)
                    pend_ids = [nid for nid, n in topo["nodes"].items()
                                if nid not in configured_ids and not n["is_local"]
                                and (n.get("is_new") or nid in changed_ids)]
                    if pend_ids and not dry_run:
                        # Only devices actually QUEUED (passive or agent) will ever get this
                        # change. A device the user left out of BOTH queues must NOT be promised
                        # "al reconectar" — its edit would silently never land. Warn separately.
                        _queued = set(self.s.get("passive_devices", set())) \
                            | {d.device_id for d in agent_devs}
                        _will = [i for i in pend_ids if i in _queued]
                        _wont = [i for i in pend_ids if i not in _queued]
                        if _will:
                            log_line(_T('  ⏳  {} dispositivo(s) sin configurar aún (offline/nuevos sin acceso): se editará su config al reconectar (pasiva) o con agente — sin aceptar nada.').format(len(_will)), "warn")
                        if _wont:
                            log_line(_T('  ⚠  {} dispositivo(s) con cambios pendientes NO están en cola (ni pasiva ni agente): su config NO se aplicará. Vuelve atrás y actívalos si los quieres configurar.').format(len(_wont)), "warn")
                    # An orphaned node (its last link was removed) is being UNSHARED. Forget the
                    # ones we ACTUALLY unshared this run (reachable → in configured_ids): drop
                    # them from the in-memory graph (topology_removed) AND prune the PERSISTED
                    # snapshot, or the build's _merge_remembered would re-add them as a ghost
                    # next session (it doesn't consult topology_removed). OFFLINE orphans are
                    # NOT forgotten here — they aren't unshared yet; they must stay in the graph
                    # + snapshot so the passive loop can finish unsharing them on reconnect (it
                    # skips nodes absent from the graph), and that loop purges them once done.
                    _orphaned_done = topo_diff.get("orphaned", set()) & configured_ids
                    if _orphaned_done and not dry_run:
                        self.s.setdefault("topology_removed", set()).update(_orphaned_done)
                        try:
                            _osnap = appconfig.load_topology_snapshot(folder.id)
                            _osnap = _topology_from_json(_osnap) if _osnap else None
                            if _osnap:
                                for _oid in _orphaned_done:
                                    _osnap["nodes"].pop(_oid, None)
                                    _osnap["edges"] = {e for e in _osnap.get("edges", set())
                                                       if _oid not in e}
                                    _osnap["edge_dir"] = {e: v for e, v in
                                                          _osnap.get("edge_dir", {}).items()
                                                          if _oid not in e}
                                appconfig.save_topology_snapshot(folder.id,
                                                                 _topology_to_json(_osnap))
                        except Exception:
                            pass
                    if _orphaned_done and not dry_run:
                        log_line(_T('  ✖  {} dispositivo(s) dejaron de compartir la carpeta (sin enlaces).').format(len(_orphaned_done)), "ok")
                    # Offline orphans aren't reachable now → tell the user clearly that the
                    # unshare is BEST-EFFORT: it completes when the device reconnects (passive)
                    # or when you run its agent (durable, even days later). Not yet done.
                    _orphaned_pending = topo_diff.get("orphaned", set()) - configured_ids
                    if _orphaned_pending and not dry_run:
                        log_line(_T('  ⏳  {} dispositivo(s) offline dejarán de compartir cuando vuelvan a estar accesibles (al reconectar, o ejecutando su agente).').format(len(_orphaned_pending)), "warn")

                # ── Advanced folder-config (#55): apply queued overrides to reachable
                # devices now; offline ones stay pending for passive/agent. ──
                fcfg_pending = dict(self.s.get("fcfg_pending", {}))
                if fcfg_pending:
                    from ..renamer import apply_folder_cfg_on_device
                    eff_fid2 = (new_folder_id if (rename_id and new_folder_id
                                                  and new_folder_id != folder.id) else folder.id)
                    log_line("", "dim")
                    log_line(_T("── Config avanzada de carpeta ──"), "warn")
                    by_id_fc = {d.device_id: d for d in reachable}
                    for did, ov in fcfg_pending.items():
                        d = by_id_fc.get(did)
                        if d and _device_kind(d) == "ok":
                            r = apply_folder_cfg_on_device(d, eff_fid2, ov, dry_run=dry_run)
                            log_line(f"  {'✓' if r.ok else '✗'}  {r.device_name} — {r.message}",
                                     "ok" if r.ok else "err")
                            if r.ok and not dry_run:
                                self.s.get("fcfg_pending", {}).pop(did, None)
                    _rem_fc = [x for x in fcfg_pending if x in self.s.get("fcfg_pending", {})]
                    if _rem_fc and not dry_run:
                        log_line(_T('  ⏳  {} con config de carpeta pendiente (offline): se aplicará al reconectar (pasiva) o con agente.').format(len(_rem_fc)), "warn")

                ok_n   = sum(1 for r in results if r.success)
                paused = [r.device.name for r in results if r.left_paused]
                paused_results = [r for r in results if r.left_paused]
                # Agent is reserved for devices that need it intrinsically: those with no way
                # to rename the directory remotely (r.warning — e.g. reachable by API but no
                # SSH/WinRM). A reachable device that simply FAILED/timed out is NOT pushed to
                # the agent — re-applying the rename is the same operation, so we queue it for
                # passive exploration (retry automatically when it's reachable again) and offer
                # a «Reintentar ahora» button. Same machine, two triggers (now / on reconnect).
                needs_agent = [r for r in results if r.warning]
                failed_now  = [r for r in results if not r.success and not r.left_paused]
                if not dry_run and failed_now:
                    _pq = self.s.setdefault("passive_devices", set())
                    for r in failed_now:
                        _pq.add(r.device.device_id)   # they were reachable → have access creds
                    log_line(_T('  ↺  {} fallido(s) → se reintentarán solos al reconectar (pasiva); «Reintentar ahora» para forzarlo.').format(len(failed_now)), "warn")

                # A real (non-dry) execute means the user CONFIGURED this folder → it's no longer
                # an "abandoned new folder", so cancel the orphan-cleanup prompt for it.
                if not dry_run:
                    self.s.pop("_pending_new_folder", None)
                # Snapshot for "undo" — meaningful for a real (non-dry) run that changed
                # something, OR for a brand-new folder (so its final "Deshacer" can offer to
                # delete the folder it just created, not only revert the topology).
                if not dry_run and (ok_n > 0 or self.s.get("folder_is_new")):
                    self.s["_undo"] = {
                        "folder_id":     folder.id,
                        "old_label":     folder.label or folder.id,
                        "old_dir_name":  _old_dir_name,
                        "skip_path":     skip_path,
                        "rename_id":     bool(rename_id and new_folder_id and new_folder_id != folder.id),
                        "new_folder_id": new_folder_id,
                        "is_new_folder": bool(self.s.get("folder_is_new")),
                    }

                def finish():
                    progress.stop()
                    progress.config(mode="determinate", value=100)
                    self._btn_next.config(state="normal",
                                          text="Cerrar" if not paused else "Cerrar ⚠")
                    # Re-enable Back so the user can fix a name and retry WITHOUT
                    # restarting/re-discovering (devices stay cached; folder_path is
                    # kept current per device, so a retry operates on the real state).
                    self._btn_back.config(state="normal")
                    if paused:
                        self._status(
                            _T('⚠  {} dispositivo(s) con sync PAUSADA — intervención manual necesaria').format(len(paused)),
                            "#C62828")
                    elif ok_n == len(results):
                        prefix = "[DRY RUN] " if dry_run else ""
                        self._status(_T('{}Completado: {}/{} dispositivos OK').format(prefix, ok_n, len(results)), "#2E7D32")
                    else:
                        self._status(_T('Completado con errores: {}/{} OK').format(ok_n, len(results)), "#C66000")

                    # Offer agent generation for pre-selected + failed devices
                    agent_devs = self.s.get("agent_devices", [])
                    if (needs_agent or agent_devs) and not dry_run:
                        _show_agent_panel(needs_agent, agent_devs)

                    # Conditional action buttons + passive exploration of offline devices
                    _show_final_actions(results, id_results, paused_results)
                    # Run finished → arm the leave-guard: if you now try to leave (Back/Cerrar/
                    # close) with offline devices still pending and no agent, it asks and reverts
                    # the nowhere-applied edits. Recomputes lazily, so passive progress counts.
                    self._exec_leave_guard = self._exec_abandon_guard

                self._post(finish)

            except Exception as e:
                import traceback
                err_detail = traceback.format_exc()
                err_msg = str(e)  # capture now: 'e' is deleted when the except block exits
                logger.error("Unexpected error in execute step: %s", err_detail)

                def finish_error():
                    progress.stop()
                    progress.config(mode="determinate", value=0)
                    self._btn_next.config(state="normal", text="Cerrar")
                    self._btn_back.config(state="normal")  # allow fixing & retry without restart
                    log_line("", "dim")
                    log_line(_T('  ✗  Error inesperado: {}').format(err_msg), "err")
                    log_line(f"     {err_detail}", "err")
                    self._status("Error inesperado — ver log", "#C62828")

                self._post(finish_error)

        def _show_agent_panel(
            results_needing_agent: list[RenameResult],
            pre_selected: list[DeviceInfo],
        ) -> None:
            """Show agent generation panel for devices that need local execution."""
            # Shrink the log's requested height so the panel + footer stay on-screen
            # in short windows (Windows 560px); it still expands on taller windows.
            log.configure(height=6)

            win_ok   = agent_template_available("windows")
            linux_ok = agent_template_available("linux")
            macos_ok = agent_template_available("macos")
            if not win_ok and not linux_ok and not macos_ok:
                log_line(_T(
                    "\nℹ  Para generar agentes: compila las plantillas con PyInstaller.\n"
                    "   python -m PyInstaller build/agent_windows.spec\n"
                    "   python -m PyInstaller build/agent_linux.spec\n"
                    "   python -m PyInstaller build/agent_macos.spec"), "dim"
                )
                return

            folder_id    = self.s["folder"].id
            new_label    = self.s["new_label"]
            new_dir_name = self.s["new_path_input"] or self.s["new_label"]
            skip_path    = self.s["skip_path"]

            # Embed the topology graph + the SAFE diff (serialized) only when there are
            # actual edits, so the agent applies ONLY the user's changes on its machine
            # directly (no accept needed, no membership rewrite).
            from ..renamer import (serialize_topology as _ser_topo,
                                  serialize_topology_diff as _ser_diff,
                                  compute_topology_diff as _ctd2)
            _topo_for_agent = None
            _diff_for_agent = None
            if _topology_delta(self.s.get("topology_orig"), self.s.get("topology")).get("any"):
                _topo_for_agent = _ser_topo(self.s.get("topology"))
                _diff_for_agent = _ser_diff(_ctd2(
                    self.s.get("topology_orig"), self.s.get("topology"),
                    locked=self.s.get("topology_locked")))

            seen_ids: set[str] = set()
            entries: list[dict] = []

            def _add_entry(dev: DeviceInfo, api_url_fallback: str = "http://127.0.0.1:8384"):
                if dev.device_id in seen_ids:
                    return
                seen_ids.add(dev.device_id)
                entries.append({
                    "device_id":        dev.device_id,
                    "device_name":      dev.name,
                    "folder_id":        folder_id,
                    "new_label":        new_label,
                    # Per-device path override (B4) wins over the shared rename target.
                    "new_dir_name":     (self.s.get("path_overrides", {}).get(dev.device_id)
                                         or new_dir_name),
                    "old_path":         dev.folder_path or "",
                    "api_key":          dev.api_key or "",
                    "api_url":          dev.api_url or api_url_fallback,
                    # A per-device override forces a path change even under global skip.
                    "skip_path_rename": (skip_path and dev.device_id
                                         not in self.s.get("path_overrides", {})),
                    "dry_run":          False,
                    "os_type":          dev.os_type,
                    "os_detected":      dev.os_detected,
                    "arch":             dev.arch,
                    "arch_detected":    dev.arch_detected,
                    "rename_id":        self.s.get("rename_id", False),
                    "new_folder_id":    self.s.get("new_folder_id", ""),
                    "topology":         _topo_for_agent,
                    "topology_diff":    _diff_for_agent,
                    # Advanced folder-config overrides queued for this device (#55).
                    "fcfg":             self.s.get("fcfg_pending", {}).get(dev.device_id),
                    # Canonical device names to write into this machine's config (item 1).
                    "names":            self.s.get("names_canonical") or None,
                })

            for dev in pre_selected:
                _add_entry(dev)
            for r in results_needing_agent:
                if r.device.api_key:
                    _add_entry(r.device)

            if not entries:
                return

            # ── OS/arch assignment: DETECTED devices are locked (chip); the rest the user picks ──
            # No OS is preselected (the user must choose) and, for Linux/macOS without a detected
            # arch, picking the OS prompts for the architecture (per device) — see _device_pick.
            from ..generate import (available_linux_arches, available_macos_arches,
                                    normalize_arch, select_agent_builds)
            unknown = [e for e in entries if not e.get("os_detected")]
            os_vars: dict[str, tk.StringVar] = {e["device_id"]: tk.StringVar(value="")
                                                for e in unknown}
            # Per-device chosen arch (only for non-Windows devices whose arch wasn't detected).
            arch_chosen: dict[str, tk.StringVar] = {e["device_id"]: tk.StringVar(value="")
                                                    for e in entries}

            def _base_arch_for(target_os: str) -> str:
                # The base/default arch. macOS has no plain template, so the base must be an arch
                # actually embedded: prefer amd64 (Intel + Rosetta on Apple Silicon), else arm64 —
                # so an arm64-only macOS build doesn't force a non-existent amd64 base. Linux base
                # is the host arch (amd64 on a Windows host, where the plain template is amd64).
                if target_os == "macos":
                    macs = available_macos_arches()
                    return "amd64" if ("amd64" in macs or not macs) else "arm64"
                return "amd64" if _IS_WIN else normalize_arch()

            def _avail_arches_for(target_os: str) -> list:
                return (available_macos_arches() if target_os == "macos"
                        else available_linux_arches())

            def _arch_label_for(target_os: str, a):
                if target_os == "macos":
                    return _T("Apple Silicon (M1/M2/M3…)") if a == "arm64" else _T("Intel (x86-64)")
                return _T("ARM64 (Raspberry Pi y similares)") if a == "arm64" else _T("x86-64 (amd64)")

            def _eff_arch(e) -> str:
                # The device's effective arch: the detected one, else the popup choice (or "").
                if e.get("arch_detected") and e.get("arch"):
                    return normalize_arch(e["arch"])
                return arch_chosen[e["device_id"]].get()

            def _ask_arch(target_os: str, current: str = ""):
                """Modal per-device arch chooser. Returns the chosen arch, or None if cancelled.
                With a single buildable arch it returns it without prompting."""
                base = _base_arch_for(target_os)
                avail = set(_avail_arches_for(target_os))
                # Linux's base arch is always buildable via the plain template; macOS only via its
                # arch-suffixed templates — but never offer an EMPTY list (that would veto the OS
                # pick and leave the button dead), so fall back to the base arch.
                opts = sorted({base} | avail) if target_os == "linux" else (sorted(avail) or [base])
                if not opts:
                    return None
                if len(opts) == 1:
                    return opts[0]
                dlg = tk.Toplevel(self)
                dlg.title(_T("Arquitectura"))
                dlg.configure(bg="white")
                dlg.resizable(False, False)
                dlg.transient(self.winfo_toplevel())
                tk.Label(dlg, text=_T("Elige la arquitectura del dispositivo:"),
                         bg="white", font=(_FONT, 9)).pack(padx=18, pady=(14, 8), anchor="w")
                default = current or ("amd64" if target_os == "linux"
                                      else ("arm64" if "arm64" in opts else opts[0]))
                var = tk.StringVar(value=default if default in opts else opts[0])
                for a in opts:
                    ttk.Radiobutton(dlg, text=_arch_label_for(target_os, a), value=a,
                                    variable=var).pack(anchor="w", padx=26)
                sel = {"v": None}
                bf = tk.Frame(dlg, bg="white")
                bf.pack(pady=12)

                def _ok():
                    sel["v"] = var.get()
                    dlg.destroy()
                ttk.Button(bf, text=_T("Aceptar"), command=_ok).pack(side=tk.LEFT, padx=4)
                ttk.Button(bf, text=_T("Cancelar"), command=dlg.destroy).pack(side=tk.LEFT, padx=4)
                dlg.update_idletasks()
                try:
                    px, py = self.winfo_rootx(), self.winfo_rooty()
                    pw, ph = self.winfo_width(), self.winfo_height()
                    dlg.geometry(f"+{px + (pw - dlg.winfo_width()) // 2}"
                                 f"+{py + (ph - dlg.winfo_height()) // 2}")
                except Exception:
                    pass
                dlg.grab_set()
                self.wait_window(dlg)
                return sel["v"]

            def entries_for_os(target_os: str) -> list[dict]:
                result = []
                for e in entries:
                    if e.get("os_detected") and e["os_type"] == target_os:
                        result.append(e)
                    elif not e.get("os_detected") and os_vars[e["device_id"]].get() == target_os:
                        result.append(e)
                return result

            # Single pointer in the dark log (no duplicated device list — it's in the card)
            log_line(_T("\n→  Genera los agentes en el panel de abajo."), "warn")

            CARD = "#FFFDE7"  # softer yellow than #FFF9C4

            # ── Cross-platform OS segmented toggle (native radios look bad on Linux) ──
            def _os_toggle(parent, var, on_pick=None):
                frame = tk.Frame(parent, bg=CARD)
                btns: dict[str, tk.Button] = {}

                def refresh(*_):
                    for val, b in btns.items():
                        sel = var.get() == val
                        b.config(bg=BLUE if sel else "#E0E0E0",
                                 fg="white" if sel else "#333",
                                 relief="sunken" if sel else "raised")

                def pick(val):
                    # on_pick runs BEFORE the var changes and may VETO it (return False) — e.g.
                    # the arch popup was cancelled, so the OS must not get selected. It also runs
                    # the side effects (arch prompt / apply-to-all). update_counts fires via the
                    # os_vars/arch_chosen traces, so it isn't called here.
                    if on_pick is not None and not on_pick(val):
                        return
                    var.set(val)              # trace fires refresh + update_counts

                for val, txt in (("windows", "🪟 Windows"), ("linux", "🐧 Linux"), ("macos", "🍎 macOS")):
                    b = tk.Button(frame, text=txt, font=(_FONT, 9), bd=1,
                                  padx=10, pady=2, cursor="hand2",
                                  command=lambda v=val: pick(v))
                    b.pack(side=tk.LEFT, padx=(0, 4))
                    btns[val] = b
                var.trace_add("write", refresh)
                refresh()
                return frame

            win_btn = None
            linux_btn = None
            macos_btn = None

            def _device_pick(e):
                # Per-device OS button handler: when Linux/macOS is chosen for a device whose arch
                # ISN'T detected, prompt for the architecture (every click, so it's editable).
                # Cancelling the popup vetoes the OS selection. Windows needs no arch.
                did = e["device_id"]

                def handler(val):
                    if val in ("linux", "macos") and not (e.get("arch_detected") and e.get("arch")):
                        a = _ask_arch(val, arch_chosen[did].get())
                        if not a:
                            return False     # cancelled → don't select this OS
                        arch_chosen[did].set(a)
                    elif val == "windows":
                        arch_chosen[did].set("")
                    return True
                return handler

            def update_counts():
                # A button is enabled only when its template is embedded, it has at least one
                # device, AND (for Linux/macOS) every assigned device has an architecture loaded —
                # we never generate an OS with a device whose arch is still unspecified.
                for _btn, _ok, _os, _fmt in (
                        (win_btn, win_ok, "windows", "🪟 Generar Windows ({})"),
                        (linux_btn, linux_ok, "linux", "🐧 Generar Linux ({})"),
                        (macos_btn, macos_ok, "macos", "🍎 Generar macOS ({})")):
                    if _btn is None or not _ok:
                        continue
                    evs = entries_for_os(_os)
                    ready = bool(evs) and (_os == "windows" or all(_eff_arch(e) for e in evs))
                    _btn.config(text=_T(_fmt).format(len(evs)),
                                state="normal" if ready else "disabled")

            # Re-evaluate the generate buttons whenever an OS assignment or a chosen arch changes.
            for _v in list(os_vars.values()) + list(arch_chosen.values()):
                _v.trace_add("write", lambda *_a: update_counts())

            # ── Card ───────────────────────────────────────────────────────────
            card = tk.Frame(f, bg=CARD, bd=1, relief="solid")
            card.pack(fill=tk.X, pady=(8, 0))

            tk.Label(card, text=_T('🧩  Agente local — {} dispositivo(s) sin acceso remoto').format(len(entries)),
                     bg=CARD, font=(_FONT, 9, "bold")).pack(anchor="w", padx=10, pady=(8, 0))
            tk.Label(card,
                     text="Cada agente detecta su equipo por ID de Syncthing y pide confirmación antes de aplicar.",
                     bg=CARD, fg="#777", font=(_FONT, 7),
                     wraplength=self._win_w - 80, justify="left").pack(anchor="w", padx=10)

            body = tk.Frame(card, bg=CARD)
            body.pack(fill=tk.X, padx=10, pady=(6, 2))

            def _arch_cell(parent, e):
                # The third column (replaces the old path — the agent shows/confirms the path on
                # the target machine anyway): the device's architecture in BLUE when known
                # (detected or chosen), or "arquitectura no seleccionada" in RED when missing. For
                # a non-Windows device without a DETECTED arch the cell is clickable → arch popup
                # (covers a detected-OS device whose arch we couldn't read — decision c).
                did = e["device_id"]
                arch_detected = bool(e.get("arch_detected") and e.get("arch"))
                lbl = tk.Label(parent, bg=CARD, font=(_FONT, 8), anchor="w")

                def _cur_os():
                    return e["os_type"] if e.get("os_detected") else os_vars[did].get()

                def refresh(*_a):
                    os_now = _cur_os()
                    if os_now == "windows":
                        lbl.config(text="—", fg="#999", cursor="")
                    elif not os_now:                     # no OS chosen yet → nothing to specify
                        lbl.config(text="", cursor="")
                    elif _eff_arch(e):
                        lbl.config(text=_eff_arch(e), fg=BLUE, font=(_FONT, 8, "bold"),
                                   cursor="" if arch_detected else "hand2")
                    else:
                        lbl.config(text=_T("arquitectura no seleccionada"), fg="#C62828",
                                   font=(_FONT, 8), cursor="hand2")

                if not arch_detected:
                    def _click(_ev=None):
                        os_now = _cur_os()
                        if os_now in ("linux", "macos"):   # arch only applies to Linux/macOS
                            a = _ask_arch(os_now, arch_chosen[did].get())
                            if a:
                                arch_chosen[did].set(a)
                    lbl.bind("<Button-1>", _click)

                if did in os_vars:
                    os_vars[did].trace_add("write", refresh)
                arch_chosen[did].trace_add("write", refresh)
                refresh()
                return lbl

            def _add_row(e, selectable):
                # Aligned columns: [device name] [OS chip/selector] [architecture].
                row = tk.Frame(body, bg=CARD)
                row.pack(fill=tk.X, pady=2)
                tk.Label(row, text=e["device_name"], bg=CARD, font=(_FONT, 9, "bold"),
                         width=18, anchor="w").pack(side=tk.LEFT)
                oscol = tk.Frame(row, bg=CARD)
                oscol.pack(side=tk.LEFT, padx=(4, 0))
                if selectable:
                    _os_toggle(oscol, os_vars[e["device_id"]], on_pick=_device_pick(e)).pack()
                else:
                    chip = {"windows": "🪟 Windows", "macos": "🍎 macOS"}.get(e["os_type"], "🐧 Linux")
                    tk.Label(oscol, text=chip, bg="#E8F5E9", fg="#1B5E20",
                             font=(_FONT, 8, "bold"), padx=8, pady=2).pack()
                _arch_cell(row, e).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))

            for e in entries:
                if e.get("os_detected"):
                    _add_row(e, selectable=False)

            if unknown:
                ttk.Separator(body, orient="horizontal").pack(fill=tk.X, pady=(4, 3))
                hdr = tk.Frame(body, bg=CARD)
                hdr.pack(fill=tk.X)
                tk.Label(hdr, text="SO sin detectar — asígnalo:", bg=CARD,
                         font=(_FONT, 8, "italic"), fg="#666").pack(side=tk.LEFT)
                all_var = tk.StringVar(value="")

                def _all_pick(val):
                    # Apply the OS to every undetected device. For Linux/macOS prompt ONCE for the
                    # arch and apply it to those without a detected arch (detected ones keep theirs).
                    if val in ("linux", "macos"):
                        a = _ask_arch(val)
                        if not a:
                            return False
                        for _e in unknown:
                            if not (_e.get("arch_detected") and _e.get("arch")):
                                arch_chosen[_e["device_id"]].set(a)
                            os_vars[_e["device_id"]].set(val)
                        # Also resolve detected-OS devices of THIS OS whose arch wasn't detected
                        # (decision c) — otherwise "Todos" leaves them red and the button disabled.
                        for _e in entries:
                            if (_e.get("os_detected") and _e.get("os_type") == val
                                    and not (_e.get("arch_detected") and _e.get("arch"))):
                                arch_chosen[_e["device_id"]].set(a)
                    else:                                  # windows → no arch needed
                        for _e in unknown:
                            arch_chosen[_e["device_id"]].set("")
                            os_vars[_e["device_id"]].set(val)
                    return True

                _os_toggle(hdr, all_var, on_pick=_all_pick).pack(side=tk.RIGHT)
                tk.Label(hdr, text="Todos:", bg=CARD, font=(_FONT, 8),
                         fg="#666").pack(side=tk.RIGHT, padx=(0, 4))
                for e in unknown:
                    _add_row(e, selectable=True)

            # Shared encryption passphrase — a single visible field used for BOTH OSes.
            # (Was a lazy popup that only fired for the FIRST OS generated, so the second
            # silently reused it and seemed to "not ask" — issue B3.)
            pw_var = tk.StringVar()
            pwf = tk.Frame(card, bg=CARD)
            pwf.pack(fill=tk.X, padx=10, pady=(6, 0))
            tk.Label(pwf, text="🔒 Contraseña de cifrado:", bg=CARD,
                     font=(_FONT, 8, "bold")).pack(side=tk.LEFT)
            pw_ent = ttk.Entry(pwf, textvariable=pw_var, width=22, show="●")
            pw_ent.pack(side=tk.LEFT, padx=(6, 0))
            tk.Button(pwf, text="👁", font=(_FONT, 8), relief="flat", bg=CARD, cursor="hand2",
                      command=lambda: pw_ent.config(show="" if pw_ent.cget("show") else "●")
                      ).pack(side=tk.LEFT)
            tk.Label(pwf, text="(vacío = sin cifrar; la API Key quedaría legible en el binario)",
                     bg=CARD, fg="#999", font=(_FONT, 7)).pack(side=tk.LEFT, padx=(6, 0))

            def _gen_multi(target_os: str) -> None:
                filtered = entries_for_os(target_os)
                os_name = {"windows": "Windows", "macos": "macOS"}.get(target_os, "Linux")
                if not filtered:
                    result_lbl.config(text=_T('No hay dispositivos asignados a {}.').format(os_name), fg="#C62828")
                    return
                passphrase = pw_var.get() or None
                is_arch_os = target_os in ("linux", "macos")

                # Decide which agent binaries to build (fast; reads GUI state on the Tk thread).
                # Windows is single-template (a x64 .exe emulates on Windows-ARM). For Linux/macOS
                # we build one binary per DISTINCT per-device architecture (detected or chosen via
                # the popup). Every assigned device MUST have an arch — the button is disabled
                # otherwise, but guard here too. builds: (target_arch_or_None, filename_or_None, lab)
                undetected_archless: list = []
                builds: list = []
                if not is_arch_os:
                    builds.append((None, None, None))
                else:
                    missing = sum(1 for e in filtered if not _eff_arch(e))
                    if missing:
                        result_lbl.config(
                            text=_T('Falta especificar la arquitectura de {} dispositivo(s) {}.').format(
                                missing, os_name), fg="#C62828")
                        return
                    base_arch = _base_arch_for(target_os)
                    avail = _avail_arches_for(target_os)
                    # The set of per-device arches drives the builds. has_undetected=False: arches
                    # are all known here, so select_agent_builds builds the base only when a device
                    # actually runs it (or there are no other arches), plus each extra arch; an arch
                    # with no embedded template lands in undetected_archless (warned, not built).
                    needed = {_eff_arch(e) for e in filtered}
                    build_base, extra, undetected_archless = select_agent_builds(
                        needed, False, avail, base_arch)
                    if build_base:
                        if target_os == "macos":
                            # macOS has no plain template: build the base arch EXPLICITLY (suffixed),
                            # never via target_arch=None (which would silently grab whichever macOS
                            # arch is embedded first and mislabel it).
                            builds.append((base_arch, f"syncthing-manager-agent-macos-{base_arch}", base_arch))
                        else:
                            builds.append((None, None, base_arch))
                    builds += [(a, f"syncthing-manager-agent-{target_os}-{a}", a) for a in extra]

                multi = len(builds) > 1
                _my_gen = self._show_gen
                # Run the (potentially several) multi-MB template reads+writes OFF the Tk thread so
                # the window stays responsive and the log streams live. Disabling the generate
                # buttons synchronously here (before the thread starts) is the re-entrancy guard —
                # a second click lands on a disabled button — mirroring _resume_paused. done()/​
                # _err() re-enable them via update_counts(). (No separate busy flag: a process-wide
                # flag could be cleared by a stale worker after a page rebuild; the per-card button
                # state is the correct scope, and the _show_gen guard ignores stale callbacks.)
                for _b, _ok in ((win_btn, win_ok), (linux_btn, linux_ok), (macos_btn, macos_ok)):
                    if _b is not None and _ok:
                        _b.config(state="disabled")
                clicked = {"windows": win_btn, "linux": linux_btn, "macos": macos_btn}.get(target_os)
                if clicked is not None:
                    clicked.config(text=_T("⏳ Generando {}…").format(os_name))

                def _work_impl():
                    successes: list = []
                    failures: list = []          # arch labels (or None) that failed to build
                    covered: set = set()
                    for tgt_arch, fn, lab in builds:
                        try:
                            out = generate_multi_agent_file(
                                entries=filtered, target_os=target_os, target_arch=tgt_arch,
                                output_dir=Path.cwd(), passphrase=passphrase, filename=fn)
                            successes.append((lab, out))
                            covered.update(e.get("device_id") for e in filtered if e.get("device_id"))
                            if lab is not None and multi:
                                log_line(_T("  ✓  Agente {} {} generado: {}  ({} disp.)").format(
                                    os_name, _arch_label_for(target_os, lab), out, len(filtered)), "ok")
                            else:
                                log_line(_T("  ✓  Agente {} generado: {}  ({} disp.)").format(
                                    os_name, out, len(filtered)), "ok")
                        except Exception as _e:
                            failures.append(lab)
                            if lab is not None:
                                log_line(_T("  ✗  Error generando agente {} {}: {}").format(
                                    os_name, _arch_label_for(target_os, lab), _e), "err")
                            else:
                                log_line(_T("  ✗  Error generando agente {}: {}").format(os_name, _e), "err")

                    def done():
                        # Bail BEFORE touching any widget if the user navigated away (stale page)
                        # or the card was torn down — checking result_lbl (built in the same card
                        # as the buttons) covers update_counts()'s button access too.
                        if self._show_gen != _my_gen or not result_lbl.winfo_exists():
                            return
                        update_counts()   # restore the OK buttons' text/state (counts unchanged)
                        if not successes:
                            if undetected_archless and not failures:
                                # Nothing built because every device's arch lacks an embedded
                                # template — surface the uncovered warning (orange), not a generic
                                # error (we never build a base nobody can run, fix #3).
                                _w = _T("⚠  {}: arquitectura(s) sin plantilla embebida: {} — esos dispositivos no quedan cubiertos (recompila con la plantilla)").format(
                                    os_name, ", ".join(undetected_archless))
                                log_line("  " + _w, "warn")
                                result_lbl.config(text=_w, fg="#E65100")
                            else:
                                result_lbl.config(text=_T('✗  Error generando agente {}.').format(os_name), fg="#C62828")
                            return
                        # Record covered devices on the Tk thread (no cross-thread set mutation).
                        self.s.setdefault("_exec_agent_generated_ids", set()).update(covered)
                        lines = []
                        for lab, out in successes:
                            if lab is not None and len(successes) > 1:
                                lines.append(_T("✓  Agente {} ({}): {}").format(
                                    os_name, _arch_label_for(target_os, lab), out))
                            else:
                                lines.append(_T("✓  Agente {} generado: {}").format(os_name, out))
                        if is_arch_os:
                            # The Unix exec bit can't be set reliably from a Windows/FAT/synced FS.
                            lines.append(_T("     ⚠ en la máquina {}: chmod +x antes de ejecutarlo").format(os_name))
                            log_line(_T("     ⚠ recuerda: chmod +x en la máquina {} antes de ejecutarlo").format(os_name), "warn")
                        if undetected_archless:
                            _w = _T("⚠  {}: arquitectura(s) sin plantilla embebida: {} — esos dispositivos no quedan cubiertos (recompila con la plantilla)").format(
                                os_name, ", ".join(undetected_archless))
                            lines.append(_w)
                            log_line("  " + _w, "warn")
                        # Partial failure: some arch(es) built, others didn't (e.g. the base agent
                        # that covers the undetected/amd64 devices). Surface it in the LABEL (not
                        # only the dark log) and drop the all-green colour so it isn't read as OK.
                        failed_labels = [_arch_label_for(target_os, l) if l is not None else os_name
                                         for l in failures]
                        if failed_labels:
                            lines.append(_T("✗  Falló: {} — revisa el registro").format(", ".join(failed_labels)))
                        # Accumulate across OS buttons (generate Windows THEN Linux keeps both).
                        new_text = "\n".join(lines)
                        prev = result_lbl.cget("text")
                        # Orange (not green) when a build failed OR some device's arch couldn't be
                        # covered — a green ✓ must never overstate a partial/uncovered result.
                        result_lbl.config(
                            text=(prev + "\n" + new_text) if (prev and prev.startswith("✓")) else new_text,
                            fg="#E65100" if (failed_labels or undetected_archless) else "#2E7D32")
                    self._post(done)

                def work():
                    # Never leave the buttons stuck disabled: surface any unexpected failure and
                    # restore them (generate_multi_agent_file could raise outside the per-build try).
                    try:
                        _work_impl()
                    except Exception as e:
                        def _err(_e=e):
                            if self._show_gen != _my_gen or not result_lbl.winfo_exists():
                                return
                            update_counts()
                            result_lbl.config(text=_T('✗  Error generando agente {}: {}').format(os_name, _e), fg="#C62828")
                        self._post(_err)

                threading.Thread(target=work, daemon=True).start()

            btnrow = tk.Frame(card, bg=CARD)
            btnrow.pack(fill=tk.X, padx=10, pady=(4, 2))

            def _missing_template_msg(os_name: str, other: str):
                # Explain WHY (and how to fix) instead of silently hiding the button — a
                # missing template just means it wasn't embedded at build time on this OS.
                messagebox.showinfo(
                    _T('Plantilla {} no disponible').format(os_name),
                    _T('El binario actual no lleva embebida la plantilla de agente {}.\n\nUna plantilla {} solo se compila EN {}. Para poder generar agentes {} desde aquí, tienes dos opciones:\n\n• Rápida (sin recompilar): deja el ejecutable de plantilla en una subcarpeta «{}» junto a este programa.\n\n• Permanente: recompila este binario con la plantilla {} presente — se sincroniza vía build/prebuilt/ y se embebe sola.').format(os_name, os_name, os_name, os_name, other, os_name),
                    parent=self)

            # Always SHOW both buttons; disable the one whose template isn't embedded and
            # explain on click (used to be hidden, which looked like a bug — issue: "no
            # aparece el botón de generar Linux").
            win_btn = ttk.Button(
                btnrow, text=_T("🪟 Generar Windows") + ("" if win_ok else _T(" (no embebida)")),
                command=(lambda: _gen_multi("windows")) if win_ok
                else (lambda: _missing_template_msg("Windows", "windows")))
            win_btn.pack(side=tk.LEFT)
            if not win_ok:
                win_btn.state(["!disabled"])  # keep clickable to show the explanation
            linux_btn = ttk.Button(
                btnrow, text=_T("🐧 Generar Linux") + ("" if linux_ok else _T(" (no embebida)")),
                command=(lambda: _gen_multi("linux")) if linux_ok
                else (lambda: _missing_template_msg("Linux", "linux")))
            linux_btn.pack(side=tk.LEFT, padx=(6, 0))
            macos_btn = ttk.Button(
                btnrow, text=_T("🍎 Generar macOS") + ("" if macos_ok else _T(" (no embebida)")),
                command=(lambda: _gen_multi("macos")) if macos_ok
                else (lambda: _missing_template_msg("macOS", "macos")))
            macos_btn.pack(side=tk.LEFT, padx=(6, 0))
            if not macos_ok:
                macos_btn.state(["!disabled"])  # keep clickable to show the explanation

            result_lbl = tk.Label(card, text="", bg=CARD, font=(_FONT, 8), anchor="w",
                                  justify="left", wraplength=self._win_w - 80)
            result_lbl.pack(fill=tk.X, padx=10, pady=(0, 8))

            update_counts()

        # ── Final-page actions: resume / undo / report / passive exploration ──

        def _resume_paused(paused_results, btn) -> None:
            btn.config(state="disabled", text="Reanudando…")
            folder = self.s["folder"]

            def _work_impl():
                from ..renamer import resume_folder_on_device
                log_line("", "dim")
                log_line(_T("── Reanudando carpetas pausadas ──"), "warn")
                still = 0
                for r in paused_results:
                    ok, msg = resume_folder_on_device(r.device, folder.id)
                    if ok:
                        r.resumed = True
                        log_line(f"  ✓  {r.device.name} — {msg}", "ok")
                    else:
                        still += 1
                        log_line(f"  ✗  {r.device.name} — {msg}", "err")

                def done():
                    if not btn.winfo_exists():
                        return
                    if still:
                        btn.config(state="normal", text=f"▶ Reintentar {still} pausada(s)")
                        self._status(f"⚠ {still} siguen pausadas", "#C62828")
                    else:
                        btn.config(state="disabled", text="✓ Reanudadas")
                        self._status("✓ Todas las carpetas reanudadas", "#2E7D32")
                self._post(done)

            def work():
                # Never leave the button stuck on "Reanudando…": surface any unexpected
                # failure and re-enable it (resume_folder_on_device could raise).
                try:
                    _work_impl()
                except Exception as e:
                    def _err(_e=e):
                        if btn.winfo_exists():
                            btn.config(state="normal", text="▶ Reintentar pausadas")
                        self._status(_T('Error al reanudar: {}').format(_e), "#C62828")
                    self._post(_err)

            threading.Thread(target=work, daemon=True).start()

        def _save_report(results) -> None:
            import datetime
            folder = self.s["folder"]
            lines = [
                "Syncthing Folder Rename — informe",
                f"Fecha:   {datetime.datetime.now().isoformat(timespec='seconds')}",
                _T('Carpeta: {}  (id={})').format(folder.label or folder.id, folder.id),
                f"Nuevo label: {self.s['new_label']}",
                _T('Nueva ruta/nombre: {}').format(self.s['new_path_input'] or '(solo label)'),
            ]
            if self.s.get("rename_id") and self.s.get("new_folder_id"):
                lines.append(f"Nuevo ID: {self.s['new_folder_id']}")
            lines.append(f"Dry run: {'sí' if self.s['dry_run'] else 'no'}")
            lines.append("")
            lines.append("Resultados por dispositivo:")
            for r in results:
                if r.success and not r.warning:
                    st = "OK"
                elif r.success and r.warning:
                    st = "OK (acción manual)"
                elif r.left_paused:
                    st = f"PAUSADA — {r.error}"
                else:
                    st = _T('ERROR — {}').format(r.error)
                steps = []
                if r.paused: steps.append("pausado")
                if r.dir_renamed: steps.append(_T("disco"))
                if r.config_updated: steps.append(_T("config"))
                if r.resumed: steps.append(_T("reanudado"))
                lines.append(f"  - {r.device.name}: {st}  [{', '.join(steps) or '—'}]")
                if r.warning:
                    for w in r.warning.splitlines():
                        lines.append(f"      {w}")
            content = "\n".join(lines) + "\n"

            default = f"syncthing-manager-{folder.id}-{datetime.datetime.now():%Y%m%d-%H%M%S}.txt"
            path = filedialog.asksaveasfilename(
                title="Guardar informe", defaultextension=".txt", initialfile=default,
                filetypes=[("Texto", "*.txt"), ("Todos", "*.*")],
            )
            if not path:
                return
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(content)
                self._status(_T('📄 Informe guardado en {}').format(path), "#2E7D32")
                log_line(_T('  📄 Informe guardado: {}').format(path), "dim")
            except OSError as e:
                messagebox.showerror("Error", _T('No se pudo guardar el informe:\n{}').format(e))

        def _undo_new_folder(btn) -> None:
            """A brand-new folder has no rename to revert — instead choose what to do with the
            folder it created: (A) keep it (revert only the topology edits), (B) stop sharing but
            KEEP the files on disk, or (C) stop sharing AND delete the files on the nodes you pick.
            B/C use the same tested delete backend as the cluster delete (not the passive-revert)."""
            folder = self.s.get("folder")
            if not folder:
                return
            fname = folder.label or folder.id
            nodes = (self.s.get("topology") or {}).get("nodes", {})
            with self._devices_lock:
                dm = {d.device_id: d for d in self.s.get("devices", [])}
            # (device_id, label, DeviceInfo|None, can_delete_disk)
            members = []
            for nid, n in nodes.items():
                d = dm.get(nid)
                can = bool(d and (d.is_local or d.ssh_reachable or d.winrm_reachable)
                           and d.folder_path)
                members.append((nid, n.get("label", nid[:7]), d, can))

            dlg = tk.Toplevel(self)
            dlg.title("Deshacer carpeta nueva")
            dlg.configure(bg="white")
            dlg.transient(self)
            dlg.grab_set()
            self._center_dialog(dlg)
            tk.Label(dlg, text=_T('Deshacer «{}» (carpeta nueva)').format(fname), bg="white",
                     font=(_FONT, 10, "bold")).pack(anchor="w", padx=16, pady=(12, 2))
            tk.Label(dlg, text="¿Qué quieres hacer con la carpeta que creaste?", bg="white",
                     fg="#888", font=(_FONT, 8)).pack(anchor="w", padx=16, pady=(0, 6))
            mode = tk.StringVar(value="topo")
            for _val, _txt in (
                    ("topo", "Revertir solo la topología (conservar la carpeta y los archivos)"),
                    ("unshare", "Dejar de compartir la carpeta y CONSERVAR los archivos en disco"),
                    ("wipe", "Dejar de compartir y BORRAR los archivos en disco (elige nodos)")):
                ttk.Radiobutton(dlg, text=_T(_txt), variable=mode, value=_val,
                                command=lambda: _upd()).pack(anchor="w", padx=18, pady=1)

            nodefrm = tk.Frame(dlg, bg="white")
            _all_v = tk.BooleanVar(value=False)
            _node_vars: dict = {}
            _eligible: list = []   # (nid, var)
            count_lbl = tk.Label(nodefrm, text="", bg="white", fg="#555", font=(_FONT, 8))

            def _upd_count():
                n = sum(1 for _nid, _v in _eligible if _v.get())
                count_lbl.config(text=_T('se borrará el disco en {} de {} nodo(s)').format(
                    n, len(_eligible)))
                _upd_btn()

            def _toggle_all():
                for _nid, _v in _eligible:
                    _v.set(_all_v.get())
                _upd_count()

            tk.Checkbutton(nodefrm, text=_T("Marcar todos"), variable=_all_v, bg="white",
                           command=_toggle_all).pack(anchor="w", padx=10)
            for nid, lbl, d, can in members:
                v = tk.BooleanVar(value=False)
                _node_vars[nid] = v
                txt = lbl if can else (lbl + _T("  (sin acceso: solo se deja de compartir)"))
                tk.Checkbutton(nodefrm, text=txt, variable=v, bg="white",
                               state=("normal" if can else "disabled"),
                               command=_upd_count).pack(anchor="w", padx=20)
                if can:
                    _eligible.append((nid, v))
            count_lbl.pack(anchor="w", padx=20, pady=(2, 0))

            name_frm = tk.Frame(dlg, bg="white")
            name_v = tk.StringVar()
            tk.Label(name_frm, text=_T('Para confirmar, escribe el nombre de la carpeta:  «{}»')
                     .format(fname), bg="white", font=(_FONT, 9)).pack(anchor="w", padx=16, pady=(6, 0))
            ttk.Entry(name_frm, textvariable=name_v, width=36).pack(anchor="w", padx=16)
            name_v.trace_add("write", lambda *_: _upd_btn())

            btnf = tk.Frame(dlg, bg="white")
            do_btn = ttk.Button(btnf, text="Aplicar")
            do_btn.pack(side=tk.RIGHT)
            ttk.Button(btnf, text="Cancelar", command=dlg.destroy).pack(side=tk.RIGHT, padx=(0, 6))

            def _upd_btn():
                m = mode.get()
                ok = (m == "topo") or (name_v.get().strip() == fname)
                do_btn.config(state="normal" if ok else "disabled")

            def _upd():
                m = mode.get()
                # Re-pack the dynamic frames ABOVE the buttons (before=btnf) in a fixed order:
                # per-node list (wipe only) then the type-the-name confirm (destructive modes).
                nodefrm.pack_forget()
                name_frm.pack_forget()
                if m == "wipe":
                    nodefrm.pack(fill=tk.X, padx=8, pady=(4, 0), before=btnf)
                    _upd_count()
                if m in ("unshare", "wipe"):
                    name_frm.pack(fill=tk.X, before=btnf)
                _upd_btn()

            def _go():
                m = mode.get()
                if m != "topo" and name_v.get().strip() != fname:
                    return
                disk_ids = {nid for nid, v in _eligible if v.get()} if m == "wipe" else set()
                dlg.destroy()
                if m == "topo":
                    # Keep the folder — revert only the topology edits. If there are none, do
                    # NOT run (and pop) the undo: that would disable "Deshacer" and leave the
                    # user no way back to the unshare/wipe options for the folder they created.
                    _to, _tc = self.s.get("topology_orig"), self.s.get("topology")
                    if _to and _tc and _topology_delta(_to, _tc).get("any"):
                        _run_undo({"topo": True}, btn, self.s.get("new_label", ""))
                    else:
                        self._status(_T('No hay cambios de topología que revertir; la carpeta '
                                        'se conserva.'), "#555")
                    return
                _delete_new_folder(folder, members, disk_ids, btn)

            do_btn.config(command=_go)
            btnf.pack(fill=tk.X, padx=16, pady=12)   # pack the buttons first…
            _upd()                                   # …then place the dynamic frames before them

        def _delete_new_folder(folder, members, disk_ids, btn) -> None:
            """Stop sharing the new folder on every member; delete the on-disk files only on the
            nodes in `disk_ids`. Uses delete_folder_on_device (the tested backend)."""
            try:
                btn.config(state="disabled", text="Deshaciendo…")
            except Exception:
                pass
            self._status(_T('Deshaciendo «{}»…').format(folder.label or folder.id), "#C62828")
            _my_gen = self._show_gen

            def _work_impl():
                from ..renamer import delete_folder_on_device
                results = []   # (label, ok, msg, disk_not_deleted)
                for nid, lbl, d, _can in members:
                    if d is None:
                        results.append((lbl, False, _T("sin acceso (offline/desconocido)"), False))
                        continue
                    r = delete_folder_on_device(d, folder.id,
                                                delete_data=(nid in disk_ids))
                    results.append((r.device_name, r.ok, r.message, r.disk_not_deleted))

                def ui():
                    appconfig.delete_topology_snapshot(folder.id)
                    if self._show_gen != _my_gen:
                        return
                    okc = sum(1 for _, k, _, _ in results if k)
                    badc = [(nm, m) for nm, k, m, _ in results if not k]
                    disk_left = [(nm, m) for nm, k, m, d in results if k and d]
                    self._reset_folder_scoped_state()
                    extra = (_T('\n{} con error: {}').format(len(badc), badc[0][1]) if badc else "")
                    if disk_left:
                        _n = ", ".join(nm for nm, _ in disk_left)
                        extra += _T('\n⚠ OJO: en {} equipo(s) se quitó de Syncthing pero los '
                                    'archivos en disco NO se borraron ({}). Bórralos a mano o '
                                    'revisa el acceso.').format(len(disk_left), _n)
                    _box = messagebox.showwarning if (badc or disk_left) else messagebox.showinfo
                    _box("Deshacer carpeta nueva",
                         _T('«{}» revertida en {} equipo(s).{}\n\nVolviendo a la selección de '
                            'carpeta.').format(folder.label or folder.id, okc, extra), parent=self)
                    self._show(1)
                self._post(ui)

            def work():
                # Never leave the button stuck on "Deshaciendo…": surface any unexpected
                # failure and re-enable it (delete_folder_on_device normally returns results,
                # but a transport error could still raise).
                try:
                    _work_impl()
                except Exception as e:
                    def _err(_e=e):
                        if btn.winfo_exists():
                            btn.config(state="normal", text="↶ Deshacer último rename")
                        self._status(_T('Error al deshacer: {}').format(_e), "#C62828")
                    self._post(_err)

            threading.Thread(target=work, daemon=True).start()

        def _undo_last(btn) -> None:
            snap = self.s.get("_undo")
            if not snap:
                return
            # A brand-new folder has no rename to revert — offer the folder-disposition dialog
            # (keep / unshare keeping disk / unshare + delete disk per-node) instead.
            if snap.get("is_new_folder"):
                _undo_new_folder(btn)
                return
            cur_label = self.s.get("new_label", "")
            topo_avail = bool(self.s.get("topology_orig") and
                              _topology_delta(self.s.get("topology_orig"),
                                              self.s.get("topology")).get("any"))
            label_avail = snap["old_label"] != cur_label
            path_avail = not snap["skip_path"]
            id_avail = bool(snap["rename_id"] and snap["new_folder_id"])

            opts = []  # (key, text)
            if label_avail:
                opts.append(("label", f"Label   «{cur_label}» → «{snap['old_label']}»"))
            if path_avail:
                opts.append(("path", _T('Ruta / disco   → «{}»').format(snap['old_dir_name'])))
            if id_avail:
                opts.append(("id", _T('ID de carpeta   → «{}»').format(snap['folder_id'])))
            if topo_avail:
                opts.append(("topo", "Topología   (enlaces, roles, dispositivos nuevos)"))
            if not opts:
                messagebox.showinfo("Deshacer", "No hay cambios que revertir.")
                return

            # ── Selection dialog (#54): choose what to revert, keep the rest ──
            dlg = tk.Toplevel(self)
            dlg.title("Deshacer — elegir qué revertir")
            dlg.configure(bg="white")
            dlg.grab_set()
            tk.Label(dlg, text="¿Qué quieres revertir?", bg="white",
                     font=(_FONT, 10, "bold")).pack(anchor="w", padx=14, pady=(12, 2))
            tk.Label(dlg, text="Lo no marcado se conserva tal cual.", bg="white", fg="#888",
                     font=(_FONT, 8)).pack(anchor="w", padx=14, pady=(0, 6))
            vars_ = {}
            for key, text in opts:
                v = tk.BooleanVar(value=True)
                vars_[key] = v
                _CheckButton(dlg, text=text, variable=v).pack(anchor="w", padx=18, pady=1)
            tk.Label(dlg, text=("Los dispositivos por exploración pasiva que no estén conectados se "
                                "revertirán al reconectar (mantén la ventana abierta). Los de agente "
                                "no se revierten automáticamente."),
                     bg="white", fg="#C66000", font=(_FONT, 8), wraplength=420,
                     justify="left").pack(anchor="w", padx=14, pady=(8, 0))
            btnf = tk.Frame(dlg, bg="white")
            btnf.pack(fill=tk.X, padx=14, pady=12)

            def _confirm():
                flags = {k: vars_[k].get() for k in vars_}
                if not any(flags.values()):
                    messagebox.showinfo("Deshacer", "No has marcado nada para revertir.")
                    return
                dlg.destroy()
                _run_undo(flags, btn, cur_label)

            ttk.Button(btnf, text="Deshacer seleccionado", command=_confirm).pack(side=tk.RIGHT)
            ttk.Button(btnf, text="Cancelar", command=dlg.destroy).pack(side=tk.RIGHT, padx=(0, 6))

        def _run_undo(flags: dict, btn, cur_label: str) -> None:
            snap = self.s.get("_undo")
            if not snap:
                return
            btn.config(state="disabled", text="Deshaciendo…")
            passive_ctrl["reverting"] = True

            r_id    = bool(flags.get("id")) and bool(snap["rename_id"] and snap["new_folder_id"])
            r_label = bool(flags.get("label"))
            r_path  = bool(flags.get("path")) and not snap["skip_path"]
            r_topo  = bool(flags.get("topo"))

            # Folder id the rename/topology revert must target on existing devices:
            # old id if we're reverting the ID, otherwise whatever id they hold now.
            if r_id:
                eff_id = snap["folder_id"]
            elif snap["rename_id"] and snap["new_folder_id"]:
                eff_id = snap["new_folder_id"]
            else:
                eff_id = snap["folder_id"]

            bits = []
            if r_label:
                bits.append(f"label→«{snap['old_label']}»")
            if r_path:
                bits.append(_T('ruta→«{}»').format(snap['old_dir_name']))
            if r_id:
                bits.append(f"ID→«{snap['folder_id']}»")
            revert_detail = ", ".join(bits) if bits else "(sin cambios de rename)"

            # Pass the selection to the passive revert loop so reconnects honor it too.
            revert_spec = dict(snap)
            revert_spec.update(revert_id=r_id, revert_label=r_label,
                               revert_path=r_path, revert_topo=r_topo, keep_label=cur_label)

            def _work_impl():
                from ..renamer import rename_all_devices as _rad, rename_folder_id as _rfi
                with self._devices_lock:
                    devs = [d for d in self.s["devices"] if _device_kind(d) == "ok"]
                # New topology devices have no prior label/path/ID to restore — they're
                # reverted purely by REMOVING their folder (in the topology-revert pass
                # below), never through the rename pipeline. Excluding them here stops a
                # guaranteed rename-revert "failure" from parking them in the passive
                # pending set, which would otherwise skip the graph reset and leave the
                # node lingering in Topología after an undo.
                _topo_cur0 = self.s.get("topology") or {"nodes": {}}
                new_ids = {nid for nid, n in _topo_cur0["nodes"].items() if n.get("is_new")}
                rename_devs = [d for d in devs if d.device_id not in new_ids]
                log_line("", "dim")
                log_line(_T("── Deshaciendo (selección) ──"), "warn")
                id_failed: set = set()
                if r_id:
                    for r_idx, (name, ok, msg) in enumerate(
                            _rfi(rename_devs, snap["new_folder_id"], snap["folder_id"], dry_run=False)):
                        if not ok and r_idx < len(rename_devs):
                            id_failed.add(rename_devs[r_idx].device_id)
                        log_line(f"  {'✓' if ok else '✗'}  {name} — "
                                 f"{'ID revertido' if ok else msg}", "ok" if ok else "err")

                # Every reachable device is handled in this immediate pass; start from
                # "all done" and drop the ones that failed, so reachable devices never
                # get re-processed by the passive reconnect loop below.
                reverted_ok: set = {d.device_id for d in devs if d.device_id not in id_failed}
                if r_label or r_path:
                    label_arg = snap["old_label"] if r_label else cur_label
                    dir_arg   = snap["old_dir_name"] if r_path else ""
                    skip_arg  = (not r_path)
                    res = _rad(devices=rename_devs, folder_id=eff_id, new_label=label_arg,
                               new_dir_name=dir_arg, dry_run=False, skip_path_rename=skip_arg)
                    with self._devices_lock:
                        for r in res:
                            if r.success and r.new_path:
                                r.device.folder_path = r.new_path
                            if not r.success:
                                reverted_ok.discard(r.device.device_id)
                    for r in res:
                        log_line(f"  {'✓' if r.success else '✗'}  {r.device.name} — "
                                 f"{(revert_detail + ' revertidos') if r.success else r.error}",
                                 "ok" if r.success else "err")

                # ── Revert topology (restore the original graph) ──────────────
                # Track which NEW (user-added) nodes we actually removed from the device,
                # so only those are dropped from the GUI graph/devices below. A new node
                # whose removal FAILS is kept (so the user can retry instead of it silently
                # lingering on the device while vanishing from the UI).
                removed_new_ok: set = set()
                if r_topo:
                    topo_orig = self.s.get("topology_orig")
                    topo_cur = self.s.get("topology")
                    if topo_orig and _topology_delta(topo_orig, topo_cur).get("any"):
                        from ..renamer import (apply_topology_on_device, remove_folder_on_device,
                                              compute_topology_diff as _ctd_rev,
                                              prune_orphan_device_entries as _prune)
                        log_line(_T("── Revirtiendo topología ──"), "warn")
                        fwd_eff = (snap["new_folder_id"] if (snap["rename_id"] and snap["new_folder_id"])
                                   else snap["folder_id"])
                        # Inverse diff (edited graph → original): mirrors the forward apply
                        # exactly and is NON-DESTRUCTIVE — a link the user ADDED becomes a
                        # removal on BOTH endpoints; untouched neighbours are left intact.
                        # (The old full-rewrite was asymmetric and could leave added links in
                        # place, so a just-linked device never got unlinked.)
                        rev_diff = _ctd_rev(topo_cur, topo_orig,
                                            locked=self.s.get("topology_locked"))
                        # Capture the inverse diff + a STABLE snapshot of both graphs for the
                        # passive-revert loop. That loop must NOT read the live self.s graph
                        # for its gate/diff: purging an already-reverted new node strips its
                        # edges from the live graph, which would make a later (not-yet-
                        # reconnected) existing neighbour's revert see an empty delta and get
                        # skipped — leaving an orphaned share while the undo reports success.
                        revert_spec["rev_diff"] = rev_diff
                        revert_spec["topo_orig_snap"] = _copy_topology(topo_orig)
                        revert_spec["topo_cur_snap"] = _copy_topology(topo_cur)
                        for d in devs:
                            if d.device_id in new_ids:
                                tr = remove_folder_on_device(d, fwd_eff)
                                if tr.ok:
                                    removed_new_ok.add(d.device_id)
                                log_line(f"  {'✓' if tr.ok else '✗'}  {tr.device_name} (nuevo) — {tr.message}",
                                         "ok" if tr.ok else "err")
                            elif topo_orig["nodes"].get(d.device_id):
                                tr = apply_topology_on_device(d, eff_id, topo_orig, diff=rev_diff,
                                                              folder_label=snap["old_label"], dry_run=False)
                                log_line(_T('  {}  {} (topología) — {}').format('✓' if tr.ok else '✗', tr.device_name, tr.message),
                                         "ok" if tr.ok else "err")
                                # B2: also drop the unlinked peers from THIS device's global
                                # device list if they're not shared via any other folder, so
                                # they stop appearing in Syncthing (not just in the folder).
                                _removed_peers = {o for e in rev_diff.get("links_removed", set())
                                                  if d.device_id in e for o in (e - {d.device_id})}
                                for _pid, _ok, _msg in _prune(d, _removed_peers):
                                    if _ok:
                                        log_line(_T('     · {}: dispositivo «{}» {}').format(tr.device_name, _pid[:7], _msg), "dim")

                # A reachable new device is reverted right here (removed above) so it's in
                # `reverted_ok` (never rename-failed) → already excluded from `pending`. An
                # OFFLINE new/passive device with creds stays in `pending` so the passive-revert
                # loop removes/restores it when it reconnects (it handles is_new removal).
                #
                # BUT only if it ACTUALLY received the forward change: a passive device that
                # stayed offline the whole run and never reconnected was never configured
                # (`passive_ctrl["configured"]`), so there is NOTHING to revert on it. Excluding
                # it stops the passive-revert loop from waiting forever for a device that doesn't
                # need reverting at all — the undo can then complete and restore the graph (#3).
                passive_ids = self.s.get("passive_devices", set())
                with passive_ctrl["lock"]:
                    fwd_done = set(passive_ctrl.get("configured", set()))
                with self._devices_lock:
                    pending = {d.device_id for d in self.s["devices"]
                               if not d.is_local and d.device_id in passive_ids
                               and d.device_id in fwd_done
                               and d.device_id not in reverted_ok}

                # All topology-graph mutations happen on the Tk main thread (via _post): the
                # Topology poll reconciles the SAME self.s["topology"] object in its ui() on
                # the main thread, so mutating it from this worker thread would race (and could
                # raise "dict changed size during iteration" or lose the node removal).
                def _apply_graph_revert():
                    if not r_topo:
                        return
                    if removed_new_ok:
                        _rm = self.s.setdefault("topology_removed", set())
                        _rm |= removed_new_ok
                        # User-added devices we successfully removed disappear from the GUI
                        # entirely (Topología + Dispositivos) and from the saved snapshot, so
                        # they don't resurface as a dotted offline node on a later session.
                        with self._devices_lock:
                            self.s["devices"] = [d for d in self.s.get("devices", [])
                                                 if d.device_id not in removed_new_ok]
                        _snap_fid = snap["folder_id"]
                        try:
                            _snap = appconfig.load_topology_snapshot(_snap_fid)
                            _snap = _topology_from_json(_snap) if _snap else None
                            if _snap:
                                for _nid in removed_new_ok:
                                    _snap["nodes"].pop(_nid, None)
                                    _snap["edges"] = {e for e in _snap.get("edges", set())
                                                      if _nid not in e}
                                    _snap["edge_dir"] = {e: v for e, v in _snap.get("edge_dir", {}).items()
                                                         if _nid not in e}
                                appconfig.save_topology_snapshot(_snap_fid, _topology_to_json(_snap))
                        except Exception:
                            pass
                    _t = self.s.get("topology")
                    if not pending:
                        # Nothing left pending → restore the original graph wholesale, so
                        # reopening Topología shows the restored graph (not the stale edits).
                        # A reachable NEW node whose folder-removal FAILED is intentionally NOT
                        # re-added here: its folder still exists on the device, so the next
                        # build/reconcile of Topología re-discovers it from live state (as a
                        # normal, non-is_new member) — which also lets it be pruned later when
                        # the folder is finally removed. Re-adding it as an is_new node instead
                        # would freeze it (reconcile never prunes is_new nodes).
                        _to = self.s.get("topology_orig")
                        if _to:
                            self.s["topology"] = _copy_topology(_to)
                    elif _t and removed_new_ok:
                        # Other devices still pending → the _passive_explore(revert) worker
                        # thread reads self.s["topology"] concurrently, so mutate a COPY and
                        # swap the reference atomically (never mutate the live dict in place,
                        # which could raise "dict changed size during iteration" in that
                        # thread). Keep the edited graph minus the new nodes we just removed.
                        _t2 = _copy_topology(_t)
                        for _nid in removed_new_ok:
                            _t2["nodes"].pop(_nid, None)
                            _t2["edges"] = {e for e in _t2.get("edges", set()) if _nid not in e}
                            _t2["edge_dir"] = {e: v for e, v in _t2.get("edge_dir", {}).items()
                                               if _nid not in e}
                        self.s["topology"] = _t2

                def done():
                    _apply_graph_revert()
                    if btn.winfo_exists():
                        btn.config(state="disabled", text="✓ Revertido")
                    self._status("Revertido (selección aplicada)", "#2E7D32")

                if pending:
                    log_line(_T('  ⏳  {} dispositivo(s) pasivo(s) no revertidos ahora — se revertirán al reconectar (mantén la ventana abierta).').format(len(pending)), "warn")
                    threading.Thread(
                        target=lambda: _passive_explore(revert=revert_spec, only_ids=pending),
                        daemon=True).start()
                else:
                    self.s.pop("_undo", None)
                self._post(done)

            def work():
                # Never leave the button stuck on "Deshaciendo…": surface any unexpected
                # failure and re-enable it (the rename/topology revert calls could raise).
                try:
                    _work_impl()
                except Exception as e:
                    def _err(_e=e):
                        if btn.winfo_exists():
                            btn.config(state="normal", text="↶ Deshacer último rename")
                        self._status(_T('Error al deshacer: {}').format(_e), "#C62828")
                    self._post(_err)

            threading.Thread(target=work, daemon=True).start()

        def _passive_explore(revert: Optional[dict] = None,
                             only_ids: Optional[set] = None) -> None:
            """Background loop that configures passive devices when they reconnect.

            Forward mode (revert=None) applies the wizard's rename. Revert mode
            (revert=<undo snapshot>) restores the prior values on the devices in
            ``only_ids`` and pops self.s["_undo"] once they're all done (#46)."""
            import time as _time
            import dataclasses as _dc
            from ..renamer import rename_on_device as _ron, rename_folder_id as _rfi
            folder        = self.s["folder"]
            # Snapshot the shared passive set UNDER the lock — other threads .discard() from it,
            # so iterating the live set here (set(passive_ids)) can raise "set changed size".
            with self._devices_lock:
                passive_ids = set(self.s.get("passive_devices", set()))
            target_ids    = set(only_ids) if only_ids is not None else set(passive_ids)
            configured: set = set()

            # Target name/ID values: forward = wizard state; revert = snapshot's old values
            # (honoring the selective-undo flags carried in the revert spec, default all on).
            if revert:
                _r_id    = revert.get("revert_id", True) and bool(revert["rename_id"] and revert["new_folder_id"])
                _r_label = revert.get("revert_label", True)
                _r_path  = revert.get("revert_path", True) and not revert["skip_path"]
                tgt_label = revert["old_label"] if _r_label else revert.get("keep_label", self.s.get("new_label", ""))
                if _r_path:
                    tgt_skip, tgt_dir = revert["skip_path"], revert["old_dir_name"]
                else:
                    tgt_skip, tgt_dir = True, ""
                do_id = bool(_r_id)
                id_from, id_to = revert["new_folder_id"], revert["folder_id"]
                # id _ron must target on the device: old id if reverting it, else the id it holds now
                _revert_ron_fid = (revert["folder_id"] if _r_id
                                   else (revert["new_folder_id"] if revert["rename_id"] else revert["folder_id"]))
            else:
                tgt_label   = self.s["new_label"]
                tgt_skip    = self.s["skip_path"]
                path_input  = self.s["new_path_input"]
                tgt_dir     = path_input if not tgt_skip else (
                    Path(folder.path.rstrip("/\\")).name if folder.path else "")
                _nfid       = (self.s.get("new_folder_id") or "").strip()
                do_id       = bool(self.s.get("rename_id", False) and _nfid and _nfid != folder.id)
                id_from, id_to = folder.id, _nfid

            def _collect_hub_ips(devices) -> dict:
                """Ask every reachable hub (devices that are 'ok' with an api_key) which
                IPs they currently see, so a passive device that reconnects to a hub (e.g.
                the Pi) instead of to us is still detected. {device_id: ip}."""
                found: dict = {}
                for hub in devices:
                    if hub.is_local:  # local node's view already covered by conns/stats
                        continue
                    if _device_kind(hub) != "ok" or not hub.api_key:
                        continue
                    try:
                        if hub.api_reachable and hub.api_url:
                            hc = SyncthingClient(hub.api_url, hub.api_key, verify_ssl=False)
                            for did, ci in hc.get_connected_devices().items():
                                if ci.connected and ci.ip:
                                    found.setdefault(did, ci.ip)
                            for did, st in hc.get_device_stats().items():
                                if st.last_ip:
                                    found.setdefault(did, st.last_ip)
                        elif hub.ssh_reachable or hub.winrm_reachable:
                            from ..discovery import _api_port_from_url, _ip_from_syncthing_addr
                            api_port = _api_port_from_url(hub.api_url)
                            if hub.ssh_reachable:
                                from ..ssh_ops import SSHClient
                                with SSHClient(host=hub.ip, user=hub.ssh_user, key_path=hub.ssh_key_path,
                                               port=hub.ssh_port, password=hub.ssh_password) as _h:
                                    raw = _h.syncthing_api_get("/rest/system/connections", hub.api_key, api_port)
                            else:
                                from ..winrm_ops import WinRMClient
                                with WinRMClient(host=hub.ip, user=hub.winrm_user,
                                                 password=hub.winrm_password, port=hub.winrm_port) as _h:
                                    raw = _h.syncthing_api_get("/rest/system/connections", hub.api_key, api_port)
                            conns_raw = raw.get("connections", {}) if isinstance(raw, dict) else {}
                            for did, ci in conns_raw.items():
                                if isinstance(ci, dict) and ci.get("connected") and ci.get("address"):
                                    _ip = _ip_from_syncthing_addr(ci["address"])
                                    if _ip:
                                        found.setdefault(did, _ip)
                    except Exception:
                        continue
                return found

            while self._show_gen == exec_gen:
                if revert is None and passive_ctrl["reverting"]:
                    return  # an undo is in progress — stop applying forward changes
                with self._devices_lock:
                    devs = list(self.s["devices"])
                try:
                    conns = self.s["client"].get_connected_devices()
                except Exception:
                    conns = {}
                try:
                    stats = self.s["client"].get_device_stats()
                except Exception:
                    stats = {}

                _hub_ips = [None]  # per-sweep cache; queried lazily, at most once

                def _hub_ip(target_id):
                    if _hub_ips[0] is None:
                        _hub_ips[0] = _collect_hub_ips(devs)
                    return _hub_ips[0].get(target_id)

                for dev in devs:
                    if self._show_gen != exec_gen:
                        return
                    if revert is None and passive_ctrl["reverting"]:
                        return
                    if dev.is_local or dev.device_id in configured:
                        continue
                    if dev.device_id not in target_ids:  # only targeted devices
                        continue
                    # Forward mode skips devices already reachable (handled by the main
                    # run). Revert mode must still revert them, so it does NOT skip.
                    if revert is None and _device_kind(dev) == "ok":
                        configured.add(dev.device_id)
                        continue
                    has_ssh   = bool(dev.ssh_user or dev.ssh_key_path or dev.ssh_password)
                    has_winrm = bool(dev.winrm_user and dev.winrm_password)
                    has_api   = bool(dev.api_key and dev.api_url)
                    if not (has_ssh or has_winrm or has_api):
                        continue
                    ip = dev.ip
                    conn = conns.get(dev.device_id)
                    if conn and conn.connected and conn.ip:
                        ip = conn.ip
                    if not ip:
                        st = stats.get(dev.device_id)
                        if st and st.last_ip:
                            ip = st.last_ip
                    if not ip:
                        ip = _hub_ip(dev.device_id)  # ask reachable hubs (e.g. the Pi)
                    if not ip:
                        continue
                    try:
                        if has_ssh or has_winrm:
                            nd = probe_device(
                                device_id=dev.device_id, name=dev.name, ip=ip, folder_id=folder.id,
                                override={"ssh_user": dev.ssh_user, "ssh_key_path": dev.ssh_key_path,
                                          "ssh_password": dev.ssh_password, "ssh_port": dev.ssh_port,
                                          "winrm_user": dev.winrm_user, "winrm_password": dev.winrm_password,
                                          "winrm_port": dev.winrm_port})
                            nd = _dc.replace(nd, api_key=nd.api_key or dev.api_key,
                                             api_url=nd.api_url or dev.api_url,
                                             folder_path=nd.folder_path or dev.folder_path)
                        else:
                            # Rebuild the API URL with the device's CURRENT ip (it may
                            # have changed since discovery), keeping scheme + port.
                            _stored = dev.api_url or f"http://{ip}:8384"
                            _scheme = _stored.split("://")[0] if "://" in _stored else "http"
                            _m = re.search(r":(\d+)$", _stored.split("//")[-1].split("/")[0])
                            _api_url = f"{_scheme}://{ip}:{_m.group(1) if _m else '8384'}"
                            nd = probe_device_manual(
                                device_id=dev.device_id, name=dev.name, ip=ip, folder_id=folder.id,
                                api_key=dev.api_key, api_url=_api_url,
                                folder_path=dev.folder_path or "")
                    except Exception:
                        continue
                    if _device_kind(nd) != "ok":
                        continue  # still unreachable — keep waiting

                    verb = _T("revirtiendo") if revert else _T("configurando")
                    log_line(_T('⟳  {} en línea ({}) — {}…').format(dev.name, ip, verb), "info")
                    # A brand-new device (added in the topology editor) has NO pre-existing
                    # folder: FORWARD creates it / REVERT removes it in the topology step
                    # below — it must never go through the rename/ID pipeline (those target a
                    # folder id it doesn't have; in a revert WITH an ID-rename, renaming its
                    # folder back to the old id would make the later removal miss it, orphaning
                    # the folder while the undo reports success).
                    # Read is_new from the SAME graph the topology block uses below: the
                    # stable captured snapshot in revert (immune to concurrent purges), the
                    # live graph in forward.
                    _topo_c_now = ((revert.get("topo_cur_snap") if revert else None)
                                   or self.s.get("topology") or {"nodes": {}})
                    _is_new_dev = bool(_topo_c_now["nodes"].get(nd.device_id, {}).get("is_new"))
                    id_fail = ""
                    # Revert mode reverses the ID first (new → old) so the label/path
                    # rename below targets the restored (old) folder id.
                    if revert and do_id and not _is_new_dev:
                        idr = _rfi([nd], id_from, id_to, dry_run=False)
                        if idr and not idr[0][1]:
                            id_fail = _T(', ID falló: {}').format(idr[0][2])
                    _ron_fid = _revert_ron_fid if revert else folder.id
                    # Forward: honour this device's per-device path override (B4) — and a
                    # device with an override gets a real path change even under global skip.
                    # Revert always restores the original dir name (no override).
                    _ron_dir, _ron_skip = tgt_dir, tgt_skip
                    if revert is None:
                        _ov = self.s.get("path_overrides", {}).get(nd.device_id)
                        if _ov:
                            _ron_dir, _ron_skip = _ov, False
                    # New device (see above): skip the rename — forward creates / revert
                    # removes its folder in the topology step, gated by `_cfg_ready`.
                    if _is_new_dev:
                        _cfg_ready = True
                    else:
                        r = _ron(nd, _ron_fid, tgt_label, _ron_dir,
                                 dry_run=False, skip_path_rename=_ron_skip)
                        # `skipped_absent` = the folder isn't on this device yet (it's joining):
                        # there's nothing to rename, and the topology step below must CREATE it.
                        # Treat it as ready (like the is_new branch) — else this device would be
                        # logged "configurado por exploración pasiva" while the folder is never
                        # created (the direct + agent paths already let topology own creation).
                        _cfg_ready = r.config_updated or r.skipped_absent
                        # Refresh cached folder_path to where the directory ACTUALLY is now,
                        # so a later undo reverts the disk from the real location (same fix
                        # as the main flow — the discovered path goes stale once renamed).
                        if r.new_path:
                            nd.folder_path = r.new_path
                        # Itemize what was applied (label / path / ID).
                        changes = []
                        if r.config_updated:
                            changes.append(f"label→«{tgt_label}»")
                            if not tgt_skip:
                                changes.append(_T('ruta→«{}»').format(tgt_dir))
                        # Forward mode applies the ID rename AFTER label/path.
                        if revert is None and do_id and r.config_updated:
                            idr = _rfi([nd], id_from, id_to, dry_run=False)
                            if idr and idr[0][1]:
                                changes.append(f"ID→«{id_to}»")
                            elif idr:
                                id_fail = _T(', ID falló: {}').format(idr[0][2])
                        elif revert and do_id and not id_fail:
                            changes.append(f"ID→«{id_to}»")
                        suffix = " revertidos" if revert else ""
                        detail = (" (" + ", ".join(changes) + suffix + ")") if changes else ""
                        action = "revertido" if revert else "configurado"
                        if r.success:
                            log_line(_T('  ✓  {} {} por exploración pasiva{}{}').format(dev.name, action, detail, id_fail), "ok")
                        elif r.left_paused:
                            log_line(f"  ⚠  {dev.name} — sync PAUSADA: {r.error}{detail}{id_fail}", "err")
                        else:
                            log_line(f"  ⚠  {dev.name} — {r.error or 'parcial'}{detail}{id_fail}", "warn")

                    # Apply topology to this device too, editing its config directly
                    # so it needs no accept. Forward = target graph; revert = orig graph
                    # (or remove the folder for a device that was new). (#topology)
                    # REVERT reads STABLE snapshots captured at undo time (not the live graph):
                    # purges of already-reverted new nodes mutate self.s["topology"], and using
                    # the live graph here would let those mutations suppress the revert of a
                    # neighbour that reconnects later. The snapshots are absent ONLY when there
                    # was no topology delta to revert — in that case we leave them None so the
                    # gate below is False (never fall back to the live graph, and never reach
                    # the diff=None full-rewrite path). FORWARD keeps reading live (it applies
                    # the user's ongoing edits).
                    if revert:
                        _topo_o = revert.get("topo_orig_snap")
                        _topo_c = revert.get("topo_cur_snap")
                    else:
                        _topo_o = self.s.get("topology_orig")
                        _topo_c = self.s.get("topology")
                    _do_topo = (revert is None) or revert.get("revert_topo", True)
                    _purged_new_now = False
                    if _do_topo and _cfg_ready and _topo_o \
                            and _topology_delta(_topo_o, _topo_c).get("any"):
                        from ..renamer import (apply_topology_on_device as _atod,
                                              remove_folder_on_device as _rfod,
                                              compute_topology_diff as _ctd3,
                                              prune_orphan_device_entries as _rprune)
                        if revert is None:
                            if _topo_c["nodes"].get(nd.device_id):
                                # Forward: apply ONLY the user's diff, MERGED onto the
                                # device's current config (non-destructive) — make it clear
                                # that a device reconnecting keeps the rest of its config.
                                _pdiff = _ctd3(_topo_o, _topo_c,
                                               locked=self.s.get("topology_locked"))
                                log_line(_T('  ↻  «{}» reconectó: aplico tus cambios sobre su configuración actual (fusión, sin borrar lo demás).').format(nd.name), "dim")
                                _tr = _atod(nd, id_to if do_id else folder.id, _topo_c,
                                            diff=_pdiff, folder_label=tgt_label, dry_run=False)
                                log_line(_T('  {}  {} (topología) — {}').format('✓' if _tr.ok else '⚠', nd.name, _tr.message),
                                         "ok" if _tr.ok else "warn")
                                # If this reconnect finished unsharing an ORPHANED node (its last
                                # link was removed while it was offline), forget it from the graph
                                # + snapshot so it doesn't resurrect as a ghost — but KEEP it in
                                # the devices list (it's a real, credentialed device that may
                                # share other folders; only THIS folder is unshared).
                                if _tr.ok and nd.device_id in _pdiff.get("orphaned", set()):
                                    self._post(lambda _i=nd.device_id, _fi=folder.id:
                                               self._purge_reverted_new_nodes(_fi, {_i},
                                                                              keep_devices=True))
                        else:
                            _new_ids = {x for x, n in _topo_c["nodes"].items() if n.get("is_new")}
                            if nd.device_id in _new_ids:
                                _fwd = revert["new_folder_id"] if (revert["rename_id"]
                                        and revert["new_folder_id"]) else revert["folder_id"]
                                _tr = _rfod(nd, _fwd)
                                log_line(f"  {'✓' if _tr.ok else '⚠'}  {nd.name} (nuevo) — {_tr.message}",
                                         "ok" if _tr.ok else "warn")
                                # Offline new device reverted on reconnect: its folder is gone,
                                # so purge it fully from the GUI (graph + devices + snapshot +
                                # topology_removed) on the main thread — the reachable path does
                                # this in _apply_graph_revert; this branch used to only remove the
                                # folder, leaving the node lingering and resurrecting next session.
                                if _tr.ok:
                                    _purged_new_now = True
                                    self._post(lambda _i=nd.device_id, _fi=revert["folder_id"]:
                                               self._purge_reverted_new_nodes(_fi, {_i}))
                            elif _topo_o["nodes"].get(nd.device_id):
                                # Use the SAME non-destructive inverse diff the reachable undo
                                # path uses (work() line ~926), not a diff=None full membership
                                # rewrite — the latter would clobber peers the user added
                                # outside this edit. Captured at undo time, so it's stable.
                                _tr = _atod(nd, _revert_ron_fid, _topo_o,
                                            diff=revert.get("rev_diff"),
                                            folder_label=tgt_label, dry_run=False)
                                log_line(_T('  {}  {} (topología) — {}').format('✓' if _tr.ok else '⚠', nd.name, _tr.message),
                                         "ok" if _tr.ok else "warn")
                                # Mirror the reachable path (work() B2): drop the just-unlinked
                                # peers from THIS device's GLOBAL device list — but ONLY if the
                                # peer no longer shares this (or any other) folder. _rprune
                                # re-reads the device's folders AFTER the revert above removed
                                # the membership, so a peer still sharing a folder is kept.
                                _rev_removed = {o for e in (revert.get("rev_diff") or {}).get("links_removed", set())
                                                if nd.device_id in e for o in (e - {nd.device_id})}
                                for _pid, _pok, _pmsg in _rprune(nd, _rev_removed):
                                    if _pok:
                                        log_line(_T('     · {}: dispositivo «{}» {}').format(nd.name, _pid[:7], _pmsg), "dim")

                    # Advanced folder-config queued for this device (#55) → apply now that it
                    # reconnected (forward only).
                    if revert is None:
                        # Read/pop fcfg_pending under the lock (the main-thread Avanzado dialog
                        # mutates it); do the network apply OUTSIDE the lock.
                        with self._devices_lock:
                            _fov = self.s.get("fcfg_pending", {}).get(nd.device_id)
                        if _fov:
                            from ..renamer import apply_folder_cfg_on_device as _afc
                            _fr = _afc(nd, id_to if do_id else folder.id, _fov, dry_run=False)
                            log_line(_T('  {}  {} (config carpeta) — {}').format('✓' if _fr.ok else '⚠', nd.name, _fr.message),
                                     "ok" if _fr.ok else "warn")
                            if _fr.ok:
                                with self._devices_lock:
                                    self.s.get("fcfg_pending", {}).pop(nd.device_id, None)

                    # Canonical device-names queued for offline equipos (#item1) → apply now
                    # that this one reconnected (write peer names into its config).
                    if revert is None:
                        with self._devices_lock:   # snapshot (main thread may be writing it)
                            _nc = dict(self.s.get("names_canonical") or {})
                        if _nc:
                            from ..device_names import sync_device_names as _sdn
                            try:
                                _sdn(self.s["client"], [nd], _nc)
                                log_line(f"  ✓  {nd.name} (nombres) — aplicados al reconectar", "ok")
                            except Exception as _e:
                                log_line(f"  ⚠  {nd.name} (nombres) — {_e}", "warn")

                    # Skip the device-list update when we just purged this node (the posted
                    # _purge_reverted_new_nodes rebuilds self.s["devices"]; writing back by a
                    # now-stale index here would clobber the wrong row or re-add the device).
                    if not _purged_new_now:
                        with self._devices_lock:
                            for i, d in enumerate(self.s["devices"]):
                                if d.device_id == nd.device_id:
                                    self.s["devices"][i] = nd
                                    break
                    self._post(lambda d=nd: None)  # row refresh handled by discover page on re-entry
                    configured.add(dev.device_id)
                    if revert is None:
                        with passive_ctrl["lock"]:
                            passive_ctrl["configured"].add(dev.device_id)
                        # Now configured DIRECTLY → drop it from the passive/agent queues so it
                        # isn't still treated as passive/agent for the rest of the session
                        # (same invariant the main run enforces on reachable devices).
                        with self._devices_lock:
                            self.s.get("passive_devices", set()).discard(dev.device_id)
                            self.s["agent_devices"] = [a for a in self.s.get("agent_devices", [])
                                                       if a.device_id != dev.device_id]

                # Revert mode: once every targeted device is restored, drop the undo
                # snapshot and stop the loop (#46).
                if revert and target_ids and configured >= target_ids:
                    self.s.pop("_undo", None)
                    # Every targeted device restored → make the in-memory graph match the
                    # reverted state (mirrors the reachable no-pending path in
                    # _apply_graph_revert), so Topología shows the restored original graph
                    # instead of the stale edits once the passive revert finishes. New nodes
                    # were already purged individually above. Done on the Tk main thread.
                    if revert.get("revert_topo", True):
                        _to = self.s.get("topology_orig")
                        if _to:
                            self._post(lambda _t=_to: self.s.__setitem__(
                                "topology", _copy_topology(_t)))
                    log_line(_T("  ✓  Reversión pasiva completada."), "ok")
                    return

                for _ in range(20):  # ~20s between sweeps, responsive to navigation
                    if self._show_gen != exec_gen:
                        return
                    if revert is None and passive_ctrl["reverting"]:
                        return
                    if passive_ctrl["wake"].is_set():  # force-discovery requested
                        passive_ctrl["wake"].clear()
                        break
                    _time.sleep(1)

        def _edit_passive_creds(dev, on_save=None) -> None:
            """Compact credential editor for a passive device (#47). Writes back to
            self.s["devices"] and wakes the passive sweep so new creds apply at once."""
            import dataclasses as _dc
            dlg = tk.Toplevel(self)
            dlg.title(_T('Credenciales — {}').format(dev.name))
            dlg.configure(bg="white")
            dlg.grab_set()
            tk.Label(dlg, text=_T('Editar credenciales: {}').format(dev.name), bg="white",
                     font=(_FONT, 10, "bold")).pack(anchor="w", padx=14, pady=(12, 6))
            grid = tk.Frame(dlg, bg="white")
            grid.pack(fill=tk.X, padx=14)
            rows = [
                ("IP / Host:",        "ip",            dev.ip or "",            False),
                ("Puerto SSH:",       "ssh_port",      str(dev.ssh_port),       False),
                ("Usuario SSH:",      "ssh_user",      dev.ssh_user or "",      False),
                ("Clave privada SSH:", "ssh_key",      dev.ssh_key_path or "",  False),
                ("Contraseña SSH:",   "ssh_password",  dev.ssh_password or "",  True),
                ("Usuario WinRM:",    "winrm_user",    dev.winrm_user or "",    False),
                ("Contraseña WinRM:", "winrm_password", dev.winrm_password or "", True),
                ("Puerto WinRM:",     "winrm_port",    str(dev.winrm_port),     False),
                ("URL API:",          "api_url",       dev.api_url or "http://127.0.0.1:8384", False),
                ("API Key:",          "api_key",       dev.api_key or "",       True),
            ]
            fields: dict = {}
            for i, (lbl, key, val, secret) in enumerate(rows):
                tk.Label(grid, text=lbl, bg="white", anchor="e", width=18).grid(
                    row=i, column=0, sticky="e", pady=2)
                v = tk.StringVar(value=val)
                ttk.Entry(grid, textvariable=v, width=34,
                          show="●" if secret else "").grid(
                    row=i, column=1, sticky="w", padx=(8, 0), pady=2)
                if key == "ssh_key":   # «…» examinar la clave privada
                    ttk.Button(grid, text="…", width=3,
                               command=lambda vv=v: vv.set(
                                   filedialog.askopenfilename(title="Clave SSH privada")
                                   or vv.get())
                               ).grid(row=i, column=2, sticky="w", padx=(4, 0))
                fields[key] = v

            def save():
                vals = {k: v.get().strip() for k, v in fields.items()}
                try:
                    ssh_port = int(vals["ssh_port"] or "22")
                except ValueError:
                    ssh_port = 22
                try:
                    winrm_port = int(vals["winrm_port"] or "5985")
                except ValueError:
                    winrm_port = 5985
                with self._devices_lock:
                    for i, d in enumerate(self.s["devices"]):
                        if d.device_id == dev.device_id:
                            self.s["devices"][i] = _dc.replace(
                                d, ip=vals["ip"] or d.ip,
                                ssh_user=vals["ssh_user"] or None,
                                ssh_key_path=vals["ssh_key"] or None,
                                ssh_password=vals["ssh_password"] or None,
                                ssh_port=ssh_port,
                                winrm_user=vals["winrm_user"] or None,
                                winrm_password=vals["winrm_password"] or None,
                                winrm_port=winrm_port,
                                api_url=vals["api_url"] or d.api_url,
                                api_key=vals["api_key"] or d.api_key,
                                # creds changed → let the next sweep re-probe reachability
                                api_reachable=False, ssh_reachable=False, winrm_reachable=False)
                            break
                passive_ctrl["wake"].set()  # apply on the next (immediate) sweep
                dlg.destroy()
                if on_save:
                    on_save()

            btnf = tk.Frame(dlg, bg="white")
            btnf.pack(fill=tk.X, padx=14, pady=12)
            ttk.Button(btnf, text="Guardar", command=save).pack(side=tk.RIGHT)
            ttk.Button(btnf, text="Cancelar", command=dlg.destroy).pack(side=tk.RIGHT, padx=(0, 6))
            dlg.bind("<Return>", lambda e: save())

        def _open_passive_status() -> None:
            """Live status window for passive devices: queue/configured state,
            per-device credential editing, and a force-discovery button (#47)."""
            passive_ids = self.s.get("passive_devices", set())
            win = tk.Toplevel(self)
            win.title("Exploración pasiva")
            win.configure(bg="white")
            if _IS_WIN:
                win.geometry(f"{min(660, self._win_w)}x{min(460, self._win_h)}")
            win.transient(self)

            tk.Label(win, text="Estado de exploración pasiva", bg="white",
                     font=(_FONT, 10, "bold")).pack(anchor="w", padx=14, pady=(12, 2))
            tk.Label(win, text=("Los dispositivos sin acceso se configuran solos al conectarse "
                                "mientras esta ventana siga abierta. Edita credenciales o fuerza "
                                "un barrido inmediato."),
                     bg="white", fg="#888", font=(_FONT, 8), justify="left",
                     wraplength=620).pack(anchor="w", padx=14, pady=(0, 8))
            ttk.Separator(win, orient="horizontal").pack(fill=tk.X, padx=14)

            body = tk.Frame(win, bg="white")
            body.pack(fill=tk.BOTH, expand=True, padx=14, pady=8)

            def _has_cred(d):
                return bool(d.api_key or d.ssh_user or d.ssh_key_path or d.ssh_password
                            or (d.winrm_user and d.winrm_password))

            def render():
                if not win.winfo_exists():
                    return
                for w in body.winfo_children():
                    w.destroy()
                with self._devices_lock:
                    devs = [d for d in self.s["devices"]
                            if not d.is_local and d.device_id in passive_ids]
                # Snapshot the configured set once under its lock (the forward passive thread
                # .add()s to it) so the per-row membership test below can't race that add.
                with passive_ctrl["lock"]:
                    _configured = set(passive_ctrl["configured"])
                if not devs:
                    tk.Label(body, text="No hay dispositivos marcados para exploración pasiva.",
                             bg="white", fg="#888", font=(_FONT, 9)).pack(anchor="w")
                for d in devs:
                    kind = _device_kind(d)
                    done = d.device_id in _configured
                    if done:
                        st, fg = "✓ configurado", "#2E7D32"
                    elif kind == "ok":
                        st, fg = "● accesible", "#1565C0"
                    elif _has_cred(d):
                        st, fg = "… en cola (esperando conexión)", "#C66000"
                    else:
                        st, fg = "✗ sin credenciales", "#C62828"
                    row = tk.Frame(body, bg="white")
                    row.pack(fill=tk.X, pady=2)
                    tk.Label(row, text=d.name, bg="white", font=(_FONT, 9, "bold"),
                             width=18, anchor="w").pack(side=tk.LEFT)
                    tk.Label(row, text=d.ip or "—", bg="white", fg="#555",
                             font=(_FONT, 8), width=16, anchor="w").pack(side=tk.LEFT)
                    tk.Label(row, text=st, bg="white", fg=fg, font=(_FONT, 8),
                             width=26, anchor="w").pack(side=tk.LEFT)
                    ttk.Button(row, text="Editar credenciales",
                               command=lambda dd=d: _edit_passive_creds(dd, render)).pack(side=tk.RIGHT)
                win.after(2500, render)

            render()

            ttk.Separator(win, orient="horizontal").pack(fill=tk.X, padx=14)
            btnf = tk.Frame(win, bg="white")
            btnf.pack(fill=tk.X, padx=14, pady=10)

            def _force():
                passive_ctrl["wake"].set()
                self._status("Forzando descubrimiento pasivo…", "#1565C0")
            ttk.Button(btnf, text="🔎 Forzar descubrimiento ahora",
                       command=_force).pack(side=tk.LEFT)
            ttk.Button(btnf, text="Cerrar", command=win.destroy).pack(side=tk.RIGHT)

        def _retry_failed(failed_results, btn) -> None:
            """Re-run the rename on the devices that failed (e.g. the folder was momentarily
            in use). Additive: passive exploration and agent generation keep working."""
            btn.config(state="disabled", text="Reintentando…")
            folder     = self.s["folder"]
            new_label  = self.s["new_label"]
            path_input = self.s["new_path_input"]
            skip_path  = self.s["skip_path"]
            devs = [r.device for r in failed_results]

            def _work_impl():
                from ..renamer import rename_all_devices as _rad
                log_line("", "dim")
                log_line(_T('── Reintentando {} dispositivo(s) ──').format(len(devs)), "warn")
                new_dir = (path_input if not skip_path
                           else (Path(folder.path.rstrip("/\\")).name if folder.path else ""))
                res = _rad(devices=devs, folder_id=folder.id, new_label=new_label,
                           new_dir_name=new_dir, dry_run=False, skip_path_rename=skip_path,
                           path_overrides=self.s.get("path_overrides"))
                n_ok = 0
                for r in res:
                    if r.success:
                        n_ok += 1
                        if r.new_path:
                            r.device.folder_path = r.new_path
                    log_line(f"  {'✓' if r.success else '✗'}  {r.device.name} — "
                             f"{'OK' if r.success else (r.error or 'parcial')}",
                             "ok" if r.success else "err")

                def done():
                    still = len(devs) - n_ok
                    if btn.winfo_exists():
                        if still:
                            btn.config(state="normal", text=f"↺ Reintentar ahora ({still})")
                        else:
                            btn.config(state="disabled", text="✓ Reintentado")
                    self._status(f"Reintento: {n_ok}/{len(devs)} OK",
                                 "#2E7D32" if n_ok == len(devs) else "#C66000")
                    # Refresh undo snapshot if this retry produced the first successes.
                    if n_ok and not self.s.get("_undo"):
                        rid = self.s.get("rename_id", False)
                        nfid = self.s.get("new_folder_id", "").strip()
                        self.s["_undo"] = {
                            "folder_id": folder.id, "old_label": folder.label or folder.id,
                            "old_dir_name": Path(folder.path.rstrip("/\\")).name if folder.path else "",
                            "skip_path": skip_path,
                            "rename_id": bool(rid and nfid and nfid != folder.id),
                            "new_folder_id": nfid,
                            "is_new_folder": bool(self.s.get("folder_is_new"))}
                self._post(done)

            def work():
                # Never leave the button stuck on "Reintentando…": surface any unexpected
                # failure and re-enable it (rename_all_devices could raise).
                try:
                    _work_impl()
                except Exception as e:
                    def _err(_e=e):
                        if btn.winfo_exists():
                            btn.config(state="normal",
                                       text=f"↺ Reintentar ahora ({len(devs)})")
                        self._status(_T('Error al reintentar: {}').format(_e), "#C62828")
                    self._post(_err)

            threading.Thread(target=work, daemon=True).start()

        def _show_final_actions(results, id_results, paused_results) -> None:
            # Shrink the log's requested height so the action bar / notice / footer
            # stay visible on short windows; it still expands on taller ones.
            log.configure(height=6)

            bar = tk.Frame(f, bg="white")
            bar.pack(fill=tk.X, pady=(6, 0))

            if not dry and self.s.get("_undo"):
                undo_btn = ttk.Button(bar, text="↶ Deshacer último rename")
                undo_btn.config(command=lambda b=undo_btn: _undo_last(b))
                undo_btn.pack(side=tk.LEFT)

            if paused_results:
                rb = ttk.Button(bar, text=f"▶ Reanudar {len(paused_results)} pausada(s)")
                rb.config(command=lambda b=rb: _resume_paused(paused_results, b))
                rb.pack(side=tk.LEFT, padx=(6, 0))

            # B5: genuine failures (e.g. local folder busy because a console/Explorer was
            # open in it) get a direct retry — additive, it does NOT stop passive/agents.
            failed_results = [r for r in results if not r.success and not r.left_paused]
            if not dry and failed_results:
                # «Reintentar ahora» = re-apply immediately. (They're also queued for passive
                # retry-on-reconnect, so doing nothing also eventually retries them.)
                fb = ttk.Button(bar, text=f"↺ Reintentar ahora ({len(failed_results)})")
                fb.config(command=lambda b=fb: _retry_failed(failed_results, b))
                fb.pack(side=tk.LEFT, padx=(6, 0))

            ttk.Button(bar, text="📄 Guardar informe",
                       command=lambda: _save_report(results)).pack(side=tk.LEFT, padx=(6, 0))

            if not dry and self.s.get("passive_devices"):
                ttk.Button(bar, text="🔎 Estado pasiva",
                           command=_open_passive_status).pack(side=tk.LEFT, padx=(6, 0))

            # Passive exploration of devices that are offline now but may come online
            # while this window stays open (and for which we have credentials).
            if not dry:
                passive_ids = self.s.get("passive_devices", set())

                def _hc(d):
                    return bool(d.api_key or d.ssh_user or d.ssh_key_path or d.ssh_password
                                or (d.winrm_user and d.winrm_password))

                with self._devices_lock:
                    passive = [d for d in self.s["devices"]
                               if not d.is_local and d.device_id in passive_ids
                               and _device_kind(d) != "ok"]
                cands   = [d for d in passive if _hc(d)]          # ready to auto-config
                no_cred = [d for d in passive if not _hc(d)]      # opted in but no creds

                if cands:
                    notice = tk.Frame(f, bg="#E3F2FD")
                    notice.pack(fill=tk.X, pady=(6, 0))
                    tk.Label(
                        notice,
                        text=(_T('🔎  Exploración pasiva activa — {} dispositivo(s) sin acceso se configurarán automáticamente si se conectan mientras esta ventana siga abierta. Puedes generar agentes arriba en cualquier momento.').format(len(cands))),
                        bg="#E3F2FD", fg="#1565C0", font=(_FONT, 8),
                        wraplength=self._win_w - 60, justify="left",
                    ).pack(anchor="w", padx=8, pady=4)
                    threading.Thread(target=_passive_explore, daemon=True).start()

                if no_cred:
                    hint = tk.Frame(f, bg="#FFF3E0")
                    hint.pack(fill=tk.X, pady=(6, 0))
                    tk.Label(
                        hint,
                        text=(_T('ℹ  {} dispositivo(s) marcados para exploración pasiva no tienen credenciales, así que no se auto-configurarán. Usa el agente, o vuelve a «Dispositivos» y añádeles credenciales.').format(len(no_cred))),
                        bg="#FFF3E0", fg="#C66000", font=(_FONT, 8),
                        wraplength=self._win_w - 60, justify="left",
                    ).pack(anchor="w", padx=8, pady=4)

        threading.Thread(target=run, daemon=True).start()
        self._next_handlers[5] = self.destroy
