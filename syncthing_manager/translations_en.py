"""English catalog (source language is Spanish).

Keys are the exact Spanish source strings. Only COMPLETE user-facing strings are listed —
the GUI shim and CLI `t()` calls translate these. Concatenated fragments and interpolated
f-string results are not keyed here (they degrade gracefully to Spanish); the most visible
dynamic strings are migrated to `t("…{x}…").format()` at their call sites over time.
"""
from __future__ import annotations

EN: dict[str, str] = {
    # ── CLI: app + command help ───────────────────────────────────────────────
    "Mostrar logs de depuración (DEBUG)": "Show debug (DEBUG) logs",
    "Idioma de la interfaz: «es» o «en» (por defecto, el del sistema).":
        "Interface language: 'es' or 'en' (defaults to the system language).",
    "Abre la interfaz gráfica (GUI).":
        "Open the graphical interface (GUI).",
    "Descubre dispositivos compartiendo una carpeta. No modifica nada.":
        "Discover devices sharing a folder. Changes nothing.",
    "Lista las carpetas del nodo Syncthing local.":
        "List the folders on the local Syncthing node.",
    "Renombra una carpeta Syncthing en todos los dispositivos.":
        "Rename a Syncthing folder across all devices.",
    "Muestra la topología real de la carpeta: dispositivos, roles, enlaces e inconsistencias.":
        "Show the folder's real topology: devices, roles, links and inconsistencies.",
    "Revierte el último rename (label, ruta en disco y, si lo hubo, ID de carpeta).":
        "Revert the last rename (label, on-disk path, and folder ID if it changed).",
    "Genera un ejecutable de agente para un dispositivo sin SSH/WinRM.":
        "Generate an agent executable for a device without SSH/WinRM.",

    # ── App chrome / navigation ───────────────────────────────────────────────
    "Conexión": "Connection",
    "Carpeta": "Folder",
    "Dispositivos": "Devices",
    "Nombres": "Names",
    "Topología": "Topology",
    "Ejecutar": "Run",
    "Configuración": "Settings",
    "Conexión a Syncthing": "Syncthing connection",
    "Ruta local": "Local path",
    "Nombre": "Name",
    "Ruta en disco": "On-disk path",
    "SO": "OS",
    "Siguiente →": "Next →",
    "← Atrás": "← Back",
    "Conectar →": "Connect →",
    "Aplicar →": "Apply →",
    "Aceptar": "OK",
    "Cancelar": "Cancel",
    "Cerrar": "Close",
    "Cerrar ⚠": "Close ⚠",
    "Salir": "Exit",
    "Guardar": "Save",
    "Añadir": "Add",
    "Probar": "Test",
    "Probar conexión": "Test connection",
    "Error": "Error",
    "Selección": "Selection",
    "Omitir todos": "Skip all",
    "Todos": "All",
    "Todos:": "All:",
    "sí": "yes",
    "no": "no",
    "error": "error",

    # ── Connection page ───────────────────────────────────────────────────────
    "Descubriendo dispositivos...": "Discovering devices...",
    "Comprobando la configuración actual de los equipos…":
        "Checking the current configuration of the devices…",
    "Dry Run — simulando cambios (nada se modificará)":
        "Dry Run — simulating changes (nothing will be modified)",
    "Seleccionar carpeta": "Select folder",
    "Seleccionar nueva carpeta": "Select another folder",
    "Selecciona una carpeta de la lista.": "Select a folder from the list.",
    "Error cargando carpetas: ": "Error loading folders: ",
    "No se pudo conectar": "Could not connect",
    "Sin conexión": "No connection",
    "✓  Syncthing en ejecución — introduce la API Key.":
        "✓  Syncthing running — enter the API key.",

    # ── Devices page ──────────────────────────────────────────────────────────
    "Nombre del dispositivo": "Device name",
    "Nombre actual": "Current name",
    "Nombre nuevo": "New name",
    "✏  Editar credenciales": "✏  Edit credentials",
    "Editar credenciales": "Edit credentials",
    "💾  Guardar credenciales": "💾  Save credentials",
    "Sincronizar nombres de dispositivos": "Sync device names",
    "Dispositivos sin acceso remoto": "Devices without remote access",
    "Ruta actual:": "Current path:",
    "Sin dispositivos": "No devices",
    "No hay dispositivos alcanzables.": "No reachable devices.",
    "Conectando con cada dispositivo…": "Connecting to each device…",
    "Conectando vía SSH/WinRM...": "Connecting via SSH/WinRM...",
    "sin SSH": "no SSH",
    "✗ error": "✗ error",
    "✗ sin credenciales": "✗ no credentials",
    "Error al guardar: ": "Error saving: ",
    "Con problemas de conexión:": "With connection problems:",
    "URL de la API:": "API URL:",
    "Ruta de carpeta:": "Folder path:",
    "Contraseña SSH:": "SSH password:",
    "  Contraseña SSH:": "  SSH password:",
    "Contraseña WinRM:": "WinRM password:",
    "(opcional — se autodescubre al reconectar)":
        "(optional — auto-discovered on reconnect)",
    "(se autodetecta al conectar)": "(auto-detected on connect)",
    "(se autodetecta al reconectar)": "(auto-detected on reconnect)",
    "SO sin detectar — asígnalo:": "OS not detected — set it:",
    "Editar credenciales: ": "Edit credentials: ",

    # ── Names page ────────────────────────────────────────────────────────────
    "Nuevo nombre": "New name",
    "Nombre (label):": "Name (label):",
    "Cambiar ruta / nombre:": "Change path / name:",
    "Renombrar ID de carpeta": "Rename folder ID",
    "Nuevo ID:": "New ID:",
    "Nueva ruta:": "New path:",
    "El label no puede estar vacío.": "The label cannot be empty.",
    "El nuevo ID no puede estar vacío.": "The new ID cannot be empty.",
    "El nuevo ID es igual al actual.": "The new ID is the same as the current one.",
    "El label contiene caracteres no válidos: ": "The label has invalid characters: ",
    "El nombre contiene caracteres no válidos: ": "The name has invalid characters: ",
    "(se creará la carpeta aquí)": "(the folder will be created here)",
    "(sin cambios — usa la ruta/nombre global)": "(unchanged — uses the global path/name)",
    "(ruta propia de este equipo)": "(this device's own path)",

    # ── Preview / execute ─────────────────────────────────────────────────────
    "Vista previa de cambios": "Change preview",
    "Resultados por dispositivo:": "Results per device:",
    "Cambios de topología:": "Topology changes:",
    "Sin cambios de rename — solo gestión de topología.":
        "No rename changes — topology management only.",
    "Sin cambios de rename — solo gestión de topología":
        "No rename changes — topology management only",
    "✓ Pre-vuelo OK — sin problemas detectados":
        "✓ Pre-flight OK — no problems detected",
    "Ejecutar de todas formas (ignorar errores del pre-vuelo)":
        "Run anyway (ignore pre-flight errors)",
    "Solo previsualizar (no aplicar)": "Preview only (don't apply)",
    "Error inesperado — ver log": "Unexpected error — see log",
    "Exploración pasiva": "Passive exploration",
    "Estado de exploración pasiva": "Passive exploration status",
    "🔎 Estado pasiva": "🔎 Passive status",
    "Guardar informe": "Save report",
    "📄 Guardar informe": "📄 Save report",
    "✓ Todas las carpetas reanudadas": "✓ All folders resumed",

    # ── Topology ──────────────────────────────────────────────────────────────
    "Cargando topología…": "Loading topology…",
    "Cargando configuración actual…": "Loading current configuration…",
    "Probando conexión…": "Testing connection…",
    "🔗 Añadir enlace": "🔗 Add link",
    "✋ Seleccionar/Mover": "✋ Select/Move",
    "✂ Borrar enlace": "✂ Delete link",
    "Seleccionar/Mover: clic en nodo o flecha = seleccionar · arrastrar = mover · doble clic / clic derecho = opciones.":
        "Select/Move: click a node or arrow = select · drag = move · double-click / right-click = options.",
    "Nuevo enlace": "New link",
    "Envía y recibe": "Send and receive",
    "Solo envía": "Send only",
    "Solo recibe": "Receive only",
    "↔ enviar y recibir": "↔ send and receive",
    "→ solo enviar": "→ send only",
    "← solo recibir": "← receive only",
    "(ninguno)": "(none)",
    "nuevo dispositivo (rol sin declarar)": "new device (role not declared)",
    "desconocido (offline)": "unknown (offline)",
    # ── Credential-editor field labels (Devices / Topology / Connection dialogs) ──
    "Usuario SSH:": "SSH user:",
    "Clave SSH:": "SSH key:",
    "Clave privada:": "Private key:",
    "Clave privada SSH:": "SSH private key:",
    "Puerto SSH:": "SSH port:",
    "Usuario WinRM:": "WinRM user:",
    "Puerto WinRM:": "WinRM port:",
    "(alternativa a clave)": "(alternative to the key)",
    "(usuario Windows)": "(Windows user)",
    "Clave SSH privada": "SSH private key",
    "Seleccionar clave privada SSH": "Select SSH private key",
    # ── Topology canvas / legend / link editing ──
    "conectado": "connected",
    "Rol desconocido": "Unknown role",
    "Enlace: ": "Link: ",
    "Enlace actualizado: ": "Link updated: ",
    "Enlace «{}» → «{}»": "Link «{}» → «{}»",
    "Enlace «{}» ↔ «{}»": "Link «{}» ↔ «{}»",
    "Editar enlace «{}» — «{}»…": "Edit link «{}» — «{}»…",
    "Enlace recordado de una sesión anterior: uno o ambos equipos están offline ahora. Se muestra para conservar la malla conocida; se verificará al reconectar (puede haber cambiado fuera de la app).":
        "Link remembered from a previous session: one or both devices are offline now. Shown to keep the known mesh; it will be re-checked on reconnect (it may have changed outside the app).",
    "Dirección desconocida: un extremo está offline. Si no tocas este enlace, no se modificará; si lo editas, el cambio se aplicará cuando el equipo reconecte (pasiva) o mediante agente.":
        "Unknown direction: one endpoint is offline. If you don't touch this link it won't change; if you edit it, the change applies when the device reconnects (passive) or via an agent.",
    "Dirección no realizable: ambos equipos quedan «envía/recibe» por sus otros enlaces, así que Syncthing lo hará bidireccional.":
        "Unachievable direction: both devices end up «send/receive» through their other links, so Syncthing will make it bidirectional.",
    "La ruta para este dispositivo no es válida:\n  • {}": "The path for this device is not valid:\n  • {}",
    "La nueva ruta para este dispositivo no es válida:\n  • {}": "The new path for this device is not valid:\n  • {}",
    "No se puede borrar en disco en: {}.\nAñade SSH/WinRM o usa la opción por equipo.":
        "Cannot delete on disk on: {}.\nAdd SSH/WinRM or use the per-device option.",
    "✓ «{}» configurado directamente.": "✓ «{}» configured directly.",
    # ── Run log / execute page ──
    "pausado": "paused",
    "reanudado": "resumed",
    "disco": "disk",
    "disco OK": "disk OK",
    "config": "config",
    "config OK": "config OK",
    "── Renombrando ID: «{}» → «{}» ──": "── Renaming ID: «{}» → «{}» ──",
    "  ⚠  {} — SYNC PAUSADA: {}": "  ⚠  {} — SYNC PAUSED: {}",
    "── Reanudando carpetas pausadas ──": "── Resuming paused folders ──",
    "sin acceso (offline/desconocido)": "no access (offline/unknown)",
    "[PREVISUALIZACIÓN — no se aplica nada]\n": "[PREVIEW — nothing is applied]\n",
    "✓  Agente {} generado: {}": "✓  {} agent generated: {}",
    "✓  Agente {} ({}): {}": "✓  {} agent ({}): {}",
    "ARM64 (Raspberry Pi y similares)": "ARM64 (Raspberry Pi and similar)",
    "x86-64 (amd64)": "x86-64 (amd64)",
    "Intel (x86-64)": "Intel (x86-64)",
    "Apple Silicon (M1/M2/M3…)": "Apple Silicon (M1/M2/M3…)",
    "✗  Error generando agente {}.": "✗  Error generating {} agent.",
    "⏳ Generando {}…": "⏳ Generating {}…",
    "Arquitectura": "Architecture",
    "Elige la arquitectura del dispositivo:": "Choose the device's architecture:",
    "arquitectura no seleccionada": "architecture not selected",
    "Falta especificar la arquitectura de {} dispositivo(s) {}.":
        "Architecture not specified for {} {} device(s).",
    "✗  Falló: {} — revisa el registro": "✗  Failed: {} — check the log",
    "  ✗  Error generando agente {}: {}": "  ✗  Error generating {} agent: {}",
    "⚠  {}: arquitectura(s) sin plantilla embebida: {} — esos dispositivos no quedan cubiertos (recompila con la plantilla)":
        "⚠  {}: architecture(s) without an embedded template: {} — those devices aren't covered (rebuild with the template)",
    "  ✓  Agente {} generado: {}  ({} disp.)": "  ✓  {} agent generated: {}  ({} dev.)",
    "\n→  Genera los agentes en el panel de abajo.": "\n→  Generate the agents in the panel below.",
    "\nℹ  Para generar agentes: compila las plantillas con PyInstaller.\n   python -m PyInstaller build/agent_windows.spec\n   python -m PyInstaller build/agent_linux.spec":
        "\nℹ  To generate agents: build the templates with PyInstaller.\n   python -m PyInstaller build/agent_windows.spec\n   python -m PyInstaller build/agent_linux.spec",
    # ── Names page summary ──
    "label + ruta": "label + path",
    "solo label": "label only",
    # ── Folder page ──
    "⚠ Ya existe una carpeta con ese ID — elige otro.": "⚠ A folder with that ID already exists — choose another.",
    # ── Offline-device agent (console + minimal GUI) ──
    "Contraseña del agente (cifrado): ": "Agent password (encrypted): ",
    "Contraseña incorrecta — reintenta: ": "Wrong password — try again: ",
    "Este agente está cifrado.\nIntroduce la contraseña:": "This agent is encrypted.\nEnter the password:",
    "Contraseña incorrecta.\nReintenta:": "Wrong password.\nTry again:",
    "Agente cifrado": "Encrypted agent",
    "No se pudo obtener la API Key de Syncthing.\nAsegúrate de que Syncthing está en ejecución.":
        "Could not get the Syncthing API key.\nMake sure Syncthing is running.",
    "✓ Ya migrado al ID «{}» (nada que hacer)": "✓ Already migrated to ID «{}» (nothing to do)",
    "[DRY RUN] crearía la carpeta «{}» (topología)": "[DRY RUN] would create folder «{}» (topology)",
    "✓ Carpeta creada (topología): ": "✓ Folder created (topology): ",
    "✗ Error creando carpeta: ": "✗ Error creating folder: ",
    "no se encontró la carpeta «{}» en este Syncthing (¿API Key correcta? ¿es el equipo adecuado?)":
        "folder «{}» not found in this Syncthing (correct API key? right device?)",
    "la carpeta no reporta ruta en disco": "the folder reports no on-disk path",
    "no se pudo consultar la API local: {}": "could not query the local API: {}",
    "✗ No se pudo determinar la ruta en disco de la carpeta, así que NO se renombró el directorio (solo se habría cambiado el label).\nMotivo: {}.\nComprueba que Syncthing está en ejecución en este equipo y que tiene la carpeta.":
        "✗ Could not determine the folder's on-disk path, so the directory was NOT renamed (only the label would have changed).\nReason: {}.\nMake sure Syncthing is running on this device and has the folder.",
    "ruta desconocida": "unknown path",
    "directorio renombrado": "directory renamed",
    "config actualizada": "config updated",
    "sync reanudada": "sync resumed",
    "ID → «{}»": "ID → «{}»",
    "sin resultado": "no result",
    "⚠ Rename aplicado, pero el cambio de ID falló": "⚠ Rename applied, but the ID change failed",
    ": {}\n(hecho: {})": ": {}\n(done: {})",
    "topología: ": "topology: ",
    "topología FALLÓ: ": "topology FAILED: ",
    "config carpeta: ": "folder config: ",
    "config carpeta FALLÓ: ": "folder config FAILED: ",
    "nombres: {} actualizado(s)": "names: {} updated",
    "nombres FALLÓ: {}": "names FAILED: {}",
    "⚠ Rename aplicado, pero falló un paso posterior": "⚠ Rename applied, but a later step failed",
    "✓ Completado": "✓ Completed",
    "⚠ Error — sync PAUSADA: {}\n\nReanuda manualmente desde la interfaz web de Syncthing.":
        "⚠ Error — sync PAUSED: {}\n\nResume it manually from the Syncthing web UI.",
    "Este es el agente de Syncthing Rename.\n\nEste ejecutable debe generarse con:\n  syncthing-manager generate-agent\n\nNo ejecutes este archivo directamente.":
        "This is the Syncthing Rename agent.\n\nThis executable must be generated with:\n  syncthing-manager generate-agent\n\nDo not run this file directly.",
    "Contraseña incorrecta o cancelada — no se pudo descifrar el agente.":
        "Wrong password or cancelled — could not decrypt the agent.",
    "El agente no contiene dispositivos configurados.": "The agent contains no configured devices.",
    "Syncthing Rename Agent — {} dispositivo(s): {}": "Syncthing Rename Agent — {} device(s): {}",
    "Identificando este equipo…": "Identifying this device…",
    "\n✗  Este dispositivo no está en la lista de pendientes.\n   IDs configurados:\n":
        "\n✗  This device is not in the pending list.\n   Configured IDs:\n",
    "Carpeta ya migrada al ID «{}»": "Folder already migrated to ID «{}»",
    "Carpeta ya configurada: label='{}', ruta={}": "Folder already configured: label='{}', path={}",
    "La ruta original ya no existe y la nueva sí: {}": "The original path no longer exists and the new one does: {}",
    "Agente para {} equipo(s)": "Agent for {} device(s)",
    "Este equipo no está en la lista configurada.\n\nEquipos en el agente:\n{}":
        "This device is not in the configured list.\n\nDevices in the agent:\n{}",
    "(autodetectar)": "(autodetect)",
    "Equipo identificado: {}": "Device identified: {}",
    "✓  Ya aplicado anteriormente.\n{}": "✓  Already applied previously.\n{}",
    "Operación pendiente para este equipo:": "Pending operation for this device:",
    "  Carpeta (label):  {}  →  {}": "  Folder (label):  {}  →  {}",
    "  Directorio:       {}  →  {}": "  Directory:        {}  →  {}",
    "  Carpeta : {}  →  {}": "  Folder : {}  →  {}",
    "  Disco   : {}  →  {}": "  Disk   : {}  →  {}",
    "Dispositivo: {}": "Device: {}",
    # ── Execute page title + agent-generation buttons ──
    "Ejecutando rename": "Running rename",
    "🪟 Generar Windows ({})": "🪟 Generate Windows ({})",
    "🐧 Generar Linux ({})": "🐧 Generate Linux ({})",
    "🪟 Generar Windows": "🪟 Generate Windows",
    "🐧 Generar Linux": "🐧 Generate Linux",
    # ── Transient status messages (_status positional / composed) ──
    "Conectando...": "Connecting...",
    "Forzando descubrimiento pasivo…": "Forcing passive discovery…",
    "Cargando carpetas...": "Loading folders...",
    "Pausando": "Pausing",
    "Reanudando": "Resuming",
    "URL API:": "API URL:",
    "revirtiendo": "reverting",
    "configurando": "configuring",
    "Desvinculando «{}»…": "Unlinking «{}»…",
    "🔄  Redescubriendo desde «{}»…": "🔄  Rediscovering from «{}»…",
    "Reintentando {}...": "Retrying {}...",
    "✓ {} — SSH/WinRM OK, redescubriendo…": "✓ {} — SSH/WinRM OK, rediscovering…",
    "⚠ {} inconsistencia(s) — ver": "⚠ {} inconsistency(ies) — view",
    "⚠ {} inconsistencia(s) — ver detalle.": "⚠ {} inconsistency(ies) — see details.",
    " (usa --passive para revertirlos al reconectar).": " (use --passive to revert them on reconnect).",
    "dispositivo-remoto": "remote-device",
    # ── macOS agent button + generic multi-arch agent strings ──
    "🍎 Generar macOS ({})": "🍎 Generate macOS ({})",
    "🍎 Generar macOS": "🍎 Generate macOS",
    "     ⚠ en la máquina {}: chmod +x antes de ejecutarlo": "     ⚠ on the {} machine: chmod +x before running it",
    "     ⚠ recuerda: chmod +x en la máquina {} antes de ejecutarlo": "     ⚠ remember: chmod +x on the {} machine before running it",
    "  ✓  Agente {} {} generado: {}  ({} disp.)": "  ✓  {} {} agent generated: {}  ({} dev.)",
    "  ✗  Error generando agente {} {}: {}": "  ✗  Error generating {} {} agent: {}",
    "\nℹ  Para generar agentes: compila las plantillas con PyInstaller.\n   python -m PyInstaller build/agent_windows.spec\n   python -m PyInstaller build/agent_linux.spec\n   python -m PyInstaller build/agent_macos.spec":
        "\nℹ  To generate agents: build the templates with PyInstaller.\n   python -m PyInstaller build/agent_windows.spec\n   python -m PyInstaller build/agent_linux.spec\n   python -m PyInstaller build/agent_macos.spec",
    "Editar enlace": "Edit link",
    "Quitar enlace": "Remove link",
    "Examinar carpetas del dispositivo": "Browse the device's folders",
    "Nuevo dispositivo": "New device",
    "➕ Nuevo dispositivo": "➕ New device",
    "✏ Editar seleccionado": "✏ Edit selected",
    "🔄 Estado": "🔄 Status",
    "(cargando dispositivos conocidos…)": "(loading known devices…)",
    "Revisión de topología": "Topology review",
    "✓ No se detectaron inconsistencias.": "✓ No inconsistencies detected.",
    "✓ Sin inconsistencias detectadas.": "✓ No inconsistencies detected.",
    # ── CLI cluster ops: unshare / delete-folder ────────────────────────────────
    "Deja de compartir una carpeta con un dispositivo en todo el clúster (no borra archivos).":
        "Stop sharing a folder with a device across the whole cluster (does not delete files).",
    "ID (o prefijo) o nombre del dispositivo que dejará de compartir la carpeta.":
        "ID (or prefix) or name of the device that will stop sharing the folder.",
    "Muestra qué se haría sin cambiar nada.": "Show what would be done without changing anything.",
    "Dispositivo no encontrado o ambiguo: {}": "Device not found or ambiguous: {}",
    "[red]Dispositivo no encontrado o ambiguo: {}[/red]":
        "[red]Device not found or ambiguous: {}[/red]",
    "Dispositivos conocidos de esta carpeta:": "Known devices for this folder:",
    "\nDejando de compartir «{}» con [bold]{}[/bold]…\n":
        "\nStopping sharing of «{}» with [bold]{}[/bold]…\n",
    "Dejar de compartir": "Stop sharing",
    "\n[yellow]⚠ {} equipo(s) no se pudieron actualizar (sin acceso). Añade credenciales y reintenta, o quítala en ese equipo.[/yellow]":
        "\n[yellow]⚠ {} device(s) could not be updated (no access). Add credentials and retry, or remove it on that device.[/yellow]",
    "BORRA una carpeta (de Syncthing y, salvo --keep-data, del disco) en el clúster. IRREVERSIBLE.":
        "DELETES a folder (from Syncthing and, unless --keep-data, from disk) across the cluster. IRREVERSIBLE.",
    "Borrar solo en este dispositivo (id/nombre). Por defecto: en todos los miembros.":
        "Delete only on this device (id/name). Default: on all members.",
    "Quitar de Syncthing pero NO borrar los archivos en disco.":
        "Remove from Syncthing but do NOT delete the files on disk.",
    "No pedir la confirmación tecleada (para scripts). Úsalo con cuidado.":
        "Skip the typed confirmation (for scripts). Use with care.",
    "Muestra qué se haría sin borrar nada.": "Show what would be done without deleting anything.",
    "el dispositivo «{}»": "the device «{}»",
    "TODOS los equipos del clúster ({} dispositivos)": "ALL devices in the cluster ({} devices)",
    "se quitará de Syncthing en {} (los archivos en disco NO se tocan)":
        "it will be removed from Syncthing on {} (files on disk are NOT touched)",
    "se quitará de Syncthing Y se borrarán los archivos en disco en {}":
        "it will be removed from Syncthing AND the files on disk will be deleted on {}",
    "\n[bold red]⚠  Vas a BORRAR la carpeta «{}»:[/bold red]":
        "\n[bold red]⚠  You are about to DELETE the folder «{}»:[/bold red]",
    "   [red]Esta acción es IRREVERSIBLE.[/red] (Se rechazan rutas protegidas del sistema y carpetas sin marcador .stfolder.)":
        "   [red]This action is IRREVERSIBLE.[/red] (Protected system paths and folders without a .stfolder marker are rejected.)",
    "Escribe el nombre de la carpeta «{}» para confirmar":
        "Type the folder name «{}» to confirm",
    "[red]El nombre no coincide — operación cancelada.[/red]":
        "[red]The name does not match — operation cancelled.[/red]",
    "Borrando...": "Deleting...",
    "Borrado de carpeta": "Folder deletion",
    "\n[yellow]⚠ {} equipo(s) no se completaron. Revisa el detalle de arriba.[/yellow]":
        "\n[yellow]⚠ {} device(s) did not complete. Check the detail above.[/yellow]",
    # ── CLI: create-folder ──────────────────────────────────────────────────────
    "Crea una carpeta NUEVA en este equipo y la registra en Syncthing (luego compártela con «share»).":
        "Create a NEW folder on this machine and register it in Syncthing (then share it with «share»).",
    "ID de la carpeta nueva (único en el clúster).": "ID of the new folder (unique across the cluster).",
    "Ruta en disco donde vivirá la carpeta (admite ~).": "On-disk path where the folder will live (supports ~).",
    "Etiqueta visible (por defecto, el ID).": "Visible label (defaults to the ID).",
    "Muestra qué se haría sin crear nada.": "Show what would be done without creating anything.",
    "[red]Se requieren --id y --path.[/red]": "[red]--id and --path are required.[/red]",
    "[red]No se pudo verificar si el ID ya existe (error de conexión). Reintenta.[/red]":
        "[red]Could not verify whether the ID already exists (connection error). Retry.[/red]",
    "[red]Ya existe una carpeta con el ID «{}».[/red]": "[red]A folder with ID «{}» already exists.[/red]",
    "[dim][dry-run][/dim] Se crearía la carpeta «{}» (id {}) en {}.":
        "[dim][dry-run][/dim] Would create folder «{}» (id {}) at {}.",
    "[green]✓ Carpeta «{}» creada en {}.[/green]": "[green]✓ Folder «{}» created at {}.[/green]",
    "[dim]Compártela con: syncthing-manager share -f {} -d <dispositivo>[/dim]":
        "[dim]Share it with: syncthing-manager share -f {} -d <device>[/dim]",
    # ── CLI: share ──────────────────────────────────────────────────────────────
    "Comparte una carpeta con un dispositivo (lo añade a la membresía en este equipo).":
        "Share a folder with a device (adds it to the membership on this machine).",
    "ID (o prefijo/nombre si ya es conocido) del dispositivo con el que compartir.":
        "ID (or prefix/name if already known) of the device to share with.",
    "Nombre para un dispositivo nuevo (por defecto, el inicio de su ID).":
        "Name for a new device (defaults to the start of its ID).",
    "Anclar el enlace a este miembro alcanzable en vez de a este equipo.":
        "Anchor the link to this reachable member instead of this machine.",
    "[red]No se pudo validar el ID del dispositivo (error de conexión). Reintenta.[/red]":
        "[red]Could not validate the device ID (connection error). Retry.[/red]",
    "[red]ID de dispositivo no válido: {}[/red]": "[red]Invalid device ID: {}[/red]",
    "[red]Miembro ancla no encontrado o ambiguo: {}[/red]":
        "[red]Anchor member not found or ambiguous: {}[/red]",
    "[red]El ancla no comparte «{}» (no es miembro). Usa --with un miembro alcanzable.[/red]":
        "[red]The anchor does not share «{}» (not a member). Use --with a reachable member.[/red]",
    "[red]El dispositivo destino y el ancla son el mismo.[/red]":
        "[red]The target device and the anchor are the same.[/red]",
    "[red]El ancla no es alcanzable ahora — no se puede aplicar el cambio.[/red]":
        "[red]The anchor is not reachable right now — the change cannot be applied.[/red]",
    "«{}» ya comparte «{}» con ese dispositivo — sin cambios.":
        "«{}» already shares «{}» with that device — no changes.",
    "Sin cambios que aplicar.": "No changes to apply.",
    "\nCompartiendo «{}» con [bold]{}[/bold] (ancla: {})…\n":
        "\nSharing «{}» with [bold]{}[/bold] (anchor: {})…\n",
    "Compartir": "Share",
    "[dim]El dispositivo recibirá la oferta de la carpeta al conectarse (o configúralo con el agente / la exploración pasiva).[/dim]":
        "[dim]The device will receive the folder offer when it connects (or configure it via the agent / passive exploration).[/dim]",
    "Dispositivo eliminado de la topología.": "Device removed from the topology.",
    "Dejar de compartir la carpeta": "Stop sharing the folder",
    "Desvincular dispositivo": "Unlink device",
    "Editar dispositivo…": "Edit device…",
    "🚫 Dejar de compartir / quitar de la topología…":
        "🚫 Stop sharing / remove from topology…",
    "🔗✖ Desvincular dispositivo del clúster…": "🔗✖ Unlink device from the cluster…",
    "Conectar / desconectar con": "Connect / disconnect with",
    "🔁 Invertir dirección": "🔁 Reverse direction",
    "🔓 Permitir editar este enlace": "🔓 Allow editing this link",
    "🔒 No editar este enlace": "🔒 Don't edit this link",
    "Enlace bloqueado: no se modificará al aplicar.":
        "Link locked: it won't be modified on apply.",
    "Ningún extremo envía: este enlace no sincroniza nada.":
        "Neither end sends: this link syncs nothing.",
    "Sin conexión con el Syncthing local.": "No connection to the local Syncthing.",
    "No se puede eliminar el equipo local.": "The local device cannot be removed.",
    "el otro nodo": "the other node",
    "Selecciona primero un dispositivo o un enlace (clic).":
        "Select a device or a link first (click).",
    "Ruta no válida": "Invalid path",
    "Nueva ruta no válida": "Invalid new path",
    "clic en ORIGEN y luego DESTINO": "click SOURCE then DESTINATION",
    "clic en los dos nodos (orden indiferente)": "click both nodes (any order)",
    "¿Qué tipo de enlace?": "What kind of link?",
    "Dirección del enlace": "Link direction",
    "Acceso (para configurarlo sin aceptar):": "Access (to configure it without accepting):",
    "🔌 Probar y conectar": "🔌 Test and connect",
    "Relación con el equipo (config local):": "Relationship with the device (local config):",
    "Introductor (presenta otros dispositivos del cluster)":
        "Introducer (presents other devices of the cluster)",
    "Auto-aceptar las carpetas que ofrezca este equipo":
        "Auto-accept the folders this device offers",
    "Pausar este dispositivo": "Pause this device",
    "Pausar esta carpeta en este equipo": "Pause this folder on this device",
    "Compresión:": "Compression:",
    "Configuración de la carpeta en este equipo:":
        "Folder configuration on this device:",
    "Muestra lo que ya hay configurado y lo hace editable.":
        "Shows what's already configured and makes it editable.",
    "Configurar vía:": "Configure via:",
    "Pasiva (al reconectar)": "Passive (on reconnect)",
    "(este equipo)": "(this device)",
    "Ruta:": "Path:",
    "Usar esta carpeta": "Use this folder",
    "Introducir nuevo dispositivo": "Enter a new device",
    "(elige para autocompletar…)": "(pick to autocomplete…)",
    "(no hay otros dispositivos conocidos)": "(no other known devices)",
    "Introduce el Device ID primero.": "Enter the Device ID first.",
    "Introduce credenciales (SSH/WinRM o API) para probar.":
        "Enter credentials (SSH/WinRM or API) to test.",
    "El nombre no puede estar vacío.": "The name cannot be empty.",
    "El Device ID no puede estar vacío.": "The Device ID cannot be empty.",
    "Device ID no válido.": "Invalid Device ID.",
    "Device ID sin validar": "Unvalidated Device ID",
    "Ese dispositivo ya está en la topología.": "That device is already in the topology.",
    "Estado actualizado: ": "Status updated: ",
    "No se pudo actualizar el estado.": "Could not update the status.",
    "✓ Conexión OK — se configurará directamente (sin aceptar).":
        "✓ Connection OK — it will be configured directly (without accepting).",

    # ── Undo ──────────────────────────────────────────────────────────────────
    "Deshacer — elegir qué revertir": "Undo — choose what to revert",
    "↶ Deshacer último rename": "↶ Undo last rename",
    "(sin cambios de rename)": "(no rename changes)",
    "No hay cambios que revertir.": "Nothing to revert.",
    "No has marcado nada para revertir.": "You haven't selected anything to revert.",
    "¿Qué quieres revertir?": "What do you want to revert?",
    "Lo no marcado se conserva tal cual.": "Unchecked items are kept as-is.",
    "Revertido (selección aplicada)": "Reverted (selection applied)",

    # ── Master password / credentials ─────────────────────────────────────────
    "Contraseña maestra": "Master password",
    "🔑  Contraseña maestra": "🔑  Master password",
    "Contraseña:": "Password:",
    "Contraseña maestra para cifrado": "Master password for encryption",
    "Contraseña maestra — cargar credenciales": "Master password — load credentials",
    "La contraseña no puede estar vacía.": "The password cannot be empty.",
    "Las contraseñas no coinciden.": "The passwords don't match.",
    "🔒 Contraseña de cifrado:": "🔒 Encryption password:",

    # ── Settings dialog ───────────────────────────────────────────────────────
    "Puertos por defecto:": "Default ports:",
    "Conéctate a Syncthing primero para comprobarlo.":
        "Connect to Syncthing first to check it.",
    "No se pudo leer la dirección de la API.": "Could not read the API address.",
    "Comprobar API-on-LAN (equipo local)": "Check API-on-LAN (local device)",
    "Carpeta de datos (credenciales y ajustes):": "Data folder (credentials and settings):",
    "Carpeta de datos": "Data folder",
    "Carpeta de datos: ": "Data folder: ",
    "Modo portable (junto al programa)": "Portable mode (next to the program)",
    "Portable (junto al programa)": "Portable (next to the program)",
    "Carpeta estándar / personalizada": "Standard / custom folder",
    "Carpeta personalizada…": "Custom folder…",
    "Estándar del sistema": "System standard",
    "Elegir carpeta de datos": "Choose data folder",
    "No se pudo mover: ": "Could not move: ",
    "Idioma": "Language",
    "Idioma:": "Language:",
    "Idioma (requiere reiniciar):": "Language (requires restart):",
    "Automático (idioma del sistema)": "Automatic (system language)",
    "Español": "Spanish",
    "Inglés": "English",
    "El idioma se aplicará al reiniciar la aplicación.":
        "The language will take effect when the app restarts.",
    "El idioma se aplica al reiniciar la aplicación. ¿Reiniciar ahora? "
    "(se perderá el progreso no guardado)":
        "The language takes effect when the app restarts. Restart now? "
        "(unsaved progress will be lost)",
    "Reinicia la aplicación para aplicar el idioma.":
        "Restart the application to apply the language.",

    # ── Misc / status ─────────────────────────────────────────────────────────
    "(sin IP)": "(no IP)",
    "sin IP": "no IP",
    "sin IP conocida": "no known IP",
    "Sin IP conocida (offline):": "No known IP (offline):",
    "(ruta autodetectada)": "(auto-detected path)",
    "Sin cambios pendientes.": "No pending changes.",
    "Error inesperado: ": "Unexpected error: ",
    "Error: ": "Error: ",
    "✗ Error: ": "✗ Error: ",
    "Puerto inválido — debe ser un número.": "Invalid port — must be a number.",
    "✗  Puerto inválido — debe ser un número.": "✗  Invalid port — must be a number.",
    "No se pudo listar: ": "Could not list: ",
    "Rescan debe ser un número (s).": "Rescan must be a number (s).",
    "Los límites deben ser números (KiB/s).": "Limits must be numbers (KiB/s).",
    "Ruta no válida: ": "Invalid path: ",
    "OK (acción manual)": "OK (manual action)",
    "ningún paso": "no steps",

    # ── Definitive delete (advanced) ──────────────────────────────────────────
    "🗑 Borrar la carpeta en TODO el clúster": "🗑 Delete the folder on the WHOLE cluster",
    "⚠ Borrar definitivamente la carpeta en este equipo (Syncthing + disco)…":
        "⚠ Permanently delete the folder on this device (Syncthing + disk)…",
    "⚠ Borrar definitivamente la carpeta… (requiere SSH/WinRM)":
        "⚠ Permanently delete the folder… (requires SSH/WinRM)",
    "🗑 Borrar definitivamente": "🗑 Delete permanently",
    "Borrar la carpeta definitivamente": "Delete the folder permanently",
    "Borrar la carpeta en TODO el clúster": "Delete the folder on the WHOLE cluster",
    "Borrar carpeta": "Delete folder",
    "Borrar en todo el clúster": "Delete on the whole cluster",
    "Ruta protegida": "Protected path",
    "Se borrará en disco:": "Will be deleted on disk:",
    "No se encontró el dispositivo.": "Device not found.",
    "Entiendo que esto borra los archivos en TODOS los equipos y es IRREVERSIBLE.":
        "I understand this deletes the files on ALL devices and is IRREVERSIBLE.",

    # ── Dynamic templates ({} = runtime values, filled with .format()) ────────
    "«{}» ⁄⁄ «{}»  (sin sincronización)": "«{}» ⁄⁄ «{}»  (no sync)",
    "Carpeta de datos: {}": "Data folder: {}",
    "{} dispositivo(s): {} OK": "{} device(s): {} OK",
    "Credenciales — {}": "Credentials — {}",
    "Se aplicará a {} dispositivo(s) accesible(s):":
        "Will be applied to {} reachable device(s):",
    "«{}» — «{}»  (dirección desconocida · offline)":
        "«{}» — «{}»  (unknown direction · offline)",
    "¿Dejar de compartir «{}» en ESTE equipo (local)?\n\n• Se ELIMINARÁ la carpeta de tu "
    "Syncthing: deja de sincronizarse aquí y desaparece de tu lista de carpetas.\n• Los demás "
    "equipos accesibles dejarán de sincronizarla contigo, pero seguirán sincronizándola entre "
    "ellos.\n• El nodo local saldrá de la topología de esta carpeta.\n\nEsta herramienta solo "
    "cambia la configuración de Syncthing; no ejecuta ningún borrado de archivos. Tus archivos "
    "en disco se conservan; haz una copia si no estás seguro.":
        "Stop sharing «{}» on THIS (local) device?\n\n• The folder will be REMOVED from your "
        "Syncthing: it stops syncing here and disappears from your folder list.\n• The other "
        "reachable devices will stop syncing it with you, but will keep syncing it among "
        "themselves.\n• The local node will leave this folder's topology.\n\nThis tool only "
        "changes Syncthing's configuration; it deletes no files. Your files on disk are kept; "
        "make a backup if you're unsure.",
    "¿Dejar de compartir «{}» con «{}» y quitarlo de la topología?\n\n• En «{}» se ELIMINARÁ "
    "la carpeta de Syncthing: deja de sincronizarse y desaparece de su lista de carpetas (si es "
    "accesible).\n• En los demás equipos accesibles se quitará a «{}» de esta carpeta.\n\nEsta "
    "herramienta solo cambia la configuración de Syncthing; no ejecuta ningún borrado de "
    "archivos. Por seguridad, haz una copia si no estás seguro de tener los datos a salvo.":
        "Stop sharing «{}» with «{}» and remove it from the topology?\n\n• On «{}» the folder "
        "will be REMOVED from Syncthing: it stops syncing and disappears from its folder list "
        "(if reachable).\n• On the other reachable devices, «{}» will be removed from this "
        "folder.\n\nThis tool only changes Syncthing's configuration; it deletes no files. To "
        "be safe, make a backup if you're unsure your data is safe.",
    "Dejando de compartir con «{}»…": "Stopping sharing with «{}»…",
    "Borrando «{}» en todo el clúster…": "Deleting «{}» on the whole cluster…",
    "Carpeta: {}  (id={})": "Folder: {}  (id={})",
    "Nueva ruta/nombre: {}": "New path/name: {}",
    "{} con problemas — selecciónalos para editar credenciales":
        "{} with problems — select them to edit credentials",
    "✓  {} nombre(s) actualizado(s) en {}/{} equipo(s)":
        "✓  {} name(s) updated on {}/{} device(s)",
    "Al reconectar — {} dispositivo(s):": "On reconnect — {} device(s):",
    "⚠ Sin gestionar ({}) — ni pasiva ni agente; habría que aceptarlos a mano:":
        "⚠ Unmanaged ({}) — neither passive nor agent; they'd need manual accepting:",
    "¿Desvincular «{}» de TODO el clúster?\n\n• Se quitará de la lista de dispositivos de cada "
    "equipo accesible, lo que deshace TODAS sus comparticiones (no solo esta carpeta).\n• Solo "
    "se rompe el emparejamiento: las carpetas siguen configuradas en cada equipo, simplemente "
    "dejan de sincronizarse con este dispositivo.\n\nEsta herramienta solo cambia la "
    "configuración de Syncthing; no ejecuta ningún borrado de archivos.":
        "Unlink «{}» from the WHOLE cluster?\n\n• It will be removed from each reachable "
        "device's device list, which undoes ALL of its shares (not just this folder).\n• Only "
        "the pairing is broken: the folders stay configured on each device, they simply stop "
        "syncing with this device.\n\nThis tool only changes Syncthing's configuration; it "
        "deletes no files.",
    "La ruta «{}» es del sistema; por seguridad no se borrará.":
        "The path «{}» is a system path; for safety it won't be deleted.",
    "Vas a BORRAR la carpeta «{}» en {}: se quitará de Syncthing Y se borrarán los archivos en "
    "disco. Es IRREVERSIBLE. (El resto de equipos no se tocan; usa la opción del clúster para "
    "eso.)":
        "You are about to DELETE the folder «{}» on {}: it will be removed from Syncthing AND "
        "the files on disk will be deleted. This is IRREVERSIBLE. (Other devices are not "
        "touched; use the cluster option for that.)",
    "Vas a BORRAR la carpeta «{}» en TODOS los equipos: se quitará de Syncthing Y se borrarán "
    "los archivos en disco en cada uno. IRREVERSIBLE.":
        "You are about to DELETE the folder «{}» on ALL devices: it will be removed from "
        "Syncthing AND the files on disk will be deleted on each one. IRREVERSIBLE.",
    "Carpeta: {}  →  {}": "Folder: {}  →  {}",
    "Procesando {} dispositivo(s) remotamente…": "Processing {} device(s) remotely…",
    "Plantilla {} no disponible": "Template {} not available",
    "El binario actual no lleva embebida la plantilla de agente {}.\n\nUna plantilla {} solo se "
    "compila EN {}. Para poder generar agentes {} desde aquí, tienes dos opciones:\n\n• Rápida "
    "(sin recompilar): deja el ejecutable de plantilla en una subcarpeta «{}» junto a este "
    "programa.\n\n• Permanente: recompila este binario con la plantilla {} presente — se "
    "sincroniza vía build/prebuilt/ y se embebe sola.":
        "This binary doesn't embed the {} agent template.\n\nA {} template is only built ON "
        "{}. To generate {} agents from here you have two options:\n\n• Quick (no rebuild): "
        "drop the template executable in a «{}» subfolder next to this program.\n\n• "
        "Permanent: rebuild this binary with the {} template present — it's synced via "
        "build/prebuilt/ and embedded automatically.",
    "ruta→«{}»": "path→«{}»",
    "── Reintentando {} dispositivo(s) ──": "── Retrying {} device(s) ──",
    "No se pudo mover: {}": "Could not move: {}",
    "{} carpeta(s) — selecciona una y pulsa Siguiente →":
        "{} folder(s) — select one and press Next →",
    "Dispositivos — {}": "Devices — {}",
    "Error al guardar: {}": "Error saving: {}",
    "Error al sincronizar: {}": "Sync error: {}",
    "No hay cambios de topología que revertir; la carpeta se conserva.":
        "No topology changes to revert; the folder is kept.",
    "⬚ rojo = credenciales SSH no válidas": "⬚ red = invalid SSH credentials",
    "Procesando {} dispositivo(s) remoto(s){}…": "Processing {} remote device(s){}…",
    " + este equipo": " + this device",
    "Comprobando acceso…": "Checking access…",
    "Comprobando el acceso remoto… espera a que termine.": "Checking remote access… wait for it to finish.",
    "Carpeta sin configurar": "Unconfigured folder",
    "Creaste «{}» pero no llegaste a configurarla (sin dispositivos ni sincronización). ¿Borrarla?\n\nSi la conservas, queda como una carpeta local en este equipo.":
        "You created «{}» but never configured it (no devices, no sync). Delete it?\n\nIf you keep it, it stays as a local folder on this device.",
    "«{}» ya estaba configurado — añadido a la topología de esta carpeta para compartírsela.":
        "«{}» was already configured — added to this folder's topology so you can share it.",
    "No se renombra nada en {} dispositivo(s) accesible(s), y no hay cambios de topología: no hay nada que aplicar.":
        "Nothing is renamed on {} reachable device(s), and there are no topology changes: nothing to apply.",
    "     ⚠ «{}» sin enlaces: se le creará la carpeta (cargada en Syncthing), pero quedará HUÉRFANA —no se comparte— hasta que la enlaces en la Topología.":
        "     ⚠ «{}» without links: the folder IS created on it (loaded into Syncthing) but stays ORPHANED —not shared— until you connect it in Topology.",
    "✗ cred. inválidas": "✗ invalid cred.",
    "Credenciales inválidas": "Invalid credentials",
    "Marcaste exploración pasiva para {}, pero sus credenciales SSH fueron rechazadas, así que la auto-configuración fallará hasta que las corrijas.\n\n¿Continuar igualmente?":
        "You marked passive exploration for {}, but their SSH credentials were rejected, so "
        "auto-configuration will fail until you fix them.\n\nContinue anyway?",
    "Quitar de la topología": "Remove from topology",
    "¿Quitar el dispositivo nuevo «{}» de la topología?\n\nAún no se ha aplicado en ningún equipo, así que solo se elimina de este diseño.":
        "Remove the new device «{}» from the topology?\n\nIt hasn't been applied to any device "
        "yet, so it's only removed from this design.",
    "Dispositivo nuevo «{}» quitado de la topología.": "New device «{}» removed from the topology.",
    "«{}»: credenciales SSH no válidas — el rename en disco fallará (corrígelas o usa el agente).":
        "«{}»: invalid SSH credentials — the on-disk rename will fail (fix them or use the agent).",
    "  ⚠  {} dispositivo(s) con cambios pendientes NO están en cola (ni pasiva ni agente): su config NO se aplicará. Vuelve atrás y actívalos si los quieres configurar.":
        "  ⚠  {} device(s) with pending changes are NOT queued (neither passive nor agent): their config will NOT be applied. Go back and enable them if you want them configured.",
    "  (sin acceso: solo se deja de compartir)": "  (no access: only stops sharing)",
    "Aplicar": "Apply",
    "Deshacer carpeta nueva": "Undo new folder",
    "Deshacer «{}» (carpeta nueva)": "Undo «{}» (new folder)",
    "Deshaciendo «{}»…": "Undoing «{}»…",
    "Marcar todos": "Select all",
    "se borrará el disco en {} de {} nodo(s)": "disk will be deleted on {} of {} node(s)",
    "«{}» revertida en {} equipo(s).{}\n\nVolviendo a la selección de carpeta.":
        "«{}» reverted on {} device(s).{}\n\nReturning to folder selection.",
    "¿Qué quieres hacer con la carpeta que creaste?":
        "What do you want to do with the folder you created?",
    "Revertir solo la topología (conservar la carpeta y los archivos)":
        "Revert only the topology (keep the folder and the files)",
    "Dejar de compartir la carpeta y CONSERVAR los archivos en disco":
        "Stop sharing the folder and KEEP the files on disk",
    "Dejar de compartir y BORRAR los archivos en disco (elige nodos)":
        "Stop sharing and DELETE the files on disk (choose nodes)",
    "\n⚠ OJO: en {} equipo(s) se quitó de Syncthing pero los archivos en disco NO se borraron "
    "({}). Bórralos a mano o revisa el acceso.":
        "\n⚠ NOTE: on {} device(s) it was removed from Syncthing but the on-disk files were NOT "
        "deleted ({}). Delete them by hand or check access.",
    "↩ Credenciales previas restauradas para este dispositivo.":
        "↩ Previous credentials restored for this device.",
    "  ·  {} offline pendiente(s) (se aplicarán al reconectar / por agente)":
        "  ·  {} offline pending (applied on reconnect / via agent)",
    "{} cambió su configuración de la carpeta desde que la editaste.\n\nSi continúas, TUS "
    "cambios se aplicarán ENCIMA de la suya (fusionados, sin borrar lo que no tocaste).\n\n• Sí "
    "= continuar y conservar tus cambios.\n• No = volver para revisarlo (puedes redescubrir "
    "para cargar su configuración actual).":
        "{} changed its folder configuration since you edited it.\n\nIf you continue, YOUR "
        "changes will be applied ON TOP of theirs (merged, without deleting what you didn't "
        "touch).\n\n• Yes = continue and keep your changes.\n• No = go back to review it (you "
        "can re-discover to load their current configuration).",
    "Carpeta (label):   «{}»   →   «{}»": "Folder (label):   «{}»   →   «{}»",
    "Carpeta (label):   «{}»   (sin cambios)": "Folder (label):   «{}»   (unchanged)",
    "Ruta / nombre:     {}": "Path / name:     {}",
    "ID de carpeta:     «{}»   →   «{}»": "Folder ID:     «{}»   →   «{}»",
    "  🔎 exploración pasiva:  {}": "  🔎 passive exploration:  {}",
    "  🧩 agente (ejecútalo en el equipo):  {}": "  🧩 agent (run it on the device):  {}",
    "  + nuevo dispositivo «{}»  (ruta: {})": "  + new device «{}»  (path: {})",
    "  ~ rol de {}:  {} → {}": "  ~ role of {}:  {} → {}",
    "Añadir enlace: {}.": "Add link: {}.",
    "\n{} con error: {}": "\n{} with error: {}",
    "«{}» borrada en {} equipo(s).{}\n\nVolviendo a la selección de carpeta.":
        "«{}» deleted on {} device(s).{}\n\nReturning to folder selection.",
    "Añadido «{}» — arrástralo sobre otro nodo para conectarlo":
        "Added «{}» — drag it onto another node to connect it",
    "Renombrar ID de carpeta: «{}» → «{}»": "Rename folder ID: «{}» → «{}»",
    "Ruta/nombre nuevo: {}": "New path/name: {}",
    "Verificando {} dispositivo(s) con credenciales…":
        "Checking {} device(s) with credentials…",
    "{} dispositivo(s) sin acceso → agente: {}": "{} device(s) without access → agent: {}",
    "  ↺  {} fallido(s) → se reintentarán solos al reconectar (pasiva); «Reintentar ahora» "
    "para forzarlo.":
        "  ↺  {} failed → they'll retry automatically on reconnect (passive); «Retry now» to "
        "force it.",
    "No se pudo guardar el informe:\n{}": "Could not save the report:\n{}",
    "Ruta / disco   → «{}»": "Path / disk   → «{}»",
    "ID de carpeta   → «{}»": "Folder ID   → «{}»",
    "  ⏳  {} dispositivo(s) pasivo(s) no revertidos ahora — se revertirán al reconectar "
    "(mantén la ventana abierta).":
        "  ⏳  {} passive device(s) not reverted now — they'll revert on reconnect (keep the "
        "window open).",
    "⟳  {} en línea ({}) — {}…": "⟳  {} online ({}) — {}…",
    "✓ API expuesta en LAN ({}) — los equipos pueden configurarse por IP:puerto directamente.":
        "✓ API exposed on the LAN ({}) — devices can be configured by IP:port directly.",
    "API solo local ({}). Para acceso directo por IP, en Syncthing pon la dirección de la GUI "
    "en 0.0.0.0:PUERTO; si no, se usará SSH/WinRM o el agente.":
        "API is local-only ({}). For direct IP access, set Syncthing's GUI address to "
        "0.0.0.0:PORT; otherwise SSH/WinRM or the agent will be used.",
    "🔄  Redescubriendo desde {} dispositivos…": "🔄  Re-discovering from {} devices…",
    "  … y {} más": "  … and {} more",
    "Editar credenciales: {}": "Edit credentials: {}",
    "✗  Sin conexión: {}": "✗  No connection: {}",
    "↳ {}: {} dispositivo(s) nuevo(s) descubierto(s)":
        "↳ {}: {} new device(s) discovered",
    "Marcaste exploración pasiva para {}, pero no tienen credenciales, así que no se podrán "
    "auto-configurar al reconectarse.\n\n¿Continuar igualmente?":
        "You marked passive exploration for {}, but they have no credentials, so they can't "
        "auto-configure on reconnect.\n\nContinue anyway?",
    "  • {}: (ruta autodetectada al ejecutar){}":
        "  • {}: (path auto-detected at run time){}",
    "⚠ No se pudo completar el pre-vuelo: {}": "⚠ Could not complete the pre-flight: {}",
    "«{}»: {} equipo(s) actualizados, pero {} sin acceso siguen compartiéndola ({}). Se "
    "reintentará solo al reconectar (pasiva); añade credenciales o quítala en ese equipo.":
        "«{}»: {} device(s) updated, but {} without access still share it ({}). It will retry "
        "on reconnect (passive); add credentials or remove it on that device.",
    "«{}»: desvinculado en {}, pero {} sin acceso aún lo tienen vinculado ({}). Añade "
    "credenciales y reintenta, o desvincúlalo en ese equipo.":
        "«{}»: unlinked on {}, but {} without access still have it linked ({}). Add "
        "credentials and retry, or unlink it on that device.",
    "«{}»: desvinculado en {}, {} con error ({}).":
        "«{}»: unlinked on {}, {} with error ({}).",
    "«{}» desvinculado del clúster ({} equipo/s).":
        "«{}» unlinked from the cluster ({} device(s)).",
    "Para confirmar, escribe el nombre de la carpeta:  «{}»":
        "To confirm, type the folder name:  «{}»",
    "No se pudo borrar en «{}»: {}": "Could not delete on «{}»: {}",
    "No se pudo dejar de compartir con «{}»: {}": "Could not stop sharing with «{}»: {}",
    "No se pudo desvincular «{}»: {}": "Could not unlink «{}»: {}",
    "No se pudo cargar la topología: {}": "Could not load the topology: {}",
    "{} (ruta protegida)": "{} (protected path)",
    "  🔒  {} enlace(s) bloqueado(s) — no se modifican.":
        "  🔒  {} locked link(s) — not modified.",
    "  •  {} — aún sin la carpeta aquí; se creará al aplicar la topología":
        "  •  {} — folder not here yet; it will be created when applying the topology",
    "  ⏳  {} dispositivo(s) sin configurar aún (offline/nuevos sin acceso): se editará su "
    "config al reconectar (pasiva) o con agente — sin aceptar nada.":
        "  ⏳  {} device(s) not configured yet (offline/new without access): their config will "
        "be edited on reconnect (passive) or via agent — no accepting needed.",
    "  ⏳  {} con config de carpeta pendiente (offline): se aplicará al reconectar (pasiva) o "
    "con agente.":
        "  ⏳  {} with pending folder config (offline): applied on reconnect (passive) or via "
        "agent.",
    "⚠  {} dispositivo(s) con sync PAUSADA — intervención manual necesaria":
        "⚠  {} device(s) with sync PAUSED — manual intervention needed",
    "  ✗  Error inesperado: {}": "  ✗  Unexpected error: {}",
    "🧩  Agente local — {} dispositivo(s) sin acceso remoto":
        "🧩  Local agent — {} device(s) without remote access",
    "No hay dispositivos asignados a {}.": "No devices assigned to {}.",
    "ERROR — {}": "ERROR — {}",
    ", ID falló: {}": ", ID failed: {}",
    "  ✓  {} {} por exploración pasiva{}{}": "  ✓  {} {} via passive exploration{}{}",
    "✓  Syncthing detectado y en ejecución ({})": "✓  Syncthing detected and running ({})",
    "«{}» se ha quitado de este equipo y ya no la comparte ningún otro equipo.\n\nVolviendo a "
    "la selección de carpeta.":
        "«{}» has been removed from this device and no other device shares it anymore.\n\n"
        "Returning to folder selection.",
    "«{}» quitada de este equipo; estado vía «{}» (remoto).":
        "«{}» removed from this device; status via «{}» (remote).",
    "«{}» se ha quitado de este equipo (los archivos en disco se conservan).\n\nLa siguen "
    "compartiendo: {}.\n\nEl estado se actualiza a través de «{}», que sigue siendo un equipo "
    "remoto (no se convierte en local). Puedes seguir gestionando estos equipos desde aquí.":
        "«{}» has been removed from this device (the files on disk are kept).\n\nStill shared "
        "by: {}.\n\nStatus now refreshes through «{}», which is still a remote device (it does "
        "not become local). You can keep managing these devices from here.",
    "«{}» se ha quitado de este equipo. La siguen compartiendo: {}, pero ninguno es accesible "
    "directamente ahora.\n\n¿Añadir credenciales a uno para seguir gestionando y refrescando el "
    "estado desde aquí?":
        "«{}» has been removed from this device. Still shared by: {}, but none is directly "
        "reachable now.\n\nAdd credentials to one to keep managing and refreshing status from "
        "here?",
    "{} carpeta(s) — doble clic para entrar": "{} folder(s) — double-click to enter",
    "  ⚠  {} — {} (acción manual necesaria)": "  ⚠  {} — {} (manual action needed)",
    "{}Completado: {}/{} dispositivos OK": "{}Done: {}/{} devices OK",
    "Completado con errores: {}/{} OK": "Completed with errors: {}/{} OK",
    "✗  Error generando agente {}: {}": "✗  Error generating agent {}: {}",
    "  {}  {} (config carpeta) — {}": "  {}  {} (folder config) — {}",
    "Error cargando carpetas: {}": "Error loading folders: {}",
    "  ✓  {}: {} nombre(s) propagado(s)": "  ✓  {}: {} name(s) propagated",
    "  —  {}: sin cambios": "  —  {}: no changes",
    "{} dispositivo(s) nuevo(s)": "{} new device(s)",
    "«{}» ya no comparte ({})": "«{}» no longer shares ({})",
    "«{}»: {} equipo(s) OK, {} con error ({}).":
        "«{}»: {} device(s) OK, {} with error ({}).",
    "«{}» ya no comparte la carpeta ({} equipo/s actualizados).":
        "«{}» no longer shares the folder ({} device(s) updated).",
    "«{}» quitada de este equipo; el resto la sigue compartiendo.":
        "«{}» removed from this device; the rest keep sharing it.",
    "dispositivo: {}": "device: {}",
    "carpeta: {}": "folder: {}",
    "No se pudo listar: {}": "Could not list: {}",
    "IP autodetectada: {} — añade credenciales y pulsa «Probar conexión».":
        "Auto-detected IP: {} — add credentials and press «Test connection».",
    "✗ Error: {}": "✗ Error: {}",
    "✓ {} dispositivo(s) comparten la carpeta. ({} descubierto(s) no la comparten y no se "
    "muestran.)":
        "✓ {} device(s) share the folder. ({} discovered don't share it and aren't shown.)",
    "✓ {} dispositivo(s) comparten la carpeta.": "✓ {} device(s) share the folder.",
    "  ✓  {} accesible — se configurará directamente.":
        "  ✓  {} reachable — it will be configured directly.",
    "  ✗  {} — {} — Error: {}": "  ✗  {} — {} — Error: {}",
    "  ↻  «{}» reconectó: aplico tus cambios sobre su configuración actual (fusión, sin borrar "
    "lo demás).":
        "  ↻  «{}» reconnected: applying your changes on top of its current configuration "
        "(merge, without deleting the rest).",
    "  {}  {} (topología) — {}": "  {}  {} (topology) — {}",
    "🔎  Exploración pasiva activa — {} dispositivo(s) sin acceso se configurarán "
    "automáticamente si se conectan mientras esta ventana siga abierta. Puedes generar agentes "
    "arriba en cualquier momento.":
        "🔎  Passive exploration active — {} device(s) without access will be configured "
        "automatically if they connect while this window stays open. You can generate agents "
        "above at any time.",
    "ℹ  {} dispositivo(s) marcados para exploración pasiva no tienen credenciales, así que no "
    "se auto-configurarán. Usa el agente, o vuelve a «Dispositivos» y añádeles credenciales.":
        "ℹ  {} device(s) marked for passive exploration have no credentials, so they won't "
        "auto-configure. Use the agent, or go back to «Devices» and add credentials.",
    "No se puede conectar a:\n{}\n\n• Comprueba que Syncthing está en ejecución\n• Verifica la "
    "URL (¿http o https?)\n• Verifica la API Key":
        "Cannot connect to:\n{}\n\n• Check that Syncthing is running\n• Verify the URL (http "
        "or https?)\n• Verify the API key",
    "Error inesperado: {}": "Unexpected error: {}",
    "Error: {}": "Error: {}",
    "🔄  Re-descubriendo dispositivos desde {}…": "🔄  Re-discovering devices from {}…",
    "\n↳ {} dispositivo(s) nuevo(s) descubierto(s)": "\n↳ {} new device(s) discovered",
    "     · {}: dispositivo «{}» {}": "     · {}: device «{}» {}",
    "El label contiene caracteres no válidos: {}": "The label has invalid characters: {}",
    "El nombre contiene caracteres no válidos: {}": "The name has invalid characters: {}",
    "[red]Label con caracteres no válidos: {}[/red]":
        "[red]Label has invalid characters: {}[/red]",
    "[red]Nombre con caracteres no válidos: {}[/red]":
        "[red]Name has invalid characters: {}[/red]",

    # ── CLI dynamic templates (rich markup preserved) ─────────────────────────
    "\n[cyan]Exploración pasiva activa[/cyan] — esperando a {} dispositivo(s) offline. Pulsa "
    "Ctrl-C para terminar.\n[dim]Se aplicará el cambio en cuanto cada equipo vuelva a estar "
    "accesible.[/dim]":
        "\n[cyan]Passive exploration active[/cyan] — waiting for {} offline device(s). Press "
        "Ctrl-C to stop.\n[dim]The change is applied as soon as each device becomes reachable "
        "again.[/dim]",
    "\n[yellow]⚠  {} dispositivo(s) sin ningún acceso disponible.[/yellow]":
        "\n[yellow]⚠  {} device(s) with no access available.[/yellow]",
    "\n[dim]Ruta de credenciales:[/dim] {}": "\n[dim]Credentials path:[/dim] {}",
    "\nDescubriendo dispositivos para: [bold]{}[/bold]\n":
        "\nDiscovering devices for: [bold]{}[/bold]\n",
    "Ruta actual:  [bold]{}[/bold]\n": "Current path:  [bold]{}[/bold]\n",
    "\n[cyan]Se generará UN agente con {} dispositivo(s) embebidos.[/cyan]\n[dim]Al ejecutarlo "
    "en cada equipo detecta automáticamente su ID de Syncthing\ny aplica solo la configuración "
    "correspondiente.[/dim]":
        "\n[cyan]ONE agent will be generated with {} embedded device(s).[/cyan]\n[dim]When run "
        "on each device it auto-detects its Syncthing ID\nand applies only the matching "
        "configuration.[/dim]",
    "\n[bold]Topología de «{}»[/bold]\n": "\n[bold]Topology of «{}»[/bold]\n",
    "\n[bold]  Dispositivo:[/bold] {}  [dim]({})[/dim]":
        "\n[bold]  Device:[/bold] {}  [dim]({})[/dim]",
    "  [red]Error:[/red] {}": "  [red]Error:[/red] {}",
    "[dim]Credenciales guardadas cargadas: {} dispositivo(s)[/dim]":
        "[dim]Loaded saved credentials: {} device(s)[/dim]",
    "\n[yellow]⚠  {} dispositivo(s) sin acceso.[/yellow]":
        "\n[yellow]⚠  {} device(s) without access.[/yellow]",
    "\n[yellow]Se saltarán {} dispositivo(s) sin acceso (ni API, SSH ni WinRM):[/yellow]":
        "\n[yellow]Skipping {} device(s) without access (no API, SSH or WinRM):[/yellow]",
    "error: {}": "error: {}",
    "[red]No se encontró la carpeta a revertir (ni «{}» ni «{}»). ¿Ya se deshizo o se "
    "borró?[/red]":
        "[red]Couldn't find the folder to revert (neither «{}» nor «{}»). Already undone or "
        "deleted?[/red]",
    "  Nombre en disco: → [bold]«{}»[/bold]": "  On-disk name: → [bold]«{}»[/bold]",
    "[red]Plantilla de agente para '{}'{} no encontrada.[/red]\n[dim]Compílala con:\n  python -m "
    "PyInstaller build/agent_{}.spec[/dim]":
        "[red]Agent template for '{}'{} not found.[/red]\n[dim]Build it with:\n  python -m "
        "PyInstaller build/agent_{}.spec[/dim]",
    "[yellow]Warning: no se pudo cargar {}: {}[/yellow]":
        "[yellow]Warning: couldn't load {}: {}[/yellow]",
    "[red]Error al guardar: {}[/red]": "[red]Error saving: {}[/red]",
    "  [dim]! {}: sin API Key, se omite del agente.[/dim]":
        "  [dim]! {}: no API key, skipped from the agent.[/dim]",
    "  [dim]Cópialo a cualquiera de los {} equipos y ejecútalo directamente — detecta el equipo "
    "solo.[/dim]":
        "  [dim]Copy it to any of the {} devices and run it directly — it detects the device "
        "itself.[/dim]",
    "  {}  —  {}  [dim](dirección desconocida · offline)[/dim]":
        "  {}  —  {}  [dim](unknown direction · offline)[/dim]",
    "\n¿Revertir en {} dispositivo(s)?": "\nRevert on {} device(s)?",
    "\n[green]✓ Agente generado (con verificación de ID):[/green] {}":
        "\n[green]✓ Agent generated (with ID verification):[/green] {}",
    "[dim]Solo funcionará en el dispositivo con ID: {}…[/dim]":
        "[dim]It will only run on the device with ID: {}…[/dim]",
    "\n[green]✓ Agente generado (sin verificación):[/green] {}":
        "\n[green]✓ Agent generated (without verification):[/green] {}",
    "[red]Error: {}[/red]": "[red]Error: {}[/red]",
    "[red]No se puede conectar a Syncthing en {}[/red]":
        "[red]Cannot connect to Syncthing at {}[/red]",
    "[cyan]⟳ {} en línea — aplicando…[/cyan]": "[cyan]⟳ {} online — applying…[/cyan]",
    "\n[yellow]Pasiva interrumpida. Sin configurar: {}.[/yellow]":
        "\n[yellow]Passive interrupted. Not configured: {}.[/yellow]",
    "\n¿Renombrar en {} dispositivo(s)?": "\nRename on {} device(s)?",
    "  [red]Error generando agente {}: {}[/red]":
        "  [red]Error generating agent {}: {}[/red]",
    "\n[yellow]{} dispositivo(s) sin acceso se saltarán":
        "\n[yellow]{} device(s) without access will be skipped",
    "[dim]Re-descubrimiento falló: {}[/dim]": "[dim]Re-discovery failed: {}[/dim]",
    "  [green]✓ {} — SSH OK, api_key descubierta vía SSH[/green]":
        "  [green]✓ {} — SSH OK, api_key discovered via SSH[/green]",
    "  [yellow]⚠ {} — {}{} (se reintentará)[/yellow]":
        "  [yellow]⚠ {} — {}{} (will retry)[/yellow]",
    "  [green]✓ {} — WinRM OK, api_key descubierta vía WinRM[/green]":
        "  [green]✓ {} — WinRM OK, api_key discovered via WinRM[/green]",
    "  [green]✓ {} — SSH OK (API solo en localhost del dispositivo, es normal)[/green]":
        "  [green]✓ {} — SSH OK (API only on the device's localhost, that's normal)[/green]",
    "  [green]✓ {} — WinRM OK (API solo en localhost del dispositivo, es normal)[/green]":
        "  [green]✓ {} — WinRM OK (API only on the device's localhost, that's normal)[/green]",

    # ── Remaining static labels ───────────────────────────────────────────────
    "  (ruta propia)": "  (own path)",
    "  (vacío = auto)": "  (empty = auto)",
    "  (✏ Editar seleccionado · clic derecho)": "  (✏ Edit selected · right-click)",
    "  hasta entonces la topología puede quedar asimétrica.":
        "  until then the topology may stay asymmetric.",
    "  · derivado de los enlaces": "  · derived from the links",
    "  ⚠ todos los dispositivos deberán aceptar la nueva carpeta":
        "  ⚠ all devices will have to accept the new folder",
    "  ✓  Reversión pasiva completada.": "  ✓  Passive revert completed.",
    " (API solo en localhost — «Examinar» no disponible)":
        " (API only on localhost — «Browse» unavailable)",
    " (no embebida)": " (not embedded)",
    " (sin cifrar)": " (unencrypted)",
    " — pulsa «Redescubrir» para actualizar.": " — press «Re-discover» to refresh.",
    "(0 = sin límite)": "(0 = no limit)",
    "(credenciales cambiadas — vuelve a Probar conexión)":
        "(credentials changed — Test connection again)",
    "(por defecto ~/<nombre>; «Examinar» tras probar la API)":
        "(default ~/<name>; «Browse» after testing the API)",
    "Carpeta quitada de este equipo": "Folder removed from this device",
    "Dispositivo": "Device",
    "ESTE equipo (local)": "THIS device (local)",
    "La configuración del equipo cambió": "The device's configuration changed",
    "Límite ↑ (KiB/s):": "Limit ↑ (KiB/s):",
    "NUEVO": "NEW",
    "No hay dispositivos marcados para exploración pasiva.":
        "No devices marked for passive exploration.",
    "No se puede borrar en disco en: ": "Cannot delete on disk on: ",
    "Ruta:              (sin cambios)": "Path:              (unchanged)",
    "Topología   (enlaces, roles, dispositivos nuevos)":
        "Topology   (links, roles, new devices)",
    "[ DRY RUN — no se realizará ningún cambio real ]":
        "[ DRY RUN — no real change will be made ]",
    "aceptar": "accept",
    "no accesible": "not reachable",
    "reconectó ": "reconnected ",
    "se desconectó ": "disconnected ",
    "sin dispositivos nuevos": "no new devices",
    "·· punteado = enlace recordado (offline, sesión anterior)":
        "·· dotted = remembered link (offline, previous session)",
    "–  sin punta = dirección desconocida (offline)":
        "–  no arrowhead = unknown direction (offline)",
    "… en cola (esperando conexión)": "… queued (waiting for connection)",
    "── Aplicando topología (solo cambios) ──": "── Applying topology (changes only) ──",
    "── Config avanzada de carpeta ──": "── Advanced folder config ──",
    "── Deshaciendo (selección) ──": "── Undoing (selection) ──",
    "── Revirtiendo topología ──": "── Reverting topology ──",
    "⚠  Syncthing responde pero la API Key guardada no es válida.":
        "⚠  Syncthing responds but the saved API key is invalid.",
    "⚠ No accesibles ahora y sin gestionar: ": "⚠ Not reachable now and unmanaged: ",
    "⚠ aceptar manual": "⚠ manual accept",
    "🔄  Cambios de conectividad: ": "🔄  Connectivity changes: ",

    # ── #55 extras (pending / .stignore / pause) + late strings ───────────────
    "  🔎+🧩 pasiva + agente:  {}  (lo que ocurra primero)":
        "  🔎+🧩 passive + agent:  {}  (whichever happens first)",
    "▶ Reanudar {} pausada(s)": "▶ Resume {} paused",
    "  ·  {} des-compartir pendiente(s) al reconectar":
        "  ·  {} unshare pending on reconnect",
    "  ✓  {} (nombres) — aplicados al reconectar":
        "  ✓  {} (names) — applied on reconnect",
    "Modo Borrar enlace: clic sobre una línea para eliminar esa conexión.":
        "Delete-link mode: click a line to remove that connection.",
    "Peticiones entrantes": "Incoming requests",
    "Syncthing Folder Rename — informe": "Syncthing Folder Rename — report",
    "Pausar carpeta": "Pause folder",
    "Mostrar opciones avanzadas (config completa de carpeta/dispositivo)":
        "Show advanced options (full folder/device config)",
    "Al cambiarla se mueven las credenciales y ajustes a la nueva carpeta.":
        "Changing it moves the credentials and settings to the new folder.",
    "Haz doble clic en una fila o selecciónala y pulsa Siguiente →":
        "Double-click a row, or select it and press Next →",
    "Introduce el nuevo nombre o ruta, o desmarca 'Cambiar ruta / nombre'.":
        "Enter the new name or path, or uncheck 'Change path / name'.",
    "  Sus cambios de rol/enlace no se aplicarán hasta aceptarlos a mano;":
        "  Their role/link changes won't apply until accepted manually;",
    "📥 Peticiones entrantes…": "📥 Incoming requests…",
    "⏸ Pausar la carpeta aquí": "⏸ Pause the folder here",
    "▶ Reanudar la carpeta aquí": "▶ Resume the folder here",
    "Pausar / reanudar la carpeta": "Pause / resume the folder",
    "Editar .stignore (exclusiones)…": "Edit .stignore (exclusions)…",
    "Este enlace está marcado como «no editar». ¿Desbloquearlo y editarlo?":
        "This link is marked “don't edit”. Unlock and edit it?",
    "↩ Configuración previa restaurada (este dispositivo ya existía).":
        "↩ Previous configuration restored (this device already existed).",
    "  (lo que ocurra primero)": "  (whichever happens first)",
    "(vacío = sin cifrar; la API Key quedaría legible en el binario)":
        "(empty = unencrypted; the API key would be readable in the binary)",
    "     ⚠ recuerda: chmod +x en la máquina Linux antes de ejecutarlo":
        "     ⚠ remember: chmod +x on the Linux machine before running it",
    "▶ Reanudar ": "▶ Resume ",
    "✓  Guardado — API accesible directamente": "✓  Saved — API reachable directly",
    "✓  Guardado — SSH OK (API accesible en localhost del dispositivo)":
        "✓  Saved — SSH OK (API reachable on the device's localhost)",
    "✓  Guardado — WinRM OK (API accesible en localhost del dispositivo)":
        "✓  Saved — WinRM OK (API reachable on the device's localhost)",
    " des-compartir pendiente(s) al reconectar": " unshare pending on reconnect",
    "(ruta desconocida)": "(unknown path)",
    "No hay peticiones entrantes.": "No incoming requests.",
    "Dispositivos:": "Devices:",
    "Descartar": "Dismiss",
    "Carpetas ofrecidas:": "Offered folders:",
    "Aceptar…": "Accept…",
    "No se pudo leer la config actual; solo se aplicará lo que cambies.":
        "Could not read the current config; only your changes will be applied.",
    "⚠ No alcanzable ahora — quedará para exploración pasiva / agente.":
        "⚠ Not reachable now — it will wait for passive exploration / agent.",
    "✓ Guardado.": "✓ Saved.",
    " (nombres) — aplicados al reconectar": " (names) — applied on reconnect",
    "Petición descartada.": "Request dismissed.",

    # ── Crear carpeta + etiquetas de label/preview ────────────────────────────
    "Carpeta «{}» creada en este equipo.": "Folder «{}» created on this device.",
    "➕ Nueva carpeta": "➕ New folder",
    "Nueva carpeta": "New folder",
    "Crear": "Create",
    "Crear una carpeta nueva en este equipo": "Create a new folder on this device",
    "El ID no puede estar vacío.": "The ID cannot be empty.",
    "Indica una ruta.": "Enter a path.",
    "Sin conexión con Syncthing.": "No connection to Syncthing.",
    "Ya existe una carpeta con ese ID.": "A folder with that ID already exists.",
    "(se crea si no existe; el explorador permite crear carpetas)":
        "(created if missing; the explorer lets you make folders)",
    "Label:": "Label:",
    "Label actual:": "Current label:",
    "Cambiar label:": "Change label:",
    "(solo label)": "(label only)",
    ": (solo label)": ": (label only)",
    "  • {}: (solo label)": "  • {}: (label only)",
    "  {}  {} (nuevo) — {}": "  {}  {} (new) — {}",
    "Label   «{}» → «{}»": "Label   «{}» → «{}»",
    "Nuevo ID: {}": "New ID: {}",
    "Nuevo label: {}": "New label: {}",
    "Nuevo ID: ": "New ID: ",
    "Nuevo label: ": "New label: ",
    "label→«{}»": "label→«{}»",

    # ── App lock (Part 2) ─────────────────────────────────────────────────────
    "Protección con contraseña (candado de la app):": "Password protection (app lock):",
    "Desactivado": "Disabled",
    "Contraseña propia": "Own password",
    "Contraseña de Syncthing": "Syncthing password",
    "Contraseña propia:": "Own password:",
    "Repetir:": "Repeat:",
    "Bloquear tras inactividad (min):": "Lock after inactivity (min):",
    "Guardar candado": "Save lock",
    "Bloquear ahora": "Lock now",
    "🔒 Bloquear ahora": "🔒 Lock now",
    "🔓 Desbloquear": "🔓 Unlock",
    "🔒 Aplicación bloqueada": "🔒 Application locked",
    "Bloqueado": "Locked",
    "Introduce la contraseña para desbloquear.": "Enter the password to unlock.",
    "Introduce tu contraseña de Syncthing.": "Enter your Syncthing password.",
    "Contraseña incorrecta.": "Incorrect password.",
    "El candado no está activado. Actívalo en Ajustes.":
        "The lock isn't enabled. Enable it in Settings.",
    "¿Bloquear la aplicación? Tendrás que introducir la contraseña para volver.":
        "Lock the application? You'll need to enter the password to return.",
    "Proteger la aplicación": "Protect the application",
    "Protección activada": "Protection enabled",
    "✓ Candado guardado.": "✓ Lock saved.",
    "Disuasorio para la app desatendida. NO protege contra acceso a tus ficheros (la API Key "
    "está en el config de Syncthing). Recuperable borrando «applock» en settings.json.":
        "Deterrent for the unattended app. Does NOT protect against access to your files (the "
        "API key is in Syncthing's config). Recoverable by deleting «applock» in settings.json.",
    "Syncthing tiene una contraseña de interfaz. ¿Proteger esta app con ella (se pedirá al "
    "abrir y tras inactividad)?\n\nEs un disuasorio configurable; podrás desactivarlo en "
    "Ajustes.":
        "Syncthing has a GUI password. Protect this app with it (asked on open and after "
        "inactivity)?\n\nIt's a configurable deterrent; you can disable it in Settings.",
    "Activada con tu contraseña de Syncthing. Es configurable en Ajustes.\n\n¿Desactivarla "
    "ahora?":
        "Enabled with your Syncthing password. It's configurable in Settings.\n\nDisable it "
        "now?",

    # ── Pre-existing strings surfaced by the wider scan ───────────────────────
    "Detectando Syncthing...": "Detecting Syncthing...",
    "Dry run — simular sin ejecutar nada (recomendado para la primera prueba)":
        "Dry run — simulate without executing anything (recommended for the first test)",
    "Editar también equipos offline (se aplicarán al reconectar: exploración pasiva o agente)":
        "Also edit offline devices (applied on reconnect: passive exploration or agent)",
    "Escribe solo el nombre (ej: Documentos) o una ruta completa (ej: D:\\Docs\\Nuevo)":
        "Type just the name (e.g. Documents) or a full path (e.g. D:\\Docs\\New)",
    "Modo Añadir enlace: clic en un dispositivo y luego en otro para crear el enlace.":
        "Add-link mode: click one device then another to create the link.",
    "No se detecta Syncthing — ¿está instalado y se ha ejecutado al menos una vez?":
        "Syncthing not detected — is it installed and has it run at least once?",
    "Solo este equipo comparte la carpeta — añade dispositivos para enlazarla.":
        "Only this device shares the folder — add devices to link it.",
    "Selecciona un dispositivo con problemas y pulsa 'Editar credenciales' para configurarlo.":
        "Select a device with problems and press 'Edit credentials' to configure it.",
    "⚠: la API Key se obtendrá automáticamente via SSH al ejecutar el rename.":
        "⚠: the API key will be obtained automatically via SSH when running the rename.",
    "⚠  Syncthing está instalado pero no parece estar en ejecución — arráncalo.":
        "⚠  Syncthing is installed but doesn't seem to be running — start it.",
    "⚠ Puede quedar bidireccional: ambos extremos ya envían/reciben por otros enlaces.":
        "⚠ It may become bidirectional: both ends already send/receive via other links.",
    "✓ Guardado (config de carpeta pendiente: se aplicará al reconectar/agente).":
        "✓ Saved (folder config pending: applied on reconnect/agent).",
    "  Útil si todos los dispositivos comparten las mismas credenciales SSH.":
        "  Useful if all devices share the same SSH credentials.",
    "Cada agente detecta su equipo por ID de Syncthing y pide confirmación antes de aplicar.":
        "Each agent detects its device by Syncthing ID and asks for confirmation before applying.",
    "▶  Credenciales SSH globales (opcional — para automatizar acceso a todos los dispositivos)":
        "▶  Global SSH credentials (optional — to automate access to all devices)",

    # ── 1-B: añadir dispositivo desde la ventana de Dispositivos + indicadores ─
    "➕  Añadir dispositivo": "➕  Add device",
    "Añadir dispositivo": "Add device",
    "Añadir dispositivo al clúster": "Add device to the cluster",
    "«{}» añadido — compártele la carpeta en Topología.":
        "«{}» added — share the folder with it in Topology.",
    "Ese dispositivo ya está en la lista.": "That device is already in the list.",
    "Acceso (opcional)": "Access (optional)",
    "Acceso (opcional):": "Access (optional):",
    "Nombre:": "Name:",
    "Vigilar cambios (fsWatcher)": "Watch for changes (fsWatcher)",
    "● cambios sin aplicar — pulsa Siguiente → para aplicarlos":
        "● unapplied changes — press Next → to apply them",
    "Lo empareja en ESTE equipo y aparece en Topología para compartirle la carpeta. El otro "
    "equipo debe aceptar, o configúralo con credenciales (acceso opcional).":
        "Pairs it on THIS device and shows it in Topology to share the folder with it. The "
        "other device must accept, or configure it with credentials (access optional).",
    # ── Settings: security toggles ────────────────────────────────────────────
    "Seguridad:": "Security:",
    "Preferir canal cifrado (SSH/WinRM) para equipos remotos en vez de la API directa — "
    "evita exponer la API Key en la red":
        "Prefer the encrypted channel (SSH/WinRM) for remote devices over the direct API — "
        "keeps the API key off the network",
    "SSH estricto: rechazar hosts cuya clave no esté en known_hosts (evita MITM en la "
    "primera conexión; requiere añadirlos a mano)":
        "Strict SSH: reject hosts whose key isn't in known_hosts (prevents first-connect "
        "MITM; you must add them by hand)",
    "WinRM sobre HTTPS estricto: validar el certificado del servidor (rechaza certificados "
    "no confiables; déjalo apagado si usas WinRM por HTTP o certificados autofirmados)":
        "Strict WinRM over HTTPS: validate the server certificate (rejects untrusted "
        "certificates; leave off if you use WinRM over HTTP or self-signed certificates)",
    "El archivo de credenciales está cifrado y no se ha desbloqueado en esta sesión; "
    "guardar ahora borraría las credenciales cifradas. Desbloquéalas primero.":
        "The credentials file is encrypted and hasn't been unlocked this session; saving "
        "now would wipe the encrypted credentials. Unlock them first.",
    # ── Auto-completed UI strings (full ES→EN coverage) ──
    '  (alternativa a clave)':
        '  (alternative to key)',
    '  Clave privada:':
        '  Private key:',
    '  Puerto SSH:':
        '  SSH port:',
    '  Usuario SSH:':
        '  SSH user:',
    '  {}  ·  {}  (de {}…)':
        '  {}  ·  {}  (of {}…)',
    '  ⏳  {} dispositivo(s) offline dejarán de compartir cuando vuelvan a estar accesibles (al reconectar, o ejecutando su agente).':
        '  ⏳  {} offline device(s) will stop sharing once they are reachable again (on reconnect, or by running their agent).',
    '  ✖  {} dispositivo(s) dejaron de compartir la carpeta (sin enlaces).':
        '  ✖  {} device(s) stopped sharing the folder (no links).',
    '  ✖ dejar de compartir en «{}» (se queda sin enlaces)':
        '  ✖ stop sharing on «{}» (left with no links)',
    '  📄 Informe guardado: {}':
        '  📄 Report saved: {}',
    ' en «{}».':
        ' on «{}».',
    ' «{}» en «{}»…':
        ' «{}» on «{}»…',
    '(ruta en ESTE dispositivo donde se creará/compartirá la carpeta; por defecto ~/<carpeta>)':
        '(path on THIS device where the folder will be created/shared; defaults to ~/<folder>)',
    'API Key requerida':
        'API key required',
    'API Key:':
        'API key:',
    'Agente (binario)':
        'Agent (binary)',
    'Aplicando…':
        'Applying…',
    'Avanzado':
        'Advanced',
    'Borrando «{}» en «{}»…':
        'Deleting «{}» on «{}»…',
    'Cargando…':
        'Loading…',
    'Carpeta local para «{}» ({})':
        'Local folder for «{}» ({})',
    'Carpeta «{}» aceptada y creada en {}.':
        'Folder «{}» accepted and created at {}.',
    'Comprobando (pre-vuelo)…':
        'Checking (preflight)…',
    'Confirmar y ejecutar':
        'Confirm and run',
    'Confirmar:':
        'Confirm:',
    'Continuar →':
        'Continue →',
    'Creando…':
        'Creating…',
    'Define un nombre canónico para cada dispositivo. Se aplicará en todos los equipos alcanzables (API, SSH, WinRM).\nSolo se actualizan los pares ya configurados — no se crean nuevas entradas.':
        'Define a canonical name for each device. It will be applied on every reachable device (API, SSH, WinRM).\nOnly already-configured peers are updated — no new entries are created.',
    'Deshacer':
        'Undo',
    'Deshacer seleccionado':
        'Undo selected',
    'Deshaciendo…':
        'Undoing…',
    'Deshecho.':
        'Undone.',
    'Dispositivo «{}» añadido.':
        'Device «{}» added.',
    'Dispositivos que han intentado conectar y carpetas que te ofrecen equipos ya conocidos. Aceptar un dispositivo lo añade a tu configuración; aceptar una carpeta la crea aquí en la ruta que elijas.':
        'Devices that have tried to connect and folders offered by already-known devices. Accepting a device adds it to your configuration; accepting a folder creates it here at the path you choose.',
    'Dispositivos sin acceso remoto → se gestionarán por exploración pasiva (al reconectar) o con un agente local.':
        'Devices with no remote access → they will be handled by passive exploration (on reconnect) or with a local agent.',
    'Editar .stignore  —  requiere acceso a este equipo':
        'Edit .stignore  —  requires access to this device',
    'Ejecutando…':
        'Running…',
    'El ID solo puede tener letras, números y . _ - (sin espacios).':
        'The ID may only contain letters, numbers and . _ - (no spaces).',
    'El acceso es opcional: con credenciales (SSH/WinRM o API) editamos su config directamente. Sin acceso, podrás aceptar el dispositivo/carpeta en la interfaz web de Syncthing del equipo, o usar un agente.':
        "Access is optional: with credentials (SSH/WinRM or API) we edit its config directly. Without access, you can accept the device/folder in the device's Syncthing web UI, or use an agent.",
    'Elige cómo configurar cada dispositivo (puedes marcar ambas):\n  🤖 Agente — ejecutable que se copia y corre en la máquina (offline, sin credenciales).\n  🔎 Pasiva — se auto-configura al reconectarse mientras la ventana final siga abierta (requiere credenciales).':
        'Choose how to configure each device (you can tick both):\n  🤖 Agent — an executable copied and run on the device (offline, no credentials).\n  🔎 Passive — auto-configures on reconnect while the final window stays open (requires credentials).',
    'Enlace bloqueado':
        'Link locked',
    'Enlace borrado: «{}» — «{}»':
        'Link deleted: «{}» — «{}»',
    'Enlace desbloqueado.':
        'Link unlocked.',
    'Equipo no accesible ahora: estos cambios quedarán PENDIENTES y se aplicarán al reconectar (pasiva) o por agente.':
        'Device not reachable right now: these changes will stay PENDING and apply on reconnect (passive) or via agent.',
    'Examinar':
        'Browse',
    'Examinar…':
        'Browse…',
    'Exclusiones guardadas en «{}».':
        'Exclusions saved on «{}».',
    'Exploración pasiva sin terminar':
        'Passive exploration unfinished',
    'Faltan credenciales':
        'Missing credentials',
    'Grafo real de la carpeta. ✋ Mover (arrastra nodos) · 🔗 Añadir enlace (clic en 2 nodos) · ✂ Borrar enlace (clic en la línea). Doble clic o clic derecho en un nodo o flecha = opciones. Editas la DIRECCIÓN del enlace; el rol (envía/recibe…) se deriva y es solo-lectura. Flecha sin punta = equipo offline (dirección desconocida); roja = no sincroniza. Rueda/🔍 = zoom · arrastra zona vacía = desplazar · ⊡ Ajustar encuadra · 🔄 Estado refresca · ↶/↷ (Ctrl+Z/Y) deshacer/rehacer.':
        'Real folder graph. ✋ Move (drag nodes) · 🔗 Add link (click 2 nodes) · ✂ Delete link (click the line). Double-click or right-click a node or arrow = options. You edit the link DIRECTION; the role (send/receive…) is derived and read-only. Arrow with no head = offline device (unknown direction); red = not syncing. Wheel/🔍 = zoom · drag empty area = pan · ⊡ Fit frames it · 🔄 Status refreshes · ↶/↷ (Ctrl+Z/Y) undo/redo.',
    'Guardando exclusiones en «{}»…':
        'Saving exclusions on «{}»…',
    'Guardando…':
        'Saving…',
    'Hay {} dispositivo(s) que se configurarían por EXPLORACIÓN PASIVA al reconectar, pero la pasiva solo sigue mientras estás en esta ventana. Si sales ahora sin generar un agente, esos cambios NO se aplicarán en ellos: se revertirá lo que no cuajó en ningún sitio y se marcarán como «sin confirmar» en la topología.\n\n(Los dispositivos que van por agente no se ven afectados: se configuran cuando ejecutes su agente.)\n\n¿Salir de todas formas?':
        'There are {} device(s) that would be configured by PASSIVE EXPLORATION on reconnect, but passive only continues while you are in this window. If you leave now without generating an agent, those changes will NOT be applied on them: whatever did not take anywhere will be reverted and they will be marked «unconfirmed» in the topology.\n\n(Devices handled by an agent are not affected: they are configured when you run their agent.)\n\nLeave anyway?',
    'IP autodetectada: {}':
        'Auto-detected IP: {}',
    'Ignorar permisos':
        'Ignore permissions',
    'Introduce la API Key de Syncthing.\n\nLa encontrarás en: Acciones → Configuración → General.':
        "Enter Syncthing's API key.\n\nYou'll find it in: Actions → Settings → General.",
    'Introduce primero la URL de la API del dispositivo nuevo (en Acceso) para poder explorar sus carpetas.':
        "First enter the new device's API URL (under Access) so you can browse its folders.",
    'Ir':
        'Go',
    'Los dispositivos por exploración pasiva que no estén conectados se revertirán al reconectar (mantén la ventana abierta). Los de agente no se revierten automáticamente.':
        'Passive-exploration devices that are not connected will be reverted on reconnect (keep the window open). Agent devices are not reverted automatically.',
    'Los dispositivos sin acceso se configuran solos al conectarse mientras esta ventana siga abierta. Edita credenciales o fuerza un barrido inmediato.':
        'Devices without access configure themselves on connect while this window stays open. Edit credentials or force an immediate sweep.',
    'No se pudieron leer las exclusiones de «{}».':
        'Could not read the exclusions of «{}».',
    'No se pudo guardar: {}':
        'Could not save: {}',
    'No se pudo validar el Device ID (¿Syncthing accesible?).\n\n¿Añadirlo de todas formas?':
        'Could not validate the Device ID (is Syncthing reachable?).\n\nAdd it anyway?',
    'No se pudo verificar si el ID ya existe (error de conexión). Reintenta.':
        'Could not verify whether the ID already exists (connection error). Try again.',
    'No se pudo: {}':
        'Failed: {}',
    'No se renombra nada en {} dispositivo(s) accesible(s) — solo se aplican los cambios de topología de abajo.':
        'Nothing is renamed on {} reachable device(s) — only the topology changes below are applied.',
    'Opciones avanzadas':
        'Advanced options',
    'Patrones de exclusión (.stignore) — «{}»':
        'Exclusion patterns (.stignore) — «{}»',
    'Pausar / reanudar la carpeta  —  requiere acceso a este equipo':
        'Pause / resume the folder  —  requires access to this device',
    'Probando...':
        'Testing...',
    'Quitar dispositivo':
        'Remove device',
    'Reanudando…':
        'Resuming…',
    'Rehecho.':
        'Redone.',
    'Reintentando…':
        'Retrying…',
    'Error al deshacer: {}':
        'Undo error: {}',
    'Error al probar: {}':
        'Test error: {}',
    'Error al reanudar: {}':
        'Resume error: {}',
    'Error al reintentar {}: {}':
        'Error retrying {}: {}',
    'Error al reintentar: {}':
        'Retry error: {}',
    '▶ Reintentar pausadas':
        '▶ Retry paused',
    'Restablecer columnas':
        'Reset columns',
    'Rol:':
        'Role:',
    'Se crea aquí, en el nodo local. Para compartirla con otros equipos, hazlo luego en Topología.':
        "It's created here, on the local node. To share it with other devices, do it later in Topology.",
    'Se usa para cifrar/descifrar las credenciales guardadas.\nNo se almacena en ningún sitio.':
        'Used to encrypt/decrypt the saved credentials.\nIt is not stored anywhere.',
    'Sistema:':
        'System:',
    'Syncthing escucha la API en localhost salvo que la GUI esté expuesta a la LAN (entonces usa http://IP:8384).':
        'Syncthing listens for the API on localhost unless the GUI is exposed to the LAN (then use http://IP:8384).',
    'Un patrón por línea (p. ej. *.tmp, /Cache, !importante.txt). Se aplican a la carpeta en ESTE equipo.':
        'One pattern per line (e.g. *.tmp, /Cache, !important.txt). They apply to the folder on THIS device.',
    'Unidireccional: pincha primero el ORIGEN y luego el DESTINO.\nBidireccional: pincha los dos nodos (orden indiferente).':
        "One-way: click the SOURCE first, then the DESTINATION.\nTwo-way: click both nodes (order doesn't matter).",
    'Ver':
        'View',
    'Verificando identidad de este equipo…':
        "Verifying this device's identity…",
    'Versionado:':
        'Versioning:',
    'Vincular conocido:':
        'Link known:',
    'Ya existe una carpeta con ese ID (en el servidor) — elige otro.':
        'A folder with that ID already exists (on the server) — choose another.',
    '[yellow]Aviso: --dir-name se ignora porque --skip-path-rename está activo (no se cambiará la ruta en disco).[/yellow]':
        "[yellow]Note: --dir-name is ignored because --skip-path-rename is active (the on-disk path won't change).[/yellow]",
    '«{}» borrada en «{}» (Syncthing + disco).':
        '«{}» deleted on «{}» (Syncthing + disk).',
    '«{}» borrada en «{}». Era el último equipo que la compartía.\n\nVolviendo a la selección de carpeta.':
        '«{}» deleted on «{}». It was the last device sharing it.\n\nReturning to folder selection.',
    '«{}» quitado de la lista.':
        '«{}» removed from the list.',
    '«{}» seleccionado (✏ Editar seleccionado · doble clic · clic derecho)':
        '«{}» selected (✏ Edit selected · double-click · right-click)',
    '«{}» — clic en {}':
        '«{}» — click on {}',
    '¿Quitar «{}» de la lista y de la topología?\n\nNo cambia la configuración de Syncthing (no deja de compartir ni borra nada en los equipos) — solo se quita de esta sesión. Para dejar de compartir una carpeta, hazlo en Topología.':
        "Remove «{}» from the list and the topology?\n\nIt doesn't change Syncthing's configuration (it neither stops sharing nor deletes anything on the devices) — it's only removed from this session. To stop sharing a folder, do it in Topology.",
    'ℹ Este dispositivo aún no está en tu configuración local. Si cambias algo aquí, se añadirá a tu config con estos ajustes (válido aunque esté offline).':
        "ℹ This device isn't in your local configuration yet. If you change anything here, it will be added to your config with these settings (valid even if it's offline).",
    'ℹ La «relación con el equipo» (introducer, auto-aceptar, compresión, límites) es una propiedad de cada dispositivo REMOTO en tu configuración, no del equipo local. Aquí editas la configuración de la CARPETA en este equipo.':
        'ℹ The «relationship with the device» (introducer, auto-accept, compression, limits) is a property of each REMOTE device in your configuration, not of the local device. Here you edit the FOLDER configuration on this device.',
    '→ Unidireccional':
        '→ One-way',
    '↔ Bidireccional':
        '↔ Two-way',
    '↶ Deshacer':
        '↶ Undo',
    '↷ Rehacer':
        '↷ Redo',
    '↺  Reintentar SSH':
        '↺  Retry SSH',
    '⊡ Ajustar':
        '⊡ Fit',
    '▼  Credenciales SSH globales (opcional)':
        '▼  Global SSH credentials (optional)',
    '⚙ Avanzado':
        '⚙ Advanced',
    '⚠ Equipo no accesible ahora. Lo que cambies aquí (rol, enlaces, avanzado) NO se aplica ya: queda pendiente y se aplicará cuando reconecte (exploración pasiva) o con un agente.':
        '⚠ Device not reachable right now. What you change here (role, links, advanced) is NOT applied now: it stays pending and will apply when it reconnects (passive exploration) or via an agent.',
    '⚠ Renombrar ID crea la carpeta nueva y borra la antigua en cada dispositivo accesible; el resto necesita el agente o la exploración pasiva.':
        '⚠ Renaming the ID creates the new folder and deletes the old one on every reachable device; the rest need the agent or passive exploration.',
    '⚠ Revisar':
        '⚠ Review',
    '⚠ faltan':
        '⚠ missing',
    '✏ Credenciales':
        '✏ Credentials',
    '✓ Guardado en {}{}':
        '✓ Saved to {}{}',
    '✓ Reanudadas':
        '✓ Resumed',
    '✓ Reintentado':
        '✓ Retried',
    '✓ Revertido':
        '✓ Reverted',
    '✨ Auto-organizar':
        '✨ Auto-arrange',
    '▭ negro (sólido) = se dejará de compartir al aplicar':
        '▭ black (solid) = will stop being shared on apply',
    '⬚ ámbar = sin confirmar (no se completó en una ejecución anterior)':
        "⬚ amber = unconfirmed (didn't complete in a previous run)",
    '🏷  Sincronizar nombres':
        '🏷  Sync names',
    '💡 Esto se aplica a todos los dispositivos. Para una ruta/rol/acceso distinto por equipo, edítalo en la siguiente ventana (Topología).':
        '💡 This applies to all devices. For a different path/role/access per device, edit it in the next window (Topology).',
    '📄 Informe guardado en {}':
        '📄 Report saved to {}',
    '🔄  Redescubrir':
        '🔄  Rediscover',
    '🔎 Forzar descubrimiento ahora':
        '🔎 Force discovery now',
    '🔎 Pasiva':
        '🔎 Passive',
    '🗑  Quitar dispositivo':
        '🗑  Remove device',
    '🤖 Agente':
        '🤖 Agent',
}

