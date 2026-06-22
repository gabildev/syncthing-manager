"""Unit tests for the pure helpers added in the bug-batch (B2/B4/B7)."""
from syncthing_manager.syncthing import SyncthingClient
from syncthing_manager.renamer import _folders_sharing_peer


class TestAddressIsLan:
    def test_localhost_variants_are_not_lan(self):
        for a in ("127.0.0.1:8384", "localhost:8384", "[::1]:8384", "", None):
            assert SyncthingClient.address_is_lan(a) is False

    def test_lan_addresses(self):
        for a in ("0.0.0.0:8384", "192.168.1.10:8384", "10.0.0.5:8384"):
            assert SyncthingClient.address_is_lan(a) is True


class TestFoldersSharingPeer:
    def test_peer_present(self):
        folders = [{"id": "a", "devices": [{"deviceID": "X"}, {"deviceID": "Y"}]},
                   {"id": "b", "devices": [{"deviceID": "X"}]}]
        assert _folders_sharing_peer(folders, "Y") is True
        assert _folders_sharing_peer(folders, "X") is True

    def test_peer_absent(self):
        folders = [{"id": "a", "devices": [{"deviceID": "X"}]}]
        assert _folders_sharing_peer(folders, "Z") is False

    def test_winrm_dict_collapse(self):
        # WinRM/ConvertTo-Json can collapse a single-element devices list to a dict.
        folders = [{"id": "a", "devices": {"deviceID": "X"}}]
        assert _folders_sharing_peer(folders, "X") is True

    def test_empty(self):
        assert _folders_sharing_peer([], "X") is False
