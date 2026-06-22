from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Optional

import yaml

from .i18n import t as _T
from .models import DeviceInfo

# Fields encrypted with the master password when present
_ENCRYPTED_FIELDS = ("ssh_password", "winrm_password", "api_key")


def default_credentials_path() -> Path:
    # Location resolved by the config module (portable-first; honours a user-chosen dir).
    from .config import credentials_path
    return credentials_path()


def needs_master_password() -> bool:
    """Return True if the saved credentials file contains encrypted fields."""
    path = default_credentials_path()
    if not path.exists():
        return False
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return bool(data.get("_salt"))
    except Exception:
        return False


def _derive_fernet(master_password: str, salt: bytes):
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(master_password.encode("utf-8")))
    return Fernet(key)


def _backup_corrupt_credentials(path: Path) -> None:
    """Preserve a credentials file we failed to parse before any later save overwrites it.

    load_credentials() returns [] on a parse error so the GUI/CLI keep working, but the
    very next save_credentials() does an atomic os.replace() that would destroy the original
    bytes — taking every stored SSH/WinRM password and API key with it. Copy the bad file to
    a timestamped sibling so a human can still recover (or repair) it. Best-effort: never let
    a backup failure mask the original read failure."""
    try:
        if not path.exists() or path.stat().st_size == 0:
            return
        import time
        backup = path.with_name(f"{path.name}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}")
        if not backup.exists():
            # Create the backup 0600 FROM THE START (the bad file holds secrets) rather than
            # shutil.copy2 — which copies the source's mode and leaves a world-readable window
            # if the source was ever looser than 0600.
            data = path.read_bytes()
            fd = os.open(str(backup), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            try:
                os.chmod(backup, 0o600)
            except OSError:
                pass
    except Exception:
        pass


def load_credentials(master_password: Optional[str] = None) -> list[dict]:
    """
    Load saved credentials.
    If the file has encrypted fields and master_password is provided, decrypt them.
    Raises ValueError on wrong master password.
    """
    path = default_credentials_path()
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        _backup_corrupt_credentials(path)
        return []

    # A hand-edited / partially-written file can parse to a non-dict (a bare list or
    # scalar). Treat that as corruption too: `data.get(...)` below would otherwise raise
    # AttributeError, and the next save_credentials() would silently overwrite a file the
    # user could still recover by hand. Preserve it before returning empty.
    if not isinstance(data, dict):
        _backup_corrupt_credentials(path)
        return []

    entries: list[dict] = list(data.get("devices", []))

    salt_b64 = data.get("_salt")
    if salt_b64 and master_password:
        from cryptography.fernet import InvalidToken
        salt = base64.b64decode(salt_b64)
        fernet = _derive_fernet(master_password, salt)
        for entry in entries:
            for field in _ENCRYPTED_FIELDS:
                enc_key = f"{field}_enc"
                if enc_key in entry:
                    try:
                        entry[field] = fernet.decrypt(entry[enc_key].encode()).decode()
                    except InvalidToken:
                        raise ValueError(
                            _T("Contraseña maestra incorrecta — no se pudieron descifrar las credenciales.")
                        )

    return entries


def save_credentials(
    devices: list[DeviceInfo],
    master_password: Optional[str] = None,
    allow_plaintext_downgrade: bool = False,
) -> Path:
    """
    Persist credentials for all non-local devices.
    If master_password is provided, ssh_password and api_key are encrypted (Fernet/PBKDF2).
    Without master_password those fields are stored in plaintext.
    The master password itself is never stored.

    Refuses (raises ValueError) to silently DOWNGRADE an already-encrypted store to plaintext:
    if the on-disk file is encrypted and this save would write real secrets without a master
    password, it aborts instead of dropping the encrypted blobs. Pass allow_plaintext_downgrade
    only from an explicit, user-confirmed "remove encryption" flow.
    """
    path = default_credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    if not master_password and not allow_plaintext_downgrade and path.exists():
        try:
            with open(path, encoding="utf-8") as _f:
                _existing = yaml.safe_load(_f) or {}
            _was_encrypted = isinstance(_existing, dict) and bool(_existing.get("_salt"))
        except Exception:
            _was_encrypted = False
        if _was_encrypted and any(
            (d.ssh_password or d.winrm_password or d.api_key)
            for d in devices if not d.is_local
        ):
            raise ValueError(_T(
                "El archivo de credenciales está cifrado; guardarlo ahora sin la contraseña "
                "maestra lo degradaría a texto plano. Proporciona la contraseña maestra para "
                "volver a guardarlo cifrado."
            ))

    fernet = None
    salt_b64 = None
    if master_password:
        salt = os.urandom(16)
        salt_b64 = base64.b64encode(salt).decode()
        fernet = _derive_fernet(master_password, salt)

    entries = []
    for d in devices:
        if d.is_local:
            continue
        entry: dict = {"device_id": d.device_id, "name": d.name}
        if d.ip:
            entry["ssh_host"] = d.ip
        if d.ssh_user:
            entry["ssh_user"] = d.ssh_user
        if d.ssh_key_path:
            entry["ssh_key_path"] = d.ssh_key_path
        if d.ssh_port != 22:
            entry["ssh_port"] = d.ssh_port
        if d.api_url:
            entry["api_url"] = d.api_url
        if d.folder_path:
            entry["folder_path"] = d.folder_path

        if d.winrm_user:
            entry["winrm_user"] = d.winrm_user
        if d.winrm_port != 5985:
            entry["winrm_port"] = d.winrm_port

        # Sensitive fields — encrypt if master password provided, else plaintext
        for field, value in (
            ("ssh_password", d.ssh_password),
            ("winrm_password", d.winrm_password),
            ("api_key", d.api_key),
        ):
            if not value:
                continue
            if fernet:
                entry[f"{field}_enc"] = fernet.encrypt(value.encode()).decode()
            else:
                entry[field] = value

        entries.append(entry)

    doc: dict = {}
    if salt_b64:
        doc["_salt"] = salt_b64
    doc["devices"] = entries

    # Pre-create with restricted permissions so the file is never world-readable,
    # even briefly. On Windows chmod is a no-op but we still try.
    try:
        path.touch(mode=0o600, exist_ok=True)
    except OSError:
        pass

    # Atomic write: serialise to a sibling temp file then os.replace() so an
    # interrupted write can never leave credentials.yml empty/corrupt.
    import tempfile
    serialized = yaml.dump(doc, default_flow_style=False, allow_unicode=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        try:
            os.chmod(tmp_path, 0o600)
        except OSError:
            pass
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(serialized)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass

    return path
