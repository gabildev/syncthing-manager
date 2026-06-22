from __future__ import annotations

from unittest.mock import MagicMock, patch

from syncthing_manager.discovery import (
    _parse_remote_config, discover_devices, read_local_api_key, resolve_live_ip)
from syncthing_manager.models import ConnectionInfo, DeviceConfig, DeviceStats, FolderConfig


class TestResolveLiveIp:
    """resolve_live_ip backs the IP-autodetect in the add/edit dialogs — one place for the
    'connected address, else last-seen address, else None' lookup."""

    def _client(self, conn=None, stats=None, disc=None, cfg=None):
        c = MagicMock()
        c.get_connected_devices.return_value = conn or {}
        c.get_device_stats.return_value = stats or {}
        c.get_discovery.return_value = disc or {}
        c.get_config_devices.return_value = cfg or []
        return c

    def test_prefers_current_connected_ip(self):
        c = self._client(
            conn={"D": ConnectionInfo("D", True, "tcp://192.168.1.10:22000", "v1")},
            stats={"D": DeviceStats("D", "2024-01-01T00:00:00Z", "tcp://10.0.0.9:22000")})
        assert resolve_live_ip(c, "D") == "192.168.1.10"

    def test_falls_back_to_last_seen_when_not_connected(self):
        c = self._client(
            conn={"D": ConnectionInfo("D", False, "", "")},
            stats={"D": DeviceStats("D", "2024-01-01T00:00:00Z", "tcp://192.168.1.99:22000")})
        assert resolve_live_ip(c, "D") == "192.168.1.99"

    def test_falls_back_to_stats_when_absent_from_connections(self):
        c = self._client(
            conn={},
            stats={"D": DeviceStats("D", "2024-01-01T00:00:00Z", "tcp://192.168.1.50:22000")})
        assert resolve_live_ip(c, "D") == "192.168.1.50"

    def test_prefers_ipv4_over_live_ipv6_from_discovery(self):
        # Live connection is over IPv6 but discovery knows the LAN IPv4 → SSH must get the IPv4,
        # not the (unusable for SSH) IPv6. Regression: the old lookup returned conn.ip blindly.
        c = self._client(
            conn={"D": ConnectionInfo("D", True, "tcp://[fe80::1]:22000", "v1")},
            disc={"D": ["tcp://[fe80::1]:22000", "tcp://192.168.1.20:22000"]})
        assert resolve_live_ip(c, "D") == "192.168.1.20"

    def test_prefers_ipv4_from_config_addresses(self):
        # No IPv4 in the live connection, but the device's configured address pins one.
        c = self._client(
            conn={"D": ConnectionInfo("D", True, "tcp://[2001:db8::5]:22000", "v1")},
            cfg=[DeviceConfig("D", "Dev", ["tcp://192.168.1.30:22000"])])
        assert resolve_live_ip(c, "D") == "192.168.1.30"

    def test_none_when_unknown(self):
        assert resolve_live_ip(self._client(), "D") is None

    def test_none_when_no_client_or_id(self):
        assert resolve_live_ip(None, "D") is None
        assert resolve_live_ip(self._client(), "") is None

    def test_none_on_api_error(self):
        c = MagicMock()
        c.get_connected_devices.side_effect = RuntimeError("boom")
        assert resolve_live_ip(c, "D") is None


CONFIG_XML = """<?xml version="1.0" encoding="UTF-8"?>
<configuration version="35">
    <folder id="folder1" label="My Docs" path="/home/ubuntu/my-docs">
    </folder>
    <gui enabled="true" tls="false">
        <address>127.0.0.1:8385</address>
        <apikey>secretapikey9876</apikey>
    </gui>
</configuration>"""


