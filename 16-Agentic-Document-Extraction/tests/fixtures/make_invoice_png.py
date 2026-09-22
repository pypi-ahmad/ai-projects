"""Generate the synthetic document image used by rendering tests.

Run with: python -m tests.fixtures.make_invoice_png

`invoice.png` is consumed by preprocessing and annotation tests.

Next: tests/test_preprocess.py, the most direct consumer of these fixtures.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

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


def main() -> None:
    image = make_invoice_image()
    image.save(FIXTURES_DIR / "invoice.png")


if __name__ == "__main__":
    main()
