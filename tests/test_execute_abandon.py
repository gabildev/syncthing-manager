"""Abandon-Execute cleanup: keep accessible↔offline edges, drop nowhere-applied
offline↔offline edges, mark pending offline nodes 'unconfirmed'. No Syncthing config touched."""
from __future__ import annotations

from types import SimpleNamespace

from syncthing_manager.gui.page_execute import ExecutePageMixin

_fs = frozenset


def test_abandon_cleanup_keeps_accessible_drops_nowhere_marks():
    cur = {"my_id": "L",
           "nodes": {"L": {"id": "L", "is_local": True}, "P": {"id": "P"},
                     "Q": {"id": "Q"}, "R": {"id": "R"}},
           "edges": {_fs(("L", "P")), _fs(("Q", "R"))}, "edge_dir": {}}
    orig = {"my_id": "L", "nodes": {k: dict(v) for k, v in cur["nodes"].items()},
            "edges": set(cur["edges"]), "edge_dir": {}}
    me = SimpleNamespace(s={"topology": cur, "topology_orig": orig, "folder": None})
    diff = {"links_added": {_fs(("L", "P")), _fs(("Q", "R"))}, "links_removed": set()}
    pending = {"P", "Q", "R"}    # P,Q,R offline; L is the reachable controller

    ExecutePageMixin._exec_abandon_cleanup(me, diff, pending)

    # L↔P prevails (L is accessible and applied it); Q↔R applied NOWHERE → dropped from both graphs
    assert _fs(("L", "P")) in cur["edges"]
    assert _fs(("Q", "R")) not in cur["edges"]
    assert _fs(("Q", "R")) not in orig["edges"]
    # every pending offline node is marked "unconfirmed"
    assert cur["nodes"]["P"].get("unconfirmed") is True
    assert cur["nodes"]["Q"].get("unconfirmed") is True
    assert cur["nodes"]["R"].get("unconfirmed") is True
    # the accessible/local node is never marked
    assert "unconfirmed" not in cur["nodes"]["L"]
