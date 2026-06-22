"""Tests for the topology model + apply helpers."""
from __future__ import annotations

from syncthing_manager.models import DeviceInfo
from syncthing_manager.renamer import (
    serialize_topology, deserialize_topology, _topo_neighbors,
    _topo_update_folder_cfg, _topo_create_folder_cfg, apply_topology_on_device,
    remove_folder_on_device,
)


def _topo():
    return {
        "my_id": "AAA",
        "nodes": {
            "AAA": {"label": "Local", "role": "sendreceive", "path": "/srv/x",
                    "is_local": True, "is_new": False},
            "BBB": {"label": "Pi", "role": "receiveonly", "path": "",
                    "is_local": False, "is_new": False},
            "CCC": {"label": "Nuevo", "role": "sendreceive", "path": "~/Nuevo",
                    "is_local": False, "is_new": True},
        },
        "edges": {frozenset(("AAA", "BBB")), frozenset(("AAA", "CCC"))},
    }


def test_neighbors():
    t = _topo()
    assert _topo_neighbors(t, "AAA") == {"BBB", "CCC"}
    assert _topo_neighbors(t, "BBB") == {"AAA"}
    assert _topo_neighbors(t, "CCC") == {"AAA"}


def test_serialize_roundtrip():
    t = _topo()
    data = serialize_topology(t)
    # edges become sorted lists; JSON-safe
    assert all(isinstance(e, list) and len(e) == 2 for e in data["edges"])
    back = deserialize_topology(data)
    assert back["edges"] == t["edges"]
    assert back["nodes"]["BBB"]["role"] == "receiveonly"


def test_serialize_none():
    assert serialize_topology(None) is None
    assert deserialize_topology(None) is None


def test_update_folder_cfg_sets_role_and_devices():
    existing = {"id": "f", "type": "sendreceive", "label": "L", "path": "/p",
                "devices": [{"deviceID": "AAA", "introducedBy": ""},
                            {"deviceID": "ZZZ"}]}  # ZZZ no longer a neighbor
    cfg = _topo_update_folder_cfg(existing, "AAA", "receiveonly", {"BBB"})
    assert cfg["type"] == "receiveonly"
    ids = {d["deviceID"] for d in cfg["devices"]}
    assert ids == {"AAA", "BBB"}          # self + neighbor, ZZZ dropped
    # preserved existing fields for AAA
    aaa = [d for d in cfg["devices"] if d["deviceID"] == "AAA"][0]
    assert aaa.get("introducedBy") == ""


def test_update_folder_cfg_winrm_dict_devices():
    # WinRM/ConvertTo-Json collapses a single-element array into a dict
    existing = {"id": "f", "type": "sendreceive", "devices": {"deviceID": "AAA"}}
    cfg = _topo_update_folder_cfg(existing, "AAA", "sendonly", {"BBB"})
    assert {d["deviceID"] for d in cfg["devices"]} == {"AAA", "BBB"}


def test_create_folder_cfg():
    cfg = _topo_create_folder_cfg("fid", "Lbl", "~/Lbl", "CCC", "sendreceive", {"AAA"})
    assert cfg["id"] == "fid" and cfg["label"] == "Lbl" and cfg["path"] == "~/Lbl"
    assert cfg["type"] == "sendreceive"
    assert {d["deviceID"] for d in cfg["devices"]} == {"AAA", "CCC"}


def test_create_folder_cfg_default_path():
    cfg = _topo_create_folder_cfg("fid", "Lbl", "", "CCC", "sendreceive", set())
    assert cfg["path"] == "~/Lbl"


def test_apply_dry_run_no_network():
    dev = DeviceInfo(device_id="AAA", name="Local", ip="127.0.0.1",
                     api_url="http://127.0.0.1:8384", api_key="k", folder_path="/srv/x",
                     ssh_reachable=False, api_reachable=True, is_local=True)
    res = apply_topology_on_device(dev, "fid", _topo(), folder_label="L", dry_run=True)
    assert res.ok
    assert "dry-run" in res.message


