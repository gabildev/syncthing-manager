from __future__ import annotations

import glob
import logging
import os
import platform
import queue
import re
import socket
import subprocess
import threading
import xml.etree.ElementTree as ET
from typing import Callable, Optional

from .i18n import t as _T

# Concurrent probes during discovery. LAN-bound; most time is SSH/API timeouts,
# so a generous pool overlaps them and cuts discovery time dramatically.
DISCOVERY_WORKERS = 16

# Quick TCP reachability check (seconds) used before a full SSH/WinRM/API attempt,
# so an offline host fails fast instead of waiting the whole connect timeout.
TCP_PRECHECK_TIMEOUT = 1.5

try:
    import pwd as _pwd
except ImportError:
    _pwd = None  # type: ignore[assignment]  # Windows

from .models import DeviceInfo, FolderConfig, parse_ip_from_address
from .ssh_ops import SSHClient, SSHError
from .syncthing import SyncthingClient, SyncthingError, rest_folder_path
from .winrm_ops import WinRMClient, WinRMError

logger = logging.getLogger(__name__)


def resolve_live_ip(client, device_id: str) -> Optional[str]:
    """Best-known IP for a device according to the LOCAL Syncthing, PREFERRING IPv4: across its
    current connected address, its last-seen address, the addresses Syncthing has discovered for
    it, and its configured addresses — the first usable IPv4. SSH over a LAN IPv6 (esp. a
    link-local fe80::) is unusable, so a dialog must NOT hand SSH the live IPv6 when an IPv4 is
    known elsewhere (discovery often holds the real LAN IPv4 even when the live connection is
    over IPv6). Returns None when nothing is known.

    Single place for this lookup so every "enter a Device ID" dialog (add in Devices, add
    in Topología, edit credentials) resolves the IP identically — avoids the per-site drift
    that let the dialogs disagree, and matches the IPv4 preference of discover_devices."""
    if not client or not device_id:
        return None
    try:
        ci = client.get_connected_devices().get(device_id)
        st = client.get_device_stats().get(device_id)
        disc_ips = [e for addr in (client.get_discovery().get(device_id, []) or [])
                    if (e := _ip_from_syncthing_addr(addr))]
        cfg_ips: list = []
        for d in client.get_config_devices():
            if getattr(d, "device_id", None) == device_id:
                cfg_ips = [e for addr in (d.addresses or [])
                           if (e := _ip_from_syncthing_addr(addr))]
                break
        return _prefer_ipv4(
            ci.ip if (ci and ci.connected) else None,
            st.last_ip if st else None,
            *cfg_ips, *disc_ips,
        )
    except Exception:
        return None


