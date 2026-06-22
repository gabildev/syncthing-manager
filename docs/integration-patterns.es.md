# Patrones de integración

> 🌐 [English](integration-patterns.md) · **Español**

Patrones de ingeniería de `syncthing-manager` que se transfieren a cualquier herramienta que tenga
que *configurar una flota de máquinas*, sea con Syncthing o no. Cada uno va con el sitio donde vive
en el código para que puedas llevártelo.

## 1. Alcanzar un dispositivo de cinco formas, por orden de prioridad

Un nodo no siempre es alcanzable de la misma manera, así que el motor prueba los canales en orden y
el resto del código está escrito contra un único `DeviceInfo` sin importar cuál ganó
(`renamer.py: rename_on_device`):

1. **API REST directa** — la propia API de Syncthing del dispositivo (local, o un par cuya GUI esté
   enlazada a la LAN). La más rápida y rica.
2. **SSH** (`ssh_ops.py`, paramiko) — para Linux/macOS/NAS. Proxyeamos las llamadas de API
   ejecutando `curl` contra la API de *localhost* del dispositivo por la sesión SSH, y editamos
   `config.xml` cuando hace falta.
3. **WinRM** (`winrm_ops.py`, pywinrm) — el equivalente de Windows. **Windows es un objetivo de
   primera clase**, no algo de segunda. Un host Windows se alcanza por WinRM, O por **SSH** cuando
   corre OpenSSH: `WindowsSSHClient` ejecuta las *mismas* operaciones PowerShell por el canal SSH
   (el `mv`/`rm`/`test` POSIX de la vía SSH fallaría en un shell cmd.exe/PowerShell). Ambos
   transportes Windows comparten una superficie de operaciones `_PowerShellOps`, así que quien los
   llama los trata igual.
4. **Exploración pasiva** — para un dispositivo offline: seguir vigilando y aplicar el cambio en el
   instante en que reconecte a un nodo que controlamos. Solo label/ruta/ID (la topología sigue
   siendo interactiva).
5. **Agente** — un binario autocontenido que copias a un dispositivo *sin* canal remoto; aplica el
   cambio localmente y reporta de vuelta.

Regla de diseño: **degradar, no fallar.** Si no se puede renombrar el disco (remoto solo-API),
cambia solo la etiqueta y conserva la ruta antigua en vez de dejar la carpeta rota.

**Ajustes de seguridad** (Ajustes; ambos desactivados por defecto para no cambiar setups
existentes):
- `prefer_secure_channel` — para dispositivos no locales alcanzables por SSH/WinRM, enruta las
  llamadas de API de Syncthing por ese canal cifrado (curl contra el localhost del dispositivo) en
  vez de pegar a su API directamente, para que la `X-API-Key` nunca cruce la red. Implementado
  degradando un flag `has_direct_api` en el punto de elección de canal (`renamer._prefer_remote_shell`).
- `ssh_strict_host_keys` — cambia la `AutoAddPolicy` de paramiko (TOFU) por `RejectPolicy`,
  rechazando hosts que no estén ya en `known_hosts` (cierra la ventana de MITM del primer conexión).
- `winrm_strict_cert` — valida el certificado TLS del servidor para WinRM-sobre-HTTPS (desactivado
  por defecto: los certificados autofirmados son comunes en máquinas Windows internas, y el HTTP
  plano/5985 va cifrado a nivel de mensaje NTLM de todos modos, así que no hay exposición en claro
  que proteger).

**Mantén la API key fuera del argv remoto.** Cuando una llamada de API se proxyea por un canal de
shell, la key se pasa por **stdin**, nunca por la línea de comandos, para que no se pueda leer de la
lista de procesos del remoto (`ps` / `/proc/*/cmdline` / `Win32_Process.CommandLine`): `curl -K -`
para la vía SSH POSIX, y `powershell -Command -` (un bootstrap base64 ASCII, nunca `-EncodedCommand`)
para ambos transportes Windows (WinRM y PowerShell-sobre-SSH). El bootstrap además fuerza UTF-8 de
entrada/salida para que rutas y etiquetas no-ASCII sobrevivan al codepage de la consola remota.

