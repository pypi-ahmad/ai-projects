"""Loads a source document (raster image or PDF) and turns it into the
model-ready payload every downstream step consumes: a capped-size PNG,
base64-encoded, plus its `doc_sha256`. `preprocess` handles page 1 only (used
by the dormant invoice path); `preprocess_pages` is what the active graph
calls for a page range.

Must not emit anything other than "image/png" or silently truncate a range.
Invalid page ranges are rejected before model calls.

Next: src/parse.py, the active caller of `preprocess_pages`.
"""

from __future__ import annotations

import base64
import hashlib
import io
from pathlib import Path

from PIL import Image, ImageOps

# Matches the resolution used for the live evaluation corpus (see "the same
# 1600-pixel page rendering" in docs/PROMPT-EVALUATION.md and docs/PROMPTS.md)
# -- changing this would make those recorded evaluation results non-reproducible
# without a new evaluation run.
MAX_LONG_EDGE = 1600
PDF_DPI = 200

_RASTER_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}


class PreprocessError(Exception):
    pass


def count_pages(path: str | Path) -> int:
    """Total page count -- 1 for a raster image, the real page count for a PDF.

    Only opens the document to read its page count; doesn't rasterize
    anything, so this is cheap enough to call right after upload to seed the
    page-range UI before the user picks a subset.
    """
    p = Path(path)
    if not p.is_file():
        raise PreprocessError(f"file not found: {p}")

    suffix = p.suffix.lower()
    if suffix in _RASTER_EXTS:
        with Image.open(p) as image:
            image.verify()
        return 1
    if suffix != ".pdf":
        raise PreprocessError(f"unsupported file type: {suffix}")

    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(p))
    try:
        return len(pdf)
    finally:
        pdf.close()


def preprocess(path: str | Path, *, enhance_contrast: bool = False) -> dict:
    """Load an invoice file and return a model-ready payload.

    Always emits a PNG-encoded image (re-encoding is unavoidable once the
    long edge is capped, and PDF pages are rasterized) so downstream code
    has exactly one mime type to deal with.
    """
    p = Path(path)
    if not p.is_file():
        raise PreprocessError(f"file not found: {p}")

    suffix = p.suffix.lower()
    raw_bytes = p.read_bytes()

    if suffix == ".pdf":
        _, images = _render_pdf_page_range(p, start_page=1, end_page=1)
        if not images:
            raise PreprocessError(f"PDF has no pages: {p}")
        image = images[0]
    elif suffix in _RASTER_EXTS:
        image = Image.open(io.BytesIO(raw_bytes))
        image.load()
    else:
        raise PreprocessError(f"unsupported file type: {suffix}")

    image = image.convert("RGB")
    image = _cap_long_edge(image, MAX_LONG_EDGE)
    if enhance_contrast:
        image = ImageOps.autocontrast(image)

    buf = io.BytesIO()
    image.save(buf, format="PNG")

    return {
        "doc_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "mime": "image/png",
        "base64": base64.b64encode(buf.getvalue()).decode("ascii"),
        "width": image.width,
        "height": image.height,
        "pages": 1,
    }


def preprocess_pages(
    path: str | Path,
    *,
    start_page: int = 1,
    end_page: int | None = None,
    enhance_contrast: bool = False,
    max_long_edge: int = MAX_LONG_EDGE,
    pdf_dpi: int = PDF_DPI,
) -> list[dict]:
    """Like `preprocess`, but one payload per page (a raster image is just page 1).

    `start_page`/`end_page` are 1-based and inclusive; `end_page=None` means
    "through the last page" -- there is no artificial page cap, so a large
    range is the caller's own choice. A raster image has exactly one page;
    any other range is rejected. Each returned dict adds a
    "page" key -- the page's true 1-based number in the source document --
    alongside the same doc_sha256/mime/base64/width/height shape
    `preprocess` returns.
    """
    p = Path(path)
    if not p.is_file():
        raise PreprocessError(f"file not found: {p}")

    suffix = p.suffix.lower()
    raw_bytes = p.read_bytes()
    doc_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if max_long_edge < 1 or pdf_dpi < 1:
        raise PreprocessError("Rendering dimensions must be positive")
    if start_page < 1 or (end_page is not None and end_page < start_page):
        raise PreprocessError("Invalid page range")

    if suffix == ".pdf":
        page_numbers, images = _render_pdf_page_range(p, start_page=start_page, end_page=end_page, dpi=pdf_dpi)
    elif suffix in _RASTER_EXTS:
        if start_page != 1 or end_page not in (None, 1):
            raise PreprocessError("Raster images have only one page")
        image = Image.open(io.BytesIO(raw_bytes))
        image.load()
        page_numbers, images = [1], [image]
    else:
        raise PreprocessError(f"unsupported file type: {suffix}")

    pages = []
    for page_number, image in zip(page_numbers, images):
        image = image.convert("RGB")
        image = _cap_long_edge(image, max_long_edge)
        if enhance_contrast:
            image = ImageOps.autocontrast(image)
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        pages.append(
            {
                "page": page_number,
                "doc_sha256": doc_sha256,
                "mime": "image/png",
                "base64": base64.b64encode(buf.getvalue()).decode("ascii"),
                "width": image.width,
                "height": image.height,
            }
        )
    return pages


def _cap_long_edge(image: Image.Image, max_long_edge: int) -> Image.Image:
    long_edge = max(image.width, image.height)
    if long_edge <= max_long_edge:
        return image
    scale = max_long_edge / long_edge
    new_size = (round(image.width * scale), round(image.height * scale))
    return image.resize(new_size, Image.LANCZOS)


def _render_pdf_page_range(
    p: Path, *, start_page: int, end_page: int | None, dpi: int = PDF_DPI
) -> tuple[list[int], list[Image.Image]]:
    """Render pages `start_page..end_page` (1-based, inclusive) of a PDF.

    `end_page=None` means through the last page. No cap is applied here --
    that's the caller's choice, since removing the fixed page limit was a
    deliberate decision (see docs/ARCHITECTURE.md).
    """
    import pypdfium2 as pdfium  # native-Windows wheel, no Poppler/Docker

    pdf = pdfium.PdfDocument(str(p))
    try:
        total = len(pdf)
        start = start_page
        end = end_page if end_page is not None else total
        if not 1 <= start <= end <= total:
            raise PreprocessError(f"Page range must be within 1..{total}")
        page_numbers = list(range(start, end + 1))
        # PDF points are 1/72 inch; the selected DPI is capped downstream.
        images = []
        for n in page_numbers:
            page = pdf[n - 1]
            try:
                bitmap = page.render(scale=dpi / 72)
                try:
                    images.append(bitmap.to_pil().copy())
                finally:
                    bitmap.close()
            finally:
                page.close()
        return page_numbers, images
    finally:
        pdf.close()
