"""Definitive delete (Syncthing config + on-disk data) — guards and capability gating."""
from unittest.mock import MagicMock, patch

from syncthing_manager.models import DeviceInfo
from syncthing_manager.renamer import (
    is_protected_delete_path, delete_folder_on_device, delete_folder_everywhere,
    TopologyResult,
)


def test_delete_everywhere_reads_real_result_ok_not_success():
    # Regression: delete_folder_everywhere must read TopologyResult.ok (the dataclass has no
    # `.success`). Using a REAL TopologyResult — not a MagicMock — so a `.success` access would
    # raise AttributeError instead of silently returning a truthy mock attribute.
    dev = _local()
    with patch("syncthing_manager.renamer.delete_folder_on_device",
               return_value=TopologyResult("local", True, "borrada en disco")):
        out = delete_folder_everywhere([dev], "f1", member_ids={"L"})
    # 4-tuple now: (name, ok, msg, disk_not_deleted) — the flag lets the UI warn when files were
    # left on disk without matching the (translated) message text.
    assert out == [("local", True, "borrada en disco", False)]


def _local(path="~/Sync"):
    return DeviceInfo(device_id="L", name="local", ip="127.0.0.1",
                      api_url="http://127.0.0.1:8384", api_key="k", folder_path=path,
                      ssh_reachable=False, api_reachable=True, is_local=True, os_type="linux")


def _ssh_remote(path="/home/pi/Sync"):
    return DeviceInfo(device_id="P", name="pi", ip="10.0.0.2", api_url=None, api_key="k",
                      folder_path=path, ssh_reachable=True, api_reachable=False,
                      is_local=False, os_type="linux", ssh_user="pi")


def _api_only_remote(path="/srv/Sync"):
    return DeviceInfo(device_id="A", name="api", ip="10.0.0.3",
                      api_url="http://10.0.0.3:8384", api_key="k", folder_path=path,
                      ssh_reachable=False, api_reachable=True, is_local=False, os_type="linux")


# ── protected-path guard ────────────────────────────────────────────────────

def test_protected_paths_posix():
    for p in ("/", "/etc", "/usr", "/home", "/home/bob", "/root", "~", "", None, "/var"):
        assert is_protected_delete_path(p, "linux") is True, p
    for p in ("/home/bob/Sync", "~/ULL", "/mnt/data/share", "/srv/syncthing/x"):
        assert is_protected_delete_path(p, "linux") is False, p


def test_protected_paths_windows():
    for p in ("C:\\", "C:", "C:\\Windows", "C:\\Windows\\System32", "C:\\Windows\\SysWOW64",
              "C:\\Program Files", "C:\\Program Files (x86)", "C:\\Users", "C:\\Users\\bob",
              "C:\\ProgramData"):
        assert is_protected_delete_path(p, "windows") is True, p
    for p in ("C:\\Users\\bob\\Sync", "D:\\Sync", "E:\\data\\folder"):
        assert is_protected_delete_path(p, "windows") is False, p


def test_protected_paths_traversal_and_relative():
    # '..' segments are ambiguous (PurePath doesn't resolve them) → always refuse.
    for p in ("/home/bob/../..", "/srv/share/../../etc", "~/Sync/../.."):
        assert is_protected_delete_path(p, "linux") is True, p
    # Bare relative paths resolve against CWD → refuse.
    for p in ("Sync", "relative/sub"):
        assert is_protected_delete_path(p, "linux") is True, p
    # POSIX preserves a leading '//' (PurePosixPath keeps it), but on Linux '//etc' == '/etc'
    # and '//' is root → both must be protected, not slip through.
    for p in ("//", "///", "//etc", "//home/bob"):
        assert is_protected_delete_path(p, "linux") is True, p


def test_protected_paths_unc_root():
    # A bare UNC share root must be protected; a deeper path under it is fine.
    assert is_protected_delete_path(r"\\server\share", "windows") is True
    assert is_protected_delete_path(r"\\server\share\Sync", "windows") is False
    # '..' on Windows too.
    assert is_protected_delete_path(r"C:\Users\bob\..\..", "windows") is True