def discover_devices(
    local_client: SyncthingClient,
    folder: FolderConfig,
    devices_config: Optional[list[dict]] = None,
    on_device_found: Optional[Callable[[DeviceInfo], None]] = None,
    keep: Optional[dict[str, DeviceInfo]] = None,
) -> list[DeviceInfo]:
    """
    Discover all devices sharing the given folder.

    Uses a dynamic queue so that hub devices (e.g. a Raspberry Pi in a star
    topology) automatically expose the devices they know about.  The local
    Syncthing config only needs to list the hub; the hub's API reveals the rest.

    devices_config: optional credential overrides (entry with no device_id/name = global default).
    on_device_found: callback fired as each DeviceInfo is resolved.
    """
    my_id = local_client.get_my_device_id()
    local_config_devices = {d.device_id: d for d in local_client.get_config_devices()}

    connections = local_client.get_connected_devices()
    try:
        stats = local_client.get_device_stats()
    except SyncthingError:
        stats = {}
    discovery = local_client.get_discovery()  # device_id → [addresses]; best-effort

    local_info = DeviceInfo(
        device_id=my_id,
        name=_get_local_hostname(local_client),
        ip="127.0.0.1",
        api_url=local_client.base_url,
        api_key=local_client.api_key,
        folder_path=folder.path,
        ssh_reachable=False,
        api_reachable=True,
        is_local=True,
        os_type=_local_os_type(),
        os_detected=True,
        arch=_local_arch(),
        arch_detected=True,
        folder_peers=[d.get("deviceID") for d in folder.devices
                      if isinstance(d, dict) and d.get("deviceID")],
        folder_role=(folder.raw or {}).get("type"),
        folder_introducers={d["deviceID"]: d["introducedBy"] for d in folder.devices
                            if isinstance(d, dict) and d.get("deviceID") and d.get("introducedBy")},
    )
    if on_device_found:
        on_device_found(local_info)

    result: list[DeviceInfo] = [local_info]
    result_lock = threading.Lock()

    # ── Dynamic, parallel discovery ───────────────────────────────────────────
    # A small worker pool drains a queue that can GROW while it runs: each hub
    # device, once probed, reveals more devices that are fed back into the queue.
    # `pending` tracks queued-but-unfinished work; discovery ends when it hits 0.
    known_ids: set[str] = {my_id}
    known_lock = threading.Lock()
    work_q: queue.Queue = queue.Queue()
    pending = 0
    pending_lock = threading.Lock()
    done = threading.Event()

    def _enqueue(device_id: str, name: str, ip: Optional[str],
                 connected: bool = False, override: Optional[dict] = None) -> None:
        nonlocal pending
        with known_lock:
            if device_id in known_ids:
                return
            known_ids.add(device_id)
        with pending_lock:
            pending += 1
        work_q.put((device_id, name, ip, connected, override))

    def _probe(device_id, name, ip, connected, override) -> DeviceInfo:
        # Lighter re-discovery: reuse a device already known to be reachable instead of
        # re-probing it (its hub expansion still runs with the cached credentials).
        if keep:
            cached = keep.get(device_id)
            if cached is not None and (cached.api_reachable or cached.ssh_reachable
                                       or cached.winrm_reachable):
                return cached
        if override and override.get("api_key") and override.get("api_url"):
            return probe_device_manual(
                device_id=device_id, name=name,
                ip=ip or override.get("ssh_host", ""), folder_id=folder.id,
                api_key=override["api_key"], api_url=override["api_url"],
                folder_path=override.get("folder_path", ""),
                ssh_user=override.get("ssh_user"), ssh_key_path=override.get("ssh_key_path"),
                ssh_password=override.get("ssh_password"), ssh_port=int(override.get("ssh_port", 22)),
                winrm_user=override.get("winrm_user"), winrm_password=override.get("winrm_password"),
                winrm_port=int(override.get("winrm_port", 5985)),
            )
        return probe_device(
            device_id=device_id, name=name, ip=ip,
            folder_id=folder.id, connected=connected, override=override,
        )

    def _worker() -> None:
        nonlocal pending
        while not done.is_set():
            try:
                device_id, name, ip, connected, override = work_q.get(timeout=0.3)
            except queue.Empty:
                continue
            try:
                device_info = _probe(device_id, name, ip, connected, override)
                # Record the probed device FIRST. Hub expansion below can raise (a hub returning
                # non-JSON, or a device-config entry missing deviceID) — and that must NOT drop
                # this already-probed, reachable device from the results.
                with result_lock:
                    result.append(device_info)
                if on_device_found:
                    on_device_found(device_info)
                # ── Hub expansion: reachable hubs reveal devices they know about ──
                if device_info.api_key:
                    with known_lock:
                        snapshot = set(known_ids)
                    if device_info.api_reachable and device_info.api_url:
                        hub_devices = _query_hub_devices(device_info, folder.id, snapshot, devices_config or [])
                    elif device_info.ssh_reachable or device_info.winrm_reachable:
                        hub_devices = _query_hub_devices_via_remote(device_info, folder.id, snapshot, devices_config or [])
                    else:
                        hub_devices = []
                    for hdev_id, hdev_name, hdev_ip, hdev_override in hub_devices:
                        # Prefer a REAL name the LOCAL node already has for this device: the user may
                        # have named it locally even though only the hub shares the folder with it,
                        # and the hub's own name is often empty for an offline/introducer-added peer
                        # (which otherwise shows as a bare device-id). `!= hdev_id[:7]` skips the
                        # short-id DEFAULT that DeviceConfig.name falls back to when truly unnamed.
                        _lcfg = local_config_devices.get(hdev_id)
                        if _lcfg and _lcfg.name and _lcfg.name != hdev_id[:7]:
                            hdev_name = _lcfg.name
                        logger.debug("Hub %s revealed new device %s (%s)", name, hdev_name, hdev_id[:7])
                        _enqueue(hdev_id, hdev_name, hdev_ip, False, hdev_override)
            except Exception as e:
                logger.debug("Discovery worker error for %s: %s", name, e)
            finally:
                work_q.task_done()
                with pending_lock:
                    pending -= 1
                    if pending == 0:
                        done.set()

    # Seed with what the local Syncthing knows about this folder.
    for entry in folder.devices:
        # Defensive: a malformed device entry (bare string / missing deviceID) must not
        # abort the whole discovery — skip it like the local_info / hub paths already do.
        if not isinstance(entry, dict) or not entry.get("deviceID"):
            continue
        dev_id = entry["deviceID"]
        if dev_id == my_id:
            continue
        cfg = local_config_devices.get(dev_id)
        name = (cfg.name if cfg else "") or dev_id[:7]   # empty config name → short id, never blank

        conn = connections.get(dev_id)
        stat = stats.get(dev_id)
        connected = bool(conn and conn.connected and conn.ip)
        # Prefer an IPv4 across connection + last-known + every discovered address
        # (SSH over a link-local IPv6 like fe80::… is unusable). Discovery often holds
        # the real LAN IPv4 even when the live connection is over IPv6.
        # Include the device's CONFIGURED addresses too (cfg.addresses): a user who pinned a
        # static LAN IPv4 there must have it preferred even when the LIVE connection happens to
        # be over a (SSH-unusable) IPv6. Without this, the local path fell back to IPv6 while the
        # hub and parse paths (which DO consult cfg) picked the IPv4 — keep all three consistent.
        cfg_ips = [e for addr in (cfg.addresses if cfg else [])
                   if (e := _ip_from_syncthing_addr(addr))]
        disc_ips = [e for addr in discovery.get(dev_id, [])
                    if (e := _ip_from_syncthing_addr(addr))]
        ip: Optional[str] = _prefer_ipv4(
            conn.ip if (conn and conn.connected) else None,
            stat.last_ip if stat else None,
            *cfg_ips, *disc_ips,
        )
        if ip and not _is_ipv4(ip):  # still only IPv6 → last resort: resolve hostname
            ip = _resolve_ipv4_hostname(name) or ip

        override = _find_override(dev_id, name, devices_config or [])
        if override and override.get("ssh_host"):
            ip = override["ssh_host"]

        _enqueue(dev_id, name, ip, connected, override)

    with pending_lock:
        nothing_to_do = pending == 0
    if nothing_to_do:
        return result

    workers = [threading.Thread(target=_worker, daemon=True) for _ in range(DISCOVERY_WORKERS)]
    for t in workers:
        t.start()
    done.wait()
    return result


def _query_hub_devices(
    hub: DeviceInfo,
    folder_id: str,
    known_ids: set[str],
    devices_config: list[dict],
) -> list[tuple[str, str, Optional[str], Optional[dict]]]:
    """
    Query a reachable hub's Syncthing API for devices sharing folder_id
    that we haven't discovered yet.  Returns list of (device_id, name, ip, override).
    """
    try:
        hub_client = SyncthingClient(hub.api_url, hub.api_key, verify_ssl=False)
        hub_folder = hub_client.get_folder(folder_id)
        if hub_folder is None:
            return []

        hub_cfg_devices = {d.device_id: d for d in hub_client.get_config_devices()}
        hub_connections = hub_client.get_connected_devices()
        try:
            hub_stats = hub_client.get_device_stats()
        except SyncthingError:
            hub_stats = {}
        hub_discovery = hub_client.get_discovery()

        new_devices = []
        for entry in hub_folder.devices:
            # Defensive: a malformed entry here raises KeyError, which escapes the
            # `except SyncthingError` below and silently drops this hub's entire
            # downstream. Skip it instead (matches _parse_hub_devices' .get() style).
            if not isinstance(entry, dict) or not entry.get("deviceID"):
                continue
            dev_id = entry["deviceID"]
            if dev_id in known_ids:
                continue

            cfg = hub_cfg_devices.get(dev_id)
            name = (cfg.name if cfg else "") or dev_id[:7]   # empty config name → short id, never blank

            # Best IP: current connection to hub > hub's last-known > config address,
            # preferring IPv4 across all of them (SSH over IPv6 on a LAN is flaky).
            conn = hub_connections.get(dev_id)
            stat = hub_stats.get(dev_id)
            cfg_ips = [e for addr in (cfg.addresses if cfg else [])
                       if (e := _ip_from_syncthing_addr(addr))]
            disc_ips = [e for addr in hub_discovery.get(dev_id, [])
                        if (e := _ip_from_syncthing_addr(addr))]
            ip: Optional[str] = _prefer_ipv4(
                conn.ip if (conn and conn.connected) else None,
                stat.last_ip if stat else None,
                *cfg_ips, *disc_ips,
            )
            if ip and not _is_ipv4(ip):
                ip = _resolve_ipv4_hostname(name) or ip

            override = _find_override(dev_id, name, devices_config)
            if override and override.get("ssh_host"):
                ip = override["ssh_host"]

            new_devices.append((dev_id, name, ip, override))

        return new_devices
    except SyncthingError as e:
        logger.debug("Hub expansion for %s failed: %s", hub.name, e)
        return []


