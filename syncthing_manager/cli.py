from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import urllib3
import typer
import yaml
from rich.console import Console
from rich.table import Table

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Make stdout/stderr UTF-8 (with replacement) as early as possible. Rich renders the CLI help and
# tables, and on a NON-UTF-8 stream its "legacy Windows" encoder raises UnicodeEncodeError on any
# non-ASCII glyph (→, á, …, table borders) and the CLI crashes (and the frozen windowed exe even
# hangs). This happens for a frozen WINDOWED Windows .exe with no console / redirected / piped
# output (cp1252), and for a Linux shell with LANG=C (ascii). A real terminal is already UTF-8;
# this only repairs the non-console case, and is a no-op where reconfigure isn't available.
import sys as _sys
for _stream in (_sys.stdout, _sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from .credentials import default_credentials_path, load_credentials, needs_master_password, save_credentials
from .discovery import discover_devices, probe_device, probe_device_manual, detect_local_syncthing
from .generate import agent_template_available, generate_agent_file, generate_legacy_agent_file, generate_multi_agent_file
from .models import DeviceInfo, RenameResult
from .renamer import is_absolute_path, rename_all_devices
from .syncthing import SyncthingClient, SyncthingError
from . import config as appconfig
from . import i18n
from .i18n import t as _T

# Resolve the language BEFORE the Typer app/commands are defined, so `--help` text (captured
# at decoration time) is in the right language. Order: an explicit --lang on the command line
# → stored preference → OS language. We peek at argv here because Typer only parses --lang in
# the callback, which runs after the help strings have already been captured.
def _early_lang_pref() -> str:
    import sys
    for i, a in enumerate(sys.argv):
        if a == "--lang" and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if a.startswith("--lang="):
            return a.split("=", 1)[1]
    return appconfig.get_setting("language", "auto")


i18n.set_language(_early_lang_pref())

app = typer.Typer(
    name="syncthing-manager",
    add_completion=False,
    # A bare invocation in a terminal prints help (instead of a "Missing command" error) — the
    # single frozen binary routes a bare-in-terminal launch here, so help is the friendly default.
    no_args_is_help=True,
)


@app.callback()
def _global_options(
    verbose: bool = typer.Option(False, "--verbose", "-v", help=_T("Mostrar logs de depuración (DEBUG)")),
    lang: Optional[str] = typer.Option(
        None, "--lang", help=_T("Idioma de la interfaz: «es» o «en» (por defecto, el del sistema).")),
) -> None:
    _setup_logging(verbose)
    if lang:                      # runtime override for messages printed by the commands
        i18n.set_language(lang)
console = Console()
err_console = Console(stderr=True)


def _ask_agent_passphrase() -> Optional[str]:
    """Offer to encrypt the agent's embedded config (which holds the Syncthing API
    key). Returns the passphrase, or None to embed in plaintext. Asked interactively
    so the secret never lands on the command line / shell history."""
    import getpass
    console.print(
        _T("\n[bold]Cifrado del agente[/bold] — el ejecutable lleva embebida la API Key.\n"
           "[dim]Con contraseña, nadie puede extraerla del binario; se pedirá al ejecutar "
           "el agente. Déjalo vacío para no cifrar (NO recomendado).[/dim]")
    )
    try:
        pw = getpass.getpass(_T("Contraseña (vacío = sin cifrar): "))
    except (EOFError, KeyboardInterrupt):
        return None
    if not pw:
        console.print(_T("[yellow]⚠  Agente sin cifrar: la API Key será legible en el binario.[/yellow]"))
        return None
    pw2 = getpass.getpass(_T("Repite la contraseña: "))
    if pw != pw2:
        err_console.print(_T("[red]Las contraseñas no coinciden — se generará SIN cifrar.[/red]"))
        return None
    return pw


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def _get_client(
    api_key: Optional[str],
    base_url: str = "https://127.0.0.1:8384",
    no_verify_ssl: bool = True,
) -> SyncthingClient:
    detected = detect_local_syncthing()
    key = api_key or detected.get("api_key")
    if not key:
        console.print(_T("[yellow]API Key no detectada automáticamente.[/yellow]"))
        key = typer.prompt(_T("Syncthing API Key"))

    verify = not no_verify_ssl
    # Try the requested URL first, then the URL resolved from config / WSL fallback
    # (correct scheme+port, and the Windows host IP when Syncthing runs on Windows).
    tried: list[str] = []
    for url in (base_url, detected.get("url")):
        if not url or url in tried:
            continue
        tried.append(url)
        client = SyncthingClient(url, key, verify_ssl=verify)
        if client.ping_status() == "ok":
            if url != base_url:
                console.print(_T("[dim]Conectado a Syncthing en {}[/dim]").format(url))
            return client

    # No connection — give a precise diagnosis.
    status = detected.get("status")
    if status == "installed_not_running":
        err_console.print(_T("[red]Syncthing está instalado pero no parece estar en ejecución.[/red]"))
        err_console.print(_T("[dim]Arráncalo (p. ej. systemctl --user start syncthing, o abre la app) y reintenta.[/dim]"))
    elif status == "bad_auth":
        err_console.print(_T("[red]Syncthing responde pero la API Key no es válida.[/red]"))
        err_console.print(_T("[dim]Revisa la key en Acciones → Configuración → General.[/dim]"))
    elif status == "not_found":
        err_console.print(_T("[red]No se detecta Syncthing — ¿está instalado y se ha ejecutado al menos una vez?[/red]"))
    else:
        err_console.print(_T('[red]No se puede conectar a Syncthing en {}[/red]').format(base_url))
    raise typer.Exit(1)


def _load_devices_config(config_path: Optional[Path]) -> list[dict]:
    if config_path is None:
        default = Path("devices.yml")
        config_path = default if default.exists() else None
    if config_path is None:
        return []
    try:
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
        defaults = data.get("defaults", {})
        devices = data.get("devices", [])
        for d in devices:
            for k, v in defaults.items():
                d.setdefault(k, v)
        return devices
    except Exception as e:
        err_console.print(_T('[yellow]Warning: no se pudo cargar {}: {}[/yellow]').format(config_path, e))
        return []


def _pick_folder(client: SyncthingClient, folder_id: Optional[str]):
    folders = client.get_folders()
    if not folders:
        err_console.print(_T("[red]No hay carpetas configuradas en Syncthing.[/red]"))
        raise typer.Exit(1)

    if folder_id:
        match = next((f for f in folders if f.id == folder_id), None)
        if not match:
            err_console.print(_T("[red]Folder ID {!r} no encontrado.[/red]").format(folder_id))
            raise typer.Exit(1)
        return match

    table = Table(title=_T("Carpetas Syncthing"), show_lines=True, expand=False)
    table.add_column("#",                style="cyan", width=4,  no_wrap=True)
    table.add_column("ID",               style="dim",  min_width=10, no_wrap=True)
    table.add_column("Label",            min_width=12)
    table.add_column(_T("Ruta"),         min_width=16, ratio=1)
    table.add_column(_T("Dispositivos"), min_width=4,  justify="right", no_wrap=True)
    for i, f in enumerate(folders, 1):
        table.add_row(str(i), f.id, f.label or f.id, f.path, str(len(f.devices)))
    console.print(table)

    choice = typer.prompt(_T("Selecciona carpeta por # o ID"))
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(folders):
            return folders[idx]
    else:
        match = next((f for f in folders if f.id == choice), None)
        if match:
            return match

    err_console.print(_T("[red]Selección inválida.[/red]"))
    raise typer.Exit(1)


def _load_saved_credentials() -> list[dict]:
    """Load saved credentials, prompting for master password if the file is encrypted."""
    if not needs_master_password():
        return load_credentials()
    console.print(_T("[dim]Las credenciales guardadas están cifradas.[/dim]"))
    for _attempt in range(3):
        master_pw = typer.prompt(_T("Contraseña maestra"), hide_input=True)
        try:
            return load_credentials(master_password=master_pw)
        except ValueError:
            console.print(_T("[red]Contraseña incorrecta — inténtalo de nuevo.[/red]"))
    err_console.print(_T("[red]Demasiados intentos fallidos. Se omiten las credenciales guardadas.[/red]"))
    return []


# ── Persistent undo (parity with the GUI's Deshacer) ──────────────────────────
def _undo_path() -> Path:
    from .config import data_dir
    return data_dir() / "undo.json"


def _save_undo_snapshot(snap: dict) -> None:
    """Persist enough to revert the last rename: original label, on-disk path,
    folder ID, and how it was applied. Failure to write is non-fatal."""
    import json
    p = _undo_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(snap, indent=2, ensure_ascii=False), encoding="utf-8")
        import os as _os
        _os.replace(tmp, p)
    except Exception as e:
        logging.getLogger(__name__).debug("No se pudo guardar el snapshot de deshacer: %s", e)


def _load_undo_snapshot() -> Optional[dict]:
    import json
    try:
        return json.loads(_undo_path().read_text(encoding="utf-8")) or None
    except Exception:
        return None


def _clear_undo_snapshot() -> None:
    try:
        _undo_path().unlink()
    except Exception:
        pass


