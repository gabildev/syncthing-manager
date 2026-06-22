"""Entry point for the macOS agent template executable.

macOS has no DISPLAY env var (Aqua, not X11): tkinter works in a normal GUI session and fails
when run headless (e.g. over SSH), in which case run_agent_main degrades to console mode. So we
just ask for GUI and let it fall back — same net behaviour as the Linux entry.
"""
from syncthing_manager.agent import run_agent_main

if __name__ == "__main__":
    run_agent_main(gui=True)
