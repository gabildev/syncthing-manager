from __future__ import annotations

from unittest.mock import patch

import pytest

from syncthing_manager import config


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """config caches parsed settings in module globals keyed by (path, mtime, size). Reset it
    around every test so a prior test's cache can't bleed in and make results order-dependent."""
    config._settings_cache = None
    config._settings_cache_key = None
    yield
    config._settings_cache = None
    config._settings_cache_key = None


class TestDataDirResolution:
    def test_env_override_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv(config._ENV, str(tmp_path / "envdir"))
        assert config.data_dir() == (tmp_path / "envdir")

    def test_prefers_existing_os_standard(self, tmp_path, monkeypatch):
        monkeypatch.delenv(config._ENV, raising=False)
        std = tmp_path / "std"
        std.mkdir()
        (std / "credentials.yml").write_text("devices: []")
        with patch.object(config, "os_standard_dir", return_value=std), \
             patch.object(config, "app_dir", return_value=tmp_path / "exe"):
            # existing data in os-standard → keep it (don't strand it)
            assert config.data_dir() == std

    def test_fresh_install_is_portable(self, tmp_path, monkeypatch):
        monkeypatch.delenv(config._ENV, raising=False)
        std = tmp_path / "std"          # empty / non-existent → no existing data
        exe = tmp_path / "exe"
        exe.mkdir()
        with patch.object(config, "os_standard_dir", return_value=std), \
             patch.object(config, "app_dir", return_value=exe):
            assert config.data_dir() == exe

    def test_fallback_os_standard_when_not_frozen(self, tmp_path, monkeypatch):
        monkeypatch.delenv(config._ENV, raising=False)
        std = tmp_path / "std"
        with patch.object(config, "os_standard_dir", return_value=std), \
             patch.object(config, "app_dir", return_value=None):
            assert config.data_dir() == std


class TestSettings:
    def test_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setenv(config._ENV, str(tmp_path / "d"))
        config.save_settings({"advanced": True, "lang": "es"})
        assert config.load_settings() == {"advanced": True, "lang": "es"}
        config.set_setting("advanced", False)
        assert config.get_setting("advanced") is False

    def test_missing_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv(config._ENV, str(tmp_path / "empty"))
        assert config.load_settings() == {}

    def test_cache_detects_external_edit(self, tmp_path, monkeypatch):
        import json
        import time
        monkeypatch.setenv(config._ENV, str(tmp_path / "c"))
        config.save_settings({"a": 1})
        assert config.get_setting("a") == 1            # served write-through
        time.sleep(0.01)
        # An edit made outside save_settings must still be seen (key includes mtime+size).
        (config.settings_path()).write_text(json.dumps({"a": 9, "ext": True}))
        assert config.load_settings() == {"a": 9, "ext": True}

    def test_cache_returns_isolated_copy(self, tmp_path, monkeypatch):
        monkeypatch.setenv(config._ENV, str(tmp_path / "iso"))
        config.save_settings({"nested": {"k": 1}})
        got = config.load_settings()
        got["nested"]["k"] = 999          # mutating the result must not poison the cache
        assert config.get_setting("nested") == {"k": 1}


