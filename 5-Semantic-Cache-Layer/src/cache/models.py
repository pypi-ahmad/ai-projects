"""Pydantic v2 shapes for cache identity and stored records.

No embeddings here -- CacheKey/CacheRecord are the exact-field shape a
lookup is built from and a hit is stored as. Nearest-neighbor matching is
a later phase (docs/ARCHITECTURE.md).
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class CacheKey(BaseModel):
    """What a lookup or write is identified by, before embedding.

    model_id is part of the key so a lookup does not serve an answer
    produced by a different model unless policy explicitly allows it
    (docs/CACHE_POLICY.md).
    """

    namespace: str = "default"
    query: str
    system_prompt_hash: str | None = None
    tool_schema_hash: str | None = None
    model_id: str


class CacheRecord(BaseModel):
    """A stored query/answer pair plus bookkeeping."""

    # Typed as a plain str, but Qdrant (src/store/qdrant_store.py) only
    # accepts an unsigned int or a UUID-parseable string as a point ID --
    # callers must populate this with str(uuid.uuid4()), not an arbitrary id.
    id: str
    namespace: str = "default"
    query_raw: str
    query_norm: str
    answer: str
    producer_model: str
    provider: str
    created_at: datetime
    expires_at: datetime | None = None
    hit_count: int = 0
    last_hit_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Hit(BaseModel):
    """A cache lookup that found an answer to serve.

    type "exact" means the query_norm short-circuit matched before any
    embedding happened -- score is 1.0 by convention (no similarity was
    actually computed). type "semantic" means it cleared the cosine
    similarity threshold (docs/TECHNICAL.md).
    """

    type: Literal["exact", "semantic"]
    answer: str
    score: float
    matched_query: str
    record_id: str


class Miss(BaseModel):
    """A cache lookup that found no usable answer.

    top1_score is the best candidate's similarity even though it didn't
    clear the threshold -- kept for near-miss metrics, not shown as a hit.
    None means nothing was indexed for this namespace/model at all.
    """

    top1_score: float | None = None


class CacheStats(BaseModel):
    entries: int
