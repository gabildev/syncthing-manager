from __future__ import annotations

import base64
import json
import logging
from typing import Optional

from .i18n import t as _T

logger = logging.getLogger(__name__)

WINRM_CONNECT_TIMEOUT = 15
WINRM_OP_TIMEOUT = 30

SYNCTHING_CONFIG_PS = r"""
$paths = @(
    "$env:LOCALAPPDATA\Syncthing\config.xml",
    "$env:APPDATA\Syncthing\config.xml"
)
foreach ($p in $paths) {
    if (Test-Path $p) { Write-Output $p; break }
}
"""


class WinRMError(Exception):
    pass


class _PowerShellOps:
    """Windows disk/API operations expressed as PowerShell, shared by the two Windows
    transports: WinRM (`WinRMClient`) and PowerShell-over-SSH (`WindowsSSHClient`). Every
    method below builds an identical PowerShell script and runs it through `run_ps()`, which
    each subclass implements for its transport. The two clients expose the SAME public
    interface as ssh_ops.SSHClient (rename_path/remove_tree/path_exists/ensure_dir/is_writable/
    read_file/write_file/syncthing_api_*), so callers can pick a transport via a factory and
    treat them interchangeably.

    Errors: `run_ps` prepends `$ErrorActionPreference='Stop'` so a non-terminating cmdlet error
    (a failed Remove-Item/Move-Item/New-Item still exits 0 by default) is forced to raise — we
    must never report a DESTRUCTIVE op as success while files remain."""

    # Transport error class raised by these ops. WinRMClient keeps WinRMError; WindowsSSHClient
    # overrides it to ssh_ops.SSHError so that the renamer's SSH-branch handlers (which catch
    # SSHError — 404 detection, delete→recreate rollback, benign-absent skip) actually fire for a
    # Windows host reached over SSH. Without this, every op would raise WinRMError and slip past
    # those `except SSHError` blocks → lost-folder rollbacks skipped, new folders never created.
    _ERR = WinRMError

    @staticmethod
    def _bootstrap(script: str) -> str:
        """Wrap a PowerShell script in an ASCII-only base64 envelope, fed to `powershell -Command -`
        over STDIN by both transports. It (1) keeps the embedded Syncthing API key OFF the remote
        process argv (Win32_Process.CommandLine) — an `-EncodedCommand` would expose it, decodable
        by any local user; (2) survives the remote console codepage so a non-ASCII path in the
        script isn't mojibake'd; and (3) forces stdout to UTF-8 so accented output (a config
        label/path, a JSON body) round-trips. Guarded OutputEncoding → a console-less host degrades
        instead of failing. Validated on real Win10 over BOTH OpenSSH and WinRM."""
        full = "$ErrorActionPreference = 'Stop'\n" + script
        b64 = base64.b64encode(full.encode("utf-8")).decode("ascii")
        return ("try{[Console]::OutputEncoding=[System.Text.Encoding]::UTF8}catch{};"
                "$s=[System.Text.Encoding]::UTF8.GetString("
                f"[System.Convert]::FromBase64String('{b64}'));Invoke-Expression $s\n")

    def run_ps(self, script: str) -> str:    # pragma: no cover - abstract
        raise NotImplementedError

    def read_file(self, remote_path: str) -> str:
        ps_path = remote_path.replace("'", "''")
        return self.run_ps(f"Get-Content -LiteralPath '{ps_path}' -Raw -Encoding UTF8")

    def write_file(self, remote_path: str, content: str) -> None:
        """Write content via base64 — avoids all escaping issues with XML."""
        b64 = base64.b64encode(content.encode("utf-8")).decode()
        ps_path = remote_path.replace("'", "''")
        self.run_ps(
            f"[System.IO.File]::WriteAllBytes("
            f"'{ps_path}', "
            f"[System.Convert]::FromBase64String('{b64}'))"
        )

    def rename_path(self, old: str, new: str) -> None:
        old_esc = old.replace("'", "''")
        new_esc = new.replace("'", "''")
        case_only = old != new and old.lower() == new.lower()
        if self.path_exists(new):
            # Windows FS is case-insensitive: a case-only change ('a'→'A') is the same
            # entry, so rename via a temp name (a plain Move-Item would error/no-op).
            if case_only:
                tmp = old + "__case_tmp__"
                n = 0
                while self.path_exists(tmp):
                    n += 1
                    tmp = old + f"__case_tmp{n}__"
                tmp_esc = tmp.replace("'", "''")
                self.run_ps(f"Move-Item -LiteralPath '{old_esc}' -Destination '{tmp_esc}'")
                self.run_ps(f"Move-Item -LiteralPath '{tmp_esc}' -Destination '{new_esc}'")
                return
            raise self._ERR(f"Destination already exists: {new}")
        self.run_ps(f"Move-Item -LiteralPath '{old_esc}' -Destination '{new_esc}'")

    def path_exists(self, path: str) -> bool:
        ps_path = path.replace("'", "''")
        result = self.run_ps(f"(Test-Path -LiteralPath '{ps_path}').ToString()").strip()
        return result.lower() == "true"

    def remove_tree(self, path: str, require_marker: bool = True) -> None:
        """DESTRUCTIVE: delete a folder tree on disk (Remove-Item -Recurse -Force). Unless
        `require_marker` is False, refuses when the Syncthing folder marker '.stfolder'
        isn't present (guards against a mis-detected path)."""
        p = path.rstrip("\\/")
        if not p:
            raise self._ERR(_T("Ruta vacía — no se borra"))
        if require_marker and not self.path_exists(p + "\\.stfolder"):
            raise self._ERR(_T("No parece una carpeta de Syncthing (falta .stfolder): {}").format(path))
        ps_path = p.replace("'", "''")
        self.run_ps(f"Remove-Item -LiteralPath '{ps_path}' -Recurse -Force")
        # Verify the delete actually happened (a mis-resolved path would otherwise report a
        # silent success while the real folder survives). Fail loudly, naming the path.
        if self.path_exists(p):
            raise self._ERR(_T("el borrado no surtió efecto — la ruta sigue existiendo: {}").format(p))

    def ensure_dir(self, path: str) -> None:
        """Create the directory (and parents) if missing. Raises on failure."""
        ps_path = path.replace("'", "''")
        self.run_ps(f"New-Item -ItemType Directory -Force -Path '{ps_path}' | Out-Null")

    def is_writable(self, path: str) -> bool:
        """True if the user can create a file in `path` (probe + delete). Advisory only —
        the Syncthing service may run as a different user."""
        ps_path = path.replace("'", "''")
        script = (
            "try { $f = Join-Path '" + ps_path + "' ([System.IO.Path]::GetRandomFileName()); "
            "[System.IO.File]::WriteAllText($f, ''); Remove-Item -LiteralPath $f -Force; 'true' } "
            "catch { 'false' }"
        )
        return self.run_ps(script).strip().lower() == "true"

    def detect_syncthing_config_path(self) -> Optional[str]:
        result = self.run_ps(SYNCTHING_CONFIG_PS).strip()
        return result if result else None

    def syncthing_api_post(self, path: str, api_key: str, port: int = 8384,
                           body: Optional[dict] = None) -> None:
        """POST to the local Syncthing API on the remote Windows machine via PowerShell.
        Optionally send a JSON body (e.g. creating a folder)."""
        key_esc = api_key.replace("'", "''")
        url_esc = f"http://127.0.0.1:{port}{path}".replace("'", "''")
        if body is None:
            self.run_ps(
                f"Invoke-RestMethod -Method POST -Uri '{url_esc}' "
                f"-Headers @{{'X-API-Key' = '{key_esc}'}} | Out-Null"
            )
            return
        body_b64 = base64.b64encode(json.dumps(body).encode("utf-8")).decode()
        self.run_ps(
            f"$body = [System.Text.Encoding]::UTF8.GetString("
            f"[System.Convert]::FromBase64String('{body_b64}'))\n"
            f"Invoke-RestMethod -Method POST -Uri '{url_esc}' "
            f"-Headers @{{'X-API-Key' = '{key_esc}'}} "
            f"-ContentType 'application/json' "
            f"-Body $body | Out-Null"
        )

    def syncthing_api_delete(self, path: str, api_key: str, port: int = 8384) -> None:
        """DELETE on the local Syncthing API on the remote Windows machine via PowerShell."""
        key_esc = api_key.replace("'", "''")
        url_esc = f"http://127.0.0.1:{port}{path}".replace("'", "''")
        self.run_ps(
            f"Invoke-RestMethod -Method DELETE -Uri '{url_esc}' "
            f"-Headers @{{'X-API-Key' = '{key_esc}'}} | Out-Null"
        )

    def syncthing_api_put(self, path: str, body: dict, api_key: str, port: int = 8384) -> None:
        """PUT to the local Syncthing API on the remote Windows machine via PowerShell."""
        key_esc = api_key.replace("'", "''")
        url_esc = f"http://127.0.0.1:{port}{path}".replace("'", "''")
        # Use Base64 to safely pass JSON body (avoids all PowerShell escaping issues)
        body_b64 = base64.b64encode(json.dumps(body).encode("utf-8")).decode()
        self.run_ps(
            f"$body = [System.Text.Encoding]::UTF8.GetString("
            f"[System.Convert]::FromBase64String('{body_b64}'))\n"
            f"Invoke-RestMethod -Method PUT -Uri '{url_esc}' "
            f"-Headers @{{'X-API-Key' = '{key_esc}'}} "
            f"-ContentType 'application/json' "
            f"-Body $body | Out-Null"
        )

    def syncthing_api_get(self, path: str, api_key: str, port: int = 8384) -> dict:
        """GET from the local Syncthing API on the remote Windows machine via PowerShell."""
        key_esc = api_key.replace("'", "''")
        url_esc = f"http://127.0.0.1:{port}{path}".replace("'", "''")
        # Depth 20 avoids truncating nested Syncthing config structures (versioning
        # params, device entries) that a low depth would silently drop.
        result = self.run_ps(
            f"Invoke-RestMethod -Method GET -Uri '{url_esc}' "
            f"-Headers @{{'X-API-Key' = '{key_esc}'}} | ConvertTo-Json -Depth 20"
        )
        try:
            data = json.loads(result)
        except json.JSONDecodeError as e:
            raise self._ERR(f"Syncthing API GET {path} returned non-JSON: {e}") from e
        # ConvertTo-Json collapses a SINGLE-element array into a bare object. A folder config's
        # 'devices' MUST stay a list or a PUT/POST-back mangles or rejects the membership. Re-wrap
        # it here at the transport boundary so EVERY caller is covered — both this WinRM transport
        # AND WindowsSSHClient (PowerShell over SSH, used for os_type=='windows' devices) share
        # this method, and several SSH-branch call sites in renamer.py would otherwise forget it,
        # corrupting a single-member folder's membership on a Windows host reached over SSH.
        if isinstance(data, dict) and isinstance(data.get("devices"), dict):
            data["devices"] = [data["devices"]]
        return data

    def restart_syncthing(self) -> None:
        # If Syncthing runs as a SERVICE, restart it and let a real restart failure surface (no
        # -ErrorAction SilentlyContinue → the bootstrap's $ErrorActionPreference='Stop' makes a
        # failed restart raise, instead of masking it as success while the config edit never takes
        # effect). Otherwise fall back to stopping the process (a watchdog/scheduled task is
        # expected to relaunch it). If NEITHER exists, Syncthing isn't running, so the edited
        # config.xml is simply read on its next start — not an error.
        self.run_ps(
            "$svc = Get-Service -Name 'Syncthing' -ErrorAction SilentlyContinue; "
            "if ($svc) { Restart-Service -Name 'Syncthing' -Force } "
            "else { Get-Process -Name 'syncthing' -ErrorAction SilentlyContinue | "
            "Stop-Process -Force -ErrorAction SilentlyContinue }"
        )


