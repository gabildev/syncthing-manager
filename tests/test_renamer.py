from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from syncthing_manager.models import DeviceInfo, RenameResult
from syncthing_manager.renamer import rename_on_device
from syncthing_manager.ssh_ops import SSHError
from syncthing_manager.syncthing import SyncthingError


def _make_local_device(folder_path: str = "/home/user/old-name") -> DeviceInfo:
    return DeviceInfo(
        device_id="LOCAL-ID",
        name="mypc",
        ip="127.0.0.1",
        api_url="http://localhost:8384",
        api_key="localkey",
        folder_path=folder_path,
        ssh_reachable=False,
        api_reachable=True,
        is_local=True,
    )


def _make_remote_device(ip: str = "192.168.1.20", folder_path: str = "/home/ubuntu/old-name") -> DeviceInfo:
    return DeviceInfo(
        device_id="REMOTE-1",
        name="nas",
        ip=ip,
        api_url=f"http://{ip}:8384",
        api_key="remotekey",
        folder_path=folder_path,
        ssh_reachable=True,
        api_reachable=True,
        is_local=False,
    )


class TestRenameOnDeviceSuccess:
    def test_full_success_local(self, tmp_path):
        old_dir = tmp_path / "old-name"
        old_dir.mkdir()
        device = _make_local_device(str(old_dir))

        mock_client = MagicMock()
        mock_client.wait_for_pause.return_value = True
        mock_client.is_version_gte.return_value = True

        # Path IS changing → delete+recreate via API (Syncthing ignores path on a
        # PUT). Patch that mechanism so we don't hit a real Syncthing.
        with patch("syncthing_manager.renamer.SyncthingClient", return_value=mock_client), \
             patch("syncthing_manager.renamer._change_path_via_recreate") as mock_b2:
            result = rename_on_device(device, "folder1", "New Name", "new-name")

        assert result.paused is True
        assert result.dir_renamed is True
        assert result.config_updated is True
        assert result.resumed is True
        assert result.success is True
        assert result.error is None

        new_dir = tmp_path / "new-name"
        assert new_dir.exists()
        assert not old_dir.exists()

        mock_client.pause_folder.assert_called_once_with("folder1")
        # A path change must NOT go through the PUT (it would be ignored) — it uses
        # delete+recreate via the API with the new path.
        mock_client.update_folder_config.assert_not_called()
        mock_b2.assert_called_once()
        assert mock_b2.call_args.args[3] == str(new_dir)  # new_path
        # The result must carry the new on-disk path so the GUI can refresh its cache
        # and a later undo reverts from the CURRENT location (not the stale one).
        assert result.new_path == str(new_dir)
        mock_client.resume_folder.assert_not_called()

    def test_dry_run_makes_no_changes(self, tmp_path):
        old_dir = tmp_path / "old-name"
        old_dir.mkdir()
        device = _make_local_device(str(old_dir))

        mock_client = MagicMock()
        mock_client.is_version_gte.return_value = True

        with patch("syncthing_manager.renamer.SyncthingClient", return_value=mock_client):
            result = rename_on_device(device, "folder1", "New Name", "new-name", dry_run=True)

        assert result.success is True
        assert old_dir.exists()
        mock_client.pause_folder.assert_not_called()
        mock_client.update_folder_config.assert_not_called()
        mock_client.resume_folder.assert_not_called()

    def test_skip_path_rename(self, tmp_path):
        old_dir = tmp_path / "old-name"
        old_dir.mkdir()
        device = _make_local_device(str(old_dir))

        mock_client = MagicMock()
        mock_client.wait_for_pause.return_value = True
        mock_client.is_version_gte.return_value = True

        with patch("syncthing_manager.renamer.SyncthingClient", return_value=mock_client):
            result = rename_on_device(
                device, "folder1", "New Label", "new-name", skip_path_rename=True
            )

        assert result.dir_renamed is True
        assert old_dir.exists()  # not renamed
        # Config updated with old path but new label
        mock_client.update_folder_config.assert_called_once_with(
            "folder1", "New Label", str(old_dir)
        )
        # Label-only → on-disk path is unchanged; result reflects the old path.
        assert result.new_path == str(old_dir)


class TestRenameOnDeviceFailures:
    def test_unreachable_device_skipped(self):
        device = DeviceInfo(
            device_id="DEV1", name="ghost", ip=None,
            api_url=None, api_key=None, folder_path=None,
            ssh_reachable=False, api_reachable=False, is_local=False,
            api_error="No IP",
        )
        result = rename_on_device(device, "folder1", "New", "new")
        assert result.success is False
        assert result.error is not None

    def test_pause_failure_aborts(self):
        device = _make_local_device()
        mock_client = MagicMock()
        mock_client.pause_folder.side_effect = SyncthingError("Connection refused")

        with patch("syncthing_manager.renamer.SyncthingClient", return_value=mock_client):
            result = rename_on_device(device, "folder1", "New", "new")

        assert result.paused is False
        assert result.dir_renamed is False
        assert result.error is not None

    def test_rename_failure_resumes_and_reports(self, tmp_path):
        device = _make_local_device("/nonexistent/path/old-name")
        mock_client = MagicMock()
        mock_client.wait_for_pause.return_value = True
        mock_client.is_version_gte.return_value = True

        with patch("syncthing_manager.renamer.SyncthingClient", return_value=mock_client):
            result = rename_on_device(device, "folder1", "New", "new")

        assert result.dir_renamed is False
        assert result.error is not None
        mock_client.resume_folder.assert_called_once_with("folder1")

    def test_config_update_failure_triggers_rollback(self, tmp_path):
        old_dir = tmp_path / "old-name"
        old_dir.mkdir()
        device = _make_local_device(str(old_dir))

        mock_client = MagicMock()
        mock_client.wait_for_pause.return_value = True
        mock_client.is_version_gte.return_value = True
        mock_client.update_folder_config.side_effect = SyncthingError("API error")

        with patch("syncthing_manager.renamer.SyncthingClient", return_value=mock_client):
            result = rename_on_device(device, "folder1", "New", "new-name")

        assert result.config_updated is False
        assert result.error is not None
        # Directory should be reverted
        assert old_dir.exists()
        new_dir = tmp_path / "new-name"
        assert not new_dir.exists()
        mock_client.resume_folder.assert_called_once()

    def test_left_paused_property(self):
        device = _make_local_device()
        result = RenameResult(device=device, paused=True, resumed=False)
        assert result.left_paused is True

    def test_not_left_paused_when_resumed(self):
        device = _make_local_device()
        result = RenameResult(device=device, paused=True, resumed=True)
        assert result.left_paused is False