## 2. Descubrimiento + expansión por hub

`discovery.py` lanza las sondas de dispositivos **en paralelo** (API/SSH/WinRM a la vez) y las
fusiona. Dos ideas que vale la pena robar:

- **Expansión por hub**: la pertenencia completa de una carpeta no está en la config de ningún nodo
  por sí solo — cada nodo solo lista *sus* pares. Así que tras sondear los dispositivos conocidos,
  consulta a un hub alcanzable (p. ej. una Pi siempre encendida) por *su* lista de pares e incorpora
  dispositivos que de otro modo nunca verías.
- **Relleno de direcciones**: la dirección de la conexión activa suele ser IPv6 link-local. Cruza
  `/rest/system/discovery` y `/rest/stats/device` para recuperar una IPv4 marcable.
- **Fusión incremental al re-descubrir**: re-ejecutar el descubrimiento fusiona por `device_id` y
  **preserva las credenciales introducidas a mano** — nunca borres las claves SSH/contraseñas que
  el usuario tecleó solo porque un dispositivo se quedó offline un momento.
- **Resolución de nombres entre nodos**: el nombre amigable de un par no es global — cada nodo
  guarda el suyo, y un par introducido/offline a menudo está sin nombrar (un device id pelado).
  Resuelve la etiqueta por **autoridad** (`topology._resolve_name_map`): el config del nodo LOCAL
  gana en un conflicto; si no, se usa un nombre descubierto, conocido por el hub, o auto-anunciado;
  el short-id es el último recurso. Un nodo mostrado *solo* por los `folder_peers` de un hub (sin
  `DeviceInfo` propio) toma su nombre directamente del hub, así que nunca se dibuja como un id crudo.

## 3. Binarios de agente auto-extensibles

El agente para dispositivos offline (`generate.py`, `agent.py`) es un truco elegante para enviar
configuración como un ejecutable:

- Se produce una **plantilla** pre-compilada una vez por SO (`build/agent_*.spec`, onefile).
- Para "generar un agente" **añades** un blob de config a los bytes de la plantilla, delimitado por
  centinelas fijos `MARKER_START`/`MARKER_END`: `plantilla || MARKER_START || json || MARKER_END`.
  En ejecución, el agente lee su propio archivo, encuentra los marcadores y carga el JSON final.
- La generación **nunca ejecuta** la plantilla — solo concatena bytes. Por eso una máquina
  **Windows** puede producir un agente **Linux** y viceversa, mientras esté presente la plantilla
  del otro SO. Las plantillas van **embebidas** en la app principal (PyInstaller `--add-data`,
  extraídas de `sys._MEIPASS` bajo demanda), así que un binario genera agentes para todos los SO
  (cross-OS; ver el workflow de CI que embebe las plantillas en cada build).
- **La arquitectura importa en Linux/macOS** — no hay ejecución cross-arch dentro del SO en la
  que apoyarse, así que la plantilla se compila **por (SO, arch)**: `…-template-linux-amd64`/`-arm64`,
  `…-template-macos-amd64`/`-arm64` (Windows lleva un único `.exe` x64 que emula en Windows-ARM).
  La app las embebe todas y elige la que corresponde a la arch de CPU detectada (o elegida) de cada
  dispositivo. PyInstaller no puede cross-compilar un binario nativo, así que la plantilla de cada
  arch debe compilarse **en** esa arch — el CI usa runners nativos arm64 (Linux) e Intel/Apple
  Silicon (macOS). La arch del dispositivo se lee de `/rest/system/version` (`arch`) o SSH `uname -m`.
- El agente **verifica la identidad** antes de actuar: compara el `myID` local
  (`/rest/system/status`) contra el device ID grabado en su config, así que un agente soltado en la
  máquina equivocada se niega a ejecutarse.

## 4. Cifrado {#encryption}