class WinRMClient(_PowerShellOps):
    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        port: int = 5985,
        use_ssl: bool = False,
    ):
        self.host = host
        self.user = user
        self.password = password
        self.port = port
        self.use_ssl = use_ssl
        self._session = None

    def connect(self) -> None:
        try:
            import winrm
        except ImportError as e:
            raise WinRMError(_T(
                "pywinrm no está instalado. "
                "Instálalo con: pip install pywinrm requests-ntlm")
            ) from e

        scheme = "https" if self.use_ssl else "http"
        endpoint = f"{scheme}://{self.host}:{self.port}/wsman"
        # Over plain HTTP (the default, 5985) there is no TLS to validate — NTLM still
        # message-encrypts the payload. Over HTTPS (5986) validate the server certificate ONLY
        # when the user opts in (setting "winrm_strict_cert", default OFF — self-signed certs are
        # common on internal Windows boxes, and defaulting to strict would break existing setups,
        # mirroring how ssh_strict_host_keys is opt-in). When strict, a MITM presenting a bad cert
        # is rejected instead of silently trusted.
        cert_check = "ignore"
        if self.use_ssl:
            try:
                from . import config as _appconfig
                if _appconfig.get_setting("winrm_strict_cert", False):
                    cert_check = "validate"
            except Exception:
                pass

        try:
            session = winrm.Session(
                endpoint,
                auth=(self.user, self.password),
                transport="ntlm",
                server_cert_validation=cert_check,
                read_timeout_sec=WINRM_CONNECT_TIMEOUT + 5,
                operation_timeout_sec=WINRM_CONNECT_TIMEOUT,
            )
            # Verify connection with a trivial command
            r = session.run_ps("$true")
            if r.status_code != 0:
                err = r.std_err.decode("utf-8", errors="replace").strip()
                raise WinRMError(f"Connection test failed: {err}")
            self._session = session
            logger.debug("WinRM connected to %s@%s:%s", self.user, self.host, self.port)
        except WinRMError:
            raise
        except Exception as e:
            raise WinRMError(f"WinRM connection to {self.host} failed: {e}") from e

    def run_ps(self, script: str) -> str:
        if self._session is None:
            raise WinRMError("Not connected")
        # Feed the script to `powershell -Command -` over STDIN via the low-level Protocol, NOT
        # Session.run_ps() — the latter delivers it as `powershell -EncodedCommand <base64>`, which
        # puts the embedded Syncthing API key on the remote process command line
        # (Win32_Process.CommandLine), trivially base64-decodable by any local user. Only the static
        # '-Command -' args sit on the argv; the secret stays on stdin (confirmed on a real WinRM
        # host: the leak with -EncodedCommand, and that this path is clean). The base64 bootstrap
        # also keeps non-ASCII paths/output intact. $ErrorActionPreference='Stop' (inside the
        # bootstrap) forces a failed destructive cmdlet to a non-zero exit → WinRMError.
        bootstrap = self._bootstrap(script)
        p = self._session.protocol
        try:
            shell_id = p.open_shell()
            try:
                cmd_id = p.run_command(shell_id, "powershell",
                                       ["-NoProfile", "-NonInteractive", "-Command", "-"])
                try:
                    p.send_command_input(shell_id, cmd_id, bootstrap.encode("utf-8"), end=True)
                    std_out, std_err, status_code = p.get_command_output(shell_id, cmd_id)
                finally:
                    p.cleanup_command(shell_id, cmd_id)
            finally:
                p.close_shell(shell_id)
        except WinRMError:
            raise
        except Exception as e:
            raise WinRMError(f"WinRM execution failed: {e}") from e
        out = std_out.decode("utf-8", errors="replace") if isinstance(std_out, bytes) else std_out
        err = std_err.decode("utf-8", errors="replace") if isinstance(std_err, bytes) else std_err
        if status_code != 0:
            raise WinRMError(f"PowerShell error (exit {status_code}): {err.strip()}")
        return out

    def close(self) -> None:
        self._session = None

    def __enter__(self) -> "WinRMClient":
        self.connect()
        return self

    def __exit__(self, *args) -> None:
        self.close()


