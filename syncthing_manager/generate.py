from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from .agent import CONFIG_FORMAT, MARKER_END, MARKER_START
from .i18n import t as _T
from .models import DeviceInfo

# Markers delimiting the agent templates EMBEDDED (appended) in the main executable, so a
# single .exe per OS can generate both Windows and Linux agents. Extracted lazily (only
# when generating) → no startup cost. The build scripts append these blobs post-build.
_EMBED_MARKERS = {
    "windows": (b"\n__STRENAME_TEMPL_WIN_START__\n", b"\n__STRENAME_TEMPL_WIN_END__\n"),
    "linux":   (b"\n__STRENAME_TEMPL_LIN_START__\n", b"\n__STRENAME_TEMPL_LIN_END__\n"),
    "macos":   (b"\n__STRENAME_TEMPL_MAC_START__\n", b"\n__STRENAME_TEMPL_MAC_END__\n"),
}

# OSes whose agent is arch-specific (no in-OS cross-arch emulation we can rely on for a native
# binary): a Linux ELF / macOS Mach-O built for amd64 won't run on arm64 and vice-versa, so the
# template must match the TARGET device's arch. Windows ships a single x64 template (Win11-on-ARM
# emulates x64). macOS has Rosetta 2 (arm can run x86), but we still prefer a native per-arch one.
_ARCH_SPECIFIC_OS = ("linux", "macos")
_embed_cache: dict = {}


def extract_embedded_template(target_os: str, exe_bytes: Optional[bytes] = None) -> Optional[Path]:
    """If a template for `target_os` is appended to the running exe (between its markers),
    write it to a temp file and return its path; else None. Lazy + cached. `exe_bytes` is
    an injection point for tests."""
    if exe_bytes is None and target_os in _embed_cache:
        return _embed_cache[target_os]
    data = exe_bytes
    if data is None:
        if not getattr(sys, "frozen", False):
            return None
        try:
            data = Path(sys.executable).read_bytes()
        except Exception:
            return None
    start, end = _EMBED_MARKERS[target_os]
    i = data.find(start)
    if i == -1:
        return None
    j = data.find(end, i + len(start))
    if j == -1:
        return None
    blob = data[i + len(start):j]
    import os as _os
    import tempfile
    ext = ".exe" if target_os == "windows" else ""
    fd, p = tempfile.mkstemp(prefix="st-agent-templ-", suffix=ext)
    try:
        with _os.fdopen(fd, "wb") as f:
            f.write(blob)
        if target_os != "windows":
            _os.chmod(p, 0o755)
    except Exception:
        return None
    if exe_bytes is None:
        _embed_cache[target_os] = Path(p)
    return Path(p)


def _build_embedded_block(config: dict, passphrase: Optional[str]) -> bytes:
    """Serialize the agent config for embedding. With a passphrase the block is
    encrypted (Fernet/PBKDF2, same scheme as saved credentials) so the Syncthing API
    key and any other secrets are NOT recoverable with `strings` on the binary; the
    agent prompts for the passphrase at run time. Without one it stays plaintext."""
    payload = json.dumps(config, ensure_ascii=False, indent=2).encode("utf-8")
    if not passphrase:
        return payload
    import base64
    import os as _os
    from .credentials import _derive_fernet
    salt = _os.urandom(16)
    token = _derive_fernet(passphrase, salt).encrypt(payload).decode()
    envelope = {
        "format": "encrypted-v1",
        "salt": base64.b64encode(salt).decode(),
        "blob": token,
    }
    return json.dumps(envelope).encode("utf-8")


def normalize_arch(machine: Optional[str] = None) -> str:
    """Normalize a machine string → 'amd64' | 'arm64' | 'armv7' | <raw lower>. With no
    argument, returns the CURRENT host's arch. Linux agents are arch-specific (Linux has no
    in-OS x86 emulation), so generation must pick the template matching the TARGET device;
    Windows ships a single x64 template (Windows 11 on ARM emulates x64)."""
    import platform
    m = (machine if machine is not None else platform.machine() or "").lower()
    if m in ("x86_64", "amd64", "x64"):
        return "amd64"
    if m in ("aarch64", "arm64", "armv8", "armv8l"):
        return "arm64"
    if m.startswith("armv7") or m.startswith("armv6") or m in ("armhf", "arm"):
        return "armv7"
    return m or "amd64"


