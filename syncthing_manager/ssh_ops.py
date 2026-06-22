from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

from .i18n import t as _T

# paramiko is heavy (~100 ms) and only needed once we actually open an SSH connection, so
# it's imported lazily (via _load_paramiko, called at the top of connect()) to keep it out
# of GUI/CLI startup. Module-level annotations use `from __future__ import annotations`, so
# `paramiko.X` in type hints is a string and doesn't need it imported.
paramiko = None  # type: ignore[assignment]


def _load_paramiko():
    global paramiko
    if paramiko is None:
        import paramiko as _p
        paramiko = _p
    return paramiko


logger = logging.getLogger(__name__)

SSH_CONNECT_TIMEOUT = 15
SSH_OP_TIMEOUT = 30

# Redact API key values from shell commands before logging
_SECRET_RE = re.compile(r"(X-API-Key:\s*)\S+")


def _mask_cmd(cmd: str) -> str:
    return _SECRET_RE.sub(r"\g<1><MASKED>", cmd)


SYNCTHING_CONFIG_PATHS_LINUX = [
    "~/.config/syncthing/config.xml",
    "~/.syncthing/config.xml",
    "/var/lib/syncthing/config.xml",
    "/volume1/@appstore/syncthing/var/config.xml",
    "/usr/local/syncthing/config.xml",
]
SYNCTHING_CONFIG_PATHS_MACOS = [
    "~/Library/Application Support/Syncthing/config.xml",
    "~/.config/syncthing/config.xml",
]


class SSHError(Exception):
    pass