def _run_passive(
    client: SyncthingClient,
    folder,
    merged_cfg: list[dict],
    pending: list[DeviceInfo],
    new_label: str,
    new_dir_name: str,
    skip_path_rename: bool,
    do_id_rename: bool,
    new_folder_id: str,
    interval: int = 15,
) -> None:
    """Keep watching for the given offline devices and apply the rename as each one
    reconnects, until all are done or the user presses Ctrl-C. Mirrors the GUI's
    passive exploration (label/path/ID only; topology stays GUI-only)."""
    import time
    from .renamer import rename_on_device, rename_folder_id

    pending_ids = {d.device_id for d in pending}
    console.print(
        _T('\n[cyan]Exploración pasiva activa[/cyan] — esperando a {} dispositivo(s) offline. Pulsa Ctrl-C para terminar.\n[dim]Se aplicará el cambio en cuanto cada equipo vuelva a estar accesible.[/dim]').format(len(pending_ids))
    )

    def _actionable(d: DeviceInfo) -> bool:
        return d.is_local or d.api_reachable or d.ssh_reachable or d.winrm_reachable

    try:
        while pending_ids:
            time.sleep(interval)
            try:
                devices = discover_devices(client, folder, merged_cfg)
            except Exception as e:
                console.print(_T('[dim]Re-descubrimiento falló: {}[/dim]').format(e))
                continue
            ready = [d for d in devices if d.device_id in pending_ids and _actionable(d)]
            if not ready:
                continue
            for dev in ready:
                console.print(_T('[cyan]⟳ {} en línea — aplicando…[/cyan]').format(dev.name))
                r = rename_on_device(dev, folder.id, new_label, new_dir_name,
                                     dry_run=False, skip_path_rename=skip_path_rename)
                id_msg = ""
                if do_id_rename and r.config_updated:
                    idr = rename_folder_id([dev], folder.id, new_folder_id, dry_run=False)
                    if idr and idr[0][1]:
                        id_msg = f", ID→«{new_folder_id}»"
                    elif idr:
                        id_msg = _T(', ID falló: {}').format(idr[0][2])
                if r.success:
                    console.print(_T('  [green]✓ {} configurado por pasiva{}[/green]').format(dev.name, id_msg))
                    pending_ids.discard(dev.device_id)
                elif r.left_paused:
                    console.print(_T('  [red]⚠ {} — sync PAUSADA: {}{}[/red]').format(dev.name, r.error, id_msg))
                    pending_ids.discard(dev.device_id)
                else:
                    console.print(_T('  [yellow]⚠ {} — {}{} (se reintentará)[/yellow]').format(dev.name, r.error or _T('parcial'), id_msg))
        console.print(_T("\n[green]✓ Todos los dispositivos pendientes se han configurado.[/green]"))
    except KeyboardInterrupt:
        if pending_ids:
            names = {d.device_id: d.name for d in pending}
            faltan = ", ".join(names.get(i, i[:7]) for i in pending_ids)
            console.print(_T('\n[yellow]Pasiva interrumpida. Sin configurar: {}.[/yellow]').format(faltan))
        else:
            console.print(_T("\n[green]Pasiva finalizada.[/green]"))


def _print_discovery_table(devices: list[DeviceInfo]) -> None:
    table = Table(title=_T("Dispositivos descubiertos"), show_lines=True, expand=False)
    table.add_column(_T("Nombre"),        min_width=14, no_wrap=True)
    table.add_column("IP",                min_width=15, no_wrap=True)
    table.add_column(_T("Remoto"),        min_width=10, no_wrap=True)
    table.add_column("API",               min_width=14, no_wrap=True)
    table.add_column(_T("Ruta en disco"), min_width=16, ratio=1, no_wrap=True, overflow="ellipsis")

    for d in devices:
        if d.is_local:
            remote_st = "[dim]local[/dim]"
            api_st    = _T("[green]✓ directa[/green]")
        else:
            if d.ssh_reachable:
                remote_st = "[green]SSH ✓[/green]"
            elif d.winrm_reachable:
                remote_st = "[green]WinRM ✓[/green]"
            else:
                err = (d.ssh_error or "")[:30]
                remote_st = f"[red]✗ {err}[/red]" if err else "[red]✗[/red]"
            if d.api_reachable:
                api_st = _T("[green]✓ directa[/green]")
            elif d.api_key and (d.ssh_reachable or d.winrm_reachable):
                api_st = _T("[dim]vía remoto[/dim]")
            elif d.api_key:
                api_st = _T("[yellow]⚠ key OK, no alcanzable[/yellow]")
            else:
                api_st = _T("[red]— sin key[/red]")
        table.add_row(d.name, d.ip or "(offline)", remote_st, api_st, d.folder_path or "—")
    console.print(table)


def _interactive_fix_devices(
    devices: list[DeviceInfo],
    folder_id: str,
) -> list[DeviceInfo]:
    """
    For each unreachable remote device, offer an interactive prompt to enter
    credentials manually and retry the probe.
    Returns an updated list with fixed DeviceInfo objects where possible.
    """
    fixed = list(devices)
    def _device_needs_fix(d: DeviceInfo) -> bool:
        return not d.is_local and not d.api_reachable and not d.ssh_reachable and not d.winrm_reachable

    failed = [d for d in fixed if _device_needs_fix(d)]

    if not failed:
        return fixed

    console.print(_T('\n[yellow]⚠  {} dispositivo(s) sin ningún acceso disponible.[/yellow]').format(len(failed)))
    for dev in failed:
        error = dev.ssh_error or dev.api_error or "desconocido"
        console.print(_T('\n[bold]  Dispositivo:[/bold] {}  [dim]({})[/dim]').format(dev.name, dev.ip or 'sin IP'))
        console.print(_T('  [red]Error:[/red] {}').format(error))
        console.print(
            _T("  Opciones: [1] Introducir credenciales manualmente  "
               "[2] Reintentar SSH  [3] Saltar este dispositivo")
        )
        choice = typer.prompt(_T("  Opción"), default="3")

        if choice == "1":
            ip        = typer.prompt(_T("  IP o hostname"), default=dev.ip or "")
            api_url   = typer.prompt(_T("  URL de la API"), default=dev.api_url or "http://127.0.0.1:8384")
            api_key   = typer.prompt(_T("  API Key"), default=dev.api_key or "")
            fp        = typer.prompt(_T("  Ruta de la carpeta en este dispositivo"), default=dev.folder_path or "")
            console.print(_T("  [dim]── SSH ──[/dim]"))
            ssh_user  = typer.prompt(_T("  Usuario SSH (vacío = no SSH)"), default=dev.ssh_user or "")
            ssh_key   = typer.prompt(_T("  Clave privada SSH (vacío = contraseña)"), default=dev.ssh_key_path or "")
            ssh_pass  = typer.prompt(_T("  Contraseña SSH"), default="", hide_input=True)
            ssh_port  = typer.prompt(_T("  Puerto SSH"), default=str(dev.ssh_port))
            console.print(_T("  [dim]── WinRM (Windows) ──[/dim]"))
            winrm_user = typer.prompt(_T("  Usuario WinRM (vacío = no WinRM)"), default=dev.winrm_user or "")
            winrm_pass = typer.prompt(_T("  Contraseña WinRM"), default="", hide_input=True) if winrm_user else ""
            winrm_port = typer.prompt(_T("  Puerto WinRM"), default=str(dev.winrm_port)) if winrm_user else "5985"

            has_ssh_creds   = bool(ssh_user or ssh_key or ssh_pass)
            has_winrm_creds = bool(winrm_user and winrm_pass)
            try:
                _ssh_port_int   = int(ssh_port or 22)
                _winrm_port_int = int(winrm_port or 5985)
            except ValueError:
                console.print(_T("[red]Puerto inválido — debe ser un número. Operación cancelada.[/red]"))
                continue
            override = {
                "ssh_user": ssh_user or None, "ssh_key_path": ssh_key or None,
                "ssh_password": ssh_pass or None, "ssh_port": _ssh_port_int,
                "winrm_user": winrm_user or None, "winrm_password": winrm_pass or None,
                "winrm_port": _winrm_port_int,
            }
            import dataclasses as _dc
            if has_ssh_creds or has_winrm_creds:
                # Full SSH/WinRM probe — discovers api_key from config.xml
                with console.status(_T("Conectando vía SSH/WinRM...")):
                    new_dev = probe_device(
                        device_id=dev.device_id, name=dev.name,
                        ip=ip, folder_id=folder_id, override=override,
                    )
                # Override with anything the user explicitly entered
                final_key  = api_key  or new_dev.api_key
                final_url  = api_url  or new_dev.api_url
                final_path = fp       or new_dev.folder_path
                new_dev = _dc.replace(new_dev,
                    api_key=final_key, api_url=final_url, folder_path=final_path)
            else:
                with console.status(_T("Verificando API...")):
                    new_dev = probe_device_manual(
                        device_id=dev.device_id, name=dev.name,
                        ip=ip, folder_id=folder_id,
                        api_key=api_key, api_url=api_url, folder_path=fp,
                    )
            if new_dev.api_reachable:
                console.print(_T("  [green]✓ {} — API accesible directamente[/green]").format(dev.name))
            elif new_dev.ssh_reachable:
                console.print(_T('  [green]✓ {} — SSH OK, api_key descubierta vía SSH[/green]').format(dev.name))
            elif new_dev.winrm_reachable:
                console.print(_T('  [green]✓ {} — WinRM OK, api_key descubierta vía WinRM[/green]').format(dev.name))
            else:
                console.print(_T("  [yellow]⚠ Sin acceso — se intentará de todas formas si hay api_key[/yellow]"))
            idx = next(i for i, d in enumerate(fixed) if d.device_id == dev.device_id)
            fixed[idx] = new_dev

        elif choice == "2":
            ip         = typer.prompt(_T("  IP"), default=dev.ip or "")
            console.print(_T("  [dim]── SSH ──[/dim]"))
            ssh_user   = typer.prompt(_T("  Usuario SSH"), default=dev.ssh_user or "")
            ssh_key    = typer.prompt(_T("  Clave privada SSH (vacío = contraseña)"), default=dev.ssh_key_path or "")
            ssh_pass   = typer.prompt(_T("  Contraseña SSH"), default="", hide_input=True)
            ssh_port   = typer.prompt(_T("  Puerto SSH"), default=str(dev.ssh_port))
            console.print(_T("  [dim]── WinRM (Windows) ──[/dim]"))
            winrm_user = typer.prompt(_T("  Usuario WinRM (vacío = no WinRM)"), default=dev.winrm_user or "")
            winrm_pass = typer.prompt(_T("  Contraseña WinRM"), default="", hide_input=True) if winrm_user else ""
            winrm_port = typer.prompt(_T("  Puerto WinRM"), default=str(dev.winrm_port)) if winrm_user else "5985"
            try:
                _ssh_port_int2   = int(ssh_port or 22)
                _winrm_port_int2 = int(winrm_port or 5985)
            except ValueError:
                console.print(_T("[red]Puerto inválido — debe ser un número. Operación cancelada.[/red]"))
                continue
            override = {
                "ssh_user": ssh_user or None, "ssh_key_path": ssh_key or None,
                "ssh_password": ssh_pass or None, "ssh_port": _ssh_port_int2,
                "winrm_user": winrm_user or None, "winrm_password": winrm_pass or None,
                "winrm_port": _winrm_port_int2,
            }
            with console.status(_T("Probando {}...").format(ip)):
                new_dev = probe_device(
                    device_id=dev.device_id, name=dev.name,
                    ip=ip, folder_id=folder_id, override=override,
                )
            if new_dev.api_reachable:
                console.print(_T("  [green]✓ {} — API accesible directamente[/green]").format(dev.name))
            elif new_dev.ssh_reachable:
                console.print(_T('  [green]✓ {} — SSH OK (API solo en localhost del dispositivo, es normal)[/green]').format(dev.name))
            elif new_dev.winrm_reachable:
                console.print(_T('  [green]✓ {} — WinRM OK (API solo en localhost del dispositivo, es normal)[/green]').format(dev.name))
            else:
                console.print(_T("  [red]✗ Sigue fallando: {}[/red]").format(new_dev.ssh_error or new_dev.api_error))
            idx = next(i for i, d in enumerate(fixed) if d.device_id == dev.device_id)
            fixed[idx] = new_dev
        # choice == "3" → leave as-is (will be skipped)

    _offer_save_credentials(fixed)
    return fixed