def test_apply_device_not_in_topology():
    dev = DeviceInfo(device_id="UNKNOWN", name="x", ip="1.2.3.4",
                     api_url="http://1.2.3.4:8384", api_key="k", folder_path="",
                     ssh_reachable=False, api_reachable=True, is_local=False)
    res = apply_topology_on_device(dev, "fid", _topo(), dry_run=True)
    assert res.ok and "no está en la topología" in res.message


def test_apply_no_access():
    dev = DeviceInfo(device_id="BBB", name="Pi", ip="", api_url="", api_key="",
                     folder_path="", ssh_reachable=False, api_reachable=False,
                     is_local=False)
    res = apply_topology_on_device(dev, "fid", _topo(), dry_run=False)
    assert not res.ok and "sin acceso" in res.message


def test_apply_orphaned_remote_unshares():
    """A non-local device whose LAST link was removed (orphaned) must be UNSHARED — the
    folder removed from it — not left configured-but-peerless ('stopped')."""
    from unittest.mock import patch
    from syncthing_manager.renamer import TopologyResult
    dev = DeviceInfo(device_id="BBB", name="Pi", ip="10.0.0.9",
                     api_url="http://10.0.0.9:8384", api_key="k", folder_path="/srv/x",
                     ssh_reachable=False, api_reachable=True, is_local=False)
    diff = {"role_changed": {}, "links_added": set(), "links_removed": {frozenset(("AAA", "BBB"))},
            "skipped_locked": [], "skipped_offline": [], "orphaned": {"BBB"}, "any": True}
    with patch("syncthing_manager.renamer.remove_folder_on_device",
               return_value=TopologyResult("Pi", True, "removed")) as rm:
        res = apply_topology_on_device(dev, "fid", _topo(), diff=diff, folder_label="L")
    assert res.ok and "dejada de compartir" in res.message
    rm.assert_called_once_with(dev, "fid")


def test_apply_orphaned_agent_node_unshares():
    """The orphan-unshare is NOT gated on is_local: an AGENT applies for its OWN node
    (is_local=True in its context). Because compute_topology_diff already drops the
    controller's my_id from `orphaned`, anything left in `orphaned` IS unshared — so the
    agent path matches the direct/passive paths instead of leaving the folder peerless."""
    from unittest.mock import patch
    from syncthing_manager.renamer import TopologyResult
    dev = DeviceInfo(device_id="BBB", name="Pi", ip="127.0.0.1",
                     api_url="http://127.0.0.1:8384", api_key="k", folder_path="/srv/x",
                     ssh_reachable=False, api_reachable=True, is_local=True)   # agent's own node
    diff = {"role_changed": {}, "links_added": set(), "links_removed": {frozenset(("AAA", "BBB"))},
            "skipped_locked": [], "skipped_offline": [], "orphaned": {"BBB"}, "any": True}
    with patch("syncthing_manager.renamer.remove_folder_on_device",
               return_value=TopologyResult("Pi", True, "removed")) as rm:
        res = apply_topology_on_device(dev, "fid", _topo(), diff=diff, folder_label="L")
    assert res.ok and "dejada de compartir" in res.message
    rm.assert_called_once_with(dev, "fid")