def _template_names(target_os: str, target_arch: Optional[str]) -> list[str]:
    """Candidate template filenames, most-specific first. Arch refines the arch-specific OSes
    (Linux, macOS). For Linux/Windows the un-suffixed name is also tried (a native single-arch
    build, build_linux.sh / build_windows.bat, leaves it un-suffixed). macOS is the exception:
    the un-suffixed `syncthing-manager-agent-template` shipped in the Windows/Linux apps IS the
    Linux binary (CI copies linux-amd64 → plain), so a macOS request must NEVER fall back to it
    — only the arch-suffixed macOS names (build_macos.sh also writes those). With no explicit
    arch we try amd64 first (Intel; runs on Apple Silicon via Rosetta) then arm64."""
    ext = ".exe" if target_os == "windows" else ""
    names = []
    if target_os in _ARCH_SPECIFIC_OS and target_arch:
        names.append(f"syncthing-manager-agent-template-{target_os}-{normalize_arch(target_arch)}")
    if target_os == "macos":
        if not target_arch:
            names += [f"syncthing-manager-agent-template-macos-{a}" for a in ("amd64", "arm64")]
        return names  # never the un-suffixed (Linux/host) template
    if target_os == "linux" and sys.platform == "darwin":
        # On a macOS host the un-suffixed template is the macOS binary (CI copies the host build
        # → plain), NOT Linux — NEVER fall back to it, even for an explicit arch (a same-arch
        # request would otherwise keep the plain via the cross-arch check and mislabel a Mach-O as
        # a Linux agent). Use only arch-suffixed Linux names: the explicit arch (if any) was
        # already appended above; with no arch, try both.
        if not target_arch:
            names += [f"syncthing-manager-agent-template-linux-{a}" for a in ("amd64", "arm64")]
        return names
    names.append(f"syncthing-manager-agent-template{ext}")
    return names


def _template_search_bases(target_os: str) -> list[Path]:
    """Directories searched for a template, in priority order: the PyInstaller bundle dir
    (_MEIPASS, set in BOTH onefile and onedir builds), the running-exe dir (+ its per-OS
    subfolder), and the project dist/ (dev/CI, flat + per-OS subfolder)."""
    subdir = {"windows": "windows", "macos": "macos"}.get(target_os, "linux")
    bases: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bases.append(Path(meipass))
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        bases += [exe_dir, exe_dir / subdir]
    for base in (Path(__file__).parent.parent / "dist", Path.cwd() / "dist", Path.cwd()):
        bases += [base, base / subdir]
    return bases


def _find_agent_template(target_os: str, target_arch: Optional[str] = None) -> Optional[Path]:
    """Locate the pre-built agent template executable for an OS (+ arch for Linux).

    Generation never *runs* the template — it just appends the embedded config
    to its bytes — so a Windows host can produce a Linux agent (and vice versa)
    as long as the *other* OS's template is present next to it. We try the
    arch-specific name first and fall back to the un-suffixed one."""
    names = _template_names(target_os, target_arch)
    # A CROSS-arch request (an explicit arch that isn't THIS host's) must match the arch-specific
    # file ONLY — never the un-suffixed/appended template, which is the host's arch and would be
    # the WRONG architecture silently. Same-arch / no-arch requests may use the fallbacks.
    cross_arch = bool(target_os in _ARCH_SPECIFIC_OS and target_arch
                      and normalize_arch(target_arch) != normalize_arch())
    if cross_arch:
        names = [n for n in names if n != "syncthing-manager-agent-template"]
    for base in _template_search_bases(target_os):   # prefer the arch-specific file per location
        for name in names:
            p = base / name
            if p.exists():
                return p
    if cross_arch:
        return None
    # Fallback: a template embedded (appended) in the running exe, extracted lazily.
    return extract_embedded_template(target_os)


def _available_arches(target_os: str) -> list[str]:
    """Arches of `target_os` that have a DEDICATED template present (the un-suffixed fallback
    does NOT count). The GUI uses this to offer an 'also generate the other arch' choice only
    when the build actually carries it — never silently falling back to a wrong-arch template."""
    bases = _template_search_bases(target_os)
    suffix = ".exe" if target_os == "windows" else ""
    found = []
    for arch in ("amd64", "arm64"):
        name = f"syncthing-manager-agent-template-{target_os}-{arch}{suffix}"
        if any((base / name).exists() for base in bases):
            found.append(arch)
    return found


