from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from syncthing_manager.syncthing import SyncthingClient, SyncthingError


@pytest.fixture
def client():
    return SyncthingClient("http://localhost:8384", "testapikey1234")


def _mock_response(json_data, status_code=200):
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_data
    mock.content = b"content"
    mock.raise_for_status = MagicMock()
    return mock


class TestPing:
    def test_ping_success(self, client):
        with patch.object(client._session, "get", return_value=_mock_response({"ping": "pong"})):
            assert client.ping() is True

    def test_ping_failure_wrong_response(self, client):
        with patch.object(client._session, "get", return_value=_mock_response({"ping": "fail"})):
            assert client.ping() is False

    def test_ping_connection_error(self, client):
        with patch.object(client._session, "get", side_effect=requests.ConnectionError()):
            assert client.ping() is False


class TestGetFolders:
    def test_returns_folder_list(self, client):
        data = [
            {"id": "folder1", "label": "My Docs", "path": "/home/user/docs", "devices": [{"deviceID": "ABC"}]},
            {"id": "folder2", "label": "Photos", "path": "/home/user/photos", "devices": []},
        ]
        with patch.object(client._session, "get", return_value=_mock_response(data)):
            folders = client.get_folders()
        assert len(folders) == 2
        assert folders[0].id == "folder1"
        assert folders[0].label == "My Docs"
        assert folders[1].id == "folder2"

    def test_raises_on_error(self, client):
        with patch.object(client._session, "get", side_effect=requests.ConnectionError()):
            with pytest.raises(SyncthingError):
                client.get_folders()

    def test_skips_malformed_entries(self, client):
        # A hostile/malformed response (non-dict element, missing id, non-list) must not crash.
        data = [{"id": "ok", "label": "L", "path": "/p", "devices": []},
                "not-a-dict", {"label": "no-id"}]
        with patch.object(client._session, "get", return_value=_mock_response(data)):
            folders = client.get_folders()
        assert [f.id for f in folders] == ["ok"]

    def test_non_list_response_returns_empty(self, client):
        with patch.object(client._session, "get", return_value=_mock_response({"unexpected": 1})):
            assert client.get_folders() == []


class TestGetFolder:
    def test_returns_single_folder(self, client):
        data = {"id": "folder1", "label": "My Docs", "path": "/home/user/docs", "devices": []}
        with patch.object(client._session, "get", return_value=_mock_response(data)):
            folder = client.get_folder("folder1")
        assert folder is not None
        assert folder.id == "folder1"

    def test_returns_none_on_404(self, client):
        # A genuine 'folder not found' (404) → None.
        resp = MagicMock()
        resp.status_code = 404
        http_err = requests.HTTPError(response=resp)
        resp.raise_for_status = MagicMock(side_effect=http_err)
        with patch.object(client._session, "get", return_value=resp):
            result = client.get_folder("missing")
        assert result is None

    def test_raises_on_transient_error(self, client):
        # A connection blip (no HTTP response) must NOT be mistaken for 'not found':
        # callers would otherwise create/overwrite a folder that actually exists.
        with patch.object(client._session, "get", side_effect=requests.ConnectionError()):
            with pytest.raises(SyncthingError):
                client.get_folder("folder1")

    def test_malformed_200_raises_not_none(self, client):
        # A non-dict 200 body must surface as a handled SyncthingError, never None (callers
        # read None as 'absent' and would then create/overwrite the folder).
        with patch.object(client._session, "get", return_value=_mock_response(["not", "a", "dict"])):
            with pytest.raises(SyncthingError):
                client.get_folder("folder1")


class TestGetMyDeviceId:
    def test_returns_device_id(self, client):
        with patch.object(client._session, "get", return_value=_mock_response({"myID": "DEVICE123"})):
            assert client.get_my_device_id() == "DEVICE123"

    def test_missing_myid_raises_syncthing_error_not_keyerror(self, client):
        # A malformed status response must surface as a handled SyncthingError (callers only
        # catch that), never a raw KeyError.
        with patch.object(client._session, "get", return_value=_mock_response({"version": "v1"})):
            with pytest.raises(SyncthingError):
                client.get_my_device_id()


