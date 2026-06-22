"""Arch-aware agent-template selection (multi-arch Linux support)."""
from __future__ import annotations

import pytest

from syncthing_manager.generate import (
    normalize_arch, _template_names, _find_agent_template, agent_template_available,
)


@pytest.mark.parametrize("raw,expect", [
    ("x86_64", "amd64"), ("AMD64", "amd64"), ("x64", "amd64"),
    ("aarch64", "arm64"), ("arm64", "arm64"),
    ("armv7l", "armv7"), ("armhf", "armv7"), ("armv6l", "armv7"),
    ("", "amd64"), ("riscv64", "riscv64"),
])
def test_normalize_arch(raw, expect):
    assert normalize_arch(raw) == expect


def test_template_names_linux_arch_then_fallback():
    assert _template_names("linux", "arm64") == [
        "syncthing-manager-agent-template-linux-arm64",
        "syncthing-manager-agent-template",
    ]
    # raw arch is normalized in the name
    assert _template_names("linux", "aarch64")[0].endswith("-linux-arm64")
    # no arch → just the un-suffixed name (backward compat with local single-arch builds)
    assert _template_names("linux", None) == ["syncthing-manager-agent-template"]
    # windows is single-template (x64 emulates on ARM) — arch ignored
    assert _template_names("windows", "arm64") == ["syncthing-manager-agent-template.exe"]


