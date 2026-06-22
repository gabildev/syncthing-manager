"""N3/N8: unshare folder + unlink device helpers."""
from unittest.mock import MagicMock, patch

from syncthing_manager.models import DeviceInfo
from syncthing_manager.renamer import (
    _drop_peer_from_folder_cfg, unshare_folder_everywhere, unlink_device_everywhere,
    TopologyResult,
)


def test_unshare_everywhere_reads_real_result_ok_not_success():
    # Regression: unshare_folder_everywhere must read TopologyResult.ok (not `.success`).
    # A real TopologyResult (not a MagicMock) makes a `.success` access raise AttributeError.
    target = DeviceInfo(device_id="T", name="t", ip="10.0.0.1", api_url="http://10.0.0.1:8384",
                        api_key="k", folder_path="/x", ssh_reachable=False, api_reachable=True,
                        is_local=False)
    with patch("syncthing_manager.renamer.remove_folder_on_device",
               return_value=TopologyResult("t", True, "borrada")):
        out = unshare_folder_everywhere([target], "folder1", "T", member_ids={"T"})
    assert ("t", True, "borrada", False) in out


def _dev(did, api=True):
    return DeviceInfo(device_id=did, name=did.lower(), ip="10.0.0.1",
                      api_url="http://10.0.0.1:8384", api_key="k", folder_path="/x",
                      ssh_reachable=False, api_reachable=api, is_local=False)


def _unreachable(did):
    """A device that shares the folder but we have no channel to (offline / no creds)."""
    return DeviceInfo(device_id=did, name=did.lower(), ip=None,
                      api_url=None, api_key=None, folder_path=None,
                      ssh_reachable=False, api_reachable=False, is_local=False)


def _local(did="L"):
    return DeviceInfo(device_id=did, name="local", ip="127.0.0.1",
                      api_url="http://127.0.0.1:8384", api_key="k", folder_path="/x",
                      ssh_reachable=False, api_reachable=True, is_local=True)


def test_drop_peer_from_folder_cfg():
    cfg = {"id": "f", "devices": [{"deviceID": "A"}, {"deviceID": "B"}]}
    new, changed = _drop_peer_from_folder_cfg(cfg, "B")
    assert changed is True
    assert [d["deviceID"] for d in new["devices"]] == ["A"]


def test_drop_peer_winrm_dict_collapse():
    cfg = {"id": "f", "devices": {"deviceID": "B"}}
    new, changed = _drop_peer_from_folder_cfg(cfg, "B")
    assert changed is True and new["devices"] == []


def test_drop_peer_absent_no_change():
    cfg = {"id": "f", "devices": [{"deviceID": "A"}]}
    _new, changed = _drop_peer_from_folder_cfg(cfg, "Z")
    assert changed is False


def test_unshare_deletes_on_target_and_prunes_peer():
    target = _dev("T")
    peer = _dev("P")
    fcfg = {"id": "folder1", "devices": [{"deviceID": "T"}, {"deviceID": "P"}]}
    with patch("syncthing_manager.renamer.remove_folder_on_device") as rm, \
         patch("syncthing_manager.renamer.read_folder_cfg_on_device", return_value=fcfg), \
         patch("syncthing_manager.renamer._write_folder_cfg_on_device") as wr:
        rm.return_value = MagicMock(device_name="t", ok=True, message="ok")
        out = unshare_folder_everywhere([target, peer], "folder1", "T")
    rm.assert_called_once()                         # folder deleted on the target itself
    # peer P was rewritten without T
    assert wr.call_count == 1
    written = wr.call_args.args[2]
    assert all(d["deviceID"] != "T" for d in written["devices"])
    assert any(ok for _, ok, _, _ in out)


def test_unshare_flags_unreachable_member_instead_of_silent_skip():
    # The bug: a peer that shares the folder with the target but isn't reachable was
    # silently skipped, so it kept showing "device has not accepted sharing" while the
    # op reported success. It must now be surfaced as an explicit failure.
    target = _dev("T")
    offline = _unreachable("P")            # shares with T but we can't reach it
    with patch("syncthing_manager.renamer.remove_folder_on_device") as rm, \
         patch("syncthing_manager.renamer.read_folder_cfg_on_device", return_value=None), \
         patch("syncthing_manager.renamer._write_folder_cfg_on_device") as wr:
        rm.return_value = MagicMock(device_name="t", ok=True, message="ok")
        out = unshare_folder_everywhere([target, offline], "folder1", "T",
                                        member_ids={"P"})
    wr.assert_not_called()
    pending = [(nm, m) for nm, ok, m, unreachable in out if unreachable]
    assert pending and pending[0][0] == "p"


def test_unshare_flags_member_missing_from_device_list():
    # A member known only via the topology (never even discovered as a device) is still
    # reported as pending so the unshare isn't claimed complete.
    target = _dev("T")
    with patch("syncthing_manager.renamer.remove_folder_on_device") as rm, \
         patch("syncthing_manager.renamer.read_folder_cfg_on_device", return_value=None):
        rm.return_value = MagicMock(device_name="t", ok=True, message="ok")
        out = unshare_folder_everywhere([target], "folder1", "T", member_ids={"GHOST"})
    assert any(unreachable for _, ok, m, unreachable in out)


