"""Entry point for the macOS PyInstaller build (single binary = GUI + CLI).

Hybrid launch rule (shared via syncthing_manager._dispatch):
- Any args (a subcommand, --help, or the explicit `gui` command) → CLI/Typer
- No args + a terminal (bare command in a shell) → CLI (prints help)
- No args + NO terminal (double-click / .app launcher) → GUI

macOS has no DISPLAY/WAYLAND_DISPLAY env var to gate on (unlike Linux), so when launching the GUI
we just attempt it and fall through to the CLI on any failure (headless / over SSH).
"""
import sys


def main() -> None:
    from syncthing_manager._dispatch import launch_gui_for_bare_invocation, stdio_is_terminal
    if launch_gui_for_bare_invocation(sys.argv, stdio_is_terminal()):
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
