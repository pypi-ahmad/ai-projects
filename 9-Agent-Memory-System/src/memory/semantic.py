"""Semantic memory: distilled facts, embedded via Ollama, stored in Qdrant.

No separate SQLite metadata table -- the full Fact is stored as the Qdrant
point's payload (Qdrant payloads are arbitrary JSON), keyed by `fact_id`.
Qdrant runs embedded (`QdrantClient(path=...)`), no server, no Docker.

Tests hit the real Ollama server (embedding calls are not mocked) -- this
module's whole point is embedding quality, so a mock would test nothing.

Does not auto-distill itself: `upsert_fact` is a plain write. Phase 5's
`orchestrator.py` calls it after `compress.py` distills episodes into
facts; nothing in this module drives that.

Must not: pass a bare fact.id (hex, no dashes) straight through as a
Qdrant point id -- see _qdrant_id, Qdrant only accepts uint64 or a
dashed-UUID string.

Next: src/memory/compress.py -- what produces the fact text embedded here.
"""

from __future__ import annotations  # avoid `list[...]` colliding with any future `list()` method

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import ollama
from pydantic import BaseModel, Field
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams

from memory import config


class Fact(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    text: str
    embedding_model: str = config.EMBED_MODEL
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_episode_id: str | None = None
    confidence: float = Field(default=0.5, ge=0, le=1)
    namespace: str  # a session_id, or the literal string "global"
    invalidated_at: datetime | None = None


class FactMatch(BaseModel):
    fact: Fact
    score: float


class RebuildRequiredError(RuntimeError):
    """index_meta.json's embed model doesn't match config.EMBED_MODEL.

    Vector spaces from different embed models aren't comparable -- there is
    no in-place migration (see README "Changing the embed model requires a
    semantic rebuild"). Drop data/memory/qdrant/ and data/memory/index_meta.json
    and re-upsert every fact to rebuild.
    """

    def __init__(self, expected_model: str, found_model: str) -> None:
        self.expected_model = expected_model
        self.found_model = found_model
        super().__init__(
            f"index_meta.json has embed_model={found_model!r}, config expects "
            f"{expected_model!r}. Rebuild required."
        )


def _qdrant_id(fact_id: str) -> str:
    """Qdrant point ids must be an unsigned int or a UUID string; fact.id is
    a bare uuid4 hex, so reformat it to canonical dashed UUID form."""
    return str(uuid.UUID(fact_id))


def _fact_payload(fact: Fact) -> dict:
    return {
        "fact_id": fact.id,
        "text": fact.text,
        "embedding_model": fact.embedding_model,
        "created_at": fact.created_at.isoformat(),
        "source_episode_id": fact.source_episode_id,
        "confidence": fact.confidence,
        "namespace": fact.namespace,
        "invalidated_at": fact.invalidated_at.isoformat() if fact.invalidated_at else None,
    }


def _payload_to_fact(payload: dict) -> Fact:
    return Fact(
        id=payload["fact_id"],
        text=payload["text"],
        embedding_model=payload["embedding_model"],
        created_at=datetime.fromisoformat(payload["created_at"]),
        source_episode_id=payload["source_episode_id"],
        confidence=payload["confidence"],
        namespace=payload["namespace"],
        invalidated_at=(
            datetime.fromisoformat(payload["invalidated_at"]) if payload["invalidated_at"] else None
        ),
    )


class SemanticMemory:
    def __init__(
        self,
        qdrant_path: Path = config.QDRANT_PATH,
        meta_path: Path = config.INDEX_META_PATH,
        embed_model: str = config.EMBED_MODEL,
        collection: str = config.FACTS_COLLECTION,
    ) -> None:
        qdrant_path.mkdir(parents=True, exist_ok=True)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        self._embed_model = embed_model
        self._meta_path = meta_path
        self._collection = collection
        self._client = QdrantClient(path=str(qdrant_path))
        self._dim = self._load_or_init_meta()

    def close(self) -> None:
        self._client.close()

    def _embed(self, text: str) -> list[float]:
        response = ollama.embed(model=self._embed_model, input=text)
        return list(response.embeddings[0])

    def _load_or_init_meta(self) -> int:
        if self._meta_path.exists():
            meta = json.loads(self._meta_path.read_text(encoding="utf-8"))
            if meta["embed_model"] != self._embed_model:
                raise RebuildRequiredError(self._embed_model, meta["embed_model"])
            dim = meta["dim"]
        else:
            dim = len(self._embed("dimension probe"))
            self._meta_path.write_text(
                json.dumps({"embed_model": self._embed_model, "dim": dim}), encoding="utf-8"
            )
        if not self._client.collection_exists(self._collection):
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )
        return dim

    def upsert_fact(self, fact: Fact) -> None:
        vector = self._embed(fact.text)
        self._client.upsert(
            collection_name=self._collection,
            points=[PointStruct(id=_qdrant_id(fact.id), vector=vector, payload=_fact_payload(fact))],
        )

    def search(
        self,
        query: str,
        namespace: str,
        k: int = 5,
        min_score: float = 0.0,
    ) -> list[FactMatch]:
        """Namespace filter is not optional -- results are always scoped to
        exactly one namespace (a session_id, or "global"); a session never
        sees another session's facts. Includes invalidated facts; callers
        that care check `fact.invalidated_at` themselves -- `recall()`
        (src/memory/recall.py) doesn't either, as of Phase 6."""
        vector = self._embed(query)
        result = self._client.query_points(
            collection_name=self._collection,
            query=vector,
            query_filter=Filter(must=[FieldCondition(key="namespace", match=MatchValue(value=namespace))]),
            limit=k,
            score_threshold=min_score,
            with_payload=True,
        )
        return [
            FactMatch(fact=_payload_to_fact(point.payload), score=point.score) for point in result.points
        ]

    def invalidate(self, fact_id: str) -> None:
        self._client.set_payload(
            collection_name=self._collection,
            payload={"invalidated_at": datetime.now(timezone.utc).isoformat()},
            points=[_qdrant_id(fact_id)],
        )

    def count(self, namespace: str) -> int:
        """Fact count for one namespace (includes invalidated facts)."""
        result = self._client.count(
            collection_name=self._collection,
            count_filter=Filter(must=[FieldCondition(key="namespace", match=MatchValue(value=namespace))]),
        )
        return result.count