class TestRemoteRename:
    def test_remote_rename_via_ssh(self):
        device = _make_remote_device()
        mock_client = MagicMock()
        mock_client.wait_for_pause.return_value = True
        mock_client.is_version_gte.return_value = True

        mock_ssh = MagicMock()
        mock_ssh.__enter__ = MagicMock(return_value=mock_ssh)
        mock_ssh.__exit__ = MagicMock(return_value=False)
        mock_ssh.path_exists.return_value = False  # destination does not exist

        # Path change → delete+recreate via API (patched); disk rename via SSH.
        with patch("syncthing_manager.renamer.SyncthingClient", return_value=mock_client), \
             patch("syncthing_manager.renamer.SSHClient", return_value=mock_ssh), \
             patch("syncthing_manager.renamer._change_path_via_recreate") as mock_b2:
            result = rename_on_device(device, "folder1", "New Name", "new-name")

        assert result.dir_renamed is True
        mock_ssh.rename_path.assert_called_once_with(
            "/home/ubuntu/old-name", "/home/ubuntu/new-name"
        )
        mock_b2.assert_called_once()
        assert result.success is True

    def test_api_only_remote_keeps_old_config_path(self):
        """Remote device reachable only by direct API (no SSH/WinRM): the disk can't
        be renamed, so the config must keep the OLD path (only the label changes) to
        avoid leaving the folder pointing at a non-existent directory."""
        device = DeviceInfo(
            device_id="REMOTE-API", name="api-only", ip="192.168.1.30",
            api_url="http://192.168.1.30:8384", api_key="k",
            folder_path="/data/old-name",
            ssh_reachable=False, api_reachable=True, is_local=False,
        )
        mock_client = MagicMock()
        mock_client.wait_for_pause.return_value = True
        mock_client.is_version_gte.return_value = True

        with patch("syncthing_manager.renamer.SyncthingClient", return_value=mock_client):
            result = rename_on_device(device, "folder1", "New Name", "new-name")

        # Config keeps the OLD path; only the label changes. Folder stays healthy.
        mock_client.update_folder_config.assert_called_once_with(
            "folder1", "New Name", "/data/old-name"
        )
        assert result.config_updated is True
        assert result.resumed is True
        assert result.success is True
        assert result.warning is not None  # manual disk-rename hint surfaced

    def test_api_only_remote_with_benign_ssh_error_is_not_a_failure(self):
        """A BENIGN ssh_error (e.g. config.xml-not-found / no-IP) with ssh_creds_rejected=False
        must NOT be treated as rejected creds: the device degrades to the benign keep-old-path
        warning, not a hard failure. Guards the renamer.py:241 discriminator (ssh_creds_rejected,
        not the mere presence of ssh_error)."""
        device = DeviceInfo(
            device_id="REMOTE-API", name="api-only", ip="192.168.1.30",
            api_url="http://192.168.1.30:8384", api_key="k",
            folder_path="/data/old-name",
            ssh_reachable=False, api_reachable=True, is_local=False,
            ssh_error="Could not find Syncthing config.xml on remote device",
            ssh_creds_rejected=False,
        )
        mock_client = MagicMock()
        mock_client.wait_for_pause.return_value = True
        mock_client.is_version_gte.return_value = True
        with patch("syncthing_manager.renamer.SyncthingClient", return_value=mock_client):
            result = rename_on_device(device, "folder1", "New Name", "new-name")
        assert result.success is True               # benign degrade, NOT a failure
        assert result.error is None
        mock_client.update_folder_config.assert_called_once_with(
            "folder1", "New Name", "/data/old-name")  # old path kept

    def test_api_only_remote_with_rejected_ssh_creds_is_failure_not_benign(self):
        """SSH was CONFIGURED but the creds are REJECTED (ssh_creds_rejected=True) — that is NOT
        the same as a device with no SSH at all. It must be reported as a FAILURE (fix-creds-and-
        retry), not folded into the benign 'use the agent' warning. Keyed on the dedicated
        ssh_creds_rejected flag (not the mere presence of ssh_error). The config stays healthy
        (not repointed) and the folder is resumed."""
        device = DeviceInfo(
            device_id="REMOTE-API", name="pi", ip="192.168.1.30",
            api_url="http://192.168.1.30:8384", api_key="k",
            folder_path="/data/old-name",
            ssh_reachable=False, api_reachable=True, is_local=False,
            ssh_user="pi", ssh_error="credenciales SSH rechazadas (autenticación fallida)",
            ssh_creds_rejected=True,
        )
        mock_client = MagicMock()
        mock_client.wait_for_pause.return_value = True
        mock_client.is_version_gte.return_value = True

        with patch("syncthing_manager.renamer.SyncthingClient", return_value=mock_client):
            result = rename_on_device(device, "folder1", "New Name", "new-name")

        assert result.success is False
        assert result.error and "Credenciales SSH no válidas" in result.error
        mock_client.update_folder_config.assert_not_called()   # config NOT repointed
        mock_client.resume_folder.assert_called_once()          # folder left healthy

    def test_remote_ssh_error_during_rename(self):
        device = _make_remote_device()
        mock_client = MagicMock()
        mock_client.wait_for_pause.return_value = True
        mock_client.is_version_gte.return_value = True

        mock_ssh = MagicMock()
        mock_ssh.__enter__ = MagicMock(return_value=mock_ssh)
        mock_ssh.__exit__ = MagicMock(return_value=False)
        mock_ssh.path_exists.return_value = False
        mock_ssh.rename_path.side_effect = SSHError("Permission denied")

        with patch("syncthing_manager.renamer.SyncthingClient", return_value=mock_client):
            with patch("syncthing_manager.renamer.SSHClient", return_value=mock_ssh):
                result = rename_on_device(device, "folder1", "New", "new-name")

        assert result.dir_renamed is False
        assert "Permission denied" in result.error
        mock_client.resume_folder.assert_called_once()

    def test_ssh_only_device_pauses_and_updates_via_config_api(self):
        """Device reachable only via SSH (API on localhost): pause, disk-rename and
        config update (LABEL ONLY here) must go through the SSH-proxied CONFIG API —
        never the non-existent /rest/db/pause|resume — toggling `paused` in the config."""
        import copy as _copy
        device = DeviceInfo(
            device_id="PI", name="raspberrypi", ip="192.168.1.40",
            api_url="http://192.168.1.40:8384", api_key="pikey",
            folder_path="/data/old-name",
            ssh_reachable=True, api_reachable=False, is_local=False,
            ssh_user="pi",
        )
        # Stateful mock: PUTs update the config the next GET returns (so the post-PUT
        # verification sees the new label).
        state = {"cfg": {"id": "ULL", "label": "old", "path": "/data/old-name",
                         "paused": False, "devices": [{"deviceID": "PI"}]}}

        mock_ssh = MagicMock()
        mock_ssh.__enter__ = MagicMock(return_value=mock_ssh)
        mock_ssh.__exit__ = MagicMock(return_value=False)
        mock_ssh.path_exists.return_value = False
        mock_ssh.syncthing_api_get.side_effect = lambda *a, **k: _copy.deepcopy(state["cfg"])
        mock_ssh.syncthing_api_put.side_effect = (
            lambda path, body, *a, **k: state.__setitem__("cfg", _copy.deepcopy(body)))

        with patch("syncthing_manager.renamer.SSHClient", return_value=mock_ssh):
            # skip_path_rename → label-only → exercises the SSH config PUT + verify.
            result = rename_on_device(device, "ULL", "New Label", "new-name",
                                      skip_path_rename=True)

        # No /rest/db/* anywhere — pause and config both go through /rest/config.
        for c in mock_ssh.syncthing_api_get.call_args_list:
            assert "/rest/db/" not in c.args[0]
        assert all(c.args[0] == "/rest/config/folders/ULL"
                   for c in mock_ssh.syncthing_api_put.call_args_list)

        bodies = [c.args[1] for c in mock_ssh.syncthing_api_put.call_args_list]
        assert bodies[0]["paused"] is True             # first PUT pauses (config-based)
        assert state["cfg"]["label"] == "New Label"    # label applied
        assert state["cfg"]["paused"] is False          # resumed via the same config PUT
        mock_ssh.rename_path.assert_not_called()        # skip_path → no disk rename
        assert result.success is True
        assert result.resumed is True


