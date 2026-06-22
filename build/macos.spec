# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the macOS executable (GUI + CLI fallback).

macOS = POSIX, so the app behaves like the Linux build; only the binary format differs (Mach-O),
which is why it must be built on a macOS runner. Mirrors linux.spec."""

import os

block_cipher = None

# Embed EVERY agent template present so a single macOS app can generate agents for any OS/arch in
# the cluster (#5a, --add-data; extracted to _MEIPASS at startup). Build the templates BEFORE this
# spec. If a template is absent the bundle simply omits it (templates can still sit next to the app).
_embed_datas = []
for _name in ("syncthing-manager-agent-template",
              "syncthing-manager-agent-template-macos-amd64",
              "syncthing-manager-agent-template-macos-arm64",
              "syncthing-manager-agent-template-linux-amd64",
              "syncthing-manager-agent-template-linux-arm64",
              "syncthing-manager-agent-template.exe"):
    # Prefer FRESH dist/ outputs; fall back to the Syncthing-synced build/prebuilt/ stash LAST so a
    # committed/stale prebuilt template can't shadow a fresh CI build (see linux.spec note).
    for _cand in (os.path.join("dist", "macos", _name),
                  os.path.join("dist", "linux", _name),
                  os.path.join("dist", "windows", _name),
                  os.path.join("dist", _name),
                  os.path.join("build", "prebuilt", _name)):
        if os.path.exists(_cand):
            _embed_datas.append((os.path.abspath(_cand), "."))
            break

# Bundle the app icon PNG so the running GUI can set its window icon (cross-platform via iconphoto).
_icon_png = os.path.join(SPECPATH, os.pardir, "assets", "icon.png")
if os.path.exists(_icon_png):
    _embed_datas.append((os.path.abspath(_icon_png), "assets"))

a = Analysis(
    ['macos_entry.py'],
    pathex=['.'],
    binaries=[],
    datas=_embed_datas,
    hiddenimports=[
        'syncthing_manager',
        'syncthing_manager.cli',
        'syncthing_manager.gui',
        'syncthing_manager.gui.app',
        'syncthing_manager.gui.common',
        'syncthing_manager.gui.settings',
        'syncthing_manager.gui.page_connect',
        'syncthing_manager.gui.page_folder',
        'syncthing_manager.gui.page_devices',
        'syncthing_manager.gui.page_names',
        'syncthing_manager.gui.page_topology',
        'syncthing_manager.gui.page_execute',
        'syncthing_manager.applock',
        'syncthing_manager.syncthing',
        'syncthing_manager.discovery',
        'syncthing_manager.renamer',
        'syncthing_manager.ssh_ops',
        'syncthing_manager.winrm_ops',
        'syncthing_manager.credentials',
        'syncthing_manager.agent',
        'syncthing_manager.generate',
        'syncthing_manager.models',
        'tkinter',
        'tkinter.ttk',
        'tkinter.filedialog',
        'tkinter.messagebox',
        'winrm',
        'winrm.protocol',
        'requests_ntlm',
        'xmltodict',
        'paramiko',
        'paramiko.transport',
        'paramiko.ed25519key',
        'cryptography',
        'cryptography.hazmat.primitives.asymmetric.ed25519',
        # Lazily imported (credentials.py / agent.py) → name explicitly so encrypted agents +
        # encrypted saved credentials work in the frozen build.
        'cryptography.fernet',
        'cryptography.hazmat.primitives.hashes',
        'cryptography.hazmat.primitives.kdf.pbkdf2',
        'nacl',
        'bcrypt',
        '_cffi_backend',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# onedir build (#87): same rationale as Linux — the COLLECT folder `syncthing-manager` is what the
# distributed tar.gz extracts to.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='syncthing-manager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,  # stripping a Mach-O can break it / future codesigning
    upx=False,
    upx_exclude=[],
    console=True,       # keep terminal for CLI fallback and log output
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='syncthing-manager',
)