def _api_port_from_url(api_url: Optional[str]) -> int:
    """Extract Syncthing API port from a URL string, defaults to 8384."""
    if api_url:
        host_part = api_url.split("//")[-1] if "//" in api_url else api_url
        host_part = host_part.split("/")[0]  # strip path component
        # $ anchor avoids matching colons inside IPv6 address literals
        m = re.search(r":(\d+)$", host_part)
        if m:
            return int(m.group(1))
    return 8384


def _parse_hub_devices(
    folder_data: dict,
    connections_raw: dict,
    hub_cfg_raw,
    stats_raw,
    known_ids: set,
    devices_config: list,
) -> list:
    """Parse raw Syncthing API dicts into new-device tuples."""
    # PowerShell ConvertTo-Json may unwrap single-element arrays into plain objects.
    # Normalise both list and dict responses defensively.
    if isinstance(hub_cfg_raw, list):
        hub_cfg = {d["deviceID"]: d for d in hub_cfg_raw if isinstance(d, dict) and "deviceID" in d}
    elif isinstance(hub_cfg_raw, dict) and "deviceID" in hub_cfg_raw:
        hub_cfg = {hub_cfg_raw["deviceID"]: hub_cfg_raw}
    else:
        hub_cfg = {}

    connections = connections_raw.get("connections", {}) if isinstance(connections_raw, dict) else {}
    stats = stats_raw if isinstance(stats_raw, dict) else {}

    # folder_data may be None/non-dict (folder paused or absent on the hub, or a malformed
    # remote response) — this runs OUTSIDE the caller's try/except, so an unguarded .get() here
    # would raise AttributeError and silently drop the WHOLE hub's peer expansion. Guard it so a
    # bad response loses at most the one malformed entry, never the entire hub.
    raw_folder_devs = folder_data.get("devices", []) if isinstance(folder_data, dict) else []
    if isinstance(raw_folder_devs, dict):
        raw_folder_devs = [raw_folder_devs]

    new_devices = []
    for entry in raw_folder_devs:
        if not isinstance(entry, dict):
            continue
        dev_id = entry.get("deviceID")
        if not dev_id or dev_id in known_ids:
            continue
        cfg  = hub_cfg.get(dev_id, {})
        if not isinstance(cfg, dict):
            cfg = {}
        name = cfg.get("name") or dev_id[:7]   # empty config name → short id, never blank

        # Guard conn/cfg like stat already is: a malformed remote response (a non-dict entry
        # from a hostile hub or a ConvertTo-Json edge) must not raise here — this runs OUTSIDE
        # the caller's try/except, so an AttributeError would silently drop the WHOLE hub's peers.
        conn = connections.get(dev_id, {})
        if not isinstance(conn, dict):
            conn = {}
        stat = stats.get(dev_id, {})
        conn_ip = (_ip_from_syncthing_addr(conn["address"])
                   if conn.get("connected") and conn.get("address") else None)
        last_ip = (_ip_from_syncthing_addr(stat["lastAddress"])
                   if isinstance(stat, dict) and stat.get("lastAddress") else None)
        cfg_ips = [e for addr in cfg.get("addresses", [])
                   if (e := _ip_from_syncthing_addr(addr))]
        # Prefer IPv4 across all sources (SSH over IPv6 on a LAN is flaky).
        ip: Optional[str] = _prefer_ipv4(conn_ip, last_ip, *cfg_ips)
        if ip and not _is_ipv4(ip):
            ip = _resolve_ipv4_hostname(name) or ip

        override = _find_override(dev_id, name, devices_config)
        if override and override.get("ssh_host"):
            ip = override["ssh_host"]

        new_devices.append((dev_id, name, ip, override))

    return new_devices


def _query_hub_devices_via_remote(
    hub: DeviceInfo,
    folder_id: str,
    known_ids: set,
    devices_config: list,
) -> list:
    """
    Query a hub's Syncthing API via SSH or WinRM to find new devices sharing folder_id.
    Used when the hub's API is not directly reachable from this machine.
    Returns list of (device_id, name, ip, override).
    Opens a single remote connection and makes all API calls within it.
    """
    api_port = _api_port_from_url(hub.api_url)
    api_key  = hub.api_key or ""
    if not api_key or not hub.ip:
        return []
    try:
        if hub.ssh_reachable:
            ssh = SSHClient(
                host=hub.ip, user=hub.ssh_user, key_path=hub.ssh_key_path,
                port=hub.ssh_port, password=hub.ssh_password,
            )
            with ssh:
                folder_data     = ssh.syncthing_api_get(rest_folder_path(folder_id), api_key, api_port)
                connections_raw = ssh.syncthing_api_get("/rest/system/connections", api_key, api_port)
                hub_cfg_raw     = ssh.syncthing_api_get("/rest/config/devices", api_key, api_port)
                try:
                    stats_raw = ssh.syncthing_api_get("/rest/stats/device", api_key, api_port)
                except SSHError:
                    stats_raw = {}
        elif hub.winrm_reachable:
            winrm = WinRMClient(
                host=hub.ip, user=hub.winrm_user, password=hub.winrm_password, port=hub.winrm_port
            )
            with winrm:
                folder_data     = winrm.syncthing_api_get(rest_folder_path(folder_id), api_key, api_port)
                connections_raw = winrm.syncthing_api_get("/rest/system/connections", api_key, api_port)
                hub_cfg_raw     = winrm.syncthing_api_get("/rest/config/devices", api_key, api_port)
                try:
                    stats_raw = winrm.syncthing_api_get("/rest/stats/device", api_key, api_port)
                except WinRMError:
                    stats_raw = {}
        else:
            return []
    except Exception as e:
        logger.debug("Remote hub expansion for %s failed: %s", hub.name, e)
        return []

    return _parse_hub_devices(folder_data, connections_raw, hub_cfg_raw, stats_raw, known_ids, devices_config)


