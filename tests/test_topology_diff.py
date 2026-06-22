from __future__ import annotations

from syncthing_manager.renamer import (
    compute_topology_diff, apply_topology_diff_to_cfg, device_topology_changes,
    serialize_topology_diff, deserialize_topology_diff, _topo_entries_to_add,
    _topo_create_folder_cfg, _topo_decide_cfg,
)


class TestNewDeviceUnpaused:
    """A device just added to the topology must end up with an ACTIVE (un-paused) folder —
    otherwise sharing never resumes and Syncthing never creates the directory on disk."""

    def test_create_cfg_is_not_paused(self):
        cfg = _topo_create_folder_cfg("f", "Label", "~/Label", "A", "sendreceive", {"B"})
        assert cfg["paused"] is False

    def test_decide_cfg_create_is_not_paused(self):
        cfg, verb, is_create = _topo_decide_cfg(
            None, "f", "Label", "~/Label", "A", "sendreceive", {"B"}, None, is_new=True)
        assert is_create is True
        assert cfg["paused"] is False

    def test_decide_cfg_new_device_clears_stale_paused_on_diff(self):
        # A folder that already exists on the device but is PAUSED: the diff-update path
        # copies the cfg verbatim, so without the is_new override it would stay paused.
        existing = {"id": "f", "type": "sendreceive", "paused": True,
                    "devices": [{"deviceID": "B"}]}
        diff = {"role_changed": {}, "links_added": {frozenset(("A", "B"))},
                "links_removed": set()}
        cfg, verb, is_create = _topo_decide_cfg(
            existing, "f", "Label", "~/Label", "A", "sendreceive", {"B"}, diff, is_new=True)
        assert is_create is False
        assert cfg["paused"] is False

    def test_decide_cfg_existing_device_does_not_force_unpause(self):
        # An ESTABLISHED device (not is_new) must keep its own paused state — we only
        # force-resume folders for freshly added devices.
        existing = {"id": "f", "type": "sendreceive", "paused": True,
                    "devices": [{"deviceID": "B"}]}
        diff = {"role_changed": {}, "links_added": {frozenset(("A", "B"))},
                "links_removed": set()}
        cfg, verb, is_create = _topo_decide_cfg(
            existing, "f", "Label", "~/Label", "A", "sendreceive", {"B"}, diff, is_new=False)
        assert cfg["paused"] is True


class TestEntriesToAdd:
    def test_create_registers_all_missing_neighbors(self):
        # On a fresh CREATE the new folder lists every neighbour, so every missing one
        # needs a device entry (else the folder references an unknown device).
        diff = {"role_changed": {}, "links_added": {frozenset(("A", "B"))}, "links_removed": set()}
        got = set(_topo_entries_to_add("A", {"B", "C"}, {"A"}, diff, is_create=True))
        assert got == {"B", "C"}

    def test_update_registers_only_newly_linked(self):
        diff = {"role_changed": {}, "links_added": {frozenset(("A", "B"))}, "links_removed": set()}
        got = set(_topo_entries_to_add("A", {"B", "C"}, {"A"}, diff, is_create=False))
        assert got == {"B"}     # C already shares the folder → already a device entry

    def test_no_diff_registers_all(self):
        got = set(_topo_entries_to_add("A", {"B", "C"}, {"A"}, None))
        assert got == {"B", "C"}


def _topo(nodes, edges):
    """nodes: {id: (role, online)}; edges: iterable of pairs."""
    return {
        "nodes": {nid: {"label": nid, "role": role, "role_known": True, "online": online}
                  for nid, (role, online) in nodes.items()},
        "edges": {frozenset(e) for e in edges},
    }


