#!/usr/bin/env python3
"""Render the RecoverX v0.4 icon (assets/recoverx.ico, .png, .svg) with Pillow.

Deterministic: re-running produces the same artwork. Run from the repository root.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
S = 1024  # supersampled canvas

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="256" height="256">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="#22d3ee"/><stop offset=".55" stop-color="#3b82f6"/><stop offset="1" stop-color="#8b5cf6"/></linearGradient>
<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#111b30"/><stop offset="1" stop-color="#070b14"/></linearGradient></defs>
<rect x="2" y="2" width="44" height="44" rx="12" fill="url(#bg)" stroke="url(#g)" stroke-width="2"/>
<path d="M15 33V15h9.5a5.5 5.5 0 0 1 0 11H15m9 0 7.5 7" fill="none" stroke="url(#g)" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"/>
<circle cx="34" cy="15" r="2.6" fill="#22d3ee"/></svg>
"""


def gradient(size: int) -> Image.Image:
    stops = [(0.0, (0x22, 0xD3, 0xEE)), (0.55, (0x3B, 0x82, 0xF6)), (1.0, (0x8B, 0x5C, 0xF6))]
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * (size - 1))
            for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
                if t0 <= t <= t1:
                    f = (t - t0) / (t1 - t0)
                    px[x, y] = tuple(int(a + (b - a) * f) for a, b in zip(c0, c1))
                    break
    return img


def render() -> Image.Image:
    u = S / 48
    grad = gradient(256).resize((S, S), Image.BICUBIC)
    base = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # background tile with vertical navy gradient
    bg = Image.new("RGBA", (S, S))
    d = ImageDraw.Draw(bg)
    for y in range(S):
        f = y / (S - 1)
        d.line([(0, y), (S, y)], fill=(int(0x11 + (0x07 - 0x11) * f), int(0x1B + (0x0B - 0x1B) * f), int(0x30 + (0x14 - 0x30) * f), 255))
    tile = Image.new("L", (S, S), 0)
    ImageDraw.Draw(tile).rounded_rectangle([2 * u, 2 * u, 46 * u, 46 * u], radius=12 * u, fill=255)
    base.paste(bg, (0, 0), tile)
    # gradient border + glyph via masks
    stroke = Image.new("L", (S, S), 0)
    sd = ImageDraw.Draw(stroke)
    sd.rounded_rectangle([2 * u, 2 * u, 46 * u, 46 * u], radius=12 * u, outline=255, width=int(2 * u))
    glyph = Image.new("L", (S, S), 0)
    gd = ImageDraw.Draw(glyph)
    w = int(3.6 * u)
    pts = [(15 * u, 33 * u), (15 * u, 15 * u), (24.5 * u, 15 * u)]
    gd.line(pts, fill=255, width=w, joint="curve")
    gd.arc([19 * u - w / 2, 15 * u - w / 2, 30 * u + w / 2, 26 * u + w / 2], start=270, end=90, fill=255, width=w)
    gd.line([(24.5 * u, 26 * u), (15 * u, 26 * u)], fill=255, width=w)
    gd.line([(24 * u, 26 * u), (31.5 * u, 33 * u)], fill=255, width=w)
    for x, y in [(15 * u, 33 * u), (15 * u, 15 * u), (31.5 * u, 33 * u)]:
        gd.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=255)
    gd.ellipse([31.4 * u, 12.4 * u, 36.6 * u, 17.6 * u], fill=255)
    glow = glyph.filter(ImageFilter.GaussianBlur(10 * u / 8))
    glow_layer = Image.new("RGBA", (S, S), (34, 211, 238, 0))
    glow_layer.putalpha(glow.point(lambda v: int(v * 0.45)))
    base = Image.alpha_composite(base, glow_layer)
    mask = Image.composite(Image.new("L", (S, S), 255), stroke, glyph)
    colored = grad.convert("RGBA")
    colored.putalpha(mask)
    return Image.alpha_composite(base, colored)


def main():
    ASSETS.mkdir(exist_ok=True)
    art = render()
    art.resize((512, 512), Image.LANCZOS).save(ASSETS / "recoverx.png")
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    art.resize((256, 256), Image.LANCZOS).save(ASSETS / "recoverx.ico", sizes=sizes)
    (ASSETS / "recoverx.svg").write_text(SVG, encoding="utf-8")
    print("Wrote", ", ".join(str(ASSETS / n) for n in ("recoverx.png", "recoverx.ico", "recoverx.svg")))


if __name__ == "__main__":
    main()
