"""Make a transparent version of the TechEase banner for the sidebar.

    python scripts/make_brand.py

The source banner is gold artwork on a solid black background, which looks
like a black box on Anchor's grey sidebar (and worse on the light theme).
This keys the black out: alpha comes from the pixel's brightness and the
colour is un-premultiplied, so anti-aliased gold edges stay smooth instead of
getting a dark fringe. The result is trimmed to its content.

Writes anchor/resources/brand/techease-banner-transparent.png
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "brand" / "techease-banner.png"
DST = ROOT / "anchor" / "resources" / "brand" / "techease-banner-transparent.png"

BLACK_POINT = 18     # anything darker than this is pure background
WHITE_POINT = 150    # brightness at which the gold is fully opaque


def main() -> None:
    im = Image.open(SRC).convert("RGB")
    out = Image.new("RGBA", im.size)
    src = im.load()
    dst = out.load()
    span = WHITE_POINT - BLACK_POINT
    for y in range(im.height):
        for x in range(im.width):
            r, g, b = src[x, y]
            v = max(r, g, b)
            a = 0.0 if v <= BLACK_POINT else min(1.0, (v - BLACK_POINT) / span)
            if a <= 0:
                dst[x, y] = (0, 0, 0, 0)
                continue
            # Un-premultiply against black so edges keep their gold hue.
            k = 1.0 / max(a, 1e-3)
            dst[x, y] = (min(255, int(r * k)), min(255, int(g * k)), min(255, int(b * k)), int(a * 255))
    bbox = out.getbbox()
    if bbox:
        pad = 6
        out = out.crop((max(0, bbox[0] - pad), max(0, bbox[1] - pad),
                        min(out.width, bbox[2] + pad), min(out.height, bbox[3] + pad)))
    out.save(DST)
    print("wrote", DST.relative_to(ROOT), out.size)


if __name__ == "__main__":
    main()
