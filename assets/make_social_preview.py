#!/usr/bin/env python3
"""Generate the project banner + social card → assets/.

Two outputs from one design (app icon on the indigo→cyan gradient + name + tagline; a thin black
border hugs the icon and, thinner, outlines the text):

  • assets/banner.png         — 1.91:1, ROUNDED corners (PNG alpha) → README header image.
  • assets/social-preview.png — 2:1 (1280×640 family), RECTANGULAR/opaque, content kept inside a
                                 ~40pt safe margin → GitHub Settings → Social preview (OG card).

Everything is drawn at R× and area-downscaled (Image.BOX) to F× → crisp, anti-aliased icon
border / text / corners. NATIVE high-res render (supersampling), not an AI upscale.
Run: python assets/make_social_preview.py
"""
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = HERE

R = 6              # render supersample (draw at design×R) …
F = 2              # … then BOX-downscale to output design×F (R/F× SSAA, high-DPI sharp)
TOP = (63, 55, 201)        # #3F37C9 — matches the icon gradient
BOT = (76, 201, 240)       # #4CC9F0
TITLE = "syncthing-manager"
TAGLINE = "Rename & manage a Syncthing folder\nacross your whole cluster — GUI + CLI"

_FONTS = "/usr/share/fonts/truetype/dejavu"


def _font(size, bold=True):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(os.path.join(_FONTS, name), size)
    except OSError:
        return ImageFont.load_default()


def _compose(dw: int, dh: int) -> Image.Image:
    """Render the card for a `dw`×`dh` design space at R×, BOX-downscaled to F× → crisp RGB.
    Content (icon + title + tagline) is centred horizontally and vertically grouped so it sits
    well within a safe margin for any 1.91:1–2:1 frame."""
    rw, rh = dw * R, dh * R

    # Vertical indigo→cyan gradient (row by row; no numpy).
    img = Image.new("RGB", (rw, rh))
    d = ImageDraw.Draw(img)
    for y in range(rh):
        t = y / (rh - 1)
        d.line([(0, y), (rw, y)],
               fill=tuple(int(TOP[i] + (BOT[i] - TOP[i]) * t) for i in range(3)))

    # Icon centred in the upper area (icon.png is 2048², downscaled here → crisp).
    sz = int(dh * 0.476) * R                 # ≈ 300 px on the 630-tall design
    ix = (rw - sz) // 2
    iy = int(dh * 0.102) * R                  # ≈ 64 px on the 630-tall design (top safe margin)
    icon = Image.open(os.path.join(HERE, "icon.png")).convert("RGBA").resize((sz, sz), Image.LANCZOS)
    img.paste(icon, (ix, iy), icon)

    d = ImageDraw.Draw(img)
    # Thin black border hugging the icon's rounded-square edge (radius = make_icon's 0.22·size).
    d.rounded_rectangle((ix, iy, ix + sz - 1, iy + sz - 1), radius=int(sz * 0.22),
                        outline=(0, 0, 0), width=2 * R)

    # Title + tagline CENTRED in the lower band. Auto-shrink the title to the safe width.
    margin = int(dw * 0.0667) * R             # ≈ 80 px side safe margin on the 1200-wide design
    avail = rw - 2 * margin
    ts = int(dh * 0.124) * R                  # ≈ 78 px title size
    title_f = _font(ts, bold=True)
    while ts > 32 * R and d.textlength(TITLE, font=title_f) > avail:
        ts -= 2 * R
        title_f = _font(ts, bold=True)
    tag_f = _font(int(dh * 0.0476) * R, bold=False)   # ≈ 30 px

    title_h = d.textbbox((0, 0), TITLE, font=title_f)[3]
    gap = int(dh * 0.0254) * R                # ≈ 16 px
    y0 = int(dh * 0.641) * R                  # ≈ 404 px on the 630-tall design (lower band)
    tw = d.textlength(TITLE, font=title_f)
    # A thin black outline so the letters read crisply on the gradient (thinner than the icon's).
    d.text(((rw - tw) // 2, y0), TITLE, font=title_f, fill=(255, 255, 255),
           stroke_width=1 * R, stroke_fill=(0, 0, 0))
    d.multiline_text((rw // 2, y0 + title_h + gap), TAGLINE, font=tag_f,
                     fill=(240, 245, 255), spacing=8 * R, align="center", anchor="ma",
                     stroke_width=max(1, R // 2), stroke_fill=(0, 0, 0))

    # BOX (area-average) downscale → ring-free SSAA: crisp icon border / text / gradient, no halo.
    return img.resize((dw * F, dh * F), Image.BOX)


def main() -> None:
    # README banner — 1.91:1, rounded corners (transparent PNG alpha).
    bw, bh = 1200, 630
    rgb = _compose(bw, bh)
    radius = 40 * F
    mask = Image.new("L", (bw * R, bh * R), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, bw * R - 1, bh * R - 1), radius=40 * R, fill=255)
    banner = rgb.convert("RGBA")
    banner.putalpha(mask.resize((bw * F, bh * F), Image.BOX))
    bpath = os.path.join(OUT_DIR, "banner.png")
    banner.save(bpath)
    print(f"wrote {bpath}  ({bw * F}x{bh * F})  [rounded — README banner]")

    # GitHub social preview / OG card — 2:1 (1280×640 family), rectangular, opaque, content well
    # inside a ~40pt safe margin so nothing is cropped on any platform.
    og = _compose(1280, 640).convert("RGB")
    opath = os.path.join(OUT_DIR, "social-preview.png")
    og.save(opath)
    print(f"wrote {opath}  ({1280 * F}x{640 * F})  [rectangular 2:1 — GitHub social preview]")


if __name__ == "__main__":
    main()
