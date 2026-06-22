"""App configuration & data directory.

Resolves WHERE the program keeps its data (credentials, settings) with a portable-first
policy that never strands a user's existing data:

  1. env override SYNCTHING_MANAGER_DATADIR, if set;
  2. a custom directory the user chose (a `.datadir` pointer file next to the exe or in
     the OS-standard location);
  3. an EXISTING install: if the OS-standard dir already has data, keep using it;
  4. fresh install: PORTABLE — next to the executable when frozen and writable;
  5. fallback: OS-standard (%APPDATA%/syncthing-manager or ~/.config/syncthing-manager).

Settings live in <data_dir>/settings.json; credentials in <data_dir>/credentials.yml.
"""
from __future__ import annotations

import copy
import json
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Optional

APP = "syncthing-manager"
_POINTER = ".datadir"            # holds a custom data-dir path, if the user set one
_DATA_FILES = ("credentials.yml", "settings.json")
_ENV = "SYNCTHING_MANAGER_DATADIR"


def app_dir() -> Optional[Path]:
    """Directory of the running executable when frozen (PyInstaller), else None
    (running from source → no portable location)."""
    if getattr(sys, "frozen", False):
        try:
            return Path(sys.executable).resolve().parent
        except Exception:
            return None
    return None


def os_standard_dir() -> Path:
    if platform.system() == "Windows":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return Path(base) / APP
    return Path.home() / ".config" / APP


def _writable(p: Path) -> bool:
    try:
        p.mkdir(parents=True, exist_ok=True)
        t = p / ".wtest"
        t.write_text("x")
        t.unlink()
        return True
    except Exception:
        return False


def _has_data(d: Path) -> bool:
    return any((d / f).exists() for f in _DATA_FILES)


def _read_pointer() -> Optional[Path]:
    for base in (app_dir(), os_standard_dir()):
        if not base:
            continue
        ptr = base / _POINTER
        try:
            if ptr.exists():
                val = ptr.read_text(encoding="utf-8").strip()
                if val:
                    return Path(val)
        except Exception:
            pass
    return None


def data_dir() -> Path:
    """Resolve the data directory (see module docstring for the policy)."""
    env = os.environ.get(_ENV)
    if env:
        return Path(env).expanduser()
    ptr = _read_pointer()
    if ptr:
        return ptr
    ad = app_dir()
    if ad and _has_data(ad):
        return ad                        # established portable (no writable re-test churn)
    std = os_standard_dir()
    if std.exists() and _has_data(std):
        return std                       # preserve an existing install
    if ad and _writable(ad):
        return ad                        # fresh install → portable
    return std


def is_portable() -> bool:
    ad = app_dir()
    try:
        return bool(ad) and data_dir().resolve() == ad.resolve()
    except Exception:
        return False


def credentials_path() -> Path:
    return data_dir() / "credentials.yml"


def settings_path() -> Path:
    return data_dir() / "settings.json"


# In-memory settings cache (write-through). settings.json is read on nearly every
# get_setting() — including per-device during a rename (prefer_secure_channel) and per SSH
# connect (ssh_strict_host_keys) — so re-reading+parsing the file each time is wasteful.
# We cache the parsed dict keyed by (path, mtime, size): a stat() validates freshness without
# re-parsing, save_settings refreshes the cache write-through, and an external edit is picked
# up because its mtime/size differ. Callers get a deep copy so they can never mutate the cache.
_settings_cache: Optional[dict] = None
_settings_cache_key: Optional[tuple] = None


def _settings_stat_key(p: Path) -> Optional[tuple]:
    try:
        st = p.stat()
        return (str(p), st.st_mtime_ns, st.st_size)
    except OSError:
        return (str(p), None, None)


def load_settings() -> dict:
    global _settings_cache, _settings_cache_key
    p = settings_path()
    key = _settings_stat_key(p)
    if _settings_cache is not None and _settings_cache_key == key:
        return copy.deepcopy(_settings_cache)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    _settings_cache, _settings_cache_key = data, key
    return copy.deepcopy(data)


def save_settings(settings: dict) -> None:
    global _settings_cache, _settings_cache_key
    p = settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    # settings.json can hold the app-lock PBKDF2 hash/salt. Write to a FRESH temp created 0600
    # from the start via mkstemp (unpredictable name → no symlink pre-plant, no stale-temp mode
    # reuse) and chmod 0600 BEFORE writing the secret, then os.replace() atomically. Mirrors
    # credentials.py exactly — the secret is never world-readable, not even in the write window.
    import tempfile
    serialized = json.dumps(settings, indent=2, ensure_ascii=False)
    fd, tmp_path = tempfile.mkstemp(dir=str(p.parent), suffix=".json.tmp")
    try:
        try:
            os.chmod(tmp_path, 0o600)
        except OSError:
            pass
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(serialized)
        os.replace(tmp_path, p)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    try:
        os.chmod(p, 0o600)   # belt-and-suspenders (no-op on Windows)
    except OSError:
        pass
    # Write-through: refresh the cache so the next read is served from memory and reflects
    # exactly what we just persisted. Deep-copy so a later mutation of `settings` can't bleed in.
    _settings_cache = copy.deepcopy(settings)
    _settings_cache_key = _settings_stat_key(p)


def get_setting(key: str, default=None):
    return load_settings().get(key, default)