class TestGetConnectedDevices:
    def test_parses_connections(self, client):
        data = {
            "connections": {
                "DEV1": {"connected": True, "address": "tcp://192.168.1.10:22000", "clientVersion": "v1.25.0"},
                "DEV2": {"connected": False, "address": "", "clientVersion": ""},
            }
        }
        with patch.object(client._session, "get", return_value=_mock_response(data)):
            conns = client.get_connected_devices()
        assert "DEV1" in conns
        assert conns["DEV1"].connected is True
        assert conns["DEV1"].ip == "192.168.1.10"
        assert conns["DEV2"].connected is False

    def test_skips_malformed_entry_without_raising(self, client):
        # A null / non-dict per-device entry must be skipped (matches get_device_stats /
        # get_discovery), not raise AttributeError that loses a whole hub's expansion.
        data = {"connections": {"DEV1": {"connected": True, "address": "tcp://10.0.0.2:22000",
                                         "clientVersion": "v1"}, "BAD": None, "BAD2": "x"}}
        with patch.object(client._session, "get", return_value=_mock_response(data)):
            conns = client.get_connected_devices()
        assert set(conns) == {"DEV1"} and conns["DEV1"].ip == "10.0.0.2"


class TestAddressIsLan:
    def test_localhost_variants_not_lan(self):
        for a in ("127.0.0.1:8384", "[::1]:8384", "localhost:8384"):
            assert SyncthingClient.address_is_lan(a) is False, a

    def test_all_interfaces_and_lan_are_lan(self):
        # ':8384' / 'tcp://:8384' = host omitted = ALL interfaces → LAN-exposed (regression).
        for a in ("0.0.0.0:8384", "[::]:8384", "192.168.1.5:8384", ":8384", "tcp://:8384"):
            assert SyncthingClient.address_is_lan(a) is True, a


class TestWaitForPause:
    def test_returns_true_when_paused(self, client):
        with patch.object(client, "get_folder_status", return_value={"state": "paused"}):
            assert client.wait_for_pause("folder1", timeout=5) is True

    def test_returns_true_when_state_empty(self, client):
        # Syncthing 1.20+ reports an EMPTY state ("") for a paused folder (the runner is stopped),
        # not "paused" — wait_for_pause must accept that, or it falsely times out on every rename.
        with patch.object(client, "get_folder_status", return_value={"state": ""}):
            assert client.wait_for_pause("folder1", timeout=5) is True

    def test_returns_false_on_timeout(self, client):
        # A running-but-idle folder ("idle", non-empty) is NOT paused → keep waiting → timeout.
        with patch.object(client, "get_folder_status", return_value={"state": "idle"}):
            with patch("syncthing_manager.syncthing.time.sleep"):
                assert client.wait_for_pause("folder1", timeout=1) is False

    def test_handles_api_errors_gracefully(self, client):
        with patch.object(client, "get_folder_status", side_effect=SyncthingError("fail")):
            with patch("syncthing_manager.syncthing.time.sleep"):
                assert client.wait_for_pause("folder1", timeout=1) is False


class TestUpdateFolderConfig:
    def test_updates_label_and_path_only(self, client):
        original = {
            "id": "folder1",
            "label": "Old Label",
            "path": "/old/path",
            "devices": [{"deviceID": "ABC"}],
            "versioning": {"type": "simple"},
        }
        updated = {**original, "label": "New Label", "path": "/new/path"}

        get_responses = [original, updated]
        get_call_count = [0]

        def fake_get(url, **kwargs):
            mock = _mock_response(get_responses[min(get_call_count[0], 1)])
            get_call_count[0] += 1
            return mock

        put_mock = _mock_response(updated)
        put_mock.content = b"content"

        with patch.object(client._session, "get", side_effect=fake_get):
            with patch.object(client._session, "put", return_value=put_mock) as put:
                client.update_folder_config("folder1", "New Label", "/new/path")

        # Verify the PUT body actually carried the new label/path and PRESERVED the rest
        # (the whole point of the function — not just that it didn't raise).
        body = put.call_args.kwargs["json"]
        assert body["label"] == "New Label"
        assert body["path"] == "/new/path"
        assert body["devices"] == [{"deviceID": "ABC"}]      # membership preserved
        assert body["versioning"] == {"type": "simple"}      # versioning preserved

    def test_raises_if_verification_fails(self, client):
        stale = {"id": "folder1", "label": "Old Label", "path": "/old/path", "devices": []}

        with patch.object(client._session, "get", return_value=_mock_response(stale)):
            with patch.object(client._session, "put", return_value=_mock_response(stale)):
                with pytest.raises(SyncthingError, match="not reflected"):
                    client.update_folder_config("folder1", "New Label", "/new/path")


