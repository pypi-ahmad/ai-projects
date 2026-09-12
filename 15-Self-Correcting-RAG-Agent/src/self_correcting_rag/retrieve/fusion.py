"""Reciprocal Rank Fusion (RRF) over N independently-ranked result lists."""


def rrf_fuse(*ranked_id_lists: list[str], k: int = 60) -> list[tuple[str, float]]:
    """Returns (chunk_id, fused_score) pairs, sorted by fused_score descending.

    RRF uses only each list's RANK (1-indexed position), not the underlying
    score values -- lists from different signals (dense cosine similarity,
    BM25 weight, or per-query rankings) are on incompatible scales. Dedups by
    chunk id: a chunk appearing in multiple lists gets every list's
    contribution summed.
    """
    scores: dict[str, float] = {}
    for ranked_ids in ranked_id_lists:
        for rank, chunk_id in enumerate(ranked_ids, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)