def _offer_save_credentials(devices: list[DeviceInfo]) -> None:
    remote = [d for d in devices if not d.is_local]
    if not remote:
        return

    path = default_credentials_path()
    console.print(_T('\n[dim]Ruta de credenciales:[/dim] {}').format(path))

    if not typer.confirm(_T("¿Guardar credenciales para próximas sesiones?"), default=False):
        return

    has_secrets = any((d.ssh_password or d.winrm_password or d.api_key) for d in remote)
    master_pw = None
    if has_secrets:
        console.print(_T("[dim]Puedes cifrar contraseñas y API keys con una contraseña maestra.[/dim]"))
        if typer.confirm(_T("  ¿Cifrar credenciales sensibles?"), default=True):
            master_pw = typer.prompt(_T("  Contraseña maestra"), hide_input=True)
            confirm   = typer.prompt(_T("  Confirmar contraseña"), hide_input=True)
            while master_pw != confirm:
                console.print(f"[red]  {_T('Las contraseñas no coinciden.')}[/red]")
                master_pw = typer.prompt(_T("  Contraseña maestra"), hide_input=True)
                confirm   = typer.prompt(_T("  Confirmar contraseña"), hide_input=True)

    try:
        # The CLI prompt is an EXPLICIT, interactive choice — if the user declined encryption
        # (master_pw is None) we honour it even when the existing store was encrypted, rather
        # than have save_credentials' anti-silent-downgrade guard reject their stated choice.
        save_credentials(devices, master_password=master_pw,
                         allow_plaintext_downgrade=(master_pw is None))
        note = _T(" (cifradas con contraseña maestra)") if master_pw else ""
        console.print(_T("[green]✓ Guardadas en {}{}[/green]").format(path, note))
    except Exception as e:
        console.print(_T('[red]Error al guardar: {}[/red]').format(e))


def _print_results_table(results: list[RenameResult]) -> None:
    table = Table(title=_T("Resultados"), show_lines=True, expand=False)
    table.add_column(_T("Dispositivo"), min_width=14)
    table.add_column(_T("Pausado"),     min_width=7,  justify="center", no_wrap=True)
    table.add_column(_T("Disco"),       min_width=7,  justify="center", no_wrap=True)
    table.add_column("Config",          min_width=7,  justify="center", no_wrap=True)
    table.add_column(_T("Reanudado"),   min_width=9,  justify="center", no_wrap=True)
    table.add_column(_T("Estado"),      min_width=16)

    paused_names = []
    manual_steps = []
    for r in results:
        if r.success and not r.warning:
            status = "[green]✓ OK[/green]"
        elif r.success and r.warning:
            status = _T("[yellow]⚠ Manual requerido[/yellow]")
            manual_steps.append((r.device.name, r.warning))
        elif r.error:
            status = f"[red]✗ {r.error}[/red]"
        else:
            status = _T("[yellow]⚠ Parcial[/yellow]")

        disk_col = "✓" if r.dir_renamed else "—"
        if r.warning and r.dir_renamed:
            disk_col = "[yellow]⚠ manual[/yellow]"

        table.add_row(
            r.device.name,
            "✓" if r.paused else "—",
            disk_col,
            "✓" if r.config_updated else "—",
            "✓" if r.resumed else "[red]✗[/red]",
            status,
        )
        if r.left_paused:
            paused_names.append(r.device.name)

    console.print(table)

    if manual_steps:
        console.print(_T("\n[bold yellow]⚠  Pasos manuales necesarios (dispositivos sin SSH):[/bold yellow]"))
        for name, warning in manual_steps:
            console.print(f"\n  [bold]{name}:[/bold]")
            for line in warning.splitlines():
                console.print(f"    {line}")

    if paused_names:
        console.print(_T("\n[bold red]⚠  Los siguientes dispositivos tienen la sync PAUSADA:[/bold red]"))
        for name in paused_names:
            console.print(f"  • {name}")
        console.print(_T("  Reanuda manualmente desde la interfaz web de Syncthing."))


def _resolve_device(devices: list[DeviceInfo], token: str) -> Optional[DeviceInfo]:
    """Find a device by exact ID, unambiguous ID-prefix, or (case-insensitive) exact name.
    Returns None when nothing matches OR the match is ambiguous (caller lists the options)."""
    token = (token or "").strip()
    if not token:
        return None
    for d in devices:                                   # exact device ID
        if d.device_id == token:
            return d
    pref = [d for d in devices if d.device_id.upper().startswith(token.upper())]
    if len(pref) == 1:                                  # unambiguous ID prefix (Syncthing short id)
        return pref[0]
    named = [d for d in devices if (d.name or "").lower() == token.lower()]
    if len(named) == 1:                                 # unambiguous exact name
        return named[0]
    return None


def _print_cluster_results(title: str, results: list) -> int:
    """Render [(device_name, ok, msg)] rows from the cluster ops (unshare/delete). Returns the
    number of FAILED rows so the caller can set a non-zero exit code for scripts."""
    table = Table(title=title, show_lines=True, expand=False)
    table.add_column(_T("Dispositivo"), min_width=14)
    table.add_column(_T("Estado"),      min_width=8, justify="center", no_wrap=True)
    table.add_column(_T("Detalle"),     min_width=16, ratio=1)
    fails = 0
    for row in results:                       # rows may be 3- or 4-tuples (delete adds a flag)
        name, ok, msg = row[0], row[1], row[2]
        if ok:
            state = "[green]✓ OK[/green]"
        else:
            state = "[red]✗[/red]"
            fails += 1
        table.add_row(name, state, msg or "")
    console.print(table)
    return fails


# ── Subcomandos ──────────────────────────────────────────────────────────────

@app.command(help=_T("Abre la interfaz gráfica (GUI)."))
def gui() -> None:
    """Open the desktop GUI explicitly. A bare command in a terminal is the CLI; the GUI opens on
    a double-click or via this subcommand (the pip install also exposes it as
    `syncthing-manager-gui`). tkinter is imported lazily here so it never weighs on CLI startup."""
    from syncthing_manager.gui import main as gui_main
    # i18n was already resolved (--lang → stored → OS) at import + in the callback; pass the
    # concrete language so an explicit `--lang en gui` isn't overridden by the stored preference.
    gui_main(i18n.get_language())


@app.command(help=_T("Descubre dispositivos compartiendo una carpeta. No modifica nada."))
def discover(
    api_key: Optional[str] = typer.Option(None, "--api-key", "-k"),
    url: str = typer.Option("https://127.0.0.1:8384", "--url"),
    folder: Optional[str] = typer.Option(None, "--folder", "-f"),
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    no_verify_ssl: bool = typer.Option(True, "--no-verify-ssl/--verify-ssl"),
) -> None:
    """Descubre dispositivos compartiendo una carpeta. No modifica nada."""
    client = _get_client(api_key, url, no_verify_ssl)
    selected = _pick_folder(client, folder)
    console.print(_T('\nDescubriendo dispositivos para: [bold]{}[/bold]\n').format(selected.label or selected.id))
    devices_cfg = _load_devices_config(config)
    saved = _load_saved_credentials()
    if saved:
        console.print(_T('[dim]Credenciales guardadas cargadas: {} dispositivo(s)[/dim]').format(len(saved)))
    merged_cfg = saved + devices_cfg
    with console.status(_T("Descubriendo...")):
        devices = discover_devices(client, selected, merged_cfg)
    _print_discovery_table(devices)

    unreachable = [
        d for d in devices
        if not d.is_local and not d.api_reachable and not d.ssh_reachable and not d.winrm_reachable
    ]
    if unreachable:
        console.print(_T('\n[yellow]⚠  {} dispositivo(s) sin acceso.[/yellow]').format(len(unreachable)))
        if typer.confirm(_T("¿Introducir credenciales para reintentar?"), default=False):
            devices = _interactive_fix_devices(devices, selected.id)
            _print_discovery_table(devices)


