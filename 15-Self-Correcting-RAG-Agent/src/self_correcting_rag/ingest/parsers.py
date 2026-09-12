"""Per-file-type parsing into page-level text. Minimum viable: txt, md, pdf-text
only -- no docx/html/images. Scanned (image-only) PDF pages are flagged
`needs_ocr` rather than parsed; see `pipeline.run_index`'s `--ocr` handling.

ParsedPage.page is 1-indexed for every file type (txt/md report a single page=1;
pymupdf's own page objects are 0-indexed, converted here via `index + 1`) -- this is the
number that ends up in citations ("source.md#page1"), so keep it 1-indexed if you add a
new parser. Next: ingest/chunker.py, which turns one page's text into chunks.
"""

from dataclasses import dataclass
from pathlib import Path

import pymupdf

# ponytail: naive length heuristic for "this PDF page is a scan, not digital text".
# No layout/whitespace analysis. Revisit if real corpora show false positives/negatives.
MIN_TEXT_CHARS_PER_PAGE = 20

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf"}


@dataclass
class ParsedPage:
    page: int
    text: str
    needs_ocr: bool


def parse_txt(path: Path) -> list[ParsedPage]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return [ParsedPage(page=1, text=text, needs_ocr=False)]


def parse_md(path: Path) -> list[ParsedPage]:
    return parse_txt(path)


def parse_pdf(path: Path) -> list[ParsedPage]:
    pages = []
    with pymupdf.open(str(path)) as doc:
        for index, page in enumerate(doc):
            text = page.get_text()
            needs_ocr = len(text.strip()) < MIN_TEXT_CHARS_PER_PAGE
            pages.append(
                ParsedPage(page=index + 1, text="" if needs_ocr else text, needs_ocr=needs_ocr)
            )
    return pages


_PARSERS_BY_EXT = {".txt": parse_txt, ".md": parse_md, ".pdf": parse_pdf}


def parse_file(path: Path) -> list[ParsedPage]:
    ext = path.suffix.lower()
    if ext not in _PARSERS_BY_EXT:
        raise ValueError(f"unsupported extension: {ext}")
    return _PARSERS_BY_EXT[ext](path)


def discover_files(input_dir: Path) -> list[Path]:
    return sorted(
        p for p in input_dir.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )
