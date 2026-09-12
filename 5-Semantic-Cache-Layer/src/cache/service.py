"""Semantic cache orchestration: normalize -> exact short-circuit -> embed
-> search -> threshold (docs/ARCHITECTURE.md). Policy enforcement
(docs/CACHE_POLICY.md) and metrics logging (docs/METRICS.md) happen here
too, at the one place every put()/get() already passes through.
"""

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.cache.models import CacheRecord, CacheStats, Hit, Miss
from src.cache.normalize import normalize_query
from src.embed.ollama_client import DEFAULT_EMBED_MODEL, embed_one
from src.metrics.logger import DEFAULT_METRICS_PATH, MetricsLogger
from src.policy.config import DEFAULT_POLICY_CONFIG_PATH, PolicyConfig, load_policy_config
from src.policy.enforcement import (
    PolicyRejectedError,
    check_puttable,
    is_expired,
    select_eviction_candidates,
)
from src.store.index_meta import (
    DEFAULT_INDEX_META_PATH,
    IndexMeta,
    ensure_embed_model_matches,
    load_index_meta,
    save_index_meta,
)
from src.store.qdrant_store import DEFAULT_QDRANT_PATH, QdrantStore

# Semantic candidates pulled per lookup -- more than 1 so an expired top
# match can be lazily dropped without losing a fresh runner-up. Not
# user-configurable; bump here if that's ever not enough.
_SEARCH_CANDIDATES = 5


