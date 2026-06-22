from __future__ import annotations

from syncthing_manager.topology import _build_topology, _copy_topology, _reconcile_topology


class _Dev:
    """Minimal stand-in for DeviceInfo (only the attrs _build_topology reads)."""
    def __init__(self, device_id, is_local=False, peers=None, role=None, introducers=None):
        self.device_id = device_id
        self.is_local = is_local
        self.name = device_id
        self.folder_peers = peers or []
        self.folder_role = role
        self.folder_path = ""
        self.folder_introducers = introducers or {}


def _folder(members):
    """Local node's authoritative view. `members` is a list of either a plain device id
    or a (device_id, introducedBy) tuple."""
    devs = []
    for m in members:
        if isinstance(m, tuple):
            devs.append({"deviceID": m[0], "introducedBy": m[1]})
        else:
            devs.append({"deviceID": m})
    return type("F", (), {"raw": {"devices": devs, "type": "sendreceive"},
                          "path": "/data/x"})()


MY = "LOCAL"


class TestRealAdjacency:
    def test_edges_follow_real_membership_not_local_star(self):
        # Star around HUB: local shares only with HUB; HUB shares with local + SPOKE.
        topo = _build_topology(
            _folder(["HUB"]), MY, {}, {"HUB"},
            devices=[_Dev("HUB", peers=[MY, "SPOKE"], role="sendreceive"),
                     _Dev("SPOKE")])  # SPOKE offline, no peers read
        assert frozenset((MY, "HUB")) in topo["edges"]
        assert frozenset(("HUB", "SPOKE")) in topo["edges"]
        # NOT a fake direct link from local to the spoke:
        assert frozenset((MY, "SPOKE")) not in topo["edges"]
        # Offline spoke's role is unknown:
        assert topo["nodes"]["SPOKE"]["role_known"] is False
        assert topo["nodes"]["HUB"]["role_known"] is True

    def test_reachable_non_member_is_not_a_node(self):
        # A device that was discovered/reachable but does NOT share this folder reports no
        # role/path/peers and isn't referenced by anyone → it must NOT appear as a node
        # (reachable ≠ sharing the folder). Only HUB (a real member) and local do.
        topo = _build_topology(
            _folder(["HUB"]), MY, {}, {"HUB", "STRANGER"},
            devices=[_Dev("HUB", peers=[MY], role="sendreceive"), _Dev("STRANGER")])
        assert "STRANGER" not in topo["nodes"]
        assert set(topo["nodes"]) == {MY, "HUB"}

    def test_introduced_member_links_to_introducer_not_local(self):
        # The Pi (HUB) introduced SPOKE, so local's config lists SPOKE with
        # introducedBy=HUB. The real link is HUB↔SPOKE, NOT a phantom LOCAL↔SPOKE.
        topo = _build_topology(
            _folder(["HUB", ("SPOKE", "HUB")]), MY, {}, {"HUB"},
            devices=[_Dev("HUB", peers=[MY], role="sendreceive"), _Dev("SPOKE")])
        assert frozenset((MY, "HUB")) in topo["edges"]
        assert frozenset(("HUB", "SPOKE")) in topo["edges"]
        assert frozenset((MY, "SPOKE")) not in topo["edges"]  # phantom edge gone


