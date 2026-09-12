"""Body integrity hashing."""

from __future__ import annotations

import hashlib


def sha256_hex(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
