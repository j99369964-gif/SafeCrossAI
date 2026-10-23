"""Makes the QR codes that open SafeCross AI on a phone, where it can be installed as an app.

    python pwa/tools/make_qr.py [https://crossing-ai.app/]

Writes to pwa/qr/:
  safecross-qr.svg        the bare code (scales to any size, for posters and slides)
  safecross-qr.png        the bare code, 1200 px
  safecross-qr-card.png   a print-ready card: code, name, and how to install on iPhone and Android
Needs: pip install qrcode pillow
"""

import sys
from pathlib import Path

import qrcode
import qrcode.image.svg
from PIL import Image, ImageDraw, ImageFont

URL = sys.argv[1] if len(sys.argv) > 1 else "https://crossing-ai.app/"
OUT = Path(__file__).resolve().parent.parent / "qr"
INK, PAPER, AMBER = (23, 25, 27), (243, 240, 232), (245, 179, 1)
FONT_DIRS = [Path("/usr/share/fonts/truetype/dejavu"), Path("C:/Windows/Fonts"), Path("/Library/Fonts"), Path("/System/Library/Fonts/Supplemental")]


def font(names: list[str], size: int):
    for directory in FONT_DIRS:
        for name in names:
            if (directory / name).exists():
                return ImageFont.truetype(str(directory / name), size)
    return ImageFont.load_default(size)


def code(box: int) -> Image.Image:
    # High error correction so the code still scans when printed small, smudged or with the logo over its centre.
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=box, border=4)
    qr.add_data(URL)
    qr.make(fit=True)
    return qr.make_image(fill_color=INK, back_color="white").convert("RGB")


def with_logo(image: Image.Image) -> Image.Image:
    """The app's crosswalk mark in the middle (about 18% of the width, well inside what level-H correction tolerates)."""
    size = image.width * 18 // 100
    mark = Image.new("RGB", (size, size), "white")
    draw = ImageDraw.Draw(mark)
    pad = size // 10
    draw.rounded_rectangle([pad, pad, size - pad, size - pad], radius=size // 5, fill=INK)
    inner = size - 2 * pad
    stripe_w, gap = inner // 9, inner // 12
    x = pad + inner // 5
    for _ in range(3):
        draw.rounded_rectangle([x, pad + inner // 4, x + stripe_w, size - pad - inner // 4], radius=stripe_w // 3, fill=PAPER)
        x += stripe_w + gap
    r = inner // 10
    cx, cy = size - pad - inner // 5, pad + inner // 4
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=AMBER)
    image.paste(mark, ((image.width - size) // 2, (image.height - size) // 2))
    return image


def card(qr_image: Image.Image) -> Image.Image:
    width, height = 1240, 1754  # A6-ish portrait at print resolution; prints fine on letter or A4 too
    page = Image.new("RGB", (width, height), PAPER)
    draw = ImageDraw.Draw(page)
    bold = lambda s: font(["DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf"], s)
    regular = lambda s: font(["DejaVuSans.ttf", "arial.ttf", "Arial.ttf"], s)

    draw.rectangle([0, 0, width, 22], fill=AMBER)
    draw.text((width // 2, 120), "SafeCross AI", font=bold(92), fill=INK, anchor="mm")
    draw.text((width // 2, 215), "Safer routes in New York City and Westchester", font=regular(40), fill=INK, anchor="mm")

    size = 860
    framed = qr_image.resize((size, size), Image.NEAREST)
    left, top = (width - size) // 2, 290
    draw.rounded_rectangle([left - 24, top - 24, left + size + 24, top + size + 24], radius=40, fill="white", outline=INK, width=6)
    page.paste(framed, (left, top))

    y = top + size + 90
    draw.text((width // 2, y), "Scan with your phone's camera", font=bold(52), fill=INK, anchor="mm")
    y += 110
    for title, text in (("iPhone:", "in Safari, tap Share, then Add to Home Screen"),
                        ("Android:", "in Chrome, tap Install (or menu, Install app)")):
        draw.text((100, y), title, font=bold(36), fill=INK, anchor="lm")
        draw.text((300, y), text, font=regular(34), fill=INK, anchor="lm")
        y += 70
    draw.text((width // 2, height - 90), URL.replace("https://", "").rstrip("/"), font=bold(44), fill=INK, anchor="mm")
    return page


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    qrcode.make(URL, image_factory=qrcode.image.svg.SvgPathImage, error_correction=qrcode.constants.ERROR_CORRECT_H).save(OUT / "safecross-qr.svg")
    plain = code(box=30)
    plain.resize((1200, 1200), Image.NEAREST).save(OUT / "safecross-qr.png")
    card(with_logo(code(box=30))).save(OUT / "safecross-qr-card.png", dpi=(300, 300))
    print(f"QR codes for {URL} written to {OUT}")


if __name__ == "__main__":
    main()
