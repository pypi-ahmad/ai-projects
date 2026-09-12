"""bm25s lexical index over chunk texts -- the BM25 sidecar to Qdrant's dense
index. Chosen over rank_bm25 (unmaintained since Feb 2022, no persistence):
bm25s is actively maintained, pure Python + numpy (Windows-friendly, no
Docker, no compiled extension), and ships save()/load().
"""

from pathlib import Path

import bm25s

BM25_DIRNAME = "bm25"


def build_and_save(chunk_ids: list[str], texts: list[str], index_dir: Path) -> None:
    """Always rebuilds the whole index from the current full chunk list.
    Building is cheap (pure numpy, no model calls) -- a full rebuild per run
    is fine at this corpus size; revisit if the corpus grows large enough
    that rebuild time matters.
    """
    corpus = [{"id": cid, "text": text} for cid, text in zip(chunk_ids, texts, strict=True)]
    corpus_tokens = bm25s.tokenize(texts, stopwords="en", show_progress=False)
    retriever = bm25s.BM25()
    retriever.index(corpus_tokens, show_progress=False)
    retriever.save(str(index_dir / BM25_DIRNAME), corpus=corpus)
