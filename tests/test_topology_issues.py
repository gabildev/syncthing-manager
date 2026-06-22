from __future__ import annotations

from syncthing_manager.topology import _detect_topology_issues, _senders_from_roles


def _node(label, role="sendreceive", path="/x", is_local=False, role_known=True,
          reachable=True):
    return {"label": label, "role": role, "path": path, "is_local": is_local,
            "role_known": role_known, "reachable": reachable}


def _topo(nodes, edges):
    # Seed edge_dir from the endpoints' roles (only for edges whose both roles are known),
    # mirroring how the real graph stores per-link direction.
    ed = {}
    for e in edges:
        a, b = sorted(e)
        if nodes[a].get("role_known", True) and nodes[b].get("role_known", True):
            ed[frozenset((a, b))] = _senders_from_roles(a, b, nodes[a]["role"], nodes[b]["role"])
    return {"nodes": nodes, "edges": {frozenset(e) for e in edges}, "edge_dir": ed}


def test_no_issues_on_healthy_graph():
    t = _topo({"A": _node("A"), "B": _node("B")}, [("A", "B")])
    assert _detect_topology_issues(t) == []


def test_isolated_node_flagged():
    t = _topo({"A": _node("A"), "B": _node("B")}, [])  # no edges
    issues = _detect_topology_issues(t)
    assert any("sin enlaces" in i for i in issues)


def test_missing_path_flagged():
    t = _topo({"A": _node("A"), "B": _node("B", path="")}, [("A", "B")])
    issues = _detect_topology_issues(t)
    assert any("sin ruta" in i and "B" in i for i in issues)


def test_missing_path_not_flagged_when_unreachable():
    # Online Syncthing peer we can't READ yet (no creds) → path unknown, not a problem (N5).
    t = _topo({"A": _node("A"), "B": _node("B", path="", reachable=False)}, [("A", "B")])
    issues = _detect_topology_issues(t)
    assert not any("sin ruta" in i for i in issues)


def test_local_node_path_not_required():
    t = _topo({"A": _node("A"), "L": _node("L", path="", is_local=True)}, [("A", "L")])
    issues = _detect_topology_issues(t)
    assert not any("sin ruta" in i for i in issues)


def test_no_flow_edge_flagged():
    # Both receive-only → nothing is ever sent across the link.
    t = _topo({"A": _node("A", role="receiveonly"), "B": _node("B", role="receiveonly")},
              [("A", "B")])
    issues = _detect_topology_issues(t)
    assert any("ningún extremo envía" in i for i in issues)


def test_unknown_role_edge_not_flagged_as_noflow():
    t = _topo({"A": _node("A"), "B": _node("B", role_known=False)}, [("A", "B")])
    issues = _detect_topology_issues(t)
    assert not any("ningún extremo envía" in i for i in issues)


def test_empty_topology():
    assert _detect_topology_issues(None) == []
    assert _detect_topology_issues({"nodes": {}, "edges": set()}) == []
