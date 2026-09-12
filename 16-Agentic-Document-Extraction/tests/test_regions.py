"""Tests for the dormant src.regions crop-targeting logic (docs/REGIONS.md)
-- confidence/math-failure crop triggers (`should_crop`) and reusing the
layout parser's own bboxes for failing line items (`regions_from_parse`).

Next: src/regions.py.
"""

from __future__ import annotations

from src.regions import regions_from_parse, should_crop
from src.schema import BBox, ParseBlock, ParsePage, ParseResult, Region, ValidationErrorItem, ValidationReport


def test_should_crop_low_confidence():
    region = Region(
        id="r1", field_or_line_index="vendor", conf=0.4, bbox_xyxy=(0, 0, 1, 1), reason=None
    )
    report = ValidationReport(ok=True, errors=[])
    assert should_crop(region, report)


def test_should_crop_failed_math_even_if_confident():
    region = Region(
        id="r1", field_or_line_index="grand_total", conf=0.95, bbox_xyxy=(0, 0, 1, 1), reason=None
    )
    report = ValidationReport(
        ok=False, errors=[ValidationErrorItem(code="grand_total_mismatch", msg="x")]
    )
    assert should_crop(region, report)


def test_should_not_crop_confident_and_passing():
    region = Region(
        id="r1", field_or_line_index="vendor", conf=0.95, bbox_xyxy=(0, 0, 1, 1), reason=None
    )
    report = ValidationReport(ok=True, errors=[])
    assert not should_crop(region, report)


def test_regions_from_parse_matches_failing_line_item_by_position():
    parse_result = ParseResult(
        doc_sha="x",
        pages=[
            ParsePage(
                page=1, width_px=10, height_px=10,
                blocks=[
                    ParseBlock(
                        id="li0", type="line_item", text="Widget A 3 10.00 30.00",
                        bbox=BBox(page=1, xyxy=(0.0, 0.1, 1.0, 0.2)), conf=None, table=None,
                    ),
                    ParseBlock(
                        id="li1", type="line_item", text="Widget B 2 25.00 50.00",
                        bbox=BBox(page=1, xyxy=(0.0, 0.2, 1.0, 0.3)), conf=None, table=None,
                    ),
                ],
            )
        ],
    )
    report = ValidationReport(
        ok=False, errors=[ValidationErrorItem(code="line_item_math[1]", msg="x")]
    )

    regions = regions_from_parse(parse_result, report)

    assert len(regions) == 1
    assert regions[0].field_or_line_index == "line_items[1]"
    assert regions[0].id == "li1"
    assert regions[0].bbox_xyxy == (0.0, 0.2, 1.0, 0.3)


def test_regions_from_parse_skips_when_no_matching_block():
    report = ValidationReport(
        ok=False, errors=[ValidationErrorItem(code="line_item_math[0]", msg="x")]
    )
    assert regions_from_parse(None, report) == []
    assert regions_from_parse(ParseResult(doc_sha="x", pages=[]), report) == []
