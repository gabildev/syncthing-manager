"""Entry point for the Linux agent template executable.

Runs in GUI mode when a display is available (so errors/results are visible in a
window), falling back to console mode on a headless box. run_agent_main also
degrades to console if tkinter can't be imported, so this is safe either way.
"""
import os

from syncthing_manager.agent import run_agent_main

if __name__ == "__main__":
    _has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    run_agent_main(gui=_has_display)
