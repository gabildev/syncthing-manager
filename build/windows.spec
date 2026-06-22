# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Windows GUI executable."""

import os

block_cipher = None

# Embed BOTH agent templates (this OS + the other) when present (#5a, --add-data;
# extracted to _MEIPASS at startup). Build the templates BEFORE this spec.
_embed_datas = []
# Windows .exe + every Linux template present (un-suffixed for backward compat + per-arch so a
# Windows host can generate amd64 OR arm64 Linux agents). generate._find_agent_template picks.
for _name in ("syncthing-manager-agent-template.exe",
              "syncthing-manager-agent-template",
              "syncthing-manager-agent-template-linux-amd64",
              "syncthing-manager-agent-template-linux-arm64",
              "syncthing-manager-agent-template-macos-amd64",
              "syncthing-manager-agent-template-macos-arm64"):
    # Prefer FRESH dist/ outputs; fall back to the Syncthing-synced build/prebuilt/ stash LAST so
    # a committed/stale prebuilt template can't shadow a fresh CI build (see linux.spec note).
    for _cand in (os.path.join("dist", "windows", _name),
                  os.path.join("dist", "linux", _name),
                  os.path.join("dist", "macos", _name),
                  os.path.join("dist", _name),
                  os.path.join("build", "prebuilt", _name)):
        if os.path.exists(_cand):
            _embed_datas.append((os.path.abspath(_cand), "."))
            break

# Bundle the app icon PNG so the running GUI can set its window icon (cross-platform).
_icon_png = os.path.join(SPECPATH, os.pardir, "assets", "icon.png")
if os.path.exists(_icon_png):
    _embed_datas.append((os.path.abspath(_icon_png), "assets"))
# Windows .exe file icon (guarded: a missing icon.ico must not break the build → None).
_ico = os.path.join(SPECPATH, "icon.ico")
_ico = _ico if os.path.exists(_ico) else None

a = Analysis(
    ['windows_entry.py'],
    pathex=['.'],
    binaries=[],
    datas=_embed_datas,
    hiddenimports=[
        'syncthing_manager',
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
        'syncthing_manager.cli',
        'syncthing_manager.syncthing',
        'syncthing_manager.discovery',
        'syncthing_manager.renamer',
        'syncthing_manager.ssh_ops',
        'syncthing_manager.winrm_ops',
        'syncthing_manager.credentials',
        'syncthing_manager.models',
        'winrm',
        'winrm.protocol',
        'requests_ntlm',
        'xmltodict',
        # paramiko / cryptography require explicit collection
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
        # tkinter
        'tkinter',
        'tkinter.ttk',
        'tkinter.filedialog',
        'tkinter.messagebox',
        'tkinter.scrolledtext',
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

# onedir build (#87): the EXE holds only the bootloader/scripts; binaries + the embedded
# agent templates live alongside it in the output folder, so launching does NOT extract a
# ~30 MB archive to a temp dir every time (that was the dominant startup cost of onefile).
# Distribute the resulting `dist/windows/syncthing-manager/` folder as a .zip.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='syncthing-manager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # disabled: UPX-packed binaries are frequently false-flagged by Windows Defender/AV
    upx_exclude=[],
    console=False,      # No console window — pure GUI
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_ico,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,  # disabled: UPX-packed binaries are frequently false-flagged by Windows Defender/AV
    upx_exclude=[],
    name='syncthing-manager',
)
