"""bm25s lexical index over chunk texts.

Chosen over rank_bm25 (the other name the spec allowed): rank_bm25's last
release was Feb 2022, is unmaintained, and has no built-in persistence -- you'd
have to pickle it yourself. bm25s is actively maintained (latest release weeks
before this was written), pure Python + numpy (no Java, no PyTorch, no
compiled extension -- Windows-friendly, no Docker), ships built-in
save()/load(), and is dramatically faster per its own published benchmarks
against rank_bm25 and Elasticsearch.
"""

from pathlib import Path

import bm25s

BM25_DIRNAME = "bm25"


def build_and_save(chunk_ids: list[str], texts: list[str], index_dir: Path) -> None:
    """Always rebuilds the whole index from the current full chunk list.
    Building is cheap (pure numpy, no model calls), so unlike the vector
    store's per-chunk hash skip, this is a full rebuild every run -- still
    idempotent (same chunks.jsonl -> same index), just not incremental.
    """
    corpus = [{"id": cid, "text": text} for cid, text in zip(chunk_ids, texts, strict=True)]
    corpus_tokens = bm25s.tokenize(texts, stopwords="en", show_progress=False)
    retriever = bm25s.BM25()
    retriever.index(corpus_tokens, show_progress=False)
    retriever.save(str(index_dir / BM25_DIRNAME), corpus=corpus)