@app.command(help=_T("Lista las carpetas del nodo Syncthing local."))
def folders(
    api_key: Optional[str] = typer.Option(None, "--api-key", "-k"),
    url: str = typer.Option("https://127.0.0.1:8384", "--url"),
    no_verify_ssl: bool = typer.Option(True, "--no-verify-ssl/--verify-ssl"),
) -> None:
    """Lista las carpetas del nodo Syncthing local."""
    client = _get_client(api_key, url, no_verify_ssl)
    folder_list = client.get_folders()
    table = Table(title=_T("Carpetas Syncthing locales"), show_lines=True, expand=False)
    table.add_column("#",                style="cyan", width=4,  no_wrap=True)
    table.add_column("ID",               min_width=10, no_wrap=True)
    table.add_column("Label",            min_width=12)
    table.add_column(_T("Ruta"),         min_width=16, ratio=1)
    table.add_column(_T("Dispositivos"), min_width=4,  justify="right", no_wrap=True)
    for i, f in enumerate(folder_list, 1):
        table.add_row(str(i), f.id, f.label or f.id, f.path, str(len(f.devices)))
    console.print(table)


@app.command(help=_T("Renombra una carpeta Syncthing en todos los dispositivos."))
def rename(
    folder: Optional[str] = typer.Option(None, "--folder", "-f"),
    label: Optional[str] = typer.Option(None, "--label", "-l"),
    dir_name: Optional[str] = typer.Option(None, "--dir-name", "-d",
        help=_T("Nuevo nombre de directorio o ruta absoluta completa")),
    api_key: Optional[str] = typer.Option(None, "--api-key", "-k"),
    url: str = typer.Option("https://127.0.0.1:8384", "--url"),
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    no_confirm: bool = typer.Option(False, "--no-confirm"),
    local_only: bool = typer.Option(False, "--local-only"),
    skip_path_rename: bool = typer.Option(False, "--skip-path-rename"),
    new_folder_id: Optional[str] = typer.Option(None, "--new-folder-id",
        help=_T("Cambiar también el ID de la carpeta. Se aplica en todos "
                "los dispositivos accesibles; los offline necesitan el agente.")),
    passive: bool = typer.Option(False, "--passive",
        help=_T("Tras renombrar, seguir esperando a los dispositivos offline y "
                "aplicarles el cambio cuando reconecten (Ctrl-C para terminar).")),
    no_verify_ssl: bool = typer.Option(True, "--no-verify-ssl/--verify-ssl"),
) -> None:
    """Renombra una carpeta Syncthing en todos los dispositivos."""
    if dry_run:
        console.print(_T("[yellow]--- DRY RUN: no se realizará ningún cambio ---[/yellow]\n"))

    client = _get_client(api_key, url, no_verify_ssl)
    selected = _pick_folder(client, folder)

    console.print(_T("\nLabel actual: [bold]{}[/bold]").format(selected.label))
    console.print(_T('Ruta actual:  [bold]{}[/bold]\n').format(selected.path))

    # New label. Fall back to the folder id if the folder carries no label at all (Syncthing can
    # return an empty/null label) so new_label is never None/empty — the downstream rename needs a
    # real string and would otherwise raise on None.
    new_label = (label or typer.prompt(_T("Nuevo label"), default=selected.label or selected.id)
                 or selected.label or selected.id)

    # New path/name — validate only bare names, not absolute paths
    new_dir = dir_name
    if not new_dir and not skip_path_rename:
        new_dir = typer.prompt(
            _T("Nuevo nombre en disco (nombre simple o ruta absoluta completa)"),
            default=new_label,
        ) or new_label

    invalid_chars = set(':*?"<>|')
    if any(c in invalid_chars for c in new_label):
        err_console.print(_T("[red]Label con caracteres no válidos: {}[/red]").format(repr(new_label)))
        raise typer.Exit(1)
    if new_dir and not is_absolute_path(new_dir):
        if any(c in set('/\\:*?"<>|') for c in new_dir):
            err_console.print(_T("[red]Nombre con caracteres no válidos: {}[/red]").format(repr(new_dir)))
            raise typer.Exit(1)
    if new_dir and skip_path_rename:
        # Contradictory flags: --dir-name asks to move/rename the directory, --skip-path-rename
        # tells the renamer to leave the path untouched. The dir name is silently ignored
        # downstream, so warn instead of letting the user believe the folder will be moved.
        console.print(_T("[yellow]Aviso: --dir-name se ignora porque --skip-path-rename está "
                         "activo (no se cambiará la ruta en disco).[/yellow]"))

    # Folder ID rename (opt-in via --new-folder-id)
    new_folder_id = (new_folder_id or "").strip()
    do_id_rename = bool(new_folder_id) and new_folder_id != selected.id
    if new_folder_id and new_folder_id == selected.id:
        err_console.print(f"[red]{_T('El nuevo ID es igual al actual.')}[/red]")
        raise typer.Exit(1)

    # Discovery — merge saved credentials with any explicit --config
    devices_cfg = _load_devices_config(config)
    saved = _load_saved_credentials()
    if saved:
        console.print(_T('[dim]Credenciales guardadas cargadas: {} dispositivo(s)[/dim]').format(len(saved)))
    merged_cfg = saved + devices_cfg
    with console.status(_T("Descubriendo dispositivos...")):
        all_devices = discover_devices(client, selected, merged_cfg)

    if local_only:
        all_devices = [d for d in all_devices if d.is_local]

    _print_discovery_table(all_devices)

    # Interactive fix for failed devices
    if not local_only and not no_confirm:
        all_devices = _interactive_fix_devices(all_devices, selected.id)

    def _is_actionable(d: DeviceInfo) -> bool:
        return d.is_local or d.api_reachable or d.ssh_reachable or d.winrm_reachable

    actionable = [d for d in all_devices if _is_actionable(d)]
    skipped    = [d for d in all_devices if not _is_actionable(d)]

    if skipped:
        console.print(_T('\n[yellow]Se saltarán {} dispositivo(s) sin acceso (ni API, SSH ni WinRM):[/yellow]').format(len(skipped)))
        for d in skipped:
            console.print(f"  • {d.name}: {d.ssh_error or d.api_error or _T('sin IP conocida')}")

    if not actionable:
        err_console.print(f"[red]{_T('No hay dispositivos alcanzables.')}[/red]")
        raise typer.Exit(1)

    # Pre-flight validation (same checks as the GUI): name validity per OS, destination
    # already exists, ID collision, write permission — before touching anything.
    from .renamer import preflight_check
    issues = preflight_check(actionable, selected.id, new_dir or new_label,
                             skip_path_rename, new_folder_id if do_id_rename else "")
    pf_errors = [i for i in issues if i.level == "error"]
    pf_warns  = [i for i in issues if i.level == "warning"]
    if issues:
        console.print(_T("\n[bold]Pre-vuelo:[/bold]"))
        for i in pf_errors:
            err_console.print(f"  [red]✗ {i.device_name}: {i.message}[/red]")
        for i in pf_warns:
            console.print(f"  [yellow]⚠ {i.device_name}: {i.message}[/yellow]")
    else:
        console.print(f"[green]{_T('✓ Pre-vuelo OK — sin problemas detectados')}[/green]")
    if pf_errors and not dry_run:
        if no_confirm:
            err_console.print(_T("[red]Pre-vuelo con errores; abortando "
                                 "(quita --no-confirm para decidir interactivamente).[/red]"))
            raise typer.Exit(1)
        if not typer.confirm(_T("Hay errores de pre-vuelo. ¿Continuar de todas formas?"), default=False):
            console.print(_T("Cancelado."))
            raise typer.Exit(0)

    if not no_confirm:
        if not typer.confirm(
            _T('\n¿Renombrar en {} dispositivo(s)?').format(len(actionable)) + (" [DRY RUN]" if dry_run else ""),
            default=True,
        ):
            console.print(_T("Cancelado."))
            raise typer.Exit(0)

    with console.status(_T("Renombrando...")):
        results = rename_all_devices(
            devices=actionable,
            folder_id=selected.id,
            new_label=new_label,
            new_dir_name=new_dir or new_label,
            dry_run=dry_run,
            skip_path_rename=skip_path_rename,
        )

    console.print()
    _print_results_table(results)

    # Folder ID rename — run after the label/path rename so it targets
    # the just-updated folder. Changing the ID on every reachable device keeps sync
    # seamless (peers re-associate by the new ID instead of seeing the folder go stale).
    id_results: list[tuple[str, bool, str]] = []
    if do_id_rename:
        from .renamer import rename_folder_id
        console.print(
            _T("\n[cyan]Renombrar ID: «{}» → «{}»[/cyan]").format(selected.id, new_folder_id)
        )
        id_results = rename_folder_id(actionable, selected.id, new_folder_id, dry_run=dry_run)
        for name, ok, msg in id_results:
            if ok:
                console.print(_T("  [green]✓ {} — ID actualizado[/green]").format(name))
            else:
                console.print(f"  [red]✗ {name} — {msg}[/red]")

    # Persist an undo snapshot once a real change landed somewhere — lets a later
    # `undo` command revert label / on-disk path / folder ID (parity with the GUI).
    if not dry_run and any(r.success for r in results):
        # Store the bare directory NAME (not an absolute path): on undo each device
        # reverts its own last path component, which is correct for heterogeneous
        # clusters where devices keep the folder under different parents (mirrors GUI).
        old_dir_name = Path(selected.path.rstrip("/\\")).name if selected.path else ""
        _save_undo_snapshot({
            "url": url,
            "folder_id": new_folder_id if do_id_rename else selected.id,  # current id now
            "orig_folder_id": selected.id,
            "old_label": selected.label,
            "new_label": new_label,
            "old_dir_name": old_dir_name,
            "skip_path_rename": skip_path_rename,
            "id_renamed": do_id_rename,
        })
        console.print(_T("\n[dim]Snapshot guardado. Usa «syncthing-manager undo» para revertir "
                         "este cambio.[/dim]"))

    # Offer to generate agents for devices that need manual action
    needs_agent = [
        r for r in results
        if r.warning or (not r.success and r.device.api_key)
    ]
    # Skip the interactive agent offer in scripted mode (--no-confirm): it calls typer.prompt/
    # confirm, which would hit EOF on a closed stdin and abort with a non-zero exit AFTER the
    # rename already succeeded. Generate agents explicitly with `generate-agent` instead.
    if needs_agent and not dry_run and not no_confirm:
        _offer_generate_agents(
            needs_agent, selected.id, new_label, new_dir or new_label, skip_path_rename,
            do_id_rename=do_id_rename, new_folder_id=new_folder_id,
        )

    # Passive exploration — keep applying to offline devices as they reconnect.
    if passive and not dry_run and skipped:
        _run_passive(
            client, selected, merged_cfg, skipped,
            new_label, new_dir or new_label, skip_path_rename,
            do_id_rename, new_folder_id,
        )

    id_failed = any(not ok for _, ok, _ in id_results)
    if any(not r.success for r in results) or id_failed:
        raise typer.Exit(1)


