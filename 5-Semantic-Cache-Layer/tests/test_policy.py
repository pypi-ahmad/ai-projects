import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from src.cache.models import CacheRecord, Hit, Miss
from src.cache.normalize import normalize_query
from src.cache.service import SemanticCache
from src.policy.config import PolicyConfig
from src.policy.enforcement import PolicyRejectedError, check_puttable, select_eviction_candidates

QUERY_A = "What is the capital of France?"

# Orthogonal basis vectors keyed by exact normalized text: cosine
# similarity is exactly 1.0 for the same text and exactly 0.0 across
# different texts, so get() can only match its own stored entry -- these
# tests are about put/get/evict bookkeeping, not similarity ranking (see
# tests/test_service.py for that).
FAKE_VECTORS = {
    normalize_query(QUERY_A): [1.0, 0.0, 0.0, 0.0],
    normalize_query("q1"): [0.0, 1.0, 0.0, 0.0],
    normalize_query("q2"): [0.0, 0.0, 1.0, 0.0],
    normalize_query("q3"): [0.0, 0.0, 0.0, 1.0],
}


def _fake_embed_one(text, **kwargs):
    return FAKE_VECTORS[text]


def _make_record(
    query: str,
    answer: str,
    *,
    namespace: str = "demo",
    created_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> CacheRecord:
    return CacheRecord(
        id=str(uuid.uuid4()),
        namespace=namespace,
        query_raw=query,
        query_norm=normalize_query(query),
        answer=answer,
        producer_model="qwen3.5:0.8b",
        provider="ollama",
        created_at=created_at or datetime.now(timezone.utc),
        expires_at=expires_at,
    )


@pytest.fixture
def mock_embed():
    with patch("src.cache.service.embed_one", side_effect=_fake_embed_one) as mock:
        yield mock


def _make_cache(tmp_path, **policy_kwargs) -> SemanticCache:
    return SemanticCache(
        qdrant_path=tmp_path / "qdrant",
        index_meta_path=tmp_path / "index_meta.json",
        metrics_path=tmp_path / "metrics.jsonl",
        policy=PolicyConfig(**policy_kwargs),
    )


# --- TTL / expiry ---------------------------------------------------------


def test_expired_entry_is_a_miss(tmp_path, mock_embed):
    cache = _make_cache(tmp_path)
    already_expired = datetime.now(timezone.utc) - timedelta(seconds=1)
    record = _make_record(QUERY_A, "Paris", expires_at=already_expired)
    cache.put(record)

    result = cache.get(QUERY_A, namespace="demo")

    assert isinstance(result, Miss)


def test_expired_entry_is_lazily_deleted(tmp_path, mock_embed):
    cache = _make_cache(tmp_path)
    already_expired = datetime.now(timezone.utc) - timedelta(seconds=1)
    cache.put(_make_record(QUERY_A, "Paris", expires_at=already_expired))

    cache.get(QUERY_A, namespace="demo")

    assert cache.stats().entries == 0


def test_ttl_seconds_computes_expires_at_when_not_given(tmp_path, mock_embed):
    cache = _make_cache(tmp_path, ttl_seconds=1)
    old_created_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    cache.put(_make_record(QUERY_A, "Paris", created_at=old_created_at))

    result = cache.get(QUERY_A, namespace="demo")

    assert isinstance(result, Miss)


def test_ttl_zero_means_no_expiry(tmp_path, mock_embed):
    cache = _make_cache(tmp_path, ttl_seconds=0)
    old_created_at = datetime.now(timezone.utc) - timedelta(days=365)
    cache.put(_make_record(QUERY_A, "Paris", created_at=old_created_at))

    result = cache.get(QUERY_A, namespace="demo")

    assert isinstance(result, Hit)


# --- never_cache_regexes / min_answer_chars -------------------------------


def test_reject_secret_like_answer(tmp_path, mock_embed):
    cache = _make_cache(tmp_path)
    record = _make_record(QUERY_A, "sure, here is your api key: sk-abc123")

    with pytest.raises(PolicyRejectedError):
        cache.put(record)

    assert cache.stats().entries == 0


def test_reject_credit_card_like_answer(tmp_path, mock_embed):
    cache = _make_cache(tmp_path)
    record = _make_record(QUERY_A, "Your card number is 4111 1111 1111 1111.")

    with pytest.raises(PolicyRejectedError):
        cache.put(record)


def test_reject_tiny_answer(tmp_path, mock_embed):
    cache = _make_cache(tmp_path, min_answer_chars=5)
    record = _make_record(QUERY_A, "ok")

    with pytest.raises(PolicyRejectedError):
        cache.put(record)


def test_check_puttable_accepts_normal_answer():
    record = _make_record(QUERY_A, "Paris is the capital of France.")
    assert check_puttable(record, PolicyConfig()) is None


# --- max_entries eviction --------------------------------------------------


def test_evict_at_max_entries(tmp_path, mock_embed):
    cache = _make_cache(tmp_path, max_entries=2)

    cache.put(_make_record("q1", "answer-one", namespace="demo"))
    cache.put(_make_record("q2", "answer-two", namespace="demo"))
    cache.put(_make_record("q3", "answer-three", namespace="demo"))

    assert cache.stats().entries == 2
    # q1 was the oldest (never hit, oldest created_at) -- it should be the one evicted.
    assert isinstance(cache.get("q1", namespace="demo"), Miss)
    assert isinstance(cache.get("q3", namespace="demo"), Hit)


def test_max_entries_zero_means_unlimited(tmp_path, mock_embed):
    cache = _make_cache(tmp_path, max_entries=0)

    for query in (QUERY_A, "q1", "q2", "q3"):
        cache.put(_make_record(query, f"answer for {query}", namespace="demo"))

    assert cache.stats().entries == 4


def test_select_eviction_candidates_prefers_never_hit_oldest_created_at():
    class FakePoint:
        def __init__(self, id_, payload):
            self.id = id_
            self.payload = payload

    points = [
        FakePoint("old", {"created_at": "2020-01-01T00:00:00Z", "last_hit_at": None}),
        FakePoint("recent-hit", {"created_at": "2020-01-01T00:00:00Z", "last_hit_at": "2026-01-01T00:00:00Z"}),
        FakePoint("new", {"created_at": "2026-01-01T00:00:00Z", "last_hit_at": None}),
    ]

    evicted = select_eviction_candidates(points, max_entries=2)

    assert evicted == ["old"]


# --- require_same_producer_model -------------------------------------------


def test_require_same_producer_model_false_allows_cross_model_serving(tmp_path, mock_embed):
    cache = _make_cache(tmp_path, require_same_producer_model=False)
    cache.put(_make_record(QUERY_A, "Paris"))

    result = cache.get(QUERY_A, namespace="demo", producer_model="gemini-3.5-flash-lite")

    assert isinstance(result, Hit)


def test_require_same_producer_model_true_blocks_cross_model_serving(tmp_path, mock_embed):
    cache = _make_cache(tmp_path, require_same_producer_model=True)
    cache.put(_make_record(QUERY_A, "Paris"))

    result = cache.get(QUERY_A, namespace="demo", producer_model="gemini-3.5-flash-lite")

    assert isinstance(result, Miss)
