"""Tests for src.annotate's PDF/PNG box-drawing -- feeds `ParseResult`
fixtures directly (no model call, no schema round-trip) and checks the
output artifacts plus the drawn/skipped block counts recorded in the
sidecar .meta.json.

Next: src/annotate.py.
"""

from __future__ import annotations

from pathlib import Path

from src.annotate import annotate_document
from src.schema import BBox, ParseBlock, ParsePage, ParseResult

FIXTURE_PATH = (Path(__file__).parent / "fixtures" / "invoice.png").resolve()


def test_annotated_pdf_is_created(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    parse_result = ParseResult(
        doc_sha="unused",  # annotate_document derives doc_sha from the source file itself
        pages=[
            ParsePage(
                page=1, width_px=900, height_px=620,
                blocks=[
                    ParseBlock(
                        id="b1", type="key_value", text="Grand Total: 88.00",
                        bbox=BBox(page=1, xyxy=(0.6, 0.8, 0.95, 0.85)), conf=None, table=None,
                    ),
                ],
            )
        ],
    )

    pdf_path, meta_path = annotate_document(FIXTURE_PATH, parse_result)

    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0
    assert meta_path.exists()

    page_png = pdf_path.parent / pdf_path.stem / "page_001.png"
    assert page_png.exists()
    assert page_png.stat().st_size > 0


def test_missing_or_out_of_range_bbox_is_skipped_not_crashed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    parse_result = ParseResult(
        doc_sha="unused",
        pages=[
            ParsePage(
                page=1, width_px=900, height_px=620,
                blocks=[
                    ParseBlock(
                        id="b1", type="text", text="no box", bbox=None, conf=None, table=None,
                    ),
                    ParseBlock(
                        id="b2", type="text", text="off page",
                        bbox=BBox(page=1, xyxy=(0.5, 0.5, 1.5, 1.5)),  # out of 0-1 range
                        conf=None, table=None,
                    ),
                ],
            )
        ],
    )

    pdf_path, meta_path = annotate_document(FIXTURE_PATH, parse_result)

    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0

    meta = meta_path.read_text(encoding="utf-8")
    assert '"blocks_drawn": 0' in meta
    assert '"blocks_skipped": 2' in meta


def test_field_labels_used_for_matched_block(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    parse_result = ParseResult(
        doc_sha="unused",
        pages=[
            ParsePage(
                page=1, width_px=900, height_px=620,
                blocks=[
                    ParseBlock(
                        id="b1", type="key_value", text="Grand Total: 88.00",
                        bbox=BBox(page=1, xyxy=(0.6, 0.8, 0.95, 0.85)), conf=None, table=None,
                    ),
                ],
            )
        ],
    )

    pdf_path, meta_path = annotate_document(
        FIXTURE_PATH, parse_result, field_labels={"grand_total": "b1"}
    )

    assert pdf_path.exists()
    meta = meta_path.read_text(encoding="utf-8")
    assert '"blocks_drawn": 1' in meta


def test_content_filtered_pages_remain_in_annotated_pdf(tmp_path, monkeypatch):
    from PIL import Image

    monkeypatch.chdir(tmp_path)
    pdf_path = tmp_path / "multi.pdf"
    page_images = [Image.new("RGB", (200, 100), color) for color in ("white", "red", "blue")]
    page_images[0].save(pdf_path, save_all=True, append_images=page_images[1:])
    parse_result = ParseResult(
        doc_sha="unused",
        pages=[ParsePage(page=2, width_px=200, height_px=100, blocks=[])],
        content_filtered_pages=[1, 3],
    )

    _, meta_path = annotate_document(pdf_path, parse_result)

    meta = meta_path.read_text(encoding="utf-8")
    assert '"pages": 3' in meta
