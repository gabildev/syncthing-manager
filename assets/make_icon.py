#!/usr/bin/env python3
"""Generate the app icon (ORIGINAL artwork — NOT derived from the Syncthing logo, which is a
trademark). Motif: a small device CLUSTER (a hub + three evenly-spaced satellites joined by
plain links) with a sync symbol on the hub — the app manages a Syncthing cluster's topology.

Rendered at 2× and downscaled with LANCZOS for smooth, antialiased edges.
Run: python3 assets/make_icon.py

Outputs:
  assets/icon.png   — 1024×1024 master (window icon / docs / .desktop)
  build/icon.ico    — multi-size Windows icon (16…256) wired into the Windows specs
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = 2048                  # PNG master resolution (window icon / banner source / docs)
SS = 2                      # supersampling factor → render at OUT*SS, downscale to OUT
S = OUT * SS
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# Palette — deliberately distinct from Syncthing's: indigo (top) → cyan (bottom).
TOP = (63, 55, 201)        # #3F37C9
BOT = (76, 201, 240)       # #4CC9F0
NODE = (255, 255, 255)
LINK = (255, 255, 255)
GLYPH = TOP                # sync symbol colour (reads on the white hub, ties to the gradient)


def _rounded_mask(size: int, radius: int) -> Image.Image:
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return m


def _gradient(size: int) -> Image.Image:
    """Vertical indigo→cyan gradient (one horizontal line per row — fast, no numpy)."""
    base = Image.new("RGB", (size, size))
    d = ImageDraw.Draw(base)
    for y in range(size):
        t = y / (size - 1)
        d.line([(0, y), (size, y)], fill=(
            int(TOP[0] + (BOT[0] - TOP[0]) * t),
            int(TOP[1] + (BOT[1] - TOP[1]) * t),
            int(TOP[2] + (BOT[2] - TOP[2]) * t)))
    return base


def _sync_glyph(d: ImageDraw.ImageDraw, cx, cy, r, width, color):
    """The universal 'sync' symbol: two opposing circular arrows centred at (cx, cy)."""
    box = (cx - r, cy - r, cx + r, cy + r)
    d.arc(box, start=18, end=165, fill=color, width=width)
    d.arc(box, start=198, end=345, fill=color, width=width)
    head = r * 0.70
    for end_deg in (165, 345):
        th = math.radians(end_deg)
        tip = (cx + r * math.cos(th), cy + r * math.sin(th))
        tang = th + math.pi / 2                     # tangent (CCW travel) at the arc tip
        d.polygon([
            (tip[0] + head * math.cos(tang), tip[1] + head * math.sin(tang)),
            (tip[0] + head * math.cos(tang + math.pi - math.radians(45)),
             tip[1] + head * math.sin(tang + math.pi - math.radians(45))),
            (tip[0] + head * math.cos(tang + math.pi + math.radians(45)),
             tip[1] + head * math.sin(tang + math.pi + math.radians(45))),
        ], fill=color)


def build(size: int, simple: bool = False) -> Image.Image:
    """Render the icon at `size` px. `simple` (used for SMALL icon sizes, 16–48 px) uses bolder
    strokes/nodes and drops the fine sync glyph — at taskbar sizes the detailed version turns to
    mush, so the bold variant stays crisp and legible."""
    img = _gradient(size)
    img.putalpha(_rounded_mask(size, int(size * 0.22)))
    d = ImageDraw.Draw(img)

    cx, cy = size / 2.0, size / 2.0
    R = size * 0.33            # spoke radius — well separated nodes, long links
    # Bolder geometry for the small/simple variant so it doesn't turn to mush when downscaled.
    hub_r = int(size * (0.140 if simple else 0.105))   # hub node radius
    sat_r = int(size * (0.082 if simple else 0.058))   # satellite node radius
    lw    = int(size * (0.032 if simple else 0.017))   # link width

    # Three satellites EVENLY spaced (120° apart) → a symmetric Y: one up, two mirrored below.
    angles = (math.radians(-90), math.radians(30), math.radians(150))
    sats = [(cx + R * math.cos(a), cy + R * math.sin(a)) for a in angles]

    # Vertical placement: with one node up and two down, the bounding box centre and the visual
    # mass centre (the hub) disagree. Pure bbox-centring puts the hub too low ("pegado abajo");
    # hub-centring puts it too high. Split the difference → optically balanced. (X is already
    # symmetric: one node on the axis, two mirrored, so dx≈0.)
    BALANCE = 0.5
    xs = ([cx - hub_r, cx + hub_r] + [p[0] - sat_r for p in sats] + [p[0] + sat_r for p in sats])
    ys = ([cy - hub_r, cy + hub_r] + [p[1] - sat_r for p in sats] + [p[1] + sat_r for p in sats])
    dx = size / 2.0 - (min(xs) + max(xs)) / 2.0
    dy = (size / 2.0 - (min(ys) + max(ys)) / 2.0) * BALANCE
    cx, cy = cx + dx, cy + dy
    sats = [(p[0] + dx, p[1] + dy) for p in sats]

    # Plain links (no direction). Endpoints sit at the disc edges; discs are drawn afterwards.
    for sx, sy in sats:
        ang = math.atan2(sy - cy, sx - cx)
        a = (cx + hub_r * math.cos(ang), cy + hub_r * math.sin(ang))
        b = (sx - sat_r * math.cos(ang), sy - sat_r * math.sin(ang))
        d.line([a, b], fill=LINK, width=lw)

    def disc(x, y, r, fill):
        d.ellipse((x - r, y - r, x + r, y + r), fill=fill)

    for sx, sy in sats:
        disc(sx, sy, sat_r, NODE)
    disc(cx, cy, hub_r, NODE)
    if simple:
        # Small sizes: a bold solid dot (gradient-coloured) in the hub → a clean "donut" that
        # reads at 16 px, where the fine circular-arrow glyph would just be a smudge.
        _r2 = int(hub_r * 0.46)
        d.ellipse((cx - _r2, cy - _r2, cx + _r2, cy + _r2), fill=GLYPH)
    else:
        # Large sizes: the detailed sync symbol.
        _sync_glyph(d, cx, cy, int(hub_r * 0.42), max(3, int(size * 0.015)), GLYPH)
    return img


def _render(px: int, simple: bool) -> Image.Image:
    """Render one icon size: supersample 8× then LANCZOS-downscale for crisp edges at `px`
    (8× — vs 4× — gives noticeably cleaner small sizes in the Windows taskbar)."""
    return build(px * 8, simple=simple).resize((px, px), Image.LANCZOS)


def main():
    HERE.mkdir(parents=True, exist_ok=True)
    (ROOT / "build").mkdir(parents=True, exist_ok=True)
    png = HERE / "icon.png"
    ico = ROOT / "build" / "icon.ico"
    # PNG master: full detailed design at 1024 (window icon / docs).
    build(OUT * SS).resize((OUT, OUT), Image.LANCZOS).save(png)
    # ICO: the BOLD simple variant for small sizes (crisp in the taskbar), the full design for
    # large ones. Each size is rendered + downscaled independently for maximum sharpness.
    # Include the per-DPI taskbar targets (Win shows ~24/30/36/48 px at 100/125/150/200%), so
    # Windows always has a near-exact size to use instead of rescaling a distant one.
    sizes = [256, 128, 64, 48, 40, 32, 24, 16]
    imgs = [_render(px, simple=(px <= 48)) for px in sizes]
    imgs[0].save(ico, format="ICO", append_images=imgs[1:])
    print(f"wrote {png} and {ico}")


if __name__ == "__main__":
    main()
