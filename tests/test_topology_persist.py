"""N4: topology snapshot (de)serialization + remembered-edge merge."""
from syncthing_manager.topology import (
    _topology_to_json, _topology_from_json, _merge_remembered,
)


def _node(nid, online=True, reachable=True, is_local=False):
    return {"id": nid, "label": nid.upper(), "is_local": is_local, "is_new": False,
            "online": online, "reachable": reachable, "role": "sendreceive",
            "role_known": True, "path": "/x"}


def _topo(nodes, edges, edge_dir=None):
    return {"my_id": "L", "nodes": {n["id"]: n for n in nodes},
            "edges": {frozenset(e) for e in edges},
            "edge_dir": {frozenset(k): frozenset(v) for k, v in (edge_dir or {}).items()}}


def test_roundtrip_preserves_edges_and_dir():
    t = _topo([_node("L", is_local=True), _node("a"), _node("b")],
              [("L", "a"), ("a", "b")], {("a", "b"): ("a",)})
    data = _topology_to_json(t)
    back = _topology_from_json(data)
    assert back["edges"] == t["edges"]
    assert back["edge_dir"][frozenset(("a", "b"))] == frozenset(("a",))
    assert set(back["nodes"]) == {"L", "a", "b"}


def test_from_json_returns_none_on_malformed():
    # Contract: "None if malformed" — a corrupt/old/hand-edited snapshot must NOT raise (the
    # topology-load worker thread isn't wrapped; a raise would freeze the page on "Cargando…").
    assert _topology_from_json(None) is None
    assert _topology_from_json({}) is None
    assert _topology_from_json({"nodes": [1, 2, 3]}) is None       # nodes a list, not a dict
    assert _topology_from_json({"nodes": "x"}) is None              # nodes a string
    assert _topology_from_json("not a dict") is None
    assert _topology_from_json({"nodes": {"a": "not-a-dict-node"}})["nodes"] == {}  # node filtered
    # Malformed edge entries with a valid nodes dict → filtered out, parses without raising.
    out = _topology_from_json({"nodes": {"a": {"label": "A"}}, "edges": ["bad", ["a", "b"]]})
    assert out is not None and set(out["nodes"]) == {"a"}
    assert out["edges"] == {frozenset(("a", "b"))}   # the 2-element list kept, the string dropped


def test_to_json_drops_transient_fields():
    t = _topo([_node("a")], [])
    t["nodes"]["a"]["x"] = 10  # layout coord must not be persisted
    data = _topology_to_json(t)
    assert "x" not in data["nodes"]["a"]


def test_merge_adds_offline_offline_edge_only():
    # Live: local sees a and b, both OFFLINE; the a–b link is invisible live.
    live = _topo([_node("L", is_local=True), _node("a", online=False, reachable=False),
                  _node("b", online=False, reachable=False)],
                 [("L", "a"), ("L", "b")])
    snap = _topology_to_json(_topo(
        [_node("L", is_local=True), _node("a"), _node("b")],
        [("L", "a"), ("L", "b"), ("a", "b")], {("a", "b"): ("a",)}))
    _merge_remembered(live, snap, tag=True)
    assert frozenset(("a", "b")) in live["edges"]
    assert frozenset(("a", "b")) in live["remembered_edges"]


def test_merge_does_not_resurrect_link_touching_a_readable_node():
    # b is readable now and does NOT list a → the a–b link was removed; must NOT come back.
    live = _topo([_node("L", is_local=True), _node("a", online=False, reachable=False),
                  _node("b", online=True, reachable=True)],
                 [("L", "a"), ("L", "b")])
    snap = _topology_to_json(_topo(
        [_node("L", is_local=True), _node("a"), _node("b")],
        [("a", "b")], {("a", "b"): ("a",)}))
    _merge_remembered(live, snap, tag=True)
    assert frozenset(("a", "b")) not in live["edges"]


def test_merge_none_snapshot_is_noop():
    live = _topo([_node("a")], [])
    assert _merge_remembered(live, None) is live


def test_merge_never_resurrects_a_removed_node_or_edge():
    # 'a' was removed/unshared by the user (in `removed`); the snapshot still remembers it +
    # its offline link to 'b'. _merge_remembered must NOT re-add either, independent of any
    # caller-side filtering (self-guard against ghost resurrection).
    live = _topo([_node("L", is_local=True), _node("b", online=False, reachable=False)],
                 [("L", "b")])
    snap = _topology_to_json(_topo(
        [_node("L", is_local=True), _node("a"), _node("b")],
        [("L", "a"), ("a", "b"), ("L", "b")], {("a", "b"): ("a",)}))
    _merge_remembered(live, snap, tag=True, removed={"a"})
    assert "a" not in live["nodes"]                       # removed node not re-added
    assert frozenset(("a", "b")) not in live["edges"]     # nor its edge
    # Without `removed`, the offline-only node WOULD be remembered (proves the guard is what stops it).
    live2 = _topo([_node("L", is_local=True), _node("b", online=False, reachable=False)],
                  [("L", "b")])
    _merge_remembered(live2, snap, tag=True)
    assert "a" in live2["nodes"]


def test_roundtrip_preserves_unconfirmed():
    # The "unconfirmed" mark (a prior abandoned run couldn't apply on this offline node) MUST
    # survive (de)serialization so the warning persists across sessions.
    t = _topo([_node("L", is_local=True), _node("a")], [("L", "a")])
    t["nodes"]["a"]["unconfirmed"] = True
    back = _topology_from_json(_topology_to_json(t))
    assert back["nodes"]["a"].get("unconfirmed") is True
