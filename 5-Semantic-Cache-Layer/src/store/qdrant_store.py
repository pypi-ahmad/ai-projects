"""Qdrant-backed vector store: one collection, namespaces isolated by a
mandatory payload filter (docs/TECHNICAL.md: "Namespace isolation" -- see
that doc for why one collection was chosen over one collection per
namespace).

Every method that can touch more than a single known point ID (search,
find_exact, delete_namespace, count) builds its filter through
`_namespace_conditions` -- that's the one thing standing between two
namespaces' data, so don't add a path that bypasses it.

API verified against qdrant-client's own docs/source, not guessed:
create_collection/collection_exists, upsert (PointStruct), query_points
(query_filter, score_threshold), scroll (scroll_filter, for payload-only
lookup with no vector), set_payload, delete (points_selector: ids or a
Filter), count (count_filter).

Point IDs must be an unsigned int or a valid UUID string -- Qdrant (even
in local/embedded mode) rejects arbitrary strings. Callers must pass
`str(uuid.uuid4())`-style ids.
"""

from pathlib import Path

from qdrant_client import QdrantClient, models

DEFAULT_QDRANT_PATH = Path("data/cache/qdrant")
COLLECTION_NAME = "semantic_cache"


def _namespace_conditions(
    namespace: str, producer_model: str | None = None
) -> list[models.FieldCondition]:
    conditions = [models.FieldCondition(key="namespace", match=models.MatchValue(value=namespace))]
    if producer_model is not None:
        conditions.append(
            models.FieldCondition(
                key="producer_model", match=models.MatchValue(value=producer_model)
            )
        )
    return conditions


class QdrantStore:
    def __init__(self, path: Path = DEFAULT_QDRANT_PATH):
        self._client = QdrantClient(path=str(path))

    def exists(self) -> bool:
        return self._client.collection_exists(COLLECTION_NAME)

    def ensure_collection(self, dim: int) -> None:
        if not self.exists():
            self._client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
            )

    def upsert_point(self, *, point_id: str, vector: list[float], payload: dict) -> None:
        self._client.upsert(
            collection_name=COLLECTION_NAME,
            points=[models.PointStruct(id=point_id, vector=vector, payload=payload)],
        )

    def search(
        self,
        vector: list[float],
        *,
        namespace: str,
        producer_model: str | None = None,
        limit: int = 1,
    ) -> list[models.ScoredPoint]:
        response = self._client.query_points(
            collection_name=COLLECTION_NAME,
            query=vector,
            query_filter=models.Filter(must=_namespace_conditions(namespace, producer_model)),
            limit=limit,
            with_payload=True,
        )
        return response.points

    def find_exact(
        self, *, namespace: str, query_norm: str, producer_model: str | None = None
    ) -> models.Record | None:
        conditions = _namespace_conditions(namespace, producer_model)
        conditions.append(models.FieldCondition(key="query_norm", match=models.MatchValue(value=query_norm)))
        points, _ = self._client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=models.Filter(must=conditions),
            limit=1,
            with_payload=True,
        )
        return points[0] if points else None

    def set_payload(self, point_id, payload: dict) -> None:
        self._client.set_payload(collection_name=COLLECTION_NAME, payload=payload, points=[point_id])

    def delete_point(self, point_id) -> None:
        self._client.delete(collection_name=COLLECTION_NAME, points_selector=[point_id])

    def delete_namespace(self, namespace: str) -> None:
        self._client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=models.Filter(must=_namespace_conditions(namespace)),
        )

    def count(self, namespace: str | None = None) -> int:
        # namespace=None is the one deliberate exception to this module's
        # namespace-isolation rule: an unfiltered whole-collection count, used
        # by SemanticCache.stats() for a cache-wide total, not a per-lookup path.
        if not self.exists():
            return 0
        count_filter = models.Filter(must=_namespace_conditions(namespace)) if namespace is not None else None
        return self._client.count(collection_name=COLLECTION_NAME, count_filter=count_filter).count

    def scroll_all(self, namespace: str) -> list[models.Record]:
        """All points in a namespace, with payload. For policy decisions
        (eviction) that need to see the whole namespace at once -- not for
        anything in the lookup hot path.
        """
        scroll_filter = models.Filter(must=_namespace_conditions(namespace))
        all_points: list[models.Record] = []
        offset = None
        while True:
            points, offset = self._client.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=scroll_filter,
                limit=256,
                offset=offset,
                with_payload=True,
            )
            all_points.extend(points)
            if offset is None:
                break
        return all_points