class TestSSHTildeExpansion:
    def test_rename_path_expands_leading_tilde(self):
        """The Pi stores folder paths like '~/ULL'; single-quoting in mv/test means
        the shell never expands ~, so SSHClient must expand it to $HOME itself."""
        from syncthing_manager.ssh_ops import SSHClient
        c = SSHClient("host")
        c._home = "/home/pi"  # pretend already connected; skips the echo $HOME exec
        cmds = []

        def fake_exec(cmd, timeout=30):
            cmds.append(cmd)
            # 'test -e' must report "not exists" so rename proceeds; mv returns ok
            return (1, "", "") if "test -e" in cmd else (0, "", "")

        c._exec = fake_exec
        c.rename_path("~/ULL", "~/T")
        joined = " ".join(cmds)
        assert "/home/pi/ULL" in joined
        assert "/home/pi/T" in joined
        assert "~/" not in joined  # tilde expanded, never passed literally


class TestReliablePathChange:
    def test_recreate_via_ssh_deletes_then_creates(self):
        from syncthing_manager.renamer import _recreate_via_ssh
        device = _make_remote_device()
        mock_ssh = MagicMock()
        mock_ssh.__enter__ = MagicMock(return_value=mock_ssh)
        mock_ssh.__exit__ = MagicMock(return_value=False)
        # 1st get → current config to clone; 2nd get → post-create verification
        mock_ssh.syncthing_api_get.side_effect = [
            {"id": "ULL", "label": "old", "path": "/data/old", "paused": True, "devices": []},
            {"id": "ULL", "label": "New", "path": "/data/new", "paused": False, "devices": []},
        ]
        with patch("syncthing_manager.renamer.SSHClient", return_value=mock_ssh):
            _recreate_via_ssh(device, "ULL", "New", "/data/new", 8384)

        mock_ssh.syncthing_api_delete.assert_called_once()
        # POST creates the new folder with the new path/label and paused=false
        created = mock_ssh.syncthing_api_post.call_args.kwargs["body"]
        assert created["path"] == "/data/new"
        assert created["label"] == "New"
        assert created["paused"] is False

    def test_rename_folder_id_over_ssh(self, tmp_path, monkeypatch):
        """An SSH-reachable device with no direct API must still get the ID rename
        (delete+create proxied over SSH), not fall back to 'usa el agente'."""
        # Isolate the data dir so the pre-delete recovery snapshot never touches the real one.
        monkeypatch.setenv("SYNCTHING_MANAGER_DATADIR", str(tmp_path / "data"))
        from syncthing_manager.renamer import rename_folder_id
        device = DeviceInfo(
            device_id="REMOTE-SSH", name="raspberrypi", ip="192.168.1.50",
            api_url="http://192.168.1.50:8384", api_key="k", folder_path="/data/ULL",
            ssh_reachable=True, api_reachable=False, is_local=False,
        )
        mock_ssh = MagicMock()
        mock_ssh.__enter__ = MagicMock(return_value=mock_ssh)
        mock_ssh.__exit__ = MagicMock(return_value=False)
        mock_ssh.syncthing_api_get.return_value = {
            "id": "ULL", "label": "L", "path": "/data/ULL", "devices": []}
        with patch("syncthing_manager.renamer.SSHClient", return_value=mock_ssh):
            results = rename_folder_id([device], "ULL", "ULL1", dry_run=False)

        assert results == [("raspberrypi", True, "OK")]
        mock_ssh.syncthing_api_delete.assert_called_once()
        created = mock_ssh.syncthing_api_post.call_args.kwargs["body"]
        assert created["id"] == "ULL1"

    def test_change_path_via_recreate_deletes_then_creates(self):
        from syncthing_manager.renamer import _change_path_via_recreate
        from syncthing_manager.models import FolderConfig
        client = MagicMock()
        old = FolderConfig(id="ULL", label="old", path="/data/old", devices=[],
                           raw={"id": "ULL", "label": "old", "path": "/data/old",
                                "paused": True, "devices": []})
        new = FolderConfig(id="ULL", label="New", path="/data/new", devices=[],
                           raw={"id": "ULL", "label": "New", "path": "/data/new",
                                "paused": False, "devices": []})
        # 1st get_folder → build new config; 2nd → post-create verification
        client.get_folder.side_effect = [old, new]

        _change_path_via_recreate(client, "ULL", "New", "/data/new")

        client.delete_folder.assert_called_once_with("ULL")
        created = client.create_folder.call_args.args[0]
        assert created["path"] == "/data/new"
        assert created["label"] == "New"
        assert created["paused"] is False

    def test_change_path_via_recreate_transient_verify_error_is_tolerated(self):
        """A TRANSIENT failure on the post-recreate verify GET (Syncthing reloads its config right
        after a delete+create) must NOT propagate: the create already succeeded, and a raised error
        here would reach rename_on_device's except and trigger the disk revert → config@new_path /
        disk@old_path desync. Trust the POST; swallow the transient verify error."""
        from syncthing_manager.renamer import _change_path_via_recreate
        from syncthing_manager.models import FolderConfig
        client = MagicMock()
        old = FolderConfig(id="ULL", label="old", path="/data/old", devices=[],
                           raw={"id": "ULL", "label": "old", "path": "/data/old", "devices": []})
        # 1st get_folder → build the new config; 2nd (verify) → transient blip (NOT a 404).
        client.get_folder.side_effect = [old, SyncthingError("503 service unavailable")]
        _change_path_via_recreate(client, "ULL", "New", "/data/new")   # must NOT raise
        client.create_folder.assert_called_once()

    def test_change_path_via_recreate_confirmed_path_mismatch_still_raises(self):
        """A CONFIRMED wrong path on the verify (got a folder at a different path) is still a real
        failure → must raise (the transient-tolerance must not weaken the genuine check)."""
        from syncthing_manager.renamer import _change_path_via_recreate
        from syncthing_manager.models import FolderConfig
        client = MagicMock()
        old = FolderConfig(id="ULL", label="old", path="/data/old", devices=[],
                           raw={"id": "ULL", "label": "old", "path": "/data/old", "devices": []})
        wrong = FolderConfig(id="ULL", label="New", path="/data/SOMETHING-ELSE", devices=[],
                             raw={"id": "ULL", "path": "/data/SOMETHING-ELSE", "devices": []})
        client.get_folder.side_effect = [old, wrong]
        with pytest.raises(SyncthingError):
            _change_path_via_recreate(client, "ULL", "New", "/data/new")

    def test_change_path_via_recreate_rolls_back_on_create_failure(self):
        from syncthing_manager.renamer import _change_path_via_recreate
        from syncthing_manager.models import FolderConfig
        client = MagicMock()
        old = FolderConfig(id="ULL", label="old", path="/data/old", devices=[],
                           raw={"id": "ULL", "label": "old", "path": "/data/old",
                                "paused": False, "devices": []})
        client.get_folder.return_value = old
        client.create_folder.side_effect = [SyncthingError("boom"), None]  # 1st fails, rollback ok

        with pytest.raises(SyncthingError):
            _change_path_via_recreate(client, "ULL", "New", "/data/new")

        # rolled back: create called twice (new, then the original config again)
        assert client.create_folder.call_count == 2
        assert client.create_folder.call_args_list[1].args[0]["path"] == "/data/old"

    def test_change_path_via_recreate_lost_folder_keeps_snapshot(self, tmp_path, monkeypatch):
        """If both the new create AND the rollback fail, the on-disk recovery snapshot must be
        kept and its path surfaced so the user can recreate the folder by hand."""
        from syncthing_manager.renamer import _change_path_via_recreate
        from syncthing_manager.models import FolderConfig
        from syncthing_manager import config as _cfg
        monkeypatch.setenv(_cfg._ENV, str(tmp_path / "data"))
        client = MagicMock()
        old = FolderConfig(id="ULL", label="old", path="/data/old", devices=[],
                           raw={"id": "ULL", "label": "old", "path": "/data/old",
                                "paused": False, "devices": []})
        client.get_folder.return_value = old
        client.create_folder.side_effect = SyncthingError("boom")   # new AND rollback fail
        with pytest.raises(SyncthingError) as ei:
            _change_path_via_recreate(client, "ULL", "New", "/data/new", dev_name="pi")
        msg = str(ei.value)
        assert "CONFIG DE CARPETA PERDIDA" in msg and "config original guardada" in msg
        rec_dir = tmp_path / "data" / "id_rename_recovery"
        assert rec_dir.exists() and list(rec_dir.glob("*.json")), \
            "recovery snapshot must survive a lost-folder failure"

    def test_recovery_snapshot_cleared_on_success(self, tmp_path, monkeypatch):
        """On a CLEAN path change the secret-bearing recovery snapshot must be removed (not
        left on disk) — the keep-on-failure path is tested separately."""
        from syncthing_manager.renamer import _change_path_via_recreate
        from syncthing_manager.models import FolderConfig
        from syncthing_manager import config as _cfg
        monkeypatch.setenv(_cfg._ENV, str(tmp_path / "data"))
        old = FolderConfig(id="ULL", label="old", path="/data/old", devices=[],
                           raw={"id": "ULL", "label": "old", "path": "/data/old",
                                "paused": False, "devices": []})
        new = FolderConfig(id="ULL", label="New", path="/data/new", devices=[],
                           raw={"id": "ULL", "label": "New", "path": "/data/new",
                                "paused": False, "devices": []})
        client = MagicMock()
        client.get_folder.side_effect = [old, new]   # build cfg, then post-create verify OK
        _change_path_via_recreate(client, "ULL", "New", "/data/new", dev_name="pi")
        rec_dir = tmp_path / "data" / "id_rename_recovery"
        assert not (rec_dir.exists() and list(rec_dir.glob("*.json"))), \
            "recovery snapshot must be cleared after a successful recreate"

    def test_recovery_snapshot_is_0600(self, tmp_path, monkeypatch):
        """The recovery snapshot persists folder config that can contain a per-device
        encryptionPassword — it must never be world-readable on a multi-user box."""
        if os.name == "nt":
            import pytest as _pt
            _pt.skip("POSIX permission semantics")
        from syncthing_manager.renamer import _save_id_rename_recovery
        from syncthing_manager import config as _cfg
        monkeypatch.setenv(_cfg._ENV, str(tmp_path / "data"))
        p = _save_id_rename_recovery(
            "pi", "fid", {"id": "fid", "devices": [{"deviceID": "X",
                                                    "encryptionPassword": "SECRET"}]})
        import stat
        assert p is not None
        assert stat.S_IMODE(os.stat(p).st_mode) == 0o600


