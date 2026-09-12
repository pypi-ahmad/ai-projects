from datetime import datetime, timezone

import pydantic
import pytest

from src.cache.models import CacheKey, CacheRecord


def test_cache_key_defaults():
    key = CacheKey(query="hi", model_id="qwen3.5:0.8b")
    assert key.namespace == "default"
    assert key.system_prompt_hash is None
    assert key.tool_schema_hash is None


def test_cache_key_requires_model_id():
    with pytest.raises(pydantic.ValidationError):
        CacheKey(query="hi")


def test_cache_record_defaults():
    now = datetime.now(timezone.utc)
    record = CacheRecord(
        id="abc123",
        query_raw="Hello?",
        query_norm="hello",
        answer="Hi!",
        producer_model="gemini-3.5-flash-lite",
        provider="gemini",
        created_at=now,
    )
    assert record.namespace == "default"
    assert record.expires_at is None
    assert record.hit_count == 0
    assert record.last_hit_at is None
    assert record.metadata == {}
