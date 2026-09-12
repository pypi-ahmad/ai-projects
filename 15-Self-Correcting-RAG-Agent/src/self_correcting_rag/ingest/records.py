"""Chunk record produced by ingest, consumed by index."""

from dataclasses import dataclass


@dataclass
class Chunk:
    chunk_id: str
    text: str
    source_path: str
    page: int