def available_linux_arches() -> list[str]:
    """Linux arches with a dedicated template present (see _available_arches)."""
    return _available_arches("linux")


def available_macos_arches() -> list[str]:
    """macOS arches with a dedicated template present (Intel amd64 / Apple-Silicon arm64)."""
    return _available_arches("macos")


def select_agent_builds(detected: set, has_undetected: bool, avail: list, base_arch: str):
    """Decide which agent binaries to build for an arch-specific OS (Linux/macOS) given the
    DETECTED CPU arches of the selected devices. The agent self-selects its device by Syncthing
    ID, so each build embeds every entry; we just need one binary per arch the devices run.

    Returns (build_base, extra_arches, uncovered):
      build_base   — also build the base-arch binary. It covers base-arch devices AND any device
                     whose arch we couldn't detect (has_undetected). Built ONLY when actually
                     needed — never as a blind fallback: if every detected device is a non-base
                     arch (covered by `extra`, or `uncovered` when no template exists), a base
                     binary would help no one, so it is skipped.
      extra_arches — sorted detected arches (≠ base) that HAVE an embedded template → arch-suffixed
                     builds.
      uncovered    — sorted detected arches with NO embedded template → can't be built here."""
    extra = sorted(a for a in detected if a in avail and a != base_arch)
    uncovered = sorted(a for a in detected if a not in avail and a != base_arch)
    build_base = has_undetected or (base_arch in detected)
    return build_base, extra, uncovered


def generate_multi_agent_file(
    entries: list[dict],
    target_os: str = "windows",
    output_dir: Optional[Path] = None,
    filename: Optional[str] = None,
    passphrase: Optional[str] = None,
    target_arch: Optional[str] = None,
) -> Path:
    """
    Generate a single agent executable covering multiple devices.

    Each entry in `entries` must be a dict with at minimum:
      device_id, device_name, folder_id, new_label, new_dir_name,
      old_path, api_key, api_url, skip_path_rename, dry_run

    The agent will probe the local Syncthing API on the target machine,
    verify the device ID, and apply only the matching config.

    Raises FileNotFoundError if the template is missing.
    Raises ValueError if entries list is empty.
    """
    if not entries:
        raise ValueError(_T("La lista de dispositivos está vacía."))

    template_path = _find_agent_template(target_os, target_arch)
    if template_path is None:
        arch_hint = f" ({normalize_arch(target_arch)})" if target_os in ("linux", "macos") and target_arch else ""
        raise FileNotFoundError(
            _T("Plantilla de agente {} no encontrada.\nCompílala con:\n"
               "  python -m PyInstaller build/agent_{}.spec").format(
                   f"{target_os}{arch_hint}", target_os)
        )

    seen: dict[str, dict] = {}
    for entry in entries:
        dev_id = entry["device_id"]
        if dev_id in seen:
            logger.warning(
                "Duplicate device_id %s in agent entries — keeping last occurrence (%s)",
                dev_id[:16], entry.get("device_name", "?"),
            )
        # `arch`/`arch_detected` are GUI-only hints (which template to build); the agent never
        # reads them, so keep them OUT of the embedded (encrypted) config — no dead payload.
        seen[dev_id] = {k: v for k, v in entry.items() if k not in ("arch", "arch_detected")}

    multi_config = {
        "format": CONFIG_FORMAT,
        "devices": seen,
    }

    template_bytes = template_path.read_bytes()
    config_bytes   = _build_embedded_block(multi_config, passphrase)
    output_bytes   = template_bytes + MARKER_START + config_bytes + MARKER_END

    ext = ".exe" if target_os == "windows" else ""
    out_name = filename or f"syncthing-manager-agent{ext}"
    out = (output_dir or Path.cwd()) / out_name

    out.write_bytes(output_bytes)
    if target_os != "windows":
        # 0700, not 0755: the bundle embeds the device's Syncthing API key (and, for a
        # multi-device agent, several). Owner-only rwx keeps a local user on the GENERATING
        # machine from reading the key out of the file; the owner can still run/scp it.
        out.chmod(0o700)

    return out


