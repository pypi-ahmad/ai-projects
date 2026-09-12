"""Prompt/response redaction. Always on: raw text is never persisted."""

from __future__ import annotations

import hashlib

PREVIEW_CHARS = 120


def redact(text: str | None) -> tuple[str | None, str | None]:
    """Return (sha256_hex, preview) for text, or (None, None) if text is None."""
    if text is None:
        return None, None
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return digest, text[:PREVIEW_CHARS]
