"""Tests for src.markdown's Markdown/HTML rendering of a `ParseResult` --
reading order, table/HTML escaping, checkbox notation, and that the
Markdown and HTML renderers stay in sync since both read the same blocks.

Next: src/markdown.py.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.markdown import parse_to_html, parse_to_markdown, render_and_save
from src.layout import BBox, ParseBlock, ParsePage, ParseResult


def test_ragged_model_table_rows_are_padded_without_changing_cells():
    block = ParseBlock(
        id="t1", type="table", text="A | B", bbox=None, conf=None,
        table=[["A", "B"], ["C"]],
    )
    assert block.table == [["A", "B"], ["C", ""]]


def _sample_result() -> ParseResult:
    return ParseResult(
        doc_sha="abc123",
        pages=[
            ParsePage(
                page=1,
                width_px=800,
                height_px=600,
                blocks=[
                    ParseBlock(
                        id="h1", type="heading", text="Line Items",
                        bbox=BBox(page=1, xyxy=(0.1, 0.1, 0.5, 0.15)), conf=None, table=None,
                    ),
                    ParseBlock(
                        id="t1", type="table", text="",
                        bbox=BBox(page=1, xyxy=(0.1, 0.2, 0.9, 0.4)), conf=None,
                        table=[["Item", "Amount"], ["Widget A", "30.00"]],
                    ),
                    ParseBlock(
                        id="p1", type="text", text="Thank you for your business.",
                        bbox=BBox(page=1, xyxy=(0.1, 0.5, 0.9, 0.55)), conf=None, table=None,
                    ),
                ],
            )
        ],
    )


def test_parse_to_markdown_snapshot():
    md = parse_to_markdown(_sample_result())

    assert md == (
        "## Line Items\n\n"
        "| Item | Amount |\n"
        "| --- | --- |\n"
        "| Widget A | 30.00 |\n\n"
        "Thank you for your business.\n"
    )


def test_parse_to_html_renders_document_like_page():
    result = _sample_result()
    doc = parse_to_html(result)

    assert doc.startswith("<!doctype html>")
    assert "background:#ffffff" in doc
    assert "color:#000000" in doc
    assert "<h2>Line Items</h2>" in doc
    assert "<table>" in doc and "<th>Item</th>" in doc and "<td>Widget A</td>" in doc
    assert "<p>Thank you for your business.</p>" in doc


def test_parse_to_html_escapes_content():
    result = ParseResult(
        doc_sha="x",
        pages=[
            ParsePage(
                page=1, width_px=10, height_px=10,
                blocks=[
                    ParseBlock(
                        id="a", type="text", text="<script>alert(1)</script>",
                        bbox=None, conf=None, table=None,
                    )
                ],
            )
        ],
    )
    doc = parse_to_html(result)
    assert "<script>" not in doc
    assert "&lt;script&gt;" in doc


def test_key_value_splits_on_first_colon():
    result = ParseResult(
        doc_sha="x",
        pages=[
            ParsePage(
                page=1, width_px=10, height_px=10,
                blocks=[
                    ParseBlock(
                        id="k1", type="key_value", text="Invoice #: INV-1001", bbox=None,
                        conf=None, table=None,
                    )
                ],
            )
        ],
    )
    assert parse_to_markdown(result) == "**Invoice #:** INV-1001\n"


def test_no_bbox_blocks_keep_model_order():
    result = ParseResult(
        doc_sha="y",
        pages=[
            ParsePage(
                page=1, width_px=10, height_px=10,
                blocks=[
                    ParseBlock(id="a", type="text", text="first", bbox=None, conf=None, table=None),
                    ParseBlock(id="b", type="text", text="second", bbox=None, conf=None, table=None),
                ],
            )
        ],
    )
    assert parse_to_markdown(result) == "first\n\nsecond\n"


def test_render_and_save_writes_md_next_to_json(tmp_path):
    json_path = tmp_path / "abc123.json"
    json_path.write_text(_sample_result().model_dump_json(indent=2), encoding="utf-8")

    out_path = render_and_save(json_path)

    assert out_path == tmp_path / "abc123.md"
    assert out_path.exists()
    assert "## Line Items" in out_path.read_text(encoding="utf-8")


def test_column_order_is_preserved_even_with_missing_bbox():
    result = _sample_result()
    result.pages[0].blocks = [
        ParseBlock(id="a", type="text", text="Left top", bbox=BBox(page=1, xyxy=(0.1, 0.1, 0.4, 0.2)), conf=None, table=None),
        ParseBlock(id="b", type="text", text="Left bottom", bbox=BBox(page=1, xyxy=(0.1, 0.7, 0.4, 0.8)), conf=None, table=None),
        ParseBlock(id="c", type="text", text="Unpositioned note", bbox=None, conf=None, table=None),
        ParseBlock(id="d", type="text", text="Right top", bbox=BBox(page=1, xyxy=(0.6, 0.1, 0.9, 0.2)), conf=None, table=None),
    ]
    for rendered in (parse_to_markdown(result), parse_to_html(result)):
        positions = [rendered.index(b.text) for b in result.pages[0].blocks]
        assert positions == sorted(positions)


def test_table_escaping_padding_and_line_breaks_preserve_source():
    result = _sample_result()
    table = result.pages[0].blocks[1]
    table.table = [["Field", "Value"], ["A|B", "C:\\temp\r\n<script>"], ["Blank"]]
    before = result.model_dump_json()
    md = parse_to_markdown(result)
    html = parse_to_html(result)
    assert "| A\\|B | C:\\\\temp<br>&lt;script&gt; |" in md
    assert "| Blank |  |" in md
    assert "<td>C:\\temp<br>&lt;script&gt;</td>" in html
    assert "<tr><td>Blank</td><td></td></tr>" in html
    assert result.model_dump_json() == before


def test_table_empty_and_unstructured_fallback():
    from src.markdown import _render_table, _render_table_html

    assert _render_table([]) == _render_table_html([]) == ""
    assert _render_table([[]]) == _render_table_html([[]]) == ""
    result = _sample_result()
    result.pages[0].blocks[1].table = None
    result.pages[0].blocks[1].text = "Unreadable grid <source>"
    assert "Unreadable grid <source>" in parse_to_markdown(result)
    assert "<pre>Unreadable grid &lt;source&gt;</pre>" in parse_to_html(result)


def test_checkbox_words_render_as_notation_without_changing_extraction():
    result = _sample_result()
    block = result.pages[0].blocks[0]
    block.text = "Participating checked; Nonparticipating unchecked; status unchecked"
    before = result.model_dump_json()

    assert "Participating [x]; Nonparticipating [ ]; status [ ]" in parse_to_markdown(result)
    assert "Participating [x]; Nonparticipating [ ]; status [ ]" in parse_to_html(result)
    assert result.model_dump_json() == before