def _cli_put(mem: SemanticMemory, args: argparse.Namespace) -> None:
    fact = Fact(
        text=args.text,
        namespace=args.namespace,
        confidence=args.confidence,
        source_episode_id=args.source_episode_id,
    )
    mem.upsert_fact(fact)
    print(f"stored fact {fact.id} namespace={fact.namespace!r}")


def _cli_search(mem: SemanticMemory, args: argparse.Namespace) -> None:
    matches = mem.search(args.query, namespace=args.namespace, k=args.k, min_score=args.min_score)
    if not matches:
        print("no matches")
        return
    for m in matches:
        print(f"{m.score:.3f}  {m.fact.id}  {m.fact.text}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    put_p = sub.add_parser("put", help="embed and upsert a fact")
    put_p.add_argument("text")
    put_p.add_argument("--namespace", default="global")
    put_p.add_argument("--confidence", type=float, default=0.5)
    put_p.add_argument("--source-episode-id", default=None)

    search_p = sub.add_parser("search", help="search facts by semantic similarity")
    search_p.add_argument("query")
    search_p.add_argument("--namespace", default="global")
    search_p.add_argument("--k", type=int, default=5)
    search_p.add_argument("--min-score", type=float, default=0.0)

    args = parser.parse_args()
    mem = SemanticMemory()
    try:
        if args.command == "put":
            _cli_put(mem, args)
        else:
            _cli_search(mem, args)
    finally:
        mem.close()


if __name__ == "__main__":
    main()
