"""Embed chunks into Qdrant (idempotent by chunk hash), and build/save a BM25
lexical index over the same chunk texts. No query path here -- see SPEC.md.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import ollama
from qdrant_client.models import PointStruct

from rag_pipeline.config import load_settings
from rag_pipeline.index import lexical_store, vector_store
from rag_pipeline.index.meta import write_index_meta
from rag_pipeline.ingest.ocr import unload_model

logger = logging.getLogger(__name__)

EMBED_MODELS = ("qwen3-embedding:0.6b", "qwen3-embedding:4b")
DEFAULT_EMBED_MODEL = "qwen3-embedding:0.6b"
EMBED_BATCH_SIZE = 32


@dataclass
class IndexReport:
    chunk_count: int
    embedded_count: int
    skipped_count: int
    index_path: Path


def load_chunks(chunks_path: Path) -> list[dict]:
    records = []
    with chunks_path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def _embed_batch(client: ollama.Client, model: str, texts: list[str]) -> list[list[float]]:
    response = client.embed(model=model, input=texts)
    return [list(vector) for vector in response.embeddings]


def _make_point(pid: str, chunk: dict, vector: list[float]) -> PointStruct:
    return PointStruct(
        id=pid,
        vector=vector,
        payload={
            "doc_id": chunk["doc_id"],
            "source_path": chunk["source_path"],
            "page": chunk["page"],
            "chunk_index": chunk["chunk_index"],
            "hash": chunk["hash"],
            "ocr_used": chunk["ocr_used"],
            "text": chunk["text"],
        },
    )


def run_index(
    chunks_path: Path,
    index_dir: Path,
    *,
    embed_model: str = DEFAULT_EMBED_MODEL,
) -> IndexReport:
    if embed_model not in EMBED_MODELS:
        raise ValueError(f"embed_model must be one of {EMBED_MODELS}, got {embed_model!r}")

    index_dir.mkdir(parents=True, exist_ok=True)
    chunks = load_chunks(chunks_path)

    ollama_client = ollama.Client(host=load_settings().ollama_host)
    qdrant_client = vector_store.open_client(index_dir)

    ids = [vector_store.point_id(c["doc_id"], c["chunk_index"]) for c in chunks]
    known_hashes = vector_store.existing_hashes(qdrant_client, ids)

    to_embed = [
        (pid, chunk)
        for pid, chunk in zip(ids, chunks, strict=True)
        if known_hashes.get(pid) != chunk["hash"]
    ]

    if to_embed:
        first_pid, first_chunk = to_embed[0]
        first_vector = _embed_batch(ollama_client, embed_model, [first_chunk["text"]])[0]
        vector_store.ensure_collection(qdrant_client, dim=len(first_vector))

        points = [_make_point(first_pid, first_chunk, first_vector)]
        remaining = to_embed[1:]
        for start in range(0, len(remaining), EMBED_BATCH_SIZE):
            batch = remaining[start : start + EMBED_BATCH_SIZE]
            vectors = _embed_batch(ollama_client, embed_model, [c["text"] for _, c in batch])
            points.extend(
                _make_point(pid, c, v) for (pid, c), v in zip(batch, vectors, strict=True)
            )
            logger.info("embedded %d/%d new/changed chunks", len(points), len(to_embed))

        vector_store.upsert_chunks(qdrant_client, points)
        # Only record the model here, on a run that actually wrote vectors with
        # it -- a fully-skipped (nothing changed) run must not overwrite this
        # with a --embed-model value that was never actually used to embed
        # anything currently stored.
        write_index_meta(index_dir, embed_model)
        unload_model(ollama_client, embed_model)

    chunk_ids = [vector_store.point_id(c["doc_id"], c["chunk_index"]) for c in chunks]
    lexical_store.build_and_save(chunk_ids, [c["text"] for c in chunks], index_dir)

    qdrant_client.close()

    return IndexReport(
        chunk_count=len(chunks),
        embedded_count=len(to_embed),
        skipped_count=len(chunks) - len(to_embed),
        index_path=index_dir,
    )