class TestPreflight:
    def _local(self, folder_path, os_type="linux"):
        return DeviceInfo(
            device_id="L", name="mypc", ip="127.0.0.1",
            api_url="http://localhost:8384", api_key="k", folder_path=folder_path,
            ssh_reachable=False, api_reachable=True, is_local=True, os_type=os_type,
        )

    def test_name_invalid_for_windows(self, tmp_path):
        from syncthing_manager.renamer import preflight_check
        dev = self._local(str(tmp_path / "old"), os_type="windows")
        issues = preflight_check([dev], "fid", "inf:orme", skip_path_rename=False)
        assert any(i.level == "error" and "nombre no válido" in i.message for i in issues)

    def test_name_ok_for_linux(self, tmp_path):
        from syncthing_manager.renamer import preflight_check
        dev = self._local(str(tmp_path / "old"), os_type="linux")
        issues = preflight_check([dev], "fid", "inf:orme", skip_path_rename=False)
        assert not any("nombre no válido" in i.message for i in issues)

    def test_local_destination_exists(self, tmp_path):
        from syncthing_manager.renamer import preflight_check
        (tmp_path / "ocupado").mkdir()
        dev = self._local(str(tmp_path / "old"), os_type="linux")
        issues = preflight_check([dev], "fid", "ocupado", skip_path_rename=False)
        assert any(i.level == "error" and "destino ya existe" in i.message for i in issues)

    def test_id_collision(self, tmp_path):
        from syncthing_manager.renamer import preflight_check
        dev = self._local(str(tmp_path / "old"), os_type="linux")
        mock_client = MagicMock()
        mock_client.get_folder.return_value = object()  # new id already exists
        with patch("syncthing_manager.renamer.SyncthingClient", return_value=mock_client):
            issues = preflight_check([dev], "fid", "nombre-ok", skip_path_rename=True,
                                     new_folder_id="NEW")
        assert any(i.level == "error" and "ya existe" in i.message for i in issues)

    def test_clean_when_all_ok(self, tmp_path):
        from syncthing_manager.renamer import preflight_check
        dev = self._local(str(tmp_path / "old"), os_type="linux")
        issues = preflight_check([dev], "fid", "nombre-libre", skip_path_rename=False)
        assert issues == []


