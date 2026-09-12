"""Token-count approximation + sentence-aware recursive splitting, then greedy
packing into overlapping token-budget windows. Operates on a single page's
text only -- callers must never pass text spanning more than one page.

Next: ingest/pipeline.py, the only caller, which assigns each returned chunk its
(source_path, page, index)-derived id.
"""

import re

# ponytail: chars/4 is a commonly-cited rough average for English under a BPE
# tokenizer -- not the real qwen3-embedding:0.6b tokenizer. Good enough for
# chunk sizing (not billing/limits). Upgrade: load the real tokenizer via the
# `tokenizers` package if chunk-boundary quality ever matters more than it
# does for this MVP.
_APPROX_CHARS_PER_TOKEN = 4

_PARAGRAPH_RE = re.compile(r"\n\s*\n+")
# ponytail: naive sentence boundary heuristic (split after ./!/? + whitespace).
# Misreads abbreviations ("Dr. Smith"), decimals ("3.14"), etc. Low-cost for
# chunking (not display); revisit with a real sentence tokenizer if it matters.
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"\s+")


def count_tokens(text: str) -> int:
    return max(1, len(text) // _APPROX_CHARS_PER_TOKEN)


def _split_keep_nonempty(pattern: re.Pattern, text: str) -> list[str]:
    return [p.strip() for p in pattern.split(text) if p.strip()]


def _hard_slice(text: str, max_tokens: int) -> list[str]:
    """Last-resort character slice for a single 'word' that alone exceeds
    max_tokens. Guarantees the split point is strictly inside the text so
    recursion terminates.
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
            end = start + 1
        chunks.append(" ".join(units[start:end]))
        if end >= n:
            break

        new_start = end
        acc = 0
        while new_start > start + 1 and acc < overlap_tokens:
            new_start -= 1
            acc += token_counts[new_start]
        start = new_start

    return chunks