class TestComputeDiff:
    def test_role_change_captured(self):
        orig = _topo({"A": ("sendreceive", True), "B": ("sendreceive", True)}, [("A", "B")])
        cur = _topo({"A": ("sendreceive", True), "B": ("receiveonly", True)}, [("A", "B")])
        diff = compute_topology_diff(orig, cur)
        assert diff["role_changed"] == {"B": "receiveonly"}
        assert diff["any"] is True

    def test_link_added_and_removed(self):
        orig = _topo({"A": ("sendreceive", True), "B": ("sendreceive", True),
                      "C": ("sendreceive", True)}, [("A", "B")])
        cur = _topo({"A": ("sendreceive", True), "B": ("sendreceive", True),
                     "C": ("sendreceive", True)}, [("A", "C")])
        diff = compute_topology_diff(orig, cur)
        assert frozenset(("A", "C")) in diff["links_added"]
        assert frozenset(("A", "B")) in diff["links_removed"]

    def test_locked_edge_skipped(self):
        orig = _topo({"A": ("sendreceive", True), "B": ("sendreceive", True)}, [])
        cur = _topo({"A": ("sendreceive", True), "B": ("sendreceive", True)}, [("A", "B")])
        locked = {frozenset(("A", "B"))}
        diff = compute_topology_diff(orig, cur, locked=locked)
        assert diff["links_added"] == set()
        assert frozenset(("A", "B")) in diff["skipped_locked"]

    def test_edited_link_to_offline_is_included(self):
        # A link the user EDITED is applied even if it touches an offline device (the
        # reachable end now, the offline end on reconnect) — it's their explicit intent.
        orig = _topo({"A": ("sendreceive", True), "B": ("sendreceive", False)}, [])
        cur = _topo({"A": ("sendreceive", True), "B": ("sendreceive", False)}, [("A", "B")])
        diff = compute_topology_diff(orig, cur)
        assert frozenset(("A", "B")) in diff["links_added"]
        assert diff["skipped_offline"] == []

    def test_no_change_is_empty(self):
        t = _topo({"A": ("sendreceive", True), "B": ("sendreceive", True)}, [("A", "B")])
        diff = compute_topology_diff(t, t)
        assert diff["any"] is False

    def test_orphaned_when_last_link_removed(self):
        # B's only link (A–B) is removed → B is orphaned (will be unshared on apply). A keeps
        # A–C so it's NOT orphaned; C keeps A–C so neither is it.
        orig = _topo({"A": ("sendreceive", True), "B": ("sendreceive", True),
                      "C": ("sendreceive", True)}, [("A", "B"), ("A", "C")])
        cur = _topo({"A": ("sendreceive", True), "B": ("sendreceive", True),
                     "C": ("sendreceive", True)}, [("A", "C")])
        diff = compute_topology_diff(orig, cur)
        assert diff["orphaned"] == {"B"}

    def test_not_orphaned_when_other_link_remains(self):
        # Remove A–B but B still has B–C → B not orphaned; only A lost ALL its links.
        orig = _topo({"A": ("sendreceive", True), "B": ("sendreceive", True),
                      "C": ("sendreceive", True)}, [("A", "B"), ("B", "C")])
        cur = _topo({"A": ("sendreceive", True), "B": ("sendreceive", True),
                     "C": ("sendreceive", True)}, [("B", "C")])
        diff = compute_topology_diff(orig, cur)
        assert diff["orphaned"] == {"A"}

    def test_locked_kept_link_prevents_orphan(self):
        # User "removed" A–B but it's LOCKED → kept on apply → B is NOT orphaned.
        orig = _topo({"A": ("sendreceive", True), "B": ("sendreceive", True)}, [("A", "B")])
        cur = _topo({"A": ("sendreceive", True), "B": ("sendreceive", True)}, [])
        diff = compute_topology_diff(orig, cur, locked={frozenset(("A", "B"))})
        assert diff["orphaned"] == set()

    def test_orphaned_excludes_controller_my_id(self):
        # The controller's OWN node (my_id) is never orphan-unshared even if it loses its last
        # link — excluded at compute time so every apply path (incl. the agent) stays correct.
        orig = _topo({"L": ("sendreceive", True), "B": ("sendreceive", True)}, [("L", "B")])
        cur = _topo({"L": ("sendreceive", True), "B": ("sendreceive", True)}, [])
        orig["my_id"] = cur["my_id"] = "L"
        diff = compute_topology_diff(orig, cur)
        assert "L" not in diff["orphaned"]    # controller protected at the source
        assert "B" in diff["orphaned"]         # the peer is orphaned → will be unshared


