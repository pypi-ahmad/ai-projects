"""Embed chunks (qwen3-embedding:0.6b) and store dense + BM25 sidecar indexes.

Every run re-embeds and re-upserts every chunk from `input_dir` -- there is no content-hash
skip for unchanged chunks (unlike a hash-based incremental index). Re-running on an unchanged
corpus re-embeds it in full; only the point ids stay stable (see vector_store.py), so re-runs
overwrite rather than duplicate. Next: retrieve/pipeline.py, which queries what this builds.
"""

from pathlib import Path

import ollama
from qdrant_client.models import PointStruct

from self_correcting_rag.config import load_settings
from self_correcting_rag.index import lexical_store, vector_store
from self_correcting_rag.ingest.pipeline import run_ingest
from self_correcting_rag.llm.vram import unload_all

EMBED_MODEL = "qwen3-embedding:0.6b"


def run_index(input_dir: Path, index_dir: Path, *, ocr: bool = False) -> int:
    """Ingests `input_dir`, embeds every chunk, and (re)builds both indexes
    under `index_dir`. Returns the number of chunks indexed.
    """
    chunks = run_ingest(input_dir, ocr=ocr)
    if not chunks:
        return 0

    client = ollama.Client(host=load_settings().ollama_host)
    texts = [c.text for c in chunks]
    vectors = client.embed(model=EMBED_MODEL, input=texts).embeddings
    unload_all(client)

    qdrant_client = vector_store.open_client(index_dir)
    vector_store.ensure_collection(qdrant_client, dim=len(vectors[0]))
    points = [
        PointStruct(
            id=chunk.chunk_id,
            vector=list(vector),
            payload={"text": chunk.text, "source_path": chunk.source_path, "page": chunk.page},
        )
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]
    vector_store.upsert_chunks(qdrant_client, points)
    qdrant_client.close()

    lexical_store.build_and_save([c.chunk_id for c in chunks], texts, index_dir)

    return len(chunks)
