from __future__ import annotations

import pytest

from syncthing_manager.ssh_ops import SSHClient, SSHError


def _client_with_exec(exec_fn):
    c = SSHClient(host="h", user="u")
    c._home = "/home/u"          # avoid an `echo $HOME` round-trip
    c._exec = exec_fn            # type: ignore[assignment]
    return c


class TestArchKind:
    """arch_kind() runs `uname -m` and normalizes the result to our template naming."""

    def _arch(self, uname_out):
        return _client_with_exec(lambda cmd, timeout=None: (0, uname_out, "")).arch_kind()

    def test_x86_64_maps_to_amd64(self):
        assert self._arch("x86_64\n") == "amd64"

    def test_aarch64_maps_to_arm64(self):
        assert self._arch("aarch64\n") == "arm64"

    def test_armv7l_maps_to_armv7(self):
        assert self._arch("armv7l\n") == "armv7"

    def test_empty_output_returns_none(self):
        # A Windows host (no uname) → `echo` yields empty → None (arch undetected).
        assert self._arch("\n") is None


def test_remove_tree_raises_if_path_survives():
    """rm -rf exits 0 even when it deleted nothing (mis-resolved path). remove_tree must
    VERIFY the path is gone and fail loudly instead of reporting a silent false success."""
    def fake_exec(cmd, timeout=None):
        if cmd.startswith("rm -rf"):
            return (0, "", "")
        if "test -e" in cmd:
            return (0, "", "")   # path STILL exists after the rm → delete didn't take
        return (0, "", "")
    ssh = _client_with_exec(fake_exec)
    with pytest.raises(SSHError, match="no surtió efecto"):
        ssh.remove_tree("/home/u/algo", require_marker=False)


def test_remove_tree_ok_when_path_gone():
    def fake_exec(cmd, timeout=None):
        if cmd.startswith("rm -rf"):
            return (0, "", "")
        if "test -e" in cmd:
            return (1, "", "")   # path gone → delete succeeded
        return (0, "", "")
    ssh = _client_with_exec(fake_exec)
    ssh.remove_tree("/home/u/algo", require_marker=False)   # must NOT raise


def test_remove_tree_raises_on_rm_failure():
    def fake_exec(cmd, timeout=None):
        if cmd.startswith("rm -rf"):
            return (1, "", "permiso denegado")
        return (0, "", "")
    ssh = _client_with_exec(fake_exec)
    with pytest.raises(SSHError, match="rm -rf falló"):
        ssh.remove_tree("/home/u/algo", require_marker=False)


def test_curl_keeps_api_key_off_argv():
    """The API key must travel via curl's stdin config (-K -), never the argv — an argv -H
    exposes the secret in the remote `ps` / /proc/*/cmdline to other users on that host."""
    captured = {}

    def fake_exec(cmd, timeout=None, stdin_data=None):
        captured["cmd"] = cmd
        captured["stdin"] = stdin_data
        return (0, '{"ok": true}\n200', "")   # body + HTTP status line for _curl

    ssh = SSHClient(host="h", user="u")
    ssh._exec = fake_exec   # type: ignore[assignment]
    ssh.syncthing_api_get("/rest/config", api_key="SECRETKEY123", port=8384)
    assert "SECRETKEY123" not in captured["cmd"]          # NOT on the command line
    assert "SECRETKEY123" in (captured["stdin"] or "")    # delivered over stdin instead
    assert "-K -" in captured["cmd"]


