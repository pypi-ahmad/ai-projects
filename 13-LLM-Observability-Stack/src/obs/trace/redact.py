"""Hash + preview computation only.

This module never sees the OBS_STORE_PROMPTS setting and never stores
anything itself - it just turns text into (hash, preview). The decision to
also keep the raw text is made by the caller (tracer.py's
SpanHandle.set_prompt), which is the file to read next for the actual
privacy gate.
"""

from __future__ import annotations

import hashlib

# Characters, not bytes/tokens; a boundary multi-byte char isn't split specially.
PREVIEW_CHARS = 120


def redact(text: str | None) -> tuple[str | None, str | None]:
    """Return (sha256_hex, preview) for text, or (None, None) if text is None."""
    if text is None:
        return None, None
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return digest, text[:PREVIEW_CHARS]
