from __future__ import annotations

from unittest.mock import MagicMock, patch

from syncthing_manager.device_names import sync_device_names
from syncthing_manager.models import DeviceInfo
from syncthing_manager.syncthing import SyncthingError


def _dev(**kw) -> DeviceInfo:
    base = dict(
        device_id="D", name="dev", ip=None, api_url=None, api_key=None, folder_path=None,
        ssh_reachable=False, api_reachable=False, is_local=False,
    )
    base.update(kw)
    return DeviceInfo(**base)


class TestSyncDeviceNames:
    def test_local_device_patches_each_name(self):
        client = MagicMock()
        client.patch_device_name.return_value = True
        res = sync_device_names(client, [_dev(is_local=True, name="local")],
                                {"A": "Alpha", "B": "Beta"})
        assert len(res) == 1
        assert res[0].success and res[0].updated == 2 and res[0].not_found == 0
        called = {c.args for c in client.patch_device_name.call_args_list}
        assert ("A", "Alpha") in called and ("B", "Beta") in called

    def test_entry_not_in_target_counts_as_not_found(self):
        client = MagicMock()
        client.patch_device_name.side_effect = [True, False]   # A applied, B absent
        res = sync_device_names(client, [_dev(is_local=True)], {"A": "Alpha", "B": "Beta"})
        assert res[0].updated == 1 and res[0].not_found == 1

    def test_syncthing_error_per_entry_is_not_fatal(self):
        client = MagicMock()
        client.patch_device_name.side_effect = SyncthingError("boom")
        res = sync_device_names(client, [_dev(is_local=True)], {"A": "Alpha"})
        assert res[0].success                       # per-entry error swallowed
        assert res[0].updated == 0 and res[0].not_found == 1

    def test_unreachable_device_is_skipped(self):
        client = MagicMock()
        res = sync_device_names(client, [_dev()], {"A": "Alpha"})  # no channel reachable
        assert res == []

    def test_api_reachable_uses_its_own_client_not_local(self):
        local = MagicMock()
        remote = MagicMock()
        remote.patch_device_name.return_value = True
        dev = _dev(api_reachable=True, api_url="http://192.168.1.20:8384", api_key="K")
        with patch("syncthing_manager.device_names.SyncthingClient", return_value=remote) as SC:
            res = sync_device_names(local, [dev], {"A": "Alpha"})
        SC.assert_called_once()                     # a client built for the remote target
        assert res[0].updated == 1
        remote.patch_device_name.assert_called_once_with("A", "Alpha")
        local.patch_device_name.assert_not_called()
