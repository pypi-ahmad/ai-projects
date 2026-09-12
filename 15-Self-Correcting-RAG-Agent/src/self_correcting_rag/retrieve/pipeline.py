"""Hybrid retrieval request path: embed query -> dense + BM25 -> RRF fuse ->
top-k. No rewrite, no rerank, no answer generation -- see SPEC.md phase plan.
Next: agent/critique.py, the first thing the agent loop does with these results.
"""

from dataclasses import replace
from pathlib import Path

import ollama

from self_correcting_rag.config import load_settings
from self_correcting_rag.index import vector_store
from self_correcting_rag.index.pipeline import EMBED_MODEL
from self_correcting_rag.llm.vram import unload_all
from self_correcting_rag.retrieve import dense, fusion, lexical
from self_correcting_rag.retrieve.records import RetrievalResult

DEFAULT_N = 50
RRF_K = 60


def retrieve(
    index_dir: Path, query: str, k: int = 5, *, n: int = DEFAULT_N
) -> list[RetrievalResult]:
    client = ollama.Client(host=load_settings().ollama_host)
    query_vector = list(client.embed(model=EMBED_MODEL, input=[query]).embeddings[0])
    unload_all(client)

    qdrant_client = vector_store.open_client(index_dir)
    dense_hits = dense.dense_search(qdrant_client, query_vector, limit=n)
    bm25_hits = lexical.bm25_search(index_dir, query, limit=n)
    fused = fusion.rrf_fuse(
        [chunk_id for chunk_id, _ in dense_hits],
        [chunk_id for chunk_id, _ in bm25_hits],
        k=RRF_K,
    )[:k]

    fused_ids = [chunk_id for chunk_id, _ in fused]
    fused_score_by_id = dict(fused)
    payloads = vector_store.get_payloads(qdrant_client, fused_ids)
    qdrant_client.close()

    results = []
    for chunk_id in fused_ids:
        payload = payloads.get(chunk_id)
        if payload is None:
            continue  # dangling id (shouldn't happen); don't crash the query
        results.append(
            RetrievalResult(
                chunk_id=chunk_id,
                text=payload["text"],
                source_path=payload["source_path"],
                page=payload["page"],
                score=fused_score_by_id[chunk_id],
            )
        )
    return results


MULTI_QUERY_CANDIDATES = 10


def retrieve_multi(index_dir: Path, queries: list[str], k: int) -> list[RetrievalResult]:
    """Retrieves each query independently (each already a full dense+BM25+RRF
    hybrid search), then RRF-fuses the per-query result rankings by rank and
    dedups by chunk id. Used by the agent loop to combine the original
    question with its rewritten variants into one candidate set.

    Each query re-embeds independently via retrieve(), so N queries means N embed calls
    (and N Ollama unload_all() calls) -- not batched into one embed request. Simple and
    correct; revisit if per-query latency here matters more than it does today.
    """
    deduped_queries = list(dict.fromkeys(queries))
    if not deduped_queries:
        return []

    per_query_results = [retrieve(index_dir, q, k=MULTI_QUERY_CANDIDATES) for q in deduped_queries]
    ranked_id_lists = [[r.chunk_id for r in results] for results in per_query_results]
    fused = fusion.rrf_fuse(*ranked_id_lists, k=RRF_K)[:k]

    by_id = {r.chunk_id: r for results in per_query_results for r in results}
    return [replace(by_id[chunk_id], score=score) for chunk_id, score in fused if chunk_id in by_id]
