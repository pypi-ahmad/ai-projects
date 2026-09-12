"""Dormant crop-targeting logic for the invoice/validation path (see
docs/REGIONS.md, docs/ARCHITECTURE.md): decides which `Region`-tagged fields
are worth a second, tighter-cropped look, either by reusing a bbox the
layout parser already found (`regions_from_parse`) or via a low-confidence
score / validation failure (`should_crop`).

Not called by the active graph -- src/parse.py never emits `Region` objects,
only `ParseBlock`s. Must not: assume every failing field has a bbox to crop;
the crop trigger (docs/REGIONS.md) requires `bbox_xyxy` to be present in the
first place, and `should_crop` only decides *whether* an already-boxed
region is worth cropping.

Next: src/extract.py's `crop_and_extract` for what happens to a region once
it's selected, or docs/REGIONS.md for the exact trigger rule.
"""

from __future__ import annotations

from PIL import Image

from src.markdown import _page_reading_order
from src.schema import ParseResult, Region, ValidationReport

CONF_THRESHOLD = 0.6


def _failed_field_keys(report: ValidationReport) -> set[str]:
    """Map validate.py error codes to the field_or_line_index keys they concern."""
    keys: set[str] = set()
    for error in report.errors:
        if error.code == "subtotal_mismatch":
            keys.add("subtotal")
        elif error.code == "grand_total_mismatch":
            keys.add("grand_total")
        elif error.code.startswith("line_item_math["):
            index = error.code[len("line_item_math[") : -1]
            keys.add(f"line_items[{index}]")
    return keys


def should_crop(region: Region, report: ValidationReport) -> bool:
    """Every Region already carries a bbox (the schema requires one); the only
    remaining gate is confidence or a math failure on that specific field.
    """
    if region.conf < CONF_THRESHOLD:
        return True
    return region.field_or_line_index in _failed_field_keys(report)


def cropable_regions(regions: list[Region], report: ValidationReport) -> list[Region]:
    return [r for r in regions if should_crop(r, report)]


def regions_from_parse(parse_result: ParseResult | None, report: ValidationReport) -> list[Region]:
    """Reuse bboxes the layout parser already found for failing line items,
    instead of asking the model a second "regions only" question for them.

    Only line items are matched here (by position: the i-th "line_item"
    block in reading order is assumed to correspond to Invoice.line_items[i]
    -- a best-effort heuristic, since ParseBlock carries no explicit index).
    Header fields (subtotal, grand_total, ...) still go through
    `extract_regions` since there's no such positional link for them.
    """
    if parse_result is None:
        return []

    line_item_blocks = [
        block
        for page in sorted(parse_result.pages, key=lambda p: p.page)
        for block in _page_reading_order(page)
        if block.type == "line_item"
    ]

    regions = []
    for key in _failed_field_keys(report):
        if not key.startswith("line_items["):
            continue
        index = int(key[len("line_items[") : -1])
        if index >= len(line_item_blocks):
            continue
        block = line_item_blocks[index]
        if block.bbox is None:
            continue
        regions.append(
            Region(
                id=block.id,
                field_or_line_index=key,
                conf=block.conf if block.conf is not None else 0.5,
                bbox_xyxy=block.bbox.xyxy,
                reason=None,
            )
        )
    return regions


def crop_image_bbox(image: Image.Image, bbox_xyxy: tuple[float, float, float, float]) -> Image.Image:
    """Crop `image` using a normalized (0-1) x0,y0,x1,y1 box."""
    x0, y0, x1, y1 = bbox_xyxy
    w, h = image.size
    box = (round(x0 * w), round(y0 * h), round(x1 * w), round(y1 * h))
    return image.crop(box)
