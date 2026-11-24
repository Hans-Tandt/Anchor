"""Generate Anchor's app icon set with Pillow.

    python scripts/make_icon.py

Writes:
    anchor/resources/icons/anchor.ico      multi-resolution (16 … 256)
    anchor/resources/icons/anchor-256.png  window icon / README
    docs/images/logo.png                    512 px, for docs and GitHub
    docs/images/logo-tile-*.png             icon at a few sizes (docs preview)

Design: a Fluent-style squircle tile in a warm gold gradient (the TechEase
brand colour) with a bold, dark anchor. The flukes are arrowheads following
the arm's arc, so the anchor doubles as a "backup cycle" mark. From 48 px up a
optional green check badge says "verified" (off by default). Small sizes (16–32 px) are drawn
separately with thicker strokes and no badge so they stay crisp.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT_ICONS = ROOT / "anchor" / "resources" / "icons"
OUT_DOCS = ROOT / "docs" / "images"

GOLD_TOP = (247, 214, 140)
GOLD_BOTTOM = (190, 134, 42)
INK = (27, 28, 33)
CHECK = (108, 203, 95)

SS = 4  # supersampling factor


def _gradient(size: int, top, bottom) -> Image.Image:
    """Diagonal gradient, top-left → bottom-right."""
    g = Image.new("RGB", (size, size))
    px = g.load()
    for y in range(size):
        for x in range(size):
            t = (x * 0.35 + y * 0.65) / size
            px[x, y] = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
    return g


def _tile_mask(size: int, margin: float, radius: float) -> Image.Image:
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    a = int(size * margin)
    d.rounded_rectangle([a, a, size - a, size - a], radius=int(size * radius), fill=255)
    return m


def _arrowhead(d: ImageDraw.ImageDraw, tip, direction, length, width, fill) -> None:
    dx, dy = direction
    n = math.hypot(dx, dy)
    dx, dy = dx / n, dy / n
    bx, by = tip[0] - dx * length, tip[1] - dy * length
    px, py = -dy, dx
    d.polygon([tip, (bx + px * width / 2, by + py * width / 2), (bx - px * width / 2, by - py * width / 2)], fill=fill)


def _anchor(d: ImageDraw.ImageDraw, s: int, cx: float, cy: float, scale: float, stroke: float, fill) -> None:
    """Draw the anchor glyph. Geometry is in a 0..1 box scaled by `scale`."""
    def P(x, y):
        return (cx + (x - 0.5) * scale * s, cy + (y - 0.5) * scale * s)

    w = stroke * s
    # Ring
    rc = P(0.5, 0.13)
    r_out = 0.105 * scale * s
    d.ellipse([rc[0] - r_out, rc[1] - r_out, rc[0] + r_out, rc[1] + r_out], fill=fill)
    r_in = r_out - w * 0.78
    d.ellipse([rc[0] - r_in, rc[1] - r_in, rc[0] + r_in, rc[1] + r_in], fill=(0, 0, 0, 0))
    # Shank
    top = P(0.5, 0.13)[1] + r_out - w * 0.2
    bot = P(0.5, 0.92)[1]
    d.rounded_rectangle([cx - w / 2, top, cx + w / 2, bot], radius=w / 2, fill=fill)
    # Stock (cross bar)
    y = P(0.5, 0.33)[1]
    x0, x1 = P(0.25, 0)[0], P(0.75, 0)[0]
    d.rounded_rectangle([x0, y - w / 2, x1, y + w / 2], radius=w / 2, fill=fill)
    # Arms: arc of a circle, bottom half
    ac = P(0.5, 0.52)
    R = 0.40 * scale * s
    start, end = 22, 158  # PIL degrees, clockwise from east → bottom arc
    d.arc([ac[0] - R, ac[1] - R, ac[0] + R, ac[1] + R], start=start, end=end, fill=fill, width=int(w))
    # Flukes: arrowheads tangent to the arc, pointing "up and out"
    for ang, sign in ((start, -1), (end, 1)):
        a = math.radians(ang)
        # point on arc centreline
        rr = R - w / 2
        x = ac[0] + rr * math.cos(a)
        y = ac[1] + rr * math.sin(a)
        # tangent direction moving away from the bottom of the arc
        tx, ty = -math.sin(a) * sign, math.cos(a) * sign
        tip = (x + tx * w * 1.6, y + ty * w * 1.6)
        _arrowhead(d, tip, (tx, ty), length=w * 2.5, width=w * 2.7, fill=fill)


def render(size: int, badge: bool | None = None, bold: bool = False) -> Image.Image:
    s = size * SS
    if badge is None:
        badge = False  # badge variant kept for docs/experiments; off by default
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    margin, radius = (0.04, 0.22) if size <= 32 else (0.06, 0.225)
    mask = _tile_mask(s, margin, radius)

    # Soft drop shadow (large sizes only)
    if size >= 64:
        sh = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        sm = _tile_mask(s, margin, radius).filter(ImageFilter.GaussianBlur(s * 0.025))
        sh.putalpha(sm.point(lambda v: int(v * 0.45)))
        img.alpha_composite(sh, (0, int(s * 0.012)))

    tile = _gradient(s, GOLD_TOP, GOLD_BOTTOM).convert("RGBA")
    tile.putalpha(mask)
    img.alpha_composite(tile)

    # Soft top-left glow (subtle depth, no hard "gloss" edge)
    if size >= 48:
        hl = Image.new("L", (s, s), 0)
        hd = ImageDraw.Draw(hl)
        hd.ellipse([-s * 0.25, -s * 0.35, s * 0.85, s * 0.55], fill=55)
        hl = hl.filter(ImageFilter.GaussianBlur(s * 0.08))
        hl = Image.composite(hl, Image.new("L", (s, s), 0), mask)
        white = Image.new("RGBA", (s, s), (255, 255, 255, 0))
        white.putalpha(hl)
        img.alpha_composite(white)

    # Anchor glyph on its own layer so the ring hole stays transparent → tile
    glyph = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glyph)
    stroke = 0.088 if bold else 0.066
    scale = 0.74 if size > 32 else 0.80
    _anchor(gd, s, s * 0.5, s * 0.515, scale, stroke, INK + (255,))
    img.alpha_composite(glyph)

    if badge:
        bd = ImageDraw.Draw(img)
        r = s * 0.155
        c = (s * 0.79, s * 0.79)
        ring = s * 0.035
        bd.ellipse([c[0] - r - ring, c[1] - r - ring, c[0] + r + ring, c[1] + r + ring], fill=GOLD_BOTTOM + (255,))
        bd.ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], fill=INK + (255,))
        lw = int(s * 0.04)
        pts = [(c[0] - r * 0.50, c[1] + r * 0.02), (c[0] - r * 0.12, c[1] + r * 0.40), (c[0] + r * 0.52, c[1] - r * 0.36)]
        bd.line(pts, fill=CHECK + (255,), width=lw, joint="curve")
        for pt in (pts[0], pts[-1]):
            bd.ellipse([pt[0] - lw / 2, pt[1] - lw / 2, pt[0] + lw / 2, pt[1] + lw / 2], fill=CHECK + (255,))

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT_ICONS.mkdir(parents=True, exist_ok=True)
    OUT_DOCS.mkdir(parents=True, exist_ok=True)
    sizes = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]
    frames = [render(sz, bold=sz <= 32) for sz in sizes]
    frames[-1].save(OUT_ICONS / "anchor.ico", format="ICO", sizes=[(f.width, f.height) for f in frames],
                    append_images=frames[:-1])
    frames[-1].save(OUT_ICONS / "anchor-256.png")
    render(512).save(OUT_DOCS / "logo.png")
    # Preview strip for the docs
    strip_sizes = [16, 24, 32, 48, 64, 128]
    w = sum(strip_sizes) + 24 * (len(strip_sizes) + 1)
    for name, bg in (("dark", (32, 32, 32, 255)), ("light", (243, 243, 243, 255))):
        strip = Image.new("RGBA", (w, 128 + 48), bg)
        x = 24
        for sz in strip_sizes:
            im = render(sz, bold=sz <= 32)
            strip.alpha_composite(im, (x, (strip.height - sz) // 2))
            x += sz + 24
        strip.save(OUT_DOCS / f"icon-sizes-{name}.png")
    print("Icons written to", OUT_ICONS, "and", OUT_DOCS)


if __name__ == "__main__":
    main()