class TestCaseOnlyRename:
    def test_rename_local_case_only(self, tmp_path):
        """A case-only rename must work (here on a case-sensitive FS it's a normal
        rename; on Windows/macOS the two-step path handles the same-entry case)."""
        from syncthing_manager.renamer import _rename_local
        old = tmp_path / "testeo"
        old.mkdir()
        (old / "data.txt").write_text("x")
        new = tmp_path / "TESTEO"
        _rename_local(str(old), str(new))
        assert new.exists()
        assert (new / "data.txt").read_text() == "x"

    def test_rename_local_real_collision_still_blocked(self, tmp_path):
        """A genuine different-name collision must still be refused (no clobber)."""
        from syncthing_manager.renamer import _rename_local
        old = tmp_path / "origen"
        old.mkdir()
        dest = tmp_path / "ocupado"
        dest.mkdir()
        with pytest.raises(OSError, match="already exists"):
            _rename_local(str(old), str(dest))


class TestReviewFixes:
    def test_recreate_rollback_failure_reports_lost(self):
        """B1: if the post-delete rollback ALSO fails, the error must clearly say the
        config was lost (not propagate the generic create error)."""
        from syncthing_manager.renamer import _change_path_via_recreate
        from syncthing_manager.models import FolderConfig
        client = MagicMock()
        old = FolderConfig(id="ULL", label="old", path="/data/old", devices=[],
                           raw={"id": "ULL", "path": "/data/old", "devices": []})
        client.get_folder.return_value = old
        client.create_folder.side_effect = [SyncthingError("boom"),
                                             SyncthingError("rollback also failed")]
        with pytest.raises(SyncthingError, match="PERDIDA"):
            _change_path_via_recreate(client, "ULL", "New", "/data/new")

    def test_rename_local_cross_device_clear_error(self, tmp_path):
        """B2: an EXDEV (cross-filesystem) rename surfaces an actionable message."""
        import errno
        from syncthing_manager.renamer import _rename_local
        old = tmp_path / "src"
        old.mkdir()
        new = tmp_path / "dst"
        with patch("pathlib.Path.rename", side_effect=OSError(errno.EXDEV, "Invalid cross-device link")):
            with pytest.raises(OSError, match="otro sistema de archivos"):
                _rename_local(str(old), str(new))

    def test_preflight_flags_cross_filesystem(self, tmp_path):
        """B2: pre-flight flags an absolute target that lands on another filesystem."""
        from syncthing_manager import renamer
        dev = DeviceInfo(
            device_id="L", name="pc", ip="127.0.0.1", api_url="http://localhost:8384",
            api_key="k", folder_path=str(tmp_path / "old"), ssh_reachable=False,
            api_reachable=True, is_local=True, os_type="linux")

        def fake_stat(p, *a, **k):
            res = MagicMock()
            res.st_dev = 1 if "old" in str(p) else 2  # source on dev 1, target parent on dev 2
            return res
        # Patch the filesystem probes narrowly so faking st_dev doesn't break isdir/exists.
        with patch.object(renamer.os.path, "exists", return_value=True), \
             patch.object(renamer.os.path, "isdir", return_value=True), \
             patch.object(renamer.os, "access", return_value=True), \
             patch.object(renamer.os, "stat", side_effect=fake_stat):
            issues = renamer.preflight_check([dev], "fid", "/mnt/otra/destino",
                                             skip_path_rename=False)
        assert any(i.level == "error" and "otro sistema de archivos" in i.message for i in issues)

    def test_ensure_stfolder_creates_marker_local(self, tmp_path):
        """B3: the .stfolder marker is recreated locally if missing."""
        from syncthing_manager.renamer import _ensure_stfolder
        dev = DeviceInfo(
            device_id="L", name="pc", ip="127.0.0.1", api_url=None, api_key=None,
            folder_path=str(tmp_path), ssh_reachable=False, api_reachable=True, is_local=True)
        _ensure_stfolder(dev, str(tmp_path))
        assert (tmp_path / ".stfolder").is_dir()


