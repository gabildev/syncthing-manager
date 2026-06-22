from __future__ import annotations
from .common import *  # noqa: F401,F403


def _hub_name_map(devs, folder_id: str) -> dict:
    """Names the reachable HUBS know for their folder peers → {deviceID: name}.

    The topology graph can show a peer that only appears via a hub's `folder_peers` (no
    DeviceInfo of its own — e.g. the user entered the hub's credentials in the Topology
    window, which never ran the Devices window's hub expansion). Its name lives in the
    HUB's config, not ours, so ask each reachable hub directly — the SAME resolution the
    Devices window uses. Network I/O: call only from a worker thread, never the UI thread.

    When two hubs disagree on a peer's name (and the LOCAL node hasn't named it — the local
    name wins earlier, in `_resolve_name_map`), the tie is broken DETERMINISTICALLY by hub
    device-id order (hubs are sorted, and the placeholder-aware merge below keeps the first
    REAL name), so the label doesn't flip between rebuilds just because concurrent discovery
    returned the hubs in a different order."""
    out: dict = {}
    for hub in sorted((devs or []), key=lambda h: getattr(h, "device_id", "")):
        if getattr(hub, "is_local", False) or not getattr(hub, "api_key", None):
            continue  # expansion (like discovery's) needs the hub's API key
        try:
            if hub.api_reachable and hub.api_url:
                revealed = _query_hub_devices(hub, folder_id, set(), [])
            elif hub.ssh_reachable or hub.winrm_reachable:
                revealed = _query_hub_devices_via_remote(hub, folder_id, set(), [])
            else:
                revealed = []
        except Exception:
            revealed = []
        for hid, hname, _ip, _ov in revealed:
            if not hid or not hname:
                continue
            # Placeholder-aware merge: a REAL name from any hub must win over the short-id
            # one hub falls back to when it has no name for the peer — plain setdefault would
            # let a lower-device-id hub's placeholder block a higher one's real name. Among
            # real (or among placeholder) names the lowest device-id hub wins (sorted above) →
            # deterministic.
            cur = out.get(hid)
            if cur is None or (_name_is_placeholder(cur, hid) and not _name_is_placeholder(hname, hid)):
                out[hid] = hname
    return out


