"""Entry point for the Windows agent template executable (GUI mode)."""
from syncthing_manager.agent import run_agent_main

if __name__ == "__main__":
    run_agent_main(gui=True)
