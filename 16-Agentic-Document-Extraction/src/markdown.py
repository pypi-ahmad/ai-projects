"""Renders a `ParseResult` (the active graph's output) as layout-aware
Markdown and as a self-contained HTML page -- the two human-facing artifacts
under data/parse/. Both renderers walk the same block/reading-order
(`_page_reading_order`) so they can't drift apart from each other; neither
one re-parses the other's output.

Must not: read from or write anything under data/committed/, data/review/,
or data/crops/ -- those belong to the dormant invoice path (see
docs/ARCHITECTURE.md).

Next: src/annotate.py, which renders the same ParseResult as boxes on the
source pages instead of text.
"""

from __future__ import annotations

import argparse
import html as _html
import re
from pathlib import Path

from src.schema import ParseBlock, ParsePage, ParseResult


def _page_reading_order(page: ParsePage) -> list[ParseBlock]:
    """The extracted order preserves columns and label/value associations."""
    return page.blocks


def _table_rows(rows: list[list[str]]) -> list[list[str]]:
    width = max((len(row) for row in rows), default=0)
    return [row + [""] * (width - len(row)) for row in rows]


def _checkbox_notation(text: str) -> str:
    return re.sub(r"\bunchecked\b", "[ ]", re.sub(r"\bchecked\b", "[x]", text), flags=re.IGNORECASE)


def _cell_html(text: str) -> str:
    # A table cell can contain an embedded newline (e.g. a multi-line
    # address); normalize CRLF/CR to LF first so a mixed-line-ending source
    # doesn't produce a stray blank <br> before converting to HTML breaks.
    return _html.escape(_checkbox_notation(text)).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def _render_table(rows: list[list[str]]) -> str:
    if not rows or not any(rows):
        return ""
    # Escape backslashes before pipes: if the order were reversed, the
    # backslash just inserted to escape a literal "|" would itself get
    # doubled by the backslash-escaping step that runs after it.
    escaped = [[_cell_html(cell).replace("\\", "\\\\").replace("|", "\\|") for cell in row] for row in _table_rows(rows)]
    header, *body = escaped
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)


def _render_block(block: ParseBlock) -> str:
    text = _checkbox_notation(block.text)
    if block.type == "title":
        return f"# {text}".rstrip()
    if block.type == "heading":
        return f"## {text}".rstrip()
    if block.type == "key_value":
        key, sep, value = text.partition(":")
        return f"**{key.strip()}:** {value.strip()}" if sep else text
    if block.type == "table":
        return _render_table(block.table) if block.table else f"```\n{text}\n```"
    if block.type == "figure":
        return f"[figure] {text}".rstrip()
    # text, line_item, other -> plain paragraph
    return text


def parse_to_markdown(result: ParseResult) -> str:
    parts: list[str] = []
    for page in sorted(result.pages, key=lambda p: p.page):
        for block in _page_reading_order(page):
            rendered = _render_block(block)
            if rendered:
                parts.append(rendered)
    return "\n\n".join(parts) + "\n"


def _render_table_html(rows: list[list[str]]) -> str:
    if not rows or not any(rows):
        return ""
    header, *body = _table_rows(rows)
    thead = "".join(f"<th>{_cell_html(c)}</th>" for c in header)
    tbody = "".join(
        "<tr>" + "".join(f"<td>{_cell_html(c)}</td>" for c in row) + "</tr>" for row in body
    )
    return f"<table><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table>"


def _render_block_html(block: ParseBlock) -> str:
    text = _checkbox_notation(block.text)
    if block.type == "title":
        return f"<h1>{_html.escape(text)}</h1>"
    if block.type == "heading":
        return f"<h2>{_html.escape(text)}</h2>"
    if block.type == "key_value":
        key, sep, value = text.partition(":")
        if sep:
            return f"<p><strong>{_html.escape(key.strip())}:</strong> {_html.escape(value.strip())}</p>"
        return f"<p>{_html.escape(text)}</p>"
    if block.type == "table":
        return _render_table_html(block.table) if block.table else f"<pre>{_html.escape(text)}</pre>"
    if block.type == "figure":
        return f"<p><em>[figure]</em> {_html.escape(text)}</p>"
    return f"<p>{_html.escape(text)}</p>"


_HTML_STYLE = """
<style>
  body { background:#ffffff; color:#000000; font-family: Georgia, 'Times New Roman', serif;
         max-width: 800px; margin: 0 auto; padding: 24px; line-height: 1.5; }
  h1 { font-size: 1.6em; border-bottom: 2px solid #000; padding-bottom: 4px; }
  h2 { font-size: 1.25em; margin-top: 1.2em; }
  table { border-collapse: collapse; width: 100%; margin: 12px 0; }
  th, td { border: 1px solid #333; padding: 6px 10px; text-align: left; }
  th { background: #eeeeee; }
  p { margin: 0.6em 0; }
</style>
"""


def parse_to_html(result: ParseResult) -> str:
    """Render `result` as a self-contained HTML page (white background, black
    text, document-like typography) so it visually resembles a printed page
    of the source document.

    Rendered from the same blocks/reading-order as `parse_to_markdown`
    (not by re-parsing the Markdown string), so the two never drift apart.
    """
    parts: list[str] = []
    for page in sorted(result.pages, key=lambda p: p.page):
        for block in _page_reading_order(page):
            parts.append(_render_block_html(block))
    body = "\n".join(parts)
    return f"<!doctype html><html><head><meta charset='utf-8'>{_HTML_STYLE}</head><body>{body}</body></html>"


def render_and_save(parse_json_path: str | Path) -> Path:
    p = Path(parse_json_path)
    result = ParseResult.model_validate_json(p.read_text(encoding="utf-8"))
    out_path = p.with_suffix(".md")
    out_path.write_text(parse_to_markdown(result), encoding="utf-8")
    return out_path


def save_markdown_for_doc(result: ParseResult, *, output_dir: str | Path = "data/parse") -> Path:
    """Write <output_dir>/<doc_sha>.md directly from an in-memory ParseResult
    (the graph's parse node already has the result, no JSON round-trip needed).
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{result.doc_sha}.md"
    out_path.write_text(parse_to_markdown(result), encoding="utf-8")
    return out_path


def _main() -> None:
    parser = argparse.ArgumentParser(description="Render a ParseResult JSON into layout-aware Markdown.")
    parser.add_argument("--parse", required=True, help="Path to a data/parse/<doc_sha>.json file")
    args = parser.parse_args()

    out_path = render_and_save(args.parse)
    print(f"written to {out_path}")


if __name__ == "__main__":
    _main()
