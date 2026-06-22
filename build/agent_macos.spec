# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the macOS agent template (console / Aqua GUI fallback).

macOS = POSIX, so the agent CODE is identical to Linux's; only the BINARY differs (Mach-O, not
ELF), which is why it must be built on a macOS runner. target_arch=None → builds for the runner's
native arch (the CI runs this on both an Intel and an Apple-Silicon runner)."""

block_cipher = None

a = Analysis(
    ['agent_macos_entry.py'],
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
    strip=False,  # stripping a Mach-O can break it / future codesigning; harmless to keep symbols
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,  # native arch of the building runner (Intel runner → x86_64, AS → arm64)
    codesign_identity=None,
    entitlements_file=None,
)
