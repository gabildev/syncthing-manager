from __future__ import annotations

import logging
import threading
import time
from typing import Optional
from urllib.parse import quote

# requests + urllib3 are heavy (~50 ms) and only needed once we actually talk to the API,
# so they're imported lazily (via _load_requests, called from SyncthingClient.__init__) to
# keep them out of GUI startup.
requests = None  # type: ignore[assignment]


def _load_requests():
    global requests
    if requests is None:
        import requests as _r
        import urllib3
        # Syncthing uses self-signed certs by default (verify_ssl=False); silence the noisy
        # per-request InsecureRequestWarning.
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        requests = _r
    return requests


from .i18n import t as _T
from .models import ConnectionInfo, DeviceConfig, DeviceStats, FolderConfig

logger = logging.getLogger(__name__)

PING_TIMEOUT = 5
DEFAULT_TIMEOUT = 10
PAUSE_POLL_INTERVAL = 1


def _mask_key(key: Optional[str]) -> str:
    if not key:
        return "(none)"
    return key[:8] + "..."


def enc_folder_id(folder_id: str) -> str:
    """URL-encode a folder id for use in a REST URL path segment or query value.

    Folder ids created in the Syncthing web UI can contain spaces/special chars; if
    interpolated raw they break the request. This is the SINGLE place that rule lives —
    every folder-id-in-URL site goes through here (or `rest_folder_path`) so a new call
    site can't silently forget to encode. It's a no-op for normal slug ids (quote's
    always-safe set is A-Za-z0-9_.-~). Device ids are NOT routed here: Syncthing device
    ids are base32 + dashes, structurally URL-safe already."""
    return quote(folder_id, safe="")


def rest_folder_path(folder_id: str) -> str:
    """REST config path for a folder with its id URL-encoded (see `enc_folder_id`)."""
    return f"/rest/config/folders/{enc_folder_id(folder_id)}"


def enc_device_id(device_id: str) -> str:
    """URL-encode a device id for a REST path segment. A genuine Syncthing device id is
    base32+dashes (no-op here), but the id can arrive verbatim from a remote/possibly-malicious
    hub's API response — encoding neutralises a crafted id ('foo?x=', '../system/restart') that
    would otherwise redirect the request to a different local-API endpoint or add a query."""
    return quote(device_id or "", safe="")


def rest_device_path(device_id: str) -> str:
    """REST config path for a device with its id URL-encoded (see `enc_device_id`)."""
    return f"/rest/config/devices/{enc_device_id(device_id)}"


def rest_db_folder_query(endpoint: str, folder_id: str) -> str:
    """REST /rest/db/<endpoint>?folder=<id> path with the id URL-encoded — for the SSH/WinRM
    proxy, which consumes the path string VERBATIM (the direct-API client uses requests
    `params={"folder": id}` instead, which encodes on its own). Use this rather than
    hand-writing the query so the encoding can't be forgotten (see `enc_folder_id`)."""
    return f"/rest/db/{endpoint}?folder={enc_folder_id(folder_id)}"