def _is_ipv4(ip: Optional[str]) -> bool:
    if not ip or re.match(r"^\d{1,3}(\.\d{1,3}){3}$", ip) is None:
        return False
    return all(0 <= int(o) <= 255 for o in ip.split("."))   # reject 256-999 octets


_HOSTNAME_IP_CACHE: dict[str, Optional[str]] = {}


def _resolve_ipv4_hostname(name: Optional[str]) -> Optional[str]:
    """Best-effort: resolve a device hostname to a LAN IPv4 (tries the bare name and
    <name>.local for mDNS). Used only when Syncthing knows a device solely over IPv6 —
    SSH over IPv6 on a LAN is unreliable. Bounded by a short timeout so a non-resolving
    name can't stall discovery; results are cached. A wrong guess simply fails the
    later SSH/API probe, so it's safe to attempt."""
    if not name:
        return None
    if name in _HOSTNAME_IP_CACHE:
        return _HOSTNAME_IP_CACHE[name]
    result: list[Optional[str]] = [None]

    def _do() -> None:
        for cand in (name, f"{name}.local"):
            try:
                infos = socket.getaddrinfo(cand, None, socket.AF_INET)
            except (socket.gaierror, OSError):
                continue
            if infos:
                result[0] = infos[0][4][0]
                return

    t = threading.Thread(target=_do, daemon=True)
    t.start()
    t.join(timeout=1.5)
    _HOSTNAME_IP_CACHE[name] = result[0]
    return result[0]


def _prefer_ipv4(*candidates: Optional[str]) -> Optional[str]:
    """From candidate IPs (in priority order), return the first IPv4. SSH over IPv6
    on a LAN is unreliable — link-local (fe80::) needs a zone id and many hosts don't
    accept SSH over v6 — so a known IPv4 is strongly preferred. Falls back to the
    first usable IPv6 (skipping link-local), else the first candidate, else None."""
    cands = [c for c in candidates if c]
    ipv4 = next((c for c in cands if _is_ipv4(c)), None)
    if ipv4:
        return ipv4
    usable = [c for c in cands if not c.lower().startswith("fe80")]
    return (usable or cands or [None])[0]


def _ip_from_syncthing_addr(addr: str) -> Optional[str]:
    """Extract the bare IP from a Syncthing address like 'tcp://192.168.1.5:22000'. Thin wrapper
    over models.parse_ip_from_address (the single source of truth shared with ConnectionInfo.ip /
    DeviceStats.last_ip), kept under this name because page_execute imports it from discovery."""
    return parse_ip_from_address(addr)


def _tcp_open(host: Optional[str], port: int, timeout: float = TCP_PRECHECK_TIMEOUT) -> bool:
    """Quick TCP connect check. Lets us skip the full (15-30s) SSH/WinRM/API handshake
    when the port is closed/filtered — an offline host then fails in ~timeout, not ~15s."""
    if not host:
        return False
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except (OSError, ValueError, OverflowError):
        return False


