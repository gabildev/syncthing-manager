from __future__ import annotations
from .common import *  # noqa: F401,F403


class SettingsMixin:
    def _open_settings(self):
        """Settings: 'show advanced options' toggle + data-directory (portable) management."""
        dlg = tk.Toplevel(self)
        dlg.title("Configuración")
        dlg.configure(bg="white")
        dlg.grab_set()
        self._center_dialog(dlg)
        tk.Label(dlg, text="Configuración", bg="white",
                 font=(_FONT, 11, "bold")).pack(anchor="w", padx=16, pady=(12, 8))

        # ── Advanced options toggle ──
        adv_var = tk.BooleanVar(value=bool(self.s.get("advanced", False)))

        def _toggle_adv():
            self.s["advanced"] = adv_var.get()
            appconfig.set_setting("advanced", adv_var.get())
            # Re-render ONLY the Topología page — it's the only page with an advanced-gated
            # build-time widget (the red cluster-delete button), so it must appear/disappear
            # immediately instead of only after navigating away and back. We deliberately don't
            # rebuild other pages: that would drop half-typed, not-yet-committed input (e.g. the
            # API key on Conexión, a label on Nombres). The settings dialog is a child of the
            # root, not of the page frame, so it survives the rebuild.
            if self._step == STEPS.index("Topología"):
                self._show(self._step)
        tk.Checkbutton(dlg, text="Mostrar opciones avanzadas (config completa de carpeta/dispositivo)",
                       variable=adv_var, bg="white", font=(_FONT, 9), command=_toggle_adv,
                       wraplength=440, justify="left", anchor="w").pack(fill=tk.X, anchor="w", padx=16)

        # ── Security ──
        tk.Label(dlg, text="Seguridad:", bg="white", fg="#555",
                 font=(_FONT, 9, "bold")).pack(anchor="w", padx=16, pady=(8, 0))
        sec_var = tk.BooleanVar(value=bool(appconfig.get_setting("prefer_secure_channel", False)))

        def _toggle_sec():
            appconfig.set_setting("prefer_secure_channel", sec_var.get())
        tk.Checkbutton(dlg, text="Preferir canal cifrado (SSH/WinRM) para equipos remotos en vez "
                                 "de la API directa — evita exponer la API Key en la red",
                       variable=sec_var, bg="white", font=(_FONT, 9), command=_toggle_sec,
                       wraplength=460, justify="left", anchor="w").pack(fill=tk.X, anchor="w", padx=16)
        strict_var = tk.BooleanVar(value=bool(appconfig.get_setting("ssh_strict_host_keys", False)))

        def _toggle_strict():
            appconfig.set_setting("ssh_strict_host_keys", strict_var.get())
        tk.Checkbutton(dlg, text="SSH estricto: rechazar hosts cuya clave no esté en known_hosts "
                                 "(evita MITM en la primera conexión; requiere añadirlos a mano)",
                       variable=strict_var, bg="white", font=(_FONT, 9), command=_toggle_strict,
                       wraplength=460, justify="left", anchor="w").pack(fill=tk.X, anchor="w", padx=16)
        winrm_cert_var = tk.BooleanVar(value=bool(appconfig.get_setting("winrm_strict_cert", False)))

        def _toggle_winrm_cert():
            appconfig.set_setting("winrm_strict_cert", winrm_cert_var.get())
        tk.Checkbutton(dlg, text="WinRM sobre HTTPS estricto: validar el certificado del servidor "
                                 "(rechaza certificados no confiables; déjalo apagado si usas "
                                 "WinRM por HTTP o certificados autofirmados)",
                       variable=winrm_cert_var, bg="white", font=(_FONT, 9),
                       command=_toggle_winrm_cert,
                       wraplength=460, justify="left", anchor="w").pack(fill=tk.X, anchor="w", padx=16)

        ttk.Separator(dlg, orient="horizontal").pack(fill=tk.X, padx=16, pady=10)

        # ── Language (applies on restart) ──
        tk.Label(dlg, text="Idioma:", bg="white", fg="#555",
                 font=(_FONT, 9, "bold")).pack(anchor="w", padx=16)
        # Option display labels are translated explicitly (combobox values aren't widget
        # `text`, so the shim doesn't touch them).
        _lang_opts = [("auto", _T("Automático (idioma del sistema)")),
                      ("es", _T("Español")), ("en", _T("Inglés"))]
        _cur_lang = appconfig.get_setting("language", "auto")
        lang_var = tk.StringVar(
            value=dict((v, d) for v, d in _lang_opts).get(_cur_lang, _lang_opts[0][1]))
        lrow = tk.Frame(dlg, bg="white")
        lrow.pack(anchor="w", padx=16, pady=(2, 0))
        lang_cb = ttk.Combobox(lrow, textvariable=lang_var, state="readonly",
                               values=[d for _v, d in _lang_opts], width=28)
        lang_cb.pack(side=tk.LEFT)
        lang_note = tk.Label(dlg, text="", bg="white", fg="#888", font=(_FONT, 8))
        lang_note.pack(anchor="w", padx=16)

        def _restart_app():
            """Relaunch the process so the new language takes effect. The i18n shim can only be
            installed at process start (it monkeypatches widget creation and can't be un-patched
            live), so applying a language change in-place isn't reliable — a clean relaunch is.
            Works for the frozen binary (sys.argv[0] is the exe) and the pip-installed GUI."""
            import os
            import subprocess
            args = list(sys.argv) if getattr(sys, "frozen", False) else [sys.executable, *sys.argv]
            try:
                subprocess.Popen(args, close_fds=False)
            except Exception:
                messagebox.showinfo("Idioma",
                                    "Reinicia la aplicación para aplicar el idioma.", parent=self)
                return
            os._exit(0)   # hard-exit so the old GUI/daemon threads don't linger behind the new one

        def _save_lang(_e=None):
            disp = lang_var.get()
            val = next((v for v, d in _lang_opts if d == disp), "auto")
            if val == appconfig.get_setting("language", "auto"):
                return
            appconfig.set_setting("language", val)
            if messagebox.askyesno(
                    "Idioma",
                    "El idioma se aplica al reiniciar la aplicación. ¿Reiniciar ahora? "
                    "(se perderá el progreso no guardado)", parent=dlg):
                _restart_app()
            else:
                lang_note.config(text="El idioma se aplicará al reiniciar la aplicación.")
        lang_cb.bind("<<ComboboxSelected>>", _save_lang)

        ttk.Separator(dlg, orient="horizontal").pack(fill=tk.X, padx=16, pady=10)

        # ── App lock (Part 2) — optional password protection ──
        from .. import applock as _applock
        tk.Label(dlg, text="Protección con contraseña (candado de la app):", bg="white",
                 fg="#555", font=(_FONT, 9, "bold")).pack(anchor="w", padx=16)
        tk.Label(dlg, text="Disuasorio para la app desatendida. NO protege contra acceso a tus "
                           "ficheros (la API Key está en el config de Syncthing). Recuperable "
                           "borrando «applock» en settings.json.",
                 bg="white", fg="#888", font=(_FONT, 8), wraplength=470,
                 justify="left").pack(anchor="w", padx=16)
        _lk = _applock.get_lock()
        lock_method_v = tk.StringVar(value=_lk.get("method", "off"))

        def _toggle_pw(*_):
            # The custom-password fields only make sense for the "Contraseña propia" method —
            # hide them for "Desactivado" and "Contraseña de Syncthing". Packed right before the
            # inactivity row to keep the dialog order.
            if lock_method_v.get() == "custom":
                _cf.pack(before=_irow, anchor="w", padx=16, pady=(2, 0))
            else:
                _cf.pack_forget()

        _lf = tk.Frame(dlg, bg="white")
        _lf.pack(anchor="w", padx=16, pady=(2, 0))
        ttk.Radiobutton(_lf, text="Desactivado", value="off",
                        variable=lock_method_v, command=_toggle_pw).pack(side=tk.LEFT)
        ttk.Radiobutton(_lf, text="Contraseña propia", value="custom",
                        variable=lock_method_v, command=_toggle_pw).pack(side=tk.LEFT, padx=(8, 0))
        if _applock.syncthing_has_gui_password():
            ttk.Radiobutton(_lf, text="Contraseña de Syncthing", value="syncthing",
                            variable=lock_method_v, command=_toggle_pw).pack(side=tk.LEFT, padx=(8, 0))
        _cf = tk.Frame(dlg, bg="white")   # packed/hidden by _toggle_pw based on the method
        _pw1 = tk.StringVar()
        _pw2 = tk.StringVar()
        tk.Label(_cf, text="Contraseña propia:", bg="white", anchor="e", width=16).grid(
            row=0, column=0, sticky="e", pady=1)
        ttk.Entry(_cf, textvariable=_pw1, width=20, show="●").grid(row=0, column=1, padx=(6, 0))
        tk.Label(_cf, text="Repetir:", bg="white", anchor="e", width=16).grid(
            row=1, column=0, sticky="e", pady=1)
        ttk.Entry(_cf, textvariable=_pw2, width=20, show="●").grid(row=1, column=1, padx=(6, 0))
        _inact_on = tk.BooleanVar(value=int(_lk.get("inactivity_min", 0) or 0) > 0)
        _inact_min = tk.StringVar(value=str(_lk.get("inactivity_min", 0) or 15))
        _irow = tk.Frame(dlg, bg="white")
        _irow.pack(anchor="w", padx=16, pady=(4, 0))
        tk.Checkbutton(_irow, text="Bloquear tras inactividad (min):", variable=_inact_on,
                       bg="white").pack(side=tk.LEFT)
        ttk.Entry(_irow, textvariable=_inact_min, width=5).pack(side=tk.LEFT, padx=(4, 0))
        _toggle_pw()   # set initial visibility now that _irow exists (pack anchor)
        _lock_note = tk.Label(dlg, text="", bg="white", fg="#888", font=(_FONT, 8))
        _lock_note.pack(anchor="w", padx=16)

        def _save_lock():
            m = lock_method_v.get()
            if m == "custom":
                if not _pw1.get():
                    _lock_note.config(text="La contraseña no puede estar vacía.", fg="#C62828")
                    return
                if _pw1.get() != _pw2.get():
                    _lock_note.config(text="Las contraseñas no coinciden.", fg="#C62828")
                    return
                _applock.set_custom_password(_pw1.get())
            elif m == "syncthing":
                _applock.set_syncthing_method()
            else:
                _applock.disable()
            try:
                _applock.set_inactivity_minutes(int(_inact_min.get()) if _inact_on.get() else 0)
            except ValueError:
                pass
            self._idle_reset()
            _pw1.set("")
            _pw2.set("")
            _lock_note.config(text="✓ Candado guardado.", fg="#2E7D32")

        _lbtns = tk.Frame(dlg, bg="white")
        _lbtns.pack(anchor="w", padx=16, pady=(4, 0))
        ttk.Button(_lbtns, text="Guardar candado", command=_save_lock).pack(side=tk.LEFT)
        ttk.Button(_lbtns, text="🔒 Bloquear ahora",
                   command=lambda: (dlg.destroy(), self.after(150, self._lock_now))
                   ).pack(side=tk.LEFT, padx=(6, 0))

        ttk.Separator(dlg, orient="horizontal").pack(fill=tk.X, padx=16, pady=10)

        # ── Default ports (used as prefills when adding/probing devices) ──
        tk.Label(dlg, text="Puertos por defecto:", bg="white", fg="#555",
                 font=(_FONT, 9, "bold")).pack(anchor="w", padx=16)
        prow = tk.Frame(dlg, bg="white")
        prow.pack(anchor="w", padx=16, pady=(2, 0))
        _ports = {
            "default_ssh_port":   (tk.StringVar(value=str(appconfig.get_setting("default_ssh_port", 22))), "SSH"),
            "default_winrm_port": (tk.StringVar(value=str(appconfig.get_setting("default_winrm_port", 5985))), "WinRM"),
            "default_api_port":   (tk.StringVar(value=str(appconfig.get_setting("default_api_port", 8384))), "API"),
        }
        for key, (var, lbl) in _ports.items():
            tk.Label(prow, text=lbl + ":", bg="white", font=(_FONT, 8)).pack(side=tk.LEFT)
            ttk.Entry(prow, textvariable=var, width=7).pack(side=tk.LEFT, padx=(2, 10))

        def _save_ports():
            for key, (var, _lbl) in _ports.items():
                try:
                    appconfig.set_setting(key, int(var.get().strip()))
                except Exception:
                    pass

        # ── API-on-LAN check (local Syncthing) ──
        lan_lbl = tk.Label(dlg, text="", bg="white", fg="#555", font=(_FONT, 8),
                           wraplength=460, justify="left")

        def _check_lan():
            client = self.s.get("client")
            if not client:
                lan_lbl.config(text="Conéctate a Syncthing primero para comprobarlo.", fg="#C66000")
                return
            addr = client.get_gui_address()
            if addr is None:
                lan_lbl.config(text="No se pudo leer la dirección de la API.", fg="#C62828")
            elif SyncthingClient.address_is_lan(addr):
                lan_lbl.config(text=_T('✓ API expuesta en LAN ({}) — los equipos pueden configurarse por IP:puerto directamente.').format(addr), fg="#2E7D32")
            else:
                lan_lbl.config(text=_T('API solo local ({}). Para acceso directo por IP, en Syncthing pon la dirección de la GUI en 0.0.0.0:PUERTO; si no, se usará SSH/WinRM o el agente.').format(addr), fg="#C66000")
        ttk.Button(dlg, text="Comprobar API-on-LAN (equipo local)",
                   command=_check_lan).pack(anchor="w", padx=16, pady=(8, 0))
        lan_lbl.pack(anchor="w", padx=16, pady=(2, 0))

        ttk.Separator(dlg, orient="horizontal").pack(fill=tk.X, padx=16, pady=10)

        # ── Data directory (portable) ──
        tk.Label(dlg, text="Carpeta de datos (credenciales y ajustes):", bg="white",
                 fg="#555", font=(_FONT, 9, "bold")).pack(anchor="w", padx=16)
        dir_var = tk.StringVar(value=str(appconfig.data_dir()))
        drow = tk.Frame(dlg, bg="white")
        drow.pack(fill=tk.X, padx=16, pady=(2, 0))
        dir_entry = ttk.Entry(drow, textvariable=dir_var, width=44, state="readonly")
        dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        mode_lbl = tk.Label(dlg, bg="white", fg="#888", font=(_FONT, 8))
        mode_lbl.pack(anchor="w", padx=16)

        def _refresh_mode():
            dir_var.set(str(appconfig.data_dir()))
            mode_lbl.config(text="Modo portable (junto al programa)" if appconfig.is_portable()
                            else "Carpeta estándar / personalizada")
        _refresh_mode()

        def _relocate(target):
            try:
                appconfig.set_data_dir(target, move=True)
            except Exception as e:
                messagebox.showerror("Carpeta de datos", _T('No se pudo mover: {}').format(e), parent=dlg)
                return
            _refresh_mode()
            self._status(_T('Carpeta de datos: {}').format(appconfig.data_dir()), "#2E7D32")

        brow = tk.Frame(dlg, bg="white")
        brow.pack(fill=tk.X, padx=16, pady=(6, 0))
        ad = appconfig.app_dir()
        if ad:
            ttk.Button(brow, text="Portable (junto al programa)",
                       command=lambda: _relocate(ad)).pack(side=tk.LEFT)
        ttk.Button(brow, text="Carpeta personalizada…",
                   command=lambda: (lambda d: _relocate(d) if d else None)(
                       filedialog.askdirectory(parent=dlg, title="Elegir carpeta de datos"))
                   ).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(brow, text="Estándar del sistema",
                   command=lambda: _relocate(appconfig.os_standard_dir())).pack(side=tk.LEFT, padx=(6, 0))
        tk.Label(dlg, text="Al cambiarla se mueven las credenciales y ajustes a la nueva carpeta.",
                 bg="white", fg="#888", font=(_FONT, 8), wraplength=440,
                 justify="left").pack(anchor="w", padx=16, pady=(6, 0))

        def _close():
            _save_ports()
            dlg.destroy()
        ttk.Button(dlg, text="Cerrar", command=_close).pack(side=tk.RIGHT, padx=16, pady=14)
        # Closing via the window-manager X must ALSO persist the default-port edits, not discard
        # them silently (the «Cerrar» button isn't the only way out of the dialog).
        dlg.protocol("WM_DELETE_WINDOW", _close)