class SyncthingError(Exception):
    """API error. ``status_code`` is the HTTP status when the server answered
    (e.g. 404), or None for connection/timeout errors where no response arrived.
    Callers use it to tell a real 'not found' (404) apart from a transient blip."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class SyncthingClient:
    def __init__(self, base_url: str, api_key: str, verify_ssl: bool = False):
        _load_requests()   # lazy: keeps requests/urllib3 out of program startup
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._session = requests.Session()
        self._session.headers.update({"X-API-Key": api_key})
        self._session.verify = verify_ssl
        self._version_cache: Optional[str] = None
        # requests.Session is not safe for CONCURRENT requests; the GUI shares ONE client
        # instance (self.s["client"]) across worker threads (status poll, Estado button,
        # passive loop, discovery watch). Serialize this instance's requests. Per-device
        # topology-apply uses SEPARATE client instances → still fully parallel.
        self._lock = threading.Lock()

    def _get(self, path: str, timeout: int = DEFAULT_TIMEOUT, params: dict = None) -> dict:
        url = f"{self.base_url}{path}"
        logger.debug("GET %s (key=%s)", url, _mask_key(self.api_key))
        try:
            with self._lock:
                resp = self._session.get(url, timeout=timeout, params=params)
                resp.raise_for_status()
                return resp.json()
        except requests.RequestException as e:
            code = e.response.status_code if e.response is not None else None
            raise SyncthingError(f"GET {path} failed: {e}", status_code=code) from e

    def _post(self, path: str, params: dict = None, json: dict = None, timeout: int = DEFAULT_TIMEOUT) -> Optional[dict]:
        url = f"{self.base_url}{path}"
        logger.debug("POST %s (key=%s)", url, _mask_key(self.api_key))
        try:
            with self._lock:
                resp = self._session.post(url, params=params, json=json, timeout=timeout)
                resp.raise_for_status()
                if resp.content:
                    return resp.json()
                return None
        except requests.RequestException as e:
            code = e.response.status_code if e.response is not None else None
            raise SyncthingError(f"POST {path} failed: {e}", status_code=code) from e

    def _put(self, path: str, json: dict, timeout: int = DEFAULT_TIMEOUT) -> dict:
        url = f"{self.base_url}{path}"
        logger.debug("PUT %s (key=%s)", url, _mask_key(self.api_key))
        try:
            with self._lock:
                resp = self._session.put(url, json=json, timeout=timeout)
                resp.raise_for_status()
                return resp.json() if resp.content else {}
        except requests.RequestException as e:
            code = e.response.status_code if e.response is not None else None
            raise SyncthingError(f"PUT {path} failed: {e}", status_code=code) from e

    def ping(self) -> bool:
        try:
            data = self._get("/rest/system/ping", timeout=PING_TIMEOUT)
            return data.get("ping") == "pong"
        except SyncthingError:
            return False

    def ping_status(self) -> str:
        """
        Diagnose connectivity, distinguishing failure modes:
          'ok'    API answered and accepted the key
          'auth'  API answered but rejected the key (401/403)
          'down'  connection refused / timed out (not running / unreachable)
          'error' reachable but unexpected response
        """
        url = f"{self.base_url}/rest/system/ping"
        try:
            with self._lock:
                resp = self._session.get(url, timeout=PING_TIMEOUT)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            return "down"
        except requests.RequestException:
            return "error"
        if resp.status_code in (401, 403):
            return "auth"
        try:
            resp.raise_for_status()
            return "ok" if resp.json().get("ping") == "pong" else "error"
        except Exception:
            return "error"

    def get_version(self) -> str:
        # Version never changes for a live process; cache to avoid an extra HTTP
        # round trip on every is_version_gte() check during a rename.
        if self._version_cache is None:
            data = self._get("/rest/system/version")
            self._version_cache = data.get("version", "unknown")
        return self._version_cache

    def get_os(self) -> Optional[str]:
        """Return 'windows', 'macos' or 'linux' based on /rest/system/version, or None on error."""
        try:
            data = self._get("/rest/system/version")
            # A possibly-hostile/malformed hub may return a non-dict body or a non-string 'os':
            # guard both so a crafted response can't raise AttributeError past the SyncthingError
            # catch and crash the probe.
            os_name = data.get("os", "") if isinstance(data, dict) else ""
            os_name = os_name.lower() if isinstance(os_name, str) else ""
            if "windows" in os_name:
                return "windows"
            if "darwin" in os_name:
                return "macos"
            if os_name in ("linux", "freebsd", "openbsd"):
                return "linux"
        except SyncthingError:
            pass
        return None

    def get_arch(self) -> Optional[str]:
        """Return the device's CPU arch ('amd64' | 'arm64' | 'armv7' | <raw>) from the 'arch'
        field of /rest/system/version (Go GOARCH), normalized to our template naming, or None
        on error / empty. Lets the agent flow pick the right Linux/macOS template automatically."""
        try:
            data = self._get("/rest/system/version")
            # Guard a non-dict body and a non-string 'arch' from a hostile/malformed hub — the
            # value feeds normalize_arch (.lower()), so a crafted type would otherwise raise past
            # the SyncthingError catch and crash a manual probe.
            arch_name = data.get("arch", "") if isinstance(data, dict) else ""
            if isinstance(arch_name, str) and arch_name:
                from .generate import normalize_arch
                return normalize_arch(arch_name)
        except SyncthingError:
            pass
        return None

    def get_my_device_id(self) -> str:
        data = self._get("/rest/system/status")
        # A malformed/hostile response must surface as a handled SyncthingError, not a raw
        # KeyError that escapes callers (which only catch SyncthingError).
        if not isinstance(data, dict) or not data.get("myID"):
            raise SyncthingError(_T("/rest/system/status sin 'myID' (respuesta inesperada)"))
        return data["myID"]

    def get_folders(self) -> list[FolderConfig]:
        data = self._get("/rest/config/folders")
        if not isinstance(data, list):
            return []
        # Skip malformed entries (non-dict / missing id) instead of crashing the enumeration.
        return [FolderConfig.from_dict(f) for f in data if isinstance(f, dict) and f.get("id")]

    def get_folder(self, folder_id: str) -> Optional[FolderConfig]:
        """Return the folder config, or None if it genuinely doesn't exist (404).
        A transient error (timeout, 5xx, auth) is re-raised so callers don't mistake
        a blip for 'folder absent' and then create/overwrite it."""
        try:
            data = self._get(rest_folder_path(folder_id))
            # A malformed (non-dict) 200 body must surface as a handled SyncthingError, not a raw
            # AttributeError from from_dict — and NOT None (callers read None as 'absent → create').
            # A dict missing "id" is equally malformed: from_dict does d["id"] and would raise a
            # bare KeyError that escapes callers catching only SyncthingError (e.g. the agent's
            # _is_already_applied, which would then kill its worker thread and hang the UI).
            if not isinstance(data, dict) or not data.get("id"):
                raise SyncthingError(_T("respuesta inesperada para la carpeta «{}»").format(folder_id))
            return FolderConfig.from_dict(data)
        except SyncthingError as e:
            if e.status_code == 404:
                return None
            raise

    def get_folder_status(self, folder_id: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
        return self._get("/rest/db/status", params={"folder": folder_id}, timeout=timeout)

    def get_connected_devices(self) -> dict[str, ConnectionInfo]:
        data = self._get("/rest/system/connections")
        # A malformed (non-dict) 200 body would make .get() raise a raw AttributeError that
        # escapes callers catching only SyncthingError (crashing the connection-poll thread).
        # Degrade gracefully to "no connection info", consistent with get_discovery.
        if not isinstance(data, dict):
            return {}
        connections = data.get("connections", {})
        if not isinstance(connections, dict):
            return {}
        result = {}
        for device_id, info in connections.items():
            # Skip a malformed per-device entry (null / non-dict) instead of letting info.get(...)
            # raise a raw AttributeError — matches get_discovery / get_device_stats. A bad entry
            # would otherwise lose a whole hub's expansion or drop a device's resolved IP.
            if not isinstance(info, dict):
                continue
            result[device_id] = ConnectionInfo(
                device_id=device_id,
                connected=info.get("connected", False),
                address=info.get("address", ""),
                client_version=info.get("clientVersion", ""),
            )
        return result

    def get_discovery(self) -> dict[str, list[str]]:
        """GET /rest/system/discovery — every address Syncthing has discovered per
        device (LAN broadcast + global). Often the only place a usable IPv4 shows up
        when the active connection happens to be a link-local IPv6. Best-effort."""
        try:
            data = self._get("/rest/system/discovery")
        except SyncthingError:
            return {}
        result: dict[str, list[str]] = {}
        if isinstance(data, dict):
            for dev_id, info in data.items():
                addrs = info.get("addresses") if isinstance(info, dict) else info
                if isinstance(addrs, list):
                    result[dev_id] = [a for a in addrs if isinstance(a, str)]
        return result

    def get_device_stats(self) -> dict[str, DeviceStats]:
        data = self._get("/rest/stats/device")
        # Same hardening as get_connected_devices: a non-dict 200 body would make .items()
        # raise a raw AttributeError that escapes SyncthingError handlers.
        if not isinstance(data, dict):
            return {}
        result = {}
        for device_id, stats in data.items():
            if not isinstance(stats, dict):
                continue
            result[device_id] = DeviceStats(
                device_id=device_id,
                last_seen=stats.get("lastSeen"),
                last_address=stats.get("lastAddress"),
            )
        return result

    def get_config_devices(self) -> list[DeviceConfig]:
        data = self._get("/rest/config/devices")
        if not isinstance(data, list):
            return []
        # Skip malformed entries (non-dict / missing deviceID) instead of crashing.
        return [DeviceConfig.from_dict(d) for d in data
                if isinstance(d, dict) and d.get("deviceID")]

    def get_gui_address(self) -> Optional[str]:
        """The GUI/API listen address from /rest/config/gui (e.g. '127.0.0.1:8384' or
        '0.0.0.0:8384'). Used to tell whether this Syncthing exposes its API on the LAN
        (anything not bound to localhost). Returns None if it can't be read."""
        try:
            data = self._get("/rest/config/gui")
            addr = data.get("address") if isinstance(data, dict) else None
            return addr or None
        except SyncthingError:
            return None

    @staticmethod
    def address_is_lan(address: Optional[str]) -> bool:
        """True if a GUI address is reachable from other hosts (not bound to localhost). Uses the
        shared address parser so a bracketless IPv6 isn't mis-split (rsplit would drop its last
        hextet); '0.0.0.0'/'::' (all interfaces) correctly count as LAN-exposed."""
        from .models import parse_ip_from_address
        if not address:
            return False
        host = (parse_ip_from_address(address) or "").strip().strip("[]")
        # A host-OMITTED bind (':8384', 'tcp://:8384') means ALL interfaces — the same as
        # '0.0.0.0'/'::' — so it IS LAN-exposed. parse_ip_from_address yields an empty host for
        # that form, so treat empty-host-from-a-non-empty-address as LAN, not as localhost.
        if host == "":
            return True
        return host not in ("127.0.0.1", "::1", "localhost")

    def set_folder_paused(self, folder_id: str, paused: bool) -> None:
        """
        Pause/resume a folder by toggling its `paused` flag in the config.

        Syncthing has no /rest/db/pause|resume for folders (that namespace 404s);
        folder pause state lives in the folder config. GET-modify-PUT round-trips
        the full object so we never drop fields.
        """
        folder = self.get_folder(folder_id)
        if folder is None:
            raise SyncthingError(f"Folder {folder_id} not found")
        config = dict(folder.raw)
        config["paused"] = paused
        self._put(rest_folder_path(folder_id), json=config)

    def pause_folder(self, folder_id: str) -> None:
        self.set_folder_paused(folder_id, True)

    def resume_folder(self, folder_id: str) -> None:
        self.set_folder_paused(folder_id, False)

    def wait_for_pause(self, folder_id: str, timeout: int = 10) -> bool:
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            req_timeout = max(1, min(DEFAULT_TIMEOUT, int(remaining)))
            try:
                status = self.get_folder_status(folder_id, timeout=req_timeout)
                # A paused folder's runtime state is "paused" on older Syncthing, but EMPTY ("")
                # on 1.20+ (the folder runner is simply stopped, so /rest/db/status reports no
                # state). Both mean it's no longer scanning/syncing → safe to rename the dir. We
                # only get here right after set_folder_paused(True), so an empty state is the
                # pause taking effect, not a not-yet-scanned folder. (Active states like
                # "scanning"/"syncing"/"idle" are non-empty, so we correctly keep waiting.)
                if isinstance(status, dict) and status.get("state") in ("paused", ""):
                    return True
            except SyncthingError:
                pass
            sleep_for = min(PAUSE_POLL_INTERVAL, max(0.0, deadline - time.time()))
            if sleep_for > 0:
                time.sleep(sleep_for)
        return False

    def update_folder_config(self, folder_id: str, label: str, path: str,
                             paused: bool = False) -> None:
        folder = self.get_folder(folder_id)
        if folder is None:
            # Carry the 404 so callers can tell 'folder absent on this device' apart from a
            # transient error (e.g. the rename step skips joining devices benignly).
            raise SyncthingError(f"Folder {folder_id} not found", status_code=404)

        config = dict(folder.raw)
        config["label"] = label
        config["path"] = path
        # Applying the rename also clears the paused flag set during step 4a, so the
        # single PUT both updates the folder and resumes it — no separate resume call.
        config["paused"] = paused

        self._put(rest_folder_path(folder_id), json=config)

        # Verify the update took effect. Normalize paths before comparing:
        # Syncthing on Windows adds trailing backslash and may swap slash direction.
        updated = self.get_folder(folder_id)
        if updated is None:
            raise SyncthingError("Could not verify folder config update")
        def norm(p):
            s = (p or "").replace("\\", "/").rstrip("/")
            # Windows paths are case-insensitive and Syncthing may echo a different drive-letter/
            # component case than we sent → casefold Windows-style paths so the verify doesn't
            # false-fail (mirrors renamer._norm_path); POSIX paths stay case-sensitive.
            if "\\" in (p or "") or (len(s) >= 2 and s[0].isalpha() and s[1] == ":"):
                s = s.casefold()
            return s
        if updated.label != label or norm(updated.path) != norm(path):
            raise SyncthingError(
                f"Config update not reflected: got label={updated.label!r}, path={updated.path!r}"
            )

    def update_folder_config_legacy(self, folder_id: str, label: str, path: str) -> None:
        """Fallback for Syncthing < 1.12: not supported via REST, caller must use SSH."""
        raise SyncthingError(
            "Syncthing < 1.12 does not support PUT /rest/config/folders/{id}. "
            "Use SSH fallback to edit config.xml and restart the service."
        )

    def create_folder(self, config: dict) -> dict:
        """POST /rest/config/folders — create a new folder. Returns the stored config."""
        result = self._post("/rest/config/folders", json=config)
        return result or config

    def rescan_folder(self, folder_id: str) -> None:
        """POST /rest/db/scan?folder=<id> — force an immediate scan. On a freshly-created
        folder this makes Syncthing materialize the folder root directory + .stfolder marker
        right away (under Syncthing's own home for a '~'-relative path), instead of waiting
        for the next periodic scan."""
        # Pass the id via params so requests URL-encodes it (folder ids created in the
        # Syncthing web UI may contain spaces/specials that would break a raw query string).
        self._post("/rest/db/scan", params={"folder": folder_id}, json=None)

    def delete_folder(self, folder_id: str) -> None:
        """DELETE /rest/config/folders/{id} — remove folder from config."""
        url = f"{self.base_url}{rest_folder_path(folder_id)}"
        logger.debug("DELETE %s (key=%s)", url, _mask_key(self.api_key))
        try:
            with self._lock:
                resp = self._session.delete(url, timeout=DEFAULT_TIMEOUT)
                # Already gone is success (idempotent) — a concurrent delete (passive sweep,
                # parallel topology apply) between a caller's get_folder() pre-check and this
                # DELETE must not become a hard failure. Mirrors delete_device().
                if resp.status_code == 404:
                    return
                resp.raise_for_status()
        except requests.RequestException as e:
            code = e.response.status_code if e.response is not None else None
            raise SyncthingError(f"DELETE /rest/config/folders/{folder_id} failed: {e}",
                                 status_code=code) from e

    def delete_device(self, device_id: str) -> None:
        """DELETE /rest/config/devices/{id} — remove a device from this node's config.
        Used to prune a peer that was added for a link and is no longer shared with."""
        url = f"{self.base_url}{rest_device_path(device_id)}"
        logger.debug("DELETE %s (key=%s)", url, _mask_key(self.api_key))
        try:
            with self._lock:
                resp = self._session.delete(url, timeout=DEFAULT_TIMEOUT)
                if resp.status_code == 404:
                    return
                resp.raise_for_status()
        except requests.RequestException as e:
            code = e.response.status_code if e.response is not None else None
            raise SyncthingError(f"DELETE /rest/config/devices/{device_id} failed: {e}",
                                 status_code=code) from e

    def patch_device_name(self, device_id: str, new_name: str) -> bool:
        """
        Update the 'name' field for a device entry in this instance's config.
        Returns True if updated, False if the device is not in this instance's config.
        Raises SyncthingError on connection/API errors.
        """
        url = f"{self.base_url}{rest_device_path(device_id)}"
        logger.debug("GET %s (key=%s)", url, _mask_key(self.api_key))
        try:
            with self._lock:   # whole read-modify-write atomic on this client
                resp = self._session.get(url, timeout=DEFAULT_TIMEOUT)
                if resp.status_code == 404:
                    return False
                resp.raise_for_status()
                current = resp.json()
                if not isinstance(current, dict):
                    raise SyncthingError(
                        f"patch_device_name {device_id[:7]}: malformed device config (not an object)")
                current["name"] = new_name
                logger.debug("PUT %s (key=%s)", url, _mask_key(self.api_key))
                resp2 = self._session.put(url, json=current, timeout=DEFAULT_TIMEOUT)
                resp2.raise_for_status()
                return True
        except requests.RequestException as e:
            raise SyncthingError(f"patch_device_name {device_id[:7]} failed: {e}") from e

    def browse(self, path: str = "") -> list[str]:
        """GET /rest/system/browse?current=... — directory listing for a folder
        picker (same endpoint the web UI uses to autocomplete folder paths).
        Returns the candidate paths; empty on error."""
        try:
            data = self._get("/rest/system/browse",
                             params={"current": path} if path else None)
        except SyncthingError:
            return []
        if isinstance(data, list):
            return [p for p in data if isinstance(p, str)]
        return []

    # ── .stignore (folder exclude patterns) ──────────────────────────────────
    def get_ignores(self, folder_id: str) -> list[str]:
        """GET /rest/db/ignores?folder= — the folder's .stignore patterns (the lines)."""
        data = self._get("/rest/db/ignores", params={"folder": folder_id})
        pats = data.get("ignore") if isinstance(data, dict) else None
        return [p for p in (pats or []) if isinstance(p, str)]

    def set_ignores(self, folder_id: str, patterns: list[str]) -> None:
        """POST /rest/db/ignores?folder= — replace the folder's .stignore patterns."""
        self._post("/rest/db/ignores", params={"folder": folder_id},
                   json={"ignore": list(patterns)})

    # ── Pending (incoming) requests ──────────────────────────────────────────
    def get_pending_devices(self) -> dict:
        """GET /rest/cluster/pending/devices — devices that tried to connect but aren't in
        our config yet. Returns {deviceID: {name, address, time, ...}} (empty on none/error)."""
        try:
            data = self._get("/rest/cluster/pending/devices")
            return data if isinstance(data, dict) else {}
        except SyncthingError:
            return {}

    def get_pending_folders(self) -> dict:
        """GET /rest/cluster/pending/folders — folders offered by known devices that we don't
        share yet. Returns {folderID: {offeredBy: {deviceID: {label, ...}}}} (empty on error)."""
        try:
            data = self._get("/rest/cluster/pending/folders")
            return data if isinstance(data, dict) else {}
        except SyncthingError:
            return {}

    def add_device(self, device_id: str, name: str = "", addresses=None) -> None:
        """PUT /rest/config/devices/{id} — add/accept a device into this node's config."""
        body = {"deviceID": device_id, "name": name or device_id[:7],
                "addresses": addresses or ["dynamic"], "compression": "metadata",
                "introducer": False, "autoAcceptFolders": False, "paused": False}
        self._put(rest_device_path(device_id), json=body)

    def share_folder_with_device(self, folder_id: str, device_id: str) -> None:
        """Add a device to an existing folder's device list (share our folder with it)."""
        folder = self.get_folder(folder_id)
        if folder is None:
            raise SyncthingError(f"Folder {folder_id} not found")
        cfg = dict(folder.raw)
        devs = list(cfg.get("devices") or [])
        if not any(isinstance(d, dict) and d.get("deviceID") == device_id for d in devs):
            devs.append({"deviceID": device_id})
            cfg["devices"] = devs
            self._put(rest_folder_path(folder_id), json=cfg)

    def _dismiss_pending(self, kind: str, params: dict) -> None:
        url = f"{self.base_url}/rest/cluster/pending/{kind}"
        try:
            with self._lock:
                resp = self._session.delete(url, params=params, timeout=DEFAULT_TIMEOUT)
                if resp.status_code != 404:
                    resp.raise_for_status()
        except requests.RequestException as e:
            raise SyncthingError(f"DELETE pending/{kind} failed: {e}") from e

    def dismiss_pending_device(self, device_id: str) -> None:
        """DELETE /rest/cluster/pending/devices?device= — ignore a pending device request."""
        self._dismiss_pending("devices", {"device": device_id})

    def dismiss_pending_folder(self, folder_id: str, device_id: str = "") -> None:
        """DELETE /rest/cluster/pending/folders — dismiss a pending folder offer."""
        params = {"folder": folder_id}
        if device_id:
            params["device"] = device_id
        self._dismiss_pending("folders", params)

    def check_device_id(self, device_id: str) -> dict:
        """GET /rest/svc/deviceid?id=... — Syncthing normalizes/validates a device ID.
        Returns {"id": "<normalized>"} when valid or {"error": "..."} when not.
        Raises SyncthingError on a network/connection failure."""
        return self._get("/rest/svc/deviceid", params={"id": device_id})

    def close(self) -> None:
        with self._lock:   # don't close the session out from under an in-flight request
            self._session.close()

    def __enter__(self) -> "SyncthingClient":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def is_version_gte(self, min_version: str) -> bool:
        """Check if running version >= min_version (e.g. '1.12.0'). Pre-release suffixes
        (e.g. '1.12.0-rc.1', '1.27.0-dev') compare on their numeric base, never raising."""
        import re as _re

        def _parse(v: str) -> tuple:
            out = []
            for seg in v.lstrip("v").split(".")[:3]:
                m = _re.match(r"\d+", seg)   # leading digits only — tolerate '-rc.1'/'-dev'
                out.append(int(m.group()) if m else 0)
            return tuple(out)

        try:
            current = _parse(self.get_version())
        except SyncthingError:
            return True  # Assume modern if we can't reach the API
        minimum = _parse(min_version)
        # Pad to equal length so a 2-segment version ('1.12') isn't treated as < '1.12.0'.
        n = max(len(current), len(minimum))
        current += (0,) * (n - len(current))
        minimum += (0,) * (n - len(minimum))
        return current >= minimum
