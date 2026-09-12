"""Sentence-aware recursive splitting into atomic units, then greedy packing
into overlapping token-budget windows. Operates on a single page's text only —
callers must never pass text spanning more than one page or one file.
"""

import re

from rag_pipeline.chunk.tokenizer import count_tokens

_PARAGRAPH_RE = re.compile(r"\n\s*\n+")
# ponytail: naive sentence boundary heuristic (split after ./!/? + whitespace).
# Misreads abbreviations ("Dr. Smith"), decimals ("3.14"), etc. as sentence
# ends. Revisit with a real sentence tokenizer if a corpus shows this matters;
# for chunking (not display) an occasional early split is low-cost.
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"\s+")


def _split_keep_nonempty(pattern: re.Pattern, text: str) -> list[str]:
    return [p.strip() for p in pattern.split(text) if p.strip()]


def _hard_slice(text: str, max_tokens: int) -> list[str]:
    """Last-resort character slice for a single 'word' that alone exceeds
    max_tokens (e.g. OCR garbage with no whitespace). Guarantees the split
    point is strictly inside the text so recursion terminates.
    """
    if len(text) <= 1:
        return [text]
    ratio = max_tokens / max(1, count_tokens(text))
    split_at = min(max(1, int(len(text) * ratio)), len(text) - 1)
    return [text[:split_at], *atomic_units(text[split_at:], max_tokens)]


def atomic_units(text: str, max_tokens: int) -> list[str]:
    """Recursively split text into pieces each with <= max_tokens tokens,
    preferring paragraph breaks, then sentences, then words, in that order.
    """
    if count_tokens(text) <= max_tokens:
        return [text]
    for pattern in (_PARAGRAPH_RE, _SENTENCE_RE, _WORD_RE):
        pieces = _split_keep_nonempty(pattern, text)
        if len(pieces) > 1:
            units = []
            for piece in pieces:
                units.extend(atomic_units(piece, max_tokens))
            return units
    return _hard_slice(text, max_tokens)


def chunk_page_text(text: str, target_tokens: int = 512, overlap_tokens: int = 64) -> list[str]:
    """Greedily pack sentence-level units into ~target_tokens windows, with
    overlap_tokens of trailing units repeated at the start of the next window.
    """
    text = text.strip()
    if not text:
        return []

    units = atomic_units(text, target_tokens)
    token_counts = [count_tokens(u) for u in units]
    n = len(units)
    chunks: list[str] = []
    start = 0

    while start < n:
        end = start
        total = 0
        while end < n and total + token_counts[end] <= target_tokens:
            total += token_counts[end]
            end += 1
        if end == start:
            # A single unit already exceeds target_tokens on its own -- can't
            # happen given atomic_units' guarantee, but guard for progress.
            end = start + 1
        chunks.append(" ".join(units[start:end]))
        if end >= n:
            break

        # Walk back from `end` accumulating overlap, never regressing past
        # `start` (guarantees the next window's start strictly increases).
        new_start = end
        acc = 0
        while new_start > start + 1 and acc < overlap_tokens:
            new_start -= 1
            acc += token_counts[new_start]
        start = new_start

    return chunks
