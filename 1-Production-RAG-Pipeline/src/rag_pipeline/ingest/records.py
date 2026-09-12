"""JSONL record schema for ingested files."""

from dataclasses import dataclass, field


@dataclass
class PageRecord:
    page: int
    text: str
    ocr: bool
    confidence: float | None = None


@dataclass
class IngestRecord:
    id: str
    path: str
    mime: str
    page_count: int
    text_by_page: list[PageRecord]
    ocr_used: bool
    lang: str
    hash: str
    ingested_at: str
    # Beyond the base schema: populated only when --translate is used and the
    # detected source language differs from --target-lang.
    translation: dict | None = field(default=None)
