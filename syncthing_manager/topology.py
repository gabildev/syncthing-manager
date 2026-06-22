"""Pure topology-graph model — no GUI / tkinter dependency.

These helpers build and reason about the folder-sharing graph (nodes = devices,
edges = shared-folder links with a per-edge direction). They are pure and testable,
and are imported by BOTH the Tk GUI and the headless CLI (`topology` command) — which
is why they live here instead of gui.py: importing gui.py pulls in tkinter, and the
CLI must run on headless servers where python3-tk isn't installed.

Link-direction model: `topo["edge_dir"]` (frozenset(pair) → frozenset(senders)) is the
source of truth; node roles are DERIVED from it via `_derive_roles`.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from .i18n import t as _T

if TYPE_CHECKING:
    from .models import DeviceInfo


def _device_kind(d: "DeviceInfo") -> str:
    """Classify a device as 'ok', 'offline', or 'problem'.

    offline  = Syncthing has never seen an IP for this device (no location known)
    problem  = has a last-known IP but is not currently reachable (needs credentials or fixing)
    ok       = reachable via any method
    """
    if d.is_local or d.api_reachable or d.ssh_reachable or d.winrm_reachable:
        return "ok"
    if not d.ip:
        return "offline"
    return "problem"


# ── Topology model ──────────────────────────────────────────────────────────
# Syncthing is a mesh: a folder is shared between two devices when BOTH list each
# other and the folder. There is no per-link direction — the arrow is DERIVED from
# each node's folder `type` (role): sendreceive ↔, sendonly →, receiveonly ←.

_ROLE_ORDER  = ["sendreceive", "sendonly", "receiveonly"]
_ROLE_LABELS = {
    "sendreceive": "↔ enviar y recibir",
    "sendonly":    "→ solo enviar",
    "receiveonly": "← solo recibir",
}
_ROLE_SHORT  = {"sendreceive": "↔ envía/recibe", "sendonly": "→ solo envía",
                "receiveonly": "← solo recibe"}


def _copy_topology(topo: dict) -> Optional[dict]:
    if not topo:
        return None
    return {
        "my_id": topo.get("my_id"),
        "nodes": {k: dict(v) for k, v in topo["nodes"].items()},
        "edges": set(topo["edges"]),
        "edge_dir": dict(topo.get("edge_dir", {})),
    }


def _senders_from_roles(a: str, b: str, role_a: str, role_b: str) -> frozenset:
    """Who SENDS across an edge (a,b), derived from both endpoint roles. Used to seed the
    per-edge direction (`edge_dir`) from a device's real folder type on first build."""
    def sends(r): return r in ("sendreceive", "sendonly")
    def recvs(r): return r in ("sendreceive", "receiveonly")
    s = set()
    if sends(role_a) and recvs(role_b):
        s.add(a)
    if sends(role_b) and recvs(role_a):
        s.add(b)
    return frozenset(s)


def _arrow_from_senders(a: str, b: str, senders) -> str:
    """tk arrow constant for an edge drawn a→b, from its sender set (edge_dir value)."""
    sa, sb = a in senders, b in senders
    if sa and sb:
        return "both"
    if sa:
        return "last"      # a sends → arrow points at b (second point)
    if sb:
        return "first"
    return "none"          # nobody sends → no flow (invalid)


def _derive_roles(topo: dict) -> None:
    """Recompute each node's role FROM the per-edge directions (`edge_dir`), the source of
    truth in the link-direction model. A node touched by ≥1 directed edge gets its role
    (and role_known=True); nodes with only unknown/offline edges keep their current role."""
    if not topo:
        return
    nodes = topo["nodes"]
    ed = topo.get("edge_dir", {})
    S: dict = {}
    R: dict = {}
    touched: set = set()
    for e, senders in ed.items():
        pair = set(e)
        for n in pair:
            if n not in nodes:
                continue
            touched.add(n)
            if n in senders:
                S[n] = True
            if (pair - {n}) & senders:
                R[n] = True
    for n in touched:
        s, r = S.get(n, False), R.get(n, False)
        nodes[n]["role"] = ("sendreceive" if s and r else
                            "sendonly" if s else "receiveonly" if r else "sendreceive")
        nodes[n]["role_known"] = True


