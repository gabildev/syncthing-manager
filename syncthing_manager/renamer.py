from __future__ import annotations

import errno
import getpass
import logging
import os
import platform
import re
import subprocess
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Optional

from .discovery import find_local_config_path
from .i18n import t as _T
from .models import DeviceInfo, RenameResult
from .validation import differs_only_in_case, validate_new_path_input
from .ssh_ops import SSHClient, SSHError
from .syncthing import (SyncthingClient, SyncthingError, rest_folder_path,
                        rest_db_folder_query, rest_device_path)
from .winrm_ops import WinRMClient, WindowsSSHClient, WinRMError

MAX_WORKERS = 4

logger = logging.getLogger(__name__)


_WINDOWS_PATH_RE = re.compile(r'^[A-Za-z]:[/\\]|^\\\\')


def is_absolute_path(p: str) -> bool:
    """
    True for a POSIX-absolute path OR a Windows drive/UNC path, regardless of the
    controller's OS. os.path.isabs() alone misses 'D:\\x' / '\\\\srv\\share' on
    Linux, which matters when a Linux controller targets Windows devices.
    """
    if not p:
        return False
    return bool(os.path.isabs(p) or _WINDOWS_PATH_RE.search(p))


def _ssh_client(device):
    """SSH transport for `device`. A POSIX host gets the usual ssh_ops.SSHClient (mv/rm/test/
    curl); a WINDOWS host gets a WindowsSSHClient that runs the equivalent PowerShell over the
    same SSH connection (the POSIX commands would fail on a cmd.exe/PowerShell default shell).
    Both expose the identical method interface, so every call site stays the same. The POSIX
    path is byte-for-byte unchanged for non-Windows devices."""
    if getattr(device, "os_type", None) == "windows":
        return WindowsSSHClient(host=device.ip, user=device.ssh_user,
                                key_path=device.ssh_key_path, port=device.ssh_port,
                                password=device.ssh_password)
    return SSHClient(host=device.ip, user=device.ssh_user, key_path=device.ssh_key_path,
                     port=device.ssh_port, password=device.ssh_password)


def _ensure_dir_and_marker(device, path: str) -> str:
    """Create `path` and its `.stfolder` marker on `device` via whatever channel it has — local
    FS, SSH, or WinRM. Used by the direct-API apply branch so a REMOTE api-reachable device that
    ALSO has SSH/WinRM (e.g. a LAN hub like a Raspberry Pi exposing its API on the LAN) gets its
    folder DIRECTORY created too — not only the local node. Without it Syncthing accepts the
    config, finds no path, parks the folder "path missing", and never writes the marker (which
    later makes a disk-delete silently skip). Returns '' on success, or a ' ⚠ …' suffix (an
    api-only remote with no shell, or an error) for the caller to append to its status verb."""
    if not path:
        return ""
    try:
        if device.is_local:
            base = os.path.expanduser(path)
            Path(base).mkdir(parents=True, exist_ok=True)
            mk = os.path.join(base, ".stfolder")
            if not os.path.exists(mk):
                os.makedirs(mk, exist_ok=True)
            return ""
        if device.winrm_reachable or device.ssh_reachable:
            cli = (WinRMClient(host=device.ip, user=device.winrm_user,
                               password=device.winrm_password, port=device.winrm_port)
                   if device.winrm_reachable else _ssh_client(device))
            sep = "\\" if (device.winrm_reachable or device.os_type == "windows") else "/"
            with cli:
                cli.ensure_dir(path)
                marker = path.rstrip("/\\") + sep + ".stfolder"
                if not cli.path_exists(marker):
                    cli.ensure_dir(marker)
            return ""
        # Pure direct-API remote with no shell — we genuinely can't create the dir for it.
        return _T(" ⚠ sin acceso de shell (solo API): crea el directorio a mano en el "
                  "dispositivo o genera un agente")
    except Exception as e:
        return _T(" ⚠ no se pudo crear el directorio: {}").format(e)


def _resolve_new_path(old_path: str, new_dir_name: str) -> str:
    """
    Absolute path → use as-is.
    Bare name     → replace last component only.

    Uses PureWindowsPath when old_path looks like a Windows path (drive letter
    or backslash separator) so this works correctly on a Linux controller
    managing Windows targets.
    """
    if is_absolute_path(new_dir_name):
        return new_dir_name
    if _WINDOWS_PATH_RE.search(old_path):
        return str(PureWindowsPath(old_path).parent / new_dir_name)
    return str(PurePosixPath(old_path).parent / new_dir_name)


def _api_port(device: DeviceInfo) -> int:
    """Extract Syncthing API port from device.api_url (defaults to 8384)."""
    if device.api_url:
        host_part = device.api_url.split("//")[-1] if "//" in device.api_url else device.api_url
        host_part = host_part.split("/")[0]  # strip any path component
        # Use $ anchor so we match the port at the end, not a colon inside IPv6
        m = re.search(r":(\d+)$", host_part)
        if m:
            return int(m.group(1))
    return 8384


def _prefer_remote_shell(device: DeviceInfo) -> bool:
    """When True, route a NON-LOCAL device's Syncthing API calls over its SSH/WinRM channel
    instead of hitting its API directly. The direct API sends the X-API-Key over a connection
    we can't verify (Syncthing's self-signed cert / plain http); SSH/WinRM is authenticated and
    encrypted and runs curl against the device's *localhost*, so the key never crosses the wire.

    Opt-in (setting "prefer_secure_channel", default False) so existing API-first setups are
    unchanged. Only applies when a shell channel is actually reachable; the local device (loopback
    API, no exposure) is never affected. Demoting `has_direct_api` is enough — every channel
    branch already falls through API → SSH → WinRM."""
    if device.is_local or not (device.ssh_reachable or device.winrm_reachable):
        return False
    try:
        from . import config as _appconfig
        return bool(_appconfig.get_setting("prefer_secure_channel", False))
    except Exception:
        return False


def _has_direct_api(device: DeviceInfo) -> bool:
    """Single source of truth for 'use this device's Syncthing API directly'. True when the API
    is reachable (or it's the local node) AND we're not deliberately routing it over SSH/WinRM
    for secrecy (_prefer_remote_shell). Every API/SSH/WinRM branch in this module derives its
    channel from this, so the secure-channel preference applies uniformly (rename, ID rename,
    topology, folder-cfg, ignores, remove, preflight)."""
    if not ((device.api_reachable or device.is_local) and bool(device.api_url)):
        return False
    return not _prefer_remote_shell(device)


def _is_folder_absent_error(e: Exception) -> bool:
    """True when an API/SSH/WinRM error means 'this folder ID isn't in the device's config'.
    Direct API: SyncthingError carries the structured ``status_code`` (404) — prefer it over the
    message (it's what get_folder already uses to tell 404 from a transient blip). SSH-curl and
    WinRM/Invoke-RestMethod have no status field, so match their rendered text ('→ HTTP 404',
    '(404)', 'No folder with given ID'). A 404 against the folder-config endpoint can only mean
    the folder is absent, so keying on the code there is safe."""
    # Direct API: rely ONLY on the structured 404. A SyncthingError whose MESSAGE merely
    # contains "404" must NOT count as absent — e.g. a path-change recreate whose create-POST
    # failed AFTER the folder was deleted re-raises the original 404-bearing text, but the
    # folder provably WAS present, so that's a real failure to surface, not a benign skip.
    if isinstance(e, SyncthingError):
        return getattr(e, "status_code", None) == 404
    # SSH/WinRM errors have no status field → match the rendered HTTP code in the message.
    s = str(e)
    return "404" in s or "No folder with given ID" in s


def rename_on_device(
    device: DeviceInfo,
    folder_id: str,
    new_label: str,
    new_dir_name: str,
    dry_run: bool = False,
    skip_path_rename: bool = False,
) -> RenameResult:
    result = RenameResult(device=device)

    # Determine available communication paths
    has_direct_api = _has_direct_api(device)
    has_ssh   = device.ssh_reachable
    has_winrm = device.winrm_reachable

    if not has_direct_api and not has_ssh and not has_winrm:
        err = _T("Sin acceso API, SSH ni WinRM")
        if device.api_error:
            err += f" (API: {device.api_error})"
        result.error = err
        return result

    api_port = _api_port(device)
    client: Optional[SyncthingClient] = None
    if has_direct_api:
        client = SyncthingClient(device.api_url, device.api_key or "", verify_ssl=False)

    old_path = device.folder_path
    if old_path:
        new_path = _resolve_new_path(old_path, new_dir_name)
    else:
        new_path = None
        skip_path_rename = True

    # ── 4a: Pause ────────────────────────────────────────────────────────────
    try:
        if dry_run:
            logger.info("[dry-run] Would pause folder %s on %s", folder_id, device.name)
        elif has_direct_api:
            client.pause_folder(folder_id)
            if not client.wait_for_pause(folder_id, timeout=10):
                logger.warning("Folder did not reach 'paused' on %s; proceeding anyway", device.name)
            result.paused = True
        elif has_ssh:
            _ssh_pause_folder(device, folder_id, api_port)
            result.paused = True
        elif has_winrm:
            _winrm_pause_folder(device, folder_id, api_port)
            result.paused = True
    except (SyncthingError, SSHError, WinRMError) as e:
        # Pause is best-effort — proceed anyway on any failure.
        # Common cases: 404 (older Syncthing / folder not on this device),
        # SSH curl returning empty output (HTTP error with -f flag), network blip.
        # update_folder_config will report a clear error if the folder truly doesn't exist.
        logger.warning("pause failed on %s (%s) — proceeding without pause", device.name, e)

    # ── 4b: Rename on disk ───────────────────────────────────────────────────
    no_ssh_remote = not device.is_local and not device.ssh_reachable and not device.winrm_reachable

    # When the disk can't be renamed (remote device reachable only by API, no
    # SSH/WinRM), we must NOT point the Syncthing config at the new path — the
    # directory still lives at old_path, so changing only the label keeps the
    # folder healthy. Updating the path here would leave the folder in an error
    # state until the user renames the directory by hand.
    keep_old_config_path = False

    if not skip_path_rename and old_path and new_path:
        if old_path == new_path:
            # Source and destination are identical — directory already has the right name
            result.dir_renamed = True
        elif no_ssh_remote and device.ssh_creds_rejected:
            # SSH was CONFIGURED but the credentials are REJECTED — that is a real misconfiguration
            # the user must fix, NOT the same as a device with no SSH access at all. Report it as a
            # FAILURE (✗) so it lands in the fix-the-creds-and-retry flow, instead of being folded
            # into the benign "use the agent" workaround below. Keep the folder healthy (don't
            # repoint the config) via _safe_resume.
            result.error = _T(
                "Credenciales SSH no válidas ({}) — corrígelas y reintenta "
                "para renombrar el directorio en {}"
            ).format(device.ssh_error, device.name)
            logger.warning("Disk rename blocked on %s (SSH creds rejected): %r → %r",
                           device.name, old_path, new_path)
            _safe_resume(client, device, folder_id, api_port, result)
            return result
        elif no_ssh_remote:
            # SSH simply NOT CONFIGURED (API-only device, by design) → benign: keep the old path so
            # the folder stays healthy, and tell the user how to rename the directory themselves.
            result.dir_renamed = True
            keep_old_config_path = True
            result.warning = _T(
                "Sin acceso SSH — renombra el directorio manualmente en {}:\n"
                "  {!r}  →  {!r}\n"
                "  (la config mantiene la ruta antigua para no romper la carpeta; "
                "usa el agente para automatizarlo)"
            ).format(device.name, old_path, new_path)
            logger.warning("Skipping disk rename on %s (no SSH): %r → %r", device.name, old_path, new_path)
        else:
            try:
                if dry_run:
                    logger.info("[dry-run] Would rename %r → %r on %s", old_path, new_path, device.name)
                    result.dir_renamed = True
                elif device.is_local:
                    _rename_with_retry(lambda: _rename_local(old_path, new_path))
                    result.dir_renamed = True
                else:
                    _rename_with_retry(lambda: _rename_remote(device, old_path, new_path))
                    result.dir_renamed = True
            except (OSError, SSHError, WinRMError) as e:
                msg = str(e)
                if _looks_like_lock(msg):
                    msg += _T("  —  algo está usando la carpeta (Explorador abierto en ella, "
                              "un fichero abierto, antivirus). Ciérralo y reintenta.")
                elif "already exists" in msg.lower() or "ya existe" in msg.lower():
                    msg += _T("  —  ya existe una carpeta con ese nombre en el destino "
                              "(no se sobrescribe para no perder datos). Bórrala o elige otro nombre.")
                result.error = f"Directory rename failed: {msg}"
                _safe_resume(client, device, folder_id, api_port, result)
                return result
    else:
        result.dir_renamed = True

    # ── 4c: Update Syncthing config ──────────────────────────────────────────
    if keep_old_config_path:
        effective_path = old_path
    else:
        effective_path = new_path if (not skip_path_rename and new_path) else old_path
    # If folder_path was unknown (remote device with no SSH), fetch live from API
    _fetch_err = None
    if not effective_path and has_direct_api:
        try:
            live = client.get_folder(folder_id)
        except SyncthingError as e:
            logger.warning("Could not fetch live folder path on %s: %s", device.name, e)
            _fetch_err = e
        else:
            if live is None:
                # get_folder returns None ONLY on a real 404 → the folder isn't on this device
                # yet (it's joining this run, which is why it has no known path). The topology
                # step creates it; this is a benign skip, not a "ruta desconocida" failure that
                # would falsely ✗ and poison the passive-retry queue.
                logger.info("Folder %s absent on %s (no path) — topology step will create it",
                            folder_id, device.name)
                result.skipped_absent = True
                return result
            effective_path = live.path
    if not effective_path:
        if not has_direct_api:
            # Reachable only by SSH/WinRM and no folder path was discovered → this device isn't
            # a member of the folder yet (a joining device; discovery found no folder on it). The
            # topology step creates it. Benign skip — NOT a "ruta desconocida" failure that would
            # falsely ✗ and poison the passive-retry queue. (Direct-API reaches here only when a
            # transient get_folder error left the path unknown → that stays a real, retryable error.)
            logger.info("No folder path for %s (SSH/WinRM, not a member yet) — topology will create it",
                        device.name)
            result.skipped_absent = True
            return result
        # Distinguish a TRANSIENT fetch failure (retryable — the device goes to the passive
        # queue) from a genuinely-unknown path, so the message doesn't sound permanent.
        result.error = (
            _T("no se pudo leer la ruta de la carpeta (error transitorio: {}); se reintentará").format(_fetch_err)
            if _fetch_err else
            _T("Ruta de carpeta desconocida — no se puede actualizar la config de Syncthing"))
        _safe_resume(client, device, folder_id, api_port, result)
        return result
    # Record the on-disk location after this op so callers can refresh their cached
    # folder_path (the discovered one goes stale once we move the directory).
    result.new_path = effective_path
    # Did the folder's path actually change? Syncthing ignores `path` on a config
    # PUT, so a real path change needs the reliable mechanism (config.xml+restart,
    # or recreate). A label-only change goes through the normal PUT.
    path_changed = (not skip_path_rename and not keep_old_config_path
                    and bool(new_path) and bool(old_path) and new_path != old_path)
    try:
        if dry_run:
            logger.info("[dry-run] Would update config: label=%r path=%r (path_changed=%s) on %s",
                        new_label, effective_path, path_changed, device.name)
            result.config_updated = True
        elif not path_changed:
            # Label only (path unchanged) — a config PUT applies this fine.
            if has_direct_api and client.is_version_gte("1.12.0"):
                client.update_folder_config(folder_id, new_label, effective_path)
            elif has_ssh and device.api_key:
                _ssh_update_folder_config(device, folder_id, new_label, effective_path, api_port)
            elif has_winrm and device.api_key:
                _winrm_update_folder_config(device, folder_id, new_label, effective_path, api_port)
            else:
                restarted = _update_config_legacy(device, folder_id, new_label, effective_path)
                if not restarted:
                    note = _T("Config actualizada en {} pero no se pudo confirmar el "
                              "reinicio de Syncthing — reinícialo para aplicar los cambios.").format(device.name)
                    result.warning = (result.warning + "\n" + note) if result.warning else note
            result.config_updated = True
        else:
            # Path is changing → a config PUT silently drops it (Syncthing locks the
            # path field). Recreate the folder (delete + create) via the API, the same
            # mechanism the ID rename uses successfully. Editing config.xml + restart is
            # NOT reliable: Syncthing rewrites config.xml from memory on shutdown, so the
            # edit is lost (old path + folder left paused). Recreate keeps the same ID
            # (peers see no new-folder prompt) and sets paused=false (no stuck pause).
            if has_direct_api:
                _change_path_via_recreate(client, folder_id, new_label, effective_path,
                                          dev_name=device.name)
            elif has_ssh:
                _recreate_via_ssh(device, folder_id, new_label, effective_path, api_port)
            elif has_winrm:
                _recreate_via_winrm(device, folder_id, new_label, effective_path, api_port)
            else:
                raise SyncthingError(_T("Sin acceso a API para cambiar la ruta"))
            result.config_updated = True
    except (SyncthingError, SSHError, WinRMError) as e:
        if _is_folder_absent_error(e):
            # The folder isn't in this device's Syncthing config yet — it's JOINING the folder
            # this run, and the topology step creates it (or passive/agent later). There is
            # nothing to rename here, so this is NOT a failure: a false ✗ would also poison the
            # passive-retry queue (the device would keep reappearing in "exploración" forever,
            # even though it ends up fully configured). Skip it cleanly. No revert (we changed
            # nothing on disk that matters) and no resume (there's no folder to resume).
            logger.info("Folder %s absent on %s during rename — topology step will create it",
                        folder_id, device.name)
            result.skipped_absent = True
            return result
        result.error = f"Config update failed: {e}"
        if (result.dir_renamed and not skip_path_rename and not keep_old_config_path
                and old_path and new_path):
            _attempt_revert(device, new_path, old_path)
        _safe_resume(client, device, folder_id, api_port, result)
        return result

    # Safety net: after a real path change, ensure the .stfolder marker exists at the
    # new location (a half-finished prior run could have left it missing). Best-effort,
    # never fails the rename.
    if path_changed and not dry_run:
        _ensure_stfolder(device, effective_path)

    # ── 4d: Resume ───────────────────────────────────────────────────────────
    # Applying the config update (step 4c) already cleared the paused flag via the
    # same PUT, and the legacy path restarts the service — so a successful config
    # update *is* the resume. No separate /rest/db/resume call (that endpoint 404s).
    result.resumed = True

    return result


