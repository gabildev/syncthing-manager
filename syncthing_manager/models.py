from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


def parse_ip_from_address(addr: Optional[str]) -> Optional[str]:
    """Extract the bare IP/host from a Syncthing address ('tcp://192.168.1.5:22000',
    '[fe80::1]:22000', 'dynamic', ''). Strips the URL scheme and a trailing ':port', but NEVER
    the last hextet of a bracketless IPv6 literal — only a SINGLE colon is treated as a port
    (a bare IPv6 has several colons and cannot carry a port without brackets). Single source of
    truth for the three call sites (ConnectionInfo.ip, DeviceStats.last_ip,
    discovery._ip_from_syncthing_addr) so the parsing rule can't drift between them."""
    if not addr or addr == "dynamic":
        return None
    if addr.startswith("relay://"):
        return None   # a relay address is not a directly-reachable device IP (can't SSH/API it)
    for prefix in ("tcp://", "quic://", "tcp4://", "tcp6://", "quic4://", "quic6://"):
        if addr.startswith(prefix):
            addr = addr[len(prefix):]
            break
    if addr.startswith("["):
        end = addr.find("]")
        if end != -1:
            return addr[1:end]
    if addr.count(":") == 1:
        return addr.rsplit(":", 1)[0]
    return addr or None


@dataclass
class FolderConfig:
    id: str
    label: str
    path: str
    devices: list[dict]
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "FolderConfig":
        return cls(
            id=d["id"],
            label=d.get("label", d["id"]),
            path=d.get("path", ""),
            devices=d.get("devices", []),
            raw=d,
        )


@dataclass
class ConnectionInfo:
    device_id: str
    connected: bool
    address: str
    client_version: str

    @property
    def ip(self) -> Optional[str]:
        return parse_ip_from_address(self.address)


@dataclass
class DeviceStats:
    device_id: str
    last_seen: Optional[str]
    last_address: Optional[str]

    @property
    def last_ip(self) -> Optional[str]:
        return parse_ip_from_address(self.last_address)


@dataclass
class DeviceConfig:
    device_id: str
    name: str
    addresses: list[str]

    @classmethod
    def from_dict(cls, d: dict) -> "DeviceConfig":
        return cls(
            device_id=d["deviceID"],
            name=d.get("name", d["deviceID"][:7]),
            addresses=d.get("addresses", []),
        )


@dataclass
class DeviceInfo:
    device_id: str
    name: str
    ip: Optional[str]
    api_url: Optional[str]
    api_key: Optional[str]
    folder_path: Optional[str]
    ssh_reachable: bool
    api_reachable: bool
    is_local: bool
    # SSH credentials used — stored so rename step can reuse them
    ssh_user: Optional[str] = None
    ssh_key_path: Optional[str] = None
    ssh_password: Optional[str] = None
    ssh_port: int = 22
    winrm_reachable: bool = False
    winrm_user: Optional[str] = None
    winrm_password: Optional[str] = None
    winrm_port: int = 5985
    ssh_error: Optional[str] = None
    # True ONLY when a remote login was actually attempted and the credentials were REJECTED
    # (SSH/WinRM "auth failed"). A benign ssh_error — offline/no-IP, config.xml not found, no
    # creds configured — leaves this False. Consumers that mean "the user typed wrong creds"
    # (cred badge, passive auto-untick, topology preview halo) MUST key on this flag, not on the
    # mere presence of ssh_error, or they'll wrongly condemn legit offline passive targets.
    ssh_creds_rejected: bool = False
    api_error: Optional[str] = None
    os_type: Optional[str] = None  # "windows", "linux", "macos" or None (unknown)
    # True only when os_type came from a REAL probe (local OS, SSH `uname`, WinRM success,
    # or /rest/system/version). A user-picked OS leaves this False, so the GUI keeps the
    # selector editable until detection confirms it (detection is authoritative and wins).
    os_detected: bool = False
    # Normalized CPU arch ('amd64' | 'arm64' | 'armv7' | <raw>) or None. Drives which agent
    # template to build for this device (Linux/macOS are arch-specific — see generate.py).
    arch: Optional[str] = None
    # True only when arch came from a REAL probe (local platform, /rest/system/version 'arch',
    # or SSH `uname -m`). Mirrors os_detected: a detected arch lets the agent flow auto-pick the
    # right template instead of asking; an undetected device falls back to the base arch.
    arch_detected: bool = False
    # Real topology data observed from THIS device's folder config (when reachable):
    # the device IDs it shares the folder with, and its folder type (role). Used to
    # draw the true graph instead of assuming everything hangs off the local node.
    folder_peers: list[str] = field(default_factory=list)
    folder_role: Optional[str] = None  # "sendreceive" | "sendonly" | "receiveonly"
    # peer_id -> deviceID that introduced it (Syncthing 'introducedBy'). A non-empty
    # value means this device reaches that peer THROUGH the introducer, not directly —
    # so the real edge is introducer↔peer, not owner↔peer (avoids phantom links).
    folder_introducers: dict = field(default_factory=dict)


@dataclass
class RenameResult:
    device: DeviceInfo
    paused: bool = False
    dir_renamed: bool = False
    config_updated: bool = False
    resumed: bool = False
    error: Optional[str] = None
    warning: Optional[str] = None
    # The folder isn't in THIS device's Syncthing config yet (the config GET 404'd): the
    # device is joining the folder this run and the topology step creates it. Not a failure
    # — there is simply nothing to rename here, so it must not error or be queued for retry.
    skipped_absent: bool = False
    # The folder's on-disk path after this operation (== new path for a path change,
    # == old path for a label-only change). Callers cache it so a later undo knows the
    # *current* location to revert from — the discovered folder_path goes stale once
    # the first rename moves the directory.
    new_path: Optional[str] = None

    @property
    def success(self) -> bool:
        # A benign "folder absent here" skip counts as success: nothing failed, and the
        # topology step is responsible for creating the folder on this device.
        return self.skipped_absent or (self.dir_renamed and self.config_updated and self.resumed)

    @property
    def left_paused(self) -> bool:
        return self.paused and not self.resumed
