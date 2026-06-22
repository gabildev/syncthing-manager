# Syncthing REST API — practical reference

> 🌐 **English** · [Español](syncthing-rest-api.es.md)

A cheat-sheet of the endpoints `syncthing-manager` relies on, with the **gotcha** for each.
This is the subset that matters when building a config/automation tool; it is not the full
upstream surface (see <https://docs.syncthing.net/dev/rest.html> for that).

## Basics

- **Base URL**: `https://127.0.0.1:8384` by default. The API and the web GUI share the same
  port/listener (`/rest/config/gui` → `address`).
- **Auth**: header `X-API-Key: <key>`. No key → `401/403`.
- **TLS**: Syncthing ships a **self-signed cert**, so an HTTP client must disable verification
  (`verify=False`) and silence `InsecureRequestWarning`. This is acceptable **only because the
  default listener is loopback** (`127.0.0.1`) — there's no network to MITM. If you talk to a
  Syncthing whose GUI is bound to a LAN/public address, don't blindly keep `verify=False`:
  pin its cert or add it to your trust store, otherwise the connection is genuinely
  interceptable. (This tool's `prefer_secure_channel` setting sidesteps it for non-local
  devices by tunnelling the API call over SSH/WinRM instead.)
- **Min version**: the config endpoints below (`PUT /rest/config/folders/{id}`) require
  **Syncthing ≥ 1.12** (per-object config endpoints landed in 1.12.0). Older versions have no per-object config REST and must be driven by
  editing `config.xml` + restarting the service.
- **Config writes are atomic per object and persisted immediately** — there is no separate
  "save/commit". A `PUT`/`POST`/`DELETE` on `/rest/config/...` takes effect live.

## System / status

| Endpoint | Method | Returns / use | Gotcha |
|---|---|---|---|
| `/rest/system/ping` | GET | `{"ping":"pong"}` | Best probe for "is it up + is my key valid". Distinguish `down` (connection refused/timeout) vs `auth` (401/403) vs `ok` by inspecting the status code, not just success. |
| `/rest/system/status` | GET | `{"myID": ...}` | `myID` is **this** node's device ID — the basis for identity checks. |
| `/rest/system/version` | GET | `{"version","os","arch"}` | `os` is `"windows"`, `"linux"`, `"darwin"`, … — use it to detect a peer's OS for path handling. Version never changes for a live process → cache it. |
| `/rest/system/connections` | GET | `{connections:{devID:{connected,address,clientVersion}}}` | `address` is the *active* connection, which is often a link-local **IPv6** — not a dialable IPv4. |
| `/rest/system/discovery` | GET | `{devID:{addresses:[...]}}` | Frequently the only place a usable **IPv4** shows up when the live connection is IPv6. Best-effort; may be empty. |
| `/rest/system/browse?current=<path>` | GET | `[paths]` | Server-side directory listing — the same autocomplete the web UI uses for a folder picker. Runs on the *target* node's filesystem. |
| `/rest/stats/device` | GET | `{devID:{lastSeen,lastAddress}}` | `lastAddress` can backfill an address for an offline device. |

## Folders (config)

| Endpoint | Method | Use | Gotcha |
|---|---|---|---|
| `/rest/config/folders` | GET | List all folders. | — |
| `/rest/config/folders` | POST | **Create** a folder from a full config object. | — |
| `/rest/config/folders/{id}` | GET | One folder's config. | **404 = genuinely absent**; a timeout/5xx/auth is a *transient* error. Treat them differently or you'll overwrite/recreate a folder that was only briefly unreachable. |
| `/rest/config/folders/{id}` | PUT | Update a folder. | **GET-modify-PUT the whole object.** A partial PUT drops every field you didn't send. Round-trip `folder.raw` and change only what you mean to. |
| `/rest/config/folders/{id}` | DELETE | Remove the folder from config. | Removes it from *this* node only. Does **not** delete the data on disk. |
| `/rest/db/status?folder={id}` | GET | Runtime state (`state: "idle"/"syncing"/"paused"`, completion). | This is *runtime*, separate from config. Poll it to confirm a pause actually landed. |
| `/rest/db/ignores?folder={id}` | GET / POST | Read / replace `.stignore` patterns (`{"ignore":[...]}`). | POST **replaces** the whole list, not appends. |

### Pausing a folder — the trap

There is **no** `/rest/db/pause` / `/rest/db/resume` for folders (that namespace 404s; those
verbs exist only for *devices*). Folder pause state lives in the **config**: GET the folder,
set `"paused": true|false`, PUT it back. Conveniently this means a single PUT that updates
`label`/`path` and sets `paused:false` both applies the change and resumes the folder.

After a path-changing PUT, **verify** the read-back: Syncthing on Windows normalizes paths
(adds a trailing `\`, may flip slash direction), so compare with slashes normalized and
trailing separators stripped, not with `==`.

## Devices (config)

| Endpoint | Method | Use | Gotcha |
|---|---|---|---|
| `/rest/config/devices` | GET | List configured devices. | — |
| `/rest/config/devices/{id}` | GET | One device entry. | 404 = not in this node's config. |
| `/rest/config/devices/{id}` | PUT | Add/accept a device, or edit its `name`. | To accept a device, PUT a full body (`deviceID`, `name`, `addresses:["dynamic"]`, `compression`, …). To rename, GET-modify-PUT. |
| `/rest/config/devices/{id}` | DELETE | Remove a device from config. | 404 is fine (already gone). Prune a peer only once **no** folder still shares with it. |

Sharing a folder with a device = add `{"deviceID": id}` to that folder's `devices[]`
(GET-modify-PUT the folder, not the device).

## Pending (incoming) requests

| Endpoint | Method | Returns | Use |
|---|---|---|---|
| `/rest/cluster/pending/devices` | GET | `{devID:{name,address,time}}` | Devices that tried to connect but aren't in config yet. |
| `/rest/cluster/pending/folders` | GET | `{folderID:{offeredBy:{devID:{label}}}}` | Folders offered by known devices we don't share yet. |
| `/rest/cluster/pending/devices?device={id}` | DELETE | — | Dismiss/ignore a pending device. |
| `/rest/cluster/pending/folders?folder={id}[&device={id}]` | DELETE | — | Dismiss a pending folder offer. |

To **accept** a pending device/folder you don't DELETE — you *add* it (PUT the device, or add
it to the folder's `devices[]`). DELETE here only means "dismiss the request". 404 on dismiss
is benign.

## Validation helper

| Endpoint | Method | Returns |
|---|---|---|
| `/rest/svc/deviceid?id={id}` | GET | `{"id":"<normalized>"}` if valid, `{"error":...}` if not. Let Syncthing normalize/validate a device ID instead of regexing it yourself. |

## Error-handling rules that bit us

1. **Carry the HTTP status on your exception.** "Folder absent (404)" vs "host had a blip
   (timeout/5xx)" must be distinguishable, or you'll recreate/overwrite live data.
2. **Pause is best-effort.** A 404 (older Syncthing, or folder not on that node) or an empty
   SSH-`curl` body shouldn't abort the operation — proceed and let the real write report the
   true error.
3. **Always verify writes that matter** (path changes) by reading back and comparing
   *normalized* values.
4. **GET-modify-PUT** for every config object. Never construct a partial PUT body by hand.
