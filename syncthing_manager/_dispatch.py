"""Single source of truth for the CLI-vs-GUI launch decision, shared by `python -m
syncthing_manager` (__main__.py) and the three PyInstaller entry scripts (build/*_entry.py) so
the rule can't drift between them.

Hybrid rule — a terminal is ALWAYS the CLI, but a double-click still opens the GUI:
  • Any arguments (a subcommand, a flag like --help, or the explicit `gui` command) → hand them to
    the CLI/Typer app, which dispatches them (its `gui` subcommand opens the GUI on demand).
  • No arguments at all:
      – attached to a terminal (the bare command was run in a shell)  → CLI (Typer prints help)
      – NOT attached to a terminal (double-clicked / desktop launcher) → GUI

The single ambiguous case is a bare invocation (argv == [program]): a double-click and typing the
bare command in a shell are identical on argv, so we tell them apart by whether a terminal is
attached (POSIX: stdio isatty; Windows windowed .exe: a parent console exists)."""
from __future__ import annotations

import sys


def launch_gui_for_bare_invocation(argv: list[str], has_terminal: bool) -> bool:
    """True → open the GUI directly (a bare, non-terminal launch = a double-click / launcher).
    False → hand `argv` to the CLI/Typer app (which prints help when bare-in-terminal and runs the
    `gui` subcommand when asked)."""
    return len(argv) <= 1 and not has_terminal


def stdio_is_terminal() -> bool:
    """POSIX terminal check (Linux/macOS and the `python -m` dev path). A desktop launcher pipes
    stdio to a non-tty → False → GUI; a shell leaves it a tty → True → CLI. Safe when a stream is
    None (a windowed process has no stdio)."""
    for stream in (sys.stdin, sys.stdout):
        try:
            if stream is not None and stream.isatty():
                return True
        except Exception:
            pass
    return False