# ── CLI interactive layer (prompts, Rich console output, Typer option help) ───────────────
# Spanish source string → English. Kept in a separate update() block so the large literal
# above stays untouched. Rich markup tags, {} placeholders and leading spaces/newlines must
# match the source exactly (see test_translation_placeholders_match_source).
EN.update({
    "Syncthing API Key": "Syncthing API Key",
    "[yellow]API Key no detectada automáticamente.[/yellow]":
        "[yellow]API key not detected automatically.[/yellow]",
    "[dim]Conectado a Syncthing en {}[/dim]": "[dim]Connected to Syncthing at {}[/dim]",
    "[red]Syncthing está instalado pero no parece estar en ejecución.[/red]":
        "[red]Syncthing is installed but does not appear to be running.[/red]",
    "[dim]Arráncalo (p. ej. systemctl --user start syncthing, o abre la app) y reintenta.[/dim]":
        "[dim]Start it (e.g. systemctl --user start syncthing, or open the app) and retry.[/dim]",
    "[red]Syncthing responde pero la API Key no es válida.[/red]":
        "[red]Syncthing responds but the API key is not valid.[/red]",
    "[dim]Revisa la key en Acciones → Configuración → General.[/dim]":
        "[dim]Check the key in Actions → Settings → General.[/dim]",
    "[red]No se detecta Syncthing — ¿está instalado y se ha ejecutado al menos una vez?[/red]":
        "[red]Syncthing not detected — is it installed and has it run at least once?[/red]",
    "[red]No hay carpetas configuradas en Syncthing.[/red]":
        "[red]No folders configured in Syncthing.[/red]",
    "[red]Folder ID {!r} no encontrado.[/red]": "[red]Folder ID {!r} not found.[/red]",
    "Carpetas Syncthing": "Syncthing folders",
    "Ruta": "Path",
    "Selecciona carpeta por # o ID": "Select a folder by # or ID",
    "[red]Selección inválida.[/red]": "[red]Invalid selection.[/red]",
    "[dim]Las credenciales guardadas están cifradas.[/dim]":
        "[dim]Saved credentials are encrypted.[/dim]",
    "[red]Contraseña incorrecta — inténtalo de nuevo.[/red]":
        "[red]Wrong password — try again.[/red]",
    "[red]Demasiados intentos fallidos. Se omiten las credenciales guardadas.[/red]":
        "[red]Too many failed attempts. Skipping saved credentials.[/red]",
    "\n[bold]Cifrado del agente[/bold] — el ejecutable lleva embebida la API Key.\n"
    "[dim]Con contraseña, nadie puede extraerla del binario; se pedirá al ejecutar "
    "el agente. Déjalo vacío para no cifrar (NO recomendado).[/dim]":
        "\n[bold]Agent encryption[/bold] — the executable embeds the API key.\n"
        "[dim]With a password, nobody can extract it from the binary; it is asked when "
        "running the agent. Leave empty to skip encryption (NOT recommended).[/dim]",
    "Contraseña (vacío = sin cifrar): ": "Password (empty = no encryption): ",
    "[yellow]⚠  Agente sin cifrar: la API Key será legible en el binario.[/yellow]":
        "[yellow]⚠  Unencrypted agent: the API key will be readable in the binary.[/yellow]",
    "Repite la contraseña: ": "Repeat the password: ",
    "[red]Las contraseñas no coinciden — se generará SIN cifrar.[/red]":
        "[red]Passwords do not match — it will be generated UNENCRYPTED.[/red]",
    "\n[green]✓ Todos los dispositivos pendientes se han configurado.[/green]":
        "\n[green]✓ All pending devices have been configured.[/green]",
    "\n[green]Pasiva finalizada.[/green]": "\n[green]Passive exploration finished.[/green]",
    "  [green]✓ {} configurado por pasiva{}[/green]":
        "  [green]✓ {} configured passively{}[/green]",
    "  [red]⚠ {} — sync PAUSADA: {}{}[/red]": "  [red]⚠ {} — sync PAUSED: {}{}[/red]",
    "parcial": "partial",
    "Dispositivos descubiertos": "Discovered devices",
    "Remoto": "Remote",
    "[green]✓ directa[/green]": "[green]✓ direct[/green]",
    "[dim]vía remoto[/dim]": "[dim]via remote[/dim]",
    "[yellow]⚠ key OK, no alcanzable[/yellow]": "[yellow]⚠ key OK, not reachable[/yellow]",
    "[red]— sin key[/red]": "[red]— no key[/red]",
    "  Opciones: [1] Introducir credenciales manualmente  "
    "[2] Reintentar SSH  [3] Saltar este dispositivo":
        "  Options: [1] Enter credentials manually  [2] Retry SSH  [3] Skip this device",
    "  Opción": "  Option",
    "  IP o hostname": "  IP or hostname",
    "  URL de la API": "  API URL",
    "  API Key": "  API Key",
    "  Ruta de la carpeta en este dispositivo": "  Folder path on this device",
    "  Usuario SSH (vacío = no SSH)": "  SSH user (empty = no SSH)",
    "  Clave privada SSH (vacío = contraseña)": "  SSH private key (empty = password)",
    "  Contraseña SSH": "  SSH password",
    "  Puerto SSH": "  SSH port",
    "  Usuario WinRM (vacío = no WinRM)": "  WinRM user (empty = no WinRM)",
    "  Contraseña WinRM": "  WinRM password",
    "  Puerto WinRM": "  WinRM port",
    "[red]Puerto inválido — debe ser un número. Operación cancelada.[/red]":
        "[red]Invalid port — must be a number. Operation cancelled.[/red]",
    "Verificando API...": "Verifying API...",
    "  [green]✓ {} — API accesible directamente[/green]":
        "  [green]✓ {} — API directly reachable[/green]",
    "  [yellow]⚠ Sin acceso — se intentará de todas formas si hay api_key[/yellow]":
        "  [yellow]⚠ No access — will try anyway if there is an api_key[/yellow]",
    "  IP": "  IP",
    "  Usuario SSH": "  SSH user",
    "Probando {}...": "Testing {}...",
    "  [red]✗ Sigue fallando: {}[/red]": "  [red]✗ Still failing: {}[/red]",
    "¿Guardar credenciales para próximas sesiones?": "Save credentials for future sessions?",
    "[dim]Puedes cifrar contraseñas y API keys con una contraseña maestra.[/dim]":
        "[dim]You can encrypt passwords and API keys with a master password.[/dim]",
    "  ¿Cifrar credenciales sensibles?": "  Encrypt sensitive credentials?",
    "  Confirmar contraseña": "  Confirm password",
    " (cifradas con contraseña maestra)": " (encrypted with master password)",
    "[green]✓ Guardadas en {}{}[/green]": "[green]✓ Saved to {}{}[/green]",
    "Resultados": "Results",
    "Disco": "Disk",
    "Reanudado": "Resumed",
    "Estado": "Status",
    "Pausado": "Paused",
    "[yellow]⚠ Manual requerido[/yellow]": "[yellow]⚠ Manual required[/yellow]",
    "[yellow]⚠ Parcial[/yellow]": "[yellow]⚠ Partial[/yellow]",
    "\n[bold yellow]⚠  Pasos manuales necesarios (dispositivos sin SSH):[/bold yellow]":
        "\n[bold yellow]⚠  Manual steps required (devices without SSH):[/bold yellow]",
    "\n[bold red]⚠  Los siguientes dispositivos tienen la sync PAUSADA:[/bold red]":
        "\n[bold red]⚠  The following devices have sync PAUSED:[/bold red]",
    "  Reanuda manualmente desde la interfaz web de Syncthing.":
        "  Resume manually from the Syncthing web interface.",
    "Descubriendo...": "Discovering...",
    "¿Introducir credenciales para reintentar?": "Enter credentials to retry?",
    "Carpetas Syncthing locales": "Local Syncthing folders",
    "Nuevo nombre de directorio o ruta absoluta completa":
        "New directory name or full absolute path",
    "Cambiar también el ID de la carpeta. Se aplica en todos "
    "los dispositivos accesibles; los offline necesitan el agente.":
        "Also change the folder ID. Applied on every reachable device; offline ones "
        "need the agent.",
    "Tras renombrar, seguir esperando a los dispositivos offline y "
    "aplicarles el cambio cuando reconecten (Ctrl-C para terminar).":
        "After renaming, keep waiting for offline devices and apply the change when "
        "they reconnect (Ctrl-C to stop).",
    "[yellow]--- DRY RUN: no se realizará ningún cambio ---[/yellow]\n":
        "[yellow]--- DRY RUN: no changes will be made ---[/yellow]\n",
    "\nLabel actual: [bold]{}[/bold]": "\nCurrent label: [bold]{}[/bold]",
    "Nuevo label": "New label",
    "Nuevo nombre en disco (nombre simple o ruta absoluta completa)":
        "New on-disk name (simple name or full absolute path)",
    "\n[bold]Pre-vuelo:[/bold]": "\n[bold]Pre-flight:[/bold]",
    "[red]Pre-vuelo con errores; abortando "
    "(quita --no-confirm para decidir interactivamente).[/red]":
        "[red]Pre-flight has errors; aborting "
        "(drop --no-confirm to decide interactively).[/red]",
    "Hay errores de pre-vuelo. ¿Continuar de todas formas?":
        "There are pre-flight errors. Continue anyway?",
    "Cancelado.": "Cancelled.",
    "Renombrando...": "Renaming...",
    "\n[cyan]Renombrar ID: «{}» → «{}»[/cyan]": "\n[cyan]Rename ID: «{}» → «{}»[/cyan]",
    "  [green]✓ {} — ID actualizado[/green]": "  [green]✓ {} — ID updated[/green]",
    "\n[dim]Snapshot guardado. Usa «syncthing-manager undo» para revertir "
    "este cambio.[/dim]":
        "\n[dim]Snapshot saved. Use «syncthing-manager undo» to revert this change.[/dim]",
    "\n[dim]ℹ  Para generar agentes para dispositivos sin acceso remoto, "
    "compila las plantillas:\n"
    "  python -m PyInstaller build/agent_windows.spec\n"
    "  python -m PyInstaller build/agent_linux.spec\n"
    "  python -m PyInstaller build/agent_macos.spec[/dim]":
        "\n[dim]ℹ  To generate agents for devices without remote access, "
        "build the templates:\n"
        "  python -m PyInstaller build/agent_windows.spec\n"
        "  python -m PyInstaller build/agent_linux.spec\n"
        "  python -m PyInstaller build/agent_macos.spec[/dim]",
    "\n[yellow]ℹ  Dispositivos que requieren agente local:[/yellow]":
        "\n[yellow]ℹ  Devices that require a local agent:[/yellow]",
    "sin SSH/WinRM": "no SSH/WinRM",
    "[b] Ambos": "[b] Both",
    "[b] Todos": "[b] All",
    "  [yellow]La plataforma elegida no está disponible — no se generó ningún agente.[/yellow]":
        "  [yellow]The chosen platform isn't available — no agent was generated.[/yellow]",
    "  [yellow]⚠ {}: arquitectura(s) detectada(s) sin plantilla embebida: {} — esos dispositivos no quedan cubiertos (recompila con la plantilla).[/yellow]":
        "  [yellow]⚠ {}: detected architecture(s) without an embedded template: {} — those devices aren't covered (rebuild with the template).[/yellow]",
    "Plataforma ({})": "Platform ({})",
    "  [green]✓ Agente {}: {}[/green]": "  [green]✓ {} agent: {}[/green]",
    "  [green]✓ Agente {} {}: {}[/green]": "  [green]✓ {} {} agent: {}[/green]",
    "¿Generar también la versión {} del agente {}?":
        "Generate the {} build of the {} agent too?",
    "  [red]Error generando agente {} {}: {}[/red]":
        "  [red]Error generating {} {} agent: {}[/red]",
    "[bold]Dispositivos:[/bold]": "[bold]Devices:[/bold]",
    "rol desconocido (offline)": "unknown role (offline)",
    "⁄⁄ (sin sync)": "⁄⁄ (no sync)",
    "\n[bold]Enlaces:[/bold]": "\n[bold]Links:[/bold]",
    "  [dim](ninguno)[/dim]": "  [dim](none)[/dim]",
    "\n[yellow]⚠ Posibles inconsistencias:[/yellow]":
        "\n[yellow]⚠ Possible inconsistencies:[/yellow]",
    "[red]No hay nada que deshacer (no se encontró undo.json).[/red]":
        "[red]Nothing to undo (no undo.json found).[/red]",
    "[red]El undo.json está corrupto o es de una versión anterior — no se puede deshacer.[/red]":
        "[red]undo.json is corrupt or from an older version — cannot undo.[/red]",
    "URL de Syncthing (por defecto, la del último rename).":
        "Syncthing URL (defaults to the last rename's).",
    "Tras revertir, esperar a los offline y revertirlos al reconectar.":
        "After reverting, wait for offline devices and revert them when they reconnect.",
    "[bold]Deshacer último rename:[/bold]": "[bold]Undo last rename:[/bold]",
    "Revirtiendo...": "Reverting...",
    "\n[cyan]Revertir ID: «{}» → «{}»[/cyan]": "\n[cyan]Revert ID: «{}» → «{}»[/cyan]",
    "  [green]✓ {} — ID revertido[/green]": "  [green]✓ {} — ID reverted[/green]",
    "Nombre del dispositivo destino": "Target device name",
    "ID de Syncthing del dispositivo (habilita verificación de identidad)":
        "Syncthing device ID (enables identity verification)",
    "Nuevo label de la carpeta": "New folder label",
    "Nuevo nombre de directorio o ruta absoluta": "New directory name or absolute path",
    "Ruta actual de la carpeta en el dispositivo destino":
        "Current folder path on the target device",
    "API Key de Syncthing en el dispositivo destino":
        "Syncthing API key on the target device",
    "Plataforma destino: windows, linux o macos": "Target platform: windows, linux or macos",
    "Arquitectura destino para Linux/macOS: amd64 o arm64 (Windows la ignora — "
    "el .exe x64 corre en Windows-ARM por emulación). Por defecto: la del equipo (Linux) "
    "o la arch macOS embebida (amd64 si está, si no arm64).":
        "Target architecture for Linux/macOS: amd64 or arm64 (Windows ignores it — "
        "the x64 .exe runs on Windows-ARM via emulation). Defaults to the current machine "
        "(Linux) or the embedded macOS arch (amd64 if present, else arm64).",
    "Cambiar también el ID de la carpeta": "Also change the folder ID",
    "API Key del nodo local (para descubrir carpetas)":
        "Local node API key (to discover folders)",
    "Nuevo nombre/ruta en disco": "New on-disk name/path",
    "Ruta actual de la carpeta en el dispositivo destino\n"
    "(deja vacío si quieres que el agente use la detección automática)":
        "Current folder path on the target device\n"
        "(leave empty to let the agent use auto-detection)",
    "API Key de Syncthing en el dispositivo destino\n"
    "(vacío = el agente intentará detectarla automáticamente)":
        "Syncthing API key on the target device\n"
        "(empty = the agent will try to detect it automatically)",
    "ID de Syncthing del dispositivo\n"
    "(encuéntralo en Syncthing → Acciones → Identificación del dispositivo)\n"
    "(deja vacío para omitir verificación de identidad)":
        "Syncthing device ID\n"
        "(find it in Syncthing → Actions → Show ID)\n"
        "(leave empty to skip identity verification)",
    "[yellow]⚠  Sin ID de dispositivo — el agente no verificará identidad y se ejecutará en cualquier máquina.[/yellow]":
        "[yellow]⚠  No device ID — the agent will not verify identity and will run on any machine.[/yellow]",
    "[dim]Cópialo al dispositivo destino y ejecútalo directamente.[/dim]":
        "[dim]Copy it to the target device and run it directly.[/dim]",
    "[dim]No requiere Python ni instalación adicional.[/dim]":
        "[dim]No Python or extra installation required.[/dim]",
    "Detalle": "Detail",
    "[red]No se pudo leer el ID del nodo local: {}[/red]":
        "[red]Could not read the local node ID: {}[/red]",
    "\n[yellow]--- DRY RUN: no se realizará ningún cambio ---[/yellow]":
        "\n[yellow]--- DRY RUN: no changes will be made ---[/yellow]",
    "  Contraseña maestra": "  Master password",
    "  [dim]── SSH ──[/dim]": "  [dim]── SSH ──[/dim]",
    "  [dim]── WinRM (Windows) ──[/dim]": "  [dim]── WinRM (Windows) ──[/dim]",
})

