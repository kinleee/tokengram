"""Render icon.png (128x128) using PIL — mirrors icon-source.svg.

Cairo-based SVG renderers (cairosvg, svglib+rlPyCairo) need libcairo-2.dll which
is not installed on this Windows box, so we redraw the design directly.
"""
from __future__ import annotations
from PIL import Image, ImageDraw, ImageFilter

SIZE = 128
SCALE = 4  # render at SIZE*SCALE then downscale with LANCZOS for clean antialiasing


def lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def diagonal_gradient(w: int, h: int, c1: tuple[int, int, int], c2: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGB", (w, h), c1)
    px = img.load()
    # 0,0 -> 1,1 diagonal
    for y in range(h):
        for x in range(w):
            t = (x / (w - 1) + y / (h - 1)) / 2
            px[x, y] = lerp(c1, c2, t)
    return img


def rounded_mask(w: int, h: int, radius: int) -> Image.Image:
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
    return m


def build_icon(path: str) -> None:
    W = SIZE * SCALE
    bg = diagonal_gradient(W, W, (0x1e, 0x1e, 0x2e), (0x31, 0x31, 0x44))
    mask = rounded_mask(W, W, 24 * SCALE)
    big = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    big.paste(bg, (0, 0), mask)

    stroke = (0xaa, 0xad, 0xf8)
    fill_dot = stroke

    overlay = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    cx, cy = 64 * SCALE, 64 * SCALE

    def P(x: float, y: float) -> tuple[float, float]:
        return (cx + x * SCALE, cy + y * SCALE)

    blob = [
        P(-30, -10), P(-25, -22), P(-16, -32), P(-8, -42), P(6, -36),
        P(22, -42), P(30, -28), P(40, -18), P(32, -2),
        P(38, 12), P(28, 22), P(22, 36), P(6, 34),
        P(-8, 40), P(-18, 30), P(-32, 28), P(-32, 10),
        P(-38, 0), P(-30, -10),
    ]
    od.line(blob, fill=stroke, width=4 * SCALE, joint="curve")

    inner = [P(-16, -20), P(0, -14), P(0, 0), P(-10, 8), P(0, 16), P(14, 12)]
    od.line(inner, fill=stroke, width=4 * SCALE, joint="curve")

    for nx, ny in [(-16, -20), (0, -14), (0, 0), (-10, 8), (0, 16), (14, 12)]:
        x, y = P(nx, ny)
        r = 3 * SCALE
        od.ellipse((x - r, y - r, x + r, y + r), fill=fill_dot)

    big.alpha_composite(overlay)
    big.paste(Image.new("RGBA", (W, W), (0, 0, 0, 0)), (0, 0),
              Image.eval(mask, lambda v: 255 - v))

    final = big.resize((SIZE, SIZE), Image.LANCZOS)
    final.save(path, "PNG")
    print(f"wrote {path} ({SIZE}x{SIZE}, supersampled {SCALE}x)")


if __name__ == "__main__":
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    build_icon(os.path.join(here, "icon.png"))