def _shares_folder(d) -> bool:
    """Whether a NON-LOCAL device actually shares THIS folder — the only thing that makes it
    a topology node by itself. Membership shows up as evidence we read from the device: its
    folder role, its on-disk path, or the peers it shares the folder with. A device that was
    merely discovered/reachable but does NOT have this folder reports none of those, so it is
    NOT a node (reachable ≠ sharing the folder). Offline members aren't nodes via this path —
    they're pulled in by a reference (local-config entry or a reachable peer that lists them).
    Cross-folder staleness is handled upstream by resetting state when the folder changes."""
    if getattr(d, "is_local", False):
        return True
    return bool(getattr(d, "folder_role", None)
                or (getattr(d, "folder_path", None) or "").strip()
                or (getattr(d, "folder_peers", None) or []))


def _name_is_placeholder(name, device_id: str) -> bool:
    """True for the labels discovery falls back to when a device is unnamed: blank, the
    full device id, or the 7-char short id. These are NOT real user-assigned names."""
    return (not name) or name == device_id or name == device_id[:7]


def _resolve_name_map(devs, client, extra_names=None) -> dict:
    """deviceID → best friendly name for topology labels (N7: "resolve deviceID→name").

    A REAL (user-assigned) name always beats the short-id placeholder discovery falls
    back to, regardless of which source reported it first; and among competing REAL names
    the first source offered wins. Sources are offered in AUTHORITY order so the right name
    survives a conflict (e.g. two devices that named the same peer differently):
      1. the LOCAL node's device config — YOUR own name for the peer is authoritative;
      2. every discovered DeviceInfo (a member's name is seeded from local config, so it
         only adds names for hub-revealed peers the local config doesn't list);
      3. any LOCAL pending request's self-announced name;
      4. `extra_names` — a {deviceID: name} map the caller resolved elsewhere, typically
         the names a reachable HUB knows for its folder peers (deterministic per caller).

    The hub map matters because the topology graph can show a peer that exists ONLY via a
    hub's `folder_peers` (no DeviceInfo of its own, e.g. credentials entered in the
    Topology window rather than the Devices window) — its name lives in the HUB's config,
    not ours, so without it the node falls back to a bare device id.

    `client` may be None to skip the (blocking) local config/pending API calls — e.g. when
    resolving on the UI thread."""
    name_map: dict = {}

    def _offer(did: str, nm) -> None:
        if not did or not nm:
            return
        cur = name_map.get(did)
        # A real name replaces a placeholder; among real names (or among placeholders)
        # the first one offered wins — so don't clobber an already-resolved real name.
        if cur is None or (_name_is_placeholder(cur, did) and not _name_is_placeholder(nm, did)):
            name_map[did] = nm

    # 1. Local node's config — authoritative (your own naming wins a conflict).
    if client is not None:
        try:
            for dc in client.get_config_devices():
                _offer(dc.device_id, dc.name)
        except Exception:
            pass
    # 2. Discovered DeviceInfos (adds names for hub-revealed peers not in local config).
    for d in (devs or []):
        _offer(getattr(d, "device_id", ""), getattr(d, "name", ""))
    # 3. Local pending requests' self-announced names.
    if client is not None:
        try:
            for did, info in (client.get_pending_devices() or {}).items():
                _offer(did, (info or {}).get("name"))
        except Exception:
            pass
    # 4. Names a reachable hub knows for its folder peers (caller-resolved).
    for did, nm in (extra_names or {}).items():
        _offer(did, nm)
    return name_map


