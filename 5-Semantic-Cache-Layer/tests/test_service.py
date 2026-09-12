import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from src.cache.models import CacheRecord, Hit, Miss
from src.cache.normalize import normalize_query
from src.cache.service import SemanticCache
from src.policy.config import PolicyConfig

QUERY_A = "What is the capital of France?"
QUERY_A_PARAPHRASE = "Whats France's capital city?"
QUERY_UNRELATED = "What is the weather today?"

# Real embeddings aren't used in this test -- deterministic fixed vectors
# stand in (mocked at the HTTP layer already in tests/test_ollama_client.py).
# v(A) and v(paraphrase) are nearly colinear (cosine ~0.995); v(unrelated)
# is orthogonal to both (cosine 0.0).
FAKE_VECTORS = {
    normalize_query(QUERY_A): [1.0, 0.0],
    normalize_query(QUERY_A_PARAPHRASE): [1.0, 0.1],
    normalize_query(QUERY_UNRELATED): [0.0, 1.0],
    normalize_query("q1"): [0.6, 0.8],
    normalize_query("q2"): [0.8, 0.6],
}


def _fake_embed_one(text, **kwargs):
    return FAKE_VECTORS[text]


def _make_record(query: str, answer: str, namespace: str = "demo") -> CacheRecord:
    return CacheRecord(
        id=str(uuid.uuid4()),
        namespace=namespace,
        query_raw=query,
        query_norm=normalize_query(query),
        answer=answer,
        producer_model="qwen3.5:0.8b",
        provider="ollama",
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def mock_embed():
    with patch("src.cache.service.embed_one", side_effect=_fake_embed_one) as mock:
        yield mock


@pytest.fixture
def cache(tmp_path, mock_embed):
    return SemanticCache(
        qdrant_path=tmp_path / "qdrant",
        index_meta_path=tmp_path / "index_meta.json",
        metrics_path=tmp_path / "metrics.jsonl",
        policy=PolicyConfig(),  # isolated from config/cache.yaml -- explicit defaults
    )


def test_paraphrase_is_a_semantic_hit_above_threshold(cache):
    cache.put(_make_record(QUERY_A, "Paris"))

    result = cache.get(QUERY_A_PARAPHRASE, namespace="demo")

    assert isinstance(result, Hit)
    assert result.type == "semantic"
    assert result.answer == "Paris"
    assert result.matched_query == QUERY_A
    assert result.score >= 0.89


def test_unrelated_query_is_a_miss(cache):
    cache.put(_make_record(QUERY_A, "Paris"))

    result = cache.get(QUERY_UNRELATED, namespace="demo")

    assert isinstance(result, Miss)
    assert result.top1_score is not None
    assert result.top1_score < 0.89


def test_query_with_nothing_indexed_is_a_miss(cache):
    result = cache.get(QUERY_A, namespace="demo")

    assert isinstance(result, Miss)
    assert result.top1_score is None


def test_exact_match_short_circuits_before_embedding(cache, mock_embed):
    cache.put(_make_record(QUERY_A, "Paris"))
    mock_embed.reset_mock()

    result = cache.get(QUERY_A, namespace="demo")

    mock_embed.assert_not_called()
    assert isinstance(result, Hit)
    assert result.type == "exact"
    assert result.answer == "Paris"
    assert result.score == 1.0


def test_namespaces_do_not_leak(cache):
    cache.put(_make_record(QUERY_A, "Paris", namespace="tenant-a"))

    result = cache.get(QUERY_A, namespace="tenant-b")

    assert isinstance(result, Miss)


def test_hit_increments_hit_count_and_last_hit_at(cache):
    cache.put(_make_record(QUERY_A, "Paris"))

    cache.get(QUERY_A, namespace="demo")
    cache.get(QUERY_A, namespace="demo")

    # hit_count/last_hit_at live in the Qdrant payload, not on Hit itself --
    # inspect the store directly to verify the side effect.
    stored = cache._store.find_exact(namespace="demo", query_norm=normalize_query(QUERY_A))
    assert stored.payload["hit_count"] == 2
    assert stored.payload["last_hit_at"] is not None


def test_stats_reports_entry_count(cache):
    cache.put(_make_record("q1", "answer-one"))
    cache.put(_make_record("q2", "answer-two"))

    assert cache.stats().entries == 2


def test_delete_removes_the_record(cache):
    record = _make_record(QUERY_A, "Paris")
    record_id = cache.put(record)

    cache.delete(record_id)

    assert cache.stats().entries == 0
    assert isinstance(cache.get(QUERY_A, namespace="demo"), Miss)


def test_clear_removes_only_the_given_namespace(cache):
    cache.put(_make_record("q1", "answer-one", namespace="a"))
    cache.put(_make_record("q2", "answer-two", namespace="b"))

    removed = cache.clear("a")

    assert removed == 1
    assert cache.stats().entries == 1