class TestApplyDiffToCfg:
    def test_add_neighbor_preserves_others_and_fields(self):
        # Existing folder cfg with B (carrying an introducedBy field) — adding C must NOT
        # drop or rewrite B's entry.
        cfg = {"id": "f", "type": "sendreceive",
               "devices": [{"deviceID": "A"},
                           {"deviceID": "B", "introducedBy": "A"}]}
        diff = {"role_changed": {}, "links_added": {frozenset(("A", "C"))},
                "links_removed": set()}
        new, summ = apply_topology_diff_to_cfg(cfg, "A", diff)
        ids = {d["deviceID"] for d in new["devices"]}
        assert ids == {"A", "B", "C"}
        b = next(d for d in new["devices"] if d["deviceID"] == "B")
        assert b["introducedBy"] == "A"          # preserved
        assert summ["added"] == ["C"]

    def test_remove_only_that_neighbor(self):
        cfg = {"id": "f", "type": "sendreceive",
               "devices": [{"deviceID": "A"}, {"deviceID": "B"}, {"deviceID": "C"}]}
        diff = {"role_changed": {}, "links_added": set(),
                "links_removed": {frozenset(("A", "B"))}}
        new, summ = apply_topology_diff_to_cfg(cfg, "A", diff)
        ids = {d["deviceID"] for d in new["devices"]}
        assert ids == {"A", "C"}                  # B removed, C kept
        assert summ["removed"] == ["B"]

    def test_role_set_only_when_changed(self):
        cfg = {"id": "f", "type": "sendreceive", "devices": [{"deviceID": "A"}]}
        # no role change for A
        new, _ = apply_topology_diff_to_cfg(
            cfg, "A", {"role_changed": {}, "links_added": set(), "links_removed": set()})
        assert new["type"] == "sendreceive"
        # role change for A
        new2, _ = apply_topology_diff_to_cfg(
            cfg, "A", {"role_changed": {"A": "receiveonly"}, "links_added": set(),
                       "links_removed": set()})
        assert new2["type"] == "receiveonly"

    def test_self_always_member(self):
        cfg = {"id": "f", "type": "sendreceive", "devices": []}
        new, _ = apply_topology_diff_to_cfg(
            cfg, "A", {"role_changed": {}, "links_added": set(), "links_removed": set()})
        assert {d["deviceID"] for d in new["devices"]} == {"A"}


class TestDeviceChanges:
    def test_only_edges_touching_device(self):
        diff = {"role_changed": {"A": "sendonly"},
                "links_added": {frozenset(("A", "B")), frozenset(("C", "D"))},
                "links_removed": set()}
        role, added, removed = device_topology_changes(diff, "A")
        assert role == "sendonly"
        assert added == {frozenset(("A", "B"))}
        assert removed == set()


class TestSerializeDiff:
    def test_roundtrip(self):
        diff = compute_topology_diff(
            _topo({"A": ("sendreceive", True), "B": ("sendreceive", True)}, []),
            _topo({"A": ("sendreceive", True), "B": ("receiveonly", True)}, [("A", "B")]))
        data = serialize_topology_diff(diff)
        back = deserialize_topology_diff(data)
        assert back["role_changed"] == {"B": "receiveonly"}
        assert frozenset(("A", "B")) in back["links_added"]

    def test_none_when_empty(self):
        assert serialize_topology_diff(None) is None
        t = _topo({"A": ("sendreceive", True)}, [])
        assert serialize_topology_diff(compute_topology_diff(t, t)) is None
        assert deserialize_topology_diff(None) is None

    def test_roundtrip_preserves_orphaned(self):
        # `orphaned` MUST survive (de)serialization or the AGENT path silently never unshares a
        # device whose last link was removed (the direct/passive paths would, the agent wouldn't).
        orig = _topo({"A": ("sendreceive", True), "B": ("sendreceive", True),
                      "C": ("sendreceive", True)}, [("A", "B"), ("A", "C")])
        cur = _topo({"A": ("sendreceive", True), "B": ("sendreceive", True),
                     "C": ("sendreceive", True)}, [("A", "C")])
        cur["my_id"] = orig["my_id"] = "A"
        diff = compute_topology_diff(orig, cur)
        assert diff["orphaned"] == {"B"}
        back = deserialize_topology_diff(serialize_topology_diff(diff))
        assert back["orphaned"] == {"B"}


