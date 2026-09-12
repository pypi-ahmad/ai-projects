"""Qdrant local-mode (embedded, disk-persisted, no server) vector store for chunk vectors."""

from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

COLLECTION_NAME = "chunks"
QDRANT_DIRNAME = "qdrant"


def open_client(index_dir: Path) -> QdrantClient:
    return QdrantClient(path=str(index_dir / QDRANT_DIRNAME))


def ensure_collection(client: QdrantClient, dim: int) -> None:
    # No check that an existing collection's vector size matches `dim`. Re-indexing the same
    # index_dir with a different embed model (different output dimension) will fail inside
    # Qdrant's own upsert call, not here, with a less obvious error.
    if client.collection_exists(COLLECTION_NAME):
        return
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
    )


def upsert_chunks(client: QdrantClient, points: list[PointStruct]) -> None:
    if points:
        client.upsert(COLLECTION_NAME, points=points)


def get_payloads(client: QdrantClient, ids: list[str]) -> dict[str, dict]:
    """Full stored payload (text, source_path, page) for each point ID that
    exists. Used by retrieve to fetch chunk metadata regardless of whether a
    chunk was found via dense search, BM25, or both.
    """
    if not ids or not client.collection_exists(COLLECTION_NAME):
        return {}
    points = client.retrieve(COLLECTION_NAME, ids=ids, with_payload=True, with_vectors=False)
    return {str(p.id): (p.payload or {}) for p in points}