def test_apply_new_device_wrong_path_recreates():
    """A NEW device whose folder already exists at a DIFFERENT path than the one chosen
    must be RECREATED there (delete+create) — a config PUT can't move it. This is what
    makes 'corregir la ruta y re-ejecutar' actually relocate the folder."""
    from unittest.mock import MagicMock, patch
    from syncthing_manager.models import FolderConfig
    topo = _topo()  # CCC is_new, path "~/Nuevo"
    dev = DeviceInfo(device_id="CCC", name="Nuevo", ip="10.0.0.5",
                     api_url="http://10.0.0.5:8384", api_key="k", folder_path="/old",
                     ssh_reachable=False, api_reachable=True, is_local=False)
    client = MagicMock()
    client.get_folder.return_value = FolderConfig.from_dict(
        {"id": "fid", "label": "L", "path": "/old", "devices": [{"deviceID": "CCC"}]})
    client.get_config_devices.return_value = []
    diff = {"role_changed": {}, "links_added": set(), "links_removed": set(),
            "skipped_locked": [], "any": False}
    with patch("syncthing_manager.renamer.SyncthingClient", return_value=client):
        res = apply_topology_on_device(dev, "fid", topo, diff=diff, folder_label="L")
    assert res.ok
    client.delete_folder.assert_called_once_with("fid")
    assert client.create_folder.call_args.args[0]["path"] == "~/Nuevo"


def test_apply_new_device_same_path_no_recreate():
    """If the folder already exists at the SAME chosen path, no destructive recreate."""
    from unittest.mock import MagicMock, patch
    from syncthing_manager.models import FolderConfig
    topo = _topo()
    topo["nodes"]["CCC"]["path"] = "/data/Nuevo"
    dev = DeviceInfo(device_id="CCC", name="Nuevo", ip="10.0.0.5",
                     api_url="http://10.0.0.5:8384", api_key="k", folder_path="/data/Nuevo",
                     ssh_reachable=False, api_reachable=True, is_local=False)
    client = MagicMock()
    client.get_folder.return_value = FolderConfig.from_dict(
        {"id": "fid", "label": "L", "path": "/data/Nuevo", "devices": [{"deviceID": "CCC"}]})
    client.get_config_devices.return_value = []
    diff = {"role_changed": {}, "links_added": {frozenset(("AAA", "CCC"))},
            "links_removed": set(), "skipped_locked": [], "any": True}
    with patch("syncthing_manager.renamer.SyncthingClient", return_value=client):
        res = apply_topology_on_device(dev, "fid", topo, diff=diff, folder_label="L")
    assert res.ok
    client.delete_folder.assert_not_called()


def test_gui_topology_delta():
    # gui imports tkinter but doesn't open a display at import time
    from syncthing_manager.topology import _topology_delta, _edge_arrow, _build_topology

    class _F:  # minimal folder stub
        raw = {"devices": [{"deviceID": "AAA"}, {"deviceID": "BBB"}], "type": "sendreceive"}
        path = "/srv/x"
    orig = _build_topology(_F(), "AAA", {"AAA": "Local", "BBB": "Pi"}, {"BBB"})
    cur = {"my_id": "AAA",
           "nodes": {k: dict(v) for k, v in orig["nodes"].items()},
           "edges": set(orig["edges"])}
    # change Pi role + remove the edge. A real role change comes from _derive_roles, which
    # sets role_known=True on the node (an offline node with role_known=False keeps its role
    # and can't be meaningfully changed) — mirror that so the delta matches the apply gate.
    cur["nodes"]["BBB"]["role"] = "receiveonly"
    cur["nodes"]["BBB"]["role_known"] = True
    cur["edges"].discard(frozenset(("AAA", "BBB")))
    d = _topology_delta(orig, cur)
    assert d["any"]
    assert d["roles_changed"] and d["roles_changed"][0][2] == "receiveonly"
    assert d["links_removed"] and not d["links_added"]

    # arrow direction derivation
    assert _edge_arrow("sendreceive", "sendreceive") == "both"
    assert _edge_arrow("sendonly", "receiveonly") == "last"
    assert _edge_arrow("receiveonly", "sendonly") == "first"
    assert _edge_arrow("sendonly", "sendonly") == "none"


def test_gui_topology_delta_none():
    from syncthing_manager.topology import _topology_delta
    assert _topology_delta(None, None) == {"any": False}