class TestSecureChannelPreference:
    """`prefer_secure_channel` (off by default) must demote direct-API to SSH/WinRM for
    NON-local devices uniformly, and never affect the local node or shell-less devices."""

    def _dev(self, **kw):
        base = dict(device_id="X", name="n", ip="1.2.3.4",
                    api_url="http://1.2.3.4:8384", api_key="k", folder_path="/data/x",
                    api_reachable=True, ssh_reachable=False, is_local=False)
        base.update(kw)
        return DeviceInfo(**base)

    def test_off_keeps_direct_api(self, monkeypatch):
        from syncthing_manager import renamer, config
        monkeypatch.setattr(config, "get_setting", lambda k, d=None: False)
        assert renamer._has_direct_api(self._dev(ssh_reachable=True)) is True

    def test_on_demotes_when_shell_reachable(self, monkeypatch):
        from syncthing_manager import renamer, config
        monkeypatch.setattr(config, "get_setting", lambda k, d=None: True)
        assert renamer._has_direct_api(self._dev(ssh_reachable=True)) is False
        assert renamer._has_direct_api(self._dev(winrm_reachable=True)) is False

    def test_on_but_no_shell_stays_direct(self, monkeypatch):
        from syncthing_manager import renamer, config
        monkeypatch.setattr(config, "get_setting", lambda k, d=None: True)
        # No SSH/WinRM channel → can't demote, must keep the only path (direct API).
        assert renamer._has_direct_api(self._dev()) is True

    def test_local_never_demoted(self, monkeypatch):
        from syncthing_manager import renamer, config
        monkeypatch.setattr(config, "get_setting", lambda k, d=None: True)
        # Local node uses loopback API (no network exposure) — never rerouted.
        assert renamer._has_direct_api(
            self._dev(is_local=True, ssh_reachable=True)) is True


class TestResolveRemoteFolderPath:
    """resolve_remote_folder_path cross-references the folder ID on the device's OWN config
    over its best channel — backs the path autodetect in the edit-credentials dialog."""

    def _dev(self, **kw):
        base = dict(device_id="REMOTE-1", name="nas", ip="192.168.1.20",
                    api_url="http://192.168.1.20:8384", api_key="K", folder_path=None,
                    ssh_reachable=False, api_reachable=True, is_local=False)
        base.update(kw)
        return DeviceInfo(**base)

    def test_via_direct_api(self):
        from syncthing_manager.renamer import resolve_remote_folder_path
        fake_client = MagicMock()
        fake_client.get_folder.return_value = MagicMock(path="/srv/data")
        with patch("syncthing_manager.renamer.SyncthingClient", return_value=fake_client):
            assert resolve_remote_folder_path(self._dev(), "f1") == "/srv/data"

    def test_none_when_folder_absent(self):
        from syncthing_manager.renamer import resolve_remote_folder_path
        fake_client = MagicMock()
        fake_client.get_folder.return_value = None        # 404 → not on this device
        with patch("syncthing_manager.renamer.SyncthingClient", return_value=fake_client):
            assert resolve_remote_folder_path(self._dev(), "f1") is None

    def test_none_when_unreachable(self):
        from syncthing_manager.renamer import resolve_remote_folder_path
        dev = self._dev(api_reachable=False, api_url=None, ssh_reachable=False)
        assert resolve_remote_folder_path(dev, "f1") is None

    def test_none_on_api_error(self):
        from syncthing_manager.renamer import resolve_remote_folder_path
        fake_client = MagicMock()
        fake_client.get_folder.side_effect = SyncthingError("boom")
        with patch("syncthing_manager.renamer.SyncthingClient", return_value=fake_client):
            assert resolve_remote_folder_path(self._dev(), "f1") is None


class TestRenameFolderAbsentBenign:
    """A device that isn't a folder member YET (its Syncthing config 404s for this folder)
    is not a rename failure — the topology step creates the folder seconds later. The rename
    must skip it gracefully: no false ✗, no queueing for passive retry."""

    def _ssh_device(self):
        return DeviceInfo(
            device_id="PI", name="raspberrypi", ip="10.0.0.9", api_url="", api_key="k",
            folder_path="/home/pi/Testeo", ssh_reachable=True, api_reachable=False,
            is_local=False, ssh_user="pi")

    def test_folder_absent_404_label_only_is_benign_skip(self):
        dev = self._ssh_device()   # label-only (Testeo→Testeo): path unchanged
        with patch("syncthing_manager.renamer._ssh_pause_folder"), \
             patch("syncthing_manager.renamer._ssh_update_folder_config",
                   side_effect=SSHError("Syncthing API GET /rest/config/folders/Testeo "
                                        "→ HTTP 404: No folder with given ID")):
            res = rename_on_device(dev, "Testeo", "Testeo", "Testeo")
        assert res.skipped_absent is True
        assert res.error is None
        assert res.success is True          # → excluded from failed_now / passive queue

    def test_real_failure_still_reported(self):
        """A NON-404 config error is still a real failure (don't swallow it)."""
        dev = self._ssh_device()
        with patch("syncthing_manager.renamer._ssh_pause_folder"), \
             patch("syncthing_manager.renamer._safe_resume"), \
             patch("syncthing_manager.renamer._attempt_revert"), \
             patch("syncthing_manager.renamer._ssh_update_folder_config",
                   side_effect=SSHError("connection reset by peer")):
            res = rename_on_device(dev, "Testeo", "Testeo", "Testeo")
        assert res.skipped_absent is False
        assert res.error is not None and "connection reset" in res.error
        assert res.success is False