def probe_device(
    device_id: str,
    name: str,
    ip: Optional[str],
    folder_id: str,
    connected: bool = False,
    override: Optional[dict] = None,
    port: int = 22,
) -> DeviceInfo:
    """Probe a single remote device. Public so the GUI/CLI can retry with new credentials."""
    if not ip:
        return DeviceInfo(
            device_id=device_id, name=name, ip=None,
            api_url=None, api_key=None, folder_path=None,
            ssh_reachable=False, api_reachable=False, is_local=False,
            ssh_error="No IP address known",
        )

    ssh_user = override.get("ssh_user") if override else None
    ssh_key = override.get("ssh_key_path") if override else None
    ssh_password = override.get("ssh_password") if override else None
    ssh_port = int(override.get("ssh_port", port)) if override else port
    winrm_user = override.get("winrm_user") if override else None
    winrm_password = override.get("winrm_password") if override else None
    winrm_port = int(override.get("winrm_port", 5985)) if override else 5985
    config_path_override = override.get("syncthing_config_path") if override else None

    # ── Try SSH (Linux/Mac, and Windows with OpenSSH) ─────────────────────────
    ssh_error_msg: Optional[str] = None
    ssh_ok = False
    # Set True only when a login was attempted and the credentials were REJECTED (vs a port
    # closed / host down / config-not-found). Mirrors probe_device_manual so the GUI's "creds
    # rejected" cues fire for stored creds gone bad too — without condemning offline targets.
    ssh_creds_rejected = False
    try:
        # Fast TCP precheck: skip the full SSH timeout when the port is closed/filtered.
        if not _tcp_open(ip, ssh_port):
            raise SSHError(_T("puerto SSH {} cerrado o inalcanzable").format(ssh_port))
        ssh = SSHClient(host=ip, user=ssh_user, key_path=ssh_key,
                        port=ssh_port, password=ssh_password)
        ssh.connect()
        try:
            if not ssh.is_windows():
                # Linux / macOS path
                config_path = config_path_override or ssh.detect_syncthing_config_path()
                if not config_path:
                    return DeviceInfo(
                        device_id=device_id, name=name, ip=ip,
                        api_url=None, api_key=None, folder_path=None,
                        ssh_reachable=True, api_reachable=False, is_local=False,
                        ssh_user=ssh_user, ssh_key_path=ssh_key, ssh_password=ssh_password,
                        ssh_port=ssh_port,
                        ssh_error="Could not find Syncthing config.xml on remote device",
                        os_type="linux", os_detected=True,
                    )
                xml_content = ssh.read_file(config_path)
                api_key, api_port, folder_path, peers, frole, fintro = _parse_remote_config(xml_content, folder_id)
                # Read the CPU arch over the already-open SSH session (one cheap `uname -m`) so the
                # agent flow can auto-pick this device's Linux template instead of asking.
                _arch = ssh.arch_kind()
                # Only ping the LAN API if its port is actually open — most setups bind
                # it to localhost, so a quick TCP precheck avoids a ~10s http+https wait
                # (we reach the API via the SSH tunnel anyway).
                if _tcp_open(ip, api_port):
                    api_reachable, api_url, api_error = _probe_api(ip, api_key, api_port)
                else:
                    api_reachable = False
                    api_url = f"http://{ip}:{api_port}"
                    api_error = _T("API no expuesta en la LAN (se usará vía SSH)")
                return DeviceInfo(
                    device_id=device_id, name=name, ip=ip,
                    api_url=api_url, api_key=api_key, folder_path=folder_path,
                    ssh_reachable=True, api_reachable=api_reachable, is_local=False,
                    ssh_user=ssh_user, ssh_key_path=ssh_key, ssh_password=ssh_password,
                    ssh_port=ssh_port, api_error=api_error,
                    os_type="linux", os_detected=True, arch=_arch, arch_detected=bool(_arch),
                    folder_peers=peers, folder_role=frole,
                    folder_introducers=fintro,
                )
            else:
                # Windows detected via SSH — prefer WinRM if available
                ssh_ok = True
                logger.debug("SSH detected Windows on %s — trying WinRM", ip)
        finally:
            ssh.close()
    except SSHError as e:
        ssh_error_msg = str(e)
        if "Authentication failed" in ssh_error_msg:
            ssh_creds_rejected = True
        logger.debug("SSH failed for %s: %s", ip, e)

    # ── Try WinRM (Windows without OpenSSH, or Windows detected above) ────────
    if winrm_user and winrm_password:
        try:
            if not _tcp_open(ip, winrm_port):
                raise WinRMError(_T("puerto WinRM {} cerrado o inalcanzable").format(winrm_port))
            winrm_client = WinRMClient(
                host=ip, user=winrm_user, password=winrm_password, port=winrm_port
            )
            winrm_client.connect()
            config_path = config_path_override or winrm_client.detect_syncthing_config_path()
            if not config_path:
                winrm_client.close()
                return DeviceInfo(
                    device_id=device_id, name=name, ip=ip,
                    api_url=None, api_key=None, folder_path=None,
                    ssh_reachable=ssh_ok, api_reachable=False, is_local=False,
                    winrm_reachable=True, winrm_user=winrm_user,
                    winrm_password=winrm_password, winrm_port=winrm_port,
                    ssh_error="Could not find Syncthing config.xml via WinRM",
                    os_type="windows", os_detected=True,
                )
            xml_content = winrm_client.read_file(config_path)
            api_key, api_port, folder_path, peers, frole, fintro = _parse_remote_config(xml_content, folder_id)
            winrm_client.close()
            if _tcp_open(ip, api_port):
                api_reachable, api_url, api_error = _probe_api(ip, api_key, api_port)
            else:
                api_reachable = False
                api_url = f"http://{ip}:{api_port}"
                api_error = _T("API no expuesta en la LAN (se usará vía WinRM)")
            return DeviceInfo(
                device_id=device_id, name=name, ip=ip,
                api_url=api_url, api_key=api_key, folder_path=folder_path,
                ssh_reachable=ssh_ok, api_reachable=api_reachable, is_local=False,
                winrm_reachable=True, winrm_user=winrm_user,
                winrm_password=winrm_password, winrm_port=winrm_port,
                api_error=api_error,
                os_type="windows", os_detected=True, folder_peers=peers, folder_role=frole,
                folder_introducers=fintro,
            )
        except Exception as e:
            winrm_error = str(e)
            _wm = winrm_error.lower()
            winrm_rejected = any(k in _wm for k in ("401", "unauthorized", "authentication",
                                                    "logon", "access is denied", "credential",
                                                    "rejected", "forbidden"))
            logger.debug("WinRM failed for %s: %s", ip, e)
            return DeviceInfo(
                device_id=device_id, name=name, ip=ip,
                api_url=None, api_key=None, folder_path=None,
                ssh_reachable=ssh_ok, api_reachable=False, is_local=False,
                winrm_user=winrm_user, winrm_password=winrm_password, winrm_port=winrm_port,
                ssh_error=f"SSH: {ssh_error_msg or 'no creds'}  |  WinRM: {winrm_error}",
                ssh_creds_rejected=(ssh_creds_rejected or winrm_rejected),
                os_type="windows", os_detected=True,
            )

    # No remote access succeeded
    return DeviceInfo(
        device_id=device_id, name=name, ip=ip,
        api_url=None, api_key=None, folder_path=None,
        ssh_reachable=False, api_reachable=False, is_local=False,
        ssh_user=ssh_user, ssh_key_path=ssh_key, ssh_password=ssh_password,
        ssh_port=ssh_port,
        # Be honest: if ssh_ok the SSH login SUCCEEDED (it detected Windows) — the gap is that we
        # don't yet read the Windows config over SSH, so without WinRM (or a LAN-exposed API) the
        # device can't be managed. Don't mislabel that as "SSH failed".
        ssh_error=(
            _T("Windows alcanzado por SSH, pero no gestionable por este canal todavía: "
               "configura WinRM, expón la API en la LAN, o usa el agente.")
            if ssh_ok else
            (ssh_error_msg or _T("Sin acceso remoto: faltan credenciales SSH/WinRM válidas."))
        ),
        # ssh_ok=True means SSH actually logged in (creds are fine), so never flag rejected there.
        ssh_creds_rejected=(ssh_creds_rejected and not ssh_ok),
        os_type="windows" if ssh_ok else None,  # ssh_ok=True means SSH reached the device and it reported Windows
        os_detected=ssh_ok,
    )


def _probe_api(
    ip: str, api_key: Optional[str], api_port: int
) -> tuple[bool, Optional[str], Optional[str]]:
    """Try http then https; return (reachable, url, error)."""
    fallback = f"http://{ip}:{api_port}"
    if not api_key:
        return False, fallback, "No API key found in config.xml"
    for scheme in ("http", "https"):
        url = f"{scheme}://{ip}:{api_port}"
        if SyncthingClient(url, api_key, verify_ssl=False).ping():
            return True, url, None
    return False, fallback, f"API at {ip}:{api_port} not reachable (tried http and https)"


