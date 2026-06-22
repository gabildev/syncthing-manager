from __future__ import annotations

from unittest.mock import patch

from syncthing_manager import agent
from syncthing_manager.models import DeviceInfo, RenameResult
from syncthing_manager.renamer import TopologyResult


def _cfg(**kw) -> dict:
    base = dict(
        folder_id="fid", new_label="New", new_dir_name="New",
        skip_path_rename=True,          # avoids the disk-path autodetect branch
        device_id="DEV",
        topology="<serialized>",        # truthy; deserialize_topology is patched
        topology_diff="<serialized>",   # truthy; deserialize_topology_diff is patched
    )
    base.update(kw)
    return base


def _ok_rename(*a, **k) -> RenameResult:
    dev = DeviceInfo(device_id="DEV", name="local", ip="127.0.0.1", api_url="u",
                     api_key="k", folder_path="/x", ssh_reachable=False,
                     api_reachable=True, is_local=True)
    r = RenameResult(device=dev)
    r.dir_renamed = True
    r.config_updated = True             # folder present here → not skipped_absent
    r.resumed = True                    # success = dir_renamed and config_updated and resumed
    return r


_TOPO = {"nodes": {"DEV": {"label": "d", "role": "sendreceive", "is_new": False}}}
_DIFF = {"any": True, "role_changed": {}, "links_added": set(), "links_removed": set(),
         "orphaned": set()}


def test_agent_reports_failure_when_topology_substep_fails():
    """The rename itself can succeed while the topology apply fails — the agent must return
    success=False so the caller (GUI/CLI passive) retries instead of marking the device done."""
    with patch("syncthing_manager.discovery.read_local_api_key", return_value="KEY"), \
         patch("syncthing_manager.agent._resolve_local_api_url", return_value="http://x:8384"), \
         patch("syncthing_manager.renamer.rename_on_device", side_effect=_ok_rename), \
         patch("syncthing_manager.renamer.deserialize_topology", return_value=_TOPO), \
         patch("syncthing_manager.renamer.deserialize_topology_diff", return_value=_DIFF), \
         patch("syncthing_manager.renamer.apply_topology_on_device",
               return_value=TopologyResult("DEV", False, "boom")):
        ok, msg = agent._run_agent_impl(_cfg())
    assert ok is False
    assert "falló un paso posterior" in msg
    assert "topología FALLÓ: boom" in msg


def test_agent_reports_success_when_topology_substep_ok():
    """Sanity counterpart: a successful topology apply keeps the overall result success."""
    with patch("syncthing_manager.discovery.read_local_api_key", return_value="KEY"), \
         patch("syncthing_manager.agent._resolve_local_api_url", return_value="http://x:8384"), \
         patch("syncthing_manager.renamer.rename_on_device", side_effect=_ok_rename), \
         patch("syncthing_manager.renamer.deserialize_topology", return_value=_TOPO), \
         patch("syncthing_manager.renamer.deserialize_topology_diff", return_value=_DIFF), \
         patch("syncthing_manager.renamer.apply_topology_on_device",
               return_value=TopologyResult("DEV", True, "+1 enlace")):
        ok, msg = agent._run_agent_impl(_cfg())
    assert ok is True
    assert "✓ Completado" in msg
