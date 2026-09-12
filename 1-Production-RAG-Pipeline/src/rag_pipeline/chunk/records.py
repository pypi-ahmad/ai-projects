"""JSONL record schema for chunks."""

from dataclasses import dataclass


@dataclass
class ChunkRecord:
    doc_id: str
    source_path: str
    page: int
    chunk_index: int
    hash: str
    ocr_used: bool
    text: str
    source_hash: str = ""  # the source file's content hash, for incremental skip