class TestReconcileTopology:
    def test_adds_devices_with_their_real_edges(self):
        base1 = _build_topology(_folder(["HUB"]), MY, {}, {"HUB"},
                                devices=[_Dev("HUB", peers=[MY], role="sendreceive")])
        cur = base1
        orig = _copy_topology(base1)
        # Later, the hub reveals an offline spoke.
        base2 = _build_topology(
            _folder(["HUB"]), MY, {}, {"HUB"},
            devices=[_Dev("HUB", peers=[MY, "SPOKE"], role="sendreceive"), _Dev("SPOKE")])
        added = _reconcile_topology(cur, orig, base2, MY)
        assert added == ["SPOKE"]
        assert frozenset(("HUB", "SPOKE")) in cur["edges"]
        assert frozenset((MY, "SPOKE")) not in cur["edges"]

    def test_user_removed_link_not_readded(self):
        # In the link-direction model the user edits links (not roles directly). A link the
        # user removed must NOT be resurrected by reconcile for an already-present node.
        base = _build_topology(_folder(["A"]), MY, {}, {"A"},
                               devices=[_Dev("A", peers=[MY], role="sendreceive")])
        cur = _copy_topology(base)
        orig = _copy_topology(base)
        cur["edges"].discard(frozenset((MY, "A")))          # user removed the link
        cur["edge_dir"].pop(frozenset((MY, "A")), None)
        _reconcile_topology(cur, orig, base, MY)
        assert frozenset((MY, "A")) not in cur["edges"]     # not re-added

    def test_reconcile_prunes_stale_non_member(self):
        # A node left in `cur` from a previous folder/state that the freshly-built `base`
        # doesn't contain (and the user didn't add) must be dropped from BOTH cur and orig.
        base = _build_topology(_folder(["A"]), MY, {}, {"A"},
                               devices=[_Dev("A", peers=[MY], role="sendreceive")])
        cur = _copy_topology(base)
        orig = _copy_topology(base)
        stale = {"id": "Z", "label": "Z", "is_local": False, "is_new": False,
                 "online": True, "role": "sendreceive", "role_known": True, "path": ""}
        cur["nodes"]["Z"] = dict(stale); orig["nodes"]["Z"] = dict(stale)
        cur["edges"].add(frozenset((MY, "Z"))); orig["edges"].add(frozenset((MY, "Z")))
        _reconcile_topology(cur, orig, base, MY)
        assert "Z" not in cur["nodes"] and "Z" not in orig["nodes"]
        assert frozenset((MY, "Z")) not in cur["edges"]
        assert frozenset((MY, "Z")) not in orig["edges"]

    def test_reconcile_keeps_user_added_new_node(self):
        # A user-added (is_new) node is NOT a base member but must be preserved.
        base = _build_topology(_folder(["A"]), MY, {}, {"A"},
                               devices=[_Dev("A", peers=[MY], role="sendreceive")])
        cur = _copy_topology(base)
        orig = _copy_topology(base)
        cur["nodes"]["NEW"] = {"id": "NEW", "label": "Nuevo", "is_local": False,
                               "is_new": True, "online": False, "role": "sendreceive",
                               "role_known": True, "path": "~/x"}
        _reconcile_topology(cur, orig, base, MY)
        assert "NEW" in cur["nodes"]

    def test_does_not_resurrect_removed_node(self):
        base = _build_topology(_folder(["A"]), MY, {}, {"A"},
                               devices=[_Dev("A", peers=[MY], role="sendreceive")])
        cur = _copy_topology(base)
        orig = _copy_topology(base)
        cur["nodes"].pop("A")
        cur["edges"] = {e for e in cur["edges"] if "A" not in e}
        _reconcile_topology(cur, orig, base, MY, removed={"A"})
        assert "A" not in cur["nodes"]

    def test_reconcile_refreshes_reachable_on_reconnect(self):
        # A peer offline at first build (reachable=False) that reconnected by the time the
        # user opens Topología must have its reachable flag refreshed from `base` — otherwise
        # it stays out of _merge_remembered's readable set and skews the "sin ruta" check.
        base = _build_topology(_folder(["A"]), MY, {}, {"A"},
                               devices=[_Dev("A", peers=[MY], role="sendreceive")])
        base["nodes"]["A"]["reachable"] = True       # now reachable
        cur = _copy_topology(base)
        orig = _copy_topology(base)
        cur["nodes"]["A"]["reachable"] = False        # stale from the first (offline) build
        _reconcile_topology(cur, orig, base, MY)
        assert cur["nodes"]["A"]["reachable"] is True
        # role/role_known are NOT clobbered (they derive from the user's edited edges).
        assert cur["nodes"]["A"]["role"] == base["nodes"]["A"]["role"]