class SSHClient:
    def __init__(
        self,
        host: str,
        user: Optional[str] = None,
        key_path: Optional[str] = None,
        port: int = 22,
        password: Optional[str] = None,
        strict_host_keys: Optional[bool] = None,
    ):
        self.host = host
        self.user = user
        self.key_path = key_path
        self.port = port
        self.password = password
        # None → resolve from the app setting at connect time (default TOFU). True/False
        # forces strict / lenient regardless of settings (used by callers/tests).
        self.strict_host_keys = strict_host_keys
        self._client: Optional[paramiko.SSHClient] = None
        self._home: Optional[str] = None  # cached remote $HOME for ~ expansion

    def _strict_host_keys(self) -> bool:
        if self.strict_host_keys is not None:
            return self.strict_host_keys
        # Lazy, defensive: config import is cheap, but the agent runtime has no settings —
        # any failure falls back to the lenient default (TOFU), never blocks a connection.
        try:
            from . import config as _appconfig
            return bool(_appconfig.get_setting("ssh_strict_host_keys", False))
        except Exception:
            return False

    def connect(self) -> None:
        _load_paramiko()   # lazy: keeps paramiko out of program startup (see top of file)
        client = paramiko.SSHClient()
        # Load system known_hosts so verified hosts are always checked. For UNKNOWN hosts:
        #  • strict (opt-in) → RejectPolicy: refuse a host not already in known_hosts,
        #    closing the first-connect MITM window. The user must add it to known_hosts.
        #  • default → AutoAddPolicy (TOFU): accept new hosts — convenient for a LAN tool.
        client.load_system_host_keys()
        if self._strict_host_keys():
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs: dict = {
            "hostname": self.host,
            "port": self.port,
            "timeout": SSH_CONNECT_TIMEOUT,
        }

        # Resolve username: explicit > SSH config > env
        ssh_cfg = self._load_ssh_config()
        if self.user:
            connect_kwargs["username"] = self.user
        elif ssh_cfg and "user" in ssh_cfg:
            connect_kwargs["username"] = ssh_cfg["user"]
        else:
            connect_kwargs["username"] = os.environ.get("USER", os.environ.get("USERNAME", ""))

        # Resolve key: explicit > SSH config > paramiko default discovery
        if self.key_path:
            connect_kwargs["key_filename"] = os.path.expanduser(self.key_path)
        elif ssh_cfg and "identityfile" in ssh_cfg:
            connect_kwargs["key_filename"] = [
                os.path.expanduser(p) for p in ssh_cfg["identityfile"]
            ]

        # SSH config host/port overrides (only when the user didn't set an explicit one).
        if ssh_cfg:
            if "hostname" in ssh_cfg and ssh_cfg["hostname"] != self.host:
                connect_kwargs["hostname"] = ssh_cfg["hostname"]
            # connect_kwargs["port"] is ALWAYS pre-set to self.port (default 22), so the old
            # setdefault() was a dead no-op and ~/.ssh/config `Port` was silently ignored.
            # Apply it only when the user kept the default port (self.port == 22).
            if "port" in ssh_cfg and self.port == 22:
                connect_kwargs["port"] = int(ssh_cfg["port"])

        if self.password:
            connect_kwargs["password"] = self.password

        logger.debug(
            "SSH connect to %s@%s:%s",
            connect_kwargs.get("username"), self.host, connect_kwargs.get("port", 22),
        )

        try:
            client.connect(**connect_kwargs)
        except paramiko.AuthenticationException as e:
            client.close()   # don't leak the transport thread/socket on a failed connect
            raise SSHError(f"Authentication failed for {self.host}: {e}") from e
        except paramiko.SSHException as e:
            client.close()
            raise SSHError(f"SSH error connecting to {self.host}: {e}") from e
        except OSError as e:
            client.close()
            raise SSHError(f"Network error connecting to {self.host}: {e}") from e
        self._client = client

    def _load_ssh_config(self) -> Optional[dict]:
        config_path = os.path.expanduser("~/.ssh/config")
        if not os.path.exists(config_path):
            return None
        try:
            cfg = paramiko.SSHConfig()
            with open(config_path) as f:
                cfg.parse(f)
            return cfg.lookup(self.host)
        except Exception:
            return None

    def _exec(self, cmd: str, timeout: int = SSH_OP_TIMEOUT,
              stdin_data: Optional[str] = None) -> tuple[int, str, str]:
        if self._client is None:
            raise SSHError("Not connected")
        logger.debug("SSH exec: %s", _mask_cmd(cmd))
        try:
            stdin, stdout, stderr = self._client.exec_command(cmd, timeout=timeout)
            if stdin_data is not None:
                # Feed secret-bearing input (e.g. the API key as a curl -K config) over STDIN so
                # it never lands in the remote argv / `ps` / /proc/*/cmdline. NOT logged above.
                # stdin is the SOLE delivery channel for the command here — for WindowsSSHClient
                # the WHOLE PowerShell script is piped in. If write/flush fails the remote runs an
                # EMPTY command and can exit 0 with empty output, which a delete's post-check would
                # misread as "already gone" (false-OK). Surface that, never swallow it.
                try:
                    stdin.write(stdin_data)
                    stdin.flush()
                except Exception as e:
                    raise SSHError(f"Failed to send command input to {self.host}: {e}") from e
                # EOF signal is best-effort: if write/flush already succeeded the data is delivered,
                # and the channel closing at command end also signals EOF.
                try:
                    stdin.channel.shutdown_write()
                except Exception:
                    pass
            exit_code = stdout.channel.recv_exit_status()
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            return exit_code, out, err
        except paramiko.SSHException as e:
            raise SSHError(f"Command execution failed: {e}") from e

    def read_file(self, remote_path: str) -> str:
        code, out, err = self._exec(f"cat {_quote(self._expand_user(remote_path))}")
        if code != 0:
            raise SSHError(f"Cannot read {remote_path}: {err.strip()}")
        return out

    def write_file(self, remote_path: str, content: str) -> None:
        """Write content to a remote file using SFTP (safe, no shell escaping issues)."""
        if self._client is None:
            raise SSHError("Not connected")
        try:
            with self._client.open_sftp() as sftp:
                # Write bytes in explicit UTF-8 rather than text mode, whose encoding is
                # locale-dependent — config.xml can carry non-ASCII folder labels/paths and
                # the read path decodes UTF-8, so the two must agree.
                with sftp.file(remote_path, "wb") as fh:
                    fh.write(content.encode("utf-8"))
        except Exception as e:
            raise SSHError(f"Failed to write {remote_path}: {e}") from e

    def _expand_user(self, path: str) -> str:
        """Expand a leading ~ to the remote $HOME. Paths are single-quoted before
        execution, so the shell never expands ~ for us — we must do it explicitly
        (Syncthing stores folder paths like '~/ULL')."""
        if path == "~" or path.startswith("~/"):
            return self._get_remote_home() + path[1:]
        return path

    def rename_path(self, old: str, new: str) -> None:
        old_e = self._expand_user(old)
        new_e = self._expand_user(new)
        case_only = old_e != new_e and old_e.lower() == new_e.lower()
        if self.path_exists(new_e):
            # Case-insensitive remote FS: 'a' and 'A' are the same entry, so a
            # case-only change needs a two-step mv via a temp name (else it's a
            # false "already exists"). On case-sensitive FS path_exists is False here.
            if case_only:
                tmp = old_e + "__case_tmp__"
                n = 0
                while self.path_exists(tmp):
                    n += 1
                    tmp = old_e + f"__case_tmp{n}__"
                code, _, err = self._exec(f"mv {_quote(old_e)} {_quote(tmp)}")
                if code != 0:
                    raise SSHError(f"mv failed ({old!r} → temp): {err.strip()}")
                code, _, err = self._exec(f"mv {_quote(tmp)} {_quote(new_e)}")
                if code != 0:
                    raise SSHError(f"mv failed (temp → {new!r}): {err.strip()}")
                return
            raise SSHError(f"Destination already exists: {new}")
        code, _, err = self._exec(f"mv {_quote(old_e)} {_quote(new_e)}")
        if code != 0:
            raise SSHError(f"mv failed ({old!r} → {new!r}): {err.strip()}")

    def path_exists(self, path: str) -> bool:
        code, _, _ = self._exec(f"test -e {_quote(self._expand_user(path))}")
        return code == 0

    def remove_tree(self, path: str, require_marker: bool = True) -> None:
        """DESTRUCTIVE: delete a folder tree on disk (`rm -rf`). Safety: unless
        `require_marker` is False, refuses when the Syncthing folder marker '.stfolder'
        isn't present inside (guards against a mis-detected path). The higher-level
        protected-path check lives in renamer.is_protected_delete_path."""
        p = self._expand_user(path).rstrip("/")
        if not p:
            raise SSHError(_T("Ruta vacía — no se borra"))
        if require_marker and not self.path_exists(p + "/.stfolder"):
            raise SSHError(_T("No parece una carpeta de Syncthing (falta .stfolder): {}").format(path))
        code, _, err = self._exec(f"rm -rf -- {_quote(p)}")
        if code != 0:
            raise SSHError(_T("rm -rf falló: {}").format(err.strip()))
        # Verify the delete ACTUALLY happened: `rm -rf` exits 0 even when the target didn't
        # exist (e.g. a mis-resolved ~ pointing the rm at the wrong path), which would silently
        # report success while the real folder survives. Fail loudly instead — and name the
        # exact resolved path so a path-resolution bug is diagnosable, never a false "borrada".
        if self.path_exists(p):
            raise SSHError(_T("el borrado no surtió efecto — la ruta sigue existiendo: {} "
                              "(¿resolución de ~ / ruta incorrecta?)").format(p))

    def ensure_dir(self, path: str) -> None:
        """`mkdir -p` the given remote path (expands a leading ~). Raises on failure."""
        code, _, err = self._exec(f"mkdir -p {_quote(self._expand_user(path))}")
        if code != 0:
            raise SSHError(f"mkdir -p {path} failed: {err.strip()}")

    def is_writable(self, path: str) -> bool:
        """True if the SSH user can write to `path`. NOTE: the Syncthing service may
        run as a different user, so callers should treat a False as advisory only."""
        code, _, _ = self._exec(f"test -w {_quote(self._expand_user(path))}")
        return code == 0

    def get_home_dir(self) -> str:
        return self._get_remote_home()

    def _get_remote_home(self) -> str:
        if self._home:
            return self._home
        # Try $HOME first, then `cd ~ && pwd` (the login shell expands ~ from the passwd database
        # even when $HOME is unset/odd) — more reliable than a single env read. Only accept a
        # single-line ABSOLUTE path: a real home always is, and this stops a hostile/odd remote
        # shell from returning a crafted value that would silently redirect every ~-relative path
        # operation for the cached session.
        for probe in ('echo "$HOME"', "cd ~ && pwd"):
            code, out, _ = self._exec(probe)
            home = out.strip()
            if code == 0 and home.startswith("/") and "\n" not in home:
                self._home = home
                return self._home
        # Last resort: derive from the SSH user rather than blindly assuming /root, which is wrong
        # for any non-root account and would silently retarget ~-relative ops to the wrong tree.
        user = (self.user or "").strip()
        guess = "/root" if user in ("", "root") else f"/home/{user}"
        logger.warning("Could not resolve a valid remote $HOME; falling back to %r (user=%r)",
                       guess, user)
        self._home = guess
        return self._home

    def detect_syncthing_config_path(self) -> Optional[str]:
        home = self._get_remote_home()
        code, out, _ = self._exec("uname -s 2>/dev/null || echo unknown")
        os_type = out.strip().lower() if code == 0 else "unknown"

        candidates = SYNCTHING_CONFIG_PATHS_MACOS if "darwin" in os_type else SYNCTHING_CONFIG_PATHS_LINUX

        for template in candidates:
            path = template.replace("~", home)
            if self.path_exists(path):
                logger.debug("Found Syncthing config at %s on %s", path, self.host)
                return path

        # Last resort: search likely home and service dirs (avoid full filesystem scan)
        code, out, _ = self._exec(
            "find /home /var/lib /root /etc -name 'config.xml' -path '*/syncthing/*'"
            " -readable 2>/dev/null | head -1",
            timeout=SSH_OP_TIMEOUT,
        )
        if code == 0 and out.strip():
            return out.strip()

        return None

    def _curl(self, method: str, path: str, api_key: str, port: int,
              body: Optional[dict] = None) -> str:
        """Run a Syncthing API call via curl and return the response body.

        `path` is used VERBATIM (only shell-quoted below, NOT url-encoded), so the CALLER
        must URL-encode any id interpolated into it — folder ids via
        `syncthing.rest_folder_path`/`rest_db_folder_query`/`enc_folder_id` (device ids are
        base32+dashes, already URL-safe). Shell-quoting and URL-encoding are orthogonal:
        both are required and neither substitutes for the other.

        We do NOT use curl's -f flag: -f makes curl exit 22 with an EMPTY body on an
        HTTP error, which throws away Syncthing's error message. Instead we append the
        HTTP status with -w and check it ourselves, so a 4xx/5xx surfaces both the code
        and the response body."""
        url = f"http://127.0.0.1:{port}{path}"
        cmd = (
            f"curl -s -m 15 -X {method} "
            f"-w {_quote(chr(10) + '%{http_code}')} "
            # Read the X-API-Key header from a curl config on STDIN (-K -) rather than putting it
            # on the argv: the key is a secret and an argv `-H` exposes it in the remote `ps` /
            # /proc/*/cmdline to any other user on that host. Only non-secret args stay on argv.
            f"-K - "
        )
        if body is not None:
            cmd += (
                f"-H {_quote('Content-Type: application/json')} "
                f"-d {_quote(json.dumps(body))} "
            )
        cmd += _quote(url)
        # curl config format: `header = "..."`. Escape backslash/quote for the double-quoted value,
        # and strip CR/LF so a (user-editable) key can't inject a second curl-config directive line
        # — real Syncthing keys are alphanumeric, but don't assume it.
        _k = (api_key.replace("\\", "\\\\").replace('"', '\\"')
              .replace("\r", "").replace("\n", ""))
        code, out, err = self._exec(cmd, stdin_data=f'header = "X-API-Key: {_k}"\n')
        if code != 0:
            raise SSHError(f"Syncthing API {method} {path} failed: {(err or out).strip()}")
        body_text, _, status = out.rpartition("\n")
        try:
            status_code = int(status.strip())
        except ValueError:
            raise SSHError(_T("Syncthing API {} {}: sin estado HTTP "
                              "(¿curl no instalado?): {}").format(method, path, out.strip()))
        if not (200 <= status_code < 300):
            detail = body_text.strip() or _T("(sin cuerpo)")
            raise SSHError(f"Syncthing API {method} {path} → HTTP {status_code}: {detail}")
        return body_text

    def syncthing_api_post(self, path: str, api_key: str, port: int = 8384,
                           body: Optional[dict] = None) -> None:
        """POST to the local Syncthing API on the remote machine via curl.
        Optionally send a JSON body (e.g. creating a folder)."""
        self._curl("POST", path, api_key, port, body=body)

    def syncthing_api_delete(self, path: str, api_key: str, port: int = 8384) -> None:
        """DELETE on the local Syncthing API on the remote machine via curl."""
        self._curl("DELETE", path, api_key, port)

    def syncthing_api_put(self, path: str, body: dict, api_key: str, port: int = 8384) -> None:
        """PUT to the local Syncthing API on the remote machine via curl."""
        self._curl("PUT", path, api_key, port, body=body)

    def syncthing_api_get(self, path: str, api_key: str, port: int = 8384) -> dict:
        """GET from the local Syncthing API on the remote machine via curl."""
        out = self._curl("GET", path, api_key, port)
        try:
            return json.loads(out)
        except json.JSONDecodeError as e:
            raise SSHError(f"Syncthing API GET {path} returned non-JSON: {e}") from e

    def is_windows(self) -> bool:
        _, out, _ = self._exec("uname -s 2>/dev/null || echo windows")
        return "windows" in out.strip().lower()

    def os_kind(self) -> str:
        """OS family via `uname -s`: 'windows' (no uname), 'macos' (Darwin) or 'linux'."""
        _, out, _ = self._exec("uname -s 2>/dev/null || echo windows")
        s = out.strip().lower()
        if not s or "windows" in s:
            return "windows"
        return "macos" if "darwin" in s else "linux"

    def arch_kind(self) -> Optional[str]:
        """CPU arch via `uname -m`, normalized to our template naming ('amd64'|'arm64'|'armv7'|
        <raw>), or None if it couldn't be read (Windows host with no uname, or any transport
        error — arch detection is best-effort and must never break the surrounding probe)."""
        try:
            _, out, _ = self._exec("uname -m 2>/dev/null || echo")
        except Exception:
            return None
        m = out.strip()
        if not m:
            return None
        from .generate import normalize_arch
        return normalize_arch(m)

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self) -> "SSHClient":
        self.connect()
        return self

    def __exit__(self, *args) -> None:
        self.close()


def _quote(path: str) -> str:
    return "'" + path.replace("'", "'\\''") + "'"