def _build_topology(folder, my_id: str, name_map: dict, online_ids: set,
                    devices=None) -> dict:
    """Build the REAL topology graph from observed adjacency — works for any shape
    (mesh, star, chain, tree…), not just 'everything hangs off the local node'.

    The graph is scoped to the FOLDER: a node appears only when the device actually shares
    this folder (see `_shares_folder`) or is referenced as a member by the local config /
    a reachable peer. Devices that were merely discovered/reachable but don't have this
    folder are excluded (they can still be added by hand). Edges come from each device's own
    folder membership (`DeviceInfo.folder_peers`, symmetric sharing) plus the local node's
    authoritative view from `folder.raw`. Each node carries its real `role` (folder type)
    when we could read it (`role_known=True`); offline peers default to sendreceive with
    role_known=False so the renderer can mark links of unknown direction."""
    raw = folder.raw or {}
    devs = list(devices or [])
    by_id = {d.device_id: d for d in devs}

    edges: set = set()
    known_role: dict = {}
    node_ids: set = set()
    if my_id:
        node_ids.add(my_id)

    def _add_member(owner_id: str, peer_id: str, introducer: str) -> None:
        """Add the edge for a folder member. If the member was *introduced* by another
        device, the real link is introducer↔peer (the owner reaches it through the
        introducer) — NOT owner↔peer, which would be a phantom edge."""
        if not peer_id:
            return
        src = introducer if introducer else owner_id
        node_ids.add(peer_id)
        node_ids.add(src)
        if peer_id != src:
            edges.add(frozenset((src, peer_id)))

    # Adjacency + roles from every device that actually shares this folder. A device that
    # only self-reports the folder (reachable member with no peers yet) still becomes a node;
    # offline/referenced members are pulled in by the `_add_member` references below.
    for d in devs:
        if not _shares_folder(d):
            continue  # reachable ≠ sharing the folder — not a node, no edges
        if getattr(d, "folder_role", None):
            known_role[d.device_id] = d.folder_role
        node_ids.add(d.device_id)
        intro = getattr(d, "folder_introducers", None) or {}
        for p in (getattr(d, "folder_peers", None) or []):
            _add_member(d.device_id, p, intro.get(p, ""))

    # Local node's authoritative view from folder.raw (covers the case where the local
    # DeviceInfo wasn't in `devices`, and pins the local role).
    if my_id:
        if raw.get("type"):
            known_role.setdefault(my_id, raw.get("type"))
        for e in (raw.get("devices") or []):
            if isinstance(e, dict) and e.get("deviceID") and e["deviceID"] != my_id:
                _add_member(my_id, e["deviceID"], e.get("introducedBy") or "")

    nodes: dict = {}
    for nid in node_ids:
        d = by_id.get(nid)
        is_local = bool(nid == my_id)
        nodes[nid] = {
            "id": nid,
            "label": (name_map.get(nid) or (d.name if d else None)
                      or (_T("Este equipo") if is_local else nid[:7])),
            "is_local": is_local,
            "is_new": False,
            "online": True if is_local else (nid in online_ids),
            # reachable = we could actually READ this device's config (local, or
            # api/ssh/winrm OK). Only then is its folder path knowable — an online-but-
            # unconfigured peer is NOT reachable, so its empty path isn't a real problem.
            "reachable": bool(is_local or (d and (getattr(d, "api_reachable", False)
                                                   or getattr(d, "ssh_reachable", False)
                                                   or getattr(d, "winrm_reachable", False)))),
            "role": known_role.get(nid, "sendreceive"),
            "role_known": (nid in known_role) or is_local,
            "path": (folder.path if is_local else (d.folder_path if d else "")) or "",
            # Useful for redrawing a remembered node next session (icon) and for agent/
            # passive config of an offline member; persisted in the snapshot (O8).
            "os_type": (getattr(d, "os_type", None) if d else None),
        }
    # Per-edge direction (source of truth in the link model). Seed it from the real roles
    # for edges whose BOTH endpoints' roles we know; edges touching an offline/unknown peer
    # stay out of edge_dir → drawn as "unknown direction" until probed or edited.
    def _role_of(nid):
        if nid == my_id and raw.get("type"):
            return raw.get("type")
        return known_role.get(nid)
    edge_dir: dict = {}
    for e in edges:
        ids = sorted(e)
        ra, rb = _role_of(ids[0]), _role_of(ids[1])
        if ra and rb:
            edge_dir[e] = _senders_from_roles(ids[0], ids[1], ra, rb)
    topo = {"my_id": my_id, "nodes": nodes, "edges": edges, "edge_dir": edge_dir}
    _derive_roles(topo)   # keep node roles consistent with the seeded directions
    return topo