def test_protected_paths_windows_relative():
    # A drive-less Windows path resolves against the remote shell's CWD → refuse (parity with
    # the POSIX relative-path rule). Absolute drive / UNC paths are still allowed.
    for p in ("Sync", r"Documents\Sync", r"\foo"):
        assert is_protected_delete_path(p, "windows") is True, p
    for p in (r"C:\Users\bob\Sync", r"D:\data\x", r"\\srv\share\sub"):
        assert is_protected_delete_path(p, "windows") is False, p


def test_protected_paths_windows_extended_length_prefix():
    # An extended-length / device prefix (\\?\, \\.\, \\?\UNC\) is kept verbatim in
    # PureWindowsPath.drive, so without stripping it '\\?\C:\Windows' would slip past the
    # drive/system-dir guards. The underlying system path must still be protected.
    for p in (r"\\?\C:\Windows", r"\\?\C:\Windows\System32", r"\\?\C:\Users\bob",
              r"\\.\C:\Windows", r"\\?\UNC\srv\share"):
        assert is_protected_delete_path(p, "windows") is True, p
    # A real deep folder under the extended prefix stays deletable.
    for p in (r"\\?\C:\Users\bob\Sync\Mine", r"\\?\D:\data\folder"):
        assert is_protected_delete_path(p, "windows") is False, p


def test_protected_paths_windows_trailing_dot_or_space():
    # NTFS strips a trailing '.'/' ' from a path component on resolution ('C:\\Windows.' opens
    # C:\\Windows), but PureWindowsPath preserves it — a trailing dot/space must not slip a system
    # path past the anchored guards.
    for p in (r"C:\Windows.", r"C:\Windows.\System32", r"C:\Program Files.", r"C:\Windows ",
              r"C:\ProgramData.", r"C:\Users\bob."):
        assert is_protected_delete_path(p, "windows") is True, p
    # A legit folder with an INTERNAL dot stays deletable (don't over-protect).
    for p in (r"C:\Users\bob\Mi.Carpeta", r"D:\Sync.v2"):
        assert is_protected_delete_path(p, "windows") is False, p


def test_protected_paths_forward_slash_unc_unknown_os():
    # A forward-slash UNC share root with an UNKNOWN os_type (a WinRM device whose OS wasn't
    # detected) must not be misclassified as a deletable POSIX path: on a Windows shell
    # '//srv/share' is a network-share root. Refuse the bare root; allow a deeper folder.
    assert is_protected_delete_path("//srv/share", None) is True
    assert is_protected_delete_path("//srv/share/myfolder", None) is False
    # An EXPLICIT linux device keeps the POSIX interpretation (not over-protected).
    assert is_protected_delete_path("//mnt/data/sync", "linux") is False


def test_protected_paths_windows_drive_relative():
    # DRIVE-RELATIVE ('C:foo\bar': a drive but NO leading '\') resolves against that drive's
    # CURRENT directory, not its root → 'C:foo' could land under C:\Windows\System32. Must refuse.
    for p in (r"C:foo\bar", r"Z:data\sync", "C:rel", r"D:a\b\c"):
        assert is_protected_delete_path(p, "windows") is True, p
    # The absolute forms with the SAME drive stay deletable (sanity: the fix didn't over-block).
    for p in (r"C:\foo\bar", r"Z:\data\sync"):
        assert is_protected_delete_path(p, "windows") is False, p


def test_protected_paths_windows_any_drive():
    # System roots are critical on ANY drive, not just C: (a D:\Program Files install).
    for p in ("D:\\Windows", "D:\\Windows\\System32", "E:\\Program Files",
              "E:\\Program Files (x86)", "F:\\ProgramData", "D:\\Users", "D:\\Users\\bob",
              "D:\\", "Z:"):
        assert is_protected_delete_path(p, "windows") is True, p
    # Deeper than a system root is fine (real folders live there).
    for p in ("D:\\Program Files\\app\\data\\Sync", "D:\\Users\\bob\\Sync"):
        assert is_protected_delete_path(p, "windows") is False, p


