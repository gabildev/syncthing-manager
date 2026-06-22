from __future__ import annotations

from syncthing_manager.topology import (
    _derive_roles, _senders_from_roles, _arrow_from_senders,
)


class TestSenders:
    def test_bidirectional(self):
        assert _senders_from_roles("A", "B", "sendreceive", "sendreceive") == frozenset({"A", "B"})

    def test_oneway_sr_ro(self):
        assert _senders_from_roles("A", "B", "sendreceive", "receiveonly") == frozenset({"A"})

    def test_oneway_so_ro(self):
        assert _senders_from_roles("A", "B", "sendonly", "receiveonly") == frozenset({"A"})

    def test_noflow(self):
        assert _senders_from_roles("A", "B", "receiveonly", "receiveonly") == frozenset()


class TestArrow:
    def test_all(self):
        assert _arrow_from_senders("A", "B", frozenset({"A", "B"})) == "both"
        assert _arrow_from_senders("A", "B", frozenset({"A"})) == "last"
        assert _arrow_from_senders("A", "B", frozenset({"B"})) == "first"
        assert _arrow_from_senders("A", "B", frozenset()) == "none"


class TestDeriveRoles:
    def test_oneway(self):
        topo = {"nodes": {"A": {}, "B": {}},
                "edge_dir": {frozenset({"A", "B"}): frozenset({"A"})}}
        _derive_roles(topo)
        assert topo["nodes"]["A"]["role"] == "sendonly"
        assert topo["nodes"]["B"]["role"] == "receiveonly"
        assert topo["nodes"]["A"]["role_known"] and topo["nodes"]["B"]["role_known"]

    def test_mixed_node_is_sendreceive(self):
        # A sends to B, C sends to A → A both sends and receives = envía/recibe; the two
        # links stay unidirectional (B=solo recibe, C=solo envía). The key insight.
        topo = {"nodes": {"A": {}, "B": {}, "C": {}}, "edge_dir": {
            frozenset({"A", "B"}): frozenset({"A"}),
            frozenset({"A", "C"}): frozenset({"C"})}}
        _derive_roles(topo)
        assert topo["nodes"]["A"]["role"] == "sendreceive"
        assert topo["nodes"]["B"]["role"] == "receiveonly"
        assert topo["nodes"]["C"]["role"] == "sendonly"

    def test_bidirectional(self):
        topo = {"nodes": {"A": {}, "B": {}},
                "edge_dir": {frozenset({"A", "B"}): frozenset({"A", "B"})}}
        _derive_roles(topo)
        assert topo["nodes"]["A"]["role"] == "sendreceive"
        assert topo["nodes"]["B"]["role"] == "sendreceive"

    def test_untouched_node_kept(self):
        # A node with no directed edges (offline/unknown) keeps its current role/known flag.
        topo = {"nodes": {"A": {"role": "sendreceive", "role_known": False}}, "edge_dir": {}}
        _derive_roles(topo)
        assert topo["nodes"]["A"]["role_known"] is False
