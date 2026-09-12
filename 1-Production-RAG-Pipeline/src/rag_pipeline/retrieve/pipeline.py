"""Hybrid retrieval request path: embed query -> dense + BM25 -> RRF fuse ->
dedup -> pointwise rerank -> top-k. No answer generation here -- see SPEC.md.
"""

from pathlib import Path

import ollama

from rag_pipeline.config import load_settings
from rag_pipeline.index import vector_store
from rag_pipeline.index.meta import read_index_meta
from rag_pipeline.ingest.ocr import unload_model
from rag_pipeline.retrieve import dense, fusion, lexical
from rag_pipeline.retrieve.records import Candidate, RetrievalResult
from rag_pipeline.retrieve.reranker import RERANK_MODEL
from rag_pipeline.retrieve.reranker import rerank as rerank_candidates

DEFAULT_N = 50
DEFAULT_K = 5
RRF_K = 60
FUSION_TOP = 20


def run_retrieve(
    index_dir: Path,
    query: str,
    *,
    k: int = DEFAULT_K,
    n: int = DEFAULT_N,
    hybrid: bool = True,
    rerank: bool = True,
) -> list[RetrievalResult]:
    meta = read_index_meta(index_dir)
    embed_model = meta["embed_model"]

    ollama_client = ollama.Client(host=load_settings().ollama_host)
    qdrant_client = vector_store.open_client(index_dir)

    query_vector = list(ollama_client.embed(model=embed_model, input=[query]).embeddings[0])
    # Unload the embed model before the rerank model (a different model) loads,
    # so at most one heavy Ollama model is resident at a time within a query --
    # matching the same policy ingest/index already enforce for their batches.
    unload_model(ollama_client, embed_model)
    dense_hits = dense.dense_search(qdrant_client, query_vector, limit=n)

    if hybrid:
        bm25_hits = lexical.bm25_search(index_dir, query, limit=n)
        fused = fusion.rrf_fuse(
            [chunk_id for chunk_id, _ in dense_hits],
            [chunk_id for chunk_id, _ in bm25_hits],
            k=RRF_K,
        )
    else:
        fused = dense_hits

    top_fused = fused[:FUSION_TOP]
    fused_ids = [chunk_id for chunk_id, _ in top_fused]
    fused_score_by_id = dict(top_fused)

    payloads = vector_store.get_payloads(qdrant_client, fused_ids)
    qdrant_client.close()

    candidates: list[Candidate] = []
    for rank, chunk_id in enumerate(fused_ids, start=1):
        payload = payloads.get(chunk_id)
        if payload is None:
            continue  # dangling id (shouldn't happen); don't crash the query
        candidates.append(
            Candidate(
                chunk_id=chunk_id,
                text=payload["text"],
                source_path=payload["source_path"],
                page=payload["page"],
                score=fused_score_by_id[chunk_id],
                fusion_rank=rank,
                rerank_score=None,
            )
        )

    if rerank and candidates:
        candidates = rerank_candidates(ollama_client, query, candidates)
        unload_model(ollama_client, RERANK_MODEL)

    return [
        RetrievalResult(
            text=c["text"],
            score=c["score"],
            source_path=c["source_path"],
            page=c["page"],
            chunk_id=c["chunk_id"],
            fusion_rank=c["fusion_rank"],
            rerank_score=c["rerank_score"],
        )
        for c in candidates[:k]
    ]
