"""Qdrant local-mode (embedded, disk-persisted, no server) vector store for chunk vectors."""

import uuid
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

COLLECTION_NAME = "chunks"
QDRANT_DIRNAME = "qdrant_db"

# Fixed, arbitrary namespace so point IDs are deterministic across runs.
_ID_NAMESPACE = uuid.UUID("2f9d9d1a-5c1e-4f6a-9b0e-2f6d0f5f2b41")


def point_id(doc_id: str, chunk_index: int) -> str:
    """Stable point ID for a (doc_id, chunk_index) position, so re-indexing the
    same logical chunk always upserts the same point instead of duplicating it.
    """
    return str(uuid.uuid5(_ID_NAMESPACE, f"{doc_id}:{chunk_index}"))


def open_client(index_dir: Path) -> QdrantClient:
    return QdrantClient(path=str(index_dir / QDRANT_DIRNAME))


def ensure_collection(client: QdrantClient, dim: int) -> None:
    if client.collection_exists(COLLECTION_NAME):
        info = client.get_collection(COLLECTION_NAME)
        vectors_config = info.config.params.vectors
        # This module always creates a single unnamed vector (see below), never
        # Qdrant's named-multi-vector form, so this is always VectorParams.
        assert isinstance(vectors_config, VectorParams), (
            f"expected a single unnamed vector config, got {type(vectors_config)}"
        )
        existing_dim = vectors_config.size
        if existing_dim != dim:
            raise RuntimeError(
                f"existing collection '{COLLECTION_NAME}' has vector size {existing_dim}, "
                f"but the configured embed model produces {dim}-dim vectors. Pick a "
                f"consistent --embed-model, or delete the qdrant_db directory to rebuild."
            )
        return
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
    )


def existing_hashes(client: QdrantClient, ids: list[str]) -> dict[str, str]:
    """Content hash currently stored for each point ID that exists, for the
    idempotent-by-hash skip check. Missing collection or empty ids -> {}.
    """
    if not ids or not client.collection_exists(COLLECTION_NAME):
        return {}
    points = client.retrieve(COLLECTION_NAME, ids=ids, with_payload=True, with_vectors=False)
    return {str(p.id): (p.payload or {}).get("hash", "") for p in points}


def upsert_chunks(client: QdrantClient, points: list[PointStruct]) -> None:
    if points:
        client.upsert(COLLECTION_NAME, points=points)


def get_payloads(client: QdrantClient, ids: list[str]) -> dict[str, dict]:
    """Full stored payload (text, source_path, page, ...) for each point ID
    that exists. Used by retrieve to fetch chunk metadata regardless of
    whether a chunk was found via dense search, BM25, or both.
    """
    if not ids or not client.collection_exists(COLLECTION_NAME):
        return {}
    points = client.retrieve(COLLECTION_NAME, ids=ids, with_payload=True, with_vectors=False)
    return {str(p.id): (p.payload or {}) for p in points}