Tanto las credenciales guardadas (`credentials.py`) como la config embebida del agente
(`generate.py`) usan el **mismo esquema**, así que solo hay una cosa que razonar:

- **Fernet** (AES-128-CBC + HMAC) con una clave derivada por **PBKDF2-HMAC-SHA256, 480.000
  iteraciones**, sobre un salt aleatorio de 16 bytes guardado junto al texto cifrado.
- La passphrase nunca se guarda. Las credenciales se cifran solo cuando hay una contraseña maestra;
  si no, están en texto plano en un archivo local de tipo `0600`.
- El payload del agente (API key de Syncthing, etc.) va cifrado `encrypted-v1` con este esquema para
  que un archivo de agente generado no sea una key en texto plano en disco durante el transporte.

## 5. La topología como modelo de grafo puro

`topology.py` es **libre de tkinter** a propósito: un modelo puro de nodos/aristas/roles que renderan
tanto el lienzo de la GUI como la CLI. Mantener el modelo libre de UI te permite:
- testearlo headless (`tests/test_topology*.py`),
- calcular un **diff** (`renamer.compute_topology_diff`) entre el grafo original y el editado y
  aplicar solo el delta por dispositivo,
- serializarlo/snapshotearlo a disco (para deshacer y aplicación pasiva).

Lección general: **separa el modelo de dominio tanto de la UI como del transporte.** El cliente
REST, el modelo de grafo y la GUI nunca importan las preocupaciones unos de otros.

## 6. Arranque rápido de la GUI: imports perezosos + onedir

Dos victorias independientes, ambas sobre no pagar por lo que aún no usas:

- **Imports perezosos**: `requests`/`urllib3` (~50 ms), `paramiko`, `cryptography` se importan
  *dentro* de las funciones que los necesitan, no al inicio del módulo. El arranque en frío de la
  GUI bajó de ~300 ms a ~150 ms. El import se memoiza (`_load_requests`).
- **onedir, no onefile**: el `onefile` de PyInstaller se auto-extrae un archivo de ~30 MB a un dir
  temporal en **cada** arranque — el coste de arranque dominante. `onedir` envía una carpeta cuyo
  binario carga sus librerías in situ. Distribuimos esa carpeta comprimida (zip/tar); el usuario la
  extrae una vez.

## 7. Directorio de datos portable y descubrible

`config.py` resuelve el directorio de datos por orden de prioridad (junto al ejecutable para una
instalación **portable** → un archivo puntero → el `%APPDATA%`/`~/.config` estándar del SO), y solo
recurre a una ubicación escribible como último recurso. Los ajustes, las credenciales por-carpeta y
los snapshots de topología viven todos ahí. Lección: haz que "portable en un USB" e "instalado
por-usuario" sean el *mismo* camino de código, decidido en ejecución por lo que sea escribible.

## 8. i18n sin framework

`i18n.py` usa la **cadena fuente en español como clave de traducción** y una tabla plana
`translations_en.py`, más un fino shim de tkinter que auto-traduce el `text`/títulos de los widgets.
Sin toolchain de `.po`. Compromiso: simple y sin dependencias, pero las claves cambian cuando
reformulas las cadenas fuente. Bien para una app de dos idiomas; reconsidéralo para muchas locales.

La cobertura la garantiza un **test AST** (`tests/test_i18n.py`): recorre el paquete buscando cada
llamada de cara al usuario — `t()`, `text=`/`label=`/messagebox de tkinter, y de la CLI
`typer.prompt/confirm`, `console.print`, `getpass`, `add_column`, `help=` — y falla si algún
literal español no tiene entrada en inglés. Guards complementarios cubren lo que el escaneo de
literales no ve — una cadena española pasada *sin envolver* a un sumidero que el shim no traduce
(escritores de widgets Text, `Combobox.set`) y la deriva de placeholders clave↔valor. Así toda la
pila — GUI, CLI, el agente para equipos offline y el backend (renamer/discovery/validation/topology/…)
— sigue 100% bilingüe sin que nadie tenga que acordarse de traducir cada cadena nueva.
