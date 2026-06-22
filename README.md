<p align="center">
  <img src="assets/banner.png" alt="syncthing-manager" width="360">
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue.svg" alt="Python">
  <a href="https://github.com/gabildev/syncthing-manager/releases"><img src="https://img.shields.io/github/v/release/gabildev/syncthing-manager?sort=semver" alt="Release"></a>
  <a href="https://github.com/gabildev/syncthing-manager/actions/workflows/build.yml"><img src="https://github.com/gabildev/syncthing-manager/actions/workflows/build.yml/badge.svg" alt="Build &amp; Release"></a>
</p>

<p align="center"><strong>🌐 English</strong> · <a href="README.es.md">Español</a></p>

Rename and manage a **Syncthing shared folder across your whole cluster** — label, on‑disk
path, and even the folder **ID** — from one place. No manual `config.xml` editing on every
machine, no service restarts, no sync conflicts.

It ships **two interfaces over the same engine**:

- 🖥️ **GUI** — a desktop app with a guided rename flow, a live
  **topology view/editor** of the folder across devices, credential management and an
  execution panel. This is the primary, most capable interface.
- ⌨️ **CLI** — scriptable commands (`folders`, `discover`, `rename`,
  `topology`, `create-folder`, `share`, `unshare`, `delete-folder`, `undo`, `generate-agent`) for headless servers and automation.

## GUI vs CLI — who does what

Same engine underneath; the difference is the experience and a few interactive‑only features.

| Capability | 🖥️ GUI | ⌨️ CLI |
|---|:---:|:---:|
| Guided rename — label / directory / absolute path / folder ID | ✓ | ✓ |
| Discover devices sharing a folder | ✓ | ✓ |
| View the per‑folder topology | ✓ interactive graph | ✓ printed |
| **Edit** topology — drag links, change roles, per‑device path, add devices | ✓ | — read‑only |
| Share / unshare a folder · create a folder | ✓ | ✓ |
| **Delete a folder** — from Syncthing and (optionally) its on‑disk data, per‑device or cluster‑wide | ✓ | ✓ |
| Undo last rename · generate an offline agent | ✓ | ✓ |
| Passive — apply to offline devices on reconnect | ✓ | ✓ |
| Credential management | ✓ in‑app, saved per device | `devices.yml` |
| Per‑device `.stignore` · pause/resume · accept pending requests · app lock | ✓ | — |
| Dry‑run / preview changes before applying | ✓ | ✓ |
| Non‑interactive · headless · scripting / automation | — | ✓ |

## What it does

- **Rename across the whole cluster at once** — label, directory name / absolute path, and the
  folder **ID**, applied to every reachable device.
- **Three ways to reach a device** — the Syncthing REST API, **SSH** (Linux, macOS, NAS, and
  **Windows via OpenSSH**), or **WinRM** (Windows): it reads the node's config, finds the folder,
  and applies the change.
- **Topology view & editor** — the real per‑folder graph (devices, roles, links, online/offline);
  share/unshare, link/unlink devices, change send/receive roles, set a per‑device path, add devices.
- **Offline devices** — applied the moment they reconnect (**passive exploration**), or via a
  generated **agent binary** you run on a device with no remote access.
- **Safe by design** — dry‑run, pre‑flight checks (path validity, destination exists,
  cross‑filesystem moves, ID collisions), `.stfolder` repair, automatic pause/resume, and **undo**.
  A rename never deletes your data; deleting a folder is a separate, explicitly‑confirmed action.
- **Encrypted agent config** and persistent, **per‑device** credential storage.

## Installation

