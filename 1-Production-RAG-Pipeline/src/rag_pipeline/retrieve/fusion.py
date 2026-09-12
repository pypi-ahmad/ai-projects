"""Reciprocal Rank Fusion (RRF) over two independently-ranked result lists."""


def rrf_fuse(
    dense_ranked_ids: list[str],
    bm25_ranked_ids: list[str],
    k: int = 60,
) -> list[tuple[str, float]]:
    """Returns (chunk_id, fused_score) pairs, sorted by fused_score descending.

    RRF uses only each list's RANK (1-indexed position), not the underlying
    dense/BM25 score values -- those are on incompatible scales (cosine
    similarity vs. a BM25 weight), which is the whole reason to use RRF
    instead of a weighted sum of raw scores. Also dedups by chunk id: a chunk
    appearing in both lists gets both lists' contributions summed.
    """
    scores: dict[str, float] = {}
    for rank, chunk_id in enumerate(dense_ranked_ids, start=1):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    for rank, chunk_id in enumerate(bm25_ranked_ids, start=1):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)
