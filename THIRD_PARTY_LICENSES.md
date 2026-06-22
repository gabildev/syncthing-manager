# Third-party licenses

`syncthing-manager` itself is licensed under the **MIT License** (see [`LICENSE`](LICENSE)).

The distributed binaries (the onedir `syncthing-manager` folder and the agent templates) are
built with **PyInstaller** and bundle the Python runtime plus the third-party libraries below.
Each remains under its own license; this file collects the attributions. PyInstaller only embeds
what is actually imported, so a given build may include a subset of this list.

All bundled licenses are compatible with redistribution. Two carry obligations beyond simple
attribution — read the callouts.

## Libraries

| Library | License |
|---|---|
| paramiko | **LGPL-2.1-or-later** ⚠ (see below) |
| requests | Apache-2.0 |
| urllib3 | MIT |
| certifi | **MPL-2.0** ⚠ (see below) |
| charset-normalizer | MIT |
| idna | BSD-3-Clause |
| cryptography | Apache-2.0 OR BSD-3-Clause |
| bcrypt | Apache-2.0 |
| PyNaCl | Apache-2.0 |
| cffi | MIT |
| pycparser | BSD-3-Clause |
| pywinrm | MIT |
| requests-ntlm | ISC |
| xmltodict | MIT |
| rich | MIT |
| markdown-it-py | MIT |
| mdurl | MIT |
| Pygments | BSD-2-Clause |
| typer | MIT |
| click | BSD-3-Clause |
| shellingham | ISC |
| PyYAML | MIT |
| six | MIT |
| typing_extensions | PSF-2.0 (Python Software Foundation License) |

The Python standard library and interpreter bundled by PyInstaller are under the
**PSF License**. Tcl/Tk (used by the GUI) is under the **Tcl/Tk (BSD-style) License**.

## ⚠ paramiko — LGPL-2.1-or-later

paramiko (the SSH layer) is weak-copyleft. When you redistribute a binary that statically
bundles it, the LGPL requires that recipients can **replace/relink paramiko** with a modified
version. The simplest way we satisfy this:

- The **complete source** of `syncthing-manager` is public (MIT), so anyone can rebuild the
  binary against a different paramiko.
- paramiko's own source is available at <https://github.com/paramiko/paramiko> and on PyPI.

Keep this notice with any redistribution. If you ship a *closed* derivative, either keep
paramiko dynamically replaceable (PyInstaller onedir already keeps libraries as separate files
in the folder, which helps) or provide the object files needed to relink.

## ⚠ certifi — MPL-2.0

certifi bundles the Mozilla CA certificate store under the Mozilla Public License 2.0 (a
file-level copyleft). Obligation is light: **keep the MPL-2.0 notice** and, if you modify the
certifi files themselves, make those modified files available. We don't modify them.

## Full license texts

Each library ships its full license inside its PyPI distribution (the `*.dist-info/` directory
in a Python install) and in its upstream repository. To regenerate a complete, exact dump from
an installed environment:

```bash
pip install pip-licenses
pip-licenses --with-license-file --format=plain-vertical \
  --packages requests paramiko rich typer pyyaml cryptography pywinrm requests-ntlm \
  > THIRD_PARTY_LICENSE_TEXTS.txt
```

This summary is maintained by hand; the package's own metadata is authoritative.
