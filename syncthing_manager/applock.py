"""Optional app lock (#Part-2).

A DETERRENT, not a security boundary: anyone who can read the local Syncthing config.xml
already holds the API key and can administer Syncthing directly, so no in-app password can
stop a filesystem-level attacker. The lock guards the casual case (app left open / a
bystander) and the destructive actions. Real at-rest security for SAVED credentials is the
separate credential-encryption master password (see credentials.py).

Two methods:
  • "custom"    — a password you set in the app; we store a salted PBKDF2 hash in settings.
  • "syncthing" — verify the typed password against Syncthing's GUI password (bcrypt hash in
                  config.xml). We store NO secret, only the chosen method.

Recovery (option A, agreed): deleting the "applock" entry in settings.json disables the lock
— a recovery path for a forgotten password, not a weakening (see module docstring rationale).
"""
from __future__ import annotations

import hashlib
import hmac
import os
import xml.etree.ElementTree as ET
from typing import Optional

from . import config as appconfig

_KEY = "applock"
_PBKDF2_ROUNDS = 200_000


# ── pure hashing (custom password) ───────────────────────────────────────────

def hash_password(password: str, salt: Optional[bytes] = None) -> tuple[str, str]:
    """Return (hash_hex, salt_hex) for a password using PBKDF2-HMAC-SHA256."""
    if salt is None:
        salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS)
    return dk.hex(), salt.hex()


def verify_password(password: str, hash_hex: str, salt_hex: str) -> bool:
    """Constant-time check of a password against a stored PBKDF2 hash."""
    try:
        salt = bytes.fromhex(salt_hex)
    except (ValueError, TypeError):
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS)
    return hmac.compare_digest(dk.hex(), hash_hex or "")


# ── Syncthing GUI password verification (bcrypt) ──────────────────────────────

def _read_syncthing_gui_password_hash(config_path: Optional[str] = None) -> Optional[str]:
    """Read the GUI password bcrypt hash from Syncthing's config.xml, or None if absent."""
    try:
        if config_path is None:
            from .discovery import find_local_config_path
            config_path = find_local_config_path()
        if not config_path or not os.path.exists(config_path):
            return None
        root = ET.parse(config_path).getroot()
        gui = root.find("gui")
        if gui is None:
            return None
        pw = gui.findtext("password")
        return pw.strip() if pw and pw.strip() else None
    except Exception:
        return None


def syncthing_has_gui_password(config_path: Optional[str] = None) -> bool:
    return _read_syncthing_gui_password_hash(config_path) is not None


def verify_syncthing_password(password: str, config_path: Optional[str] = None) -> bool:
    """Verify `password` against Syncthing's GUI bcrypt hash. False if no hash / mismatch."""
    h = _read_syncthing_gui_password_hash(config_path)
    if not h:
        return False
    try:
        import bcrypt
        return bcrypt.checkpw(password.encode("utf-8"), h.encode("utf-8"))
    except Exception:
        return False


# ── lock configuration (persisted in settings.json) ──────────────────────────

def get_lock() -> dict:
    """Current lock config: {method: 'off'|'custom'|'syncthing', hash, salt, inactivity_min}."""
    cfg = appconfig.get_setting(_KEY, None)
    if not isinstance(cfg, dict):
        return {"method": "off", "inactivity_min": 0}
    cfg.setdefault("method", "off")
    cfg.setdefault("inactivity_min", 0)
    return cfg


def _save_lock(cfg: dict) -> None:
    appconfig.set_setting(_KEY, cfg)


def is_enabled() -> bool:
    return get_lock().get("method", "off") in ("custom", "syncthing")


def method() -> str:
    return get_lock().get("method", "off")


def inactivity_minutes() -> int:
    try:
        return int(get_lock().get("inactivity_min", 0) or 0)
    except (TypeError, ValueError):
        return 0


def set_inactivity_minutes(minutes: int) -> None:
    cfg = get_lock()
    cfg["inactivity_min"] = max(0, int(minutes))
    _save_lock(cfg)


def set_custom_password(password: str) -> None:
    """Enable the lock with a custom app password (stored as a salted PBKDF2 hash)."""
    h, s = hash_password(password)
    cfg = get_lock()
    cfg.update({"method": "custom", "hash": h, "salt": s})
    _save_lock(cfg)


def set_syncthing_method() -> None:
    """Enable the lock using the Syncthing GUI password (no secret stored)."""
    cfg = get_lock()
    cfg.update({"method": "syncthing"})
    cfg.pop("hash", None)
    cfg.pop("salt", None)
    _save_lock(cfg)


def disable() -> None:
    """Turn the lock off (keeps the inactivity interval setting)."""
    cfg = get_lock()
    cfg.update({"method": "off"})
    cfg.pop("hash", None)
    cfg.pop("salt", None)
    _save_lock(cfg)


def verify(password: str, config_path: Optional[str] = None) -> bool:
    """Verify a password against the active lock method."""
    cfg = get_lock()
    m = cfg.get("method", "off")
    if m == "off":
        return True  # lock off → always "open"
    if m == "custom":
        return verify_password(password, cfg.get("hash", ""), cfg.get("salt", ""))
    if m == "syncthing":
        return verify_syncthing_password(password, config_path)
    # Enabled but the method is unrecognised (corrupt/tampered settings). Fail CLOSED —
    # never treat an unknown active method as "open", or a corrupted entry would bypass
    # the lock. To recover, delete the "applock" entry in settings.json (see module docs).
    return False