def test_delta_new_device_detected():
    from syncthing_manager.topology import _topology_delta
    orig = {"my_id": "AAA",
            "nodes": {"AAA": {"label": "Local", "role": "sendreceive", "is_local": True, "is_new": False}},
            "edges": set()}
    cur = {"my_id": "AAA",
           "nodes": {"AAA": dict(orig["nodes"]["AAA"]),
                     "CCC": {"label": "Nuevo", "role": "sendreceive", "is_local": False, "is_new": True}},
           "edges": {frozenset(("AAA", "CCC"))}}
    d = _topology_delta(orig, cur)
    assert d["any"]
    assert len(d["new_devices"]) == 1 and d["new_devices"][0]["label"] == "Nuevo"
    assert d["links_added"] and not d["links_removed"]


def test_remove_folder_no_access():
    dev = DeviceInfo(device_id="CCC", name="Nuevo", ip="", api_url="", api_key="",
                     folder_path="", ssh_reachable=False, api_reachable=False, is_local=False)
    res = remove_folder_on_device(dev, "fid")
    assert not res.ok and "sin acceso" in res.message


def test_orphaned_node_ids_helper():
    """Shared source of truth for 'who lost their last link' (apply + preview + render)."""
    from syncthing_manager.topology import orphaned_node_ids
    fs = frozenset
    orig = {fs(("A", "B")), fs(("A", "C"))}
    # Remove A–B → B orphaned; A and C still tied by A–C.
    assert orphaned_node_ids(orig, {fs(("A", "C"))}) == {"B"}
    # Remove everything → all three orphaned.
    assert orphaned_node_ids(orig, set()) == {"A", "B", "C"}
    # A locked link that was "removed" is KEPT → its endpoints are NOT orphaned.
    assert orphaned_node_ids({fs(("A", "B"))}, set(), locked={fs(("A", "B"))}) == set()
    # No change → nobody orphaned.
    assert orphaned_node_ids(orig, orig) == set()


def test_apply_ssh_transient_get_aborts_no_clobber():
    """A TRANSIENT (non-404) read error over SSH must NOT fall through to CREATE — the POST
    upsert would clobber the existing folder's membership. Abort with a failure instead."""
    from unittest.mock import MagicMock, patch
    from syncthing_manager.ssh_ops import SSHError
    dev = DeviceInfo(device_id="BBB", name="pi", ip="1.2.3.4", api_url="", api_key="k",
                     folder_path="/x", ssh_reachable=True, api_reachable=False, is_local=False,
                     ssh_user="u")
    ssh = MagicMock()
    ssh.syncthing_api_get.side_effect = SSHError("Syncthing API GET /rest/... failed: timeout")
    # BBB has a REAL change (a new link), so we must read its live config before writing —
    # the transient GET failure must then abort, not fall through to a clobbering CREATE.
    diff = {"role_changed": {}, "links_added": {frozenset(("BBB", "CCC"))},
            "links_removed": set(), "skipped_locked": [], "skipped_offline": [],
            "orphaned": set(), "any": True}
    with patch("syncthing_manager.renamer.SSHClient", return_value=ssh):
        res = apply_topology_on_device(dev, "fid", _topo(), diff=diff, folder_label="L")
    assert not res.ok and "no se pudo leer" in res.message
    ssh.syncthing_api_post.assert_not_called()   # nothing was written → no clobber


def test_serialize_topology_drops_degenerate_edges_and_roundtrips():
    from syncthing_manager.renamer import serialize_topology, deserialize_topology
    topo = {"nodes": {"AAA": {"label": "a", "role": "sendreceive"},
                      "BBB": {"label": "b", "role": "receiveonly"}},
            "edges": {frozenset(("AAA", "BBB")), frozenset(("AAA",))}}  # 2nd is degenerate
    ser = serialize_topology(topo)
    assert all(len(e) == 2 for e in ser["edges"])         # 1-element edge filtered out
    back = deserialize_topology(ser)
    assert back["edges"] == {frozenset(("AAA", "BBB"))}