def _ssh_port_open(host: str, port: int, timeout: float = 3.0) -> bool:
    """Quick TCP check: is the SSH port accepting connections right now? Used to decide
    whether it's worth attempting a (slower) SSH handshake to verify credentials — an
    offline host fails this in ~timeout seconds instead of the full SSH connect timeout."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def probe_device_manual(
    device_id: str,
    name: str,
    ip: str,
    folder_id: str,
    api_key: str,
    api_url: str,
    folder_path: str,
    ssh_user: Optional[str] = None,
    ssh_key_path: Optional[str] = None,
    ssh_password: Optional[str] = None,
    ssh_port: int = 22,
    winrm_user: Optional[str] = None,
    winrm_password: Optional[str] = None,
    winrm_port: int = 5985,
) -> DeviceInfo:
    """
    Build a DeviceInfo from manually supplied credentials, verifying the API is reachable.
    Used when the user enters credentials by hand in the GUI/CLI.
    """
    client = SyncthingClient(api_url, api_key, verify_ssl=False)
    api_reachable = client.ping()
    has_winrm = bool(winrm_user and winrm_password)
    os_type = "windows" if has_winrm else (client.get_os() if api_reachable else None)
    # CPU arch for agent template auto-pick: the API's /rest/system/version is the cheapest
    # source; fall back to the SSH probe's `uname -m` below when the API isn't reachable.
    device_arch = client.get_arch() if api_reachable else None
    # If the OS is still unknown and only SSH creds were given, best-effort detect Windows
    # over SSH (a Windows host with OpenSSH). Without this, os_type=None + ssh_reachable would
    # route the rename through the POSIX SSH path (mv/rm -rf) against a cmd.exe shell. We only
    # SET os_type here (never clear ssh_reachable) — purely additive, fully guarded.
    has_ssh_creds = bool(ssh_user or ssh_key_path or ssh_password)
    ssh_auth_failed = False
    ssh_err_msg: Optional[str] = None
    # Verify the SSH credentials when the host is actually UP. A device that ANSWERS on the SSH
    # port but REJECTS the credentials is "credenciales fallidas" — NOT a legit offline-with-
    # creds passive device (whose host is simply down). We only attempt the bounded handshake
    # when a quick port check says the host is reachable, so an OFFLINE device doesn't make the
    # probe wait the full SSH connect timeout (it stays an optimistic passive target as before).
    if has_ssh_creds and ip:
        from .ssh_ops import SSHClient, SSHError
        if _ssh_port_open(ip, ssh_port):
            try:
                _probe = SSHClient(host=ip, user=ssh_user, key_path=ssh_key_path,
                                   port=ssh_port, password=ssh_password)
                with _probe:
                    if os_type is None:
                        os_type = _probe.os_kind()
                    if device_arch is None:
                        device_arch = _probe.arch_kind()
            except SSHError as e:
                # Host up + auth rejected → flag the bad creds (vs a mere connection blip).
                if "Authentication failed" in str(e):
                    ssh_auth_failed = True
                    ssh_err_msg = _T("credenciales SSH rechazadas (autenticación fallida)")
            except Exception:
                pass   # other connect issue → treat as offline (unchanged passive behaviour)
    # Verify WinRM credentials the same way R20 did for SSH: a host that ANSWERS on the WinRM port
    # but fails the handshake means the creds/config are wrong — surface it instead of the old
    # "trusted just because creds were typed", which showed bad WinRM creds as a healthy device
    # that then only failed at execution. Port closed (host down) stays optimistic so an offline
    # passive target doesn't wait the full timeout.
    winrm_auth_failed = False
    winrm_err_msg: Optional[str] = None
    if has_winrm and ip:
        from .winrm_ops import WinRMClient
        if _tcp_open(ip, winrm_port):
            try:
                _wprobe = WinRMClient(host=ip, user=winrm_user,
                                      password=winrm_password, port=winrm_port)
                _wprobe.connect()
                _wprobe.close()
            except Exception as e:
                # Only a CLEAR auth rejection means bad creds (mirrors the SSH path's
                # "Authentication failed" check). A transient blip/timeout must NOT flip a
                # healthy device to "bad credentials" — leave it optimistic (passive target).
                _em = str(e).lower()
                if any(k in _em for k in ("401", "unauthorized", "authentication", "logon",
                                          "access is denied", "credential", "rejected",
                                          "forbidden")):
                    winrm_auth_failed = True
                    winrm_err_msg = _T("credenciales WinRM rechazadas ({})").format(e)
    # If the API answered, read this device's real adjacency + role for the folder.
    peers: list[str] = []
    frole: Optional[str] = None
    fintro: dict = {}
    if api_reachable:
        try:
            f = client.get_folder(folder_id)
            if f:
                for d in f.devices:
                    if isinstance(d, dict) and d.get("deviceID"):
                        peers.append(d["deviceID"])
                        if d.get("introducedBy"):
                            fintro[d["deviceID"]] = d["introducedBy"]
                frole = f.raw.get("type")
        except SyncthingError:
            pass
    return DeviceInfo(
        device_id=device_id, name=name, ip=ip,
        api_url=api_url, api_key=api_key, folder_path=folder_path or None,
        ssh_reachable=(has_ssh_creds and not ssh_auth_failed),
        api_reachable=api_reachable, is_local=False,
        ssh_user=ssh_user, ssh_key_path=ssh_key_path, ssh_password=ssh_password,
        ssh_port=ssh_port, ssh_error=ssh_err_msg or winrm_err_msg,
        ssh_creds_rejected=(ssh_auth_failed or winrm_auth_failed),
        winrm_reachable=(has_winrm and not winrm_auth_failed),
        winrm_user=winrm_user, winrm_password=winrm_password, winrm_port=winrm_port,
        api_error=None if api_reachable else f"API at {api_url} not reachable",
        os_type=os_type, os_detected=bool(os_type),
        arch=device_arch, arch_detected=bool(device_arch),
        folder_peers=peers, folder_role=frole,
        folder_introducers=fintro,
    )


def _parse_remote_config(
    xml_content: str, folder_id: str
) -> tuple[Optional[str], int, Optional[str], list[str], Optional[str], dict]:
    """Parse a remote config.xml for the folder of interest. Returns
    (api_key, api_port, folder_path, peer_device_ids, folder_type, introducers).
    `introducers` maps peer_id -> introducedBy (empty string if a direct share), so the
    topology can route a member to its introducer instead of drawing a phantom link."""
    # Defend against entity-expansion DoS (billion-laughs) from a malicious peer's config.xml.
    # Syncthing's config.xml never carries a DTD/DOCTYPE, so reject any that does before parsing.
    if re.search(r"<!\s*(DOCTYPE|ENTITY)", xml_content or "", re.I):
        raise SSHError(_T("config.xml remoto con DTD/ENTITY rechazado (posible expansión maliciosa)"))
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        raise SSHError(f"Failed to parse config.xml: {e}") from e

    api_key = None
    api_port = 8384
    folder_path = None
    peers: list[str] = []
    folder_type: Optional[str] = None
    introducers: dict = {}

    gui = root.find("gui")
    if gui is not None:
        key_el = gui.find("apikey")
        if key_el is not None and key_el.text:
            api_key = key_el.text.strip()
        addr_el = gui.find("address")
        if addr_el is not None and addr_el.text:
            addr = addr_el.text.strip()
            # Parse the port without tripping on IPv6. "[::1]:8384" → 8384; "127.0.0.1:8384"
            # → 8384; a bracketless IPv6 literal ("fe80::1234", many colons, no port) must
            # NOT have its last hextet mistaken for a port → keep the default.
            port_str = None
            if addr.startswith("[") and "]:" in addr:
                port_str = addr.rsplit("]:", 1)[1]
            elif addr.count(":") == 1:
                port_str = addr.rsplit(":", 1)[1]
            if port_str is not None:
                try:
                    api_port = int(port_str)
                except ValueError:
                    pass

    for folder_el in root.findall("folder"):
        if folder_el.get("id") == folder_id:
            path_attr = folder_el.get("path", "")
            if path_attr:
                folder_path = path_attr
            folder_type = folder_el.get("type") or None
            for dev_el in folder_el.findall("device"):
                did = dev_el.get("id")
                if did:
                    peers.append(did)
                    intro = dev_el.get("introducedBy") or ""
                    if intro:
                        introducers[did] = intro
            break

    return api_key, api_port, folder_path, peers, folder_type, introducers


def _get_local_hostname(client: SyncthingClient) -> str:
    try:
        my_id = client.get_my_device_id()
        for d in client.get_config_devices():
            if d.device_id == my_id:
                return d.name
    except SyncthingError:
        pass
    try:
        return socket.gethostname()
    except Exception:
        return "local"


def _find_override(device_id: str, name: str, devices_config: list[dict]) -> Optional[dict]:
    global_default = None
    for entry in devices_config:
        if entry.get("device_id") == device_id:
            return entry
        if not entry.get("device_id") and not entry.get("name"):
            global_default = entry
    return global_default


def _find_syncthing_config_paths_dynamic() -> list[str]:
    """Discover config.xml paths from the running Syncthing process or system services."""
    found: list[str] = []

    def _add(path: str, source: str) -> None:
        if path and path not in found:
            found.append(path)
            logger.debug("Found Syncthing config candidate via %s: %s", source, path)

    def _xdg_paths_for_home(home_dir: str) -> list[str]:
        return [
            os.path.join(home_dir, ".local", "state", "syncthing", "config.xml"),
            os.path.join(home_dir, ".local", "share", "syncthing", "config.xml"),
            os.path.join(home_dir, ".config", "syncthing", "config.xml"),
        ]

    # ── /proc: read running process cmdline + derive user home ───────────────
    if os.path.exists("/proc"):
        for cmdline_file in glob.glob("/proc/*/cmdline"):
            try:
                pid = cmdline_file.split("/")[2]
                with open(cmdline_file, "rb") as f:
                    raw = f.read()
                parts = raw.split(b"\x00")
                if not any(b"syncthing" in p.lower() for p in parts[:3]):
                    continue

                # Strategy A: explicit --home / -home flag
                for i, part in enumerate(parts):
                    decoded = part.decode("utf-8", errors="replace")
                    if decoded in ("-home", "--home") and i + 1 < len(parts):
                        home_dir = parts[i + 1].decode("utf-8", errors="replace")
                        _add(os.path.join(home_dir, "config.xml"), "/proc --home")
                    elif decoded.startswith(("--home=", "-home=")):
                        home_dir = decoded.split("=", 1)[1]
                        _add(os.path.join(home_dir, "config.xml"), "/proc --home=")

                # Strategy B: look up the UID of the process → home dir → XDG paths
                # Handles both user services and system services (e.g. syncthing user)
                try:
                    with open(f"/proc/{pid}/status") as sf:
                        for line in sf:
                            if line.startswith("Uid:"):
                                uid = int(line.split()[2])  # effective UID (index 2; index 1 is real UID)
                                try:
                                    if _pwd is not None:
                                        pw = _pwd.getpwuid(uid)
                                        for p in _xdg_paths_for_home(pw.pw_dir):
                                            _add(p, f"/proc UID={uid} ({pw.pw_name})")
                                except KeyError:
                                    pass
                                break
                except Exception:
                    pass
            except Exception:
                pass

    # ── syncthing --paths (if syncthing binary is on PATH) ────────────────────
    try:
        r = subprocess.run(
            ["syncthing", "--paths"],
            capture_output=True, text=True, timeout=5,
        )
        for line in (r.stdout + r.stderr).splitlines():
            if "Config file" in line or "Configuration file" in line:
                cfg = line.split(":", 1)[-1].strip()
                _add(cfg, "syncthing --paths")
    except Exception:
        pass

    # ── systemd: user and system service ─────────────────────────────────────
    user = os.environ.get("USER", "")
    for svc in filter(None, ["syncthing", f"syncthing@{user}" if user else ""]):
        for scope in [["systemctl", "--user"], ["systemctl"]]:
            try:
                r = subprocess.run(
                    scope + ["show", svc, "--property=ExecStart", "--no-pager"],
                    capture_output=True, text=True, timeout=3,
                )
                if "syncthing" not in r.stdout:
                    continue
                # Look for explicit --home flag in ExecStart
                for token in r.stdout.split():
                    if token.startswith(("--home=", "-home=")):
                        home_dir = token.split("=", 1)[1].rstrip(";")
                        _add(os.path.join(home_dir, "config.xml"), "systemd ExecStart")
                # Also look for User= property to derive home dir
                r2 = subprocess.run(
                    scope + ["show", svc, "--property=User", "--no-pager"],
                    capture_output=True, text=True, timeout=3,
                )
                for line in r2.stdout.splitlines():
                    if line.startswith("User=") and line.strip() != "User=":
                        svc_user = line.split("=", 1)[1].strip()
                        try:
                            pw = _pwd.getpwnam(svc_user)  # type: ignore[union-attr]
                            for p in _xdg_paths_for_home(pw.pw_dir):
                                _add(p, f"systemd User={svc_user}")
                        except KeyError:
                            pass
            except Exception:
                pass

    return found


def find_local_config_path() -> Optional[str]:
    """Return the path to the local Syncthing config.xml, or None if not found."""
    for path in _local_config_candidates():
        if path and os.path.exists(path):
            return path
    return None


def _local_config_candidates() -> list[str]:
    """Build ordered list of candidate config.xml paths for the local machine."""
    if platform.system() == "Windows":
        localappdata = os.environ.get("LOCALAPPDATA", "")
        appdata = os.environ.get("APPDATA", "")
        return [
            os.path.join(localappdata, "Syncthing", "config.xml"),
            os.path.join(appdata, "Syncthing", "config.xml"),
        ]

    home = os.path.expanduser("~")
    candidates = _find_syncthing_config_paths_dynamic()

    xdg_state  = os.environ.get("XDG_STATE_HOME",  os.path.join(home, ".local", "state"))
    xdg_data   = os.environ.get("XDG_DATA_HOME",   os.path.join(home, ".local", "share"))
    xdg_config = os.environ.get("XDG_CONFIG_HOME", os.path.join(home, ".config"))

    candidates += [
        os.path.join(xdg_state,  "syncthing", "config.xml"),
        os.path.join(xdg_data,   "syncthing", "config.xml"),
        os.path.join(xdg_config, "syncthing", "config.xml"),
        os.path.join(home, ".syncthing", "config.xml"),
        os.path.join(home, "Library", "Application Support", "Syncthing", "config.xml"),
        os.path.join(home, "snap", "syncthing", "current", ".local", "state", "syncthing", "config.xml"),
        os.path.join(home, "snap", "syncthing", "current", ".local", "share", "syncthing", "config.xml"),
        os.path.join(home, "snap", "syncthing", "current", ".config", "syncthing", "config.xml"),
        os.path.join(home, ".var", "app", "me.kozec.syncthingtray", "config", "syncthing", "config.xml"),
        "/var/lib/syncthing/.local/state/syncthing/config.xml",
        "/var/lib/syncthing/.local/share/syncthing/config.xml",
        "/var/lib/syncthing/.config/syncthing/config.xml",
        "/var/lib/syncthing/config.xml",
        "/home/syncthing/.local/state/syncthing/config.xml",
        "/home/syncthing/.local/share/syncthing/config.xml",
        "/home/syncthing/.config/syncthing/config.xml",
    ]

    # Note: we deliberately do NOT scan the Windows host's config via /mnt/c when
    # running in WSL. A WSL Syncthing is just Linux; the Windows instance is a
    # separate device managed from Windows. Cross-OS visibility is Syncthing's own
    # device discovery, not ours.
    return candidates


def _local_url_from_gui(address: str, tls: bool) -> str:
    """Build a loopback URL from a Syncthing <gui> address+tls. The bind address
    may be 0.0.0.0/a LAN IP, so we always connect via 127.0.0.1 keeping the port."""
    scheme = "https" if tls else "http"
    port = 8384
    a = (address or "").strip()
    if a:
        if a.startswith("["):  # IPv6 literal, e.g. [::]:8384
            idx = a.find("]:")
            tail = a[idx + 2:] if idx != -1 else ""
            if tail.isdigit():
                port = int(tail)
        elif ":" in a:
            p = a.rsplit(":", 1)[1]
            if p.isdigit():
                port = int(p)
    return f"{scheme}://127.0.0.1:{port}"


def _parse_gui_config(path: str) -> Optional[dict]:
    """Parse a config.xml <gui> block → {api_key, address, tls}, or None on error."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, PermissionError, OSError) as e:
        logger.debug("Could not read %s: %s", path, e)
        return None
    gui = root.find("gui")
    if gui is None:
        return None
    key_el = gui.find("apikey")
    api_key = key_el.text.strip() if (key_el is not None and key_el.text) else None
    addr_el = gui.find("address")
    address = addr_el.text.strip() if (addr_el is not None and addr_el.text) else ""
    tls = gui.get("tls", "false").strip().lower() == "true"
    return {"api_key": api_key, "address": address, "tls": tls}


