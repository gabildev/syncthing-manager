import os
import sys


def _has_display() -> bool:
    """Return True if a graphical display is available (Linux/Mac)."""
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _launch() -> None:
    # Hybrid rule (shared with the frozen-binary entry scripts via _dispatch): a terminal is
    # always the CLI; the GUI opens only on a bare, NON-terminal launch (a double-click). Any
    # arguments — a subcommand, --help, or the explicit `gui` command — go to the CLI/Typer app.
    from syncthing_manager._dispatch import launch_gui_for_bare_invocation, stdio_is_terminal
    if launch_gui_for_bare_invocation(sys.argv, stdio_is_terminal()):
        use_gui = sys.platform == "win32" or _has_display()
        if use_gui:
            try:
                from syncthing_manager.gui import main
                main()
                return
            except Exception:
                if sys.platform == "win32":
                    raise  # GUI is required on Windows — don't silently swallow
        # else: headless (no display) → fall through to the CLI

    from syncthing_manager.cli import app
    app()


# Only launch when run as `python -m syncthing_manager` (__name__ == "__main__"); importing
# this module (e.g. in tests, to reach _wants_cli) must NOT dispatch. The PyInstaller builds
# use their own entry scripts (build/linux_entry.py, build/windows_entry.py), not this file.
if __name__ == "__main__":
    _launch()