class TestRenameFolderAbsentDirectAPI:
    """The benign-skip must also cover the DIRECT-API path (not just SSH/WinRM curl): a joining
    device reachable by API raises 'Folder X not found' (status_code=404) from update_folder_config
    / get_folder, which must be recognised as absent — else a false ✗ + passive poison."""

    def _api_device(self, folder_path="/srv/Testeo"):
        return DeviceInfo(
            device_id="API", name="nas", ip="10.0.0.5",
            api_url="http://10.0.0.5:8384", api_key="k", folder_path=folder_path,
            ssh_reachable=False, api_reachable=True, is_local=False)

    def test_api_404_label_only_is_benign_skip(self):
        dev = self._api_device()                      # label-only (path unchanged)
        client = MagicMock()
        client.wait_for_pause.return_value = True
        client.is_version_gte.return_value = True
        # update_folder_config raises the real 'not found' (now carrying status_code=404)
        from syncthing_manager.syncthing import SyncthingError as SErr
        client.update_folder_config.side_effect = SErr("Folder Testeo not found", status_code=404)
        with patch("syncthing_manager.renamer.SyncthingClient", return_value=client):
            res = rename_on_device(dev, "Testeo", "Testeo", "Testeo")
        assert res.skipped_absent is True and res.error is None and res.success is True

    def test_api_404_no_path_is_benign_skip(self):
        # Joining device with UNKNOWN path: get_folder returns None (404) → skip, not "ruta desconocida".
        dev = self._api_device(folder_path=None)
        client = MagicMock()
        client.wait_for_pause.return_value = True
        client.get_folder.return_value = None         # absent on this device
        with patch("syncthing_manager.renamer.SyncthingClient", return_value=client):
            res = rename_on_device(dev, "Testeo", "Testeo", "Testeo")
        assert res.skipped_absent is True and res.error is None

    def test_api_transient_still_fails(self):
        dev = self._api_device()
        client = MagicMock()
        client.wait_for_pause.return_value = True
        client.is_version_gte.return_value = True
        from syncthing_manager.syncthing import SyncthingError as SErr
        client.update_folder_config.side_effect = SErr("PUT failed: 500", status_code=500)
        with patch("syncthing_manager.renamer.SyncthingClient", return_value=client), \
             patch("syncthing_manager.renamer._safe_resume"):
            res = rename_on_device(dev, "Testeo", "Testeo", "Testeo")
        assert res.skipped_absent is False and res.error is not None and res.success is False


class TestFolderAbsentHelperAndNormPath:
    def test_is_folder_absent_error_structured_only_for_syncthing(self):
        from syncthing_manager.renamer import _is_folder_absent_error
        from syncthing_manager.syncthing import SyncthingError as SErr
        # API: structured 404 → absent
        assert _is_folder_absent_error(SErr("Folder x not found", status_code=404))
        # API: message has "404" but NO status (e.g. a recreate create-POST failure re-raised) →
        # NOT absent — the folder was present, this is a real failure to surface.
        assert not _is_folder_absent_error(SErr("Revertido (creación falló): POST ... 404"))
        assert not _is_folder_absent_error(SErr("PUT failed: 500", status_code=500))
        # SSH/WinRM: no status field → message-based
        assert _is_folder_absent_error(SSHError("→ HTTP 404: No folder with given ID"))
        assert not _is_folder_absent_error(SSHError("connection reset by peer"))

    def test_norm_path_windows_case_insensitive_posix_sensitive(self):
        from syncthing_manager.renamer import _norm_path
        assert _norm_path("C:\\Sync\\Testeo") == _norm_path("c:/sync/testeo")   # Windows: case-insensitive
        assert _norm_path("C:/Sync/") == _norm_path("c:/Sync")                  # + trailing slash
        assert _norm_path("/home/User/A") != _norm_path("/home/user/a")          # POSIX: case-sensitive


def test_ssh_only_joining_device_no_path_is_benign_skip():
    """An SSH/WinRM-only device JOINING the folder (no discovered path, not a member yet) must
    skip benignly — the topology step creates it — not hard-fail with 'ruta desconocida' and
    poison the passive queue. This is the Raspberry-Pi (SSH-only) joining case."""
    from unittest.mock import patch
    dev = DeviceInfo(device_id="PI", name="raspberrypi", ip="10.0.0.9", api_url="", api_key="k",
                     folder_path=None, ssh_reachable=True, api_reachable=False, is_local=False,
                     ssh_user="pi")
    with patch("syncthing_manager.renamer._ssh_pause_folder"):
        res = rename_on_device(dev, "Testeo", "Testeo", "Testeo")
    assert res.skipped_absent is True and res.error is None and res.success is True


def test_path_already_at_tilde_and_windows():
    """A new folder's default path is '~/Label' but Syncthing stores it expanded; that must
    count as 'already there' so a re-run doesn't do a needless destructive recreate."""
    from syncthing_manager.renamer import _path_already_at
    assert _path_already_at("/home/pi/Nuevo", "~/Nuevo")          # tilde ↔ expanded → match
    assert _path_already_at("/home/pi/sub/Nuevo", "~/sub/Nuevo")  # multi-component tail
    assert _path_already_at("/srv/Nuevo", "/srv/Nuevo")           # exact
    assert _path_already_at("C:\\Sync\\Nuevo", "c:/sync/nuevo")   # windows case-insensitive
    assert not _path_already_at("/home/pi/Otro", "~/Nuevo")       # genuinely different → recreate
    assert not _path_already_at("/home/pi/XNuevo", "~/Nuevo")     # tail not on a boundary


