<p align="center"><img src="https://raw.githubusercontent.com/gabildev/syncthing-manager/main/assets/banner.png" alt="syncthing-manager" width="360"></p>

<p align="center"><b>🌐 English</b> · <b>Español</b></p>

<details open>
<summary><h3>English</h3></summary>

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

</details>

<details>
<summary><h3>Español</h3></summary>

### Descargas

<div align="center">

| Archivo | Plataforma |
|---|---|
| `syncthing-manager-windows.zip` | Windows (x86-64) |
| `syncthing-manager-linux-amd64.tar.gz` | Linux (x86-64, incl. WSL) |
| `syncthing-manager-linux-arm64.tar.gz` | Linux (ARM64 — Raspberry Pi de 64 bits, etc.) |
| `syncthing-manager-macos-amd64.tar.gz` | macOS (Intel · x86-64) |
| `syncthing-manager-macos-arm64.tar.gz` | macOS (Apple Silicon · M1/M2/M3…) |

</div>

<br>

Es una build **one-dir** (arranque rápido — no se desempaqueta nada al iniciar): extrae el archivo y obtienes una carpeta `syncthing-manager/` — mantén sus ficheros juntos.

### Inicio rápido

El ejecutable dentro de esa carpeta es **a la vez la GUI y la CLI** (todas las plataformas incluyen ambas):

**GUI** — haz doble clic en el ejecutable (`syncthing-manager.exe` en Windows) → se abre un asistente gráfico. Desde una terminal, ejecuta `syncthing-manager gui` para abrirlo.

**CLI** — ejecútalo con un comando en una terminal en cualquier plataforma; añade `--help` para listar todos los comandos.

### Agentes para dispositivos offline

Cada build embebe los agentes para dispositivos offline de **todas las plataformas y arquitecturas soportadas**, así que la app puede generar un agente para cualquier dispositivo de tu clúster (`syncthing-manager generate-agent`, o desde la GUI). No necesitas descargar nada extra para eso.

### Compilar para una plataforma no soportada

¿No ves tu plataforma o arquitectura arriba? Compila la app tú mismo con el script de tu SO — produce el binario y el agente para esa máquina.

Ejecuta:
```bash
build/build_linux.sh      # Linux
build/build_windows.bat   # Windows
build/build_macos.sh      # macOS
```

Una compilación propia solo embebe el agente para **su propia** arquitectura. Si quieres que esa build también genere agentes para los **otros** dispositivos de tu clúster, descarga los ficheros `syncthing-manager-agent-template-*` de los assets de abajo y colócalos en `dist/` antes de ejecutar el script de compilación (la build embebe las plantillas que estén presentes). Esa es la única razón por la que se publican esos ficheros de plantilla — no se pueden ejecutar por sí solos, solo embeber en (o colocar junto a) la app.

### Verifica tu descarga (opcional)

`SHA256SUMS.txt` lista el hash SHA-256 de cada fichero subido. Descárgalo en la misma carpeta que tu(s) archivo(s) y ejecuta la comprobación desde esa carpeta. Si no necesitas verificar todos los ficheros, añade `--ignore-missing` al comando:

**Linux:**
```bash
sha256sum -c SHA256SUMS.txt
```

**macOS:**
```bash
shasum -a 256 -c SHA256SUMS.txt
```

**Windows** (PowerShell) — calcula el hash de tu fichero y compáralo con su línea en `SHA256SUMS.txt`:
```powershell
(Get-FileHash syncthing-manager-windows.zip -Algorithm SHA256).Hash
```

<br>

La app está disponible en inglés y español, ajustándose automáticamente al idioma de tu sistema.

</details>
