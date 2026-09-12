"""Generate synthetic invoice fixture images whose numbers match good_invoice.json.

Run with: python -m tests.fixtures.make_invoice_png

`invoice.png` is consumed by several tests (e.g. test_preprocess.py,
test_annotate.py). `invoice_distorted.png`'s stated purpose is to exercise a
retry path (see `make_distorted`'s docstring), but that retry path belongs
to the dormant invoice extract/validate cycle (see docs/ARCHITECTURE.md);
none of the currently-listed test files load invoice_distorted.png. Must
not: change the numbers in INVOICE_LINES without also updating
good_invoice.json -- the two are meant to describe the same invoice.

Next: tests/test_preprocess.py, the most direct consumer of these fixtures.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

FIXTURES_DIR = Path(__file__).parent

INVOICE_LINES = [
    "INVOICE",
    "Invoice #: INV-1001",
    "Vendor: Acme Supplies",
    "Date: 2026-09-01",
    "Currency: USD",
    "",
    "Description        Qty   Unit Price   Amount",
    "Widget A             3       10.00      30.00",
    "Widget B             2       25.00      50.00",
    "",
    "Subtotal:                            80.00",
    "Tax:                                   8.00",
    "Grand Total:                         88.00",
]


def make_invoice_image(width: int = 900, height: int = 620) -> Image.Image:
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=22)
    y = 30
    for line in INVOICE_LINES:
        draw.text((40, y), line, fill="black", font=font)
        y += 34
    return image


def make_distorted(image: Image.Image) -> Image.Image:
    """Dimmer and slightly rotated, same numbers -- exercises the retry path."""
    dim = ImageEnhance.Brightness(image).enhance(0.55)
    return dim.rotate(3, expand=True, fillcolor="white")


def main() -> None:
    image = make_invoice_image()
    image.save(FIXTURES_DIR / "invoice.png")

    distorted = make_distorted(image)
    distorted.save(FIXTURES_DIR / "invoice_distorted.png")


if __name__ == "__main__":
    main()
