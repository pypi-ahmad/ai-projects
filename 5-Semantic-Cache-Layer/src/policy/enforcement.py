"""Policy decisions applied by SemanticCache.put()/get() (docs/CACHE_POLICY.md).

Pure functions -- no Qdrant/embedding I/O here. src/cache/service.py does
the fetching/deleting; this module only decides.
"""

import re
from datetime import datetime, timezone
from typing import Any

from src.cache.models import CacheRecord
from src.policy.config import PolicyConfig


class PolicyRejectedError(Exception):
    """put() refused a record for violating cache policy."""

    code = "POLICY_REJECTED"

    def __init__(self, *, reason: str):
        self.reason = reason
        super().__init__(f"put() rejected by cache policy: {reason}")


def check_puttable(record: CacheRecord, config: PolicyConfig) -> str | None:
    """Return a rejection reason, or None if the record may be stored."""
    if len(record.answer.strip()) < config.min_answer_chars:
        return f"answer shorter than min_answer_chars ({config.min_answer_chars})"
    for pattern in config.never_cache_regexes:
        if re.search(pattern, record.answer):
            return f"answer matches never_cache_regexes pattern: {pattern!r}"
    return None


def is_expired(payload: dict, *, now: datetime | None = None) -> bool:
    expires_at = payload.get("expires_at")
    if not expires_at:
        return False
    now = now or datetime.now(timezone.utc)
    return datetime.fromisoformat(expires_at) <= now


def select_eviction_candidates(points: list[Any], max_entries: int) -> list:
    """IDs to evict (oldest first) so `points` fits within max_entries.

    `points` are qdrant_client records: any object with `.id`/`.payload`.
    Ordering key is last_hit_at, falling back to created_at for entries
    that were never hit -- a fresh, never-hit entry still sorts as "newest"
    by its created_at, so it isn't evicted ahead of stale hit entries.
    """
    if max_entries <= 0 or len(points) <= max_entries:
        return []

    def sort_key(point: Any) -> str:
        return point.payload.get("last_hit_at") or point.payload["created_at"]

    ordered = sorted(points, key=sort_key)
    return [p.id for p in ordered[: len(ordered) - max_entries]]
