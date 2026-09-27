"""Generate the Anchor app icon as a multi-resolution Windows .ico file.

Requires Pillow (not in requirements.txt because the Anchor app itself does
not use it — this is a build-time tool only):

    pip install "Pillow>=10.0"

Run from the project root:

    python scripts/make_icon.py

Produces:
    assets/icon.ico          — multi-resolution (16,24,32,48,64,128,256)
    assets/icon-256.png      — preview PNG at full res
    assets/icon-light.png    — same icon on a light background (for README)
    assets/icon-dark.png     — same icon on a dark background  (for README)

Design:
    - Anchor silhouette in TechEase brand gold (#FAB541) with a subtle dark
      stroke so the shape stays crisp on either light or dark backgrounds.
    - Transparent background.
    - Drawn at 1024×1024 for crisp downsampling, then scaled with Lanczos.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

# --- Design constants ---------------------------------------------------------

# Brand colours, sampled from the TechEase banner.
GOLD       = (250, 181,  65, 255)   # main fill
GOLD_HI    = (255, 218, 130, 255)   # subtle inner highlight
DARK_EDGE  = ( 35,  30,  20, 220)   # contrast stroke

# Source canvas (downsampled into each icon size).
CANVAS = 1024


def _ring(draw: ImageDraw.ImageDraw, cx: float, cy: float,
          outer_r: float, inner_r: float, fill, stroke=None, stroke_w=0) -> None:
    """Draw an annulus (ring) at (cx, cy)."""
    draw.ellipse(
        [cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r],
        fill=fill, outline=stroke, width=stroke_w,
    )
    # Punch out the hole.
    draw.ellipse(
        [cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r],
        fill=(0, 0, 0, 0),
    )


def _stadium(draw: ImageDraw.ImageDraw, cx: float, cy: float,
             w: float, h: float, fill, stroke=None, stroke_w=0) -> None:
    """A rectangle with semicircular ends, centred at (cx, cy)."""
    draw.rounded_rectangle(
        [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2],
        radius=h / 2, fill=fill, outline=stroke, width=stroke_w,
    )


def _arc_arm(im: Image.Image, cx: float, cy: float, radius: float,
             thickness: float, start_deg: float, end_deg: float, fill) -> None:
    """Draw a thick arc by stroking an ellipse outline with the right width."""
    d = ImageDraw.Draw(im)
    d.arc(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        start=start_deg, end=end_deg,
        fill=fill, width=int(thickness),
    )


def _fluke_triangle(draw: ImageDraw.ImageDraw, tip: tuple[float, float],
                    base_mid: tuple[float, float], half_width: float,
                    fill) -> None:
    """Triangle from `base_mid` (perp to the tip vector) to `tip`."""
    tx, ty = tip
    bx, by = base_mid
    dx, dy = tx - bx, ty - by
    length = math.hypot(dx, dy) or 1.0
    # Perpendicular unit vector for the base width.
    px, py = -dy / length, dx / length
    b1 = (bx + px * half_width, by + py * half_width)
    b2 = (bx - px * half_width, by - py * half_width)
    draw.polygon([tip, b1, b2], fill=fill)


def render(size: int = CANVAS) -> Image.Image:
    """Render the anchor at the requested square `size`.

    Geometry (CANVAS coords; CANVAS=1024):
      - Eye (top ring): cy=160, outer R=105, inner R=58
      - Stock (crossbar): cy=345, half-width 280, height 64
      - Shaft: 70 wide, from y=255 (joining ring) down to y=735
        (joining the arms arc), centred on cx
      - Arms arc: centred at (cx, 380), R=355, thickness 76, swept
        from 20° to 160°. The bottom of the shaft meets the arc top.
      - Flukes: triangular wedges added at each arm tip, pointing up-out
    Then a thin dark outline is added on top of the whole silhouette.
    """
    im = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx = CANVAS / 2

    # ---- Eye (top ring) ------------------------------------------------
    ring_cy = 160
    ring_outer = 105
    ring_inner = 58
    _ring(d, cx, ring_cy, ring_outer, ring_inner, fill=GOLD)

    # ---- Shaft ---------------------------------------------------------
    shaft_top = ring_cy + ring_outer - 12   # tucks into the ring slightly
    shaft_bottom = 740                       # meets the arms arc
    shaft_half = 35
    d.rectangle(
        [cx - shaft_half, shaft_top, cx + shaft_half, shaft_bottom],
        fill=GOLD,
    )

    # ---- Stock (crossbar) ---------------------------------------------
    stock_cy = 345
    stock_w = 560
    stock_h = 70
    _stadium(d, cx, stock_cy, stock_w, stock_h, fill=GOLD)

    # ---- Arms arc + flukes --------------------------------------------
    # Arc geometry chosen so the arc TOP touches shaft_bottom and the
    # endpoints fall in the lower outer quadrants of the icon.
    arms_cx = cx
    arms_cy = 380
    arms_r = 355
    arm_thickness = 76
    _arc_arm(im, arms_cx, arms_cy, arms_r, arm_thickness,
             start_deg=20, end_deg=160, fill=GOLD)
    d = ImageDraw.Draw(im)   # PIL needs a fresh Draw after arc

    def _arc_endpoint(deg: float) -> tuple[float, float]:
        rad = math.radians(deg)
        return (arms_cx + arms_r * math.cos(rad),
                arms_cy + arms_r * math.sin(rad))

    # Triangular flukes pointing outward-and-upward from each arm tip,
    # tangent to the arc so they look attached.
    fluke_len = 165
    fluke_half = 88
    for deg, x_dir in ((160, -1), (20, 1)):
        base_x, base_y = _arc_endpoint(deg)
        # Outward unit vector at the tangent of the arc.
        tan_rad = math.radians(deg - 90)
        tx = math.cos(tan_rad) * x_dir
        ty = math.sin(tan_rad) * x_dir
        tip = (base_x + tx * fluke_len, base_y + ty * fluke_len)
        _fluke_triangle(d, tip=tip, base_mid=(base_x, base_y),
                        half_width=fluke_half, fill=GOLD)

    # ---- Highlights for a little dimension ----------------------------
    # Subtle bright streak along the inside-left of the shaft.
    d.rectangle(
        [cx - shaft_half + 6, shaft_top + 14,
         cx - shaft_half + 18, shaft_bottom - 14],
        fill=GOLD_HI,
    )
    # Highlight across the top of the stock.
    _stadium(d, cx, stock_cy - 18, stock_w - 80, 12, fill=GOLD_HI)

    # ---- Dark stroke pass (drawn last so it sits on top) ---------------
    stroke_w = 10
    # Outer edge of the ring
    d.ellipse(
        [cx - ring_outer, ring_cy - ring_outer,
         cx + ring_outer, ring_cy + ring_outer],
        outline=DARK_EDGE, width=stroke_w,
    )
    # Inner edge of the ring
    d.ellipse(
        [cx - ring_inner, ring_cy - ring_inner,
         cx + ring_inner, ring_cy + ring_inner],
        outline=DARK_EDGE, width=stroke_w,
    )
    # Stock outline
    d.rounded_rectangle(
        [cx - stock_w / 2, stock_cy - stock_h / 2,
         cx + stock_w / 2, stock_cy + stock_h / 2],
        radius=stock_h / 2, outline=DARK_EDGE, width=stroke_w,
    )
    # Shaft sides — only the bits not covered by the stock.
    d.line([cx - shaft_half, shaft_top + 5,
            cx - shaft_half, stock_cy - stock_h / 2],
           fill=DARK_EDGE, width=stroke_w)
    d.line([cx + shaft_half, shaft_top + 5,
            cx + shaft_half, stock_cy - stock_h / 2],
           fill=DARK_EDGE, width=stroke_w)
    d.line([cx - shaft_half, stock_cy + stock_h / 2,
            cx - shaft_half, shaft_bottom],
           fill=DARK_EDGE, width=stroke_w)
    d.line([cx + shaft_half, stock_cy + stock_h / 2,
            cx + shaft_half, shaft_bottom],
           fill=DARK_EDGE, width=stroke_w)
    # Arc outlines (outer + inner edges).
    _arc_arm(im, arms_cx, arms_cy,
             arms_r + arm_thickness / 2 - 5, stroke_w,
             start_deg=20, end_deg=160, fill=DARK_EDGE)
    _arc_arm(im, arms_cx, arms_cy,
             arms_r - arm_thickness / 2 + 5, stroke_w,
             start_deg=20, end_deg=160, fill=DARK_EDGE)

    if size != CANVAS:
        im = im.resize((size, size), Image.LANCZOS)
    return im


# --- Output -------------------------------------------------------------------

def main() -> int:
    out_dir = Path(__file__).resolve().parent.parent / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)

    master = render(CANVAS)
    # Multi-resolution .ico — Windows picks the right one per context.
    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48),
                 (64, 64), (128, 128), (256, 256)]
    icons = [master.resize(s, Image.LANCZOS) for s in ico_sizes]
    ico_path = out_dir / "icon.ico"
    icons[-1].save(
        ico_path, format="ICO",
        sizes=ico_sizes, append_images=icons[:-1],
    )

    # Standalone previews.
    master.resize((256, 256), Image.LANCZOS).save(out_dir / "icon-256.png")

    # Background swatches for the README/marketing.
    for bg_name, bg in (("dark", (24, 26, 32, 255)), ("light", (245, 245, 245, 255))):
        bg_im = Image.new("RGBA", (512, 512), bg)
        icon = master.resize((400, 400), Image.LANCZOS)
        bg_im.paste(icon, ((512 - 400) // 2, (512 - 400) // 2), icon)
        bg_im.save(out_dir / f"icon-{bg_name}.png")

    print(f"Wrote {ico_path}")
    print(f"Wrote {out_dir / 'icon-256.png'}")
    print(f"Wrote {out_dir / 'icon-light.png'}")
    print(f"Wrote {out_dir / 'icon-dark.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