class TestRelocate:
    def test_moves_files_and_cleans_orphan(self, tmp_path, monkeypatch):
        # Frozen-portable scenario: pointer goes to the exe dir, so the emptied
        # os-standard source can be removed (no orphan under ~/.config).
        monkeypatch.delenv(config._ENV, raising=False)
        old = tmp_path / "old"
        old.mkdir()
        (old / "credentials.yml").write_text("devices: []")
        (old / "settings.json").write_text("{}")
        exe = tmp_path / "exe"
        exe.mkdir()
        new = tmp_path / "new"
        with patch.object(config, "os_standard_dir", return_value=old), \
             patch.object(config, "app_dir", return_value=exe):
            config.set_data_dir(new)
            assert (new / "credentials.yml").exists()
            assert (new / "settings.json").exists()
            assert not old.exists()              # orphan removed (was emptied)
            assert (exe / config._POINTER).read_text().strip() == str(new)  # pointer kept

    def test_move_to_portable_clears_pointer(self, tmp_path, monkeypatch):
        monkeypatch.delenv(config._ENV, raising=False)
        old = tmp_path / "old"
        old.mkdir()
        (old / "credentials.yml").write_text("devices: []")
        exe = tmp_path / "exe"
        exe.mkdir()
        with patch.object(config, "os_standard_dir", return_value=old), \
             patch.object(config, "app_dir", return_value=exe):
            config.set_data_dir(exe)                 # → portable (the exe dir itself)
            assert (exe / "credentials.yml").exists()
            assert not (exe / config._POINTER).exists()   # portable default needs no pointer


class TestTopologySnapshotDelete:
    """delete_topology_snapshot must forget the persisted snapshot so a folder re-created
    with the SAME id can't resurrect now-deleted nodes/links (the ghost-Pi / blank-preview
    / GET-404 cluster of bugs)."""

    def test_delete_removes_persisted_snapshot(self, tmp_path, monkeypatch):
        monkeypatch.setenv(config._ENV, str(tmp_path / "snap"))
        config.save_topology_snapshot("Testeo", {"nodes": {}, "edges": []})
        assert config.topology_snapshot_path("Testeo").exists()
        config.delete_topology_snapshot("Testeo")
        assert not config.topology_snapshot_path("Testeo").exists()
        assert config.load_topology_snapshot("Testeo") is None   # no resurrection

    def test_delete_missing_is_noop(self, tmp_path, monkeypatch):
        monkeypatch.setenv(config._ENV, str(tmp_path / "snap2"))
        config.delete_topology_snapshot("nonexistent")           # must not raise


class TestSafeFolderKey:
    def test_simple_id_kept_verbatim_backward_compatible(self):
        # Already filesystem-safe + short → unchanged (existing snapshots keep their name).
        assert config._safe_folder_key("default") == "default"
        assert config._safe_folder_key("abc-123_x.y") == "abc-123_x.y"

    def test_distinct_unsafe_ids_dont_collide(self):
        # Two IDs that sanitise to the same chars must NOT map to the same filename.
        a = config._safe_folder_key("proj/alpha")
        b = config._safe_folder_key("proj_alpha")
        assert a != b
        assert a.startswith("proj_alpha_") and b == "proj_alpha"

    def test_long_id_is_bounded_and_unique(self):
        long_a = "x" * 200 + "A"
        long_b = "x" * 200 + "B"
        ka, kb = config._safe_folder_key(long_a), config._safe_folder_key(long_b)
        assert ka != kb and len(ka) <= 120 and len(kb) <= 120

    def test_empty_id_defaults(self):
        assert config._safe_folder_key("") == "default"


class TestMoveOverPreservesData:
    """set_data_dir's _move_over must not destroy the destination if the move fails."""

    def test_failed_move_restores_destination(self, tmp_path, monkeypatch):
        old = tmp_path / "old"
        new = tmp_path / "new"
        old.mkdir(); new.mkdir()
        (old / "credentials.yml").write_text("devices: [{device_id: SRC}]")
        (new / "credentials.yml").write_text("devices: [{device_id: DST}]")  # pre-existing dst
        monkeypatch.setattr(config, "data_dir", lambda: old)
        monkeypatch.setattr(config, "_write_pointer", lambda *a, **k: None)
        # Force the move to fail AFTER the destination has been cleared out of the way.
        import shutil
        monkeypatch.setattr(shutil, "move",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
        with __import__("pytest").raises(OSError):
            config.set_data_dir(new, move=True)
        # The destination's original data must still be there (restored from backup).
        assert (new / "credentials.yml").read_text() == "devices: [{device_id: DST}]"
        assert not list(new.glob("*.bak-move"))   # backup cleaned up on restore