class WindowsSSHClient(_PowerShellOps):
    """Runs the SAME PowerShell operations as WinRMClient, but over an SSH transport — for a
    Windows host reachable by OpenSSH whose default shell is cmd.exe/PowerShell (the POSIX
    mv/rm/test commands of ssh_ops.SSHClient would fail there). Each script is fed to
    `powershell -NoProfile -NonInteractive -Command -` over STDIN (see run_ps): stdin keeps the
    Syncthing API key off the remote argv/process list, and `-Command -` sidesteps ALL shell-
    quoting differences over SSH regardless of the remote default shell.

    Validated on a real Windows 10 + OpenSSH host. Selected by renamer._ssh_client when
    device.os_type == 'windows'; the POSIX SSHClient path is unchanged for every other device."""

    def __init__(self, host: str, user: Optional[str], key_path: Optional[str] = None,
                 port: int = 22, password: Optional[str] = None):
        from .ssh_ops import SSHClient, SSHError
        self._ssh = SSHClient(host=host, user=user, key_path=key_path, port=port,
                              password=password)
        # Raise SSHError (not WinRMError) so the renamer's SSH-branch handlers fire — see _ERR.
        self._ERR = SSHError

    def connect(self) -> None:
        self._ssh.connect()

    def run_ps(self, script: str) -> str:
        from .ssh_ops import SSHError
        # Feed the script to `powershell -Command -` over STDIN (NOT `-EncodedCommand`, which would
        # expose the embedded API key on the remote argv) using the shared base64 bootstrap — it
        # keeps the key off the command line, survives the remote console codepage for non-ASCII
        # paths, and forces stdout to UTF-8 so accented output round-trips. See _bootstrap.
        try:
            code, out, err = self._ssh._exec(
                "powershell -NoProfile -NonInteractive -Command -",
                stdin_data=self._bootstrap(script))
        except SSHError as e:
            raise SSHError(f"PowerShell over SSH failed: {e}") from e
        if code != 0:
            raise SSHError(f"PowerShell error (exit {code}): {(err or out).strip()}")
        return out

    def close(self) -> None:
        self._ssh.close()

    def __enter__(self) -> "WindowsSSHClient":
        self.connect()
        return self

    def __exit__(self, *args) -> None:
        self.close()
