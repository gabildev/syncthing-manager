#!/usr/bin/env python3
"""Compose the README screenshots from the raw window captures in assets/captures/ (git-ignored).

For each popup dialog we paste it centred over the window it's launched from, on a dimmed
backdrop with a soft drop shadow — so the gallery shows visually WHERE each dialog comes from.
Standalone pages are copied as-is. Output → assets/screenshots/ (committed, referenced by the
READMEs). Run: python assets/make_screenshots.py
"""
import os

from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "captures")
OUT = os.path.join(HERE, "screenshots")
os.makedirs(OUT, exist_ok=True)


def _open(name):
    return Image.open(os.path.join(SRC, name)).convert("RGBA")


def compose(bg_name, popup_name, out_name, dim=0.5):
    """Popup centred over the FULL dimmed parent window, with a soft drop shadow — NO cropping,
    so the dialog is shown over its real, complete context (the whole window it launches from).
    Native resolution throughout (no upscaling)."""
    bg = _open(bg_name)
    pop = _open(popup_name)
    # Dim the whole parent window so the centred dialog stands out.
    base = Image.blend(bg, Image.new("RGBA", bg.size, (10, 12, 20, 255)), dim)
    # A dialog should be smaller than its parent window; if a capture isn't (wrong window grabbed),
    # scale it DOWN to fit with a margin instead of silently cropping it off the edges.
    fit = min(1.0, (base.width * 0.92) / pop.width, (base.height * 0.92) / pop.height)
    if fit < 1.0:
        pop = pop.resize((max(1, int(pop.width * fit)), max(1, int(pop.height * fit))), Image.LANCZOS)
    x = max(0, (base.width - pop.width) // 2)
    y = max(0, (base.height - pop.height) // 2)
    # Soft drop shadow behind the dialog, on a full-size layer so paste() clips cleanly even if
    # the shadow would extend past the window edges (no out-of-bounds errors).
    pad = 50
    shadow = Image.new("RGBA", (pop.width + pad * 2, pop.height + pad * 2), (0, 0, 0, 0))
    block = Image.new("RGBA", (pop.width + 16, pop.height + 16), (0, 0, 0, 150))
    shadow.paste(block, (pad - 8, pad - 8 + 10))
    shadow = shadow.filter(ImageFilter.GaussianBlur(16))
    sh_layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sh_layer.paste(shadow, (x - pad, y - pad), shadow)
    base = Image.alpha_composite(base, sh_layer)
    base.alpha_composite(pop, (x, y))
    base.convert("RGB").save(os.path.join(OUT, out_name))
    print(f"  composed {out_name}")


def copy_page(src_name, out_name):
    _open(src_name).convert("RGB").save(os.path.join(OUT, out_name))
    print(f"  copied   {out_name}")


def main():
    # The full ("big") windows go in AS CAPTURED — unmodified.
    copy_page("Connection.png", "connection.png")
    copy_page("Folder.png",     "folder.png")
    copy_page("Devices.png",    "devices.png")
    copy_page("Names.png",      "names.png")
    copy_page("Topology.png",   "topology.png")
    copy_page("Run.png",        "execute.png")
    copy_page("Settings.png",   "settings.png")
    # Only the DIALOGS get the modal treatment — centred over the page that launches them.
    compose("Folder.png",   "New-folder.png",                  "new-folder.png")
    compose("Devices.png",  "Edit-credentials-device.png",     "edit-credentials.png")
    compose("Devices.png",  "Sync-names.png",                  "sync-names.png")
    compose("Devices.png",  "Devices-with-remote-access.png",  "offline-agents.png")
    compose("Topology.png", "Add-device.png",                  "add-device.png")


if __name__ == "__main__":
    main()