# ── Backend layer (renamer / discovery / validation / topology / generate / ssh / winrm /
# syncthing / credentials / device_names): result, error, validation and status messages that
# surface in the UI via result.message / .error / .warning, exceptions and device status. ──
EN.update({
    "el nombre está vacío": "the name is empty",
    "«.» y «..» no son nombres de carpeta válidos": "«.» and «..» are not valid folder names",
    "contiene un carácter NUL": "contains a NUL character",
    "caracteres no válidos en Windows: ": "invalid characters on Windows: ",
    "«{}» es un nombre reservado en Windows": "«{}» is a reserved name on Windows",
    "no puede terminar en espacio ni punto (Windows lo recorta)": "cannot end in a space or dot (Windows trims it)",
    "el nombre es demasiado largo (>255 caracteres)": "the name is too long (>255 characters)",
    "no puede contener «/»": "cannot contain «/»",
    "el nombre es demasiado largo (>255 bytes)": "the name is too long (>255 bytes)",
    "la ruta/el nombre está vacío": "the path/name is empty",
    "es una ruta de Windows (C:\\…) pero este dispositivo es Linux": "it's a Windows path (C:\\…) but this device is Linux",
    "es una ruta de Windows (C:\\…) pero este dispositivo no es Windows": "it's a Windows path (C:\\…) but this device is not Windows",
    "es una ruta POSIX (/…) pero este dispositivo es Windows": "it's a POSIX path (/…) but this device is Windows",
    "la ruta supera el límite de longitud de Windows (~260)": "the path exceeds the Windows length limit (~260)",
    "/rest/system/status sin 'myID' (respuesta inesperada)": "/rest/system/status without 'myID' (unexpected response)",
    "respuesta inesperada para la carpeta «{}»": "unexpected response for folder «{}»",
    "Contraseña maestra incorrecta — no se pudieron descifrar las credenciales.": "Wrong master password — could not decrypt the credentials.",
    "El archivo de credenciales está cifrado; guardarlo ahora sin la contraseña maestra lo degradaría a texto plano. Proporciona la contraseña maestra para volver a guardarlo cifrado.": "The credentials file is encrypted; saving it now without the master password would downgrade it to plaintext. Provide the master password to save it encrypted again.",
    "Sin API key — no se puede actualizar la config": "No API key — cannot update the config",
    "puerto SSH {} cerrado o inalcanzable": "SSH port {} closed or unreachable",
    "puerto WinRM {} cerrado o inalcanzable": "WinRM port {} closed or unreachable",
    "API no expuesta en la LAN (se usará vía SSH)": "API not exposed on the LAN (will be used via SSH)",
    "API no expuesta en la LAN (se usará vía WinRM)": "API not exposed on the LAN (will be used via WinRM)",
    "Windows alcanzado por SSH, pero no gestionable por este canal todavía: configura WinRM, expón la API en la LAN, o usa el agente.": "Windows reached over SSH, but not manageable through this channel yet: configure WinRM, expose the API on the LAN, or use the agent.",
    "Sin acceso remoto: faltan credenciales SSH/WinRM válidas.": "No remote access: valid SSH/WinRM credentials are missing.",
    "credenciales SSH rechazadas (autenticación fallida)": "SSH credentials rejected (authentication failed)",
    "credenciales WinRM rechazadas ({})": "WinRM credentials rejected ({})",
    "config.xml remoto con DTD/ENTITY rechazado (posible expansión maliciosa)": "remote config.xml with DTD/ENTITY rejected (possible malicious expansion)",
    "La lista de dispositivos está vacía.": "The device list is empty.",
    "Plantilla de agente {} no encontrada.\nCompílala con:\n  python -m PyInstaller build/agent_{}.spec": "Agent template {} not found.\nBuild it with:\n  python -m PyInstaller build/agent_{}.spec",
    "El dispositivo no tiene un ID de Syncthing conocido.\nDescúbrelo primero desde la pantalla de descubrimiento.": "The device has no known Syncthing ID.\nDiscover it first from the discovery screen.",
    "El dispositivo no tiene API Key.\nEdita sus credenciales antes de generar el agente.": "The device has no API key.\nEdit its credentials before generating the agent.",
    "Ruta vacía — no se borra": "Empty path — nothing is deleted",
    "No parece una carpeta de Syncthing (falta .stfolder): {}": "Doesn't look like a Syncthing folder (.stfolder missing): {}",
    "rm -rf falló: {}": "rm -rf failed: {}",
    "el borrado no surtió efecto — la ruta sigue existiendo: {} (¿resolución de ~ / ruta incorrecta?)": "the deletion had no effect — the path still exists: {} (~ resolution / wrong path?)",
    "Syncthing API {} {}: sin estado HTTP (¿curl no instalado?): {}": "Syncthing API {} {}: no HTTP status (curl not installed?): {}",
    "(sin cuerpo)": "(no body)",
    "pywinrm no está instalado. Instálalo con: pip install pywinrm requests-ntlm": "pywinrm is not installed. Install it with: pip install pywinrm requests-ntlm",
    "Este equipo": "This device",
    "«{}»: sin ruta de carpeta definida.": "«{}»: no folder path defined.",
    "«{}»: sin enlaces (no sincroniza con nadie).": "«{}»: no links (does not sync with anyone).",
    "«{}» — «{}»: ningún extremo envía (no se sincroniza).": "«{}» — «{}»: neither endpoint sends (it does not sync).",
    "«{}» — «{}»: dirección no realizable — ambos quedan envía/recibe por sus otros enlaces (será bidireccional).": "«{}» — «{}»: unachievable direction — both end up send/receive through their other links (it will be bidirectional).",
    # renamer
    " ⚠ sin acceso de shell (solo API): crea el directorio a mano en el dispositivo o genera un agente": " ⚠ no shell access (API only): create the directory by hand on the device or generate an agent",
    " ⚠ no se pudo crear el directorio: {}": " ⚠ could not create the directory: {}",
    "Sin acceso API, SSH ni WinRM": "No API, SSH or WinRM access",
    "Credenciales SSH no válidas ({}) — corrígelas y reintenta para renombrar el directorio en {}": "Invalid SSH credentials ({}) — fix them and retry to rename the directory on {}",
    "Sin acceso SSH — renombra el directorio manualmente en {}:\n  {!r}  →  {!r}\n  (la config mantiene la ruta antigua para no romper la carpeta; usa el agente para automatizarlo)": "No SSH access — rename the directory manually on {}:\n  {!r}  →  {!r}\n  (the config keeps the old path so the folder isn't broken; use the agent to automate it)",
    "  —  algo está usando la carpeta (Explorador abierto en ella, un fichero abierto, antivirus). Ciérralo y reintenta.": "  —  something is using the folder (Explorer open in it, an open file, antivirus). Close it and retry.",
    "  —  ya existe una carpeta con ese nombre en el destino (no se sobrescribe para no perder datos). Bórrala o elige otro nombre.": "  —  a folder with that name already exists at the destination (not overwritten to avoid data loss). Delete it or choose another name.",
    "no se pudo leer la ruta de la carpeta (error transitorio: {}); se reintentará": "could not read the folder path (transient error: {}); it will be retried",
    "Ruta de carpeta desconocida — no se puede actualizar la config de Syncthing": "Unknown folder path — cannot update the Syncthing config",
    "Config actualizada en {} pero no se pudo confirmar el reinicio de Syncthing — reinícialo para aplicar los cambios.": "Config updated on {} but Syncthing's restart could not be confirmed — restart it to apply the changes.",
    "Sin acceso a API para cambiar la ruta": "No API access to change the path",
    "Sin acceso API/SSH/WinRM — usa el agente": "No API/SSH/WinRM access — use the agent",
    "¡CARPETA PERDIDA! borrada pero no se pudo recrear: {}": "FOLDER LOST! deleted but could not be recreated: {}",
    "\nLa configuración original se guardó en:\n  {}\nLos archivos en disco siguen intactos. Vuelve a añadir la carpeta en Syncthing (ese archivo JSON contiene la configuración original).": "\nThe original configuration was saved in:\n  {}\nThe files on disk are intact. Re-add the folder in Syncthing (that JSON file holds the original configuration).",
    "Carpeta «{}» no encontrada": "Folder «{}» not found",
    "Revertido (creación falló): {}": "Reverted (creation failed): {}",
    "Carpeta «{}» no encontrada (SSH)": "Folder «{}» not found (SSH)",
    "No se pudo leer «{}» (SSH): {}": "Could not read «{}» (SSH): {}",
    "Carpeta «{}» no encontrada (WinRM)": "Folder «{}» not found (WinRM)",
    "No se pudo leer «{}» (WinRM): {}": "Could not read «{}» (WinRM): {}",
    "carpeta creada": "folder created",
    " ⚠ la carpeta está PAUSADA aquí — reanúdala para que sincronice": " ⚠ the folder is PAUSED here — resume it so it syncs",
    "config actualizada (diff)": "config updated (diff)",
    "¡CONFIG DE CARPETA PERDIDA! «{}»: se borró para moverla a la ruta nueva y no se pudo recrear ni la nueva ni la original. Los datos en disco siguen intactos — vuelve a añadir la carpeta en Syncthing": "FOLDER CONFIG LOST! «{}»: it was deleted to move it to the new path and neither the new nor the original could be recreated. The data on disk is intact — re-add the folder in Syncthing",
    " (config original guardada en {})": " (original config saved in {})",
    ". Causa: {}": ". Cause: {}",
    "no está en la topología (sin cambios)": "not in the topology (no changes)",
    "[dry-run] se dejaría de compartir (sin enlaces)": "[dry-run] would stop sharing (no links)",
    "[dry-run] +{}/−{} enlace(s)": "[dry-run] +{}/−{} link(s)",
    ", rol→{}": ", role→{}",
    "[dry-run] rol={}, {} vecino(s)": "[dry-run] role={}, {} neighbour(s)",
    "carpeta dejada de compartir (sin enlaces)": "folder stopped being shared (no links)",
    "sin cambios para este dispositivo": "no changes for this device",
    "{}: +{}/−{} enlace(s)": "{}: +{}/−{} link(s)",
    ", +{} disp.": ", +{} dev.",
    "{}: rol={}, {} vecino(s), +{} disp.": "{}: role={}, {} neighbour(s), +{} dev.",
    "ruta corregida → {}": "path fixed → {}",
    "no se pudo leer la config (no se crea, para no sobrescribir la carpeta existente): {}": "could not read the config (not created, to avoid overwriting the existing folder): {}",
    "sin cambios de carpeta": "no folder changes",
    "[dry-run] config de carpeta: {} campo(s)": "[dry-run] folder config: {} field(s)",
    "la carpeta no existe aquí (config omitida)": "the folder does not exist here (config skipped)",
    "config de carpeta aplicada ({} campo(s))": "folder config applied ({} field(s))",
    "no se pudo leer la config (SSH): {}": "could not read the config (SSH): {}",
    "la carpeta no existe aquí (SSH)": "the folder does not exist here (SSH)",
    "config de carpeta aplicada (SSH)": "folder config applied (SSH)",
    "no se pudo leer la config (WinRM): {}": "could not read the config (WinRM): {}",
    "la carpeta no existe aquí (WinRM)": "the folder does not exist here (WinRM)",
    "config de carpeta aplicada (WinRM)": "folder config applied (WinRM)",
    "carpeta ya no existe": "folder no longer exists",
    "carpeta eliminada (config)": "folder removed (config)",
    "carpeta ya no existe (SSH)": "folder no longer exists (SSH)",
    "carpeta eliminada (SSH)": "folder removed (SSH)",
    "carpeta ya no existe (WinRM)": "folder no longer exists (WinRM)",
    "carpeta eliminada (WinRM)": "folder removed (WinRM)",
    "sin acceso (API/SSH/WinRM)": "no access (API/SSH/WinRM)",
    "ruta protegida o vacía, no se borra: {}": "protected or empty path, not deleted: {}",
    "no parece una carpeta de Syncthing (falta .stfolder): {}": "doesn't look like a Syncthing folder (.stfolder missing): {}",
    "ruta protegida del sistema, no se borra: {}": "protected system path, not deleted: {}",
    "borrar en disco requiere SSH/WinRM en este equipo": "deleting on disk requires SSH/WinRM on this device",
    "[dry-run] se quitaría de Syncthing y se borraría en disco: {}": "[dry-run] would be removed from Syncthing and deleted on disk: {}",
    "[dry-run] se quitaría de Syncthing (sin tocar disco)": "[dry-run] would be removed from Syncthing (disk untouched)",
    "no se conoce la ruta en disco": "the on-disk path is unknown",
    "no se pudo verificar la carpeta (acceso): {}": "could not verify the folder (access): {}",
    "falta .stfolder (¿directorio sin crear?): {}": ".stfolder missing (directory not created?): {}",
    "no se pudo quitar de Syncthing: {}": "could not remove from Syncthing: {}",
    "quitada de Syncthing; disco NO borrado ({})": "removed from Syncthing; disk NOT deleted ({})",
    "carpeta eliminada de Syncthing; en disco ya no existía ({})": "folder removed from Syncthing; it no longer existed on disk ({})",
    "quitada de Syncthing; disco NO borrado (requiere SSH/WinRM)": "removed from Syncthing; disk NOT deleted (requires SSH/WinRM)",
    "carpeta eliminada de Syncthing y borrada en disco ({})": "folder removed from Syncthing and deleted on disk ({})",
    "quitada de Syncthing, pero el borrado en disco falló: {}": "removed from Syncthing, but the on-disk deletion failed: {}",
    "no presente/alcanzable — la carpeta puede seguir en ese equipo": "not present/reachable — the folder may still be on that device",
    "aún compartido en otra carpeta": "still shared in another folder",
    "[dry-run] se quitaría del dispositivo": "[dry-run] would be removed from the device",
    "entrada de dispositivo eliminada": "device entry removed",
    "[dry-run] se eliminaría la carpeta aquí": "[dry-run] the folder would be removed here",
    "no accesible — no se pudo eliminar la carpeta aquí": "not reachable — could not remove the folder here",
    "no accesible — aún comparte con «{}»; añade credenciales y reintenta, o quítalo en ese equipo": "not reachable — still shares with «{}»; add credentials and retry, or remove it on that device",
    "[dry-run] se quitaría «{}» de la carpeta": "[dry-run] «{}» would be removed from the folder",
    "«{}» quitado de la carpeta": "«{}» removed from the folder",
    "no accesible — aún tiene vinculado al dispositivo; añade credenciales y reintenta, o desvincúlalo en ese equipo": "not reachable — still has the device linked; add credentials and retry, or unlink it on that device",
    "[dry-run] se desvincularía aquí": "[dry-run] would unlink here",
    "dispositivo desvinculado": "device unlinked",
    "nombre no válido — {}": "invalid name — {}",
    "el ID «{}» ya existe en este dispositivo": "the ID «{}» already exists on this device",
    "el destino ya existe: {}": "the destination already exists: {}",
    "puede que no haya permiso de escritura en {} (verifícalo)": "there may be no write permission in {} (check it)",
    "el destino está en otro sistema de archivos que el origen ({} → {}); un renombrado no puede cruzar discos": "the destination is on a different filesystem than the source ({} → {}); a rename cannot cross disks",
    "puede que Syncthing no tenga permiso de escritura en {} (usuario SSH ≠ usuario del servicio; verifícalo)": "Syncthing may not have write permission in {} (SSH user ≠ service user; check it)",
    "puede que Syncthing no tenga permiso de escritura en {} (usuario WinRM ≠ usuario del servicio; verifícalo)": "Syncthing may not have write permission in {} (WinRM user ≠ service user; check it)",
    "no se puede comprobar si el destino existe (solo API, sin SSH/WinRM)": "cannot check whether the destination exists (API only, no SSH/WinRM)",
    "no se pudieron completar las comprobaciones: {}": "the checks could not be completed: {}",
    "El destino está en otro sistema de archivos: {!r} → {!r}. Un renombrado solo cambia el nombre en el mismo disco; para mover los datos a otro volumen hazlo manualmente y reintenta con esa ruta.": "The destination is on a different filesystem: {!r} → {!r}. A rename only changes the name on the same disk; to move the data to another volume do it manually and retry with that path.",
    "La config no reflejó el cambio (label={!r})": "The config did not reflect the change (label={!r})",
    "reanudado (404 — la carpeta se reanuda al reiniciar)": "resumed (404 — the folder resumes on restart)",
    "¡CONFIG DE CARPETA PERDIDA! «{}» (SSH): se borró para recrearla y ni la nueva ni la original pudieron volver a crearse. Los datos en disco siguen intactos — vuelve a añadir la carpeta en Syncthing": "FOLDER CONFIG LOST! «{}» (SSH): it was deleted to recreate it and neither the new nor the original could be created again. The data on disk is intact — re-add the folder in Syncthing",
    "La ruta no se aplicó al recrear la carpeta (SSH)": "The path was not applied when recreating the folder (SSH)",
    "¡CONFIG DE CARPETA PERDIDA! «{}» (WinRM): se borró para recrearla y ni la nueva ni la original pudieron volver a crearse. Los datos en disco siguen intactos — vuelve a añadir la carpeta en Syncthing": "FOLDER CONFIG LOST! «{}» (WinRM): it was deleted to recreate it and neither the new nor the original could be created again. The data on disk is intact — re-add the folder in Syncthing",
    "La ruta no se aplicó al recrear la carpeta (WinRM)": "The path was not applied when recreating the folder (WinRM)",
    "¡CONFIG DE CARPETA PERDIDA! «{}»: se borró para recrearla y ni la nueva ni la original pudieron volver a crearse. Los datos en disco siguen intactos — vuelve a añadir la carpeta en Syncthing": "FOLDER CONFIG LOST! «{}»: it was deleted to recreate it and neither the new nor the original could be created again. The data on disk is intact — re-add the folder in Syncthing",
    "La ruta no se aplicó al recrear la carpeta": "The path was not applied when recreating the folder",
    "{}: Syncthing <1.12 alcanzable solo por API y sin acceso SSH/WinRM — actualiza Syncthing a ≥1.12 (o habilita SSH/WinRM) para renombrar la carpeta": "{}: Syncthing <1.12 reachable only via API and without SSH/WinRM access — update Syncthing to ≥1.12 (or enable SSH/WinRM) to rename the folder",
    "el borrado no surtió efecto — la ruta sigue existiendo: {}": "the deletion had no effect — the path still exists: {}",
    "destino": "destination",
})
