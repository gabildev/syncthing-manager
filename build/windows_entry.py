"""Entry point for the Windows PyInstaller build (single frozen .exe = GUI + CLI).

Hybrid launch rule (shared via syncthing_manager._dispatch):
- Any args (a subcommand, --help, or the explicit `gui` command) → CLI/Typer
- No args + launched from a terminal (a parent console exists) → CLI (prints help)
- No args + NO parent console (double-clicked) → GUI

The exe is built windowed (console=False) so the GUI never flashes a console, and it has NO
stdio of its own. We use AttachConsole(ATTACH_PARENT_PROCESS) as the terminal probe: it SUCCEEDS
when launched from cmd/PowerShell (there is a parent console → CLI, and reattaching makes output
visible) and FAILS when double-clicked (no parent console → GUI). On the CLI path with no parent
console (double-clicked WITH args) the CLI still runs, just without visible output.
"""
import sys


def _attach_parent_console() -> bool:
    """Reattach this windowed process to the launching terminal so CLI output is visible. Returns
    True when a parent console existed (→ launched from a terminal), False otherwise (→ a
    double-click). Silent on any failure."""
    try:
        import ctypes
        ATTACH_PARENT_PROCESS = -1
        if ctypes.windll.kernel32.AttachConsole(ATTACH_PARENT_PROCESS):
            # Reopen the standard streams onto the now-attached console.
            sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")
            sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace")
            try:
                sys.stdin = open("CONIN$", "r", encoding="utf-8")
            except OSError:
                pass
            return True
    except Exception:
        pass
    return False


def main() -> None:
    from syncthing_manager._dispatch import launch_gui_for_bare_invocation
    # Probe for a parent console first: it both tells us if this is a terminal launch and makes
    # CLI output visible. Harmless when we go on to open the GUI.
    has_terminal = _attach_parent_console()
    if launch_gui_for_bare_invocation(sys.argv, has_terminal):
        from syncthing_manager.gui import main as gui_main
        gui_main()
        return

    from syncthing_manager.cli import app
    app()


if __name__ == "__main__":
    main()
