#!/usr/bin/env bash
# Builds dist/macos/syncthing-manager/ (onedir folder) + the macOS agent template.
# Run from the project root, ON A MAC (PyInstaller does not cross-compile: a Mach-O binary is
# only built on macOS, just like the Linux ELF only on Linux).
#
# Usage:  build/build_macos.sh [--no-package]
#   --no-package (aliases --no-pack / --skip-package): do NOT build the .tar.gz, leave only the
#   onedir folder dist/macos/syncthing-manager/ -- handy for fast iteration while testing.
set -euo pipefail

NO_PACKAGE=0
for _arg in "$@"; do
    case "$_arg" in
        --no-package|--no-pack|--skip-package) NO_PACKAGE=1 ;;
        *) echo "Unknown argument: $_arg (usage: $0 [--no-package])" >&2; exit 2 ;;
    esac
done

PYTHON="${PYTHON:-python3}"
echo "Using: $PYTHON"
"$PYTHON" --version

# Make the in-tree package importable for PyInstaller even when it isn't pip-installed.
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

echo
echo "Preparing build dependencies..."
if "$PYTHON" -c "import PyInstaller, paramiko, cryptography, typer, syncthing_manager" 2>/dev/null; then
    echo "  Dependencies already present -- skipping installation."
elif "$PYTHON" -m pip install pyinstaller -e . -q 2>/dev/null; then
    echo "  Dependencies installed with pip."
else
    # System Python refuses a direct install (PEP 668 externally-managed) → use a local build venv.
    echo "  Direct pip unavailable (PEP 668?) -- using the build venv build_venv/ ..."
    "$PYTHON" -m venv build_venv
    PYTHON="$PWD/build_venv/bin/python"
    "$PYTHON" -m pip install -q --upgrade pip
    "$PYTHON" -m pip install pyinstaller -e . -q
fi

# (Re)generate the app icon from source (best-effort). The specs fall back to no icon if this
# fails, so a missing Pillow never breaks the build.
"$PYTHON" assets/make_icon.py 2>/dev/null \
    || { "$PYTHON" -m pip install pillow -q 2>/dev/null && "$PYTHON" assets/make_icon.py; } \
    || echo "  (note: could not generate the icon -- building without one)"

echo
echo "Building macOS agent (for devices without remote access)..."
"$PYTHON" -m PyInstaller build/agent_macos.spec --distpath dist/macos --workpath build_tmp --noconfirm

# Stash the freshly built macOS template in the PERSISTENT, synced build/prebuilt/ so it survives
# the post-build cleanup AND is available — via Syncthing — on the other build machines to embed
# into their executables (cross-OS agent generation, #5a). Suffix it by THIS Mac's arch so an
# Intel + an Apple-Silicon Mac don't overwrite each other's template.
ARCH="$(uname -m)"
case "$ARCH" in
    arm64|aarch64) ARCH_TAG="arm64" ;;
    x86_64|amd64)  ARCH_TAG="amd64" ;;
    *)             ARCH_TAG="$ARCH" ;;
esac
mkdir -p build/prebuilt
cp -f dist/macos/syncthing-manager-agent-template \
      "build/prebuilt/syncthing-manager-agent-template-macos-${ARCH_TAG}" 2>/dev/null || true
# Also expose it under the arch-suffixed name in dist/macos so macos.spec embeds it for THIS arch.
cp -f dist/macos/syncthing-manager-agent-template \
      "dist/macos/syncthing-manager-agent-template-macos-${ARCH_TAG}" 2>/dev/null || true

echo
echo "Building main executable (macOS, with embedded templates if present)..."
"$PYTHON" -m PyInstaller build/macos.spec --distpath dist/macos --workpath build_tmp --noconfirm

# The templates are now EMBEDDED in the program folder (extracted on demand when generating an
# agent), so we delete the loose template binaries from dist/. NOTE: we do NOT delete
# build/prebuilt/ (it is the persistent store for the cross-embed).
rm -f dist/macos/syncthing-manager-agent-template \
      dist/macos/syncthing-manager-agent-template-macos-*

# Resilient (set -e): a leftover that can't be deleted must not abort the build before packaging.
rm -rf build_tmp 2>/dev/null || true

# onedir build (#87): the output is the FOLDER dist/macos/syncthing-manager/. We package it into
# a .tar.gz with an arch suffix to tell Intel vs Apple Silicon apart when downloading.
if [ "$NO_PACKAGE" -eq 0 ]; then
    echo
    echo "Packaging dist/macos/syncthing-manager-macos-${ARCH_TAG}.tar.gz ..."
    cp -f LICENSE THIRD_PARTY_LICENSES.md dist/macos/syncthing-manager/ 2>/dev/null || true
    rm -f "dist/macos/syncthing-manager-macos-${ARCH_TAG}.tar.gz"
    tar -czf "dist/macos/syncthing-manager-macos-${ARCH_TAG}.tar.gz" -C dist/macos syncthing-manager
else
    echo
    echo "Skipping packaging (--no-package): onedir folder only."
fi

# Final cleanup.
rm -rf build/__pycache__ build/build build/dist build_tmp ./*.egg-info 2>/dev/null || true

echo
echo "============================================="
if [ "$NO_PACKAGE" -eq 0 ]; then
    echo " Done in dist/macos/ (onedir folder + tar.gz, arch=${ARCH_TAG}):"
    echo "   syncthing-manager/syncthing-manager           (agent templates embedded)"
    echo "   syncthing-manager-macos-${ARCH_TAG}.tar.gz    (for distribution; extracts to syncthing-manager/)"
else
    echo " Done in dist/macos/ (onedir folder only, not packaged):"
    echo "   syncthing-manager/syncthing-manager           (agent templates embedded)"
fi
echo "============================================="
