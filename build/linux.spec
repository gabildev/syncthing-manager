# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Linux/WSL executable (GUI + CLI fallback)."""

import os

block_cipher = None

# Embed BOTH agent templates (this OS + the other) when present, so a single exe can
# generate Windows AND Linux agents (#5, option a: --add-data; extracted to _MEIPASS at
# startup). Build the agent templates BEFORE this spec so they exist here. If absent the
# bundle simply omits them (templates can still sit next to the exe).
_embed_datas = []
# Embed every template present: the un-suffixed one (local single-arch build / backward compat),
# the per-arch Linux ones (CI multi-arch → one build serves amd64 AND arm64 Linux agents), and
# the Windows .exe (cross-OS). generate._find_agent_template picks the right one by target arch.
for _name in ("syncthing-manager-agent-template",
              "syncthing-manager-agent-template-linux-amd64",
              "syncthing-manager-agent-template-linux-arm64",
              "syncthing-manager-agent-template-macos-amd64",
              "syncthing-manager-agent-template-macos-arm64",
              "syncthing-manager-agent-template.exe"):
    # Prefer the FRESH build outputs in dist/ (CI artifacts + the freshly built local template);
    # fall back to build/prebuilt/ LAST. build/prebuilt/ is a PERSISTENT, Syncthing-synced stash
    # of the OTHER OS's template (built on the other machine) — it must NOT shadow a fresh dist/
    # build, or CI (whose checkout may carry a committed, stale build/prebuilt/) would embed an
    # outdated template. dist/ first guarantees the just-built bytes win.
    for _cand in (os.path.join("dist", "linux", _name),
                  os.path.join("dist", "macos", _name),
                  os.path.join("dist", "windows", _name),
                  os.path.join("dist", _name),
                  os.path.join("build", "prebuilt", _name)):
        if os.path.exists(_cand):
            _embed_datas.append((os.path.abspath(_cand), "."))
            break

# Bundle the app icon PNG so the running GUI can set its window icon (the Linux ELF itself
# carries no embedded icon, so the window icon is the meaningful one on Linux).
_icon_png = os.path.join(SPECPATH, os.pardir, "assets", "icon.png")
if os.path.exists(_icon_png):
    _embed_datas.append((os.path.abspath(_icon_png), "assets"))

a = Analysis(
    ['linux_entry.py'],
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

# onedir build (#87): the binary holds only bootloader/scripts; libraries + the embedded
# agent templates sit alongside it, so launching doesn't extract a ~30 MB archive to a temp
# dir each time. The COLLECT folder is named `syncthing-manager` (mirrors the Windows build)
# so the distributed `dist/linux/syncthing-manager.tar.gz` extracts to a `syncthing-manager/`
# parent folder.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='syncthing-manager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=False,  # disabled: UPX-packed binaries are frequently false-flagged by Windows Defender/AV
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
    strip=True,
    upx=False,  # disabled: UPX-packed binaries are frequently false-flagged by Windows Defender/AV
    upx_exclude=[],
    name='syncthing-manager',
)
