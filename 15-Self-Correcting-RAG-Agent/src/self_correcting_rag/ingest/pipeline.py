"""Parse supported files under a directory into 512/64-token chunks. Next: index/pipeline.py,
which embeds and stores what this produces.
"""

import logging
import uuid
from pathlib import Path

from self_correcting_rag.ingest.chunker import chunk_page_text
from self_correcting_rag.ingest.parsers import discover_files, parse_file
from self_correcting_rag.ingest.records import Chunk

logger = logging.getLogger(__name__)

# Fixed, arbitrary namespace so chunk IDs are deterministic across runs.
_ID_NAMESPACE = uuid.UUID("7e6e6a2a-4b8b-4a2e-9b5a-3a6b6f9e2b41")


def _chunk_id(source_path: str, page: int, index: int) -> str:
    return str(uuid.uuid5(_ID_NAMESPACE, f"{source_path}:{page}:{index}"))


def run_ingest(input_dir: Path, *, ocr: bool = False) -> list[Chunk]:
    chunks: list[Chunk] = []
    skipped_ocr_pages = 0

    for path in discover_files(input_dir):
        # .as_posix(): source_path is stored in the index and later compared/displayed
        # (citations, eval expected_source). Keep it forward-slash on every OS so a chunk
        # indexed on Windows still matches by string equality anywhere else it's read.
        source_path = str(path.relative_to(input_dir).as_posix())
        for parsed_page in parse_file(path):
            if parsed_page.needs_ocr:
                skipped_ocr_pages += 1
                continue
            for index, text in enumerate(chunk_page_text(parsed_page.text)):
                chunks.append(
                    Chunk(
                        chunk_id=_chunk_id(source_path, parsed_page.page, index),
                        text=text,
                        source_path=source_path,
                        page=parsed_page.page,
                    )
                )

    if skipped_ocr_pages:
        if ocr:
            logger.warning(
                "OCR is not implemented in this phase (allowed model: "
                "AuditAid/PaddleOCR-VL-1.6-0.9B) -- skipped %d scanned page(s).",
                skipped_ocr_pages,
            )
        else:
            logger.warning(
                "skipped %d scanned page(s) with no extractable text; pass --ocr "
                "to see this noted explicitly (OCR itself is not yet wired in).",
                skipped_ocr_pages,
            )

    return chunks