def local_gui_config() -> Optional[dict]:
    """
    Locate the local Syncthing config.xml and return {api_key, url, path}.
    `url` is built from the config's address + tls so we target the exact scheme
    and port Syncthing uses (no http/https guessing). Returns None if not found.
    """
    seen: set[str] = set()
    for path in _local_config_candidates():
        if not path or path in seen:
            continue
        seen.add(path)
        if not os.path.exists(path):
            continue
        parsed = _parse_gui_config(path)
        if parsed and parsed.get("api_key"):
            logger.debug("Loaded GUI config from %s", path)
            return {
                "api_key": parsed["api_key"],
                "url": _local_url_from_gui(parsed["address"], parsed["tls"]),
                "path": path,
            }
    logger.debug("Local config.xml with API key not found (searched %d paths).", len(seen))
    return None


def read_local_api_key() -> Optional[str]:
    """Read Syncthing API key from local config.xml."""
    cfg = local_gui_config()
    return cfg["api_key"] if cfg else None


def detect_local_syncthing(url_override: Optional[str] = None,
                           key_override: Optional[str] = None) -> dict:
    """
    Diagnose the local Syncthing instance.

    Returns {status, url, api_key, config_path} where status is one of:
      - "running"               API answered (and key accepted)
      - "bad_auth"              API answered but rejected the key
      - "installed_not_running" config.xml exists but the API is unreachable
      - "not_found"             no config.xml and the API is unreachable

    Detection is purely local: in WSL it looks only at WSL's own Syncthing (a WSL
    instance is just Linux); it never reaches out to the Windows host.
    """
    from .syncthing import SyncthingClient

    gui = local_gui_config()
    api_key = key_override or (gui["api_key"] if gui else None)
    config_path = gui["path"] if gui else None
    url = url_override or (gui["url"] if gui else "https://127.0.0.1:8384")

    status = SyncthingClient(url, api_key or "", verify_ssl=False).ping_status()

    if status == "ok":
        st = "running"
    elif status == "auth":
        st = "bad_auth"
    elif config_path is not None:
        st = "installed_not_running"
    else:
        st = "not_found"
    return {"status": st, "url": url, "api_key": api_key, "config_path": config_path}


def _local_os_type() -> str:
    """OS of the locally-managed Syncthing. WSL counts as Linux; macOS → 'macos'."""
    _s = platform.system()
    return "windows" if _s == "Windows" else ("macos" if _s == "Darwin" else "linux")


def _local_arch() -> str:
    """CPU arch of THIS host, normalized to our template naming ('amd64'|'arm64'|'armv7'|<raw>)."""
    from .generate import normalize_arch
    return normalize_arch()