def set_setting(key: str, value) -> None:
    s = load_settings()
    s[key] = value
    save_settings(s)


import re as _re


def _safe_folder_key(folder_id: str) -> str:
    """A filesystem-safe filename component for a folder ID (which can contain anything).

    For IDs that are already safe and short, return them verbatim (stable, backward-compatible
    snapshot filenames). When sanitisation would substitute a character or truncate, two
    distinct IDs could map to the same name and silently overwrite each other's snapshot —
    so append a short hash of the FULL id to disambiguate."""
    fid = folder_id or "default"
    safe = _re.sub(r"[^A-Za-z0-9_.-]", "_", fid)
    if safe == fid and len(fid) <= 120:
        return safe or "default"
    import hashlib
    h = hashlib.sha1(fid.encode("utf-8")).hexdigest()[:8]
    return (safe[:111] or "default") + "_" + h


def topology_snapshot_path(folder_id: str) -> Path:
    return data_dir() / "topology" / f"{_safe_folder_key(folder_id)}.json"


def load_topology_snapshot(folder_id: str) -> Optional[dict]:
    """Load the last-saved topology snapshot for a folder, or None if absent/unreadable."""
    try:
        return json.loads(topology_snapshot_path(folder_id).read_text(encoding="utf-8")) or None
    except Exception:
        return None


def save_topology_snapshot(folder_id: str, data: dict) -> None:
    """Persist a topology snapshot for a folder (atomic write). Best-effort: a write error
    must never break the rename flow, so callers wrap this and ignore failures."""
    p = topology_snapshot_path(folder_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def delete_topology_snapshot(folder_id: str) -> None:
    """Forget a folder's persisted topology snapshot. MUST be called when the folder is
    deleted from the cluster: otherwise re-creating a folder with the SAME id reloads the
    stale snapshot and resurrects nodes/links that no longer exist. Best-effort."""
    try:
        topology_snapshot_path(folder_id).unlink(missing_ok=True)
    except Exception:
        pass


def _write_pointer(target: Optional[Path]) -> None:
    """Persist (or clear) the custom-data-dir pointer where we can write it."""
    base = app_dir()
    if not (base and _writable(base)):
        base = os_standard_dir()
        base.mkdir(parents=True, exist_ok=True)
    ptr = base / _POINTER
    try:
        if target is None:
            if ptr.exists():
                ptr.unlink()
        else:
            ptr.write_text(str(target), encoding="utf-8")
    except Exception:
        pass


def set_data_dir(new_dir, move: bool = True) -> Path:
    """Relocate the data directory. Moves the known data files to `new_dir`, records the
    choice (pointer), and removes the old directory if it's left empty (no orphan)."""
    old = data_dir()
    new = Path(new_dir).expanduser()
    new.mkdir(parents=True, exist_ok=True)
    moved_from = None
    if old.resolve() != new.resolve():
        def _move_over(src, dst):
            # Windows shutil.move does NOT overwrite an existing destination file (raises
            # FileExistsError) — which would abort the relocation mid-way and split data across
            # the old and new dirs. Clear the way for the move, but DON'T just unlink dst: if the
            # move then fails (disk full, EXDEV, permissions) the destination data would be lost
            # with no rollback. Stash dst as a backup, move, and restore the backup on failure.
            backup = None
            if dst.exists():
                backup = dst.with_name(dst.name + ".bak-move")
                if backup.exists():
                    backup.unlink()
                dst.rename(backup)
            try:
                shutil.move(str(src), str(dst))
            except Exception:
                if backup is not None:
                    if dst.exists():
                        try:
                            dst.unlink()        # clear a partial move before restoring
                        except OSError:
                            pass
                    backup.rename(dst)          # put the original destination data back
                raise
            if backup is not None:
                try:
                    backup.unlink()
                except OSError:
                    pass

        if move:
            for name in _DATA_FILES:
                src = old / name
                if src.exists():
                    _move_over(src, new / name)
            # Per-folder topology snapshots live in a `topology/` SUBDIR — move it too, or
            # relocation silently orphans every remembered offline edge/role. Move file-by-file
            # (robust whether or not the destination subdir already exists), then drop the empty
            # old subdir so the old data dir can be cleaned up below.
            topo_src = old / "topology"
            if topo_src.is_dir():
                topo_dst = new / "topology"
                topo_dst.mkdir(parents=True, exist_ok=True)
                for snap in topo_src.iterdir():
                    _move_over(snap, topo_dst / snap.name)
                try:
                    topo_src.rmdir()
                except OSError:
                    pass
            moved_from = old
    # Pointer: only needed when the chosen dir isn't the natural default (portable app dir).
    ad = app_dir()
    if ad and new.resolve() == ad.resolve():
        ptr_base = None
        _write_pointer(None)             # portable default → no pointer needed
    else:
        _write_pointer(new)
        ptr_base = ad if (ad and _writable(ad)) else os_standard_dir()
    # Clean up an emptied old directory (no orphan under ~/.config etc.) — but never
    # delete the directory that now holds our pointer file.
    if moved_from is not None and (ptr_base is None
                                   or moved_from.resolve() != ptr_base.resolve()):
        try:
            stale_ptr = moved_from / _POINTER
            if stale_ptr.exists():
                stale_ptr.unlink()
            if moved_from.exists() and not any(moved_from.iterdir()):
                moved_from.rmdir()
        except Exception:
            pass
    return new
