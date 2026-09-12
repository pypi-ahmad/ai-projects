import json

from rag_pipeline.chunk import pipeline, splitter, tokenizer


def _word_count(text: str) -> int:
    return len(text.split())


def test_run_chunk_is_incremental_by_source_hash(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(splitter, "count_tokens", _word_count)

    ingest_dir = tmp_path / "processed"
    ingest_dir.mkdir()
    ingest_path = ingest_dir / "ingest.jsonl"
    out_path = tmp_path / "chunks.jsonl"

    def write_ingest(text: str, file_hash: str) -> None:
        record = {
            "id": "doc1",
            "path": "doc1.txt",
            "text_by_page": [{"page": 1, "ocr": False, "text": text}],
            "hash": file_hash,
        }
        ingest_path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    calls: list[dict] = []
    original = pipeline.chunk_document

    def counting_chunk_document(record, *args, **kwargs):
        calls.append(record)
        return original(record, *args, **kwargs)

    monkeypatch.setattr(pipeline, "chunk_document", counting_chunk_document)

    write_ingest("hello world", "hash-a")
    pipeline.run_chunk(ingest_dir, out_path)
    assert len(calls) == 1

    # Unchanged source hash -> not re-chunked.
    pipeline.run_chunk(ingest_dir, out_path)
    assert len(calls) == 1
    chunks = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines()]
    assert all(c["source_hash"] == "hash-a" for c in chunks)

    # Changed source hash -> re-chunked, old chunks for that doc_id replaced.
    write_ingest("hello world, edited", "hash-b")
    pipeline.run_chunk(ingest_dir, out_path)
    assert len(calls) == 2
    chunks = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines()]
    assert all(c["source_hash"] == "hash-b" for c in chunks)


def test_overlap_exists(monkeypatch) -> None:
    # Deterministic, offline token counting: 1 "token" per whitespace word.
    monkeypatch.setattr(splitter, "count_tokens", _word_count)

    sentences = [f"Sentence number {i} is here" for i in range(10)]
    text = ". ".join(sentences) + "."
    # 5-word sentences: target_tokens=12 packs 2 sentences per window, leaving
    # room for overlap_tokens=5 (~1 sentence) to actually repeat between windows.
    chunks = splitter.chunk_page_text(text, target_tokens=12, overlap_tokens=5)

    assert len(chunks) > 1
    # A whole sentence (its word content, independent of surrounding
    # punctuation from joining/splitting) must appear in two consecutive chunks.
    overlap_found = False
    for a, b in zip(chunks, chunks[1:], strict=False):
        if any(s in a and s in b for s in sentences):
            overlap_found = True
    assert overlap_found


def test_pages_not_crossed(monkeypatch) -> None:
    monkeypatch.setattr(splitter, "count_tokens", _word_count)

    record = {
        "id": "doc1",
        "path": "doc1.pdf",
        "text_by_page": [
            {
                "page": 1,
                "ocr": False,
                "text": ". ".join(f"PAGEONE sentence {i}" for i in range(8)) + ".",
            },
            {
                "page": 2,
                "ocr": False,
                "text": ". ".join(f"PAGETWO sentence {i}" for i in range(8)) + ".",
            },
        ],
    }

    chunks = pipeline.chunk_document(record, target_tokens=6, overlap_tokens=2)

    assert len(chunks) > 2  # both pages actually got split into >1 chunk each
    for chunk in chunks:
        has_one = "PAGEONE" in chunk["text"]
        has_two = "PAGETWO" in chunk["text"]
        assert has_one != has_two  # exactly one marker, never both
        if has_one:
            assert chunk["page"] == 1
        else:
            assert chunk["page"] == 2

    # chunk_index runs continuously across pages within the same document.
    indices = [c["chunk_index"] for c in chunks]
    assert indices == list(range(len(chunks)))


def test_empty_page_dropped(monkeypatch) -> None:
    monkeypatch.setattr(splitter, "count_tokens", _word_count)

    record = {
        "id": "doc2",
        "path": "doc2.pdf",
        "text_by_page": [
            {"page": 1, "ocr": False, "text": "Real content on page one."},
            {"page": 2, "ocr": False, "text": "   \n  "},
            {"page": 3, "ocr": False, "text": ""},
            {"page": 4, "ocr": False, "text": "Real content on page four."},
        ],
    }

    chunks = pipeline.chunk_document(record)

    pages_present = {c["page"] for c in chunks}
    assert pages_present == {1, 4}
    assert 2 not in pages_present
    assert 3 not in pages_present


def test_count_tokens_is_positive_for_nonempty_text() -> None:
    # Whichever backend loaded (real tokenizer or approximation), sanity-check
    # the public API without asserting on which one is active.
    assert tokenizer.count_tokens("hello world") > 0
