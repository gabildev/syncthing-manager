# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Linux agent template (console)."""

block_cipher = None

a = Analysis(
    ['agent_linux_entry.py'],
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
        # Lazily imported (credentials.py / agent.py) → static analysis misses them; name them
        # explicitly so encrypted agents + encrypted saved credentials work in the frozen build.
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
    excludes=['tkinter'],
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
    strip=True,
    upx=False,  # disabled: UPX-packed binaries are frequently false-flagged by Windows Defender/AV
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
