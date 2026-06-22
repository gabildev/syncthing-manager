"""The CLI must run on headless servers (no python3-tk). The pure topology model
lives in topology.py precisely so importing it — and the CLI — never pulls in tkinter.
This guards against someone moving the helpers back into gui.py (which imports tk)."""
import subprocess
import sys


def test_topology_and_cli_import_without_tkinter():
    # Run in a fresh interpreter so this test isn't fooled by tkinter already being
    # imported by another test in the same session.
    code = (
        "import sys; "
        "import syncthing_manager.topology; "
        "import syncthing_manager.cli; "
        "assert 'tkinter' not in sys.modules, 'tkinter got imported'; "
        "from syncthing_manager.topology import (_build_topology, _detect_topology_issues, "
        "_arrow_from_senders, _ROLE_LABELS, _device_kind); "
        "print('OK')"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "OK" in r.stdout
