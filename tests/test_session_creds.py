"""In-session credential reuse: remember creds typed for one folder's devices and re-apply
them to the same devices when they reappear in another folder (in-memory only, by device-id
with IP/host fallback)."""
from __future__ import annotations

from syncthing_manager.gui.app import App
from syncthing_manager.models import DeviceInfo


def _app():
    a = App.__new__(App)   # no Tk init
    a.s = {}
    return a


def _dev(did, ip="10.0.0.5", **kw):
    base = dict(device_id=did, name=did, ip=ip, api_url=None, api_key=None, folder_path=None,
                ssh_reachable=False, api_reachable=False, is_local=False)
    base.update(kw)
    return DeviceInfo(**base)


def test_remember_and_apply_by_device_id():
    a = _app()
    a._remember_session_creds([_dev("X", ssh_user="pi", ssh_key_path="/k", ssh_port=2222)])
    fresh = _dev("X")                      # same device, another folder, no creds
    a._apply_session_creds([fresh])
    assert fresh.ssh_user == "pi" and fresh.ssh_key_path == "/k" and fresh.ssh_port == 2222


def test_apply_ip_fallback_when_id_differs():
    a = _app()
    a._remember_session_creds([_dev("OLDID", ip="10.0.0.9", ssh_user="pi", ssh_password="pw")])
    fresh = _dev("NEWID", ip="10.0.0.9")   # id changed but same host
    a._apply_session_creds([fresh])
    assert fresh.ssh_user == "pi" and fresh.ssh_password == "pw"


def test_remember_never_wipes_existing():
    a = _app()
    a._remember_session_creds([_dev("X", ssh_user="pi")])
    a._remember_session_creds([_dev("X")])           # reappears offline, no creds
    assert a.s["_session_creds"]["X"]["ssh_user"] == "pi"


def test_apply_does_not_override_existing():
    a = _app()
    a._remember_session_creds([_dev("X", ssh_user="pi")])
    fresh = _dev("X", ssh_user="already")
    a._apply_session_creds([fresh])
    assert fresh.ssh_user == "already"


def test_local_device_never_remembered():
    a = _app()
    a._remember_session_creds([_dev("L", ssh_user="pi", is_local=True)])
    assert a.s.get("_session_creds", {}) == {}


def test_cfg_entries_exclude_already_covered():
    a = _app()
    a._remember_session_creds([_dev("X", ssh_user="pi"), _dev("Y", ssh_user="po")])
    ents = a._session_cred_entries(exclude_ids={"X"})
    assert {e["device_id"] for e in ents} == {"Y"}
    assert "folder_path" not in ents[0]              # per-folder, not carried


def test_remember_merges_preserves_other_channel_creds():
    """Re-probing a device over SSH-only must NOT drop a previously-remembered api_key (the
    whole-entry-replace bug): merge non-empty fields, keep the rest."""
    a = _app()
    a._remember_session_creds([_dev("X", ssh_user="pi", api_key="abc")])
    a._remember_session_creds([_dev("X", ssh_user="pi")])     # SSH re-probe, api_key not re-read
    assert a.s["_session_creds"]["X"]["api_key"] == "abc"
    assert a.s["_session_creds"]["X"]["ssh_user"] == "pi"


def test_ip_fallback_skipped_when_ambiguous():
    """Two remembered device-ids on the same IP → a new id at that IP must NOT inherit either
    one's creds (can't disambiguate)."""
    a = _app()
    a._remember_session_creds([_dev("A", ip="10.0.0.9", ssh_user="ua"),
                               _dev("B", ip="10.0.0.9", ssh_user="ub")])
    fresh = _dev("C", ip="10.0.0.9")
    a._apply_session_creds([fresh])
    assert fresh.ssh_user is None        # ambiguous IP → no fallback


def test_ip_fallback_carries_only_host_level_creds():
    """IP fallback (different device-id, same host) reuses SSH/WinRM host creds but NOT
    api_key/api_url — those identify a specific Syncthing instance/port on that host."""
    a = _app()
    a._remember_session_creds([_dev("OLD", ip="10.0.0.9", ssh_user="pi", ssh_password="pw",
                                    api_key="KEY", api_url="http://10.0.0.9:8384")])
    fresh = _dev("NEW", ip="10.0.0.9")              # same host, new id → IP fallback
    a._apply_session_creds([fresh])
    assert fresh.ssh_user == "pi" and fresh.ssh_password == "pw"   # host-level: reused
    assert fresh.api_key is None and fresh.api_url is None          # instance-level: NOT reused


def test_exact_id_match_still_carries_api_creds():
    a = _app()
    a._remember_session_creds([_dev("X", ip="10.0.0.9", api_key="KEY",
                                    api_url="http://10.0.0.9:8384")])
    fresh = _dev("X", ip="10.0.0.9")                 # exact id → all creds
    a._apply_session_creds([fresh])
    assert fresh.api_key == "KEY" and fresh.api_url == "http://10.0.0.9:8384"