class TestParseRemoteConfig:
    def test_extracts_api_key(self):
        key, port, path, peers, role, intro = _parse_remote_config(CONFIG_XML, "folder1")
        assert key == "secretapikey9876"

    def test_extracts_api_port(self):
        _, port, _, _, _, _ = _parse_remote_config(CONFIG_XML, "folder1")
        assert port == 8385

    def test_extracts_folder_path(self):
        _, _, path, _, _, _ = _parse_remote_config(CONFIG_XML, "folder1")
        assert path == "/home/ubuntu/my-docs"

    def test_returns_none_for_missing_folder(self):
        _, _, path, peers, role, intro = _parse_remote_config(CONFIG_XML, "nonexistent")
        assert path is None
        assert peers == []
        assert role is None
        assert intro == {}

    def test_default_port_8384(self):
        xml = """<configuration><gui><apikey>key</apikey></gui></configuration>"""
        _, port, _, _, _, _ = _parse_remote_config(xml, "f1")
        assert port == 8384

    def test_extracts_peers_role_and_introducers(self):
        xml = ("""<configuration><gui><apikey>k</apikey></gui>"""
               """<folder id="f1" path="/x" type="receiveonly">"""
               """<device id="DEV-A"></device>"""
               """<device id="DEV-B" introducedBy="DEV-A"></device>"""
               """</folder></configuration>""")
        _, _, _, peers, role, intro = _parse_remote_config(xml, "f1")
        assert peers == ["DEV-A", "DEV-B"]
        assert role == "receiveonly"
        assert intro == {"DEV-B": "DEV-A"}

    def test_ipv4_address_with_port(self):
        xml = """<configuration><gui><apikey>k</apikey><address>127.0.0.1:8385</address></gui></configuration>"""
        _, port, _, _, _, _ = _parse_remote_config(xml, "f1")
        assert port == 8385

    def test_bracketed_ipv6_address_with_port(self):
        xml = """<configuration><gui><apikey>k</apikey><address>[::1]:8385</address></gui></configuration>"""
        _, port, _, _, _, _ = _parse_remote_config(xml, "f1")
        assert port == 8385

    def test_bracketless_ipv6_no_port_keeps_default(self):
        # A bare IPv6 literal (many colons, no port) must NOT have a hextet mistaken for a port.
        xml = """<configuration><gui><apikey>k</apikey><address>fe80::1234</address></gui></configuration>"""
        _, port, _, _, _, _ = _parse_remote_config(xml, "f1")
        assert port == 8384

    def test_rejects_dtd_entity_billion_laughs(self):
        # A malicious peer's config.xml with entity definitions must be rejected pre-parse
        # (entity-expansion DoS), not expanded.
        from syncthing_manager.ssh_ops import SSHError
        xml = ('<?xml version="1.0"?>\n<!DOCTYPE lolz [<!ENTITY lol "lol">'
               '<!ENTITY lol2 "&lol;&lol;&lol;">]>\n<configuration><gui>'
               '<apikey>&lol2;</apikey></gui></configuration>')
        with __import__("pytest").raises(SSHError):
            _parse_remote_config(xml, "f1")


class TestIsIpv4:
    def test_accepts_valid(self):
        from syncthing_manager.discovery import _is_ipv4
        for ip in ("192.168.1.10", "10.0.0.5", "255.255.255.255", "0.0.0.0"):
            assert _is_ipv4(ip) is True, ip

    def test_rejects_out_of_range_octets(self):
        from syncthing_manager.discovery import _is_ipv4
        for ip in ("999.1.1.1", "256.0.0.1", "1.2.3.300"):
            assert _is_ipv4(ip) is False, ip

    def test_rejects_non_ipv4(self):
        from syncthing_manager.discovery import _is_ipv4
        for ip in ("fe80::1", "::1", "host.local", "", None):
            assert _is_ipv4(ip) is False, ip


class TestConnectionInfoIp:
    def test_parses_tcp_address(self):
        conn = ConnectionInfo("DEV1", True, "tcp://192.168.1.10:22000", "v1.25")
        assert conn.ip == "192.168.1.10"

    def test_parses_quic_address(self):
        conn = ConnectionInfo("DEV1", True, "quic://10.0.0.5:22000", "v1.25")
        assert conn.ip == "10.0.0.5"

    def test_parses_quic4_address(self):
        # quic4://quic6:// are real Syncthing schemes (parallel to tcp4/tcp6); they must be
        # stripped too or the whole 'quic4://ip:port' string leaks through as the bogus host.
        conn = ConnectionInfo("DEV1", True, "quic4://192.168.1.50:22000", "v1.25")
        assert conn.ip == "192.168.1.50"

    def test_parses_ipv6_address(self):
        conn = ConnectionInfo("DEV1", True, "tcp://[::1]:22000", "v1.25")
        assert conn.ip == "::1"

    def test_returns_none_for_empty(self):
        conn = ConnectionInfo("DEV1", False, "", "")
        assert conn.ip is None