def test_find_prefers_arch_specific_then_falls_back(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("platform.machine", lambda: "x86_64")   # host = amd64 (deterministic)
    dist = tmp_path / "dist"
    dist.mkdir()
    arch_file = dist / "syncthing-manager-agent-template-linux-arm64"
    plain = dist / "syncthing-manager-agent-template"
    arch_file.write_bytes(b"ARM"); plain.write_bytes(b"X86")
    # arch-specific wins for arm64
    assert _find_agent_template("linux", "arm64") == arch_file
    # the HOST arch (amd64) with no specific file falls back to the plain (host-arch) template
    assert _find_agent_template("linux", "amd64") == plain
    assert agent_template_available("linux", "arm64") is True
    # missing everything → None
    arch_file.unlink(); plain.unlink()
    assert _find_agent_template("linux", "arm64") is None


def test_cross_arch_never_falls_back_to_host_template(tmp_path, monkeypatch):
    """Headline safety check: requesting a NON-host arch must NOT silently return the host-arch
    plain template (it would be the wrong architecture)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("platform.machine", lambda: "x86_64")   # host = amd64
    dist = tmp_path / "dist"; dist.mkdir()
    (dist / "syncthing-manager-agent-template").write_bytes(b"X86")   # ONLY the host-arch plain
    assert _find_agent_template("linux", "arm64") is None            # cross-arch → never the plain
    assert agent_template_available("linux", "arm64") is False
    # the host arch still accepts the plain fallback
    assert _find_agent_template("linux", "amd64") == dist / "syncthing-manager-agent-template"


def test_template_names_macos_never_uses_plain():
    # macOS must use arch-suffixed names only — the un-suffixed template is the Linux/host binary
    # (CI copies the host build → plain), so emitting it for macOS would ship a mislabeled Mach-O.
    assert _template_names("macos", "arm64") == ["syncthing-manager-agent-template-macos-arm64"]
    assert _template_names("macos", "aarch64")[0].endswith("-macos-arm64")
    names = _template_names("macos", None)   # no arch → both macOS arches, NEVER the plain
    assert names == [
        "syncthing-manager-agent-template-macos-amd64",
        "syncthing-manager-agent-template-macos-arm64",
    ]
    assert "syncthing-manager-agent-template" not in names


def test_macos_available_only_from_macos_suffixed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    dist = tmp_path / "dist"; dist.mkdir()
    from syncthing_manager.generate import available_macos_arches
    # only the plain (Linux/host) template → macOS must NOT be enabled off the plain
    (dist / "syncthing-manager-agent-template").write_bytes(b"x")
    assert agent_template_available("macos") is False
    assert available_macos_arches() == []
    (dist / "syncthing-manager-agent-template-macos-arm64").write_bytes(b"a")
    assert agent_template_available("macos", "arm64") is True
    assert available_macos_arches() == ["arm64"]


def test_linux_no_arch_on_macos_host_avoids_plain(monkeypatch):
    # On a macOS host the un-suffixed template is the macOS binary (CI copies host build → plain),
    # so a no-arch Linux request must use arch-suffixed Linux names, not the (Mach-O) plain.
    monkeypatch.setattr("sys.platform", "darwin")
    names = _template_names("linux", None)
    assert names == [
        "syncthing-manager-agent-template-linux-amd64",
        "syncthing-manager-agent-template-linux-arm64",
    ]
    assert "syncthing-manager-agent-template" not in names
    # a non-macOS host keeps the historical plain behavior
    monkeypatch.setattr("sys.platform", "linux")
    assert _template_names("linux", None) == ["syncthing-manager-agent-template"]


def test_linux_explicit_arch_on_macos_host_never_uses_plain(monkeypatch):
    # Even with an EXPLICIT arch equal to the host's, a Linux request on a macOS host must not
    # append the plain template (the macOS Mach-O) — the cross-arch check wouldn't strip it since
    # the arch matches the host, so it would otherwise be mislabeled as a Linux agent.
    monkeypatch.setattr("sys.platform", "darwin")
    assert _template_names("linux", "amd64") == ["syncthing-manager-agent-template-linux-amd64"]
    assert "syncthing-manager-agent-template" not in _template_names("linux", "amd64")
    # Off a macOS host the plain fallback still applies (regression guard).
    monkeypatch.setattr("sys.platform", "linux")
    assert "syncthing-manager-agent-template" in _template_names("linux", "amd64")


class TestSelectAgentBuilds:
    """Auto-pick of agent binaries from DETECTED device arches (the GUI/CLI agent flow)."""

    def _sel(self, detected, has_undetected, avail=("amd64", "arm64"), base="amd64"):
        from syncthing_manager.generate import select_agent_builds
        return select_agent_builds(set(detected), has_undetected, list(avail), base)

    def test_all_arm64_detected_skips_amd64_base(self):
        # Every device is a detected arm64 (template present) → build ONLY arm64, not the base
        # amd64 binary that no device would run.
        build_base, extra, uncovered = self._sel({"arm64"}, has_undetected=False)
        assert build_base is False
        assert extra == ["arm64"]
        assert uncovered == []

    def test_mixed_detected_builds_base_plus_extra(self):
        build_base, extra, uncovered = self._sel({"amd64", "arm64"}, has_undetected=False)
        assert build_base is True            # amd64 is the base → plain build covers it
        assert extra == ["arm64"]
        assert uncovered == []

    def test_undetected_forces_base_fallback(self):
        # An undetected device → always build the base as the best-guess catch-all.
        build_base, extra, uncovered = self._sel({"arm64"}, has_undetected=True)
        assert build_base is True
        assert extra == ["arm64"]

    def test_nothing_detected_builds_only_base(self):
        build_base, extra, uncovered = self._sel(set(), has_undetected=True)
        assert build_base is True and extra == [] and uncovered == []

    def test_non_amd64_base_arm64_host(self):
        # arm64 HOST (base_arch="arm64"): an amd64 device needs an extra amd64 build; the arm64
        # devices are covered by the base. Exercises the base_arch != "amd64" branch.
        build_base, extra, uncovered = self._sel({"amd64", "arm64"}, False,
                                                 avail=("amd64", "arm64"), base="arm64")
        assert build_base is True            # arm64 (the base) is among detected
        assert extra == ["amd64"]
        assert uncovered == []

    def test_non_amd64_base_skips_base_when_all_extra(self):
        # arm64 host, every device is detected amd64 → skip the arm64 base, build only amd64.
        build_base, extra, uncovered = self._sel({"amd64"}, False,
                                                 avail=("amd64", "arm64"), base="arm64")
        assert build_base is False and extra == ["amd64"] and uncovered == []

    def test_multiple_extra_arches_sorted(self):
        # >1 extra arch builds (both present as templates), base also built (it's in detected).
        build_base, extra, uncovered = self._sel({"amd64", "arm64"}, False,
                                                 avail=("amd64", "arm64"), base="amd64")
        assert extra == ["arm64"]            # amd64 is base; arm64 is the lone extra
        assert build_base is True

    def test_detected_arch_without_template_is_uncovered(self):
        # Only an arch with no embedded template is detected (here armv7; same shape as a macOS
        # set of {arm64} when only amd64 is shipped). It's reported as uncovered and NO useless
        # base is built — the base would run on no one (fix #3). has_undetected stays the only
        # thing that can force the base.
        build_base, extra, uncovered = self._sel({"armv7"}, has_undetected=False,
                                                 avail=("amd64", "arm64"))
        assert uncovered == ["armv7"]
        assert extra == []
        assert build_base is False           # base helps no device → not built

    def test_uncovered_with_undetected_still_builds_base(self):
        # Same uncovered arch, but an undetected device is present → the base IS built as the
        # catch-all for that undetected device (the uncovered one is still reported).
        build_base, extra, uncovered = self._sel({"armv7"}, has_undetected=True,
                                                 avail=("amd64", "arm64"))
        assert build_base is True and extra == [] and uncovered == ["armv7"]

    def test_macos_arm64_only_set_with_amd64_template_skips_base(self):
        # macOS devices all detected arm64, but only the amd64 macOS template is embedded → arm64
        # is uncovered and no useless amd64 base is built (fix #3, the concrete macOS case).
        build_base, extra, uncovered = self._sel({"arm64"}, has_undetected=False,
                                                 avail=("amd64",), base="amd64")
        assert build_base is False and extra == [] and uncovered == ["arm64"]


def test_embed_strips_gui_only_arch_keys(tmp_path, monkeypatch):
    """arch/arch_detected are GUI-only hints (which template to build); the agent never reads
    them, so they must NOT be baked into the embedded agent config — only real agent keys."""
    import json
    from syncthing_manager.generate import generate_multi_agent_file
    from syncthing_manager.agent import MARKER_START, MARKER_END
    monkeypatch.chdir(tmp_path)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "syncthing-manager-agent-template").write_bytes(b"FAKE-ELF")   # plain Linux template
    entry = {"device_id": "D1", "device_name": "pi", "folder_id": "f", "new_label": "L",
             "new_dir_name": "L", "old_path": "/x", "api_key": "k",
             "api_url": "http://127.0.0.1:8384", "skip_path_rename": False, "dry_run": False,
             "arch": "arm64", "arch_detected": True}
    out = generate_multi_agent_file(entries=[entry], target_os="linux", output_dir=tmp_path)
    data = out.read_bytes()
    i = data.find(MARKER_START)
    blob = data[i + len(MARKER_START):data.find(MARKER_END, i)]
    dev = json.loads(blob)["devices"]["D1"]
    assert "arch" not in dev and "arch_detected" not in dev        # GUI hints stripped
    assert dev["old_path"] == "/x" and dev["device_id"] == "D1"     # real keys preserved


def test_available_linux_arches(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    dist = tmp_path / "dist"
    dist.mkdir()
    from syncthing_manager.generate import available_linux_arches
    assert available_linux_arches() == []                      # nothing → empty
    (dist / "syncthing-manager-agent-template").write_bytes(b"x")  # plain doesn't count
    assert available_linux_arches() == []
    (dist / "syncthing-manager-agent-template-linux-arm64").write_bytes(b"a")
    assert available_linux_arches() == ["arm64"]
    (dist / "syncthing-manager-agent-template-linux-amd64").write_bytes(b"b")
    assert available_linux_arches() == ["amd64", "arm64"]