class TestWindowsSSHClient:
    """PowerShell-over-SSH transport (Windows host via OpenSSH): same op surface as WinRMClient
    but scripts run through `powershell -Command -` over the SSH channel (script on STDIN, so the
    API key never lands on the argv), and ops raise SSHError so renamer's SSH handlers fire."""

    def _client(self, exec_return=(0, "", "")):
        from syncthing_manager.winrm_ops import WindowsSSHClient
        from unittest.mock import MagicMock
        cli = WindowsSSHClient(host="h", user="u", password="p")
        cli._ssh = MagicMock()
        cli._ssh._exec.return_value = exec_return
        return cli

    @staticmethod
    def _decode_bootstrap(stdin: str) -> str:
        # run_ps wraps the real script in an ASCII-only base64 bootstrap (immune to the remote
        # console codepage, so non-ASCII paths survive). Recover the UTF-8 script it carries.
        import base64
        import re
        m = re.search(r"FromBase64String\('([^']+)'\)", stdin)
        assert m, f"bootstrap shape unexpected: {stdin!r}"
        return base64.b64decode(m.group(1)).decode("utf-8")

    def test_run_ps_sends_script_over_stdin_not_argv(self):
        cli = self._client(exec_return=(0, "out", ""))
        assert cli.run_ps("Write-Output hi") == "out"
        cmd = cli._ssh._exec.call_args[0][0]
        stdin = cli._ssh._exec.call_args[1]["stdin_data"]
        assert cmd == "powershell -NoProfile -NonInteractive -Command -"  # no script on argv
        script = self._decode_bootstrap(stdin)
        assert "$ErrorActionPreference = 'Stop'" in script
        assert "Write-Output hi" in script

    def test_api_key_not_on_argv_only_on_stdin(self):
        # The security fix: a Windows host's API key must NOT be readable from its process list.
        cli = self._client(exec_return=(0, '{"x":1}', ""))
        cli.syncthing_api_get("/rest/config", api_key="SECRETKEY123", port=8384)
        cmd = cli._ssh._exec.call_args[0][0]
        stdin = cli._ssh._exec.call_args[1]["stdin_data"]
        assert "SECRETKEY123" not in cmd       # not on the command line (Win32_Process.CommandLine)
        # Delivered over stdin (inside the base64 bootstrap, recoverable by decoding it).
        assert "SECRETKEY123" in self._decode_bootstrap(stdin)

    def test_non_ascii_path_survives_via_utf8_bootstrap(self):
        # PowerShell reads `-Command -` stdin in the console codepage, not UTF-8, so the real
        # script is base64-wrapped; an accented path must round-trip intact through the bootstrap.
        cli = self._client(exec_return=(0, "True\r\n", ""))
        cli.path_exists("C:/Año/Música")
        stdin = cli._ssh._exec.call_args[1]["stdin_data"]
        assert "Año/Música" in self._decode_bootstrap(stdin)

    def test_bootstrap_forces_utf8_output_encoding(self):
        # The RETURN path is also codepage-bound: the bootstrap must set Console.OutputEncoding to
        # UTF-8 (guarded) so accented stdout — a config label/path via read_file, a JSON body via
        # syncthing_api_get — round-trips instead of coming back mojibake. Validated on real Win10.
        cli = self._client(exec_return=(0, "x", ""))
        cli.run_ps("Write-Output hi")
        stdin = cli._ssh._exec.call_args[1]["stdin_data"]
        assert "OutputEncoding" in stdin and "UTF8" in stdin
        assert stdin.startswith("try{")   # guarded so a console-less host degrades, never fails

    def test_api_get_rewraps_single_member_devices_array(self):
        # ConvertTo-Json collapses a single-element array to a bare object; the transport must
        # re-wrap a folder config's 'devices' back to a list so the renamer's SSH-branch
        # PUT/POST-backs don't corrupt a single-member folder's membership on a Windows host.
        import json
        cli = self._client()
        cli._ssh.reset_mock()
        cli._ssh._exec.return_value = (
            0, json.dumps({"id": "f", "devices": {"deviceID": "X"}}), "")
        out = cli.syncthing_api_get("/rest/config/folders/f", api_key="k", port=8384)
        assert out["devices"] == [{"deviceID": "X"}]   # re-wrapped to a list
        # A normal multi-member list is left untouched.
        cli._ssh._exec.return_value = (
            0, json.dumps({"id": "f", "devices": [{"deviceID": "X"}, {"deviceID": "Y"}]}), "")
        out = cli.syncthing_api_get("/rest/config/folders/f", api_key="k", port=8384)
        assert len(out["devices"]) == 2

    def test_run_ps_nonzero_exit_raises_ssherror(self):
        from syncthing_manager.ssh_ops import SSHError
        cli = self._client(exec_return=(1, "", "boom"))
        with pytest.raises(SSHError):
            cli.run_ps("whatever")

    def test_ops_raise_ssherror_so_renamer_handlers_fire(self):
        # remove_tree's empty-path guard must raise SSHError (not WinRMError) on this transport,
        # or renamer's `except SSHError` blocks (404/rollback/skip) would miss it.
        from syncthing_manager.ssh_ops import SSHError
        cli = self._client()
        with pytest.raises(SSHError):
            cli.remove_tree("", require_marker=False)

    def test_path_exists_parses_powershell_true(self):
        cli = self._client(exec_return=(0, "True\r\n", ""))
        assert cli.path_exists("C:/x") is True

    def test_has_full_powershell_op_surface(self):
        from syncthing_manager.winrm_ops import _PowerShellOps
        cli = self._client()
        assert isinstance(cli, _PowerShellOps)
        for m in ("rename_path", "remove_tree", "ensure_dir", "is_writable",
                  "syncthing_api_get", "syncthing_api_post", "syncthing_api_put",
                  "syncthing_api_delete", "read_file", "write_file",
                  "detect_syncthing_config_path"):
            assert callable(getattr(cli, m))


