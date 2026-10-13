"""Generates the PWA icons into pwa/web/icons. Re-run after changing the design:

    python pwa/tools/make_icons.py

Needs Pillow. The design: an asphalt square with a route, a start ring, a destination dot and a red "risky intersection" dot on the path.
Icons are drawn large and scaled down for smooth edges.
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "web" / "icons"
INK = (23, 25, 27, 255)  # asphalt
PAPER = (243, 240, 232, 255)
AMBER = (245, 179, 1, 255)  # signal amber
RED = (215, 25, 28, 255)
CANVAS = 1024


def glyph(scale: float) -> Image.Image:
    """The route drawing on a transparent square, scaled so its content fits `scale` of the width."""
    layer = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    # An S-shaped route from bottom-left to top-right, as a thick polyline with round joins.
    points = [(250, 760), (250, 620), (420, 560), (600, 500), (770, 440), (770, 300)]
    width = 62
    draw.line(points, fill=PAPER, width=width, joint="curve")
    for x, y in (points[0], points[-1]):
        draw.ellipse((x - width // 2, y - width // 2, x + width // 2, y + width // 2), fill=PAPER)
    # start ring and destination dot
    sx, sy = points[0]
    draw.ellipse((sx - 92, sy - 92, sx + 92, sy + 92), fill=PAPER)
    draw.ellipse((sx - 48, sy - 48, sx + 48, sy + 48), fill=AMBER)
    ex, ey = points[-1]
    draw.ellipse((ex - 100, ey - 100, ex + 100, ey + 100), fill=PAPER)
    # the risky intersection
    rx, ry = 600, 500
    draw.ellipse((rx - 84, ry - 84, rx + 84, ry + 84), fill=PAPER)
    draw.ellipse((rx - 62, ry - 62, rx + 62, ry + 62), fill=RED)
    # centre and scale the artwork
    box = layer.getbbox()
    art = layer.crop(box)
    target = int(CANVAS * scale)
    ratio = target / max(art.size)
    art = art.resize((max(1, int(art.width * ratio)), max(1, int(art.height * ratio))), Image.LANCZOS)
    out = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    out.paste(art, ((CANVAS - art.width) // 2, (CANVAS - art.height) // 2), art)
    return out


def background(rounded: bool) -> Image.Image:
    image = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if rounded:
        draw.rounded_rectangle((0, 0, CANVAS - 1, CANVAS - 1), radius=int(CANVAS * 0.22), fill=INK)
    else:
        draw.rectangle((0, 0, CANVAS, CANVAS), fill=INK)
    return image


def compose(rounded: bool, glyph_scale: float, size: int) -> Image.Image:
    image = background(rounded)
    image.alpha_composite(glyph(glyph_scale))
    return image.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # "any" icons: rounded square with transparent corners.
    compose(True, 0.62, 192).save(OUT / "icon-192.png")
    compose(True, 0.62, 512).save(OUT / "icon-512.png")
    # Maskable: full-bleed, artwork kept inside the central safe zone (Android crops to a circle/squircle).
    compose(False, 0.50, 512).save(OUT / "icon-maskable-512.png")
    # iOS: full-bleed with no transparency (iOS applies its own rounded mask).
    compose(False, 0.62, 180).convert("RGB").save(OUT / "apple-touch-icon.png")
    compose(True, 0.70, 32).save(OUT / "favicon-32.png")
    print("Icons written to", OUT)


if __name__ == "__main__":
    main()