def _offer_generate_agents(
    results: list[RenameResult],
    folder_id: str,
    new_label: str,
    new_dir_name: str,
    skip_path_rename: bool,
    do_id_rename: bool = False,
    new_folder_id: str = "",
) -> None:
    if not results:
        return
    win_avail   = agent_template_available("windows")
    linux_avail = agent_template_available("linux")
    macos_avail = agent_template_available("macos")
    if not win_avail and not linux_avail and not macos_avail:
        console.print(
            _T("\n[dim]ℹ  Para generar agentes para dispositivos sin acceso remoto, "
               "compila las plantillas:\n"
               "  python -m PyInstaller build/agent_windows.spec\n"
               "  python -m PyInstaller build/agent_linux.spec\n"
               "  python -m PyInstaller build/agent_macos.spec[/dim]")
        )
        return

    console.print(_T("\n[yellow]ℹ  Dispositivos que requieren agente local:[/yellow]"))
    for r in results:
        reason = _T("sin SSH/WinRM") if r.warning else _T('error: {}').format(r.error)
        console.print(f"  • [bold]{r.device.name}[/bold] ({r.device.device_id[:16]}…) — {reason}")

    # Build shared entries list
    entries = []
    for r in results:
        dev = r.device
        if not dev.api_key:
            console.print(_T('  [dim]! {}: sin API Key, se omite del agente.[/dim]').format(dev.name))
            continue
        entries.append({
            "device_id":       dev.device_id,
            "device_name":     dev.name,
            "folder_id":       folder_id,
            "new_label":       new_label,
            "new_dir_name":    new_dir_name,
            "old_path":        dev.folder_path or "",
            "api_key":         dev.api_key or "",
            "api_url":         dev.api_url or "http://127.0.0.1:8384",
            "skip_path_rename": skip_path_rename,
            "dry_run":         False,
            "rename_id":       do_id_rename,
            "new_folder_id":   new_folder_id,
        })

    if not entries:
        return

    console.print(
        _T('\n[cyan]Se generará UN agente con {} dispositivo(s) embebidos.[/cyan]\n[dim]Al ejecutarlo en cada equipo detecta automáticamente su ID de Syncthing\ny aplica solo la configuración correspondiente.[/dim]').format(len(entries))
    )

    choices = []
    if win_avail:   choices.append("[w] Windows")
    if linux_avail: choices.append("[l] Linux")
    if macos_avail: choices.append("[m] macOS")
    if len(choices) > 1:
        choices.append(_T("[b] Todos"))
    plat_prompt = " / ".join(choices)
    _default = "w" if win_avail else ("l" if linux_avail else "m")
    plat = typer.prompt(_T("Plataforma ({})").format(plat_prompt), default=_default).lower()[:1]
    do_win   = win_avail   and plat in ("w", "b")
    do_linux = linux_avail and plat in ("l", "b")
    do_macos = macos_avail and plat in ("m", "b")
    if not (do_win or do_linux or do_macos):
        # The user typed a platform that isn't on offer (e.g. "l" when only Windows is embedded):
        # don't fall through to an empty build loop that silently produces nothing.
        console.print(_T("  [yellow]La plataforma elegida no está disponible — no se generó ningún agente.[/yellow]"))
        return

    passphrase = _ask_agent_passphrase()

    import sys as _sys
    from .generate import (select_agent_builds, available_linux_arches,
                           available_macos_arches, normalize_arch)

    # Per-OS arches we DETECTED on fully-probed devices (OS *and* arch known, not user-guessed) —
    # these drive the automatic builds. A guessed os_type must not seed this.
    detected_arches_by_os: dict = {}
    for r in results:
        d = r.device
        if d.arch_detected and d.arch and d.os_type and d.os_detected:
            detected_arches_by_os.setdefault(d.os_type, set()).add(normalize_arch(d.arch))

    def _copy_hint():
        console.print(
            _T('  [dim]Cópialo a cualquiera de los {} equipos y ejecútalo directamente — detecta el equipo solo.[/dim]').format(len(entries)))

    def _gen_one(_os, _arch, _fname):
        try:
            out = generate_multi_agent_file(entries=entries, target_os=_os,
                                            target_arch=_arch, passphrase=passphrase, filename=_fname)
            if _arch:
                console.print(_T("  [green]✓ Agente {} {}: {}[/green]").format(_os, _arch, out))
            else:
                console.print(_T("  [green]✓ Agente {}: {}[/green]").format(_os, out))
            _copy_hint()
        except Exception as e:  # symmetric with the success line: arch only when there is one
            if _arch:
                console.print(_T('  [red]Error generando agente {} {}: {}[/red]').format(_os, _arch, e))
            else:
                console.print(_T('  [red]Error generando agente {}: {}[/red]').format(_os, e))

    for target_os in ((["windows"] if do_win else []) + (["linux"] if do_linux else [])
                       + (["macos"] if do_macos else [])):
        if target_os == "windows":
            _gen_one("windows", None, None)
            continue

        # Linux/macOS: auto-build one binary per distinct DETECTED arch (parity with the GUI's
        # select_agent_builds — no useless base when nobody runs it; the base stays as a catch-all
        # when some device's OS or arch wasn't detected).
        _avail = available_macos_arches() if target_os == "macos" else available_linux_arches()
        if target_os == "macos":
            # macOS has no plain template — the base must be an arch actually embedded.
            base_arch = "amd64" if ("amd64" in _avail or not _avail) else "arm64"
        else:
            base_arch = "amd64" if _sys.platform == "win32" else normalize_arch()
        _detected = detected_arches_by_os.get(target_os, set())
        _has_undet = any(
            (r.device.os_type == target_os and not (r.device.arch_detected and r.device.arch))
            or not r.device.os_type
            for r in results)
        build_base, extra, uncovered = select_agent_builds(_detected, _has_undet, _avail, base_arch)
        built: set = set()
        if build_base:
            # macOS base built EXPLICITLY (suffixed); Linux base via the plain template.
            if target_os == "macos":
                _gen_one(target_os, base_arch, f"syncthing-manager-agent-macos-{base_arch}")
            else:
                _gen_one(target_os, None, None)
            built.add(base_arch)
        for a in extra:
            _gen_one(target_os, a, f"syncthing-manager-agent-{target_os}-{a}")
            built.add(a)
        # Manual control: the agent path is for devices we usually CAN'T probe (offline/no
        # SSH-API), so their arch is often undetected. Offer the remaining embedded arches so the
        # user can target e.g. an offline arm64 Raspberry Pi explicitly (parity with the GUI popup).
        for a in [x for x in _avail if x not in built]:
            if typer.confirm(_T('¿Generar también la versión {} del agente {}?').format(a, target_os),
                             default=False):
                _gen_one(target_os, a, f"syncthing-manager-agent-{target_os}-{a}")
        if uncovered:
            console.print(_T('  [yellow]⚠ {}: arquitectura(s) detectada(s) sin plantilla embebida: {} — esos dispositivos no quedan cubiertos (recompila con la plantilla).[/yellow]').format(
                target_os, ", ".join(uncovered)))


@app.command(help=_T("Muestra la topología real de la carpeta: dispositivos, roles, enlaces e inconsistencias."))
def topology(
    folder: Optional[str] = typer.Option(None, "--folder", "-f"),
    api_key: Optional[str] = typer.Option(None, "--api-key", "-k"),
    url: str = typer.Option("https://127.0.0.1:8384", "--url"),
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    no_verify_ssl: bool = typer.Option(True, "--no-verify-ssl/--verify-ssl"),
) -> None:
    """Muestra la topología real de la carpeta: dispositivos, roles, enlaces e inconsistencias."""
    client = _get_client(api_key, url, no_verify_ssl)
    selected = _pick_folder(client, folder)
    merged_cfg = _load_saved_credentials() + _load_devices_config(config)
    with console.status(_T("Descubriendo dispositivos...")):
        devices = discover_devices(client, selected, merged_cfg)
    try:
        my_id = client.get_my_device_id()
    except Exception:
        my_id = ""
    # Reuse the same pure builders the GUI uses — from topology.py, which has NO tkinter
    # dependency, so this command works on a headless server (no python3-tk needed).
    from .topology import _build_topology, _detect_topology_issues, _arrow_from_senders, _ROLE_LABELS
    name_map = {d.device_id: d.name for d in devices}
    online_ids = {d.device_id for d in devices
                  if d.is_local or d.api_reachable or d.ssh_reachable or d.winrm_reachable}
    topo = _build_topology(selected, my_id, name_map, online_ids, devices=devices)
    nodes = topo["nodes"]

    console.print(_T('\n[bold]Topología de «{}»[/bold]\n').format(selected.label or selected.id))
    console.print(_T("[bold]Dispositivos:[/bold]"))
    for nid, n in nodes.items():
        state = ("local" if n["is_local"] else ("online" if n["online"] else "offline"))
        scol = {"local": "cyan", "online": "green", "offline": "red"}[state]
        role = _T(_ROLE_LABELS.get(n["role"], n["role"])) if n.get("role_known", True) else _T("rol desconocido (offline)")
        console.print(f"  • [bold]{n['label']}[/bold]  [{scol}]{state}[/{scol}]  ·  {role}")

    edir = topo.get("edge_dir", {})
    _sym = {"both": "↔", "last": "→", "first": "←", "none": _T("⁄⁄ (sin sync)")}
    console.print(_T("\n[bold]Enlaces:[/bold]"))
    if not topo["edges"]:
        console.print(_T("  [dim](ninguno)[/dim]"))
    for e in topo["edges"]:
        ids = sorted(e)
        if len(ids) < 2:
            continue
        la, lb = nodes[ids[0]]["label"], nodes[ids[1]]["label"]
        if e in edir:
            console.print(f"  {la}  {_sym[_arrow_from_senders(ids[0], ids[1], edir[e])]}  {lb}")
        else:
            console.print(_T('  {}  —  {}  [dim](dirección desconocida · offline)[/dim]').format(la, lb))

    issues = _detect_topology_issues(topo)
    if issues:
        console.print(_T("\n[yellow]⚠ Posibles inconsistencias:[/yellow]"))
        for i in issues:
            console.print(f"  [yellow]•[/yellow] {i}")
    else:
        console.print(f"\n[green]{_T('✓ Sin inconsistencias detectadas.')}[/green]")