def rename_all_devices(
    devices: list[DeviceInfo],
    folder_id: str,
    new_label: str,
    new_dir_name: str,
    dry_run: bool = False,
    skip_path_rename: bool = False,
    path_overrides: Optional[dict] = None,
) -> list[RenameResult]:
    """Rename the folder on every device. `path_overrides` (device_id → new path/name)
    lets a specific device use its OWN target path instead of the shared `new_dir_name`
    (per-device path change, B4); devices without an override use `new_dir_name`."""
    results: list[RenameResult] = []
    # Drop empty/blank override values: an EMPTY per-device override (a field the user cleared
    # but whose key lingered) must NOT count as "has an override" — otherwise _skip_for would
    # force a path rename toward new_dir_name on that device even under a global skip_path_rename.
    overrides = {k: v for k, v in (path_overrides or {}).items() if v}

    def _dir_for(device: DeviceInfo) -> str:
        return overrides.get(device.device_id) or new_dir_name

    def _skip_for(device: DeviceInfo) -> bool:
        # A device with an explicit per-device path override always gets a real path
        # change, even under a global "solo label" (skip) — that's the point of the override.
        return skip_path_rename and device.device_id not in overrides

    local_devices = [d for d in devices if d.is_local]
    remote_devices = [d for d in devices if not d.is_local]

    for device in local_devices:
        logger.info("Processing local device: %s", device.name)
        results.append(rename_on_device(device, folder_id, new_label, _dir_for(device),
                                        dry_run, _skip_for(device)))

    if remote_devices:
        # Use daemon threads so the process exits cleanly if the GUI window is
        # closed mid-rename instead of waiting for all workers to finish.
        sem = threading.BoundedSemaphore(MAX_WORKERS)
        result_lock = threading.Lock()

        def _run_one(device: DeviceInfo) -> None:
            with sem:
                try:
                    r = rename_on_device(device, folder_id, new_label,
                                         _dir_for(device), dry_run, _skip_for(device))
                except Exception as e:
                    logger.error("Unexpected error on %s: %s", device.name, e)
                    r = RenameResult(device=device, error=str(e))
                with result_lock:
                    results.append(r)

        threads = [
            threading.Thread(target=_run_one, args=(dev,), daemon=True)
            for dev in remote_devices
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    return results


def rename_folder_id(
    devices: list[DeviceInfo],
    old_folder_id: str,
    new_folder_id: str,
    dry_run: bool = False,
) -> list[tuple[str, bool, str]]:
    """
    Rename a folder's ID by deleting the old config entry and creating
    a new one with new_folder_id (same path, same device list, same options).

    Returns list of (device_name, success, message).

    Strategy (per reachable device — direct API, or proxied over SSH/WinRM):
      1. Fetch the current folder config.
      2. Delete the old folder (old and new share a path; Syncthing won't allow
         two folders on the same directory simultaneously).
      3. Create the new folder (POST with new_folder_id, same config). If this
         fails, recreate the original folder to roll back.
    Changing the ID on *every* device in the cluster (not just one) is what keeps
    sync seamless: peers re-associate by the new ID instead of seeing the old folder
    go stale and prompting to link a new one. Devices not reachable by API/SSH/WinRM
    keep the old ID until updated (e.g. via the agent), so the cluster is temporarily
    split for them — this is expected.
    """
    results: list[tuple[str, bool, str]] = []

    for dev in devices:
        has_direct_api = _has_direct_api(dev)
        api_port = _api_port(dev)
        try:
            if has_direct_api:
                client = SyncthingClient(dev.api_url, dev.api_key or "", verify_ssl=False)
                ok, msg = _rename_id_direct(client, old_folder_id, new_folder_id, dev.name, dry_run)
            elif dev.ssh_reachable:
                ok, msg = _rename_id_ssh(dev, old_folder_id, new_folder_id, api_port, dry_run)
            elif dev.winrm_reachable:
                ok, msg = _rename_id_winrm(dev, old_folder_id, new_folder_id, api_port, dry_run)
            else:
                ok, msg = False, _T("Sin acceso API/SSH/WinRM — usa el agente")
            results.append((dev.name, ok, msg))
        except (SyncthingError, SSHError, WinRMError) as e:
            results.append((dev.name, False, str(e)))
        except Exception as e:
            logger.error("rename_folder_id on %s: %s", dev.name, e)
            results.append((dev.name, False, str(e)))

    return results


def _id_rename_recovery_path(dev_name: str, old_id: str):
    """Filesystem-safe path of the recovery snapshot for (device, folder). None if unresolved."""
    try:
        from . import config as _appconfig
        safe_dev = re.sub(r"[^A-Za-z0-9_.-]", "_", dev_name or "device")[:60]
        safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", old_id or "folder")[:60]
        return _appconfig.data_dir() / "id_rename_recovery" / f"{safe_dev}-{safe_id}.json"
    except Exception:
        return None


def _save_id_rename_recovery(dev_name: str, old_id: str, config: dict):
    """Persist the original folder config to disk just before an ID rename DELETEs it.
    If the process dies in the delete→create gap (no in-process rollback can fire), this file
    lets the user recreate the folder by hand. Best-effort: never raises, never blocks the op.
    Returns the snapshot path (to clear on success) or None."""
    p = _id_rename_recovery_path(dev_name, old_id)
    if p is None:
        return None
    try:
        import json as _json
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(p.parent, 0o700)   # no-op on Windows
        except OSError:
            pass
        data = _json.dumps(config, indent=2, ensure_ascii=False)
        # The folder config can carry secrets (per-device encryptionPassword). Create the file
        # 0600 from the start so it's never briefly world-readable on a multi-user box.
        fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
        return p
    except Exception as e:
        logger.debug("could not write ID-rename recovery snapshot: %s", e)
        return None


def _clear_id_rename_recovery(path) -> None:
    """Delete a recovery snapshot once the ID rename completed (or rolled back) cleanly, so
    only snapshots from genuinely interrupted runs are left behind. Best-effort."""
    try:
        if path is not None:
            os.remove(path)
    except OSError:
        pass


def _lost_folder_msg(detail, rec_path) -> str:
    """Message for the worst case: the folder was deleted to recreate it under a new ID and
    neither the new nor the original config could be re-created. Point the user at the
    recovery snapshot we kept on disk so the config is actually recoverable (the data on
    disk is untouched; only Syncthing's folder entry was lost)."""
    msg = _T("¡CARPETA PERDIDA! borrada pero no se pudo recrear: {}").format(detail)
    if rec_path:
        msg += _T("\nLa configuración original se guardó en:\n  {}\n"
                  "Los archivos en disco siguen intactos. Vuelve a añadir la carpeta en "
                  "Syncthing (ese archivo JSON contiene la configuración original).").format(rec_path)
    return msg


def _rename_id_direct(client: SyncthingClient, old_id: str, new_id: str,
                      dev_name: str, dry_run: bool) -> tuple[bool, str]:
    folder = client.get_folder(old_id)
    if folder is None:
        return False, _T("Carpeta «{}» no encontrada").format(old_id)
    old_config = dict(folder.raw)
    new_config = dict(folder.raw)
    new_config["id"] = new_id
    if dry_run:
        logger.info("[dry-run] Would rename folder ID %s → %s on %s", old_id, new_id, dev_name)
        return True, "[dry-run] OK"
    # Delete before create: both share a path and Syncthing rejects two folders on
    # the same directory. Roll back by recreating the original if creation fails.
    _rec = _save_id_rename_recovery(dev_name, old_id, old_config)
    client.delete_folder(old_id)
    try:
        client.create_folder(new_config)
    except SyncthingError as e:
        logger.error("create_folder %s failed on %s — rolling back", new_id, dev_name)
        try:
            client.create_folder(old_config)
            _clear_id_rename_recovery(_rec)   # original restored — snapshot no longer needed
            return False, _T("Revertido (creación falló): {}").format(e)
        except SyncthingError as e2:
            # Keep the snapshot: this is exactly the case where it's needed for recovery.
            return False, _lost_folder_msg(e2, _rec)
    _clear_id_rename_recovery(_rec)
    return True, "OK"


def _rename_id_ssh(dev: DeviceInfo, old_id: str, new_id: str,
                   api_port: int, dry_run: bool) -> tuple[bool, str]:
    api_key = dev.api_key or ""
    ssh = _ssh_client(dev)
    with ssh:
        try:
            old_config = ssh.syncthing_api_get(rest_folder_path(old_id), api_key, api_port)
        except SSHError as e:
            # Don't mislabel a transient blip as 'not found' (and then abort): say what happened.
            if _is_folder_absent_error(e):
                return False, _T("Carpeta «{}» no encontrada (SSH)").format(old_id)
            return False, _T("No se pudo leer «{}» (SSH): {}").format(old_id, e)
        new_config = dict(old_config)
        new_config["id"] = new_id
        if dry_run:
            return True, "[dry-run] OK"
        _rec = _save_id_rename_recovery(dev.name, old_id, old_config)
        ssh.syncthing_api_delete(rest_folder_path(old_id), api_key, api_port)
        try:
            ssh.syncthing_api_post("/rest/config/folders", api_key, api_port, body=new_config)
        except SSHError as e:
            try:
                ssh.syncthing_api_post("/rest/config/folders", api_key, api_port, body=old_config)
                _clear_id_rename_recovery(_rec)
                return False, _T("Revertido (creación falló): {}").format(e)
            except SSHError as e2:
                return False, _lost_folder_msg(e2, _rec)
    _clear_id_rename_recovery(_rec)
    return True, "OK"


def _rename_id_winrm(dev: DeviceInfo, old_id: str, new_id: str,
                     api_port: int, dry_run: bool) -> tuple[bool, str]:
    api_key = dev.api_key or ""
    winrm = WinRMClient(host=dev.ip, user=dev.winrm_user,
                        password=dev.winrm_password, port=dev.winrm_port)
    with winrm:
        try:
            old_config = winrm.syncthing_api_get(rest_folder_path(old_id), api_key, api_port)
        except WinRMError as e:
            if _is_folder_absent_error(e):
                return False, _T("Carpeta «{}» no encontrada (WinRM)").format(old_id)
            return False, _T("No se pudo leer «{}» (WinRM): {}").format(old_id, e)
        # ConvertTo-Json collapses single-element arrays — re-wrap before POSTing back.
        if isinstance(old_config.get("devices"), dict):
            old_config["devices"] = [old_config["devices"]]
        new_config = dict(old_config)
        new_config["id"] = new_id
        if dry_run:
            return True, "[dry-run] OK"
        _rec = _save_id_rename_recovery(dev.name, old_id, old_config)
        winrm.syncthing_api_delete(rest_folder_path(old_id), api_key, api_port)
        try:
            winrm.syncthing_api_post("/rest/config/folders", api_key, api_port, body=new_config)
        except WinRMError as e:
            try:
                winrm.syncthing_api_post("/rest/config/folders", api_key, api_port, body=old_config)
                _clear_id_rename_recovery(_rec)
                return False, _T("Revertido (creación falló): {}").format(e)
            except WinRMError as e2:
                return False, _lost_folder_msg(e2, _rec)
    _clear_id_rename_recovery(_rec)
    return True, "OK"


# ── Topology apply ──────────────────────────────────────────────────────────
# Apply graph edits (folder role/type, device membership, new devices) to a
# reachable device. Adding a device/link to the reachable hubs is enough for
# Syncthing to auto-offer it to the new/offline peer when it connects; changing a
# specific device's OWN role must be applied on that device (now if reachable,
# else via passive/agent).

@dataclass
class TopologyResult:
    device_name: str
    ok: bool
    message: str
    # True when the folder was removed from Syncthing but its on-disk files were NOT deleted
    # (skipped/unreachable). A language-independent signal so the UI can warn without matching
    # the translated message text.
    disk_not_deleted: bool = False


def serialize_topology(topo: Optional[dict]) -> Optional[dict]:
    """JSON-friendly form of a topology graph (edges as lists; only the fields the
    apply step needs), for embedding in an agent's config."""
    if not topo:
        return None
    return {
        "nodes": {k: {"label": v.get("label", k[:7]), "role": v.get("role", "sendreceive"),
                      "path": v.get("path", ""), "is_local": bool(v.get("is_local")),
                      "is_new": bool(v.get("is_new"))}
                  for k, v in topo["nodes"].items()},
        # Only well-formed 2-node edges — matches the deserialize filter so the round-trip
        # is symmetric (a degenerate 1-element edge can't survive one side but not the other).
        "edges": [sorted(e) for e in topo["edges"] if len(e) == 2],
    }


def deserialize_topology(data: Optional[dict]) -> Optional[dict]:
    """Inverse of serialize_topology — rebuild edges as a set of frozenset pairs."""
    if not data:
        return None
    return {
        # Copy each node dict so a later in-place mutation of the deserialized graph can't
        # write back into the raw embedded JSON (parity with topology._topology_from_json).
        "nodes": {k: dict(v) for k, v in (data.get("nodes") or {}).items()},
        "edges": {frozenset(e) for e in data.get("edges", []) if len(e) == 2},
    }


def serialize_topology_diff(diff: Optional[dict]) -> Optional[dict]:
    """JSON-friendly form of a topology diff, for embedding in an agent's config so the
    agent applies ONLY the user's edits (not a full membership rewrite)."""
    if not diff or not diff.get("any"):
        return None
    return {"role_changed": dict(diff.get("role_changed", {})),
            "links_added": [sorted(e) for e in diff.get("links_added", set())],
            "links_removed": [sorted(e) for e in diff.get("links_removed", set())],
            # MUST carry `orphaned` (device ids that lost their last link) so the AGENT also
            # unshares them — without it the agent's diff has an empty orphaned set and the
            # orphan-unshare never happens on the agent path (it does on direct/passive).
            "orphaned": sorted(diff.get("orphaned", set()))}


def deserialize_topology_diff(data: Optional[dict]) -> Optional[dict]:
    """Inverse of serialize_topology_diff — edges back to sets of frozenset pairs."""
    if not data:
        return None
    return {"role_changed": dict(data.get("role_changed", {})),
            "links_added": {frozenset(e) for e in data.get("links_added", []) if len(e) == 2},
            "links_removed": {frozenset(e) for e in data.get("links_removed", []) if len(e) == 2},
            "orphaned": set(data.get("orphaned", [])),
            "skipped_locked": [], "skipped_offline": [],
            "any": bool(data.get("role_changed") or data.get("links_added")
                        or data.get("links_removed"))}


def _topo_neighbors(topology: dict, device_id: str) -> set:
    out = set()
    for e in topology.get("edges", set()):
        if device_id in e:
            out |= (set(e) - {device_id})
    return out


def _topo_update_folder_cfg(folder_cfg: dict, self_id: str, role: str, neighbor_ids: set) -> dict:
    """Existing folder → set role + devices = self + neighbors, preserving any
    existing per-device fields (introducedBy, encryptionPassword…)."""
    cfg = dict(folder_cfg)
    cfg["type"] = role
    existing_list = cfg.get("devices") or []   # `or []` also handles a null/None devices field
    if isinstance(existing_list, dict):   # WinRM ConvertTo-Json collapses single-element arrays
        existing_list = [existing_list]
    existing = {d.get("deviceID"): d for d in existing_list
                if isinstance(d, dict) and d.get("deviceID")}
    want = set(neighbor_ids) | {self_id}
    cfg["devices"] = [existing.get(did, {"deviceID": did}) for did in sorted(want)]
    return cfg


def _topo_create_folder_cfg(folder_id: str, label: str, path: str, self_id: str,
                            role: str, neighbor_ids: set) -> dict:
    """Folder missing on this device → create it directly (no accept prompt).
    Syncthing tilde-expands a leading ~ in the path itself."""
    want = set(neighbor_ids) | {self_id}
    return {"id": folder_id, "label": label or folder_id, "path": path or f"~/{label or folder_id}",
            "type": role, "paused": False,
            "devices": [{"deviceID": did} for did in sorted(want)]}


def compute_topology_diff(orig: Optional[dict], cur: Optional[dict],
                          locked=None) -> dict:
    """The MINIMAL set of edits the user made, expressed per-device — never a full
    membership rewrite. A link the user EDITED is applied even if it touches an offline
    device: the reachable end is configured now, the offline end when it reconnects
    (passive) or via agent. Links the user did NOT touch aren't in the diff, so they're
    never modified. Locked edges are always skipped."""
    empty = {"any": False, "role_changed": {}, "links_added": set(),
             "links_removed": set(), "skipped_locked": [], "skipped_offline": [],
             "orphaned": set()}
    if not orig or not cur:
        return empty
    locked = set(locked or set())
    role_changed = {}
    for nid, n in cur["nodes"].items():
        on = orig["nodes"].get(nid)
        if on and on.get("role") != n.get("role") and n.get("role_known", True):
            role_changed[nid] = n.get("role", "sendreceive")
    cur_e, orig_e = cur.get("edges", set()), orig.get("edges", set())
    links_added, links_removed, skipped_locked = set(), set(), []
    for bucket, src in ((links_added, cur_e - orig_e), (links_removed, orig_e - cur_e)):
        for e in src:
            if e in locked:
                skipped_locked.append(e)
            else:
                bucket.add(e)
    # Devices whose LAST link was removed (had ≥1 link in orig, none remain after this apply):
    # fully disconnected → the folder should be UNSHARED on them, not left configured-but-
    # peerless ("stopped"). Pausing has its own action; removing the link means stop sharing.
    # Shared locked-aware helper so the apply, the preview and the graph render agree on who is
    # orphaned. Exclude the CONTROLLER's own node (my_id) HERE rather than via the apply's
    # is_local check: that way the orphan set is correct for EVERY apply path — including the
    # AGENT, whose own node is is_local=True in its context and would otherwise never unshare.
    from .topology import orphaned_node_ids
    _my = (cur or {}).get("my_id")
    orphaned = orphaned_node_ids(orig_e, cur_e, locked) - ({_my} if _my else set())
    return {"role_changed": role_changed, "links_added": links_added,
            "links_removed": links_removed, "skipped_locked": skipped_locked,
            "skipped_offline": [], "orphaned": orphaned,
            "any": bool(role_changed or links_added or links_removed)}


def device_topology_changes(diff: Optional[dict], self_id: str):
    """(new_role_or_None, added_edges, removed_edges) that touch this device."""
    if not diff:
        return None, set(), set()
    added = {e for e in diff.get("links_added", set()) if self_id in e}
    removed = {e for e in diff.get("links_removed", set()) if self_id in e}
    return diff.get("role_changed", {}).get(self_id), added, removed


def apply_topology_diff_to_cfg(folder_cfg: dict, self_id: str, diff: dict):
    """Apply ONLY this device's diff to its EXISTING folder cfg, preserving every other
    device entry and per-device field (introducedBy, encryptionPassword…). Adds/removes
    just the changed neighbours and sets the role iff it changed. (folder membership
    only — never touches the global device list.) Returns (new_cfg, summary)."""
    role, added, removed = device_topology_changes(diff, self_id)
    cfg = dict(folder_cfg)
    lst = cfg.get("devices", [])
    if isinstance(lst, dict):   # WinRM ConvertTo-Json collapses single-element arrays
        lst = [lst]
    by_id = {d.get("deviceID"): d for d in lst
             if isinstance(d, dict) and d.get("deviceID")}
    add_ids, rem_ids = [], []
    for e in added:
        other = next(iter(e - {self_id}), None)
        if other and other not in by_id:
            by_id[other] = {"deviceID": other}
            add_ids.append(other)
    for e in removed:
        other = next(iter(e - {self_id}), None)
        if other and other in by_id:
            del by_id[other]
            rem_ids.append(other)
    by_id.setdefault(self_id, {"deviceID": self_id})   # self always stays a member
    cfg["devices"] = [by_id[k] for k in sorted(by_id)]
    if role is not None:
        cfg["type"] = role
    return cfg, {"added": add_ids, "removed": rem_ids, "role": role}


def _topo_entries_to_add(self_id: str, neighbors: set, existing_ids: set,
                         diff: Optional[dict], is_create: bool = False) -> list:
    """Device IDs to register as device entries on this device. On a fresh CREATE we need
    ALL neighbours (the new folder lists them all). On a diff UPDATE we only add the new
    neighbours from this device's added links (others already have entries)."""
    if diff is not None and not is_create:
        _, added, _ = device_topology_changes(diff, self_id)
        want = {o for e in added for o in (e - {self_id})}
    else:
        want = set(neighbors)
    return [nid for nid in want if nid not in existing_ids]


def _topo_decide_cfg(folder_cfg, folder_id, folder_label, new_path, self_id, role,
                     neighbors, diff, is_new=False):
    """(cfg, verb, is_create). Create fresh when the folder is missing; otherwise apply
    only the diff (non-destructive) when given, or the legacy full rewrite for back-compat.
    For a newly-shared device (`is_new`) the folder is forced un-paused: a device just added
    to the topology is meant to sync, so a stale `paused: true` on a pre-existing folder cfg
    (which the diff-update path would otherwise copy verbatim) must be cleared — a paused
    folder also never gets its directory created on disk."""
    if not folder_cfg:
        return (_topo_create_folder_cfg(folder_id, folder_label, new_path, self_id, role,
                                        neighbors), _T("carpeta creada"), True)
    # Warn (don't force) when editing an EXISTING device whose folder is PAUSED: the change
    # applies but won't sync until the user resumes it, and force-unpausing could override a
    # deliberate pause. is_new folders ARE force-unpaused (a just-shared device must sync).
    _paused_warn = (_T(" ⚠ la carpeta está PAUSADA aquí — reanúdala para que sincronice")
                    if (not is_new and folder_cfg.get("paused")) else "")
    if diff is not None:
        cfg, _summ = apply_topology_diff_to_cfg(folder_cfg, self_id, diff)
        if is_new:
            cfg["paused"] = False
        return cfg, _T("config actualizada (diff)") + _paused_warn, False
    cfg = _topo_update_folder_cfg(folder_cfg, self_id, role, neighbors)
    if is_new:
        cfg["paused"] = False
    return cfg, _T("config actualizada") + _paused_warn, False


def _recreate_folder_at_path(folder_id: str, new_path: str, base_cfg: dict,
                             fallback_cfg: dict, *, delete, create, err_cls, dev_name: str = ""):
    """Delete + recreate the folder so its on-disk path actually changes — a plain config
    PUT/replace silently keeps the old path (Syncthing locks it). `base_cfg` is the desired
    config (membership already applied); we point it at `new_path` and unpause it. Rolls back
    to `fallback_cfg` if creation fails; raises if even rollback fails (the data on disk is
    intact, only the config entry is gone). Transport-agnostic via the delete/create callables."""
    cfg = dict(base_cfg)
    cfg["path"] = new_path
    cfg["paused"] = False
    # Snapshot the original config before the destructive delete so a crash in the
    # delete→create gap is recoverable (parity with the rename/ID-rename recreate paths).
    _rec = _save_id_rename_recovery(dev_name or "device", folder_id, fallback_cfg)
    delete()
    try:
        create(cfg)
        _clear_id_rename_recovery(_rec)   # new folder exists → destructive window closed
    except err_cls:
        try:
            create(fallback_cfg)
            _clear_id_rename_recovery(_rec)
        except err_cls as e2:
            raise err_cls(
                _T("¡CONFIG DE CARPETA PERDIDA! «{}»: se borró para moverla a la ruta "
                   "nueva y no se pudo recrear ni la nueva ni la original. Los datos en disco "
                   "siguen intactos — vuelve a añadir la carpeta en Syncthing").format(folder_id)
                + (_T(" (config original guardada en {})").format(_rec) if _rec else "")
                + _T(". Causa: {}").format(e2)
            ) from e2
        raise


def apply_topology_on_device(device: DeviceInfo, folder_id: str, topology: dict,
                             diff: Optional[dict] = None, folder_label: str = "",
                             dry_run: bool = False) -> TopologyResult:
    """Apply this device's topology node DIRECTLY on the device (no Syncthing accept
    prompts). When `diff` is given the folder is updated NON-DESTRUCTIVELY — only the
    neighbours/role the user actually changed are touched, every other membership entry
    is preserved. When the folder doesn't exist yet it's created fresh (new device).
    Works over direct API / SSH / WinRM."""
    node = (topology or {}).get("nodes", {}).get(device.device_id)
    if node is None:
        return TopologyResult(device.name, True, _T("no está en la topología (sin cambios)"))
    role = node.get("role", "sendreceive")
    neighbors = _topo_neighbors(topology, device.device_id)
    names = {nid: n.get("label", nid[:7]) for nid, n in topology["nodes"].items()}
    new_path = node.get("path") or (f"~/{folder_label}" if folder_label else "")
    # With a diff, an existing device with no edits of its own is left completely alone.
    d_role, d_added, d_removed = device_topology_changes(diff, device.device_id)
    has_dev_changes = bool(d_role is not None or d_added or d_removed)
    # A device whose LAST link was removed is fully disconnected from the folder → UNSHARE it
    # (remove the folder from its config) instead of leaving it peerless/"stopped". No is_local
    # guard needed: compute_topology_diff already drops the controller's own node from
    # `orphaned`, so this stays correct for the direct, passive AND agent apply paths.
    is_orphaned = bool(diff is not None
                       and device.device_id in diff.get("orphaned", set()))

    if dry_run:
        if is_orphaned:
            return TopologyResult(device.name, True,
                                  _T("[dry-run] se dejaría de compartir (sin enlaces)"))
        if diff is not None:
            return TopologyResult(device.name, True,
                                  _T("[dry-run] +{}/−{} enlace(s)").format(len(d_added), len(d_removed))
                                  + (_T(", rol→{}").format(d_role) if d_role else ""))
        return TopologyResult(device.name, True,
                              _T("[dry-run] rol={}, {} vecino(s)").format(role, len(neighbors)))

    if is_orphaned:
        r = remove_folder_on_device(device, folder_id)
        return (TopologyResult(device.name, True, _T("carpeta dejada de compartir (sin enlaces)"))
                if r.ok else r)

    # With a diff, a device the user didn't touch (no role/link change) and that isn't a
    # brand-new device has nothing to do here — EVEN IF the folder happens to be absent on
    # it. Short-circuit before the create path below so we never resurrect a folder the
    # operator removed from this device while editing OTHER devices. (The per-channel "sin
    # cambios" guards only fire when the folder is present; this also covers folder=None,
    # which is exactly the agent's skipped_absent / config_updated=False case.)
    if diff is not None and not has_dev_changes and not node.get("is_new"):
        return TopologyResult(device.name, True, _T("sin cambios para este dispositivo"))

    has_direct_api = _has_direct_api(device)
    has_ssh, has_winrm = device.ssh_reachable, device.winrm_reachable
    api_port = _api_port(device)
    api_key = device.api_key or ""

    def _add_entry_msg(added: int, verb: str) -> str:
        if diff is not None:
            return _T("{}: +{}/−{} enlace(s)").format(verb, len(d_added), len(d_removed)) + \
                   (_T(", rol→{}").format(d_role) if d_role else "") + \
                   (_T(", +{} disp.").format(added) if added else "")
        return _T("{}: rol={}, {} vecino(s), +{} disp.").format(verb, role, len(neighbors), added)

    try:
        if has_direct_api:
            client = SyncthingClient(device.api_url, api_key, verify_ssl=False)
            folder = client.get_folder(folder_id)
            # A NEW device's folder may already exist (a prior run created it) but at a
            # DIFFERENT path than the one now chosen in the editor — Syncthing ignores `path`
            # on a config PUT, so that needs a recreate. Detect it here so it isn't dismissed
            # as "no changes" and so the path is actually corrected on a re-run.
            need_path_fix = bool(node.get("is_new") and new_path and folder is not None
                                 and not _path_already_at(folder.path, new_path))
            if folder is not None and diff is not None and not has_dev_changes and not need_path_fix:
                return TopologyResult(device.name, True, _T("sin cambios para este dispositivo"))
            existing_ids = {d.device_id for d in client.get_config_devices()}
            added = 0
            for nid in _topo_entries_to_add(device.device_id, neighbors, existing_ids, diff,
                                            is_create=folder is None):
                client._post("/rest/config/devices",
                             json={"deviceID": nid, "name": names.get(nid, nid[:7]),
                                   "addresses": ["dynamic"]})
                added += 1
            cfg, verb, is_create = _topo_decide_cfg(
                folder.raw if folder else None, folder_id, folder_label, new_path,
                device.device_id, role, neighbors, diff, is_new=bool(node.get("is_new")))
            if is_create:
                # Create the directory + .stfolder BEFORE registering the folder. Otherwise
                # Syncthing accepts the config, finds no path, parks the folder "path missing"
                # (it does NOT auto-create an absolute path), and never writes the marker (which
                # later makes a disk-delete silently skip). Covers the LOCAL node AND a remote
                # device reachable via SSH/WinRM (e.g. a LAN hub on the direct-API branch); a
                # pure API-only remote has no shell → the helper returns a ⚠ to surface that.
                verb += _ensure_dir_and_marker(device, new_path)
                client.create_folder(cfg)
            elif need_path_fix:
                _recreate_folder_at_path(folder_id, new_path, cfg, folder.raw,
                                         delete=lambda: client.delete_folder(folder_id),
                                         create=lambda c: client.create_folder(c),
                                         err_cls=SyncthingError, dev_name=device.name)
                verb = _T("ruta corregida → {}").format(new_path)
            else:
                # Plain UPDATE. Self-heal: (re)create the LOCAL dir first so a folder left in
                # "folder path missing" is repaired on re-apply (a remote direct-API device has
                # no shell to mkdir on, so this only helps the local node).
                if device.is_local and new_path:
                    try:
                        Path(new_path).expanduser().mkdir(parents=True, exist_ok=True)
                    except OSError:
                        pass
                client._put(rest_folder_path(folder_id), json=cfg)
            if need_path_fix and new_path:
                # Re-make the dir + marker after the recreate (local, or remote via SSH/WinRM).
                verb += _ensure_dir_and_marker(device, new_path)
            # Guarantee the .stfolder marker so Syncthing doesn't park the folder as "Stopped —
            # folder marker missing" (a plain rescan doesn't reliably recreate it). LOCAL only —
            # a remote direct-API device has no shell to create it on.
            if device.is_local and new_path:
                _mk = os.path.join(os.path.expanduser(new_path), ".stfolder")
                try:
                    if not os.path.exists(_mk):   # don't touch an existing marker (reused folder)
                        os.makedirs(_mk, exist_ok=True)
                except OSError:
                    pass
            # ALWAYS rescan so the folder's .stfolder marker is (re)written — repairs a "folder
            # marker missing" state on any re-apply, not only on create/path-fix.
            try:
                client.rescan_folder(folder_id)
            except SyncthingError:
                pass
            return TopologyResult(device.name, True, _add_entry_msg(added, verb))
        elif has_ssh:
            ssh = _ssh_client(device)
            with ssh:
                try:
                    folder_cfg = ssh.syncthing_api_get(rest_folder_path(folder_id), api_key, api_port)
                except SSHError as e:
                    # Distinguish "folder genuinely absent" (404 → create below) from a TRANSIENT
                    # read error. The direct-API branch gets this free (get_folder re-raises
                    # non-404); here a bare None would fall through to CREATE and the POST upsert
                    # would CLOBBER an existing folder's membership/fields. So abort on non-404.
                    if not _is_folder_absent_error(e):
                        return TopologyResult(device.name, False,
                                              _T("no se pudo leer la config (no se crea, para no "
                                                 "sobrescribir la carpeta existente): {}").format(e))
                    folder_cfg = None
                need_path_fix = bool(node.get("is_new") and new_path and folder_cfg
                                     and not _path_already_at(folder_cfg.get("path"), new_path))
                if folder_cfg and diff is not None and not has_dev_changes and not need_path_fix:
                    return TopologyResult(device.name, True, _T("sin cambios para este dispositivo"))
                devs = ssh.syncthing_api_get("/rest/config/devices", api_key, api_port)
                if isinstance(devs, dict):   # WinRM/PowerShell ConvertTo-Json collapses a 1-element array
                    devs = [devs]
                existing_ids = {d.get("deviceID") for d in devs if isinstance(d, dict)}
                added = 0
                for nid in _topo_entries_to_add(device.device_id, neighbors, existing_ids, diff,
                                                is_create=not folder_cfg):
                    ssh.syncthing_api_post("/rest/config/devices", api_key, api_port,
                                           body={"deviceID": nid, "name": names.get(nid, nid[:7]),
                                                 "addresses": ["dynamic"]})
                    added += 1
                cfg, verb, _is_create = _topo_decide_cfg(
                    folder_cfg, folder_id, folder_label, new_path,
                    device.device_id, role, neighbors, diff, is_new=bool(node.get("is_new")))
                if need_path_fix:
                    _recreate_folder_at_path(
                        folder_id, new_path, cfg, folder_cfg,
                        delete=lambda: ssh.syncthing_api_delete(
                            rest_folder_path(folder_id), api_key, api_port),
                        create=lambda c: ssh.syncthing_api_post(
                            "/rest/config/folders", api_key, api_port, body=c),
                        err_cls=SSHError, dev_name=device.name)
                    verb = _T("ruta corregida → {}").format(new_path)
                elif _is_create:
                    # Create the remote dir BEFORE registering the folder: otherwise Syncthing
                    # parks it in "folder path missing" and never writes .stfolder (which then
                    # makes a later disk-delete silently skip). ensure_dir expands a leading ~ to
                    # the SSH user's $HOME (matches the daemon in the common same-user setup; an
                    # absolute path is unambiguous). Surface a real failure instead of a fake "OK".
                    if new_path:
                        try:
                            ssh.ensure_dir(new_path)
                        except SSHError as _e:
                            verb += _T(" ⚠ no se pudo crear el directorio: {}").format(_e)
                    ssh.syncthing_api_post("/rest/config/folders", api_key, api_port, body=cfg)
                else:
                    # Plain UPDATE. Self-heal: ensure the dir exists FIRST, so a folder left in
                    # "folder path missing" (e.g. after a failed delete) is REPAIRED on re-apply,
                    # not merely re-configured.
                    if new_path:
                        try:
                            ssh.ensure_dir(new_path)
                        except SSHError as _e:
                            verb += _T(" ⚠ no se pudo crear el directorio: {}").format(_e)
                    ssh.syncthing_api_post("/rest/config/folders", api_key, api_port, body=cfg)
                # Guarantee the .stfolder marker so Syncthing doesn't park the folder as
                # "Stopped — folder marker missing" (a plain rescan does NOT reliably recreate it
                # for a folder it already stopped). Create it ourselves on the open channel, then
                # rescan. Repairs a "folder marker/path missing" state on any re-apply.
                if need_path_fix and new_path:
                    try:
                        ssh.ensure_dir(new_path)
                    except SSHError as _e:
                        verb += _T(" ⚠ no se pudo crear el directorio: {}").format(_e)
                if new_path:
                    _mk = new_path.rstrip("/") + "/.stfolder"
                    try:
                        if not ssh.path_exists(_mk):   # don't touch an existing marker (folder
                            ssh.ensure_dir(_mk)        # reused from a previous Syncthing setup)
                    except SSHError:
                        pass
                try:
                    ssh.syncthing_api_post(
                        rest_db_folder_query("scan", folder_id), api_key, api_port)
                except SSHError:
                    pass
            return TopologyResult(device.name, True, _add_entry_msg(added, verb) + " (SSH)")
        elif has_winrm:
            winrm = WinRMClient(host=device.ip, user=device.winrm_user,
                                password=device.winrm_password, port=device.winrm_port)
            with winrm:
                try:
                    folder_cfg = winrm.syncthing_api_get(rest_folder_path(folder_id), api_key, api_port)
                except WinRMError as e:
                    # As in the SSH branch: only a genuine 404 means "absent → create". A
                    # transient read error must NOT fall through to CREATE (the POST upsert would
                    # clobber the existing folder). Abort on non-404.
                    if not _is_folder_absent_error(e):
                        return TopologyResult(device.name, False,
                                              _T("no se pudo leer la config (no se crea, para no "
                                                 "sobrescribir la carpeta existente): {}").format(e))
                    folder_cfg = None
                # ConvertTo-Json collapses single-element arrays — re-wrap so the fallback
                # config (used for rollback) is well-formed before any recreate.
                if isinstance(folder_cfg, dict) and isinstance(folder_cfg.get("devices"), dict):
                    folder_cfg["devices"] = [folder_cfg["devices"]]
                need_path_fix = bool(node.get("is_new") and new_path and folder_cfg
                                     and not _path_already_at(folder_cfg.get("path"), new_path))
                if folder_cfg and diff is not None and not has_dev_changes and not need_path_fix:
                    return TopologyResult(device.name, True, _T("sin cambios para este dispositivo"))
                devs = winrm.syncthing_api_get("/rest/config/devices", api_key, api_port)
                if isinstance(devs, dict):
                    devs = [devs]
                existing_ids = {d.get("deviceID") for d in devs if isinstance(d, dict)}
                added = 0
                for nid in _topo_entries_to_add(device.device_id, neighbors, existing_ids, diff,
                                                is_create=not folder_cfg):
                    winrm.syncthing_api_post("/rest/config/devices", api_key, api_port,
                                             body={"deviceID": nid, "name": names.get(nid, nid[:7]),
                                                   "addresses": ["dynamic"]})
                    added += 1
                cfg, verb, _is_create = _topo_decide_cfg(
                    folder_cfg, folder_id, folder_label, new_path,
                    device.device_id, role, neighbors, diff, is_new=bool(node.get("is_new")))
                if need_path_fix:
                    _recreate_folder_at_path(
                        folder_id, new_path, cfg, folder_cfg,
                        delete=lambda: winrm.syncthing_api_delete(
                            rest_folder_path(folder_id), api_key, api_port),
                        create=lambda c: winrm.syncthing_api_post(
                            "/rest/config/folders", api_key, api_port, body=c),
                        err_cls=WinRMError, dev_name=device.name)
                    verb = _T("ruta corregida → {}").format(new_path)
                elif _is_create:
                    # Create the remote dir BEFORE registering the folder (avoids "folder path
                    # missing" + the missing .stfolder that makes a later disk-delete skip).
                    if new_path:
                        try:
                            winrm.ensure_dir(new_path)
                        except WinRMError as _e:
                            verb += _T(" ⚠ no se pudo crear el directorio: {}").format(_e)
                    winrm.syncthing_api_post("/rest/config/folders", api_key, api_port, body=cfg)
                else:
                    # Plain UPDATE. Self-heal: ensure the dir exists first (repairs "folder path
                    # missing"), then re-config.
                    if new_path:
                        try:
                            winrm.ensure_dir(new_path)
                        except WinRMError as _e:
                            verb += _T(" ⚠ no se pudo crear el directorio: {}").format(_e)
                    winrm.syncthing_api_post("/rest/config/folders", api_key, api_port, body=cfg)
                if need_path_fix and new_path:
                    try:
                        winrm.ensure_dir(new_path)
                    except WinRMError as _e:
                        verb += _T(" ⚠ no se pudo crear el directorio: {}").format(_e)
                # Guarantee the .stfolder marker so Syncthing doesn't park the folder as
                # "Stopped — folder marker missing" (a plain rescan doesn't reliably recreate it),
                # then ALWAYS rescan. Repairs a "folder marker/path missing" state on any re-apply.
                if new_path:
                    _mk = new_path.rstrip("\\/") + "\\.stfolder"
                    try:
                        if not winrm.path_exists(_mk):   # don't touch an existing marker (reused
                            winrm.ensure_dir(_mk)        # folder from a previous Syncthing setup)
                    except WinRMError:
                        pass
                try:
                    winrm.syncthing_api_post(
                        rest_db_folder_query("scan", folder_id), api_key, api_port)
                except WinRMError:
                    pass
            return TopologyResult(device.name, True, _add_entry_msg(added, verb) + " (WinRM)")
        else:
            return TopologyResult(device.name, False, _T("sin acceso (API/SSH/WinRM)"))
    except (SyncthingError, SSHError, WinRMError) as e:
        return TopologyResult(device.name, False, str(e))


_FCFG_FLAT_KEYS = ("rescanIntervalS", "fsWatcherEnabled", "ignorePerms", "paused")


def folder_cfg_with_overrides(folder_cfg: dict, ov: dict) -> dict:
    """Merge the curated advanced folder-config fields (`ov`) into a folder cfg dict,
    preserving everything else. `ov` keys: versioning_type + the flat keys above. Pure."""
    cfg = dict(folder_cfg)
    if "versioning_type" in ov:
        v = dict(cfg.get("versioning") or {})
        v["type"] = ov["versioning_type"]
        cfg["versioning"] = v
    for k in _FCFG_FLAT_KEYS:
        if k in ov:
            cfg[k] = ov[k]
    return cfg


def read_folder_cfg_on_device(device: DeviceInfo, folder_id: str) -> Optional[dict]:
    """Read this device's folder config over the best available channel (direct API / SSH /
    WinRM). Returns the raw cfg dict or None (offline / not reachable / folder missing)."""
    has_direct_api = _has_direct_api(device)
    api_port = _api_port(device)
    api_key = device.api_key or ""
    try:
        if has_direct_api:
            f = SyncthingClient(device.api_url, api_key, verify_ssl=False).get_folder(folder_id)
            return f.raw if f else None
        if device.ssh_reachable:
            with _ssh_client(device) as ssh:
                try:
                    return ssh.syncthing_api_get(rest_folder_path(folder_id), api_key, api_port)
                except SSHError:
                    return None
        if device.winrm_reachable:
            with WinRMClient(host=device.ip, user=device.winrm_user,
                             password=device.winrm_password, port=device.winrm_port) as winrm:
                try:
                    cfg = winrm.syncthing_api_get(rest_folder_path(folder_id), api_key, api_port)
                except WinRMError:
                    return None
                # PowerShell's ConvertTo-Json collapses a single-element array to a scalar —
                # re-wrap `devices` so callers that PUT this cfg back don't mangle a one-member
                # folder into a bare dict (parity with the other WinRM read sites).
                if isinstance(cfg, dict) and isinstance(cfg.get("devices"), dict):
                    cfg["devices"] = [cfg["devices"]]
                return cfg
    except (SyncthingError, SSHError, WinRMError):
        return None
    return None


def apply_folder_cfg_on_device(device: DeviceInfo, folder_id: str, overrides: dict,
                               dry_run: bool = False) -> TopologyResult:
    """Apply advanced FOLDER-config overrides to this device's folder (NON-destructive:
    only the given fields change). Works over direct API / SSH / WinRM — so it can run now
    for a reachable device, on reconnect (passive) or via an agent."""
    if not overrides:
        return TopologyResult(device.name, True, _T("sin cambios de carpeta"))
    if dry_run:
        return TopologyResult(device.name, True,
                              _T("[dry-run] config de carpeta: {} campo(s)").format(len(overrides)))
    has_direct_api = _has_direct_api(device)
    api_port = _api_port(device)
    api_key = device.api_key or ""
    try:
        if has_direct_api:
            client = SyncthingClient(device.api_url, api_key, verify_ssl=False)
            folder = client.get_folder(folder_id)
            if folder is None:
                return TopologyResult(device.name, True, _T("la carpeta no existe aquí (config omitida)"))
            client._put(rest_folder_path(folder_id),
                        json=folder_cfg_with_overrides(folder.raw, overrides))
            return TopologyResult(device.name, True,
                                  _T("config de carpeta aplicada ({} campo(s))").format(len(overrides)))
        elif device.ssh_reachable:
            ssh = _ssh_client(device)
            with ssh:
                try:
                    fc = ssh.syncthing_api_get(rest_folder_path(folder_id), api_key, api_port)
                except SSHError as e:
                    # Only a real 404 means 'folder absent here' (benign skip). A transient error
                    # must NOT masquerade as absent+success — the caller would drop the queued
                    # override from fcfg_pending and never retry. Parity with the API branch,
                    # whose get_folder re-raises non-404.
                    if not _is_folder_absent_error(e):
                        return TopologyResult(device.name, False, _T("no se pudo leer la config (SSH): {}").format(e))
                    fc = None
                if not fc:
                    return TopologyResult(device.name, True, _T("la carpeta no existe aquí (SSH)"))
                ssh.syncthing_api_post("/rest/config/folders", api_key, api_port,
                                       body=folder_cfg_with_overrides(fc, overrides))
            return TopologyResult(device.name, True, _T("config de carpeta aplicada (SSH)"))
        elif device.winrm_reachable:
            winrm = WinRMClient(host=device.ip, user=device.winrm_user,
                                password=device.winrm_password, port=device.winrm_port)
            with winrm:
                try:
                    fc = winrm.syncthing_api_get(rest_folder_path(folder_id), api_key, api_port)
                except WinRMError as e:
                    if not _is_folder_absent_error(e):
                        return TopologyResult(device.name, False, _T("no se pudo leer la config (WinRM): {}").format(e))
                    fc = None
                if not fc:
                    return TopologyResult(device.name, True, _T("la carpeta no existe aquí (WinRM)"))
                # ConvertTo-Json collapses a single-element 'devices' array into a bare object;
                # re-wrap before POSTing back or Syncthing rejects/mangles a 1-member folder.
                if isinstance(fc.get("devices"), dict):
                    fc["devices"] = [fc["devices"]]
                winrm.syncthing_api_post("/rest/config/folders", api_key, api_port,
                                         body=folder_cfg_with_overrides(fc, overrides))
            return TopologyResult(device.name, True, _T("config de carpeta aplicada (WinRM)"))
        else:
            return TopologyResult(device.name, False, _T("sin acceso (API/SSH/WinRM)"))
    except (SyncthingError, SSHError, WinRMError) as e:
        return TopologyResult(device.name, False, str(e))


def get_ignores_on_device(device: DeviceInfo, folder_id: str) -> Optional[list]:
    """Read the folder's .stignore patterns over the best channel (API/SSH/WinRM). Returns
    the list of pattern lines, or None when unreachable / on error."""
    q = rest_db_folder_query("ignores", folder_id)
    has_direct_api = _has_direct_api(device)
    api_port = _api_port(device)
    api_key = device.api_key or ""
    try:
        if has_direct_api:
            return SyncthingClient(device.api_url, api_key, verify_ssl=False).get_ignores(folder_id)
        if device.ssh_reachable:
            with _ssh_client(device) as ssh:
                data = ssh.syncthing_api_get(q, api_key, api_port)
        elif device.winrm_reachable:
            with WinRMClient(host=device.ip, user=device.winrm_user,
                             password=device.winrm_password, port=device.winrm_port) as winrm:
                data = winrm.syncthing_api_get(q, api_key, api_port)
        else:
            return None
        pats = data.get("ignore") if isinstance(data, dict) else None
        # WinRM/ConvertTo-Json collapses a single-element array to a bare string — re-wrap, or
        # the comprehension below would iterate it CHARACTER by character (one .stignore line
        # like "*.tmp" → ['*','.','t','m','p']).
        if isinstance(pats, str):
            pats = [pats]
        return [p for p in (pats or []) if isinstance(p, str)]
    except (SyncthingError, SSHError, WinRMError):
        return None


def resolve_remote_folder_path(device: DeviceInfo, folder_id: str) -> Optional[str]:
    """The folder's on-disk path as configured ON `device`, fetched over its best channel
    (direct API / SSH / WinRM) by cross-referencing the folder ID. Returns None when the
    device is unreachable or doesn't have that folder. Used to autodetect the path field
    when editing credentials of a device that already shares the folder."""
    fp = rest_folder_path(folder_id)
    api_port = _api_port(device)
    api_key = device.api_key or ""
    try:
        if _has_direct_api(device):
            f = SyncthingClient(device.api_url, api_key, verify_ssl=False).get_folder(folder_id)
            return f.path if f else None
        if device.ssh_reachable:
            with _ssh_client(device) as ssh:
                data = ssh.syncthing_api_get(fp, api_key, api_port)
        elif device.winrm_reachable:
            with WinRMClient(host=device.ip, user=device.winrm_user,
                             password=device.winrm_password, port=device.winrm_port) as winrm:
                data = winrm.syncthing_api_get(fp, api_key, api_port)
        else:
            return None
        return data.get("path") if isinstance(data, dict) else None
    except (SyncthingError, SSHError, WinRMError):
        return None


def set_ignores_on_device(device: DeviceInfo, folder_id: str, patterns: list) -> TopologyResult:
    """Replace the folder's .stignore patterns over the best channel (API/SSH/WinRM)."""
    q = rest_db_folder_query("ignores", folder_id)
    body = {"ignore": list(patterns)}
    has_direct_api = _has_direct_api(device)
    api_port = _api_port(device)
    api_key = device.api_key or ""
    try:
        if has_direct_api:
            SyncthingClient(device.api_url, api_key, verify_ssl=False).set_ignores(folder_id, patterns)
        elif device.ssh_reachable:
            with _ssh_client(device) as ssh:
                ssh.syncthing_api_post(q, api_key, api_port, body=body)
        elif device.winrm_reachable:
            with WinRMClient(host=device.ip, user=device.winrm_user,
                             password=device.winrm_password, port=device.winrm_port) as winrm:
                winrm.syncthing_api_post(q, api_key, api_port, body=body)
        else:
            return TopologyResult(device.name, False, _T("sin acceso (API/SSH/WinRM)"))
        return TopologyResult(device.name, True, "patrones .stignore guardados")
    except (SyncthingError, SSHError, WinRMError) as e:
        return TopologyResult(device.name, False, str(e))


def remove_folder_on_device(device: DeviceInfo, folder_id: str) -> TopologyResult:
    """Delete the folder config entry on a device (inverse of create — used when
    undoing a newly-added topology device). Never deletes files on disk."""
    has_direct_api = _has_direct_api(device)
    has_ssh, has_winrm = device.ssh_reachable, device.winrm_reachable
    api_port = _api_port(device)
    api_key = device.api_key or ""
    try:
        if has_direct_api:
            client = SyncthingClient(device.api_url, api_key, verify_ssl=False)
            if client.get_folder(folder_id) is None:
                return TopologyResult(device.name, True, _T("carpeta ya no existe"))
            client.delete_folder(folder_id)
            return TopologyResult(device.name, True, _T("carpeta eliminada (config)"))
        elif has_ssh:
            ssh = _ssh_client(device)
            with ssh:
                try:
                    ssh.syncthing_api_delete(rest_folder_path(folder_id), api_key, api_port)
                except SSHError as e:
                    if not _is_folder_absent_error(e):   # already gone is SUCCESS (idempotent, like the API branch)
                        raise
                    return TopologyResult(device.name, True, _T("carpeta ya no existe (SSH)"))
            return TopologyResult(device.name, True, _T("carpeta eliminada (SSH)"))
        elif has_winrm:
            winrm = WinRMClient(host=device.ip, user=device.winrm_user,
                                password=device.winrm_password, port=device.winrm_port)
            with winrm:
                try:
                    winrm.syncthing_api_delete(rest_folder_path(folder_id), api_key, api_port)
                except WinRMError as e:
                    if not _is_folder_absent_error(e):
                        raise
                    return TopologyResult(device.name, True, _T("carpeta ya no existe (WinRM)"))
            return TopologyResult(device.name, True, _T("carpeta eliminada (WinRM)"))
        else:
            return TopologyResult(device.name, False, _T("sin acceso (API/SSH/WinRM)"))
    except (SyncthingError, SSHError, WinRMError) as e:
        return TopologyResult(device.name, False, str(e))


# ── Definitive delete (Syncthing config + on-disk data) ──────────────────────
# DESTRUCTIVE and irreversible. Gated in the GUI behind advanced options, with a
# typed-name confirmation. Multiple safety layers: a protected-path blocklist (system /
# root / home dirs on POSIX *and* Windows), and a required '.stfolder' marker so a
# mis-detected path can't wipe an unrelated directory.

_PROTECTED_POSIX = {
    "/", "/bin", "/boot", "/dev", "/etc", "/home", "/lib", "/lib32", "/lib64",
    "/libx32", "/media", "/mnt", "/opt", "/proc", "/root", "/run", "/sbin", "/srv",
    "/sys", "/tmp", "/usr", "/usr/bin", "/usr/local", "/usr/sbin", "/usr/lib",
    "/usr/share", "/var", "/var/lib", "/var/log", "/Applications", "/System",
    "/Library", "/Users", "/private", "/Volumes",
}
_PROTECTED_WIN = {
    "C:\\WINDOWS", "C:\\WINDOWS\\SYSTEM32", "C:\\WINDOWS\\SYSWOW64",
    "C:\\PROGRAM FILES", "C:\\PROGRAM FILES (X86)", "C:\\PROGRAMDATA", "C:\\USERS",
    "C:\\$RECYCLE.BIN", "C:\\SYSTEM VOLUME INFORMATION",
}


def is_protected_delete_path(path: Optional[str], os_type: Optional[str] = None) -> bool:
    """True when `path` must NEVER be recursively deleted: empty, a filesystem/drive root,
    a user-home root, or a known system/critical directory (or the Windows directory
    subtree). Works for both POSIX and Windows paths regardless of the host OS."""
    if not path or not path.strip():
        return True
    p = path.strip()
    # A '..' segment is ambiguous (the real target depends on resolution, which PurePath does
    # NOT do) and no legitimate Syncthing folder path contains one — refuse to delete it.
    if ".." in re.split(r"[\\/]+", p):
        return True
    is_win = (os_type == "windows") or bool(re.match(r"^[A-Za-z]:([\\/]|$)", p)) or \
        ("\\" in p and "/" not in p) or \
        (os_type not in ("linux", "macos") and bool(re.match(r"^[\\/]{2}[^\\/]", p)))
    if is_win:
        # An extended-length / device prefix (\\?\, \\.\, and the \\?\UNC\ share form) is kept
        # VERBATIM inside PureWindowsPath.drive, so '\\?\C:\Windows' would slip past every
        # drive/system-dir check below (drive becomes '\\?\C:', the '[A-Za-z]:\WINDOWS' regex
        # never matches) and a system tree could be deleted. Strip it to the plain path it
        # denotes first, then evaluate that.
        m = re.match(r"^[\\/]{2}[?.][\\/](UNC[\\/])?", p)
        if m:
            p = ("\\\\" + p[m.end():]) if m.group(1) else p[m.end():]
        q = str(PureWindowsPath(p))
        if re.fullmatch(r"[A-Za-z]:\\?", q):          # bare drive root: C: / C:\
            return True
        pw = PureWindowsPath(p)
        if pw.drive.startswith("\\\\") and len(pw.parts) <= 1:   # bare UNC share root \\srv\share
            return True
        if not pw.drive:   # bare relative path (no drive, no UNC) → resolves against the remote
            return True    # shell's CWD; refuse (parity with POSIX).
        if not pw.root:    # DRIVE-RELATIVE ('C:foo\bar': has a drive but NO leading '\') → resolves
            return True    # against THAT drive's current directory, not the root. Refuse — e.g.
            #              # 'C:foo' could rm-rf under C:\Windows\System32 if that's the shell CWD.
        up = q.rstrip("\\").upper()
        # NTFS strips a TRAILING '.'/' ' from each path component when resolving ('C:\Windows.'
        # and 'C:\Windows.\System32' both open C:\Windows), but PureWindowsPath PRESERVES them, so
        # a trailing dot/space would slip a system path past the '(\\|$)'-anchored checks below.
        # Strip per component to mirror NTFS before matching → 'C:\WINDOWS.' is caught as \WINDOWS.
        up = "\\".join(seg.rstrip(" .") if i else seg for i, seg in enumerate(up.split("\\")))
        if re.fullmatch(r"[A-Za-z]:", up):            # "C:"
            return True
        protected = {x.rstrip("\\").upper() for x in _PROTECTED_WIN}
        if up in protected:
            return True
        if re.match(r"^[A-Za-z]:\\WINDOWS(\\|$)", up):   # anything under \Windows (System32…)
            return True
        if re.fullmatch(r"[A-Za-z]:\\USERS\\[^\\]+", up):  # a user-profile root (deeper is ok)
            return True
        # Same system roots on ANY drive (a D:\Program Files install is just as critical as C:).
        if re.fullmatch(
            r"[A-Za-z]:\\(PROGRAM FILES( \(X86\))?|PROGRAMDATA|USERS|\$RECYCLE\.BIN|"
            r"SYSTEM VOLUME INFORMATION)", up
        ):
            return True
        return False
    # POSIX (and ~)
    if p in ("~",) or re.fullmatch(r"~[\\/]?", p):
        return True
    q = str(PurePosixPath(p))
    # A truly relative path resolves against CWD; refuse. (~/... is home-relative and fine —
    # _delete_local_tree os.path.expanduser()s it before use.)
    if not q.startswith(("/", "~")):
        return True
    # PurePosixPath PRESERVES a leading '//' (POSIX treats it specially), so "//" and "//etc"
    # would slip past the root/system checks while resolving to "/" and "/etc" on Linux.
    # Collapse the leading slash run so they're matched.
    q = re.sub(r"^/{2,}", "/", q)
    if q in _PROTECTED_POSIX:
        return True
    if re.fullmatch(r"/home/[^/]+", q) or re.fullmatch(r"/Users/[^/]+", q) or q == "/root":
        return True
    return False


def _delete_local_tree(path: str, require_marker: bool = True) -> None:
    """Delete the local directory tree, with the same safety guards as the remote path."""
    import shutil
    p = os.path.expanduser(path).rstrip("/\\")
    if is_protected_delete_path(p, "windows" if os.name == "nt" else "linux"):
        raise OSError(_T("ruta protegida o vacía, no se borra: {}").format(path))
    if require_marker and not os.path.exists(os.path.join(p, ".stfolder")):
        raise OSError(_T("no parece una carpeta de Syncthing (falta .stfolder): {}").format(path))
    shutil.rmtree(p)


def _stfolder_marker_present(device: DeviceInfo, path: str) -> bool:
    """Is the '.stfolder' marker present in `path` on this device RIGHT NOW? Must be checked
    BEFORE removing the folder from Syncthing: Syncthing deletes the marker when the folder is
    removed from its config, so a check afterwards always fails (that was the bug — the on-disk
    delete was silently skipped because the marker the guard looked for had just been removed).
    Best-effort; raises the channel error so the caller can decide."""
    if device.is_local:
        p = os.path.expanduser(path).rstrip("/\\")
        return os.path.exists(os.path.join(p, ".stfolder"))
    if device.ssh_reachable:
        with _ssh_client(device) as ssh:
            return ssh.path_exists(path.rstrip("/") + "/.stfolder")
    if device.winrm_reachable:
        with WinRMClient(host=device.ip, user=device.winrm_user,
                         password=device.winrm_password, port=device.winrm_port) as winrm:
            return winrm.path_exists(path.rstrip("\\/") + "\\.stfolder")
    return False


def _folder_dir_exists_on_device(device: DeviceInfo, path: str) -> bool:
    """Does the folder's directory itself exist on this device RIGHT NOW? Used to tell a remote
    whose dir was never created / already gone ('folder path missing') — where there's NOTHING
    to delete on disk — apart from a real directory we couldn't fully remove."""
    if device.is_local:
        return os.path.exists(os.path.expanduser(path).rstrip("/\\"))
    if device.ssh_reachable:
        with _ssh_client(device) as ssh:
            return ssh.path_exists(path)
    if device.winrm_reachable:
        with WinRMClient(host=device.ip, user=device.winrm_user,
                         password=device.winrm_password, port=device.winrm_port) as winrm:
            return winrm.path_exists(path)
    return False


def delete_folder_on_device(device: DeviceInfo, folder_id: str, delete_data: bool = True,
                            dry_run: bool = False, require_marker: bool = True) -> TopologyResult:
    """DESTRUCTIVE: remove the folder from this device's Syncthing config AND (when
    `delete_data`) delete its on-disk directory tree. On-disk deletion needs the local
    filesystem (is_local) or shell access (SSH/WinRM) — the Syncthing API alone CANNOT
    delete data, so an API-only remote returns a failure asking for SSH/WinRM. Refuses
    protected/system paths and (by default) paths without a '.stfolder' marker."""
    name = device.name
    # device.folder_path can be unset (a folder created this session and not yet re-discovered,
    # or a device added by hand → folder_path None). Resolve the authoritative path from the
    # device's LIVE Syncthing config so the delete knows what to remove on disk. If it STILL
    # can't be resolved we do NOT fail early — the folder is still removed from Syncthing's
    # config below (non-destructive) and only the on-disk delete is skipped.
    path = device.folder_path or resolve_remote_folder_path(device, folder_id)
    if delete_data and path:
        if is_protected_delete_path(path, device.os_type):
            return TopologyResult(name, False, _T("ruta protegida del sistema, no se borra: {}").format(path))
        if not device.is_local and not (device.ssh_reachable or device.winrm_reachable):
            return TopologyResult(name, False,
                                  _T("borrar en disco requiere SSH/WinRM en este equipo"))
    if dry_run:
        msg = (_T("[dry-run] se quitaría de Syncthing y se borraría en disco: {}").format(path)
               if delete_data and path else _T("[dry-run] se quitaría de Syncthing (sin tocar disco)"))
        return TopologyResult(name, True, msg)
    # Safety: confirm the '.stfolder' marker exists NOW — BEFORE removing the config, because
    # Syncthing deletes the marker when it drops the folder. (Checking it afterwards, as the old
    # rmtree guard did, always failed → the disk delete was silently skipped and this behaved
    # like a plain unshare.) IMPORTANT: this guard gates ONLY the on-disk rmtree — it must NOT
    # block removing the folder from Syncthing's config (that's non-destructive). Previously a
    # missing/unverifiable marker returned early, so a remote whose dir was never created (the
    # "folder path missing" case) kept the folder in its Syncthing config forever — the folder
    # looked deleted on the cluster locally but lingered remotely.
    skip_disk_reason = None
    disk_already_gone = False
    if delete_data and not path:
        # Couldn't determine the on-disk path → can't delete it, but still remove the folder from
        # Syncthing's config (below) so it doesn't linger. Surfaced as a clear, non-fatal skip.
        skip_disk_reason = _T("no se conoce la ruta en disco")
    elif delete_data and require_marker:
        try:
            marker_ok = _stfolder_marker_present(device, path)
        except (SSHError, WinRMError, OSError) as e:
            skip_disk_reason = _T("no se pudo verificar la carpeta (acceso): {}").format(e)
        else:
            if not marker_ok:
                # No .stfolder. Tell apart "the directory doesn't exist at all" (a 'folder path
                # missing' remote — there is simply NOTHING to delete on disk, so it's a benign
                # success) from "the directory exists but lacks the marker" (a possibly mis-
                # detected path — too risky to rmtree, so warn). Without this, a delete on a
                # never-materialised remote dir surfaced as a scary "disco NO borrado" warning.
                try:
                    dir_there = _folder_dir_exists_on_device(device, path)
                except (SSHError, WinRMError, OSError):
                    dir_there = True   # can't tell → assume present and warn (safe side)
                if dir_there:
                    skip_disk_reason = _T("falta .stfolder (¿directorio sin crear?): {}").format(path)
                else:
                    disk_already_gone = True
    # 1) Remove from the Syncthing config (API / SSH / WinRM) — ALWAYS, even if the disk delete
    #    will be skipped, so the folder really disappears from Syncthing on this device.
    r = remove_folder_on_device(device, folder_id)
    if not r.ok:
        return TopologyResult(name, False, _T("no se pudo quitar de Syncthing: {}").format(r.message))
    if not delete_data:
        return r
    if skip_disk_reason:
        return TopologyResult(name, True,
                              _T("quitada de Syncthing; disco NO borrado ({})").format(skip_disk_reason),
                              disk_not_deleted=True)
    if disk_already_gone:
        # Nothing on disk to delete (the directory wasn't there) → a clean success, not a
        # "disco NO borrado" warning. The folder is gone from Syncthing and from disk.
        return TopologyResult(name, True,
                              _T("carpeta eliminada de Syncthing; en disco ya no existía ({})").format(path))
    # 2) Delete the on-disk tree. Marker already verified above (Syncthing just removed it), so
    #    don't re-require it here — only the protected-path guard still applies.
    try:
        if device.is_local:
            _delete_local_tree(path, require_marker=False)
        elif device.ssh_reachable:
            with _ssh_client(device) as ssh:
                ssh.remove_tree(path, require_marker=False)
        elif device.winrm_reachable:
            with WinRMClient(host=device.ip, user=device.winrm_user,
                             password=device.winrm_password, port=device.winrm_port) as winrm:
                winrm.remove_tree(path, require_marker=False)
        else:
            return TopologyResult(name, True,
                                  _T("quitada de Syncthing; disco NO borrado (requiere SSH/WinRM)"),
                                  disk_not_deleted=True)
        return TopologyResult(name, True, _T("carpeta eliminada de Syncthing y borrada en disco ({})").format(path))
    except (OSError, SSHError, WinRMError) as e:
        return TopologyResult(name, False,
                              _T("quitada de Syncthing, pero el borrado en disco falló: {}").format(e))


def delete_folder_everywhere(devices: list, folder_id: str, member_ids=None,
                             delete_data: bool = True, dry_run: bool = False) -> list:
    """DESTRUCTIVE cluster-wide: delete the folder (config + on-disk data when delete_data)
    on every member device. `member_ids` limits the scope (defaults to all given devices).
    Returns [(device_name, ok, msg, disk_not_deleted)]."""
    expected = set(member_ids) if member_ids is not None else {d.device_id for d in devices}
    out: list = []
    seen = set()
    for d in devices:
        if d.device_id not in expected:
            continue
        seen.add(d.device_id)
        r = delete_folder_on_device(d, folder_id, delete_data=delete_data, dry_run=dry_run)
        out.append((r.device_name, r.ok, r.message, r.disk_not_deleted))
    # Honest contract (like unshare/unlink): members we were asked to delete on but have NO
    # DeviceInfo for (offline / unknown) are reported as failures, never silently dropped — so
    # a cluster-delete summary can't claim success while the folder lingers on those equipos.
    for mid in sorted(expected - seen):
        out.append((mid[:7], False,
                    _T("no presente/alcanzable — la carpeta puede seguir en ese equipo"), False))
    return out


def _folders_sharing_peer(all_folders: list, peer_id: str) -> bool:
    """True if any folder in `all_folders` (raw dicts) lists `peer_id` as a member."""
    for f in all_folders:
        devs = f.get("devices", []) if isinstance(f, dict) else []
        if isinstance(devs, dict):   # WinRM ConvertTo-Json single-element collapse
            devs = [devs]
        for d in devs:
            if isinstance(d, dict) and d.get("deviceID") == peer_id:
                return True
    return False


def prune_orphan_device_entries(device: DeviceInfo, peer_ids, dry_run: bool = False) -> list:
    """Remove from `device`'s global config any peer in `peer_ids` that is no longer a
    member of ANY folder on this device — so undoing a link also takes the peer out of
    Syncthing's device list, not just out of the folder (the "sigue apareciendo" bug).
    Safe: a peer still shared via another folder is kept. Returns [(peer_id, removed, msg)]."""
    peer_ids = [p for p in (peer_ids or []) if p]
    if not peer_ids:
        return []
    has_direct_api = _has_direct_api(device)
    has_ssh, has_winrm = device.ssh_reachable, device.winrm_reachable
    api_port = _api_port(device)
    api_key = device.api_key or ""
    out: list = []
    try:
        if has_direct_api:
            client = SyncthingClient(device.api_url, api_key, verify_ssl=False)
            folders = [f.raw for f in client.get_folders()]
            for pid in peer_ids:
                if _folders_sharing_peer(folders, pid):
                    out.append((pid, False, _T("aún compartido en otra carpeta")))
                elif dry_run:
                    out.append((pid, True, _T("[dry-run] se quitaría del dispositivo")))
                else:
                    client.delete_device(pid)
                    out.append((pid, True, _T("entrada de dispositivo eliminada")))
        elif has_ssh or has_winrm:
            if has_ssh:
                conn = _ssh_client(device)
            else:
                conn = WinRMClient(host=device.ip, user=device.winrm_user,
                                   password=device.winrm_password, port=device.winrm_port)
            with conn:
                folders = conn.syncthing_api_get("/rest/config/folders", api_key, api_port)
                if isinstance(folders, dict):
                    folders = [folders]
                for pid in peer_ids:
                    if _folders_sharing_peer(folders or [], pid):
                        out.append((pid, False, _T("aún compartido en otra carpeta")))
                    elif dry_run:
                        out.append((pid, True, _T("[dry-run] se quitaría del dispositivo")))
                    else:
                        conn.syncthing_api_delete(rest_device_path(pid), api_key, api_port)
                        out.append((pid, True, _T("entrada de dispositivo eliminada")))
    except (SyncthingError, SSHError, WinRMError) as e:
        out.append(("", False, str(e)))
    return out


def _device_reachable(device: DeviceInfo) -> bool:
    """True if we have ANY working channel to act on this device right now."""
    return bool(((device.api_reachable or device.is_local) and device.api_url)
                or device.ssh_reachable or device.winrm_reachable)


def _drop_peer_from_folder_cfg(folder_cfg: dict, peer_id: str) -> tuple:
    """Pure: (new_cfg, changed) with `peer_id` removed from the folder's device list."""
    cfg = dict(folder_cfg)
    lst = cfg.get("devices", [])
    if isinstance(lst, dict):     # WinRM ConvertTo-Json single-element collapse
        lst = [lst]
    new = [d for d in lst if not (isinstance(d, dict) and d.get("deviceID") == peer_id)]
    cfg["devices"] = new
    return cfg, len(new) != len(lst)


def _write_folder_cfg_on_device(device: DeviceInfo, folder_id: str, cfg: dict) -> None:
    """PUT/POST a full folder cfg on a device over the best channel (API/SSH/WinRM)."""
    has_direct_api = _has_direct_api(device)
    api_port = _api_port(device)
    api_key = device.api_key or ""
    if has_direct_api:
        SyncthingClient(device.api_url, api_key, verify_ssl=False)._put(
            rest_folder_path(folder_id), json=cfg)
    elif device.ssh_reachable:
        with _ssh_client(device) as ssh:
            ssh.syncthing_api_post("/rest/config/folders", api_key, api_port, body=cfg)
    elif device.winrm_reachable:
        with WinRMClient(host=device.ip, user=device.winrm_user,
                         password=device.winrm_password, port=device.winrm_port) as winrm:
            winrm.syncthing_api_post("/rest/config/folders", api_key, api_port, body=cfg)
    else:
        raise SyncthingError(_T("sin acceso (API/SSH/WinRM)"))


def unshare_folder_everywhere(devices: list, folder_id: str, target_id: str,
                              dry_run: bool = False, member_ids=None,
                              prune_only: bool = False) -> list:
    """Stop sharing `folder_id` with `target_id` across the cluster:
      • delete the folder config ON the target device itself (if reachable), and
      • remove `target_id` from the folder membership of every OTHER device that
        shares it with the target.
    A peer that shares with the target but is NOT reachable right now can't be
    pruned (we have no channel to it) — instead of silently skipping it (which made
    the unshare look complete while those peers kept showing "device has not accepted
    sharing"), it is reported as an explicit failure so the caller can tell the user
    exactly which equipos still list the target and why.

    `member_ids` (optional) = the authoritative set of devices that share the folder
    with the target (e.g. from the topology graph). When given, unreachable members
    are flagged even if discovery couldn't read the target's own peer list. Falls back
    to the target's discovered `folder_peers`.

    Never deletes files on disk. Returns [(device_name, ok, msg, unreachable)] — `unreachable`
    is True for a member we couldn't reach (still shares the folder, pending a retry); a
    language-stable signal so the UI flags pending members without matching translated text."""
    out: list = []
    by_id = {d.device_id: d for d in devices}
    target = by_id.get(target_id)
    # Who is expected to drop the target = everyone that shares the folder with it
    # (sharing is mutual). Prefer the caller-supplied set; else the target's own view.
    expected = set(member_ids) if member_ids is not None else set(
        getattr(target, "folder_peers", None) or [])
    expected.discard(target_id)
    target_lbl = (target.name if target else target_id[:7])
    # 1) The folder on the target device itself. Skipped on a passive re-sweep
    # (`prune_only`): the target was already handled by the first run — we're only
    # finishing the peer-side prune on members that have since become reachable.
    if prune_only:
        pass
    elif target is not None:
        if dry_run:
            out.append((target.name, True, _T("[dry-run] se eliminaría la carpeta aquí"), False))
        else:
            r = remove_folder_on_device(target, folder_id)
            out.append((r.device_name, r.ok, r.message, False))
    elif target_id in expected:
        # We don't even have the target as a known device — note it's unreachable.
        out.append((target_id[:7], False, _T("no accesible — no se pudo eliminar la carpeta aquí"), True))
    # 2) Peer-side membership prune on every other device that shares with the target.
    for d in devices:
        if d.device_id == target_id:
            continue
        fc = read_folder_cfg_on_device(d, folder_id)
        if not fc:
            # Couldn't read this device's folder. If it's a known member of the share
            # with the target, it's a PENDING prune (offline / missing credentials) —
            # surface it instead of pretending it's done. (A REACHABLE member returning None
            # means the folder is simply absent there — nothing to prune — so we don't flag
            # it: read_folder_cfg_on_device conflates "404/absent" with "transient error",
            # and flagging would false-positive the common "member no longer has it" case.)
            if d.device_id in expected and not _device_reachable(d):
                out.append((d.name, False,
                            _T("no accesible — aún comparte con «{}»; añade "
                               "credenciales y reintenta, o quítalo en ese equipo").format(target_lbl), True))
            continue
        new_cfg, changed = _drop_peer_from_folder_cfg(fc, target_id)
        if not changed:
            continue
        if dry_run:
            out.append((d.name, True, _T("[dry-run] se quitaría «{}» de la carpeta").format(target_id[:7]), False))
            continue
        try:
            _write_folder_cfg_on_device(d, folder_id, new_cfg)
            out.append((d.name, True, _T("«{}» quitado de la carpeta").format(target_id[:7]), False))
        except (SyncthingError, SSHError, WinRMError) as e:
            out.append((d.name, False, str(e), False))
    # 3) Known members we never even saw in the device list (offline, only known via
    # the topology) — they still list the target and we couldn't touch them.
    seen = {d.device_id for d in devices}
    for mid in sorted(expected - seen):
        out.append((mid[:7], False,
                    _T("no accesible — aún comparte con «{}»; añade "
                       "credenciales y reintenta, o quítalo en ese equipo").format(target_lbl), True))
    return out


def unlink_device_everywhere(devices: list, target_id: str, dry_run: bool = False,
                             member_ids=None) -> list:
    """Fully UNPAIR `target_id`: remove its global device entry from every OTHER reachable
    device that lists it (which also drops all of its folder shares there). Never deletes
    files on disk.

    `member_ids` (optional) = peers that are known to be paired with the target (e.g. from
    the topology graph). Any such peer we can't reach right now is reported as an explicit
    failure instead of being silently skipped (which would make the unlink look complete
    while those equipos kept listing the target). Returns [(device_name, ok, msg, unreachable)] —
    `unreachable` True for a peer we couldn't reach (still has the target linked, pending retry);
    a language-stable signal so the UI flags pending peers without matching translated text."""
    out: list = []
    expected = set(member_ids or [])
    expected.discard(target_id)
    for d in devices:
        if d.device_id == target_id:
            continue
        api_port = _api_port(d)
        api_key = d.api_key or ""
        has_direct_api = _has_direct_api(d)
        if not (has_direct_api or d.ssh_reachable or d.winrm_reachable):
            if d.device_id in expected:
                out.append((d.name, False,
                            _T("no accesible — aún tiene vinculado al dispositivo; añade "
                               "credenciales y reintenta, o desvincúlalo en ese equipo"), True))
            continue
        try:
            if has_direct_api:
                client = SyncthingClient(d.api_url, api_key, verify_ssl=False)
                if target_id not in {x.device_id for x in client.get_config_devices()}:
                    continue
                if dry_run:
                    out.append((d.name, True, _T("[dry-run] se desvincularía aquí"), False))
                    continue
                client.delete_device(target_id)
                out.append((d.name, True, _T("dispositivo desvinculado"), False))
            elif d.ssh_reachable or d.winrm_reachable:
                if d.ssh_reachable:
                    conn = _ssh_client(d)
                else:
                    conn = WinRMClient(host=d.ip, user=d.winrm_user,
                                       password=d.winrm_password, port=d.winrm_port)
                with conn:
                    devs = conn.syncthing_api_get("/rest/config/devices", api_key, api_port)
                    if isinstance(devs, dict):
                        devs = [devs]
                    if target_id not in {x.get("deviceID") for x in devs if isinstance(x, dict)}:
                        continue
                    if dry_run:
                        out.append((d.name, True, _T("[dry-run] se desvincularía aquí"), False))
                        continue
                    conn.syncthing_api_delete(rest_device_path(target_id),
                                              api_key, api_port)
                    out.append((d.name, True, _T("dispositivo desvinculado"), False))
        except (SyncthingError, SSHError, WinRMError) as e:
            out.append((d.name, False, str(e), False))
    # Known paired peers we never saw in the device list (offline, only known via the
    # topology) — they still have the target linked and we couldn't touch them.
    seen = {d.device_id for d in devices}
    for mid in sorted(expected - seen):
        out.append((mid[:7], False,
                    _T("no accesible — aún tiene vinculado al dispositivo; añade "
                       "credenciales y reintenta, o desvincúlalo en ese equipo"), True))
    return out


# ── Pre-flight checks ───────────────────────────────────────────────────────
# Validate everything we can BEFORE touching any device, so a rename doesn't fail
# halfway on one machine. Each check is per-device and uses the OS we detected.

@dataclass
class PreflightIssue:
    device_name: str
    level: str   # "error" (blocks) | "warning" (informative)
    message: str


def preflight_check(
    devices: list[DeviceInfo],
    folder_id: str,
    new_dir_name: str,
    skip_path_rename: bool,
    new_folder_id: str = "",
) -> list[PreflightIssue]:
    """Run per-device pre-flight checks. Returns a flat list of issues (errors block,
    warnings inform). Does NOT modify anything. Safe to call from a worker thread."""
    issues: list[PreflightIssue] = []
    new_id = (new_folder_id or "").strip()
    id_change = bool(new_id) and new_id != folder_id

    for dev in devices:
        # 1. Name validity for THIS device's OS (pure, no I/O).
        if not skip_path_rename and new_dir_name:
            for p in validate_new_path_input(new_dir_name, dev.os_type):
                issues.append(PreflightIssue(dev.name, "error", _T("nombre no válido — {}").format(p)))

        # 2. Compute the real target path for this device (skip if no actual move).
        target = None
        if not skip_path_rename and new_dir_name and dev.folder_path:
            tp = _resolve_new_path(dev.folder_path, new_dir_name)
            if tp != dev.folder_path and not differs_only_in_case(dev.folder_path, tp):
                target = tp

        # 3 & 4. I/O checks (destination exists, ID collision) — one connection.
        if target or id_change:
            issues += _preflight_io(dev, target, new_id if id_change else None)

    return issues


def _preflight_io(dev: DeviceInfo, target_path: Optional[str],
                  new_id: Optional[str]) -> list[PreflightIssue]:
    issues: list[PreflightIssue] = []
    api_port = _api_port(dev)
    has_direct_api = _has_direct_api(dev)

    def _id_via_client() -> None:
        if not new_id:
            return
        client = SyncthingClient(dev.api_url, dev.api_key or "", verify_ssl=False)
        if client.get_folder(new_id) is not None:
            issues.append(PreflightIssue(dev.name, "error",
                                         _T("el ID «{}» ya existe en este dispositivo").format(new_id)))

    try:
        if dev.is_local:
            if target_path and os.path.exists(target_path):
                issues.append(PreflightIssue(dev.name, "error",
                                             _T("el destino ya existe: {}").format(target_path)))
            if target_path:
                parent = os.path.dirname(target_path.rstrip("/\\")) or os.sep
                if os.path.isdir(parent) and not os.access(parent, os.W_OK):
                    issues.append(PreflightIssue(dev.name, "warning",
                        _T("puede que no haya permiso de escritura en {} (verifícalo)").format(parent)))
                # Cross-filesystem move: a rename can't span mount points/drives, so an
                # absolute target on a different volume would fail at apply time.
                try:
                    if (dev.folder_path and os.path.exists(dev.folder_path) and os.path.isdir(parent)
                            and os.stat(dev.folder_path).st_dev != os.stat(parent).st_dev):
                        issues.append(PreflightIssue(dev.name, "error",
                            _T("el destino está en otro sistema de archivos que el origen "
                               "({} → {}); un renombrado no puede cruzar discos").format(dev.folder_path, target_path)))
                except OSError:
                    pass
            _id_via_client()

        elif dev.ssh_reachable:
            ssh = _ssh_client(dev)
            with ssh:
                if target_path and ssh.path_exists(target_path):
                    issues.append(PreflightIssue(dev.name, "error",
                                                 _T("el destino ya existe: {}").format(target_path)))
                if target_path:
                    parent = str(PurePosixPath(target_path).parent)
                    if not ssh.is_writable(parent):
                        issues.append(PreflightIssue(dev.name, "warning",
                            _T("puede que Syncthing no tenga permiso de escritura en {} "
                               "(usuario SSH ≠ usuario del servicio; verifícalo)").format(parent)))
                if new_id:
                    if has_direct_api:
                        _id_via_client()
                    else:
                        try:
                            ssh.syncthing_api_get(rest_folder_path(new_id),
                                                  dev.api_key or "", api_port)
                            issues.append(PreflightIssue(dev.name, "error",
                                          _T("el ID «{}» ya existe en este dispositivo").format(new_id)))
                        except SSHError:
                            pass  # 404 → free

        elif dev.winrm_reachable:
            winrm = WinRMClient(host=dev.ip, user=dev.winrm_user,
                                password=dev.winrm_password, port=dev.winrm_port)
            with winrm:
                if target_path and winrm.path_exists(target_path):
                    issues.append(PreflightIssue(dev.name, "error",
                                                 _T("el destino ya existe: {}").format(target_path)))
                if target_path:
                    parent = str(PureWindowsPath(target_path).parent)
                    if parent and not winrm.is_writable(parent):
                        issues.append(PreflightIssue(dev.name, "warning",
                            _T("puede que Syncthing no tenga permiso de escritura en {} "
                               "(usuario WinRM ≠ usuario del servicio; verifícalo)").format(parent)))
                if new_id:
                    if has_direct_api:
                        _id_via_client()
                    else:
                        try:
                            winrm.syncthing_api_get(rest_folder_path(new_id),
                                                    dev.api_key or "", api_port)
                            issues.append(PreflightIssue(dev.name, "error",
                                          _T("el ID «{}» ya existe en este dispositivo").format(new_id)))
                        except WinRMError:
                            pass

        elif has_direct_api:
            # API reachable but no shell → can't inspect the disk.
            if target_path:
                issues.append(PreflightIssue(dev.name, "warning",
                              _T("no se puede comprobar si el destino existe (solo API, sin SSH/WinRM)")))
            _id_via_client()

    except (SSHError, WinRMError, SyncthingError, OSError) as e:
        issues.append(PreflightIssue(dev.name, "warning",
                                     _T("no se pudieron completar las comprobaciones: {}").format(e)))
    return issues


# ── Internal helpers ──────────────────────────────────────────────────────────

RENAME_RETRIES = 3
RENAME_RETRY_DELAY = 1.0


def _looks_like_lock(msg: str) -> bool:
    """Heuristic: does this error look like the directory is held open by another
    process (Syncthing's watcher mid-teardown, Explorer, antivirus, open file)?"""
    m = msg.lower()
    return any(s in m for s in (
        "winerror 5", "acceso denegado", "access is denied", "permission denied",
        "being used by another process", "resource busy", "text file busy",
    ))


def _rename_with_retry(fn) -> None:
    """Run a rename, retrying a few times with backoff — absorbs the brief window
    where a just-paused folder's filesystem watcher hasn't released its handle yet."""
    last: Exception | None = None
    for attempt in range(RENAME_RETRIES):
        try:
            fn()
            return
        except (OSError, SSHError, WinRMError) as e:
            last = e
            if attempt < RENAME_RETRIES - 1 and _looks_like_lock(str(e)):
                logger.warning("Rename attempt %d failed (%s) — retrying in %.1fs",
                               attempt + 1, e, RENAME_RETRY_DELAY)
                time.sleep(RENAME_RETRY_DELAY)
            else:
                raise
    if last:  # pragma: no cover - defensive
        raise last


def _rename_local(old_path: str, new_path: str) -> None:
    old = Path(old_path)
    new = Path(new_path)
    if not old.exists():
        raise OSError(f"Source path does not exist: {old_path}")
    case_only = differs_only_in_case(str(old), str(new))
    if new.exists():
        # On a case-insensitive FS (Windows/macOS) 'testeo' and 'TESTEO' resolve to
        # the SAME directory, so new.exists() is a false positive for a case-only
        # change. Rename via a temp name so the displayed case actually changes.
        if case_only:
            tmp = old.parent / (old.name + "__case_tmp__")
            n = 0
            while tmp.exists():
                n += 1
                tmp = old.parent / (old.name + f"__case_tmp{n}__")
            old.rename(tmp)
            tmp.rename(new)
            logger.debug("Case-only local rename %r → %r (via temp)", old_path, new_path)
            return
        raise OSError(f"Destination already exists: {new_path}")
    try:
        old.rename(new)
    except OSError as e:
        if e.errno == errno.EXDEV:
            # Different filesystems/mount points: os.rename can't move across them
            # (would need a slow copy + delete that also resets mtimes Syncthing relies
            # on). Surface a clear, actionable error instead of a cryptic [Errno 18].
            raise OSError(
                _T("El destino está en otro sistema de archivos: {!r} → {!r}. "
                   "Un renombrado solo cambia el nombre en el mismo disco; para mover los "
                   "datos a otro volumen hazlo manualmente y reintenta con esa ruta.").format(old_path, new_path)
            ) from e
        raise
    logger.debug("Renamed local %r → %r", old_path, new_path)


def _rename_remote(device: DeviceInfo, old_path: str, new_path: str) -> None:
    if device.winrm_reachable:
        winrm = WinRMClient(host=device.ip, user=device.winrm_user,
                            password=device.winrm_password, port=device.winrm_port)
        with winrm:
            winrm.rename_path(old_path, new_path)
    else:
        ssh = _ssh_client(device)
        with ssh:
            ssh.rename_path(old_path, new_path)
    logger.debug("Renamed remote %r → %r on %s", old_path, new_path, device.name)


def _ensure_stfolder(device: DeviceInfo, folder_path: str) -> None:
    """Best-effort safety net: make sure the Syncthing folder marker (.stfolder)
    exists at folder_path after a path change, so Syncthing never reports a missing
    marker if a prior run was interrupted mid-move. NEVER raises — a hiccup here must
    not fail an otherwise-successful rename."""
    if not folder_path:
        return
    try:
        if device.is_local:
            marker = os.path.join(folder_path, ".stfolder")
            if not os.path.exists(marker):
                os.makedirs(marker, exist_ok=True)
                logger.info("Recreated missing .stfolder marker at %s", marker)
        elif device.winrm_reachable:
            marker = folder_path.rstrip("/\\") + "\\.stfolder"
            winrm = WinRMClient(host=device.ip, user=device.winrm_user,
                                password=device.winrm_password, port=device.winrm_port)
            with winrm:
                if not winrm.path_exists(marker):
                    winrm.ensure_dir(marker)
                    logger.info("Recreated missing .stfolder marker at %s on %s", marker, device.name)
        elif device.ssh_reachable:
            marker = folder_path.rstrip("/") + "/.stfolder"
            ssh = _ssh_client(device)
            with ssh:
                if not ssh.path_exists(marker):
                    ssh.ensure_dir(marker)
                    logger.info("Recreated missing .stfolder marker at %s on %s", marker, device.name)
    except Exception as e:
        logger.warning("Could not verify/recreate .stfolder on %s: %s", device.name, e)


def _attempt_revert(device: DeviceInfo, current_path: str, original_path: str) -> None:
    logger.warning("Reverting rename %r → %r on %s", current_path, original_path, device.name)
    try:
        if device.is_local:
            cur, orig = Path(current_path), Path(original_path)
            if cur.exists() and not orig.exists():
                cur.rename(orig)
                logger.info("Reverted local rename on %s", device.name)
        elif device.winrm_reachable:
            winrm = WinRMClient(host=device.ip, user=device.winrm_user,
                                password=device.winrm_password, port=device.winrm_port)
            with winrm:
                if winrm.path_exists(current_path) and not winrm.path_exists(original_path):
                    winrm.rename_path(current_path, original_path)
                    logger.info("Reverted remote rename on %s via WinRM", device.name)
        else:
            ssh = _ssh_client(device)
            with ssh:
                if ssh.path_exists(current_path) and not ssh.path_exists(original_path):
                    ssh.rename_path(current_path, original_path)
                    logger.info("Reverted remote rename on %s", device.name)
    except Exception as e:
        logger.error("Revert failed on %s: %s", device.name, e)


def _ssh_set_paused(device: DeviceInfo, folder_id: str, api_port: int, paused: bool) -> None:
    """Pause/resume a folder via the config API proxied over SSH (no /rest/db/pause)."""
    ssh = _ssh_client(device)
    api_key = device.api_key or ""
    with ssh:
        cfg = ssh.syncthing_api_get(rest_folder_path(folder_id), api_key, api_port)
        cfg["paused"] = paused
        ssh.syncthing_api_put(rest_folder_path(folder_id), cfg, api_key, api_port)


def _ssh_pause_folder(device: DeviceInfo, folder_id: str, api_port: int) -> None:
    _ssh_set_paused(device, folder_id, api_port, True)
    # The config PUT is synchronous and the next step opens a fresh SSH session
    # (its own handshake), which already gives the folder time to come to rest.
    time.sleep(0.3)


def _ssh_resume_folder(device: DeviceInfo, folder_id: str, api_port: int) -> None:
    _ssh_set_paused(device, folder_id, api_port, False)


def _winrm_set_paused(device: DeviceInfo, folder_id: str, api_port: int, paused: bool) -> None:
    """Pause/resume a folder via the config API proxied over WinRM."""
    winrm = WinRMClient(host=device.ip, user=device.winrm_user,
                        password=device.winrm_password, port=device.winrm_port)
    with winrm:
        cfg = winrm.syncthing_api_get(rest_folder_path(folder_id), device.api_key or "", api_port)
        # ConvertTo-Json collapses single-element arrays — re-wrap before PUT.
        if isinstance(cfg.get("devices"), dict):
            cfg["devices"] = [cfg["devices"]]
        cfg["paused"] = paused
        winrm.syncthing_api_put(rest_folder_path(folder_id), cfg, device.api_key or "", api_port)


def _winrm_pause_folder(device: DeviceInfo, folder_id: str, api_port: int) -> None:
    _winrm_set_paused(device, folder_id, api_port, True)
    time.sleep(0.3)


def _winrm_resume_folder(device: DeviceInfo, folder_id: str, api_port: int) -> None:
    _winrm_set_paused(device, folder_id, api_port, False)


def _ssh_update_folder_config(
    device: DeviceInfo, folder_id: str, new_label: str, new_path: str, api_port: int
) -> None:
    """Update folder config (label only) via SSH-proxied REST API and verify it took.
    Path changes don't come here — they use _recreate_via_ssh."""
    ssh = _ssh_client(device)
    with ssh:
        current = ssh.syncthing_api_get(rest_folder_path(folder_id),
                                        device.api_key or "", api_port)
        current["label"] = new_label
        current["path"] = new_path
        current["paused"] = False  # applying the rename also resumes the folder
        ssh.syncthing_api_put(rest_folder_path(folder_id), current,
                              device.api_key or "", api_port)
        check = ssh.syncthing_api_get(rest_folder_path(folder_id),
                                      device.api_key or "", api_port)
        if check.get("label") != new_label:
            raise SSHError(_T("La config no reflejó el cambio (label={!r})").format(check.get('label')))


def _winrm_update_folder_config(
    device: DeviceInfo, folder_id: str, new_label: str, new_path: str, api_port: int
) -> None:
    """Update folder config on a remote Windows device via WinRM-proxied REST API."""
    winrm = WinRMClient(host=device.ip, user=device.winrm_user,
                        password=device.winrm_password, port=device.winrm_port)
    with winrm:
        current = winrm.syncthing_api_get(rest_folder_path(folder_id),
                                          device.api_key or "", api_port)
        # PowerShell's ConvertTo-Json unwraps single-element arrays into bare
        # objects; re-wrap so the PUT-back keeps 'devices' as a list (Syncthing
        # would otherwise reject or mangle the config).
        if isinstance(current.get("devices"), dict):
            current["devices"] = [current["devices"]]
        current["label"] = new_label
        current["path"] = new_path
        current["paused"] = False  # applying the rename also resumes the folder
        winrm.syncthing_api_put(rest_folder_path(folder_id), current,
                                device.api_key or "", api_port)
        check = winrm.syncthing_api_get(rest_folder_path(folder_id),
                                        device.api_key or "", api_port)
        if check.get("label") != new_label:
            raise WinRMError(_T("La config no reflejó el cambio (label={!r})").format(check.get('label')))


def resume_folder_on_device(device: DeviceInfo, folder_id: str) -> tuple[bool, str]:
    """Resume a (possibly left-paused) folder on a device. Returns (ok, message)."""
    api_port = _api_port(device)
    try:
        # Honor prefer_secure_channel like the rest of the module (_has_direct_api): don't
        # send the API key over the direct (unverified) channel the user opted out of.
        if _has_direct_api(device):
            SyncthingClient(device.api_url, device.api_key or "", verify_ssl=False).resume_folder(folder_id)
        elif device.ssh_reachable:
            _ssh_resume_folder(device, folder_id, api_port)
        elif device.winrm_reachable:
            _winrm_resume_folder(device, folder_id, api_port)
        else:
            return False, _T("sin acceso (API/SSH/WinRM)")
        return True, "reanudado"
    except (SyncthingError, SSHError, WinRMError) as e:
        # Folder absent (any channel) → nothing to resume; not a failure. Uses the shared helper
        # (structured status_code for the API, '404' text for SSH/WinRM) instead of matching the
        # message of a SyncthingError, which could false-match a transient error quoting "404".
        if _is_folder_absent_error(e):
            return True, _T("reanudado (404 — la carpeta se reanuda al reiniciar)")
        return False, str(e)


def _safe_resume(
    client: Optional[SyncthingClient],
    device: DeviceInfo,
    folder_id: str,
    api_port: int,
    result: RenameResult,
) -> None:
    try:
        if client:
            client.resume_folder(folder_id)
        elif device.ssh_reachable:
            _ssh_resume_folder(device, folder_id, api_port)
        elif device.winrm_reachable:
            _winrm_resume_folder(device, folder_id, api_port)
        result.resumed = True
    except Exception as e:
        logger.error("Could not resume folder %s: %s — SYNC IS PAUSED", folder_id, e)


# ── Reliable path change ───────────────────────────────────────────────────────
# Syncthing IGNORES a folder's `path` on a config PUT (the field is locked in the
# web GUI for the same reason). So a path change can't go through update_folder_config.
# The reliable mechanism is delete + recreate the folder via the API — the exact
# same thing the (working) ID rename does. We keep the same folder ID, so peers see
# no new-folder share prompt, and set paused=false so the folder resumes.
#
# NOT used: editing config.xml + restarting. Syncthing rewrites config.xml from its
# in-memory config on shutdown, so a file edit made while it's running is silently
# overwritten — the symptom was "path unchanged + folder left paused".

def _norm_path(p: Optional[str]) -> str:
    """Normalize a path for COMPARISON only (every caller compares, none uses the result as a
    real path). Windows paths are case-insensitive and Syncthing may echo back a different
    drive-letter/component case than we sent — so casefold Windows-style paths (drive letter or
    backslash) to avoid a spurious 'path didn't apply' failure. POSIX paths stay case-sensitive."""
    raw = str(p or "")
    s = raw.replace("\\", "/").rstrip("/")
    if "\\" in raw or re.match(r"[A-Za-z]:", s):
        s = s.casefold()
    return s


def _path_already_at(stored: str, wanted: str) -> bool:
    """True if a folder already sits at `wanted`. Handles the tilde case: a NEW folder's wanted
    path defaults to '~/Label', but Syncthing stores it EXPANDED ('/home/pi/Label') — and we
    can't expand '~' here (it's the REMOTE user's home). So a tilde path matches when the stored
    path's tail equals the part after '~/'. Without this, a re-run sees '~/Nuevo' != '/home/pi/
    Nuevo' and does a needless destructive delete+recreate of an already-correct folder."""
    ns, nw = _norm_path(stored), _norm_path(wanted)
    if ns == nw:
        return True
    w = (wanted or "").replace("\\", "/")
    if w.startswith("~/"):
        tail = _norm_path(w[2:])
        return bool(tail) and (ns == tail or ns.endswith("/" + tail))
    return False


def _recreate_via_ssh(device: DeviceInfo, folder_id: str, new_label: str,
                      new_path: str, api_port: int) -> None:
    """Path change on an SSH-reachable device via the SSH-proxied API: delete the
    folder then recreate it (same id, new path, paused=false). Rolls back on failure."""
    api_key = device.api_key or ""
    ssh = _ssh_client(device)
    with ssh:
        old_cfg = ssh.syncthing_api_get(rest_folder_path(folder_id), api_key, api_port)
        new_cfg = dict(old_cfg)
        new_cfg["label"] = new_label
        new_cfg["path"] = new_path
        new_cfg["paused"] = False
        # Snapshot before the destructive delete so a crash in the delete→create gap is
        # recoverable (parity with the direct-API path).
        _rec = _save_id_rename_recovery(device.name, folder_id, old_cfg)
        ssh.syncthing_api_delete(rest_folder_path(folder_id), api_key, api_port)
        try:
            ssh.syncthing_api_post("/rest/config/folders", api_key, api_port, body=new_cfg)
            _clear_id_rename_recovery(_rec)   # new folder exists → destructive window closed
        except SSHError:
            try:
                ssh.syncthing_api_post("/rest/config/folders", api_key, api_port, body=old_cfg)
                _clear_id_rename_recovery(_rec)
            except SSHError as e2:
                raise SSHError(
                    _T("¡CONFIG DE CARPETA PERDIDA! «{}» (SSH): se borró para recrearla "
                       "y ni la nueva ni la original pudieron volver a crearse. Los datos en disco "
                       "siguen intactos — vuelve a añadir la carpeta en Syncthing").format(folder_id)
                    + (_T(" (config original guardada en {})").format(_rec) if _rec else "")
                    + _T(". Causa: {}").format(e2)
                ) from e2
            raise
        # The recreate POST already succeeded → the folder exists at new_path. CONFIRM the path,
        # but a TRANSIENT failure while confirming (Syncthing briefly reloads config right after a
        # delete+create) must NOT propagate: it would reach rename_on_device's except and trigger
        # _attempt_revert, moving the disk back to old_path while the config now points at new_path
        # (broken folder, recovery snapshot already cleared). Trust the POST on a transient verify
        # error; only a CONFIRMED path mismatch is a real failure.
        try:
            check = ssh.syncthing_api_get(rest_folder_path(folder_id), api_key, api_port)
        except SSHError as e:
            logger.warning("Recreate verify (SSH) failed transiently on %s (%s) — assuming applied",
                           device.name, e)
            return
        if isinstance(check, dict) and _norm_path(check.get("path")) != _norm_path(new_path):
            raise SSHError(_T("La ruta no se aplicó al recrear la carpeta (SSH)"))


def _recreate_via_winrm(device: DeviceInfo, folder_id: str, new_label: str,
                        new_path: str, api_port: int) -> None:
    """Path change on a WinRM-reachable Windows device via the WinRM-proxied API."""
    api_key = device.api_key or ""
    winrm = WinRMClient(host=device.ip, user=device.winrm_user,
                        password=device.winrm_password, port=device.winrm_port)
    with winrm:
        old_cfg = winrm.syncthing_api_get(rest_folder_path(folder_id), api_key, api_port)
        # ConvertTo-Json collapses single-element arrays — re-wrap before POSTing back.
        if isinstance(old_cfg.get("devices"), dict):
            old_cfg["devices"] = [old_cfg["devices"]]
        new_cfg = dict(old_cfg)
        new_cfg["label"] = new_label
        new_cfg["path"] = new_path
        new_cfg["paused"] = False
        # Snapshot before the destructive delete so a crash in the delete→create gap is
        # recoverable (parity with the direct-API path).
        _rec = _save_id_rename_recovery(device.name, folder_id, old_cfg)
        winrm.syncthing_api_delete(rest_folder_path(folder_id), api_key, api_port)
        try:
            winrm.syncthing_api_post("/rest/config/folders", api_key, api_port, body=new_cfg)
            _clear_id_rename_recovery(_rec)   # new folder exists → destructive window closed
        except WinRMError:
            try:
                winrm.syncthing_api_post("/rest/config/folders", api_key, api_port, body=old_cfg)
                _clear_id_rename_recovery(_rec)
            except WinRMError as e2:
                raise WinRMError(
                    _T("¡CONFIG DE CARPETA PERDIDA! «{}» (WinRM): se borró para recrearla "
                       "y ni la nueva ni la original pudieron volver a crearse. Los datos en disco "
                       "siguen intactos — vuelve a añadir la carpeta en Syncthing").format(folder_id)
                    + (_T(" (config original guardada en {})").format(_rec) if _rec else "")
                    + _T(". Causa: {}").format(e2)
                ) from e2
            raise
        # Transient verify failure must not trigger the caller's disk revert (see _recreate_via_ssh).
        try:
            check = winrm.syncthing_api_get(rest_folder_path(folder_id), api_key, api_port)
        except WinRMError as e:
            logger.warning("Recreate verify (WinRM) failed transiently on %s (%s) — assuming applied",
                           device.name, e)
            return
        if isinstance(check, dict) and _norm_path(check.get("path")) != _norm_path(new_path):
            raise WinRMError(_T("La ruta no se aplicó al recrear la carpeta (WinRM)"))


def _change_path_via_recreate(client: SyncthingClient, folder_id: str,
                              new_label: str, new_path: str, dev_name: str = "") -> None:
    """Delete + recreate the folder (same id, new path) via the direct API.
    Re-scans the folder, but the on-disk data is intact so it's a re-hash, not a
    re-download. Rolls back to the original config if recreation fails."""
    folder = client.get_folder(folder_id)
    if folder is None:
        raise SyncthingError(f"Folder {folder_id} not found", status_code=404)
    old_config = dict(folder.raw)
    new_config = dict(folder.raw)
    new_config["label"] = new_label
    new_config["path"] = new_path
    new_config["paused"] = False
    # Snapshot the original config to disk BEFORE the destructive delete (parity with the
    # ID-rename path): if the process is killed in the delete→create gap, the in-process
    # rollback can't run, and this file is the only way to recover the folder's membership/
    # role/versioning config.
    _rec = _save_id_rename_recovery(dev_name or "device", folder_id, old_config)
    client.delete_folder(folder_id)
    try:
        client.create_folder(new_config)
        # The new folder now exists → the destructive delete→create window is closed and the
        # folder is no longer at risk of being lost. Clear the snapshot here so a later
        # verify failure (folder exists, just at an unexpected path) doesn't leak a stale file.
        _clear_id_rename_recovery(_rec)
    except SyncthingError:
        try:
            client.create_folder(old_config)  # rollback so the folder is never lost
            _clear_id_rename_recovery(_rec)    # original restored — snapshot no longer needed
        except SyncthingError as e2:
            raise SyncthingError(
                _T("¡CONFIG DE CARPETA PERDIDA! «{}»: se borró para recrearla y "
                   "ni la nueva ni la original pudieron volver a crearse. Los datos en disco "
                   "siguen intactos — vuelve a añadir la carpeta en Syncthing").format(folder_id)
                + (_T(" (config original guardada en {})").format(_rec) if _rec else "")
                + _T(". Causa: {}").format(e2)
            ) from e2
        raise
    # Transient verify failure must not trigger the caller's disk revert (see _recreate_via_ssh).
    # get_folder returns None ONLY on 404 (folder genuinely vanished = real failure) and RAISES on
    # a transient blip → swallow the transient and trust the POST that already succeeded.
    try:
        updated = client.get_folder(folder_id)
    except SyncthingError as e:
        logger.warning("Recreate verify (API) failed transiently for %s (%s) — assuming applied",
                       folder_id, e)
        return
    if updated is None or _norm_path(updated.path) != _norm_path(new_path):
        raise SyncthingError(_T("La ruta no se aplicó al recrear la carpeta"))


def _update_config_legacy(
    device: DeviceInfo,
    folder_id: str,
    new_label: str,
    new_path: str,
) -> bool:
    """
    Fallback for Syncthing < 1.12: edit config.xml directly and restart.

    Returns True if the service restart was confirmed to succeed (so the folder
    is guaranteed to come back up unpaused), False if the restart could not be
    confirmed (caller should then attempt an explicit resume / report honestly).
    """
    def _patch_xml(xml_content: str) -> bytes:
        # Defend against entity-expansion DoS / XXE from a malicious peer's config.xml: reject
        # any DTD/DOCTYPE before parsing (Syncthing config.xml never has one).
        if re.search(r"<!\s*(DOCTYPE|ENTITY)", xml_content or "", re.I):
            raise SSHError(_T("config.xml remoto con DTD/ENTITY rechazado (posible expansión maliciosa)"))
        parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
        root = ET.fromstring(xml_content.encode(), parser=parser)
        updated = False
        for folder_el in root.findall("folder"):
            if folder_el.get("id") == folder_id:
                folder_el.set("label", new_label)
                folder_el.set("path", new_path)
                updated = True
                break
        if not updated:
            raise SSHError(f"Folder {folder_id} not found in config.xml")
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    if device.is_local:
        if platform.system() == "Windows":
            candidates = []
            for env_var in ("LOCALAPPDATA", "APPDATA"):
                base = os.environ.get(env_var, "")
                if base:
                    candidates.append(os.path.join(base, "Syncthing", "config.xml"))
            config_path = next((p for p in candidates if os.path.exists(p)), None)
            if not config_path:
                tried = ", ".join(candidates) or "(no LOCALAPPDATA/APPDATA set)"
                raise SSHError(f"Local config.xml not found — tried: {tried}")
        else:
            config_path = find_local_config_path()
            if not config_path:
                raise SSHError("Local Syncthing config.xml not found — check Syncthing installation")

        with open(config_path, encoding="utf-8") as f:
            xml_content = f.read()
        new_xml_bytes = _patch_xml(xml_content)
        # Atomic write: write to a sibling temp file then os.replace() to avoid
        # leaving config.xml empty/corrupt if the process is killed mid-write.
        config_dir = os.path.dirname(config_path)
        tmp_fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "wb") as f:
                f.write(new_xml_bytes)
            os.replace(tmp_path, config_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        # Restart Syncthing without a shell: try the per-user unit first, then the
        # system unit for this account. List-form argv means the username is passed as a
        # single argument (no shell parsing), so an unusual account name can't be misread.
        _user = getpass.getuser()
        _devnull = subprocess.DEVNULL
        rc = subprocess.run(["systemctl", "--user", "restart", "syncthing"],
                            check=False, stdout=_devnull, stderr=_devnull).returncode
        if rc != 0:
            rc = subprocess.run(["systemctl", "restart", f"syncthing@{_user}"],
                                check=False, stdout=_devnull, stderr=_devnull).returncode
        if rc != 0:
            logger.warning("Local Syncthing restart command failed (rc=%s) — "
                           "folder may remain paused until manual restart", rc)
        return rc == 0
    else:
        if device.winrm_reachable:
            winrm = WinRMClient(host=device.ip, user=device.winrm_user,
                                password=device.winrm_password, port=device.winrm_port)
            with winrm:
                config_path = winrm.detect_syncthing_config_path()
                if not config_path:
                    raise SSHError("Could not find config.xml on remote Windows device")
                xml_content = winrm.read_file(config_path)
                new_xml_bytes = _patch_xml(xml_content)
                winrm.write_file(config_path, new_xml_bytes.decode("utf-8"))
                try:
                    winrm.restart_syncthing()
                    return True
                except WinRMError as e:
                    logger.warning("Remote Syncthing restart via WinRM failed on %s: %s",
                                   device.name, e)
                    return False
        else:
            # An API-only remote on Syncthing <1.12: there's no per-object config REST to PUT the
            # label, and no shell channel (SSH/WinRM) to edit config.xml. Opening an SSH client here
            # would fail with a misleading "Network error connecting" — be honest about the real gap.
            if not device.ssh_reachable:
                raise SyncthingError(
                    _T("{}: Syncthing <1.12 alcanzable solo por API y sin acceso SSH/WinRM "
                       "— actualiza Syncthing a ≥1.12 (o habilita SSH/WinRM) para renombrar la carpeta").format(device.name))
            # SSH path. The factory picks WindowsSSHClient for a Windows host (read/write_file +
            # detect work over PowerShell-SSH) and the POSIX SSHClient otherwise. Restart differs
            # per OS: Windows uses the PowerShell Restart-Service/Stop-Process path (no _exec on
            # WindowsSSHClient); POSIX uses systemctl over the raw exec.
            cli = _ssh_client(device)
            with cli:
                config_path = cli.detect_syncthing_config_path()
                if not config_path:
                    raise SSHError("Could not find config.xml on remote device")
                xml_content = cli.read_file(config_path)
                new_xml_bytes = _patch_xml(xml_content)
                cli.write_file(config_path, new_xml_bytes.decode("utf-8"))
                try:
                    if device.os_type == "windows":
                        cli.restart_syncthing()
                        return True
                    code, _, _ = cli._exec(
                        "systemctl --user restart syncthing 2>/dev/null || "
                        "systemctl restart syncthing@$(whoami) 2>/dev/null"
                    )
                    if code != 0:
                        logger.warning("Remote Syncthing restart on %s failed (rc=%s)",
                                       device.name, code)
                    return code == 0
                except Exception as e:
                    logger.warning("Remote Syncthing restart on %s failed: %s", device.name, e)
                    return False
