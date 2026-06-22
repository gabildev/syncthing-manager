"""Entry point for the Linux/WSL PyInstaller build (single binary = GUI + CLI).

Hybrid launch rule (shared via syncthing_manager._dispatch):
- Any args (a subcommand, --help, or the explicit `gui` command) → CLI/Typer
- No args + a terminal (bare command in a shell) → CLI (prints help)
- No args + NO terminal (double-click / .desktop launcher) + a display → GUI
- No args + no terminal + no display (headless server) → CLI
"""
import os
import sys


def _has_display() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def main() -> None:
    from syncthing_manager._dispatch import launch_gui_for_bare_invocation, stdio_is_terminal
    if launch_gui_for_bare_invocation(sys.argv, stdio_is_terminal()) and _has_display():
        try:
            from syncthing_manager.gui import main as gui_main
            gui_main()
            return
        except Exception:
            pass  # tkinter missing or display init failed — fall through to CLI

    from syncthing_manager.cli import app
    app()


if __name__ == "__main__":
    main()