# ── delete_folder_on_device ─────────────────────────────────────────────────

def test_delete_refuses_protected_path():
    dev = _local(path="/")
    out = delete_folder_on_device(dev, "f1", delete_data=True)
    assert not out.ok and "protegida" in out.message


def test_delete_resolves_path_from_live_config_when_device_path_unset():
    # device.folder_path unset (e.g. an orphan folder created this session, not yet re-discovered)
    # → resolve the authoritative path from the device's LIVE config and delete using it.
    with patch("syncthing_manager.renamer.resolve_remote_folder_path", return_value="/data/found"), \
         patch("syncthing_manager.renamer._stfolder_marker_present", return_value=True), \
         patch("syncthing_manager.renamer.remove_folder_on_device",
               return_value=MagicMock(device_name="local", ok=True, message="cfg")) as rm, \
         patch("syncthing_manager.renamer._delete_local_tree") as rt:
        out = delete_folder_on_device(_local(path=None), "f1", delete_data=True)
    assert out.ok and "/data/found" in out.message
    rm.assert_called_once()
    rt.assert_called_once()


def test_delete_no_path_still_removes_config_skips_disk():
    # No device path AND it can't be resolved → DON'T fail early: still remove the folder from
    # Syncthing's config (non-destructive), only skip the on-disk delete. Regression: it used to
    # return early so the folder lingered in Syncthing on the remote.
    with patch("syncthing_manager.renamer.resolve_remote_folder_path", return_value=None), \
         patch("syncthing_manager.renamer.remove_folder_on_device",
               return_value=MagicMock(device_name="local", ok=True, message="cfg")) as rm, \
         patch("syncthing_manager.renamer._delete_local_tree") as rt:
        out = delete_folder_on_device(_local(path=None), "f1", delete_data=True)
    assert out.ok                                  # removed from Syncthing
    assert "no se conoce la ruta" in out.message    # disk skipped (path unknown)
    rm.assert_called_once()
    rt.assert_not_called()


def test_delete_api_only_remote_cannot_delete_disk():
    # Reachable, but only via API → cannot delete on disk (Syncthing API doesn't).
    out = delete_folder_on_device(_api_only_remote(), "f1", delete_data=True)
    assert not out.ok and ("SSH/WinRM" in out.message)


def test_delete_dry_run_touches_nothing():
    with patch("syncthing_manager.renamer.remove_folder_on_device") as rm, \
         patch("syncthing_manager.renamer._delete_local_tree") as rt:
        out = delete_folder_on_device(_local(), "f1", delete_data=True, dry_run=True)
    rm.assert_not_called()
    rt.assert_not_called()
    assert out.ok and "dry-run" in out.message.lower()


def test_delete_local_removes_config_then_disk():
    with patch("syncthing_manager.renamer._stfolder_marker_present", return_value=True), \
         patch("syncthing_manager.renamer.remove_folder_on_device",
               return_value=MagicMock(device_name="local", ok=True, message="ok")) as rm, \
         patch("syncthing_manager.renamer._delete_local_tree") as rt:
        out = delete_folder_on_device(_local(), "f1", delete_data=True)
    rm.assert_called_once()
    rt.assert_called_once()
    # The marker was verified up front, so the actual rmtree must NOT re-require it (Syncthing
    # deletes .stfolder when it drops the folder — re-checking would abort the delete).
    assert rt.call_args.kwargs.get("require_marker") is False
    assert out.ok and "disco" in out.message


