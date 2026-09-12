"""Retrieval result record returned by retrieve(query, k).

`score` is the RRF fused score (see retrieve/fusion.py), not the underlying dense cosine
similarity or BM25 weight -- those are discarded once fusion has used their ranks.
"""

from dataclasses import dataclass


@dataclass
class RetrievalResult:
    chunk_id: str
    text: str
    source_path: str
    page: int
    score: float
