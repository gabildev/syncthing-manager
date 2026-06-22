from __future__ import annotations

from syncthing_manager.generate import extract_embedded_template, _EMBED_MARKERS


def _fake_exe():
    ws, we = _EMBED_MARKERS["windows"]
    ls, le = _EMBED_MARKERS["linux"]
    return b"MAINEXEPAYLOAD" + ws + b"WIN-AGENT-BYTES" + we + ls + b"LIN-AGENT-BYTES" + le


def test_extracts_windows():
    p = extract_embedded_template("windows", exe_bytes=_fake_exe())
    assert p is not None and p.read_bytes() == b"WIN-AGENT-BYTES"


def test_extracts_linux():
    p = extract_embedded_template("linux", exe_bytes=_fake_exe())
    assert p is not None and p.read_bytes() == b"LIN-AGENT-BYTES"


def test_missing_returns_none():
    assert extract_embedded_template("windows", exe_bytes=b"no markers here") is None
