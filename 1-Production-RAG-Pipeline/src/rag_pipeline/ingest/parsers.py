"""Per-file-type parsing into page-level text, flagging pages that need OCR."""

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

import pymupdf
from docx import Document

# ponytail: naive length heuristic for "this PDF page is a scan, not digital text".
# No layout/whitespace analysis. Revisit if real corpora show false positives
# (e.g. a mostly-image page with a short digital caption) or false negatives
# (e.g. a scan with a few embedded digital annotations).
MIN_TEXT_CHARS_PER_PAGE = 20

PDF_RENDER_DPI = 200

SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".txt",
    ".md",
    ".html",
    ".png",
    ".jpg",
    ".jpeg",
    ".tiff",
}

_MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".html": "text/html",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tiff": "image/tiff",
}


@dataclass
class ParsedPage:
    page: int
    text: str
    needs_ocr: bool
    image_bytes: bytes | None = field(default=None, repr=False)


def get_mime(path: Path) -> str:
    return _MIME_BY_EXT[path.suffix.lower()]


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.chunks: list[str] = []

    _SKIP_TAGS = ("script", "style", "head")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.chunks.append(data)


def parse_txt(path: Path) -> list[ParsedPage]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return [ParsedPage(page=1, text=text, needs_ocr=False)]


def parse_md(path: Path) -> list[ParsedPage]:
    return parse_txt(path)


def parse_html(path: Path) -> list[ParsedPage]:
    extractor = _HTMLTextExtractor()
    extractor.feed(path.read_text(encoding="utf-8", errors="replace"))
    text = re.sub(r"\s+", " ", "".join(extractor.chunks)).strip()
    return [ParsedPage(page=1, text=text, needs_ocr=False)]


def parse_docx(path: Path) -> list[ParsedPage]:
    document = Document(str(path))
    text = "\n".join(p.text for p in document.paragraphs)
    return [ParsedPage(page=1, text=text, needs_ocr=False)]


def parse_image(path: Path) -> list[ParsedPage]:
    return [ParsedPage(page=1, text="", needs_ocr=True, image_bytes=path.read_bytes())]


def parse_pdf(path: Path) -> list[ParsedPage]:
    pages = []
    with pymupdf.open(str(path)) as doc:
        for index, page in enumerate(doc):
            text = page.get_text()
            if len(text.strip()) < MIN_TEXT_CHARS_PER_PAGE:
                image_bytes = page.get_pixmap(dpi=PDF_RENDER_DPI).tobytes("png")
                pages.append(
                    ParsedPage(page=index + 1, text="", needs_ocr=True, image_bytes=image_bytes)
                )
            else:
                pages.append(ParsedPage(page=index + 1, text=text, needs_ocr=False))
    return pages


_PARSERS_BY_EXT = {
    ".pdf": parse_pdf,
    ".docx": parse_docx,
    ".txt": parse_txt,
    ".md": parse_md,
    ".html": parse_html,
    ".png": parse_image,
    ".jpg": parse_image,
    ".jpeg": parse_image,
    ".tiff": parse_image,
}


def parse_file(path: Path) -> list[ParsedPage]:
    ext = path.suffix.lower()
    if ext not in _PARSERS_BY_EXT:
        raise ValueError(f"unsupported extension: {ext}")
    return _PARSERS_BY_EXT[ext](path)
