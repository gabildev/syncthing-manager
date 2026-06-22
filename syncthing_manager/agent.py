from __future__ import annotations

import json
import platform
import queue
import sys
import threading
from typing import Optional

# Make the agent's console output UTF-8 (with replacement) as early as possible. The agent runs
# headless/console on Windows (tkinter is excluded from the agent build) and prints status with
# non-ASCII glyphs (✓, «», →, accents). On a Windows non-console / redirected stream that defaults
# to cp1252, those would raise UnicodeEncodeError and the agent would crash mid-apply. Same fix as
# cli.py; harmless where reconfigure isn't available.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from . import i18n
_T = i18n.t


def _init_agent_language() -> None:
    """Pick the agent's UI language: `--lang es|en` on the command line wins, else the
    SYNCTHING_MANAGER_LANG env var, else auto-detect from THIS machine's OS locale."""
    import os
    pref = None
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--lang" and i + 1 < len(argv):
            pref = argv[i + 1]
            break
        if a.startswith("--lang="):
            pref = a.split("=", 1)[1]
            break
    i18n.set_language(pref or os.environ.get("SYNCTHING_MANAGER_LANG"))


# Delimiters appended to the executable binary
MARKER_START = b"\n###SYNCTHING_AGENT_CONFIG_START###\n"
MARKER_END   = b"\n###SYNCTHING_AGENT_CONFIG_END###\n"

# Embedded config format version
CONFIG_FORMAT = "multi-device-v1"


# ── Config embedding / reading ────────────────────────────────────────────────

def read_embedded_config() -> Optional[dict]:
    """Read the JSON config block appended to this executable, if present."""
    exe_path = sys.executable if getattr(sys, "frozen", False) else __file__
    try:
        with open(exe_path, "rb") as f:
            data = f.read()
        start = data.find(MARKER_START)  # first occurrence — rfind would allow injected blocks
        if start == -1:
            return None
        start += len(MARKER_START)
        end = data.find(MARKER_END, start)
        if end == -1:
            return None
        return json.loads(data[start:end].decode("utf-8"))
    except Exception:
        return None


# ── Encrypted-config support ──────────────────────────────────────────────────

def _is_encrypted_config(config: Optional[dict]) -> bool:
    return isinstance(config, dict) and config.get("format") == "encrypted-v1"


def _decrypt_config(envelope: dict, passphrase: str) -> Optional[dict]:
    """Decrypt an 'encrypted-v1' envelope. Returns the inner config dict, or None if
    the passphrase is wrong / the data is malformed."""
    import base64
    try:
        from cryptography.fernet import InvalidToken
        from .credentials import _derive_fernet
    except Exception:
        return None
    try:
        salt = base64.b64decode(envelope["salt"])
        data = _derive_fernet(passphrase, salt).decrypt(envelope["blob"].encode())
        return json.loads(data.decode("utf-8"))
    except (InvalidToken, KeyError, ValueError, json.JSONDecodeError):
        return None


def _unlock_config(config: dict, gui: bool) -> Optional[dict]:
    """If the embedded config is encrypted, ask for the passphrase (up to 3 tries) and
    return the decrypted config. Returns None if the user cancels or all tries fail."""
    if not _is_encrypted_config(config):
        return config
    for attempt in range(3):
        if gui:
            pw = _prompt_passphrase_gui(attempt)
        else:
            pw = _prompt_passphrase_console(attempt)
        if pw is None:           # cancelled / EOF
            return None
        inner = _decrypt_config(config, pw)
        if inner is not None:
            return inner
    return None


def _prompt_passphrase_console(attempt: int) -> Optional[str]:
    import getpass
    prompt = (_T("Contraseña del agente (cifrado): ") if attempt == 0
              else _T("Contraseña incorrecta — reintenta: "))
    try:
        return getpass.getpass(prompt)
    except (EOFError, KeyboardInterrupt):
        return None