def test_deserialize_topology_copies_nodes():
    """Mutating the deserialized graph must not write back into the raw embedded JSON."""
    from syncthing_manager.renamer import deserialize_topology
    raw = {"nodes": {"AAA": {"label": "a", "role": "sendreceive"}}, "edges": []}
    topo = deserialize_topology(raw)
    topo["nodes"]["AAA"]["role"] = "receiveonly"
    assert raw["nodes"]["AAA"]["role"] == "sendreceive"   # source untouched


def test_apply_diff_untouched_device_absent_folder_is_noop():
    """A diff that doesn't touch THIS device must be a no-op even when the folder is ABSENT
    here — never re-create a folder the operator removed from this device while editing
    others. (Regression guard for the agent's skipped_absent / config_updated=False path.)"""
    from unittest.mock import MagicMock, patch
    dev = DeviceInfo(device_id="BBB", name="pi", ip="1.2.3.4", api_url="http://1.2.3.4:8384",
                     api_key="k", folder_path="/x", ssh_reachable=False, api_reachable=True,
                     is_local=False)
    client = MagicMock()
    client.get_folder.return_value = None         # folder absent on this device
    # Diff changes only the link between AAA and CCC — nothing touching BBB.
    diff = {"role_changed": {}, "links_added": {frozenset(("AAA", "CCC"))},
            "links_removed": set(), "skipped_locked": [], "skipped_offline": [],
            "orphaned": set(), "any": True}
    with patch("syncthing_manager.renamer.SyncthingClient", return_value=client):
        res = apply_topology_on_device(dev, "fid", _topo(), diff=diff, folder_label="L")
    assert res.ok and "sin cambios" in res.message
    client.create_folder.assert_not_called()      # the bug: would have re-created the folder
    client.get_folder.assert_not_called()          # short-circuits before any channel I/O


def test_remove_folder_ssh_404_is_success():
    """Unsharing a folder already gone on an SSH device is idempotent SUCCESS (like the API
    branch), so the orphan node gets purged instead of failing + ghosting."""
    from unittest.mock import MagicMock, patch
    from syncthing_manager.renamer import remove_folder_on_device
    from syncthing_manager.ssh_ops import SSHError
    dev = DeviceInfo(device_id="X", name="pi", ip="1.2.3.4", api_url="", api_key="k",
                     folder_path="", ssh_reachable=True, api_reachable=False, is_local=False,
                     ssh_user="u")
    ssh = MagicMock()
    ssh.syncthing_api_delete.side_effect = SSHError("DELETE /rest/... → HTTP 404: No folder")
    with patch("syncthing_manager.renamer.SSHClient", return_value=ssh):
        r = remove_folder_on_device(dev, "f1")
    assert r.ok and "ya no existe" in r.message


def test_remove_folder_ssh_transient_is_failure():
    """A NON-404 delete error must still surface as a failure (don't swallow real errors)."""
    from unittest.mock import MagicMock, patch
    from syncthing_manager.renamer import remove_folder_on_device
    from syncthing_manager.ssh_ops import SSHError
    dev = DeviceInfo(device_id="X", name="pi", ip="1.2.3.4", api_url="", api_key="k",
                     folder_path="", ssh_reachable=True, api_reachable=False, is_local=False,
                     ssh_user="u")
    ssh = MagicMock()
    ssh.syncthing_api_delete.side_effect = SSHError("connection reset by peer")
    with patch("syncthing_manager.renamer.SSHClient", return_value=ssh):
        r = remove_folder_on_device(dev, "f1")
    assert not r.ok


