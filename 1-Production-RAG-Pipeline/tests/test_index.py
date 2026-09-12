import hashlib
import json

from rag_pipeline.index import pipeline


class _FakeResponse:
    def __init__(self, embeddings: list[list[float]]) -> None:
        self.embeddings = embeddings


class _FakeOllamaClient:
    """Deterministic, offline stand-in for ollama.Client: embeds text as a
    hash-derived fixed-size vector and counts calls so tests can assert on it.
    """

    def __init__(self, *args, **kwargs) -> None:
        self.embed_calls = 0
        self.generate_calls = 0

    def embed(self, model: str, input: list[str]):  # noqa: A002 (matches ollama's kwarg name)
        self.embed_calls += 1
        vectors = []
        for text in input:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vectors.append([b / 255 for b in digest[:8]])
        return _FakeResponse(vectors)

    def generate(self, model: str, prompt: str, keep_alive: int = 0):
        self.generate_calls += 1


def _write_chunks(path, chunks: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk) + "\n")


def _chunk(doc_id: str, chunk_index: int, text: str) -> dict:
    return {
        "doc_id": doc_id,
        "source_path": f"{doc_id}.txt",
        "page": 1,
        "chunk_index": chunk_index,
        "hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "ocr_used": False,
        "text": text,
    }


def test_idempotent_reindex_by_hash(tmp_path, monkeypatch) -> None:
    fake_client = _FakeOllamaClient()
    monkeypatch.setattr(pipeline.ollama, "Client", lambda *a, **kw: fake_client)

    chunks_path = tmp_path / "chunks.jsonl"
    index_dir = tmp_path / "indexes"
    chunks = [_chunk("doc1", 0, "alpha text"), _chunk("doc1", 1, "beta text")]
    _write_chunks(chunks_path, chunks)

    report1 = pipeline.run_index(chunks_path, index_dir)
    assert report1.chunk_count == 2
    assert report1.embedded_count == 2
    assert report1.skipped_count == 0
    assert fake_client.embed_calls == 2  # one probe call + one remaining-batch call
    assert fake_client.generate_calls == 1  # unloaded once

    # Re-run unchanged: nothing should be re-embedded.
    report2 = pipeline.run_index(chunks_path, index_dir)
    assert report2.embedded_count == 0
    assert report2.skipped_count == 2
    assert fake_client.embed_calls == 2  # unchanged from before -- no new calls
    assert fake_client.generate_calls == 1  # unload only runs when something was embedded

    # Change one chunk's content (and hash) -> only that one gets re-embedded.
    chunks[1] = _chunk("doc1", 1, "beta text, edited")
    _write_chunks(chunks_path, chunks)
    report3 = pipeline.run_index(chunks_path, index_dir)
    assert report3.embedded_count == 1
    assert report3.skipped_count == 1
    assert fake_client.generate_calls == 2

    # BM25 index and Qdrant store both landed on disk.
    assert (index_dir / pipeline.vector_store.QDRANT_DIRNAME).exists()
    assert (index_dir / pipeline.lexical_store.BM25_DIRNAME).exists()
