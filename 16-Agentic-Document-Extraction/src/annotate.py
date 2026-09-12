"""Draws every parsed block's bbox onto a rasterized copy of each page and
saves the result as a multi-page annotated PDF (plus per-page PNGs and a
sidecar .meta.json) under data/annotated/ -- a human-readable check of what
the layout parser found, not a data source anything else reads back.

Must not: read from or write to data/committed/ or data/review/ (those
belong to the dormant invoice path, see docs/ARCHITECTURE.md), and must not
guess a box for a block with a missing/out-of-range bbox -- skip and count
it instead (see `_bbox_is_valid`).

Next: src/markdown.py, which renders the same ParseResult as text instead of
boxes.
"""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from src.preprocess import preprocess_pages
from src.schema import ParseResult

BOX_COLOR = (220, 30, 30)
LABEL_FONT_SIZE = 16


def _bbox_is_valid(xyxy: tuple[float, float, float, float]) -> bool:
    # Coordinates are normalized 0-1 (see BBox.xyxy in src/schema.py);
    # reject anything outside that range or degenerate (zero/negative width
    # or height) instead of drawing a nonsensical box.
    x0, y0, x1, y1 = xyxy
    if not all(0.0 <= v <= 1.0 for v in xyxy):
        return False
    return x1 > x0 and y1 > y0


def annotate_document(
    source_path: str | Path,
    parse_result: ParseResult,
    *,
    field_labels: dict[str, str] | None = None,
) -> tuple[Path, Path]:
    """Draw every block's bbox onto a rasterized copy of each page and save a
    multi-page PDF, plus a sidecar .meta.json.

    No PDF library needed: every page is already rasterized for the rest of
    this pipeline (via `preprocess_pages`), and Pillow itself can write a
    multi-page PDF straight from those images. Overlaying boxes onto an
    original PDF's own vector content (via pypdf/reportlab) would be a more
    fragile path for the same result, so this project doesn't use either.

    `field_labels` maps an Invoice field name (e.g. "grand_total") to the
    `ParseBlock.id` it came from, so that block's box is labeled with the
    field name instead of its generic block type. Blocks with a missing or
    out-of-range bbox are skipped, not guessed at, and counted in the
    sidecar file.
    """
    field_labels = field_labels or {}
    block_id_to_label = {block_id: field for field, block_id in field_labels.items()}

    # Annotate exactly the pages parse_result actually covers (whatever page
    # range was parsed) -- no separate range/cap needed here.
    parsed_page_numbers = sorted(
        [page.page for page in parse_result.pages] + parse_result.content_filtered_pages
        + [d.page for d in parse_result.page_diagnostics if d.page is not None]
    )
    start_page = parsed_page_numbers[0] if parsed_page_numbers else 1
    end_page = parsed_page_numbers[-1] if parsed_page_numbers else 1

    pages_payload = preprocess_pages(source_path, start_page=start_page, end_page=end_page)
    doc_sha = pages_payload[0]["doc_sha256"]
    blocks_by_page = {page.page: page.blocks for page in parse_result.pages}

    font = ImageFont.load_default(size=LABEL_FONT_SIZE)
    annotated_images: list[Image.Image] = []
    drawn = 0
    skipped = 0

    for payload in pages_payload:
        image = Image.open(io.BytesIO(base64.b64decode(payload["base64"]))).convert("RGB")
        draw = ImageDraw.Draw(image)

        for block in blocks_by_page.get(payload["page"], []):
            if block.bbox is None or not _bbox_is_valid(block.bbox.xyxy):
                skipped += 1
                continue
            x0, y0, x1, y1 = block.bbox.xyxy
            box_px = (x0 * image.width, y0 * image.height, x1 * image.width, y1 * image.height)
            label = block_id_to_label.get(block.id, block.type)
            draw.rectangle(box_px, outline=BOX_COLOR, width=3)
            draw.text((box_px[0], max(box_px[1] - LABEL_FONT_SIZE - 2, 0)), label, fill=BOX_COLOR, font=font)
            drawn += 1

        annotated_images.append(image)

    out_dir = Path("data/annotated")
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / f"{doc_sha}.pdf"
    first, *rest = annotated_images
    first.save(pdf_path, "PDF", save_all=True, append_images=rest)

    # Also save each annotated page as its own PNG, so the UI can preview
    # them inline (st.image) without needing a PDF-viewer widget/dependency.
    pages_dir = out_dir / doc_sha
    pages_dir.mkdir(parents=True, exist_ok=True)
    for payload, image in zip(pages_payload, annotated_images):
        image.save(pages_dir / f"page_{payload['page']:03d}.png")

    meta_path = out_dir / f"{doc_sha}.meta.json"
    meta_path.write_text(
        json.dumps(
            {
                "doc_sha": doc_sha,
                "pages": len(annotated_images),
                "blocks_drawn": drawn,
                "blocks_skipped": skipped,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return pdf_path, meta_path