@app.command(help=_T("Deja de compartir una carpeta con un dispositivo en todo el clúster (no borra archivos)."))
def unshare(
    device: str = typer.Option(..., "--device", "-d",
        help=_T("ID (o prefijo) o nombre del dispositivo que dejará de compartir la carpeta.")),
    folder: Optional[str] = typer.Option(None, "--folder", "-f"),
    api_key: Optional[str] = typer.Option(None, "--api-key", "-k"),
    url: str = typer.Option("https://127.0.0.1:8384", "--url"),
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    no_verify_ssl: bool = typer.Option(True, "--no-verify-ssl/--verify-ssl"),
    dry_run: bool = typer.Option(False, "--dry-run", help=_T("Muestra qué se haría sin cambiar nada.")),
) -> None:
    """Deja de compartir una carpeta con un dispositivo en todo el clúster (no borra archivos)."""
    from .renamer import unshare_folder_everywhere
    client = _get_client(api_key, url, no_verify_ssl)
    selected = _pick_folder(client, folder)
    merged_cfg = _load_saved_credentials() + _load_devices_config(config)
    with console.status(_T("Descubriendo dispositivos...")):
        devices = discover_devices(client, selected, merged_cfg)
    target = _resolve_device(devices, device)
    if target is None:
        err_console.print(_T("[red]Dispositivo no encontrado o ambiguo: {}[/red]").format(device))
        console.print(_T("Dispositivos conocidos de esta carpeta:"))
        for d in devices:
            console.print(f"  • {d.name}  [dim]{d.device_id[:7]}[/dim]")
        raise typer.Exit(1)
    console.print(_T('\nDejando de compartir «{}» con [bold]{}[/bold]…\n').format(
        selected.label or selected.id, target.name))
    # member_ids defaults to None → the helper uses the target's own discovered peer list and
    # reports any member it can't reach as an explicit failure (never a silent partial success).
    results = unshare_folder_everywhere(devices, selected.id, target.device_id, dry_run=dry_run)
    fails = _print_cluster_results(_T("Dejar de compartir"), results)
    if fails:
        err_console.print(_T("\n[yellow]⚠ {} equipo(s) no se pudieron actualizar (sin acceso). Añade credenciales y reintenta, o quítala en ese equipo.[/yellow]").format(fails))
        raise typer.Exit(1)


@app.command(name="delete-folder",
             help=_T("BORRA una carpeta (de Syncthing y, salvo --keep-data, del disco) en el clúster. IRREVERSIBLE."))
def delete_folder_cmd(
    folder: Optional[str] = typer.Option(None, "--folder", "-f"),
    on_device: Optional[str] = typer.Option(None, "--on-device",
        help=_T("Borrar solo en este dispositivo (id/nombre). Por defecto: en todos los miembros.")),
    keep_data: bool = typer.Option(False, "--keep-data",
        help=_T("Quitar de Syncthing pero NO borrar los archivos en disco.")),
    yes: bool = typer.Option(False, "--yes", "-y",
        help=_T("No pedir la confirmación tecleada (para scripts). Úsalo con cuidado.")),
    api_key: Optional[str] = typer.Option(None, "--api-key", "-k"),
    url: str = typer.Option("https://127.0.0.1:8384", "--url"),
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    no_verify_ssl: bool = typer.Option(True, "--no-verify-ssl/--verify-ssl"),
    dry_run: bool = typer.Option(False, "--dry-run", help=_T("Muestra qué se haría sin borrar nada.")),
) -> None:
    """BORRA una carpeta en el clúster. IRREVERSIBLE.

    Las mismas guardas que la GUI siguen activas en el backend: rechaza rutas protegidas del
    sistema y carpetas sin marcador .stfolder, y un remoto solo-API (sin SSH/WinRM) no puede
    borrar en disco. Aquí, además, se exige teclear el nombre de la carpeta (salvo --yes/--dry-run).
    """
    from .renamer import delete_folder_everywhere, delete_folder_on_device
    client = _get_client(api_key, url, no_verify_ssl)
    selected = _pick_folder(client, folder)
    merged_cfg = _load_saved_credentials() + _load_devices_config(config)
    with console.status(_T("Descubriendo dispositivos...")):
        devices = discover_devices(client, selected, merged_cfg)

    fname = selected.label or selected.id
    target = None
    if on_device:
        target = _resolve_device(devices, on_device)
        if target is None:
            err_console.print(_T("[red]Dispositivo no encontrado o ambiguo: {}[/red]").format(on_device))
            raise typer.Exit(1)

    scope = (_T("el dispositivo «{}»").format(target.name) if target
             else _T("TODOS los equipos del clúster ({} dispositivos)").format(len(devices)))
    if keep_data:
        what = _T("se quitará de Syncthing en {} (los archivos en disco NO se tocan)").format(scope)
    else:
        what = _T("se quitará de Syncthing Y se borrarán los archivos en disco en {}").format(scope)
    console.print(_T("\n[bold red]⚠  Vas a BORRAR la carpeta «{}»:[/bold red]").format(fname))
    console.print(f"   {what}.")
    if not keep_data:
        console.print(_T("   [red]Esta acción es IRREVERSIBLE.[/red] (Se rechazan rutas protegidas del sistema y carpetas sin marcador .stfolder.)"))

    if not dry_run and not yes:
        typed = typer.prompt(_T("Escribe el nombre de la carpeta «{}» para confirmar").format(fname))
        if typed.strip() != fname:
            err_console.print(_T("[red]El nombre no coincide — operación cancelada.[/red]"))
            raise typer.Exit(1)

    console.print()
    with console.status(_T("Borrando...")):
        if target:
            r = delete_folder_on_device(target, selected.id, delete_data=not keep_data, dry_run=dry_run)
            results = [(r.device_name, r.ok, r.message)]
        else:
            results = delete_folder_everywhere(devices, selected.id,
                                               delete_data=not keep_data, dry_run=dry_run)
    fails = _print_cluster_results(_T("Borrado de carpeta"), results)
    if fails:
        err_console.print(_T("\n[yellow]⚠ {} equipo(s) no se completaron. Revisa el detalle de arriba.[/yellow]").format(fails))
        raise typer.Exit(1)


@app.command(name="create-folder",
             help=_T("Crea una carpeta NUEVA en este equipo y la registra en Syncthing (luego compártela con «share»)."))
def create_folder_cmd(
    folder_id: str = typer.Option(..., "--id", help=_T("ID de la carpeta nueva (único en el clúster).")),
    path: str = typer.Option(..., "--path", "-p", help=_T("Ruta en disco donde vivirá la carpeta (admite ~).")),
    label: Optional[str] = typer.Option(None, "--label", "-l", help=_T("Etiqueta visible (por defecto, el ID).")),
    api_key: Optional[str] = typer.Option(None, "--api-key", "-k"),
    url: str = typer.Option("https://127.0.0.1:8384", "--url"),
    no_verify_ssl: bool = typer.Option(True, "--no-verify-ssl/--verify-ssl"),
    dry_run: bool = typer.Option(False, "--dry-run", help=_T("Muestra qué se haría sin crear nada.")),
) -> None:
    """Crea una carpeta NUEVA en este equipo (operación LOCAL) y la registra en Syncthing.

    Réplica del flujo de la GUI: comprueba que el ID no exista ya (un error de conexión aborta,
    nunca se crea sobre una comprobación no verificada), crea el directorio, registra la carpeta
    (paused:false, solo este equipo) y la re-escanea para que se escriba el marcador .stfolder.
    Para compartirla con otros dispositivos, usa después «syncthing-manager share».
    """
    folder_id = (folder_id or "").strip()
    path = (path or "").strip()
    if not folder_id or not path:
        err_console.print(_T("[red]Se requieren --id y --path.[/red]"))
        raise typer.Exit(1)
    client = _get_client(api_key, url, no_verify_ssl)
    # get_folder returns None ONLY on 404; it RE-RAISES timeouts/5xx/auth. Don't create on an
    # UNVERIFIED check — the upsert could clobber an existing folder. Fail safe: abort.
    try:
        exists = client.get_folder(folder_id) is not None
    except Exception:
        err_console.print(_T("[red]No se pudo verificar si el ID ya existe (error de conexión). Reintenta.[/red]"))
        raise typer.Exit(1)
    if exists:
        err_console.print(_T("[red]Ya existe una carpeta con el ID «{}».[/red]").format(folder_id))
        raise typer.Exit(1)
    lbl = label or folder_id
    if dry_run:
        console.print(_T("[dim][dry-run][/dim] Se crearía la carpeta «{}» (id {}) en {}.").format(lbl, folder_id, path))
        return
    try:
        Path(path).expanduser().mkdir(parents=True, exist_ok=True)
    except OSError:
        pass   # Syncthing también crea la ruta; ignoramos problemas de mkdir aquí.
    try:
        my_id = client.get_my_device_id()
    except SyncthingError as e:
        err_console.print(_T("[red]No se pudo leer el ID del nodo local: {}[/red]").format(e))
        raise typer.Exit(1)
    client.create_folder({
        "id": folder_id, "label": lbl, "path": path, "type": "sendreceive",
        "fsWatcherEnabled": True, "rescanIntervalS": 3600,
        "devices": [{"deviceID": my_id}]})
    try:
        client.rescan_folder(folder_id)   # escribe .stfolder ahora (el dir ya existe)
    except Exception:
        pass
    console.print(_T("[green]✓ Carpeta «{}» creada en {}.[/green]").format(lbl, path))
    console.print(_T("[dim]Compártela con: syncthing-manager share -f {} -d <dispositivo>[/dim]").format(folder_id))


