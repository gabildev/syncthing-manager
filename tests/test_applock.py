"""App lock (Part 2): password hashing, Syncthing-bcrypt verify, lock config."""
import pytest

from syncthing_manager import applock


# ── pure password hashing ─────────────────────────────────────────────────────

def test_hash_verify_roundtrip():
    h, s = applock.hash_password("hunter2")
    assert applock.verify_password("hunter2", h, s) is True
    assert applock.verify_password("wrong", h, s) is False


def test_hash_uses_random_salt():
    h1, s1 = applock.hash_password("same")
    h2, s2 = applock.hash_password("same")
    assert s1 != s2 and h1 != h2          # different salt → different hash
    assert applock.verify_password("same", h1, s1)
    assert applock.verify_password("same", h2, s2)


def test_verify_password_bad_salt():
    assert applock.verify_password("x", "deadbeef", "nothex!") is False


# ── Syncthing GUI password (bcrypt) ───────────────────────────────────────────

def _write_config_with_password(tmp_path, plain):
    import bcrypt
    h = bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()
    p = tmp_path / "config.xml"
    p.write_text(
        f'<configuration><gui enabled="true"><user>u</user>'
        f'<password>{h}</password></gui></configuration>', encoding="utf-8")
    return str(p)


def test_syncthing_verify_correct_and_wrong(tmp_path):
    cfg = _write_config_with_password(tmp_path, "s3cret")
    assert applock.syncthing_has_gui_password(cfg) is True
    assert applock.verify_syncthing_password("s3cret", cfg) is True
    assert applock.verify_syncthing_password("nope", cfg) is False


def test_syncthing_no_password(tmp_path):
    p = tmp_path / "config.xml"
    p.write_text('<configuration><gui><user>u</user></gui></configuration>', encoding="utf-8")
    assert applock.syncthing_has_gui_password(str(p)) is False
    assert applock.verify_syncthing_password("x", str(p)) is False


def test_syncthing_missing_config():
    assert applock.syncthing_has_gui_password("/no/such/config.xml") is False


# ── lock config (settings-backed; isolated via monkeypatch) ───────────────────

@pytest.fixture
def mem_settings(monkeypatch):
    store = {}
    monkeypatch.setattr(applock.appconfig, "get_setting",
                        lambda k, d=None: store.get(k, d))
    monkeypatch.setattr(applock.appconfig, "set_setting",
                        lambda k, v: store.__setitem__(k, v))
    return store


def test_default_off(mem_settings):
    assert applock.is_enabled() is False
    assert applock.method() == "off"


def test_custom_enable_verify_disable(mem_settings):
    applock.set_custom_password("abc")
    assert applock.is_enabled() and applock.method() == "custom"
    assert applock.verify("abc") is True
    assert applock.verify("zzz") is False
    applock.disable()
    assert not applock.is_enabled()
    assert applock.verify("anything") is True   # off → always open


def test_syncthing_method_stores_no_secret(mem_settings):
    applock.set_custom_password("abc")
    applock.set_syncthing_method()
    cfg = applock.get_lock()
    assert cfg["method"] == "syncthing"
    assert "hash" not in cfg and "salt" not in cfg


def test_inactivity_setting(mem_settings):
    assert applock.inactivity_minutes() == 0
    applock.set_inactivity_minutes(10)
    assert applock.inactivity_minutes() == 10


def test_verify_unknown_method_fails_closed(mem_settings):
    # A corrupt/tampered settings entry with an unrecognised method must NOT open the lock.
    mem_settings[applock._KEY] = {"method": "bogus"}
    assert applock.verify("anything") is False
    # A "custom" entry stripped of its hash also can't be satisfied.
    mem_settings[applock._KEY] = {"method": "custom"}
    assert applock.verify("anything") is False
    applock.set_inactivity_minutes(-5)
    assert applock.inactivity_minutes() == 0
