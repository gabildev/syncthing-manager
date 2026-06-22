# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Windows agent template (GUI, no console)."""

import os

block_cipher = None

# Windows .exe file icon (guarded: a missing icon.ico must not break the build → None).
_ico = os.path.join(SPECPATH, "icon.ico")
_ico = _ico if os.path.exists(_ico) else None

a = Analysis(
    ['agent_windows_entry.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=[
        'syncthing_manager',
        'syncthing_manager.agent',
        'syncthing_manager.i18n',
        'syncthing_manager.translations_en',
        'syncthing_manager.renamer',
        'syncthing_manager.syncthing',
        'syncthing_manager.models',
        'syncthing_manager.ssh_ops',
        'syncthing_manager.discovery',
        'syncthing_manager.credentials',
        'cryptography',
        'cryptography.hazmat.primitives.asymmetric.ed25519',
        # Lazily imported (credentials.py / agent.py) → name explicitly so encrypted agents +
        # encrypted saved credentials work in the frozen build.
        'cryptography.fernet',
        'cryptography.hazmat.primitives.hashes',
        'cryptography.hazmat.primitives.kdf.pbkdf2',
        'tkinter',
        'tkinter.ttk',
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

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='syncthing-manager-agent-template',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # disabled: UPX-packed binaries are frequently false-flagged by Windows Defender/AV
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_ico,
)
