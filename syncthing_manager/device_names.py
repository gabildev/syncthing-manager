from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from .models import DeviceInfo
from .ssh_ops import SSHClient, SSHError
from .syncthing import SyncthingClient, SyncthingError, rest_device_path
from .winrm_ops import WinRMClient, WinRMError
from .i18n import t as _T

logger = logging.getLogger(__name__)


@dataclass
class NameSyncResult:
    device: DeviceInfo
    updated: int = 0    # device-name entries successfully changed on this target
    not_found: int = 0  # entries not in this target's config (skipped cleanly)
    error: Optional[str] = None  # fatal error connecting to / calling this target

    @property
    def success(self) -> bool:
        return self.error is None


def sync_device_names(
    local_client: SyncthingClient,
    devices: list[DeviceInfo],
    name_map: dict[str, str],
) -> list[NameSyncResult]:
    """
    Push canonical names (name_map: device_id → new_name) to every reachable device.

    For each target device, only entries that already exist in its config are updated
    (we never create new device pairings).  Unreachable devices are skipped silently.
    """
    results = []
    for dev in devices:
        if not (dev.is_local or dev.api_reachable or dev.ssh_reachable or dev.winrm_reachable):
            continue
        results.append(_apply_names_to_device(local_client, dev, name_map))
    return results


def _api_port(api_url: Optional[str]) -> int:
    import re
    if api_url:
        host = api_url.split("//")[-1] if "//" in api_url else api_url
        host = host.split("/")[0]  # strip path component
        m = re.search(r":(\d+)$", host)  # $ avoids matching colons inside IPv6
        if m:
            return int(m.group(1))
    return 8384


def _apply_names_to_device(
    local_client: SyncthingClient,
    dev: DeviceInfo,
    name_map: dict[str, str],
) -> NameSyncResult:
    updated = not_found = 0

    try:
        if dev.is_local or dev.api_reachable:
            client = (
                local_client
                if dev.is_local
                else SyncthingClient(
                    dev.api_url or "http://127.0.0.1:8384",
                    dev.api_key or "",
                    verify_ssl=False,
                )
            )
            for dev_id, new_name in name_map.items():
                try:
                    if client.patch_device_name(dev_id, new_name):
                        updated += 1
                    else:
                        not_found += 1
                except SyncthingError as e:
                    logger.debug("patch_device_name %s on %s: %s", dev_id[:7], dev.name, e)
                    not_found += 1

        elif dev.ssh_reachable:
            if not dev.api_key:
                return NameSyncResult(device=dev, error=_T("Sin API key — no se puede actualizar la config"))
            api_port = _api_port(dev.api_url)
            with SSHClient(
                host=dev.ip or "",
                user=dev.ssh_user,
                key_path=dev.ssh_key_path,
                port=dev.ssh_port,
                password=dev.ssh_password,
            ) as ssh:
                for dev_id, new_name in name_map.items():
                    try:
                        current = ssh.syncthing_api_get(
                            rest_device_path(dev_id), dev.api_key, api_port
                        )
                        if not current:
                            not_found += 1
                            continue
                        current["name"] = new_name
                        ssh.syncthing_api_put(
                            rest_device_path(dev_id), current, dev.api_key, api_port
                        )
                        updated += 1
                    except SSHError as e:
                        logger.debug("SSH name update %s on %s: %s", dev_id[:7], dev.name, e)
                        not_found += 1

        elif dev.winrm_reachable:
            if not dev.api_key:
                return NameSyncResult(device=dev, error=_T("Sin API key — no se puede actualizar la config"))
            api_port = _api_port(dev.api_url)
            with WinRMClient(
                host=dev.ip or "",
                user=dev.winrm_user or "",
                password=dev.winrm_password or "",
                port=dev.winrm_port,
            ) as winrm:
                for dev_id, new_name in name_map.items():
                    try:
                        current = winrm.syncthing_api_get(
                            rest_device_path(dev_id), dev.api_key, api_port
                        )
                        if not current:
                            not_found += 1
                            continue
                        # PowerShell's ConvertTo-Json collapses single-element arrays
                        # into scalars; re-wrap list fields before the PUT-back so we
                        # don't malform the device config.
                        for _arr in ("addresses", "allowedNetworks", "ignoredFolders"):
                            val = current.get(_arr)
                            if val is not None and not isinstance(val, list):
                                current[_arr] = [val]
                        current["name"] = new_name
                        winrm.syncthing_api_put(
                            rest_device_path(dev_id), current, dev.api_key, api_port
                        )
                        updated += 1
                    except WinRMError as e:
                        logger.debug("WinRM name update %s on %s: %s", dev_id[:7], dev.name, e)
                        not_found += 1

        return NameSyncResult(device=dev, updated=updated, not_found=not_found)

    except Exception as e:
        logger.debug("sync_device_names on %s failed: %s", dev.name, e)
        return NameSyncResult(device=dev, updated=updated, not_found=not_found, error=str(e))
