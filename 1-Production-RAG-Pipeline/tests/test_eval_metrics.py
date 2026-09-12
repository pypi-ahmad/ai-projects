from rag_pipeline.eval.metrics import citation_hit_rate, recall_at_k
from rag_pipeline.eval.records import EvalCase
from rag_pipeline.retrieve.records import RetrievalResult

RESULTS = [
    RetrievalResult(
        text="a",
        score=0.9,
        source_path="a.txt",
        page=1,
        chunk_id="c1",
        fusion_rank=1,
        rerank_score=0.9,
    ),
    RetrievalResult(
        text="b",
        score=0.8,
        source_path="b.txt",
        page=2,
        chunk_id="c2",
        fusion_rank=2,
        rerank_score=0.8,
    ),
]


def test_recall_at_k_by_chunk_id_hit() -> None:
    case = EvalCase(id="q1", question="?", relevant_chunk_ids=["c2"])
    assert recall_at_k(case, RESULTS) == 1.0


def test_recall_at_k_by_chunk_id_miss() -> None:
    case = EvalCase(id="q1", question="?", relevant_chunk_ids=["nonexistent"])
    assert recall_at_k(case, RESULTS) == 0.0


def test_recall_at_k_by_source_page_hit() -> None:
    case = EvalCase(id="q1", question="?", relevant_sources=[{"source_path": "b.txt", "page": 2}])
    assert recall_at_k(case, RESULTS) == 1.0


def test_recall_at_k_no_labels_is_none() -> None:
    case = EvalCase(id="q1", question="?")
    assert recall_at_k(case, RESULTS) is None


def test_citation_hit_rate_all_valid() -> None:
    assert citation_hit_rate("claim [S1] and [S2].", num_results=2) == 1.0


def test_citation_hit_rate_partial_hallucination() -> None:
    # [S1] valid, [S9] out of range -> 1 of 2 distinct cited indices valid.
    assert citation_hit_rate("claim [S1] and [S9].", num_results=2) == 0.5


def test_citation_hit_rate_no_citations_is_none() -> None:
    assert citation_hit_rate("no citations here.", num_results=2) is None