def _reconcile_topology(cur: dict, orig: dict, base: dict, my_id: str,
                        removed: Optional[set] = None) -> list:
    """Merge devices present in `base` (freshly built from the current device list)
    into the live graph `cur` and the baseline `orig`, WITHOUT discarding the user's
    edits. A device discovered after the first build is a pre-existing folder member,
    so it goes into both `orig` and `cur` (default-connected to the local node) — not
    treated as a user-added link. Existing nodes keep their role/path/edges; only their
    OBSERVED state (online + reachable) is refreshed. Nodes the user explicitly removed
    (`removed`) are NOT re-added. Returns the list of node ids that were added."""
    removed = removed or set()
    added = []
    for nid, node in base["nodes"].items():
        if nid in removed:
            continue  # user deleted this node on purpose — don't resurrect it
        if nid not in cur["nodes"]:
            cur["nodes"][nid] = dict(node)
            orig["nodes"].setdefault(nid, dict(node))
            # Bring the REAL edges incident to this node from the observed graph (its actual
            # neighbours) + their seeded direction (edge_dir), into BOTH cur and orig (it's
            # pre-existing reality, not a user edit).
            bed = base.get("edge_dir", {})
            for e in base["edges"]:
                if nid in e:
                    cur["edges"].add(e)
                    orig["edges"].add(e)
                    if e in bed:
                        cur.setdefault("edge_dir", {})[e] = bed[e]
                        orig.setdefault("edge_dir", {})[e] = bed[e]
            added.append(nid)
        elif not cur["nodes"][nid].get("is_new"):
            # Refresh OBSERVED state (online + reachable): a peer that reconnected since the
            # first build must not keep reachable=False, which would wrongly keep it out of
            # _merge_remembered's `readable` set and skew the "sin ruta" issue check. We do NOT
            # refresh role/role_known here — those are derived from the user's edited edges and
            # refreshing them would clobber the user's in-progress topology edits.
            cur["nodes"][nid]["online"] = node.get("online", cur["nodes"][nid].get("online"))
            if "reachable" in node:
                cur["nodes"][nid]["reachable"] = node["reachable"]
            # Upgrade a placeholder label (the deviceID shown while discovery was still
            # running) to the real device name once it's available — without clobbering a
            # name the user typed (only replace the id-prefix fallback).
            blabel = node.get("label")
            if (blabel and blabel not in (nid, nid[:7])
                    and cur["nodes"][nid].get("label") in (nid, nid[:7])):
                cur["nodes"][nid]["label"] = blabel
                if orig["nodes"].get(nid):
                    orig["nodes"][nid]["label"] = blabel
    # Prune nodes that are NOT members of THIS folder. `base` always contains every member
    # (the local config's folder.raw.devices are seeded into it), so anything in `cur` that
    # base doesn't have — and that the user didn't add by hand (is_new) — is a leftover from
    # a previous folder/state ("linked" devices that don't actually share THIS folder). Drop
    # it from BOTH cur and orig (and its edges) so it never lingers nor shows as a spurious
    # diff. Devices merely discovered/reachable but not sharing the folder were never base
    # members, so this also keeps "reachable ≠ sharing the folder" honest across rebuilds.
    base_ids = set(base["nodes"])
    stale = [nid for nid, n in cur["nodes"].items()
             if nid != my_id and nid not in base_ids
             and not n.get("is_local") and not n.get("is_new")]
    for nid in stale:
        cur["nodes"].pop(nid, None)
        orig["nodes"].pop(nid, None)
        cur["edges"] = {e for e in cur["edges"] if nid not in e}
        orig["edges"] = {e for e in orig["edges"] if nid not in e}
        cur["edge_dir"] = {e: s for e, s in cur.get("edge_dir", {}).items() if nid not in e}
        orig["edge_dir"] = {e: s for e, s in orig.get("edge_dir", {}).items() if nid not in e}
    # Roles are DERIVED from edge directions (link model) — recompute both graphs so the
    # diff stays "user edits only" (unedited edge_dir is identical in cur and orig).
    _derive_roles(cur)
    _derive_roles(orig)
    return added


def _edge_names(edge, topo) -> tuple:
    ids = sorted(edge)
    def nm(i):
        n = topo["nodes"].get(i)
        return n["label"] if n else i[:7]
    if len(ids) >= 2:
        return (nm(ids[0]), nm(ids[1]))
    return (nm(ids[0]), nm(ids[0]))


def _edge_arrow(role_first: str, role_second: str) -> str:
    """tk arrow constant for an edge drawn first→second, derived from both roles."""
    def sends(r): return r in ("sendreceive", "sendonly")
    def recvs(r): return r in ("sendreceive", "receiveonly")
    a2b = sends(role_first) and recvs(role_second)
    b2a = sends(role_second) and recvs(role_first)
    if a2b and b2a:
        return "both"
    if a2b:
        return "last"
    if b2a:
        return "first"
    return "none"


def orphaned_node_ids(orig_edges, cur_edges, locked=None) -> set:
    """Node ids that had ≥1 link in `orig_edges` but have NONE after this apply — fully
    disconnected, so the folder should be UNSHARED on them. LOCKED links are KEPT, so a node
    still tied by a locked link is NOT orphaned. The local node (if any) is the caller's job to
    exclude — its own folder is never removed this way. Single source of truth shared by the
    apply (compute_topology_diff), the change preview (_topology_delta) and the graph render,
    so the three can't disagree about who gets unshared."""
    locked = set(locked or set())
    oe, ce = set(orig_edges), set(cur_edges)
    kept = ce | {e for e in (oe - ce) if e in locked}   # locked-but-"removed" links stay

    def _ids(es):
        out = set()
        for e in es:
            out |= set(e)
        return out
    return _ids(oe) - _ids(kept)