def _ms_since(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def _utc_now_iso() -> str:
    # Matches pydantic's own datetime serialization (trailing "Z", not
    # "+00:00") so payload timestamps look consistent everywhere.
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class SemanticCache:
    def __init__(
        self,
        *,
        qdrant_path: Path = DEFAULT_QDRANT_PATH,
        index_meta_path: Path = DEFAULT_INDEX_META_PATH,
        metrics_path: Path = DEFAULT_METRICS_PATH,
        policy_config_path: Path = DEFAULT_POLICY_CONFIG_PATH,
        embed_model: str = DEFAULT_EMBED_MODEL,
        policy: PolicyConfig | None = None,
        score_threshold: float | None = None,
    ):
        self._store = QdrantStore(path=qdrant_path)
        self._index_meta_path = index_meta_path
        self._embed_model = embed_model
        self._policy = policy if policy is not None else load_policy_config(policy_config_path)
        self._score_threshold = (
            score_threshold if score_threshold is not None else self._policy.threshold
        )
        self._metrics = MetricsLogger(path=metrics_path)

    @property
    def score_threshold(self) -> float:
        return self._score_threshold

    @score_threshold.setter
    def score_threshold(self, value: float) -> None:
        # Lets a long-lived cache instance (e.g. the Streamlit UI's slider)
        # retune the cutoff without reopening the Qdrant connection.
        self._score_threshold = value

    @property
    def embed_model(self) -> str:
        return self._embed_model

    @embed_model.setter
    def embed_model(self, value: str) -> None:
        # Not validated here -- a mismatch against data/cache/index_meta.json
        # is only caught lazily, on the next get()/put(), as RebuildRequiredError.
        self._embed_model = value

    def put(self, record: CacheRecord) -> str:
        start = time.perf_counter()

        reason = check_puttable(record, self._policy)
        if reason is not None:
            self._metrics.log(event="reject", namespace=record.namespace, latency_ms=_ms_since(start))
            raise PolicyRejectedError(reason=reason)

        if record.expires_at is None and self._policy.ttl_seconds > 0:
            record = record.model_copy(
                update={
                    "expires_at": record.created_at + timedelta(seconds=self._policy.ttl_seconds)
                }
            )

        embed_start = time.perf_counter()
        vector = embed_one(record.query_norm, model=self._embed_model)
        embed_ms = _ms_since(embed_start)

        meta = load_index_meta(self._index_meta_path)
        if meta is None:
            # First successful put() ever: this locks the whole collection to
            # this embed model/dimension until an explicit wipe (docs/RUNBOOK.md).
            meta = IndexMeta(embed_model=self._embed_model, dim=len(vector))
            save_index_meta(meta, self._index_meta_path)
        else:
            ensure_embed_model_matches(
                meta, requested_model=self._embed_model, requested_dim=len(vector)
            )

        self._store.ensure_collection(dim=len(vector))
        self._store.upsert_point(
            point_id=record.id,
            vector=vector,
            payload=record.model_dump(mode="json"),
        )

        if self._policy.max_entries > 0:
            # Re-scans the whole namespace on every put() to enforce the cap --
            # O(namespace size) per write, not incremental.
            points = self._store.scroll_all(namespace=record.namespace)
            for evict_id in select_eviction_candidates(points, self._policy.max_entries):
                self._store.delete_point(evict_id)
                self._metrics.log(event="evict", namespace=record.namespace)

        self._metrics.log(
            event="put", namespace=record.namespace, latency_ms=_ms_since(start), embed_ms=embed_ms
        )
        return record.id

    def get(
        self,
        query: str,
        *,
        namespace: str = "default",
        producer_model: str | None = None,
    ) -> Hit | Miss:
        start = time.perf_counter()
        query_norm = normalize_query(query)
        # docs/CACHE_POLICY.md: require_same_producer_model=false means
        # producer_model is recorded but not enforced as a filter.
        effective_producer_model = (
            producer_model if self._policy.require_same_producer_model else None
        )

        if not self._store.exists():
            self._metrics.log(event="miss", namespace=namespace, latency_ms=_ms_since(start))
            return Miss(top1_score=None)

        exact = self._store.find_exact(
            namespace=namespace, query_norm=query_norm, producer_model=effective_producer_model
        )
        if exact is not None:
            if is_expired(exact.payload):
                self._store.delete_point(exact.id)  # lazy delete, fall through to semantic search
            else:
                self._register_hit(exact.id, exact.payload)
                self._metrics.log(
                    event="hit",
                    namespace=namespace,
                    score=1.0,
                    latency_ms=_ms_since(start),
                    exact=True,
                )
                return Hit(
                    type="exact",
                    answer=exact.payload["answer"],
                    score=1.0,
                    matched_query=exact.payload["query_raw"],
                    record_id=str(exact.id),
                )

        embed_start = time.perf_counter()
        vector = embed_one(query_norm, model=self._embed_model)
        embed_ms = _ms_since(embed_start)

        meta = load_index_meta(self._index_meta_path)
        if meta is not None:
            ensure_embed_model_matches(
                meta, requested_model=self._embed_model, requested_dim=len(vector)
            )

        raw_results = self._store.search(
            vector,
            namespace=namespace,
            producer_model=effective_producer_model,
            limit=_SEARCH_CANDIDATES,
        )
        results = []
        for candidate in raw_results:
            if is_expired(candidate.payload):
                self._store.delete_point(candidate.id)  # lazy delete
                continue
            results.append(candidate)

        if not results:
            self._metrics.log(
                event="miss", namespace=namespace, latency_ms=_ms_since(start), embed_ms=embed_ms
            )
            return Miss(top1_score=None)

        top = results[0]
        if top.score >= self._score_threshold:
            self._register_hit(top.id, top.payload)
            self._metrics.log(
                event="hit",
                namespace=namespace,
                score=top.score,
                latency_ms=_ms_since(start),
                embed_ms=embed_ms,
                exact=False,
            )
            return Hit(
                type="semantic",
                answer=top.payload["answer"],
                score=top.score,
                matched_query=top.payload["query_raw"],
                record_id=str(top.id),
            )

        self._metrics.log(
            event="miss",
            namespace=namespace,
            score=top.score,
            latency_ms=_ms_since(start),
            embed_ms=embed_ms,
            exact=False,
        )
        return Miss(top1_score=top.score)

    def delete(self, record_id: str) -> None:
        self._store.delete_point(record_id)

    def clear(self, namespace: str) -> int:
        if not self._store.exists():
            return 0
        removed = self._store.count(namespace=namespace)
        self._store.delete_namespace(namespace)
        return removed

    def stats(self) -> CacheStats:
        return CacheStats(entries=self._store.count())

    def _register_hit(self, point_id, payload: dict) -> None:
        self._store.set_payload(
            point_id,
            {
                "hit_count": payload.get("hit_count", 0) + 1,
                "last_hit_at": _utc_now_iso(),
            },
        )
