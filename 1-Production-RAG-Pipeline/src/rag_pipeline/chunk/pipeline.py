"""Read processed JSONL, chunk each non-empty page, write one JSONL record per chunk."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from rag_pipeline.chunk.records import ChunkRecord
from rag_pipeline.chunk.splitter import chunk_page_text
from rag_pipeline.ingest.pipeline import OUTPUT_FILENAME as INGEST_FILENAME

DEFAULT_TARGET_TOKENS = 512
DEFAULT_OVERLAP_TOKENS = 64


def chunk_document(
    record: dict,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list[dict]:
    """Chunk one ingest record's pages. Never merges text across pages: each
    page is split independently, so chunks from different pages -- and
    therefore always from different files -- are never combined.
    """
    doc_id = record["id"]
    source_path = record["path"]
    results: list[dict] = []
    chunk_index = 0

    for page in record["text_by_page"]:
        if not page["text"].strip():
            continue  # empty page dropped
        for piece in chunk_page_text(page["text"], target_tokens, overlap_tokens):
            chunk = ChunkRecord(
                doc_id=doc_id,
                source_path=source_path,
                page=page["page"],
                chunk_index=chunk_index,
                hash=hashlib.sha256(piece.encode("utf-8")).hexdigest(),
                ocr_used=page["ocr"],
                text=piece,
                source_hash=record.get("hash", ""),
            )
            results.append(asdict(chunk))
            chunk_index += 1

    return results


def _load_existing_chunks_by_doc(out_path: Path) -> dict[str, list[dict]]:
    """Existing chunks.jsonl grouped by doc_id, for the incremental skip
    check. Missing file (first run) -> {}.
    """
    if not out_path.exists():
        return {}
    by_doc: dict[str, list[dict]] = {}
    for line in out_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        chunk = json.loads(line)
        by_doc.setdefault(chunk["doc_id"], []).append(chunk)
    return by_doc


def run_chunk(
    in_dir: Path,
    out_path: Path,
    *,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> Path:
    """Incremental by source file hash: a doc_id whose ingest record's hash
    matches every one of its existing chunks' `source_hash` is reused as-is
    (not re-split) -- mirrors ingest/index's hash-skip pattern. A changed or
    new doc_id is (re-)chunked fully; chunk_index numbering for a changed doc
    always restarts at 0 (chunk_document's own behavior), so old chunks for
    that doc_id are fully replaced, never left mixed with new ones.
    """
    ingest_path = in_dir / INGEST_FILENAME
    out_path.parent.mkdir(parents=True, exist_ok=True)
    existing_by_doc = _load_existing_chunks_by_doc(out_path)

    chunks: list[dict] = []
    with ingest_path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            existing = existing_by_doc.get(record["id"])
            if existing and all(c.get("source_hash") == record["hash"] for c in existing):
                chunks.extend(existing)
                continue
            chunks.extend(chunk_document(record, target_tokens, overlap_tokens))

    with out_path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, ensure_ascii=False))
            f.write("\n")

    return out_path