class TestDeviceStatsLastIp:
    def test_parses_last_address(self):
        stat = DeviceStats("DEV1", "2024-01-01T00:00:00Z", "tcp://192.168.1.99:22000")
        assert stat.last_ip == "192.168.1.99"

    def test_none_when_no_address(self):
        stat = DeviceStats("DEV1", None, None)
        assert stat.last_ip is None


class TestDiscoverDevices:
    def _make_local_client(self):
        client = MagicMock()
        client.base_url = "http://localhost:8384"
        client.api_key = "localkey"
        client.get_my_device_id.return_value = "LOCAL-ID"
        client.get_config_devices.return_value = [
            DeviceConfig("LOCAL-ID", "mypc", []),
            DeviceConfig("REMOTE-1", "nas", []),
        ]
        client.get_connected_devices.return_value = {
            "REMOTE-1": ConnectionInfo("REMOTE-1", True, "tcp://192.168.1.20:22000", "v1.25"),
        }
        client.get_device_stats.return_value = {}
        return client

    def _make_folder(self):
        return FolderConfig(
            id="folder1",
            label="My Docs",
            path="/home/user/docs",
            devices=[{"deviceID": "LOCAL-ID"}, {"deviceID": "REMOTE-1"}],
        )

    def test_malformed_device_entries_dont_abort_discovery(self):
        """A bare-string / deviceID-less entry in folder.devices must be skipped, not crash
        the whole discovery (the seed loop isn't wrapped in a try)."""
        client = self._make_local_client()
        client.get_discovery.return_value = {}
        folder = FolderConfig(
            id="folder1", label="My Docs", path="/home/user/docs",
            devices=["not-a-dict", {"name": "no-id"}, {"deviceID": ""}],
        )
        with patch("syncthing_manager.discovery.probe_device") as mock_probe:
            devices = discover_devices(client, folder)   # must not raise
        mock_probe.assert_not_called()                   # no valid peer to probe
        assert [d for d in devices if d.is_local]         # local device still present

    def test_parse_hub_devices_tolerates_malformed_folder_data(self):
        """_parse_hub_devices runs OUTSIDE its caller's try/except — a None/non-dict folder_data
        or a bare-string device entry must be skipped, never raise AttributeError that would drop
        the entire hub's peer expansion."""
        from syncthing_manager.discovery import _parse_hub_devices
        # folder_data is None (folder paused/absent on the hub) — must return [] not raise.
        assert _parse_hub_devices(None, {}, {}, {}, set(), []) == []
        # A bare-string device entry is skipped; the valid one survives.
        out = _parse_hub_devices(
            {"devices": ["junk", {"deviceID": "NEW-PEER"}]},
            {}, {}, {}, set(), [])
        assert [d[0] for d in out] == ["NEW-PEER"]

    def test_parse_hub_devices_empty_name_falls_back_to_short_id(self):
        """A hub device whose config `name` is EMPTY (common for an offline/introducer-added peer)
        must fall back to the short device id, NEVER propagate a blank name (which the GUI then
        shows as a bare device-id)."""
        from syncthing_manager.discovery import _parse_hub_devices
        out = _parse_hub_devices(
            {"devices": [{"deviceID": "ABCDEFG-1234567"}]},   # folder member on the hub
            {},                                               # connections
            [{"deviceID": "ABCDEFG-1234567", "name": ""}],    # hub config: empty name
            {}, set(), [])
        assert out and out[0][1] == "ABCDEFG"                 # short id, not "" and not full id

    def test_local_device_always_included(self):
        client = self._make_local_client()
        folder = self._make_folder()

        with patch("syncthing_manager.discovery.probe_device") as mock_probe:
            mock_probe.return_value = MagicMock(is_local=False, device_id="REMOTE-1")
            devices = discover_devices(client, folder)

        local = next(d for d in devices if d.is_local)
        assert local.device_id == "LOCAL-ID"
        assert local.api_reachable is True

    def test_probes_remote_device(self):
        client = self._make_local_client()
        folder = self._make_folder()

        with patch("syncthing_manager.discovery.probe_device") as mock_probe:
            remote = MagicMock(is_local=False, device_id="REMOTE-1", name="nas")
            mock_probe.return_value = remote
            discover_devices(client, folder)

        mock_probe.assert_called_once()
        call_kwargs = mock_probe.call_args
        assert call_kwargs.kwargs["ip"] == "192.168.1.20"

    def test_uses_last_known_ip_for_offline_device(self):
        client = self._make_local_client()
        client.get_connected_devices.return_value = {}
        client.get_device_stats.return_value = {
            "REMOTE-1": DeviceStats("REMOTE-1", "2024-01-01T00:00:00Z", "tcp://192.168.1.20:22000")
        }
        folder = self._make_folder()

        with patch("syncthing_manager.discovery.probe_device") as mock_probe:
            mock_probe.return_value = MagicMock(is_local=False)
            discover_devices(client, folder)

        call_kwargs = mock_probe.call_args
        assert call_kwargs.kwargs["ip"] == "192.168.1.20"
        assert call_kwargs.kwargs["connected"] is False