def test_unshare_reachable_member_not_flagged_when_folder_absent():
    # A reachable peer whose folder simply doesn't exist locally must NOT be reported as
    # an unreachable pending member (read returns None but the device IS reachable).
    target = _dev("T")
    peer = _dev("P")                       # reachable, but folder not present
    with patch("syncthing_manager.renamer.remove_folder_on_device") as rm, \
         patch("syncthing_manager.renamer.read_folder_cfg_on_device", return_value=None):
        rm.return_value = MagicMock(device_name="t", ok=True, message="ok")
        out = unshare_folder_everywhere([target, peer], "folder1", "T", member_ids={"P"})
    assert not any(nm == "p" and not ok for nm, ok, _, _ in out)


def test_unlink_flags_unreachable_member():
    target = _dev("T")
    offline = _unreachable("P")
    out = unlink_device_everywhere([target, offline], "T", member_ids={"P"})
    assert any(unreachable for _, ok, m, unreachable in out)


def test_unshare_prune_only_skips_target_deletion():
    # Passive re-sweep: the target's folder was already removed by the first run, so a
    # prune_only pass must NOT call remove_folder_on_device — only re-prune reachable peers.
    target = _dev("T")
    peer = _dev("P")
    fcfg = {"id": "folder1", "devices": [{"deviceID": "T"}, {"deviceID": "P"}]}
    with patch("syncthing_manager.renamer.remove_folder_on_device") as rm, \
         patch("syncthing_manager.renamer.read_folder_cfg_on_device", return_value=fcfg), \
         patch("syncthing_manager.renamer._write_folder_cfg_on_device") as wr:
        unshare_folder_everywhere([target, peer], "folder1", "T",
                                  member_ids={"P"}, prune_only=True)
    rm.assert_not_called()                 # target NOT re-deleted
    assert wr.call_count == 1              # peer still pruned


def test_unshare_dry_run_writes_nothing():
    target = _dev("T"); peer = _dev("P")
    fcfg = {"id": "folder1", "devices": [{"deviceID": "T"}, {"deviceID": "P"}]}
    with patch("syncthing_manager.renamer.remove_folder_on_device") as rm, \
         patch("syncthing_manager.renamer.read_folder_cfg_on_device", return_value=fcfg), \
         patch("syncthing_manager.renamer._write_folder_cfg_on_device") as wr:
        unshare_folder_everywhere([target, peer], "folder1", "T", dry_run=True)
    rm.assert_not_called()
    wr.assert_not_called()


def test_unlink_calls_delete_device_on_peers_listing_target():
    target = _dev("T"); peer = _dev("P")
    client = MagicMock()
    client.get_config_devices.return_value = [MagicMock(device_id="T"), MagicMock(device_id="P")]
    with patch("syncthing_manager.renamer.SyncthingClient", return_value=client):
        out = unlink_device_everywhere([target, peer], "T")
    client.delete_device.assert_called_once_with("T")
    assert any(ok for _, ok, _, _ in out)


def test_unlink_skips_peer_not_listing_target():
    peer = _dev("P")
    client = MagicMock()
    client.get_config_devices.return_value = [MagicMock(device_id="P")]   # no T
    with patch("syncthing_manager.renamer.SyncthingClient", return_value=client):
        out = unlink_device_everywhere([peer], "T")
    client.delete_device.assert_not_called()
    assert out == []


def test_unshare_prunes_local_node_folder_for_remote_target():
    # Regression (P5): when unsharing a REMOTE target, the LOCAL node must drop the target
    # from its folder membership — else the local Syncthing keeps offering the folder to a
    # device that no longer has it ("el nodo local sigue compartiendo").
    local = _local("L")
    target = _dev("T")
    fcfg = {"id": "folder1", "devices": [{"deviceID": "L"}, {"deviceID": "T"}]}
    with patch("syncthing_manager.renamer.remove_folder_on_device") as rm, \
         patch("syncthing_manager.renamer.read_folder_cfg_on_device", return_value=fcfg), \
         patch("syncthing_manager.renamer._write_folder_cfg_on_device") as wr:
        rm.return_value = MagicMock(device_name="t", ok=True, message="ok")
        unshare_folder_everywhere([local, target], "folder1", "T", member_ids=set())
    # The local folder was rewritten without the target.
    assert wr.call_count == 1
    written = wr.call_args.args[2]
    assert all(d["deviceID"] != "T" for d in written["devices"])


def test_unshare_local_target_removes_local_folder_and_prunes_peer():
    # P5: unsharing the LOCAL node = delete the folder on THIS machine (the target) and prune
    # the local id from every other reachable peer; the rest keep syncing among themselves.
    local = _local("L")
    peer = _dev("P")
    fcfg = {"id": "folder1", "devices": [{"deviceID": "L"}, {"deviceID": "P"}]}
    with patch("syncthing_manager.renamer.remove_folder_on_device") as rm, \
         patch("syncthing_manager.renamer.read_folder_cfg_on_device", return_value=fcfg), \
         patch("syncthing_manager.renamer._write_folder_cfg_on_device") as wr:
        rm.return_value = MagicMock(device_name="local", ok=True, message="ok")
        out = unshare_folder_everywhere([local, peer], "folder1", "L", member_ids={"P"})
    rm.assert_called_once()                 # folder deleted on the local target itself
    assert wr.call_count == 1               # peer P pruned of the local id
    written = wr.call_args.args[2]
    assert all(d["deviceID"] != "L" for d in written["devices"])
    assert any(ok for _, ok, _, _ in out)
