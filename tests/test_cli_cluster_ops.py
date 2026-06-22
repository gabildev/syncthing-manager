"""CLI cluster ops (unshare / delete-folder): device resolution + the destructive-delete
safety gate (typed confirmation) + flag plumbing. These commands are thin wrappers over the
heavily-tested renamer backend, so the value here is the CLI-side behavior the backend can't
enforce: resolving a device token, aborting a delete on a mismatched typed name, and passing
--keep-data/--dry-run/--yes through correctly."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from syncthing_manager.cli import app, _resolve_device, _print_cluster_results
from syncthing_manager.models import DeviceInfo, FolderConfig

runner = CliRunner()


def _dev(did, name, *, is_local=False, ssh_reachable=False, winrm_reachable=False,
         api_reachable=True, folder_path=None):
    return DeviceInfo(device_id=did, name=name, ip=None, api_url=None, api_key=None,
                      folder_path=folder_path, ssh_reachable=ssh_reachable,
                      api_reachable=api_reachable, is_local=is_local,
                      winrm_reachable=winrm_reachable)


def _patch_cli(devices, folder):
    """Stub out the network-touching seams in cli.py so the command runs offline."""
    return patch.multiple(
        "syncthing_manager.cli",
        _get_client=MagicMock(return_value=MagicMock()),
        _pick_folder=MagicMock(return_value=folder),
        _load_saved_credentials=MagicMock(return_value=[]),
        _load_devices_config=MagicMock(return_value=[]),
        discover_devices=MagicMock(return_value=devices),
    )


# ── _resolve_device ──────────────────────────────────────────────────────────
class TestResolveDevice:
    def _two(self):
        return [_dev("ABCDEFG-1111111", "pi"), _dev("ZZZZZZZ-2222222", "nas")]

    def test_exact_id(self):
        assert _resolve_device(self._two(), "ABCDEFG-1111111").name == "pi"

    def test_unambiguous_prefix_case_insensitive(self):
        assert _resolve_device(self._two(), "abcdefg").name == "pi"

    def test_ambiguous_prefix_returns_none(self):
        devs = [_dev("ABCDEFG", "pi"), _dev("ABCZZZZ", "nas")]
        assert _resolve_device(devs, "ABC") is None

    def test_exact_name_case_insensitive(self):
        assert _resolve_device(self._two(), "NAS").device_id == "ZZZZZZZ-2222222"

    def test_not_found(self):
        assert _resolve_device(self._two(), "ghost") is None

    def test_blank_token(self):
        assert _resolve_device(self._two(), "   ") is None


def test_print_cluster_results_counts_failures(capsys):
    n = _print_cluster_results("t", [("a", True, "ok"), ("b", False, "no"), ("c", False, "x")])
    assert n == 2


# ── unshare ──────────────────────────────────────────────────────────────────
class TestUnshare:
    def test_calls_backend_with_resolved_target(self):
        folder = FolderConfig(id="f1", label="Docs", path="/x", devices=[])
        devices = [_dev("PIXXXXX-aaa", "pi"), _dev("NASYYYY-bbb", "nas")]
        with _patch_cli(devices, folder), \
             patch("syncthing_manager.renamer.unshare_folder_everywhere",
                   return_value=[("nas", True, "ok")]) as m:
            res = runner.invoke(app, ["unshare", "-f", "f1", "-d", "nas"])
        assert res.exit_code == 0, res.output
        args, kwargs = m.call_args
        assert args[0] is devices and args[1] == "f1" and args[2] == "NASYYYY-bbb"

    def test_unknown_device_exits_1_without_calling_backend(self):
        folder = FolderConfig(id="f1", label="Docs", path="/x", devices=[])
        with _patch_cli([_dev("PIXXXXX-aaa", "pi")], folder), \
             patch("syncthing_manager.renamer.unshare_folder_everywhere") as m:
            res = runner.invoke(app, ["unshare", "-f", "f1", "-d", "ghost"])
        assert res.exit_code == 1
        m.assert_not_called()

    def test_unreachable_member_reported_as_failure_exit_1(self):
        folder = FolderConfig(id="f1", label="Docs", path="/x", devices=[])
        devices = [_dev("NASYYYY-bbb", "nas")]
        with _patch_cli(devices, folder), \
             patch("syncthing_manager.renamer.unshare_folder_everywhere",
                   return_value=[("nas", False, "no accesible")]):
            res = runner.invoke(app, ["unshare", "-f", "f1", "-d", "nas"])
        assert res.exit_code == 1


# ── delete-folder (destructive) ───────────────────────────────────────────────
class TestDeleteFolder:
    def _folder(self):
        return FolderConfig(id="f1", label="Docs", path="/srv/docs", devices=[])

    def test_aborts_on_wrong_typed_name_nothing_deleted(self):
        devices = [_dev("LOCAL-x", "local", is_local=True)]
        with _patch_cli(devices, self._folder()), \
             patch("syncthing_manager.renamer.delete_folder_everywhere") as m:
            res = runner.invoke(app, ["delete-folder", "-f", "f1"], input="WRONG\n")
        assert res.exit_code == 1
        m.assert_not_called()                      # the safety gate held — no deletion

    def test_proceeds_on_correct_typed_name(self):
        devices = [_dev("LOCAL-x", "local", is_local=True)]
        with _patch_cli(devices, self._folder()), \
             patch("syncthing_manager.renamer.delete_folder_everywhere",
                   return_value=[("local", True, "borrado")]) as m:
            res = runner.invoke(app, ["delete-folder", "-f", "f1"], input="Docs\n")
        assert res.exit_code == 0, res.output
        m.assert_called_once()

    def test_yes_skips_confirmation(self):
        devices = [_dev("LOCAL-x", "local", is_local=True)]
        with _patch_cli(devices, self._folder()), \
             patch("syncthing_manager.renamer.delete_folder_everywhere",
                   return_value=[("local", True, "borrado")]) as m:
            res = runner.invoke(app, ["delete-folder", "-f", "f1", "--yes"])  # no stdin
        assert res.exit_code == 0, res.output
        m.assert_called_once()

    def test_dry_run_skips_confirmation_and_passes_flag(self):
        devices = [_dev("LOCAL-x", "local", is_local=True)]
        with _patch_cli(devices, self._folder()), \
             patch("syncthing_manager.renamer.delete_folder_everywhere",
                   return_value=[("local", True, "[dry-run] …")]) as m:
            res = runner.invoke(app, ["delete-folder", "-f", "f1", "--dry-run"])
        assert res.exit_code == 0, res.output
        assert m.call_args.kwargs.get("dry_run") is True

    def test_keep_data_passes_delete_data_false(self):
        devices = [_dev("LOCAL-x", "local", is_local=True)]
        with _patch_cli(devices, self._folder()), \
             patch("syncthing_manager.renamer.delete_folder_everywhere",
                   return_value=[("local", True, "ok")]) as m:
            res = runner.invoke(app, ["delete-folder", "-f", "f1", "--yes", "--keep-data"])
        assert res.exit_code == 0, res.output
        assert m.call_args.kwargs.get("delete_data") is False

    def test_on_device_routes_to_single_device_delete(self):
        devices = [_dev("PIXXXXX-aaa", "pi", ssh_reachable=True),
                   _dev("NASYYYY-bbb", "nas")]
        fake = MagicMock(device_name="pi", ok=True, message="borrado")
        with _patch_cli(devices, self._folder()), \
             patch("syncthing_manager.renamer.delete_folder_on_device",
                   return_value=fake) as m_one, \
             patch("syncthing_manager.renamer.delete_folder_everywhere") as m_all:
            res = runner.invoke(app, ["delete-folder", "-f", "f1", "--on-device", "pi", "--yes"])
        assert res.exit_code == 0, res.output
        m_one.assert_called_once()
        m_all.assert_not_called()
        assert m_one.call_args.args[0].device_id == "PIXXXXX-aaa"


# ── create-folder (local) ─────────────────────────────────────────────────────
class TestCreateFolder:
    def _client(self, *, exists=False, check_raises=False):
        c = MagicMock()
        if check_raises:
            c.get_folder.side_effect = RuntimeError("boom")
        else:
            c.get_folder.return_value = (MagicMock() if exists else None)
        c.get_my_device_id.return_value = "LOCAL-aaaa"
        return c

    def test_happy_path_creates_and_rescans(self, tmp_path):
        c = self._client(exists=False)
        with patch("syncthing_manager.cli._get_client", return_value=c):
            res = runner.invoke(app, ["create-folder", "--id", "f1", "-p", str(tmp_path / "docs"),
                                      "-l", "Docs"])
        assert res.exit_code == 0, res.output
        c.create_folder.assert_called_once()
        cfg = c.create_folder.call_args.args[0]
        assert cfg["id"] == "f1" and cfg["label"] == "Docs"
        assert cfg.get("paused") is not True          # created unpaused (Syncthing default)
        assert cfg["devices"] == [{"deviceID": "LOCAL-aaaa"}]
        c.rescan_folder.assert_called_once_with("f1")

    def test_clash_aborts_without_creating(self):
        c = self._client(exists=True)
        with patch("syncthing_manager.cli._get_client", return_value=c):
            res = runner.invoke(app, ["create-folder", "--id", "f1", "-p", "/x"])
        assert res.exit_code == 1
        c.create_folder.assert_not_called()

    def test_unverified_check_aborts_without_creating(self):
        c = self._client(check_raises=True)
        with patch("syncthing_manager.cli._get_client", return_value=c):
            res = runner.invoke(app, ["create-folder", "--id", "f1", "-p", "/x"])
        assert res.exit_code == 1
        c.create_folder.assert_not_called()

    def test_dry_run_creates_nothing(self):
        c = self._client(exists=False)
        with patch("syncthing_manager.cli._get_client", return_value=c):
            res = runner.invoke(app, ["create-folder", "--id", "f1", "-p", "/x", "--dry-run"])
        assert res.exit_code == 0, res.output
        c.create_folder.assert_not_called()


# ── share (drives the real topology diff, applies on the anchor) ──────────────
class TestShare:
    def _folder(self, members=("LOCAL-aaaa",)):
        devs = [{"deviceID": m} for m in members]
        return FolderConfig(id="f1", label="Docs", path="/srv/docs", devices=devs,
                            raw={"id": "f1", "type": "sendreceive", "devices": devs})

    def _cli_client(self):
        c = MagicMock()
        c.get_my_device_id.return_value = "LOCAL-aaaa"
        return c

    def _patch(self, client, devices, folder):
        return patch.multiple(
            "syncthing_manager.cli",
            _get_client=MagicMock(return_value=client),
            _pick_folder=MagicMock(return_value=folder),
            _load_saved_credentials=MagicMock(return_value=[]),
            _load_devices_config=MagicMock(return_value=[]),
            discover_devices=MagicMock(return_value=devices),
        )

    def test_share_new_device_validates_and_applies_on_local_anchor(self):
        client = self._cli_client()
        client.check_device_id.return_value = {"id": "NEWDEV1-bbbbbbb"}
        devices = [_dev("LOCAL-aaaa", "this", is_local=True, api_reachable=True)]
        tr = MagicMock(device_name="this", ok=True, message="compartida")
        with self._patch(client, devices, self._folder()), \
             patch("syncthing_manager.renamer.apply_topology_on_device", return_value=tr) as m:
            res = runner.invoke(app, ["share", "-f", "f1", "-d", "NEWDEV1-bbbbbbb"])
        assert res.exit_code == 0, res.output
        client.check_device_id.assert_called_once()
        m.assert_called_once()
        args, kwargs = m.call_args
        assert args[0].device_id == "LOCAL-aaaa" and args[1] == "f1"      # applied on local anchor
        added = kwargs["diff"]["links_added"]
        assert any("NEWDEV1-bbbbbbb" in e and "LOCAL-aaaa" in e for e in added)

    def test_share_invalid_device_id_exits_1(self):
        client = self._cli_client()
        client.check_device_id.return_value = {"error": "not a device id"}
        devices = [_dev("LOCAL-aaaa", "this", is_local=True, api_reachable=True)]
        with self._patch(client, devices, self._folder()), \
             patch("syncthing_manager.renamer.apply_topology_on_device") as m:
            res = runner.invoke(app, ["share", "-f", "f1", "-d", "garbage"])
        assert res.exit_code == 1
        m.assert_not_called()

    def test_share_already_member_is_noop(self):
        # The peer already shares with the local node (edge exists in the built graph).
        client = self._cli_client()
        devices = [_dev("LOCAL-aaaa", "this", is_local=True, api_reachable=True),
                   _dev("PEER-ccccccc", "nas", api_reachable=True)]
        folder = self._folder(members=("LOCAL-aaaa", "PEER-ccccccc"))
        with self._patch(client, devices, folder), \
             patch("syncthing_manager.renamer.apply_topology_on_device") as m:
            res = runner.invoke(app, ["share", "-f", "f1", "-d", "PEER-ccccccc"])
        assert res.exit_code == 0, res.output
        m.assert_not_called()                       # edge already present → nothing applied

    def test_share_with_peer_anchor_applies_on_that_peer(self):
        client = self._cli_client()
        client.check_device_id.return_value = {"id": "NEWDEV1-bbbbbbb"}
        devices = [_dev("LOCAL-aaaa", "this", is_local=True, api_reachable=True),
                   _dev("PEER-ccccccc", "nas", api_reachable=True)]
        folder = self._folder(members=("LOCAL-aaaa", "PEER-ccccccc"))
        tr = MagicMock(device_name="nas", ok=True, message="ok")
        with self._patch(client, devices, folder), \
             patch("syncthing_manager.renamer.apply_topology_on_device", return_value=tr) as m:
            res = runner.invoke(app, ["share", "-f", "f1", "-d", "NEWDEV1-bbbbbbb", "--with", "nas"])
        assert res.exit_code == 0, res.output
        assert m.call_args.args[0].device_id == "PEER-ccccccc"           # anchored on the peer
