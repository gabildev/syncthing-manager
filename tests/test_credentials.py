from __future__ import annotations

import pytest

from syncthing_manager import credentials as cred
from syncthing_manager.models import DeviceInfo

pytest.importorskip("cryptography")   # encrypted path needs Fernet/PBKDF2


def _dev(**kw) -> DeviceInfo:
    base = dict(
        device_id="DEV-1", name="nas", ip="192.168.1.20",
        api_url="http://192.168.1.20:8384", api_key="APIKEY123", folder_path=None,
        ssh_reachable=False, api_reachable=False, is_local=False,
        ssh_user="admin", ssh_password="s3cret",
    )
    base.update(kw)
    return DeviceInfo(**base)


@pytest.fixture
def cred_path(tmp_path, monkeypatch):
    """Point credentials I/O at a throwaway file (never the user's real one)."""
    p = tmp_path / "credentials.yml"
    monkeypatch.setattr(cred, "default_credentials_path", lambda: p)
    return p


class TestPlaintext:
    def test_saves_and_loads_plaintext_without_master_password(self, cred_path):
        cred.save_credentials([_dev()])
        assert cred.needs_master_password() is False
        e = cred.load_credentials()[0]
        assert e["ssh_password"] == "s3cret"
        assert e["api_key"] == "APIKEY123"
        assert "ssh_password_enc" not in e


class TestEncrypted:
    def test_roundtrip_with_master_password(self, cred_path):
        cred.save_credentials([_dev()], master_password="hunter2")
        assert cred.needs_master_password() is True
        e = cred.load_credentials(master_password="hunter2")[0]
        assert e["ssh_password"] == "s3cret"
        assert e["api_key"] == "APIKEY123"

    def test_wrong_master_password_raises(self, cred_path):
        cred.save_credentials([_dev()], master_password="hunter2")
        with pytest.raises(ValueError):
            cred.load_credentials(master_password="WRONG-pw")

    def test_secrets_never_plaintext_on_disk_when_encrypted(self, cred_path):
        cred.save_credentials([_dev()], master_password="hunter2")
        raw = cred_path.read_text()
        assert "s3cret" not in raw
        assert "APIKEY123" not in raw
        assert "_salt" in raw

    def test_load_without_password_does_not_expose_encrypted_secrets(self, cred_path):
        cred.save_credentials([_dev()], master_password="hunter2")
        e = cred.load_credentials()[0]            # no master password
        assert "ssh_password" not in e            # only the _enc form remains, undecrypted
        assert "ssh_password_enc" in e


class TestEdgeCases:
    def test_missing_file_returns_empty(self, cred_path):
        assert cred.load_credentials() == []
        assert cred.needs_master_password() is False

    def test_local_device_is_skipped(self, cred_path):
        cred.save_credentials([_dev(is_local=True)])
        assert cred.load_credentials() == []


class TestCorruptFileRecovery:
    """A corrupt/hand-broken credentials file must NOT crash and must be preserved before
    the next save overwrites it (otherwise every stored secret is silently lost)."""

    def test_non_dict_yaml_does_not_crash(self, cred_path):
        # A bare YAML list parses fine but is not a dict — data.get(...) would AttributeError.
        cred_path.write_text("- a\n- b\n")
        assert cred.load_credentials() == []        # graceful, no exception
        assert cred.needs_master_password() is False

    def test_invalid_yaml_does_not_crash(self, cred_path):
        cred_path.write_text("devices: [unterminated\n:::bad")
        assert cred.load_credentials() == []

    def test_corrupt_file_is_backed_up_before_overwrite(self, cred_path):
        cred_path.write_text("- not\n- a mapping\n")
        cred.load_credentials()                      # triggers the backup
        backups = list(cred_path.parent.glob(cred_path.name + ".corrupt-*"))
        assert backups, "corrupt credentials file should be preserved"
        assert "not" in backups[0].read_text()

    def test_empty_file_is_not_backed_up(self, cred_path):
        cred_path.write_text("")
        assert cred.load_credentials() == []
        assert not list(cred_path.parent.glob(cred_path.name + ".corrupt-*"))

    def test_corrupt_backup_is_0600(self, cred_path):
        import os
        import stat
        if os.name == "nt":
            pytest.skip("POSIX permission semantics")
        cred_path.write_text("- not\n- a mapping\n")
        cred.load_credentials()
        backup = next(iter(cred_path.parent.glob(cred_path.name + ".corrupt-*")))
        assert stat.S_IMODE(os.stat(backup).st_mode) == 0o600


class TestNoPlaintextDowngrade:
    """An encrypted credentials store must not be silently rewritten as plaintext."""

    def test_save_without_master_pw_over_encrypted_refuses(self, cred_path):
        cred.save_credentials([_dev()], master_password="hunter2")   # encrypted on disk
        assert cred.needs_master_password() is True
        # Re-saving a device that still carries secrets, with no master password → must refuse.
        with pytest.raises(ValueError):
            cred.save_credentials([_dev()])

    def test_explicit_downgrade_allowed(self, cred_path):
        cred.save_credentials([_dev()], master_password="hunter2")
        # The intentional override succeeds (and the store becomes plaintext).
        cred.save_credentials([_dev()], allow_plaintext_downgrade=True)
        assert cred.needs_master_password() is False
        assert cred.load_credentials()[0]["ssh_password"] == "s3cret"

    def test_save_with_master_pw_over_encrypted_ok(self, cred_path):
        cred.save_credentials([_dev()], master_password="hunter2")
        cred.save_credentials([_dev()], master_password="hunter2")   # re-encrypt, no raise
        assert cred.needs_master_password() is True

    def test_no_secrets_no_refusal(self, cred_path):
        # A device with no secret fields doesn't trigger the downgrade guard.
        cred.save_credentials([_dev()], master_password="hunter2")
        nosecret = _dev(ssh_password=None, api_key=None)
        cred.save_credentials([nosecret])   # no secrets to leak → allowed, no raise
