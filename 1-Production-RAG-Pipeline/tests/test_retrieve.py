"""Retrieve tests build a small real index and make real Ollama calls -- dense
vs. BM25 behavior can't be verified against a mocked embedder, since the
whole point is real lexical vs. semantic matching. Skips gracefully (instead
of hanging or erroring confusingly) if Ollama isn't reachable.
"""

import json

import ollama
import pytest

from rag_pipeline.config import load_settings
from rag_pipeline.index import vector_store
from rag_pipeline.index.meta import read_index_meta
from rag_pipeline.index.pipeline import run_index
from rag_pipeline.retrieve import dense, lexical
from rag_pipeline.retrieve.pipeline import run_retrieve
from rag_pipeline.retrieve.reranker import rerank


def _ollama_available() -> bool:
    try:
        ollama.Client(host=load_settings().ollama_host).list()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _ollama_available(), reason="Ollama is not reachable")

# doc-a and doc-b share almost all their vocabulary (power supply, ambient
# temperature) -- only doc-a has the exact rare token "XJ-4471Z", so an exact
# match on that token is a real BM25-vs-dense differentiator, not a case
# where any reasonable retrieval method would trivially win.
CHUNKS = [
    {
        "doc_id": "doc-a",
        "source_path": "model-a.txt",
        "page": 1,
        "chunk_index": 0,
        "hash": "ha",
        "ocr_used": False,
        "text": "Model XJ-4471Z requires a steady 12V power supply and operates "
        "safely between -20C and 60C ambient temperature.",
    },
    {
        "doc_id": "doc-b",
        "source_path": "model-b.txt",
        "page": 1,
        "chunk_index": 0,
        "hash": "hb",
        "ocr_used": False,
        "text": "This device needs a stable twelve volt power source and can "
        "function reliably across a wide range of ambient temperatures.",
    },
    {
        "doc_id": "doc-quantum",
        "source_path": "quantum.txt",
        "page": 1,
        "chunk_index": 0,
        "hash": "hq",
        "ocr_used": False,
        "text": "Quantum computers use qubits and superposition to perform certain "
        "calculations exponentially faster than classical computers.",
    },
]


@pytest.fixture(scope="module")
def built_index(tmp_path_factory):
    base = tmp_path_factory.mktemp("retrieve_fixture")
    chunks_path = base / "chunks.jsonl"
    with chunks_path.open("w", encoding="utf-8") as f:
        for chunk in CHUNKS:
            f.write(json.dumps(chunk) + "\n")
    index_dir = base / "indexes"
    run_index(chunks_path, index_dir)
    return index_dir


def test_exact_token_query_surfaces_bm25_hit(built_index) -> None:
    # "XJ-4471Z" appears in exactly one chunk; BM25 must find it by exact
    # token match even though doc-b is a near-paraphrase distractor.
    hits = lexical.bm25_search(built_index, "XJ-4471Z power supply requirements", limit=3)
    assert hits
    top_chunk_id, _ = hits[0]
    payload = vector_store.get_payloads(vector_store.open_client(built_index), [top_chunk_id])
    assert payload[top_chunk_id]["source_path"] == "model-a.txt"


def test_paraphrase_query_surfaces_dense_hit(built_index) -> None:
    # Shares essentially no vocabulary with the quantum chunk's text.
    query = (
        "How do overlapping states of tiny particles let some machines "
        "outperform ordinary ones on certain problems?"
    )
    client = ollama.Client(host=load_settings().ollama_host)
    qdrant_client = vector_store.open_client(built_index)
    embed_model = read_index_meta(built_index)["embed_model"]
    query_vector = list(client.embed(model=embed_model, input=[query]).embeddings[0])

    hits = dense.dense_search(qdrant_client, query_vector, limit=3)
    assert hits
    top_chunk_id, _ = hits[0]
    payload = vector_store.get_payloads(qdrant_client, [top_chunk_id])
    assert payload[top_chunk_id]["source_path"] == "quantum.txt"


def test_end_to_end_hybrid_retrieve(built_index) -> None:
    results = run_retrieve(built_index, "XJ-4471Z power supply requirements", k=3, rerank=False)
    assert len(results) == 3
    assert results[0].source_path == "model-a.txt"
    assert results[0].rerank_score is None
    # fusion_rank is a dense 1..N ranking over the returned candidates.
    assert [r.fusion_rank for r in results] == [1, 2, 3]


def test_rerank_produces_scores_in_range(built_index) -> None:
    client = ollama.Client(host=load_settings().ollama_host)
    candidates = [
        {
            "chunk_id": "c1",
            "text": CHUNKS[0]["text"],
            "source_path": "model-a.txt",
            "page": 1,
            "score": 0.5,
            "fusion_rank": 1,
            "rerank_score": None,
        },
        {
            "chunk_id": "c2",
            "text": CHUNKS[2]["text"],
            "source_path": "quantum.txt",
            "page": 1,
            "score": 0.4,
            "fusion_rank": 2,
            "rerank_score": None,
        },
    ]
    scored = rerank(client, "power supply voltage requirements", candidates)
    assert len(scored) == 2
    for candidate in scored:
        assert candidate["rerank_score"] is not None
        assert 0.0 <= candidate["rerank_score"] <= 1.0
    assert scored[0]["rerank_score"] >= scored[1]["rerank_score"]
