from __future__ import annotations

from syncthing_manager.validation import (
    differs_only_in_case,
    is_windows_os,
    validate_dir_name,
    validate_new_path_input,
)


class TestValidateDirName:
    def test_valid_name_all_os(self):
        assert validate_dir_name("Proyecto-2026", "linux") == []
        assert validate_dir_name("Proyecto-2026", "windows") == []
        assert validate_dir_name("Proyecto-2026", None) == []

    def test_windows_invalid_chars(self):
        problems = validate_dir_name("inf:orme", "windows")
        assert any("no válidos en Windows" in p for p in problems)

    def test_linux_allows_colon(self):
        # ':' is fine on Linux
        assert validate_dir_name("inf:orme", "linux") == []

    def test_unknown_os_treated_as_windows(self):
        # None → strict (Windows) rules apply
        assert validate_dir_name("inf:orme", None) != []

    def test_windows_reserved_name(self):
        assert any("reservado" in p for p in validate_dir_name("CON", "windows"))
        assert any("reservado" in p for p in validate_dir_name("nul.txt", "windows"))
        # not reserved on Linux
        assert validate_dir_name("CON", "linux") == []

    def test_windows_trailing_dot_or_space(self):
        assert validate_dir_name("carpeta.", "windows") != []
        assert validate_dir_name("carpeta ", "windows") != []
        # fine on Linux
        assert validate_dir_name("carpeta.", "linux") == []

    def test_empty(self):
        assert validate_dir_name("", "linux") != []
        assert validate_dir_name("   ", "windows") != []

    def test_linux_slash_rejected(self):
        assert any("/" in p for p in validate_dir_name("a/b", "linux"))

    def test_dot_and_dotdot_rejected_every_os(self):
        # '.'/'..' as a bare dir-name are path-traversal segments: _resolve_new_path would move
        # the folder into its parent/grandparent. Must be rejected on every OS (POSIX used to
        # let them through; Windows already caught them via the trailing-dot rule).
        for os_type in ("linux", "windows", None):
            assert validate_dir_name(".", os_type), os_type
            assert validate_dir_name("..", os_type), os_type
        # a normal name with internal dots is still fine.
        assert validate_dir_name("v1.2.3", "linux") == []


class TestValidateNewPathInput:
    def test_bare_name(self):
        assert validate_new_path_input("MiCarpeta", "windows") == []

    def test_windows_abs_on_linux_device(self):
        problems = validate_new_path_input(r"C:\Users\x\Carpeta", "linux")
        assert any("Windows" in p for p in problems)

    def test_posix_abs_on_windows_device(self):
        problems = validate_new_path_input("/home/x/Carpeta", "windows")
        assert any("POSIX" in p for p in problems)

    def test_abs_leaf_validated(self):
        # invalid leaf in a posix path on a linux device — leaf 'a:b' is fine on linux
        assert validate_new_path_input("/home/x/a:b", "linux") == []


class TestCaseHelpers:
    def test_differs_only_in_case(self):
        assert differs_only_in_case("testeo", "TESTEO")
        assert differs_only_in_case("MiCarpeta", "micarpeta")
        assert not differs_only_in_case("testeo", "testeo")
        assert not differs_only_in_case("testeo", "produccion")
        assert not differs_only_in_case("", "")

    def test_is_windows_os(self):
        assert is_windows_os("windows")
        assert is_windows_os(None)       # unknown → strict
        assert not is_windows_os("linux")
