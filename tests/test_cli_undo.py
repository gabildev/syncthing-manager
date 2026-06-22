"""Round-trip tests for the CLI persistent-undo snapshot helpers (#56)."""
from syncthing_manager import cli, config


def _use_tmp_datadir(monkeypatch, tmp_path):
    monkeypatch.setenv(config._ENV, str(tmp_path / "data"))


class TestUndoSnapshot:
    def test_round_trip(self, monkeypatch, tmp_path):
        _use_tmp_datadir(monkeypatch, tmp_path)
        snap = {
            "url": "https://127.0.0.1:8384",
            "folder_id": "newid",
            "orig_folder_id": "oldid",
            "old_label": "Antiguo",
            "new_label": "Nuevo",
            "old_dir_name": "Antiguo",
            "skip_path_rename": False,
            "id_renamed": True,
        }
        assert cli._load_undo_snapshot() is None
        cli._save_undo_snapshot(snap)
        assert cli._undo_path().exists()
        loaded = cli._load_undo_snapshot()
        assert loaded == snap

    def test_clear(self, monkeypatch, tmp_path):
        _use_tmp_datadir(monkeypatch, tmp_path)
        cli._save_undo_snapshot({"folder_id": "x", "old_label": "L", "old_dir_name": "p"})
        assert cli._undo_path().exists()
        cli._clear_undo_snapshot()
        assert not cli._undo_path().exists()
        assert cli._load_undo_snapshot() is None

    def test_clear_when_absent_is_noop(self, monkeypatch, tmp_path):
        _use_tmp_datadir(monkeypatch, tmp_path)
        cli._clear_undo_snapshot()  # must not raise
        assert cli._load_undo_snapshot() is None

    def test_path_under_data_dir(self, monkeypatch, tmp_path):
        _use_tmp_datadir(monkeypatch, tmp_path)
        assert cli._undo_path() == config.data_dir() / "undo.json"
