"""Dense vector search against the Qdrant index."""

from qdrant_client import QdrantClient

from self_correcting_rag.index.vector_store import COLLECTION_NAME


def dense_search(
    client: QdrantClient, query_vector: list[float], limit: int
) -> list[tuple[str, float]]:
    """Returns (chunk_id, dense_score) pairs, ranked descending by score."""
    if not client.collection_exists(COLLECTION_NAME):
        return []
    result = client.query_points(
        COLLECTION_NAME, query=query_vector, limit=limit, with_payload=False
    )
    return [(str(point.id), point.score) for point in result.points]
