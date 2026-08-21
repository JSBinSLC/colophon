#!/usr/bin/env python3
"""Render calibre-plugin/images/icon.png (transparent, 256x256)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent / "icon.png"
SIZE = 256


def star(cx: float, cy: float, r_out: float, r_in: float, n: int = 4) -> list[tuple[float, float]]:
    from math import cos, pi, sin

    pts: list[tuple[float, float]] = []
    for i in range(n * 2):
        r = r_out if i % 2 == 0 else r_in
        a = -pi / 2 + i * pi / n
        pts.append((cx + r * cos(a), cy + r * sin(a)))
    return pts


def main() -> None:
    raw = Image.new("RGBA", (SIZE * 2, SIZE * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(raw)
    s = 2

    gold = (212, 160, 32, 255)
    gold_hi = (240, 208, 120, 255)
    ink = (32, 24, 16, 255)
    page_l = (255, 246, 228, 255)
    page_r = (236, 220, 186, 255)
    rule = (196, 176, 132, 200)

    d.polygon(star(128 * s, 48 * s, 26 * s, 9 * s, 4), fill=gold)
    d.ellipse((122 * s, 42 * s, 134 * s, 54 * s), fill=gold_hi)

    left = [(128 * s, 88 * s), (48 * s, 76 * s), (32 * s, 198 * s), (128 * s, 220 * s)]
    right = [(128 * s, 88 * s), (208 * s, 76 * s), (224 * s, 198 * s), (128 * s, 220 * s)]
    d.polygon(left, fill=page_l)
    d.polygon(right, fill=page_r)
    d.line([(128 * s, 88 * s), (128 * s, 220 * s)], fill=(90, 58, 18, 255), width=10)
    d.line(left + [left[0]], fill=ink, width=8)
    d.line(right + [right[0]], fill=ink, width=8)

    for y0, y1 in ((118, 126), (142, 148), (166, 170)):
        d.line([(58 * s, y0 * s), (114 * s, y1 * s)], fill=rule, width=5)
        d.line([(198 * s, y0 * s), (142 * s, y1 * s)], fill=rule, width=5)

    im = raw.resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    im.save(OUT, "PNG")
    print(f"wrote {OUT} {im.size} {im.mode}")


if __name__ == "__main__":
    main()
