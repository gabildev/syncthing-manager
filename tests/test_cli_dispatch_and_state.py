"""CLI dispatch (_wants_cli) + folder-scoped state reset — both parity-critical paths the
Windows-only GUI testing never exercises."""
from __future__ import annotations

import sys
from types import SimpleNamespace


def _gui_for(args, has_terminal) -> bool:
    """Wraps the shared launch decision: True → open the GUI directly (double-click), False → hand
    argv to the CLI/Typer app (which prints help bare-in-terminal and runs the `gui` subcommand)."""
    from syncthing_manager._dispatch import launch_gui_for_bare_invocation
    return launch_gui_for_bare_invocation(["syncthing-manager", *args], has_terminal)


def test_launch_decision_hybrid_rule():
    # Bare invocation is the only ambiguous case → decided by whether a terminal is attached.
    assert _gui_for([], has_terminal=False) is True     # double-click / launcher → GUI
    assert _gui_for([], has_terminal=True) is False      # bare command in a shell → CLI (help)
    # ANY argument goes to the CLI/Typer app regardless of terminal (it dispatches `gui` itself).
    for args in (["--help"], ["-h"], ["--version"], ["--lang", "es"], ["rename", "--api-key", "k"],
                 ["discover"], ["undo"], ["gui"]):
        assert _gui_for(args, has_terminal=False) is False, args
        assert _gui_for(args, has_terminal=True) is False, args


def test_stdio_is_terminal_safe_when_streams_missing():
    # A windowed process can have sys.stdin/stdout == None — the probe must not raise.
    import syncthing_manager._dispatch as d
    old_in, old_out = sys.stdin, sys.stdout
    sys.stdin, sys.stdout = None, None
    try:
        assert d.stdio_is_terminal() is False
    finally:
        sys.stdin, sys.stdout = old_in, old_out


def test_reset_folder_scoped_state_clears_every_key():
    from syncthing_manager.gui.app import App
    s = {"topology": {"x": 1}, "topology_orig": {"y": 1}, "topology_snapshot": {"z": 1},
         "topology_removed": {"a"}, "topology_locked": {"b"}, "topo_undo": [1], "topo_redo": [2],
         "_undo": {"folder_id": "old"}, "agent_devices": [object()], "passive_devices": {"c"},
         "path_overrides": {"k": "v"}, "fcfg_pending": {"k": "v"},
         "manual_topo_nodes": {"n": {}}, "_disc_auto_retry_done": True,
         "new_label": "x", "new_path_input": "p", "new_folder_id": "i",
         "skip_path": True, "rename_id": True}
    App._reset_folder_scoped_state(SimpleNamespace(s=s))
    assert "topology" not in s and "topology_orig" not in s and "topology_snapshot" not in s
    assert "_undo" not in s                          # the bug the review caught
    assert s["topology_removed"] == set() and s["topology_locked"] == set()
    assert s["topo_undo"] == [] and s["topo_redo"] == []
    assert s["agent_devices"] == [] and s["passive_devices"] == set()
    assert s["path_overrides"] == {} and s["fcfg_pending"] == {} and s["manual_topo_nodes"] == {}
    assert s["_disc_auto_retry_done"] is False
    assert s["new_label"] == "" and s["new_path_input"] == "" and s["new_folder_id"] == ""
    assert s["skip_path"] is False and s["rename_id"] is False