class TopologyPageMixin:
    def _page_topology(self, f: tk.Frame):
        import math
        folder: FolderConfig = self.s["folder"]

        tk.Label(f, text="Topología", bg="white",
                 font=(_FONT, 11, "bold")).pack(anchor="w")
        ttk.Separator(f, orient="horizontal").pack(fill=tk.X, pady=(6, 4))
        _help_lbl = tk.Label(f, text=("Grafo real de la carpeta. ✋ Mover (arrastra nodos) · 🔗 Añadir enlace "
                          "(clic en 2 nodos) · ✂ Borrar enlace (clic en la línea). "
                          "Doble clic o clic derecho en un nodo o flecha = opciones. "
                          "Editas la DIRECCIÓN del enlace; el rol (envía/recibe…) se deriva y es "
                          "solo-lectura. Flecha sin punta = equipo offline (dirección desconocida); "
                          "roja = no sincroniza. Rueda/🔍 = zoom · arrastra zona vacía = desplazar · "
                          "⊡ Ajustar encuadra · 🔄 Estado refresca · ↶/↷ (Ctrl+Z/Y) deshacer/rehacer."),
                 bg="white", fg="#888", font=(_FONT, 8), justify="left",
                 wraplength=self._win_w - 40)
        _help_lbl.pack(anchor="w", fill=tk.X, pady=(0, 4))
        # Re-wrap to the ACTUAL page width on every resize: a fixed wraplength (set once at the
        # initial window width) left a ragged right edge / looked "descuadrado" once the window
        # was wider/maximised. Update only this label; bound on the page frame (add=+ so it
        # never clobbers the canvas's own <Configure> handler).
        def _rewrap_help(_e):
            w = max(200, f.winfo_width() - 24)
            if abs(w - int(_help_lbl.cget("wraplength"))) > 8:
                _help_lbl.config(wraplength=w)
        f.bind("<Configure>", _rewrap_help, add="+")

        # Two toolbar rows so all buttons fit in narrow/windowed mode (else they overflow
        # the window width and clip — taking the Back/Next footer with them).
        # Row 1: add device + tool palette (Move / Connect / Delete-link).
        toolbar = tk.Frame(f, bg="white")
        toolbar.pack(fill=tk.X, pady=(0, 2))
        ttk.Button(toolbar, text="➕ Nuevo dispositivo",
                   command=lambda: _add_device_dialog()).pack(side=tk.LEFT)
        ttk.Separator(toolbar, orient="vertical").pack(side=tk.LEFT, fill=tk.Y, padx=8)
        mode_btns: dict = {}
        for _m, _txt in (("move", "✋ Seleccionar/Mover"), ("connect", "🔗 Añadir enlace"),
                         ("delete", "✂ Borrar enlace")):
            b = tk.Button(toolbar, text=_txt, font=(_FONT, 8), relief="raised",
                          command=(lambda m=_m: _set_mode(m)))
            b.pack(side=tk.LEFT, padx=(0, 4))
            mode_btns[_m] = b
        # Zoom controls (right side of row 1). Drag empty space to pan; wheel zooms.
        ttk.Button(toolbar, text="⊡ Ajustar",
                   command=lambda: (_fit_view(set_auto=True), _render())).pack(side=tk.RIGHT)
        tk.Button(toolbar, text="🔍+", font=(_FONT, 9), relief="raised", width=3,
                  command=lambda: _zoom_to(view["zoom"] * 1.2)).pack(side=tk.RIGHT, padx=(0, 4))
        tk.Button(toolbar, text="🔍−", font=(_FONT, 9), relief="raised", width=3,
                  command=lambda: _zoom_to(view["zoom"] / 1.2)).pack(side=tk.RIGHT, padx=(0, 2))
        # Row 2: actions on the selection / graph. (Editing a node/link is done by double-click
        # or right-click on it — no separate "edit selected" button needed.)
        toolbar2 = tk.Frame(f, bg="white")
        toolbar2.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(toolbar2, text="✨ Auto-organizar",
                   command=lambda: (_layout_circle(force=True), _fit_view(set_auto=True), _render())
                   ).pack(side=tk.LEFT)
        undo_btns: dict = {}
        undo_btns["undo"] = tk.Button(toolbar2, text="↶ Deshacer", font=(_FONT, 8),
                                      relief="raised", command=lambda: _undo())
        undo_btns["undo"].pack(side=tk.LEFT, padx=(8, 0))
        undo_btns["redo"] = tk.Button(toolbar2, text="↷ Rehacer", font=(_FONT, 8),
                                      relief="raised", command=lambda: _redo())
        undo_btns["redo"].pack(side=tk.LEFT, padx=(2, 0))
        ttk.Button(toolbar2, text="⚠ Revisar",
                   command=lambda: _check_issues()).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(toolbar2, text="🔄 Estado",
                   command=lambda: _refresh_status(quiet=False)).pack(side=tk.LEFT, padx=(8, 0))
        # Row 3: incoming requests + the destructive cluster delete on their own line, so the
        # (wide) red button is never clipped in narrow/windowed mode.
        toolbar3 = tk.Frame(f, bg="white")
        toolbar3.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(toolbar3, text="📥 Peticiones entrantes…",
                   command=lambda: _show_pending_dialog()).pack(side=tk.LEFT)
        # DESTRUCTIVE cluster-wide delete (advanced only). The button is HIDDEN unless every
        # member can be wiped on disk (local or SSH/WinRM, non-protected path) — never just
        # disabled — so it can't be triggered on a cluster that can't complete it.
        _cluster_del = {"btn": None}
        if self.s.get("advanced"):
            _cluster_del["btn"] = tk.Button(
                toolbar3, text="🗑 Borrar la carpeta en TODO el clúster",
                font=(_FONT, 8), relief="raised", fg="white", bg="#C62828",
                activebackground="#B71C1C", activeforeground="white",
                command=lambda: _delete_folder_cluster())

        def _cluster_all_deletable():
            t = topo()
            if not t or not t["nodes"]:
                return False
            from ..renamer import is_protected_delete_path
            with self._devices_lock:
                dm = {d.device_id: d for d in self.s.get("devices", [])}
            for nid in t["nodes"]:
                d = dm.get(nid)
                if not d or not (d.is_local or d.ssh_reachable or d.winrm_reachable):
                    return False
                if d.folder_path and is_protected_delete_path(d.folder_path, d.os_type):
                    return False
            return True

        def _refresh_cluster_delete_btn():
            btn = _cluster_del["btn"]
            if not btn or not btn.winfo_exists():
                return
            if _cluster_all_deletable():
                if not btn.winfo_ismapped():
                    btn.pack(side=tk.LEFT, padx=(16, 0))
            elif btn.winfo_ismapped():
                btn.pack_forget()

        # Status/help line BELOW the toolbar, right-aligned. In windowed/narrow mode the
        # toolbar buttons would otherwise push this off the right edge and hide it.
        statusbar = tk.Frame(f, bg="white")
        statusbar.pack(fill=tk.X, pady=(2, 0))
        # Always-visible inconsistency counter (updated on every render; click → details). On the
        # dedicated status line, NOT crammed into the legend chip row where it got clipped to "…ve"
        # in a narrow window. Packed BEFORE status_lbl so it claims its space first — a long status
        # message (which wraps near full width) then clips instead of this actionable counter.
        issues_lbl = tk.Label(statusbar, text="", bg="white", fg="#C62828",
                              font=(_FONT, 8, "bold"), cursor="hand2")
        # Pending-changes reminder in a calm INFO blue (NOT red): unapplied edits are an action
        # prompt ("press Next →"), not an error. Packed FIRST (leftmost); the inconsistency counter
        # sits to its RIGHT. Its own label so its colour stays independent of the counter.
        pending_lbl = tk.Label(statusbar, text="", bg="white", fg="#1565C0", font=(_FONT, 8))
        pending_lbl.pack(side=tk.LEFT, padx=(6, 4))
        issues_lbl.pack(side=tk.LEFT, padx=(0, 4))
        issues_lbl.bind("<Button-1>", lambda _e: _check_issues())
        status_lbl = tk.Label(statusbar, text="", bg="white", fg="#1565C0",
                              font=(_FONT, 8), anchor="e", justify="right",
                              wraplength=self._win_w - 40)
        status_lbl.pack(side=tk.RIGHT, padx=(0, 6))

        # Legend: node colour = network state; dashed/no-arrow = unknown link direction.
        # Two stacked rows so the legend never overflows (and clips) a narrow window — the
        # single-row layout cut off the rightmost items (rosa/ámbar) when the window shrank.
        legend = tk.Frame(f, bg="white")
        legend.pack(fill=tk.X)
        legend_r1 = tk.Frame(legend, bg="white")
        legend_r1.pack(fill=tk.X)
        legend_r2 = tk.Frame(legend, bg="white")
        legend_r2.pack(fill=tk.X)

        def _legend_chip(color, text):
            chip = tk.Frame(legend_r1, bg="white")
            chip.pack(side=tk.LEFT, padx=(0, 10))
            tk.Label(chip, text="■", bg="white", fg=color, font=(_FONT, 8)).pack(side=tk.LEFT)
            tk.Label(chip, text=text, bg="white", fg="#666", font=(_FONT, 7)).pack(side=tk.LEFT)

        _legend_chip("#1565C0", "local")
        _legend_chip("#2E7D32", "conectado")
        _legend_chip("#C62828", "offline")
        tk.Label(legend_r1, text="–  sin punta = dirección desconocida (offline)",
                 bg="white", fg="#666", font=(_FONT, 7)).pack(side=tk.LEFT, padx=(4, 0))
        tk.Label(legend_r1, text="·· punteado = enlace recordado (offline, sesión anterior)",
                 bg="white", fg="#7E57C2", font=(_FONT, 7)).pack(side=tk.LEFT, padx=(4, 0))
        # Second row: the "halo" meanings (longer text) — kept off row 1 so neither row overflows.
        tk.Label(legend_r2, text="▭ negro (sólido) = se dejará de compartir al aplicar",
                 bg="white", fg="#212121", font=(_FONT, 7)).pack(side=tk.LEFT, padx=(0, 0))
        tk.Label(legend_r2, text="⬚ ámbar = sin confirmar (no se completó en una ejecución anterior)",
                 bg="white", fg="#F9A825", font=(_FONT, 7)).pack(side=tk.LEFT, padx=(12, 0))
        tk.Label(legend_r2, text="⬚ rojo = credenciales SSH no válidas",
                 bg="white", fg="#C62828", font=(_FONT, 7)).pack(side=tk.LEFT, padx=(12, 0))

        cv = tk.Canvas(f, bg="#FAFAFA", highlightthickness=1, highlightbackground="#CCC")
        cv.pack(fill=tk.BOTH, expand=True)

        NODE_W, NODE_H = 146, 60
        drag = {"id": None, "ox": 0.0, "oy": 0.0, "moved": False, "sx": 0, "sy": 0,
                "sel": None, "sel_edge": None, "click_after": None, "mode": "move",
                "panning": False, "px0": 0.0, "py0": 0.0, "new_kind": "bi"}
        # View transform: node positions are stored in WORLD coords; the canvas draws them
        # at screen = (world - pan) * zoom. Hit-testing converts the other way.
        # "auto": re-fit to the window on resize until the user manually zooms/pans.
        view = {"zoom": 1.0, "px": 0.0, "py": 0.0, "auto": True}

        def _to_screen(x, y):
            return (x - view["px"]) * view["zoom"], (y - view["py"]) * view["zoom"]

        def _to_world(sx, sy):
            return sx / view["zoom"] + view["px"], sy / view["zoom"] + view["py"]

        _MODE_HELP = {
            "move": "Seleccionar/Mover: clic en nodo o flecha = seleccionar · arrastrar = mover · doble clic / clic derecho = opciones.",
            "connect": "Modo Añadir enlace: clic en un dispositivo y luego en otro para crear el enlace.",
            "delete": "Modo Borrar enlace: clic sobre una línea para eliminar esa conexión.",
        }

        def _ask_link_kind():
            """Popup to choose the kind of link before drawing it (per the user's flow)."""
            dlg = tk.Toplevel(self)
            dlg.title("Nuevo enlace")
            dlg.configure(bg="white")
            dlg.grab_set()
            self._center_dialog(dlg)
            tk.Label(dlg, text="¿Qué tipo de enlace?", bg="white",
                     font=(_FONT, 10, "bold")).pack(padx=18, pady=(14, 4))
            tk.Label(dlg, text=("Unidireccional: pincha primero el ORIGEN y luego el DESTINO.\n"
                                "Bidireccional: pincha los dos nodos (orden indiferente)."),
                     bg="white", fg="#555", font=(_FONT, 8), justify="left").pack(padx=18)
            res = {"k": None}

            def pick(k):
                res["k"] = k
                dlg.destroy()
            bf = tk.Frame(dlg, bg="white")
            bf.pack(pady=14)
            ttk.Button(bf, text="→ Unidireccional", command=lambda: pick("uni")).pack(side=tk.LEFT, padx=6)
            ttk.Button(bf, text="↔ Bidireccional", command=lambda: pick("bi")).pack(side=tk.LEFT, padx=6)
            ttk.Button(bf, text="Cancelar", command=dlg.destroy).pack(side=tk.LEFT, padx=6)
            dlg.wait_window()
            return res["k"]

        def _set_mode(m, ask=True):
            # Entering "Añadir enlace" → ask uni/bi up front (per the user's flow).
            if m == "connect" and ask:
                kind = _ask_link_kind()
                if not kind:
                    return  # cancelled → stay in the current mode
                drag["new_kind"] = kind
            drag["mode"] = m
            drag["sel"] = None
            drag["sel_edge"] = None
            for k, b in mode_btns.items():
                b.config(relief="sunken" if k == m else "raised",
                         bg="#BBDEFB" if k == m else "#F0F0F0")
            if m == "connect":
                hint = ("clic en ORIGEN y luego DESTINO" if drag.get("new_kind") == "uni"
                        else "clic en los dos nodos (orden indiferente)")
                status_lbl.config(text=_T('Añadir enlace: {}.').format(hint))
            else:
                status_lbl.config(text=_MODE_HELP.get(m, ""))
            _render()

        def _apply_path(nid, node):
            """How this node will be configured on execute: local / directo / pasiva /
            agente / aceptar (manual)."""
            if node.get("is_local"):
                return "local"
            with self._devices_lock:
                d = next((x for x in self.s.get("devices", []) if x.device_id == nid), None)
                agent_ids = {x.device_id for x in self.s.get("agent_devices", [])}
            if d and _device_kind(d) == "ok":
                return "directo"
            has_creds = bool(d and (d.ssh_user or d.ssh_key_path or d.ssh_password
                                    or (d.winrm_user and d.winrm_password)
                                    or (d.api_key and d.api_url)))
            if has_creds:
                return "pasiva"
            if nid in agent_ids:
                return "agente"
            return "aceptar"

        def topo():
            return self.s.get("topology")

        def _node_at(x, y, exclude=None):
            t = topo()
            if not t:
                return None
            wx, wy = _to_world(x, y)   # event coords are screen → compare in world space
            for nid, n in t["nodes"].items():
                if nid == exclude or "x" not in n:
                    continue
                if abs(wx - n["x"]) <= NODE_W / 2 and abs(wy - n["y"]) <= NODE_H / 2:
                    return nid
            return None

        def _edge_at(x, y, tol=7):
            """Return the edge (frozenset) whose drawn segment is within `tol` px of
            (x,y), or None. Used by the ✂ delete-link tool."""
            t = topo()
            if not t:
                return None
            x, y = _to_world(x, y)        # event coords are screen → work in world space
            tol = tol / view["zoom"]
            best, best_d = None, tol + 1
            for e in t["edges"]:
                ids = sorted(e)
                if len(ids) < 2:
                    continue
                na, nb = t["nodes"].get(ids[0]), t["nodes"].get(ids[1])
                if not na or not nb or "x" not in na or "x" not in nb:
                    continue
                x1, y1, x2, y2 = na["x"], na["y"], nb["x"], nb["y"]
                dx, dy = x2 - x1, y2 - y1
                seg2 = dx * dx + dy * dy
                if seg2 == 0:
                    continue
                tt = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / seg2))
                px, py = x1 + tt * dx, y1 + tt * dy
                d = ((x - px) ** 2 + (y - py) ** 2) ** 0.5
                if d < best_d:
                    best, best_d = e, d
            return best

        _ARROW = {"both": tk.BOTH, "first": tk.FIRST, "last": tk.LAST, "none": tk.NONE}

        # Hover tooltip (delayed) for the ⚠ markers — explains the link problem only after
        # the mouse rests on it for a moment (not instantly).
        _tip = {"win": None, "after": None}

        def _hide_tip():
            if _tip["after"]:
                cv.after_cancel(_tip["after"]); _tip["after"] = None
            if _tip["win"]:
                _tip["win"].destroy(); _tip["win"] = None

        def _show_tip(text):
            if _tip["win"]:
                _tip["win"].destroy()
            w = tk.Toplevel(self)
            w.overrideredirect(True)
            try:
                w.attributes("-topmost", True)
            except Exception:
                pass
            tk.Label(w, text=text, bg="#333", fg="white", font=(_FONT, 8), justify="left",
                     padx=6, pady=3, wraplength=280).pack()
            w.geometry(f"+{self.winfo_pointerx() + 14}+{self.winfo_pointery() + 16}")
            _tip["win"] = w

        def _schedule_tip(text):
            _hide_tip()
            _tip["after"] = cv.after(650, lambda: _show_tip(text))

        def _clip_to_box(cx, cy, tx, ty):
            """Point where the segment (cx,cy)->(tx,ty) crosses the node's box border,
            so arrowheads land in the gap between boxes (not hidden under them)."""
            dx, dy = tx - cx, ty - cy
            if dx == 0 and dy == 0:
                return cx, cy
            hw, hh = NODE_W / 2 + 2, NODE_H / 2 + 2
            sx = hw / abs(dx) if dx else float("inf")
            sy = hh / abs(dy) if dy else float("inf")
            s = min(sx, sy)
            return cx + dx * s, cy + dy * s

        def _ssh_cred_problems(cur):
            """(device_id, label, error) for CURRENT members whose SSH credentials were verified
            and REJECTED (ssh_error set by probe). Such a device can't do a disk path-rename even
            when its API is reachable, so it's flagged in the preview BEFORE applying. Distinct
            from a device with NO SSH configured (api-only by design), which is not flagged here."""
            cur = cur or {"nodes": {}}
            out = []
            # Snapshot the device list (atomic copy under the GIL) — this runs on the main thread
            # inside _render while worker threads append/rebind self.s["devices"] under the lock;
            # a live `for d in self.s["devices"]` would raise "list changed size during iteration".
            for d in list(self.s.get("devices", [])):
                nid = d.device_id
                if not d.is_local and getattr(d, "ssh_creds_rejected", False) and nid in cur.get("nodes", {}):
                    out.append((nid, cur["nodes"][nid].get("label", nid[:7]), d.ssh_error))
            return out

        def _render():
            # A worker callback (unshare/unlink/delete/probe) can land here after the user
            # navigated away and the canvas was destroyed — drawing on it would raise TclError.
            if not cv.winfo_exists():
                return
            _hide_tip()
            _refresh_cluster_delete_btn()   # show/hide the cluster-delete button per capability
            cv.delete("all")
            t = topo()
            if not t:
                cv.create_text((cv.winfo_width() or 400) // 2, 30,
                               text="Cargando topología…", fill="#888", font=(_FONT, 9))
                return
            # Edges first (clipped to box borders so the arrowheads show). An edge whose
            # direction we can't know (an offline endpoint with unreadable role) is drawn
            # dashed and WITHOUT arrowheads, plus a ⚠ at its midpoint.
            z = view["zoom"]
            locked = self.s.get("topology_locked", set())
            sel_e = drag.get("sel_edge")
            edir = t.get("edge_dir", {})
            bg = "#FAFAFA"   # canvas background → white casing makes crossings legible
            # N4 remembered overlay: links from the saved snapshot between two currently-
            # offline nodes that the live graph can't observe. Render-only (not in t["edges"]).
            _nodes = t["nodes"]
            _snap = self.s.get("topology_snapshot")
            def _is_offline(i):
                nn = _nodes.get(i, {})
                return not (nn.get("is_local") or nn.get("online", True))
            remembered, rem_dir = set(), {}
            if _snap:
                rem_dir = _snap.get("edge_dir", {})
                for _e in _snap.get("edges", set()):
                    _ids = sorted(_e)
                    if (len(_ids) == 2 and all(i in _nodes for i in _ids)
                            and _e not in t["edges"]
                            and _is_offline(_ids[0]) and _is_offline(_ids[1])):
                        remembered.add(_e)

            def _draw_edge(e):
                ids = sorted(e)
                if len(ids) < 2:
                    return
                na, nb = t["nodes"].get(ids[0]), t["nodes"].get(ids[1])
                if not na or not nb or "x" not in na or "x" not in nb:
                    return
                ax, ay = _to_screen(*_clip_to_box(na["x"], na["y"], nb["x"], nb["y"]))
                bx, by = _to_screen(*_clip_to_box(nb["x"], nb["y"], na["x"], na["y"]))
                is_sel = (sel_e == e)
                wdt = (3 if is_sel else 2) * z
                ash = (12 * z, 14 * z, 5 * z)
                mx, my = (ax + bx) / 2, (ay + by) / 2
                # Casing: a slightly thicker background-coloured line UNDER the edge, so where
                # two edges cross the one drawn later shows a clean gap over the other.
                cv.create_line(ax, ay, bx, by, fill=bg, width=wdt + max(3 * z, 3),
                               capstyle="round")

                def _warn(color, fs, msg):
                    it = cv.create_text(mx, my - 8, text="⚠", fill=color,
                                        font=(_FONT, max(7, int(fs * z))))
                    cv.tag_bind(it, "<Enter>", lambda _e, m=_T(msg): _schedule_tip(m))
                    cv.tag_bind(it, "<Leave>", lambda _e: _hide_tip())

                both_online = bool(na.get("online", True) and nb.get("online", True))
                if e in remembered:
                    # N4: a link known from a PREVIOUS session whose endpoints are offline
                    # now — dotted, dimmed, with the snapshot's arrow direction if we had it.
                    arr = (_arrow_from_senders(ids[0], ids[1], rem_dir[e]) if e in rem_dir
                           else "none")
                    cv.create_line(ax, ay, bx, by, width=wdt, dash=(2, 4),
                                   fill="#5E35B1" if is_sel else "#7E57C2",
                                   arrow=_ARROW.get(arr, tk.NONE), arrowshape=ash)
                    _warn("#7E57C2", 9, "Enlace recordado de una sesión anterior: uno o ambos "
                          "equipos están offline ahora. Se muestra para conservar la malla "
                          "conocida; se verificará al reconectar (puede haber cambiado fuera "
                          "de la app).")
                elif e not in edir:
                    # Unknown direction (an offline/unread endpoint) → dashed, no arrow, ⚠.
                    cv.create_line(ax, ay, bx, by, width=wdt, dash=(5, 3),
                                   fill="#5E35B1" if is_sel else "#9E9E9E")
                    _warn("#C66000", 9, "Dirección desconocida: un extremo está offline. Si no "
                          "tocas este enlace, no se modificará; si lo editas, el cambio se "
                          "aplicará cuando el equipo reconecte (pasiva) o mediante agente.")
                else:
                    senders = edir[e]
                    arr = _arrow_from_senders(ids[0], ids[1], senders)
                    noflow = (arr == "none")
                    # Conflict: a one-way link the global roles can't honour (both ends end
                    # up envía/recibe). Only flagged when BOTH ends are online — for an
                    # offline endpoint we can't be sure of its real role, so no red alert.
                    conflict = (len(senders) == 1 and both_online
                                and _edge_arrow(na.get("role"), nb.get("role")) == "both")
                    if noflow or conflict:
                        cv.create_line(ax, ay, bx, by, width=wdt, dash=(4, 3),
                                       fill="#5E35B1" if is_sel else "#C62828",
                                       arrow=_ARROW.get(arr, tk.NONE), arrowshape=ash)
                        _warn("#C62828",
                              10, ("Ningún extremo envía: este enlace no sincroniza nada."
                                   if noflow else
                                   "Dirección no realizable: ambos equipos quedan «envía/recibe» "
                                   "por sus otros enlaces, así que Syncthing lo hará bidireccional."))
                    else:
                        cv.create_line(ax, ay, bx, by, width=wdt,
                                       fill="#5E35B1" if is_sel else "#5A5A5A",
                                       arrow=_ARROW[arr], arrowshape=ash)
                if e in locked:
                    cv.create_text(mx, my + 9, text="🔒", font=(_FONT, max(7, int(8 * z))))

            # Draw non-selected edges first, then the selected one LAST so a clicked edge
            # comes to the front (over the others it crosses).
            for e in t["edges"]:
                if e != sel_e:
                    _draw_edge(e)
            if sel_e in t["edges"]:
                _draw_edge(sel_e)
            for e in remembered:        # remembered offline-mesh overlay (dotted)
                _draw_edge(e)
            # Nodes: box colour = network state (🔵 local / 🟢 conectado / 🔴 offline);
            # lines = name · role (text) · brief "aceptar manual" tag when applicable.
            _ROLE_FULL = {"sendreceive": "Envía y recibe", "sendonly": "Solo envía",
                          "receiveonly": "Solo recibe"}
            hw, hh = NODE_W / 2 * z, NODE_H / 2 * z
            # Scale fonts WITH the zoom (no inflated floor) so text stays inside the box;
            # hide it entirely when zoomed far out (boxes become plain colour blocks).
            show_text = z >= 0.5
            fs_label = max(1, int(round(8 * z)))
            fs_role = max(1, int(round(7 * z)))
            # Nodes that will be UNSHARED on apply (lost their last link) — drawn with a dashed
            # pink halo so it's obvious BEFORE you open the preview. Same locked-aware rule as
            # the apply/preview, excluding local/new (those are never orphan-unshared).
            _orig_t = self.s.get("topology_orig")
            _orphan_ids = set()
            if _orig_t:
                _orphan_ids = {nid for nid in orphaned_node_ids(
                                   _orig_t.get("edges", set()), t.get("edges", set()),
                                   self.s.get("topology_locked"))
                               if nid in t["nodes"] and not t["nodes"][nid].get("is_local")
                               and not t["nodes"][nid].get("is_new")}
            # Members whose SSH creds were verified-and-rejected → flag with a distinct halo so the
            # user sees the bad creds in the preview (a disk path-rename will fail on them).
            _ssh_bad_ids = {p[0] for p in _ssh_cred_problems(t)}
            for nid, n in t["nodes"].items():
                if "x" not in n:
                    continue
                x, y = _to_screen(n["x"], n["y"])
                if n["is_local"]:
                    fill, outline = "#E3F2FD", "#1565C0"     # blue
                elif n["online"]:
                    fill, outline = "#E8F5E9", "#2E7D32"     # green
                else:
                    fill, outline = "#FFEBEE", "#C62828"     # red (offline)
                if drag["sel"] == nid:
                    # Selection halo: an indigo ring OUTSIDE the box. The node keeps its
                    # status colour (blue/green/red) so the two cues never collide (the
                    # old orange outline clashed with the red "offline" outline).
                    cv.create_rectangle(x - hw - 4, y - hh - 4, x + hw + 4, y + hh + 4,
                                        outline="#5E35B1", width=3)
                if nid in _orphan_ids:
                    # SOLID black halo (outer ring) = "se dejará de compartir al aplicar". Solid (no
                    # dash) sets it apart from the DASHED warning halos (amber-unconfirmed, red
                    # SSH-bad): solid = a definitive removal on apply, dashed = a warning. Black is
                    # neutral/strong and (being SOLID) is never confused with the grey DASHED
                    # "unknown direction" edges.
                    cv.create_rectangle(x - hw - 6, y - hh - 6, x + hw + 6, y + hh + 6,
                                        outline="#212121", width=2)
                if n.get("unconfirmed"):
                    # Dashed amber halo (outermost) = "sin confirmar": una ejecución anterior no
                    # pudo aplicar/verificar el cambio en este nodo (offline, sin agente).
                    cv.create_rectangle(x - hw - 9, y - hh - 9, x + hw + 9, y + hh + 9,
                                        outline="#F9A825", width=2, dash=(2, 3))
                if nid in _ssh_bad_ids:
                    # Dashed RED halo = "credenciales SSH no válidas" (red = error/invalid, intuitive).
                    # Distinct from the offline node: that's a SOLID red box, this is a DASHED red
                    # outer ring at offset 12 — and from the SOLID black orphan ring.
                    cv.create_rectangle(x - hw - 12, y - hh - 12, x + hw + 12, y + hh + 12,
                                        outline="#C62828", width=2, dash=(5, 2))
                cv.create_rectangle(x - hw, y - hh, x + hw, y + hh,
                                    fill=fill, outline=outline, width=1.5)
                if not show_text:
                    continue   # zoomed far out → plain colour blocks, no (overflowing) text
                # A NEW device gets a distinct "NUEVO" pill on its OWN top line (a green
                # badge, white text) instead of a prefix that used to stretch the name line
                # and break the box layout. Name/role then sit a touch lower so nothing
                # collides; non-new nodes keep the original vertical placement.
                is_new = bool(n.get("is_new"))
                name_dy, role_dy, warn_dy = (-7, 9, 21) if is_new else (-15, 2, 17)
                if is_new:
                    # Teal pill — deliberately NOT green (green = connected box) nor blue
                    # (local), red (offline), indigo/violet (selection/remembered edges) or
                    # orange (warnings). Distinct and easy on the eye.
                    bid = cv.create_text(x, y - 20 * z, text="NUEVO", fill="#FFFFFF",
                                         font=(_FONT, max(1, int(round(7 * z))), "bold"))
                    bb = cv.bbox(bid)
                    if bb:
                        pad = max(2, int(round(3 * z)))
                        rid = cv.create_rectangle(bb[0] - pad, bb[1] - 1, bb[2] + pad, bb[3] + 1,
                                                  fill="#00897B", outline="#00695C")
                        cv.tag_raise(bid, rid)   # keep the white text above its pill
                label = (n["label"]
                         + ("  (local)" if n["is_local"] else
                            ("  · offline" if not n["online"] else "")))
                cv.create_text(x, y + name_dy * z, text=label, font=(_FONT, fs_label, "bold"),
                               fill="#222", width=NODE_W * z - 12)
                # A brand-new node has no role YET (it's being added this run) — say so plainly
                # instead of the alarming "Rol desconocido", which we reserve for an EXISTING
                # device whose role we genuinely couldn't read (offline/unprobed).
                role_txt = (_ROLE_FULL.get(n["role"], n["role"]) if n.get("role_known", True)
                            else ("Nuevo dispositivo" if n.get("is_new") else "Rol desconocido"))
                cv.create_text(x, y + role_dy * z, text=role_txt, font=(_FONT, fs_role),
                               fill="#555" if n.get("role_known", True) else "#C66000",
                               width=NODE_W * z - 12)
                if _apply_path(nid, n) == "aceptar":
                    cv.create_text(x, y + warn_dy * z, text="⚠ aceptar manual",
                                   font=(_FONT, fs_role), fill="#C62828")
            # Always-visible indicators: pending-to-apply changes (so creating a folder +
            # adding/sharing devices isn't mistaken for already-applied) + inconsistencies.
            _det = _topology_issues_detailed(t)
            _ssh = _ssh_cred_problems(t)
            n_issues = len(_det) + len(_ssh)
            # An orphan (isolated, "sin enlaces") node is a SOFT issue — disconnecting a node can
            # be deliberate — so when those are the ONLY issues the counter goes AMBER, not red.
            # Any other problem (no path, no-flow link, bad SSH creds) keeps it RED. The is_hard
            # flag is language-independent (no substring match on translated text).
            _hard = [m for _h, m in _det if _h] or _ssh
            # Pending changes: calm blue, separate label — a "press Next" reminder, not an error.
            pending_lbl.config(
                text="● cambios sin aplicar — pulsa Siguiente → para aplicarlos"
                if _topology_delta(self.s.get("topology_orig"), t).get("any") else "")
            if n_issues:
                issues_lbl.config(text=_T("⚠ {} inconsistencia(s) — ver").format(n_issues),
                                  fg="#C62828" if _hard else "#F9A825")
            else:
                issues_lbl.config(text="")

        def _force_directed(nodes: dict, edges: set, w: float, h: float) -> None:
            """Fruchterman–Reingold layout: nodes repel, edges pull. Produces a clean,
            non-overlapping arrangement for ANY topology (star, chain, tree, mesh), then
            the highest-degree node (the natural hub) is centred. Static (no animation)."""
            import random as _rnd
            ids = list(nodes)
            n = len(ids)
            if n == 0:
                return
            adj = {i: set() for i in ids}
            for e in edges:
                pair = sorted(e)
                if len(pair) >= 2 and pair[0] in adj and pair[1] in adj:
                    adj[pair[0]].add(pair[1])
                    adj[pair[1]].add(pair[0])
            # Comfortable ABSOLUTE spacing in world units — independent of the canvas; the
            # view is fitted to the available window afterwards (_fit_view). Leaves room
            # for the arrows between boxes (the old canvas-bounded layout cramped them).
            SP = max(NODE_W, NODE_H) + 70
            # A (near-)complete graph collapses into a blob under FR (every pair attracts).
            # An even ring is far cleaner — chord spacing so adjacent boxes never touch.
            m_edges = sum(len(v) for v in adj.values()) / 2
            full = n * (n - 1) / 2
            if n >= 3 and full and m_edges >= 0.8 * full:
                r = max((NODE_W + 90) / (2 * math.sin(math.pi / n)), SP)
                for idx, nid in enumerate(ids):
                    ang = 2 * math.pi * idx / n - math.pi / 2
                    nodes[nid]["x"] = r * math.cos(ang)
                    nodes[nid]["y"] = r * math.sin(ang)
                    nodes[nid]["_placed"] = True
                return
            # FR only makes sense for the CONNECTED part: a link-less node feels only
            # repulsion and gets flung thousands of px away, wrecking auto-fit (you literally
            # can't find it). So run FR on the connected nodes, then park loose (link-less)
            # nodes in a tidy grid — the "folder shared locally + devices not linked yet" case.
            loose = [i for i in ids if not adj[i]]
            connected = [i for i in ids if adj[i]]
            placed_box = None
            if connected:
                cids, cn = connected, len(connected)
                side = max(SP * (cn ** 0.5) * 1.4, 2 * SP)
                pos = {i: [_rnd.random() * side, _rnd.random() * side] for i in cids}
                k = SP * 0.9          # natural edge length ≈ comfortable spacing
                iters = 200
                for it in range(iters):
                    disp = {i: [0.0, 0.0] for i in cids}
                    for a_i in range(cn):
                        for b_i in range(a_i + 1, cn):
                            a, b = cids[a_i], cids[b_i]
                            dx, dy = pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]
                            dist = (dx * dx + dy * dy) ** 0.5 or 0.01
                            rep = k * k / dist
                            ux, uy = dx / dist, dy / dist
                            disp[a][0] += ux * rep; disp[a][1] += uy * rep
                            disp[b][0] -= ux * rep; disp[b][1] -= uy * rep
                    for a in cids:
                        for b in adj[a]:
                            if a < b:
                                dx, dy = pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]
                                dist = (dx * dx + dy * dy) ** 0.5 or 0.01
                                att = dist * dist / k
                                ux, uy = dx / dist, dy / dist
                                disp[a][0] -= ux * att; disp[a][1] -= uy * att
                                disp[b][0] += ux * att; disp[b][1] += uy * att
                    temp = side * 0.1 * (1 - it / iters)
                    for i in cids:
                        dx, dy = disp[i]
                        d = (dx * dx + dy * dy) ** 0.5 or 0.01
                        step = min(d, temp)
                        pos[i][0] += dx / d * step
                        pos[i][1] += dy / d * step
                for i in cids:
                    nodes[i]["x"] = pos[i][0]
                    nodes[i]["y"] = pos[i][1]
                    nodes[i]["_placed"] = True
                xs = [pos[i][0] for i in cids]; ys = [pos[i][1] for i in cids]
                placed_box = (min(xs), min(ys), max(xs), max(ys))
            if loose:
                # Compact grid: beside the connected cluster if there is one, else centred at
                # the origin. Deterministic and always on-screen, so a link-less node is easy
                # to find (and _fit_view bounds it tightly instead of zooming way out).
                cols = max(1, round(len(loose) ** 0.5))
                ox = (placed_box[2] + SP * 1.5) if placed_box else 0.0
                oy = placed_box[1] if placed_box else 0.0
                for idx, nid in enumerate(loose):
                    nodes[nid]["x"] = ox + (idx % cols) * SP
                    nodes[nid]["y"] = oy + (idx // cols) * SP
                    nodes[nid]["_placed"] = True
            # Final pass: nudge apart any boxes that still overlap (ALL nodes), keeping a wide
            # gap so the connecting arrows stay visible (overlap when |dx|<NODE_W, |dy|<NODE_H).
            half_w, half_h = NODE_W + 30, NODE_H + 30
            for _ in range(120):
                moved = False
                for a_i in range(n):
                    for b_i in range(a_i + 1, n):
                        a, b = nodes[ids[a_i]], nodes[ids[b_i]]
                        dx, dy = a["x"] - b["x"], a["y"] - b["y"]
                        gx, gy = half_w - abs(dx), half_h - abs(dy)
                        if gx > 0 and gy > 0:
                            if gx < gy:
                                sh = (gx / 2 + 1) * (1 if dx >= 0 else -1)
                                a["x"] += sh; b["x"] -= sh
                            else:
                                sh = (gy / 2 + 1) * (1 if dy >= 0 else -1)
                                a["y"] += sh; b["y"] -= sh
                            moved = True
                if not moved:
                    break

        def _layout_circle(force: bool = False):
            """Position nodes. force=True re-lays out everything (the ✨ Auto-organizar
            button); otherwise only places nodes that have no position yet (e.g. just
            added), leaving the user's manual drags untouched."""
            t = topo()
            if not t or not t["nodes"]:
                return
            w, h = cv.winfo_width(), cv.winfo_height()
            if w <= 1 or h <= 1:
                return  # canvas not sized yet — the <Configure> handler will call us again
            nodes = t["nodes"]
            unplaced = [nid for nid, n in nodes.items() if not n.get("_placed")]
            if force or len(unplaced) == len(nodes):
                _force_directed(nodes, t["edges"], w, h)
            elif unplaced:
                # Drop new nodes around the world centroid of the placed ones; the user
                # can Auto-organizar to refit. (Coords are world units, not canvas.)
                placed = [n for n in nodes.values() if n.get("_placed") and "x" in n]
                if placed:
                    cx = sum(p["x"] for p in placed) / len(placed)
                    cy = sum(p["y"] for p in placed) / len(placed)
                else:
                    cx = cy = 0.0
                # Rotate the start angle by how many nodes are already placed (and vary the
                # radius a touch) so a LONE new node added in a separate op doesn't always land
                # at angle 0 = the same spot, stacking exactly on a previously-placed node and
                # looking like it "didn't appear". Auto-organizar still refits everything.
                base = 0.6 * len(placed)
                for i, nid in enumerate(unplaced):
                    ang = base + 2 * math.pi * i / max(len(unplaced), 1)
                    radius = (NODE_W + 70) * (1.0 + 0.15 * (i % 3))
                    nodes[nid]["x"] = cx + radius * math.cos(ang)
                    nodes[nid]["y"] = cy + radius * math.sin(ang)
                    nodes[nid]["_placed"] = True

        def _fit_view(set_auto=None):
            """Encuadra TODO el grafo, centrado, dentro del tamaño disponible del canvas.
            El zoom se topa a 1.0 (no agranda más allá del tamaño natural → en pantalla
            completa queda centrado sin agigantarse) y baja hasta 0.3 si no cabe."""
            if set_auto is not None:
                view["auto"] = set_auto
            t = topo()
            if not t or not t["nodes"]:
                return
            xs = [n["x"] for n in t["nodes"].values() if "x" in n]
            ys = [n["y"] for n in t["nodes"].values() if "x" in n]
            if not xs:
                return
            minx, maxx = min(xs) - NODE_W / 2, max(xs) + NODE_W / 2
            miny, maxy = min(ys) - NODE_H / 2, max(ys) + NODE_H / 2
            bw, bh = max(maxx - minx, 1), max(maxy - miny, 1)
            cw, ch = cv.winfo_width(), cv.winfo_height()
            if cw <= 1 or ch <= 1:
                return  # canvas not sized yet
            margin = 36
            # Window mode (detected by how much of the screen width we occupy):
            #  · maximised/fullscreen → fill the available space (scale up to ~180 %),
            #    aligned top-left with a small margin → aprovecha el hueco.
            #  · normal window → don't enlarge past 100 %, centred.
            try:
                fullscreen = self.winfo_width() >= self.winfo_screenwidth() - 80
            except Exception:
                fullscreen = False
            zmax = 1.8 if fullscreen else 1.0
            z = min((cw - margin) / bw, (ch - margin) / bh, zmax)
            view["zoom"] = z = max(z, 0.3)
            if fullscreen:
                view["px"] = minx - 20 / z          # top-left, small margin
                view["py"] = miny - 20 / z
            else:
                view["px"] = (minx + maxx) / 2 - (cw / 2) / z   # centred
                view["py"] = (miny + maxy) / 2 - (ch / 2) / z
            # Reflect the resulting zoom in the status (else ⊡ Ajustar changed it silently
            # and the next manual zoom seemed to "jump").
            status_lbl.config(text=f"Zoom {int(round(view['zoom'] * 100))}%")

        def _toggle_edge(a, b):
            """Connect/disconnect a pair (quick toggle). A new link defaults to ↔; use
            🔗 Añadir enlace for a directional one. Removing also drops its direction."""
            t = topo()
            if a not in t["nodes"] or b not in t["nodes"]:
                return   # a node vanished (background sweep/removal) since this action was queued
            _push_undo()
            e = frozenset((a, b))
            ed = t.setdefault("edge_dir", {})
            if e in t["edges"]:
                t["edges"].discard(e)
                ed.pop(e, None)
                # Removing also UNLOCKS it: an explicit "quitar" must actually take effect on
                # apply, otherwise a locked edge would vanish from the canvas yet be kept by
                # compute_topology_diff (skipped_locked) — canvas lying about what apply does.
                self.s.get("topology_locked", set()).discard(e)
                status_lbl.config(text=f"Desvinculados «{t['nodes'][a]['label']}» y «{t['nodes'][b]['label']}»")
            else:
                t["edges"].add(e)
                ed[e] = frozenset((a, b))   # default bidirectional
                status_lbl.config(text=f"Vinculados «{t['nodes'][a]['label']}» y «{t['nodes'][b]['label']}»")
            _derive_roles(t)
            drag["sel"] = None
            drag["sel_edge"] = None

        def _add_link(src, dst, kind):
            """Create a link with an explicit direction. kind='uni' → src→dst; 'bi' → ↔."""
            t = topo()
            # A background sweep/reconcile can drop a node between the press that selected the
            # origin and the release that picks the target. Don't resurrect a removed node into
            # edges (nor KeyError on its label) — abort the link silently and clear the selection.
            if not t or src not in t.get("nodes", {}) or dst not in t.get("nodes", {}):
                drag["sel"] = drag["sel_edge"] = None
                return
            _push_undo()
            e = frozenset((src, dst))
            t["edges"].add(e)
            ed = t.setdefault("edge_dir", {})
            ed[e] = frozenset((src,)) if kind == "uni" else frozenset((src, dst))
            _derive_roles(t)
            la, lb = t["nodes"][src]["label"], t["nodes"][dst]["label"]
            status_lbl.config(text=(_T("Enlace «{}» → «{}»").format(la, lb) if kind == "uni"
                                    else _T("Enlace «{}» ↔ «{}»").format(la, lb)))
            drag["sel"] = drag["sel_edge"] = None

        # ── Undo / Redo (graph edits only — drags/layout are not recorded) ──────────
        # Stored in self.s so the stacks SURVIVE navigating Back/Next (the page is rebuilt
        # but the topology lives in self.s, so the snapshots stay valid).
        _undo_stack: list = self.s.setdefault("topo_undo", [])
        _redo_stack: list = self.s.setdefault("topo_redo", [])

        def _topo_snapshot():
            t = topo()
            if not t:
                return None
            return {"nodes": {nid: dict(n) for nid, n in t["nodes"].items()},
                    "edges": set(t["edges"]),
                    "edge_dir": dict(t.get("edge_dir", {})),
                    "locked": set(self.s.get("topology_locked", set())),
                    "removed": set(self.s.get("topology_removed", set())),
                    # A canvas-added (is_new) node lives in BOTH the graph and manual_topo_nodes;
                    # capture the latter so undo/redo restore them together (see _topo_restore).
                    "manual": {k: dict(v) for k, v in
                               (self.s.get("manual_topo_nodes") or {}).items()}}

        def _topo_restore(snap):
            t = topo()
            if not t or not snap:
                return
            t["nodes"] = {nid: dict(n) for nid, n in snap["nodes"].items()}
            t["edges"] = set(snap["edges"])
            t["edge_dir"] = dict(snap.get("edge_dir", {}))
            self.s["topology_locked"] = set(snap["locked"])
            self.s["topology_removed"] = set(snap["removed"])
            # Restore the manually-added (is_new) node metadata too. A node added in the canvas
            # lives in BOTH the graph and manual_topo_nodes; if undo restored only the graph, a
            # later rebuild/reconcile would RE-INJECT the node from manual_topo_nodes and it would
            # then get configured for the folder on apply — exactly what undoing the add must
            # prevent. ('manual' is absent on snapshots taken before this fix → leave as-is.)
            if "manual" in snap:
                self.s["manual_topo_nodes"] = {k: dict(v) for k, v in snap["manual"].items()}
            drag["sel"] = drag["sel_edge"] = None

        def _sync_undo_btns():
            undo_btns["undo"].config(state="normal" if _undo_stack else "disabled")
            undo_btns["redo"].config(state="normal" if _redo_stack else "disabled")

        def _push_undo():
            snap = _topo_snapshot()
            if snap is None:
                return
            _undo_stack.append(snap)
            del _undo_stack[:-20]   # keep at most ~20 steps
            _redo_stack.clear()
            _sync_undo_btns()

        def _undo():
            if not _undo_stack:
                return
            cur = _topo_snapshot()
            _topo_restore(_undo_stack.pop())
            if cur:
                _redo_stack.append(cur)
            _sync_undo_btns()
            status_lbl.config(text="Deshecho.")
            _render()

        def _redo():
            if not _redo_stack:
                return
            cur = _topo_snapshot()
            _topo_restore(_redo_stack.pop())
            if cur:
                _undo_stack.append(cur)
            _sync_undo_btns()
            status_lbl.config(text="Rehecho.")
            _render()

        def _check_issues():
            _cur = topo()
            issues = _detect_topology_issues(_cur)
            issues += [_T('«{}»: credenciales SSH no válidas — el rename en disco fallará '
                          '(corrígelas o usa el agente).').format(lbl)
                       for _id, lbl, _err in _ssh_cred_problems(_cur)]
            if not issues:
                status_lbl.config(text="✓ Sin inconsistencias detectadas.")
                messagebox.showinfo("Revisión de topología",
                                    "✓ No se detectaron inconsistencias.", parent=self)
            else:
                status_lbl.config(text=_T("⚠ {} inconsistencia(s) — ver detalle.").format(len(issues)))
                messagebox.showwarning(
                    "Revisión de topología",
                    "Posibles inconsistencias:\n\n  • " + "\n  • ".join(issues), parent=self)

        def _zoom_to(new_z, sx=None, sy=None):
            new_z = max(0.3, min(3.0, new_z))
            if abs(new_z - view["zoom"]) < 1e-6:
                return
            view["auto"] = False   # manual zoom → stop auto-fitting on resize
            cw, ch = cv.winfo_width(), cv.winfo_height()
            if sx is None:
                sx = cw / 2
            if sy is None:
                sy = ch / 2
            wx, wy = _to_world(sx, sy)          # keep the point under the cursor fixed
            view["zoom"] = new_z
            view["px"] = wx - sx / new_z
            view["py"] = wy - sy / new_z
            status_lbl.config(text=f"Zoom {int(round(new_z * 100))}%")
            _render()

        # ── Pending "stop sharing" prunes (passive retry) ────────────────────────
        # When «Dejar de compartir» can't reach every equipo that still shares with the
        # target, the unreachable members are remembered here so the periodic status poll
        # (or the 🔄 Estado button) finishes the prune automatically once they reconnect —
        # same passive model as the rename. Keyed (folder_id, target_id) → {label, members}.
        # pending_unshare is read+mutated by the off-thread «Estado» sweep (_sweep_pending_unshare)
        # AND by these UI-thread register/clear helpers — guard every mutation with one lock so a
        # background prune can't interleave a torn write with a foreground register/clear. The lock
        # is created once (dict.setdefault is atomic under the GIL) and never held across network I/O.
        def _pu_lock():
            return self.s.setdefault("_pending_unshare_lock", threading.Lock())

        def _register_pending_unshare(folder_id, target_id, label, member_ids):
            key = (folder_id, target_id)
            with _pu_lock():
                pend = self.s.setdefault("pending_unshare", {})
                if member_ids:
                    pend[key] = {"label": label, "members": set(member_ids)}
                else:
                    pend.pop(key, None)

        def _clear_pending_unshare(folder_id, target_id):
            with _pu_lock():
                self.s.get("pending_unshare", {}).pop((folder_id, target_id), None)

        def _clear_folder_pending_unshare(folder_id):
            # Drop ALL pending-unshares for a folder being DELETED/recreated. _reset_folder_scoped_
            # state can't do this (it's also the folder-SWITCH path, where pending work must
            # survive), so clear here — else a stale (folder_id, target) entry would prune that
            # target on a freshly-recreated SAME-id folder when it reconnects.
            with _pu_lock():
                pend = self.s.get("pending_unshare", {})
                for _k in [k for k in pend if k[0] == folder_id]:
                    pend.pop(_k, None)

        def _sweep_pending_unshare(devs):
            """Off-thread: for the current folder, prune any pending-unshare member that has
            become reachable. Returns a list of (label, [pruned names]) for UI feedback."""
            from ..renamer import unshare_folder_everywhere, _device_reachable
            pend = self.s.get("pending_unshare", {})
            if not pend:
                return []
            folder = self.s.get("folder")
            if not folder:
                return []
            dm = {d.device_id: d for d in devs}
            done = []
            for (fid, tid), info in list(pend.items()):
                if fid != folder.id:
                    continue
                members = set(info.get("members", set()))
                reachable_now = {m for m in members if dm.get(m) and _device_reachable(dm[m])}
                if not reachable_now:
                    continue
                # prune_only: the target's own folder was already removed by the first run.
                unshare_folder_everywhere(devs, fid, tid, member_ids=members, prune_only=True)
                remaining = {m for m in members
                             if not (dm.get(m) and _device_reachable(dm[m]))}
                pruned = members - remaining
                if pruned:
                    done.append({
                        "target_id": tid,
                        "label": info.get("label", tid[:7]),
                        "names": [dm[m].name if dm.get(m) else m[:7] for m in pruned],
                        "done": not remaining,
                    })
                # Apply the prune result under the lock (the network call above ran WITHOUT it).
                # Re-read the entry: if a foreground register replaced it meanwhile, don't clobber
                # its fresh members — leave it for the next sweep to prune.
                with _pu_lock():
                    cur = pend.get((fid, tid))
                    if cur is info:
                        if remaining:
                            info["members"] = remaining
                        else:
                            pend.pop((fid, tid), None)
            return done

        def _remote_ref():
            """A reachable, direct-API remote that still shares the folder. Used to drive the
            live refresh AFTER the local node left this folder (so the remaining cluster's real
            status is read from a node that still has it), and to self-heal once the user adds
            credentials to a remote (tier-b). Returns a DeviceInfo or None."""
            t = topo()
            if not t:
                return None
            ids = set(t["nodes"].keys())
            with self._devices_lock:
                for d in self.s.get("devices", []):
                    if (not d.is_local and d.device_id in ids
                            and d.api_reachable and d.api_url and d.api_key):
                        return d
            return None

        def _refresh_status(quiet: bool = True, on_done=None):
            """Live connectivity: ask Syncthing which peers are connected right now and
            recolour the nodes (🟢/🔴). Cheap (one API call); runs off-thread. Used by the
            🔄 Estado button and a light periodic poll while on this page. Normally driven by
            the LOCAL node; after a local unshare (`local_folder_gone`) it re-anchors to a
            reachable remote that still shares the folder, falling back to the local daemon
            (which keeps reporting its own peer connections even without the folder)."""
            _my_gen = self._show_gen   # bind now; ui() must not mutate state for a page we left
            client = self.s.get("client")
            if self.s.get("local_folder_gone"):
                _rd = _remote_ref()
                if _rd:
                    try:
                        client = SyncthingClient(_rd.api_url, _rd.api_key, verify_ssl=False)
                    except Exception:
                        pass
            t = topo()
            if not client or not t:
                if on_done:
                    on_done()
                return

            def work():
                try:
                    conn = client.get_connected_devices()
                    online = {d for d, ci in conn.items() if ci.connected}
                except Exception:
                    conn, online = {}, None

                # Auto-rediscovery: a node that is offline in our model but is NOW a connected
                # Syncthing peer (and has stored credentials) gets RE-PROBED here so it truly
                # becomes configurable — not merely repainted green. Before, this poll only
                # recoloured the dot, so a reconnected passive device never upgraded to "ok".
                if online is not None:
                    import dataclasses as _dc
                    folder = self.s["folder"]
                    with self._devices_lock:
                        cands = [d for d in self.s.get("devices", [])
                                 if not d.is_local
                                 and _device_kind(d) != "ok"
                                 and (d.ssh_user or d.ssh_key_path or d.ssh_password
                                      or (d.winrm_user and d.winrm_password)
                                      or (d.api_key and d.api_url))
                                 # Reconnected Syncthing peer (cheap), OR — on an EXPLICIT
                                 # Estado press (not quiet) — any credentialed device even if it
                                 # isn't a connected peer yet. That's what lets a newly
                                 # SSH-configured node get probed (OS auto-detected, the
                                 # "configurar vía" state cleared) when the remote hasn't
                                 # accepted the share. The periodic quiet poll keeps only the
                                 # cheap `in online` set so it never blocks on SSH timeouts.
                                 and (d.device_id in online or not quiet)]
                    for d in cands:
                        ci = conn.get(d.device_id)
                        ip = (ci.ip if ci else None) or d.ip
                        try:
                            if d.ssh_user or d.ssh_key_path or d.ssh_password or (d.winrm_user and d.winrm_password):
                                nd = probe_device(
                                    device_id=d.device_id, name=d.name, ip=ip, folder_id=folder.id,
                                    override={"ssh_user": d.ssh_user, "ssh_key_path": d.ssh_key_path,
                                              "ssh_password": d.ssh_password, "ssh_port": d.ssh_port,
                                              "winrm_user": d.winrm_user, "winrm_password": d.winrm_password,
                                              "winrm_port": d.winrm_port})
                                nd = _dc.replace(nd, api_key=nd.api_key or d.api_key,
                                                 api_url=nd.api_url or d.api_url,
                                                 folder_path=nd.folder_path or d.folder_path)
                            else:
                                _stored = d.api_url or f"http://{ip}:8384"
                                _scheme = _stored.split("://")[0] if "://" in _stored else "http"
                                _m = re.search(r":(\d+)$", _stored.split("//")[-1].split("/")[0])
                                _url = f"{_scheme}://{ip}:{_m.group(1) if _m else '8384'}"
                                nd = probe_device_manual(
                                    device_id=d.device_id, name=d.name, ip=ip, folder_id=folder.id,
                                    api_key=d.api_key, api_url=_url, folder_path=d.folder_path or "")
                        except Exception:
                            continue
                        if _device_kind(nd) == "ok":
                            # Update the device AND clean the passive/agent queues under one
                            # lock: two _refresh_status.work() threads can run at once (a quiet
                            # poll blocked on an SSH timeout + an explicit 🔄 Estado press), and
                            # the read-modify-write of agent_devices would otherwise lose an
                            # update and resurrect a stale agent entry.
                            with self._devices_lock:
                                for i, x in enumerate(self.s["devices"]):
                                    if x.device_id == nd.device_id:
                                        self.s["devices"][i] = nd
                                        break
                                # Now reachable → drop it from the passive/agent queues so it
                                # isn't ALSO offered "al reconectar"/as an agent in Ejecutar
                                # (the node editor and add-device/execute probes already do
                                # this; the Estado re-probe used to skip it, leaving a stale
                                # agent entry → a device configured directly via SSH was also
                                # shown as agent).
                                self.s.get("passive_devices", set()).discard(nd.device_id)
                                self.s["agent_devices"] = [a for a in self.s.get("agent_devices", [])
                                                           if a.device_id != nd.device_id]

                # Passive retry of any pending «dejar de compartir»: now that reconnected
                # members were re-probed above, finish pruning the target from those that
                # became reachable. Runs off-thread (network); feedback applied in ui().
                with self._devices_lock:
                    _devs_for_sweep = list(self.s.get("devices", []))
                swept = _sweep_pending_unshare(_devs_for_sweep)

                # Rebuild the REAL graph so 🔄 Estado also INTEGRATES newly-connected peers
                # and upgrades deviceID placeholders to real names (N7) — not just recolour.
                # Names come from our DeviceInfos AND the local node's device config, so an
                # introduced peer we have no DeviceInfo for still shows its name instead of a
                # bare device ID. Built off-thread (network); reconciled in ui().
                base = None
                if online is not None:
                    try:
                        folder = self.s["folder"]
                        my_id = self.s.get("my_id", "")
                        with self._devices_lock:
                            devs_snap = list(self.s.get("devices", []))
                        # Skip the per-hub name query on the 15s background quiet poll — names
                        # don't change between polls and reconcile only UPGRADES placeholder
                        # labels (never downgrades), so already-resolved names survive. An
                        # explicit 🔄 Estado (not quiet) still does the full hub resolution.
                        _extra = {} if quiet else _hub_name_map(devs_snap, folder.id)
                        name_map = _resolve_name_map(devs_snap, client, extra_names=_extra)
                        online_ids = {d.device_id for d in devs_snap if _device_kind(d) == "ok"}
                        online_ids |= set(online or set())
                        base = _build_topology(folder, my_id, name_map, online_ids,
                                               devices=devs_snap)
                    except Exception:
                        base = None

                def ui():
                    if not cv.winfo_exists() or self._show_gen != _my_gen:
                        return   # navigated away while the probe ran — don't touch stale state
                    if online is None:
                        if not quiet:
                            status_lbl.config(text="No se pudo actualizar el estado.")
                        return
                    myid = self.s.get("my_id", "")
                    cur = self.s.get("topology")
                    # Merge freshly-observed reality into the live + baseline graphs without
                    # discarding the user's edits (same path discovery uses). This is what
                    # makes the button resolve a phantom deviceID node into its real device.
                    _added = []
                    if base and cur:
                        orig = self.s.get("topology_orig") or _copy_topology(cur)
                        self.s["topology_orig"] = orig
                        _added = _reconcile_topology(cur, orig, base, myid,
                                                     removed=self.s.get("topology_removed"))
                    with self._devices_lock:
                        devmap = {d.device_id: d for d in self.s.get("devices", [])}
                    for nid, n in t["nodes"].items():
                        d = devmap.get(nid)
                        # Green = connected Syncthing peer OR reachable via our access
                        # (SSH/WinRM/API) — a just-probed device must not flip back to red.
                        reachable = bool(d and _device_kind(d) == "ok")
                        n["online"] = bool(n.get("is_local") or nid == myid
                                           or nid in online or reachable)
                        # Reachable by us again → clear a stale "unconfirmed" mark here too (the
                        # build does the same), so «Estado» heals it without a full rebuild.
                        if reachable or n.get("is_local"):
                            n.pop("unconfirmed", None)
                    # Passive «dejar de compartir»: a target whose pending prune just
                    # finished on all members no longer shares with anyone → drop its node.
                    if swept:
                        for s_ in swept:
                            if s_["done"] and s_["target_id"] in t["nodes"]:
                                t["nodes"].pop(s_["target_id"], None)
                                t["edges"] = {e for e in t["edges"] if s_["target_id"] not in e}
                                t["edge_dir"] = {e: v for e, v in t.get("edge_dir", {}).items()
                                                 if s_["target_id"] not in e}
                        _derive_roles(t)
                        msg = "; ".join(
                            _T('«{}» ya no comparte ({})').format(s_['label'], ', '.join(s_['names']))
                            if s_["done"] else
                            f"«{s_['label']}»: {', '.join(s_['names'])} actualizados (quedan otros)"
                            for s_ in swept)
                        status_lbl.config(text="↺ Pasiva — " + msg)
                    elif not quiet:
                        _pend = self.s.get("pending_unshare", {})
                        _fid = (self.s.get("folder") or type("F", (), {"id": None})).id
                        _np = sum(1 for (fid2, _t) in _pend if fid2 == _fid)
                        extra = (f"  ·  {_np} des-compartir pendiente(s) al reconectar"
                                 if _np else "")
                        status_lbl.config(
                            text=f"Estado actualizado: {len(online)} conectado(s).{extra}")
                    if _added and not quiet:
                        # An EXPLICIT 🔄 Estado found a new peer → re-organise the whole graph +
                        # refit so it slots in cleanly (no overlapping nodes/arrows). NOT on the
                        # 15s background quiet poll: a peer reconnecting on its own must never
                        # silently rearrange the graph the user is looking at.
                        _layout_circle(force=True)
                        _fit_view(set_auto=True)
                    else:
                        _layout_circle()        # place any node the reconcile just added
                        if view.get("auto", True):
                            _fit_view()
                    _render()
                self._post(ui)
            def _run():
                # Guarantee on_done ALWAYS fires — even if work() raises mid-sweep (e.g. a
                # network error in _sweep_pending_unshare) — or the poll's _poll_busy flag
                # would latch True forever and live-status polling would stop for the session.
                try:
                    work()
                finally:
                    if on_done:
                        self._post(on_done)
            threading.Thread(target=_run, daemon=True).start()

        def _on_resize(_e=None):
            # Place any unplaced nodes, then (until the user manually zooms/pans) keep the
            # whole graph fitted to the now-current window size.
            _layout_circle()
            if view.get("auto", True):
                _fit_view()
            _render()

        def _on_wheel(ev):
            # Windows/macOS: ev.delta (±120). Linux: Button-4/5 (no delta).
            up = getattr(ev, "delta", 0) > 0 or getattr(ev, "num", 0) == 4
            _zoom_to(view["zoom"] * (1.15 if up else 1 / 1.15), ev.x, ev.y)

        def on_press(ev):
            nid = _node_at(ev.x, ev.y)
            drag.update(id=nid, moved=False, sx=ev.x, sy=ev.y, panning=False)
            if nid:
                n = topo()["nodes"][nid]
                drag["ox"], drag["oy"] = n["x"], n["y"]
            elif drag["mode"] == "move" and not _edge_at(ev.x, ev.y):
                # Empty space in Move mode → drag to pan the view.
                drag["panning"] = True
                drag["px0"], drag["py0"] = view["px"], view["py"]

        def on_motion(ev):
            if drag.get("panning"):
                if abs(ev.x - drag["sx"]) > 2 or abs(ev.y - drag["sy"]) > 2:
                    drag["moved"] = True
                    view["auto"] = False   # manual pan → stop auto-fitting on resize
                view["px"] = drag["px0"] - (ev.x - drag["sx"]) / view["zoom"]
                view["py"] = drag["py0"] - (ev.y - drag["sy"]) / view["zoom"]
                _render()
                return
            nid = drag["id"]
            if not nid or drag["mode"] != "move":
                return
            if abs(ev.x - drag["sx"]) > 3 or abs(ev.y - drag["sy"]) > 3:
                drag["moved"] = True
            n = topo()["nodes"].get(nid)
            if n is None:          # node removed by a posted ui() between press and this motion
                drag["id"] = None
                return
            n["x"], n["y"] = _to_world(ev.x, ev.y)
            _render()

        def _select(nid):
            drag["sel_edge"] = None
            # A deferred single-click (self.after 260ms) or a context action can fire AFTER a
            # passive sweep / reconcile dropped this node — guard the lookup so it degrades to
            # "no selection" instead of a KeyError crashing the (unprotected) Tk callback.
            node = topo()["nodes"].get(nid) if nid else None
            drag["sel"] = nid if node else None
            if node:
                status_lbl.config(text=_T('«{}» seleccionado (✏ Editar seleccionado · doble clic · clic derecho)').format(node['label']))
            _render()

        def _edge_dir_text(e):
            """Human-readable direction of an edge, from its stored per-link direction."""
            t = topo()
            ids = sorted(e)
            na, nb = t["nodes"].get(ids[0]), t["nodes"].get(ids[1])
            if not na or not nb:
                return ""
            la, lb = na["label"], nb["label"]
            senders = t.get("edge_dir", {}).get(e)
            if senders is None:
                return _T('«{}» — «{}»  (dirección desconocida · offline)').format(la, lb)
            arr = _arrow_from_senders(ids[0], ids[1], senders)
            if arr == "both":
                return f"«{la}» ↔ «{lb}»  (bidireccional)"
            if arr == "last":
                return f"«{la}» → «{lb}»"
            if arr == "first":
                return f"«{lb}» → «{la}»"
            return _T('«{}» ⁄⁄ «{}»  (sin sincronización)').format(la, lb)

        def _select_edge(e):
            drag["sel"] = None
            drag["sel_edge"] = e
            status_lbl.config(text=_T("Enlace: ") + _edge_dir_text(e)
                              + "  (✏ Editar seleccionado · clic derecho)")
            _render()

        def _connect_click(nid):
            sel = drag["sel"]
            kind = drag.get("new_kind", "bi")
            if sel is None or sel == nid:
                drag["sel"] = None if sel == nid else nid
                if drag["sel"]:
                    hint = _T("destino") if kind == "uni" else _T("el otro nodo")
                    # A background sweep can pop nid between press and release — look up the
                    # label defensively (mirrors _select / the delete branch) so the Tk release
                    # callback never raises KeyError.
                    _lbl = topo().get('nodes', {}).get(nid, {}).get('label', nid[:7])
                    status_lbl.config(text=_T('«{}» — clic en {}').format(_lbl, hint))
            else:
                # sel was clicked first → it's the ORIGIN for a unidirectional link.
                _add_link(sel, nid, kind)
            _render()

        def on_release(ev):
            nid = drag["id"]
            mode = drag["mode"]
            drag["id"] = None
            if drag.get("panning"):
                # End a pan. A pan that didn't move = a plain click on empty space →
                # fall through to the move-mode branch to clear the selection.
                drag["panning"] = False
                if drag["moved"]:
                    return
            if mode == "delete":
                e = _edge_at(ev.x, ev.y)
                if e:
                    t = topo()
                    ids = sorted(e)
                    a = t["nodes"].get(ids[0], {}).get("label", ids[0][:7])
                    b = t["nodes"].get(ids[1], {}).get("label", ids[1][:7])
                    _push_undo()
                    t["edges"].discard(e)
                    t.get("edge_dir", {}).pop(e, None)
                    self.s.get("topology_locked", set()).discard(e)   # removal unlocks (see _toggle_edge)
                    _derive_roles(t)
                    status_lbl.config(text=_T("Enlace borrado: «{}» — «{}»").format(a, b))
                    _render()
                return
            if mode == "connect":
                if nid and not drag["moved"]:
                    _connect_click(nid)
                elif nid and drag["moved"]:
                    target = _node_at(ev.x, ev.y, exclude=nid)
                    n = topo()["nodes"].get(nid)
                    if n is not None:
                        n["x"], n["y"] = drag["ox"], drag["oy"]
                        if target:
                            _add_link(nid, target, drag.get("new_kind", "bi"))  # dragged = origin
                    _render()
                return
            # move mode
            if not nid:
                # No node under the cursor: a plain click on a line selects that edge
                # (so the user can see/edit its direction); empty space clears selection.
                if not drag["moved"]:
                    e = _edge_at(ev.x, ev.y)
                    if e:
                        _select_edge(e)
                    else:
                        drag["sel"] = drag["sel_edge"] = None
                        _render()
                return
            if drag["moved"]:
                target = _node_at(ev.x, ev.y, exclude=nid)
                n = topo()["nodes"].get(nid)
                if target and n is not None:
                    n["x"], n["y"] = drag["ox"], drag["oy"]
                    _toggle_edge(nid, target)
                _render()
            else:
                # Defer select so a double-click (edit) doesn't leave a stray selection.
                if drag.get("click_after"):
                    self.after_cancel(drag["click_after"])
                drag["click_after"] = self.after(
                    260, lambda did=nid: (drag.update(click_after=None), _select(did)))

        def on_double(ev):
            if drag.get("click_after"):
                self.after_cancel(drag["click_after"])
                drag["click_after"] = None
            nid = _node_at(ev.x, ev.y)
            if nid:
                _edit_node_dialog(nid)
                return
            e = _edge_at(ev.x, ev.y)
            if e:                       # double-click an arrow → edit that link
                _select_edge(e)
                _edit_edge_dialog(e)

        def _remove_node(nid, allow_local=False, sync_orig=False, push_undo=True):
            t = topo()
            if t["nodes"].get(nid, {}).get("is_local") and not allow_local:
                status_lbl.config(text="No se puede eliminar el equipo local.")
                return
            if push_undo:
                _push_undo()
            t["nodes"].pop(nid, None)
            t["edges"] = {e for e in t["edges"] if nid not in e}
            t["edge_dir"] = {e: s for e, s in t.get("edge_dir", {}).items() if nid not in e}
            _derive_roles(t)
            # Remember the removal so the reconcile pass doesn't resurrect the node.
            self.s.setdefault("topology_removed", set()).add(nid)
            # When the removal was ALREADY applied to the real cluster (immediate unshare),
            # drop it from the baseline too so it doesn't linger as a phantom pending diff.
            if sync_orig:
                orig = self.s.get("topology_orig")
                if orig:
                    orig["nodes"].pop(nid, None)
                    orig["edges"] = {e for e in orig.get("edges", set()) if nid not in e}
                    orig["edge_dir"] = {e: s for e, s in orig.get("edge_dir", {}).items()
                                        if nid not in e}
            if drag["sel"] == nid:
                drag["sel"] = None
            status_lbl.config(text="Dispositivo eliminado de la topología.")
            _render()

        def _unshare_folder_on_node(nid):
            """N3 / P5 — Stop sharing THIS folder with/on a node AND remove it from the
            topology, in one immediate step (the two used to be separate actions). On the
            target it deletes the folder from Syncthing (if reachable); on every other
            reachable node it prunes the target from the folder membership. Works on the
            LOCAL node too: that removes the folder from THIS machine only — the rest of the
            cluster keeps syncing among themselves. Never deletes files on disk."""
            t = topo()
            n = t["nodes"].get(nid)
            if not n:
                return
            is_local = bool(n.get("is_local"))
            folder = self.s["folder"]
            label = n.get("label", nid[:7])
            fname = folder.label or folder.id
            if n.get("is_new"):
                # A brand-new device (added by ID, NOT yet applied anywhere) → there is nothing
                # to unshare on any real equipo. Running the network unshare would just mark it
                # "no accesible" and KEEP it (so it lingered in the preview). Instead, undo the
                # add purely locally: drop it from the graph, the device list, the passive/agent
                # queues and the manual-node set. No network action, no folder-delete prompt.
                if not messagebox.askyesno(
                        "Quitar de la topología",
                        _T('¿Quitar el dispositivo nuevo «{}» de la topología?\n\nAún no se ha aplicado en ningún equipo, así que solo se elimina de este diseño.').format(label),
                        parent=self):
                    return
                _remove_node(nid, allow_local=False, sync_orig=True)
                with self._devices_lock:
                    self.s["devices"] = [d for d in self.s.get("devices", [])
                                         if d.device_id != nid]
                    self.s.get("passive_devices", set()).discard(nid)
                    self.s["agent_devices"] = [a for a in self.s.get("agent_devices", [])
                                               if a.device_id != nid]
                self.s.get("manual_topo_nodes", {}).pop(nid, None)
                self._status(_T('Dispositivo nuevo «{}» quitado de la topología.').format(label), "#2E7D32")
                return
            if is_local:
                _msg = (_T('¿Dejar de compartir «{}» en ESTE equipo (local)?\n\n• Se ELIMINARÁ la carpeta de tu Syncthing: deja de sincronizarse aquí y desaparece de tu lista de carpetas.\n• Los demás equipos accesibles dejarán de sincronizarla contigo, pero seguirán sincronizándola entre ellos.\n• El nodo local saldrá de la topología de esta carpeta.\n\nEsta herramienta solo cambia la configuración de Syncthing; no ejecuta ningún borrado de archivos. Tus archivos en disco se conservan; haz una copia si no estás seguro.').format(fname))
            else:
                _msg = (_T('¿Dejar de compartir «{}» con «{}» y quitarlo de la topología?\n\n• En «{}» se ELIMINARÁ la carpeta de Syncthing: deja de sincronizarse y desaparece de su lista de carpetas (si es accesible).\n• En los demás equipos accesibles se quitará a «{}» de esta carpeta.\n\nEsta herramienta solo cambia la configuración de Syncthing; no ejecuta ningún borrado de archivos. Por seguridad, haz una copia si no estás seguro de tener los datos a salvo.').format(fname, label, label, label))
            if not messagebox.askyesno("Dejar de compartir la carpeta", _msg, parent=self):
                return
            self._status(_T('Dejando de compartir con «{}»…').format(label), "#555")
            # Authoritative member set per the graph: every node linked to the target
            # shares the folder with it and must drop it. Passing this lets the helper
            # flag members it couldn't reach (instead of silently leaving them sharing).
            member_ids = {o for e in t["edges"] if nid in e for o in e
                          if o != nid and not t["nodes"].get(o, {}).get("is_local")}
            _my_gen = self._show_gen   # bind now; ui() must not render/navigate a page we left

            def work():
                from ..renamer import unshare_folder_everywhere
                import dataclasses as _dc2
                # Never leave the status stuck on "Dejando de compartir…" if the backend raises.
                try:
                    with self._devices_lock:
                        devs = list(self.s.get("devices", []))
                    # Guarantee a correct LOCAL entry so the local folder is reliably pruned of
                    # the target (the "el nodo local sigue compartiendo" bug): drive it from the
                    # live client instead of trusting a possibly-stale devices snapshot.
                    client = self.s.get("client")
                    my_id = self.s.get("my_id", "")
                    if client and my_id:
                        _seen_local = False
                        for i, d in enumerate(devs):
                            if d.device_id == my_id:
                                devs[i] = _dc2.replace(
                                    d, api_url=d.api_url or client.base_url,
                                    api_key=d.api_key or client.api_key,
                                    is_local=True, api_reachable=True)
                                _seen_local = True
                                break
                        if not _seen_local:
                            devs.append(DeviceInfo(
                                device_id=my_id, name="local", ip="127.0.0.1",
                                api_url=client.base_url, api_key=client.api_key,
                                folder_path=folder.path, ssh_reachable=False,
                                api_reachable=True, is_local=True))
                    results = unshare_folder_everywhere(devs, folder.id, nid,
                                                        member_ids=member_ids)
                except Exception as e:
                    self._post(lambda _e=e: self._status(
                        _T('No se pudo dejar de compartir con «{}»: {}').format(label, _e), "#C62828"))
                    return

                def ui():
                    ok = sum(1 for _, k, _, _ in results if k)
                    bad = [(nm, m) for nm, k, m, _ in results if not k]
                    pending = [(nm, m) for nm, k, m, u in results if u]  # flag, not translated text
                    # Members still sharing because we can't reach them now = the ones we
                    # have no working channel to. Register them so the passive poll prunes
                    # them automatically when they reconnect (and the user can also retry by
                    # re-running this action or just adding credentials).
                    from ..renamer import _device_reachable
                    with self._devices_lock:
                        _dm = {d.device_id: d for d in self.s.get("devices", [])}
                    pending_ids = {m for m in member_ids
                                   if not (_dm.get(m) and _device_reachable(_dm[m]))}
                    if pending_ids:
                        _register_pending_unshare(folder.id, nid, label, pending_ids)
                    else:
                        _clear_pending_unshare(folder.id, nid)
                    if self._show_gen != _my_gen:
                        # User left the Topology page mid-unshare. The cluster change already
                        # landed and the pending_unshare tracking above is preserved (the passive
                        # poll will still prune on reconnect); skip the render/navigation/state
                        # reset below, which would disrupt whatever page they moved to.
                        return
                    if pending:
                        # Some equipos still list the target and we couldn't reach them.
                        # KEEP the node so the user can add credentials and retry; don't
                        # claim the share is fully gone.
                        _render()
                        names = ", ".join(nm for nm, _ in pending)
                        self._status(
                            _T('«{}»: {} equipo(s) actualizados, pero {} sin acceso siguen compartiéndola ({}). Se reintentará solo al reconectar (pasiva); añade credenciales o quítala en ese equipo.').format(label, ok, len(pending), names),
                            "#C66000")
                    else:
                        _clear_pending_unshare(folder.id, nid)
                        # Peers pruned + folder gone → drop it from the graph. allow_local so
                        # the local node can leave too; sync_orig so this applied removal
                        # doesn't linger as a phantom pending diff.
                        _remove_node(nid, allow_local=is_local, sync_orig=True)
                        other_bad = [m for _, m in bad]
                        if not is_local:
                            _render()
                            if other_bad:
                                self._status(_T('«{}»: {} equipo(s) OK, {} con error ({}).').format(label, ok, len(other_bad), other_bad[0]), "#C66000")
                            else:
                                self._status(_T('«{}» ya no comparte la carpeta ({} equipo/s actualizados).').format(label, ok), "#2E7D32")
                            return
                        # ── LOCAL node: the folder is gone from THIS machine ──────────────
                        # Drop the local device entry so it isn't re-probed. The remaining
                        # remotes STAY remote — we never promote one to "local"; only the
                        # topology view + the refresh's data source change.
                        with self._devices_lock:
                            self.s["devices"] = [d for d in self.s.get("devices", [])
                                                 if d.device_id != nid]
                            _dm2 = {d.device_id: d for d in self.s.get("devices", [])}
                        remaining = sorted(member_ids)
                        names = ", ".join(_dm2[m].name if _dm2.get(m) else m[:7]
                                          for m in remaining)
                        if not remaining:
                            # Nothing left to manage → the folder is gone everywhere we know.
                            # Forget its snapshot + wipe folder state so a same-id re-create can't
                            # resurrect ghosts (disk data is kept — unshare never deletes files).
                            self.s["local_folder_gone"] = False
                            appconfig.delete_topology_snapshot(folder.id)
                            _clear_folder_pending_unshare(folder.id)
                            self._reset_folder_scoped_state()
                            messagebox.showinfo(
                                "Carpeta quitada de este equipo",
                                _T('«{}» se ha quitado de este equipo y ya no la comparte ningún otro equipo.\n\nVolviendo a la selección de carpeta.').format(fname),
                                parent=self)
                            self._show(1)
                            return
                        # Some remotes still share it → keep managing them from here. The live
                        # refresh re-anchors to a reachable remote (it stays remote; only the
                        # view changes), and self-heals once any remote becomes reachable.
                        self.s["local_folder_gone"] = True
                        _render()
                        ref = _remote_ref()
                        if ref is not None:
                            self._status(_T('«{}» quitada de este equipo; estado vía «{}» (remoto).').format(fname, ref.name), "#2E7D32")
                            messagebox.showinfo(
                                "Carpeta quitada de este equipo",
                                _T('«{}» se ha quitado de este equipo (los archivos en disco se conservan).\n\nLa siguen compartiendo: {}.\n\nEl estado se actualiza a través de «{}», que sigue siendo un equipo remoto (no se convierte en local). Puedes seguir gestionando estos equipos desde aquí.').format(fname, names, ref.name), parent=self)
                        elif messagebox.askyesno(
                                "Carpeta quitada de este equipo",
                                _T('«{}» se ha quitado de este equipo. La siguen compartiendo: {}, pero ninguno es accesible directamente ahora.\n\n¿Añadir credenciales a uno para seguir gestionando y refrescando el estado desde aquí?').format(fname, names), parent=self):
                            _edit_node_dialog(remaining[0])
                        else:
                            self._status(_T('«{}» quitada de este equipo; el resto la sigue compartiendo.').format(fname), "#2E7D32")
                self._post(ui)
            threading.Thread(target=work, daemon=True).start()

        def _unlink_device_on_node(nid):
            """N8 — Fully UNPAIR a device from the cluster: remove its device entry on every
            other reachable node (which drops all its folder shares too). Immediate."""
            t = topo()
            n = t["nodes"].get(nid)
            if not n or n.get("is_local"):
                return
            label = n.get("label", nid[:7])
            if not messagebox.askyesno(
                    "Desvincular dispositivo",
                    _T('¿Desvincular «{}» de TODO el clúster?\n\n• Se quitará de la lista de dispositivos de cada equipo accesible, lo que deshace TODAS sus comparticiones (no solo esta carpeta).\n• Solo se rompe el emparejamiento: las carpetas siguen configuradas en cada equipo, simplemente dejan de sincronizarse con este dispositivo.\n\nEsta herramienta solo cambia la configuración de Syncthing; no ejecuta ningún borrado de archivos.').format(label), parent=self):
                return
            self._status(_T("Desvinculando «{}»…").format(label), "#555")
            member_ids = {o for e in t["edges"] if nid in e for o in e
                          if o != nid and not t["nodes"].get(o, {}).get("is_local")}
            _my_gen = self._show_gen   # bind now; ui() must not render/navigate a page we left

            def work():
                from ..renamer import unlink_device_everywhere
                # Never leave the status stuck on "Desvinculando…" if the backend raises.
                try:
                    with self._devices_lock:
                        devs = list(self.s.get("devices", []))
                    results = unlink_device_everywhere(devs, nid, member_ids=member_ids)
                except Exception as e:
                    self._post(lambda _e=e: self._status(
                        _T('No se pudo desvincular «{}»: {}').format(label, _e), "#C62828"))
                    return

                def ui():
                    if self._show_gen != _my_gen:
                        return   # left the Topology page mid-unlink; the unpair already landed
                    ok = sum(1 for _, k, _, _ in results if k)
                    bad = [(nm, m) for nm, k, m, _ in results if not k]
                    pending = [(nm, m) for nm, k, m, u in results if u]  # flag, not translated text
                    if pending:
                        # Some equipos still have the device linked and we couldn't reach
                        # them → keep it in the graph so the user can retry after adding
                        # credentials; don't claim it's fully unpaired.
                        _render()
                        names = ", ".join(nm for nm, _ in pending)
                        self._status(
                            _T('«{}»: desvinculado en {}, pero {} sin acceso aún lo tienen vinculado ({}). Añade credenciales y reintenta, o desvincúlalo en ese equipo.').format(label, ok, len(pending), names), "#C66000")
                        return
                    # The device is gone from the cluster → drop it from the graph AND from
                    # our device list so it stops showing in the Devices window. sync_orig so
                    # the applied removal doesn't linger as a phantom pending diff.
                    _remove_node(nid, sync_orig=True)
                    with self._devices_lock:
                        self.s["devices"] = [d for d in self.s.get("devices", [])
                                             if d.device_id != nid]
                        self.s.get("passive_devices", set()).discard(nid)
                        self.s["agent_devices"] = [d for d in self.s.get("agent_devices", [])
                                                   if d.device_id != nid]
                    _render()
                    if bad:
                        self._status(_T('«{}»: desvinculado en {}, {} con error ({}).').format(label, ok, len(bad), bad[0][1]), "#C66000")
                    else:
                        self._status(_T('«{}» desvinculado del clúster ({} equipo/s).').format(label, ok), "#2E7D32")
                self._post(ui)
            threading.Thread(target=work, daemon=True).start()

        def _edit_selected():
            if drag.get("sel_edge"):
                _edit_edge_dialog(drag["sel_edge"])
            elif drag["sel"]:
                _edit_node_dialog(drag["sel"])
            else:
                status_lbl.config(text="Selecciona primero un dispositivo o un enlace (clic).")

        def _confirm_destructive_delete(title, intro, path_lines, folder_name, cluster=False):
            """Modal, anti-foot-gun confirmation for a definitive delete: lists the exact
            on-disk paths, requires typing the folder name (and, cluster-wide, ticking an
            irreversibility box) before the red Delete button enables. Returns True/False."""
            dlg = tk.Toplevel(self)
            dlg.title(title)
            dlg.configure(bg="white")
            dlg.transient(self)
            dlg.grab_set()
            self._center_dialog(dlg)
            tk.Label(dlg, text="⚠ " + title, bg="white", fg="#C62828",
                     font=(_FONT, 11, "bold")).pack(anchor="w", padx=16, pady=(12, 4))
            tk.Label(dlg, text=intro, bg="white", justify="left", wraplength=520,
                     font=(_FONT, 9)).pack(anchor="w", padx=16)
            tk.Label(dlg, text="Se borrará en disco:", bg="white", fg="#555",
                     font=(_FONT, 8, "bold")).pack(anchor="w", padx=16, pady=(8, 0))
            box = scrolledtext.ScrolledText(dlg, height=min(8, max(2, len(path_lines))),
                                            font=(_MONO, 8), wrap=tk.NONE, relief=tk.FLAT,
                                            bg="#FBE9E7")
            for ln in path_lines:
                box.insert(tk.END, ln + "\n")
            box.config(state="disabled")
            box.pack(fill=tk.X, padx=16, pady=(2, 4))
            tk.Label(dlg, text=_T('Para confirmar, escribe el nombre de la carpeta:  «{}»').format(folder_name),
                     bg="white", font=(_FONT, 9)).pack(anchor="w", padx=16, pady=(6, 0))
            name_var = tk.StringVar()
            ent = ttk.Entry(dlg, textvariable=name_var, width=42)
            ent.pack(anchor="w", padx=16)
            chk_var = tk.BooleanVar(value=False)
            if cluster:
                tk.Checkbutton(dlg, variable=chk_var, bg="white", anchor="w",
                               justify="left", wraplength=500,
                               text="Entiendo que esto borra los archivos en TODOS los equipos "
                                    "y es IRREVERSIBLE.").pack(anchor="w", padx=12, pady=(6, 0))
            state = {"ok": False}
            btnf = tk.Frame(dlg, bg="white")
            btnf.pack(fill=tk.X, padx=16, pady=12)

            def _do():
                state["ok"] = True
                dlg.destroy()
            del_btn = tk.Button(btnf, text="🗑 Borrar definitivamente", fg="white", bg="#C62828",
                                activebackground="#B71C1C", activeforeground="white",
                                relief="raised", state="disabled", command=_do)
            del_btn.pack(side=tk.RIGHT)
            ttk.Button(btnf, text="Cancelar", command=dlg.destroy).pack(side=tk.RIGHT, padx=(0, 6))

            def _upd(*_):
                ok = (name_var.get().strip() == folder_name
                      and (chk_var.get() if cluster else True))
                del_btn.config(state="normal" if ok else "disabled")
            name_var.trace_add("write", _upd)
            if cluster:
                chk_var.trace_add("write", _upd)
            ent.focus_set()
            dlg.wait_window()
            return state["ok"]

        def _delete_folder_on_node(nid):
            """Advanced + DESTRUCTIVE: delete the folder on ONE device — Syncthing config +
            on-disk data. Local via the filesystem; remote via SSH/WinRM."""
            t = topo()
            n = t["nodes"].get(nid)
            if not n:
                return
            folder = self.s["folder"]
            fname = folder.label or folder.id
            label = n.get("label", nid[:7])
            with self._devices_lock:
                dev = next((x for x in self.s.get("devices", []) if x.device_id == nid), None)
            if not dev:
                messagebox.showwarning("Borrar carpeta", "No se encontró el dispositivo.",
                                       parent=self)
                return
            from ..renamer import is_protected_delete_path
            if dev.folder_path and is_protected_delete_path(dev.folder_path, dev.os_type):
                messagebox.showerror(
                    "Ruta protegida",
                    _T('La ruta «{}» es del sistema; por seguridad no se borrará.').format(dev.folder_path),
                    parent=self)
                return
            where = "ESTE equipo (local)" if dev.is_local else f"«{label}» (remoto)"
            if not _confirm_destructive_delete(
                    "Borrar la carpeta definitivamente",
                    _T('Vas a BORRAR la carpeta «{}» en {}: se quitará de Syncthing Y se borrarán los archivos en disco. Es IRREVERSIBLE. (El resto de equipos no se tocan; usa la opción del clúster para eso.)').format(fname, where),
                    [f"{label}:  {dev.folder_path or '(ruta desconocida)'}"], fname):
                return
            self._status(_T('Borrando «{}» en «{}»…').format(fname, label), "#C62828")
            _my_gen = self._show_gen   # bind now; ui() must not render/navigate a page we left

            def work():
                from ..renamer import delete_folder_on_device
                # Destructive op: never leave the status stuck on "Borrando…" with no feedback if
                # the backend raises unexpectedly (it normally returns a result, but guard anyway).
                try:
                    r = delete_folder_on_device(dev, folder.id, delete_data=True)
                except Exception as e:
                    self._post(lambda _e=e: self._status(
                        _T('No se pudo borrar en «{}»: {}').format(label, _e), "#C62828"))
                    return

                def ui():
                    if self._show_gen != _my_gen:
                        # Left the Topology page mid-delete. The delete (config+disk) already
                        # happened; if it was the last member, still forget the snapshot so a
                        # same-id re-create can't resurrect ghosts. Skip render/navigation/reset.
                        # NOTE: the stale path never calls _remove_node, so nid is still in the
                        # graph — detect "last member" as "nid is the only node left".
                        if r.ok and set(t["nodes"]) <= {nid}:
                            appconfig.delete_topology_snapshot(folder.id)
                            _clear_folder_pending_unshare(folder.id)
                        return
                    if r.ok:
                        _clear_pending_unshare(folder.id, nid)
                        _remove_node(nid, allow_local=dev.is_local, sync_orig=True)
                        if dev.is_local:
                            with self._devices_lock:
                                self.s["devices"] = [d for d in self.s.get("devices", [])
                                                     if d.device_id != nid]
                            # folder gone locally → refresh re-anchors to a remote (if any)
                            self.s["local_folder_gone"] = bool(t["nodes"])
                        if not t["nodes"]:
                            # That was the LAST member → the folder is gone cluster-wide. Forget
                            # its snapshot + wipe folder state (same as the cluster-delete button)
                            # so a same-id re-create can't resurrect ghosts; back to selection.
                            appconfig.delete_topology_snapshot(folder.id)
                            _clear_folder_pending_unshare(folder.id)
                            self._reset_folder_scoped_state()
                            messagebox.showinfo(
                                "Borrar carpeta",
                                _T('«{}» borrada en «{}». Era el último equipo que la compartía.\n\nVolviendo a la selección de carpeta.').format(fname, label),
                                parent=self)
                            self._show(1)
                            return
                        _render()
                        self._status(_T('«{}» borrada en «{}» (Syncthing + disco).').format(fname, label),
                                     "#2E7D32")
                    else:
                        _render()
                        self._status(_T('No se pudo borrar en «{}»: {}').format(label, r.message), "#C62828")
                        messagebox.showerror("Borrar carpeta", r.message, parent=self)
                self._post(ui)
            threading.Thread(target=work, daemon=True).start()

        def _delete_folder_cluster():
            """Advanced + DESTRUCTIVE: delete the folder on EVERY member — Syncthing + disk.
            Only reachable when all members can be wiped on disk (the button is hidden
            otherwise), but we re-check here as a guard."""
            t = topo()
            if not t or not t["nodes"]:
                return
            folder = self.s["folder"]
            fname = folder.label or folder.id
            member_ids = list(t["nodes"].keys())
            from ..renamer import is_protected_delete_path
            with self._devices_lock:
                dm = {d.device_id: d for d in self.s.get("devices", [])}
            lines, blocked = [], []
            for nid in member_ids:
                lbl = t["nodes"][nid].get("label", nid[:7])
                d = dm.get(nid)
                if not d or not (d.is_local or d.ssh_reachable or d.winrm_reachable):
                    blocked.append(lbl)
                elif d.folder_path and is_protected_delete_path(d.folder_path, d.os_type):
                    blocked.append(_T('{} (ruta protegida)').format(lbl))
                else:
                    lines.append(f"{lbl}:  {d.folder_path or '(ruta desconocida)'}")
            if blocked:
                messagebox.showwarning(
                    "Borrar en todo el clúster",
                    _T("No se puede borrar en disco en: {}.\nAñade SSH/WinRM o usa la opción por equipo.").format(
                        ", ".join(blocked)), parent=self)
                return
            if not _confirm_destructive_delete(
                    "Borrar la carpeta en TODO el clúster",
                    _T('Vas a BORRAR la carpeta «{}» en TODOS los equipos: se quitará de Syncthing Y se borrarán los archivos en disco en cada uno. IRREVERSIBLE.').format(fname),
                    lines, fname, cluster=True):
                return
            self._status(_T('Borrando «{}» en todo el clúster…').format(fname), "#C62828")
            _my_gen = self._show_gen   # bind now; ui() must not render/navigate a page we left

            def work():
                from ..renamer import delete_folder_everywhere
                with self._devices_lock:
                    devs = list(self.s.get("devices", []))
                # Destructive cluster-wide op: guard against an unexpected raise leaving the status
                # frozen on "Borrando…" (the user couldn't tell what landed on a IRREVERSIBLE op).
                try:
                    results = delete_folder_everywhere(devs, folder.id, member_ids=set(member_ids),
                                                       delete_data=True)
                except Exception as e:
                    self._post(lambda _e=e: self._status(
                        _T('No se pudo borrar en «{}»: {}').format(fname, _e), "#C62828"))
                    return

                def ui():
                    if self._show_gen != _my_gen:
                        # Left the page mid cluster-delete. The folder is gone everywhere; still
                        # forget its snapshot so a same-id re-create can't resurrect ghosts, then
                        # skip the navigation/reset that would disrupt the page they moved to.
                        appconfig.delete_topology_snapshot(folder.id)
                        _clear_folder_pending_unshare(folder.id)
                        return
                    okc = sum(1 for _, k, _, _ in results if k)
                    badc = [(nm, m) for nm, k, m, _ in results if not k]
                    # Disk-delete SKIPPED (removed from Syncthing but the files survive on disk):
                    # the backend flags it (disk_not_deleted) so it isn't counted as a clean
                    # success. Surface it loudly — a cluster-delete that leaves files behind must
                    # never look like everything went fine. (Flag, not translated-text match.)
                    disk_left = [(nm, m) for nm, k, m, d in results if k and d]
                    self.s["local_folder_gone"] = False
                    # The folder is gone cluster-wide → forget its persisted topology snapshot
                    # AND wipe the in-memory folder state. Otherwise re-creating a folder with
                    # the SAME id reloads the stale snapshot, resurrecting these now-deleted
                    # nodes/links — the blank preview, ghost Pi node and GET-404-on-apply.
                    appconfig.delete_topology_snapshot(folder.id)
                    _clear_folder_pending_unshare(folder.id)
                    self._reset_folder_scoped_state()
                    extra = (_T('\n{} con error: {}').format(len(badc), badc[0][1]) if badc else "")
                    if disk_left:
                        _names = ", ".join(nm for nm, _ in disk_left)
                        extra += _T('\n⚠ OJO: en {} equipo(s) se quitó de Syncthing pero los '
                                    'archivos en disco NO se borraron ({}). Bórralos a mano o '
                                    'revisa el acceso.').format(len(disk_left), _names)
                    _box = messagebox.showwarning if (badc or disk_left) else messagebox.showinfo
                    _box(
                        "Borrar en todo el clúster",
                        _T('«{}» borrada en {} equipo(s).{}\n\nVolviendo a la selección de carpeta.').format(fname, okc, extra), parent=self)
                    self._show(1)
                self._post(ui)
            threading.Thread(target=work, daemon=True).start()

        def _show_pending_dialog():
            """Feature: accept INCOMING requests the local node received — devices that tried
            to connect (add them to config) and folders offered by known devices (create them
            locally at a chosen path, shared with the offerer). Read/acted via the local API."""
            client = self.s.get("client")
            if not client:
                messagebox.showinfo("Peticiones entrantes",
                                    "Sin conexión con el Syncthing local.", parent=self)
                return
            my_id = self.s.get("my_id", "")
            dlg = tk.Toplevel(self)
            dlg.title("Peticiones entrantes")
            dlg.configure(bg="white")
            dlg.transient(self)
            dlg.grab_set()
            self._center_dialog(dlg)
            tk.Label(dlg, text="Peticiones entrantes", bg="white",
                     font=(_FONT, 11, "bold")).pack(anchor="w", padx=16, pady=(12, 2))
            tk.Label(dlg, text="Dispositivos que han intentado conectar y carpetas que te "
                               "ofrecen equipos ya conocidos. Aceptar un dispositivo lo añade a "
                               "tu configuración; aceptar una carpeta la crea aquí en la ruta "
                               "que elijas.", bg="white", fg="#888", font=(_FONT, 8),
                     wraplength=520, justify="left").pack(anchor="w", padx=16)
            body = tk.Frame(dlg, bg="white")
            body.pack(fill=tk.BOTH, expand=True, padx=16, pady=(8, 4))
            btnf = tk.Frame(dlg, bg="white")
            btnf.pack(fill=tk.X, padx=16, pady=10)
            ttk.Button(btnf, text="Cerrar", command=dlg.destroy).pack(side=tk.RIGHT)

            def _refresh():
                def work():
                    try:
                        pdev = client.get_pending_devices()
                        pfold = client.get_pending_folders()
                    except Exception:
                        pdev, pfold = {}, {}
                    self._post(lambda: _render(pdev, pfold))
                threading.Thread(target=work, daemon=True).start()

            def _act(fn, ok_msg):
                """Run a client call off-thread, then refresh the list + status."""
                def work():
                    try:
                        fn()
                        err = None
                    except Exception as e:
                        err = str(e)

                    def ui():
                        self._status(ok_msg if not err else _T('Error: {}').format(err),
                                     "#2E7D32" if not err else "#C62828")
                        if dlg.winfo_exists():
                            _refresh()
                    self._post(ui)
                threading.Thread(target=work, daemon=True).start()

            def _accept_folder(fid, info):
                # info: {label?, offeredBy: {deviceID: {label, ...}}} — pick the offerer.
                offered = info.get("offeredBy") or {}
                dev_id = next(iter(offered), "")
                label = (offered.get(dev_id, {}) or {}).get("label") or info.get("label") or fid
                path = filedialog.askdirectory(
                    title=_T('Carpeta local para «{}» ({})').format(label, fid), parent=dlg)
                if not path:
                    return
                cfg = {"id": fid, "label": label, "path": path, "type": "sendreceive",
                       "devices": [{"deviceID": d} for d in ({my_id, dev_id} - {""})]}
                _act(lambda: (client.create_folder(cfg),
                              client.dismiss_pending_folder(fid, dev_id)),
                     _T('Carpeta «{}» aceptada y creada en {}.').format(label, path))

            def _render(pdev, pfold):
                for w in body.winfo_children():
                    w.destroy()
                if not pdev and not pfold:
                    tk.Label(body, text="No hay peticiones entrantes.", bg="white",
                             fg="#2E7D32").pack(anchor="w")
                    return
                if pdev:
                    tk.Label(body, text="Dispositivos:", bg="white", fg="#555",
                             font=(_FONT, 9, "bold")).pack(anchor="w", pady=(2, 0))
                for did, info in pdev.items():
                    nm = (info or {}).get("name") or did[:7]
                    addr = (info or {}).get("address", "")
                    row = tk.Frame(body, bg="white")
                    row.pack(fill=tk.X, pady=1)
                    tk.Label(row, text=f"  {nm}  ·  {did[:7]}…  {addr}", bg="white",
                             font=(_FONT, 8)).pack(side=tk.LEFT)
                    ttk.Button(row, text="Descartar", width=10,
                               command=lambda d=did: _act(
                                   lambda: client.dismiss_pending_device(d),
                                   "Petición descartada.")).pack(side=tk.RIGHT)
                    ttk.Button(row, text="Aceptar", width=10,
                               command=lambda d=did, name=nm: _act(
                                   lambda: client.add_device(d, name),
                                   _T('Dispositivo «{}» añadido.').format(name))).pack(side=tk.RIGHT, padx=(0, 4))
                if pfold:
                    tk.Label(body, text="Carpetas ofrecidas:", bg="white", fg="#555",
                             font=(_FONT, 9, "bold")).pack(anchor="w", pady=(8, 0))
                for fid, info in pfold.items():
                    offered = (info or {}).get("offeredBy") or {}
                    dev_id = next(iter(offered), "")
                    flabel = (offered.get(dev_id, {}) or {}).get("label") or fid
                    row = tk.Frame(body, bg="white")
                    row.pack(fill=tk.X, pady=1)
                    tk.Label(row, text=_T('  {}  ·  {}  (de {}…)').format(flabel, fid, dev_id[:7]), bg="white",
                             font=(_FONT, 8)).pack(side=tk.LEFT)
                    ttk.Button(row, text="Descartar", width=10,
                               command=lambda f=fid, d=dev_id: _act(
                                   lambda: client.dismiss_pending_folder(f, d),
                                   "Oferta descartada.")).pack(side=tk.RIGHT)
                    ttk.Button(row, text="Aceptar…", width=10,
                               command=lambda f=fid, i=info: _accept_folder(f, i)
                               ).pack(side=tk.RIGHT, padx=(0, 4))
            _refresh()

        def _pause_folder_on_node(nid, paused):
            """Pause/resume THIS folder on a node (local or reachable remote) by toggling its
            `paused` flag via the existing folder-config apply (API/SSH/WinRM)."""
            t = topo()
            n = t["nodes"].get(nid)
            if not n:
                return
            folder = self.s["folder"]
            fname = folder.label or folder.id
            label = n.get("label", nid[:7])
            with self._devices_lock:
                dev = next((x for x in self.s.get("devices", []) if x.device_id == nid), None)
            if not dev:
                messagebox.showwarning("Pausar carpeta", "No se encontró el dispositivo.",
                                       parent=self)
                return
            self._status((_T("Pausando") if paused else _T("Reanudando")) +
                         _T(' «{}» en «{}»…').format(fname, label), "#555")

            def work():
                from ..renamer import apply_folder_cfg_on_device
                # Never leave the status stuck on "Pausando…/Reanudando…" if the backend raises.
                try:
                    r = apply_folder_cfg_on_device(dev, folder.id, {"paused": bool(paused)})
                except Exception as e:
                    self._post(lambda _e=e: self._status(
                        _T('No se pudo: {}').format(_e), "#C62828"))
                    return

                def ui():
                    if r.ok:
                        self._status(f"«{fname}» " + ("pausada" if paused else "reanudada") +
                                     _T(' en «{}».').format(label), "#2E7D32")
                    else:
                        self._status(_T('No se pudo: {}').format(r.message), "#C62828")
                self._post(ui)
            threading.Thread(target=work, daemon=True).start()

        def _edit_ignores_on_node(nid):
            """Edit a folder's .stignore (exclude patterns) on a node, over its live channel."""
            t = topo()
            n = t["nodes"].get(nid)
            if not n:
                return
            folder = self.s["folder"]
            label = n.get("label", nid[:7])
            with self._devices_lock:
                dev = next((x for x in self.s.get("devices", []) if x.device_id == nid), None)
            if not dev:
                return
            dlg = tk.Toplevel(self)
            dlg.title(f"Editar .stignore — {label}")
            dlg.configure(bg="white")
            dlg.transient(self)
            dlg.grab_set()
            self._center_dialog(dlg)
            tk.Label(dlg, text=_T('Patrones de exclusión (.stignore) — «{}»').format(label), bg="white",
                     font=(_FONT, 10, "bold")).pack(anchor="w", padx=14, pady=(12, 2))
            tk.Label(dlg, text="Un patrón por línea (p. ej. *.tmp, /Cache, !importante.txt). "
                               "Se aplican a la carpeta en ESTE equipo.",
                     bg="white", fg="#888", font=(_FONT, 8), wraplength=460,
                     justify="left").pack(anchor="w", padx=14)
            txt = scrolledtext.ScrolledText(dlg, height=12, width=56, font=(_MONO, 9),
                                            wrap=tk.NONE)
            txt.pack(fill=tk.BOTH, expand=True, padx=14, pady=(6, 4))
            txt.insert("1.0", _T("Cargando…"))
            txt.config(state="disabled")
            btnf = tk.Frame(dlg, bg="white")
            btnf.pack(fill=tk.X, padx=14, pady=10)
            save_btn = ttk.Button(btnf, text="Guardar")
            save_btn.pack(side=tk.RIGHT)
            save_btn.config(state="disabled")
            ttk.Button(btnf, text="Cancelar", command=dlg.destroy).pack(side=tk.RIGHT, padx=(0, 6))

            def _load():
                from ..renamer import get_ignores_on_device
                # Never leave the dialog stuck on "Cargando…" with Guardar disabled: surface an
                # unexpected transport error and make the editor usable (empty + editable).
                try:
                    pats = get_ignores_on_device(dev, folder.id)
                except Exception as e:
                    def _err(_e=e):
                        if not dlg.winfo_exists():
                            return
                        txt.config(state="normal")
                        txt.delete("1.0", tk.END)
                        save_btn.config(state="normal")
                        self._status(_T('No se pudieron leer las exclusiones de «{}».').format(label)
                                     + f" ({_e})", "#C62828")
                    self._post(_err)
                    return

                def ui():
                    if not dlg.winfo_exists():
                        return
                    txt.config(state="normal")
                    txt.delete("1.0", tk.END)
                    if pats is None:
                        txt.insert("1.0", "")
                        self._status(_T('No se pudieron leer las exclusiones de «{}».').format(label), "#C66000")
                    else:
                        txt.insert("1.0", "\n".join(pats))
                    save_btn.config(state="normal")
                self._post(ui)
            threading.Thread(target=_load, daemon=True).start()

            def _save():
                patterns = txt.get("1.0", "end-1c").split("\n")
                # Drop trailing blank lines but keep meaningful empties/comments in between.
                while patterns and not patterns[-1].strip():
                    patterns.pop()
                save_btn.config(state="disabled")
                self._status(_T('Guardando exclusiones en «{}»…').format(label), "#555")

                def work():
                    from ..renamer import set_ignores_on_device
                    try:
                        r = set_ignores_on_device(dev, folder.id, patterns)
                    except Exception as e:
                        def _err(_e=e):
                            if dlg.winfo_exists():
                                save_btn.config(state="normal")
                            self._status(_T('No se pudo guardar: {}').format(_e), "#C62828")
                        self._post(_err)
                        return

                    def ui():
                        if r.ok:
                            self._status(_T('Exclusiones guardadas en «{}».').format(label), "#2E7D32")
                            if dlg.winfo_exists():
                                dlg.destroy()
                        else:
                            self._status(_T('No se pudo guardar: {}').format(r.message), "#C62828")
                            if dlg.winfo_exists():
                                save_btn.config(state="normal")
                    self._post(ui)
                threading.Thread(target=work, daemon=True).start()
            save_btn.config(command=_save)

        def _node_menu(nid, ev):
            # Right-click on a node. No "Rol" here: direction is now edited per-link
            # (right-click the arrow / ✏ Editar seleccionado on an edge).
            t = topo()
            n = t["nodes"][nid]
            menu = tk.Menu(self, tearoff=0)
            connmenu = tk.Menu(menu, tearoff=0)
            others = [(oid, on) for oid, on in t["nodes"].items() if oid != nid]
            if others:
                for oid, on in others:
                    linked = frozenset((nid, oid)) in t["edges"]
                    connmenu.add_command(label=("✓ " if linked else "    ") + on["label"],
                                         command=lambda oo=oid, nn=nid: (_toggle_edge(nn, oo), _render()))
                menu.add_cascade(label="Conectar / desconectar con", menu=connmenu)
            menu.add_separator()
            menu.add_command(label="Editar dispositivo…", command=lambda: _edit_node_dialog(nid))
            menu.add_separator()
            # Merged action (P5): quitar un nodo de la topología = dejar de compartir la
            # carpeta con/en él, de inmediato. Disponible también para el nodo local (quita
            # la carpeta solo de este equipo; el resto del clúster la sigue sincronizando).
            menu.add_command(label="🚫 Dejar de compartir / quitar de la topología…",
                             command=lambda: _unshare_folder_on_node(nid))
            # Unlinking a device from the WHOLE cluster (undoes all its shares, not just this
            # folder) is critical → only offered with advanced options enabled.
            if not n["is_local"] and self.s.get("advanced"):
                menu.add_command(label="🔗✖ Desvincular dispositivo del clúster…",
                                 command=lambda: _unlink_device_on_node(nid))
            # Per-node folder management (needs a live channel: local / API / SSH / WinRM).
            with self._devices_lock:
                _nd = next((x for x in self.s.get("devices", []) if x.device_id == nid), None)
            menu.add_separator()
            if n["is_local"] or (_nd and _device_kind(_nd) == "ok"):
                pmenu = tk.Menu(menu, tearoff=0)
                pmenu.add_command(label="⏸ Pausar la carpeta aquí",
                                  command=lambda: _pause_folder_on_node(nid, True))
                pmenu.add_command(label="▶ Reanudar la carpeta aquí",
                                  command=lambda: _pause_folder_on_node(nid, False))
                menu.add_cascade(label="Pausar / reanudar la carpeta", menu=pmenu)
                menu.add_command(label="Editar .stignore (exclusiones)…",
                                 command=lambda: _edit_ignores_on_node(nid))
            else:
                # Offline / no access: show these DISABLED with the reason (instead of hiding
                # them) so they're discoverable and it's clear WHY they're unavailable.
                menu.add_command(state="disabled",
                                 label="Pausar / reanudar la carpeta  —  requiere acceso a este equipo")
                menu.add_command(state="disabled",
                                 label="Editar .stignore  —  requiere acceso a este equipo")
            # DESTRUCTIVE (advanced only): delete the folder definitively on this device —
            # from Syncthing AND on disk. Shown but DISABLED (with the reason in the label)
            # when on-disk deletion isn't possible here (needs local FS or SSH/WinRM; the
            # Syncthing API alone can't delete data).
            if self.s.get("advanced"):
                with self._devices_lock:
                    _dev = next((x for x in self.s.get("devices", [])
                                 if x.device_id == nid), None)
                _can = bool(_dev and (_dev.is_local or _dev.ssh_reachable
                                      or _dev.winrm_reachable))
                menu.add_separator()
                if _can:
                    menu.add_command(
                        label="⚠ Borrar definitivamente la carpeta en este equipo (Syncthing + disco)…",
                        command=lambda: _delete_folder_on_node(nid))
                else:
                    menu.add_command(
                        label="⚠ Borrar definitivamente la carpeta… (requiere SSH/WinRM)",
                        state="disabled")
            try:
                menu.tk_popup(ev.x_root, ev.y_root)
            finally:
                menu.grab_release()

        def _edge_menu(e, ev):
            locked = self.s.setdefault("topology_locked", set())
            t = topo()
            ids = sorted(e)
            la = t["nodes"].get(ids[0], {}).get("label", ids[0][:7])
            lb = t["nodes"].get(ids[1], {}).get("label", ids[1][:7])
            menu = tk.Menu(self, tearoff=0)
            menu.add_command(label=_T("Editar enlace «{}» — «{}»…").format(la, lb),
                             command=lambda: _edit_edge_dialog(e))
            if e in locked:
                menu.add_command(
                    label="🔓 Permitir editar este enlace",
                    command=lambda: (_push_undo(), locked.discard(e),
                                     status_lbl.config(text="Enlace desbloqueado."), _render()))
            else:
                menu.add_command(
                    label="🔒 No editar este enlace",
                    command=lambda: (_push_undo(), locked.add(e),
                                     status_lbl.config(text="Enlace bloqueado: no se "
                                                            "modificará al aplicar."), _render()))
            menu.add_separator()
            menu.add_command(label="Quitar enlace",
                             command=lambda: (_toggle_edge(ids[0], ids[1]), _render()))
            try:
                menu.tk_popup(ev.x_root, ev.y_root)
            finally:
                menu.grab_release()

        def _show_context_menu(ev):
            nid = _node_at(ev.x, ev.y)
            if nid:
                drag["sel"], drag["sel_edge"] = nid, None
                _render()
                _node_menu(nid, ev)
                return
            e = _edge_at(ev.x, ev.y)
            if e:
                _select_edge(e)
                _edge_menu(e, ev)

        def _validate_node_path(path, os_type):
            """Per-OS sanity check of a device's folder path. Tilde-aware (~/x is OK);
            only the final component is checked for OS-forbidden names/characters."""
            if not path:
                return []
            from ..validation import validate_dir_name
            leaf = path.rstrip("/\\").replace("\\", "/").split("/")[-1]
            if not leaf or leaf == "~":
                return []
            return validate_dir_name(leaf, os_type)

        def _endpoint_port(url) -> int:
            """Best-effort GUI/API port from a URL string (defaults to 8384)."""
            if url:
                host = url.rstrip("/").split("//")[-1].split("/")[0]
                m = re.search(r":(\d+)$", host)
                if m:
                    return int(m.group(1))
            return 8384

        def _edit_node_dialog(nid):
            import dataclasses as _dc
            t = topo()
            node = t["nodes"].get(nid)
            if not node:
                return
            with self._devices_lock:
                dev = next((x for x in self.s.get("devices", []) if x.device_id == nid), None)
            dlg = tk.Toplevel(self)
            dlg.title(f"Editar — {node['label']}")
            dlg.configure(bg="white")
            dlg.grab_set()
            self._center_dialog(dlg)
            tk.Label(dlg, text=f"Editar: {node['label']}", bg="white",
                     font=(_FONT, 10, "bold")).pack(anchor="w", padx=14, pady=(12, 4))

            # Device ID — read-only but selectable/copyable, handy to have at a glance.
            idf = tk.Frame(dlg, bg="white")
            idf.pack(fill=tk.X, padx=14, pady=(0, 4))
            tk.Label(idf, text="Device ID:", bg="white", width=8, anchor="e").pack(side=tk.LEFT)
            _ide = ttk.Entry(idf, width=44)
            _ide.insert(0, nid)
            _ide.config(state="readonly")
            _ide.pack(side=tk.LEFT, padx=(4, 0))

            # Foolproof notice: anything configured for an unreachable device is queued, not
            # applied now — applied later via passive exploration (on reconnect) or an agent.
            _reach = bool(node.get("is_local") or (dev and _device_kind(dev) == "ok"))
            if not _reach:
                tk.Label(dlg, text=("⚠ Equipo no accesible ahora. Lo que cambies aquí (rol, "
                                    "enlaces, avanzado) NO se aplica ya: queda pendiente y se "
                                    "aplicará cuando reconecte (exploración pasiva) o con un agente."),
                         bg="#FFF3E0", fg="#C66000", font=(_FONT, 8), wraplength=440,
                         justify="left").pack(fill=tk.X, anchor="w", padx=14, pady=(2, 6))

            # Role is DERIVED from the link directions (read-only) — you edit it by editing
            # the arrows, not here.
            rf = tk.Frame(dlg, bg="white")
            rf.pack(anchor="w", padx=14)
            tk.Label(rf, text="Rol:", bg="white", width=8, anchor="e").pack(side=tk.LEFT)
            _role_txt = (_ROLE_LABELS.get(node.get("role"), node.get("role", "—"))
                         if node.get("role_known", True)
                         else ("nuevo dispositivo (rol sin declarar)" if node.get("is_new")
                               else "desconocido (offline)"))
            tk.Label(rf, text=_T(_role_txt) + _T("  · derivado de los enlaces"), bg="white",
                     fg="#555", font=(_FONT, 9)).pack(side=tk.LEFT, padx=(4, 0))

            fields: dict = {}
            via_v = None          # passive/agent selector (set for non-local nodes)
            os_v = None           # OS override for unreachable nodes (agent/passive)
            probe_lbl = None
            client = self.s.get("client")
            _is_offline = bool(not node["is_local"] and not (dev and _device_kind(dev) == "ok"))
            _is_new = bool(node.get("is_new"))

            # «Examinar» (listar carpetas del dispositivo) solo es fiable si su API responde
            # DIRECTAMENTE desde aquí; por SSH/WinRM o sin credenciales no funciona, así que el
            # botón solo aparece cuando es seguro que funcionará.
            def _can_browse():
                return bool(dev and dev.api_reachable and dev.api_url and dev.api_key)

            def _browse_into(var):
                if _can_browse():
                    _browse_dialog(dev.api_url, dev.api_key, var.get().strip() or "~",
                                   lambda p: var.set(p))

            if _is_new:
                # A brand-new, not-yet-created device has NO current path on disk — the folder
                # will be CREATED at the path chosen here. So show ONLY "Nueva ruta", bound
                # straight to the node's creation path (node["path"]); no "current path", and no
                # rename override (the override only feeds the rename pipeline, not creation —
                # using it here is exactly what made the folder appear at the wrong path).
                path_v = None
                npf = tk.Frame(dlg, bg="white")
                npf.pack(anchor="w", padx=14, pady=(6, 0))
                tk.Label(npf, text="Nueva ruta:", bg="white", width=10, anchor="e").pack(side=tk.LEFT)
                newpath_v = tk.StringVar(value=node.get("path") or "")
                ttk.Entry(npf, textvariable=newpath_v, width=30).pack(side=tk.LEFT, padx=(4, 0))
                if _can_browse():
                    ttk.Button(npf, text="Examinar…", width=10,
                               command=lambda: _browse_into(newpath_v)).pack(side=tk.LEFT, padx=(4, 0))
                tk.Label(npf, text="(se creará la carpeta aquí)", bg="white", fg="#888",
                         font=(_FONT, 8)).pack(side=tk.LEFT, padx=(6, 0))
            else:
                # Current path + per-device NEW path for an EXISTING node.
                # • LOCAL: current path is authoritative (read-only), but you can still give this
                #   machine its own NEW path independently of the global rename target.
                # • OFFLINE: the current path is usually unknown — auto-detected later (passive
                #   exploration / agent) by matching THIS folder's id against the device's config.
                pf = tk.Frame(dlg, bg="white")
                pf.pack(anchor="w", padx=14, pady=(6, 0))
                tk.Label(pf, text="Ruta actual:", bg="white", width=10, anchor="e").pack(side=tk.LEFT)
                path_v = tk.StringVar(value=node.get("path")
                                      or (folder.path if node["is_local"] else (dev.folder_path if dev else ""))
                                      or "")
                _path_ent = ttk.Entry(pf, textvariable=path_v, width=30,
                                      state=("readonly" if node["is_local"] else "normal"))
                _path_ent.pack(side=tk.LEFT, padx=(4, 0))
                if not node["is_local"] and _can_browse():
                    ttk.Button(pf, text="Examinar…", width=10,
                               command=lambda: _browse_into(path_v)).pack(side=tk.LEFT, padx=(4, 0))
                if node["is_local"]:
                    tk.Label(pf, text="(este equipo)", bg="white", fg="#888",
                             font=(_FONT, 8)).pack(side=tk.LEFT, padx=(6, 0))
                elif _is_offline:
                    tk.Label(pf, text="(se autodetecta al reconectar)", bg="white", fg="#888",
                             font=(_FONT, 8)).pack(side=tk.LEFT, padx=(6, 0))

                # Per-device NEW path/name (B4): empty = use the global rename target. Set it to
                # give THIS device a different on-disk name/path (applied directly if reachable,
                # else via agent / passive). Validated by the device's OS.
                _ov0 = (self.s.get("path_overrides", {}) or {}).get(nid, "")
                npf = tk.Frame(dlg, bg="white")
                npf.pack(anchor="w", padx=14, pady=(4, 0))
                tk.Label(npf, text="Nueva ruta:", bg="white", width=10, anchor="e").pack(side=tk.LEFT)
                newpath_v = tk.StringVar(value=_ov0)
                ttk.Entry(npf, textvariable=newpath_v, width=30).pack(side=tk.LEFT, padx=(4, 0))
                _np_hint = tk.Label(npf, text="", bg="white", fg="#888", font=(_FONT, 8))
                _np_hint.pack(side=tk.LEFT, padx=(6, 0))

                def _np_hint_update(*_):
                    _np_hint.config(text="(sin cambios — usa la ruta/nombre global)"
                                    if not newpath_v.get().strip() else "(ruta propia de este equipo)")
                newpath_v.trace_add("write", _np_hint_update)
                _np_hint_update()

            if not node["is_local"]:
                ttk.Separator(dlg, orient="horizontal").pack(fill=tk.X, padx=14, pady=(8, 4))
                tk.Label(dlg, text="Acceso (para configurarlo sin aceptar):", bg="white",
                         fg="#555", font=(_FONT, 8, "bold")).pack(anchor="w", padx=14)
                grid = tk.Frame(dlg, bg="white")
                grid.pack(fill=tk.X, padx=14, pady=(2, 0))
                rows = [("IP / Host:", "ip", (dev.ip if dev else "") or "", ""),
                        ("Usuario SSH:", "ssh_user", (dev.ssh_user if dev else "") or "", ""),
                        ("Clave SSH:", "ssh_key", (dev.ssh_key_path if dev else "") or "", ""),
                        ("Contraseña SSH:", "ssh_password", (dev.ssh_password if dev else "") or "", "●"),
                        ("Puerto SSH:", "ssh_port", str(dev.ssh_port if dev else 22), ""),
                        ("Usuario WinRM:", "winrm_user", (dev.winrm_user if dev else "") or "", ""),
                        ("Contraseña WinRM:", "winrm_password", (dev.winrm_password if dev else "") or "", "●"),
                        ("Puerto WinRM:", "winrm_port", str(dev.winrm_port if dev else 5985), ""),
                        ("API Key:", "api_key", (dev.api_key if dev else "") or "", "●"),
                        # API URL — now editable (O5). Default to the discovered endpoint, or a
                        # LAN URL built from the IP. Leave blank to let probing derive it.
                        ("API URL:", "api_url",
                         (dev.api_url if dev else "") or "", "")]
                for i, (lbl, key, val, show) in enumerate(rows):
                    tk.Label(grid, text=lbl, bg="white", anchor="e", width=16).grid(
                        row=i, column=0, sticky="e", pady=1)
                    v = tk.StringVar(value=val)
                    ent = ttk.Entry(grid, textvariable=v, width=28, show=show)
                    ent.grid(row=i, column=1, sticky="w", padx=(8, 0))
                    if show:  # 👁 reveal/hide toggle for masked (password / API key) fields
                        tk.Button(grid, text="👁", font=(_FONT, 8), relief="flat", bg="white",
                                  cursor="hand2",
                                  command=lambda e=ent: e.config(show="" if e.cget("show") else "●")
                                  ).grid(row=i, column=2, padx=(2, 0))
                    elif key == "ssh_key":  # «…» examinar clave privada (paridad con Dispositivos)
                        ttk.Button(grid, text="…", width=3,
                                   command=lambda vv=v: vv.set(
                                       filedialog.askopenfilename(title="Clave SSH privada")
                                       or vv.get())
                                   ).grid(row=i, column=2, padx=(2, 0))
                    fields[key] = v
                tk.Label(grid, text="Syncthing escucha la API en localhost salvo que la GUI esté "
                                    "expuesta a la LAN (entonces usa http://IP:8384).",
                         bg="white", fg="#888", font=(_FONT, 8), wraplength=380,
                         justify="left").grid(row=len(rows), column=1, sticky="w", padx=(8, 0), pady=(2, 0))

                # How to configure this device when it can't be reached now — only relevant
                # for OFFLINE/unreachable nodes (a reachable one is configured directly).
                _reachable = bool(dev and _device_kind(dev) == "ok")
                if not _reachable:
                    with self._devices_lock:
                        _agent_ids = {x.device_id for x in self.s.get("agent_devices", [])}
                    via_v = tk.StringVar(value="agente" if nid in _agent_ids else "pasiva")
                    vf = tk.Frame(dlg, bg="white")
                    vf.pack(anchor="w", padx=14, pady=(8, 0))
                    tk.Label(vf, text="Configurar vía:", bg="white", width=12, anchor="e").pack(side=tk.LEFT)
                    ttk.Radiobutton(vf, text="Pasiva (al reconectar)", value="pasiva",
                                    variable=via_v).pack(side=tk.LEFT, padx=(4, 0))
                    ttk.Radiobutton(vf, text="Agente (binario)", value="agente",
                                    variable=via_v).pack(side=tk.LEFT, padx=(8, 0))

                # Operating system (E2/N6): shown for every non-local device. LOCKED only
                # when we truly DETECTED it (os_detected) — detection is authoritative and
                # runs in the background. Otherwise the user picks Windows or Linux (no
                # "Auto" radio): it selects the agent template and makes path validation use
                # the correct rules (POSIX vs Windows) instead of assuming Windows.
                osf = tk.Frame(dlg, bg="white")
                osf.pack(anchor="w", padx=14, pady=(4, 0))
                tk.Label(osf, text="Sistema:", bg="white", width=12, anchor="e").pack(side=tk.LEFT)
                if dev and dev.os_detected and dev.os_type:
                    _oslbl = {"windows": "🪟 Windows", "macos": "🍎 macOS"}.get(dev.os_type, "🐧 Linux")
                    tk.Label(osf, text=f"{_oslbl}  · detectado", bg="white", fg="#2E7D32",
                             font=(_FONT, 9)).pack(side=tk.LEFT, padx=(4, 0))
                else:
                    _os0 = dev.os_type if (dev and dev.os_type in ("windows", "linux", "macos")) else ""
                    os_v = tk.StringVar(value=_os0)
                    for _val, _txt in (("windows", "🪟 Windows"), ("linux", "🐧 Linux"), ("macos", "🍎 macOS")):
                        ttk.Radiobutton(osf, text=_txt, value=_val,
                                        variable=os_v).pack(side=tk.LEFT, padx=(4, 0))
                    tk.Label(osf, text="(se autodetecta al conectar)", bg="white", fg="#888",
                             font=(_FONT, 8)).pack(side=tk.LEFT, padx=(6, 0))
                probe_lbl = tk.Label(dlg, text="", bg="white", fg="#555",
                                     font=(_FONT, 8), wraplength=430, justify="left")
                probe_lbl.pack(anchor="w", padx=14, pady=(4, 0))

                def _reorganize_after_probe(pid, extra_names=None):
                    folder = self.s["folder"]
                    my_id = self.s.get("my_id", "")
                    with self._devices_lock:
                        devs = list(self.s.get("devices", []))
                    # client=None: this runs on the UI thread, so resolve names from the
                    # in-memory devices only (no blocking config/pending API calls here).
                    # extra_names carries the hub-resolved names the off-thread probe gathered,
                    # so a peer revealed via the just-probed hub shows its name, not a bare id.
                    name_map = _resolve_name_map(devs, None, extra_names=extra_names)
                    online_ids = {d.device_id for d in devs if _device_kind(d) == "ok"}
                    base = _build_topology(folder, my_id, name_map, online_ids, devices=devs)
                    cur = topo()
                    _added = []
                    if cur:
                        orig = self.s.get("topology_orig") or _copy_topology(cur)
                        self.s["topology_orig"] = orig
                        _added = _reconcile_topology(cur, orig, base, my_id,
                                                     removed=self.s.get("topology_removed"))
                        # Make the just-probed node's REALITY authoritative in BOTH cur and
                        # orig, so it isn't later mistaken for a user edit (phantom diff).
                        bn = base["nodes"].get(pid)
                        if bn and pid in cur["nodes"]:
                            for fld in ("online", "path"):
                                if bn.get(fld) or fld == "online":
                                    cur["nodes"][pid][fld] = bn.get(fld)
                                    if pid in orig["nodes"]:
                                        orig["nodes"][pid][fld] = bn.get(fld)
                        # Pull in the real edges incident to the just-probed node + their
                        # seeded direction (into cur AND orig — it's discovered reality).
                        bed = base.get("edge_dir", {})
                        for e in base["edges"]:
                            if pid in e and all(x in cur["nodes"] for x in e):
                                cur["edges"].add(e); orig["edges"].add(e)
                                if e in bed:
                                    cur.setdefault("edge_dir", {})[e] = bed[e]
                                    orig.setdefault("edge_dir", {})[e] = bed[e]
                        _derive_roles(cur); _derive_roles(orig)   # roles follow the directions
                    if _added:
                        # Entering hub credentials here revealed new peer(s) → auto-organise +
                        # refit so they slot in cleanly (no overlapping nodes/arrows), same as the
                        # build/Estado paths. This is a direct user action (not a background poll).
                        _layout_circle(force=True)
                        _fit_view(set_auto=True)
                    else:
                        _layout_circle()
                        if view.get("auto", True):
                            _fit_view()
                    _render()

                def _probe_node():
                    vals = {k: v.get().strip() for k, v in fields.items()}
                    try:
                        sp = int(vals["ssh_port"] or "22")
                    except ValueError:
                        sp = 22
                    try:
                        wp = int(vals["winrm_port"] or "5985")
                    except ValueError:
                        wp = 5985
                    has_ssh = bool(vals["ssh_user"] or vals["ssh_key"] or vals["ssh_password"])
                    has_winrm = bool(vals["winrm_user"] and vals["winrm_password"])
                    ip = vals["ip"]
                    api_key = vals["api_key"]
                    # Prefer a user-typed API URL (O5); else the discovered one; else build
                    # a LAN URL from the IP.
                    api_url = (vals.get("api_url") or (dev.api_url if dev else None)
                               or (f"http://{ip}:8384" if ip else None))
                    if not (has_ssh or has_winrm or (api_key and api_url)):
                        probe_lbl.config(text="Introduce credenciales (SSH/WinRM o API) para probar.",
                                         fg="#C66000")
                        return
                    probe_lbl.config(text="Probando conexión…", fg="#555")
                    folder = self.s["folder"]
                    # Bind now: the commit below is intentionally done even if the DIALOG closed
                    # (background probe from Guardar) — closing a Toplevel doesn't change _show_gen.
                    # But if the user NAVIGATED (folder switch → _reset_folder_scoped_state rebuilt
                    # the graph), _show_gen differs and we must NOT merge this device into another
                    # folder's graph.
                    _my_gen = self._show_gen
                    override = {"ssh_user": vals["ssh_user"] or None,
                                "ssh_key_path": vals["ssh_key"] or None,
                                "ssh_password": vals["ssh_password"] or None, "ssh_port": sp,
                                "winrm_user": vals["winrm_user"] or None,
                                "winrm_password": vals["winrm_password"] or None, "winrm_port": wp}

                    def work():
                        try:
                            if has_ssh or has_winrm:
                                nd = probe_device(device_id=nid, name=node["label"], ip=ip or None,
                                                  folder_id=folder.id, override=override)
                                nd = _dc.replace(nd, api_key=nd.api_key or api_key or None)
                            else:
                                nd = probe_device_manual(device_id=nid, name=node["label"], ip=ip,
                                                         folder_id=folder.id, api_key=api_key,
                                                         api_url=api_url, folder_path=node.get("path") or "")
                            err = None
                        except Exception as e:
                            nd, err = None, str(e)

                        # Off-thread (here, NOT in ui()): if the just-probed device is a
                        # reachable hub, ask it for the names of its folder peers — a peer
                        # revealed only via this hub has no DeviceInfo of its own, so without
                        # this it would render as a bare device id in the graph.
                        _extra_names = {}
                        if nd is not None:
                            try:
                                _extra_names = _hub_name_map([nd], folder.id)
                            except Exception:
                                _extra_names = {}

                        def ui():
                            # The dialog may already be closed (Guardar launches this probe in
                            # the background — P2). Commit the result + reorganize the graph
                            # REGARDLESS; only the in-dialog status label is guarded.
                            _dlg_alive = dlg.winfo_exists()
                            if self._show_gen != _my_gen:
                                # User navigated away (e.g. switched folders) after a background
                                # probe — committing would merge this device into a different
                                # folder's graph. The dialog-close-only case keeps committing.
                                return
                            if nd is None:
                                if _dlg_alive:
                                    probe_lbl.config(text=_T('✗ Error: {}').format(err), fg="#C62828")
                                return
                            # Keep the typed creds even if unreachable (for later passive/agent).
                            nd2 = _dc.replace(
                                nd, ip=ip or nd.ip,
                                ssh_user=override["ssh_user"] or nd.ssh_user,
                                ssh_key_path=override["ssh_key_path"] or nd.ssh_key_path,
                                ssh_password=override["ssh_password"] or nd.ssh_password, ssh_port=sp,
                                winrm_user=override["winrm_user"] or nd.winrm_user,
                                winrm_password=override["winrm_password"] or nd.winrm_password, winrm_port=wp,
                                api_url=vals.get("api_url") or nd.api_url,
                                folder_path=nd.folder_path or node.get("path") or None)
                            with self._devices_lock:
                                found = False
                                for i, x in enumerate(self.s["devices"]):
                                    if x.device_id == nid:
                                        self.s["devices"][i] = nd2; found = True; break
                                if not found:
                                    self.s["devices"].append(nd2)
                            ok = _device_kind(nd2) == "ok"
                            if ok:
                                # Reachable now → it's configured directly; remove it from the
                                # passive/agent queues so it isn't also shown/handled "al reconectar".
                                # Under the lock: _refresh_status mutates these same set/list off-thread.
                                with self._devices_lock:
                                    self.s.get("passive_devices", set()).discard(nid)
                                    self.s["agent_devices"] = [a for a in self.s.get("agent_devices", [])
                                                               if a.device_id != nid]
                            # Node online/role/path + edges are refreshed from the freshly
                            # rebuilt graph (which now includes nd2's reachability/adjacency).
                            _reorganize_after_probe(nid, extra_names=_extra_names)
                            if not _dlg_alive:
                                # Background probe (from Guardar): reflect the outcome in the
                                # status bar since there's no dialog label to update.
                                if ok:
                                    self._status(_T("✓ «{}» configurado directamente.").format(node['label']),
                                                 "#2E7D32")
                                return
                            if ok:
                                probe_lbl.config(text="✓ Conexión OK — se configurará directamente "
                                                      "(sin aceptar).", fg="#2E7D32")
                            else:
                                probe_lbl.config(text="⚠ No alcanzable ahora — quedará para "
                                                      "exploración pasiva / agente.", fg="#C66000")
                        self._post(ui)
                    threading.Thread(target=work, daemon=True).start()
            else:
                # Local node: the editable current/new path are shown above. Here we show
                # the (read-only) API endpoint and the FULL API key — masked by default with
                # a 👁 toggle to reveal (the tag goes OUTSIDE the field, to the right).
                _lport = _endpoint_port(client.base_url if client else None)
                _lkey = (client.api_key if client else "") or ""
                info = tk.Frame(dlg, bg="white")
                info.pack(anchor="w", padx=14, pady=(6, 0))

                def _ro_row(r, lbl, val, tag=None, mask=False):
                    tk.Label(info, text=lbl, bg="white", anchor="e", width=10).grid(
                        row=r, column=0, sticky="e", pady=1)
                    e = ttk.Entry(info, width=34, show="●" if mask else "")
                    e.insert(0, val)
                    e.config(state="readonly")
                    e.grid(row=r, column=1, sticky="w", padx=(8, 0))
                    if mask:
                        tk.Button(info, text="👁", font=(_FONT, 8), relief="flat", bg="white",
                                  cursor="hand2",
                                  command=lambda ee=e: ee.config(show="" if ee.cget("show") else "●")
                                  ).grid(row=r, column=2, padx=(2, 0))
                    elif tag:
                        tk.Label(info, text=tag, bg="white", fg="#888",
                                 font=(_FONT, 7)).grid(row=r, column=2, sticky="w", padx=(4, 0))

                _ro_row(0, "API:", f"127.0.0.1:{_lport}", tag="(local)")
                _ro_row(1, "API Key:", _lkey or "—", mask=bool(_lkey))

            def save():
                # Chosen OS override (None = auto/unknown) — used for path validation now and
                # stored on the device so agent generation picks the right template.
                _sel_os = (os_v.get() if (os_v is not None and os_v.get() in ("windows", "linux", "macos"))
                           else None)
                _os_for_val = _sel_os or (dev.os_type if dev else None)
                # The local node's current path is read-only/authoritative — only validate an
                # editable (remote) current path.
                if path_v is not None and not node["is_local"]:
                    _p = path_v.get().strip()
                    _probs = _validate_node_path(_p, _os_for_val)
                    if _probs:
                        messagebox.showwarning(
                            "Ruta no válida",
                            _T("La ruta para este dispositivo no es válida:\n  • {}").format(
                                "\n  • ".join(_probs)), parent=dlg)
                        return
                # Validate the per-device NEW path (rename target) when set (B4).
                _newp = newpath_v.get().strip() if newpath_v is not None else ""
                if _newp:
                    _nprobs = _validate_node_path(_newp, _os_for_val)
                    if _nprobs:
                        messagebox.showwarning(
                            "Nueva ruta no válida",
                            _T("La nueva ruta para este dispositivo no es válida:\n  • {}").format(
                                "\n  • ".join(_nprobs)), parent=dlg)
                        return
                _push_undo()
                # Role is derived from the links — not set here anymore.
                if _is_new:
                    # New device: the entered path is the folder's CREATION path → it lives
                    # in node["path"] (what apply uses to create/relocate the folder), NOT in
                    # path_overrides (which only feeds the rename pipeline, doing nothing for
                    # a not-yet-existing folder — the original cause of the wrong path). The
                    # Syncthing LABEL (the global one from the Nombres page) is independent of
                    # this path. A bare name (no path) is created under home (~/name), like the
                    # add dialog, so it's never an unpredictable relative path; a full/absolute
                    # path is used verbatim (the on-disk folder name is its last segment).
                    if _newp:
                        node["path"] = _newp if (is_absolute_path(_newp)
                                                 or _newp.startswith("~")) else f"~/{_newp}"
                    self.s.setdefault("path_overrides", {}).pop(nid, None)
                else:
                    if path_v is not None and not node["is_local"]:
                        node["path"] = path_v.get().strip() or node.get("path", "")
                    # Persist / clear the per-device path override.
                    _pov = self.s.setdefault("path_overrides", {})
                    if _newp:
                        _pov[nid] = _newp
                    else:
                        _pov.pop(nid, None)
                if fields:
                    vals = {k: v.get().strip() for k, v in fields.items()}
                    try:
                        sp = int(vals["ssh_port"] or "22")
                    except ValueError:
                        sp = 22
                    try:
                        wp = int(vals["winrm_port"] or "5985")
                    except ValueError:
                        wp = 5985
                    has_any = bool(vals["ssh_user"] or vals["ssh_key"] or vals["ssh_password"]
                                   or (vals["winrm_user"] and vals["winrm_password"])
                                   or vals.get("api_key"))
                    with self._devices_lock:
                        if dev is not None:
                            # Reset reachability: the edited credentials are unverified until
                            # the user hits 🔌 Probar y conectar (avoids a stale "reachable").
                            nd = _dc.replace(
                                dev, ip=vals["ip"] or dev.ip,
                                ssh_user=vals["ssh_user"] or None, ssh_key_path=vals["ssh_key"] or None,
                                ssh_password=vals["ssh_password"] or None, ssh_port=sp,
                                winrm_user=vals["winrm_user"] or None,
                                winrm_password=vals["winrm_password"] or None, winrm_port=wp,
                                api_key=vals["api_key"] or dev.api_key,
                                api_url=vals.get("api_url") or dev.api_url,
                                folder_path=node["path"] or dev.folder_path,
                                os_type=_sel_os or dev.os_type,
                                api_reachable=False, ssh_reachable=False, winrm_reachable=False)
                        else:
                            nd = DeviceInfo(
                                device_id=nid, name=node["label"], ip=vals["ip"] or None,
                                api_url=vals.get("api_url") or None, api_key=vals["api_key"] or None,
                                folder_path=node["path"] or None,
                                ssh_reachable=False, api_reachable=False, is_local=False,
                                ssh_user=vals["ssh_user"] or None, ssh_key_path=vals["ssh_key"] or None,
                                ssh_password=vals["ssh_password"] or None, ssh_port=sp,
                                winrm_user=vals["winrm_user"] or None,
                                winrm_password=vals["winrm_password"] or None, winrm_port=wp,
                                os_type=_sel_os)
                        replaced = False
                        for i, x in enumerate(self.s["devices"]):
                            if x.device_id == nid:
                                self.s["devices"][i] = nd; replaced = True; break
                        if not replaced:
                            self.s["devices"].append(nd)
                        # Passive vs agent, per the selector (only meaningful with creds).
                        ag = self.s.setdefault("agent_devices", [])
                        passive = self.s.setdefault("passive_devices", set())
                        if via_v is not None and via_v.get() == "agente":
                            passive.discard(nid)
                            if not any(d.device_id == nid for d in ag):
                                ag.append(nd)
                        else:
                            self.s["agent_devices"] = [d for d in ag if d.device_id != nid]
                            if has_any:
                                passive.add(nid)
                # P2: like the Devices tab's Guardar — when there are credentials, probe in the
                # background so the OS auto-detects and the reachability/passive flags settle
                # without the user having to press Estado. _probe_node() reads the fields
                # synchronously now and finishes (commit + reorganize) even after this dialog
                # closes (its ui() no longer bails just because the dialog is gone).
                if not node["is_local"] and fields and has_any:
                    _probe_node()
                # Remember the typed creds in the SESSION store right away, so they survive to
                # other folders even if this device list is later rebuilt/cleared — topology-
                # entered creds used to be remembered only on the next discovery.
                self._remember_session_creds(self.s.get("devices", []))
                dlg.destroy()
                _render()

            btnf = tk.Frame(dlg, bg="white")
            btnf.pack(fill=tk.X, padx=14, pady=12)
            ttk.Button(btnf, text="Guardar", command=save).pack(side=tk.RIGHT)
            ttk.Button(btnf, text="Cancelar", command=dlg.destroy).pack(side=tk.RIGHT, padx=(0, 6))
            if not node["is_local"]:
                ttk.Button(btnf, text="🔌 Probar y conectar",
                           command=_probe_node).pack(side=tk.LEFT)
            if self.s.get("advanced"):   # local node → folder config; remote → also device flags
                ttk.Button(btnf, text="⚙ Avanzado",
                           command=lambda: _advanced_node_dialog(nid, dlg)).pack(side=tk.LEFT, padx=(6, 0))
            dlg.bind("<Return>", lambda e: save())

        def _advanced_node_dialog(nid, parent):
            """Child window (advanced mode). Two sections: (1) device relationship in the
            LOCAL config (introducer, auto-accept, compression, pause, rate limits) — remote
            only; (2) the FOLDER's config on this device (versioning, rescan, fsWatcher,
            ignore-perms, pause) — read/written via the local API (local node) or the remote's
            API when reachable. Closes with its parent."""
            client = self.s.get("client")
            t = topo()
            node = (t["nodes"].get(nid) if t else None) or {}
            is_local = bool(node.get("is_local"))
            with self._devices_lock:
                dev = next((x for x in self.s.get("devices", []) if x.device_id == nid), None)
            folder_id = self.s["folder"].id
            if not client:
                messagebox.showinfo("Avanzado", "Sin conexión con el Syncthing local.", parent=parent)
                return

            # (1) Device relationship — LOCAL config entry (remote devices only). This lives
            # entirely in the LOCAL config, so it's editable even when the remote is OFFLINE.
            # If the device isn't in the local config yet (introduced/just-added peer), we
            # seed a default entry; saving upserts it (PUT /rest/config/devices/{id}) — which
            # is exactly how you establish a relationship, and works while it's offline.
            dcfg = None
            dcfg_is_new = False
            if not is_local:
                try:
                    dcfg = client._get(f"/rest/config/devices/{nid}")
                except Exception:
                    dcfg = None
                if dcfg is None:
                    dcfg_is_new = True
                    dcfg = {"deviceID": nid, "name": node.get("label", nid[:7]) or nid[:7],
                            "addresses": ["dynamic"], "compression": "metadata",
                            "introducer": False, "autoAcceptFolders": False, "paused": False,
                            "maxSendKbps": 0, "maxRecvKbps": 0}

            # (2) Folder config on this device — readable/appliable over ANY channel
            # (local / direct API / SSH / WinRM) when the device is reachable. The live read
            # is done ASYNCHRONOUSLY after the window opens (an SSH/WinRM read must not block
            # the UI thread); widgets prefill from a queued pending edit / defaults meanwhile.
            _reachable = bool(is_local or (dev and _device_kind(dev) == "ok"))
            from ..renamer import (read_folder_cfg_on_device as _read_fcfg,
                                  apply_folder_cfg_on_device as _apply_fcfg)

            win = tk.Toplevel(self)
            win.title("Opciones avanzadas")
            win.configure(bg="white")
            win.transient(parent)
            win.grab_set()
            self._center_dialog(win)
            try:
                # Close this window when the PARENT dialog itself is destroyed. Tk delivers
                # <Destroy> for every descendant widget too, so guard on `_e.widget is parent`
                # — otherwise tearing down any child of the parent would close this prematurely.
                parent.bind("<Destroy>",
                            lambda _e, w=win, p=parent: (_e.widget is p and w.winfo_exists()
                                                         and w.destroy()),
                            add="+")
            except Exception:
                pass
            tk.Label(win, text=f"Opciones avanzadas — {node.get('label', nid[:7])}",
                     bg="white", font=(_FONT, 10, "bold")).pack(anchor="w", padx=16, pady=(12, 2))
            tk.Label(win, text="Muestra lo que ya hay configurado y lo hace editable.",
                     bg="white", fg="#888", font=(_FONT, 8)).pack(anchor="w", padx=16)

            # The "device relationship" (introducer, auto-accept, compression, rate limits)
            # is a property of each REMOTE device entry, not of the local node — so it isn't
            # shown for the local node. Explain that instead of leaving the user wondering.
            if is_local:
                tk.Label(win, text="ℹ La «relación con el equipo» (introducer, auto-aceptar, "
                                   "compresión, límites) es una propiedad de cada dispositivo "
                                   "REMOTO en tu configuración, no del equipo local. Aquí editas "
                                   "la configuración de la CARPETA en este equipo.",
                         bg="#E3F2FD", fg="#1565C0", font=(_FONT, 8), wraplength=470,
                         justify="left").pack(fill=tk.X, anchor="w", padx=16, pady=(6, 2))

            intro_v = auto_v = comp_v = dpaused_v = send_v = recv_v = None
            _rel_init: dict = {}
            if dcfg is not None and not is_local:
                tk.Label(win, text="Relación con el equipo (config local):", bg="white",
                         fg="#555", font=(_FONT, 8, "bold")).pack(anchor="w", padx=16, pady=(8, 0))
                if dcfg_is_new:
                    tk.Label(win, text="ℹ Este dispositivo aún no está en tu configuración local. "
                                       "Si cambias algo aquí, se añadirá a tu config con estos ajustes "
                                       "(válido aunque esté offline).",
                             bg="#FFF8E1", fg="#8a6d00", font=(_FONT, 8), wraplength=470,
                             justify="left").pack(fill=tk.X, anchor="w", padx=16, pady=(2, 2))
                intro_v = tk.BooleanVar(value=bool(dcfg.get("introducer")))
                auto_v = tk.BooleanVar(value=bool(dcfg.get("autoAcceptFolders")))
                comp_v = tk.StringVar(value=dcfg.get("compression", "metadata"))
                dpaused_v = tk.BooleanVar(value=bool(dcfg.get("paused")))
                fr = tk.Frame(win, bg="white")
                fr.pack(fill=tk.X, padx=16)
                tk.Checkbutton(fr, text="Introductor (presenta otros dispositivos del cluster)",
                               variable=intro_v, bg="white", anchor="w", wraplength=430,
                               justify="left").pack(fill=tk.X, anchor="w")
                tk.Checkbutton(fr, text="Auto-aceptar las carpetas que ofrezca este equipo",
                               variable=auto_v, bg="white", anchor="w", wraplength=430,
                               justify="left").pack(fill=tk.X, anchor="w")
                tk.Checkbutton(fr, text="Pausar este dispositivo",
                               variable=dpaused_v, bg="white", anchor="w").pack(fill=tk.X, anchor="w")
                cf = tk.Frame(win, bg="white")
                cf.pack(fill=tk.X, padx=16, pady=(4, 0))
                tk.Label(cf, text="Compresión:", bg="white").pack(side=tk.LEFT)
                ttk.Combobox(cf, textvariable=comp_v, state="readonly", width=12,
                             values=["metadata", "always", "never"]).pack(side=tk.LEFT, padx=(6, 0))
                send_v = tk.StringVar(value=str(dcfg.get("maxSendKbps", 0) or 0))
                recv_v = tk.StringVar(value=str(dcfg.get("maxRecvKbps", 0) or 0))
                rl = tk.Frame(win, bg="white")
                rl.pack(fill=tk.X, padx=16, pady=(4, 0))
                tk.Label(rl, text="Límite ↑ (KiB/s):", bg="white").pack(side=tk.LEFT)
                ttk.Entry(rl, textvariable=send_v, width=7).pack(side=tk.LEFT, padx=(4, 8))
                tk.Label(rl, text="↓:", bg="white").pack(side=tk.LEFT)
                ttk.Entry(rl, textvariable=recv_v, width=7).pack(side=tk.LEFT, padx=(4, 0))
                tk.Label(rl, text="(0 = sin límite)", bg="white", fg="#888",
                         font=(_FONT, 8)).pack(side=tk.LEFT, padx=(8, 0))
                _rel_init = {"introducer": intro_v.get(), "autoAcceptFolders": auto_v.get(),
                             "compression": comp_v.get(), "paused": dpaused_v.get(),
                             "maxSendKbps": send_v.get(), "maxRecvKbps": recv_v.get()}

            ttk.Separator(win, orient="horizontal").pack(fill=tk.X, padx=16, pady=(8, 4))
            tk.Label(win, text="Configuración de la carpeta en este equipo:", bg="white",
                     fg="#555", font=(_FONT, 8, "bold")).pack(anchor="w", padx=16)
            # Prefill from a queued pending edit / defaults; if reachable, the LIVE config is
            # loaded asynchronously (below) and replaces these without blocking the UI.
            pend = (self.s.get("fcfg_pending", {}) or {}).get(nid) or {}
            vers_v = tk.StringVar(value=(pend.get("versioning_type", "") or _T("(ninguno)")))
            rescan_v = tk.StringVar(value=str(pend.get("rescanIntervalS", 3600)))
            fsw_v = tk.BooleanVar(value=bool(pend.get("fsWatcherEnabled", True)))
            ignperm_v = tk.BooleanVar(value=bool(pend.get("ignorePerms", False)))
            fpaused_v = tk.BooleanVar(value=bool(pend.get("paused", False)))
            # Snapshot of what's DISPLAYED. Only fields the user changes from this are
            # applied → untouched fields are never overwritten (e.g. clobbered with defaults).
            _init: dict = {}

            def _snapshot_init():
                _init.update(
                    versioning_type=("" if vers_v.get() == _T("(ninguno)") else vers_v.get()),
                    rescanIntervalS=rescan_v.get().strip(),
                    fsWatcherEnabled=fsw_v.get(), ignorePerms=ignperm_v.get(),
                    paused=fpaused_v.get())
            _snapshot_init()
            vf = tk.Frame(win, bg="white")
            vf.pack(fill=tk.X, padx=16, pady=(4, 0))
            tk.Label(vf, text="Versionado:", bg="white").pack(side=tk.LEFT)
            ttk.Combobox(vf, textvariable=vers_v, state="readonly", width=12,
                         values=[_T("(ninguno)"), "trashcan", "staggered", "simple"]).pack(side=tk.LEFT, padx=(6, 0))
            tk.Label(vf, text="Rescan (s):", bg="white").pack(side=tk.LEFT, padx=(10, 0))
            ttk.Entry(vf, textvariable=rescan_v, width=7).pack(side=tk.LEFT, padx=(4, 0))
            ff = tk.Frame(win, bg="white")
            ff.pack(fill=tk.X, padx=16, pady=(2, 0))
            tk.Checkbutton(ff, text="Vigilar cambios (fsWatcher)", variable=fsw_v,
                           bg="white", anchor="w").pack(fill=tk.X, anchor="w")
            tk.Checkbutton(ff, text="Ignorar permisos", variable=ignperm_v,
                           bg="white", anchor="w").pack(fill=tk.X, anchor="w")
            tk.Checkbutton(ff, text="Pausar esta carpeta en este equipo", variable=fpaused_v,
                           bg="white", anchor="w").pack(fill=tk.X, anchor="w")
            if not _reachable:
                tk.Label(win, text="Equipo no accesible ahora: estos cambios quedarán PENDIENTES "
                                   "y se aplicarán al reconectar (pasiva) o por agente.",
                         bg="white", fg="#C66000", font=(_FONT, 8), wraplength=430,
                         justify="left").pack(anchor="w", padx=16, pady=(2, 0))

            status = tk.Label(win, text="", bg="white", font=(_FONT, 8))
            status.pack(anchor="w", padx=16, pady=(8, 0))

            # Async live read (reachable) — an SSH/WinRM read must not block the UI thread.
            if _reachable and dev is not None:
                status.config(text="Cargando configuración actual…", fg="#555")

                def _load():
                    try:
                        live = _read_fcfg(dev, folder_id)
                    except Exception:
                        live = None

                    def _ui():
                        if not win.winfo_exists():
                            return
                        if live:
                            vers_v.set((live.get("versioning", {}) or {}).get("type", "") or _T("(ninguno)"))
                            rescan_v.set(str(live.get("rescanIntervalS", 3600)))
                            fsw_v.set(bool(live.get("fsWatcherEnabled", True)))
                            ignperm_v.set(bool(live.get("ignorePerms", False)))
                            fpaused_v.set(bool(live.get("paused", False)))
                            _snapshot_init()
                            status.config(text="")
                        else:
                            status.config(text="No se pudo leer la config actual; solo se "
                                               "aplicará lo que cambies.", fg="#C66000")
                    self._post(_ui)
                threading.Thread(target=_load, daemon=True).start()

            def _save_adv():
                cur = {"versioning_type": "" if vers_v.get() == _T("(ninguno)") else vers_v.get(),
                       "rescanIntervalS": rescan_v.get().strip(),
                       "fsWatcherEnabled": fsw_v.get(), "ignorePerms": ignperm_v.get(),
                       "paused": fpaused_v.get()}
                # Only the fields the user actually changed from what was shown.
                ov: dict = {}
                for k, v in cur.items():
                    if v != _init.get(k):
                        if k == "rescanIntervalS":
                            try:
                                ov[k] = max(0, int(v or "0"))
                            except ValueError:
                                status.config(text="Rescan debe ser un número (s).", fg="#C62828")
                                return
                        else:
                            ov[k] = v
                # Device-relationship rate limits (live local config → safe to set all).
                sk = rk = None
                if send_v:
                    try:
                        sk = max(0, int(send_v.get().strip() or "0"))
                        rk = max(0, int(recv_v.get().strip() or "0"))
                    except ValueError:
                        status.config(text="Los límites deben ser números (KiB/s).", fg="#C62828")
                        return
                status.config(text="Guardando…", fg="#555")

                # Snapshot the relationship tkinter Vars in the MAIN thread — work() runs
                # off-thread and must NOT call .get() on tk Vars (Tcl is single-threaded →
                # crash / garbage). `intro_v is not None` is a plain object check (no tk access).
                _has_rel = intro_v is not None
                _rel_now = ({"introducer": intro_v.get(), "autoAcceptFolders": auto_v.get(),
                             "compression": comp_v.get(), "paused": dpaused_v.get(),
                             "maxSendKbps": send_v.get(), "maxRecvKbps": recv_v.get()}
                            if _has_rel else {})
                # fcfg_pending is folder-scoped; if the user switches folders mid-save,
                # _reset_folder_scoped_state clears it and this stale worker must NOT repopulate
                # it (it would apply the OLD folder's override to the new folder).
                _my_gen = self._show_gen

                def work():
                    errs = []
                    # Write the device-relationship config only when it actually changed. This
                    # matters for a device NOT yet in the local config (dcfg_is_new): we must
                    # NOT silently add it just because Avanzado was opened — only when the user
                    # edited a relationship field. The write upserts (works while offline).
                    rel_now = _rel_now
                    rel_changed = bool(rel_now and rel_now != _rel_init)
                    if dcfg is not None and (rel_changed or (not dcfg_is_new and _has_rel)):
                        dcfg["introducer"] = _rel_now["introducer"]
                        dcfg["autoAcceptFolders"] = _rel_now["autoAcceptFolders"]
                        dcfg["compression"] = _rel_now["compression"]
                        dcfg["paused"] = _rel_now["paused"]
                        dcfg["maxSendKbps"] = sk
                        dcfg["maxRecvKbps"] = rk
                        try:
                            client._put(f"/rest/config/devices/{nid}", json=dcfg)
                        except Exception as e:
                            errs.append(_T('dispositivo: {}').format(e))
                    queued = False
                    if ov:
                        if _reachable and dev is not None:
                            r = _apply_fcfg(dev, folder_id, ov, dry_run=False)
                            if r.ok:
                                if self._show_gen == _my_gen:
                                    # Under the lock: the page_execute passive loop reads/pops
                                    # fcfg_pending under _devices_lock and this writer runs on a
                                    # worker thread — match it so the two never race on the dict.
                                    with self._devices_lock:
                                        self.s.get("fcfg_pending", {}).pop(nid, None)
                            else:
                                errs.append(_T('carpeta: {}').format(r.message))
                        elif self._show_gen == _my_gen:
                            with self._devices_lock:
                                self.s.setdefault("fcfg_pending", {}).setdefault(nid, {}).update(ov)
                            queued = True

                    def ui():
                        if not win.winfo_exists():
                            return
                        if errs:
                            status.config(text="✗ " + "; ".join(errs), fg="#C62828")
                        else:
                            status.config(text=("✓ Guardado (config de carpeta pendiente: se "
                                                "aplicará al reconectar/agente)." if queued
                                                else "✓ Guardado."), fg="#2E7D32")
                            win.after(900, win.destroy)
                    self._post(ui)
                threading.Thread(target=work, daemon=True).start()

            bf = tk.Frame(win, bg="white")
            bf.pack(fill=tk.X, padx=16, pady=12)
            ttk.Button(bf, text="Guardar", command=_save_adv).pack(side=tk.RIGHT)
            ttk.Button(bf, text="Cerrar", command=win.destroy).pack(side=tk.RIGHT, padx=(0, 6))

        def _set_edge_direction(a, b, direction):
            """Set the per-link direction (the source of truth) and re-derive node roles.
            direction: 'both' (↔), 'a2b' (a→b) or 'b2a' (b→a)."""
            t = topo()
            e = frozenset((a, b))
            ed = t.setdefault("edge_dir", {})
            if direction == "both":
                ed[e] = frozenset((a, b))
            elif direction == "a2b":
                ed[e] = frozenset((a,))
            else:  # b2a
                ed[e] = frozenset((b,))
            _derive_roles(t)

        def _edit_edge_dialog(e):
            t = topo()
            ids = sorted(e)
            if len(ids) < 2 or ids[0] not in t["nodes"] or ids[1] not in t["nodes"]:
                return
            if e in self.s.get("topology_locked", set()):
                if not messagebox.askyesno(
                        "Enlace bloqueado",
                        "Este enlace está marcado como «no editar». ¿Desbloquearlo y editarlo?",
                        parent=self):
                    return
                self.s["topology_locked"].discard(e)
            a, b = ids
            na, nb = t["nodes"][a], t["nodes"][b]
            # Initial direction from the stored edge_dir (default ↔ if unknown).
            senders = t.get("edge_dir", {}).get(e)
            if senders is None or len(senders) != 1:
                st = {"src": a, "bidir": True}
            else:
                st = {"src": (a if a in senders else b), "bidir": False}

            dlg = tk.Toplevel(self)
            dlg.title("Editar enlace")
            dlg.configure(bg="white")
            dlg.grab_set()
            self._center_dialog(dlg)
            tk.Label(dlg, text="Dirección del enlace", bg="white",
                     font=(_FONT, 10, "bold")).pack(anchor="w", padx=16, pady=(12, 2))

            dir_lbl = tk.Label(dlg, bg="white", font=(_FONT, 13, "bold"), fg="#1565C0")
            dir_lbl.pack(pady=(10, 2))
            warn_lbl = tk.Label(dlg, bg="white", font=(_FONT, 8), fg="#C66000",
                                wraplength=380, justify="left")
            warn_lbl.pack(padx=16, pady=(6, 0))

            def _direction():
                if st["bidir"]:
                    return "both"
                return "a2b" if st["src"] == a else "b2a"

            def _refresh():
                la, lb = na["label"], nb["label"]
                d = _direction()
                dir_lbl.config(text=f"{la}  ↔  {lb}" if d == "both" else
                               (f"{la}  →  {lb}" if d == "a2b" else f"{lb}  →  {la}"))
                # Preview the would-be conflict: a one-way link whose endpoints are already
                # envía/recibe by their OTHER links can't be one-way (Syncthing global role).
                if d != "both":
                    src = st["src"]; dst = b if src == a else a
                    # If dst also sends elsewhere AND src receives elsewhere → both become
                    # envía/recibe → the link is forced bidirectional (can't be one-way).
                    dst_sends = any(dst in s for ee, s in t.get("edge_dir", {}).items()
                                    if ee != e and dst in ee)
                    src_recv = any((set(ee) - {src}) & s for ee, s in t.get("edge_dir", {}).items()
                                   if ee != e and src in ee)
                    warn_lbl.config(text=("⚠ Puede quedar bidireccional: ambos extremos ya "
                                          "envían/reciben por otros enlaces.")
                                    if (dst_sends and src_recv) else "")
                else:
                    warn_lbl.config(text="")
                flip_btn.config(state="disabled" if st["bidir"] else "normal")

            def _flip():
                if st["bidir"]:
                    return            # symmetric — nothing to invert (don't make it one-way)
                st["src"] = b if st["src"] == a else a
                _refresh()

            def _toggle_bidir():
                st["bidir"] = not st["bidir"]
                _refresh()

            bf = tk.Frame(dlg, bg="white")
            bf.pack(pady=(10, 0))
            flip_btn = ttk.Button(bf, text="🔁 Invertir dirección", command=_flip)
            flip_btn.pack(side=tk.LEFT, padx=4)
            ttk.Button(bf, text="↔ Bidireccional", command=_toggle_bidir).pack(side=tk.LEFT, padx=4)

            def _save():
                _push_undo()
                _set_edge_direction(a, b, _direction())
                dlg.destroy()
                drag["sel"], drag["sel_edge"] = None, e
                status_lbl.config(text=_T("Enlace actualizado: ") + _edge_dir_text(e))
                _render()

            sf = tk.Frame(dlg, bg="white")
            sf.pack(fill=tk.X, padx=16, pady=14)
            ttk.Button(sf, text="Guardar", command=_save).pack(side=tk.RIGHT)
            ttk.Button(sf, text="Cancelar", command=dlg.destroy).pack(side=tk.RIGHT, padx=(0, 6))
            _refresh()

        # Middle mouse button (wheel-click) drag = pan, in ANY mode. Left-drag only pans in
        # "Move" mode (and over empty space), so when "Añadir enlaces" is active you couldn't
        # reach nodes outside the viewport — the middle button always can, without a mode switch.
        def on_mid_press(ev):
            # Cancel any in-progress LEFT-button interaction first, so a middle-button pan during
            # a held left-drag can't later fire a spurious node move / edge toggle on B1 release.
            drag["id"] = None
            drag["panning"] = False
            drag["moved"] = False
            drag["mpan"] = True
            drag["msx"], drag["msy"] = ev.x, ev.y
            drag["mpx0"], drag["mpy0"] = view["px"], view["py"]
            cv.config(cursor="fleur")

        def on_mid_motion(ev):
            if not drag.get("mpan"):
                return
            view["auto"] = False   # manual pan → stop auto-fitting on resize
            view["px"] = drag["mpx0"] - (ev.x - drag["msx"]) / view["zoom"]
            view["py"] = drag["mpy0"] - (ev.y - drag["msy"]) / view["zoom"]
            _render()

        def on_mid_release(_ev):
            drag["mpan"] = False
            cv.config(cursor="")

        cv.bind("<Button-1>", on_press)
        cv.bind("<B1-Motion>", on_motion)
        cv.bind("<ButtonRelease-1>", on_release)
        cv.bind("<Button-2>", on_mid_press)
        cv.bind("<B2-Motion>", on_mid_motion)
        cv.bind("<ButtonRelease-2>", on_mid_release)
        cv.bind("<Double-Button-1>", on_double)
        cv.bind("<Button-3>", _show_context_menu)
        cv.bind("<Configure>", _on_resize)
        # Undo/redo keyboard shortcuts (canvas needs focus → grab it on enter).
        cv.bind("<Enter>", lambda e: cv.focus_set())
        cv.bind("<Control-z>", lambda e: _undo())
        cv.bind("<Control-y>", lambda e: _redo())
        cv.bind("<Control-Shift-Z>", lambda e: _redo())
        cv.bind("<MouseWheel>", _on_wheel)          # Windows / macOS
        cv.bind("<Button-4>", _on_wheel)            # Linux scroll up
        cv.bind("<Button-5>", _on_wheel)            # Linux scroll down
        _set_mode("move")
        _sync_undo_btns()

        # Light periodic live-status poll while this page is showing; stops automatically
        # when the wizard navigates away (detected via the page generation counter).
        _topo_gen = self._show_gen

        _poll_busy = [False]

        def _poll_status():
            if self._show_gen != _topo_gen or not cv.winfo_exists():
                return
            # Skip this tick if the previous status refresh is still in flight (a slow/hung API
            # must not stack workers on the shared requests.Session every 15s — same guard
            # page_folder uses for its folder poll).
            if not _poll_busy[0]:
                _poll_busy[0] = True
                _refresh_status(quiet=True,
                                on_done=lambda: _poll_busy.__setitem__(0, False))
            self.after(15000, _poll_status)
        self.after(6000, _poll_status)

        def _validate_device_id(did):
            """→ normalized id (str) if valid, False if explicitly invalid, None if
            it couldn't be checked (no client / network)."""
            client = self.s.get("client")
            if not client:
                return None
            try:
                res = client.check_device_id(did)
            except Exception:
                return None
            if isinstance(res, dict) and res.get("id"):
                return res["id"]
            if isinstance(res, dict) and res.get("error"):
                return False
            return None

        def _browse_dialog(api_url, api_key, start, on_pick):
            if not api_url:
                messagebox.showinfo("Examinar",
                                    "Introduce primero la URL de la API del dispositivo nuevo "
                                    "(en Acceso) para poder explorar sus carpetas.")
                return
            bd = tk.Toplevel(self)
            bd.title("Examinar carpetas del dispositivo")
            bd.configure(bg="white")
            bd.grab_set()
            self._center_dialog(bd)
            cur_v = tk.StringVar(value=start or "~")
            row = tk.Frame(bd, bg="white")
            row.pack(fill=tk.X, padx=12, pady=(10, 0))
            tk.Label(row, text="Ruta:", bg="white").pack(side=tk.LEFT)
            ttk.Entry(row, textvariable=cur_v, width=46).pack(side=tk.LEFT, padx=(6, 0))
            lst = tk.Listbox(bd, height=11, width=64)
            lst.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)
            info = tk.Label(bd, text="Cargando…", bg="white", fg="#888", font=(_FONT, 8))
            info.pack(anchor="w", padx=12)

            def load(path):
                info.config(text="Cargando…")
                def work():
                    try:
                        items = SyncthingClient(api_url, api_key, verify_ssl=False).browse(path)
                        err = None
                    except Exception as e:
                        items, err = None, str(e)
                    def ui():
                        if not bd.winfo_exists():
                            return
                        lst.delete(0, tk.END)
                        if items is None:
                            info.config(text=_T('No se pudo listar: {}').format(err))
                            return
                        for it in items:
                            lst.insert(tk.END, it)
                        info.config(text=_T('{} carpeta(s) — doble clic para entrar').format(len(items)))
                    self._post(ui)
                threading.Thread(target=work, daemon=True).start()

            lst.bind("<Double-Button-1>", lambda e: (
                cur_v.set(lst.get(lst.curselection()[0])) or load(cur_v.get())
            ) if lst.curselection() else None)
            btns = tk.Frame(bd, bg="white")
            btns.pack(fill=tk.X, padx=12, pady=(0, 10))
            ttk.Button(btns, text="Ir", command=lambda: load(cur_v.get())).pack(side=tk.LEFT)
            ttk.Button(btns, text="Usar esta carpeta",
                       command=lambda: (on_pick(cur_v.get()), bd.destroy())).pack(side=tk.RIGHT)
            ttk.Button(btns, text="Cancelar", command=bd.destroy).pack(side=tk.RIGHT, padx=(0, 6))
            load(cur_v.get())

        def _add_device_dialog():
            if not topo():
                return
            import dataclasses as _dc
            dlg = tk.Toplevel(self)
            dlg.title("Nuevo dispositivo")
            dlg.configure(bg="white")
            dlg.grab_set()
            self._center_dialog(dlg)
            tk.Label(dlg, text="Introducir nuevo dispositivo", bg="white",
                     font=(_FONT, 10, "bold")).pack(anchor="w", padx=14, pady=(12, 4))
            tk.Label(dlg, text=("El acceso es opcional: con credenciales (SSH/WinRM o API) editamos "
                                "su config directamente. Sin acceso, podrás aceptar el dispositivo/"
                                "carpeta en la interfaz web de Syncthing del equipo, o usar un agente."),
                     bg="white", fg="#888", font=(_FONT, 8), wraplength=440,
                     justify="left").pack(anchor="w", padx=14, pady=(0, 6))

            # Quick-link: pick a device your Syncthing already knows (e.g. shared in
            # OTHER folders) so you don't have to type its ID. Manual entry still works.
            link_frm = tk.Frame(dlg, bg="white")
            link_frm.pack(fill=tk.X, padx=14, pady=(0, 4))
            tk.Label(link_frm, text="Vincular conocido:", bg="white", anchor="e",
                     width=16).pack(side=tk.LEFT)
            known_var = tk.StringVar()
            known_cb = ttk.Combobox(link_frm, textvariable=known_var, state="readonly", width=34)
            known_cb.pack(side=tk.LEFT, padx=(8, 0))
            known_cb.set(_T("(cargando dispositivos conocidos…)"))
            _known_map: dict = {}

            def _on_known(_e=None):
                sel = known_var.get()
                if sel in _known_map:
                    did, nm = _known_map[sel]
                    id_v.set(did)
                    if not label_v.get().strip():
                        label_v.set(nm)

            known_cb.bind("<<ComboboxSelected>>", _on_known)

            def _load_known():
                client = self.s.get("client")
                items = []
                if client:
                    try:
                        present = set(topo()["nodes"].keys()) if topo() else set()
                        my_id = self.s.get("my_id", "")
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
            grid.pack(fill=tk.X, padx=14)

            def _row(r, lbl, var, width=36, show=""):
                tk.Label(grid, text=lbl, bg="white", anchor="e", width=16).grid(
                    row=r, column=0, sticky="e", pady=2)
                e = ttk.Entry(grid, textvariable=var, width=width, show=show)
                e.grid(row=r, column=1, sticky="w", padx=(8, 0))
                return e

            label_v = tk.StringVar()
            id_v = tk.StringVar()
            # Default folder path for a NEW device = the FOLDER's label (where the folder will
            # live on that machine), NOT the device name. E.g. folder «Workspace» → ~/Workspace
            # regardless of whether the device is called "raspberrypi".
            _flabel = (self.s.get("new_label") or self.s["folder"].label or self.s["folder"].id)
            path_v = tk.StringVar(value="~/" + _flabel)
            _row(0, "Nombre (label):", label_v)
            _row(1, "Device ID:", id_v)
            tk.Label(grid, text="Ruta de carpeta:", bg="white", anchor="e",
                     width=16).grid(row=2, column=0, sticky="e", pady=2)
            prow = tk.Frame(grid, bg="white")
            prow.grid(row=2, column=1, sticky="w", padx=(8, 0))
            ttk.Entry(prow, textvariable=path_v, width=28).pack(side=tk.LEFT)

            # «Examinar» lista las carpetas del dispositivo via /rest/system/browse, que solo
            # responde si su API es alcanzable DIRECTAMENTE desde aquí (no por el túnel SSH).
            # Por eso el botón solo se habilita tras un «Probar conexión» con API directa OK;
            # si no, queda deshabilitado (evita el fallo silencioso de antes).
            def _browse_add():
                nd = probed.get("nd")
                if nd and nd.api_reachable and nd.api_url:
                    _browse_dialog(nd.api_url, nd.api_key or "",
                                   path_v.get().strip() or "~", lambda p: path_v.set(p))
            _browse_btn = ttk.Button(prow, text="Examinar…", width=10, state="disabled",
                                     command=_browse_add)
            _browse_btn.pack(side=tk.LEFT, padx=(4, 0))
            tk.Label(grid, text="(por defecto ~/<nombre>; «Examinar» tras probar la API)",
                     bg="white", fg="#888", font=(_FONT, 8)).grid(
                row=3, column=1, sticky="w", padx=(8, 0))

            ttk.Separator(dlg, orient="horizontal").pack(fill=tk.X, padx=14, pady=(8, 4))
            tk.Label(dlg, text="Acceso (opcional)", bg="white", fg="#555",
                     font=(_FONT, 9, "bold")).pack(anchor="w", padx=14)
            agrid = tk.Frame(dlg, bg="white")
            agrid.pack(fill=tk.X, padx=14, pady=(2, 0))

            def _arow(r, lbl, var, width=30, show="", browse=False):
                tk.Label(agrid, text=lbl, bg="white", anchor="e", width=16).grid(
                    row=r, column=0, sticky="e", pady=2)
                ttk.Entry(agrid, textvariable=var, width=width, show=show).grid(
                    row=r, column=1, sticky="w", padx=(8, 0))
                if browse:   # «…» examinar la clave privada
                    ttk.Button(agrid, text="…", width=3,
                               command=lambda vv=var: vv.set(
                                   filedialog.askopenfilename(title="Clave SSH privada")
                                   or vv.get())
                               ).grid(row=r, column=2, sticky="w", padx=(4, 0))

            ip_v = tk.StringVar(); ssh_user_v = tk.StringVar(); ssh_key_v = tk.StringVar()
            _def_ssh_p = int(appconfig.get_setting("default_ssh_port", 22) or 22)
            _def_winrm_p = int(appconfig.get_setting("default_winrm_port", 5985) or 5985)
            ssh_pass_v = tk.StringVar(); ssh_port_v = tk.StringVar(value=str(_def_ssh_p))
            winrm_user_v = tk.StringVar(); winrm_pass_v = tk.StringVar()
            winrm_port_v = tk.StringVar(value=str(_def_winrm_p))
            api_url_v = tk.StringVar(); api_key_v = tk.StringVar()
            _arow(0, "IP / Host:", ip_v)
            _arow(1, "Usuario SSH:", ssh_user_v)
            _arow(2, "Clave SSH:", ssh_key_v, browse=True)
            _arow(3, "Contraseña SSH:", ssh_pass_v, show="●")
            _arow(4, "Puerto SSH:", ssh_port_v, width=8)
            _arow(5, "Usuario WinRM:", winrm_user_v)
            _arow(6, "Contraseña WinRM:", winrm_pass_v, show="●")
            _arow(7, "Puerto WinRM:", winrm_port_v, width=8)
            _arow(8, "URL API:", api_url_v)
            _arow(9, "API Key:", api_key_v, show="●")

            # default API url follows the IP as you type it (until edited by hand)
            _auto_api = [""]
            def on_ip(*_):
                if api_url_v.get() in ("", _auto_api[0]):
                    api_url_v.set(f"http://{ip_v.get().strip()}:8384" if ip_v.get().strip() else "")
                    _auto_api[0] = api_url_v.get()
            ip_v.trace_add("write", on_ip)

            test_lbl = tk.Label(dlg, text="", bg="white", font=(_FONT, 8),
                                wraplength=440, justify="left")
            err_lbl = tk.Label(dlg, text="", bg="white", fg="#C62828", font=(_FONT, 8),
                               wraplength=440, justify="left")

            # The path defaults to the FOLDER label (set above) and no longer mirrors the
            # device name — the folder is named after the folder, not the machine.

            probed = {"nd": None}

            # Editing any identity/access field invalidates a prior "Probar conexión"
            # result so save() never reuses stale credentials/reachability (finding B).
            def _invalidate_probe(*_):
                if probed["nd"] is not None:
                    probed["nd"] = None
                    test_lbl.config(text="(credenciales cambiadas — vuelve a Probar conexión)", fg="#888")
            for _v in (id_v, ip_v, ssh_user_v, ssh_key_v, ssh_pass_v, ssh_port_v,
                       winrm_user_v, winrm_pass_v, winrm_port_v, api_url_v, api_key_v):
                _v.trace_add("write", _invalidate_probe)

            # Autodetect the IP from the LOCAL Syncthing — it already knows the address of
            # every device it has seen. As soon as a full Device ID is entered (typed, pasted
            # or picked from «Vincular conocido»), fill the IP field if the user hasn't typed
            # one, so a freshly-added device that's currently connected is reachable without
            # hunting for its address. Background lookup; never clobbers a typed value. The
            # `on_ip` trace then derives the API URL from it.
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
                            ip_v.set(found)   # the on_ip trace fills the API URL too
                            test_lbl.config(text=_T('IP autodetectada: {} — añade credenciales y pulsa «Probar conexión».').format(found), fg="#2E7D32")
                    self._post(ui)
                threading.Thread(target=work, daemon=True).start()
            id_v.trace_add("write", _autodetect_ip)

            # Edge-case: a device removed from the GRAPH (not unlinked from the cluster) keeps
            # its DeviceInfo in memory. Re-adding it must NOT reset to blanks — restore the
            # prior config (name, path, IP, credentials) from that DeviceInfo, filling only the
            # fields the user hasn't already typed. This runs synchronously before the IP
            # autodetect's background result, so its restored IP stands unless still empty.
            _prefilled = {"for": None}

            def _prefill_from_existing(*_):
                did = id_v.get().strip().upper()
                if len(did) < 50 or _prefilled["for"] == did:
                    return
                with self._devices_lock:
                    ex = next((d for d in self.s.get("devices", []) if d.device_id == did), None)
                # Also consult the in-session credential store and the saved (disk) credentials,
                # so a device you configured earlier this session — or in another folder — pre-
                # fills its credentials even in a NEW folder. This ONLY fills the dialog fields;
                # it NEVER links the device to the folder (folder_path is only restored from a
                # device already present in THIS session, since the path is per-folder).
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
                if not label_v.get().strip() and _name:
                    label_v.set(_name)
                if ex is not None and not path_v.get().strip() and ex.folder_path:
                    path_v.set(ex.folder_path)
                _ip = _val("ip", "ip", "ssh_host")    # saved entries store the IP as 'ssh_host'
                if not ip_v.get().strip() and _ip:
                    ip_v.set(_ip)
                for _var, _attr, _key in ((ssh_user_v, "ssh_user", "ssh_user"),
                                          (ssh_key_v, "ssh_key_path", "ssh_key_path"),
                                          (ssh_pass_v, "ssh_password", "ssh_password"),
                                          (winrm_user_v, "winrm_user", "winrm_user"),
                                          (winrm_pass_v, "winrm_password", "winrm_password"),
                                          (api_key_v, "api_key", "api_key")):
                    _v = _val(_attr, _key)
                    if _v and not _var.get().strip():
                        _var.set(_v)
                _sp = _val("ssh_port", "ssh_port")
                if _sp and _sp != 22 and ssh_port_v.get().strip() in ("", "22"):
                    ssh_port_v.set(str(_sp))
                _wp = _val("winrm_port", "winrm_port")
                if _wp and _wp != 5985 and winrm_port_v.get().strip() in ("", "5985"):
                    winrm_port_v.set(str(_wp))
                _au = _val("api_url", "api_url")
                if _au and not api_url_v.get().strip():
                    api_url_v.set(_au)   # set last so it isn't overwritten by on_ip
                test_lbl.config(text="↩ Credenciales previas restauradas para este dispositivo.",
                                fg="#1565C0")
            id_v.trace_add("write", _prefill_from_existing)

            def _gather_overrides():
                try:
                    sp = int(ssh_port_v.get().strip() or "22")
                except ValueError:
                    sp = 22
                try:
                    wp = int(winrm_port_v.get().strip() or "5985")
                except ValueError:
                    wp = 5985
                return {"ssh_user": ssh_user_v.get().strip() or None,
                        "ssh_key_path": ssh_key_v.get().strip() or None,
                        "ssh_password": ssh_pass_v.get().strip() or None,
                        "ssh_port": sp,
                        "winrm_user": winrm_user_v.get().strip() or None,
                        "winrm_password": winrm_pass_v.get().strip() or None,
                        "winrm_port": wp}

            def _make_deviceinfo(did, label):
                """Build a DeviceInfo from the entered fields (no probe)."""
                o = _gather_overrides()
                return DeviceInfo(
                    device_id=did, name=label, ip=ip_v.get().strip() or None,
                    api_url=api_url_v.get().strip() or None, api_key=api_key_v.get().strip() or None,
                    folder_path=path_v.get().strip() or None,
                    ssh_reachable=False, api_reachable=False, is_local=False,
                    ssh_user=o["ssh_user"], ssh_key_path=o["ssh_key_path"],
                    ssh_password=o["ssh_password"], ssh_port=o["ssh_port"],
                    winrm_user=o["winrm_user"], winrm_password=o["winrm_password"],
                    winrm_port=o["winrm_port"])

            def _do_test():
                did = id_v.get().strip().upper()
                if not did:
                    test_lbl.config(text="Introduce el Device ID primero.", fg="#C62828")
                    return
                ip = ip_v.get().strip()
                api_url = api_url_v.get().strip()
                api_key = api_key_v.get().strip()
                o = _gather_overrides()
                has_ssh = bool(o["ssh_user"] or o["ssh_key_path"] or o["ssh_password"])
                has_winrm = bool(o["winrm_user"] and o["winrm_password"])
                if not (has_ssh or has_winrm or (api_url and api_key)):
                    test_lbl.config(text="Introduce credenciales (SSH/WinRM o API) para probar.", fg="#C66000")
                    return
                test_lbl.config(text="Probando conexión…", fg="#555")
                folder = self.s["folder"]
                name = label_v.get().strip() or did[:7]

                def work():
                    # Refresh the device's CURRENT ip from the local Syncthing before probing:
                    # an offline/passive device that just reconnected may have a new DHCP
                    # address (or none was ever typed), so the field ip is stale/empty. This
                    # is why "probar y conectar" used to say "no alcanzable" for a device that
                    # WAS reachable — it probed the wrong/empty address. (This path always
                    # PREFERS the live ip over the typed one, hence `... or ip`.)
                    use_ip = resolve_live_ip(self.s.get("client"), did) or ip
                    # Rebuild the API URL with the live ip (keep scheme + port) so an API-only
                    # probe targets where the device actually is now.
                    use_api_url = api_url
                    if use_ip and api_url:
                        try:
                            _scheme = api_url.split("://")[0] if "://" in api_url else "http"
                            _m = re.search(r":(\d+)$", api_url.split("//")[-1].split("/")[0])
                            use_api_url = f"{_scheme}://{use_ip}:{_m.group(1) if _m else '8384'}"
                        except Exception:
                            use_api_url = api_url
                    try:
                        if has_ssh or has_winrm:
                            nd = probe_device(device_id=did, name=name, ip=use_ip,
                                              folder_id=folder.id, override=o)
                            nd = _dc.replace(nd, api_key=nd.api_key or api_key,
                                             api_url=nd.api_url or use_api_url)
                        else:
                            nd = probe_device_manual(device_id=did, name=name, ip=use_ip,
                                                     folder_id=folder.id, api_key=api_key,
                                                     api_url=use_api_url, folder_path="")
                    except Exception as e:
                        nd, errm = None, str(e)
                    def ui():
                        if not dlg.winfo_exists():
                            return
                        if nd is None:
                            test_lbl.config(text=_T('✗ Error: {}').format(errm), fg="#C62828")
                            return
                        probed["nd"] = nd
                        # «Examinar» solo si la API responde DIRECTAMENTE (no por SSH/WinRM).
                        _browse_btn.config(
                            state="normal" if (nd.api_reachable and nd.api_url) else "disabled")
                        if _device_kind(nd) == "ok":
                            _extra = "" if nd.api_reachable else " (API solo en localhost — «Examinar» no disponible)"
                            test_lbl.config(text="✓ Conexión OK — se configurará directamente (sin aceptar)."
                                                 + _extra, fg="#2E7D32")
                        else:
                            test_lbl.config(text="⚠ No alcanzable ahora — quedará para exploración pasiva / agente.",
                                            fg="#C66000")
                    self._post(ui)
                threading.Thread(target=work, daemon=True).start()

            def save():
                label = label_v.get().strip()
                did = id_v.get().strip().upper()
                if not label:
                    err_lbl.config(text="El nombre no puede estar vacío.")
                    return
                if not did:
                    err_lbl.config(text="El Device ID no puede estar vacío.")
                    return
                norm = _validate_device_id(did)
                if norm is False:
                    err_lbl.config(text="Device ID no válido.")
                    return
                if isinstance(norm, str):
                    did = norm
                elif norm is None:
                    # Couldn't validate (no Syncthing / network) — confirm before adding.
                    if not messagebox.askyesno(
                            "Device ID sin validar",
                            "No se pudo validar el Device ID (¿Syncthing accesible?).\n\n"
                            "¿Añadirlo de todas formas?", icon="warning"):
                        return
                t = topo()
                if did in t["nodes"]:
                    err_lbl.config(text="Ese dispositivo ya está en la topología.")
                    return
                path = path_v.get().strip() or ("~/" + _flabel)
                _os_type = probed["nd"].os_type if probed["nd"] else None
                _probs = _validate_node_path(path, _os_type)
                if _probs:
                    err_lbl.config(text="Ruta no válida: " + "; ".join(_probs))
                    return
                # Use the probed DeviceInfo if it matches; else build from the fields.
                nd = probed["nd"] if (probed["nd"] and probed["nd"].device_id == did) else _make_deviceinfo(did, label)
                nd = _dc.replace(nd, name=label, folder_path=path)
                has_creds = bool(nd.ssh_user or nd.ssh_key_path or nd.ssh_password
                                 or (nd.winrm_user and nd.winrm_password) or (nd.api_key and nd.api_url))
                with self._devices_lock:
                    if not any(d.device_id == did for d in self.s["devices"]):
                        self.s["devices"].append(nd)
                    else:
                        for i, d in enumerate(self.s["devices"]):
                            if d.device_id == did:
                                self.s["devices"][i] = nd
                                break
                # Passive/agent are ONLY for devices we can't reach right now: a reachable
                # device is configured directly, so it must not be queued for passive nor
                # offered in the agent panel (that's why those options are hidden for it).
                reachable_now = _device_kind(nd) == "ok"
                # Under the lock: _refresh_status mutates these same set/list off-thread.
                with self._devices_lock:
                    if has_creds and not reachable_now:
                        self.s.setdefault("passive_devices", set()).add(did)
                    ag = self.s.setdefault("agent_devices", [])
                    if not reachable_now and not any(d.device_id == did for d in ag):
                        ag.append(nd)
                    elif reachable_now:
                        # If a prior attempt had queued it, drop it now that it's reachable.
                        self.s.get("passive_devices", set()).discard(did)
                        self.s["agent_devices"] = [d for d in ag if d.device_id != did]
                w = max(cv.winfo_width(), 420)
                h = max(cv.winfo_height(), 300)
                _push_undo()
                t["nodes"][did] = {"id": did, "label": label, "is_local": False,
                                   "is_new": True, "online": _device_kind(nd) == "ok",
                                   # role NOT declared yet → role_known=False so it renders as
                                   # "Nuevo dispositivo" (not a fake role / "Rol desconocido").
                                   # _derive_roles sets it True with the real role once linked.
                                   "role": "sendreceive", "role_known": False, "path": path,
                                   "x": w / 2, "y": h / 2, "_placed": True}
                # Re-adding clears any prior removal so the reconcile pass keeps it.
                self.s.get("topology_removed", set()).discard(did)
                # Remember the typed creds in the SESSION store now, so the same device comes
                # pre-filled in other folders even if this device list is later rebuilt/cleared.
                self._remember_session_creds(self.s.get("devices", []))
                dlg.destroy()
                status_lbl.config(text=_T('Añadido «{}» — arrástralo sobre otro nodo para conectarlo').format(label))
                _render()

            btnf = tk.Frame(dlg, bg="white")
            btnf.pack(fill=tk.X, padx=14, pady=(8, 12))
            ttk.Button(btnf, text="Añadir", command=save).pack(side=tk.RIGHT)
            ttk.Button(btnf, text="Cancelar", command=dlg.destroy).pack(side=tk.RIGHT, padx=(0, 6))
            ttk.Button(btnf, text="Probar conexión", command=_do_test).pack(side=tk.LEFT)
            test_lbl.pack(anchor="w", padx=14, pady=(2, 0))
            err_lbl.pack(anchor="w", padx=14)
            dlg.bind("<Return>", lambda e: save())

        # Build or RECONCILE the topology graph against the current device list. We
        # never reuse a cached graph blindly: devices discovered after the first build
        # (or after a 'Redescubrir') are merged in, preserving the user's edits. A
        # "Cargando…" note stays until we've confirmed the graph covers every non-local
        # device shown in the Devices window (contrast check).
        if True:
            status_lbl.config(text="Cargando topología…", fg="#555")
            my_gen = self._show_gen

            def work():
                client = self.s.get("client")
                try:
                    my_id = self.s.get("my_id") or (client.get_my_device_id() if client else "")
                except Exception:
                    my_id = ""
                self.s["my_id"] = my_id
                with self._devices_lock:
                    devs_snapshot = list(self.s.get("devices", []))
                name_map = _resolve_name_map(devs_snapshot, client,
                                             extra_names=_hub_name_map(devs_snapshot, folder.id))
                online_ids = set()
                # Build the graph defensively: a malformed device/folder must not kill the
                # worker thread and leave the page stuck on "Cargando topología…" forever.
                try:
                    for d in devs_snapshot:
                        if _device_kind(d) == "ok":
                            online_ids.add(d.device_id)
                    built = _build_topology(folder, my_id, name_map, online_ids,
                                            devices=devs_snapshot)
                except Exception as e:
                    def _fail(_e=e):
                        if self._show_gen != my_gen or not status_lbl.winfo_exists():
                            return
                        status_lbl.config(
                            text=_T('No se pudo cargar la topología: {}').format(_e), fg="#C62828")
                    self._post(_fail)
                    return

                # N4: remember the mesh across sessions. Load the prior snapshot for this
                # folder so offline peers (and the links between them, which no online node
                # can report) are redrawn dotted; then persist the merged best-known graph.
                snap = None
                try:
                    snap = appconfig.load_topology_snapshot(folder.id)
                except Exception:
                    snap = None
                if snap:
                    snap = _topology_from_json(snap)
                try:
                    # Save reality (built) plus the offline-only part of the prior snapshot,
                    # so a degraded (some-offline) view never wipes a known full mesh.
                    to_save = _merge_remembered(_copy_topology(built), snap, tag=False,
                                                removed=self.s.get("topology_removed")) \
                        if snap else built
                    # NEVER persist a node the user removed/unshared (topology_removed): otherwise
                    # _merge_remembered would re-add an unshared offline peer here and resurrect
                    # it as a ghost next session. This is the authoritative guard — it also closes
                    # the last-writer race with the execute-side snapshot prune (whichever save
                    # lands last, a removed id is filtered out either way).
                    _rm = self.s.get("topology_removed") or set()
                    if to_save and _rm:
                        to_save["nodes"] = {k: v for k, v in to_save.get("nodes", {}).items()
                                            if k not in _rm}
                        to_save["edges"] = {e for e in to_save.get("edges", set())
                                            if not (e & _rm)}
                        to_save["edge_dir"] = {e: v for e, v in to_save.get("edge_dir", {}).items()
                                               if not (e & _rm)}
                    if to_save and to_save.get("edges"):
                        appconfig.save_topology_snapshot(folder.id, _topology_to_json(to_save))
                except Exception:
                    pass

                def ui():
                    if self._show_gen != my_gen:
                        return
                    cur = self.s.get("topology")
                    _added = []
                    if not cur:
                        self.s["topology"] = built
                        self.s["topology_orig"] = _copy_topology(built)
                    else:
                        orig = self.s.get("topology_orig") or _copy_topology(cur)
                        self.s["topology_orig"] = orig
                        _added = _reconcile_topology(cur, orig, built, my_id,
                                                     removed=self.s.get("topology_removed"))
                    # 1-B: devices added from the Devices window appear here as UNCONNECTED
                    # nodes so you can share the folder with them. They aren't folder members
                    # yet, so _build_topology excludes them — inject them as is_new nodes
                    # (same shape as «➕ Nuevo dispositivo»); reconcile then preserves them.
                    _manual = self.s.get("manual_topo_nodes") or {}
                    if _manual:
                        _t = self.s["topology"]
                        _removed = self.s.get("topology_removed", set())
                        with self._devices_lock:
                            _dm = {d.device_id: d for d in self.s.get("devices", [])}
                        for _mid, _info in _manual.items():
                            if _mid in _t["nodes"] or _mid in _removed:
                                continue
                            _d = _dm.get(_mid)
                            _t["nodes"][_mid] = {
                                "id": _mid,
                                "label": _info.get("label") or (_d.name if _d else _mid[:7]),
                                "is_local": False, "is_new": True,
                                "online": bool(_d and _device_kind(_d) == "ok"),
                                # role not declared yet → role_known=False renders "Nuevo
                                # dispositivo" instead of a fake role / "Rol desconocido".
                                "role": "sendreceive", "role_known": False,
                                "path": (_info.get("path") or (_d.folder_path if _d else None)),
                                # NOT placed → _layout_circle() (called below) positions it around
                                # the centroid. Placing it at the exact centre (_placed:True) made
                                # it stack UNDER the local node, so it looked like it never
                                # appeared in Topología (B1).
                                "_placed": False}
                    # Keep the snapshot as a render-only OVERLAY (not baked into the graph, so
                    # it never contaminates the rename diff nor accumulates): _render draws the
                    # offline-mesh links from it dotted. Drop anything the user removed.
                    if snap:
                        removed = self.s.get("topology_removed", set())
                        self.s["topology_snapshot"] = {
                            "nodes": {k: v for k, v in snap["nodes"].items() if k not in removed},
                            "edges": {e for e in snap["edges"] if not (e & removed)},
                            "edge_dir": snap.get("edge_dir", {})}
                    # The graph is scoped to the FOLDER: only devices that actually share
                    # this folder are nodes (reachable ≠ sharing the folder). A discovered
                    # device that doesn't have the folder is intentionally absent — note how
                    # many were filtered so the count isn't surprising.
                    topo_now = self.s["topology"]
                    node_ids = set(topo_now["nodes"])
                    n_peers = sum(1 for nd in topo_now["nodes"].values()
                                  if not nd.get("is_local"))
                    not_member = [d.name for d in devs_snapshot
                                  if not d.is_local and d.device_id not in node_ids]
                    if n_peers == 0:
                        status_lbl.config(
                            text="Solo este equipo comparte la carpeta — añade dispositivos "
                                 "para enlazarla.", fg="#555")
                    elif not_member:
                        status_lbl.config(
                            text=_T('✓ {} dispositivo(s) comparten la carpeta. ({} descubierto(s) no la comparten y no se muestran.)').format(n_peers, len(not_member)), fg="#2E7D32")
                    else:
                        status_lbl.config(
                            text=_T('✓ {} dispositivo(s) comparten la carpeta.').format(n_peers),
                            fg="#2E7D32")
                    # Recompute online for EVERY node from the current device reachability —
                    # including manually-injected is_new nodes, which _reconcile_topology and
                    # the manual injection don't refresh on revisit. Without this, a device
                    # probed OK in the Devices window showed red/offline here until the slow
                    # «Estado» poll (B2).
                    with self._devices_lock:
                        _dmap = {d.device_id: d for d in self.s.get("devices", [])}
                    for _nid, _n in self.s["topology"]["nodes"].items():
                        _dd = _dmap.get(_nid)
                        _reach = bool(_dd and _device_kind(_dd) == "ok")
                        _n["online"] = bool(_n.get("is_local") or _nid == my_id or _reach)
                        # Reachable again → we can see/verify it, so clear any stale
                        # "unconfirmed" mark from a prior abandoned run (if it still needs the
                        # change, the diff will show it again).
                        if _reach or _n.get("is_local"):
                            _n.pop("unconfirmed", None)
                    if _added:
                        # A device appeared since the last view (Redescubrir / hub revealed a new
                        # peer) → re-organise the whole graph and refit so it slots in cleanly
                        # instead of being dropped near the centroid where nodes/arrows overlap
                        # (user request). This worker only runs on page entry / Redescubrir, never
                        # on the background poll, so it can't silently rearrange behind the user.
                        _layout_circle(force=True)
                        _fit_view(set_auto=True)
                    else:
                        _layout_circle()
                        if view.get("auto", True):   # initial view = same fit as ⊡ Ajustar
                            _fit_view()
                    _render()
                self._post(ui)
            threading.Thread(target=work, daemon=True).start()

        self._next_handlers[4] = self._open_change_preview
