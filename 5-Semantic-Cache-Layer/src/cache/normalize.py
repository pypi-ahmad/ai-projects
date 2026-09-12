"""Deterministic query text normalization for cache-key matching.

No stemming, no NLP -- normalization is a pure, order-preserving text
transform so its output is easy to reason about and stays stable across
runs.
"""

import re
import string

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_query(
    text: str,
    *,
    lowercase: bool = True,
    drop_trailing_punct: bool = False,
) -> str:
    """Normalize a query string: strip, collapse whitespace, then options.

    lowercase defaults on (English). drop_trailing_punct defaults off --
    not stated as a default by spec, kept conservative until tuning shows
    it helps hit rate.
    """
    normalized = _WHITESPACE_RE.sub(" ", text.strip())
    if lowercase:
        normalized = normalized.lower()
    if drop_trailing_punct:
        normalized = normalized.rstrip(string.punctuation).rstrip()
    return normalized