def generate_legacy_agent_file(
    device_name: str,
    folder_id: str,
    new_label: str,
    new_dir_name: str,
    old_path: str = "",
    api_key: str = "",
    api_url: str = "http://127.0.0.1:8384",
    skip_path_rename: bool = False,
    dry_run: bool = False,
    target_os: str = "windows",
    output_dir: Optional[Path] = None,
    filename: Optional[str] = None,
    new_folder_id: str = "",
    passphrase: Optional[str] = None,
    target_arch: Optional[str] = None,
) -> Path:
    """
    Generate a single-device agent without Syncthing device ID verification.
    Used when the target device ID is not known in advance (e.g. manual generation).
    The agent runs unconditionally on whatever machine it's executed on.
    """
    template_path = _find_agent_template(target_os, target_arch)
    if template_path is None:
        arch_hint = f" ({normalize_arch(target_arch)})" if target_os in ("linux", "macos") and target_arch else ""
        raise FileNotFoundError(
            _T("Plantilla de agente {} no encontrada.\nCompílala con:\n"
               "  python -m PyInstaller build/agent_{}.spec").format(
                   f"{target_os}{arch_hint}", target_os)
        )

    config = {
        "device_name": device_name,
        "folder_id": folder_id,
        "new_label": new_label,
        "new_dir_name": new_dir_name,
        "old_path": old_path,
        "api_key": api_key,
        "api_url": api_url,
        "skip_path_rename": skip_path_rename,
        "dry_run": dry_run,
        "rename_id": bool(new_folder_id and new_folder_id != folder_id),
        "new_folder_id": new_folder_id,
    }

    template_bytes = template_path.read_bytes()
    config_bytes   = _build_embedded_block(config, passphrase)
    output_bytes   = template_bytes + MARKER_START + config_bytes + MARKER_END

    ext = ".exe" if target_os == "windows" else ""
    safe = re.sub(r"[^\w-]", "_", device_name)
    out_name = filename or f"syncthing-manager-agent-{safe}{ext}"
    out = (output_dir or Path.cwd()) / out_name

    out.write_bytes(output_bytes)
    if target_os != "windows":
        # 0700, not 0755: the bundle embeds the device's Syncthing API key (and, for a
        # multi-device agent, several). Owner-only rwx keeps a local user on the GENERATING
        # machine from reading the key out of the file; the owner can still run/scp it.
        out.chmod(0o700)

    return out


def generate_agent_file(
    device: DeviceInfo,
    folder_id: str,
    new_label: str,
    new_dir_name: str,
    skip_path_rename: bool = False,
    dry_run: bool = False,
    target_os: str = "windows",
    output_dir: Optional[Path] = None,
    new_folder_id: str = "",
    passphrase: Optional[str] = None,
    target_arch: Optional[str] = None,
) -> Path:
    """
    Generate a one-shot agent executable for a single device.
    Convenience wrapper around generate_multi_agent_file().

    Raises FileNotFoundError if the template is missing.
    Raises ValueError if the device has no device_id or api_key.
    """
    if not device.device_id or device.device_id == "local-agent":
        raise ValueError(_T(
            "El dispositivo no tiene un ID de Syncthing conocido.\n"
            "Descúbrelo primero desde la pantalla de descubrimiento."
        ))
    if not device.api_key:
        raise ValueError(_T(
            "El dispositivo no tiene API Key.\n"
            "Edita sus credenciales antes de generar el agente."
        ))

    entry = {
        "device_id":       device.device_id,
        "device_name":     device.name,
        "folder_id":       folder_id,
        "new_label":       new_label,
        "new_dir_name":    new_dir_name,
        "old_path":        device.folder_path or "",
        "api_key":         device.api_key or "",
        "api_url":         device.api_url or "http://127.0.0.1:8384",
        "skip_path_rename": skip_path_rename,
        "dry_run":         dry_run,
        "rename_id":       bool(new_folder_id and new_folder_id != folder_id),
        "new_folder_id":   new_folder_id,
    }

    safe = re.sub(r"[^\w-]", "_", device.name)
    ext  = ".exe" if target_os == "windows" else ""
    filename = f"syncthing-manager-agent-{safe}{ext}"

    return generate_multi_agent_file(
        [entry],
        target_os=target_os,
        output_dir=output_dir,
        filename=filename,
        passphrase=passphrase,
        target_arch=target_arch,
    )


def agent_template_available(target_os: str = "windows", target_arch: Optional[str] = None) -> bool:
    return _find_agent_template(target_os, target_arch) is not None
