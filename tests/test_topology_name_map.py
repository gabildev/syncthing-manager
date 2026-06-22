"""Regression tests for `_resolve_name_map` — the deviceID→name resolver used to label
topology nodes (N7). The bug: an offline peer revealed by a reachable hub showed its bare
device id because hub expansion now creates a DeviceInfo whose name is only the short-id
fallback, and the old `name_map.setdefault()` (first-wins) could not let the REAL name the
local node had for it override that placeholder."""
from __future__ import annotations

from unittest.mock import MagicMock

from syncthing_manager.models import DeviceConfig, DeviceInfo
from syncthing_manager.topology import _name_is_placeholder, _resolve_name_map

# A real 63-char Syncthing device id (so name == id[:7] is a genuine short-id check).
DID = "ABCDEFG-HIJKLMN-OPQRSTU-VWXYZ01-23456AB-CDEFGHI-JKLMNOP-QRSTUVW"
SHORT = DID[:7]


def _dev(**kw) -> DeviceInfo:
    base = dict(
        device_id=DID, name=SHORT, ip=None, api_url=None, api_key=None, folder_path=None,
        ssh_reachable=False, api_reachable=False, is_local=False,
    )
    base.update(kw)
    return DeviceInfo(**base)


def test_placeholder_predicate():
    assert _name_is_placeholder("", DID)
    assert _name_is_placeholder(None, DID)
    assert _name_is_placeholder(DID, DID)          # full id
    assert _name_is_placeholder(SHORT, DID)        # short id
    assert not _name_is_placeholder("Raspberry Pi", DID)


def test_local_config_name_overrides_discovered_short_id():
    """The core regression: DeviceInfo carries only the short-id placeholder, but the local
    node's config knows the real name → the real name must win (setdefault could not)."""
    client = MagicMock()
    client.get_config_devices.return_value = [DeviceConfig(DID, "Raspberry Pi", [])]
    client.get_pending_devices.return_value = {}
    nm = _resolve_name_map([_dev(name=SHORT)], client)
    assert nm[DID] == "Raspberry Pi"


def test_pending_device_announced_name_resolves_offline_peer():
    """No DeviceInfo and no config entry — only the pending request's announced name."""
    client = MagicMock()
    client.get_config_devices.return_value = []
    client.get_pending_devices.return_value = {DID: {"name": "Laptop", "address": "1.2.3.4"}}
    nm = _resolve_name_map([], client)
    assert nm[DID] == "Laptop"


def test_real_discovered_name_is_not_clobbered_by_placeholders():
    client = MagicMock()
    client.get_config_devices.return_value = [DeviceConfig(DID, SHORT, [])]   # placeholder
    client.get_pending_devices.return_value = {DID: {"name": ""}}             # placeholder
    nm = _resolve_name_map([_dev(name="My NAS")], client)
    assert nm[DID] == "My NAS"


def test_all_placeholders_leaves_short_id():
    client = MagicMock()
    client.get_config_devices.return_value = []
    client.get_pending_devices.return_value = {}
    nm = _resolve_name_map([_dev(name=SHORT)], client)
    # only the placeholder is known → short id stands (the renderer's nid[:7] fallback)
    assert nm[DID] == SHORT


def test_client_none_skips_network_and_uses_devices_only():
    nm = _resolve_name_map([_dev(name="Office PC")], None)
    assert nm[DID] == "Office PC"


def test_extra_names_resolves_folder_peer_only_node():
    """The Topology-window case: a peer revealed only via a hub's folder_peers has no
    DeviceInfo and isn't in our config/pending — its name comes from the hub (extra_names)."""
    nm = _resolve_name_map([], None, extra_names={DID: "Hub-known name"})
    assert nm[DID] == "Hub-known name"


def test_extra_names_does_not_override_a_real_local_name():
    """A name the LOCAL node assigned is authoritative over the hub's name."""
    client = MagicMock()
    client.get_config_devices.return_value = [DeviceConfig(DID, "My local name", [])]
    client.get_pending_devices.return_value = {}
    nm = _resolve_name_map([], client, extra_names={DID: "Hub name"})
    assert nm[DID] == "My local name"


def test_extra_names_overrides_a_placeholder():
    nm = _resolve_name_map([_dev(name=SHORT)], None, extra_names={DID: "Real from hub"})
    assert nm[DID] == "Real from hub"


def test_local_config_name_beats_a_different_discovered_name():
    """Conflict resolution: when the local config and a DeviceInfo BOTH carry a real (but
    different) name for the same peer, the LOCAL node's name is authoritative."""
    client = MagicMock()
    client.get_config_devices.return_value = [DeviceConfig(DID, "What I call it", [])]
    client.get_pending_devices.return_value = {}
    nm = _resolve_name_map([_dev(name="What the hub calls it")], client)
    assert nm[DID] == "What I call it"


def test_api_errors_are_swallowed():
    client = MagicMock()
    client.get_config_devices.side_effect = Exception("boom")
    client.get_pending_devices.side_effect = Exception("boom")
    nm = _resolve_name_map([_dev(name=SHORT)], client)
    assert nm[DID] == SHORT          # degraded gracefully, no raise