@app.command(help=_T("Comparte una carpeta con un dispositivo (lo añade a la membresía en este equipo)."))
def share(
    device: str = typer.Option(..., "--device", "-d",
        help=_T("ID (o prefijo/nombre si ya es conocido) del dispositivo con el que compartir.")),
    folder: Optional[str] = typer.Option(None, "--folder", "-f"),
    name: Optional[str] = typer.Option(None, "--name",
        help=_T("Nombre para un dispositivo nuevo (por defecto, el inicio de su ID).")),
    with_peer: Optional[str] = typer.Option(None, "--with",
        help=_T("Anclar el enlace a este miembro alcanzable en vez de a este equipo.")),
    api_key: Optional[str] = typer.Option(None, "--api-key", "-k"),
    url: str = typer.Option("https://127.0.0.1:8384", "--url"),
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    no_verify_ssl: bool = typer.Option(True, "--no-verify-ssl/--verify-ssl"),
    dry_run: bool = typer.Option(False, "--dry-run", help=_T("Muestra qué se haría sin cambiar nada.")),
) -> None:
    """Comparte una carpeta con un dispositivo: lo añade a la membresía de la carpeta en el ancla
    (este equipo por defecto, o un miembro alcanzable con --with). Reutiliza la misma maquinaria
    de topología que la GUI (compute_topology_diff + apply_topology_on_device): añade una arista
    ancla↔dispositivo y aplica SOLO ese cambio. El dispositivo recibe la oferta de la carpeta al
    conectarse; un dispositivo nuevo se valida con la API de Syncthing antes de añadirlo.
    """
    import copy
    from .topology import _build_topology
    from .renamer import compute_topology_diff, apply_topology_on_device
    client = _get_client(api_key, url, no_verify_ssl)
    selected = _pick_folder(client, folder)
    merged_cfg = _load_saved_credentials() + _load_devices_config(config)
    with console.status(_T("Descubriendo dispositivos...")):
        devices = discover_devices(client, selected, merged_cfg)
    try:
        my_id = client.get_my_device_id()
    except Exception:
        my_id = ""

    # Resolve the target: a known (discovered) device, else a raw device ID validated by Syncthing.
    tgt = _resolve_device(devices, device)
    if tgt is not None:
        target_id, target_label = tgt.device_id, (name or tgt.name)
    else:
        try:
            chk = client.check_device_id(device)
        except Exception:
            err_console.print(_T("[red]No se pudo validar el ID del dispositivo (error de conexión). Reintenta.[/red]"))
            raise typer.Exit(1)
        if not isinstance(chk, dict) or "id" not in chk:
            err_console.print(_T("[red]ID de dispositivo no válido: {}[/red]").format(device))
            raise typer.Exit(1)
        target_id, target_label = chk["id"], (name or chk["id"][:7])

    name_map = {d.device_id: d.name for d in devices}
    online_ids = {d.device_id for d in devices
                  if d.is_local or d.api_reachable or d.ssh_reachable or d.winrm_reachable}
    orig = _build_topology(selected, my_id, name_map, online_ids, devices=devices)

    # Anchor = the member that will list the target (this machine by default, or --with peer).
    anchor_id = my_id
    if with_peer:
        a = _resolve_device(devices, with_peer)
        if a is None:
            err_console.print(_T("[red]Miembro ancla no encontrado o ambiguo: {}[/red]").format(with_peer))
            raise typer.Exit(1)
        anchor_id = a.device_id
    if anchor_id not in orig.get("nodes", {}):
        err_console.print(_T("[red]El ancla no comparte «{}» (no es miembro). Usa --with un miembro alcanzable.[/red]").format(selected.label or selected.id))
        raise typer.Exit(1)
    if target_id == anchor_id:
        err_console.print(_T("[red]El dispositivo destino y el ancla son el mismo.[/red]"))
        raise typer.Exit(1)
    anchor_dev = next((d for d in devices if d.device_id == anchor_id), None)
    if anchor_dev is None or not (anchor_dev.is_local or anchor_dev.api_reachable
                                  or anchor_dev.ssh_reachable or anchor_dev.winrm_reachable):
        err_console.print(_T("[red]El ancla no es alcanzable ahora — no se puede aplicar el cambio.[/red]"))
        raise typer.Exit(1)

    # Build the edited graph: add the target node (if new) + the anchor↔target edge, then let the
    # SAME diff engine the GUI uses compute the minimal change and apply only it.
    cur = copy.deepcopy(orig)
    if target_id not in cur["nodes"]:
        cur["nodes"][target_id] = {
            "id": target_id, "label": target_label, "is_local": False, "is_new": True,
            "online": target_id in online_ids, "reachable": False,
            "role": "sendreceive", "role_known": False, "path": "", "os_type": None}
    edge = frozenset((anchor_id, target_id))
    if edge in cur.get("edges", set()):
        console.print(_T("«{}» ya comparte «{}» con ese dispositivo — sin cambios.").format(
            cur["nodes"].get(anchor_id, {}).get("label", anchor_id[:7]), selected.label or selected.id))
        return
    cur.setdefault("edges", set()).add(edge)
    diff = compute_topology_diff(orig, cur)
    if not diff.get("any"):
        console.print(_T("Sin cambios que aplicar."))
        return

    anchor_lbl = cur["nodes"].get(anchor_id, {}).get("label", anchor_id[:7])
    console.print(_T('\nCompartiendo «{}» con [bold]{}[/bold] (ancla: {})…\n').format(
        selected.label or selected.id, target_label, anchor_lbl))
    tr = apply_topology_on_device(anchor_dev, selected.id, cur, diff=diff,
                                  folder_label=selected.label or selected.id, dry_run=dry_run)
    fails = _print_cluster_results(_T("Compartir"), [(tr.device_name, tr.ok, tr.message)])
    if fails:
        raise typer.Exit(1)
    if not dry_run:
        console.print(_T("[dim]El dispositivo recibirá la oferta de la carpeta al conectarse (o configúralo con el agente / la exploración pasiva).[/dim]"))


@app.command(help=_T("Revierte el último rename (label, ruta en disco y, si lo hubo, ID de carpeta)."))
def undo(
    api_key: Optional[str] = typer.Option(None, "--api-key", "-k"),
    url: Optional[str] = typer.Option(None, "--url",
        help=_T("URL de Syncthing (por defecto, la del último rename).")),
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    no_confirm: bool = typer.Option(False, "--no-confirm"),
    passive: bool = typer.Option(False, "--passive",
        help=_T("Tras revertir, esperar a los offline y revertirlos al reconectar.")),
    no_verify_ssl: bool = typer.Option(True, "--no-verify-ssl/--verify-ssl"),
) -> None:
    """Revierte el último rename (label, ruta en disco y, si lo hubo, ID de carpeta)."""
    snap = _load_undo_snapshot()
    if not snap:
        err_console.print(_T("[red]No hay nada que deshacer (no se encontró undo.json).[/red]"))
        raise typer.Exit(1)
    # A corrupt / hand-edited / older-format undo.json may parse to a non-dict or be missing the
    # required key — fail with a friendly message instead of a raw TypeError/KeyError traceback.
    if not isinstance(snap, dict) or "folder_id" not in snap:
        err_console.print(_T("[red]El undo.json está corrupto o es de una versión anterior — no se puede deshacer.[/red]"))
        raise typer.Exit(1)

    snap_cur_id = snap["folder_id"]            # ID con el que se guardó (post-rename)
    orig_id     = snap.get("orig_folder_id", snap_cur_id)
    skip_path   = bool(snap.get("skip_path_rename"))
    old_dir_name = snap.get("old_dir_name", "")

    client = _get_client(api_key, url or snap.get("url") or "https://127.0.0.1:8384", no_verify_ssl)

    # The folder might be under the new id (rename succeeded locally) OR still under the
    # original id (a partial forward run where the ID change never landed on this node).
    # Find it under either, and only revert the ID if it actually differs now.
    folders = client.get_folders()
    selected = next((f for f in folders if f.id == snap_cur_id), None) \
        or next((f for f in folders if f.id == orig_id), None)
    if selected is None:
        err_console.print(_T('[red]No se encontró la carpeta a revertir (ni «{}» ni «{}»). ¿Ya se deshizo o se borró?[/red]').format(snap_cur_id, orig_id))
        raise typer.Exit(1)
    cur_id = selected.id
    do_id  = bool(snap.get("id_renamed")) and orig_id != cur_id

    console.print(_T("[bold]Deshacer último rename:[/bold]"))
    console.print(f"  Label:  «{snap.get('new_label','?')}» → [bold]«{snap['old_label']}»[/bold]")
    if not skip_path:
        console.print(_T('  Nombre en disco: → [bold]«{}»[/bold]').format(old_dir_name))
    if do_id:
        console.print(f"  ID:     «{cur_id}» → [bold]«{orig_id}»[/bold]")
    if dry_run:
        console.print(_T("\n[yellow]--- DRY RUN: no se realizará ningún cambio ---[/yellow]"))

    merged_cfg = _load_saved_credentials() + _load_devices_config(config)
    with console.status(_T("Descubriendo dispositivos...")):
        all_devices = discover_devices(client, selected, merged_cfg)

    def _actionable(d: DeviceInfo) -> bool:
        return d.is_local or d.api_reachable or d.ssh_reachable or d.winrm_reachable

    actionable = [d for d in all_devices if _actionable(d)]
    skipped    = [d for d in all_devices if not _actionable(d)]
    _print_discovery_table(all_devices)
    if not actionable:
        err_console.print(f"[red]{_T('No hay dispositivos alcanzables.')}[/red]")
        raise typer.Exit(1)
    if skipped:
        console.print(_T('\n[yellow]{} dispositivo(s) sin acceso se saltarán').format(len(skipped))
                      + (_T(" (usa --passive para revertirlos al reconectar).") if not passive else ".")
                      + "[/yellow]")

    if not no_confirm and not dry_run:
        if not typer.confirm(_T('\n¿Revertir en {} dispositivo(s)?').format(len(actionable)), default=True):
            console.print(_T("Cancelado."))
            raise typer.Exit(0)

    # Revert label/path on the folder by its CURRENT id, then revert the id back.
    with console.status(_T("Revirtiendo...")):
        results = rename_all_devices(
            devices=actionable,
            folder_id=cur_id,
            new_label=snap["old_label"],
            new_dir_name=old_dir_name,   # bare name → each device reverts its own path
            dry_run=dry_run,
            skip_path_rename=skip_path,
        )
    console.print()
    _print_results_table(results)

    id_results: list[tuple[str, bool, str]] = []
    if do_id:
        from .renamer import rename_folder_id
        console.print(_T("\n[cyan]Revertir ID: «{}» → «{}»[/cyan]").format(cur_id, orig_id))
        id_results = rename_folder_id(actionable, cur_id, orig_id, dry_run=dry_run)
        for name, ok, msg in id_results:
            console.print(_T("  [green]✓ {} — ID revertido[/green]").format(name) if ok
                          else f"  [red]✗ {name} — {msg}[/red]")

    if passive and not dry_run and skipped:
        _run_passive(
            client, selected, merged_cfg, skipped,
            snap["old_label"], old_dir_name, skip_path,
            do_id, orig_id,
        )

    # Clear the snapshot once the revert ran for real (even if some devices failed —
    # re-running undo would target the now-reverted id and do nothing useful).
    if not dry_run:
        _clear_undo_snapshot()

    id_failed = any(not ok for _, ok, _ in id_results)
    if any(not r.success for r in results) or id_failed:
        raise typer.Exit(1)