def _topology_delta(orig: Optional[dict], cur: Optional[dict], locked=None) -> dict:
    if not orig or not cur:
        return {"any": False}
    new_devices = [n for n in cur["nodes"].values() if n.get("is_new")]
    oe, ce = orig["edges"], cur["edges"]
    links_added   = [_edge_names(e, cur) for e in (ce - oe)]
    links_removed = [_edge_names(e, cur) for e in (oe - ce)]
    roles_changed = []
    for nid, n in cur["nodes"].items():
        on = orig["nodes"].get(nid)
        # Gate on role_known exactly like compute_topology_diff (the apply): a node whose role
        # we can't actually observe (role_known=False) must NOT show as "rol cambiado" in the
        # preview, or the preview would promise a role change the apply silently skips.
        if on and on.get("role") != n.get("role") and n.get("role_known", True):
            roles_changed.append((n["label"], on.get("role"), n.get("role")))
    # Non-local devices whose LAST link was removed → they'll be UNSHARED on apply (the folder
    # is removed from them, not left peerless). Same locked-aware logic as the apply, so the
    # preview never promises an unshare the apply won't do (e.g. a node tied by a locked link).
    unshared = sorted(cur["nodes"][nid].get("label", nid[:7])
                      for nid in orphaned_node_ids(oe, ce, locked)
                      if nid in cur["nodes"] and not cur["nodes"][nid].get("is_local"))
    any_ = bool(new_devices or links_added or links_removed or roles_changed)
    return {"any": any_, "new_devices": new_devices, "links_added": links_added,
            "links_removed": links_removed, "roles_changed": roles_changed,
            "unshared": unshared}


def _topology_to_json(topo: Optional[dict]) -> Optional[dict]:
    """Serialize a topology graph to JSON-safe primitives (frozenset edges/keys → lists).
    Persisted per folder so a known mesh can be redrawn next session when peers are offline.
    Only stable fields are kept (no x/y layout, no transient `remembered_edges` tag)."""
    if not topo or not topo.get("nodes"):
        return None
    keep = ("id", "label", "is_local", "is_new", "online", "reachable", "role",
            "role_known", "path", "os_type", "unconfirmed")
    nodes = {nid: {k: n[k] for k in keep if k in n} for nid, n in topo["nodes"].items()}
    edges = [sorted(e) for e in topo.get("edges", set()) if len(e) == 2]
    edge_dir = [{"pair": sorted(e), "senders": sorted(s)}
                for e, s in topo.get("edge_dir", {}).items() if len(e) == 2]
    return {"my_id": topo.get("my_id"), "nodes": nodes, "edges": edges, "edge_dir": edge_dir}


def _topology_from_json(data: Optional[dict]) -> Optional[dict]:
    """Inverse of `_topology_to_json`. Returns a topology dict, or None if malformed."""
    if not data or not isinstance(data, dict) or not isinstance(data.get("nodes"), dict):
        return None
    # Honor the "None if malformed" contract for ANY corrupt shape (a hand-edited or old-format
    # snapshot whose nodes/edges aren't the expected types): a raised exception here would crash
    # the (unwrapped) topology-load worker thread and freeze the page on "Cargando topología…".
    try:
        nodes = {nid: dict(n) for nid, n in data["nodes"].items() if isinstance(n, dict)}
        edges = {frozenset(e) for e in data.get("edges", []) or []
                 if isinstance(e, (list, tuple)) and len(e) == 2}
        edge_dir = {}
        for item in data.get("edge_dir", []) or []:
            p = item.get("pair", []) if isinstance(item, dict) else []
            if isinstance(p, (list, tuple)) and len(p) == 2:
                edge_dir[frozenset(p)] = frozenset(item.get("senders", []) or [])
    except (TypeError, ValueError, AttributeError):
        return None
    return {"my_id": data.get("my_id"), "nodes": nodes, "edges": edges, "edge_dir": edge_dir}


