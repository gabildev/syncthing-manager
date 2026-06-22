# Integration patterns

> 🌐 **English** · [Español](integration-patterns.es.md)

Engineering patterns from `syncthing-manager` that transfer to any tool that has to
*configure a fleet of machines*, Syncthing or not. Each is paired with where it lives in the
code so you can lift it.

## 1. Reach a device five ways, in priority order

A node isn't always reachable the same way, so the engine tries channels in order and the rest
of the code is written against a single `DeviceInfo` regardless of which one won
(`renamer.py: rename_on_device`):

1. **Direct REST API** — the device's own Syncthing API (local, or a peer whose GUI is bound
   to the LAN). Fastest, richest.
2. **SSH** (`ssh_ops.py`, paramiko) — for Linux/macOS/NAS. We proxy API calls by running
   `curl` against the device's *localhost* API over the SSH session, and edit `config.xml`
   when needed.
3. **WinRM** (`winrm_ops.py`, pywinrm) — the Windows equivalent. **Windows is a first-class
   target**, not an afterthought. A Windows host is reached over WinRM, OR over **SSH** when it
   runs OpenSSH: `WindowsSSHClient` runs the *same* PowerShell operations over the SSH channel
   (the POSIX `mv`/`rm`/`test` of the SSH path would fail on a cmd.exe/PowerShell shell). Both
   Windows transports share one `_PowerShellOps` op surface, so callers treat them identically.
4. **Passive exploration** — for an offline device: keep watching, and apply the change the
   instant it reconnects to a node we control. Label/path/ID only (topology stays interactive).
5. **Agent** — a self-contained binary you copy to a device with *no* remote channel; it
   applies the change locally and reports back.

Design rule: **degrade, don't fail.** If the disk can't be renamed (API-only remote), change
only the label and keep the old path rather than leaving the folder broken.