@app.command(name="generate-agent",
             help=_T("Genera un ejecutable de agente para un dispositivo sin SSH/WinRM."))
def generate_agent_cmd(
    folder:      Optional[str]  = typer.Option(None, "--folder", "-f"),
    device_name: Optional[str]  = typer.Option(None, "--device", "-d",
                                   help=_T("Nombre del dispositivo destino")),
    device_id:   Optional[str]  = typer.Option(None, "--device-id",
                                   help=_T("ID de Syncthing del dispositivo (habilita verificación de identidad)")),
    label:       Optional[str]  = typer.Option(None, "--label", "-l",
                                   help=_T("Nuevo label de la carpeta")),
    dir_name:    Optional[str]  = typer.Option(None, "--dir-name",
                                   help=_T("Nuevo nombre de directorio o ruta absoluta")),
    old_path:    Optional[str]  = typer.Option(None, "--old-path",
                                   help=_T("Ruta actual de la carpeta en el dispositivo destino")),
    api_key_opt: Optional[str]  = typer.Option(None, "--api-key", "-k",
                                   help=_T("API Key de Syncthing en el dispositivo destino")),
    api_url_opt: str            = typer.Option("http://127.0.0.1:8384", "--api-url"),
    target_os:   str            = typer.Option("windows", "--os",
                                   help=_T("Plataforma destino: windows, linux o macos")),
    target_arch: Optional[str]  = typer.Option(None, "--arch",
                                   help=_T("Arquitectura destino para Linux/macOS: amd64 o arm64 (Windows la ignora — el .exe x64 corre en Windows-ARM por emulación). Por defecto: la del equipo (Linux) o la arch macOS embebida (amd64 si está, si no arm64).")),
    output_dir:  Optional[Path] = typer.Option(None, "--output-dir", "-o"),
    skip_path:   bool           = typer.Option(False, "--skip-path-rename"),
    new_folder_id: Optional[str] = typer.Option(None, "--new-folder-id",
                                   help=_T("Cambiar también el ID de la carpeta")),
    dry_run:     bool           = typer.Option(False, "--dry-run"),
    url:         str            = typer.Option("https://127.0.0.1:8384", "--url"),
    main_key:    Optional[str]  = typer.Option(None, "--main-api-key",
                                   help=_T("API Key del nodo local (para descubrir carpetas)")),
) -> None:
    """Genera un ejecutable de agente para un dispositivo sin SSH/WinRM."""

    # Linux & macOS agents are arch-specific (native ELF/Mach-O, no in-OS cross-arch run we rely
    # on). Default (no --arch): Linux → THIS host's arch (its plain template); macOS → an arch
    # actually embedded, preferring amd64 (Intel + Rosetta), else arm64 — consistent with the GUI
    # and the `apply` agent fallback, so an arm64-only macOS build doesn't fail on a phantom amd64.
    # Windows ships one x64 template (runs on Windows-ARM via emulation) → arch is N/A.
    from .generate import normalize_arch, available_macos_arches
    if target_os == "macos":
        _macs = available_macos_arches()
        eff_arch = target_arch or ("amd64" if ("amd64" in _macs or not _macs) else "arm64")
    elif target_os == "linux":
        eff_arch = target_arch or normalize_arch()
    else:
        eff_arch = None
    if not agent_template_available(target_os, eff_arch):
        _arch_hint = f" ({eff_arch})" if eff_arch else ""
        err_console.print(
            _T("[red]Plantilla de agente para '{}'{} no encontrada.[/red]\n[dim]Compílala con:\n  python -m PyInstaller build/agent_{}.spec[/dim]").format(target_os, _arch_hint, target_os)
        )
        raise typer.Exit(1)

    # Get folder info from local Syncthing
    client = _get_client(main_key, url, no_verify_ssl=True)
    selected = _pick_folder(client, folder)

    new_label_val = label or typer.prompt(_T("Nuevo label"), default=selected.label)
    new_dir_val   = dir_name or (
        "" if skip_path else
        typer.prompt(_T("Nuevo nombre/ruta en disco"), default=new_label_val)
    )
    old_path_val  = old_path or typer.prompt(
        _T("Ruta actual de la carpeta en el dispositivo destino\n"
           "(deja vacío si quieres que el agente use la detección automática)"),
        default="",
    )
    api_key_val   = api_key_opt or typer.prompt(
        _T("API Key de Syncthing en el dispositivo destino\n"
           "(vacío = el agente intentará detectarla automáticamente)"),
        default="",
    )
    dev_name = device_name or typer.prompt(_T("Nombre del dispositivo"), default=_T("dispositivo-remoto"))
    new_fid_val = (new_folder_id or "").strip()
    if new_fid_val and new_fid_val == selected.id:
        err_console.print(f"[red]{_T('El nuevo ID es igual al actual.')}[/red]")
        raise typer.Exit(1)

    # If device_id is provided, use multi-device format (with identity verification).
    # Otherwise, fall back to legacy single-device format (runs on any machine).
    dev_id_val = device_id or typer.prompt(
        _T("ID de Syncthing del dispositivo\n"
           "(encuéntralo en Syncthing → Acciones → Identificación del dispositivo)\n"
           "(deja vacío para omitir verificación de identidad)"),
        default="",
    )

    passphrase = _ask_agent_passphrase()

    try:
        if dev_id_val:
            from .models import DeviceInfo
            target_device = DeviceInfo(
                device_id=dev_id_val,
                name=dev_name,
                ip=None,
                api_url=api_url_opt,
                api_key=api_key_val or None,
                folder_path=old_path_val or None,
                ssh_reachable=False,
                api_reachable=False,
                is_local=False,
            )
            out = generate_agent_file(
                device=target_device,
                folder_id=selected.id,
                new_label=new_label_val,
                new_dir_name=new_dir_val or new_label_val,
                skip_path_rename=skip_path,
                dry_run=dry_run,
                target_os=target_os,
                target_arch=eff_arch,
                output_dir=output_dir,
                new_folder_id=new_fid_val,
                passphrase=passphrase,
            )
            console.print(_T('\n[green]✓ Agente generado (con verificación de ID):[/green] {}').format(out))
            console.print(_T('[dim]Solo funcionará en el dispositivo con ID: {}…[/dim]').format(dev_id_val[:20]))
        else:
            console.print(_T("[yellow]⚠  Sin ID de dispositivo — el agente no verificará identidad y se ejecutará en cualquier máquina.[/yellow]"))
            out = generate_legacy_agent_file(
                device_name=dev_name,
                folder_id=selected.id,
                new_label=new_label_val,
                new_dir_name=new_dir_val or new_label_val,
                old_path=old_path_val,
                api_key=api_key_val,
                api_url=api_url_opt,
                skip_path_rename=skip_path,
                dry_run=dry_run,
                target_os=target_os,
                target_arch=eff_arch,
                output_dir=output_dir,
                new_folder_id=new_fid_val,
                passphrase=passphrase,
            )
            console.print(_T('\n[green]✓ Agente generado (sin verificación):[/green] {}').format(out))

        console.print(_T("[dim]Cópialo al dispositivo destino y ejecútalo directamente.[/dim]"))
        console.print(_T("[dim]No requiere Python ni instalación adicional.[/dim]"))
    except Exception as e:
        err_console.print(_T('[red]Error: {}[/red]').format(e))
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