def _merge_remembered(topo: dict, snapshot: Optional[dict], tag: bool = True,
                      removed: Optional[set] = None) -> dict:
    """Supplement a freshly-built graph with the part of a saved `snapshot` we CAN'T observe
    right now: purely-offline nodes, and edges whose BOTH endpoints are unreadable now. Live,
    readable nodes stay authoritative — an edge touching a readable node is trusted as-is, so
    a link the user removed while a peer was offline is NOT resurrected. Nodes/edges in
    `removed` (the user's topology_removed set) are NEVER re-added — the function self-guards
    against resurrecting an unshared/removed peer, independent of any caller-side filtering.
    Remembered edges are recorded in `topo['remembered_edges']` (when `tag`) so the renderer
    can dot them. Mutates and returns `topo`."""
    if not topo or not snapshot:
        return topo
    snap = _topology_from_json(snapshot) if "edges" in snapshot and isinstance(
        snapshot.get("edges"), list) else snapshot
    if not snap:
        return topo
    removed = removed or set()
    remembered = topo.setdefault("remembered_edges", set())
    # Purely-offline members we have no live trace of → add as offline nodes (but NEVER a node
    # the user removed/unshared).
    for nid, sn in snap.get("nodes", {}).items():
        if nid not in topo["nodes"] and nid not in removed:
            nn = dict(sn)
            nn.update(online=False, reachable=False, is_new=False, remembered=True)
            topo["nodes"][nid] = nn
    readable = {nid for nid, n in topo["nodes"].items()
                if n.get("is_local") or n.get("reachable")}
    sed = snap.get("edge_dir", {})
    for e in snap.get("edges", set()):
        if len(e) == 2 and all(x in topo["nodes"] for x in e) \
                and not any(x in removed for x in e) \
                and not any(x in readable for x in e) and e not in topo["edges"]:
            topo["edges"].add(e)
            if e in sed:
                topo.setdefault("edge_dir", {})[e] = sed[e]
            if tag:
                remembered.add(e)
    return topo


def _topology_issues_detailed(topo: Optional[dict]) -> list:
    """Like _detect_topology_issues, but each item is a (is_hard, message) tuple. `is_hard` is
    False only for the "isolated node" warning (disconnecting a node can be deliberate) — the GUI
    uses the flag to colour the counter amber-vs-red WITHOUT matching translated text. Pure;
    messages are i18n'd (Spanish source = key)."""
    if not topo or not topo.get("nodes"):
        return []
    nodes = topo["nodes"]
    edges = topo.get("edges", set())
    deg = {nid: 0 for nid in nodes}
    for e in edges:
        for nid in e:
            if nid in deg:
                deg[nid] += 1
    issues = []
    for nid, n in nodes.items():
        label = n.get("label", nid[:7])
        # Only flag a missing path for a node we can actually READ now (reachable). An
        # offline OR online-but-unconfigured node's path is resolved later via passive
        # exploration / agent, so an empty path there is not a real problem yet (N5).
        if (not n.get("is_local") and n.get("reachable")
                and not (n.get("path") or "").strip()):
            issues.append((True, _T("«{}»: sin ruta de carpeta definida.").format(label)))
        if deg.get(nid, 0) == 0:
            issues.append((False, _T("«{}»: sin enlaces (no sincroniza con nadie).").format(label)))
    edir = topo.get("edge_dir", {})
    for e in edges:
        ids = sorted(e)
        if len(ids) < 2:
            continue
        a, b = nodes.get(ids[0]), nodes.get(ids[1])
        if not a or not b:
            continue
        la = a.get("label", ids[0][:7])
        lb = b.get("label", ids[1][:7])
        senders = edir.get(e)
        if senders is None:
            continue  # unknown direction (offline) — not flagged
        if len(senders) == 0:
            issues.append((True, _T("«{}» — «{}»: ningún extremo envía (no se sincroniza).").format(la, lb)))
        elif (len(senders) == 1 and a.get("online", True) and b.get("online", True)
              and _edge_arrow(a.get("role"), b.get("role")) == "both"):
            issues.append((True, _T("«{}» — «{}»: dirección no realizable — ambos quedan "
                                    "envía/recibe por sus otros enlaces (será bidireccional).").format(la, lb)))
    return issues


def _detect_topology_issues(topo: Optional[dict]) -> list:
    """Read-only sanity check of an edited topology graph: flag configurations that
    won't sync as the user likely expects (no path, isolated node, no-flow link).
    Pure and testable — does not touch the network. Returns a list of message strings."""
    return [msg for _hard, msg in _topology_issues_detailed(topo)]