def test_apply_folder_cfg_ssh_transient_is_failure_not_silent_skip():
    """A transient SSH read error while applying a queued folder-config override must surface as
    a FAILURE (so it stays in fcfg_pending for retry) — not a false 'folder absent'+success that
    silently drops the override. Parity with the API branch."""
    from unittest.mock import MagicMock, patch
    from syncthing_manager.renamer import apply_folder_cfg_on_device
    from syncthing_manager.ssh_ops import SSHError
    dev = DeviceInfo(device_id="X", name="pi", ip="1.2.3.4", api_url="", api_key="k",
                     folder_path="", ssh_reachable=True, api_reachable=False, is_local=False,
                     ssh_user="u")
    ssh = MagicMock()
    ssh.syncthing_api_get.side_effect = SSHError("Syncthing API GET /rest/... failed: timeout")
    with patch("syncthing_manager.renamer.SSHClient", return_value=ssh):
        r = apply_folder_cfg_on_device(dev, "fid", {"paused": True})
    assert not r.ok and "no se pudo leer" in r.message
    ssh.syncthing_api_post.assert_not_called()


def test_apply_folder_cfg_ssh_404_is_benign_skip():
    """A real 404 (folder absent on this device) IS a benign skip (ok)."""
    from unittest.mock import MagicMock, patch
    from syncthing_manager.renamer import apply_folder_cfg_on_device
    from syncthing_manager.ssh_ops import SSHError
    dev = DeviceInfo(device_id="X", name="pi", ip="1.2.3.4", api_url="", api_key="k",
                     folder_path="", ssh_reachable=True, api_reachable=False, is_local=False,
                     ssh_user="u")
    ssh = MagicMock()
    ssh.syncthing_api_get.side_effect = SSHError("DELETE/GET → HTTP 404: No folder with given ID")
    with patch("syncthing_manager.renamer.SSHClient", return_value=ssh):
        r = apply_folder_cfg_on_device(dev, "fid", {"paused": True})
    assert r.ok and "no existe aquí" in r.message


def test_apply_folder_cfg_winrm_rewraps_collapsed_devices():
    """WinRM/ConvertTo-Json collapses a 1-element 'devices' array to a bare object; the cfg
    apply must re-wrap it to a list before POSTing back, or a single-member folder is mangled."""
    from unittest.mock import MagicMock, patch
    from syncthing_manager.renamer import apply_folder_cfg_on_device
    dev = DeviceInfo(device_id="W", name="win", ip="1.2.3.4", api_url="", api_key="k",
                     folder_path="", ssh_reachable=False, api_reachable=False, is_local=False,
                     winrm_reachable=True, winrm_user="u", winrm_password="p")
    wr = MagicMock()
    wr.syncthing_api_get.return_value = {"id": "f", "label": "L", "devices": {"deviceID": "AAA"}}
    with patch("syncthing_manager.renamer.WinRMClient", return_value=wr):
        r = apply_folder_cfg_on_device(dev, "f", {"paused": True})
    assert r.ok
    body = wr.syncthing_api_post.call_args.kwargs["body"]
    assert isinstance(body["devices"], list) and body["devices"][0]["deviceID"] == "AAA"


def test_lone_new_node_embeds_topology_but_null_diff():
    """The GUI embeds `topology` when _topology_delta.any, but serialize_topology_diff returns
    None when the only edit is a lone UNLINKED new node — the agent MUST treat a None diff as a
    no-op, never the legacy full-rewrite (which would drop peers). Pins that divergence so the
    agent's `diff is not None` guard stays justified."""
    from syncthing_manager.topology import _topology_delta
    from syncthing_manager.renamer import compute_topology_diff, serialize_topology_diff
    _n = lambda **k: {"label": "x", "is_local": False, "is_new": False, "role": "sendreceive",
                      "role_known": True, **k}
    orig = {"my_id": "AAA",
            "nodes": {"AAA": _n(is_local=True), "BBB": _n()},
            "edges": {frozenset(("AAA", "BBB"))}}
    cur = {"my_id": "AAA",
           "nodes": {"AAA": _n(is_local=True), "BBB": _n(), "CCC": _n(is_new=True)},  # added, NO link
           "edges": {frozenset(("AAA", "BBB"))}}
    assert _topology_delta(orig, cur).get("any") is True                       # → GUI embeds topology
    assert serialize_topology_diff(compute_topology_diff(orig, cur)) is None    # → but diff is None