class TestWinRMClientApiKeyNotOnArgv:
    """The WinRM transport must feed the script over STDIN (`powershell -Command -`), NOT via
    `powershell -EncodedCommand <b64>` which would put the embedded API key on the remote process
    command line (Win32_Process.CommandLine). Verified end-to-end on a real WinRM host; this locks
    the mechanism at unit level. (run_ps now drives the low-level pywinrm Protocol.)"""

    def _client(self, out=b"ok", err=b"", rc=0):
        from unittest.mock import MagicMock
        from syncthing_manager.winrm_ops import WinRMClient
        cli = WinRMClient(host="h", user="u", password="p")
        proto = MagicMock()
        proto.open_shell.return_value = "shell-1"
        proto.run_command.return_value = "cmd-1"
        proto.get_command_output.return_value = (out, err, rc)
        cli._session = MagicMock()
        cli._session.protocol = proto
        return cli, proto

    def test_run_ps_uses_command_dash_stdin_not_encodedcommand(self):
        import base64
        import re
        cli, proto = self._client(out=b"hi")
        assert cli.run_ps("Write-Output $env:THE_KEY") == "hi"
        # Args on the remote argv are static — '-Command -', never '-EncodedCommand'.
        command = proto.run_command.call_args[0][1]
        args = proto.run_command.call_args[0][2]
        assert command == "powershell"
        assert "-Command" in args and "-" in args
        assert not any("encoded" in a.lower() for a in args)
        # The actual script is delivered over STDIN as the base64 bootstrap.
        stdin = proto.send_command_input.call_args[0][2]
        stdin = stdin.decode() if isinstance(stdin, (bytes, bytearray)) else stdin
        m = re.search(r"FromBase64String\('([^']+)'\)", stdin)
        assert m, stdin
        decoded = base64.b64decode(m.group(1)).decode("utf-8")
        assert "Write-Output $env:THE_KEY" in decoded
        proto.cleanup_command.assert_called_once()
        proto.close_shell.assert_called_once_with("shell-1")

    def test_run_ps_nonzero_exit_raises_winrmerror(self):
        from syncthing_manager.winrm_ops import WinRMError
        cli, _ = self._client(out=b"", err=b"boom", rc=1)
        with pytest.raises(WinRMError):
            cli.run_ps("whatever")


class TestWinRMTLSCertValidation:
    """Over HTTP there's no TLS to validate; over HTTPS the server cert is validated ONLY when the
    user opts in (winrm_strict_cert, default OFF — self-signed certs are common internally)."""

    def _connect_capture(self, use_ssl, strict):
        from unittest.mock import patch, MagicMock
        import winrm
        from syncthing_manager.winrm_ops import WinRMClient
        cli = WinRMClient(host="h", user="u", password="p",
                          port=5986 if use_ssl else 5985, use_ssl=use_ssl)
        cap = {}

        def fake_session(endpoint, **kw):
            cap.update(kw)
            sess = MagicMock()
            sess.run_ps.return_value = MagicMock(status_code=0, std_err=b"", std_out=b"")
            return sess

        with patch.object(winrm, "Session", fake_session), \
                patch("syncthing_manager.config.get_setting", return_value=strict):
            cli.connect()
        return cap["server_cert_validation"]

    def test_http_always_ignores(self):
        assert self._connect_capture(use_ssl=False, strict=True) == "ignore"

    def test_https_validates_only_when_opted_in(self):
        assert self._connect_capture(use_ssl=True, strict=False) == "ignore"
        assert self._connect_capture(use_ssl=True, strict=True) == "validate"


class TestRestartSyncthing:
    def test_service_restart_not_silenced(self):
        # A real service-restart failure must surface (no -ErrorAction SilentlyContinue on
        # Restart-Service); the process fallback stays best-effort.
        from unittest.mock import MagicMock
        from syncthing_manager.winrm_ops import WindowsSSHClient
        cli = WindowsSSHClient(host="h", user="u", password="p")
        cli._ssh = MagicMock()
        cli._ssh._exec.return_value = (0, "", "")
        cli.restart_syncthing()
        import base64
        import re
        stdin = cli._ssh._exec.call_args[1]["stdin_data"]
        script = base64.b64decode(re.search(r"FromBase64String\('([^']+)'\)", stdin).group(1)).decode()
        assert "Restart-Service -Name 'Syncthing' -Force" in script
        assert "Restart-Service -ErrorAction SilentlyContinue" not in script