def _prompt_passphrase_gui(attempt: int) -> Optional[str]:
    import tkinter as tk
    from tkinter import simpledialog
    root = tk.Tk()
    root.withdraw()
    msg = (_T("Este agente está cifrado.\nIntroduce la contraseña:") if attempt == 0
           else _T("Contraseña incorrecta.\nReintenta:"))
    try:
        pw = simpledialog.askstring(_T("Agente cifrado"), msg, show="*", parent=root)
    finally:
        root.destroy()
    return pw


# ── Local API URL resolution ──────────────────────────────────────────────────

def _resolve_local_api_url(api_key: str, stored_url: Optional[str] = None) -> str:
    """
    Resolve the local Syncthing API URL on the machine the agent runs on.

    The agent always talks to 127.0.0.1, but the GUI may be served over http OR
    https (Syncthing's "Use HTTPS for GUI" is a single toggle). We only keep the
    port from the stored URL (which may carry an external IP) and probe both
    schemes, returning the first that answers. Falls back to http on failure.
    """
    import re as _re

    port = 8384
    if stored_url:
        host_part = stored_url.rstrip("/").split("//")[-1].split("/")[0]
        m = _re.search(r":(\d+)$", host_part)  # $ avoids IPv6 false matches
        if m:
            port = int(m.group(1))

    if api_key:
        from .syncthing import SyncthingClient
        for scheme in ("http", "https"):
            url = f"{scheme}://127.0.0.1:{port}"
            try:
                if SyncthingClient(url, api_key, verify_ssl=False).ping():
                    return url
            except Exception:
                pass
    return f"http://127.0.0.1:{port}"


# ── Device identity verification ──────────────────────────────────────────────

def get_local_device_id(api_url: str = "http://127.0.0.1:8384",
                         api_key: str = "") -> Optional[str]:
    """
    Query the local Syncthing API to get this machine's device ID.
    Returns None if Syncthing is not running or API key is wrong.
    """
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        import requests
        resp = requests.get(
            f"{api_url}/rest/system/status",
            headers={"X-API-Key": api_key},
            timeout=8,
            verify=False,
        )
        resp.raise_for_status()
        return resp.json().get("myID")
    except Exception:
        return None


def _find_matching_device(devices: dict[str, dict]) -> tuple[Optional[str], Optional[dict]]:
    """
    Probe local Syncthing to find which device config matches this machine.
    Returns (device_id, device_config) or (None, None).
    """
    from .discovery import read_local_api_key

    # Build list of (device_id, stored_url, api_key) to try. The stored URL is only
    # used for its PORT — the agent runs ON the target, so we must always probe
    # 127.0.0.1 (Syncthing binds localhost by default; the stored URL is usually the
    # external IP the controller saw and is unreachable from the device itself).
    candidates: list[tuple[str, Optional[str], str]] = []
    for dev_id, cfg in devices.items():
        candidates.append((dev_id, cfg.get("api_url"), cfg.get("api_key") or ""))

    # Also try auto-detected local API key (covers case where api_key was not saved)
    local_key = read_local_api_key() or ""

    for dev_id, stored_url, api_key in candidates:
        keys_to_try = [api_key, local_key] if local_key != api_key else [api_key]
        for key in keys_to_try:
            if not key:
                continue
            api_url = _resolve_local_api_url(key, stored_url)
            my_id = get_local_device_id(api_url, key)
            if my_id and my_id == dev_id:
                return dev_id, devices[dev_id]

    return None, None


# ── Core rename logic ─────────────────────────────────────────────────────────