def test_delete_dir_exists_but_no_marker_skips_disk_with_warning():
    # Directory EXISTS but has no .stfolder (a possibly mis-detected path): the marker guards
    # ONLY the destructive rmtree, which is skipped (warning) — but the folder is STILL removed
    # from Syncthing's config (non-destructive). Otherwise it would linger in Syncthing forever.
    with patch("syncthing_manager.renamer._stfolder_marker_present", return_value=False), \
         patch("syncthing_manager.renamer._folder_dir_exists_on_device", return_value=True), \
         patch("syncthing_manager.renamer.remove_folder_on_device",
               return_value=MagicMock(device_name="local", ok=True, message="cfg")) as rm, \
         patch("syncthing_manager.renamer._delete_local_tree") as rt:
        out = delete_folder_on_device(_local(), "f1", delete_data=True)
    assert out.ok                       # removed from Syncthing config
    assert ".stfolder" in out.message   # but warns the disk was NOT deleted (dir exists, no marker)
    rm.assert_called_once()             # config removal DID run
    rt.assert_not_called()              # destructive rmtree was skipped (no marker)


def test_delete_dir_already_gone_is_clean_success():
    # No .stfolder AND the directory doesn't exist (a "folder path missing" remote — nothing to
    # delete on disk): this is a CLEAN success, not a "disco NO borrado" warning. The folder is
    # removed from Syncthing and the disk is already empty/absent.
    with patch("syncthing_manager.renamer._stfolder_marker_present", return_value=False), \
         patch("syncthing_manager.renamer._folder_dir_exists_on_device", return_value=False), \
         patch("syncthing_manager.renamer.remove_folder_on_device",
               return_value=MagicMock(device_name="local", ok=True, message="cfg")) as rm, \
         patch("syncthing_manager.renamer._delete_local_tree") as rt:
        out = delete_folder_on_device(_local(), "f1", delete_data=True)
    assert out.ok
    assert "ya no existía" in out.message   # benign: nothing to delete on disk
    assert "NO borrado" not in out.message   # NOT the scary skip warning
    rm.assert_called_once()
    rt.assert_not_called()                   # nothing to rmtree


def test_delete_config_only_skips_disk():
    with patch("syncthing_manager.renamer.remove_folder_on_device",
               return_value=MagicMock(device_name="local", ok=True, message="cfg")) as rm, \
         patch("syncthing_manager.renamer._delete_local_tree") as rt:
        out = delete_folder_on_device(_local(), "f1", delete_data=False)
    rm.assert_called_once()
    rt.assert_not_called()
    assert out.ok


def test_delete_aborts_disk_if_config_removal_failed():
    with patch("syncthing_manager.renamer._stfolder_marker_present", return_value=True), \
         patch("syncthing_manager.renamer.remove_folder_on_device",
               return_value=MagicMock(device_name="local", ok=False, message="boom")), \
         patch("syncthing_manager.renamer._delete_local_tree") as rt:
        out = delete_folder_on_device(_local(), "f1", delete_data=True)
    rt.assert_not_called()
    assert not out.ok


def test_delete_ssh_remote_uses_remove_tree():
    dev = _ssh_remote()
    ssh = MagicMock()
    ssh.__enter__ = MagicMock(return_value=ssh)
    ssh.__exit__ = MagicMock(return_value=False)
    with patch("syncthing_manager.renamer.remove_folder_on_device",
               return_value=MagicMock(device_name="pi", ok=True, message="ok")), \
         patch("syncthing_manager.renamer.SSHClient", return_value=ssh):
        out = delete_folder_on_device(dev, "f1", delete_data=True)
    ssh.remove_tree.assert_called_once()
    assert out.ok


def test_delete_everywhere_scopes_to_members():
    a, b = _local(), _ssh_remote()
    with patch("syncthing_manager.renamer.delete_folder_on_device",
               return_value=MagicMock(device_name="x", ok=True, message="ok")) as d:
        out = delete_folder_everywhere([a, b], "f1", member_ids={"L"}, dry_run=True)
    assert d.call_count == 1                # only the member in scope
    assert len(out) == 1