class TestAuditFixesAndGaps:
    """Regression tests added during the full-project audit (pure cross-OS deciders + the
    most-destructive rollback path + the WinRM/SSH single-pattern collapse)."""

    def test_is_absolute_path_cross_os(self):
        from syncthing_manager.renamer import is_absolute_path
        assert is_absolute_path("D:\\Sync\\x")          # Windows drive (on a Linux host)
        assert is_absolute_path("\\\\srv\\share")        # UNC
        assert is_absolute_path("/etc/x")                # POSIX
        assert is_absolute_path("C:/Sync")
        assert not is_absolute_path("sub")
        assert not is_absolute_path("")

    def test_resolve_new_path_cross_os(self):
        from syncthing_manager.renamer import _resolve_new_path
        assert _resolve_new_path("/srv/Old", "New") == "/srv/New"
        assert _resolve_new_path("D:\\Sync\\Old", "New") == "D:\\Sync\\New"   # Windows parent kept
        assert _resolve_new_path("/srv/Old", "/other/New") == "/other/New"    # absolute pass-through

    def test_get_ignores_ssh_single_pattern_rewrapped(self):
        from unittest.mock import MagicMock, patch
        from syncthing_manager.renamer import get_ignores_on_device
        dev = DeviceInfo(device_id="X", name="pi", ip="1.2.3.4", api_url="", api_key="k",
                         folder_path="", ssh_reachable=True, api_reachable=False, is_local=False,
                         ssh_user="u")
        ssh = MagicMock()
        ssh.__enter__.return_value = ssh
        ssh.syncthing_api_get.return_value = {"ignore": "*.tmp"}   # single-element JSON collapse
        with patch("syncthing_manager.renamer.SSHClient", return_value=ssh):
            assert get_ignores_on_device(dev, "fid") == ["*.tmp"]  # NOT ['*','.','t','m','p']

    def test_rename_id_direct_rolls_back_on_create_fail(self):
        from unittest.mock import MagicMock, patch
        from syncthing_manager.renamer import _rename_id_direct
        from syncthing_manager.models import FolderConfig
        client = MagicMock()
        client.get_folder.return_value = FolderConfig.from_dict(
            {"id": "old", "label": "L", "path": "/p", "devices": [{"deviceID": "A"}]})
        client.create_folder.side_effect = lambda cfg: (
            (_ for _ in ()).throw(SyncthingError("create failed")) if cfg.get("id") == "new" else None)
        with patch("syncthing_manager.renamer._save_id_rename_recovery", return_value="rec"), \
             patch("syncthing_manager.renamer._clear_id_rename_recovery"):
            ok, msg = _rename_id_direct(client, "old", "new", "dev", dry_run=False)
        assert ok is False and "Revertido" in msg
        client.delete_folder.assert_called_once_with("old")
        assert any(c.args[0].get("id") == "old" for c in client.create_folder.call_args_list)

    def test_rename_id_direct_reports_lost_when_rollback_fails(self):
        from unittest.mock import MagicMock, patch
        from syncthing_manager.renamer import _rename_id_direct
        from syncthing_manager.models import FolderConfig
        client = MagicMock()
        client.get_folder.return_value = FolderConfig.from_dict(
            {"id": "old", "label": "L", "path": "/p", "devices": [{"deviceID": "A"}]})
        client.create_folder.side_effect = SyncthingError("always fails")   # new AND rollback fail
        with patch("syncthing_manager.renamer._save_id_rename_recovery", return_value="rec"), \
             patch("syncthing_manager.renamer._clear_id_rename_recovery") as clr:
            ok, msg = _rename_id_direct(client, "old", "new", "dev", dry_run=False)
        assert ok is False and "CARPETA PERDIDA" in msg
        clr.assert_not_called()   # snapshot KEPT for recovery


def test_ssh_client_factory_selects_transport_by_os():
    """renamer._ssh_client routes a Windows host to the PowerShell-over-SSH client and every
    other device to the POSIX SSHClient (Linux behaviour unchanged)."""
    from syncthing_manager.renamer import _ssh_client
    from syncthing_manager.ssh_ops import SSHClient
    from syncthing_manager.winrm_ops import WindowsSSHClient
    from syncthing_manager.models import DeviceInfo

    def _dev(os_type):
        return DeviceInfo(device_id="d", name="n", ip="1.2.3.4", api_url=None, api_key=None,
                          folder_path=None, ssh_reachable=True, api_reachable=False,
                          is_local=False, ssh_user="u", os_type=os_type)

    assert isinstance(_ssh_client(_dev("windows")), WindowsSSHClient)
    assert isinstance(_ssh_client(_dev("linux")), SSHClient)
    assert isinstance(_ssh_client(_dev(None)), SSHClient)


def _winhost(**over):
    from syncthing_manager.models import DeviceInfo
    base = dict(device_id="d", name="n", ip="1.2.3.4", api_url="http://1.2.3.4:8384",
                api_key="k", folder_path=None, ssh_reachable=True, api_reachable=True,
                is_local=False, ssh_user="u", os_type="linux")
    base.update(over)
    return DeviceInfo(**base)


def test_ensure_dir_and_marker_remote_with_ssh_creates_dir_and_marker():
    """A1-1: a REMOTE api-reachable device that ALSO has SSH (e.g. a LAN hub) must get its dir +
    .stfolder created via SSH on the direct-API branch — not be skipped as 'local only'."""
    from unittest.mock import MagicMock, patch
    from syncthing_manager.renamer import _ensure_dir_and_marker
    cli = MagicMock(); cli.__enter__ = MagicMock(return_value=cli); cli.__exit__ = MagicMock(return_value=False)
    cli.path_exists.return_value = False
    with patch("syncthing_manager.renamer._ssh_client", return_value=cli):
        warn = _ensure_dir_and_marker(_winhost(os_type="linux"), "/home/u/Sync")
    assert warn == ""
    cli.ensure_dir.assert_any_call("/home/u/Sync")
    cli.ensure_dir.assert_any_call("/home/u/Sync/.stfolder")   # POSIX separator


def test_ensure_dir_and_marker_windows_uses_backslash_marker():
    from unittest.mock import MagicMock, patch
    from syncthing_manager.renamer import _ensure_dir_and_marker
    cli = MagicMock(); cli.__enter__ = MagicMock(return_value=cli); cli.__exit__ = MagicMock(return_value=False)
    cli.path_exists.return_value = False
    with patch("syncthing_manager.renamer._ssh_client", return_value=cli):
        warn = _ensure_dir_and_marker(_winhost(os_type="windows"), r"C:\Sync")
    assert warn == ""
    cli.ensure_dir.assert_any_call(r"C:\Sync\.stfolder")       # Windows separator


def test_ensure_dir_and_marker_api_only_no_shell_warns():
    """A pure direct-API remote (no SSH/WinRM) genuinely can't have its dir created → warn."""
    from syncthing_manager.renamer import _ensure_dir_and_marker
    warn = _ensure_dir_and_marker(_winhost(ssh_reachable=False, winrm_reachable=False), "/x/Sync")
    assert "sin acceso de shell" in warn