class TestIsVersionGte:
    def test_true_for_newer_version(self, client):
        with patch.object(client, "get_version", return_value="v1.25.0"):
            assert client.is_version_gte("1.20.0") is True

    def test_false_for_older_version(self, client):
        with patch.object(client, "get_version", return_value="v1.19.2"):
            assert client.is_version_gte("1.20.0") is False

    def test_true_for_equal_version(self, client):
        with patch.object(client, "get_version", return_value="v1.20.0"):
            assert client.is_version_gte("1.20.0") is True

    def test_two_segment_version_not_treated_as_older(self, client):
        # (1,20) must NOT compare < (1,20,0) — pad to equal length.
        with patch.object(client, "get_version", return_value="v1.20"):
            assert client.is_version_gte("1.20.0") is True
        with patch.object(client, "get_version", return_value="v1.21"):
            assert client.is_version_gte("1.20.0") is True

    def test_prerelease_suffix_compares_on_numeric_base(self, client):
        # Pre-release/dev suffixes must compare on their numeric base and NEVER raise.
        with patch.object(client, "get_version", return_value="1.12.0-rc.1"):
            assert client.is_version_gte("1.12.0") is True
        with patch.object(client, "get_version", return_value="1.27.0-dev"):
            assert client.is_version_gte("1.12.0") is True
        with patch.object(client, "get_version", return_value="1.11.0-rc.2"):
            assert client.is_version_gte("1.12.0") is False

    def test_unparseable_version_does_not_raise(self, client):
        # Garbage parses to (0,0,0) → below the floor, but must not raise (old int() would).
        with patch.object(client, "get_version", return_value="weird"):
            assert client.is_version_gte("1.12.0") is False


class TestGetArch:
    """get_arch() reads /rest/system/version 'arch' (Go GOARCH) and normalizes it to our
    template naming, so the agent flow can auto-pick the right Linux/macOS build."""

    def test_amd64(self, client):
        with patch.object(client, "_get", return_value={"arch": "amd64"}):
            assert client.get_arch() == "amd64"

    def test_arm64(self, client):
        with patch.object(client, "_get", return_value={"arch": "arm64"}):
            assert client.get_arch() == "arm64"

    def test_go_arm_maps_to_armv7(self, client):
        # Syncthing reports 32-bit ARM as GOARCH 'arm' → our template arch is 'armv7'.
        with patch.object(client, "_get", return_value={"arch": "arm"}):
            assert client.get_arch() == "armv7"

    def test_missing_arch_field_returns_none(self, client):
        with patch.object(client, "_get", return_value={"version": "v1.27.0"}):
            assert client.get_arch() is None

    def test_api_error_returns_none(self, client):
        with patch.object(client, "_get", side_effect=SyncthingError("boom")):
            assert client.get_arch() is None

    def test_non_dict_body_returns_none(self, client):
        # A hostile/malformed hub returning a JSON list (not an object) must not crash.
        with patch.object(client, "_get", return_value=["unexpected"]):
            assert client.get_arch() is None

    def test_non_string_arch_returns_none(self, client):
        # arch as a number/list → must NOT raise (it feeds normalize_arch's .lower()).
        with patch.object(client, "_get", return_value={"arch": 12345}):
            assert client.get_arch() is None


class TestGetOs:
    """get_os() must tolerate hostile/malformed /rest/system/version bodies."""

    def test_darwin_maps_to_macos(self, client):
        with patch.object(client, "_get", return_value={"os": "darwin"}):
            assert client.get_os() == "macos"

    def test_non_string_os_returns_none(self, client):
        with patch.object(client, "_get", return_value={"os": 123}):
            assert client.get_os() is None

    def test_non_dict_body_returns_none(self, client):
        with patch.object(client, "_get", return_value=["x"]):
            assert client.get_os() is None


class TestRestDevicePathEncoding:
    """Device ids can arrive verbatim from a remote/possibly-malicious hub; the REST path
    builder must URL-encode them so a crafted id can't redirect/inject the local-API request."""

    def test_normal_device_id_unchanged(self):
        from syncthing_manager.syncthing import rest_device_path
        # A real base32+dash id is URL-safe → no-op (path stays literal).
        did = "ABCDEF1-GHIJKL2-MNOPQR3-STUVWX4"
        assert rest_device_path(did) == f"/rest/config/devices/{did}"

    def test_crafted_id_is_encoded(self):
        from syncthing_manager.syncthing import rest_device_path
        # '?', '/', '#', '..' must be percent-encoded, not left to alter the endpoint/query.
        p = rest_device_path("foo?folder=evil#/../system/restart")
        assert "?" not in p and "#" not in p
        assert p.startswith("/rest/config/devices/")
        assert "%3F" in p and "%2F" in p   # ? and / encoded

    def test_empty_id_safe(self):
        from syncthing_manager.syncthing import rest_device_path
        assert rest_device_path("") == "/rest/config/devices/"
