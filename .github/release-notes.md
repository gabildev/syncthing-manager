### Downloads

<div align="center">

| File | Platform |
|---|---|
| `syncthing-manager-windows.zip` | Windows (x86-64) |
| `syncthing-manager-linux-amd64.tar.gz` | Linux (x86-64, incl. WSL) |
| `syncthing-manager-linux-arm64.tar.gz` | Linux (ARM64 — Raspberry Pi 64-bit, etc.) |
| `syncthing-manager-macos-amd64.tar.gz` | macOS (Intel · x86-64) |
| `syncthing-manager-macos-arm64.tar.gz` | macOS (Apple Silicon · M1/M2/M3…) |

</div>

<br>

It's a **one-dir** build (fast startup — nothing is unpacked at launch): extract the archive and you get a `syncthing-manager/` folder — keep its files together.

### Quick start

The executable inside that folder is **both the GUI and the CLI** (every platform ships both):

**GUI** — double-click the executable (`syncthing-manager.exe` on Windows) → a graphical wizard opens. From a terminal, run `syncthing-manager gui` to open it.

**CLI** — run it with a command in a terminal on any platform; add `--help` to list every command.

### Agents for offline devices

Every build embeds the offline-device agents for **all supported platforms and architectures**, so the app can generate an agent for any device in your cluster (`syncthing-manager generate-agent`, or from the GUI). You don't need to download anything extra for that.

### Building for an unsupported platform

Don't see your platform or architecture above? Build the app yourself with the script for your OS — it produces the binary and the agent for that machine.

Run:
```bash
build/build_linux.sh      # Linux
build/build_windows.bat   # Windows
build/build_macos.sh      # macOS
```

A self-build only embeds the agent for **its own** architecture. If you want that build to also generate agents for the **other** devices in your cluster, download the `syncthing-manager-agent-template-*` files from the assets below and drop them into `dist/` before running the build script (the build embeds whatever templates are present). That's the only reason those template files are published — they can't be run on their own, only embedded in (or placed next to) the app.

### Verify your download (optional)

`SHA256SUMS.txt` lists the SHA-256 hash of every uploaded file. Download it into the same folder as your archive(s) and run the check from that folder. If you don't need to verify every file, add `--ignore-missing` to the command:

**Linux:**
```bash
sha256sum -c SHA256SUMS.txt
```

**macOS:**
```bash
shasum -a 256 -c SHA256SUMS.txt
```

**Windows** (PowerShell) — hash your file and compare it with its line in `SHA256SUMS.txt`:
```powershell
(Get-FileHash syncthing-manager-windows.zip -Algorithm SHA256).Hash
```

<br>

The app is available in English and Spanish, automatically matching your system's language.
