"""Resolve a RequestContext from request headers.

The only supported way to get a tenant_id: look up the raw key's hash
against active api_keys and read the tenant it belongs to. Nothing here
ever reads a tenant_id from anywhere else (see docs/TENANCY.md).

Called from src/api/deps.py::get_context on every tenant-facing route.
"""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.context import RequestContext
from src.auth.errors import (
    InvalidKeyError,
    KeyRevokedError,
    MissingCredentialsError,
    TenantSuspendedError,
)
from src.auth.headers import extract_raw_key
from src.auth.keys import verify_key
from src.db import ApiKey, Tenant


def authenticate(session: Session, headers: Mapping[str, str]) -> RequestContext:
    raw_key = extract_raw_key(headers)
    if not raw_key:
        raise MissingCredentialsError()

    # Prefix narrows the candidate set (it's public, indexed, not secret);
    # the actual match still requires argon2's verify() on each candidate,
    # which does a constant-time comparison of the computed hash.
    candidates = session.execute(
        select(ApiKey).where(ApiKey.prefix == raw_key[:8])
    ).scalars().all()

    matched = next((c for c in candidates if verify_key(raw_key, c.key_hash)), None)
    if matched is None:
        raise InvalidKeyError()
    if matched.revoked_at is not None:
        raise KeyRevokedError()

    tenant = session.get(Tenant, matched.tenant_id)
    if tenant.status == "suspended":
        raise TenantSuspendedError()

    return RequestContext(tenant_id=tenant.id, key_id=matched.id)