**Security knobs** (Settings, both off by default so existing setups don't change):
- `prefer_secure_channel` — for non-local devices reachable by SSH/WinRM, route the Syncthing
  API calls over that encrypted channel (curl against the device's localhost) instead of
  hitting its API directly, so the `X-API-Key` never crosses the network. Implemented by
  demoting one `has_direct_api` flag at the channel-selection choke point (`renamer._prefer_remote_shell`).
- `ssh_strict_host_keys` — swap paramiko's `AutoAddPolicy` (TOFU) for `RejectPolicy`, refusing
  hosts not already in `known_hosts` (closes the first-connect MITM window).
- `winrm_strict_cert` — validate the server's TLS certificate for WinRM-over-HTTPS (off by
  default: self-signed certs are common on internal Windows boxes, and plain HTTP/5985 is
  NTLM-message-encrypted anyway, so there's no cleartext exposure to gate).

**Keep the API key off the remote argv.** When an API call is proxied over a shell channel the
key is fed on **stdin**, never the command line, so it can't be read from the remote process list
(`ps` / `/proc/*/cmdline` / `Win32_Process.CommandLine`): `curl -K -` for the POSIX SSH path, and
`powershell -Command -` (an ASCII base64 bootstrap, never `-EncodedCommand`) for both Windows
transports (WinRM and PowerShell-over-SSH). The bootstrap also forces UTF-8 in/out so non-ASCII
paths and labels survive the remote console codepage.

## 2. Discovery + hub expansion

`discovery.py` runs device probes **in parallel** (API/SSH/WinRM at once) and merges. Two
ideas worth stealing:

- **Hub expansion**: a folder's full membership isn't in any single node's config — each node
  only lists *its* peers. So after probing the known devices, query a reachable hub (e.g. a
  always-on Pi) for *its* peer list and fold in devices you'd otherwise never see.
- **Address backfill**: the active connection address is often link-local IPv6. Cross-reference
  `/rest/system/discovery` and `/rest/stats/device` to recover a dialable IPv4.
- **Incremental merge on re-discover**: re-running discovery merges by `device_id` and
  **preserves manually-entered credentials** — never blow away SSH keys/passwords the user
  typed because a device went briefly offline.
- **Name resolution across nodes**: a peer's friendly name isn't global — every node keeps its
  own, and an introduced/offline peer is often unnamed (a bare device id). Resolve a label by
  **authority** (`topology._resolve_name_map`): the LOCAL node's config wins a conflict;
  otherwise a discovered, hub-known, or self-announced name is used; a short-id is the last
  resort. A node shown *only* via a hub's `folder_peers` (no `DeviceInfo` of its own) has its
  name fetched straight from the hub, so it never renders as a raw id.

## 3. Self-extending agent binaries

The offline-device agent (`generate.py`, `agent.py`) is a neat trick for shipping
configuration as a runnable:

- A pre-built **template** executable is produced once per OS (`build/agent_*.spec`, onefile).
- To "generate an agent" you **append** a config blob to the template bytes, delimited by
  fixed `MARKER_START`/`MARKER_END` sentinels: `template || MARKER_START || json || MARKER_END`.
  At runtime the agent reads its own file, finds the markers, and loads the trailing JSON.
- Generation **never executes** the template — it only concatenates bytes. That's why a
  **Windows** machine can produce a **Linux** agent and vice-versa, as long as the other OS's
  template is present. Both templates are **embedded** into the main app (PyInstaller
  `--add-data`, extracted from `sys._MEIPASS` on demand), so one binary generates agents for
  every OS (cross-OS, see the CI workflow which embeds the templates into each build).
- **Arch matters for Linux/macOS** — there's no in-OS cross-arch execution to lean on, so the
  template is built **per (OS, arch)**: `…-template-linux-amd64`/`-arm64`,
  `…-template-macos-amd64`/`-arm64` (Windows ships a single x64 `.exe` that emulates on
  Windows-ARM). The app embeds all of them and picks the match for each device's detected (or
  user-chosen) CPU arch. PyInstaller can't cross-compile a native binary, so each arch's template
  must be built **on** that arch — CI uses native arm64 Linux and Intel/Apple-Silicon macOS
  runners. A device's arch is read from `/rest/system/version` (`arch`) or SSH `uname -m`.
- The agent **verifies identity** before acting: it compares the local `myID`
  (`/rest/system/status`) against the device ID baked into its config, so an agent dropped on
  the wrong machine refuses to run.

## 4. Encryption {#encryption}

Both saved credentials (`credentials.py`) and the agent's embedded config (`generate.py`) use
the **same scheme**, so there's one thing to reason about:

- **Fernet** (AES-128-CBC + HMAC) with a key derived by **PBKDF2-HMAC-SHA256, 480,000
  iterations**, over a random 16-byte salt stored alongside the ciphertext.
- The passphrase is never stored. Credentials are encrypted only when a master password is
  set; otherwise they're plaintext on a `0600`-style local file.
- The agent payload (Syncthing API key, etc.) is encrypted `encrypted-v1` with this scheme so
  a generated agent file isn't a plaintext key sitting on disk in transit.

## 5. Topology as a pure graph model

`topology.py` is **tkinter-free** on purpose: a pure model of nodes/edges/roles that both the
GUI canvas and the CLI render. Keeping the model free of UI lets you:
- unit-test it headless (`tests/test_topology*.py`),
- compute a **diff** (`renamer.compute_topology_diff`) between the original and edited graph
  and apply only the delta per device,
- serialize/snapshot it to disk (for undo and passive application).

General lesson: **separate the domain model from both the UI and the transport.** The REST
client, the graph model, and the GUI never import each other's concerns.

## 6. Fast GUI startup: lazy imports + onedir

Two independent wins, both about not paying for what you don't use yet:

- **Lazy imports**: `requests`/`urllib3` (~50 ms), `paramiko`, `cryptography` are imported
  *inside* the functions that need them, not at module top. GUI cold start dropped from ~300 ms
  to ~150 ms. The import is memoized (`_load_requests`).
- **onedir, not onefile**: PyInstaller `onefile` self-extracts a ~30 MB archive to a temp dir
  on **every** launch — the dominant startup cost. `onedir` ships a folder whose binary loads
  its libraries in place. We distribute that folder zipped/tarred; the user extracts once.

## 7. Portable, discoverable data dir

`config.py` resolves the data directory in priority order (next to the executable for a
**portable** install → a pointer file → OS-standard `%APPDATA%`/`~/.config`), and only falls
back to a writable location. Settings, per-folder credentials, and topology snapshots all live
there. Lesson: make "portable on a USB stick" and "installed per-user" the *same* code path,
decided at runtime by what's writable.

## 8. i18n without a framework

`i18n.py` uses the **Spanish source string as the translation key** and a flat
`translations_en.py` table, plus a thin tkinter shim that auto-translates widget `text`/titles.
No `.po` toolchain. Trade-off: simple and zero-dependency, but keys churn when you reword
source strings. Fine for a two-language app; reconsider for many locales.

Coverage is enforced by an **AST test** (`tests/test_i18n.py`): it walks the package for every
user-facing call — `t()`, tkinter `text=`/`label=`/messagebox, and the CLI's
`typer.prompt/confirm`, `console.print`, `getpass`, `add_column`, `help=` — and fails if any
Spanish literal lacks an English entry. Companion guards cover what the literal scan can't see —
a Spanish string passed *unwrapped* to a sink the shim doesn't translate (Text-widget writers,
`Combobox.set`), and key↔value placeholder drift. So the whole stack — GUI, CLI, the offline-device
agent and the backend (renamer/discovery/validation/topology/…) — stays fully bilingual without a
human remembering to translate each new string.
