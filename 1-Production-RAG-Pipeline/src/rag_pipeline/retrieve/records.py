"""Result schema for retrieve."""

from dataclasses import dataclass
from typing import TypedDict


class Candidate(TypedDict):
    """Mutable working record for one fused chunk, before/after reranking."""

    chunk_id: str
    text: str
    source_path: str
    page: int
    score: float
    fusion_rank: int
    rerank_score: float | None


@dataclass
class RetrievalResult:
    text: str
    score: float
    source_path: str
    page: int
    chunk_id: str
    fusion_rank: int
    rerank_score: float | None