**Download a build** from [Releases](https://github.com/gabildev/syncthing-manager/releases)
for your platform, extract it, and run the binary inside the `syncthing-manager/` folder — **no
Python needed** (it's a self-contained **onedir** bundle: a folder, not an installer). On Linux
you can drop the folder under `/opt` and symlink it onto your `PATH` — see
[Install as a system command](#install-as-a-system-command-linux). To build your own, see
[Building binaries](#building-binaries).

> ℹ️ Linux and Windows are the most battle‑tested. **macOS** builds (Intel + Apple Silicon) are
> provided and the code treats macOS as a first‑class POSIX target, but they've had less
> real‑world testing — issue reports welcome.

**From source** (for development, or a platform with no prebuilt binary):

```bash
git clone https://github.com/gabildev/syncthing-manager
cd syncthing-manager
pip install -e .          # add ".[dev]" for the test/build extras (pytest, pyinstaller)
```

**Requires Python 3.10+.** The GUI needs Tk (`python3-tk` on Debian/Ubuntu; bundled with
python.org builds on Windows/macOS).

## Requirements

- **Syncthing ≥ 1.12** on the devices you manage (for the per-object REST config API; older versions are driven over SSH/WinRM instead).
- The **local** Syncthing REST API reachable (default `https://127.0.0.1:8384`); the tool
  auto‑detects the API key from the local config when possible.
- To configure **remote** devices without manually accepting on each one, provide a channel:
  the remote's API key + URL, **SSH** credentials, or **WinRM** credentials. Devices with no
  channel are handled passively (on reconnect) or via an agent.

## GUI quick tour

```bash
syncthing-manager-gui
```

1. **Connection** — point at the local Syncthing (auto‑detected), pick a folder.
2. **Devices** — review discovered devices; add SSH/WinRM/API credentials (with “probe &
   connect”), browse for an SSH key, choose each device's OS (auto‑detected when reachable).
3. **Names** — choose the new label, on‑disk path, and/or folder ID (each independently).
4. **Topology** — inspect and edit the per‑folder graph: right‑click a node to stop sharing
   the folder / unlink the device / edit it; drag to add or cut links; set roles. Changes are
   shown as a diff and applied only where reachable (the rest go passive/agent).
5. **Preview & Execute** — a per‑device preview of exactly what will change, then run it with
   a live progress/results panel and a retry button.

<details>
<summary><h3>📸 Screenshots</h3></summary>

**1 · Connection** — point at the local Syncthing and connect

<p align="center"><img src="assets/screenshots/connection.png" alt="Connection" width="820"></p>

**2 · Folder** — pick a folder, or create a new one

<p align="center"><img src="assets/screenshots/folder.png" alt="Folder" width="820"></p>
<p align="center"><img src="assets/screenshots/new-folder.png" alt="New folder" width="820"></p>

**3 · Devices** — discovered devices; set per‑device SSH/WinRM/API credentials, sync names, and handle offline devices via agent / passive exploration

<p align="center"><img src="assets/screenshots/devices.png" alt="Devices" width="820"></p>
<p align="center"><img src="assets/screenshots/edit-credentials.png" alt="Edit credentials" width="820"></p>
<p align="center"><img src="assets/screenshots/sync-names.png" alt="Sync device names" width="820"></p>
<p align="center"><img src="assets/screenshots/offline-agents.png" alt="Offline devices" width="820"></p>

**4 · Names** — choose the new label, on‑disk path and/or folder ID

<p align="center"><img src="assets/screenshots/names.png" alt="Names" width="820"></p>

**5 · Topology** — inspect and edit the per‑folder graph; add devices

<p align="center"><img src="assets/screenshots/topology.png" alt="Topology" width="820"></p>
<p align="center"><img src="assets/screenshots/add-device.png" alt="Add device" width="820"></p>

**6 · Execute** — dry‑run or run with a live log, then generate agents for offline devices. Each device's OS and CPU arch are auto‑detected (or you pick them per device), so the right binary is built — Windows / Linux / macOS, amd64 / arm64

<p align="center"><img src="assets/screenshots/execute.png" alt="Execute" width="820"></p>

**Settings** — security knobs, language, default ports and the optional app lock

<p align="center"><img src="assets/screenshots/settings.png" alt="Settings" width="820"></p>

</details>

## CLI

```bash
syncthing-manager --help
```

| Command | What it does |
|---|---|
| `folders` | List folders on the local node. |
| `discover` | Discover all devices sharing a folder (read‑only). |
| `rename` | Rename a folder's label / path / ID across the cluster. |
| `topology` | Print the real per‑folder topology (devices, roles, links, inconsistencies). |
| `create-folder` | Create a new folder on this machine (local) and register it in Syncthing; share it afterwards with `share`. |
| `share` | Share a folder with a device — add it to the folder membership on this machine (or on a reachable member via `--with`). |
| `unshare` | Stop sharing a folder with one device across the cluster (config only — never deletes files). |
| `delete-folder` | **Destructive:** remove a folder from Syncthing and (unless `--keep-data`) delete its on‑disk data, per‑device or cluster‑wide. Refuses protected paths / folders without a `.stfolder` marker and asks you to type the folder name to confirm. |
| `undo` | Revert the last rename (label, path, and folder ID if changed). |
| `generate-agent` | Build an agent executable for a device with no SSH/WinRM access. |
| `gui` | Open the desktop GUI. |

### Rename examples

```bash
# Interactive
syncthing-manager rename

# Non-interactive (scripts)
syncthing-manager rename -f my-folder-id -l "New Label" -d "new-dir-name" --no-confirm

# See what would happen, change nothing
syncthing-manager rename --dry-run

# Only the label; keep the on-disk path
syncthing-manager rename --skip-path-rename -l "New Label"

# Also change the folder ID
syncthing-manager rename -f old-id --new-folder-id new-id

# Keep waiting for offline devices and apply on reconnect (Ctrl-C to stop)
syncthing-manager rename --passive

# Only this machine
syncthing-manager rename --local-only
```

Key `rename` options: `--folder/-f`, `--label/-l`, `--dir-name/-d`, `--new-folder-id`,
`--api-key/-k`, `--url`, `--config/-c devices.yml`, `--dry-run`, `--no-confirm`,
`--local-only`, `--skip-path-rename`, `--passive`. Global flag (before any command):
`--lang es|en` for the interface language.

## devices.yml — credential overrides

When auto‑detection isn't enough (password auth, non‑standard config paths, WinRM, etc.),
supply a `devices.yml` and pass it with `--config` (CLI) or load it from the GUI:

```yaml
defaults:
  ssh_user: ubuntu
  ssh_key_path: ~/.ssh/id_rsa

devices:
  - name: nas
    ssh_host: 192.168.1.20
    ssh_user: admin
    syncthing_config_path: /volume1/@appstore/syncthing/var/config.xml

  - device_id: "XXXXXXX-..."
    name: winbox
    winrm_host: 192.168.1.30
    winrm_user: Administrator
    winrm_password: "..."
```

See `devices.example.yml`. The GUI also stores credentials per device so you don't re‑enter
them; real `devices.yml` files are git‑ignored.

## Agents for unreachable devices

For a device with no API/SSH/WinRM channel, generate a self‑contained agent and run it there:

```bash
syncthing-manager generate-agent --os windows                 # or: --os linux / --os macos
# For a Linux/macOS target of a different CPU, pick the arch (default: the host arch on Linux; on macOS the embedded one — amd64, else arm64):
syncthing-manager generate-agent --os linux --arch arm64       # e.g. a 64-bit Raspberry Pi
syncthing-manager generate-agent --os macos --arch arm64       # e.g. an Apple-Silicon Mac
```

The agent carries the (optionally encrypted) instructions, applies the rename locally, and
verifies identity by Syncthing device ID. Agent templates are built from `build/agent_*.spec`.

## Building binaries

```bash
# Windows (from a Windows machine) — builds the agent template, then the main exe
build\build_windows.bat

# Linux
build/build_linux.sh

# macOS (from a Mac) — same onedir + agent template, as a Mach-O binary
build/build_macos.sh

# Any, with --no-package: build only the onedir folder, skip the .zip/.tar.gz
# (faster iteration while testing — alias --no-pack / --skip-package)
build/build_linux.sh --no-package
```

The main app is built **onedir** (a folder, not a single self‑extracting exe) for fast
startup, and the scripts package it as `syncthing-manager-windows.zip` /
`syncthing-manager-linux.tar.gz` — extract and run the binary inside (pass `--no-package`
to skip that archive step while testing). The offline‑device **agent templates** stay
single‑file (you copy one to a device and run it). Both scripts clean up their own
temporary build files afterward, leaving only `dist/` and the sources.

<details>
<summary><strong>CI &amp; release automation</strong></summary>

CI (`.github/workflows/build.yml`) builds the agent templates and main executables on every
tag push (`v*`) and attaches `syncthing-manager-windows.zip`,
`syncthing-manager-linux-amd64.tar.gz`, `syncthing-manager-linux-arm64.tar.gz`,
`syncthing-manager-macos-amd64.tar.gz`, `syncthing-manager-macos-arm64.tar.gz` (plus a
`SHA256SUMS.txt`) and every agent template (Windows, Linux ×2, macOS ×2) to a **GitHub
Release** automatically. (A local `build_*.sh` produces a single un‑suffixed tarball for the
host arch.) Each main binary embeds *all* agent templates, so any platform's release can
generate agents for Windows, Linux and macOS. Tag a release
with e.g. `git tag v1.0.0 && git push --tags`; run it manually from the Actions tab
(`workflow_dispatch`) to build artifacts without publishing. Build outputs (`dist/`,
`build_tmp/`) are git‑ignored.

</details>

### Install as a system command (Linux)

The build is **onedir**: the `syncthing-manager` binary needs the files next to it (its
`_internal/` runtime), so you can't copy the binary alone into `/usr/local/bin`. Move the
**whole folder** and symlink the binary onto your `PATH`:

```bash
# From a GitHub Release pick your arch: -linux-amd64 (PC/WSL) or -linux-arm64 (Pi 64-bit).
# (A local build_linux.sh produces the un-suffixed syncthing-manager-linux.tar.gz.)
tar -xzf syncthing-manager-linux-amd64.tar.gz
sudo mv syncthing-manager /opt/syncthing-manager
sudo ln -s /opt/syncthing-manager/syncthing-manager /usr/local/bin/syncthing-manager
```

Now `syncthing-manager` is a global command. A terminal is always the CLI: a bare command in a
shell prints help, any subcommand runs, and `syncthing-manager gui` opens the GUI; the GUI also
opens on a double-click / desktop launcher (a bare launch with no terminal attached). The binary
resolves the symlink to find its libraries, and because `/opt`
isn't user‑writable, each user's data lands in their own `~/.config/syncthing-manager/`
automatically — shared binary, per‑user config. (Install it under a **writable** path instead,
e.g. `~/apps/…`, and it stays *portable*, keeping its data inside its own folder.)

> Prefer a clean install from source? `pip install .` puts `syncthing-manager` (CLI) and
> `syncthing-manager-gui` (GUI) on your `PATH` directly and uses `~/.config`. The onedir binary
> is for distributing **without** requiring Python.

## Project layout

```
syncthing_manager/
  cli.py          Typer CLI (commands above)
  _dispatch.py    CLI-vs-GUI launch logic (terminal → CLI; bare double-click → GUI)
  gui/            Tkinter GUI package — app shell + one module per page:
                    app.py, common.py, settings.py, page_connect.py, page_folder.py,
                    page_devices.py, page_names.py, page_topology.py, page_execute.py
  applock.py      Optional GUI lock (lock-now + idle auto-lock; off by default)
  discovery.py    Parallel device discovery (API/SSH/WinRM, hub expansion)
  renamer.py      Core engine: rename, topology apply/diff, share/unshare, unlink, pre-flight
  topology.py     Pure topology-graph model (no tkinter — used by GUI and CLI)
  syncthing.py    Syncthing REST API client
  ssh_ops.py      SSH operations (paramiko)
  winrm_ops.py    WinRM operations (pywinrm)
  agent.py        Agent generation/runtime
  generate.py     Agent executable packaging
  device_names.py Device-name sync
  credentials.py  Persistent per-device credential storage
  config.py       App config & data directory (incl. language preference)
  models.py       Dataclasses (DeviceInfo, FolderConfig, results)
  validation.py   Path/name validation (POSIX vs Windows)
  i18n.py         Language detection + translations (English/Spanish)
  translations_en.py  English translation table (Spanish source strings are the keys)
build/            PyInstaller specs, build scripts (prebuilt agent templates are generated/synced, not versioned)
tests/            pytest suite (pure logic: renamer, topology, discovery, …)
docs/             Reusable reference: Syncthing REST API, concepts/gotchas, integration patterns
```

## Tests

```bash
pip install -e ".[dev]"
pytest
```

## Troubleshooting

- **API not reachable on a remote**: Syncthing's GUI/API is often bound to `127.0.0.1`. Bind
  it to the LAN IP, use an SSH/WinRM channel (which reaches the API on the device's
  localhost), or rely on passive/agent.
- **SSH fails**: confirm `ssh user@ip` works manually; set the right key in `~/.ssh/config`
  or `devices.yml`; set a non‑standard port in `devices.yml`.
- **Windows remotes**: supported via **WinRM** (enable WinRM on the target) or via an agent.
- **A device is left paused after an error**: the tool reports it; resume from the Syncthing
  web UI, or `curl -X POST -H "X-API-Key: <key>" "http://localhost:8384/rest/db/resume?folder=<id>"`.

## Documentation

`docs/` holds reusable reference notes for building tools on top of Syncthing — distilled from
this project's integration work, written to be useful for future apps too:

- [`docs/syncthing-rest-api.md`](docs/syncthing-rest-api.md) — the REST endpoints used here, with the catch for each.
- [`docs/syncthing-concepts.md`](docs/syncthing-concepts.md) — device/folder IDs, the immutable‑ID rename strategy, `config.xml` locations, roles, pending acceptance.
- [`docs/integration-patterns.md`](docs/integration-patterns.md) — multi‑channel device reach, discovery/hub expansion, self‑extending agents, encryption, fast‑startup packaging.

## Contributing

1. Fork and branch: `git checkout -b feat/my-feature`
2. Make changes and add tests
3. `pytest`
4. Open a pull request

## License

**MIT** — see [`LICENSE`](LICENSE).

The distributed binaries bundle third‑party libraries under their own (permissive) licenses;
attributions are in [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md), which also ships
inside the release archives. Note paramiko is **LGPL‑2.1** — keep that notice when
redistributing (the full source here already satisfies its relink clause).