def _write_agent_log(device_config: dict, success: bool, msg: str) -> None:
    """Append the outcome to a log file next to the agent executable (best-effort)."""
    try:
        import datetime
        import os
        base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.getcwd()
        logf = os.path.join(base, "syncthing-manager-agent.log")
        name = device_config.get("device_name", "?")
        folder = device_config.get("folder_id", "?")
        # 0600 on creation: the log records device names / folder ids (no secrets, but cluster
        # metadata) — keep it owner-only, consistent with the rest of the codebase's perms.
        fd = os.open(logf, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(
                f"[{datetime.datetime.now().isoformat(timespec='seconds')}] "
                f"{name} | folder={folder} | {'OK' if success else 'FALLO'} | "
                f"{msg.replace(chr(10), ' / ')}\n"
            )
    except Exception:
        pass


def run_agent(device_config: dict) -> tuple[bool, str]:
    """Run the rename and record the outcome to a log file beside the executable."""
    success, msg = _run_agent_impl(device_config)
    _write_agent_log(device_config, success, msg)
    return success, msg


def _run_agent_impl(device_config: dict) -> tuple[bool, str]:
    """
    Execute the rename locally using the given device config dict.
    Returns (success, human-readable message).
    """
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    from .discovery import read_local_api_key
    from .models import DeviceInfo
    from .renamer import rename_on_device

    folder_id     = device_config["folder_id"]
    new_label     = device_config["new_label"]
    new_dir_name  = device_config["new_dir_name"]
    old_path      = device_config.get("old_path") or ""
    skip_path     = device_config.get("skip_path_rename", False)
    dry_run       = device_config.get("dry_run", False)
    rename_id     = bool(device_config.get("rename_id"))
    new_folder_id = (device_config.get("new_folder_id") or "").strip()
    do_id_rename  = rename_id and new_folder_id and new_folder_id != folder_id

    # Prefer the LOCAL machine's own API key (read from its Syncthing config) over the
    # one embedded at generation time: the embedded key can belong to a different node
    # (e.g. the hub that introduced this device), which would 401 every API call and make
    # the path autodetection below silently fail → the disk rename gets skipped and only
    # the label changes (the "ruta vacía  →  /workspace" symptom). Fall back to embedded.
    api_key = read_local_api_key() or device_config.get("api_key")

    if not api_key:
        return False, _T(
            "No se pudo obtener la API Key de Syncthing.\n"
            "Asegúrate de que Syncthing está en ejecución."
        )

    # Always use localhost — the agent runs ON the target machine. We keep only
    # the port from the stored URL and probe http/https to handle TLS-enabled GUIs.
    api_url = _resolve_local_api_url(api_key, device_config.get("api_url"))

    # Idempotency for ID renames: if the old folder is gone but the new one exists,
    # this machine was already migrated — re-running the agent is a no-op.
    if do_id_rename:
        try:
            from .syncthing import SyncthingClient
            _c = SyncthingClient(api_url, api_key, verify_ssl=False)
            if _c.get_folder(folder_id) is None and _c.get_folder(new_folder_id) is not None:
                return True, _T("✓ Ya migrado al ID «{}» (nada que hacer)").format(new_folder_id)
        except Exception:
            pass

    # New-device create: if the topology marks THIS device as new and the folder
    # doesn't exist locally, there's nothing to rename — create it directly from the
    # topology (edit config, no accept prompt).
    topo_data = device_config.get("topology")
    if topo_data:
        from .renamer import deserialize_topology
        _topo = deserialize_topology(topo_data)
        _node = _topo["nodes"].get(device_config.get("device_id", "")) if _topo else None
        if _node and _node.get("is_new"):
            eff_fid = new_folder_id if do_id_rename else folder_id
            try:
                from .syncthing import SyncthingClient
                _c = SyncthingClient(api_url, api_key, verify_ssl=False)
                exists = (_c.get_folder(eff_fid) is not None
                          or _c.get_folder(folder_id) is not None)
            except Exception:
                exists = True  # play safe → fall through to the normal rename path
            if not exists:
                if dry_run:
                    return True, _T("[DRY RUN] crearía la carpeta «{}» (topología)").format(eff_fid)
                from .renamer import apply_topology_on_device
                dev = DeviceInfo(
                    device_id=device_config.get("device_id", "local-agent"),
                    name=device_config.get("device_name", platform.node()),
                    ip="127.0.0.1", api_url=api_url, api_key=api_key, folder_path=None,
                    ssh_reachable=False, api_reachable=True, is_local=True)
                tr = apply_topology_on_device(dev, eff_fid, _topo,
                                              folder_label=new_label, dry_run=False)
                return tr.ok, ((_T("✓ Carpeta creada (topología): ") + tr.message) if tr.ok
                               else (_T("✗ Error creando carpeta: ") + tr.message))

    # Autodetect the current folder path from the local API when it wasn't supplied
    # (e.g. the device was offline during discovery). Without this the disk rename
    # would be silently skipped and only the label would change.
    autodetect_err = ""
    if not old_path and not skip_path:
        try:
            from .syncthing import SyncthingClient
            _c = SyncthingClient(api_url, api_key, verify_ssl=False)
            live = _c.get_folder(folder_id)
            # The folder may already carry the new id (a partially-applied prior run), or
            # the embedded id may differ — fall back to matching any folder by id.
            if live is None and do_id_rename:
                live = _c.get_folder(new_folder_id)
            if live and live.path:
                old_path = live.path
            elif live is None:
                autodetect_err = _T("no se encontró la carpeta «{}» en este Syncthing "
                                    "(¿API Key correcta? ¿es el equipo adecuado?)").format(folder_id)
            else:
                autodetect_err = _T("la carpeta no reporta ruta en disco")
        except Exception as e:
            autodetect_err = _T("no se pudo consultar la API local: {}").format(e)
    # If we still don't know the path and a path change was requested, do NOT silently
    # fall through to a label-only change — tell the user why the disk wasn't renamed.
    if not old_path and not skip_path:
        return False, _T(
            "✗ No se pudo determinar la ruta en disco de la carpeta, así que NO se renombró "
            "el directorio (solo se habría cambiado el label).\n"
            "Motivo: {}.\n"
            "Comprueba que Syncthing está en ejecución en este equipo y que tiene la carpeta."
        ).format(autodetect_err or _T("ruta desconocida"))

    device = DeviceInfo(
        device_id=device_config.get("device_id", "local-agent"),
        name=device_config.get("device_name", platform.node()),
        ip="127.0.0.1",
        api_url=api_url,
        api_key=api_key,
        folder_path=old_path or None,
        ssh_reachable=False,
        api_reachable=True,
        is_local=True,
    )

    result = rename_on_device(
        device=device,
        folder_id=folder_id,
        new_label=new_label,
        new_dir_name=new_dir_name,
        dry_run=dry_run,
        skip_path_rename=skip_path,
    )

    if result.success:
        parts = []
        if result.dir_renamed and not skip_path:
            parts.append(_T("directorio renombrado"))
        if result.config_updated:
            parts.append(_T("config actualizada"))
        if result.resumed:
            parts.append(_T("sync reanudada"))
        suffix = " [DRY RUN]" if dry_run else ""

        # Propagate the folder-ID rename locally (delete old + create new via the local API).
        # Gate on config_updated (NOT just success): a `skipped_absent` result is success=True
        # but config_updated=False (folder not on this device) — renaming an absent folder's ID
        # would fail and wrongly mark the whole agent run failed. GUI/CLI passive both gate the
        # same way.
        if do_id_rename and result.config_updated:
            from .renamer import rename_folder_id
            id_res = rename_folder_id([device], folder_id, new_folder_id, dry_run=dry_run)
            ok = bool(id_res and id_res[0][1])
            if ok:
                parts.append(_T("ID → «{}»").format(new_folder_id))
            else:
                detail = id_res[0][2] if id_res else _T("sin resultado")
                return False, (
                    _T("⚠ Rename aplicado, pero el cambio de ID falló") + suffix +
                    _T(": {}\n(hecho: {})").format(detail, ", ".join(parts))
                )

        # Track sub-step failures so the boolean result reflects them. A failed
        # topology/folder-config/names apply must NOT be reported as overall success:
        # the rename landed but the device is in a half-applied state, and the caller
        # (GUI/CLI passive) needs success=False to retry it instead of marking it done.
        substep_failed = False

        # Apply topology locally by editing this device's config directly (no accept
        # needed). Embedded only when the user made topology edits.
        topo_data = device_config.get("topology")
        if topo_data and not dry_run:
            from .renamer import (deserialize_topology, deserialize_topology_diff,
                                  apply_topology_on_device)
            topo = deserialize_topology(topo_data)
            # Apply ONLY the user's diff (non-destructive). A None diff means "no membership/
            # role/link change" — NEVER fall through to apply_topology_on_device(diff=None), which
            # runs the legacy FULL REWRITE and would DROP this folder's peers that aren't nodes in
            # the (folder-scoped) editor graph. The GUI direct path always passes a real diff; the
            # agent must not be the one place that rewrites membership destructively. (topology is
            # embedded whenever the delta is non-empty — e.g. a lone new unlinked node — but the
            # diff serializes to None then, which previously triggered the rewrite here.)
            diff = deserialize_topology_diff(device_config.get("topology_diff"))
            if diff is not None and topo and topo.get("nodes", {}).get(device.device_id):
                eff_fid = new_folder_id if do_id_rename else folder_id
                tr = apply_topology_on_device(device, eff_fid, topo, diff=diff,
                                              folder_label=new_label, dry_run=False)
                parts.append((_T("topología: ") + tr.message) if tr.ok
                             else (_T("topología FALLÓ: ") + tr.message))
                substep_failed = substep_failed or not tr.ok

        # Advanced folder-config overrides embedded for this device (#55).
        fcfg_ov = device_config.get("fcfg")
        if fcfg_ov and not dry_run:
            from .renamer import apply_folder_cfg_on_device
            eff_fid = new_folder_id if do_id_rename else folder_id
            fr = apply_folder_cfg_on_device(device, eff_fid, fcfg_ov, dry_run=False)
            parts.append((_T("config carpeta: ") + fr.message) if fr.ok
                         else (_T("config carpeta FALLÓ: ") + fr.message))
            substep_failed = substep_failed or not fr.ok

        # Canonical device names to write into THIS machine's local config (item 1).
        names_map = device_config.get("names")
        if names_map and not dry_run:
            try:
                from .syncthing import SyncthingClient, rest_device_path
                _c = SyncthingClient(api_url, api_key, verify_ssl=False)
                changed = 0
                for d in _c.get_config_devices():
                    want = names_map.get(d.device_id)
                    if want and want != d.name:
                        raw = _c._get(rest_device_path(d.device_id))
                        raw["name"] = want
                        _c._put(rest_device_path(d.device_id), json=raw)
                        changed += 1
                parts.append(_T("nombres: {} actualizado(s)").format(changed))
            except Exception as e:
                parts.append(_T("nombres FALLÓ: {}").format(e))
                substep_failed = True

        if substep_failed:
            return False, (_T("⚠ Rename aplicado, pero falló un paso posterior") + suffix +
                           ": " + ", ".join(parts))
        return True, _T("✓ Completado") + suffix + ": " + ", ".join(parts)
    elif result.left_paused:
        return False, _T(
            "⚠ Error — sync PAUSADA: {}\n\n"
            "Reanuda manualmente desde la interfaz web de Syncthing."
        ).format(result.error)
    else:
        return False, _T("✗ Error: {}").format(result.error)


# ── Entry points ──────────────────────────────────────────────────────────────

def run_agent_main(gui: bool = False) -> None:
    """Called from the agent executable entry points."""
    _init_agent_language()
    # Degrade to console if a GUI was requested but tkinter isn't available (headless
    # box, minimal Python) — better a console run than crashing on import.
    if gui:
        import importlib.util
        if importlib.util.find_spec("tkinter") is None:
            gui = False

    config = read_embedded_config()

    if config is None:
        msg = _T(
            "Este es el agente de Syncthing Rename.\n\n"
            "Este ejecutable debe generarse con:\n"
            "  syncthing-manager generate-agent\n\n"
            "No ejecutes este archivo directamente."
        )
        if gui:
            _show_simple_dialog(False, msg)
        else:
            print(msg, file=sys.stderr)
        sys.exit(1)

    # Encrypted config → ask for the passphrase before doing anything else.
    if _is_encrypted_config(config):
        config = _unlock_config(config, gui)
        if config is None:
            msg = _T("Contraseña incorrecta o cancelada — no se pudo descifrar el agente.")
            if gui:
                _show_simple_dialog(False, msg)
            else:
                print(msg, file=sys.stderr)
            sys.exit(1)

    # Multi-device format: find matching device by Syncthing device ID
    if config.get("format") == CONFIG_FORMAT:
        devices = config.get("devices", {})
        if not devices:
            msg = _T("El agente no contiene dispositivos configurados.")
            if gui:
                _show_simple_dialog(False, msg)
            else:
                print(msg, file=sys.stderr)
            sys.exit(1)

        if gui:
            _run_gui_detecting(devices)
        else:
            _run_console_detecting(devices)
    else:
        # Legacy single-device format (backward compat)
        device_name = config.get("device_name", platform.node())
        if gui:
            _run_gui(config, device_name)
        else:
            _run_console(config, device_name)


def _run_console_detecting(devices: dict) -> None:
    n = len(devices)
    names = ", ".join(cfg.get("device_name", did[:8]) for did, cfg in devices.items())
    print(_T("Syncthing Rename Agent — {} dispositivo(s): {}").format(n, names))
    print(_T("Identificando este equipo…"))

    dev_id, device_config = _find_matching_device(devices)
    if device_config is None:
        print(
            _T("\n✗  Este dispositivo no está en la lista de pendientes.\n"
            "   IDs configurados:\n") +
            "".join(f"   • {did[:20]}… ({cfg.get('device_name', '?')})\n"
                    for did, cfg in devices.items()),
            file=sys.stderr,
        )
        sys.exit(1)

    _run_console(device_config, device_config.get("device_name", platform.node()))


def _is_already_applied(device_config: dict) -> tuple[bool, str]:
    """
    Check if the rename was already applied on this machine.
    Returns (already_done, description).
    """
    import os
    from .discovery import read_local_api_key
    from .syncthing import SyncthingClient, SyncthingError

    folder_id    = device_config.get("folder_id", "")
    new_label    = device_config.get("new_label", "")
    new_dir_name = device_config.get("new_dir_name", "")
    old_path     = device_config.get("old_path", "")

    new_folder_id = (device_config.get("new_folder_id") or "").strip()
    rename_id     = bool(device_config.get("rename_id")) and new_folder_id and new_folder_id != folder_id

    # Local-FIRST (same order as _run_agent_impl): the embedded api_key can belong to a DIFFERENT
    # node (the hub that introduced this device) and 401 every call — read the local one first.
    api_key = read_local_api_key() or device_config.get("api_key") or ""
    api_url = _resolve_local_api_url(api_key, device_config.get("api_url"))

    # Strategy 0: an ID rename was requested and the new folder already exists → migrated.
    if rename_id and api_key:
        try:
            client = SyncthingClient(api_url, api_key, verify_ssl=False)
            if client.get_folder(new_folder_id) is not None:
                return True, _T("Carpeta ya migrada al ID «{}»").format(new_folder_id)
        except SyncthingError:
            pass

    # Strategy 1: query local Syncthing — label + directory name already match
    if api_key and folder_id:
        try:
            client = SyncthingClient(api_url, api_key, verify_ssl=False)
            folder = client.get_folder(folder_id)
            if folder:
                label_ok = (folder.label == new_label)
                dir_ok   = (os.path.basename(folder.path.rstrip("/\\")) == new_dir_name)
                if label_ok and dir_ok:
                    return True, _T("Carpeta ya configurada: label='{}', ruta={}").format(new_label, folder.path)
        except SyncthingError:
            pass

    # Strategy 2: old path gone AND new path exists — avoid false positive if just deleted
    _new_dir = device_config.get("new_dir_name", "")
    if old_path and _new_dir and not os.path.exists(old_path):
        new_path = os.path.join(os.path.dirname(old_path), _new_dir)
        if new_path != os.path.dirname(old_path) and os.path.exists(new_path):
            return True, _T("La ruta original ya no existe y la nueva sí: {}").format(new_path)

    return False, ""


def _run_gui_detecting(devices: dict) -> None:
    import tkinter as tk
    from tkinter import ttk

    _FONT = "Segoe UI" if sys.platform == "win32" else "DejaVu Sans"

    root = tk.Tk()
    root.title("Syncthing Rename Agent")
    root.resizable(False, False)
    root.configure(bg="white")

    # ── Header ────────────────────────────────────────────────────────────────
    hdr = tk.Frame(root, bg="#1565C0")
    hdr.pack(fill=tk.X)
    hdr_inner = tk.Frame(hdr, bg="#1565C0")
    hdr_inner.pack(fill=tk.X, padx=14, pady=8)
    tk.Label(hdr_inner, text="Syncthing Rename Agent", bg="#1565C0", fg="white",
             font=(_FONT, 11, "bold")).pack(anchor="w")
    tk.Label(hdr_inner, text=_T("Agente para {} equipo(s)").format(len(devices)), bg="#1565C0",
             fg="#BBDEFB", font=(_FONT, 8)).pack(anchor="w")

    body = tk.Frame(root, bg="white", padx=16, pady=12)
    body.pack(fill=tk.BOTH, expand=True)

    # ── Phase 1: detecting ────────────────────────────────────────────────────
    detect_lbl = tk.Label(body, text=_T("Verificando identidad de este equipo…"),
                          bg="white", fg="#555", font=(_FONT, 9))
    detect_lbl.pack(anchor="w")

    pb = ttk.Progressbar(body, mode="indeterminate", length=400)
    pb.pack(fill=tk.X, pady=(6, 0))
    pb.start(12)

    # ── Phase 2: confirmation — shown after detection via result_lbl/confirm_btn ──
    result_lbl = tk.Label(body, text="", bg="white",
                          font=(_FONT, 9), wraplength=420, justify="left")
    result_lbl.pack(anchor="w", pady=(10, 4))

    btn_row = tk.Frame(body, bg="white")
    btn_row.pack(anchor="e")

    close_btn  = ttk.Button(btn_row, text=_T("Cerrar"), state="disabled", command=root.destroy)
    close_btn.pack(side=tk.RIGHT)
    confirm_btn = ttk.Button(btn_row, text=_T("Confirmar y ejecutar"), state="disabled")
    confirm_btn.pack(side=tk.RIGHT, padx=(0, 6))

    root.geometry("460x280")

    q: queue.Queue = queue.Queue()

    def drain():
        try:
            while True:
                q.get_nowait()()
        except queue.Empty:
            pass
        root.after(50, drain)

    def _do_execute(device_config: dict, device_name: str) -> None:
        """Called when user confirms — runs the rename."""
        confirm_btn.config(state="disabled")
        close_btn.config(state="disabled")
        result_lbl.config(text=_T("Ejecutando…"), fg="#555")

        def work():
            success, msg = run_agent(device_config)
            color = "#2E7D32" if success else "#C62828"
            def update():
                pb.stop()
                pb.config(mode="determinate", value=100 if success else 0)
                result_lbl.config(text=msg, fg=color)
                close_btn.config(state="normal")
            q.put(update)

        threading.Thread(target=work, daemon=True).start()

    def worker():
        dev_id, device_config = _find_matching_device(devices)

        if device_config is None:
            names = "\n".join(
                f"  • {cfg.get('device_name', did[:14] + '…')}"
                for did, cfg in devices.items()
            )
            msg = _T("Este equipo no está en la lista configurada.\n\nEquipos en el agente:\n{}").format(names)
            def _no_match():
                pb.stop()
                result_lbl.config(text=msg, fg="#C62828")
                close_btn.config(state="normal")
            q.put(_no_match)
            return

        device_name  = device_config.get("device_name", platform.node())
        folder_id    = device_config.get("folder_id", "?")
        new_label    = device_config.get("new_label", "?")
        new_dir_name = device_config.get("new_dir_name", "?")
        old_path     = device_config.get("old_path", "") or _T("(autodetectar)")

        # Check if already applied before showing confirmation
        already, already_msg = _is_already_applied(device_config)

        def _show_confirmation():
            pb.stop()
            detect_lbl.config(text=_T("Equipo identificado: {}").format(device_name), fg="#1565C0")

            if already:
                result_lbl.config(
                    text=_T("✓  Ya aplicado anteriormente.\n{}").format(already_msg),
                    fg="#2E7D32",
                )
                close_btn.config(state="normal")
                root.geometry("460x260")
                return

            # Show what will be done
            lines = [
                _T("Operación pendiente para este equipo:"),
                "",
                _T("  Carpeta (label):  {}  →  {}").format(folder_id, new_label),
                _T("  Directorio:       {}  →  {}").format(old_path, new_dir_name),
            ]
            result_lbl.config(text="\n".join(lines), fg="#333", font=(_FONT, 9))

            confirm_btn.config(
                state="normal",
                command=lambda: _do_execute(device_config, device_name),
            )
            close_btn.config(state="normal")
            root.geometry("460x300")

        q.put(_show_confirmation)

    threading.Thread(target=worker, daemon=True).start()
    root.after(50, drain)
    root.mainloop()


def _run_console(device_config: dict, device_name: str) -> None:
    print(f"Syncthing Rename Agent — {device_name}")
    print(_T("  Carpeta : {}  →  {}").format(device_config['folder_id'], device_config['new_label']))
    if not device_config.get("skip_path_rename"):
        print(_T("  Disco   : {}  →  {}").format(device_config.get('old_path', '?'), device_config['new_dir_name']))
    print()
    success, msg = run_agent(device_config)
    print(msg)
    sys.exit(0 if success else 1)


def _run_gui(device_config: dict, device_name: str) -> None:
    import tkinter as tk
    from tkinter import ttk

    q: queue.Queue = queue.Queue()

    root = tk.Tk()
    root.title(f"Syncthing Rename Agent — {device_name}")
    root.geometry("440x230")
    root.resizable(False, False)
    root.configure(bg="white")

    hdr = tk.Frame(root, bg="#1565C0", height=54)
    hdr.pack(fill=tk.X)
    hdr.pack_propagate(False)
    tk.Label(hdr, text="Syncthing Rename Agent", bg="#1565C0", fg="white",
             font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=14, pady=14)

    body = tk.Frame(root, bg="white", padx=16, pady=10)
    body.pack(fill=tk.BOTH, expand=True)

    tk.Label(body, text=_T("Dispositivo: {}").format(device_name), bg="white",
             font=("Segoe UI", 9, "bold")).pack(anchor="w")
    tk.Label(body,
             text=f"{device_config['folder_id']}  →  label: {device_config['new_label']}",
             bg="white", fg="#555", font=("Segoe UI", 8)).pack(anchor="w", pady=(2, 8))

    pb = ttk.Progressbar(body, mode="indeterminate")
    pb.pack(fill=tk.X)
    pb.start(12)

    result_lbl = tk.Label(body, text=_T("Ejecutando…"), bg="white",
                          font=("Segoe UI", 9), wraplength=400, justify="left")
    result_lbl.pack(anchor="w", pady=(8, 4))

    ok_btn = ttk.Button(body, text=_T("Cerrar"), state="disabled", command=root.destroy)
    ok_btn.pack(side=tk.BOTTOM, anchor="e")

    def drain():
        try:
            while True:
                q.get_nowait()()
        except queue.Empty:
            pass
        root.after(50, drain)

    def worker():
        success, msg = run_agent(device_config)
        color = "#2E7D32" if success else "#C62828"
        def update():
            pb.stop()
            pb.config(mode="determinate", value=100)
            result_lbl.config(text=msg, fg=color)
            ok_btn.config(state="normal")
        q.put(update)

    threading.Thread(target=worker, daemon=True).start()
    root.after(50, drain)
    root.mainloop()


def _show_simple_dialog(success: bool, msg: str) -> None:
    import tkinter as tk
    from tkinter import ttk
    root = tk.Tk()
    root.title("Syncthing Rename Agent")
    root.geometry("380x160")
    root.configure(bg="white")
    color = "#2E7D32" if success else "#C62828"
    tk.Label(root, text=msg, bg="white", fg=color, wraplength=340,
             font=("Segoe UI", 9), justify="left").pack(padx=20, pady=20)
    ttk.Button(root, text=_T("Cerrar"), command=root.destroy).pack(
        side=tk.BOTTOM, anchor="e", padx=20, pady=10)
    root.mainloop()
