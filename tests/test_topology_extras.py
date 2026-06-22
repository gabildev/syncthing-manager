"""#55 extras: .stignore get/set, pending requests, share-with-device."""
from unittest.mock import MagicMock, patch

from syncthing_manager.models import DeviceInfo
from syncthing_manager.syncthing import SyncthingClient
from syncthing_manager.renamer import get_ignores_on_device, set_ignores_on_device


def _resp(json_data, status_code=200):
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = json_data
    m.content = b"x"
    m.raise_for_status = MagicMock()
    return m


def _client():
    return SyncthingClient("http://localhost:8384", "k")


def _local():
    return DeviceInfo(device_id="L", name="local", ip="127.0.0.1",
                      api_url="http://127.0.0.1:8384", api_key="k", folder_path="/x",
                      ssh_reachable=False, api_reachable=True, is_local=True)


# ── .stignore (client) ───────────────────────────────────────────────────────

def test_get_ignores_parses_list():
    c = _client()
    with patch.object(c._session, "get", return_value=_resp({"ignore": ["*.tmp", "/Cache"]})):
        assert c.get_ignores("f1") == ["*.tmp", "/Cache"]


def test_get_ignores_empty_when_none():
    c = _client()
    with patch.object(c._session, "get", return_value=_resp({"ignore": None})):
        assert c.get_ignores("f1") == []


def test_set_ignores_posts_patterns():
    c = _client()
    with patch.object(c._session, "post", return_value=_resp({})) as post:
        c.set_ignores("f1", ["*.tmp", "!keep"])
    body = post.call_args.kwargs["json"]
    assert body == {"ignore": ["*.tmp", "!keep"]}
    assert "folder" in post.call_args.kwargs["params"]


# ── .stignore (per-device helper, local channel) ──────────────────────────────

def test_get_ignores_on_device_local():
    fake = MagicMock()
    fake.get_ignores.return_value = ["a", "b"]
    with patch("syncthing_manager.renamer.SyncthingClient", return_value=fake):
        assert get_ignores_on_device(_local(), "f1") == ["a", "b"]


def test_set_ignores_on_device_local_ok():
    fake = MagicMock()
    with patch("syncthing_manager.renamer.SyncthingClient", return_value=fake):
        r = set_ignores_on_device(_local(), "f1", ["*.tmp"])
    fake.set_ignores.assert_called_once_with("f1", ["*.tmp"])
    assert r.ok


def test_set_ignores_on_device_unreachable():
    dev = DeviceInfo(device_id="P", name="pi", ip=None, api_url=None, api_key=None,
                     folder_path=None, ssh_reachable=False, api_reachable=False, is_local=False)
    r = set_ignores_on_device(dev, "f1", ["x"])
    assert not r.ok and "sin acceso" in r.message


# ── Pending requests ──────────────────────────────────────────────────────────

def test_get_pending_devices_dict_or_empty():
    c = _client()
    with patch.object(c._session, "get", return_value=_resp({"DID": {"name": "pc"}})):
        assert c.get_pending_devices() == {"DID": {"name": "pc"}}


def test_get_pending_folders_empty_on_error():
    c = _client()
    import requests
    with patch.object(c._session, "get", side_effect=requests.ConnectionError()):
        assert c.get_pending_folders() == {}


def test_add_device_puts_config():
    c = _client()
    with patch.object(c._session, "put", return_value=_resp({})) as put:
        c.add_device("ABC", name="laptop")
    body = put.call_args.kwargs["json"]
    assert body["deviceID"] == "ABC" and body["name"] == "laptop"


def test_share_folder_with_device_adds_member():
    c = _client()
    folder = MagicMock()
    folder.raw = {"id": "f1", "devices": [{"deviceID": "L"}]}
    with patch.object(c, "get_folder", return_value=folder), \
         patch.object(c, "_put") as put:
        c.share_folder_with_device("f1", "NEW")
    written = put.call_args.kwargs["json"] if put.call_args.kwargs else put.call_args.args[1]
    assert any(d["deviceID"] == "NEW" for d in written["devices"])


def test_dismiss_pending_device_calls_delete():
    c = _client()
    with patch.object(c._session, "delete", return_value=_resp({}, 200)) as d:
        c.dismiss_pending_device("ABC")
    assert d.call_args.kwargs["params"] == {"device": "ABC"}