class TestFolderCfgOverrides:
    def test_merge_preserves_and_overrides(self):
        from syncthing_manager.renamer import folder_cfg_with_overrides
        cfg = {"id": "f", "path": "/x", "type": "sendreceive",
               "versioning": {"type": "", "params": {"keep": "5"}},
               "rescanIntervalS": 3600, "fsWatcherEnabled": True, "ignorePerms": False,
               "paused": False, "devices": [{"deviceID": "A"}]}
        ov = {"versioning_type": "trashcan", "rescanIntervalS": 60,
              "fsWatcherEnabled": False, "ignorePerms": True, "paused": True}
        new = folder_cfg_with_overrides(cfg, ov)
        assert new["versioning"]["type"] == "trashcan"
        assert new["versioning"]["params"] == {"keep": "5"}      # preserved
        assert new["rescanIntervalS"] == 60
        assert new["fsWatcherEnabled"] is False
        assert new["ignorePerms"] is True and new["paused"] is True
        assert new["path"] == "/x" and new["devices"] == [{"deviceID": "A"}]  # untouched

    def test_empty_overrides_noop(self):
        from syncthing_manager.renamer import folder_cfg_with_overrides
        cfg = {"id": "f", "rescanIntervalS": 3600}
        assert folder_cfg_with_overrides(cfg, {}) == cfg


class TestNewDeviceMembership:
    """A device newly added to a PRE-EXISTING folder must end up sharing it. The apply path only
    touches a device the diff names (device_topology_changes), so the new device's edges MUST land
    in links_added — and BOTH ends (the new device and its hub) must see the edge. Locks the
    'new device + preexisting folder + diff lacking edges' case against silently dropping the
    membership. (Apply behaviour is asserted at the helper level; no code change.)"""

    def test_diff_captures_edges_to_a_brand_new_node(self):
        # orig: a 2-node folder (HUB↔A). cur: the operator added a NEW node N linked to the hub.
        orig = _topo({"HUB": ("sendreceive", True), "A": ("sendreceive", True)},
                     [("HUB", "A")])
        cur = _topo({"HUB": ("sendreceive", True), "A": ("sendreceive", True),
                     "N": ("sendreceive", True)}, [("HUB", "A"), ("HUB", "N")])
        diff = compute_topology_diff(orig, cur)
        assert frozenset(("HUB", "N")) in diff["links_added"]
        assert diff["any"] is True
        # the new device sees the edge as ITS change → it is configured, not short-circuited
        _, n_added, _ = device_topology_changes(diff, "N")
        assert n_added == {frozenset(("HUB", "N"))}
        # …and the hub sees the same edge → it registers N as a new member of its folder cfg
        _, hub_added, _ = device_topology_changes(diff, "HUB")
        assert hub_added == {frozenset(("HUB", "N"))}

    def test_new_device_create_uses_full_neighbor_set_not_just_diff(self):
        # When the folder does NOT yet exist on the new device (is_create), its fresh config must
        # list ALL neighbours regardless of which edges the diff carries — so a new device joined
        # to several peers in one edit gets every membership, never a partial one.
        diff = {"role_changed": {}, "links_added": {frozenset(("N", "HUB"))}, "links_removed": set()}
        got = set(_topo_entries_to_add("N", {"HUB", "PEER"}, set(), diff, is_create=True))
        assert got == {"HUB", "PEER"}     # PEER included even though the diff omits the N↔PEER edge

    def test_hub_diff_update_adds_new_device_to_existing_folder_cfg(self):
        # The hub's folder already exists; applying the diff must ADD the new device N to its
        # membership while preserving the pre-existing peer A (non-destructive).
        existing = {"id": "f", "type": "sendreceive", "paused": False,
                    "devices": [{"deviceID": "HUB"}, {"deviceID": "A"}]}
        diff = {"role_changed": {}, "links_added": {frozenset(("HUB", "N"))}, "links_removed": set()}
        cfg, summ = apply_topology_diff_to_cfg(existing, "HUB", diff)
        ids = {d["deviceID"] for d in cfg["devices"]}
        assert ids == {"HUB", "A", "N"}      # N added, A preserved
        assert summ["added"] == ["N"]
