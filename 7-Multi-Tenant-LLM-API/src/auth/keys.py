"""Tenant API key generation and hashing.

Argon2id via argon2-cffi (OWASP-recommended, argon2-cffi's PasswordHasher
default) -- raw keys are never stored, only their hash.

Used by src/tenants/service.py (issuing a key) and src/auth/resolve.py
(verifying one on every request).
"""

from __future__ import annotations

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()


def generate_api_key() -> tuple[str, str]:
    """Returns (raw_key, prefix). raw_key is shown to the caller once and
    never stored; only prefix (public) and hash_key(raw_key) are persisted."""
    raw_key = secrets.token_urlsafe(32)
    return raw_key, raw_key[:8]


def hash_key(raw_key: str) -> str:
    return _hasher.hash(raw_key)


def verify_key(raw_key: str, key_hash: str) -> bool:
    try:
        return _hasher.verify(key_hash, raw_key)
    except VerifyMismatchError:
        return False
