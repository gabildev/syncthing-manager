# Syncthing concepts & gotchas

> 🌐 **English** · [Español](syncthing-concepts.es.md)

The mental model you need before automating Syncthing, and the sharp edges that cost real
debugging time. Pairs with [syncthing-rest-api.md](syncthing-rest-api.md).

## Device IDs

- A device ID is a long, stable, self-certifying string (the hash of the node's TLS cert).
  It identifies a node across address changes. It is **not** secret — it's how peers name
  each other.
- `GET /rest/system/status → myID` is "who am I". This is the anchor for **identity checks**:
  an agent sent to a machine confirms it's on the right one by comparing the local `myID`
  against the expected device ID before doing anything.
- Validate/normalize IDs via `GET /rest/svc/deviceid?id=...` rather than with your own regex.

## Folder IDs are immutable

The single most important gotcha. Syncthing has **no API to change a folder's ID**, and the
ID is the key peers use to associate the folder across the cluster.

To "rename" an ID you must **delete + recreate** on every device:
1. Fetch the current folder config.
2. DELETE the old folder (old and new can't coexist on the same path — Syncthing forbids two
   folders pointing at one directory).
3. POST a new folder with the new ID and the *same* path/devices/options. If the POST fails,
   recreate the original to roll back.

Do this on **every** device, not just one. If only some flip, the cluster is temporarily
split: peers still on the old ID see the folder go stale and get a "new folder offered"
prompt. That's expected for any device you couldn't reach (it stays on the old ID until an
agent or a later pass updates it). The label and on-disk path, by contrast, *are* mutable via
a normal `PUT`.

## label vs path vs ID

Three independent things people conflate:

- **label** — the human-friendly display name. Free text, mutable, purely cosmetic.
- **path** — the directory on disk. Mutable via PUT, but changing it does **not** move the
  data; you must rename the directory on disk *and* update the config to match. If you can't
  rename the directory (e.g. an API-only remote with no shell), only change the label and
  leave the path — pointing the config at a non-existent path puts the folder in an error
  state.
- **ID** — the cluster key. Immutable (see above).

## config.xml — where it lives

When there's no API/SSH channel you read/patch `config.xml` directly. Its location varies a
lot; search candidates in this order (see `discovery.py`):

**Windows**
- `%LOCALAPPDATA%\Syncthing\config.xml`
- `%APPDATA%\Syncthing\config.xml`

**Linux / macOS** (XDG and historical paths)
- `$XDG_STATE_HOME/syncthing/config.xml`, `~/.local/state/syncthing/config.xml`
- `$XDG_DATA_HOME/syncthing/config.xml`, `~/.local/share/syncthing/config.xml`
- `$XDG_CONFIG_HOME/syncthing/config.xml`, `~/.config/syncthing/config.xml`
- `~/.syncthing/config.xml`
- `~/Library/Application Support/Syncthing/config.xml` (macOS)
- Snap: `~/snap/syncthing/current/.local/{state,share,config}/syncthing/config.xml`
- System service: `/var/lib/syncthing/.local/state/syncthing/config.xml`

On a remote you can also derive the real path from the **running process**: inspect
`/proc/<pid>` for a `--home=`/`-home` arg, or read the systemd unit's `ExecStart`. The process
is more authoritative than guessing.

The API key is the `<gui><apikey>` element in that XML; the GUI/API port is the `<gui>`
`address`. That's how you bootstrap an API client when the key isn't already known.

## Send/receive roles

A folder has a per-node **type**:
- `sendreceive` (default) — two-way.
- `sendonly` — this node pushes, ignores incoming changes.
- `receiveonly` — this node accepts, never pushes local changes.

When you model topology, the role lives on each node's copy of the folder config, so a
"link" between two nodes can be asymmetric (A sendonly ↔ B receiveonly). Reconcile by reading
each side, not by assuming symmetry.

## Pending acceptance flow

Sharing is **mutual consent**. When A shares a folder with B, B doesn't get it automatically —
B sees it under `GET /rest/cluster/pending/folders` and must accept (add the folder, or add A
to its device list). Likewise a new device shows up under `pending/devices` until accepted.

This is why "change the folder ID across the cluster" can't be fully hands-off for devices you
can't reach programmatically: someone/something has to accept on the far side. The tool's
answer is the **agent** (run code locally on that device) or **passive exploration** (wait and
apply the moment the device reconnects to a node you *do* control).

## .stfolder and .stignore

- **`.stfolder`** is a marker directory Syncthing creates inside a folder to prove the path
  exists and is the intended folder. After moving a directory you may need to ensure it's
  present. It also doubles as a safety marker: destructive operations check for it before
  touching a tree, so you never `rm -rf` an arbitrary path.
- **`.stignore`** holds exclude patterns. Read/replace via `GET`/`POST /rest/db/ignores`
  (replace, not append).

## Encrypted folders

Syncthing supports untrusted/encrypted folders (a password per share). If you read folder
config generically, don't assume every peer holds plaintext — an encrypted peer's view
differs. This project's agent payload can itself be encrypted independently of that (see
[integration-patterns.md](integration-patterns.md#encryption)).

## Versioning & restarts

- Config changes via REST are live; you generally **don't** restart Syncthing.
- The one case that needs a restart is the legacy `config.xml`-editing path (Syncthing < 1.12,
  or no REST channel at all): edit the XML, then restart the service for it to load.
