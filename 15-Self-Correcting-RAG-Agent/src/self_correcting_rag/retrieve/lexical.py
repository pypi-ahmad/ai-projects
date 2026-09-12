"""Lexical (BM25) search against the saved bm25s index."""

from pathlib import Path

import bm25s

from self_correcting_rag.index.lexical_store import BM25_DIRNAME


def bm25_search(index_dir: Path, query: str, limit: int) -> list[tuple[str, float]]:
    """Returns (chunk_id, bm25_score) pairs, ranked descending by score."""
    if not (index_dir / BM25_DIRNAME).exists():
        return []
    retriever = bm25s.BM25.load(str(index_dir / BM25_DIRNAME), load_corpus=True)
    corpus_size = len(retriever.corpus)
    if corpus_size == 0:
        return []
    query_tokens = bm25s.tokenize([query], stopwords="en", show_progress=False)
    results, scores = retriever.retrieve(
        query_tokens, k=min(limit, corpus_size), show_progress=False
    )
    return [(doc["id"], float(score)) for doc, score in zip(results[0], scores[0], strict=True)]