class TestReadLocalApiKey:
    def test_reads_key_from_config_xml(self, tmp_path, monkeypatch):
        # Place config at the standard Linux path under our fake home
        config_dir = tmp_path / ".config" / "syncthing"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.xml"
        config_file.write_text("""<configuration>
            <gui><apikey>mylocalapikey</apikey></gui>
        </configuration>""")

        # Isolate from the host: clear XDG overrides and disable the running-process/systemd
        # scan, otherwise a REAL Syncthing running on the dev machine returns its own
        # config.xml first and the test reads the real API key instead of our fake one.
        for _v in ("XDG_STATE_HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
            monkeypatch.delenv(_v, raising=False)
        monkeypatch.setattr(
            "syncthing_manager.discovery._find_syncthing_config_paths_dynamic", lambda: [])
        # expanduser("~") → tmp_path, so candidate becomes tmp_path/.config/syncthing/config.xml
        with patch("os.path.expanduser", return_value=str(tmp_path)):
            key = read_local_api_key()

        assert key == "mylocalapikey"


class TestManualProbeSshCredVerification:
    """probe_device_manual must distinguish SSH creds that are REJECTED by a reachable host
    (credenciales fallidas) from a host that's simply offline (legit offline-with-creds passive)."""

    def _probe(self, **over):
        from syncthing_manager.discovery import probe_device_manual
        args = dict(device_id="D1", name="pi", ip="10.0.0.2", folder_id="f1",
                    api_key="k", api_url="http://10.0.0.2:8384", folder_path="/x",
                    ssh_user="pi", ssh_password="bad")
        args.update(over)
        with patch("syncthing_manager.syncthing.SyncthingClient.ping", return_value=False):
            return probe_device_manual(**args)

    def test_auth_rejected_flags_bad_creds(self):
        from syncthing_manager.ssh_ops import SSHError
        # Host UP (port open) but auth rejected → ssh_reachable False + ssh_error set.
        with patch("syncthing_manager.discovery._ssh_port_open", return_value=True), \
             patch("syncthing_manager.ssh_ops.SSHClient.connect",
                   side_effect=SSHError("Authentication failed for 10.0.0.2: bad password")):
            dev = self._probe()
        assert dev.ssh_reachable is False
        assert dev.ssh_error and "rechazadas" in dev.ssh_error
        # Only a VERIFIED rejection sets the flag the GUI keys on (cred badge / passive untick /
        # topology halo) — never the mere presence of an ssh_error.
        assert dev.ssh_creds_rejected is True

    def test_offline_host_stays_optimistic_passive(self):
        # Port closed (host down) → no handshake; keep ssh_reachable True (legit passive), no error.
        with patch("syncthing_manager.discovery._ssh_port_open", return_value=False):
            dev = self._probe()
        assert dev.ssh_reachable is True
        assert dev.ssh_error is None
        assert dev.ssh_creds_rejected is False

    def test_port_open_good_creds_is_reachable(self):
        # Port open + handshake succeeds → reachable, no error.
        ssh = MagicMock()
        ssh.__enter__ = MagicMock(return_value=ssh)
        ssh.__exit__ = MagicMock(return_value=False)
        ssh.is_windows.return_value = False
        with patch("syncthing_manager.discovery._ssh_port_open", return_value=True), \
             patch("syncthing_manager.ssh_ops.SSHClient", return_value=ssh):
            dev = self._probe()
        assert dev.ssh_reachable is True
        assert dev.ssh_error is None


class TestBenignSshErrorIsNotCredRejection:
    """A benign ssh_error (offline/no-IP, config.xml not found, no creds) must NOT set
    ssh_creds_rejected — otherwise the GUI condemns legit offline passive targets as
    'credenciales inválidas' and force-unticks them from passive exploration."""

    def test_offline_no_ip_device_is_not_cred_rejected(self):
        from syncthing_manager.discovery import probe_device
        dev = probe_device(device_id="D1", name="pi", ip=None, folder_id="f1")
        # The canonical passive target: offline, no IP. It carries an ssh_error for display…
        assert dev.ssh_error == "No IP address known"
        # …but its credentials were never tested, so it must not be flagged rejected.
        assert dev.ssh_creds_rejected is False

    def test_auto_discovery_auth_rejection_flags_rejected(self):
        """Regression: stored SSH creds gone bad must still flag ssh_creds_rejected during
        AUTOMATIC discovery (not just the manual probe), so the red 'inválidas' badge fires."""
        from syncthing_manager.discovery import probe_device
        from syncthing_manager.ssh_ops import SSHError
        with patch("syncthing_manager.discovery._tcp_open", return_value=True), \
             patch("syncthing_manager.ssh_ops.SSHClient.connect",
                   side_effect=SSHError("Authentication failed for pi@10.0.0.2")):
            dev = probe_device(device_id="D1", name="pi", ip="10.0.0.2", folder_id="f1",
                               override={"ssh_user": "pi", "ssh_password": "wrong"})
        assert dev.ssh_reachable is False
        assert dev.ssh_creds_rejected is True

    def test_auto_discovery_port_closed_is_not_cred_rejected(self):
        """A closed SSH port (host down) with stored creds is a legit offline target, NOT a
        rejection — it must stay green '✓ cred.', not red 'inválidas'."""
        from syncthing_manager.discovery import probe_device
        with patch("syncthing_manager.discovery._tcp_open", return_value=False):
            dev = probe_device(device_id="D1", name="pi", ip="10.0.0.2", folder_id="f1",
                               override={"ssh_user": "pi", "ssh_password": "secret"})
        assert dev.ssh_creds_rejected is False


class TestManualProbeArchDetection:
    """probe_device_manual must populate arch/arch_detected from the API
    (/rest/system/version) or, when the API is unreachable, from the SSH probe's `uname -m`."""

    def _probe(self, **over):
        from syncthing_manager.discovery import probe_device_manual
        args = dict(device_id="D1", name="pi", ip="10.0.0.2", folder_id="f1",
                    api_key="k", api_url="http://10.0.0.2:8384", folder_path="/x")
        args.update(over)
        return probe_device_manual(**args)

    def test_arch_from_api(self):
        with patch("syncthing_manager.syncthing.SyncthingClient.ping", return_value=True), \
             patch("syncthing_manager.syncthing.SyncthingClient.get_os", return_value="linux"), \
             patch("syncthing_manager.syncthing.SyncthingClient.get_arch", return_value="arm64"), \
             patch("syncthing_manager.syncthing.SyncthingClient.get_folder", return_value=None):
            dev = self._probe()
        assert dev.arch == "arm64"
        assert dev.arch_detected is True

    def test_arch_none_when_api_down_and_no_ssh(self):
        # API unreachable and no SSH creds → arch stays unknown (no probe to read it from).
        with patch("syncthing_manager.syncthing.SyncthingClient.ping", return_value=False):
            dev = self._probe()
        assert dev.arch is None
        assert dev.arch_detected is False

    def test_arch_from_ssh_when_api_unreachable(self):
        # API down but SSH creds given + port open + handshake OK → arch from the probe's uname -m.
        ssh = MagicMock()
        ssh.__enter__ = MagicMock(return_value=ssh)
        ssh.__exit__ = MagicMock(return_value=False)
        ssh.os_kind.return_value = "linux"
        ssh.arch_kind.return_value = "amd64"
        with patch("syncthing_manager.syncthing.SyncthingClient.ping", return_value=False), \
             patch("syncthing_manager.discovery._ssh_port_open", return_value=True), \
             patch("syncthing_manager.ssh_ops.SSHClient", return_value=ssh):
            dev = self._probe(ssh_user="pi", ssh_password="pw")
        assert dev.arch == "amd64"
        assert dev.arch_detected is True


class TestManualProbeWinrmCredVerification:
    """probe_device_manual must verify WinRM creds the same way it does SSH (R20): a host that
    ANSWERS on the WinRM port but fails the handshake is 'credenciales fallidas', not a healthy
    device that's silently trusted just because creds were typed."""

    def _probe(self, **over):
        from syncthing_manager.discovery import probe_device_manual
        args = dict(device_id="W1", name="win", ip="10.0.0.3", folder_id="f1",
                    api_key="k", api_url="http://10.0.0.3:8384", folder_path="C:/x",
                    winrm_user="admin", winrm_password="bad")
        args.update(over)
        with patch("syncthing_manager.syncthing.SyncthingClient.ping", return_value=False):
            return probe_device_manual(**args)

    def test_handshake_failure_flags_bad_creds(self):
        from syncthing_manager.winrm_ops import WinRMError
        # Port open (host up) but handshake rejected → winrm_reachable False + error surfaced.
        with patch("syncthing_manager.discovery._tcp_open", return_value=True), \
             patch("syncthing_manager.winrm_ops.WinRMClient.connect",
                   side_effect=WinRMError("the specified credentials were rejected")):
            dev = self._probe()
        assert dev.winrm_reachable is False
        assert dev.ssh_error and "WinRM" in dev.ssh_error
        assert dev.ssh_creds_rejected is True

    def test_offline_host_stays_optimistic(self):
        # Port closed (host down) → no handshake; keep winrm_reachable True (legit passive target).
        with patch("syncthing_manager.discovery._tcp_open", return_value=False):
            dev = self._probe()
        assert dev.winrm_reachable is True
        assert dev.ssh_error is None

    def test_transient_blip_stays_optimistic_not_flagged_bad(self):
        # Port open but a TRANSIENT error (timeout, not an auth rejection) must NOT flip a healthy
        # device to "bad credentials" — same philosophy as the SSH path.
        from syncthing_manager.winrm_ops import WinRMError
        with patch("syncthing_manager.discovery._tcp_open", return_value=True), \
             patch("syncthing_manager.winrm_ops.WinRMClient.connect",
                   side_effect=WinRMError("read operation timed out")):
            dev = self._probe()
        assert dev.winrm_reachable is True
        assert dev.ssh_error is None

    def test_port_open_good_creds_is_reachable(self):
        with patch("syncthing_manager.discovery._tcp_open", return_value=True), \
             patch("syncthing_manager.winrm_ops.WinRMClient.connect", return_value=None), \
             patch("syncthing_manager.winrm_ops.WinRMClient.close", return_value=None):
            dev = self._probe()
        assert dev.winrm_reachable is True
        assert dev.ssh_error is None


class TestSshPortOpen:
    def test_closed_port_returns_false(self):
        from syncthing_manager.discovery import _ssh_port_open
        # An unroutable/closed target returns False fast (short timeout), never raises.
        assert _ssh_port_open("192.0.2.1", 22, timeout=0.2) is False
