from __future__ import annotations
from .common import *  # noqa: F401,F403


class ConnectPageMixin:
    def _page_connect(self, f: tk.Frame):
        tk.Label(f, text="Conexión a Syncthing", bg="white",
                 font=(_FONT, 11, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Separator(f, orient="horizontal").grid(
            row=1, column=0, columnspan=3, sticky="ew", pady=(6, 14))

        # URL
        tk.Label(f, text="URL de la API:", bg="white").grid(row=2, column=0, sticky="w")
        url_v = tk.StringVar(value=self.s["url"])
        ttk.Entry(f, textvariable=url_v, width=46).grid(
            row=2, column=1, columnspan=2, sticky="w", padx=(10, 0), pady=3)

        # API Key
        tk.Label(f, text="API Key:", bg="white").grid(row=4, column=0, sticky="w", pady=(10, 0))
        key_v = tk.StringVar(value=self.s["api_key"])
        show_v = tk.BooleanVar()
        key_e = ttk.Entry(f, textvariable=key_v, width=42, show="●")
        key_e.grid(row=4, column=1, sticky="w", padx=(10, 0), pady=(10, 3))
        _CheckButton(f, text="Ver", variable=show_v,
                     command=lambda: key_e.config(show="" if show_v.get() else "●")
                     ).grid(row=4, column=2, sticky="w", padx=(6, 0), pady=(10, 0))

        auto_lbl = tk.Label(f, text="Detectando Syncthing...", bg="white",
                             fg="#888", font=(_FONT, 8))
        auto_lbl.grid(row=5, column=1, columnspan=2, sticky="w", padx=(10, 0))

        _autodetect_gen = self._show_gen

        def try_autodetect():
            # Detection pings the API, so run it off the main thread to avoid freezing
            # the UI; results are posted back via the drain queue.
            def work():
                info = detect_local_syncthing()

                def ui():
                    if self._show_gen != _autodetect_gen or not auto_lbl.winfo_exists():
                        return
                    if info["api_key"] and not key_v.get().strip():
                        key_v.set(info["api_key"])
                    # Only override the URL if the user hasn't customised it.
                    if info["url"] and url_v.get().strip() in ("", "https://127.0.0.1:8384"):
                        url_v.set(info["url"])
                    status = info["status"]
                    if status == "running":
                        auto_lbl.config(text=_T('✓  Syncthing detectado y en ejecución ({})').format(info['url']),
                                        fg="#2E7D32")
                    elif status == "installed_not_running":
                        auto_lbl.config(
                            text="⚠  Syncthing está instalado pero no parece estar en ejecución — arráncalo.",
                            fg="#C66000")
                    elif status == "bad_auth":
                        if info["api_key"]:
                            auto_lbl.config(
                                text="⚠  Syncthing responde pero la API Key guardada no es válida.",
                                fg="#C66000")
                        else:
                            auto_lbl.config(
                                text="✓  Syncthing en ejecución — introduce la API Key.",
                                fg="#2E7D32")
                    else:
                        auto_lbl.config(
                            text="No se detecta Syncthing — ¿está instalado y se ha ejecutado al menos una vez?",
                            fg="#C66000")
                self._post(ui)

            threading.Thread(target=work, daemon=True).start()
        self.after(120, try_autodetect)

        # SSH section
        ttk.Separator(f, orient="horizontal").grid(
            row=6, column=0, columnspan=3, sticky="ew", pady=(14, 8))

        ssh_expanded = tk.BooleanVar(value=False)
        ssh_frame = tk.Frame(f, bg="white")
        ssh_btn = ttk.Button(f, text="▶  Credenciales SSH globales (opcional — para automatizar acceso a todos los dispositivos)")
        ssh_btn.grid(row=7, column=0, columnspan=3, sticky="w")

        def toggle_ssh():
            if ssh_expanded.get():
                ssh_frame.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(6, 0))
                ssh_btn.config(text="▼  Credenciales SSH globales (opcional)")
            else:
                ssh_frame.grid_remove()
                ssh_btn.config(text="▶  Credenciales SSH globales (opcional — para automatizar acceso a todos los dispositivos)")
        ssh_btn.config(command=lambda: [ssh_expanded.set(not ssh_expanded.get()), toggle_ssh()])

        tk.Label(ssh_frame, text="  Útil si todos los dispositivos comparten las mismas credenciales SSH.",
                 bg="white", fg="#888", font=(_FONT, 8)).grid(
                 row=0, column=0, columnspan=3, sticky="w", pady=(2, 6))

        tk.Label(ssh_frame, text="  Usuario SSH:", bg="white").grid(row=1, column=0, sticky="w", pady=2)
        ssh_user_v = tk.StringVar(value=self.s["ssh_user"])
        ttk.Entry(ssh_frame, textvariable=ssh_user_v, width=24).grid(
            row=1, column=1, sticky="w", padx=(8, 0), pady=2)
        tk.Label(ssh_frame, text="  (vacío = auto)", bg="white", fg="#888",
                 font=(_FONT, 8)).grid(row=1, column=2, sticky="w", padx=(4, 0))

        tk.Label(ssh_frame, text="  Puerto SSH:", bg="white").grid(row=2, column=0, sticky="w", pady=2)
        ssh_port_v = tk.StringVar(value=str(self.s.get("ssh_port", 22)))
        ttk.Entry(ssh_frame, textvariable=ssh_port_v, width=8).grid(
            row=2, column=1, sticky="w", padx=(8, 0), pady=2)

        tk.Label(ssh_frame, text="  Clave privada:", bg="white").grid(row=3, column=0, sticky="w", pady=2)
        ssh_key_v = tk.StringVar(value=self.s["ssh_key"])
        key_row = tk.Frame(ssh_frame, bg="white")
        key_row.grid(row=3, column=1, columnspan=2, sticky="w", padx=(8, 0), pady=2)
        ttk.Entry(key_row, textvariable=ssh_key_v, width=30).pack(side=tk.LEFT)
        ttk.Button(key_row, text="…", width=3,
                   command=lambda: ssh_key_v.set(
                       filedialog.askopenfilename(title=_T("Seleccionar clave privada SSH")) or ssh_key_v.get()
                   )).pack(side=tk.LEFT, padx=(4, 0))

        tk.Label(ssh_frame, text="  Contraseña SSH:", bg="white").grid(row=4, column=0, sticky="w", pady=2)
        ssh_pass_v = tk.StringVar(value=self.s.get("ssh_password", ""))
        ttk.Entry(ssh_frame, textvariable=ssh_pass_v, width=24, show="●").grid(
            row=4, column=1, sticky="w", padx=(8, 0), pady=2)
        tk.Label(ssh_frame, text="  (alternativa a clave)", bg="white", fg="#888",
                 font=(_FONT, 8)).grid(row=4, column=2, sticky="w", padx=(4, 0))

        f.columnconfigure(1, weight=1)

        def do_connect():
            url = url_v.get().strip()
            key = key_v.get().strip()
            if not key:
                messagebox.showerror("API Key requerida",
                                     "Introduce la API Key de Syncthing.\n\n"
                                     "La encontrarás en: Acciones → Configuración → General.")
                return
            try:
                _port = int(ssh_port_v.get().strip() or "22")
            except ValueError:
                _port = 22
            self.s.update({"url": url, "api_key": key,
                           "ssh_user": ssh_user_v.get().strip(),
                           "ssh_key": ssh_key_v.get().strip(),
                           "ssh_password": ssh_pass_v.get().strip(),
                           "ssh_port": _port})
            self._btn_next.config(state="disabled")
            self._status("Conectando...", "#555")
            my_gen = self._show_gen

            def work():
                try:
                    client = SyncthingClient(url, key, verify_ssl=False)
                    if self._show_gen != my_gen:
                        return
                    if client.ping():
                        self.s["client"] = client
                        self._post(lambda: self._show(1))
                    else:
                        self._post(lambda: (
                            self._status("No se pudo conectar", "#C62828"),
                            self._btn_next.config(state="normal"),
                            messagebox.showerror(
                                "Sin conexión",
                                _T('No se puede conectar a:\n{}\n\n• Comprueba que Syncthing está en ejecución\n• Verifica la URL (¿http o https?)\n• Verifica la API Key').format(url)
                            ),
                        ))
                except Exception as e:
                    self._post(lambda err=str(e): (
                        self._status(_T('Error inesperado: {}').format(err), "#C62828"),
                        self._btn_next.config(state="normal"),
                    ))
            threading.Thread(target=work, daemon=True).start()

        self._next_handlers[0] = do_connect
        self._btn_next.config(text="Conectar →")
